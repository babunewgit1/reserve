"""Inline stroke icons (original, 24×24 grid) rendered to QIcon via QtSvg."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtSvg import QSvgRenderer

_P = {
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M10 21v-6h4v6"/>',
    "plug": '<path d="M9 2v6M15 2v6"/><path d="M6 8h12v3a6 6 0 0 1-12 0z"/><path d="M12 17v5"/>',
    "sliders": '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
    "clipboard": '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 3h6v3H9z"/><path d="M9 11h6M9 15h4"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/>',
    "captions": '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M7 15h4M13 15h4M7 11h10"/>',
    "scenes": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M8 4l-2 5M13 4l-2 5M18 4l-2 5"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/>',
    "video": '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="m16 10 5-3v10l-5-3z"/>',
    "scissors": '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M8.6 7.6 20 18M8.6 16.4 20 6"/>',
    "youtube": '<rect x="2.5" y="5" width="19" height="14" rx="4"/><path d="m10 9 5 3-5 3z"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14.6-4.4L4 8"/><path d="M4 3v5h5"/><path d="M4 13a8 8 0 0 0 14.6 4.4L20 16"/><path d="M20 21v-5h-5"/>',
    "play": '<path d="M7 4.5v15l13-7.5z" fill="currentColor"/>',
    "pause": '<path d="M8 5v14M16 5v14" stroke-width="3"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "folder-open": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v1"/><path d="M3 19 6 11h16l-3 8z"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6"/><path d="M6 7l1 13h10l1-13"/><path d="M9 7V4h6v3"/>',
    "split": '<path d="M12 3v18"/><path d="m7 8-4 4 4 4M17 8l4 4-4 4"/>',
    "merge": '<path d="m3 8 4 4-4 4M21 8l-4 4 4 4"/><path d="M8 12h8"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7"/>',
    "check-circle": '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 3 3 5-6"/>',
    "alert": '<path d="M12 3.5 2.5 20h19z"/><path d="M12 10v4M12 17v.5"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "upload": '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
    "sparkles": '<path d="M11 3l1.8 4.7 4.7 1.8-4.7 1.8L11 16l-1.8-4.7L4.5 9.5l4.7-1.8z"/><path d="M18.5 14.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
    "save": '<path d="M5 3h11l3 3v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M7 3v5h8V3M7 21v-7h10v7"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    "up": '<path d="M12 19V5M6 11l6-6 6 6"/>',
    "down": '<path d="M12 5v14M6 13l6 6 6-6"/>',
    "left": '<path d="m15 18-6-6 6-6"/>',
    "right": '<path d="m9 18 6-6-6-6"/>',
    "wand": '<path d="M4 20 15 9"/><path d="m13 7 4 4"/><path d="M15 3v2M20 8h2M18.5 4.5 17 6M21 3l-1 1"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M17 6l3 3M14 9l2 2"/>',
    "activity": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "film": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 3v18M17 3v18M3 8h4M3 12h4M3 16h4M17 8h4M17 12h4M17 16h4"/>',
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "link": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7L12 6.3"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    "bolt": '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    "music": '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "file": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>',
    "copy": '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
    "shield": '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/>',
    "palette": '<path d="M12 3a9 9 0 1 0 0 18c1 0 1.5-.8 1.5-1.6 0-1-.8-1.4-.8-2.4 0-.9.7-1.5 1.6-1.5H17a4 4 0 0 0 4-4c0-4.7-4-8.5-9-8.5z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10" cy="7" r="1"/><circle cx="15" cy="7.5" r="1"/>',
    "layers": '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    "cpu": '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
}

_cache: dict[tuple, QIcon] = {}


def svg(name: str, color: str) -> bytes:
    body = _P.get(name, _P["info"]).replace("currentColor", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{body}</svg>').encode()


def pixmap(name: str, color: str = "#5B6684", size: int = 18, scale: float = 2.0) -> QPixmap:
    px = QPixmap(int(size * scale), int(size * scale))
    px.fill(Qt.GlobalColor.transparent)
    r = QSvgRenderer(QByteArray(svg(name, color)))
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p)
    p.end()
    px.setDevicePixelRatio(scale)
    return px


def icon(name: str, color: str = "#5B6684", size: int = 18) -> QIcon:
    key = (name, color, size)
    if key not in _cache:
        _cache[key] = QIcon(pixmap(name, color, size))
    return _cache[key]


def logo_pixmap(size: int = 36, scale: float = 2.0) -> QPixmap:
    """App mark: violet gradient tile with a play glyph over a sound wave."""
    s = int(size * scale)
    px = QPixmap(s, s)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(0, 0, s, s)
    g.setColorAt(0, QColor("#4F7BFF"))
    g.setColorAt(1, QColor("#7A4DF0"))
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, s, s), s * 0.26, s * 0.26)
    p.fillPath(path, g)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 70))
    for i, h in enumerate((0.22, 0.38, 0.5, 0.34, 0.2)):
        x = s * (0.18 + i * 0.14)
        p.drawRoundedRect(QRectF(x, s * (0.5 - h / 2), s * 0.07, s * h), s * 0.03, s * 0.03)
    tri = QPainterPath()
    tri.moveTo(QPointF(s * 0.40, s * 0.30))
    tri.lineTo(QPointF(s * 0.72, s * 0.50))
    tri.lineTo(QPointF(s * 0.40, s * 0.70))
    tri.closeSubpath()
    p.setBrush(QColor("white"))
    p.drawPath(tri)
    p.end()
    px.setDevicePixelRatio(scale)
    return px
