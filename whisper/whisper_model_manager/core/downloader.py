"""
downloader.py — Threaded download manager with real progress tracking.

Uses huggingface_hub's snapshot_download with a custom tqdm wrapper to
report byte-level progress back to the UI.  Downloads run in daemon threads
so the GUI never blocks.
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from pathlib import Path
from queue import Queue, Empty
from typing import Any, Callable, Optional

from tqdm import tqdm

logger = logging.getLogger(__name__)

# Type alias for progress callbacks:
#   callback(model_id, downloaded_bytes, total_bytes, speed_bps, eta_seconds, done, error_msg)
ProgressCallback = Callable[[str, int, int, float, float, bool, str], None]


# ── Custom tqdm class for capturing byte progress ────────────────────────────

class _HFProgressBar(tqdm):
    """
    A tqdm subclass that routes progress updates to a callback instead of
    writing to stderr.  huggingface_hub's snapshot_download accepts a
    ``tqdm_class`` parameter; we exploit that to get real byte progress.
    """

    # Class-level storage set before each download call
    _callback: Optional[ProgressCallback] = None
    _model_id: str = ""
    _cancel_event: Optional[threading.Event] = None
    _global_downloaded: int = 0
    _global_total: int = 0
    _start_time: float = 0.0
    _lock = threading.Lock()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Silence tqdm's own output by redirecting to devnull
        import io
        kwargs["disable"] = False
        kwargs.setdefault("file", io.StringIO())  # swallow all tqdm output
        super().__init__(*args, **kwargs)
        self._file_total = self.total or 0

    def update(self, n: int = 1) -> None:  # type: ignore[override]
        """Called by huggingface_hub as bytes are written."""
        super().update(n)

        if _HFProgressBar._cancel_event and _HFProgressBar._cancel_event.is_set():
            raise DownloadCancelled(f"Download cancelled for {_HFProgressBar._model_id}")

        with _HFProgressBar._lock:
            _HFProgressBar._global_downloaded += n
            downloaded = _HFProgressBar._global_downloaded
            total = _HFProgressBar._global_total

        elapsed = time.time() - _HFProgressBar._start_time
        speed = downloaded / elapsed if elapsed > 0.5 else 0.0
        eta = (total - downloaded) / speed if speed > 0 else 0.0

        if _HFProgressBar._callback:
            _HFProgressBar._callback(
                _HFProgressBar._model_id,
                downloaded,
                total,
                speed,
                eta,
                False,  # not done yet
                "",
            )

    def close(self) -> None:
        super().close()


class DownloadCancelled(Exception):
    """Raised inside the tqdm callback to abort a running download."""


# ── Download Manager ─────────────────────────────────────────────────────────

class DownloadManager:
    """
    Manages background downloads of HuggingFace model repositories.

    Features:
    - One download thread per model (daemon thread)
    - Cancel support via threading.Event
    - Real byte-level progress via custom tqdm
    - Automatic resume (huggingface_hub handles partial files)
    - Disk-space pre-check
    """

    def __init__(self) -> None:
        self._active_threads: dict[str, threading.Thread] = {}
        self._cancel_events: dict[str, threading.Event] = {}

    # ── Public API ────────────────────────────────────────────────────────

    def is_downloading(self, model_id: str) -> bool:
        t = self._active_threads.get(model_id)
        return t is not None and t.is_alive()

    def start_download(
        self,
        model_id: str,
        hf_repo_id: str,
        dest_dir: Path,
        approx_size_bytes: int,
        callback: ProgressCallback,
    ) -> Optional[str]:
        """
        Start downloading *hf_repo_id* into *dest_dir* in a background thread.

        Returns an error string if the download cannot start (e.g. not enough
        disk space), or None on success.
        """
        if self.is_downloading(model_id):
            return "A download is already in progress for this model."

        # ── Disk space check ──────────────────────────────────────────────
        try:
            free = shutil.disk_usage(dest_dir).free
            if free < approx_size_bytes:
                from whisper_model_manager.core.models import format_bytes
                msg = (
                    f"Not enough disk space. Need ~{format_bytes(approx_size_bytes)}, "
                    f"but only {format_bytes(free)} free."
                )
                logger.warning(msg)
                return msg
        except OSError as exc:
            logger.warning("Could not check disk space: %s", exc)

        cancel_event = threading.Event()
        self._cancel_events[model_id] = cancel_event

        thread = threading.Thread(
            target=self._download_worker,
            args=(model_id, hf_repo_id, dest_dir, approx_size_bytes, callback, cancel_event),
            daemon=True,
            name=f"dl-{model_id}",
        )
        self._active_threads[model_id] = thread
        thread.start()
        return None

    def cancel_download(self, model_id: str) -> None:
        """Signal a running download to stop."""
        evt = self._cancel_events.get(model_id)
        if evt:
            evt.set()
            logger.info("Cancel requested for model '%s'", model_id)

    # ── Worker Thread ─────────────────────────────────────────────────────

    def _download_worker(
        self,
        model_id: str,
        hf_repo_id: str,
        dest_dir: Path,
        approx_size_bytes: int,
        callback: ProgressCallback,
        cancel_event: threading.Event,
    ) -> None:
        """Background thread that performs the actual download."""
        try:
            # Late imports to keep startup fast
            from huggingface_hub import snapshot_download, HfApi

            # ── Resolve total size via HF API ─────────────────────────────
            total_bytes = approx_size_bytes  # fallback
            try:
                api = HfApi()
                info = api.model_info(hf_repo_id, files_metadata=True)
                if info.siblings:
                    computed = sum(
                        s.size for s in info.siblings if s.size is not None
                    )
                    if computed > 0:
                        total_bytes = computed
                        logger.info(
                            "Resolved total size for %s: %d bytes", hf_repo_id, total_bytes
                        )
            except Exception as exc:
                logger.warning("Could not resolve repo size via API: %s", exc)

            # ── Configure the progress tracker ────────────────────────────
            _HFProgressBar._callback = callback
            _HFProgressBar._model_id = model_id
            _HFProgressBar._cancel_event = cancel_event
            _HFProgressBar._global_downloaded = 0
            _HFProgressBar._global_total = total_bytes
            _HFProgressBar._start_time = time.time()

            # ── Determine destination folder ──────────────────────────────
            local_dir = dest_dir / hf_repo_id.replace("/", "--")
            local_dir.mkdir(parents=True, exist_ok=True)

            # ── Run the download ──────────────────────────────────────────
            snapshot_download(
                repo_id=hf_repo_id,
                local_dir=str(local_dir),
                tqdm_class=_HFProgressBar,
            )

            # ── Success ───────────────────────────────────────────────────
            callback(model_id, total_bytes, total_bytes, 0.0, 0.0, True, "")
            logger.info("Download complete: %s", hf_repo_id)

        except DownloadCancelled:
            callback(model_id, 0, 0, 0.0, 0.0, True, "__cancelled__")
            logger.info("Download cancelled: %s", hf_repo_id)

        except Exception as exc:
            error_msg = self._friendly_error(exc)
            callback(model_id, 0, 0, 0.0, 0.0, True, error_msg)
            logger.exception("Download failed for %s", hf_repo_id)

        finally:
            self._active_threads.pop(model_id, None)
            self._cancel_events.pop(model_id, None)
            # Reset class-level state
            _HFProgressBar._callback = None
            _HFProgressBar._cancel_event = None

    # ── Error Handling ────────────────────────────────────────────────────

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        """Convert an exception into a user-friendly error message."""
        msg = str(exc).lower()

        if "connectionerror" in type(exc).__name__.lower() or "no internet" in msg:
            return "No internet connection. Check your network and try again."
        if "timeout" in msg:
            return "Connection timed out. Try again later."
        if "429" in msg or "rate limit" in msg:
            return "HuggingFace rate limit reached. Wait a few minutes and retry."
        if "disk" in msg or "space" in msg or "errno 28" in msg or "no space" in msg:
            return "Disk full. Free up space and try again."
        if "403" in msg or "401" in msg:
            return "Access denied. The model repository may be private or gated."
        if "404" in msg:
            return "Model not found on HuggingFace. The repo ID may have changed."

        return f"Download failed: {type(exc).__name__}: {exc}"
