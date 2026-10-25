"""Visual design system: palette, typography and the application stylesheet."""
from __future__ import annotations

import sys

from PySide6.QtCore import QCoreApplication, QEvent, QObject
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QComboBox

from ..core.paths import assets_dir

C = {
    "bg": "#F3F5FA",
    "surface": "#FFFFFF",
    "surface2": "#F7F8FC",
    "border": "#E3E7F0",
    "border2": "#CED5E3",
    "text": "#0E1A3A",
    "muted": "#5B6684",
    "faint": "#8F98B0",
    "primary": "#5B4BDB",
    "primary_h": "#4C3CC9",
    "primary_p": "#3F31B0",
    "primary_soft": "#EEEBFF",
    "blue": "#2F6FEB",
    "blue_soft": "#E8F0FE",
    "success": "#0E8F63",
    "success_soft": "#E2F6EE",
    "warning": "#A86400",
    "warning_soft": "#FFF4DC",
    "danger": "#C9343F",
    "danger_soft": "#FDECEE",
    "rail": "#0E1530",
    "rail2": "#18224A",
    "rail_text": "#B3BCD8",
    "rail_mute": "#6D7AA0",
}

TONES = {
    "neutral": (C["muted"], "#EEF1F6"),
    "info": (C["blue"], C["blue_soft"]),
    "ok": (C["success"], C["success_soft"]),
    "warn": (C["warning"], C["warning_soft"]),
    "error": (C["danger"], C["danger_soft"]),
    "primary": (C["primary"], C["primary_soft"]),
}


