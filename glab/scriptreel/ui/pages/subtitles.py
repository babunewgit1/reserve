"""E. Subtitle alignment & review page."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QProgressBar, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ...core.i18n import t
from ...core.project import Cue
from ...services.srt import SrtCue, auto_fix, fmt_ts, parse_srt, parse_ts, validate
from ..media import AudioPlayer
from ..theme import C
from ..widgets import (
    Badge, Banner, Card, EmptyState, Page, Segmented, StatusLine, button, confirm, hbox, label, labeled, tool_button,
)

COLS = ["#", "Start", "End", "Dur.", "Subtitle text", "Check"]


class SubtitlesPage(Page):
    title_text = "Subtitles"
    subtitle_text = ("Timing is created locally from the generated narration audio. Review and correct it here — the SRT is "
                     "exported even if you don't burn subtitles into the video.")

    def __init__(self, ctrl, parent=None) -> None:
        super().__init__(ctrl, parent)
        L = self.layout_
        self.review_btn = self.add_action(button("Mark reviewed & continue", "check", "primary", on_click=self._reviewed))
        self.review_btn.setObjectName("btnSubtitlesReviewed")
        self.empty = EmptyState("captions", "Narration needed first",
                                "Generate the voiceover on the Narration page, then align subtitles here.",
                                "Go to Narration", lambda: ctrl.request_page.emit("narration"), "mic")
        L.addWidget(self.empty)
        self.body_w = QWidget()
        body = QVBoxLayout(self.body_w)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)
        L.addWidget(self.body_w, 1)

        # alignment controls
        ac = Card("Alignment", "", "wand")
        self.reviewed_badge = ac.add_action(Badge())
        row = QHBoxLayout()
        row.setSpacing(12)
        self.engine = QComboBox()
        self.engine.addItem(t("Settings default"), "")
        self.engine.addItem("faster-whisper", "faster_whisper")
        self.engine.addItem(t("Estimate from pauses"), "estimate")
        row.addWidget(labeled("Engine", self.engine))
        self.method = Segmented([("script", "Script-guided (recommended)"), ("asr", "Recognized text only")], "script")
        self.method.setToolTip(t("Script-guided keeps your exact script text and only takes timing from speech "
                                 "recognition. 'Recognized text' uses the words the recognizer heard."))
        row.addWidget(labeled("Method", self.method))
        row.addStretch(1)
        self.run_btn = button("Align subtitles", "wand", "primary", on_click=self._run)
        self.run_btn.setObjectName("btnAlign")
        row.addWidget(self.run_btn, 0, Qt.AlignmentFlag.AlignBottom)
        self.stop_btn = button("Stop", "stop", "danger", on_click=lambda: ctrl.jobs.cancel("align"))
        row.addWidget(self.stop_btn, 0, Qt.AlignmentFlag.AlignBottom)
        ac.add(row)
        self.progress = QProgressBar()
        self.progress.setProperty("thin", "true")
        self.progress.setRange(0, 1000)
        ac.add(self.progress)
        self.status = StatusLine()
        ac.add(self.status)
        self.precision = Banner("info", "")
        ac.add(self.precision)
        self.stale = Banner("warn", "")
        ac.add(self.stale)
        body.addWidget(ac)

        # player
        self.player = AudioPlayer(64)
        self.player.position.connect(self._follow)
        body.addWidget(self.player)

        # editor
        ec = Card("Subtitle cues", "Double-click a cell to edit. Times accept 0:00:01.250 or 1.25.", "captions")
        tb = QHBoxLayout()
        tb.setSpacing(4)
        tb.addWidget(button("Add", "plus", "ghost", "Insert a cue after the selected one", on_click=self._add))
        tb.addWidget(button("Split", "split", "ghost", "Split the selected cue in two", on_click=self._split))
        tb.addWidget(button("Merge", "merge", "ghost", "Merge the selected cue with the next one", on_click=self._merge))
        tb.addWidget(button("Delete", "trash", "ghost", on_click=self._delete))
        tb.addWidget(button("Auto-fix timing", "wand", "ghost", "Sort cues, remove overlaps and negative times",
                            on_click=self._autofix))
        tb.addStretch(1)
        tb.addWidget(tool_button("play", "Play from selected cue", self._play_cue))
        tb.addWidget(button("Import SRT", "upload", "ghost", on_click=self._import))
        tb.addWidget(button("Export SRT", "save", "soft", on_click=self._export))
        ec.add(tb)
        self.issues = Banner("ok", "")
        ec.add(self.issues)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels([t(c) for c in COLS])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
                                   | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.table.setWordWrap(True)
        hh = self.table.horizontalHeader()
        for c in (0, 1, 2, 3):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(5, 220)
        self.table.setMinimumHeight(380)
        self.table.itemChanged.connect(self._cell_changed)
        self.table.itemSelectionChanged.connect(self._selection)
        ec.add(self.table, 1)
        body.addWidget(ec, 1)

        ctrl.project_loaded.connect(self.mark_stale)
        ctrl.project_closed.connect(self.mark_stale)
        ctrl.peaks_changed.connect(self.mark_stale)
        ctrl.changed.connect(lambda a: a in ("subtitles", "voice") and self.mark_stale())
        ctrl.task_changed.connect(lambda k: k == "align" and self.mark_stale())
        ctrl.jobs.progress.connect(self._progress)
        ctrl.about_to_render.connect(self.player.release)

    # ------------------------------------------------------------- actions
    def _run(self) -> None:
        p = self.project
        if p and p.cues and not confirm(self, "Re-align subtitles?", "This replaces the current cues (including your edits) "
                                                                    "with a fresh alignment.", "Re-align", danger=True):
            return
        self.ctrl.run_alignment(self.method.value() or "script", self.engine.currentData() or None)
        self.mark_stale()

    def _reviewed(self) -> None:
        if self.ctrl.mark_subtitles_reviewed():
            self.ctrl.notify.emit("success", "Subtitles reviewed. subtitles.srt exported.")
            self.ctrl.request_page.emit("scenes")

    def _sel_row(self) -> int:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return rows[0] if rows else -1

    def _cues(self) -> list[Cue]:
        return self.project.cues if self.project else []

    def _commit(self, select: int | None = None) -> None:
        self.edit("subtitles")
        self._fill(select)

    def _add(self) -> None:
        p = self.project
        if not p:
            return
        i = self._sel_row()
        cues = p.cues
        if i < 0:
            start = cues[-1].end if cues else 0.0
            nxt = None
            i = len(cues) - 1
        else:
            start = cues[i].end
            nxt = cues[i + 1].start if i + 1 < len(cues) else None
        end = min(start + 2.0, nxt) if nxt is not None else start + 2.0
        if end - start < 0.2:
            self.ctrl.notify.emit("warning", "No room after this cue. Shorten it first or use Split.")
            return
        cues.insert(i + 1, Cue(start=round(start, 3), end=round(end, 3), text=t("New subtitle")))
        self._commit(i + 1)

    def _split(self) -> None:
        i = self._sel_row()
        cues = self._cues()
        if i < 0:
            return
        c = cues[i]
        words = c.text.split()
        if len(words) < 2 or c.end - c.start < 0.4:
            self.ctrl.notify.emit("warning", "This cue is too short to split.")
            return
        k = len(words) // 2
        a_txt, b_txt = " ".join(words[:k]), " ".join(words[k:])
        mid = c.start + (c.end - c.start) * (len(a_txt) / max(1, len(a_txt) + len(b_txt)))
        cues[i] = Cue(start=c.start, end=round(mid, 3), text=a_txt)
        cues.insert(i + 1, Cue(start=round(mid, 3), end=c.end, text=b_txt))
        self._commit(i)

    def _merge(self) -> None:
        i = self._sel_row()
        cues = self._cues()
        if i < 0 or i + 1 >= len(cues):
            return
        a, b = cues[i], cues[i + 1]
        cues[i] = Cue(start=a.start, end=max(a.end, b.end), text=f"{a.text} {b.text}".strip())
        del cues[i + 1]
        self._commit(i)

    def _delete(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows or not self.project:
            return
        if len(rows) > 3 and not confirm(self, "Delete cues", f"Delete {len(rows)} subtitle cues?", "Delete", danger=True):
            return
        for r in rows:
            del self.project.cues[r]
        self._commit(min(rows[-1], len(self.project.cues) - 1))

    def _autofix(self) -> None:
        p = self.project
        if not p:
            return
        fixed = auto_fix([SrtCue(c.start, c.end, c.text) for c in p.cues], p.voice.duration or None)
        p.cues = [Cue(start=round(c.start, 3), end=round(c.end, 3), text=c.text) for c in fixed]
        self._commit()

    def _import(self) -> None:
        p = self.project
        if not p:
            return
        path, _ = QFileDialog.getOpenFileName(self, t("Import SRT"), str(self.ctrl.folder), "SubRip (*.srt)")
        if not path:
            return
        try:
            cues = parse_srt(Path(path).read_text(encoding="utf-8-sig"))
        except Exception as exc:
            self.ctrl.notify.emit("error", f"Could not read SRT: {exc}")
            return
        if not cues:
            self.ctrl.notify.emit("error", "No cues found in that file.")
            return
        if p.cues and not confirm(self, "Replace cues?", f"Replace {len(p.cues)} cues with {len(cues)} imported cues?", "Replace"):
            return
        p.cues = [Cue(start=c.start, end=c.end, text=c.text) for c in cues]
        p.alignment.reviewed = False
        self._commit()

    def _export(self) -> None:
        p = self.project
        if not p or not p.cues:
            return
        default = str(self.ctrl.folder / "subtitles.srt")
        path, _ = QFileDialog.getSaveFileName(self, t("Export SRT"), default, "SubRip (*.srt)")
        if path:
            out = self.ctrl.export_srt(Path(path))
            self.ctrl.notify.emit("success", f"Saved {Path(out).name}")

    def _play_cue(self) -> None:
        i = self._sel_row()
        if 0 <= i < len(self._cues()):
            self.player.seek_to(self._cues()[i].start)
            if self.player.player and self.player.player.playbackState() != self.player.player.PlaybackState.PlayingState:
                self.player.toggle()

    def _selection(self) -> None:
        i = self._sel_row()
        cues = self._cues()
        self.player.wave.set_regions([(c.start, c.end) for c in cues], i)
        if 0 <= i < len(cues):
            self.player.seek_to(cues[i].start)

    def _follow(self, sec: float) -> None:
        pass  # waveform playhead follows automatically; avoid fighting the user's selection

    def _cell_changed(self, item: QTableWidgetItem) -> None:
        p = self.project
        if not p:
            return
        r, c = item.row(), item.column()
        if not (0 <= r < len(p.cues)):
            return
        cue = p.cues[r]
        try:
            if c == 1:
                cue.start = round(parse_ts(item.text()), 3)
            elif c == 2:
                cue.end = round(parse_ts(item.text()), 3)
            elif c == 4:
                cue.text = item.text().strip()
            else:
                return
        except ValueError:
            self.ctrl.notify.emit("error", f"'{item.text()}' is not a valid time. Use 0:00:01.250 or seconds.")
        self.edit("subtitles")
        self._fill(r)

    # ------------------------------------------------------------- refresh
    def _progress(self, key: str, frac: float, msg: str) -> None:
        if key == "align" and self.project:
            self.progress.setValue(int(frac * 1000))
            self.status.set_task(self.project.alignment.task, msg)

    def _fill(self, select: int | None = None) -> None:
        p = self.project
        if not p:
            return
        cues = p.cues
        issues = validate(cues, p.voice.duration or None)
        by_row: dict[int, list] = {}
        for iss in issues:
            by_row.setdefault(iss.index, []).append(iss)
        with QSignalBlocker(self.table):
            self.table.setRowCount(len(cues))
            for r, cue in enumerate(cues):
                vals = [str(r + 1), fmt_ts(cue.start, "."), fmt_ts(cue.end, "."), f"{cue.end - cue.start:.2f}s", cue.text]
                errs = by_row.get(r, [])
                sev = "error" if any(i.severity == "error" for i in errs) else "warning" if errs else ""
                vals.append("; ".join(i.message for i in errs) or "✓")
                for c, v in enumerate(vals):
                    it = self.table.item(r, c)
                    if it is None:
                        it = QTableWidgetItem()
                        self.table.setItem(r, c, it)
                    it.setText(v)
                    flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
                    if c in (1, 2, 4):
                        flags |= Qt.ItemFlag.ItemIsEditable
                    it.setFlags(flags)
                    bg = QColor(C["danger_soft"]) if sev == "error" else QColor(C["warning_soft"]) if sev else QColor(0, 0, 0, 0)
                    it.setBackground(bg)
                    if c == 5:
                        it.setForeground(QColor(C["danger"] if sev == "error" else C["warning"] if sev else C["success"]))
                        it.setToolTip(vals[5])
            self.table.resizeRowsToContents()
        if select is not None and 0 <= select < len(cues):
            self.table.selectRow(select)
        n_err = sum(1 for i in issues if i.severity == "error")
        n_warn = len(issues) - n_err
        if not cues:
            self.issues.set("info", t("No cues yet. Run alignment, import an SRT, or add cues manually."))
        elif n_err:
            self.issues.set("error", f"{n_err} {t('timing error(s)')} (overlap / negative / inverted) · {n_warn} {t('warning(s)')}. "
                            + t("Fix them or use Auto-fix before continuing."), "Auto-fix", self._autofix)
        elif n_warn:
            self.issues.set("warn", f"{len(cues)} cues · {n_warn} {t('warning(s)')} ({t('long or fast cues')}). "
                            + t("These don't block you."))
        else:
            self.issues.set("ok", f"{len(cues)} cues · {t('no timing problems found')}.")
        self.player.wave.set_regions([(c.start, c.end) for c in cues], self._sel_row())

    def refresh(self) -> None:
        p = self.project
        has_audio = bool(p and p.narration_take())
        self.empty.setVisible(not (p and (has_audio or p.cues)))
        self.body_w.setVisible(bool(p and (has_audio or p.cues)))
        self.review_btn.setVisible(bool(p and p.cues))
        if not p:
            self.player.release()
            return
        running = self.ctrl.jobs.is_running("align")
        self.run_btn.setEnabled(not running and has_audio)
        self.run_btn.setText(t("Re-align") if p.cues else t("Align subtitles"))
        self.stop_btn.setVisible(running)
        self.progress.setVisible(running)
        a = p.alignment
        self.status.set_task(a.task, self.ctrl.jobs.last_progress.get("align", (0, ""))[1])
        self.status.setVisible(a.task.state in ("running", "failed", "cancelled"))
        if a.precision_note:
            extra = f" {t('Engine')}: {a.engine} {a.model}."
            self.precision.set("info" if (a.method == "script" and (a.match_ratio or 0) >= 0.8) else "warn",
                               a.precision_note + extra)
        else:
            self.precision.set("info", "")
        self.stale.set("warn", t("These subtitles were aligned to a different narration take. Re-align so the timing "
                                 "matches the audio in use.") if self.ctrl.alignment_stale() else "")
        self.reviewed_badge.set("Reviewed" if a.reviewed else ("Needs review" if p.cues else "Not aligned"),
                                "ok" if a.reviewed else "warn" if p.cues else "neutral")
        self.player.load(self.ctrl.narration_audio(), self.ctrl.peaks, p.voice.duration)
        self._fill()


__all__ = ["SubtitlesPage", "hbox"]
