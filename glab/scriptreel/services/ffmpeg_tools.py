"""FFmpeg / ffprobe discovery and helpers (external executables)."""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
import threading
from array import array
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..core.paths import bundled_bin_dir
from .http_base import CancelledError, CancelToken

log = logging.getLogger("scriptreel.ffmpeg")

IS_WIN = sys.platform == "win32"


class FFmpegError(Exception):
    def __init__(self, message: str, stderr_tail: str = "") -> None:
        super().__init__(message)
        self.stderr_tail = stderr_tail


@dataclass
class FFmpegInfo:
    ffmpeg: str | None = None
    ffprobe: str | None = None
    ffmpeg_version: str = ""
    ffprobe_version: str = ""
    h264_encoder: str = ""
    has_subtitles_filter: bool = False
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.ffmpeg and self.ffprobe and not self.problems)


def popen_kwargs() -> dict:
    kw: dict = {"stdin": subprocess.DEVNULL}
    if IS_WIN:
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW: no console flashes
    return kw


def _find(name: str, configured: str) -> str | None:
    if configured:
        p = Path(configured)
        return str(p) if p.is_file() else None
    exe = name + (".exe" if IS_WIN else "")
    cand = bundled_bin_dir() / exe
    if cand.is_file():
        return str(cand)
    return shutil.which(name)


def resolve(ffmpeg_cfg: str = "", ffprobe_cfg: str = "") -> tuple[str | None, str | None]:
    ff = _find("ffmpeg", ffmpeg_cfg)
    fp = _find("ffprobe", ffprobe_cfg)
    if ff and not fp and not ffprobe_cfg:  # ffprobe usually sits next to ffmpeg
        sib = Path(ff).with_name("ffprobe" + (".exe" if IS_WIN else ""))
        if sib.is_file():
            fp = str(sib)
    return ff, fp


def _run_capture(args: list[str], timeout: float = 20) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, **popen_kwargs())


def inspect(ffmpeg_cfg: str = "", ffprobe_cfg: str = "") -> FFmpegInfo:
    ff, fp = resolve(ffmpeg_cfg, ffprobe_cfg)
    info = FFmpegInfo(ff, fp)
    if not ff:
        info.problems.append("ffmpeg not found. Install FFmpeg and set its path in Settings (or put ffmpeg.exe in the app's bin folder).")
    if not fp:
        info.problems.append("ffprobe not found. It ships with FFmpeg; set its path in Settings.")
    try:
        if ff:
            out = _run_capture([ff, "-hide_banner", "-version"]).stdout
            info.ffmpeg_version = out.splitlines()[0] if out else ""
            enc = _run_capture([ff, "-hide_banner", "-encoders"]).stdout
            for cand in ("libx264", "libopenh264", "h264_mf", "mpeg4"):
                if re.search(rf"\s{cand}\s", enc):
                    info.h264_encoder = cand
                    break
            if not info.h264_encoder:
                info.problems.append("No usable video encoder (libx264) in this ffmpeg build.")
            flt = _run_capture([ff, "-hide_banner", "-filters"]).stdout
            info.has_subtitles_filter = bool(re.search(r"\ssubtitles\s", flt))
        if fp:
            out = _run_capture([fp, "-hide_banner", "-version"]).stdout
            info.ffprobe_version = out.splitlines()[0] if out else ""
    except (OSError, subprocess.SubprocessError) as exc:
        info.problems.append(f"Could not run FFmpeg: {exc}")
    return info


def run_ffmpeg(
    args: list[str],
    *,
    cancel: CancelToken | None = None,
    on_progress: Callable[[float], None] | None = None,
    total_s: float | None = None,
    cwd: Path | None = None,
) -> str:
    """Run ffmpeg; report progress (0..1) from `-progress pipe:1`; terminate on cancel."""
    cmd = list(args)
    if on_progress and total_s:
        cmd[1:1] = ["-progress", "pipe:1", "-nostats"]
    log.debug("ffmpeg: %s", " ".join(cmd[:6]))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", cwd=str(cwd) if cwd else None, **popen_kwargs())
    tail: deque[str] = deque(maxlen=40)
    cancelled = threading.Event()

    def read_err() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            tail.append(line.rstrip())

    def watch_cancel() -> None:
        while proc.poll() is None:
            if cancel is not None and cancel.cancelled:
                cancelled.set()
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return
            threading.Event().wait(0.2)

    t_err = threading.Thread(target=read_err, daemon=True)
    t_err.start()
    t_watch = threading.Thread(target=watch_cancel, daemon=True)
    t_watch.start()
    assert proc.stdout is not None
    for line in proc.stdout:
        if on_progress and total_s and line.startswith("out_time_us="):
            try:
                us = int(line.split("=", 1)[1])
                on_progress(min(1.0, max(0.0, us / 1e6 / total_s)))
            except ValueError:
                pass
    rc = proc.wait()
    t_err.join(timeout=2)
    if cancelled.is_set():
        raise CancelledError("Render cancelled")
    if rc != 0:
        raise FFmpegError(f"ffmpeg failed (exit code {rc})", "\n".join(tail))
    return "\n".join(tail)


