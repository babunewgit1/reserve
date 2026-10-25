"""H. Video clip generation page."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget,
)

from ...core.catalog import MODE_LABELS
from ...core.i18n import t
from ...services.srt import fmt_short
from ..media import VideoPlayer
from ..theme import C
from ..widgets import (
    Badge, Banner, Card, EmptyState, Page, ResponsiveRow, ThumbLabel, button, confirm, label, labeled, task_detail,
    tool_button,
)
from .common import fill_mode_combo, fill_video_combo, video_help


class SceneClipRow(QFrame):
    def __init__(self, page: "VideosPage", sid: str) -> None:
        super().__init__()
        self.page, self.sid = page, sid
        self.setObjectName("Card")
        ctrl = page.ctrl
        vertical = page.project.settings.aspect_ratio == "9:16"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(4)
        self.check = QCheckBox()
        hdr = QHBoxLayout()
        hdr.addWidget(self.check)
        self.num = label("", "CardTitle")
        hdr.addWidget(self.num)
        hdr.addStretch(1)
        left.addLayout(hdr)
        self.thumb = ThumbLabel(96, 170) if vertical else ThumbLabel(176, 99)
        self.thumb.setToolTip(t("Start frame sent to the video model"))
        left.addWidget(self.thumb)
        self.thumb_note = label("", "Faint", wrap=True)
        self.thumb_note.setMaximumWidth(176)
        left.addWidget(self.thumb_note)
        left.addStretch(1)
        lay.addLayout(left)

        mid = QVBoxLayout()
        mid.setSpacing(6)
        top = QHBoxLayout()
        self.timing = label("", "FieldLabel")
        top.addWidget(self.timing)
        top.addStretch(1)
        self.badge = Badge()
        top.addWidget(self.badge)
        mid.addLayout(top)
        self.motion = QPlainTextEdit()
        self.motion.setFixedHeight(56)
        self.motion.setPlaceholderText(t("Motion prompt: what moves, camera movement…"))
        self.motion.textChanged.connect(self._motion)
        mid.addWidget(self.motion)
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        self.opt = QComboBox()
        self.opt.currentIndexChanged.connect(self._opt)
        g.addWidget(labeled("Video option", self.opt), 0, 0)
        self.mode = QComboBox()
        self.mode.currentIndexChanged.connect(self._mode)
        g.addWidget(labeled("Mode", self.mode), 0, 1)
        g.setColumnStretch(0, 3)
        g.setColumnStretch(1, 2)
        mid.addLayout(g)
        self.plan = label("", "Help", wrap=True)
        mid.addWidget(self.plan)
        self.status = label("", "Help", wrap=True, selectable=True)
        mid.addWidget(self.status)
        self.err = label("", None, wrap=True, selectable=True)
        self.err.setStyleSheet(f"color:{C['danger']}; font-size:12px;")
        mid.addWidget(self.err)
        self.fallback = button("", "wand", "soft", on_click=self._fallback)
        mid.addWidget(self.fallback, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addLayout(mid, 1)

        right = QVBoxLayout()
        right.setSpacing(6)
        self.versions = QComboBox()
        self.versions.setMinimumWidth(170)
        self.versions.setToolTip(t("All clip versions are kept. Pick the one to use in the edit."))
        self.versions.currentIndexChanged.connect(self._version)
        right.addWidget(self.versions)
        self.gen = button("Generate", "sparkles", "primary", on_click=self._generate)
        right.addWidget(self.gen)
        self.play = button("Preview", "play", "soft", on_click=self._play)
        right.addWidget(self.play)
        row = QHBoxLayout()
        row.addWidget(tool_button("upload", "Use your own clip (kept as a new version)", self._upload))
        self.stop = tool_button("stop", "Stop polling (remote task may still finish)", lambda: page.stop_scene(sid), C["danger"])
        row.addWidget(self.stop)
        row.addStretch(1)
        right.addLayout(row)
        right.addStretch(1)
        lay.addLayout(right)
        self.update_view(full=True)

    def scene(self):
        return self.page.project.scene(self.sid) if self.page.project else None

    def update_view(self, full: bool = False) -> None:
        s = self.scene()
        if not s:
            return
        ctrl = self.page.ctrl
        p = self.page.project
        i = p.scene_index(s.id)
        info = ctrl.video_plan(i)
        e = info["entry"]
        self.num.setText(f"{t('Scene')} {i + 1}")
        self.timing.setText(f"{fmt_short(s.start)} → {fmt_short(s.end)} · {s.duration:.2f}s · {p.settings.aspect_ratio}")
        # start frame preview
        start = info["start"]
        if start == "chain":
            prev = p.scenes[i - 1] if i > 0 else None
            if s.chain_frame and ctrl.abs_path(s.chain_frame).exists():
                self.thumb.set_path(ctrl.abs_path(s.chain_frame))
            else:
                self.thumb.clear_thumb(t("last frame of scene") + f" {i}")
            self.thumb_note.setText("🔗 " + t("chained from previous clip") + ("" if prev and prev.video_asset() else
                                                                           " · " + t("waits for it")))
        elif start == "image" and s.image_asset():
            self.thumb.set_path(ctrl.abs_path(s.image_asset().path))
            self.thumb_note.setText(t("scene image") + ("" if s.image_approved else " · " + t("not approved")))
        else:
            self.thumb.clear_thumb(t("text only"))
            self.thumb_note.setText(t("no start image"))
        if full or self.motion.toPlainText() != s.motion_prompt:
            if not self.motion.hasFocus():
                with QSignalBlocker(self.motion):
                    self.motion.setPlainText(s.motion_prompt)
        ckey = (s.video_option, s.video_mode, p.settings.video_option, id(ctrl.catalog), ctrl.settings.google_ultra)
        if full or ckey != getattr(self, "_ckey", None):
            self._ckey = ckey
            fill_video_combo(self.opt, ctrl.catalog, s.video_option,
                             t("Project default") + (f" ({e.label})" if e and not s.video_option else ""))
            fill_mode_combo(self.mode, e, s.video_mode, include_default=True)
        bits = []
        if e:
            bits.append(f"{e.route} · " + (f"model={e.model} · " if e.model else "") +
                        f"mode {info['mode_key']}→{e.modes.get(info['mode_key'], '?')}")
            if info["gen_length"]:
                bits.append(f"{t('generate')} {info['gen_length']}s")
            if info["resolution"]:
                bits.append(info["resolution"])
            if info["trim"] > 0.05:
                bits.append(f"✂ {t('trim')} {info['trim']:.2f}s")
            if info["hold"] > 0.05:
                bits.append(f"⏸ {t('hold last frame')} {info['hold']:.2f}s")
            if info["chained"]:
                bits.append(t("drops duplicate first frame"))
        txt = " · ".join(bits)
        if info["problems"]:
            txt += f"<br><span style='color:{C['danger']}'>⚠ " + "; ".join(info["problems"]) + "</span>"
        self.plan.setText(txt)
        task = s.video_task
        key_running = ctrl.jobs.is_running(f"vid:{s.id}") or (s.id in ctrl._chain_ids and ctrl.jobs.is_running("vid:chain"))
        self.badge.set_state(task.state)
        prog = ctrl.jobs.last_progress.get(f"vid:{s.id}", ctrl.jobs.last_progress.get("vid:chain", (0, "")))[1]
        st = []
        if task.task_id:
            st.append(f"task_id {task.task_id}")
        if task.remote_status and task.busy:
            st.append(task.remote_status)
        if key_running and prog:
            st.append(prog)
        if task.message and task.state not in ("failed",):
            st.append(task.message)
        va = s.video_asset()
        if va:
            st.append(f"{t('using')} v{s.selected_video + 1}" + (f" · {va.duration:.2f}s" if va.duration else "") +
                      (" · " + t("chained") if va.chained else ""))
        self.status.setText(" · ".join(st))
        self.status.setToolTip(task_detail(task))
        err = ""
        if task.state in ("failed", "lost"):
            err = task.error + (f"\n→ {task.hint}" if task.hint else "")
        self.err.setText(err)
        self.err.setVisible(bool(err))
        fb = task.fallback if task.state == "failed" else ""
        self.fallback.setVisible(bool(fb))
        if fb:
            self.fallback.setText(t("Use documented fallback:") + f" {t(MODE_LABELS.get(fb, fb))}")
        with QSignalBlocker(self.versions):
            self.versions.clear()
            for k, a in enumerate(s.videos):
                tag = t("uploaded") if a.source == "uploaded" else f"{a.model} {a.mode}".strip()
                self.versions.addItem(f"v{k + 1} · {tag}", k)
            self.versions.setCurrentIndex(s.selected_video)
            self.versions.setVisible(bool(s.videos))
        self.gen.setText(t("Regenerate") if s.videos else t("Generate"))
        self.gen.setEnabled(not key_running and e is not None)
        self.play.setEnabled(va is not None)
        self.stop.setVisible(key_running)

    def _motion(self) -> None:
        s = self.scene()
        if s:
            s.motion_prompt = self.motion.toPlainText()
            s.prompt_source = "manual"
            self.page.edit("scenes")

    def _opt(self) -> None:
        s = self.scene()
        if s is None or self.opt.currentData() is None:
            return
        s.video_option = self.opt.currentData() or ""
        self.page.ctrl.update_gen_lengths()
        self.page.edit("videos")
        self.update_view()

    def _mode(self) -> None:
        s = self.scene()
        if s is None:
            return
        s.video_mode = self.mode.currentData() or ""
        self.page.ctrl.update_gen_lengths()
        self.page.edit("videos")
        self.update_view()

    def _fallback(self) -> None:
        s = self.scene()
        if not s or not s.video_task.fallback:
            return
        fb = s.video_task.fallback
        s.video_mode = fb
        s.video_task.fallback = ""
        self.page.ctrl.update_gen_lengths()
        self.page.edit("videos")
        self.page.ctrl.notify.emit("info", f"Scene {self.page.project.scene_index(s.id) + 1}: mode set to "
                                           f"'{MODE_LABELS.get(fb, fb)}'. The model was not changed. Press Generate to retry.")
        self.update_view()

    def _version(self) -> None:
        self.page.ctrl.select_video(self.sid, self.versions.currentData())

    def _generate(self) -> None:
        self.page.generate([self.sid])

    def _play(self) -> None:
        self.page.preview(self.sid)

    def _upload(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("Choose clip"), str(Path.home()), "Video (*.mp4 *.mov *.webm *.mkv)")
        if path:
            self.page.ctrl.import_clip(self.sid, Path(path))


class VideosPage(Page):
    title_text = "Video clips"
    subtitle_text = ("Animate each scene with G-Labs Studio. Veo/Omni use /api/video/generate with a model value; Grok and "
                     "Meta use their own routes with t2v / i2v modes.")

    def __init__(self, ctrl, parent=None) -> None:
        super().__init__(ctrl, parent)
        L = self.layout_
        self.rows: dict[str, SceneClipRow] = {}
        self._ids: list[str] = []
        self._aspect = ""
        self.next_btn = self.add_action(button("Continue to edit & export", "right", "primary",
                                               on_click=lambda: ctrl.request_page.emit("export")))
        self.empty = EmptyState("video", "No scenes yet", "Plan scenes, then generate images (or use text-to-video).",
                                "Go to Scenes", lambda: ctrl.request_page.emit("scenes"), "scenes")
        L.addWidget(self.empty)
        self.body_w = QWidget()
        body = QVBoxLayout(self.body_w)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)
        L.addWidget(self.body_w, 1)

        top = ResponsiveRow(16)
        gc = Card("Default video settings", "", "video")
        self.stats = gc.add_action(Badge())
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(8)
        self.opt = QComboBox()
        self.opt.currentIndexChanged.connect(self._opt)
        g.addWidget(labeled("Video model / mode", self.opt), 0, 0, 1, 2)
        self.mode = QComboBox()
        self.mode.currentIndexChanged.connect(self._mode)
        g.addWidget(labeled("Generation mode", self.mode), 1, 0)
        self.res = QComboBox()
        self.res.currentIndexChanged.connect(self._res)
        g.addWidget(labeled("Clip resolution", self.res), 1, 1)
        gc.add(g)
        self.chain = QCheckBox(t("Chain scenes from the previous clip's last frame"))
        self.chain.setToolTip(t("1) extract the last clean frame of scene N, 2) send it as the first frame of scene N+1, "
                                "3) drop the duplicated boundary frame when editing. Clips are generated one after another."))
        self.chain.toggled.connect(self._chain)
        gc.add(self.chain)
        self.help = label("", "Help", wrap=True)
        self.help.setTextFormat(Qt.TextFormat.RichText)
        gc.add(self.help)
        act = QHBoxLayout()
        act.setSpacing(8)
        self.gen_missing = button("Generate missing", "sparkles", "primary", on_click=self._gen_missing)
        self.gen_missing.setObjectName("btnGenerateClips")
        act.addWidget(self.gen_missing)
        act.addWidget(button("Generate selected", "sparkles", "soft", on_click=self._gen_selected))
        act.addWidget(button("All", None, "ghost", on_click=lambda: self._select(True)))
        act.addWidget(button("None", None, "ghost", on_click=lambda: self._select(False)))
        act.addStretch(1)
        self.resume_btn = button("Resume interrupted", "refresh", None, on_click=ctrl.resume_videos)
        act.addWidget(self.resume_btn)
        self.stop_all = button("Stop all", "stop", "danger", "Stops polling. No cancel endpoint exists; remote tasks may "
                               "still finish and use quota.", on_click=lambda: ctrl.jobs.cancel_prefix("vid:"))
        act.addWidget(self.stop_all)
        gc.add(act)
        self.banner = Banner("info", "")
        gc.add(self.banner)
        top.addWidget(gc, 3)

        pc = Card("Clip preview", "", "play")
        self.player = VideoPlayer(200)
        pc.add(self.player)
        self.player_note = label("", "Help", wrap=True)
        pc.add(self.player_note)
        top.addWidget(pc, 2)
        body.addWidget(top)

        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(10)
        body.addLayout(self.list_box)

        ctrl.project_loaded.connect(self._reset)
        ctrl.project_closed.connect(self._reset)
        ctrl.scene_changed.connect(self._scene_changed)
        ctrl.changed.connect(lambda a: a in ("scenes", "images", "videos", "catalog", "setup") and self.mark_stale())
        ctrl.jobs.progress.connect(self._progress)
        ctrl.jobs.changed.connect(self._update_stats)
        ctrl.about_to_render.connect(self.player.release)

    def _reset(self) -> None:
        self._ids = []
        self.player.release()
        self.mark_stale()

    # ------------------------------------------------------------- global settings
    def _opt(self) -> None:
        p = self.project
        v = self.opt.currentData()
        if p and v:
            p.settings.video_option = v
            self.ctrl.update_gen_lengths()
            self.edit("videos")
            self._header()
            self._update_rows()

    def _mode(self) -> None:
        p = self.project
        if p and self.mode.currentData():
            p.settings.video_mode = self.mode.currentData()
            self.ctrl.update_gen_lengths()
            self.edit("videos")
            self._update_rows()

    def _res(self) -> None:
        p = self.project
        if p and self.res.currentData():
            p.settings.video_resolution = self.res.currentData()
            self.edit("videos")
            self._update_rows()

    def _chain(self, on: bool) -> None:
        p = self.project
        if p:
            p.settings.chain_frames = on
            self.ctrl.update_gen_lengths()
            self.edit("videos")
            self._update_rows()
            self._header()

    # ------------------------------------------------------------- actions
    def _select(self, on: bool) -> None:
        for r in self.rows.values():
            r.check.setChecked(on)

    def stop_scene(self, sid: str) -> None:
        if sid in self.ctrl._chain_ids:
            if confirm(self, "Stop chain?", "This scene is part of a chained batch. Stopping it stops the whole chain.", "Stop"):
                self.ctrl.jobs.cancel("vid:chain")
        else:
            self.ctrl.jobs.cancel(f"vid:{sid}")

    def generate(self, ids: list[str]) -> None:
        p = self.project
        if not p or not ids:
            return
        if p.settings.run_mode == "manual" and p.settings.require_image_approval:
            pending = [p.scene_index(s.id) + 1 for s in p.scenes if s.id in ids and s.image_asset() and not s.image_approved]
            if pending:
                if not confirm(self, "Images not approved", f"Scene(s) {', '.join(map(str, pending[:12]))} use images that "
                                                            "are not approved yet. Approve them and continue?", "Approve & continue"):
                    return
                self.ctrl.set_image_approved([s.id for s in p.scenes if s.id in ids], True)
        replacing = [s for s in p.scenes if s.id in ids and s.videos]
        if len(replacing) > 1 and not confirm(self, "Regenerate clips?", f"{len(replacing)} scene(s) already have clips. New "
                                              "versions will be added (old ones are kept). This uses your G-Labs quota.",
                                              "Generate"):
            return
        n = self.ctrl.generate_videos(ids)
        if n:
            self.ctrl.notify.emit("info", f"Started {n} clip task(s)" + (" as a sequential chain." if p.settings.chain_frames
                                                                          and n > 1 else "."))
        self.mark_stale()

    def _gen_missing(self) -> None:
        p = self.project
        ids = [s.id for s in p.scenes if not s.video_asset()]
        if not ids:
            self.ctrl.notify.emit("info", "Every scene already has a clip.")
            return
        self.generate(ids)

    def _gen_selected(self) -> None:
        ids = [sid for sid, r in self.rows.items() if r.check.isChecked()]
        if not ids:
            self.ctrl.notify.emit("info", "Tick the scenes you want to generate first.")
            return
        self.generate(ids)

    def preview(self, sid: str) -> None:
        p = self.project
        s = p.scene(sid)
        a = s.video_asset() if s else None
        if not a:
            return
        self.player.load(self.ctrl.abs_path(a.path), autoplay=True)
        i = p.scene_index(sid)
        info = self.ctrl.video_plan(i)
        self.player_note.setText(f"{t('Scene')} {i + 1} · v{s.selected_video + 1} · {a.model or a.source} {a.mode} · "
                                 + (f"{a.duration:.2f}s {t('clip')} → {s.duration:.2f}s {t('scene')}" if a.duration else "")
                                 + (f" · ✂ {info['trim']:.2f}s" if info['trim'] > 0.05 else ""))

    # ------------------------------------------------------------- refresh
    def _progress(self, key: str, _f: float, _m: str) -> None:
        if key == "vid:chain":
            for sid in self.ctrl._chain_ids:
                self._scene_changed(sid)
        elif key.startswith("vid:"):
            self._scene_changed(key[4:])

    def _scene_changed(self, sid: str) -> None:
        r = self.rows.get(sid)
        if r is not None and self.isVisible():
            r.update_view()
            self._update_stats()
        else:
            self._stale = True

    def _update_rows(self) -> None:
        for r in self.rows.values():
            r.update_view()
        self._update_stats()

    def _update_stats(self) -> None:
        p = self.project
        if not p or not p.scenes:
            return
        done = sum(1 for s in p.scenes if s.video_asset())
        busy = sum(1 for s in p.scenes if s.video_task.busy)
        failed = sum(1 for s in p.scenes if s.video_task.state in ("failed", "lost"))
        self.stats.set(f"{done}/{len(p.scenes)} {t('clips')}" + (f" · {busy} {t('running')}" if busy else "")
                       + (f" · {failed} {t('failed')}" if failed else ""),
                       "error" if failed else "primary" if busy else "ok" if done == len(p.scenes) else "neutral")
        self.stop_all.setVisible(bool(self.ctrl.jobs.running_keys("vid:")))
        self.resume_btn.setVisible(any(s.video_task.state == "interrupted" and s.video_task.task_id for s in p.scenes))

    def _header(self) -> None:
        p = self.project
        e = self.ctrl.video_entry_for()
        fill_video_combo(self.opt, self.ctrl.catalog, p.settings.video_option)
        fill_mode_combo(self.mode, e, p.settings.video_mode)
        with QSignalBlocker(self.res):
            self.res.clear()
            if e:
                for r in e.resolutions:
                    locked = r in e.ultra_resolutions and not self.ctrl.settings.google_ultra
                    self.res.addItem(r + (f"  ({t('ULTRA only')})" if r in e.ultra_resolutions else ""), r)
                    if locked:
                        self.res.model().item(self.res.count() - 1).setEnabled(False)
            idx = self.res.findData(p.settings.video_resolution)
            if idx < 0 and e:
                idx = self.res.findData(e.default_resolution)
            self.res.setCurrentIndex(max(0, idx))
            self.res.setEnabled(self.res.count() > 0)
        with QSignalBlocker(self.chain):
            self.chain.setChecked(p.settings.chain_frames)
        self.help.setText(video_help(e, self.ctrl))
        notes = []
        if p.settings.chain_frames:
            notes.append(t("Chaining is on: selected clips are generated in order, each waiting for the previous one."))
            if e and not e.chaining_supported:
                notes.append(t("The default option does not support start-frame chaining; those scenes are generated "
                               "without it."))
        if p.settings.run_mode == "manual" and p.settings.require_image_approval:
            pending = sum(1 for s in p.scenes if s.image_asset() and not s.image_approved)
            if pending:
                notes.append(f"{pending} {t('image(s) not approved yet (Images page).')}")
        self.banner.set("info", " ".join(notes))

    def refresh(self) -> None:
        p = self.project
        has = bool(p and p.scenes)
        self.empty.setVisible(not has)
        self.body_w.setVisible(has)
        self.next_btn.setVisible(has)
        if not has:
            while self.list_box.count():
                it = self.list_box.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
            self.rows.clear()
            self._ids = []
            return
        self._header()
        ids = [s.id for s in p.scenes]
        if ids != self._ids or self._aspect != p.settings.aspect_ratio:
            checked = {sid for sid, r in self.rows.items() if r.check.isChecked()}
            while self.list_box.count():
                it = self.list_box.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
            self.rows.clear()
            for sid in ids:
                r = SceneClipRow(self, sid)
                r.check.setChecked(sid in checked)
                self.rows[sid] = r
                self.list_box.addWidget(r)
            self._ids = ids
            self._aspect = p.settings.aspect_ratio
        else:
            for r in self.rows.values():
                r.update_view()
        self._update_stats()
