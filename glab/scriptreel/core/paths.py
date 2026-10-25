"""Filesystem locations (works from source and from a PyInstaller bundle)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from platformdirs import user_config_dir, user_documents_dir

from .. import APP_SLUG


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Directory that contains the `config/` and `assets/` folders of the package."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "scriptreel"
    return Path(__file__).resolve().parent.parent


def app_root() -> Path:
    """Folder next to the executable (frozen) or the repository root (source)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return resource_dir().parent


def bundled_bin_dir() -> Path:
    """Optional `bin/` folder where a user may drop ffmpeg.exe / ffprobe.exe."""
    return app_root() / "bin"


def bundled_catalog_path() -> Path:
    return resource_dir() / "config" / "model_catalog.json"


def i18n_dir() -> Path:
    return resource_dir() / "config" / "i18n"


def assets_dir() -> Path:
    return resource_dir() / "assets"


def config_dir() -> Path:
    override = os.environ.get("SCRIPTREEL_CONFIG_DIR")
    p = Path(override) if override else Path(user_config_dir(APP_SLUG, appauthor=False, roaming=True))
    p.mkdir(parents=True, exist_ok=True)
    return p


def user_catalog_path() -> Path:
    """Editable copy of the model catalog. Takes precedence over the bundled one."""
    return config_dir() / "model_catalog.json"


def logs_dir() -> Path:
    p = config_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_projects_dir() -> Path:
    try:
        docs = Path(user_documents_dir())
    except Exception:  # pragma: no cover - very unusual systems
        docs = Path.home()
    return docs / "ScriptReel Projects"