def probe(ffprobe: str, path: Path) -> dict:
    res = _run_capture([ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], timeout=30)
    if res.returncode != 0:
        raise FFmpegError(f"ffprobe could not read {Path(path).name}", res.stderr[-800:])
    data = json.loads(res.stdout or "{}")
    fmt = data.get("format", {})
    out = {"duration": float(fmt.get("duration") or 0.0), "has_audio": False, "has_video": False}
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not out["has_video"]:
            out["has_video"] = True
            out["width"] = int(s.get("width") or 0)
            out["height"] = int(s.get("height") or 0)
            num, _, den = str(s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/1").partition("/")
            try:
                out["fps"] = float(num) / float(den or 1) if float(den or 1) else 0.0
            except ValueError:
                out["fps"] = 0.0
            nb = str(s.get("nb_frames") or "")
            if nb.isdigit():
                out["nb_frames"] = int(nb)
            if not out["duration"] and s.get("duration"):
                out["duration"] = float(s["duration"])
        elif s.get("codec_type") == "audio":
            out["has_audio"] = True
            if not out["duration"] and s.get("duration"):
                out["duration"] = float(s["duration"])
    return out


def extract_last_frame(ffmpeg: str, video: Path, out_png: Path) -> Path:
    """Write the absolute last decoded frame of `video` to `out_png`."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    for pre in (["-sseof", "-1.0"], []):
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *pre, "-i", str(video),
               "-an", "-update", "1", str(out_png)]
        res = _run_capture(cmd, timeout=120)
        if res.returncode == 0 and out_png.exists() and out_png.stat().st_size > 100:
            return out_png
    raise FFmpegError(f"Could not extract the last frame of {video.name}", res.stderr[-800:])


def waveform_peaks(ffmpeg: str, audio: Path, points: int = 1600) -> list[float]:
    res = subprocess.run([ffmpeg, "-v", "error", "-i", str(audio), "-ac", "1", "-ar", "4000", "-f", "s16le", "-"],
                         capture_output=True, timeout=120, **popen_kwargs())
    if res.returncode != 0:
        raise FFmpegError("Could not decode audio for waveform", res.stderr.decode("utf-8", "replace")[-500:])
    data = res.stdout[: len(res.stdout) - len(res.stdout) % 2]
    arr = array("h")
    arr.frombytes(data)
    if sys.byteorder == "big":
        arr.byteswap()
    n = len(arr)
    if n == 0:
        return []
    step = max(1, n // points)
    peaks = []
    for i in range(0, n, step):
        chunk = arr[i:i + step]
        peaks.append(max(max(chunk), -min(chunk)) / 32768.0)
    top = max(peaks) or 1.0
    return [p / top for p in peaks]


def silence_detect(ffmpeg: str, audio: Path, noise_db: float = -35.0, min_d: float = 0.2) -> list[tuple[float, float]]:
    res = _run_capture([ffmpeg, "-hide_banner", "-nostats", "-i", str(audio), "-af",
                        f"silencedetect=noise={noise_db}dB:d={min_d}", "-f", "null", "-"], timeout=300)
    silences: list[tuple[float, float]] = []
    start = None
    for line in res.stderr.splitlines():
        m = re.search(r"silence_start:\s*(-?[\d.]+)", line)
        if m:
            start = max(0.0, float(m.group(1)))
            continue
        m = re.search(r"silence_end:\s*([\d.]+)", line)
        if m and start is not None:
            silences.append((start, float(m.group(1))))
            start = None
    if start is not None:
        silences.append((start, float("inf")))
    return silences
