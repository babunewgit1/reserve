"""G-Labs Studio (G-Labs Automation) webhook client.

Request bodies are built per documented route (WEBHOOK_INTEGRATION.en.md §5):
  /api/image/generate   flow images: model, aspect_ratio, reference_images, upscale
  /api/openai/generate  GPT Image 2: aspect_ratio, quality, prompt_mode, reference_images
  /api/video/generate   Veo/Omni: model, mode, reference_images, resolution[], video_length
  /api/grok/generate    Grok: mode t2i|i2i|t2v|i2v (modes, not model ids), video_length, resolution
  /api/meta/generate    Meta AI: mode + named image fields (start_image, end_image, ...)
No model-list or cancel endpoint is documented, so none is called.
"""
from __future__ import annotations

import base64
import logging
import mimetypes
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from ..core.catalog import ALLOWED_ROUTES, MODE_LABELS, ImageModelEntry, VideoOptionEntry
from ..core.logging_setup import shorten
from .http_base import BaseClient

log = logging.getLogger("scriptreel.glabs")

MAX_BODY_BYTES = 50 * 1024 * 1024
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


@dataclass
class RefImage:
    path: Path
    name: str = ""
    role: str = "subject"  # subject | scene | style


def summarize_body(body: dict) -> str:
    parts = []
    for k, v in body.items():
        if k == "prompt":
            parts.append(f"prompt=«{shorten(v, 60)}»")
        elif k == "reference_images":
            parts.append(f"reference_images={len(v)}")
        elif k.endswith("_image"):
            parts.append(f"{k}=<image>")
        else:
            parts.append(f"{k}={v}")
    return ", ".join(parts)


