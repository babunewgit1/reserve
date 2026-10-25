"""Persistent activity panel (redacted log + live tasks) and toast notifications."""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar, QVBoxLayout, QWidget,
)

from ..core.i18n import t
from ..core.logging_setup import RedactingFormatter, redact
from .icons import pixmap
from .theme import C, TONES
from .widgets import button, label, tool_button


class _Emitter(QObject):
    record = Signal(float, str, str, str)  # ts, level, logger, message


class QtLogHandler(logging.Handler):
    """Thread-safe bridge from Python logging to the GUI (messages are redacted)."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.emitter = _Emitter()
        self.setFormatter(RedactingFormatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.emitter.record.emit(record.created, record.levelname, record.name, msg)
        except Exception:
            pass


LEVEL_COLORS = {"DEBUG": C["faint"], "INFO": C["muted"], "WARNING": C["warning"], "ERROR": C["danger"],
                "CRITICAL": C["danger"], "SUCCESS": C["success"], "USER": C["primary_p"]}


class ActivityPanel(QFrame):
    def __init__(self, ctrl, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctrl = ctrl
        self.setObjectName("Activity")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 8, 16, 10)
        lay.setSpacing(6)
        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(pixmap("activity", C["primary"], 15))
        head.addWidget(ic)
        head.addWidget(label(t("Activity"), "CardTitle"))
        self.summary = label("", "Help")
        head.addWidget(self.summary)
        head.addStretch(1)
        self.errors_only = QCheckBox(t("Warnings & errors only").replace("&", "&&"))
        self.errors_only.toggled.connect(self._refilter)
        head.addWidget(self.errors_only)
        head.addWidget(button("Clear", None, "ghost", on_click=self._clear))
        self.collapse = tool_button("down", "Hide activity panel", self.toggle)
        head.addWidget(self.collapse)
        lay.addLayout(head)
        self.content = QWidget()
        cl = QHBoxLayout(self.content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(12)
        tasks_box = QVBoxLayout()
        tasks_box.setSpacing(4)
        tasks_box.addWidget(label(t("Running tasks"), "FieldLabel"))
        self.tasks = QListWidget()
        self.tasks.setFixedWidth(360)
        self.tasks.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        tasks_box.addWidget(self.tasks, 1)
        cl.addLayout(tasks_box)
        log_box = QVBoxLayout()
        log_box.setSpacing(4)
        log_box.addWidget(label(t("Log (secrets are redacted)"), "FieldLabel"))
        self.log = QListWidget()
        self.log.setWordWrap(True)
        self.log.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        f = self.log.font()
        f.setPixelSize(12)
        self.log.setFont(f)
        log_box.addWidget(self.log, 1)
        cl.addLayout(log_box, 1)
        lay.addWidget(self.content, 1)
        self._entries: list[tuple[float, str, str]] = []
        self._task_items: dict[str, tuple[QListWidgetItem, QWidget, QProgressBar, QLabel]] = {}

        self.handler = QtLogHandler()
        self.handler.emitter.record.connect(self._on_record, Qt.ConnectionType.QueuedConnection)
        logging.getLogger("scriptreel").addHandler(self.handler)
        ctrl.notify.connect(self._on_notify)
        ctrl.jobs.started.connect(self._task_started)
        ctrl.jobs.progress.connect(self._task_progress)
        ctrl.jobs.changed.connect(self._sync_tasks)
        self._expanded = True

    # ------------------------------------------------------------- log
    def _add(self, ts: float, level: str, msg: str) -> None:
        self._entries.append((ts, level, msg))
        if len(self._entries) > 2000:
            self._entries = self._entries[-1500:]
            self._refilter()
            return
        self._append_item(ts, level, msg)

    def _append_item(self, ts: float, level: str, msg: str) -> None:
        if self.errors_only.isChecked() and level not in ("WARNING", "ERROR", "CRITICAL"):
            return
        it = QListWidgetItem(f"{time.strftime('%H:%M:%S', time.localtime(ts))}  {level.capitalize():<8} {msg}")
        it.setForeground(QColor(LEVEL_COLORS.get(level, C["muted"])))
        self.log.addItem(it)
        self.log.scrollToBottom()

    def _refilter(self) -> None:
        self.log.clear()
        for e in self._entries[-800:]:
            self._append_item(*e)

    def _clear(self) -> None:
        self._entries.clear()
        self.log.clear()

    def _on_record(self, ts: float, level: str, _name: str, msg: str) -> None:
        self._add(ts, level, msg)

    def _on_notify(self, level: str, msg: str) -> None:
        lvl = {"error": "ERROR", "warning": "WARNING", "success": "SUCCESS"}.get(level, "USER")
        self._add(time.time(), lvl, redact(msg))

    # ------------------------------------------------------------- tasks
    def _task_started(self, key: str, title: str) -> None:
        if key in ("waveform",):
            return
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(2)
        top = QHBoxLayout()
        name = label(title, "FieldLabel")
        top.addWidget(name, 1)
        stop = tool_button("x", "Stop (polling only — remote tasks may still finish)", lambda k=key: self.ctrl.jobs.cancel(k),
                           C["danger"])
        top.addWidget(stop)
        lay.addLayout(top)
        bar = QProgressBar()
        bar.setProperty("thin", "true")
        bar.setRange(0, 1000)
        bar.setValue(0)
        lay.addWidget(bar)
        msg = label(t("Queued…"), "Faint")
        lay.addWidget(msg)
        it = QListWidgetItem()
        it.setSizeHint(w.sizeHint())
        self.tasks.addItem(it)
        self.tasks.setItemWidget(it, w)
        self._task_items[key] = (it, w, bar, msg)
        self._sync_tasks()

    def _task_progress(self, key: str, frac: float, msg: str) -> None:
        e = self._task_items.get(key)
        if e:
            e[2].setValue(int(max(0.0, min(1.0, frac)) * 1000))
            e[3].setText(redact(msg)[:90])

    def _sync_tasks(self) -> None:
        running = set(self.ctrl.jobs.running_keys())
        for key in list(self._task_items):
            if key not in running:
                it = self._task_items.pop(key)[0]
                self.tasks.takeItem(self.tasks.row(it))
        n = len([k for k in running if k != "waveform"])
        self.summary.setText(f"· {n} {t('running')}" if n else f"· {t('idle')}")
        if not n and self.tasks.count() == 0:
            pass

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self.content.setVisible(self._expanded)
        self.collapse.setToolTip(t("Hide activity panel") if self._expanded else t("Show activity panel"))
        from .icons import icon
        self.collapse.setIcon(icon("down" if self._expanded else "up", C["muted"], 16))
        self.setMaximumHeight(16777215 if self._expanded else 44)

    def shutdown(self) -> None:
        logging.getLogger("scriptreel").removeHandler(self.handler)


class Toast(QFrame):
    ICONS = {"success": ("check-circle", "#7BE0B5"), "error": ("alert", "#FF9AA2"), "warning": ("alert", "#FFD27A"),
             "info": ("info", "#B9C6FF")}

    def __init__(self, parent: QWidget, level: str, text: str, on_close) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setFixedWidth(400)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 11, 10, 11)
        lay.setSpacing(10)
        name, col = self.ICONS.get(level, self.ICONS["info"])
        ic = QLabel()
        ic.setPixmap(pixmap(name, col, 18))
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(lb, 1)
        x = tool_button("x", "Dismiss", lambda: on_close(self), "#C9D0E8")
        lay.addWidget(x, 0, Qt.AlignmentFlag.AlignTop)
        self.adjustSize()
        ms = 9000 if level == "error" else 6500 if level == "warning" else 4200
        QTimer.singleShot(ms, lambda: on_close(self))


class ToastHost(QObject):
    def __init__(self, area: QWidget) -> None:
        super().__init__(area)
        self.area = area
        self.toasts: list[Toast] = []

    def show(self, level: str, text: str) -> None:
        if len(self.toasts) >= 4:
            self._close(self.toasts[0])
        tt = Toast(self.area, level, redact(text), self._close)
        tt.show()
        tt.raise_()
        self.toasts.append(tt)
        self.layout()

    def _close(self, toast: Toast) -> None:
        if toast in self.toasts:
            self.toasts.remove(toast)
            toast.hide()
            toast.deleteLater()
            self.layout()

    def layout(self) -> None:
        y = self.area.height() - 18
        for tt in reversed(self.toasts):
            tt.adjustSize()
            y -= tt.height()
            tt.move(self.area.width() - tt.width() - 22, y)
            y -= 10


__all__ = ["ActivityPanel", "ToastHost", "TONES"]
