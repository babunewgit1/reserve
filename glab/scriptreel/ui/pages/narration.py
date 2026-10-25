"""D. Narration & voice page."""
from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QListWidget, QListWidgetItem, QProgressBar, QSpinBox,
    QVBoxLayout, QWidget,
)

from ...core.i18n import t
from ...services.voice_studio_client import LANGUAGE_CHOICES
from ..media import AudioPlayer
from ..widgets import (
    Badge, Banner, Card, EmptyState, Page, ResponsiveRow, Segmented, StatusLine, button, fmt_age, fmt_dur, hbox, label,
    labeled,
)
from .common import ScriptEditor, fill_voice_combo


class NarrationPage(Page):
    title_text = "Narration & voice"
    subtitle_text = "Generate the voiceover with G-Labs Voice Studio. Every take is kept; choose which one the video uses."

    def __init__(self, ctrl, parent=None) -> None:
        super().__init__(ctrl, parent)
        L = self.layout_
        self.next_btn = self.add_action(button("Continue to subtitles", "right", "primary",
                                               on_click=lambda: ctrl.request_page.emit("subtitles")))
        self.empty = EmptyState("mic", "No project open", "Create or open a project first.", "Go to Welcome",
                                lambda: ctrl.request_page.emit("welcome"), "home")
        L.addWidget(self.empty)
        self.body_w = ResponsiveRow(16)
        L.addWidget(self.body_w)

        # left: script
        left = self.body_w.add_column(11)
        sc = Card("Narration script", "Exactly what will be spoken. Subtitles are aligned to this text.", "file")
        self.stale = Banner("warn", "")
        sc.add(self.stale)
        self.script = ScriptEditor(380)
        self.script.edited.connect(self._script)
        sc.add(self.script)
        left.addWidget(sc, 1)

        # right: voice + output
        right = self.body_w.add_column(10)
        vc = Card("Voice", "Presets are loaded from Voice Studio (GET /api/voices).", "mic")
        self.preset = QComboBox()
        self.preset.setObjectName("voicePreset")
        self.preset.currentIndexChanged.connect(self._preset)
        vc.add(labeled("Voice preset", hbox(self.preset, button("", "refresh", "ghost", "Reload voice presets",
                                                                on_click=ctrl.load_voices))))
        self.tags = QHBoxLayout()
        self.tags.setSpacing(6)
        vc.add(self.tags)
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        self.lang = QComboBox()
        self.lang.addItems(LANGUAGE_CHOICES)
        self.lang.currentTextChanged.connect(lambda v: self._vs("language", v))
        g.addWidget(labeled("Language", self.lang), 0, 0)
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.5, 2.0)
        self.speed.setSingleStep(0.05)
        self.speed.setPrefix("×")
        self.speed.valueChanged.connect(self._speed)
        g.addWidget(labeled("Speed", self.speed), 0, 1)
        self.fmt = Segmented([("wav", "WAV"), ("mp3", "MP3")])
        self.fmt.changed.connect(lambda v: self._vs("output_format", v))
        g.addWidget(labeled("Output format", self.fmt), 1, 0)
        self.steps = QSpinBox()
        self.steps.setRange(0, 128)
        self.steps.setSpecialValueText(t("App default"))
        self.steps.setToolTip(t("Optional num_step (diffusion steps). 0 = let Voice Studio decide."))
        self.steps.valueChanged.connect(lambda v: self._vs("num_step", v or None))
        g.addWidget(labeled("Quality steps", self.steps), 1, 1)
        vc.add(g)
        row = QHBoxLayout()
        self.preview_btn = button("Preview voice", "play", "soft", "Generates a short excerpt (first sentence or two) "
                                  "with the same settings. Uses Voice Studio, not a local voice.",
                                  on_click=lambda: ctrl.generate_voice(preview=True))
        row.addWidget(self.preview_btn)
        self.gen_btn = button("Generate voiceover", "sparkles", "primary", on_click=self._generate)
        self.gen_btn.setObjectName("btnGenerateVoice")
        row.addWidget(self.gen_btn)
        self.stop_btn = button("Stop", "stop", "danger", "Stops polling. Voice Studio has no cancel endpoint, so the "
                               "task may still finish there.", on_click=lambda: ctrl.jobs.cancel("voice"))
        row.addWidget(self.stop_btn)
        self.resume_btn = button("Resume polling", "refresh", None, on_click=ctrl.resume_voice)
        row.addWidget(self.resume_btn)
        row.addStretch(1)
        vc.add(row)
        self.progress = QProgressBar()
        self.progress.setProperty("thin", "true")
        self.progress.setRange(0, 1000)
        vc.add(self.progress)
        self.status = StatusLine()
        vc.add(self.status)
        self.preview_player = AudioPlayer(36)
        self.preview_player.wave.empty_text = t("Preview plays here")
        self.preview_box = labeled("Voice preview", self.preview_player)
        vc.add(self.preview_box)
        right.addWidget(vc)

        oc = Card("Narration audio", "", "music")
        self.player = AudioPlayer(76)
        oc.add(self.player)
        self.audio_meta = label("", "Help", wrap=True, selectable=True)
        oc.add(self.audio_meta)
        oc.add(label(t("Takes"), "FieldLabel"))
        self.takes = QListWidget()
        self.takes.setMaximumHeight(130)
        self.takes.itemDoubleClicked.connect(self._use_take)
        oc.add(self.takes)
        oc.add(hbox(button("Use selected take", "check", "soft", on_click=lambda: self._use_take(self.takes.currentItem())),
                    button("Open folder", "folder-open", "ghost", on_click=self._open_folder), None))
        right.addWidget(oc)
        right.addStretch(1)

        ctrl.project_loaded.connect(self.mark_stale)
        ctrl.project_closed.connect(self.mark_stale)
        ctrl.voices_changed.connect(self.mark_stale)
        ctrl.peaks_changed.connect(self.mark_stale)
        ctrl.task_changed.connect(self._task)
        ctrl.changed.connect(lambda a: a in ("voice", "setup") and self.mark_stale())
        ctrl.jobs.progress.connect(self._progress)
        ctrl.about_to_render.connect(self.player.release)

    # ------------------------------------------------------------- edits
    def _script(self, v: str) -> None:
        if self.project:
            self.project.script = v
            self.edit("setup")
            self._update_stale()

    def _preset(self) -> None:
        p = self.project
        if not p:
            return
        vid = self.preset.currentData() or ""
        vs = p.voice_settings
        vs.preset_id = vid
        v = next((x for x in self.ctrl.voices if x.id == vid), None)
        if v:
            vs.preset_name, vs.preset_tags = v.name, list(v.tags)
        self.edit("voice")
        self._render_tags()

    def _vs(self, attr: str, v) -> None:
        if self.project:
            setattr(self.project.voice_settings, attr, v)
            self.edit("voice")

    def _speed(self, v: float) -> None:
        self._vs("speed", round(v, 2))
        self.script.set_speed(v)

    def _generate(self) -> None:
        p = self.project
        if not p:
            return
        if p.narration_take() and p.cues:
            from ..widgets import confirm
            if not confirm(self, "Generate a new take?", "A new take will be added (existing takes are kept). Subtitles "
                                                         "must be re-aligned to the new audio afterwards.", "Generate"):
                return
        self.ctrl.generate_voice()

    def _use_take(self, item: QListWidgetItem | None) -> None:
        if item is not None:
            self.ctrl.select_take(item.data(Qt.ItemDataRole.UserRole))
            self.mark_stale()

    def _open_folder(self) -> None:
        if self.ctrl.folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctrl.folder / "assets" / "voice")))

    # ------------------------------------------------------------- live updates
    def _task(self, key: str) -> None:
        if key == "voice":
            self._update_task()
            if not self.ctrl.jobs.is_running("voice"):
                self.mark_stale()
        elif key == "voice_preview":
            self._update_task()
            if self.ctrl.preview_audio:
                self.preview_player.load(self.ctrl.preview_audio)
                self.preview_player.toggle()

    def _progress(self, key: str, frac: float, msg: str) -> None:
        if key in ("voice", "voice_preview") and self.project:
            self.progress.setValue(int(frac * 1000))
            self.status.set_task(self.project.voice.task, msg)

    def _update_task(self) -> None:
        p = self.project
        if not p:
            return
        running = self.ctrl.jobs.is_running("voice")
        prev_running = self.ctrl.jobs.is_running("voice_preview")
        self.gen_btn.setEnabled(not running)
        self.preview_btn.setEnabled(not running and not prev_running)
        self.stop_btn.setVisible(running)
        self.resume_btn.setVisible(not running and p.voice.task.state == "interrupted" and bool(p.voice.task.task_id))
        self.progress.setVisible(running or prev_running)
        if not running:
            self.progress.setValue(0)
        prog = self.ctrl.jobs.last_progress.get("voice", (0, ""))[1]
        self.status.set_task(p.voice.task, prog)
        self.status.setVisible(p.voice.task.state != "idle" or running)
        self.preview_box.setVisible(prev_running or self.ctrl.preview_audio is not None)

    def _render_tags(self) -> None:
        while self.tags.count():
            it = self.tags.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        p = self.project
        if not p:
            return
        for tag in p.voice_settings.preset_tags[:8]:
            self.tags.addWidget(Badge(tag, "primary"))
        self.tags.addStretch(1)

    def _update_stale(self) -> None:
        p = self.project
        if not p:
            return
        changed = bool(p.voice.script_hash and p.voice.script_hash != self.ctrl.script_hash(p.script))
        self.stale.set("warn", t("The script changed after the current narration take was generated. Generate a new take "
                                 "so the audio matches the text.") if changed else "")

    def refresh(self) -> None:
        p = self.project
        self.empty.setVisible(p is None)
        self.body_w.setVisible(p is not None)
        self.next_btn.setVisible(p is not None)
        if not p:
            self.player.release()
            return
        vs = p.voice_settings
        self.script.set_speed(vs.speed)
        self.script.set_text(p.script)
        fill_voice_combo(self.preset, self.ctrl.voices, vs.preset_id, vs.preset_name)
        with QSignalBlocker(self.lang):
            if self.lang.findText(vs.language) < 0:
                self.lang.addItem(vs.language)
            self.lang.setCurrentText(vs.language)
        with QSignalBlocker(self.speed):
            self.speed.setValue(vs.speed)
        with QSignalBlocker(self.steps):
            self.steps.setValue(vs.num_step or 0)
        self.fmt.set_value(vs.output_format)
        self._render_tags()
        self._update_stale()
        self._update_task()
        # audio
        take = p.narration_take()
        path = self.ctrl.narration_audio()
        self.player.load(path, self.ctrl.peaks, p.voice.duration)
        if take:
            self.audio_meta.setText(f"{t('Duration')} {fmt_dur(p.voice.duration)} · {take.prompt} · "
                                    f"{t('file')} {p.voice.narration_file or take.path}"
                                    + (f" · task {take.task_id}" if take.task_id else ""))
        else:
            self.audio_meta.setText(t("No narration yet. Choose a voice and press Generate voiceover."))
        with QSignalBlocker(self.takes):
            self.takes.clear()
            for i, tk in enumerate(p.voice.takes):
                cur = "  ✔ " + t("in use") if i == p.voice.selected_take else ""
                it = QListWidgetItem(f"{t('Take')} {i + 1} · {fmt_dur(tk.duration)} · {tk.prompt} · {fmt_age(tk.created_at)}{cur}")
                it.setData(Qt.ItemDataRole.UserRole, i)
                it.setToolTip(tk.path)
                self.takes.addItem(it)
            if p.voice.selected_take >= 0:
                self.takes.setCurrentRow(p.voice.selected_take)
