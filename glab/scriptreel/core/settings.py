"""Application settings (per user). Never contains API keys."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .paths import config_dir, default_projects_dir

log = logging.getLogger("scriptreel.settings")


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    settings_version: int = 1
    language: str = "en"

    # Connections (keys live in the OS credential vault, not here)
    voice_base_url: str = "http://127.0.0.1:8766"
    glabs_base_url: str = "http://127.0.0.1:8765"
    request_timeout_s: float = 30.0
    voice_task_timeout_s: int = 1800
    image_task_timeout_s: int = 900
    video_task_timeout_s: int = 2700
    poll_interval_s: float = 4.0
    max_parallel_tasks: int = 4
    reference_transfer: str = "auto"  # auto | base64 | path
    google_ultra: bool = False  # user-declared account tier (unlocks ULTRA-only options in the UI)

    # Tools
    ffmpeg_path: str = ""
    ffprobe_path: str = ""

    # Alignment
    alignment_engine: str = "auto"  # auto | faster_whisper | estimate
    whisper_model: str = "small"
    whisper_device: str = "auto"
    whisper_compute_type: str = "auto"
    whisper_model_dir: str = ""

    # Prompt LLM
    llm_provider: str = "none"
    llm_model: str = ""
    llm_base_url: str = ""
    llm_temperature: float = 0.7

    # Misc
    output_dir: str = Field(default_factory=lambda: str(default_projects_dir()))
    recent_projects: list[str] = Field(default_factory=list)
    autosave: bool = True
    show_activity: bool = True


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config_dir() / "settings.json")
        self.settings = self.load()

    def load(self) -> AppSettings:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                return AppSettings.model_validate(data)
            except Exception as exc:
                log.error("Settings file unreadable (%s); using defaults", exc)
                try:
                    self.path.replace(self.path.with_suffix(".broken.json"))
                except OSError:
                    pass
        return AppSettings()

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(self.settings.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def add_recent(self, folder: Path) -> None:
        f = str(Path(folder).resolve())
        rec = [r for r in self.settings.recent_projects if r != f]
        rec.insert(0, f)
        self.settings.recent_projects = rec[:12]
        self.save()

    def remove_recent(self, folder: str) -> None:
        self.settings.recent_projects = [r for r in self.settings.recent_projects if r != folder]
        self.save()
