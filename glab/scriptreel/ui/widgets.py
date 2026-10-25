"""Reusable widgets shared by all pages."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Iterable

from PySide6.QtCore import QObject, QPoint, QRect, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import (
    QBoxLayout, QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget, QWidgetItem,
)

from ..core.i18n import t
from .icons import icon, pixmap
from .theme import C, TONES

STATE_LABELS: dict[str, tuple[str, str]] = {
    "idle": ("Not started", "neutral"),
    "queued": ("Queued", "info"),
    "submitting": ("Submitting", "info"),
    "running": ("Running", "primary"),
    "downloading": ("Downloading", "primary"),
    "completed": ("Completed", "ok"),
    "failed": ("Failed", "error"),
    "lost": ("Lost", "error"),
    "cancelled": ("Stopped", "warn"),
    "interrupted": ("Interrupted", "warn"),
}

STEP_TONES = {"done": "ok", "partial": "warn", "running": "primary", "error": "error", "todo": "neutral", "skipped": "neutral"}


def repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def amp(text: str) -> str:
    """Escape '&' for QAbstractButton/QAction captions (otherwise Qt renders it as a mnemonic underline)."""
    return text.replace("&", "&&")


def button(text: str, icon_name: str | None = None, variant: str | None = None, tip: str = "",
           on_click: Callable | None = None, icon_color: str | None = None) -> QPushButton:
    b = QPushButton(amp(t(text)))
    if variant:
        b.setProperty("variant", variant)
    if icon_name:
        color = icon_color or ("#FFFFFF" if variant == "primary" else C["primary_p"] if variant in ("soft", "hero") else
                               C["danger"] if variant == "danger" else C["muted"])
        b.setIcon(icon(icon_name, color, 16))
    if tip:
        b.setToolTip(t(tip))
    if on_click:
        b.clicked.connect(lambda _=False: on_click())
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def tool_button(icon_name: str, tip: str, on_click: Callable | None = None, color: str = C["muted"]) -> QToolButton:
    b = QToolButton()
    b.setIcon(icon(icon_name, color, 16))
    b.setToolTip(t(tip))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click:
        b.clicked.connect(lambda _=False: on_click())
    return b


def label(text: str = "", name: str | None = None, wrap: bool = False, selectable: bool = False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    if wrap:
        lb.setWordWrap(True)
    if selectable:
        lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lb


def hline() -> QFrame:
    f = QFrame()
    f.setObjectName("Line")
    return f


def hbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0), stretch_at: int | None = None) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for i, w in enumerate(widgets):
        if stretch_at is not None and i == stretch_at:
            lay.addStretch(1)
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QLayout):
            lay.addLayout(w)
        else:
            lay.addWidget(w)
    return lay


def vbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0)) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QLayout):
            lay.addLayout(w)
        else:
            lay.addWidget(w)
    return lay


def labeled(text: str, widget: QWidget | QLayout, help_text: str = "", tip: str = "") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lb = label(t(text), "FieldLabel")
    if tip:
        lb.setToolTip(t(tip))
        lb.setText(t(text) + "  ⓘ")
    lay.addWidget(lb)
    if isinstance(widget, QLayout):
        lay.addLayout(widget)
    else:
        lay.addWidget(widget)
    if help_text:
        h = label(t(help_text), "Help", wrap=True)
        lay.addWidget(h)
        w.help_label = h  # type: ignore[attr-defined]
    w.field_label = lb  # type: ignore[attr-defined]
    return w


class Badge(QLabel):
    def __init__(self, text: str = "", tone: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Badge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.set(text, tone)

    def set(self, text: str, tone: str = "neutral") -> None:
        self.setText(t(text))
        if self.property("tone") != tone:
            self.setProperty("tone", tone if tone in TONES else "neutral")
            repolish(self)

    def set_state(self, state: str, extra: str = "") -> None:
        text, tone = STATE_LABELS.get(state, (state.capitalize() or "—", "neutral"))
        self.set(t(text) + (f" · {extra}" if extra else ""), tone)


class Dot(QLabel):
    """Small coloured status dot."""

    def __init__(self, tone: str = "neutral", size: int = 8) -> None:
        super().__init__()
        self._size = size
        self.setFixedSize(size, size)
        self.set(tone)

    def set(self, tone: str) -> None:
        fg = TONES.get(tone, TONES["neutral"])[0]
        self.setStyleSheet(f"background:{fg}; border-radius:{self._size // 2}px;")


class Card(QFrame):
    def __init__(self, title: str = "", subtitle: str = "", icon_name: str | None = None, accent: bool = False,
                 parent: QWidget | None = None, margins: int = 18) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        if accent:
            self.setProperty("accent", "true")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(margins, margins - 2, margins, margins)
        outer.setSpacing(12)
        self.header = QHBoxLayout()
        self.header.setSpacing(10)
        self.title_label = self.subtitle_label = None
        if title or icon_name:
            if icon_name:
                ic = QLabel()
                ic.setPixmap(pixmap(icon_name, C["primary"], 18))
                ic.setFixedSize(30, 30)
                ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
                ic.setStyleSheet(f"background:{C['primary_soft']}; border-radius:8px;")
                self.header.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
            tbox = QVBoxLayout()
            tbox.setSpacing(1)
            self.title_label = label(t(title), "CardTitle")
            tbox.addWidget(self.title_label)
            if subtitle:
                self.subtitle_label = label(t(subtitle), "CardSubtitle", wrap=True)
                tbox.addWidget(self.subtitle_label)
            self.header.addLayout(tbox, 1)
            outer.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        outer.addLayout(self.body)

    def add_action(self, w: QWidget) -> QWidget:
        self.header.addWidget(w, 0, Qt.AlignmentFlag.AlignTop)
        return w

    def add(self, w: QWidget | QLayout, stretch: int = 0) -> None:
        if isinstance(w, QLayout):
            self.body.addLayout(w, stretch)
        else:
            self.body.addWidget(w, stretch)


class Banner(QFrame):
    ICONS = {"info": "info", "ok": "check-circle", "warn": "alert", "error": "alert", "neutral": "info", "primary": "sparkles"}

    def __init__(self, tone: str = "info", text: str = "", action_text: str = "", on_action: Callable | None = None) -> None:
        super().__init__()
        self.setObjectName("Banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 9, 10, 9)
        lay.setSpacing(10)
        self.ic = QLabel()
        self.ic.setFixedWidth(18)
        lay.addWidget(self.ic, 0, Qt.AlignmentFlag.AlignTop)
        self.text = label("", "BannerText", wrap=True)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setOpenExternalLinks(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        lay.addWidget(self.text, 1)
        self.action = QPushButton()
        self.action.setProperty("variant", "ghost")
        self.action.setVisible(False)
        self._cb: Callable | None = None
        self.action.clicked.connect(lambda: self._cb and self._cb())
        lay.addWidget(self.action, 0, Qt.AlignmentFlag.AlignVCenter)
        self.set(tone, text, action_text, on_action)

    def set(self, tone: str, text: str, action_text: str = "", on_action: Callable | None = None) -> None:
        self.setProperty("tone", tone)
        repolish(self)
        fg = TONES.get(tone, TONES["info"])[0]
        self.ic.setPixmap(pixmap(self.ICONS.get(tone, "info"), fg, 16))
        self.text.setText(text)
        self._cb = on_action
        self.action.setText(t(action_text))
        self.action.setVisible(bool(action_text and on_action))
        self.setVisible(bool(text))


class EmptyState(QWidget):
    def __init__(self, icon_name: str, title: str, text: str, action_text: str = "", on_action: Callable | None = None,
                 icon_name2: str | None = None) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 36, 24, 36)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic = QLabel()
        ic.setPixmap(pixmap(icon_name, C["primary"], 28))
        ic.setFixedSize(60, 60)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setStyleSheet(f"background:{C['primary_soft']}; border-radius:30px;")
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title = label(t(title), "H2")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.title)
        self.text = label(t(text), "Muted", wrap=True)
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text.setMaximumWidth(520)
        lay.addWidget(self.text, 0, Qt.AlignmentFlag.AlignHCenter)
        self.button = None
        if action_text and on_action:
            self.button = button(action_text, icon_name2, "primary", on_click=on_action)
            lay.addSpacing(6)
            lay.addWidget(self.button, 0, Qt.AlignmentFlag.AlignHCenter)


class Segmented(QWidget):
    changed = Signal(str)

    def __init__(self, options: Iterable[tuple[str, str]], value: str | None = None) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        opts = list(options)
        for i, (val, text) in enumerate(opts):
            b = QPushButton(amp(t(text)))
            b.setCheckable(True)
            b.setProperty("seg", "true")
            b.setProperty("segpos", "first" if i == 0 else "last" if i == len(opts) - 1 else "mid")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.group.addButton(b)
            self.buttons[val] = b
            lay.addWidget(b)
            b.clicked.connect(lambda _=False, v=val: self.changed.emit(v))
        lay.addStretch(1)
        if value is not None:
            self.set_value(value)

    def value(self) -> str:
        for v, b in self.buttons.items():
            if b.isChecked():
                return v
        return ""

    def set_value(self, value: str) -> None:
        b = self.buttons.get(value)
        if b:
            b.setChecked(True)


class SecretField(QWidget):
    """API-key editor. Never displays a stored key; the field is write-only."""

    saved = Signal()

    def __init__(self, secrets, name: str, placeholder: str = "Paste API key") -> None:
        super().__init__()
        self.secrets, self.name, self._ph = secrets, name, placeholder
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setClearButtonEnabled(True)
        self.edit.returnPressed.connect(self.save)
        row.addWidget(self.edit, 1)
        self.show_btn = tool_button("eye", "Show what you are typing (stored keys are never shown)")
        self.show_btn.setCheckable(True)
        self.show_btn.toggled.connect(lambda on: self.edit.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        row.addWidget(self.show_btn)
        self.save_btn = button("Save key", "key", "soft", on_click=self.save)
        row.addWidget(self.save_btn)
        self.clear_btn = button("Clear", None, "ghost", tip="Remove this key from the credential store",
                                on_click=self.clear)
        row.addWidget(self.clear_btn)
        lay.addLayout(row)
        self.status = label("", "Help", wrap=True)
        lay.addWidget(self.status)
        self.refresh()

    def refresh(self) -> None:
        has = self.secrets.has(self.name)
        where = self.secrets.backend_name
        self.edit.clear()
        self.edit.setPlaceholderText(t("•••••••• saved — type to replace") if has else t(self._ph))
        self.clear_btn.setEnabled(has)
        if has:
            self.status.setText(t("Stored securely in") + f" {where}.")
        else:
            self.status.setText(t("No key saved.") + (" " + t("Keys are stored in") + f" {where}." if self.secrets.persistent
                                                      else " " + t("No secure store found: the key is kept for this session only.")))

    def save(self) -> None:
        value = self.edit.text().strip()
        if not value:
            return
        self.secrets.set(self.name, value)
        self.edit.clear()
        self.show_btn.setChecked(False)
        self.refresh()
        self.saved.emit()

    def clear(self) -> None:
        self.secrets.delete(self.name)
        self.refresh()
        self.saved.emit()


class PathField(QWidget):
    changed = Signal(str)

    def __init__(self, mode: str = "file", placeholder: str = "", file_filter: str = "All files (*)",
                 caption: str = "Choose") -> None:
        super().__init__()
        self.mode, self.filter, self.caption = mode, file_filter, caption
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(t(placeholder))
        self.edit.editingFinished.connect(lambda: self.changed.emit(self.edit.text().strip()))
        lay.addWidget(self.edit, 1)
        b = button("Browse…", "folder-open", on_click=self.browse)
        lay.addWidget(b)

    def text(self) -> str:
        return self.edit.text().strip()

    def set_text(self, text: str) -> None:
        self.edit.setText(text)

    def browse(self) -> None:
        start = self.text() or str(Path.home())
        if self.mode == "dir":
            p = QFileDialog.getExistingDirectory(self, t(self.caption), start)
        else:
            p, _ = QFileDialog.getOpenFileName(self, t(self.caption), start, self.filter)
        if p:
            self.edit.setText(p)
            self.changed.emit(p)


def confirm(parent: QWidget | None, title: str, text: str, ok: str = "Continue", danger: bool = False) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(t(title))
    box.setText(t(text))
    box.setIcon(QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question)
    ok_btn = box.addButton(t(ok), QMessageBox.ButtonRole.AcceptRole)
    box.addButton(t("Cancel"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(ok_btn)
    box.exec()
    return box.clickedButton() is ok_btn


def show_error(parent: QWidget | None, title: str, text: str) -> None:
    QMessageBox.critical(parent, t(title), text)


def show_info(parent: QWidget | None, title: str, text: str) -> None:
    QMessageBox.information(parent, t(title), text)


# ---------------------------------------------------------------- flow layout
class ResponsiveRow(QWidget):
    """Children side by side when they fit, stacked vertically when the window is narrow (e.g. 1280×800)."""

    def __init__(self, spacing: int = 16, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(spacing)
        self.box.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._ws: list[tuple[QWidget, int]] = []

    def addWidget(self, w: QWidget, stretch: int = 0) -> None:  # noqa: N802
        self._ws.append((w, stretch))
        self.box.addWidget(w, stretch)

    def add_column(self, stretch: int = 1, spacing: int = 16) -> QVBoxLayout:
        """Add an empty vertical column and return its layout."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(spacing)
        self.addWidget(w, stretch)
        return lay

    def _min_w(self, w: QWidget) -> int:
        return max(w.minimumSizeHint().width(), w.minimumWidth())

    def _horizontal_min(self) -> int:
        vis = [w for w, _ in self._ws if not w.isHidden()]
        return sum(self._min_w(w) for w in vis) + self.box.spacing() * max(0, len(vis) - 1)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        widths = [self._min_w(w) for w, _ in self._ws if not w.isHidden()] or [0]
        return QSize(max(widths), self.box.minimumSize().height())

    def _apply(self, width: int) -> None:
        vertical = width < self._horizontal_min()
        want = QBoxLayout.Direction.TopToBottom if vertical else QBoxLayout.Direction.LeftToRight
        if self.box.direction() != want:
            self.box.setDirection(want)
            for w, st in self._ws:
                self.box.setStretchFactor(w, 0 if vertical else st)
            self.updateGeometry()

    def resizeEvent(self, e) -> None:  # noqa: N802
        self._apply(e.size().width())
        super().resizeEvent(e)


