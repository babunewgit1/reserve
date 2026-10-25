"""Application controller.

Owns the open project on the GUI thread, starts background jobs, applies
their results, autosaves, computes step progress and drives the optional
automatic pipeline (with review gates).
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal

from ..core import secrets as sec
from ..core.catalog import ImageModelEntry, ModelCatalog, VideoOptionEntry, load_catalog
from ..core.logging_setup import redact
from ..core.project import AlignmentState, AssetVersion, Cue, Project, Scene, TaskInfo, render_dims
from ..core.secrets import SecretStore
from ..core.settings import SettingsStore
from ..services import ffmpeg_tools, project_store, tasks
from ..services.alignment import create_engine
from ..services.glabs_client import RefImage
from ..services.http_base import CancelledError, ServiceError
from ..services.prompt_provider import PROVIDERS, PromptContext, draft_prompts_offline
from ..services.scene_planner import W, assign_text, best_split_time, choose_generation_length, plan
from ..services.srt import validate, write_srt
from ..services.video_renderer import RenderScene, RenderSpec, SubtitleStyleSpec
from ..services.voice_studio_client import VoicePreset
from ..services import youtube_package
from ..workers.jobs import JobManager

log = logging.getLogger("scriptreel.controller")

STEPS = [
    ("setup", "Project setup"),
    ("narration", "Narration & voice"),
    ("subtitles", "Subtitles"),
    ("scenes", "Scenes & prompts"),
    ("images", "Images"),
    ("videos", "Video clips"),
    ("export", "Edit & export"),
    ("youtube", "YouTube package"),
]

VISUAL_FIELDS = (
    "image_prompt", "motion_prompt", "prompt_source", "ref_names", "extra_refs", "image_model", "video_option",
    "video_mode", "image_task", "images", "selected_image", "image_approved", "video_task", "videos",
    "selected_video", "chain_frame", "trim_in", "crop_mode", "focal_x", "focal_y", "gen_length",
)


class ConnState:
    def __init__(self) -> None:
        self.state = "unknown"  # unknown | checking | ok | warn | error
        self.message = "Not checked yet"
        self.hint = ""
        self.details = ""


class Controller(QObject):
    project_loaded = Signal()
    project_closed = Signal()
    changed = Signal(str)  # area
    scene_changed = Signal(str)  # scene id
    task_changed = Signal(str)  # job key / area
    save_state = Signal(str)  # saved | dirty | error
    conn_changed = Signal()
    voices_changed = Signal()
    peaks_changed = Signal()
    batch_done = Signal(str, int, int)
    notify = Signal(str, str)  # level, message
    auto_state = Signal(str)  # running | gate | stopped
    request_page = Signal(str)
    about_to_render = Signal()

    def __init__(self, settings_store: SettingsStore, secrets: SecretStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings_store = settings_store
        self.settings = settings_store.settings
        self.secrets = secrets
        self.catalog: ModelCatalog
        self.catalog_path: Path
        self.catalog_warnings: list[str] = []
        self.reload_catalog()
        self.jobs = JobManager(self, self.settings.max_parallel_tasks)
        self.jobs.event.connect(self._dispatch_event)
        self.jobs.finished.connect(self._dispatch_done)
        self.jobs.failed.connect(self._dispatch_fail)
        self._handlers: dict[str, tuple[Callable | None, Callable | None, Callable | None]] = {}
        self._batches: dict[str, dict] = {}

        self.project: Project | None = None
        self.folder: Path | None = None
        self.dirty = False
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(1200)
        self._autosave.timeout.connect(self.save)

        self.conn: dict[str, ConnState] = {"voice": ConnState(), "glabs": ConnState(), "ffmpeg": ConnState()}
        self.voices: list[VoicePreset] = []
        self.ffmpeg_info: ffmpeg_tools.FFmpegInfo | None = None
        self.peaks: list[float] = []

        self._auto = False
        self._gate: str | None = None
        self._gates_passed: set[str] = set()

    # ================================================================ basics
    def has_project(self) -> bool:
        return self.project is not None and self.folder is not None

    def abs_path(self, rel: str) -> Path:
        assert self.folder is not None
        return project_store.abs_path(self.folder, rel)

    def rel_path(self, path: Path) -> str:
        assert self.folder is not None
        return project_store.rel_path(self.folder, path)

    def save_settings(self) -> None:
        self.settings_store.save()
        self.jobs.set_glabs_parallel(self.settings.max_parallel_tasks)

    def reload_catalog(self) -> None:
        self.catalog, self.catalog_path, self.catalog_warnings = load_catalog()
        for w in self.catalog_warnings:
            log.warning("Catalog: %s", w)
        if hasattr(self, "jobs"):  # not during __init__
            self.changed.emit("catalog")

    def start_job(self, key: str, title: str, fn: Callable, *args: Any, pool: str = "default",
                  on_done: Callable | None = None, on_fail: Callable | None = None,
                  on_event: Callable | None = None, **kwargs: Any) -> bool:
        if self.jobs.is_running(key):
            self.notify.emit("info", f"'{title}' is already running.")
            return False
        self._handlers[key] = (on_event, on_done, on_fail)
        job = self.jobs.start(key, title, fn, *args, pool=pool, **kwargs)
        if job is None:
            self._handlers.pop(key, None)
            return False
        return True

    def _dispatch_event(self, key: str, payload: object) -> None:
        h = self._handlers.get(key)
        if h and h[0]:
            h[0](key, payload)

    def _dispatch_done(self, key: str, result: object) -> None:
        h = self._handlers.pop(key, None)
        if h and h[1]:
            try:
                h[1](key, result)
            except Exception as exc:  # never let a handler bug crash the UI
                log.exception("Handler for %s failed", key)
                self.notify.emit("error", f"Internal error while finishing '{key}': {redact(str(exc))}")
        self._batch_progress(key, True)
        self.task_changed.emit(key)

    def _dispatch_fail(self, key: str, exc: object) -> None:
        h = self._handlers.pop(key, None)
        if not isinstance(exc, CancelledError):
            log.error("%s failed: %s", self.jobs.titles.get(key, key), redact(str(exc)))
        if h and h[2]:
            try:
                h[2](key, exc)
            except Exception:
                log.exception("Failure handler for %s failed", key)
        elif not isinstance(exc, CancelledError):
            self.notify.emit("error", self._err_text(exc))
        self._batch_progress(key, False)
        self.task_changed.emit(key)

    @staticmethod
    def _err_text(exc: object) -> str:
        if isinstance(exc, ServiceError):
            return exc.user_text()
        return redact(f"{exc}") or type(exc).__name__

    def _apply_failure(self, task: TaskInfo, exc: object) -> None:
        task.finished_at = time.time()
        task.fallback = ""
        if isinstance(exc, CancelledError):
            task.state = "cancelled"
            task.error = ""
            task.message = ("Stopped locally. The app has no cancel endpoint, so it may still finish this task "
                            "(and use quota)." if task.task_id else "Cancelled before submission.")
        elif isinstance(exc, ServiceError):
            task.state = "lost" if exc.kind == "task_lost" else "failed"
            task.error = str(exc)
            task.error_code = exc.error_code if exc.error_code is not None else exc.status
            task.hint = exc.hint
            task.fallback = exc.fallback
        else:
            task.state = "failed"
            task.error = redact(str(exc)) or type(exc).__name__
            task.hint = getattr(exc, "stderr_tail", "")[-400:] if hasattr(exc, "stderr_tail") else ""

    @staticmethod
    def _apply_event(task: TaskInfo, payload: dict) -> bool:
        """Update a TaskInfo from a worker event. Returns True if a task id was newly assigned."""
        new_id = False
        if payload.get("state"):
            task.state = payload["state"]
        if payload.get("task_id") and payload["task_id"] != task.task_id:
            task.task_id = payload["task_id"]
            new_id = True
        for k in ("remote_status", "route", "mode"):
            if payload.get(k):
                setattr(task, k, payload[k])
        if payload.get("submitted_at"):
            task.submitted_at = payload["submitted_at"]
        return new_id

    # ================================================================ batches
    def _batch_start(self, kind: str, keys: list[str]) -> None:
        if not keys:
            return
        b = self._batches.setdefault(kind, {"pending": set(), "ok": 0, "failed": 0})
        b["pending"].update(keys)

    def _batch_progress(self, key: str, ok: bool) -> None:
        for kind, b in list(self._batches.items()):
            if key in b["pending"]:
                b["pending"].discard(key)
                b["ok" if ok else "failed"] += 1
                if not b["pending"]:
                    del self._batches[kind]
                    self.batch_done.emit(kind, b["ok"], b["failed"])
                    self._after_batch(kind, b["ok"], b["failed"])

    def batch_running(self, kind: str) -> bool:
        return kind in self._batches

    # ================================================================ projects
    def new_project(self, parent: Path, title: str) -> None:
        self.close_project()
        project, folder = project_store.create_project(parent, title)
        self._set_project(project, folder, [])

    def open_project(self, folder: Path) -> None:
        folder = Path(folder)
        if not project_store.is_project_folder(folder):
            raise project_store.ProjectLoadError(f"{folder} does not contain a project.json")
        self.close_project()
        project, notes = project_store.load_project(folder)
        self._set_project(project, folder, notes)

    def _set_project(self, project: Project, folder: Path, notes: list[str]) -> None:
        self.project = project
        self.folder = Path(folder)
        self.dirty = False
        self._gates_passed.clear()
        self.peaks = []
        self.settings_store.add_recent(self.folder)
        interrupted = self._mark_interrupted()
        self.project_loaded.emit()
        self.save_state.emit("saved")
        for n in notes:
            self.notify.emit("info", n)
        if interrupted:
            self.notify.emit("warning", f"{interrupted} generation task(s) were still running when this project was last "
                                        "closed. Use 'Resume' to keep polling them (tasks survive only while the G-Labs app stays open).")
        self.load_peaks()
        log.info("Opened project '%s'", project.settings.title)

    def _all_tasks(self) -> list[TaskInfo]:
        p = self.project
        if not p:
            return []
        out = [p.voice.task, p.alignment.task, p.render.task, p.youtube.task]
        for s in p.scenes:
            out += [s.image_task, s.video_task, s.prompt_task]
        return out

    def _mark_interrupted(self) -> int:
        n = 0
        resumable = self._resumable_tasks()
        for t in self._all_tasks():
            if t.busy:
                if t.task_id and any(t is r for r in resumable):
                    t.state = "interrupted"
                    t.message = "Was running when the project closed. Resume to keep polling."
                    n += 1
                else:
                    t.state = "idle" if not t.task_id else "interrupted"
                    t.message = "Interrupted."
        return n

    def _resumable_tasks(self) -> list[TaskInfo]:
        p = self.project
        if not p:
            return []
        return [p.voice.task] + [s.image_task for s in p.scenes] + [s.video_task for s in p.scenes]

    def pending_resume_count(self) -> int:
        return sum(1 for t in self._resumable_tasks() if t.state == "interrupted" and t.task_id)

    def close_project(self) -> None:
        if not self.project:
            return
        self.stop_auto()
        self.jobs.cancel_all()
        if self.dirty:
            self.save()
        self.project = None
        self.folder = None
        self.voices_changed.emit()
        self.project_closed.emit()

    def save(self) -> bool:
        if not self.has_project():
            return False
        try:
            project_store.save_project(self.project, self.folder)  # type: ignore[arg-type]
        except OSError as exc:
            self.save_state.emit("error")
            self.notify.emit("error", f"Could not save the project: {exc}")
            return False
        self.dirty = False
        self.save_state.emit("saved")
        return True

    def save_as(self, dest: Path) -> None:
        assert self.project and self.folder
        if self.jobs.running_keys():
            raise RuntimeError("Wait for running tasks to finish (or cancel them) before Save As.")
        new = project_store.save_project_as(self.project, self.folder, dest)
        self.folder = new
        self.settings_store.add_recent(new)
        self.dirty = False
        self.save_state.emit("saved")
        self.project_loaded.emit()

    def mark_dirty(self, area: str = "project") -> None:
        if not self.project:
            return
        self.dirty = True
        self.save_state.emit("dirty")
        self.changed.emit(area)
        if self.settings.autosave:
            self._autosave.start()

    # ================================================================ connections
    def voice_conn(self) -> tasks.VoiceConn:
        s = self.settings
        return tasks.VoiceConn(s.voice_base_url, self.secrets.get(sec.VOICE_KEY), s.request_timeout_s,
                               max(2.0, s.poll_interval_s * 0.75))

    def glabs_conn(self) -> tasks.GLabsConn:
        s = self.settings
        return tasks.GLabsConn(s.glabs_base_url, self.secrets.get(sec.GLABS_KEY), s.request_timeout_s,
                               max(3.0, s.poll_interval_s), s.reference_transfer)

    def tools(self, refresh: bool = False) -> ffmpeg_tools.FFmpegInfo:
        if refresh or self.ffmpeg_info is None:
            self.ffmpeg_info = ffmpeg_tools.inspect(self.settings.ffmpeg_path, self.settings.ffprobe_path)
            self._apply_ffmpeg_state()
        return self.ffmpeg_info

    def _apply_ffmpeg_state(self) -> None:
        info = self.ffmpeg_info
        c = self.conn["ffmpeg"]
        if info is None:
            return
        if info.ok:
            c.state, c.message = "ok", "FFmpeg ready"
            c.details = info.ffmpeg_version.split(" Copyright")[0]
            c.hint = "" if info.has_subtitles_filter else "No libass 'subtitles' filter: burned-in subtitles become a soft track."
            if c.hint:
                c.state = "warn"
        else:
            c.state, c.message, c.hint, c.details = "error", "FFmpeg not ready", " ".join(info.problems), ""
        self.conn_changed.emit()

    def refresh_connections(self, which: tuple[str, ...] = ("voice", "glabs", "ffmpeg")) -> None:
        """Health + key check only. Does NOT refresh the model catalog (no documented endpoint for that)."""
        for w in which:
            self.conn[w].state, self.conn[w].message = "checking", "Checking…"
        self.conn_changed.emit()

        def done(_k, res: dict) -> None:
            for w in ("voice", "glabs"):
                if w not in which:
                    continue
                r = res[w]
                c = self.conn[w]
                c.message, c.hint, c.details = r["message"], r["hint"], r["details"]
                c.state = "ok" if (r["reachable"] and r["key_ok"]) else ("warn" if r["reachable"] else "error")
                if w == "voice" and r.get("voices") is not None:
                    self.voices = r["voices"]
                    self.voices_changed.emit()
            if "ffmpeg" in which:
                self.ffmpeg_info = res["ffmpeg"]
                self._apply_ffmpeg_state()
            self.conn_changed.emit()

        def fail(_k, exc) -> None:
            for w in which:
                self.conn[w].state, self.conn[w].message = "error", self._err_text(exc)
            self.conn_changed.emit()

        self.start_job("conn", "Checking connections", tasks.check_all, self.voice_conn(), self.glabs_conn(),
                       (self.settings.ffmpeg_path, self.settings.ffprobe_path), on_done=done, on_fail=fail)

    def load_voices(self) -> None:
        def done(_k, voices) -> None:
            self.voices = voices
            self.voices_changed.emit()
            self.notify.emit("success", f"Loaded {len(voices)} voice preset(s) from Voice Studio.")
            if not voices:
                self.notify.emit("warning", "Voice Studio has no saved voices. Create one in its Voice Bank first.")

        self.start_job("voices", "Loading voice presets", tasks.list_voices, self.voice_conn(), on_done=done)

    # ================================================================ catalog helpers
    def image_entry_for(self, scene: Scene | None = None) -> ImageModelEntry | None:
        mid = (scene.image_model if scene and scene.image_model else None) or (self.project.settings.image_model if self.project else "")
        e = self.catalog.image(mid)
        return e if e and e.enabled else None

    def video_entry_for(self, scene: Scene | None = None) -> VideoOptionEntry | None:
        vid = (scene.video_option if scene and scene.video_option else None) or (self.project.settings.video_option if self.project else "")
        e = self.catalog.video(vid)
        return e if e and e.enabled else None

    def durations_for(self, entry: VideoOptionEntry) -> list[int]:
        return self.catalog.durations(entry, self.settings.google_ultra)

    def resolutions_for(self, entry: VideoOptionEntry) -> list[str]:
        return self.catalog.resolutions(entry, self.settings.google_ultra)

    def max_scene_len(self) -> float:
        p = self.project
        assert p
        entry = self.video_entry_for()
        mx = p.settings.max_scene
        if entry:
            ds = self.durations_for(entry)
            if ds:
                mx = min(mx, float(max(ds)))
        return mx

    # ================================================================ voice
    @staticmethod
    def script_hash(text: str) -> str:
        return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:16]

    def generate_voice(self, preview: bool = False) -> None:
        p = self.project
        if not p or not self.folder:
            return
        vs = p.voice_settings
        if not vs.preset_id:
            self.notify.emit("error", "Choose a voice preset first (Narration page → Voice).")
            self._auto_after("voice", False)
            return
        script = p.script.strip()
        if not script:
            self.notify.emit("error", "The narration script is empty.")
            self._auto_after("voice", False)
            return
        if preview:
            cut = script[:240]
            dot = max(cut.rfind(". "), cut.rfind("। "), cut.rfind("? "), cut.rfind("! "))
            script = cut[: dot + 1] if dot > 40 else cut
        ext = "." + (vs.output_format if vs.output_format in ("wav", "mp3") else "wav")
        if preview:
            dest_stem = self.folder / "cache" / f"voice_preview_{int(time.time())}"
        else:
            dest_stem = project_store.next_version_path(self.folder, "assets/voice", "narration_take", ext).with_suffix("")
        params = dict(preset_id=vs.preset_id, script=script, language=vs.language, speed=vs.speed,
                      output_format=vs.output_format, num_step=vs.num_step, guidance_scale=vs.guidance_scale)
        key = "voice_preview" if preview else "voice"
        if not preview:
            p.voice.task = TaskInfo(state="queued", route="/api/voice/design", model=vs.preset_id)
            self.mark_dirty("voice")

        def on_event(_k, payload: dict) -> None:
            if preview:
                return
            if self._apply_event(p.voice.task, payload):
                self.save()  # persist task id so it can be resumed
            self.task_changed.emit("voice")

        def done(_k, res: dict) -> None:
            if preview:
                self.preview_audio = res["path"]
                self.task_changed.emit("voice_preview")
                self.notify.emit("success", "Voice preview ready.")
                return
            self._on_voice_done(res, script)

        def fail(_k, exc) -> None:
            if preview:
                self.notify.emit("error", "Voice preview failed: " + self._err_text(exc))
                return
            self._apply_failure(p.voice.task, exc)
            self.mark_dirty("voice")
            if not isinstance(exc, CancelledError):
                self.notify.emit("error", self._err_text(exc))
            self._auto_after("voice", False)

        tools = self.tools()
        self.start_job(key, "Voice preview" if preview else "Generating voiceover", tasks.run_voice, self.voice_conn(),
                       params, dest_stem, float(self.settings.voice_task_timeout_s), tools.ffprobe,
                       pool="voice", on_event=on_event, on_done=done, on_fail=fail)

    preview_audio: Path | None = None

    def resume_voice(self) -> None:
        p = self.project
        if not p or not self.folder or not p.voice.task.task_id:
            return
        vs = p.voice_settings
        ext = "." + vs.output_format
        dest_stem = project_store.next_version_path(self.folder, "assets/voice", "narration_take", ext).with_suffix("")
        params = dict(output_format=vs.output_format, script=p.script)
        task_id = p.voice.task.task_id
        p.voice.task.state = "running"

        def on_event(_k, payload):
            self._apply_event(p.voice.task, payload)
            self.task_changed.emit("voice")

        def fail(_k, exc):
            self._apply_failure(p.voice.task, exc)
            self.mark_dirty("voice")
            self.notify.emit("error", self._err_text(exc))

        self.start_job("voice", "Resuming voiceover", tasks.run_voice, self.voice_conn(), params, dest_stem,
                       float(self.settings.voice_task_timeout_s), self.tools().ffprobe, existing_task_id=task_id,
                       pool="voice", on_event=on_event, on_done=lambda _k, r: self._on_voice_done(r, p.script.strip()),
                       on_fail=fail)

    def _on_voice_done(self, res: dict, script: str) -> None:
        p = self.project
        assert p and self.folder
        vs = p.voice_settings
        path: Path = res["path"]
        take = AssetVersion(path=self.rel_path(path), task_id=res["task_id"], model=vs.preset_id,
                            prompt=f"{vs.preset_name or vs.preset_id} · {vs.language} · ×{vs.speed:.2f}",
                            duration=res.get("duration") or None)
        p.voice.takes.append(take)
        p.voice.task.state = "completed"
        p.voice.task.finished_at = time.time()
        p.voice.script_hash = self.script_hash(script)
        self.select_take(len(p.voice.takes) - 1, announce=False)
        self.notify.emit("success", f"Voiceover ready ({p.voice.duration:.1f}s). Next: align subtitles.")
        if p.cues:
            self.notify.emit("warning", "A new narration take was generated. Run subtitle alignment again so timings match.")
        self.save()
        self._auto_after("voice", True)

    def select_take(self, index: int, announce: bool = True) -> None:
        p = self.project
        if not p or not self.folder or not (0 <= index < len(p.voice.takes)):
            return
        p.voice.selected_take = index
        take = p.voice.takes[index]
        src = self.abs_path(take.path)
        dur = take.duration or 0.0
        if not dur:
            info = self.tools()
            if info.ffprobe:
                try:
                    dur = ffmpeg_tools.probe(info.ffprobe, src)["duration"]
                    take.duration = dur
                except ffmpeg_tools.FFmpegError:
                    pass
        p.voice.duration = dur
        dst = self.folder / f"narration{src.suffix}"
        try:
            for old in self.folder.glob("narration.*"):
                if old.suffix != src.suffix:
                    old.unlink()
            shutil.copyfile(src, dst)
            p.voice.narration_file = dst.name
        except OSError as exc:
            log.warning("Could not update %s: %s", dst.name, exc)
            p.voice.narration_file = take.path
        self.mark_dirty("voice")
        self.load_peaks()
        if announce:
            self.notify.emit("info", f"Using narration take {index + 1}.")

    def narration_audio(self) -> Path | None:
        p = self.project
        take = p.narration_take() if p else None
        return self.abs_path(take.path) if take else None

    def load_peaks(self) -> None:
        audio = self.narration_audio()
        info = self.ffmpeg_info or self.tools()
        if not audio or not audio.exists() or not info.ffmpeg:
            self.peaks = []
            self.peaks_changed.emit()
            return

        def done(_k, peaks):
            self.peaks = peaks
            self.peaks_changed.emit()

        self.start_job("waveform", "Reading waveform", tasks.run_waveform, info.ffmpeg, audio,
                       on_done=done, on_fail=lambda _k, e: None)

    # ================================================================ alignment
    def alignment_engine(self, engine_id: str | None = None):
        info = self.tools()
        return create_engine(engine_id or self.settings.alignment_engine, settings=self.settings,
                             ffmpeg=info.ffmpeg, ffprobe=info.ffprobe)

    def run_alignment(self, method: str = "script", engine_id: str | None = None) -> None:
        p = self.project
        if not p:
            return
        take = p.narration_take()
        if not take:
            self.notify.emit("error", "Generate (or choose) a narration take first.")
            self._auto_after("align", False)
            return
        engine = self.alignment_engine(engine_id)
        ok, why = engine.available()
        if not ok:
            self.notify.emit("error", f"{engine.label}: {why}")
            self._auto_after("align", False)
            return
        if p.voice.script_hash and p.voice.script_hash != self.script_hash(p.script):
            self.notify.emit("warning", "The script was edited after this narration was generated. Subtitles follow the "
                                        "current script text; regenerate the voiceover if the wording changed.")
        p.alignment.task = TaskInfo(state="running", model=engine.id)
        self.task_changed.emit("align")

        def done(_k, res) -> None:
            r = res["result"]
            p.alignment = AlignmentState(
                engine=r.engine, model=r.model, method=r.method, precision_note=r.precision_note,
                match_ratio=r.match_ratio, created_at=time.time(), audio_take=take.path, reviewed=False,
                words=[(round(w.start, 3), round(w.end, 3), w.text) for w in r.words],
                task=TaskInfo(state="completed", model=r.engine, finished_at=time.time()),
            )
            p.cues = [Cue(start=a, end=b, text=t) for a, b, t in res["cues"]]
            for w in r.warnings:
                self.notify.emit("warning", w)
            self.mark_dirty("subtitles")
            self.save()
            self.notify.emit("success", f"Created {len(p.cues)} subtitle cues. Review them before planning scenes.")
            self._auto_after("align", True)

        def fail(_k, exc) -> None:
            self._apply_failure(p.alignment.task, exc)
            self.task_changed.emit("align")
            if not isinstance(exc, CancelledError):
                self.notify.emit("error", f"Alignment failed: {self._err_text(exc)}")
            self._auto_after("align", False)

        self.start_job("align", "Aligning subtitles", tasks.run_alignment, engine, self.abs_path(take.path), p.script,
                       p.voice_settings.language, method, on_done=done, on_fail=fail)

    def alignment_stale(self) -> bool:
        p = self.project
        take = p.narration_take() if p else None
        return bool(p and p.cues and take and p.alignment.audio_take and p.alignment.audio_take != take.path)

    def set_cues(self, cues: list[Cue]) -> None:
        if self.project:
            self.project.cues = cues
            self.mark_dirty("subtitles")

    def export_srt(self, path: Path | None = None) -> Path | None:
        p = self.project
        if not p or not self.folder or not p.cues:
            return None
        path = path or (self.folder / "subtitles.srt")
        write_srt(path, p.cues)
        return path

    def mark_subtitles_reviewed(self) -> bool:
        p = self.project
        if not p:
            return False
        errors = [i for i in validate(p.cues, p.voice.duration or None) if i.severity == "error"]
        if errors:
            self.notify.emit("error", f"Fix {len(errors)} timing error(s) first (overlaps / negative / inverted times).")
            return False
        p.alignment.reviewed = True
        self.export_srt()
        self.mark_dirty("subtitles")
        self.save()
        return True

    # ================================================================ scenes
    def words(self) -> list[W]:
        p = self.project
        if not p:
            return []
        if p.alignment.words:
            return [W(a, b, t) for a, b, t in p.alignment.words]
        out = []
        for c in p.cues:  # derive approximate word timings from cues
            toks = c.text.split()
            d = (c.end - c.start) / max(1, len(toks))
            out += [W(c.start + i * d, c.start + (i + 1) * d, tok) for i, tok in enumerate(toks)]
        return out

    def plan_scenes(self) -> bool:
        p = self.project
        if not p:
            return False
        dur = p.voice.duration
        if dur <= 0:
            self.notify.emit("error", "Narration duration unknown. Generate the voiceover first.")
            return False
        st = p.settings
        mx = self.max_scene_len()
        planned = plan(self.words(), dur, st.clip_mode, min_s=min(st.min_scene, mx - 0.5), target_s=min(st.target_scene, mx), max_s=mx)
        p.scenes = [Scene(start=s.start, end=s.end, text=s.text) for s in planned]
        self.update_gen_lengths()
        self.mark_dirty("scenes")
        self.save()
        self.notify.emit("success", f"Planned {len(p.scenes)} scenes (max {mx:g}s each for the selected video model).")
        return True

    def update_gen_lengths(self) -> None:
        p = self.project
        if not p:
            return
        for i, s in enumerate(p.scenes):
            info = self.video_plan(i)
            s.gen_length = info["gen_length"]

    def _retext(self, s: Scene) -> None:
        s.text = assign_text(self.words(), s.start, s.end)

    def split_scene(self, scene_id: str, at: float | None = None) -> None:
        p = self.project
        if not p:
            return
        i = p.scene_index(scene_id)
        if i < 0:
            return
        s = p.scenes[i]
        if s.duration < 1.2:
            self.notify.emit("warning", "Scene too short to split.")
            return
        t = at if at is not None else best_split_time(self.words(), s.start, s.end)
        t = min(max(t, s.start + 0.5), s.end - 0.5)
        new = Scene(start=t, end=s.end)
        s.end = t
        self._retext(s)
        self._retext(new)
        p.scenes.insert(i + 1, new)
        self.update_gen_lengths()
        self.mark_dirty("scenes")

    def merge_scene_with_next(self, scene_id: str) -> None:
        p = self.project
        if not p:
            return
        i = p.scene_index(scene_id)
        if i < 0 or i + 1 >= len(p.scenes):
            return
        s, nxt = p.scenes[i], p.scenes[i + 1]
        s.end = nxt.end
        self._retext(s)
        if not s.image_prompt and nxt.image_prompt:
            s.image_prompt, s.motion_prompt = nxt.image_prompt, nxt.motion_prompt
        del p.scenes[i + 1]
        self.update_gen_lengths()
        self.mark_dirty("scenes")

    def delete_scene(self, scene_id: str) -> None:
        """Remove a scene; its time span is absorbed by a neighbour so the timeline stays contiguous."""
        p = self.project
        if not p or len(p.scenes) < 2:
            return
        i = p.scene_index(scene_id)
        if i < 0:
            return
        s = p.scenes.pop(i)
        if i > 0:
            p.scenes[i - 1].end = s.end
            self._retext(p.scenes[i - 1])
        else:
            p.scenes[0].start = s.start
            self._retext(p.scenes[0])
        self.update_gen_lengths()
        self.mark_dirty("scenes")

    def set_boundary(self, index: int, t: float) -> bool:
        """Move the cut between scene index-1 and index."""
        p = self.project
        if not p or not (0 < index < len(p.scenes)):
            return False
        a, b = p.scenes[index - 1], p.scenes[index]
        if not (a.start + 0.5 <= t <= b.end - 0.5):
            return False
        a.end = b.start = round(t, 3)
        self._retext(a)
        self._retext(b)
        self.update_gen_lengths()
        self.mark_dirty("scenes")
        return True

    def move_visual(self, scene_id: str, delta: int) -> None:
        """Reorder clips: swap visuals with a neighbour; narration timing stays fixed."""
        p = self.project
        if not p:
            return
        i = p.scene_index(scene_id)
        j = i + delta
        if i < 0 or not (0 <= j < len(p.scenes)):
            return
        a, b = p.scenes[i], p.scenes[j]
        for f in VISUAL_FIELDS:
            va, vb = getattr(a, f), getattr(b, f)
            setattr(a, f, vb)
            setattr(b, f, va)
        self.update_gen_lengths()
        self.mark_dirty("scenes")

    # ================================================================ prompts
    def prompt_context(self) -> PromptContext:
        p = self.project
        assert p
        st = p.style
        e = self.image_entry_for()
        tags = [r.name for r in st.references if r.name] if e and e.supports_tag_binding else []
        return PromptContext(title=p.settings.title, aspect_ratio=p.settings.aspect_ratio, visual_style=st.visual_style,
                             characters=st.characters, setting=st.setting, palette=st.palette, avoid=st.avoid,
                             ref_tags=tags, script=p.script)

    def provider_params(self, require_key: bool = True) -> dict | None:
        s = self.settings
        if s.llm_provider not in PROVIDERS or s.llm_provider == "none":
            return None
        cls = PROVIDERS[s.llm_provider]
        key = self.secrets.get(sec.llm_key(s.llm_provider))
        if require_key and cls.needs_key and not key:
            return None
        return dict(provider_id=s.llm_provider, api_key=key, model=s.llm_model or cls.default_model,
                    base_url=s.llm_base_url or cls.default_base_url, temperature=s.llm_temperature)

    def llm_ready(self) -> bool:
        return self.provider_params() is not None

    def generate_prompts(self, scene_ids: list[str] | None = None) -> bool:
        p = self.project
        if not p or not p.scenes:
            return False
        params = self.provider_params()
        if params is None:
            self.notify.emit("warning", "No prompt LLM is configured. Use 'Draft from narration' or write prompts manually "
                                        "(Settings → Prompt generation to add a provider).")
            return False
        ids = scene_ids or [s.id for s in p.scenes]
        payload = []
        for i, s in enumerate(p.scenes):
            if s.id in ids:
                payload.append({"index": i + 1, "id": s.id, "duration": s.duration, "text": s.text})
                s.prompt_task = TaskInfo(state="running", model=params["model"])
        index_to_id = {d["index"]: d["id"] for d in payload}
        self.changed.emit("scenes")

        def done(_k, result: dict) -> None:
            n = 0
            for idx, (img, mot) in result.items():
                sc = p.scene(index_to_id.get(idx, ""))
                if sc and (img or mot):
                    sc.image_prompt = img or sc.image_prompt
                    sc.motion_prompt = mot or sc.motion_prompt
                    sc.prompt_source = "llm"
                    sc.prompt_task = TaskInfo(state="completed", finished_at=time.time())
                    n += 1
            missing = 0
            for sid in index_to_id.values():
                sc = p.scene(sid)
                if sc and sc.prompt_task.state == "running":
                    sc.prompt_task = TaskInfo(state="failed", error="The LLM returned no prompt for this scene.")
                    missing += 1
            self.mark_dirty("scenes")
            self.save()
            self.notify.emit("success" if not missing else "warning",
                             f"Wrote prompts for {n} scene(s)." + (f" {missing} scene(s) got no prompt — retry them." if missing else ""))
            self._auto_after("prompts", missing == 0)

        def fail(_k, exc) -> None:
            for sid in index_to_id.values():
                sc = p.scene(sid)
                if sc and sc.prompt_task.state == "running":
                    self._apply_failure(sc.prompt_task, exc)
            self.mark_dirty("scenes")
            if not isinstance(exc, CancelledError):
                self.notify.emit("error", f"Prompt generation failed: {self._err_text(exc)}")
            self._auto_after("prompts", False)

        return self.start_job("prompts", "Writing scene prompts", tasks.run_prompts, params, self.prompt_context(),
                              payload, on_done=done, on_fail=fail)

    def draft_prompts(self, scene_ids: list[str] | None = None, overwrite: bool = False) -> int:
        p = self.project
        if not p:
            return 0
        ctx = self.prompt_context()
        n = 0
        for s in p.scenes:
            if scene_ids and s.id not in scene_ids:
                continue
            if s.image_prompt and not overwrite:
                continue
            s.image_prompt, s.motion_prompt = draft_prompts_offline(ctx, s.text)
            s.prompt_source = "draft"
            n += 1
        self.mark_dirty("scenes")
        return n

    # ================================================================ images
    def refs_for(self, scene: Scene, entry: ImageModelEntry) -> list[RefImage]:
        p = self.project
        assert p
        refs = []
        for r in p.style.references:
            use = r.use_by_default if scene.ref_names is None else (r.name in scene.ref_names)
            if use:
                path = self.abs_path(r.path)
                if path.exists():
                    refs.append(RefImage(path, r.name, r.role))
        for rel in scene.extra_refs:
            path = self.abs_path(rel)
            if path.exists():
                refs.append(RefImage(path, path.stem, "subject"))
        return refs[: entry.max_reference_images] if entry.max_reference_images else []

    def generate_images(self, scene_ids: list[str]) -> int:
        p = self.project
        if not p or not self.folder:
            return 0
        started = []
        for sid in scene_ids:
            s = p.scene(sid)
            if not s:
                continue
            key = f"img:{sid}"
            if self.jobs.is_running(key):
                continue
            n = p.scene_index(sid) + 1
            entry = self.image_entry_for(s)
            if entry is None:
                s.image_task = TaskInfo(state="failed", error="Selected image model is not in the (enabled) catalog.")
                continue
            if not s.image_prompt.strip():
                s.image_task = TaskInfo(state="failed", error="Write an image prompt first.")
                continue
            if p.settings.aspect_ratio not in entry.aspect_ratios:
                s.image_task = TaskInfo(state="failed", error=f"{entry.label} does not support {p.settings.aspect_ratio}.")
                continue
            dest = project_store.next_version_path(self.folder, "assets/images", f"scene_{n:03d}", ".png").with_suffix("")
            upscale = p.settings.image_upscale if p.settings.image_upscale in entry.upscale_options else ""
            if upscale in entry.ultra_upscale and not self.settings.google_ultra:
                upscale = ""
            spec = tasks.ImageTaskSpec(sid, n, entry, s.image_prompt, p.settings.aspect_ratio, self.refs_for(s, entry),
                                       dest, float(self.settings.image_task_timeout_s), upscale)
            s.image_task = TaskInfo(state="queued", model=entry.id, route=entry.route)
            if self.start_job(key, f"Image · scene {n}", tasks.run_image, self.glabs_conn(), spec, pool="glabs",
                              on_event=self._on_scene_event, on_done=self._on_image_done, on_fail=self._on_scene_fail):
                started.append(key)
            self.scene_changed.emit(sid)
        self._batch_start("images", started)
        self.mark_dirty("images")
        if not started:
            self._auto_after("images", self._all_have_images())
        return len(started)

    def resume_images(self) -> int:
        p = self.project
        if not p or not self.folder:
            return 0
        started = []
        for i, s in enumerate(p.scenes):
            t = s.image_task
            if t.state != "interrupted" or not t.task_id:
                continue
            entry = self.image_entry_for(s) or self.catalog.image(t.model)
            if entry is None:
                continue
            dest = project_store.next_version_path(self.folder, "assets/images", f"scene_{i + 1:03d}", ".png").with_suffix("")
            spec = tasks.ImageTaskSpec(s.id, i + 1, entry, s.image_prompt, p.settings.aspect_ratio, [], dest,
                                       float(self.settings.image_task_timeout_s), existing_task_id=t.task_id)
            t.state = "running"
            key = f"img:{s.id}"
            if self.start_job(key, f"Resume image · scene {i + 1}", tasks.run_image, self.glabs_conn(), spec, pool="glabs",
                              on_event=self._on_scene_event, on_done=self._on_image_done, on_fail=self._on_scene_fail):
                started.append(key)
        self._batch_start("images", started)
        return len(started)

    def _scene_from_key(self, key: str) -> Scene | None:
        p = self.project
        return p.scene(key.split(":", 1)[1]) if p and ":" in key else None

    def _on_scene_event(self, key: str, payload: dict) -> None:
        s = self._scene_from_key(key)
        if not s:
            return
        task = s.image_task if key.startswith("img:") else s.video_task
        if self._apply_event(task, payload):
            self.save()
        self.scene_changed.emit(s.id)

    def _on_scene_fail(self, key: str, exc: object) -> None:
        s = self._scene_from_key(key)
        if not s:
            return
        task = s.image_task if key.startswith("img:") else s.video_task
        self._apply_failure(task, exc)
        self.scene_changed.emit(s.id)
        self.mark_dirty("scenes")

    def _on_image_done(self, key: str, res: dict) -> None:
        s = self._scene_from_key(key)
        p = self.project
        if not s or not p:
            return
        s.images.append(AssetVersion(path=self.rel_path(res["path"]), task_id=res["task_id"], model=res["model"],
                                     prompt=res["prompt"]))
        s.selected_image = len(s.images) - 1
        s.image_approved = p.settings.run_mode == "automatic" or not p.settings.require_image_approval
        s.image_task.state = "completed"
        s.image_task.finished_at = time.time()
        s.image_task.error = ""
        self.scene_changed.emit(s.id)
        self.mark_dirty("images")

    def import_image(self, scene_id: str, src: Path) -> None:
        p = self.project
        s = p.scene(scene_id) if p else None
        if not s or not self.folder:
            return
        n = p.scene_index(scene_id) + 1  # type: ignore[union-attr]
        dst = project_store.next_version_path(self.folder, "assets/images", f"scene_{n:03d}", src.suffix.lower() or ".png")
        shutil.copyfile(src, dst)
        s.images.append(AssetVersion(path=self.rel_path(dst), source="uploaded", note=src.name))
        s.selected_image = len(s.images) - 1
        s.image_task = TaskInfo(state="completed", message="Uploaded")
        self.scene_changed.emit(scene_id)
        self.mark_dirty("images")

    def select_image(self, scene_id: str, index: int) -> None:
        s = self.project.scene(scene_id) if self.project else None
        if s and 0 <= index < len(s.images):
            s.selected_image = index
            self.scene_changed.emit(scene_id)
            self.mark_dirty("images")

    def set_image_approved(self, scene_ids: list[str], approved: bool) -> None:
        p = self.project
        if not p:
            return
        for sid in scene_ids:
            s = p.scene(sid)
            if s and s.image_asset():
                s.image_approved = approved
                self.scene_changed.emit(sid)
        self.mark_dirty("images")

    def _all_have_images(self) -> bool:
        p = self.project
        return bool(p and p.scenes and all(s.image_asset() for s in p.scenes))

    # ================================================================ videos
    def video_plan(self, index: int) -> dict:
        p = self.project
        assert p
        s = p.scenes[index]
        entry = self.video_entry_for(s)
        info: dict[str, Any] = {"entry": entry, "problems": [], "mode_key": "", "start": None, "end": None,
                                "gen_length": None, "trim": 0.0, "hold": 0.0, "resolution": "", "chained": False}
        if entry is None:
            info["problems"].append("Video option not in the enabled catalog.")
            return info
        chained = bool(p.settings.chain_frames and index > 0 and entry.chaining_supported)
        img = s.image_asset()
        nxt = p.scenes[index + 1].image_asset() if index + 1 < len(p.scenes) else None
        mode_key, start, end = tasks.resolve_video_mode(entry, s.video_mode or p.settings.video_mode, has_image=bool(img),
                                                        chained=chained, has_next_image=bool(nxt))
        fps = p.render.fps or 30
        need = s.duration + (1.0 / fps if start == "chain" else 0.0) + s.trim_in
        gen, trim, hold = choose_generation_length(need, self.durations_for(entry), entry.default_duration)
        res = p.settings.video_resolution if p.settings.video_resolution in self.resolutions_for(entry) else entry.default_resolution
        if p.settings.aspect_ratio not in entry.aspect_ratios:
            info["problems"].append(f"{entry.label} does not support {p.settings.aspect_ratio}.")
        if entry.requires_ultra and not self.settings.google_ultra:
            info["problems"].append(f"{entry.label} requires ULTRA accounts (enable in Settings if you have them).")
        if mode_key not in entry.modes:
            info["problems"].append(f"Mode '{mode_key}' is not documented for {entry.label}.")
        if mode_key in ("start", "start_end") and start is None:
            info["problems"].append("Needs a start image — generate/upload the scene image first.")
        if mode_key == "start_end" and end is None:
            info["problems"].append("Start+end mode needs an end frame (next scene image or chaining).")
        info.update(mode_key=mode_key, start=start, end=end, gen_length=gen, trim=trim, hold=hold, resolution=res, chained=start == "chain")
        return info

    def generate_videos(self, scene_ids: list[str]) -> int:
        p = self.project
        if not p or not self.folder:
            return 0
        info = self.tools()
        order = [i for i, s in enumerate(p.scenes) if s.id in scene_ids]
        specs: list[tasks.VideoTaskSpec] = []
        for i in order:
            s = p.scenes[i]
            if self.jobs.is_running(f"vid:{s.id}") or (p.settings.chain_frames and self.jobs.is_running("vid:chain")):
                continue
            plan_ = self.video_plan(i)
            entry = plan_["entry"]
            if entry is None:
                s.video_task = TaskInfo(state="failed", error="Video option not available in the catalog.")
                continue
            if not s.motion_prompt.strip():
                s.video_task = TaskInfo(state="failed", error="Write a motion prompt first.")
                continue
            img = s.image_asset()
            nxt = p.scenes[i + 1].image_asset() if i + 1 < len(p.scenes) else None
            prev_clip = p.scenes[i - 1].video_asset() if i > 0 else None
            dest = project_store.next_version_path(self.folder, "assets/videos", f"scene_{i + 1:03d}", ".mp4").with_suffix("")
            spec = tasks.VideoTaskSpec(
                scene_id=s.id, scene_no=i + 1, entry=entry, prompt=s.motion_prompt, aspect=p.settings.aspect_ratio,
                mode_key=plan_["mode_key"], start_source=plan_["start"], end_source=plan_["end"],
                image=self.abs_path(img.path) if img else None, next_image=self.abs_path(nxt.path) if nxt else None,
                duration=plan_["gen_length"], resolution=plan_["resolution"], dest_stem=dest,
                frames_dir=self.folder / "assets" / "frames", timeout_s=float(self.settings.video_task_timeout_s),
                prev_clip=self.abs_path(prev_clip.path) if prev_clip else None,
                chain_from_batch=(i - 1) in order,
            )
            s.video_task = TaskInfo(state="queued", model=entry.id, route=entry.route, mode=plan_["mode_key"])
            s.gen_length = plan_["gen_length"]
            specs.append(spec)
            self.scene_changed.emit(s.id)
        if not specs:
            self.mark_dirty("videos")
            self._auto_after("videos", self._all_have_clips())
            return 0
        if p.settings.chain_frames and any(sp.start_source == "chain" for sp in specs):
            if not info.ffmpeg:
                self.notify.emit("error", "Chaining needs FFmpeg to extract last frames. Configure it in Settings.")
                for sp in specs:
                    p.scene(sp.scene_id).video_task.state = "idle"  # type: ignore[union-attr]
                return 0
            ok = self.start_job("vid:chain", f"Chained clips ({len(specs)})", tasks.run_video_chain, self.glabs_conn(),
                                specs, info.ffmpeg, info.ffprobe, pool="glabs", on_event=self._on_chain_event,
                                on_done=self._on_chain_done, on_fail=self._on_chain_fail)
            if ok:
                self._chain_ids = [sp.scene_id for sp in specs]
                self._batch_start("videos", ["vid:chain"])
            self.mark_dirty("videos")
            return len(specs) if ok else 0
        started = []
        for sp in specs:
            key = f"vid:{sp.scene_id}"
            if self.start_job(key, f"Clip · scene {sp.scene_no}", tasks.run_video, self.glabs_conn(), sp, info.ffprobe,
                              pool="glabs", on_event=self._on_scene_event, on_done=self._on_video_done,
                              on_fail=self._on_scene_fail):
                started.append(key)
        self._batch_start("videos", started)
        self.mark_dirty("videos")
        return len(started)

    _chain_ids: list[str] = []

    def resume_videos(self) -> int:
        p = self.project
        if not p or not self.folder:
            return 0
        info = self.tools()
        started = []
        for i, s in enumerate(p.scenes):
            t = s.video_task
            if t.state != "interrupted" or not t.task_id:
                continue
            entry = self.video_entry_for(s) or self.catalog.video(t.model)
            if not entry:
                continue
            dest = project_store.next_version_path(self.folder, "assets/videos", f"scene_{i + 1:03d}", ".mp4").with_suffix("")
            spec = tasks.VideoTaskSpec(s.id, i + 1, entry, s.motion_prompt, p.settings.aspect_ratio, t.mode or "text",
                                       None, None, None, None, s.gen_length, "", dest, self.folder / "assets" / "frames",
                                       float(self.settings.video_task_timeout_s), existing_task_id=t.task_id)
            t.state = "running"
            key = f"vid:{s.id}"
            if self.start_job(key, f"Resume clip · scene {i + 1}", tasks.run_video, self.glabs_conn(), spec, info.ffprobe,
                              pool="glabs", on_event=self._on_scene_event, on_done=self._on_video_done,
                              on_fail=self._on_scene_fail):
                started.append(key)
        self._batch_start("videos", started)
        return len(started)

    def resume_all(self) -> int:
        n = 0
        p = self.project
        if p and p.voice.task.state == "interrupted" and p.voice.task.task_id:
            self.resume_voice()
            n += 1
        n += self.resume_images() + self.resume_videos()
        if n:
            self.notify.emit("info", f"Resumed polling {n} task(s).")
        return n

    def _apply_video_result(self, s: Scene, res: dict) -> None:
        s.videos.append(AssetVersion(path=self.rel_path(res["path"]), task_id=res["task_id"], model=res["model"],
                                     mode=res["mode"], prompt=res["prompt"], chained=bool(res.get("chained")),
                                     duration=res.get("duration")))
        s.selected_video = len(s.videos) - 1
        if res.get("chain_frame"):
            s.chain_frame = self.rel_path(res["chain_frame"])
        s.video_task.state = "completed"
        s.video_task.finished_at = time.time()
        s.video_task.error = ""
        self.scene_changed.emit(s.id)
        p = self.project
        if p and p.settings.chain_frames:
            i = p.scene_index(s.id)
            if i + 1 < len(p.scenes):
                nxt = p.scenes[i + 1]
                va = nxt.video_asset()
                if va and va.chained and nxt.id not in self._chain_ids:
                    self.notify.emit("warning", f"Scene {i + 2} was chained from the previous clip of scene {i + 1}. "
                                                "Regenerate it to keep the transition seamless.")

    def _on_video_done(self, key: str, res: dict) -> None:
        s = self._scene_from_key(key)
        if s:
            self._apply_video_result(s, res)
            self.mark_dirty("videos")

    def _on_chain_event(self, _key: str, payload: dict) -> None:
        p = self.project
        s = p.scene(payload.get("scene_id", "")) if p else None
        if not s:
            return
        typ = payload.get("type")
        if typ == "scene_state":
            if self._apply_event(s.video_task, payload):
                self.save()
        elif typ == "scene_result":
            self._apply_video_result(s, payload["result"])
            self.mark_dirty("videos")
        elif typ == "scene_error":
            self._apply_failure(s.video_task, payload["error"])
            self.notify.emit("error", f"Chain stopped at scene {p.scene_index(s.id) + 1}: {self._err_text(payload['error'])}")
        self.scene_changed.emit(s.id)

    def _on_chain_done(self, _key: str, res: dict) -> None:
        p = self.project
        if p:
            for sid in self._chain_ids:
                s = p.scene(sid)
                if s and s.video_task.busy:
                    s.video_task.state = "idle"
                    s.video_task.message = "Not generated: chain stopped earlier."
                    self.scene_changed.emit(sid)
        self._chain_ids = []
        self.mark_dirty("videos")
        if res.get("stopped_at"):
            self._batches.pop("videos", None)
            self._after_batch("videos", res["done"], 1)

    def _on_chain_fail(self, _key: str, exc: object) -> None:
        p = self.project
        if p:
            for sid in self._chain_ids:
                s = p.scene(sid)
                if s and s.video_task.busy:
                    self._apply_failure(s.video_task, exc)
                    self.scene_changed.emit(sid)
        self._chain_ids = []
        self.mark_dirty("videos")

    def import_clip(self, scene_id: str, src: Path) -> None:
        p = self.project
        s = p.scene(scene_id) if p else None
        if not s or not self.folder:
            return
        n = p.scene_index(scene_id) + 1  # type: ignore[union-attr]
        dst = project_store.next_version_path(self.folder, "assets/videos", f"scene_{n:03d}", src.suffix.lower() or ".mp4")
        shutil.copyfile(src, dst)
        dur = None
        info = self.tools()
        if info.ffprobe:
            try:
                dur = ffmpeg_tools.probe(info.ffprobe, dst)["duration"]
            except ffmpeg_tools.FFmpegError:
                pass
        s.videos.append(AssetVersion(path=self.rel_path(dst), source="uploaded", note=src.name, duration=dur))
        s.selected_video = len(s.videos) - 1
        s.video_task = TaskInfo(state="completed", message="Uploaded")
        self.scene_changed.emit(scene_id)
        self.mark_dirty("videos")

    def select_video(self, scene_id: str, index: int) -> None:
        s = self.project.scene(scene_id) if self.project else None
        if s and 0 <= index < len(s.videos):
            s.selected_video = index
            self.scene_changed.emit(scene_id)
            self.mark_dirty("videos")

    def _all_have_clips(self) -> bool:
        p = self.project
        return bool(p and p.scenes and all(s.video_asset() for s in p.scenes))

    # ================================================================ render
    def output_path(self) -> Path:
        p = self.project
        assert p and self.folder
        name = (p.render.output_name or "final_animated_explainer.mp4").strip()
        name = "".join(ch for ch in name if ch not in '<>:"/\\|?*') or "final_animated_explainer.mp4"
        if not name.lower().endswith(".mp4"):
            name += ".mp4"
        return self.folder / "renders" / name

    def build_render_spec(self) -> RenderSpec:
        p = self.project
        assert p and self.folder
        audio = self.narration_audio()
        if audio is None:
            raise RuntimeError("Generate the narration first.")
        w, h = render_dims(p.settings.aspect_ratio, p.render.resolution)
        r = p.render
        scenes = []
        for i, s in enumerate(p.scenes):
            va, ia = s.video_asset(), s.image_asset()
            scenes.append(RenderScene(
                index=i + 1, start=s.start, end=s.end,
                clip=self.abs_path(va.path) if va and self.abs_path(va.path).exists() else None,
                image=self.abs_path(ia.path) if ia and self.abs_path(ia.path).exists() else None,
                drop_first_frame=bool(va and va.chained), trim_in=s.trim_in,
                crop_mode=s.crop_mode or r.crop_mode, focal_x=s.focal_x, focal_y=s.focal_y))
        srt = self.export_srt()
        st = r.subtitle_style
        dur = p.voice.duration or 0.0
        return RenderSpec(
            scenes=scenes, audio=audio, audio_duration=dur, width=w, height=h, fps=int(r.fps),
            out_path=self.output_path(), work_dir=self.folder / "cache" / "_render_work",
            fit_background=r.fit_background, srt=srt, burn_subtitles=p.settings.burn_subtitles,
            soft_subtitles=r.soft_subtitles,
            sub_style=SubtitleStyleSpec(st.font, st.size, st.color, st.outline_color, st.outline, st.bold, st.margin_v, st.box),
            narration_volume=r.narration_volume,
            music=self.abs_path(r.music_path) if r.music_path else None, music_volume=r.music_volume,
            ducking=r.ducking, crf=r.crf, preset=r.preset)

    def render(self) -> bool:
        p = self.project
        if not p or not self.folder:
            return False
        tools = self.tools(refresh=True)
        if not tools.ok:
            self.notify.emit("error", "Cannot render: " + " ".join(tools.problems))
            self._auto_after("render", False)
            return False
        if not p.scenes:
            self.notify.emit("error", "Plan scenes before rendering.")
            self._auto_after("render", False)
            return False
        try:
            spec = self.build_render_spec()
        except Exception as exc:
            self.notify.emit("error", str(exc))
            self._auto_after("render", False)
            return False
        if spec.audio_duration <= 0:
            self.notify.emit("error", "Narration duration is unknown; re-select the narration take.")
            return False
        self.about_to_render.emit()
        p.render.task = TaskInfo(state="running")
        self.task_changed.emit("render")

        def done(_k, report) -> None:
            p.render.task = TaskInfo(state="completed", finished_at=time.time())
            p.render.last_output = self.rel_path(report.out_path)
            p.render.last_render_at = time.time()
            p.render.last_report = report.summary()
            self.mark_dirty("render")
            self.save()
            self.notify.emit("success", f"Final video saved: {report.out_path.name}")
            for w in report.warnings:
                log.warning("Render: %s", w)
            self._auto_after("render", True)

        def fail(_k, exc) -> None:
            self._apply_failure(p.render.task, exc)
            if isinstance(exc, CancelledError):
                p.render.task.message = "Render cancelled."
            self.mark_dirty("render")
            if not isinstance(exc, CancelledError):
                self.notify.emit("error", f"Render failed: {self._err_text(exc)}")
            self._auto_after("render", False)

        return self.start_job("render", "Rendering final video", tasks.run_render, spec, tools, on_done=done, on_fail=fail)

    # ================================================================ youtube
    def generate_youtube(self) -> bool:
        p = self.project
        if not p or not self.folder:
            return False
        segs = [(s.start, s.end, s.text) for s in p.scenes] or [(c.start, c.end, c.text) for c in p.cues]
        chapters = youtube_package.build_chapters(segs)
        p.youtube.task = TaskInfo(state="running")
        self.task_changed.emit("yt")

        def done(_k, res) -> None:
            data, warning = res
            p.youtube.data = data
            md, js = youtube_package.export(self.folder, data, p.settings.title)  # type: ignore[arg-type]
            p.youtube.md_path, p.youtube.json_path = self.rel_path(md), self.rel_path(js)
            p.youtube.task = TaskInfo(state="completed", finished_at=time.time(), message=warning)
            self.mark_dirty("youtube")
            self.save()
            self.notify.emit("warning" if warning else "success", warning or "YouTube package exported (youtube_metadata.md/.json).")
            self._auto_after("youtube", True)

        def fail(_k, exc) -> None:
            self._apply_failure(p.youtube.task, exc)
            self.mark_dirty("youtube")
            self.notify.emit("warning", f"YouTube metadata failed (video unaffected): {self._err_text(exc)}")
            self._auto_after("youtube", True)  # never blocks the pipeline

        return self.start_job("yt", "YouTube metadata", tasks.run_youtube, self.provider_params(), p.settings.title,
                              p.script, chapters, on_done=done, on_fail=fail)

    def save_youtube_edits(self) -> None:
        p = self.project
        if not p or not self.folder or not p.youtube.data:
            return
        md, js = youtube_package.export(self.folder, p.youtube.data, p.settings.title)
        p.youtube.md_path, p.youtube.json_path = self.rel_path(md), self.rel_path(js)
        self.mark_dirty("youtube")

    def generate_thumbnail(self) -> bool:
        """Thumbnail image from the package's prompt through the documented G-Labs image endpoint (16:9)."""
        p = self.project
        if not p or not self.folder:
            return False
        prompt = (p.youtube.data or {}).get("thumbnail_prompt", "").strip()
        entry = self.image_entry_for()
        if not prompt or entry is None:
            self.notify.emit("warning", "Generate the YouTube package (with a thumbnail prompt) and choose an image model first.")
            return False
        aspect = "16:9" if "16:9" in entry.aspect_ratios else entry.aspect_ratios[0]
        dest = project_store.next_version_path(self.folder, "renders", "thumbnail", ".png").with_suffix("")
        spec = tasks.ImageTaskSpec("thumbnail", 0, entry, prompt, aspect, [], dest, float(self.settings.image_task_timeout_s))

        def done(_k, res) -> None:
            p.youtube.thumbnail = self.rel_path(res["path"])
            self.mark_dirty("youtube")
            self.notify.emit("success", "Thumbnail image saved in renders/.")

        def fail(_k, exc) -> None:
            if not isinstance(exc, CancelledError):
                self.notify.emit("warning", f"Thumbnail generation failed: {self._err_text(exc)}")

        return self.start_job("thumb", "Thumbnail image", tasks.run_image, self.glabs_conn(), spec, pool="glabs",
                              on_done=done, on_fail=fail)

    # ================================================================ progress
    def step_states(self) -> dict[str, str]:
        p = self.project
        if not p:
            return {k: "todo" for k, _ in STEPS}
        st: dict[str, str] = {}
        vs = p.voice_settings
        st["setup"] = "done" if (p.settings.title and p.script.strip() and vs.preset_id and self.image_entry_for()
                                 and self.video_entry_for()) else ("partial" if p.script.strip() else "todo")
        if self.jobs.is_running("voice"):
            st["narration"] = "running"
        elif p.narration_take():
            st["narration"] = "done"
        elif p.voice.task.state in ("failed", "lost"):
            st["narration"] = "error"
        else:
            st["narration"] = "todo"
        if self.jobs.is_running("align"):
            st["subtitles"] = "running"
        elif p.cues and p.alignment.reviewed and not self.alignment_stale():
            st["subtitles"] = "done"
        elif p.cues:
            st["subtitles"] = "partial"
        else:
            st["subtitles"] = "error" if p.alignment.task.state == "failed" else "todo"
        if self.jobs.is_running("prompts"):
            st["scenes"] = "running"
        elif p.scenes and all(s.image_prompt.strip() and s.motion_prompt.strip() for s in p.scenes):
            st["scenes"] = "done"
        else:
            st["scenes"] = "partial" if p.scenes else "todo"

        def gen_state(kind: str) -> str:
            if not p.scenes:
                return "todo"
            if self.jobs.running_keys("img:" if kind == "images" else "vid:"):
                return "running"
            if kind == "images":
                have = [s for s in p.scenes if s.image_asset()]
                need_ok = p.settings.require_image_approval and p.settings.run_mode == "manual"
                done = len(have) == len(p.scenes) and (not need_ok or all(s.image_approved for s in p.scenes))
                failed = any(s.image_task.state in ("failed", "lost") for s in p.scenes)
            else:
                have = [s for s in p.scenes if s.video_asset()]
                done = len(have) == len(p.scenes)
                failed = any(s.video_task.state in ("failed", "lost") for s in p.scenes)
            if done:
                return "done"
            if failed:
                return "error"
            return "partial" if have else "todo"

        st["images"] = gen_state("images")
        st["videos"] = gen_state("videos")
        if self.jobs.is_running("render"):
            st["export"] = "running"
        elif p.render.last_output and self.abs_path(p.render.last_output).exists():
            st["export"] = "done"
        else:
            st["export"] = "error" if p.render.task.state == "failed" else "todo"
        if not p.settings.youtube_metadata:
            st["youtube"] = "skipped"
        elif self.jobs.is_running("yt"):
            st["youtube"] = "running"
        else:
            st["youtube"] = "done" if p.youtube.data else "todo"
        return st

    def overall_progress(self) -> float:
        states = [v for v in self.step_states().values() if v != "skipped"]
        if not states:
            return 0.0
        score = sum(1.0 if v == "done" else 0.5 if v in ("partial", "running") else 0.0 for v in states)
        return score / len(states)

    # ================================================================ automatic pipeline
    def auto_running(self) -> bool:
        return self._auto

    def run_auto(self) -> None:
        if not self.project:
            return
        if self._gate:
            self._gates_passed.add(self._gate)
            self._gate = None
        self._auto = True
        self.auto_state.emit("running")
        self._auto_step()

    def stop_auto(self, reason: str = "") -> None:
        if self._auto and reason:
            self.notify.emit("info", reason)
        self._auto = False
        self.auto_state.emit("stopped")

    def _gate_at(self, step: str, message: str) -> None:
        self._auto = False
        self._gate = step
        self.auto_state.emit("gate")
        self.request_page.emit(step)
        self.notify.emit("info", message)

    def _auto_after(self, kind: str, ok: bool) -> None:
        if not self._auto:
            return
        if ok:
            QTimer.singleShot(250, self._auto_step)
        else:
            self.stop_auto(f"Automatic run paused: the '{kind}' step needs attention.")

    def _after_batch(self, kind: str, ok: int, failed: int) -> None:
        if failed:
            self.notify.emit("warning", f"{kind.capitalize()}: {ok} succeeded, {failed} failed. Failed items keep their error; retry them individually.")
        elif ok:
            self.notify.emit("success", f"{kind.capitalize()}: all {ok} finished.")
        self.save()
        self._auto_after(kind, failed == 0)

    def _auto_step(self) -> None:
        p = self.project
        if not self._auto or not p:
            return
        if self.jobs.running_keys():
            busy = [k for k in self.jobs.running_keys() if k not in ("waveform", "conn")]
            if busy:
                QTimer.singleShot(1500, self._auto_step)
                return
        manual = p.settings.run_mode == "manual"
        if not p.narration_take():
            self.request_page.emit("narration")
            return self.generate_voice()
        if not p.cues or self.alignment_stale():
            self.request_page.emit("subtitles")
            return self.run_alignment()
        if manual and not p.alignment.reviewed and "subtitles" not in self._gates_passed:
            return self._gate_at("subtitles", "Review the subtitles, then press Continue.")
        if not p.alignment.reviewed:
            self.mark_subtitles_reviewed()
        if not p.scenes:
            if not self.plan_scenes():
                return self.stop_auto("Automatic run paused: scene planning failed.")
        missing = [s.id for s in p.scenes if not (s.image_prompt.strip() and s.motion_prompt.strip())]
        if missing:
            self.request_page.emit("scenes")
            if self.llm_ready():
                if not self.generate_prompts(missing):
                    self.stop_auto("Automatic run paused: could not start prompt generation.")
                return
            n = self.draft_prompts(missing)
            self.notify.emit("info", f"No LLM configured: drafted {n} prompt(s) from the narration.")
        if p.settings.review_prompts and "scenes" not in self._gates_passed:
            return self._gate_at("scenes", "Review the scene prompts, then press Continue.")
        need_img = [s.id for s in p.scenes if not s.image_asset()]
        if need_img:
            self.request_page.emit("images")
            if self.generate_images(need_img) == 0 and not self._all_have_images():
                self.stop_auto("Automatic run paused: images could not be started (see scene errors).")
            return
        if manual and p.settings.require_image_approval and not all(s.image_approved for s in p.scenes) \
                and "images" not in self._gates_passed:
            return self._gate_at("images", "Approve the images, then press Continue to generate clips.")
        need_vid = [s.id for s in p.scenes if not s.video_asset()]
        if need_vid:
            self.request_page.emit("videos")
            if self.generate_videos(need_vid) == 0 and not self._all_have_clips():
                self.stop_auto("Automatic run paused: clips could not be started (see scene errors).")
            return
        if not (p.render.last_output and self.abs_path(p.render.last_output).exists()):
            self.request_page.emit("export")
            if not self.render():
                self.stop_auto()
            return
        if p.settings.youtube_metadata and not p.youtube.data:
            self.generate_youtube()
            return
        self.stop_auto("Automatic run complete. Your video is in the renders folder.")
