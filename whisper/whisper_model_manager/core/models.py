"""
models.py — Model definitions and local-detection logic.

All supported faster-whisper / CTranslate2 models are defined here in a single
list-of-dicts so that adding new models requires touching *only* this file.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── Model Status ──────────────────────────────────────────────────────────────

class ModelStatus(Enum):
    """Lifecycle states for a model entry."""
    NOT_DOWNLOADED = auto()
    DOWNLOADING = auto()
    DOWNLOADED = auto()
    ERROR = auto()


# ── Model Dataclass ───────────────────────────────────────────────────────────

@dataclass
class ModelInfo:
    """Metadata for one faster-whisper model."""
    id: str                          # short key, e.g. "turbo"
    display_name: str                # e.g. "Turbo (Recommended)"
    hf_repo_id: str                  # HuggingFace repo identifier
    params: str                      # e.g. "809 M"
    approx_size: str                 # human-readable, e.g. "1.6 GB"
    approx_size_bytes: int           # bytes, used for disk-space check
    ram_usage: str                   # e.g. "~4 GB"
    recommended: bool = False        # show a badge on the row
    status: ModelStatus = ModelStatus.NOT_DOWNLOADED
    local_size_bytes: int = 0        # actual size on disk
    error_message: str = ""
    progress: float = 0.0           # 0.0 – 1.0 during download
    speed_bps: float = 0.0          # bytes per second
    eta_seconds: float = 0.0        # estimated time remaining
    downloaded_bytes: int = 0       # bytes downloaded so far
    total_bytes: int = 0            # total bytes to download

    @property
    def local_folder_name(self) -> str:
        """Folder name under the model directory (last segment of repo id)."""
        return self.hf_repo_id.replace("/", "--")

    @property
    def simple_folder_name(self) -> str:
        """Simple folder name for manual installs."""
        return self.hf_repo_id.split("/")[-1]


# ── Model Registry ───────────────────────────────────────────────────────────

# Keep this list as the single source of truth.  To add a model, just append
# a new dict here — the rest of the app picks it up automatically.

MODEL_DEFS: list[dict] = [
    {
        "id": "turbo",
        "display_name": "Turbo",
        "hf_repo_id": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        "params": "809 M",
        "approx_size": "1.6 GB",
        "approx_size_bytes": 1_717_986_918,
        "ram_usage": "~4 GB",
        "recommended": True,
    },
    {
        "id": "tiny",
        "display_name": "Tiny",
        "hf_repo_id": "Systran/faster-whisper-tiny",
        "params": "39 M",
        "approx_size": "75 MB",
        "approx_size_bytes": 78_643_200,
        "ram_usage": "~0.5 GB",
    },
    {
        "id": "base",
        "display_name": "Base",
        "hf_repo_id": "Systran/faster-whisper-base",
        "params": "74 M",
        "approx_size": "145 MB",
        "approx_size_bytes": 151_994_368,
        "ram_usage": "~1 GB",
    },
    {
        "id": "small",
        "display_name": "Small",
        "hf_repo_id": "Systran/faster-whisper-small",
        "params": "244 M",
        "approx_size": "484 MB",
        "approx_size_bytes": 507_510_784,
        "ram_usage": "~2 GB",
    },
    {
        "id": "medium",
        "display_name": "Medium",
        "hf_repo_id": "Systran/faster-whisper-medium",
        "params": "769 M",
        "approx_size": "1.5 GB",
        "approx_size_bytes": 1_610_612_736,
        "ram_usage": "~5 GB",
    },
    {
        "id": "large-v3",
        "display_name": "Large v3",
        "hf_repo_id": "Systran/faster-whisper-large-v3",
        "params": "1550 M",
        "approx_size": "3.1 GB",
        "approx_size_bytes": 3_328_599_654,
        "ram_usage": "~8 GB",
    },
]


def build_model_list() -> list[ModelInfo]:
    """Create fresh ModelInfo instances from the registry."""
    return [ModelInfo(**d) for d in MODEL_DEFS]


# ── Detection Logic ──────────────────────────────────────────────────────────

# Files that a valid CTranslate2 faster-whisper model folder must contain.
REQUIRED_FILES: set[str] = {"model.bin", "config.json", "tokenizer.json"}

# Additional vocabulary files — at least one must be present.
VOCAB_FILES: set[str] = {"vocabulary.txt", "vocabulary.json", "added_tokens.json"}


def _folder_size(path: Path) -> int:
    """Recursively compute the total byte size of *path*."""
    total = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file():
                total += entry.stat().st_size
    except OSError:
        pass
    return total


def is_model_complete(folder: Path) -> bool:
    """
    Return True if *folder* looks like a valid, fully-downloaded model.

    Checks for the presence of required core files and at least one
    vocabulary file.
    """
    if not folder.is_dir():
        return False

    existing = {f.name for f in folder.iterdir() if f.is_file()}

    # All required files must be present
    if not REQUIRED_FILES.issubset(existing):
        return False

    # At least one vocabulary file must be present
    if not VOCAB_FILES & existing:
        return False

    # model.bin must not be zero-length (incomplete download)
    model_bin = folder / "model.bin"
    if model_bin.exists() and model_bin.stat().st_size == 0:
        return False

    return True


def scan_models(model_dir: Path, models: list[ModelInfo]) -> None:
    """
    Scan *model_dir* and update each ModelInfo's status and local_size_bytes.

    Models are detected by checking both the HF-style folder name
    (org--repo-name) and the simple folder name (repo-name).
    """
    for m in models:
        # Don't overwrite an active download
        if m.status == ModelStatus.DOWNLOADING:
            continue

        # Check both naming conventions
        candidates = [
            model_dir / m.local_folder_name,
            model_dir / m.simple_folder_name,
        ]

        found = False
        for folder in candidates:
            if is_model_complete(folder):
                m.status = ModelStatus.DOWNLOADED
                m.local_size_bytes = _folder_size(folder)
                m.error_message = ""
                found = True
                logger.info("Model '%s' found at %s (%d bytes)",
                            m.display_name, folder, m.local_size_bytes)
                break

        if not found and m.status != ModelStatus.ERROR:
            m.status = ModelStatus.NOT_DOWNLOADED
            m.local_size_bytes = 0


def delete_model(model_dir: Path, model: ModelInfo) -> None:
    """Delete a downloaded model's folder(s) from disk."""
    for name in (model.local_folder_name, model.simple_folder_name):
        folder = model_dir / name
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
            logger.info("Deleted model folder: %s", folder)
    model.status = ModelStatus.NOT_DOWNLOADED
    model.local_size_bytes = 0
    model.error_message = ""


def get_disk_usage(models: list[ModelInfo]) -> int:
    """Return total bytes used by all downloaded models."""
    return sum(m.local_size_bytes for m in models if m.status == ModelStatus.DOWNLOADED)


def format_bytes(size_bytes: int) -> str:
    """Human-readable byte size (e.g. '1.6 GB')."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / 1024**2:.1f} MB"
    else:
        return f"{size_bytes / 1024**3:.2f} GB"