class GLabsClient(BaseClient):
    service_name = "G-Labs Studio"

    def __init__(self, base_url: str, api_key: str = "", timeout: float = 30.0, reference_transfer: str = "auto") -> None:
        super().__init__(base_url, api_key, timeout)
        self.reference_transfer = reference_transfer

    # -- connection ------------------------------------------------------------
    def verify_key(self) -> int:
        """GET /api/tasks is the documented authenticated read-only call; used to test the key."""
        data = self.request_json("GET", "/api/tasks")
        return len(data.get("tasks") or [])

    # -- reference encoding -----------------------------------------------------
    def uses_paths(self) -> bool:
        if self.reference_transfer == "path":
            return True
        if self.reference_transfer == "base64":
            return False
        if sys.platform == "darwin":
            # macOS privacy protection blocks other apps from reading ~/Documents etc.
            # ("[Errno 1] Operation not permitted"), so never rely on shared paths there.
            return False
        return (urlparse(self.base_url).hostname or "") in LOOPBACK

    @staticmethod
    def _path_denied_text(text: str) -> bool:
        low = text.lower()
        return "upload" in low and any(k in low for k in ("operation not permitted", "errno 1]", "errno 13",
                                                           "permission denied"))

    @classmethod
    def is_path_upload_denied(cls, exc: Exception) -> bool:
        """True when a task failed because G-Labs could not read a reference image file path."""
        return cls._path_denied_text(f"{exc} {getattr(exc, 'detail', '')}")

    @staticmethod
    def data_uri(path: Path) -> str:
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        if mime not in ("image/png", "image/jpeg", "image/webp"):
            mime = "image/png"
        return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")

    def _encode_list_item(self, ref: RefImage, with_name: bool) -> object:
        if not ref.path.exists():
            raise self._err(f"Reference image not found: {ref.path.name}", kind="bad_request")
        if self.uses_paths():
            # Same-machine form. @tag binding uses the real filename.
            return {"path": str(ref.path.resolve())}
        uri = self.data_uri(ref.path)
        if with_name and ref.name:
            return {"data": uri, "name": ref.name if "." in ref.name else ref.name + ref.path.suffix}
        return uri

    def _encode_named(self, ref: RefImage) -> object:
        if not ref.path.exists():
            raise self._err(f"Reference image not found: {ref.path.name}", kind="bad_request")
        return {"path": str(ref.path.resolve())} if self.uses_paths() else self.data_uri(ref.path)

    # -- builders --------------------------------------------------------------
    def build_image_request(
        self,
        entry: ImageModelEntry,
        *,
        prompt: str,
        aspect_ratio: str,
        refs: list[RefImage] | None = None,
        upscale: str = "",
    ) -> tuple[str, dict]:
        refs = list(refs or [])
        if not prompt.strip():
            raise self._err("Image prompt is empty.", kind="bad_request")
        if aspect_ratio not in entry.aspect_ratios:
            raise self._err(f"{entry.label} does not support aspect ratio {aspect_ratio} "
                            f"(supported: {', '.join(entry.aspect_ratios)}).", kind="bad_request")
        if len(refs) > entry.max_reference_images:
            log.warning("%s accepts at most %d reference images; extra ones are not sent.", entry.label, entry.max_reference_images)
            refs = refs[: entry.max_reference_images]
        style = entry.request_style
        body: dict = {"prompt": prompt}
        if style == "flow_image":
            body.update(model=entry.model, aspect_ratio=aspect_ratio)
            if refs:
                body["reference_images"] = [self._encode_list_item(r, entry.supports_tag_binding) for r in refs]
            if upscale and upscale in entry.upscale_options:
                body["upscale"] = [upscale]
        elif style == "openai_image":
            body.update(aspect_ratio=aspect_ratio,
                        quality=entry.extra_params.get("quality", "high"),
                        prompt_mode=entry.extra_params.get("prompt_mode", "auto"))
            if refs:
                body["reference_images"] = [self._encode_list_item(r, False) for r in refs]
        elif style == "grok_image":
            mode = entry.modes.get("reference" if refs else "text", "i2i" if refs else "t2i")
            body.update(mode=mode, aspect_ratio=aspect_ratio)
            if refs:
                body["reference_images"] = [self._encode_list_item(r, False) for r in refs]
        elif style == "meta_image":
            mode = entry.modes.get("reference" if refs else "text", "i2i" if refs else "t2i")
            body.update(mode=mode, aspect_ratio=aspect_ratio, count=1)
            field_for = {"subject": "character_image", "scene": "scene_image", "style": "style_image"}
            for r in refs:
                f = field_for.get(r.role, "character_image")
                if f not in body:
                    body[f] = self._encode_named(r)
        else:
            raise self._err(f"Unsupported image request style '{style}'.", kind="config")
        return entry.route, body

    def build_video_request(
        self,
        entry: VideoOptionEntry,
        *,
        prompt: str,
        aspect_ratio: str,
        mode_key: str,
        start_ref: RefImage | None = None,
        end_ref: RefImage | None = None,
        duration: int | None = None,
        resolution: str = "",
    ) -> tuple[str, dict]:
        if not prompt.strip():
            raise self._err("Motion prompt is empty.", kind="bad_request")
        if mode_key not in entry.modes:
            fallback = "start" if (mode_key == "start_end" and "start" in entry.modes) else ("text" if "text" in entry.modes else "")
            raise self._err(
                f"{entry.label} has no documented '{MODE_LABELS.get(mode_key, mode_key)}' mode.",
                kind="unsupported_mode",
                hint=f"Documented fallback: {MODE_LABELS.get(fallback, fallback)}." if fallback else "",
                fallback=fallback,
            )
        if mode_key in ("start", "start_end") and start_ref is None:
            raise self._err("This mode needs a start image. Generate or upload the scene image first.", kind="bad_request",
                            fallback="text" if "text" in entry.modes else "")
        if mode_key == "start_end" and end_ref is None:
            raise self._err("Start + end mode needs an end frame.", kind="bad_request", fallback="start")
        if aspect_ratio not in entry.aspect_ratios:
            raise self._err(f"{entry.label} does not support aspect ratio {aspect_ratio}.", kind="bad_request")
        allowed_d = sorted(set(entry.durations) | set(entry.ultra_durations))
        if duration is not None and allowed_d and duration not in allowed_d:
            raise self._err(f"{entry.label} does not support {duration}s clips (supported: {allowed_d}).", kind="bad_request")
        if resolution and entry.resolutions and resolution not in entry.resolutions:
            resolution = entry.default_resolution
        api_mode = entry.modes[mode_key]
        style = entry.request_style
        body: dict = {"prompt": prompt}
        if style == "veo":
            body.update(model=entry.model, aspect_ratio=aspect_ratio, mode=api_mode)
            refs = []
            if mode_key in ("start", "start_end"):
                refs.append(self._encode_list_item(start_ref, True))  # type: ignore[arg-type]
            if mode_key == "start_end":
                refs.append(self._encode_list_item(end_ref, True))  # type: ignore[arg-type]
            if refs:
                body["reference_images"] = refs
            if resolution:
                body["resolution"] = [resolution]
            if duration:
                body["video_length"] = int(duration)
        elif style == "grok_video":
            body.update(mode=api_mode, aspect_ratio=aspect_ratio)
            if duration:
                body["video_length"] = int(duration)
            if resolution:
                body["resolution"] = resolution
            if api_mode == "i2v":
                body["reference_images"] = [self._encode_list_item(start_ref, False)]  # type: ignore[arg-type]
        elif style == "meta_video":
            body.update(mode=api_mode, aspect_ratio=aspect_ratio, count=1)
            if resolution:
                body["resolution"] = resolution
            if api_mode == "i2v":
                body["start_image"] = self._encode_named(start_ref)  # type: ignore[arg-type]
                if mode_key == "start_end" and end_ref is not None:
                    body["end_image"] = self._encode_named(end_ref)
        else:
            raise self._err(f"Unsupported video request style '{style}'.", kind="config")
        return entry.route, body

    # -- submit ----------------------------------------------------------------
    def submit(self, route: str, body: dict) -> str:
        if route not in ALLOWED_ROUTES:
            raise self._err(f"Route {route} is not a documented G-Labs endpoint.", kind="config")
        approx = sum(len(v) for v in _iter_strings(body))
        if approx > MAX_BODY_BYTES * 0.97:
            raise self._err("Request is larger than the 50 MB limit.", kind="payload_too_large",
                            hint="Use fewer/smaller reference images or switch reference transfer to 'local file path'.")
        log.info("G-Labs: POST %s (%s)", route, summarize_body(body))
        data = self.request_json("POST", route, body=body, timeout=max(self._timeout, 60.0))
        task_id = data.get("task_id")
        if not task_id:
            raise self._err("G-Labs accepted the request but returned no task_id.", kind="invalid_response")
        return str(task_id)

    def failure_hint(self, status: dict) -> str:
        code = status.get("error_code")
        err = str(status.get("error") or "") + " " + str(status.get("error_detail") or "")
        low = err.lower()
        if self._path_denied_text(err):
            return ("G-Labs Studio cannot read the reference image file (OS privacy protection). Settings → Generation "
                    "→ Reference image transfer: choose 'Auto' or 'Always base64', then retry.")
        if code == 429 or "quota" in low or "resource_exhausted" in low:
            return "Quota or rate limit reached on the logged-in account. Wait, enable more accounts in G-Labs, or retry later."
        if code == 401 or "cookie expired" in low:
            return "The provider session expired. Log in again inside G-Labs Studio."
        if code == 403 or "permission" in low:
            return "Permission denied / session issue. Check the account is logged in and enabled in G-Labs Studio."
        if "no active accounts" in low or "no enabled" in low:
            return "No eligible account is logged in and enabled in G-Labs Studio for this model."
        if "ultra" in low or "4k" in low:
            return "This option needs an ULTRA account. Choose another duration/resolution or model."
        if "i2v_end" in low:
            return "This server is not configured for start+end frames on Omni Flash. Retry with 'Start image' mode."
        if code == 400 or "invalid_argument" in low or "policy" in low:
            return "The prompt or parameters were rejected (possibly a content policy). Edit the prompt and retry."
        if "timeout" in low:
            return "G-Labs gave up waiting for a result. Retry later."
        return "See the G-Labs Studio window for details."


def _iter_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_strings(v)