def ui_font() -> QFont:
    f = QFont()
    if sys.platform == "win32":
        f.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Arial"])
    elif sys.platform == "darwin":
        f.setFamilies([".AppleSystemUIFont", "Helvetica Neue", "Arial"])
    else:
        f.setFamilies(["Inter", "Noto Sans", "Ubuntu", "DejaVu Sans"])
    f.setPixelSize(13)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def stylesheet() -> str:
    check = (assets_dir() / "check.svg").as_posix()
    down = (assets_dir() / "chevron-down.svg").as_posix()
    t = C
    badge_rules = "\n".join(
        f'QLabel#Badge[tone="{k}"] {{ color: {fg}; background: {bg}; }}' for k, (fg, bg) in TONES.items()
    )
    banner_rules = "\n".join(
        f'QFrame#Banner[tone="{k}"] {{ background: {bg}; border: 1px solid {bg}; }}\n'
        f'QFrame#Banner[tone="{k}"] QLabel#BannerText {{ color: {fg if k != "neutral" else t["text"]}; }}'
        for k, (fg, bg) in TONES.items()
    )
    return f"""
* {{ outline: none; }}
QWidget {{ color: {t['text']}; font-size: 13px; }}
QMainWindow, QWidget#Central, QWidget#PageBody, QScrollArea#PageScroll > QWidget > QWidget {{ background: {t['bg']}; }}
QScrollArea {{ border: none; background: transparent; }}
QToolTip {{ background: {t['text']}; color: white; border: none; padding: 6px 8px; border-radius: 6px; }}

/* ---------- rail ---------- */
QFrame#Rail {{ background: {t['rail']}; border: none; }}
QLabel#RailTitle {{ color: white; font-size: 15px; font-weight: 700; }}
QLabel#RailSub {{ color: {t['rail_mute']}; font-size: 11px; }}
QLabel#RailSection {{ color: {t['rail_mute']}; font-size: 10px; font-weight: 700; letter-spacing: 1px; padding: 14px 0 4px 18px; }}
QPushButton#RailButton {{
    color: {t['rail_text']}; background: transparent; border: none; border-left: 3px solid transparent;
    text-align: left; padding: 9px 14px 9px 15px; font-size: 13px; border-radius: 0px;
}}
QPushButton#RailButton:hover {{ background: {t['rail2']}; color: white; }}
QPushButton#RailButton:checked {{ background: {t['rail2']}; color: white; border-left: 3px solid #8B7DFF; font-weight: 600; }}
QPushButton#RailButton:disabled {{ color: #4A5579; }}

/* ---------- header ---------- */
QFrame#Header {{ background: {t['surface']}; border: none; border-bottom: 1px solid {t['border']}; }}
QLabel#ProjectName {{ font-size: 16px; font-weight: 700; }}
QLabel#HeaderMeta {{ color: {t['muted']}; font-size: 12px; }}
QLabel#PageTitle {{ font-size: 22px; font-weight: 700; }}
QLabel#PageSubtitle {{ color: {t['muted']}; font-size: 13px; }}
QLabel#H2 {{ font-size: 15px; font-weight: 700; }}
QLabel#Muted {{ color: {t['muted']}; }}
QLabel#Faint {{ color: {t['faint']}; font-size: 12px; }}
QLabel#Help {{ color: {t['muted']}; font-size: 12px; }}
QLabel#FieldLabel {{ color: {t['text']}; font-weight: 600; font-size: 12px; }}
QLabel#Mono {{ font-family: Consolas, Menlo, monospace; font-size: 12px; color: {t['muted']}; }}
QLabel#Stat {{ font-size: 22px; font-weight: 700; }}

/* ---------- cards ---------- */
QFrame#Card {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px; }}
QFrame#Card[accent="true"] {{ border: 1px solid #D9D3FF; }}
QLabel#CardTitle {{ font-size: 14px; font-weight: 700; }}
QLabel#CardSubtitle {{ color: {t['muted']}; font-size: 12px; }}
QFrame#SoftPanel {{ background: {t['surface2']}; border: 1px solid {t['border']}; border-radius: 10px; }}
QFrame#Hero {{ border-radius: 16px; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1B1F5C, stop:0.55 #3B2FA8, stop:1 #6A4FE0); }}
QFrame#Hero QLabel {{ color: white; background: transparent; }}
QFrame#Hero QLabel#HeroSub {{ color: #D8D4FF; font-size: 14px; }}
QFrame#Line {{ background: {t['border']}; max-height: 1px; min-height: 1px; border: none; }}

/* ---------- badges / banners ---------- */
QLabel#Badge {{ border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 700; }}
{badge_rules}
QFrame#Banner {{ border-radius: 10px; }}
QLabel#BannerText {{ font-size: 12px; }}
{banner_rules}

/* ---------- buttons ---------- */
QPushButton {{
    background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border2']}; border-radius: 8px;
    padding: 7px 14px; font-weight: 600;
}}
QPushButton:hover {{ background: {t['surface2']}; border-color: #B7C0D3; }}
QPushButton:pressed {{ background: #ECEFF6; }}
QPushButton:disabled {{ color: #A8B0C3; background: #F4F6FA; border-color: {t['border']}; }}
QPushButton[variant="primary"] {{ background: {t['primary']}; color: white; border: 1px solid {t['primary']}; }}
QPushButton[variant="primary"]:hover {{ background: {t['primary_h']}; border-color: {t['primary_h']}; }}
QPushButton[variant="primary"]:pressed {{ background: {t['primary_p']}; }}
QPushButton[variant="primary"]:disabled {{ background: #C9C3F2; border-color: #C9C3F2; color: #F5F3FF; }}
QPushButton[variant="soft"] {{ background: {t['primary_soft']}; color: {t['primary_p']}; border: 1px solid {t['primary_soft']}; }}
QPushButton[variant="soft"]:hover {{ background: #E3DEFF; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; color: {t['muted']}; }}
QPushButton[variant="ghost"]:hover {{ background: #EEF1F7; color: {t['text']}; }}
QPushButton[variant="danger"] {{ color: {t['danger']}; border-color: #F0C6CB; }}
QPushButton[variant="danger"]:hover {{ background: {t['danger_soft']}; }}
QPushButton[variant="hero"] {{ background: white; color: {t['primary_p']}; border: none; padding: 10px 18px; font-size: 14px; }}
QPushButton[variant="hero"]:hover {{ background: #F1EEFF; }}
QPushButton[variant="heroGhost"] {{ background: rgba(255,255,255,0.12); color: white; border: 1px solid rgba(255,255,255,0.35); padding: 10px 18px; font-size: 14px; }}
QPushButton[variant="heroGhost"]:hover {{ background: rgba(255,255,255,0.2); }}
QPushButton[seg="true"] {{ border-radius: 0px; padding: 6px 14px; background: {t['surface']}; color: {t['muted']}; }}
QPushButton[seg="true"]:checked {{ background: {t['primary_soft']}; color: {t['primary_p']}; border-color: #BDB3FF; }}
QPushButton[segpos="first"] {{ border-top-left-radius: 8px; border-bottom-left-radius: 8px; }}
QPushButton[segpos="last"] {{ border-top-right-radius: 8px; border-bottom-right-radius: 8px; }}
QToolButton {{ border: none; background: transparent; border-radius: 6px; padding: 4px; }}
QToolButton:hover {{ background: #EEF1F7; }}

/* ---------- inputs ---------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTimeEdit {{
    background: {t['surface']}; border: 1px solid {t['border2']}; border-radius: 8px; padding: 6px 9px;
    selection-background-color: #CFC7FF; selection-color: {t['text']};
}}
QPlainTextEdit, QTextEdit {{ padding: 8px 10px; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {t['primary']}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ background: #F4F6FA; color: #9AA3B8; }}
QLineEdit[readOnly="true"] {{ background: {t['surface2']}; }}
QComboBox {{ padding-right: 26px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({down}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: white; border: 1px solid {t['border2']}; border-radius: 8px; padding: 4px;
    selection-background-color: {t['primary_soft']}; selection-color: {t['text']}; outline: none; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 16px; border: none; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {t['border2']}; background: white; }}
QCheckBox::indicator:hover {{ border-color: {t['primary']}; }}
QCheckBox::indicator:checked {{ background: {t['primary']}; border-color: {t['primary']}; image: url({check}); }}
QCheckBox::indicator:disabled {{ background: #EEF1F6; }}
QRadioButton::indicator {{ width: 15px; height: 15px; }}
QSlider::groove:horizontal {{ height: 4px; background: #E1E5EE; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t['primary']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; border: 2px solid {t['primary']}; width: 12px; height: 12px; margin: -6px 0; border-radius: 8px; }}

/* ---------- tables / lists ---------- */
QTableWidget, QTableView, QListWidget, QTreeWidget {{
    background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px;
    gridline-color: #EEF1F6; selection-background-color: {t['primary_soft']}; selection-color: {t['text']};
    alternate-background-color: #FAFBFD;
}}
QTableWidget::item, QTableView::item {{ padding: 4px 6px; }}
QListWidget::item {{ padding: 6px 8px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {t['primary_soft']}; color: {t['text']}; }}
QHeaderView::section {{
    background: {t['surface2']}; color: {t['muted']}; border: none; border-bottom: 1px solid {t['border']};
    padding: 7px 6px; font-size: 11px; font-weight: 700;
}}
QTableCornerButton::section {{ background: {t['surface2']}; border: none; }}

/* ---------- misc ---------- */
QProgressBar {{ background: #E7EAF2; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ border-radius: 4px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {t['blue']}, stop:1 {t['primary']}); }}
QProgressBar[thin="true"] {{ max-height: 6px; min-height: 6px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #CBD2E0; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #AEB8CC; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #CBD2E0; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {t['muted']}; padding: 8px 12px; border: none; border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {t['primary_p']}; border-bottom: 2px solid {t['primary']}; }}
QTabBar::tab:hover {{ color: {t['text']}; }}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 8px; }}
QSplitter::handle:vertical {{ height: 8px; }}
QDockWidget {{ titlebar-close-icon: none; font-weight: 600; }}
QDockWidget::title {{ background: {t['surface']}; padding: 6px 10px; border-top: 1px solid {t['border']}; }}
QFrame#Activity {{ background: {t['surface']}; border-top: 1px solid {t['border']}; }}
QFrame#Toast {{ background: {t['text']}; border-radius: 10px; }}
QFrame#Toast QLabel {{ color: white; background: transparent; }}
QMenu {{ background: white; border: 1px solid {t['border2']}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t['primary_soft']}; }}
QMessageBox QLabel {{ font-size: 13px; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setFont(ui_font())
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(C["bg"]))
    pal.setColor(QPalette.ColorRole.Base, QColor(C["surface"]))
    pal.setColor(QPalette.ColorRole.Text, QColor(C["text"]))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(C["text"]))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(C["text"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor("#CFC7FF"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(C["text"]))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(C["faint"]))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(C["text"]))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor("white"))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet())
    global _polisher
    if _polisher is None:
        _polisher = _ComboPolisher(app)
        app.installEventFilter(_polisher)


class _ComboPolisher(QObject):
    """App-wide combo box tweaks.

    * Combo boxes default to sizing themselves to their longest item, which pushes pages wider than the
      window when catalog labels are long. Give every combo a bounded minimum instead; layouts still stretch it.
    * The mouse wheel never changes a closed combo's value (too easy to alter a setting while scrolling the
      page). The wheel event is handed to the surrounding scroll area so the page keeps scrolling; values
      change only by clicking and picking an item.
    """

    def eventFilter(self, obj, ev):  # noqa: N802
        et = ev.type()
        if et == QEvent.Type.Wheel and isinstance(obj, QComboBox) and not obj.view().isVisible():
            area = obj.parentWidget()
            while area is not None and not isinstance(area, QAbstractScrollArea):
                area = area.parentWidget()
            if area is not None:
                QCoreApplication.sendEvent(area.viewport(), ev)
            return True
        if et == QEvent.Type.Polish and isinstance(obj, QComboBox) and not obj.property("_sized"):
            obj.setProperty("_sized", True)
            obj.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            obj.setMinimumContentsLength(max(obj.minimumContentsLength(), 18))
        return False


_polisher: _ComboPolisher | None = None
