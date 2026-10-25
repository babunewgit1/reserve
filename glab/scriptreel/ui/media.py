"""Media widgets: waveform, audio player, video player and crop/safe-zone preview."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QSlider, QToolButton, QVBoxLayout, QWidget

from ..core.i18n import t
from .icons import icon
from .theme import C

try:  # QtMultimedia can be missing in stripped builds; degrade gracefully
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget
    HAS_MM = True
except Exception:  # pragma: no cover
    HAS_MM = False


def fmt_clock(sec: float) -> str:
    sec = max(0.0, sec)
    m, s = divmod(sec, 60)
    return f"{int(m)}:{s:04.1f}"


class Waveform(QWidget):
    seek = Signal(float)

    def __init__(self, height: int = 64) -> None:
        super().__init__()
        self.peaks: list[float] = []
        self.duration = 0.0
        self.playhead = -1.0
        self.regions: list[tuple[float, float]] = []
        self.selected: int = -1
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.empty_text = t("No narration audio yet")

    def set_data(self, peaks: list[float], duration: float) -> None:
        self.peaks, self.duration = peaks or [], max(0.0, duration or 0.0)
        self.update()

    def set_regions(self, regions: list[tuple[float, float]], selected: int = -1) -> None:
        self.regions, self.selected = regions, selected
        self.update()

    def set_playhead(self, t_s: float) -> None:
        self.playhead = t_s
        self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if self.duration > 0:
            self.seek.emit(max(0.0, min(self.duration, e.position().x() / max(1, self.width()) * self.duration)))

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(QRectF(r), 8, 8)
        p.fillPath(path, QColor(C["surface2"]))
        p.setClipPath(path)
        w, h = self.width(), self.height()
        if self.duration > 0:
            for i, (a, b) in enumerate(self.regions):
                x0, x1 = a / self.duration * w, b / self.duration * w
                col = QColor(C["primary_soft"]) if i == self.selected else QColor(0, 0, 0, 0) if i % 2 else QColor("#EEF1F8")
                p.fillRect(QRectF(x0, 0, x1 - x0, h), col)
                p.setPen(QPen(QColor(C["border2"]), 1))
                if i:
                    p.drawLine(QPointF(x0, 0), QPointF(x0, h))
        if not self.peaks:
            p.setPen(QColor(C["faint"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty_text)
        else:
            n = len(self.peaks)
            bar = 3.0
            gap = 1.0
            cols = max(1, int(w / (bar + gap)))
            mid = h / 2
            p.setPen(Qt.PenStyle.NoPen)
            played = self.playhead / self.duration * w if self.duration and self.playhead >= 0 else -1
            for c in range(cols):
                a = int(c / cols * n)
                b = max(a + 1, int((c + 1) / cols * n))
                v = max(self.peaks[a:b]) if b <= n else self.peaks[-1]
                bh = max(2.0, v * (h - 12))
                x = c * (bar + gap)
                p.setBrush(QColor(C["primary"]) if x < played else QColor("#A9B3CC"))
                p.drawRoundedRect(QRectF(x, mid - bh / 2, bar, bh), 1.2, 1.2)
        if self.duration > 0 and self.playhead >= 0:
            x = self.playhead / self.duration * w
            p.setPen(QPen(QColor(C["danger"]), 2))
            p.drawLine(QPointF(x, 0), QPointF(x, h))
        p.end()


class AudioPlayer(QWidget):
    position = Signal(float)

    def __init__(self, wave_height: int = 70) -> None:
        super().__init__()
        self._path: Path | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.wave = Waveform(wave_height)
        lay.addWidget(self.wave)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.play_btn = QToolButton()
        self.play_btn.setIcon(icon("play", C["primary"], 18))
        self.play_btn.setToolTip(t("Play / pause"))
        self.play_btn.clicked.connect(self.toggle)
        row.addWidget(self.play_btn)
        self.time = QLabel("0:00.0 / 0:00.0")
        self.time.setObjectName("Mono")
        row.addWidget(self.time)
        row.addStretch(1)
        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(90)
        self.vol.setFixedWidth(90)
        self.vol.setToolTip(t("Preview volume"))
        row.addWidget(QLabel("🔊"))
        row.addWidget(self.vol)
        lay.addLayout(row)
        self.player = None
        if HAS_MM:
            self.audio = QAudioOutput(self)
            self.audio.setVolume(0.9)
            self.player = QMediaPlayer(self)
            self.player.setAudioOutput(self.audio)
            self.player.positionChanged.connect(self._on_pos)
            self.player.durationChanged.connect(lambda d: self._update_time())
            self.player.playbackStateChanged.connect(self._on_state)
            self.vol.valueChanged.connect(lambda v: self.audio.setVolume(v / 100))
        self.wave.seek.connect(self.seek_to)
        self._enable(False)

    def _enable(self, on: bool) -> None:
        self.play_btn.setEnabled(on and self.player is not None)

    def load(self, path: Path | None, peaks: list[float] | None = None, duration: float = 0.0) -> None:
        if peaks is not None:
            self.wave.set_data(peaks, duration)
        if path == self._path:
            return
        self._path = path
        if self.player is None:
            return
        self.player.stop()
        if path and Path(path).exists():
            self.player.setSource(QUrl.fromLocalFile(str(path)))
            self._enable(True)
        else:
            self.player.setSource(QUrl())
            self._enable(False)
        self._update_time()

    def release(self) -> None:
        """Drop the file handle (Windows locks files that are open in a player)."""
        self._path = None
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl())
        self._enable(False)

    def toggle(self) -> None:
        if not self.player:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def stop(self) -> None:
        if self.player:
            self.player.pause()

    def seek_to(self, sec: float) -> None:
        if self.player and self._path:
            self.player.setPosition(int(sec * 1000))
        self.wave.set_playhead(sec)

    def _on_pos(self, ms: int) -> None:
        self.wave.set_playhead(ms / 1000)
        self._update_time()
        self.position.emit(ms / 1000)

    def _on_state(self, st) -> None:
        playing = st == QMediaPlayer.PlaybackState.PlayingState
        self.play_btn.setIcon(icon("pause" if playing else "play", C["primary"], 18))

    def _update_time(self) -> None:
        if not self.player:
            return
        pos = self.player.position() / 1000
        dur = (self.player.duration() / 1000) or self.wave.duration
        self.time.setText(f"{fmt_clock(pos)} / {fmt_clock(dur)}")


class VideoPlayer(QWidget):
    position = Signal(float)

    def __init__(self, min_h: int = 220) -> None:
        super().__init__()
        self._path: Path | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.player = None
        if HAS_MM:
            self.view = QVideoWidget()
            self.view.setStyleSheet("background:#0B1022; border-radius:10px;")
            self.view.setMinimumHeight(min_h)
            self.audio = QAudioOutput(self)
            self.player = QMediaPlayer(self)
            self.player.setAudioOutput(self.audio)
            self.player.setVideoOutput(self.view)
            self.player.positionChanged.connect(self._on_pos)
            self.player.durationChanged.connect(self._on_dur)
            self.player.playbackStateChanged.connect(self._on_state)
        else:
            self.view = QLabel(t("Video preview needs Qt Multimedia."))
            self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.view.setMinimumHeight(min_h)
        self.placeholder = QLabel(t("No video loaded"))
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet("background:#0B1022; color:#7F8AB0; border-radius:10px;")
        self.placeholder.setMinimumHeight(min_h)
        lay.addWidget(self.placeholder, 1)
        lay.addWidget(self.view, 1)
        self.view.setVisible(False)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.play_btn = QToolButton()
        self.play_btn.setIcon(icon("play", C["primary"], 18))
        self.play_btn.clicked.connect(self.toggle)
        row.addWidget(self.play_btn)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.sliderMoved.connect(lambda v: self.player and self.player.setPosition(v))
        row.addWidget(self.slider, 1)
        self.time = QLabel("0:00.0")
        self.time.setObjectName("Mono")
        row.addWidget(self.time)
        lay.addLayout(row)
        self._enable(False)

    def _enable(self, on: bool) -> None:
        self.play_btn.setEnabled(on)
        self.slider.setEnabled(on)

    def load(self, path: Path | None, autoplay: bool = False) -> None:
        if path == self._path:
            return
        self._path = path
        ok = bool(path and Path(path).exists() and self.player)
        self.view.setVisible(ok)
        self.placeholder.setVisible(not ok)
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl.fromLocalFile(str(path)) if ok else QUrl())
            if ok and autoplay:
                self.player.play()
        self._enable(ok)

    def release(self) -> None:
        self._path = None
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())
        self.view.setVisible(False)
        self.placeholder.setVisible(True)
        self._enable(False)

    def set_placeholder(self, text: str) -> None:
        self.placeholder.setText(text)

    def toggle(self) -> None:
        if not self.player:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def stop(self) -> None:
        if self.player:
            self.player.pause()

    def seek_to(self, sec: float) -> None:
        if self.player and self._path:
            self.player.setPosition(int(sec * 1000))

    def _on_pos(self, ms: int) -> None:
        if not self.slider.isSliderDown():
            self.slider.setValue(ms)
        dur = self.player.duration() / 1000 if self.player else 0
        self.time.setText(f"{fmt_clock(ms / 1000)} / {fmt_clock(dur)}")
        self.position.emit(ms / 1000)

    def _on_dur(self, ms: int) -> None:
        self.slider.setRange(0, ms)

    def _on_state(self, st) -> None:
        playing = st == QMediaPlayer.PlaybackState.PlayingState
        self.play_btn.setIcon(icon("pause" if playing else "play", C["primary"], 18))


class CropPreview(QWidget):
    """WYSIWYG frame preview: output aspect, Fit/Fill, draggable focal point and subtitle safe zones.

    Mirrors the renderer: Fill scales to cover and crops at (focal_x, focal_y); Fit letterboxes over
    a blurred/black background. Subtitle size/margin follow libass defaults (PlayResY 288).
    """

    focal_changed = Signal(float, float)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(260, 180)
        self.px: QPixmap | None = None
        self.aspect = "16:9"
        self.mode = "fill"
        self.background = "blur"
        self.fx = self.fy = 0.5
        self.show_safe = True
        self.subtitle = ""
        self.sub_size = 18
        self.sub_margin = 28
        self.burn = True
        self._drag = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def set_image(self, path: Path | None) -> None:
        self.px = QPixmap(str(path)) if path and Path(path).exists() else None
        if self.px is not None and self.px.isNull():
            self.px = None
        self.update()

    def configure(self, aspect: str, mode: str, background: str, fx: float, fy: float, subtitle: str = "",
                  sub_size: int = 18, sub_margin: int = 28, burn: bool = True) -> None:
        self.aspect, self.mode, self.background = aspect, mode or "fill", background
        self.fx, self.fy = fx, fy
        self.subtitle, self.sub_size, self.sub_margin, self.burn = subtitle, sub_size, sub_margin, burn
        self.setCursor(Qt.CursorShape.OpenHandCursor if self.mode == "fill" else Qt.CursorShape.ArrowCursor)
        self.update()

    def _frame(self) -> QRectF:
        w, h = self.width() - 16, self.height() - 16
        ar = 16 / 9 if self.aspect == "16:9" else 9 / 16
        if w / max(1, h) > ar:
            fh = h
            fw = fh * ar
        else:
            fw = w
            fh = fw / ar
        return QRectF((self.width() - fw) / 2, (self.height() - fh) / 2, fw, fh)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if self.mode == "fill" and self.px is not None:
            self._drag = True
            self._last = e.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if not self._drag or self.px is None:
            return
        fr = self._frame()
        sw, sh = self._cover_size(fr)
        dx, dy = e.position().x() - self._last.x(), e.position().y() - self._last.y()
        self._last = e.position()
        ox, oy = sw - fr.width(), sh - fr.height()
        if ox > 1:
            self.fx = min(1.0, max(0.0, self.fx - dx / ox))
        if oy > 1:
            self.fy = min(1.0, max(0.0, self.fy - dy / oy))
        self.update()

    def mouseReleaseEvent(self, _e) -> None:  # noqa: N802
        if self._drag:
            self._drag = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.focal_changed.emit(round(self.fx, 3), round(self.fy, 3))

    def _cover_size(self, fr: QRectF) -> tuple[float, float]:
        assert self.px is not None
        iw, ih = self.px.width(), self.px.height()
        s = max(fr.width() / iw, fr.height() / ih)
        return iw * s, ih * s

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#0B1022"))
        fr = self._frame()
        p.save()
        p.setClipRect(fr)
        p.fillRect(fr, QColor("#000000"))
        if self.px is not None:
            iw, ih = self.px.width(), self.px.height()
            if self.mode == "fill":
                sw, sh = self._cover_size(fr)
                x = fr.left() - (sw - fr.width()) * self.fx
                y = fr.top() - (sh - fr.height()) * self.fy
                p.drawPixmap(QRectF(x, y, sw, sh), self.px, QRectF(0, 0, iw, ih))
            else:
                if self.background == "blur":
                    sw, sh = self._cover_size(fr)
                    p.setOpacity(0.45)
                    p.drawPixmap(QRectF(fr.center().x() - sw / 2, fr.center().y() - sh / 2, sw, sh), self.px,
                                 QRectF(0, 0, iw, ih))
                    p.setOpacity(1.0)
                    p.fillRect(fr, QColor(10, 14, 30, 90))
                s = min(fr.width() / iw, fr.height() / ih)
                dw, dh = iw * s, ih * s
                p.drawPixmap(QRectF(fr.center().x() - dw / 2, fr.center().y() - dh / 2, dw, dh), self.px,
                             QRectF(0, 0, iw, ih))
        else:
            p.setPen(QColor("#56608A"))
            p.drawText(fr, Qt.AlignmentFlag.AlignCenter, t("No image or clip for this scene yet"))
        if self.show_safe:
            pen = QPen(QColor(255, 255, 255, 110), 1, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(fr.adjusted(fr.width() * 0.05, fr.height() * 0.05, -fr.width() * 0.05, -fr.height() * 0.05))
            sub_h = fr.height() * (self.sub_size * 2.6) / 288
            bottom = fr.bottom() - fr.height() * self.sub_margin / 288
            zone = QRectF(fr.left() + fr.width() * 0.08, bottom - sub_h, fr.width() * 0.84, sub_h)
            p.fillRect(zone, QColor(91, 75, 219, 50))
            p.setPen(QPen(QColor("#B9AEFF"), 1, Qt.PenStyle.DashLine))
            p.drawRect(zone)
            if self.subtitle and self.burn:
                f = QFont(self.font())
                f.setPixelSize(max(8, int(fr.height() * self.sub_size / 288)))
                f.setBold(True)
                p.setFont(f)
                txt = self.subtitle if len(self.subtitle) < 90 else self.subtitle[:88] + "…"
                path = QPainterPath()
                rect = zone.adjusted(4, 0, -4, 0)
                p.setPen(QPen(QColor("#101833"), 3))
                p.drawText(rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom | Qt.TextFlag.TextWordWrap, txt)
                p.setPen(QColor("white"))
                p.drawText(rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom | Qt.TextFlag.TextWordWrap, txt)
                del path
        p.restore()
        p.setPen(QPen(QColor("#8B7DFF"), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(fr)
        p.end()
