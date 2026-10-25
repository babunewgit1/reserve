"""Painted multi-lane timeline: ruler, scene clips, narration waveform and subtitle cues."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..core.i18n import t
from .theme import C

STATUS_COLORS = {
    "clip": "#5B4BDB",      # has a generated/uploaded clip
    "image": "#2F6FEB",     # still image only (renders as a pan)
    "empty": "#A7B0C6",     # nothing yet (renders as a title card)
    "busy": "#C084FC",
    "error": "#C9343F",
}


@dataclass
class TLScene:
    id: str
    start: float
    end: float
    label: str
    status: str  # clip | image | empty | busy | error
    trimmed: bool = False


class Timeline(QWidget):
    scene_clicked = Signal(str)
    seek = Signal(float)
    boundary_moved = Signal(int, float)  # index of right-hand scene, new time

    RULER = 20
    SCENE_H = 44
    WAVE_H = 40
    SUB_H = 26
    PAD = 6

    def __init__(self, editable_boundaries: bool = True) -> None:
        super().__init__()
        self.scenes: list[TLScene] = []
        self.cues: list[tuple[float, float, str]] = []
        self.peaks: list[float] = []
        self.duration = 0.0
        self.selected = ""
        self.playhead = -1.0
        self.editable = editable_boundaries
        self._drag_idx = -1
        self._drag_t = 0.0
        self.setMouseTracking(True)
        h = self.RULER + self.SCENE_H + self.WAVE_H + self.SUB_H + self.PAD * 5
        self.setFixedHeight(h)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_data(self, scenes: list[TLScene], cues, peaks: list[float], duration: float) -> None:
        self.scenes, self.cues, self.peaks = scenes, cues, peaks or []
        self.duration = max(duration, scenes[-1].end if scenes else 0.0)
        self.update()

    def set_selected(self, sid: str) -> None:
        self.selected = sid
        self.update()

    def set_playhead(self, sec: float) -> None:
        self.playhead = sec
        self.update()

    # -- geometry
    def _x(self, sec: float) -> float:
        return 8 + (self.width() - 16) * (sec / self.duration if self.duration else 0)

    def _t(self, x: float) -> float:
        return max(0.0, min(self.duration, (x - 8) / max(1, self.width() - 16) * self.duration))

    def _lane_y(self, lane: int) -> float:
        ys = [self.RULER + self.PAD, self.RULER + self.SCENE_H + self.PAD * 2,
              self.RULER + self.SCENE_H + self.WAVE_H + self.PAD * 3]
        return ys[lane]

    def _boundary_at(self, x: float) -> int:
        if not self.editable:
            return -1
        for i in range(1, len(self.scenes)):
            if abs(self._x(self.scenes[i].start) - x) < 5:
                return i
        return -1

    # -- interaction
    def mousePressEvent(self, e) -> None:  # noqa: N802
        x, y = e.position().x(), e.position().y()
        if not self.duration:
            return
        sy = self._lane_y(0)
        if sy <= y <= sy + self.SCENE_H:
            b = self._boundary_at(x)
            if b > 0:
                self._drag_idx, self._drag_t = b, self.scenes[b].start
                return
            sec = self._t(x)
            for s in self.scenes:
                if s.start <= sec < s.end:
                    self.selected = s.id
                    self.scene_clicked.emit(s.id)
                    self.update()
                    break
        self.seek.emit(self._t(x))

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        x, y = e.position().x(), e.position().y()
        if self._drag_idx > 0:
            a, b = self.scenes[self._drag_idx - 1], self.scenes[self._drag_idx]
            self._drag_t = min(max(self._t(x), a.start + 0.5), b.end - 0.5)
            self.update()
            return
        sy = self._lane_y(0)
        on_b = sy <= y <= sy + self.SCENE_H and self._boundary_at(x) > 0
        self.setCursor(Qt.CursorShape.SizeHorCursor if on_b else Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, _e) -> None:  # noqa: N802
        if self._drag_idx > 0:
            idx, tt = self._drag_idx, self._drag_t
            self._drag_idx = -1
            if abs(tt - self.scenes[idx].start) > 0.04:
                self.boundary_moved.emit(idx, round(tt, 3))
            self.update()

    # -- painting
    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        bg = QPainterPath()
        bg.addRoundedRect(QRectF(0, 0, w - 1, self.height() - 1), 10, 10)
        p.fillPath(bg, QColor(C["surface"]))
        p.setPen(QPen(QColor(C["border"]), 1))
        p.drawPath(bg)
        if not self.duration:
            p.setPen(QColor(C["faint"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, t("The timeline appears after narration and scene planning."))
            p.end()
            return
        small = QFont(self.font())
        small.setPixelSize(10)
        p.setFont(small)
        # ruler
        step = next((s for s in (1, 2, 5, 10, 15, 30, 60, 120) if (w - 16) / self.duration * s > 46), 300)
        tt = 0.0
        while tt <= self.duration + 0.001:
            x = self._x(tt)
            p.setPen(QPen(QColor(C["border2"]), 1))
            p.drawLine(QPointF(x, 14), QPointF(x, self.RULER))
            p.setPen(QColor(C["faint"]))
            m, s = divmod(int(tt), 60)
            p.drawText(QPointF(x + 3, 12), f"{m}:{s:02d}")
            tt += step
        # scenes lane
        y0 = self._lane_y(0)
        lbl = QFont(self.font())
        lbl.setPixelSize(11)
        lbl.setBold(True)
        for i, s in enumerate(self.scenes):
            start = self._drag_t if (self._drag_idx == i and i > 0) else s.start
            end = self._drag_t if (self._drag_idx == i + 1) else s.end
            x0, x1 = self._x(start) + 1, self._x(end) - 1
            r = QRectF(x0, y0, max(2.0, x1 - x0), self.SCENE_H)
            col = QColor(STATUS_COLORS.get(s.status, STATUS_COLORS["empty"]))
            path = QPainterPath()
            path.addRoundedRect(r, 6, 6)
            fill = QColor(col)
            fill.setAlpha(235 if s.id == self.selected else 175)
            p.fillPath(path, fill)
            if s.id == self.selected:
                p.setPen(QPen(QColor(C["text"]), 2))
                p.drawPath(path)
            p.setPen(QColor("white"))
            p.setFont(lbl)
            if r.width() > 22:
                p.drawText(r.adjusted(6, 4, -4, -4), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, f"{i + 1}")
            p.setFont(small)
            if r.width() > 60:
                p.drawText(r.adjusted(6, 4, -4, -4), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                           p.fontMetrics().elidedText(s.label, Qt.TextElideMode.ElideRight, int(r.width() - 10)))
            if s.trimmed and r.width() > 16:
                p.drawText(r.adjusted(0, 3, -5, 0), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, "✂")
        # waveform lane
        y1 = self._lane_y(1)
        mid = y1 + self.WAVE_H / 2
        p.fillRect(QRectF(8, y1, w - 16, self.WAVE_H), QColor(C["surface2"]))
        if self.peaks:
            n = len(self.peaks)
            cols = max(1, int((w - 16) / 3))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#9AA6C4"))
            for c in range(cols):
                a = int(c / cols * n)
                b = max(a + 1, int((c + 1) / cols * n))
                v = max(self.peaks[a:b]) if b <= n else 0
                bh = max(1.5, v * (self.WAVE_H - 8))
                p.drawRect(QRectF(8 + c * 3, mid - bh / 2, 2, bh))
        else:
            p.setPen(QColor(C["faint"]))
            p.drawText(QRectF(8, y1, w - 16, self.WAVE_H), Qt.AlignmentFlag.AlignCenter, t("Narration"))
        # subtitles lane
        y2 = self._lane_y(2)
        for a, b, text in self.cues:
            r = QRectF(self._x(a) + 0.5, y2, max(2.0, self._x(b) - self._x(a) - 1), self.SUB_H)
            path = QPainterPath()
            path.addRoundedRect(r, 4, 4)
            p.fillPath(path, QColor(C["warning_soft"]))
            p.setPen(QPen(QColor("#F0D9A8"), 1))
            p.drawPath(path)
            if r.width() > 26:
                p.setPen(QColor(C["warning"]))
                p.drawText(r.adjusted(4, 0, -3, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(r.width() - 8)))
        # playhead
        if self.playhead >= 0:
            x = self._x(self.playhead)
            p.setPen(QPen(QColor(C["danger"]), 2))
            p.drawLine(QPointF(x, 4), QPointF(x, self.height() - 4))
        p.end()
