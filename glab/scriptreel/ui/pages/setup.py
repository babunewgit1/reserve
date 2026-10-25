"""C. Project setup page."""
from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout,
)

from ...core.i18n import t
from ...core.project import RESOLUTIONS
from ...services.voice_studio_client import LANGUAGE_CHOICES
from ..icons import pixmap
from ..theme import C
from ..widgets import (
    Banner, Card, EmptyState, Page, ResponsiveRow, Segmented, button, clear_layout, hbox, label, labeled,
)
from .common import ScriptEditor, fill_image_combo, fill_video_combo, fill_voice_combo, image_help, video_help


class SetupPage(Page):
    title_text = "Project setup"
    subtitle_text = "Everything the pipeline needs. Required items are marked with •; the rest have sensible defaults."

    def __init__(self, ctrl, parent=None) -> None:
        super().__init__(ctrl, parent)
        L = self.layout_
        self.next_btn = self.add_action(button("Continue to narration", "right", "primary",
                                               on_click=lambda: ctrl.request_page.emit("narration")))
        self.empty = EmptyState("clipboard", "No project open", "Create or open a project on the Welcome page.",
                                "Go to Welcome", lambda: ctrl.request_page.emit("welcome"), "home")
        L.addWidget(self.empty)
        self.content = QVBoxLayout()
        self.content.setSpacing(16)
        L.addLayout(self.content)

        # readiness
        self.ready_card = Card("Ready to generate?", "", "check-circle", accent=True)
        self.ready_list = QHBoxLayout()
        self.ready_list.setSpacing(18)
        self.ready_card.add(self.ready_list)
        self.content.addWidget(self.ready_card)

        cols = ResponsiveRow(16)
        left = cols.add_column(11)
        right = cols.add_column(10)
        self.content.addWidget(cols)

        # title + script
        sc = Card("Title & narration script", "", "file")
        self.title = QLineEdit()
        self.title.setObjectName("projectTitle")
        self.title.textEdited.connect(self._title)
        sc.add(labeled("• Project title", self.title))
        self.script = ScriptEditor(300)
        self.script.edited.connect(self._script)
        sc.add(labeled("• Narration script", self.script))
        left.addWidget(sc)

        # style
        st = Card("Visual style & continuity", "Project-wide style bible sent with every prompt. Edit more on the Scenes page.",
                  "palette")
        self.style = QPlainTextEdit()
        self.style.setFixedHeight(64)
        self.style.textChanged.connect(lambda: self._style("visual_style", self.style.toPlainText()))
        st.add(labeled("Visual style", self.style))
        self.chars = QPlainTextEdit()
        self.chars.setFixedHeight(64)
        self.chars.setPlaceholderText(t("e.g. Maya — a curious 10-year-old girl with curly black hair, yellow raincoat"))
        self.chars.textChanged.connect(lambda: self._style("characters", self.chars.toPlainText()))
        st.add(labeled("Recurring characters", self.chars, "Describe each character the same way every time for consistency."))
        left.addWidget(st)
        left.addStretch(1)

        # voice
        vc = Card("Voice", "From G-Labs Voice Studio's saved presets.", "mic")
        self.voice = QComboBox()
        self.voice.setObjectName("setupVoice")
        self.voice.currentIndexChanged.connect(self._voice)
        reload_btn = button("", "refresh", "ghost", "Reload presets (GET /api/voices)", on_click=ctrl.load_voices)
        vc.add(labeled("• Voice preset", hbox(self.voice, reload_btn)))
        self.voice_hint = label("", "Help", wrap=True)
        vc.add(self.voice_hint)
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        self.lang = QComboBox()
        self.lang.addItems(LANGUAGE_CHOICES)
        self.lang.currentTextChanged.connect(self._lang)
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.5, 2.0)
        self.speed.setSingleStep(0.05)
        self.speed.setPrefix("×")
        self.speed.valueChanged.connect(self._speed)
        g.addWidget(labeled("• Language", self.lang), 0, 0)
        g.addWidget(labeled("Speed", self.speed), 0, 1)
        vc.add(g)
        right.addWidget(vc)

        # visuals
        mc = Card("Visual models", "Options come from the local model catalog — availability depends on your G-Labs "
                  "accounts.", "layers")
        self.aspect = Segmented([("16:9", "16:9 Landscape"), ("9:16", "9:16 Vertical")])
        self.aspect.changed.connect(self._aspect)
        mc.add(labeled("• Aspect ratio", self.aspect))
        self.image_model = QComboBox()
        self.image_model.currentIndexChanged.connect(self._image_model)
        mc.add(labeled("• Image model", self.image_model))
        self.image_help = label("", "Help", wrap=True)
        self.image_help.setTextFormat(Qt.TextFormat.RichText)
        mc.add(self.image_help)
        self.video = QComboBox()
        self.video.currentIndexChanged.connect(self._video)
        mc.add(labeled("• Video model / mode", self.video, tip="Veo/Omni use /api/video/generate with a model value. Grok "
                       "and Meta use their own routes with modes (t2v / i2v), not model IDs."))
        self.video_help = label("", "Help", wrap=True)
        self.video_help.setTextFormat(Qt.TextFormat.RichText)
        mc.add(self.video_help)
        right.addWidget(mc)

        # format & workflow
        fc = Card("Format & workflow", "", "sliders")
        g2 = QGridLayout()
        g2.setHorizontalSpacing(12)
        g2.setVerticalSpacing(10)
        self.clip_mode = Segmented([("flexible", "Flexible 3–10 s"), ("fixed8", "Fixed 8 s")])
        self.clip_mode.changed.connect(self._clip_mode)
        g2.addWidget(labeled("Clip duration", self.clip_mode), 0, 0, 1, 2)
        self.out_res = QComboBox()
        for r in RESOLUTIONS:
            self.out_res.addItem(r, r)
        self.out_res.currentIndexChanged.connect(lambda: self._render("resolution", self.out_res.currentData()))
        g2.addWidget(labeled("Output resolution", self.out_res), 1, 0)
        self.run_mode = Segmented([("manual", "Review mode"), ("automatic", "Automatic")])
        self.run_mode.changed.connect(self._run_mode)
        g2.addWidget(labeled("Run mode", self.run_mode, tip="Review mode pauses for subtitles, prompts and image approval. "
                             "Automatic runs unattended (still stops on errors)."), 1, 1)
        fc.add(g2)
        self.burn = QCheckBox(t("Burn subtitles into the video (an .srt is always exported)"))
        self.burn.toggled.connect(lambda v: self._setting("burn_subtitles", v))
        self.yt = QCheckBox(t("Create a YouTube metadata package"))
        self.yt.toggled.connect(lambda v: self._setting("youtube_metadata", v))
        self.chain = QCheckBox(t("Chain scenes using the previous clip's last frame"))
        self.chain.setToolTip(t("Scene N+1 starts from the exact last frame of scene N for seamless motion. Clips are then "
                                "generated one after another (slower) and the duplicated boundary frame is trimmed."))
        self.chain.toggled.connect(self._chain)
        self.review = QCheckBox(t("Review prompts before generating images"))
        self.review.toggled.connect(lambda v: self._setting("review_prompts", v))
        self.approve = QCheckBox(t("Require image approval before clips (review mode)"))
        self.approve.toggled.connect(lambda v: self._setting("require_image_approval", v))
        for w in (self.burn, self.yt, self.chain, self.review, self.approve):
            fc.add(w)
        right.addWidget(fc)
        right.addStretch(1)

        ctrl.project_loaded.connect(self.mark_stale)
        ctrl.project_closed.connect(self.mark_stale)
        ctrl.voices_changed.connect(self.mark_stale)
        ctrl.changed.connect(lambda a: a in ("catalog", "setup", "voice") and self.mark_stale())
        ctrl.conn_changed.connect(self._readiness)

    # ------------------------------------------------------------- edits
    def _title(self, v: str) -> None:
        if self.project:
            self.project.settings.title = v.strip() or "Untitled explainer"
            self.edit("setup")
            self._readiness()

    def _script(self, v: str) -> None:
        if self.project:
            self.project.script = v
            self.edit("setup")
            self._readiness()

    def _style(self, attr: str, v: str) -> None:
        if self.project and getattr(self.project.style, attr) != v:
            setattr(self.project.style, attr, v)
            self.edit("style")

    def _voice(self) -> None:
        p = self.project
        if not p:
            return
        vid = self.voice.currentData() or ""
        vs = p.voice_settings
        vs.preset_id = vid
        v = next((x for x in self.ctrl.voices if x.id == vid), None)
        if v:
            vs.preset_name, vs.preset_tags = v.name, list(v.tags)
        elif not vid:
            vs.preset_name, vs.preset_tags = "", []
        self.edit("voice")
        self._readiness()

    def _lang(self, v: str) -> None:
        if self.project:
            self.project.voice_settings.language = v
            self.edit("voice")

    def _speed(self, v: float) -> None:
        if self.project:
            self.project.voice_settings.speed = round(v, 2)
            self.script.set_speed(v)
            self.edit("voice")

    def _aspect(self, v: str) -> None:
        if self.project:
            self.project.settings.aspect_ratio = v
            self.edit("setup")
            self._update_help()

    def _image_model(self) -> None:
        if self.project and self.image_model.currentData():
            self.project.settings.image_model = self.image_model.currentData()
            self.edit("setup")
            self._update_help()
            self._readiness()

    def _video(self) -> None:
        vid = self.video.currentData()
        if self.project and vid:
            self.project.settings.video_option = vid
            self.ctrl.update_gen_lengths()
            self.edit("videos")
            self._update_help()
            self._readiness()

    def _clip_mode(self, v: str) -> None:
        if self.project:
            self.project.settings.clip_mode = v
            self.edit("setup")

    def _run_mode(self, v: str) -> None:
        if self.project:
            self.project.settings.run_mode = v
            self.edit("setup")

    def _setting(self, attr: str, v) -> None:
        if self.project:
            setattr(self.project.settings, attr, v)
            self.edit("setup")

    def _chain(self, v: bool) -> None:
        if self.project:
            self.project.settings.chain_frames = v
            self.ctrl.update_gen_lengths()
            self.edit("videos")

    def _render(self, attr: str, v) -> None:
        if self.project and v:
            setattr(self.project.render, attr, v)
            self.edit("render")

    # ------------------------------------------------------------- refresh
    def _update_help(self) -> None:
        p = self.project
        if not p:
            return
        ie = self.ctrl.catalog.image(p.settings.image_model)
        txt = image_help(ie)
        if ie and p.settings.aspect_ratio not in ie.aspect_ratios:
            txt = f"<span style='color:{C['danger']}'>⚠ {ie.label} {t('does not support')} {p.settings.aspect_ratio}.</span><br>" + txt
        self.image_help.setText(txt)
        ve = self.ctrl.catalog.video(p.settings.video_option)
        txt = video_help(ve, self.ctrl)
        if ve and p.settings.aspect_ratio not in ve.aspect_ratios:
            txt = f"<span style='color:{C['danger']}'>⚠ {ve.label} {t('does not support')} {p.settings.aspect_ratio}.</span><br>" + txt
        self.video_help.setText(txt)

    def _readiness(self) -> None:
        p = self.project
        if not p:
            return
        clear_layout(self.ready_list)
        items = [
            ("Title", bool(p.settings.title.strip())),
            ("Script", bool(p.script.strip())),
            ("Voice preset", bool(p.voice_settings.preset_id)),
            ("Image model", self.ctrl.image_entry_for() is not None),
            ("Video option", self.ctrl.video_entry_for() is not None),
            ("Voice Studio", self.ctrl.conn["voice"].state == "ok"),
            ("G-Labs Studio", self.ctrl.conn["glabs"].state == "ok"),
        ]
        for name, ok in items:
            box = QHBoxLayout()
            box.setSpacing(5)
            ic = QLabel()
            ic.setPixmap(pixmap("check-circle" if ok else "alert", C["success"] if ok else C["warning"], 15))
            box.addWidget(ic)
            box.addWidget(label(t(name), "Help"))
            self.ready_list.addLayout(box)
        self.ready_list.addStretch(1)
        done = all(ok for _, ok in items[:5])
        self.ready_card.title_label.setText(t("Ready — continue to Narration & voice") if done else t("Ready to generate?"))

    def refresh(self) -> None:
        p = self.project
        has = p is not None
        self.empty.setVisible(not has)
        for i in range(self.content.count()):
            w = self.content.itemAt(i).widget()
            if w:
                w.setVisible(has)
        self.ready_card.setVisible(has)
        self.next_btn.setVisible(has)
        self._set_layout_visible(has)
        if not p:
            return
        with QSignalBlocker(self.title):
            if self.title.text() != p.settings.title:
                self.title.setText(p.settings.title)
        self.script.set_speed(p.voice_settings.speed)
        self.script.set_text(p.script)
        for w, attr in ((self.style, "visual_style"), (self.chars, "characters")):
            if w.toPlainText() != getattr(p.style, attr):
                with QSignalBlocker(w):
                    w.setPlainText(getattr(p.style, attr))
        vs = p.voice_settings
        fill_voice_combo(self.voice, self.ctrl.voices, vs.preset_id, vs.preset_name)
        self.voice_hint.setText("" if self.ctrl.voices else t("No presets loaded — connect Voice Studio (Settings) and press "
                                                              "the refresh button. Saved choices are kept."))
        with QSignalBlocker(self.lang):
            if self.lang.findText(vs.language) < 0:
                self.lang.addItem(vs.language)
            self.lang.setCurrentText(vs.language)
        with QSignalBlocker(self.speed):
            self.speed.setValue(vs.speed)
        s = p.settings
        self.aspect.set_value(s.aspect_ratio)
        fill_image_combo(self.image_model, self.ctrl.catalog, s.image_model)
        fill_video_combo(self.video, self.ctrl.catalog, s.video_option)
        self.clip_mode.set_value(s.clip_mode)
        self.run_mode.set_value(s.run_mode)
        with QSignalBlocker(self.out_res):
            self.out_res.setCurrentIndex(max(0, self.out_res.findData(p.render.resolution)))
        for w, v in ((self.burn, s.burn_subtitles), (self.yt, s.youtube_metadata), (self.chain, s.chain_frames),
                     (self.review, s.review_prompts), (self.approve, s.require_image_approval)):
            with QSignalBlocker(w):
                w.setChecked(v)
        self._update_help()
        self._readiness()

    def _set_layout_visible(self, on: bool) -> None:
        def walk(lay):
            for i in range(lay.count()):
                it = lay.itemAt(i)
                if it.widget():
                    it.widget().setVisible(on)
                elif it.layout():
                    walk(it.layout())
        walk(self.content)


__all__ = ["SetupPage", "Banner"]
