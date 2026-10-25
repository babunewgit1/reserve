"""Typed, versioned project schema (project.json).

Rules:
* Paths are stored relative to the project folder (POSIX separators).
* API keys are never part of this schema.
* Unknown fields are ignored so older apps can still open newer minor files,
  and `migrate()` upgrades older schema versions step by step.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .. import __version__

SCHEMA_VERSION = 1

BUSY_STATES = ("queued", "submitting", "running", "downloading")


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore")


class TaskInfo(_M):
    state: str = "idle"  # idle|queued|submitting|running|downloading|completed|failed|lost|cancelled
    task_id: str = ""
    route: str = ""
    model: str = ""
    mode: str = ""
    remote_status: str = ""
    message: str = ""
    error: str = ""
    error_code: int | None = None
    hint: str = ""
    fallback: str = ""  # suggested documented fallback (e.g. video mode key)
    submitted_at: float | None = None
    finished_at: float | None = None

    @property
    def busy(self) -> bool:
        return self.state in BUSY_STATES


class AssetVersion(_M):
    path: str
    created_at: float = Field(default_factory=time.time)
    source: str = "generated"  # generated | uploaded
    task_id: str = ""
    model: str = ""
    mode: str = ""
    prompt: str = ""
    chained: bool = False  # clip was generated from previous scene's last frame
    duration: float | None = None
    note: str = ""


class Cue(_M):
    start: float
    end: float
    text: str


class StyleRef(_M):
    path: str
    name: str = ""
    role: str = "subject"  # subject | scene | style
    use_by_default: bool = True


class StyleBible(_M):
    visual_style: str = "Clean, modern 3D explainer illustration, soft studio lighting, friendly and clear"
    characters: str = ""
    setting: str = ""
    palette: str = ""
    avoid: str = "on-screen text, captions, watermarks, logos, distorted hands"
    references: list[StyleRef] = Field(default_factory=list)


class VoiceSettings(_M):
    preset_id: str = ""
    preset_name: str = ""
    preset_tags: list[str] = Field(default_factory=list)
    language: str = "Auto"
    speed: float = 1.0
    output_format: str = "wav"
    num_step: int | None = None
    guidance_scale: float | None = None


class VoiceState(_M):
    task: TaskInfo = Field(default_factory=TaskInfo)
    takes: list[AssetVersion] = Field(default_factory=list)
    selected_take: int = -1
    duration: float = 0.0
    script_hash: str = ""
    narration_file: str = ""  # canonical copy in project root (narration.wav / .mp3)


class AlignmentState(_M):
    engine: str = ""
    model: str = ""
    method: str = ""
    precision_note: str = ""
    match_ratio: float | None = None
    created_at: float | None = None
    audio_take: str = ""
    reviewed: bool = False
    task: TaskInfo = Field(default_factory=TaskInfo)
    words: list[tuple[float, float, str]] = Field(default_factory=list)


class Scene(_M):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    start: float = 0.0
    end: float = 0.0
    text: str = ""

    image_prompt: str = ""
    motion_prompt: str = ""
    prompt_source: str = ""  # llm | draft | manual
    prompt_task: TaskInfo = Field(default_factory=TaskInfo)

    ref_names: list[str] | None = None  # None = use style refs marked default
    extra_refs: list[str] = Field(default_factory=list)

    image_model: str = ""  # "" = project default
    video_option: str = ""  # "" = project default
    video_mode: str = ""  # "" = project default; auto|text|start|start_end

    image_task: TaskInfo = Field(default_factory=TaskInfo)
    images: list[AssetVersion] = Field(default_factory=list)
    selected_image: int = -1
    image_approved: bool = False

    video_task: TaskInfo = Field(default_factory=TaskInfo)
    videos: list[AssetVersion] = Field(default_factory=list)
    selected_video: int = -1
    gen_length: int | None = None
    chain_frame: str = ""

    trim_in: float = 0.0
    crop_mode: str = ""  # "" = project default; fit | fill
    focal_x: float = 0.5
    focal_y: float = 0.5
    notes: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def image_asset(self) -> AssetVersion | None:
        if 0 <= self.selected_image < len(self.images):
            return self.images[self.selected_image]
        return None

    def video_asset(self) -> AssetVersion | None:
        if 0 <= self.selected_video < len(self.videos):
            return self.videos[self.selected_video]
        return None


class ProjectSettings(_M):
    title: str = "Untitled explainer"
    aspect_ratio: str = "16:9"
    image_model: str = "nano_banana_2"
    image_upscale: str = ""
    video_option: str = "veo_31_fast"
    video_mode: str = "auto"
    video_resolution: str = "720p"
    clip_mode: str = "flexible"  # flexible | fixed8
    min_scene: float = 3.0
    target_scene: float = 6.0
    max_scene: float = 10.0
    burn_subtitles: bool = True
    youtube_metadata: bool = False
    chain_frames: bool = False
    run_mode: str = "manual"  # manual | automatic
    review_prompts: bool = True
    require_image_approval: bool = True


class SubtitleStyle(_M):
    font: str = "Arial"
    size: int = 18
    color: str = "#FFFFFF"
    outline_color: str = "#101833"
    outline: float = 2.0
    bold: bool = True
    margin_v: int = 28
    box: bool = False


class RenderSettings(_M):
    resolution: str = "1080p"
    fps: int = 30
    crop_mode: str = "fill"  # fill | fit
    fit_background: str = "blur"  # blur | black
    subtitle_style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    soft_subtitles: bool = False
    narration_volume: float = 1.0
    music_path: str = ""
    music_volume: float = 0.15
    ducking: bool = True
    crf: int = 20
    preset: str = "medium"
    output_name: str = "final_animated_explainer.mp4"
    task: TaskInfo = Field(default_factory=TaskInfo)
    last_output: str = ""
    last_render_at: float | None = None
    last_report: str = ""


class YouTubeState(_M):
    task: TaskInfo = Field(default_factory=TaskInfo)
    data: dict[str, Any] = Field(default_factory=dict)
    md_path: str = ""
    json_path: str = ""
    thumbnail: str = ""


class Project(_M):
    schema_version: int = SCHEMA_VERSION
    app_version: str = __version__
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    settings: ProjectSettings = Field(default_factory=ProjectSettings)
    script: str = ""
    voice_settings: VoiceSettings = Field(default_factory=VoiceSettings)
    voice: VoiceState = Field(default_factory=VoiceState)
    alignment: AlignmentState = Field(default_factory=AlignmentState)
    cues: list[Cue] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    style: StyleBible = Field(default_factory=StyleBible)
    render: RenderSettings = Field(default_factory=RenderSettings)
    youtube: YouTubeState = Field(default_factory=YouTubeState)

    def scene(self, scene_id: str) -> Scene | None:
        return next((s for s in self.scenes if s.id == scene_id), None)

    def scene_index(self, scene_id: str) -> int:
        return next((i for i, s in enumerate(self.scenes) if s.id == scene_id), -1)

    def narration_take(self) -> AssetVersion | None:
        v = self.voice
        if 0 <= v.selected_take < len(v.takes):
            return v.takes[v.selected_take]
        return None


RESOLUTIONS = {
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "2160p": (3840, 2160),
}


def render_dims(aspect: str, resolution: str) -> tuple[int, int]:
    w, h = RESOLUTIONS.get(resolution, RESOLUTIONS["1080p"])
    return (w, h) if aspect == "16:9" else (h, w)


class SchemaError(Exception):
    pass


def _migrate_0_to_1(data: dict) -> dict:
    # v0 (pre-release drafts) stored `title` at the root.
    settings = data.setdefault("settings", {})
    if "title" in data and "title" not in settings:
        settings["title"] = data.pop("title")
    return data


MIGRATIONS = {0: _migrate_0_to_1}


def migrate(data: dict) -> tuple[dict, list[str]]:
    notes: list[str] = []
    version = int(data.get("schema_version", 0))
    if version > SCHEMA_VERSION:
        notes.append(
            f"This project was saved by a newer app (schema v{version}). It was opened in compatibility mode; "
            "unknown fields will be dropped if you save."
        )
        return data, notes
    while version < SCHEMA_VERSION:
        fn = MIGRATIONS.get(version)
        if fn is None:
            raise SchemaError(f"No migration path from schema v{version}")
        data = fn(data)
        notes.append(f"Upgraded project schema v{version} → v{version + 1}")
        version += 1
        data["schema_version"] = version
    return data, notes
