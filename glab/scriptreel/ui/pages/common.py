"""Helpers shared by several pages: catalog combos, voice combo, script editor."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget

from ...core.catalog import MODE_LABELS
from ...core.i18n import t
from ..widgets import button, label

WPM = 150  # typical narration pace at speed 1.0


def words_in(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def fill_voice_combo(combo: QComboBox, voices, current_id: str, current_name: str = "") -> None:
    with QSignalBlocker(combo):
        combo.clear()
        combo.addItem(t("— Choose a voice preset —"), "")
        found = False
        for v in voices:
            combo.addItem(v.label, v.id)
            combo.setItemData(combo.count() - 1, f"id: {v.id}" + (f"\ntags: {', '.join(v.tags)}" if v.tags else ""),
                              Qt.ItemDataRole.ToolTipRole)
            found |= v.id == current_id
        if current_id and not found:
            combo.addItem(f"{current_name or current_id}  ·  {t('saved in project (not in current list)')}", current_id)
        idx = combo.findData(current_id)
        combo.setCurrentIndex(max(0, idx))


def fill_image_combo(combo: QComboBox, catalog, current: str, default_label: str | None = None) -> None:
    with QSignalBlocker(combo):
        combo.clear()
        if default_label is not None:
            combo.addItem(default_label, "")
        for e in catalog.enabled_images():
            combo.addItem(f"{e.label}", e.id)
            combo.setItemData(combo.count() - 1, f"{e.api_identity}\n{e.requirements}", Qt.ItemDataRole.ToolTipRole)
        if current and combo.findData(current) < 0:
            combo.addItem(f"{current} · {t('not in catalog')}", current)
        combo.setCurrentIndex(max(0, combo.findData(current)))


def fill_video_combo(combo: QComboBox, catalog, current: str, default_label: str | None = None) -> None:
    """Grouped by API route so Veo/Omni models, Grok modes and Meta modes are never confused."""
    model = QStandardItemModel(combo)
    if default_label is not None:
        it = QStandardItem(default_label)
        it.setData("", Qt.ItemDataRole.UserRole)
        model.appendRow(it)
    group = None
    for v in catalog.enabled_videos():
        if v.group != group:
            group = v.group
            head = QStandardItem(f"  {group or v.route}")
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            f = head.font()
            f.setBold(True)
            head.setFont(f)
            model.appendRow(head)
        lbl = f"    {v.label}" + (f"  ·  model {v.model}" if v.model else "  ·  modes " + "/".join(v.modes.values()))
        it = QStandardItem(lbl)
        it.setData(v.id, Qt.ItemDataRole.UserRole)
        it.setToolTip(f"{v.api_identity}\n{v.requirements}")
        model.appendRow(it)
    with QSignalBlocker(combo):
        combo.setModel(model)
        idx = combo.findData(current)
        if idx < 0 and current:
            it = QStandardItem(f"{current} · {t('not in catalog')}")
            it.setData(current, Qt.ItemDataRole.UserRole)
            model.appendRow(it)
            idx = combo.findData(current)
        if idx < 0:
            idx = next((i for i in range(model.rowCount()) if model.item(i).data(Qt.ItemDataRole.UserRole) is not None), 0)
        combo.setCurrentIndex(idx)


def fill_mode_combo(combo: QComboBox, entry, current: str, include_default: bool = False) -> None:
    with QSignalBlocker(combo):
        combo.clear()
        if include_default:
            combo.addItem(t("Project default"), "")
        combo.addItem(t(MODE_LABELS["auto"]), "auto")
        if entry is not None:
            for key, api in entry.modes.items():
                note = ""
                if key == "start_end" and entry.end_frame_note:
                    note = " *"
                combo.addItem(f"{t(MODE_LABELS.get(key, key))}  ({api}){note}", key)
                if key == "start_end" and entry.end_frame_note:
                    combo.setItemData(combo.count() - 1, entry.end_frame_note, Qt.ItemDataRole.ToolTipRole)
        combo.setCurrentIndex(max(0, combo.findData(current)))


def image_help(entry) -> str:
    if entry is None:
        return t("Not in the enabled catalog.")
    bits = [f"<b>{entry.api_identity}</b>", entry.requirements]
    bits.append(t("Ratios") + ": " + ", ".join(entry.aspect_ratios))
    bits.append(t("Max reference images") + f": {entry.max_reference_images}")
    if not entry.documented:
        bits.append("⚠ " + t("Not in the official docs — may silently fall back."))
    if entry.notes:
        bits.append(f"<i>{entry.notes}</i>")
    return "<br>".join(b for b in bits if b)


def video_help(entry, ctrl) -> str:
    if entry is None:
        return t("Not in the enabled catalog.")
    ds = ctrl.durations_for(entry)
    bits = [f"<b>{entry.api_identity}</b>", entry.requirements,
            t("Native clip lengths") + ": " + (", ".join(f"{d}s" for d in ds) if ds else t("not documented (server default)")),
            t("Ratios") + ": " + ", ".join(entry.aspect_ratios) + " · " + t("Resolutions") + ": " +
            (", ".join(ctrl.resolutions_for(entry)) or "—"),
            t("End-frame chaining") + ": " + (t("supported") if entry.chaining_supported else t("not supported"))]
    if entry.requires_ultra and not ctrl.settings.google_ultra:
        bits.append("⚠ " + t("Requires ULTRA accounts. Enable the ULTRA option in Settings if you have them."))
    if entry.end_frame_note:
        bits.append(f"<i>{entry.end_frame_note}</i>")
    if entry.notes:
        bits.append(f"<i>{entry.notes}</i>")
    return "<br>".join(b for b in bits if b)


class ScriptEditor(QWidget):
    """Narration editor with word count, estimated duration and .txt/.md import."""

    edited = Signal(str)

    def __init__(self, min_height: int = 260) -> None:
        super().__init__()
        self.speed = 1.0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.edit = QPlainTextEdit()
        self.edit.setObjectName("scriptEditor")
        self.edit.setPlaceholderText(t("Paste or type your narration here. Write it exactly as it should be spoken — "
                                       "one idea per sentence works best for subtitles and scenes."))
        self.edit.setMinimumHeight(min_height)
        f = self.edit.font()
        f.setPixelSize(14)
        self.edit.setFont(f)
        self.edit.textChanged.connect(self._changed)
        lay.addWidget(self.edit, 1)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.stats = label("", "Help")
        row.addWidget(self.stats, 1)
        row.addWidget(button("Load .txt / .md", "upload", "ghost", on_click=self.load_file))
        lay.addLayout(row)
        self._update_stats()

    def set_text(self, text: str) -> None:
        if self.edit.toPlainText() != text:
            with QSignalBlocker(self.edit):
                self.edit.setPlainText(text)
            self._update_stats()

    def text(self) -> str:
        return self.edit.toPlainText()

    def set_speed(self, speed: float) -> None:
        self.speed = speed or 1.0
        self._update_stats()

    def _changed(self) -> None:
        self._update_stats()
        self.edited.emit(self.edit.toPlainText())

    def _update_stats(self) -> None:
        n = words_in(self.edit.toPlainText())
        secs = n / (WPM * self.speed) * 60 if n else 0
        m, s = divmod(int(round(secs)), 60)
        chars = len(self.edit.toPlainText())
        self.stats.setText(f"{n} {t('words')} · {chars} {t('characters')} · ≈ {m}:{s:02d} {t('estimated narration')} "
                           f"({t('at')} ×{self.speed:.2f})")

    def load_file(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, t("Load narration script"), str(Path.home()),
                                           "Text (*.txt *.md);;All files (*)")
        if not p:
            return
        raw = Path(p).read_bytes()
        for enc in ("utf-8-sig", "utf-16", "cp1252"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", "replace")
        if p.lower().endswith(".md"):
            text = strip_markdown(text)
        self.edit.setPlainText(text.strip())


def strip_markdown(text: str) -> str:
    out = []
    for line in text.splitlines():
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)
        line = re.sub(r"^\s*[-*+]\s+", "", line)
        line = re.sub(r"^\s*>\s?", "", line)
        line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
        line = re.sub(r"[*_`]{1,3}", "", line)
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out))
