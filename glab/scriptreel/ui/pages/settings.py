"""B. Connections and settings page."""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QHeaderView, QLineEdit,
    QSizePolicy, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...core import secrets as sec
from ...core.catalog import ensure_user_catalog, reset_user_catalog
from ...core.i18n import LANGUAGES, t
from ...core.paths import config_dir, logs_dir
from ...services import tasks
from ...services.prompt_provider import PROVIDERS
from ..theme import C
from ..widgets import (
    Badge, Banner, Card, Page, PathField, ResponsiveRow, SecretField, button, confirm, hbox, label, labeled, show_info,
    tool_button,
)
from .welcome import CONN_TONES

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3", "distil-large-v3", "large-v3-turbo"]


class ServiceCard(Card):
    def __init__(self, page: "SettingsPage", which: str, title: str, subtitle: str, url_attr: str, default_url: str,
                 key_name: str, notes: str) -> None:
        super().__init__(title, subtitle, "plug")
        self.page, self.which, self.url_attr, self.default_url = page, which, url_attr, default_url
        ctrl = page.ctrl
        self.badge = self.add_action(Badge("Unknown"))
        self.url = QLineEdit(getattr(ctrl.settings, url_attr))
        self.url.setPlaceholderText(default_url)
        self.url.setObjectName(f"{which}BaseUrl")
        self.url.editingFinished.connect(self._save_url)
        reset = button("Default", None, "ghost", f"Reset to {default_url}", on_click=self._reset_url)
        self.add(labeled("Base URL", hbox(self.url, reset),
                         "Loopback (127.0.0.1) keeps the server private. Never expose these servers to the internet."))
        self.key = SecretField(ctrl.secrets, key_name)
        self.key.saved.connect(lambda: ctrl.refresh_connections((which,)))
        self.add(labeled("API key", self.key))
        row = QHBoxLayout()
        self.test_btn = button("Test connection", "bolt", "primary", on_click=self.test)
        self.test_btn.setObjectName(f"btnTest_{which}")
        row.addWidget(self.test_btn)
        row.addStretch(1)
        self.add(row)
        self.status = label("", "Help", wrap=True, selectable=True)
        self.add(self.status)
        self.add(label(t(notes), "Faint", wrap=True))

    def _save_url(self) -> None:
        v = self.url.text().strip().rstrip("/") or self.default_url
        setattr(self.page.ctrl.settings, self.url_attr, v)
        self.page.ctrl.save_settings()

    def _reset_url(self) -> None:
        self.url.setText(self.default_url)
        self._save_url()

    def test(self) -> None:
        self._save_url()
        self.page.ctrl.refresh_connections((self.which,))

    def refresh(self) -> None:
        st = self.page.ctrl.conn[self.which]
        tone = CONN_TONES.get(st.state, "neutral")
        self.badge.set({"ok": "Connected", "warn": "Reachable · key problem", "error": "Not reachable",
                        "checking": "Checking…", "unknown": "Not checked"}.get(st.state, st.state), tone)
        lines = [st.message]
        if st.hint:
            lines.append("→ " + st.hint)
        if st.details:
            lines.append(st.details)
        self.status.setText("\n".join(x for x in lines if x))
        self.key.refresh()


