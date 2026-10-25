"""Main window: navigation rail, project header, page stack, activity panel and toasts."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QProgressBar, QPushButton, QSplitter,
    QStackedWidget, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__
from ..app.controller import STEPS
from ..core.i18n import t
from .activity import ActivityPanel, ToastHost
from .icons import icon, logo_pixmap
from .pages.export import ExportPage
from .pages.images import ImagesPage
from .pages.narration import NarrationPage
from .pages.scenes import ScenesPage
from .pages.settings import SettingsPage
from .pages.setup import SetupPage
from .pages.subtitles import SubtitlesPage
from .pages.videos import VideosPage
from .pages.welcome import WelcomePage
from .pages.youtube import YouTubePage
from .theme import C
from .widgets import Badge, Dot, STEP_TONES, button, confirm, label, show_error

log = logging.getLogger("scriptreel.ui")

STEP_ICONS = {"welcome": "home", "settings": "sliders", "setup": "clipboard", "narration": "mic", "subtitles": "captions",
              "scenes": "scenes", "images": "image", "videos": "video", "export": "scissors", "youtube": "youtube"}
STATE_TEXT = {"done": "Done", "partial": "In progress", "running": "Running", "error": "Needs attention", "todo": "To do",
              "skipped": "Off"}


class RailButton(QPushButton):
    def __init__(self, key: str, text: str, number: int | None = None) -> None:
        super().__init__()
        self.key = key
        self.setObjectName("RailButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIcon(icon(STEP_ICONS.get(key, "info"), "#B3BCD8", 17))
        self.setIconSize(QSize(17, 17))
        prefix = f"{number}  " if number else ""
        self.setText(f"  {prefix}{t(text)}".replace("&", "&&"))
        self.setMinimumHeight(38)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 14, 0)
        lay.addStretch(1)
        self.dot = Dot("neutral", 8)
        self.dot.setVisible(number is not None)
        lay.addWidget(self.dot)

    def set_state(self, state: str) -> None:
        tone = STEP_TONES.get(state, "neutral")
        self.dot.set(tone if state != "todo" else "neutral")
        self.dot.setStyleSheet(self.dot.styleSheet() + ("" if state != "todo" else "background:#3A4670;"))
        self.setToolTip(t(STATE_TEXT.get(state, state)))


class MainWindow(QMainWindow):
    def __init__(self, ctrl) -> None:
        super().__init__()
        self.ctrl = ctrl
        self.setWindowTitle(APP_NAME)
        from PySide6.QtGui import QIcon
        self.setWindowIcon(QIcon(logo_pixmap(64)))
        self.resize(1440, 900)
        self.setMinimumSize(1180, 720)

        central = QWidget()
        central.setObjectName("Central")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_rail())

        main = QWidget()
        mv = QVBoxLayout(main)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(0)
        mv.addWidget(self._build_header())
        self.split = QSplitter(Qt.Orientation.Vertical)
        self.split.setChildrenCollapsible(False)
        self.stack = QStackedWidget()
        self.split.addWidget(self.stack)
        self.activity = ActivityPanel(ctrl)
        self.activity.setMinimumHeight(44)
        self.split.addWidget(self.activity)
        self.split.setStretchFactor(0, 1)
        self.split.setSizes([740, 140])
        mv.addWidget(self.split, 1)
        root.addWidget(main, 1)
        self.toasts = ToastHost(self.stack)
        self.stack.installEventFilter(self)

        self.pages: dict[str, QWidget] = {
            "welcome": WelcomePage(ctrl), "settings": SettingsPage(ctrl), "setup": SetupPage(ctrl),
            "narration": NarrationPage(ctrl), "subtitles": SubtitlesPage(ctrl), "scenes": ScenesPage(ctrl),
            "images": ImagesPage(ctrl), "videos": VideosPage(ctrl), "export": ExportPage(ctrl), "youtube": YouTubePage(ctrl),
        }
        for key, page in self.pages.items():
            page.setObjectName(f"page_{key}")
            self.stack.addWidget(page)
        if not ctrl.settings.show_activity:
            self.activity.toggle()

        ctrl.project_loaded.connect(self._project_changed)
        ctrl.project_closed.connect(self._project_changed)
        ctrl.save_state.connect(self._save_state)
        ctrl.notify.connect(self.toasts.show)
        ctrl.request_page.connect(self.go)
        ctrl.auto_state.connect(self._auto_state)
        ctrl.conn_changed.connect(self._conn)
        ctrl.changed.connect(lambda _a: self._schedule_steps())
        ctrl.scene_changed.connect(lambda _s: self._schedule_steps())
        ctrl.task_changed.connect(lambda _k: self._schedule_steps())
        ctrl.jobs.changed.connect(self._schedule_steps)
        self._steps_timer = QTimer(self)
        self._steps_timer.setSingleShot(True)
        self._steps_timer.setInterval(150)
        self._steps_timer.timeout.connect(self._update_steps)

        QShortcut(QKeySequence.StandardKey.Save, self, activated=self._save)
        QShortcut(QKeySequence.StandardKey.Open, self, activated=self.pages["welcome"].open_folder)
        QShortcut(QKeySequence.StandardKey.New, self, activated=self.pages["welcome"].new_project)

        self._project_changed()
        self._conn()
        self.go("welcome")

    # ------------------------------------------------------------- build
    def _build_rail(self) -> QWidget:
        rail = QFrame()
        rail.setObjectName("Rail")
        rail.setFixedWidth(236)
        v = QVBoxLayout(rail)
        v.setContentsMargins(0, 18, 0, 14)
        v.setSpacing(0)
        brand = QHBoxLayout()
        brand.setContentsMargins(18, 0, 14, 12)
        brand.setSpacing(10)
        lg = QLabel()
        lg.setPixmap(logo_pixmap(34))
        brand.addWidget(lg)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(label("ScriptReel Studio", "RailTitle"))
        col.addWidget(label(t("for G-Labs") + f" · v{__version__}", "RailSub"))
        brand.addLayout(col, 1)
        v.addLayout(brand)
        self.rail_buttons: dict[str, RailButton] = {}
        v.addWidget(label(t("START"), "RailSection"))
        for key, text in (("welcome", "Welcome"), ("settings", "Connections & settings")):
            b = RailButton(key, text)
            b.clicked.connect(lambda _=False, k=key: self.go(k))
            self.rail_buttons[key] = b
            v.addWidget(b)
        v.addWidget(label(t("PRODUCTION"), "RailSection"))
        for n, (key, text) in enumerate(STEPS, start=1):
            b = RailButton(key, text, n)
            b.clicked.connect(lambda _=False, k=key: self.go(k))
            self.rail_buttons[key] = b
            v.addWidget(b)
        v.addStretch(1)
        self.rail_conn = QVBoxLayout()
        self.rail_conn.setContentsMargins(18, 8, 18, 6)
        self.rail_conn.setSpacing(5)
        self.conn_dots = {}
        for key, name in (("voice", "Voice Studio"), ("glabs", "G-Labs Studio"), ("ffmpeg", "FFmpeg")):
            r = QHBoxLayout()
            r.setSpacing(8)
            d = Dot("neutral", 8)
            r.addWidget(d)
            lb = label(t(name), "RailSub")
            r.addWidget(lb, 1)
            self.conn_dots[key] = (d, lb)
            self.rail_conn.addLayout(r)
        v.addLayout(self.rail_conn)
        act = QPushButton("  " + t("Activity panel"))
        act.setObjectName("RailButton")
        act.setIcon(icon("activity", "#B3BCD8", 16))
        act.clicked.connect(self._toggle_activity)
        v.addWidget(act)
        return rail

    def _build_header(self) -> QWidget:
        h = QFrame()
        h.setObjectName("Header")
        h.setFixedHeight(66)
        lay = QHBoxLayout(h)
        lay.setContentsMargins(24, 8, 18, 8)
        lay.setSpacing(14)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.h_name = label("", "ProjectName")
        col.addWidget(self.h_name)
        self.h_meta = label("", "HeaderMeta")
        col.addWidget(self.h_meta)
        lay.addLayout(col, 1)
        self.h_step = Badge("", "primary")
        lay.addWidget(self.h_step)
        pcol = QVBoxLayout()
        pcol.setSpacing(3)
        self.h_progress_l = label("", "HeaderMeta")
        pcol.addWidget(self.h_progress_l)
        self.h_progress = QProgressBar()
        self.h_progress.setRange(0, 100)
        self.h_progress.setFixedWidth(170)
        self.h_progress.setProperty("thin", "true")
        pcol.addWidget(self.h_progress)
        lay.addLayout(pcol)
        self.h_resume = button("Resume", "refresh", "soft", "Keep polling tasks that were running when the project was "
                               "closed (works while the G-Labs apps stay open).", on_click=self._resume)
        lay.addWidget(self.h_resume)
        self.h_auto = button("Run automatically", "bolt", "soft", on_click=self._auto)
        self.h_auto.setObjectName("btnAuto")
        lay.addWidget(self.h_auto)
        self.h_save = button("Save", "save", None, "Ctrl+S", on_click=self._save)
        lay.addWidget(self.h_save)
        self.h_more = button("", "folder", "ghost", "Project menu")
        menu = QMenu(self)
        self.a_open_folder = QAction(t("Open project folder in Explorer"), self, triggered=self._open_folder)
        self.a_save_as = QAction(t("Save project as…"), self, triggered=self._save_as)
        self.a_close = QAction(t("Close project"), self, triggered=self._close_project)
        menu.addAction(self.a_open_folder)
        menu.addAction(self.a_save_as)
        menu.addSeparator()
        menu.addAction(QAction(t("Open project…"), self, triggered=lambda: self.pages["welcome"].open_folder()))
        menu.addAction(QAction(t("New project…"), self, triggered=lambda: self.pages["welcome"].new_project()))
        menu.addSeparator()
        menu.addAction(self.a_close)
        self.h_more.setMenu(menu)
        lay.addWidget(self.h_more)
        return h

    # ------------------------------------------------------------- navigation
    def go(self, key: str) -> None:
        if key not in self.pages:
            return
        if key not in ("welcome", "settings") and not self.ctrl.has_project():
            key = "welcome"
        self.stack.setCurrentWidget(self.pages[key])
        for k, b in self.rail_buttons.items():
            b.setChecked(k == key)
        self._current = key
        self._update_header()

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        if obj is self.stack and ev.type() == QEvent.Type.Resize:
            self.toasts.layout()
        return super().eventFilter(obj, ev)

    # ------------------------------------------------------------- header state
    def _project_changed(self) -> None:
        has = self.ctrl.has_project()
        for key, _ in STEPS:
            self.rail_buttons[key].setEnabled(has)
        for w in (self.h_save, self.h_auto, self.h_more, self.h_progress, self.h_progress_l, self.h_step):
            w.setVisible(has)
        self.a_save_as.setEnabled(has)
        self.a_close.setEnabled(has)
        if not has and getattr(self, "_current", "welcome") not in ("welcome", "settings"):
            self.go("welcome")
        self._save_state("saved")
        self._update_steps()

    def _save_state(self, state: str) -> None:
        if not self.ctrl.has_project():
            self.h_name.setText(t("No project open"))
            self.h_meta.setText(t("Create a new project or open an existing project folder."))
            self.setWindowTitle(APP_NAME)
            return
        p = self.ctrl.project
        self.h_name.setText(p.settings.title)
        txt = {"saved": t("All changes saved") + f" · {time.strftime('%H:%M')}",
               "dirty": t("Unsaved changes") + (" · " + t("autosaving…") if self.ctrl.settings.autosave else ""),
               "error": "⚠ " + t("Save failed — check disk space / permissions")}.get(state, state)
        self.h_meta.setText(f"{txt}  ·  {self.ctrl.folder}")
        self.setWindowTitle(f"{p.settings.title}{' •' if state == 'dirty' else ''} — {APP_NAME}")

    def _schedule_steps(self) -> None:
        self._steps_timer.start()

    def _update_steps(self) -> None:
        states = self.ctrl.step_states()
        for key, st in states.items():
            b = self.rail_buttons.get(key)
            if b:
                b.set_state(st if self.ctrl.has_project() else "todo")
        self._update_header()

    def _update_header(self) -> None:
        if not self.ctrl.has_project():
            self.h_resume.setVisible(False)
            return
        pct = int(round(self.ctrl.overall_progress() * 100))
        self.h_progress.setValue(pct)
        self.h_progress_l.setText(f"{t('Overall progress')} · {pct}%")
        key = getattr(self, "_current", "welcome")
        names = dict(STEPS)
        if key in names:
            n = [k for k, _ in STEPS].index(key) + 1
            self.h_step.set(f"{t('Step')} {n}/{len(STEPS)} · {t(names[key])}", "primary")
        else:
            self.h_step.set(t("Connections & settings") if key == "settings" else t("Welcome"), "neutral")
        n_resume = self.ctrl.pending_resume_count()
        self.h_resume.setVisible(n_resume > 0)
        self.h_resume.setText(f"{t('Resume')} ({n_resume})")
        self._save_state("dirty" if self.ctrl.dirty else "saved")
        self._auto_state("running" if self.ctrl.auto_running() else ("gate" if self.ctrl._gate else "stopped"))

    def _auto_state(self, state: str) -> None:
        b = self.h_auto
        if state == "running":
            b.setText(t("Stop automatic run"))
            b.setProperty("variant", "danger")
            b.setIcon(icon("stop", C["danger"], 16))
            b.setToolTip(t("Stops starting new steps. Running tasks continue until they finish or you stop them."))
        elif state == "gate":
            b.setText(t("Continue"))
            b.setProperty("variant", "primary")
            b.setIcon(icon("right", "#FFFFFF", 16))
            b.setToolTip(t("Review done — continue the automatic run."))
        else:
            b.setText(t("Run automatically"))
            b.setProperty("variant", "soft")
            b.setIcon(icon("bolt", C["primary_p"], 16))
            p = self.ctrl.project
            manual = p is not None and p.settings.run_mode == "manual"
            b.setToolTip(t("Runs every remaining step in order.") + " " +
                         (t("Review mode: pauses for subtitles, prompts and image approval.") if manual else
                          t("Automatic mode: runs unattended and stops only on errors.")))
        b.style().unpolish(b)
        b.style().polish(b)

    def _conn(self) -> None:
        tones = {"ok": "ok", "warn": "warn", "error": "error", "checking": "info", "unknown": "neutral"}
        for key, (d, lb) in self.conn_dots.items():
            c = self.ctrl.conn[key]
            d.set(tones.get(c.state, "neutral"))
            lb.setToolTip(c.message + (f"\n{c.hint}" if c.hint else ""))

    # ------------------------------------------------------------- actions
    def _save(self) -> None:
        if self.ctrl.has_project() and self.ctrl.save():
            self.toasts.show("success", t("Project saved."))

    def _save_as(self) -> None:
        if not self.ctrl.has_project():
            return
        dest = QFileDialog.getExistingDirectory(self, t("Choose an empty folder for the copy"), self.ctrl.settings.output_dir)
        if not dest:
            return
        try:
            self.ctrl.save_as(Path(dest))
            self.toasts.show("success", t("Project copied and opened from the new folder."))
        except Exception as exc:
            show_error(self, "Save As failed", str(exc))

    def _close_project(self) -> None:
        if not self._confirm_running("Close project?"):
            return
        self.ctrl.save()
        self.ctrl.close_project()

    def _open_folder(self) -> None:
        if self.ctrl.folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctrl.folder)))

    def _auto(self) -> None:
        if self.ctrl.auto_running():
            self.ctrl.stop_auto("Automatic run stopped. Running tasks keep going until they finish.")
        else:
            self.ctrl.run_auto()

    def _resume(self) -> None:
        self.ctrl.resume_all()
        self._update_header()

    def _toggle_activity(self) -> None:
        self.activity.toggle()
        self.ctrl.settings.show_activity = self.activity._expanded
        self.ctrl.save_settings()

    def _confirm_running(self, title: str) -> bool:
        busy = [k for k in self.ctrl.jobs.running_keys() if k not in ("waveform", "conn")]
        if not busy:
            return True
        return confirm(self, title, f"{len(busy)} task(s) are still running. Closing stops polling here; G-Labs may still "
                                    "finish them (and use quota). Task IDs are saved — reopen the project and press Resume "
                                    "while the G-Labs apps are still open.", "Close anyway", danger=True)

    def closeEvent(self, e) -> None:  # noqa: N802
        if not self._confirm_running("Quit ScriptReel Studio?"):
            e.ignore()
            return
        try:
            if self.ctrl.has_project():
                self.ctrl.save()
            for page in self.pages.values():
                for attr in ("player", "preview_player"):
                    pl = getattr(page, attr, None)
                    if pl is not None and hasattr(pl, "release"):
                        pl.release()
            self.ctrl.close_project()
            self.ctrl.jobs.cancel_all()
            self.ctrl.jobs.wait_all(1500)
            self.activity.shutdown()
        except Exception:
            log.exception("Error while closing")
        e.accept()
