"""A. Welcome / projects page."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QSizePolicy, QVBoxLayout, QWidget,
)

from ...core.i18n import t
from ...services import project_store
from ..icons import logo_pixmap, pixmap
from ..theme import C
from ..widgets import (
    Badge, Card, Dot, EmptyState, Page, PathField, button, clear_layout, fmt_age, label, labeled, show_error,
)

CONN_TONES = {"ok": "ok", "warn": "warn", "error": "error", "checking": "info", "unknown": "neutral"}


class NewProjectDialog(QDialog):
    def __init__(self, parent: QWidget, default_parent: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("New project"))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(14)
        lay.addWidget(label(t("Start a new explainer"), "H2"))
        lay.addWidget(label(t("A project is a normal folder with project.json, your script, audio, subtitles and all "
                              "generated assets. No database is used."), "Help", wrap=True))
        self.title = QLineEdit()
        self.title.setPlaceholderText(t("e.g. How photosynthesis works"))
        lay.addWidget(labeled("Project title", self.title))
        self.folder = PathField("dir", caption="Choose where to create the project folder")
        self.folder.set_text(default_parent)
        lay.addWidget(labeled("Location", self.folder, "A sub-folder named after the title is created here."))
        self.aspect = QComboBox()
        self.aspect.addItem(t("16:9 · Landscape (YouTube)"), "16:9")
        self.aspect.addItem(t("9:16 · Vertical (Shorts / Reels)"), "9:16")
        lay.addWidget(labeled("Aspect ratio", self.aspect))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(t("Create project"))
        bb.button(QDialogButtonBox.StandardButton.Ok).setProperty("variant", "primary")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.title.setFocus()

    def _accept(self) -> None:
        if not self.title.text().strip():
            self.title.setFocus()
            self.title.setPlaceholderText(t("Please enter a title"))
            return
        if not self.folder.text():
            return
        self.accept()


class WelcomePage(Page):
    title_text = "Welcome"
    subtitle_text = ""

    def __init__(self, ctrl, parent=None) -> None:
        super().__init__(ctrl, parent)
        self.title_label.setVisible(False)
        self.subtitle_label.setVisible(False)
        L = self.layout_

        # hero
        hero = QWidget()
        hero.setObjectName("HeroWrap")
        from PySide6.QtWidgets import QFrame
        hf = QFrame()
        hf.setObjectName("Hero")
        hl = QHBoxLayout(hf)
        hl.setContentsMargins(32, 28, 32, 28)
        hl.setSpacing(24)
        left = QVBoxLayout()
        left.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(44))
        left.addWidget(logo)
        h1 = QLabel(t("Script in. Finished explainer out."))
        h1.setStyleSheet("font-size: 28px; font-weight: 800;")
        h1.setWordWrap(True)
        left.addWidget(h1)
        sub = QLabel(t("Narration from G-Labs Voice Studio, subtitles aligned on your PC, scenes and visuals from "
                       "G-Labs Studio, edited together with FFmpeg — with a review step wherever you want one."))
        sub.setObjectName("HeroSub")
        sub.setWordWrap(True)
        sub.setMaximumWidth(640)
        left.addWidget(sub)
        left.addSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.new_btn = button("New project", "plus", "hero", on_click=self.new_project)
        self.new_btn.setObjectName("btnNewProject")
        row.addWidget(self.new_btn)
        self.open_btn = button("Open project folder", "folder-open", "heroGhost", on_click=self.open_folder,
                               icon_color="#FFFFFF")
        self.open_btn.setObjectName("btnOpenProject")
        row.addWidget(self.open_btn)
        row.addStretch(1)
        left.addLayout(row)
        hl.addLayout(left, 3)
        hl.addWidget(self._pipeline_art(), 2)
        L.addWidget(hf)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        # connections
        self.conn_card = Card("Connections", "Live status of the local apps this tool drives.", "plug")
        self.conn_rows: dict[str, tuple[Dot, QLabel, QLabel]] = {}
        for key, name in (("voice", "G-Labs Voice Studio"), ("glabs", "G-Labs Studio"), ("ffmpeg", "FFmpeg / ffprobe")):
            r = QHBoxLayout()
            r.setSpacing(10)
            d = Dot("neutral", 10)
            r.addWidget(d, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(label(t(name), "FieldLabel"))
            msg = label("", "Help", wrap=True)
            col.addWidget(msg)
            r.addLayout(col, 1)
            badge = Badge()
            r.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
            self.conn_card.add(r)
            self.conn_rows[key] = (d, msg, badge)
        br = QHBoxLayout()
        br.addWidget(button("Refresh connections", "refresh", "soft", "Checks /api/health and your API keys only. "
                            "It does not fetch model names (no such API exists).", on_click=self.ctrl.refresh_connections))
        br.addWidget(button("Connection settings", "sliders", "ghost", on_click=lambda: self.ctrl.request_page.emit("settings")))
        br.addStretch(1)
        self.conn_card.add(br)
        grid.addWidget(self.conn_card, 0, 0)

        # checklist
        self.check_card = Card("Setup checklist", "Shown until everything is connected.", "check-circle", accent=True)
        self.check_list = QVBoxLayout()
        self.check_list.setSpacing(8)
        self.check_card.add(self.check_list)
        grid.addWidget(self.check_card, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        L.addLayout(grid)

        # recent projects
        self.recent_card = Card("Recent projects", "Pick up where you left off — unfinished generation tasks can be resumed.",
                                "clock")
        self.recent_card.add_action(button("Open project folder…", "folder-open", "ghost", on_click=self.open_folder))
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(8)
        self.recent_card.add(self.recent_box)
        L.addWidget(self.recent_card)
        L.addStretch(1)

        ctrl.conn_changed.connect(self.mark_stale)
        ctrl.project_loaded.connect(self.mark_stale)
        ctrl.project_closed.connect(self.mark_stale)

    def _pipeline_art(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        steps = [("mic", "Voiceover", "Voice Studio"), ("captions", "Subtitles", "local alignment"),
                 ("scenes", "Scenes & prompts", "your LLM or manual"), ("image", "Images", "G-Labs Studio"),
                 ("video", "Clips", "Veo · Omni · Grok · Meta"), ("film", "Final MP4", "FFmpeg")]
        for ic, a, b in steps:
            row = QWidget()
            row.setStyleSheet("background: rgba(255,255,255,0.10); border-radius: 10px;")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(10, 6, 10, 6)
            rl.setSpacing(10)
            il = QLabel()
            il.setPixmap(pixmap(ic, "#FFFFFF", 16))
            il.setStyleSheet("background: transparent;")
            rl.addWidget(il)
            tl = QLabel(f"<b>{t(a)}</b>  <span style='color:#CFCBFF'>· {t(b)}</span>")
            tl.setStyleSheet("background: transparent; color: white;")
            tl.setWordWrap(True)
            rl.addWidget(tl, 1)
            lay.addWidget(row)
        return w

    # ------------------------------------------------------------- actions
    def new_project(self) -> None:
        dlg = NewProjectDialog(self, self.ctrl.settings.output_dir)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        parent = Path(dlg.folder.text())
        try:
            parent.mkdir(parents=True, exist_ok=True)
            self.ctrl.new_project(parent, dlg.title.text().strip())
        except Exception as exc:
            show_error(self, "Could not create project", str(exc))
            return
        self.ctrl.project.settings.aspect_ratio = dlg.aspect.currentData()
        self.ctrl.mark_dirty("setup")
        self.ctrl.request_page.emit("setup")

    def open_folder(self) -> None:
        start = self.ctrl.settings.output_dir or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, t("Open project folder"), start)
        if folder:
            self.open_path(Path(folder))

    def open_path(self, folder: Path) -> None:
        try:
            self.ctrl.open_project(folder)
        except Exception as exc:
            show_error(self, "Could not open project", f"{exc}")
            return
        self.ctrl.request_page.emit(self._resume_step())

    def _resume_step(self) -> str:
        st = self.ctrl.step_states()
        for key in ("setup", "narration", "subtitles", "scenes", "images", "videos", "export"):
            if st.get(key) != "done":
                return key
        return "export"

    # ------------------------------------------------------------- refresh
    def refresh(self) -> None:
        c = self.ctrl.conn
        for key, (dot, msg, badge) in self.conn_rows.items():
            st = c[key]
            tone = CONN_TONES.get(st.state, "neutral")
            dot.set(tone)
            text = st.message + (f" — {st.hint}" if st.hint else "")
            if st.details and st.state == "ok":
                text += f"\n{st.details}"
            msg.setText(text)
            badge.set({"ok": "Ready", "warn": "Check", "error": "Offline" if key != "ffmpeg" else "Missing",
                       "checking": "Checking…", "unknown": "Unknown"}.get(st.state, st.state), tone)
        self._refresh_checklist()
        self._refresh_recent()

    def _refresh_checklist(self) -> None:
        clear_layout(self.check_list)
        c = self.ctrl.conn
        items = [
            (c["voice"].state == "ok", "Open G-Labs Voice Studio → Settings → Webhook API, start the server and copy its API key "
                                       "into Settings here (default http://127.0.0.1:8766)."),
            (c["voice"].state == "ok" and bool(self.ctrl.voices), "Save at least one voice in Voice Studio's Voice Bank "
                                                                  "(presets are listed via GET /api/voices)."),
            (c["glabs"].state == "ok", "Open G-Labs Studio → Settings → Webhook API (MAX license), start the server and copy "
                                       "its separate API key (default http://127.0.0.1:8765)."),
            (False if c["glabs"].state != "ok" else None, "Log in and enable the accounts you will use (Google Flow/Veo, Grok, "
                                                          "Meta, OpenAI) inside G-Labs Studio. Generation uses their quotas."),
            (c["ffmpeg"].state in ("ok", "warn"), "Install FFmpeg (e.g. `winget install Gyan.FFmpeg`) or point Settings → FFmpeg "
                                                  "to ffmpeg.exe / ffprobe.exe."),
            (self.ctrl.llm_ready() or None, "Optional: add a prompt LLM in Settings, or write/draft prompts manually."),
        ]
        all_ok = all(ok is not False for ok, _ in items[:3]) and items[4][0]
        for ok, text in items:
            r = QHBoxLayout()
            r.setSpacing(10)
            ic = QLabel()
            name, col = ("check-circle", C["success"]) if ok else ("alert", C["warning"]) if ok is False else ("info", C["faint"])
            ic.setPixmap(pixmap(name, col, 16))
            r.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
            lb = label(t(text), "Help", wrap=True)
            r.addWidget(lb, 1)
            self.check_list.addLayout(r)
        self.check_card.title_label.setText(t("All set — you're ready to create") if all_ok else t("Setup checklist"))

    def _refresh_recent(self) -> None:
        clear_layout(self.recent_box)
        rec = [r for r in self.ctrl.settings.recent_projects]
        if not rec:
            self.recent_box.addWidget(EmptyState("film", "No projects yet",
                                                 "Create your first explainer. You can save, close and resume it at any time.",
                                                 "New project", self.new_project, "plus"))
            return
        for path in rec[:8]:
            info = project_store.project_summary(Path(path))
            fr = QFrame()
            fr.setObjectName("SoftPanel")
            rl = QHBoxLayout(fr)
            rl.setContentsMargins(14, 10, 10, 10)
            rl.setSpacing(12)
            ic = QLabel()
            ic.setPixmap(pixmap("film" if info.get("ok") else "alert", C["primary"] if info.get("ok") else C["danger"], 20))
            rl.addWidget(ic)
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(label(info.get("title", Path(path).name), "FieldLabel"))
            if info.get("ok"):
                meta = (f"{info.get('aspect', '')} · {info.get('scenes', 0)} scenes · {info.get('clips', 0)} clips · "
                        f"{t('rendered') if info.get('rendered') else t('not rendered')} · {t('edited')} {fmt_age(info.get('updated_at'))}")
            else:
                meta = t("Folder missing or project.json unreadable")
            ml = label(meta, "Help", wrap=True)
            col.addWidget(ml)
            pl = label(path, "Faint")
            pl.setToolTip(path)
            pl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            pl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            col.addWidget(pl)
            rl.addLayout(col, 1)
            if self.ctrl.folder and str(self.ctrl.folder.resolve()) == path:
                rl.addWidget(Badge("Open now", "primary"))
            if info.get("ok"):
                rl.addWidget(button("Open", "folder-open", "soft", on_click=lambda p=path: self.open_path(Path(p))))
            rl.addWidget(button("Remove", None, "ghost", "Remove from this list (files are not deleted)",
                                on_click=lambda p=path: (self.ctrl.settings_store.remove_recent(p), self.mark_stale())))
            self.recent_box.addWidget(fr)
