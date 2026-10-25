"""J. Optional YouTube package page."""
from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

from ...core.i18n import t
from ..widgets import (
    Badge, Banner, Card, EmptyState, Page, StatusLine, ThumbLabel, button, hbox, label, labeled, tool_button,
)


class YouTubePage(Page):
    title_text = "YouTube package"
    subtitle_text = ("Optional titles, SEO description, chapters from the final scene timing, tags, hashtags and a thumbnail "
                     "concept. Never blocks the video render.")

    def __init__(self, ctrl, parent=None) -> None:
        super().__init__(ctrl, parent)
        L = self.layout_
        self.empty = EmptyState("youtube", "No project open", "Open a project first.", "Go to Welcome",
                                lambda: ctrl.request_page.emit("welcome"), "home")
        L.addWidget(self.empty)
        self.body_w = QWidget()
        body = QVBoxLayout(self.body_w)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)
        L.addWidget(self.body_w, 1)

        gc = Card("Generate", "", "sparkles")
        self.badge = gc.add_action(Badge())
        self.enabled = QCheckBox(t("Include a YouTube package in this project (automatic runs create it after rendering)"))
        self.enabled.toggled.connect(self._enabled)
        gc.add(self.enabled)
        row = QHBoxLayout()
        self.gen_btn = button("Generate package", "sparkles", "primary", on_click=ctrl.generate_youtube)
        self.gen_btn.setObjectName("btnYouTube")
        row.addWidget(self.gen_btn)
        row.addWidget(button("Save edits", "save", "soft", "Re-export youtube_metadata.md / .json with your edits",
                             on_click=self._save))
        row.addWidget(button("Open youtube_metadata.md", "external", "ghost", on_click=self._open_md))
        row.addStretch(1)
        gc.add(row)
        self.llm_note = Banner("info", "")
        gc.add(self.llm_note)
        self.status = StatusLine()
        gc.add(self.status)
        body.addWidget(gc)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        tc = Card("Title options", "", "file")
        self.titles = QPlainTextEdit()
        self.titles.setFixedHeight(120)
        self.titles.setPlaceholderText(t("One title per line"))
        tc.add(self.titles)
        tc.add(hbox(None, tool_button("copy", "Copy", lambda: self._copy(self.titles.toPlainText()))))
        grid.addWidget(tc, 0, 0)
        cc = Card("Chapters", "From the final scene timing (YouTube needs ≥3 chapters of ≥10 s, starting at 0:00).", "clock")
        self.chapters = QPlainTextEdit()
        self.chapters.setFixedHeight(120)
        cc.add(self.chapters)
        cc.add(hbox(None, tool_button("copy", "Copy", lambda: self._copy(self.chapters.toPlainText()))))
        grid.addWidget(cc, 0, 1)
        dc = Card("Description", "", "clipboard")
        self.desc = QPlainTextEdit()
        self.desc.setMinimumHeight(180)
        dc.add(self.desc)
        dc.add(hbox(None, tool_button("copy", "Copy description + chapters", self._copy_desc)))
        grid.addWidget(dc, 1, 0, 1, 2)
        tg = Card("Tags & hashtags", "", "link")
        self.tags = QPlainTextEdit()
        self.tags.setFixedHeight(80)
        self.tags.setPlaceholderText(t("comma-separated"))
        tg.add(labeled("Tags", self.tags))
        self.hashtags = QLineEdit()
        tg.add(labeled("Hashtags", self.hashtags))
        tg.add(hbox(None, tool_button("copy", "Copy tags", lambda: self._copy(self.tags.toPlainText()))))
        grid.addWidget(tg, 2, 0)
        th = Card("Thumbnail", "", "image")
        self.thumb_concept = QPlainTextEdit()
        self.thumb_concept.setFixedHeight(70)
        th.add(labeled("Concept", self.thumb_concept))
        self.thumb_prompt = QPlainTextEdit()
        self.thumb_prompt.setFixedHeight(70)
        th.add(labeled("Image prompt", self.thumb_prompt))
        tr = QHBoxLayout()
        self.thumb = ThumbLabel(192, 108)
        tr.addWidget(self.thumb)
        col = QVBoxLayout()
        self.thumb_btn = button("Generate thumbnail image", "image", "soft", "Uses the project's image model through "
                                "G-Labs Studio (/api/image/… route from the catalog).", on_click=self._thumb)
        col.addWidget(self.thumb_btn)
        col.addWidget(label(t("Add your title text in an editor afterwards — image models are asked not to draw text."),
                            "Faint", wrap=True))
        col.addStretch(1)
        tr.addLayout(col, 1)
        th.add(tr)
        grid.addWidget(th, 2, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        body.addLayout(grid)

        ctrl.project_loaded.connect(self.mark_stale)
        ctrl.project_closed.connect(self.mark_stale)
        ctrl.changed.connect(lambda a: a in ("youtube", "setup") and self.mark_stale())
        ctrl.task_changed.connect(lambda k: k in ("yt", "thumb") and self.mark_stale())

    def _enabled(self, v: bool) -> None:
        if self.project:
            self.project.settings.youtube_metadata = v
            self.edit("setup")

    def _collect(self) -> None:
        p = self.project
        if not p:
            return
        d = dict(p.youtube.data or {})
        d["titles"] = [x.strip() for x in self.titles.toPlainText().splitlines() if x.strip()]
        d["description"] = self.desc.toPlainText().strip()
        d["tags"] = [x.strip() for x in self.tags.toPlainText().replace("\n", ",").split(",") if x.strip()]
        d["hashtags"] = [x if x.startswith("#") else "#" + x for x in self.hashtags.text().split() if x.strip("#")]
        d["thumbnail_concept"] = self.thumb_concept.toPlainText().strip()
        d["thumbnail_prompt"] = self.thumb_prompt.toPlainText().strip()
        chapters = []
        for line in self.chapters.toPlainText().splitlines():
            line = line.strip()
            if not line:
                continue
            ts, _, title = line.partition(" ")
            parts = ts.split(":")
            try:
                secs = sum(int(x) * 60 ** i for i, x in enumerate(reversed(parts)))
            except ValueError:
                continue
            chapters.append({"time": ts, "start": float(secs), "title": title.strip()})
        d["chapters"] = chapters
        p.youtube.data = d

    def _save(self) -> None:
        if not self.project or not self.project.youtube.data:
            self.ctrl.notify.emit("info", "Generate the package first.")
            return
        self._collect()
        self.ctrl.save_youtube_edits()
        self.ctrl.notify.emit("success", "youtube_metadata.md and .json updated.")

    def _thumb(self) -> None:
        if self.project and self.project.youtube.data:
            self._collect()
        self.ctrl.generate_thumbnail()
        self.mark_stale()

    def _open_md(self) -> None:
        p = self.project
        if p and p.youtube.md_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctrl.abs_path(p.youtube.md_path))))

    def _copy(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self.ctrl.notify.emit("info", "Copied to clipboard.")

    def _copy_desc(self) -> None:
        self._copy(self.desc.toPlainText().strip() + "\n\n" + self.chapters.toPlainText().strip())

    def refresh(self) -> None:
        p = self.project
        self.empty.setVisible(p is None)
        self.body_w.setVisible(p is not None)
        if not p:
            return
        with QSignalBlocker(self.enabled):
            self.enabled.setChecked(p.settings.youtube_metadata)
        running = self.ctrl.jobs.is_running("yt")
        self.gen_btn.setEnabled(not running)
        self.gen_btn.setText(t("Regenerate package") if p.youtube.data else t("Generate package"))
        y = p.youtube
        self.badge.set("Writing…" if running else "Exported" if y.md_path else "Not generated",
                       "primary" if running else "ok" if y.md_path else "neutral")
        self.status.set_task(y.task)
        self.status.setVisible(y.task.state not in ("idle",) and (y.task.state != "completed" or bool(y.task.message)))
        self.llm_note.set("info" if self.ctrl.llm_ready() else "warn",
                          t("Uses your prompt LLM") + f" ({self.ctrl.settings.llm_provider})." if self.ctrl.llm_ready() else
                          t("No prompt LLM configured: only chapters can be generated locally. Add a provider in Settings "
                            "for titles, description, tags and thumbnail ideas."))
        d = y.data or {}
        for w, v in ((self.titles, "\n".join(d.get("titles") or [])), (self.desc, d.get("description") or ""),
                     (self.chapters, "\n".join(f"{c['time']} {c['title']}" for c in d.get("chapters") or [])),
                     (self.tags, ", ".join(d.get("tags") or [])), (self.thumb_concept, d.get("thumbnail_concept") or ""),
                     (self.thumb_prompt, d.get("thumbnail_prompt") or "")):
            if w.toPlainText() != v:
                w.setPlainText(v)
        self.hashtags.setText(" ".join(d.get("hashtags") or []))
        if y.thumbnail and self.ctrl.abs_path(y.thumbnail).exists():
            self.thumb.set_path(self.ctrl.abs_path(y.thumbnail))
        else:
            self.thumb.clear_thumb(t("Generating…") if self.ctrl.jobs.is_running("thumb") else "")
        self.thumb_btn.setEnabled(not self.ctrl.jobs.is_running("thumb") and bool(d.get("thumbnail_prompt")))
