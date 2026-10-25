"""Model catalog loading and validation.

The catalog is a local, versioned JSON file. It is NOT fetched from G-Labs
(no documented model-list endpoint exists). A user copy in the config dir
overrides the bundled one so it can be edited in packaged installs.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .paths import bundled_catalog_path, user_catalog_path

log = logging.getLogger("scriptreel.catalog")

ALLOWED_ROUTES = {
    "/api/image/generate",
    "/api/video/generate",
    "/api/grok/generate",
    "/api/meta/generate",
    "/api/openai/generate",
}
STYLE_ROUTES = {
    "flow_image": "/api/image/generate",
    "openai_image": "/api/openai/generate",
    "grok_image": "/api/grok/generate",
    "meta_image": "/api/meta/generate",
    "veo": "/api/video/generate",
    "grok_video": "/api/grok/generate",
    "meta_video": "/api/meta/generate",
}
VIDEO_MODE_KEYS = ("text", "start", "start_end")
MODE_LABELS = {
    "auto": "Auto (best available)",
    "text": "Text → video",
    "start": "Start image → video",
    "start_end": "Start + end frame",
}


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ImageModelEntry(_M):
    id: str
    label: str
    provider: str = ""
    route: str
    request_style: str
    model: str | None = None
    modes: dict[str, str] = Field(default_factory=dict)
    aspect_ratios: list[str]
    max_reference_images: int = 0
    upscale_options: list[str] = Field(default_factory=list)
    ultra_upscale: list[str] = Field(default_factory=list)
    supports_tag_binding: bool = False
    extra_params: dict = Field(default_factory=dict)
    requirements: str = ""
    notes: str = ""
    doc_section: str = ""
    enabled: bool = True
    documented: bool = True

    @property
    def api_identity(self) -> str:
        if self.model:
            return f"{self.route} · model={self.model}"
        if self.modes:
            return f"{self.route} · mode={'/'.join(self.modes.values())}"
        return self.route


class VideoOptionEntry(_M):
    id: str
    label: str
    group: str = ""
    provider: str = ""
    route: str
    request_style: str
    model: str | None = None
    modes: dict[str, str]
    aspect_ratios: list[str]
    durations: list[int] = Field(default_factory=list)
    ultra_durations: list[int] = Field(default_factory=list)
    default_duration: int | None = None
    resolutions: list[str] = Field(default_factory=list)
    ultra_resolutions: list[str] = Field(default_factory=list)
    default_resolution: str = "720p"
    max_reference_images: int = 0
    supports_end_frame: bool = False
    end_frame_note: str = ""
    chaining_supported: bool = True
    requires_ultra: bool = False
    requirements: str = ""
    notes: str = ""
    doc_section: str = ""
    enabled: bool = True
    documented: bool = True

    @property
    def api_identity(self) -> str:
        if self.model:
            return f"{self.route} · model={self.model}"
        return f"{self.route} · modes {', '.join(f'{k}={v}' for k, v in self.modes.items())}"


class ModelCatalog(_M):
    schema_version: int = 1
    catalog_version: str = "unknown"
    updated: str = ""
    verified_against: str = ""
    sources: dict[str, str] = Field(default_factory=dict)
    disclaimer: str = ""
    image_models: list[ImageModelEntry] = Field(default_factory=list)
    video_options: list[VideoOptionEntry] = Field(default_factory=list)

    def image(self, model_id: str) -> ImageModelEntry | None:
        return next((m for m in self.image_models if m.id == model_id), None)

    def video(self, option_id: str) -> VideoOptionEntry | None:
        return next((v for v in self.video_options if v.id == option_id), None)

    def enabled_images(self) -> list[ImageModelEntry]:
        return [m for m in self.image_models if m.enabled]

    def enabled_videos(self) -> list[VideoOptionEntry]:
        return [v for v in self.video_options if v.enabled]

    @staticmethod
    def durations(entry: VideoOptionEntry, ultra: bool) -> list[int]:
        d = set(entry.durations)
        if ultra:
            d |= set(entry.ultra_durations)
        return sorted(d)

    @staticmethod
    def resolutions(entry: VideoOptionEntry, ultra: bool) -> list[str]:
        return [r for r in entry.resolutions if ultra or r not in entry.ultra_resolutions]


def validate_catalog(cat: ModelCatalog) -> list[str]:
    """Return human-readable problems. Entries with fatal problems are disabled."""
    problems: list[str] = []
    seen: set[str] = set()
    for e in [*cat.image_models, *cat.video_options]:
        if e.id in seen:
            problems.append(f"Duplicate id '{e.id}'.")
        seen.add(e.id)
        if e.route not in ALLOWED_ROUTES:
            problems.append(f"'{e.id}': route {e.route} is not a documented G-Labs endpoint — disabled.")
            e.enabled = False
        expected = STYLE_ROUTES.get(e.request_style)
        if expected is None:
            problems.append(f"'{e.id}': unknown request_style '{e.request_style}' — disabled.")
            e.enabled = False
        elif expected != e.route:
            problems.append(f"'{e.id}': request_style {e.request_style} must use {expected} — disabled.")
            e.enabled = False
    for v in cat.video_options:
        bad = [k for k in v.modes if k not in VIDEO_MODE_KEYS]
        if bad:
            problems.append(f"'{v.id}': unknown mode keys {bad} (allowed: {VIDEO_MODE_KEYS}).")
        if v.request_style in ("grok_video", "meta_video") and v.model:
            problems.append(f"'{v.id}': {v.route} takes modes, not a model id — 'model' will be ignored.")
            v.model = None
    if not cat.enabled_images():
        problems.append("No enabled image models in catalog.")
    if not cat.enabled_videos():
        problems.append("No enabled video options in catalog.")
    return problems


def load_catalog(path: Path | None = None) -> tuple[ModelCatalog, Path, list[str]]:
    """Load user override if present, else bundled. Falls back to bundled on errors."""
    candidates = [path] if path else [user_catalog_path(), bundled_catalog_path()]
    warnings: list[str] = []
    for p in candidates:
        if p is None or not p.exists():
            continue
        try:
            cat = ModelCatalog.model_validate(json.loads(p.read_text(encoding="utf-8")))
            warnings += validate_catalog(cat)
            return cat, p, warnings
        except Exception as exc:
            msg = f"Model catalog {p} could not be loaded: {exc}"
            log.error(msg)
            warnings.append(msg)
    cat = ModelCatalog()
    warnings.append("No usable model catalog found.")
    return cat, bundled_catalog_path(), warnings


def ensure_user_catalog() -> Path:
    """Copy bundled catalog to the user config dir (for editing) if not there yet."""
    dst = user_catalog_path()
    if not dst.exists():
        shutil.copyfile(bundled_catalog_path(), dst)
    return dst


def reset_user_catalog() -> None:
    dst = user_catalog_path()
    if dst.exists():
        dst.replace(dst.with_suffix(".previous.json"))
