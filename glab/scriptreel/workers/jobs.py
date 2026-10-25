"""Qt job system: QRunnable workers + signal bridge to the GUI thread.

Workers never touch widgets or the project; they emit signals that are
delivered (queued) to `JobManager`, which lives on the GUI thread.
"""
from __future__ import annotations

import logging
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..services.http_base import CancelledError, CancelToken

log = logging.getLogger("scriptreel.jobs")


class _JobSignals(QObject):
    event = Signal(str, object)
    progress = Signal(str, float, str)
    done = Signal(str, object)
    error = Signal(str, object)


class JobContext:
    def __init__(self, key: str, signals: _JobSignals, cancel: CancelToken) -> None:
        self.key = key
        self._signals = signals
        self.cancel = cancel

    def progress(self, frac: float, message: str = "") -> None:
        self._signals.progress.emit(self.key, float(frac), message)

    def emit(self, payload: dict) -> None:
        self._signals.event.emit(self.key, payload)


class Job(QRunnable):
    def __init__(self, key: str, title: str, fn: Callable, args: tuple, kwargs: dict) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.key = key
        self.title = title
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.cancel_token = CancelToken()
        self.signals = _JobSignals()
        self.started = False

    def run(self) -> None:  # worker thread
        self.started = True
        ctx = JobContext(self.key, self.signals, self.cancel_token)
        try:
            result = self.fn(ctx, *self.args, **self.kwargs)
        except CancelledError as exc:
            self.signals.error.emit(self.key, exc)
        except Exception as exc:  # noqa: BLE001 - reported to the UI
            log.debug("Job %s failed:\n%s", self.key, traceback.format_exc())
            self.signals.error.emit(self.key, exc)
        else:
            self.signals.done.emit(self.key, result)


class JobManager(QObject):
    started = Signal(str, str)  # key, title
    event = Signal(str, object)
    progress = Signal(str, float, str)
    finished = Signal(str, object)
    failed = Signal(str, object)
    changed = Signal()

    def __init__(self, parent: QObject | None = None, glabs_parallel: int = 4) -> None:
        super().__init__(parent)
        self.pools = {"default": QThreadPool(self), "glabs": QThreadPool(self), "voice": QThreadPool(self)}
        self.pools["default"].setMaxThreadCount(4)
        self.pools["glabs"].setMaxThreadCount(max(1, glabs_parallel))
        self.pools["voice"].setMaxThreadCount(1)  # Voice Studio generates serially anyway
        self.jobs: dict[str, Job] = {}
        self._pool_of: dict[str, str] = {}
        self.titles: dict[str, str] = {}
        self.last_progress: dict[str, tuple[float, str]] = {}

    def set_glabs_parallel(self, n: int) -> None:
        self.pools["glabs"].setMaxThreadCount(max(1, int(n)))

    def is_running(self, key: str) -> bool:
        return key in self.jobs

    def running_keys(self, prefix: str = "") -> list[str]:
        return [k for k in self.jobs if k.startswith(prefix)]

    def start(self, key: str, title: str, fn: Callable, *args: Any, pool: str = "default", **kwargs: Any) -> Job | None:
        if key in self.jobs:
            log.info("Job %s already running", key)
            return None
        job = Job(key, title, fn, args, kwargs)
        s = job.signals
        s.event.connect(self._on_event)
        s.progress.connect(self._on_progress)
        s.done.connect(self._on_done)
        s.error.connect(self._on_error)
        self.jobs[key] = job
        self._pool_of[key] = pool
        self.titles[key] = title
        self.pools[pool].start(job)
        self.started.emit(key, title)
        self.changed.emit()
        return job

    def cancel(self, key: str) -> None:
        job = self.jobs.get(key)
        if not job:
            return
        job.cancel_token.cancel()
        pool = self.pools[self._pool_of.get(key, "default")]
        if not job.started and pool.tryTake(job):
            self._on_error(key, CancelledError("Cancelled before start"))

    def cancel_prefix(self, prefix: str) -> None:
        for k in list(self.jobs):
            if k.startswith(prefix):
                self.cancel(k)

    def cancel_all(self) -> None:
        self.cancel_prefix("")

    def wait_all(self, msecs: int = 3000) -> None:
        for p in self.pools.values():
            p.waitForDone(msecs)

    # -- slots (GUI thread) -----------------------------------------------
    def _on_event(self, key: str, payload: object) -> None:
        self.event.emit(key, payload)

    def _on_progress(self, key: str, frac: float, msg: str) -> None:
        self.last_progress[key] = (frac, msg)
        self.progress.emit(key, frac, msg)

    def _finish(self, key: str) -> None:
        self.jobs.pop(key, None)
        self._pool_of.pop(key, None)
        self.last_progress.pop(key, None)
        self.changed.emit()

    def _on_done(self, key: str, result: object) -> None:
        self._finish(key)
        self.finished.emit(key, result)
        self.titles.pop(key, None)

    def _on_error(self, key: str, exc: object) -> None:
        if key not in self.jobs:
            return
        self._finish(key)
        self.failed.emit(key, exc)
        self.titles.pop(key, None)
