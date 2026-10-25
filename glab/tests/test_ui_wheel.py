"""UI behaviour: the mouse wheel must not change a closed combo box; it scrolls the page instead."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox, QScrollArea, QVBoxLayout, QWidget  # noqa: E402

from scriptreel.ui import theme  # noqa: E402


def _wheel(widget, dy: int) -> None:
    pos = QPointF(widget.rect().center())
    ev = QWheelEvent(pos, QPointF(widget.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, dy),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, ev)


def test_wheel_does_not_change_combo_and_scrolls_page():
    app = QApplication.instance() or QApplication([])
    theme.apply_theme(app)
    area = QScrollArea()
    area.setWidgetResizable(True)
    inner = QWidget()
    lay = QVBoxLayout(inner)
    combos = []
    for _ in range(3):
        c = QComboBox()
        c.addItems([f"item {i}" for i in range(10)])
        c.setCurrentIndex(5)
        combos.append(c)
        lay.addWidget(c)
        lay.addSpacing(600)
    editable = QComboBox()
    editable.setEditable(True)
    editable.addItems(["a", "b", "c"])
    editable.setCurrentIndex(1)
    lay.addWidget(editable)
    area.setWidget(inner)
    area.resize(400, 300)
    area.show()
    app.processEvents()

    bar = area.verticalScrollBar()
    assert bar.value() == 0
    _wheel(combos[0], -120)   # wheel down over a combo
    _wheel(editable.lineEdit(), -120)
    _wheel(editable, -120)
    app.processEvents()
    assert [c.currentIndex() for c in combos] == [5, 5, 5]
    assert editable.currentIndex() == 1
    assert bar.value() > 0    # the page scrolled instead
    area.close()