class SettingsPage(Page):
    title_text = "Connections & settings"
    subtitle_text = "Local app connections, credentials, tools and defaults. API keys are stored in the OS credential vault."

    def __init__(self, ctrl, parent=None) -> None:
        super().__init__(ctrl, parent)
        s = ctrl.settings
        L = self.layout_
        self.add_action(button("Refresh connections", "refresh", "soft",
                               "Health + key check only. Does not refresh the model catalog.",
                               on_click=lambda: ctrl.refresh_connections()))
        L.addWidget(Banner("info", t("<b>Refresh connections</b> calls each app's <code>/api/health</code> and verifies your key. "
                                     "It never fetches model names — G-Labs Studio has no documented model-list API, so the "
                                     "models shown in this app come from the local, editable model catalog below.")))

        # --- services
        grid = ResponsiveRow(16)
        self.voice_card = ServiceCard(self, "voice", "G-Labs Voice Studio", "Narration audio · voice presets",
                                      "voice_base_url", "http://127.0.0.1:8766", sec.VOICE_KEY,
                                      "Voice Studio → Settings → Webhook API: start the server and copy the key. Voice "
                                      "presets come from GET /api/voices. Voice Studio returns audio only; subtitles "
                                      "are created by this app.")
        self.glabs_card = ServiceCard(self, "glabs", "G-Labs Studio", "Images · video clips",
                                      "glabs_base_url", "http://127.0.0.1:8765", sec.GLABS_KEY,
                                      "Requires a G-Labs MAX license (webhook API). Generation runs on the accounts you are "
                                      "logged into inside G-Labs Studio and uses their quotas and plan limits.")
        grid.addWidget(self.voice_card, 1)
        grid.addWidget(self.glabs_card, 1)
        L.addWidget(grid)

        # --- catalog
        cat = Card("Model catalog", "Local, versioned list of documented G-Labs image models and video options.", "layers")
        self.cat_meta = label("", "Help", wrap=True, selectable=True)
        cat.add(self.cat_meta)
        self.cat_warn = Banner("warn", "")
        cat.add(self.cat_warn)
        self.cat_table = QTableWidget(0, 7)
        self.cat_table.setHorizontalHeaderLabels([t("Option"), t("Kind"), t("API route"), t("model / mode"), t("Ratios"),
                                                  t("Native durations"), t("Requirements")])
        self.cat_table.verticalHeader().setVisible(False)
        self.cat_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cat_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.cat_table.setAlternatingRowColors(True)
        self.cat_table.setWordWrap(True)
        hh = self.cat_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.cat_table.setMinimumHeight(260)
        cat.add(self.cat_table)
        self.ultra = QCheckBox(t("My Google accounts in G-Labs are ULTRA (unlocks 4 s / 6 s Veo clips, 4K and ULTRA-only options)"))
        self.ultra.setChecked(s.google_ultra)
        self.ultra.toggled.connect(self._ultra)
        cat.add(self.ultra)
        cat.add(hbox(
            button("Edit catalog file", "file", "soft", "Copies the bundled catalog to your settings folder (if needed) "
                   "and opens it in your editor.", on_click=self._open_catalog),
            button("Reload catalog", "refresh", None, "Re-read the JSON file (no network call).", on_click=self._reload_catalog),
            button("Reset to bundled", None, "ghost", on_click=self._reset_catalog),
            None))
        L.addWidget(cat)

        # --- prompt LLM
        llm = Card("Prompt generation (LLM)", "Writes image and motion prompts and the optional YouTube package. "
                   "Optional — without it you can draft prompts from the narration or write them yourself.", "sparkles")
        self.provider = QComboBox()
        for pid, cls in PROVIDERS.items():
            self.provider.addItem(t(cls.label), pid)
        self.provider.setCurrentIndex(max(0, self.provider.findData(s.llm_provider)))
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self.llm_base = QLineEdit(s.llm_base_url)
        self.llm_base.editingFinished.connect(self._llm_save)
        self.llm_model = QComboBox()
        self.llm_model.setEditable(True)
        self.llm_model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.llm_model.setObjectName("llmModel")
        self.llm_model.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.llm_model.setCurrentText(s.llm_model)
        self.llm_model.lineEdit().editingFinished.connect(self._llm_save)
        self.llm_model.activated.connect(lambda *_: self._llm_save())
        self.llm_refresh = tool_button("refresh", "Fetch the model list from the provider",
                                       on_click=lambda: self._llm_models(auto=False))
        self.llm_refresh.setObjectName("btnLlmModels")
        self.llm_temp = QDoubleSpinBox()
        self.llm_temp.setRange(0.0, 1.5)
        self.llm_temp.setSingleStep(0.1)
        self.llm_temp.setValue(s.llm_temperature)
        self.llm_temp.valueChanged.connect(self._llm_save)
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(10)
        g.addWidget(labeled("Provider", self.provider), 0, 0)
        g.addWidget(labeled("Model", hbox(self.llm_model, self.llm_refresh, stretch_at=None)), 0, 1)
        self.llm_base_box = labeled("Base URL", self.llm_base, "Leave empty for the provider default.")
        g.addWidget(self.llm_base_box, 1, 0)
        self.llm_temp_box = labeled("Temperature", self.llm_temp)
        g.addWidget(self.llm_temp_box, 1, 1)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        llm.add(g)
        self.llm_key_holder = QVBoxLayout()
        llm.add(self.llm_key_holder)
        self.llm_status = label("", "Help", wrap=True, selectable=True)
        self.llm_test = button("Test prompt provider", "bolt", "soft", on_click=self._llm_test_run)
        llm.add(hbox(self.llm_test, None))
        llm.add(self.llm_status)
        L.addWidget(llm)
        self._llm_key_field: SecretField | None = None
        self._provider_changed(save=False)
        self._llm_models(auto=True)

        # --- tools + alignment row
        row = ResponsiveRow(16)
        ff = Card("FFmpeg & ffprobe", "Used for frame extraction, trimming, waveform and the final render.", "film")
        self.ffmpeg = PathField("file", "Auto-detect (bin\\ffmpeg.exe or PATH)", "Programs (*.exe);;All files (*)")
        self.ffmpeg.set_text(s.ffmpeg_path)
        self.ffmpeg.changed.connect(lambda v: self._set("ffmpeg_path", v))
        self.ffprobe = PathField("file", "Auto-detect (bin\\ffprobe.exe or PATH)", "Programs (*.exe);;All files (*)")
        self.ffprobe.set_text(s.ffprobe_path)
        self.ffprobe.changed.connect(lambda v: self._set("ffprobe_path", v))
        ff.add(labeled("ffmpeg executable", self.ffmpeg))
        ff.add(labeled("ffprobe executable", self.ffprobe))
        ff.add(hbox(button("Verify FFmpeg", "check", "soft", on_click=self._verify_ffmpeg), None))
        self.ff_status = label("", "Help", wrap=True, selectable=True)
        ff.add(self.ff_status)
        ff.add(label(t("Install with `winget install Gyan.FFmpeg`, or copy ffmpeg.exe and ffprobe.exe into the app's bin "
                       "folder. A build with libass is needed for burned-in subtitles."), "Faint", wrap=True))
        row.addWidget(ff, 1)

        al = Card("Subtitle alignment", "Runs locally on your PC. Voice Studio does not return subtitles.", "captions")
        self.engine = QComboBox()
        self.engine.addItem(t("Auto — faster-whisper if installed, else estimate"), "auto")
        self.engine.addItem(t("faster-whisper (speech recognition, script-guided)"), "faster_whisper")
        self.engine.addItem(t("Estimate from pauses (no ML, needs careful review)"), "estimate")
        self.engine.setCurrentIndex(max(0, self.engine.findData(s.alignment_engine)))
        self.engine.currentIndexChanged.connect(lambda: self._set("alignment_engine", self.engine.currentData()))
        al.add(labeled("Engine", self.engine))
        self.wmodel = QComboBox()
        self.wmodel.setEditable(True)
        self.wmodel.addItems(WHISPER_MODELS)
        self.wmodel.setCurrentText(s.whisper_model)
        self.wmodel.currentTextChanged.connect(lambda v: self._set("whisper_model", v.strip() or "small"))
        self.wdevice = QComboBox()
        self.wdevice.addItems(["auto", "cpu", "cuda"])
        self.wdevice.setCurrentText(s.whisper_device)
        self.wdevice.currentTextChanged.connect(lambda v: self._set("whisper_device", v))
        self.wcompute = QComboBox()
        self.wcompute.addItems(["auto", "int8", "int8_float16", "float16", "float32"])
        self.wcompute.setCurrentText(s.whisper_compute_type)
        self.wcompute.currentTextChanged.connect(lambda v: self._set("whisper_compute_type", v))
        gg = QGridLayout()
        gg.setHorizontalSpacing(10)
        gg.addWidget(labeled("Whisper model", self.wmodel), 0, 0)
        gg.addWidget(labeled("Device", self.wdevice), 0, 1)
        gg.addWidget(labeled("Compute", self.wcompute), 0, 2)
        al.add(gg)
        self.wdir = PathField("dir", "Default Hugging Face cache")
        self.wdir.set_text(s.whisper_model_dir)
        self.wdir.changed.connect(lambda v: self._set("whisper_model_dir", v))
        al.add(labeled("Model folder", self.wdir))
        al.add(hbox(button("Check model", "check", "soft", on_click=lambda: self._whisper(False)),
                    button("Download model", "down", None, "Downloads the selected model once (internet needed).",
                           on_click=lambda: self._whisper(True)), None))
        self.w_status = label("", "Help", wrap=True, selectable=True)
        al.add(self.w_status)
        al.add(label(t("faster-whisper is optional: pip install -r requirements-alignment.txt. Word timings come from speech "
                       "recognition guided by your script; they are typically within ~0.1–0.3 s, not frame-perfect — always "
                       "review the subtitles."), "Faint", wrap=True))
        row.addWidget(al, 1)
        L.addWidget(row)

        # --- generation & general
        row2 = ResponsiveRow(16)
        gen = Card("Generation & polling", "Timeouts and parallelism for asynchronous G-Labs tasks.", "cpu")
        g2 = QGridLayout()
        g2.setHorizontalSpacing(12)
        g2.setVerticalSpacing(10)

        def spin(attr, lo, hi, suffix, dbl=False, step=1.0):
            w = QDoubleSpinBox() if dbl else QSpinBox()
            w.setRange(lo, hi)
            if dbl:
                w.setSingleStep(step)
            w.setSuffix(suffix)
            w.setValue(getattr(s, attr))
            w.valueChanged.connect(lambda v, a=attr: self._set(a, v))
            return w

        g2.addWidget(labeled("Poll interval", spin("poll_interval_s", 2.0, 30.0, " s", True, 0.5)), 0, 0)
        g2.addWidget(labeled("HTTP timeout", spin("request_timeout_s", 5.0, 300.0, " s", True, 5)), 0, 1)
        g2.addWidget(labeled("Parallel G-Labs tasks", spin("max_parallel_tasks", 1, 12, "")), 0, 2)
        g2.addWidget(labeled("Voice timeout", spin("voice_task_timeout_s", 60, 14400, " s")), 1, 0)
        g2.addWidget(labeled("Image timeout", spin("image_task_timeout_s", 60, 7200, " s")), 1, 1)
        g2.addWidget(labeled("Video timeout", spin("video_task_timeout_s", 120, 14400, " s")), 1, 2)
        gen.add(g2)
        self.ref_mode = QComboBox()
        self.ref_mode.addItem(t("Auto — base64 on macOS; file path when G-Labs runs on this PC (Windows)"), "auto")
        self.ref_mode.addItem(t("Always base64 (works across machines, larger requests)"), "base64")
        self.ref_mode.addItem(t("Always file path (G-Labs must be allowed to read the project folder)"), "path")
        self.ref_mode.setCurrentIndex(max(0, self.ref_mode.findData(s.reference_transfer)))
        self.ref_mode.currentIndexChanged.connect(lambda: self._set("reference_transfer", self.ref_mode.currentData()))
        gen.add(labeled("Reference image transfer", self.ref_mode,
                        "Requests above 50 MB are rejected by G-Labs (HTTP 413)."))
        gen.add(label(t("Stopping a task only stops polling here: neither API has a cancel endpoint, so the remote app may "
                        "still finish the task and use quota."), "Faint", wrap=True))
        row2.addWidget(gen, 1)

        gl = Card("Projects, language & privacy", "", "shield")
        self.outdir = PathField("dir")
        self.outdir.set_text(s.output_dir)
        self.outdir.changed.connect(lambda v: self._set("output_dir", v))
        gl.add(labeled("Default projects folder", self.outdir))
        self.autosave = QCheckBox(t("Autosave project changes"))
        self.autosave.setChecked(s.autosave)
        self.autosave.toggled.connect(lambda v: self._set("autosave", v))
        gl.add(self.autosave)
        self.lang = QComboBox()
        for code, name in LANGUAGES.items():
            self.lang.addItem(name, code)
        self.lang.setCurrentIndex(max(0, self.lang.findData(s.language)))
        self.lang.currentIndexChanged.connect(self._lang)
        gl.add(labeled("Interface language", self.lang, "Takes effect after restarting the app."))
        self.sec_status = label("", "Help", wrap=True)
        gl.add(self.sec_status)
        gl.add(hbox(button("Clear all stored credentials", "trash", "danger", on_click=self._clear_creds),
                    button("Open logs folder", "folder", "ghost", on_click=lambda: QDesktopServices.openUrl(
                        QUrl.fromLocalFile(str(logs_dir())))), None))
        gl.add(label(t("Keys are never written to project.json, settings.json, logs, exported metadata or error dialogs. "
                       "Log lines are redacted automatically."), "Faint", wrap=True))
        row2.addWidget(gl, 1)
        L.addWidget(row2)
        L.addStretch(1)

        ctrl.conn_changed.connect(self.mark_stale)
        ctrl.changed.connect(lambda area: area == "catalog" and self.mark_stale())

    # ------------------------------------------------------------- helpers
    def _set(self, attr: str, value) -> None:
        setattr(self.ctrl.settings, attr, value)
        self.ctrl.save_settings()

    def _ultra(self, on: bool) -> None:
        self._set("google_ultra", on)
        if self.ctrl.project:
            self.ctrl.update_gen_lengths()
            self.ctrl.mark_dirty("videos")

    def _lang(self) -> None:
        self._set("language", self.lang.currentData())
        show_info(self, "Language", t("Restart ScriptReel Studio to apply the interface language."))

    def _open_catalog(self) -> None:
        p = ensure_user_catalog()
        self.ctrl.reload_catalog()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _reload_catalog(self) -> None:
        self.ctrl.reload_catalog()
        self.ctrl.notify.emit("info", f"Model catalog reloaded (v{self.ctrl.catalog.catalog_version}). No network call was made.")

    def _reset_catalog(self) -> None:
        if confirm(self, "Reset catalog", "Replace your edited catalog with the bundled one? Your copy is kept as "
                                          "model_catalog.previous.json.", "Reset"):
            reset_user_catalog()
            self.ctrl.reload_catalog()

    def _provider_changed(self, *_a, save: bool = True) -> None:
        pid = self.provider.currentData()
        cls = PROVIDERS.get(pid)
        if save:
            self.ctrl.settings.llm_provider = pid
            self.llm_model.clear()
            self.llm_model.setCurrentText("")
            self.llm_base.setText("")
            self._llm_save()
        self.llm_model.lineEdit().setPlaceholderText(cls.default_model if cls else "")
        self.llm_base.setPlaceholderText(cls.default_base_url if cls else "")
        if cls is not None:
            self.llm_base_box.field_label.setText(t(cls.base_label))
            if hasattr(self.llm_base_box, "help_label"):
                self.llm_base_box.help_label.setText(t(cls.base_help))
        none = pid == "none"
        for w in (self.llm_model, self.llm_base, self.llm_temp, self.llm_test):
            w.setEnabled(not none)
        self.llm_refresh.setEnabled(bool(cls and cls.can_list_models))
        self.llm_temp_box.setVisible(bool(cls is None or cls.uses_temperature))
        if self._llm_key_field is not None:
            self._llm_key_field.setParent(None)
            self._llm_key_field.deleteLater()
            self._llm_key_field = None
        while self.llm_key_holder.count():
            it = self.llm_key_holder.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        uses_key = not none and pid != "antigravity_cli"
        if uses_key:
            self._llm_key_field = SecretField(self.ctrl.secrets, sec.llm_key(pid),
                                              "Paste API key" + ("" if cls.needs_key else " (optional for local servers)"))
            self.llm_key_holder.addWidget(labeled("API key", self._llm_key_field, cls.key_help))
        if none:
            self.llm_status.setText(t("No provider: prompts are drafted from the narration or written by you."))
        elif pid == "antigravity_cli":
            self.llm_status.setText(t("Uses the Google account you are signed into in the Antigravity CLI — no API key. "
                                      "Usage counts against that account's plan."))
        else:
            self.llm_status.setText("")
        if save:
            self._llm_models(auto=True)

    def _llm_models(self, auto: bool) -> None:
        cls = PROVIDERS.get(self.ctrl.settings.llm_provider)
        if not cls or not cls.can_list_models:
            return
        params = self.ctrl.provider_params(require_key=False)
        if params is None:
            return
        if not auto:
            self.llm_status.setText(t("Fetching model list…"))
        pid = params["provider_id"]

        def done(_k, models) -> None:
            if self.ctrl.settings.llm_provider != pid:
                return
            current = self.llm_model.currentText().strip()
            self.llm_model.blockSignals(True)
            self.llm_model.clear()
            for mid, name in models:
                self.llm_model.addItem(mid, mid)
                self.llm_model.setItemData(self.llm_model.count() - 1, name, Qt.ItemDataRole.ToolTipRole)
            self.llm_model.setCurrentText(current)
            self.llm_model.blockSignals(False)
            self.llm_status.setText(t("Models available:") + f" {len(models)}. " +
                                    t("Pick one from the Model list, or type an ID."))

        def fail(_k, e) -> None:
            if not auto and self.ctrl.settings.llm_provider == pid:
                self.llm_status.setText(t("Failed:") + f" {self.ctrl._err_text(e)}")

        self.ctrl.start_job("llm_models", "Fetching LLM models", tasks.run_llm_models, params,
                            on_done=done, on_fail=fail)

    def _llm_save(self) -> None:
        s = self.ctrl.settings
        s.llm_model = self.llm_model.currentText().strip()
        s.llm_base_url = self.llm_base.text().strip()
        s.llm_temperature = float(self.llm_temp.value())
        self.ctrl.save_settings()

    def _llm_test_run(self) -> None:
        self._llm_save()
        params = self.ctrl.provider_params()
        if params is None:
            self.llm_status.setText(t("Add the API key for this provider first."))
            return
        self.llm_status.setText(t("Testing…"))
        self.ctrl.start_job("llm_test", "Testing prompt provider", tasks.run_llm_test, params,
                            on_done=lambda _k, r: self.llm_status.setText(t("Provider replied:") + f" {r[:300]}"),
                            on_fail=lambda _k, e: self.llm_status.setText(t("Failed:") + f" {self.ctrl._err_text(e)}"))

    def _verify_ffmpeg(self) -> None:
        self.ctrl.settings.ffmpeg_path = self.ffmpeg.text()
        self.ctrl.settings.ffprobe_path = self.ffprobe.text()
        self.ctrl.save_settings()
        self.ctrl.tools(refresh=True)
        self.refresh()

    def _whisper(self, download: bool) -> None:
        engine = self.ctrl.alignment_engine("faster_whisper")
        self.w_status.setText(t("Downloading… this can take a few minutes.") if download else t("Checking…"))
        self.ctrl.start_job("whisper", "Alignment model", tasks.run_whisper_check, engine, download,
                            on_done=lambda _k, r: self.w_status.setText(r),
                            on_fail=lambda _k, e: self.w_status.setText(t("Failed:") + f" {self.ctrl._err_text(e)}"))

    def _clear_creds(self) -> None:
        if not confirm(self, "Clear credentials", "Remove the Voice Studio, G-Labs Studio and all prompt-provider API keys "
                                                  "from the credential store?", "Clear all", danger=True):
            return
        self.ctrl.secrets.clear_all([sec.llm_key(p) for p in PROVIDERS])
        self.voice_card.key.refresh()
        self.glabs_card.key.refresh()
        if self._llm_key_field:
            self._llm_key_field.refresh()
        self.ctrl.refresh_connections()

    # ------------------------------------------------------------- refresh
    def refresh(self) -> None:
        self.voice_card.refresh()
        self.glabs_card.refresh()
        cat = self.ctrl.catalog
        n_img, n_vid = len(cat.enabled_images()), len(cat.enabled_videos())
        self.cat_meta.setText(
            f"<b>v{cat.catalog_version}</b> · updated {cat.updated or '—'} · {n_img} image models · {n_vid} video options<br>"
            f"{t('Verified against')}: {cat.verified_against or '—'}<br>"
            f"{t('File')}: <code>{self.ctrl.catalog_path}</code><br><i>{cat.disclaimer}</i>")
        self.cat_meta.setTextFormat(Qt.TextFormat.RichText)
        self.cat_warn.set("warn", "<br>".join(self.ctrl.catalog_warnings[:6]))
        rows = []
        for e in cat.image_models:
            rows.append((e, "Image", e.route, e.model or ", ".join(f"{k}={v}" for k, v in e.modes.items()),
                         " ".join(e.aspect_ratios), "—", e.requirements))
        for v in cat.video_options:
            ds = ", ".join(f"{d}s" for d in cat.durations(v, self.ctrl.settings.google_ultra)) or t("undocumented")
            ident = (f"model={v.model}" if v.model else "") + ("  " if v.model else "") + \
                ", ".join(f"{k}→{m}" for k, m in v.modes.items())
            rows.append((v, "Video", v.route, ident, " ".join(v.aspect_ratios), ds, v.requirements))
        self.cat_table.setRowCount(len(rows))
        for r, (e, kind, route, ident, ratios, durs, req) in enumerate(rows):
            vals = [e.label + ("" if e.enabled else "  (disabled)") + ("" if e.documented else "  ⚠ undocumented"),
                    kind, route, ident, ratios, durs, req]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if not e.enabled:
                    it.setForeground(Qt.GlobalColor.gray)
                if c == 6:
                    it.setToolTip(req + ("\n" + e.notes if e.notes else ""))
                self.cat_table.setItem(r, c, it)
        self.cat_table.resizeRowsToContents()

        info = self.ctrl.ffmpeg_info
        if info is None:
            self.ff_status.setText(t("Not checked yet."))
        elif info.ok:
            self.ff_status.setText(f"✔ {info.ffmpeg}\n✔ {info.ffprobe}\n{info.ffmpeg_version.split(' Copyright')[0]} · "
                                   f"H.264: {info.h264_encoder or '—'} · "
                                   f"{'subtitles filter available' if info.has_subtitles_filter else 'no libass: burn-in falls back to soft subtitles'}")
        else:
            self.ff_status.setText("✖ " + " ".join(info.problems))
        self.ff_status.setStyleSheet(f"color:{C['success'] if info and info.ok else C['danger'] if info else C['muted']};")
        sec_backend = self.ctrl.secrets.backend_name
        self.sec_status.setText(t("Credential store:") + f" <b>{sec_backend}</b>" +
                                ("" if self.ctrl.secrets.persistent else " — " + t("keys will be forgotten when the app closes.")))
        self.sec_status.setTextFormat(Qt.TextFormat.RichText)


__all__ = ["SettingsPage", "QWidget"]
