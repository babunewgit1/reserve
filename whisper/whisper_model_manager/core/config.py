"""
config.py — Persistent configuration management.

Stores user preferences (model folder path, window geometry, etc.)
in %APPDATA%/WhisperModelManager/config.json on Windows,
or ~/.config/WhisperModelManager/config.json on other platforms.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Default Paths ────────────────────────────────────────────────────────────

def _default_app_data_dir() -> Path:
    """Return the platform-appropriate application data directory."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    return Path(base) / "WhisperModelManager"


def _default_model_dir() -> Path:
    """Return the default folder where models are stored."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    return Path(base) / "WhisperModelManager" / "models"


# ── Config Keys & Defaults ───────────────────────────────────────────────────

_DEFAULTS: dict[str, Any] = {
    "model_dir": str(_default_model_dir()),
    "window_geometry": "900x650",
}


# ── Config Class ─────────────────────────────────────────────────────────────

class AppConfig:
    """Thread-safe, JSON-backed configuration store."""

    def __init__(self, config_dir: Path | None = None) -> None:
        self._dir = config_dir or _default_app_data_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "config.json"
        self._data: dict[str, Any] = dict(_DEFAULTS)
        self._load()

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def config_dir(self) -> Path:
        return self._dir

    @property
    def model_dir(self) -> Path:
        """Return the current model directory (creates it if missing)."""
        p = Path(self._data["model_dir"])
        p.mkdir(parents=True, exist_ok=True)
        return p

    @model_dir.setter
    def model_dir(self, value: str | Path) -> None:
        self._data["model_dir"] = str(value)
        self._save()

    @property
    def window_geometry(self) -> str:
        return self._data.get("window_geometry", _DEFAULTS["window_geometry"])

    @window_geometry.setter
    def window_geometry(self, value: str) -> None:
        self._data["window_geometry"] = value
        self._save()

    @property
    def log_file(self) -> Path:
        return self._dir / "app.log"

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._save()

    # ── Internal ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                self._data.update(stored)
                logger.info("Config loaded from %s", self._path)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not read config (%s); using defaults.", exc)
        else:
            logger.info("No config file found; using defaults.")
            self._save()  # persist defaults

    def _save(self) -> None:
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except OSError as exc:
            logger.error("Failed to save config: %s", exc)