class FlowLayout(QLayout):
    """Wraps children left-to-right like text; used for image/clip grids."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 14) -> None:
        super().__init__(parent)
        self._items: list = []
        self._sp = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i: int):  # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i: int):  # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, w: int) -> int:  # noqa: N802
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def clear(self) -> None:
        while self._items:
            it = self._items.pop()
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

    def _do(self, rect: QRect, test: bool) -> int:
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            if it.hasHeightForWidth():
                hint = QSize(hint.width(), max(hint.height(), it.heightForWidth(hint.width())))
            nx = x + hint.width() + self._sp
            if nx - self._sp > rect.right() + 1 and line_h > 0:
                x = rect.x()
                y += line_h + self._sp
                nx = x + hint.width() + self._sp
                line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x = nx
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


# ---------------------------------------------------------------- thumbnails
_thumb_cache: dict[tuple, QPixmap] = {}


def load_thumb(path: Path | str | None, w: int, h: int, crop: bool = False) -> QPixmap | None:
    if not path:
        return None
    p = Path(path)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return None
    key = (str(p), mtime, w, h, crop)
    if key in _thumb_cache:
        return _thumb_cache[key]
    reader = QImageReader(str(p))
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and size.width() > 0:
        scaled = size.scaled(QSize(w * 2, h * 2), Qt.AspectRatioMode.KeepAspectRatioByExpanding if crop
                             else Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(scaled)
    img = reader.read()
    if img.isNull():
        return None
    px = QPixmap.fromImage(img)
    if crop:
        px = px.scaled(w * 2, h * 2, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        x = max(0, (px.width() - w * 2) // 2)
        y = max(0, (px.height() - h * 2) // 2)
        px = px.copy(x, y, w * 2, h * 2)
    else:
        px = px.scaled(w * 2, h * 2, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    px.setDevicePixelRatio(2.0)
    if len(_thumb_cache) > 400:
        _thumb_cache.clear()
    _thumb_cache[key] = px
    return px


class _PosterSignals(QObject):
    ready = Signal(str, str)  # video path, poster path


class _PosterJob(QRunnable):
    def __init__(self, ffmpeg: str, video: Path, out: Path, signals: _PosterSignals) -> None:
        super().__init__()
        self.ffmpeg, self.video, self.out, self.signals = ffmpeg, video, out, signals

    def run(self) -> None:
        import subprocess

        from ..services.ffmpeg_tools import popen_kwargs
        try:
            self.out.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", "0.3", "-i", str(self.video),
                            "-frames:v", "1", "-vf", "scale=480:-2", str(self.out)], timeout=30,
                           capture_output=True, **popen_kwargs())
            if self.out.exists():
                self.signals.ready.emit(str(self.video), str(self.out))
        except Exception:
            pass


class PosterCache(QObject):
    """Extracts a poster frame from clips in the background (ffmpeg) and caches it in the project cache."""

    ready = Signal(str)  # video path

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._sig = _PosterSignals()
        self._sig.ready.connect(self._done)
        self._pending: set[str] = set()
        self._map: dict[str, str] = {}

    def poster(self, ffmpeg: str | None, video: Path, cache_dir: Path) -> Path | None:
        key = str(video)
        try:
            mt = int(video.stat().st_mtime)
        except OSError:
            return None
        out = cache_dir / "posters" / f"{video.stem}_{mt}.jpg"
        if out.exists():
            return out
        if ffmpeg and key not in self._pending:
            self._pending.add(key)
            self._pool.start(_PosterJob(ffmpeg, video, out, self._sig))
        return None

    def _done(self, video: str, _out: str) -> None:
        self._pending.discard(video)
        self.ready.emit(video)


class ThumbLabel(QLabel):
    """Fixed-size rounded preview tile with a placeholder."""

    def __init__(self, w: int, h: int, placeholder_icon: str = "image") -> None:
        super().__init__()
        self._w, self._h, self._ph = w, h, placeholder_icon
        self.setFixedSize(w, h)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"background:{C['surface2']}; border:1px solid {C['border']}; border-radius:8px;")
        self.clear_thumb()

    def resize_tile(self, w: int, h: int) -> None:
        self._w, self._h = w, h
        self.setFixedSize(w, h)

    def clear_thumb(self, text: str = "") -> None:
        if text:
            self.setPixmap(QPixmap())
            self.setText(text)
            self.setStyleSheet(f"background:{C['surface2']}; border:1px solid {C['border']}; border-radius:8px;"
                               f"color:{C['faint']}; font-size:11px;")
        else:
            self.setText("")
            self.setPixmap(pixmap(self._ph, C["border2"], 26))

    def set_path(self, path: Path | str | None, crop: bool = False) -> bool:
        px = load_thumb(path, self._w - 2, self._h - 2, crop)
        if px is None:
            self.clear_thumb()
            return False
        self.setText("")
        self.setPixmap(px)
        return True


# ---------------------------------------------------------------- page base
class Page(QWidget):
    """Scrollable page with a title row. Subclasses implement `refresh()`."""

    title_text = ""
    subtitle_text = ""
    scroll = True

    def __init__(self, ctrl, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctrl = ctrl
        self._stale = True
        self._editing = 0
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QWidget()
        body.setObjectName("PageBody")
        self.layout_ = QVBoxLayout(body)
        self.layout_.setContentsMargins(28, 22, 28, 28)
        self.layout_.setSpacing(16)
        head = QHBoxLayout()
        head.setSpacing(10)
        tb = QVBoxLayout()
        tb.setSpacing(2)
        self.title_label = label(t(self.title_text), "PageTitle")
        tb.addWidget(self.title_label)
        self.subtitle_label = label(t(self.subtitle_text), "PageSubtitle", wrap=True)
        tb.addWidget(self.subtitle_label)
        head.addLayout(tb, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        head.addLayout(self.actions)
        self.layout_.addLayout(head)
        if self.scroll:
            sa = QScrollArea()
            sa.setObjectName("PageScroll")
            sa.setWidgetResizable(True)
            sa.setFrameShape(QFrame.Shape.NoFrame)
            sa.setWidget(body)
            outer.addWidget(sa)
            self.scroll_area = sa
        else:
            outer.addWidget(body)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(60)
        self._refresh_timer.timeout.connect(self._do_refresh)

    def add_action(self, w: QWidget) -> QWidget:
        self.actions.addWidget(w)
        return w

    # -- refresh plumbing
    def mark_stale(self, *_args) -> None:
        if self._editing:
            return
        self._stale = True
        if self.isVisible():
            self._refresh_timer.start()

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        if self._stale:
            self._do_refresh()
        self.on_show()

    def _do_refresh(self) -> None:
        self._stale = False
        try:
            self.refresh()
        except Exception:
            import logging
            logging.getLogger("scriptreel.ui").exception("Refreshing %s failed", type(self).__name__)

    def refresh(self) -> None:  # override
        pass

    def on_show(self) -> None:  # override
        pass

    def edit(self, area: str = "project") -> None:
        """Mark the project dirty after a user edit without re-rendering this page."""
        self._editing += 1
        try:
            self.ctrl.mark_dirty(area)
        finally:
            self._editing -= 1

    @property
    def project(self):
        return self.ctrl.project


def fmt_age(ts: float | None) -> str:
    if not ts:
        return "—"
    d = time.time() - ts
    if d < 60:
        return t("just now")
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if d < 86400:
        return f"{int(d // 3600)} h ago"
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def fmt_dur(sec: float | None) -> str:
    if sec is None:
        return "—"
    sec = max(0.0, float(sec))
    m, s = divmod(sec, 60)
    return f"{int(m)}:{s:04.1f}"


def task_detail(task) -> str:
    """Human summary of a TaskInfo for tooltips / status lines (never contains secrets)."""
    parts = []
    if task.task_id:
        parts.append(f"task {task.task_id}")
    if task.remote_status:
        parts.append(f"remote: {task.remote_status}")
    if task.mode:
        parts.append(f"mode: {task.mode}")
    if task.message:
        parts.append(task.message)
    if task.error:
        parts.append(task.error)
    if task.hint:
        parts.append(task.hint)
    return " · ".join(parts)


class StatusLine(QWidget):
    """Badge + message + optional error/hint display for a TaskInfo."""

    def __init__(self) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.badge = Badge()
        lay.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        self.text = label("", "Help", wrap=True, selectable=True)
        lay.addWidget(self.text, 1)

    def set_task(self, task, progress_msg: str = "") -> None:
        self.badge.set_state(task.state)
        bits = []
        if progress_msg and task.busy:
            bits.append(progress_msg)
        if task.task_id:
            bits.append(f"task_id {task.task_id}")
        if task.remote_status and task.busy:
            bits.append(task.remote_status)
        if task.message and not task.error:
            bits.append(task.message)
        txt = " · ".join(bits)
        if task.error:
            txt = (txt + "\n" if txt else "") + task.error + (f"\n→ {task.hint}" if task.hint else "")
        self.text.setText(txt)
        self.setToolTip(task_detail(task))


def clear_layout(lay: QLayout) -> None:
    while lay.count():
        it = lay.takeAt(0)
        w = it.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif it.layout() is not None:
            clear_layout(it.layout())


__all__ = [
    "Badge", "Banner", "Card", "Dot", "EmptyState", "FlowLayout", "Page", "PathField", "PosterCache", "QWidgetItem",
    "STATE_LABELS", "STEP_TONES", "SecretField", "Segmented", "StatusLine", "ThumbLabel", "button", "clear_layout",
    "confirm", "fmt_age", "fmt_dur", "hbox", "hline", "label", "labeled", "load_thumb", "repolish", "show_error",
    "show_info", "task_detail", "tool_button", "vbox",
]
