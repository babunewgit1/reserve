"""G. Image generation page."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from ...core.i18n import t
from ...services.srt import fmt_short
from ..theme import C
from ..widgets import (
    Badge, Banner, Card, EmptyState, FlowLayout, Page, ThumbLabel, button, confirm, label, labeled, load_thumb,
    task_detail, tool_button,
)
from .common import fill_image_combo, image_help


class ImagePreview(QDialog):
    def __init__(self, parent: QWidget, path: Path, title: str, meta: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1000, 720)
        lay = QVBoxLayout(self)
        img = QLabel()
        img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        px = load_thumb(path, 960, 600)
        if px:
            img.setPixmap(px)
        img.setStyleSheet("background:#0B1022; border-radius:10px;")
        lay.addWidget(img, 1)
        m = label(meta, "Help", wrap=True, selectable=True)
        lay.addWidget(m)


class SceneImageCard(QFrame):
    def __init__(self, page: "ImagesPage", sid: str) -> None:
        super().__init__()
        self.page, self.sid = page, sid
        self.setObjectName("Card")
        p = page.project
        vertical = p.settings.aspect_ratio == "9:16"
        tw, th = (150, 266) if vertical else (272, 153)
        self.setFixedWidth(tw + 26)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.check = QCheckBox()
        self.check.setToolTip(t("Select for batch actions"))
        head.addWidget(self.check)
        self.title = label("", "CardTitle")
        head.addWidget(self.title)
        head.addStretch(1)
        self.badge = Badge()
        head.addWidget(self.badge)
        lay.addLayout(head)
        self.thumb = ThumbLabel(tw, th)
        self.thumb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.thumb.mousePressEvent = lambda _e: self._preview()  # type: ignore[assignment]
        lay.addWidget(self.thumb)
        self.meta = label("", "Faint", wrap=True)
        lay.addWidget(self.meta)
        self.prompt = label("", "Help", wrap=True)
        self.prompt.setMaximumHeight(self.prompt.fontMetrics().lineSpacing() * 3 + 2)
        lay.addWidget(self.prompt)
        self.err = label("", None, wrap=True, selectable=True)
        self.err.setStyleSheet(f"color:{C['danger']}; font-size:11px;")
        lay.addWidget(self.err)
        vrow = QHBoxLayout()
        vrow.setSpacing(6)
        self.versions = QComboBox()
        self.versions.setToolTip(t("All generated/uploaded versions are kept. Pick which one to use."))
        self.versions.currentIndexChanged.connect(self._version)
        vrow.addWidget(self.versions, 1)
        self.approve = QCheckBox(t("Approved"))
        self.approve.toggled.connect(self._approve)
        vrow.addWidget(self.approve)
        lay.addLayout(vrow)
        act = QHBoxLayout()
        act.setSpacing(4)
        self.gen = button("Generate", "sparkles", "soft", on_click=self._generate)
        act.addWidget(self.gen)
        act.addStretch(1)
        self.stop = tool_button("stop", "Stop polling (the remote task may still finish)",
                                lambda: page.ctrl.jobs.cancel(f"img:{sid}"), C["danger"])
        act.addWidget(self.stop)
        act.addWidget(tool_button("upload", "Replace with your own image (kept as a new version)", self._upload))
        act.addWidget(tool_button("eye", "Preview", self._preview))
        lay.addLayout(act)
        self.update_view()

    def scene(self):
        return self.page.project.scene(self.sid) if self.page.project else None

    def update_view(self) -> None:
        s = self.scene()
        if not s:
            return
        p = self.page.project
        ctrl = self.page.ctrl
        i = p.scene_index(s.id)
        self.title.setText(f"{t('Scene')} {i + 1}")
        task = s.image_task
        running = ctrl.jobs.is_running(f"img:{s.id}")
        self.badge.set_state(task.state)
        if s.image_approved and s.image_asset() and not task.busy:
            self.badge.set("Approved", "ok")
        asset = s.image_asset()
        if asset:
            self.thumb.set_path(ctrl.abs_path(asset.path))
        else:
            self.thumb.clear_thumb(t("Generating…") if running else "")
        entry = ctrl.image_entry_for(s)
        model = entry.label if entry else (s.image_model or p.settings.image_model)
        prog = ctrl.jobs.last_progress.get(f"img:{s.id}", (0, ""))[1]
        meta = f"{fmt_short(s.start)}–{fmt_short(s.end)} · {model}" + (" · " + t("override") if s.image_model else "")
        if task.task_id:
            meta += f" · {task.task_id[:10]}"
        if running and prog:
            meta += f"\n{prog}"
        self.meta.setText(meta)
        self.meta.setToolTip(task_detail(task))
        self.prompt.setText(s.image_prompt or t("(no image prompt — write one on the Scenes page)"))
        self.prompt.setToolTip(s.image_prompt)
        err = ""
        if task.state in ("failed", "lost"):
            err = task.error + (f"\n→ {task.hint}" if task.hint else "")
        elif task.state == "cancelled":
            err = task.message
        self.err.setText(err)
        self.err.setVisible(bool(err))
        with QSignalBlocker(self.versions):
            self.versions.clear()
            for k, a in enumerate(s.images):
                src = t("uploaded") if a.source == "uploaded" else (a.model or "")
                self.versions.addItem(f"v{k + 1} · {src}", k)
            self.versions.setCurrentIndex(s.selected_image)
            self.versions.setVisible(len(s.images) > 0)
        with QSignalBlocker(self.approve):
            self.approve.setChecked(s.image_approved)
            self.approve.setEnabled(asset is not None)
        self.gen.setText(t("Regenerate") if s.images else t("Generate"))
        self.gen.setEnabled(not running)
        self.stop.setVisible(running)

    def _version(self) -> None:
        self.page.ctrl.select_image(self.sid, self.versions.currentData())

    def _approve(self, on: bool) -> None:
        self.page.ctrl.set_image_approved([self.sid], on)

    def _generate(self) -> None:
        s = self.scene()
        if s and s.images and s.video_asset():
            if not confirm(self, "Regenerate image?", "This scene already has a clip made from the current image. The new "
                                                     "image is added as a new version; regenerate the clip afterwards.",
                           "Regenerate"):
                return
        self.page.ctrl.generate_images([self.sid])

    def _upload(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("Choose image"), str(Path.home()), "Images (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.page.ctrl.import_image(self.sid, Path(path))

    def _preview(self) -> None:
        s = self.scene()
        a = s.image_asset() if s else None
        if not a:
            return
        meta = (f"{a.path} · {a.source} · {a.model or ''} {('· task ' + a.task_id) if a.task_id else ''}\n\n"
                f"{t('Prompt')}: {a.prompt or s.image_prompt}")
        ImagePreview(self, self.page.ctrl.abs_path(a.path), f"{t('Scene')} {self.page.project.scene_index(s.id) + 1}", meta).exec()


class ImagesPage(Page):
    title_text = "Images"
    subtitle_text = "Key images for every scene from G-Labs Studio. Approve them before clips are generated."

    def __init__(self, ctrl, parent=None) -> None:
        super().__init__(ctrl, parent)
        L = self.layout_
        self.cards: dict[str, SceneImageCard] = {}
        self._ids: list[str] = []
        self._aspect = ""
        self.next_btn = self.add_action(button("Continue to clips", "right", "primary",
                                               on_click=lambda: ctrl.request_page.emit("videos")))
        self.empty = EmptyState("image", "No scenes yet", "Plan scenes and write prompts first.", "Go to Scenes",
                                lambda: ctrl.request_page.emit("scenes"), "scenes")
        L.addWidget(self.empty)
        self.body_w = QWidget()
        body = QVBoxLayout(self.body_w)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)
        L.addWidget(self.body_w, 1)

        tc = Card("Image generation", "", "image")
        row = QHBoxLayout()
        row.setSpacing(12)
        self.model = QComboBox()
        self.model.currentIndexChanged.connect(self._model)
        row.addWidget(labeled("Default image model", self.model))
        self.upscale = QComboBox()
        self.upscale.currentIndexChanged.connect(self._upscale)
        row.addWidget(labeled("Upscale", self.upscale))
        row.addStretch(1)
        self.stats = {}
        for key, name, tone in (("queued", "Queue", "info"), ("running", "Running", "primary"), ("completed", "Completed", "ok"),
                                ("failed", "Failed", "error")):
            col = QVBoxLayout()
            col.setSpacing(0)
            n = label("0", "Stat")
            n.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(n)
            b = Badge(name, tone)
            col.addWidget(b, 0, Qt.AlignmentFlag.AlignHCenter)
            row.addLayout(col)
            self.stats[key] = n
        tc.add(row)
        self.model_help = label("", "Help", wrap=True)
        self.model_help.setTextFormat(Qt.TextFormat.RichText)
        tc.add(self.model_help)
        act = QHBoxLayout()
        act.setSpacing(8)
        self.gen_all = button("Generate missing", "sparkles", "primary", "Generate images for scenes without one",
                              on_click=self._gen_missing)
        self.gen_all.setObjectName("btnGenerateImages")
        act.addWidget(self.gen_all)
        act.addWidget(button("Generate selected", "sparkles", "soft", on_click=self._gen_selected))
        act.addWidget(button("Regenerate all", "refresh", None, on_click=self._gen_all))
        act.addWidget(button("Select all", None, "ghost", on_click=lambda: self._select(True)))
        act.addWidget(button("None", None, "ghost", on_click=lambda: self._select(False)))
        act.addStretch(1)
        self.approve_all = button("Approve all", "check", "soft", on_click=self._approve_all)
        act.addWidget(self.approve_all)
        self.resume_btn = button("Resume interrupted", "refresh", None, on_click=ctrl.resume_images)
        act.addWidget(self.resume_btn)
        self.stop_all = button("Stop all", "stop", "danger", "Stops polling. G-Labs has no cancel endpoint; remote tasks "
                               "may still finish and use quota.", on_click=lambda: ctrl.jobs.cancel_prefix("img:"))
        act.addWidget(self.stop_all)
        tc.add(act)
        self.gate = Banner("info", "")
        tc.add(self.gate)
        body.addWidget(tc)

        self.grid_w = QWidget()
        self.grid = FlowLayout(self.grid_w, 14)
        body.addWidget(self.grid_w, 1)

        ctrl.project_loaded.connect(self._rebuild_all)
        ctrl.project_closed.connect(self._rebuild_all)
        ctrl.scene_changed.connect(self._scene_changed)
        ctrl.changed.connect(lambda a: a in ("scenes", "images", "catalog", "setup") and self.mark_stale())
        ctrl.jobs.progress.connect(lambda k, f, m: k.startswith("img:") and self._scene_changed(k[4:]))
        ctrl.jobs.changed.connect(self._update_stats)

    def _rebuild_all(self) -> None:
        self._ids = []
        self.mark_stale()

    # ------------------------------------------------------------- actions
    def _model(self) -> None:
        p = self.project
        if p and self.model.currentData():
            p.settings.image_model = self.model.currentData()
            self.edit("setup")
            self._update_header()
            for c in self.cards.values():
                c.update_view()

    def _upscale(self) -> None:
        p = self.project
        if p:
            p.settings.image_upscale = self.upscale.currentData() or ""
            self.edit("setup")

    def _selected(self) -> list[str]:
        return [sid for sid, c in self.cards.items() if c.check.isChecked()]

    def _select(self, on: bool) -> None:
        for c in self.cards.values():
            c.check.setChecked(on)

    def _gen_missing(self) -> None:
        p = self.project
        ids = [s.id for s in p.scenes if not s.image_asset()]
        if not ids:
            self.ctrl.notify.emit("info", "Every scene already has an image. Use Regenerate on a card or select scenes.")
            return
        n = self.ctrl.generate_images(ids)
        self.ctrl.notify.emit("info", f"Started {n} image task(s).")

    def _gen_selected(self) -> None:
        ids = self._selected()
        if not ids:
            self.ctrl.notify.emit("info", "Tick the scenes you want to generate first.")
            return
        self.ctrl.generate_images(ids)

    def _gen_all(self) -> None:
        p = self.project
        if not confirm(self, "Regenerate every image?", f"Submit {len(p.scenes)} new image tasks? Existing images are kept "
                                                        "as older versions. This uses your G-Labs quota.", "Regenerate all"):
            return
        self.ctrl.generate_images([s.id for s in p.scenes])

    def _approve_all(self) -> None:
        p = self.project
        self.ctrl.set_image_approved([s.id for s in p.scenes if s.image_asset()], True)

    # ------------------------------------------------------------- refresh
    def _scene_changed(self, sid: str) -> None:
        c = self.cards.get(sid)
        if c is not None and self.isVisible():
            c.update_view()
            self._update_stats()
            self._update_gate()
        else:
            self._stale = True

    def _update_stats(self) -> None:
        p = self.project
        if not p:
            return
        counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0}
        for s in p.scenes:
            st = s.image_task.state
            if st in ("queued", "submitting"):
                counts["queued"] += 1
            elif st in ("running", "downloading"):
                counts["running"] += 1
            elif st in ("failed", "lost"):
                counts["failed"] += 1
            if s.image_asset():
                counts["completed"] += 1
        for k, n in counts.items():
            self.stats[k].setText(str(n))
        busy = bool(self.ctrl.jobs.running_keys("img:"))
        self.stop_all.setVisible(busy)
        self.resume_btn.setVisible(any(s.image_task.state == "interrupted" and s.image_task.task_id for s in p.scenes))

    def _update_gate(self) -> None:
        p = self.project
        if not p:
            return
        have = [s for s in p.scenes if s.image_asset()]
        need_ok = p.settings.require_image_approval and p.settings.run_mode == "manual"
        pending = [s for s in have if not s.image_approved]
        if need_ok and pending:
            msg = t("image(s) waiting for approval. Approve them (or turn off approval in Project setup) before "
                    "generating clips.")
            self.gate.set("info", f"{len(pending)} {msg}", "Approve all", self._approve_all)
        elif have and len(have) == len(p.scenes):
            self.gate.set("ok", t("All scenes have an image. Continue to clips when you're happy with them."))
        else:
            self.gate.set("info", "")

    def _update_header(self) -> None:
        p = self.project
        e = self.ctrl.image_entry_for()
        self.model_help.setText(image_help(e))
        with QSignalBlocker(self.upscale):
            self.upscale.clear()
            self.upscale.addItem(t("None"), "")
            if e:
                for u in e.upscale_options:
                    locked = u in e.ultra_upscale and not self.ctrl.settings.google_ultra
                    self.upscale.addItem(u + (f"  ({t('ULTRA only')})" if u in e.ultra_upscale else ""), u)
                    if locked:
                        self.upscale.model().item(self.upscale.count() - 1).setEnabled(False)
            self.upscale.setCurrentIndex(max(0, self.upscale.findData(p.settings.image_upscale)))
            self.upscale.setEnabled(self.upscale.count() > 1)

    def refresh(self) -> None:
        p = self.project
        has = bool(p and p.scenes)
        self.empty.setVisible(not has)
        self.body_w.setVisible(has)
        self.next_btn.setVisible(has)
        if not has:
            self.grid.clear()
            self.cards.clear()
            self._ids = []
            return
        fill_image_combo(self.model, self.ctrl.catalog, p.settings.image_model)
        self._update_header()
        ids = [s.id for s in p.scenes]
        if ids != self._ids or p.settings.aspect_ratio != self._aspect:
            checked = set(self._selected())
            self.grid.clear()
            self.cards.clear()
            for sid in ids:
                c = SceneImageCard(self, sid)
                c.check.setChecked(sid in checked)
                self.cards[sid] = c
                self.grid.addWidget(c)
            self._ids = ids
            self._aspect = p.settings.aspect_ratio
        else:
            for c in self.cards.values():
                c.update_view()
        self._update_stats()
        self._update_gate()
