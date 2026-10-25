"""Final video assembly with FFmpeg.

Pipeline:
1. Frame-accurate plan: scene boundaries are rounded to whole frames so the
   video is exactly round(narration_duration * fps) frames long.
2. Each scene is normalized to an intermediate H.264 segment: optional removal
   of the redundant first frame of chained clips, user trim, fit/fill crop with
   focal point, fps conversion, hold-last-frame padding, exact frame count.
   Scenes without a clip fall back to a gentle pan over the scene image, or a
   plain card if there is no image either (so a render never blocks).
3. Segments are concatenated losslessly (concat demuxer, stream copy).
4. Narration (+ optional ducked music) is muxed; subtitles are optionally
   burned in (libass) and/or added as a soft mov_text track.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .ffmpeg_tools import FFmpegError, FFmpegInfo, probe, run_ffmpeg
from .http_base import CancelToken

log = logging.getLogger("scriptreel.render")


@dataclass
class RenderScene:
    index: int
    start: float
    end: float
    clip: Path | None = None
    image: Path | None = None
    drop_first_frame: bool = False
    trim_in: float = 0.0
    crop_mode: str = "fill"
    focal_x: float = 0.5
    focal_y: float = 0.5


@dataclass
class SubtitleStyleSpec:
    font: str = "Arial"
    size: int = 18
    color: str = "#FFFFFF"
    outline_color: str = "#101833"
    outline: float = 2.0
    bold: bool = True
    margin_v: int = 28
    box: bool = False


@dataclass
class RenderSpec:
    scenes: list[RenderScene]
    audio: Path
    audio_duration: float
    width: int
    height: int
    fps: int
    out_path: Path
    work_dir: Path
    fit_background: str = "blur"
    srt: Path | None = None
    burn_subtitles: bool = False
    soft_subtitles: bool = False
    sub_style: SubtitleStyleSpec = field(default_factory=SubtitleStyleSpec)
    narration_volume: float = 1.0
    music: Path | None = None
    music_volume: float = 0.15
    ducking: bool = True
    crf: int = 20
    preset: str = "medium"


@dataclass
class RenderReport:
    out_path: Path
    total_frames: int
    fps: int
    audio_duration: float
    video_duration: float
    rounding_ms: float
    measured_duration: float | None
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Output: {self.out_path.name}",
            f"Narration {self.audio_duration:.3f}s → {self.total_frames} frames @ {self.fps} fps = {self.video_duration:.3f}s "
            f"({self.rounding_ms:+.1f} ms frame rounding)",
        ]
        if self.measured_duration is not None:
            lines.append(f"Measured file duration: {self.measured_duration:.3f}s")
        lines += [f"⚠ {w}" for w in self.warnings]
        return "\n".join(lines)


def frame_plan(scenes: list[RenderScene], duration: float, fps: int) -> tuple[list[int], int]:
    total = max(1, round(duration * fps))
    bounds = [0]
    for s in scenes[:-1]:
        b = min(total, max(bounds[-1], round(s.end * fps)))
        bounds.append(b)
    bounds.append(total)
    return [bounds[i + 1] - bounds[i] for i in range(len(scenes))], total


def _ass_color(hex_rgb: str) -> str:
    h = hex_rgb.lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def subtitle_force_style(st: SubtitleStyleSpec) -> str:
    parts = [
        f"FontName={st.font}",
        f"FontSize={int(st.size)}",
        f"PrimaryColour={_ass_color(st.color)}",
        f"OutlineColour={_ass_color(st.outline_color)}",
        f"BackColour={_ass_color(st.outline_color)}",
        f"Bold={-1 if st.bold else 0}",
        f"BorderStyle={3 if st.box else 1}",
        f"Outline={st.outline:g}",
        "Shadow=0",
        "Alignment=2",
        f"MarginV={int(st.margin_v)}",
    ]
    return ",".join(parts)


def _even(v: float) -> int:
    return max(2, int(round(v / 2.0)) * 2)


def _geometry(mode: str, w: int, h: int, fx: float, fy: float, fit_bg: str) -> str:
    fx = min(1.0, max(0.0, fx))
    fy = min(1.0, max(0.0, fy))
    if mode == "fit":
        if fit_bg == "black":
            return (f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
                    f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")
        return (f"split=2[bg0][fg0];[bg0]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                f"boxblur=24:2,eq=brightness=-0.06[bg];[fg0]scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1")
    return (f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={w}:{h}:(iw-{w})*{fx:.4f}:(ih-{h})*{fy:.4f},setsar=1")


def scene_command(ffmpeg: str, sc: RenderScene, frames: int, spec: RenderSpec, encoder: str, out: Path) -> list[str]:
    w, h, fps = spec.width, spec.height, spec.fps
    need = frames / fps
    if sc.clip is not None:
        pre = []
        if sc.drop_first_frame:
            pre.append("trim=start_frame=1")
        if sc.trim_in > 0:
            pre.append(f"trim=start={sc.trim_in:.3f}")
        pre += ["setpts=PTS-STARTPTS", f"fps={fps}"]
        graph = (f"[0:v]{','.join(pre)},{_geometry(sc.crop_mode, w, h, sc.focal_x, sc.focal_y, spec.fit_background)},"
                 f"tpad=stop_mode=clone:stop_duration={need + 1:.3f},trim=end_frame={frames},setpts=PTS-STARTPTS,format=yuv420p[v]")
        inputs = ["-i", str(sc.clip)]
    elif sc.image is not None:
        inputs = ["-loop", "1", "-framerate", str(fps), "-t", f"{need + 0.5:.3f}", "-i", str(sc.image)]
        if sc.crop_mode == "fit":
            geo = _geometry("fit", w, h, 0.5, 0.5, spec.fit_background)
            graph = f"[0:v]{geo},trim=end_frame={frames},setpts=PTS-STARTPTS,format=yuv420p[v]"
        else:
            bw, bh = _even(w * 1.12), _even(h * 1.12)
            x0 = 0.15 + 0.3 * sc.focal_x  # gentle left→right pan around the focal point
            graph = (f"[0:v]scale={bw}:{bh}:force_original_aspect_ratio=increase:flags=lanczos,crop={bw}:{bh},"
                     f"crop={w}:{h}:x='(iw-ow)*({x0:.3f}+0.4*t/{max(need, 0.1):.3f})':y='(ih-oh)*{sc.focal_y:.3f}',"
                     f"setsar=1,trim=end_frame={frames},setpts=PTS-STARTPTS,format=yuv420p[v]")
    else:
        inputs = ["-f", "lavfi", "-i", f"color=c=0x101833:s={w}x{h}:r={fps}"]
        graph = f"[0:v]trim=end_frame={frames},setpts=PTS-STARTPTS,format=yuv420p[v]"
    enc = [*(["-c:v", encoder]), *(["-preset", "veryfast", "-crf", "16"] if encoder == "libx264" else ["-b:v", "12M"])]
    return [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", graph,
            "-map", "[v]", "-frames:v", str(frames), "-r", str(fps), *enc, "-pix_fmt", "yuv420p", "-an", str(out)]


def render(spec: RenderSpec, tools: FFmpegInfo, *, progress: Callable[[float, str], None], cancel: CancelToken) -> RenderReport:
    if not tools.ffmpeg or not tools.ffprobe:
        raise FFmpegError("FFmpeg/ffprobe not configured. Open Settings → Tools.")
    if not spec.audio.exists():
        raise FFmpegError("Narration audio is missing. Generate the voiceover first.")
    if not spec.scenes:
        raise FFmpegError("No scenes to render. Plan scenes first.")
    ffmpeg = tools.ffmpeg
    encoder = tools.h264_encoder or "libx264"
    warnings: list[str] = []
    work = spec.work_dir
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    counts, total = frame_plan(spec.scenes, spec.audio_duration, spec.fps)
    video_duration = total / spec.fps
    rounding_ms = (video_duration - spec.audio_duration) * 1000.0

    # ---- 1. per-scene segments
    seg_files: list[str] = []
    done_frames = 0
    for sc, n in zip(spec.scenes, counts):
        cancel.check()
        if n <= 0:
            warnings.append(f"Scene {sc.index} is shorter than one frame and was skipped.")
            continue
        if sc.clip is not None:
            try:
                info = probe(tools.ffprobe, sc.clip)
                available = max(0.0, info["duration"] - sc.trim_in - (1 / max(1.0, info.get("fps") or spec.fps) if sc.drop_first_frame else 0))
                if available + 1e-3 < n / spec.fps:
                    warnings.append(f"Scene {sc.index}: clip is {available:.2f}s but the scene needs {n / spec.fps:.2f}s — last frame held.")
            except FFmpegError:
                warnings.append(f"Scene {sc.index}: clip unreadable, using still image instead.")
                sc.clip = None
        if sc.clip is None and sc.image is None:
            warnings.append(f"Scene {sc.index}: no image or clip — a blank card was used.")
        elif sc.clip is None:
            warnings.append(f"Scene {sc.index}: no video clip — animated still image used.")
        name = f"seg_{sc.index:03d}.mp4"
        progress(0.75 * done_frames / total, f"Preparing scene {sc.index} ({n} frames)")
        run_ffmpeg(scene_command(ffmpeg, sc, n, spec, encoder, work / name), cancel=cancel)
        seg_files.append(name)
        done_frames += n

    # ---- 2. concat (stream copy)
    cancel.check()
    progress(0.76, "Joining scenes")
    (work / "list.txt").write_text("".join(f"file '{f}'\n" for f in seg_files), encoding="utf-8")
    run_ffmpeg([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
                "-i", "list.txt", "-c", "copy", "video_only.mp4"], cancel=cancel, cwd=work)

    # ---- 3. final mux
    burn = spec.burn_subtitles and spec.srt is not None and spec.srt.exists()
    soft = spec.soft_subtitles and spec.srt is not None and spec.srt.exists()
    if burn and not tools.has_subtitles_filter:
        warnings.append("This ffmpeg build has no 'subtitles' filter (libass); subtitles were added as a soft track instead of burned in.")
        burn, soft = False, True
    if burn or soft:
        shutil.copyfile(spec.srt, work / "subs.srt")  # relative name avoids Windows path escaping in filters

    inputs = ["-i", "video_only.mp4", "-i", str(spec.audio.resolve())]
    idx = 2
    music_idx = None
    if spec.music and spec.music.exists():
        inputs += ["-stream_loop", "-1", "-i", str(spec.music.resolve())]
        music_idx = idx
        idx += 1
    sub_idx = None
    if soft:
        inputs += ["-i", "subs.srt"]
        sub_idx = idx
        idx += 1

    fc = [f"[1:a]aresample=48000,volume={spec.narration_volume:.3f},apad[narr]"]
    if music_idx is not None:
        fc.append(f"[{music_idx}:a]aresample=48000,volume={spec.music_volume:.3f}[mus]")
        if spec.ducking:
            fc.append("[narr]asplit=2[n1][nsc]")
            fc.append("[mus][nsc]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[duck]")
            fc.append("[n1][duck]amix=inputs=2:duration=first:dropout_transition=0,volume=2[aout]")
        else:
            fc.append("[narr][mus]amix=inputs=2:duration=first:dropout_transition=0,volume=2[aout]")
    else:
        fc.append("[narr]anull[aout]")
    vmap = ["-map", "0:v"]
    venc = ["-c:v", "copy"]
    if burn:
        fc.append(f"[0:v]subtitles=subs.srt:force_style='{subtitle_force_style(spec.sub_style)}'[vout]")
        vmap = ["-map", "[vout]"]
        venc = ["-c:v", encoder, *(["-preset", spec.preset, "-crf", str(spec.crf)] if encoder == "libx264" else ["-b:v", "10M"]),
                "-pix_fmt", "yuv420p", "-r", str(spec.fps)]
    smap: list[str] = []
    if sub_idx is not None:
        smap = ["-map", f"{sub_idx}:0", "-c:s", "mov_text", "-metadata:s:s:0", "language=und"]

    spec.out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = work / "final.mp4"
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", ";".join(fc),
           *vmap, "-map", "[aout]", *venc, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", *smap,
           "-t", f"{video_duration:.6f}", "-movflags", "+faststart", "final.mp4"]
    progress(0.78, "Mixing audio" + (" and burning subtitles" if burn else ""))
    run_ffmpeg(cmd, cancel=cancel, cwd=work, total_s=video_duration,
               on_progress=lambda f: progress(0.78 + 0.2 * f, "Encoding final video"))
    shutil.move(str(tmp_out), str(spec.out_path))

    measured = None
    try:
        measured = probe(tools.ffprobe, spec.out_path)["duration"]
    except FFmpegError:
        pass
    progress(1.0, "Render complete")
    return RenderReport(spec.out_path, total, spec.fps, spec.audio_duration, video_duration, rounding_ms, measured, warnings)
