"""Long-running task functions executed on worker threads.

They receive plain specs (never the live Project object), report through the
`ctx` object (progress / emit / cancel) and return plain results. The GUI
thread applies results to the project, so project state is never mutated
from a worker thread.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..core.catalog import ImageModelEntry, VideoOptionEntry
from . import ffmpeg_tools
from .alignment import AlignmentEngine, build_cues
from .glabs_client import GLabsClient, RefImage
from .http_base import CancelToken, ServiceError, ext_from_url
from .prompt_provider import PromptContext, create_provider, generate_scene_prompts
from .video_renderer import RenderSpec, render
from .voice_studio_client import VoiceStudioClient
from . import youtube_package

log = logging.getLogger("scriptreel.tasks")


class Ctx(Protocol):
    cancel: CancelToken

    def progress(self, frac: float, message: str = "") -> None: ...
    def emit(self, payload: dict) -> None: ...


@dataclass
class VoiceConn:
    base_url: str
    api_key: str
    timeout: float
    poll_interval: float

    def client(self) -> VoiceStudioClient:
        return VoiceStudioClient(self.base_url, self.api_key, self.timeout)


@dataclass
class GLabsConn:
    base_url: str
    api_key: str
    timeout: float
    poll_interval: float
    reference_transfer: str = "auto"

    def client(self) -> GLabsClient:
        return GLabsClient(self.base_url, self.api_key, self.timeout, self.reference_transfer)


# ------------------------------------------------------------------ connections
def check_service(ctx: Ctx, which: str, conn: VoiceConn | GLabsConn) -> dict:
    out: dict[str, Any] = {"service": which, "reachable": False, "key_ok": None, "message": "", "hint": "", "details": "", "voices": None}
    with conn.client() as c:
        try:
            h = c.health()
            out["reachable"] = True
            out["details"] = f"uptime {int(h.get('uptime') or 0)}s · pending {h.get('tasks_pending', 0)} · running {h.get('tasks_running', 0)}"
        except ServiceError as exc:
            out["message"], out["hint"] = str(exc), exc.hint
            return out
        if not conn.api_key:
            out["key_ok"] = False
            out["message"] = "Server reachable, but no API key is saved."
            out["hint"] = "Paste the key from the app's Webhook tab."
            return out
        try:
            if which == "voice":
                voices = c.list_voices()  # type: ignore[attr-defined]
                out["voices"] = voices
                out["details"] += f" · {len(voices)} voice preset(s)"
            else:
                c.verify_key()  # type: ignore[attr-defined]
            out["key_ok"] = True
            out["message"] = "Connected"
        except ServiceError as exc:
            out["key_ok"] = False if exc.status in (401, 403) else None
            out["message"], out["hint"] = str(exc), exc.hint
    return out


def check_all(ctx: Ctx, voice: VoiceConn, glabs: GLabsConn, ffmpeg_cfg: tuple[str, str]) -> dict:
    res = {}
    ctx.progress(0.1, "Checking Voice Studio")
    res["voice"] = check_service(ctx, "voice", voice)
    ctx.progress(0.5, "Checking G-Labs Studio")
    res["glabs"] = check_service(ctx, "glabs", glabs)
    ctx.progress(0.8, "Checking FFmpeg")
    res["ffmpeg"] = ffmpeg_tools.inspect(*ffmpeg_cfg)
    return res


def list_voices(ctx: Ctx, conn: VoiceConn):
    with conn.client() as c:
        return c.list_voices()


# ------------------------------------------------------------------ voice
def run_voice(ctx: Ctx, conn: VoiceConn, params: dict, dest_stem: Path, timeout_s: float,
              ffprobe: str | None, existing_task_id: str = "") -> dict:
    with conn.client() as c:
        task_id = existing_task_id
        if not task_id:
            ctx.emit({"state": "submitting"})
            task_id = c.submit(**params)
        ctx.emit({"state": "running", "task_id": task_id, "submitted_at": time.time()})
        t0 = time.monotonic()

        def on_status(st: dict) -> None:
            ctx.emit({"state": "running", "task_id": task_id, "remote_status": st.get("status", "")})
            ctx.progress(min(0.9, (time.monotonic() - t0) / max(30.0, len(params.get("script", "")) / 12)),
                         f"Voice Studio: {st.get('status', '')}")

        st = c.wait_for_task(task_id, timeout_s=timeout_s, interval_s=conn.poll_interval, cancel=ctx.cancel, on_status=on_status)
        url = st["results"][0]
        dest = dest_stem.with_suffix(ext_from_url(url, "." + params.get("output_format", "wav")))
        ctx.emit({"state": "downloading", "task_id": task_id})
        c.download(url, dest, cancel=ctx.cancel)
    duration = 0.0
    if ffprobe:
        try:
            duration = ffmpeg_tools.probe(ffprobe, dest)["duration"]
        except ffmpeg_tools.FFmpegError:
            pass
    return {"path": dest, "task_id": task_id, "duration": duration}


# ------------------------------------------------------------------ alignment
def run_alignment(ctx: Ctx, engine: AlignmentEngine, audio: Path, script: str, language: str, method: str) -> dict:
    res = engine.align(audio, script, language, method=method, progress=ctx.progress, cancel=ctx.cancel)
    cues = build_cues(res.words)
    return {"result": res, "cues": cues}


# ------------------------------------------------------------------ prompts
def run_prompts(ctx: Ctx, provider_params: dict, pctx: PromptContext, scenes: list[dict]) -> dict:
    provider = create_provider(**provider_params)
    return generate_scene_prompts(provider, pctx, scenes, cancel=ctx.cancel, progress=ctx.progress)


def run_llm_test(ctx: Ctx, provider_params: dict) -> str:
    provider = create_provider(**provider_params)
    data = provider.complete_json("Reply with JSON only.", 'Return {"ok": true, "model": "<your model name>"}')
    return str(data)


def run_llm_models(ctx: Ctx, provider_params: dict) -> list[tuple[str, str]]:
    ctx.progress(0.2, "Fetching model list")
    return create_provider(**provider_params).list_models()


# ------------------------------------------------------------------ images
@dataclass
class ImageTaskSpec:
    scene_id: str
    scene_no: int
    entry: ImageModelEntry
    prompt: str
    aspect: str
    refs: list[RefImage]
    dest_stem: Path  # without extension
    timeout_s: float
    upscale: str = ""
    existing_task_id: str = ""


def _poll_and_download(ctx: Ctx, c: GLabsClient, conn: GLabsConn, task_id: str, timeout_s: float,
                       dest_stem: Path, default_ext: str, label: str) -> Path:
    t0 = time.monotonic()

    def on_status(st: dict) -> None:
        ctx.emit({"state": "running", "task_id": task_id, "remote_status": st.get("status", "")})
        ctx.progress(min(0.95, (time.monotonic() - t0) / (timeout_s * 0.25)), f"{label}: {st.get('status', '')}")

    st = c.wait_for_task(task_id, timeout_s=timeout_s, interval_s=conn.poll_interval, cancel=ctx.cancel, on_status=on_status)
    url = st["results"][-1]  # highest requested resolution comes last
    dest = dest_stem.with_suffix(ext_from_url(url, default_ext))
    ctx.emit({"state": "downloading", "task_id": task_id})
    c.download(url, dest, cancel=ctx.cancel)
    return dest


def _submit_with_fallback(ctx: Ctx, c: GLabsClient, conn: GLabsConn, build, existing_task_id: str, timeout_s: float,
                          dest_stem: Path, default_ext: str, label: str, submit_info: dict) -> tuple[Path, str]:
    """Submit (or resume) and poll. If G-Labs could not read a reference *file path* (e.g. macOS privacy
    protection), the upload failed before any generation, so resubmit once with base64 references."""
    task_id = existing_task_id
    for attempt in (1, 2):
        if not task_id:
            route, body = build()
            ctx.emit({"state": "submitting", "route": route, **submit_info})
            task_id = c.submit(route, body)
        ctx.emit({"state": "running", "task_id": task_id, "submitted_at": time.time()})
        try:
            return _poll_and_download(ctx, c, conn, task_id, timeout_s, dest_stem, default_ext, label), task_id
        except ServiceError as exc:
            if attempt == 1 and c.uses_paths() and GLabsClient.is_path_upload_denied(exc):
                log.warning("%s: G-Labs Studio cannot read the reference file path (OS privacy protection); "
                            "retrying once with base64 references.", label)
                c.reference_transfer = "base64"
                task_id = ""
                continue
            raise
    raise AssertionError("unreachable")


def run_image(ctx: Ctx, conn: GLabsConn, spec: ImageTaskSpec) -> dict:
    with conn.client() as c:
        path, task_id = _submit_with_fallback(
            ctx, c, conn,
            lambda: c.build_image_request(spec.entry, prompt=spec.prompt, aspect_ratio=spec.aspect,
                                          refs=spec.refs, upscale=spec.upscale),
            spec.existing_task_id, spec.timeout_s, spec.dest_stem, ".png", f"Scene {spec.scene_no} image", {})
    return {"path": path, "task_id": task_id, "model": spec.entry.id, "prompt": spec.prompt}


# ------------------------------------------------------------------ videos
@dataclass
class VideoTaskSpec:
    scene_id: str
    scene_no: int
    entry: VideoOptionEntry
    prompt: str
    aspect: str
    mode_key: str
    start_source: str | None  # "chain" | "image" | None
    end_source: str | None  # "image" | "next_image" | None
    image: Path | None
    next_image: Path | None
    duration: int | None
    resolution: str
    dest_stem: Path
    frames_dir: Path
    timeout_s: float
    existing_task_id: str = ""
    prev_clip: Path | None = None  # existing clip of the previous scene (when it is not part of this batch)
    chain_from_batch: bool = False  # previous scene is generated earlier in this same chain job


def resolve_video_mode(entry: VideoOptionEntry, requested: str, *, has_image: bool, chained: bool,
                       has_next_image: bool) -> tuple[str, str | None, str | None]:
    """Decide the documented mode and where its reference frames come from.

    Auto never invents capability: it only picks modes present in the catalog
    entry. Explicit choices are passed through and validated by the client,
    which reports a documented fallback instead of silently changing them.
    """
    m = entry.modes
    if requested in ("", "auto"):
        if chained and has_image and "start_end" in m and entry.supports_end_frame:
            return "start_end", "chain", "image"
        if chained and "start" in m:
            return "start", "chain", None
        if has_image and "start" in m:
            return "start", "image", None
        return "text", None, None
    if requested == "text":
        return "text", None, None
    if requested == "start":
        return "start", ("chain" if chained else ("image" if has_image else None)), None
    if requested == "start_end":
        if chained:
            return "start_end", "chain", ("image" if has_image else None)
        return "start_end", ("image" if has_image else None), ("next_image" if has_next_image else None)
    return requested, None, None


def run_video(ctx: Ctx, conn: GLabsConn, spec: VideoTaskSpec, ffprobe: str | None,
              chain_frame: Path | None = None) -> dict:
    def ref(source: str | None) -> RefImage | None:
        if source == "chain":
            return RefImage(chain_frame, "start_frame") if chain_frame else None
        if source == "image":
            return RefImage(spec.image, "scene_image") if spec.image else None
        if source == "next_image":
            return RefImage(spec.next_image, "end_frame") if spec.next_image else None
        return None

    with conn.client() as c:
        path, task_id = _submit_with_fallback(
            ctx, c, conn,
            lambda: c.build_video_request(spec.entry, prompt=spec.prompt, aspect_ratio=spec.aspect,
                                          mode_key=spec.mode_key, start_ref=ref(spec.start_source),
                                          end_ref=ref(spec.end_source), duration=spec.duration,
                                          resolution=spec.resolution),
            spec.existing_task_id, spec.timeout_s, spec.dest_stem, ".mp4", f"Scene {spec.scene_no} clip",
            {"mode": spec.mode_key})
    duration = None
    if ffprobe:
        try:
            duration = ffmpeg_tools.probe(ffprobe, path)["duration"]
        except ffmpeg_tools.FFmpegError:
            pass
    return {"path": path, "task_id": task_id, "model": spec.entry.id, "mode": spec.mode_key, "prompt": spec.prompt,
            "chained": spec.start_source == "chain", "duration": duration, "chain_frame": chain_frame}


def run_video_chain(ctx: Ctx, conn: GLabsConn, specs: list[VideoTaskSpec], ffmpeg: str, ffprobe: str | None) -> dict:
    """Sequential generation: scene N+1 starts from the absolute last frame of scene N."""
    done = 0
    last_clip: Path | None = None
    for k, spec in enumerate(specs):
        ctx.cancel.check()
        ctx.emit({"type": "scene_state", "scene_id": spec.scene_id, "state": "submitting"})
        ctx.progress(k / max(1, len(specs)), f"Chained clip {k + 1}/{len(specs)} (scene {spec.scene_no})")
        try:
            frame = None
            if spec.start_source == "chain":
                prev_clip = last_clip if spec.chain_from_batch else spec.prev_clip
                if prev_clip is None or not prev_clip.exists():
                    raise ServiceError(f"Scene {spec.scene_no}: the previous scene has no clip, so it cannot be chained. "
                                       "Generate the previous clip first or turn off chaining.", kind="bad_request")
                frame = ffmpeg_tools.extract_last_frame(
                    ffmpeg, prev_clip, spec.frames_dir / f"{spec.dest_stem.name}_startframe.png")

            sub = _ScopedCtx(ctx, spec.scene_id)
            result = run_video(sub, conn, spec, ffprobe, chain_frame=frame)
        except Exception as exc:  # report and stop the chain: later scenes depend on this one
            ctx.emit({"type": "scene_error", "scene_id": spec.scene_id, "error": exc})
            return {"done": done, "stopped_at": spec.scene_id}
        ctx.emit({"type": "scene_result", "scene_id": spec.scene_id, "result": result})
        last_clip = result["path"]
        done += 1
    return {"done": done, "stopped_at": None}


class _ScopedCtx:
    """Wraps ctx so events from a sub-task are tagged with the scene id."""

    def __init__(self, ctx: Ctx, scene_id: str) -> None:
        self._ctx = ctx
        self.cancel = ctx.cancel
        self.scene_id = scene_id

    def progress(self, frac: float, message: str = "") -> None:
        pass  # chain job reports per-scene progress itself

    def emit(self, payload: dict) -> None:
        self._ctx.emit({"type": "scene_state", "scene_id": self.scene_id, **payload})


# ------------------------------------------------------------------ render / misc
def run_render(ctx: Ctx, spec: RenderSpec, tools: ffmpeg_tools.FFmpegInfo):
    return render(spec, tools, progress=ctx.progress, cancel=ctx.cancel)


def run_waveform(ctx: Ctx, ffmpeg: str, audio: Path) -> list[float]:
    return ffmpeg_tools.waveform_peaks(ffmpeg, audio)


def run_youtube(ctx: Ctx, provider_params: dict | None, title: str, script: str, chapters: list[dict]) -> tuple[dict, str]:
    provider = create_provider(**provider_params) if provider_params else None
    ctx.progress(0.2, "Writing YouTube metadata")
    return youtube_package.generate(provider, title=title, script=script, chapters=chapters, cancel=ctx.cancel)


def run_whisper_check(ctx: Ctx, engine, download: bool) -> str:
    ok, why = engine.available()
    if not ok:
        return why
    if download:
        ctx.progress(0.1, f"Downloading/loading model '{engine.model_size}'…")
        engine.load_model(local_only=False)
        return f"Model '{engine.model_size}' is downloaded and loads correctly."
    return (f"Model '{engine.model_size}' is available offline." if engine.model_cached()
            else f"Model '{engine.model_size}' is not downloaded yet (it downloads on first alignment).")
