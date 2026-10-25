"""F. Scene planning & prompt review page."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLineEdit, QPlainTextEdit, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...core.i18n import t
from ...core.project import StyleRef
from ...services import project_store
from ...services.srt import fmt_short
from ..theme import C
from ..widgets import (
    Badge, Banner, Card, EmptyState, Page, ResponsiveRow, Segmented, ThumbLabel, button, clear_layout, confirm, hbox,
    label, labeled, tool_button,
)
from .common import fill_image_combo, fill_mode_combo, fill_video_combo

SOURCE_LABELS = {"llm": ("LLM", "primary"), "draft": ("Draft", "warn"), "manual": ("Edited", "info"), "": ("Empty", "neutral")}


class StyleBibleCard(Card):
    def __init__(self, page: "ScenesPage") -> None:
        super().__init__("Character & style bible", "Sent with every prompt request to keep characters, palette and look "
                         "consistent across scenes.", "palette")
        self.page = page
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        self.fields: dict[str, QPlainTextEdit] = {}
        specs = [("visual_style", "Visual style", ""), ("characters", "Characters", "Name + fixed description per character"),
                 ("setting", "Setting / world", ""), ("palette", "Colour palette", ""),
                 ("avoid", "Avoid", "Things that must never appear")]
        for i, (attr, name, ph) in enumerate(specs):
            w = QPlainTextEdit()
            w.setFixedHeight(58)
            w.setPlaceholderText(t(ph))
            w.textChanged.connect(lambda a=attr, ww=w: self._edit(a, ww.toPlainText()))
            self.fields[attr] = w
            g.addWidget(labeled(name, w), i // 3, i % 3)
        self.add(g)
        self.add(label(t("Reference images"), "FieldLabel"))
        self.refs_note = label("", "Help", wrap=True)
        self.add(self.refs_note)
        self.refs_box = QHBoxLayout()
        self.refs_box.setSpacing(10)
        self.add(self.refs_box)

    def _edit(self, attr: str, v: str) -> None:
        p = self.page.project
        if p and getattr(p.style, attr) != v:
            setattr(p.style, attr, v)
            self.page.edit("style")

    def refresh(self) -> None:
        p = self.page.project
        if not p:
            return
        for attr, w in self.fields.items():
            if w.toPlainText() != getattr(p.style, attr):
                with QSignalBlocker(w):
                    w.setPlainText(getattr(p.style, attr))
        e = self.page.ctrl.image_entry_for()
        tag = (t("This image model supports @tag binding: prompts can reference images by name, e.g. @Maya.")
               if e and e.supports_tag_binding else
               t("References are sent in order (no @tag binding for this model)."))
        self.refs_note.setText(t("Characters, objects or style frames to send with image requests.") + " " + tag +
                               (f" {t('Max')} {e.max_reference_images} {t('per request')}." if e else ""))
        clear_layout(self.refs_box)
        for i, r in enumerate(p.style.references):
            fr = QFrame()
            fr.setObjectName("SoftPanel")
            v = QVBoxLayout(fr)
            v.setContentsMargins(8, 8, 8, 8)
            v.setSpacing(4)
            th = ThumbLabel(110, 80)
            th.set_path(self.page.ctrl.abs_path(r.path), crop=True)
            v.addWidget(th)
            name = QLineEdit(r.name)
            name.setPlaceholderText(t("name / @tag"))
            name.setFixedWidth(110)
            name.editingFinished.connect(lambda ref=r, w=name: self._set_ref(ref, "name", w.text().strip().lstrip("@")))
            v.addWidget(name)
            role = QComboBox()
            role.addItems(["subject", "scene", "style"])
            role.setCurrentText(r.role)
            role.setFixedWidth(110)
            role.currentTextChanged.connect(lambda val, ref=r: self._set_ref(ref, "role", val))
            v.addWidget(role)
            use = QCheckBox(t("Use by default"))
            use.setChecked(r.use_by_default)
            use.toggled.connect(lambda val, ref=r: self._set_ref(ref, "use_by_default", val))
            v.addWidget(use)
            v.addWidget(button("Remove", "trash", "ghost", on_click=lambda idx=i: self._remove(idx)))
            self.refs_box.addWidget(fr)
        add = button("Add reference image", "plus", "soft", on_click=self._add)
        self.refs_box.addWidget(add, 0, Qt.AlignmentFlag.AlignTop)
        self.refs_box.addStretch(1)

    def _set_ref(self, ref: StyleRef, attr: str, v) -> None:
        setattr(ref, attr, v)
        self.page.edit("style")

    def _add(self) -> None:
        ctrl = self.page.ctrl
        paths, _ = QFileDialog.getOpenFileNames(self, t("Add reference images"), str(Path.home()),
                                                "Images (*.png *.jpg *.jpeg *.webp)")
        for src in paths:
            src_p = Path(src)
            dst = project_store.next_version_path(ctrl.folder, "assets/refs", src_p.stem[:40], src_p.suffix.lower())
            shutil.copyfile(src_p, dst)
            ctrl.project.style.references.append(StyleRef(path=ctrl.rel_path(dst), name=src_p.stem[:24].replace(" ", "_")))
        if paths:
            ctrl.mark_dirty("style")
            self.refresh()

    def _remove(self, idx: int) -> None:
        refs = self.page.project.style.references
        if 0 <= idx < len(refs):
            del refs[idx]
            self.page.ctrl.mark_dirty("style")
            self.refresh()


class ScenesPage(Page):
    title_text = "Scenes & prompts"
    subtitle_text = ("Narration is cut into visual beats from the subtitle timing. Each scene gets an image prompt and a "
                     "motion prompt — written by your LLM, drafted from the narration, or by you.")

    def __init__(self, ctrl, parent=None) -> None:
        super().__init__(ctrl, parent)
        L = self.layout_
        self._sid = ""
        self.next_btn = self.add_action(button("Continue to images", "right", "primary",
                                               on_click=lambda: ctrl.request_page.emit("images")))
        self.empty = EmptyState("scenes", "Subtitles needed first",
                                "Align and review subtitles, then plan scenes here.", "Go to Subtitles",
                                lambda: ctrl.request_page.emit("subtitles"), "captions")
        L.addWidget(self.empty)
        self.body_w = QWidget()
        body = QVBoxLayout(self.body_w)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)
        L.addWidget(self.body_w, 1)

        # planning + prompt toolbar
        top = ResponsiveRow(16)
        pc = Card("Scene planning", "", "scenes")
        r = QHBoxLayout()
        r.setSpacing(12)
        self.clip_mode = Segmented([("flexible", "Flexible"), ("fixed8", "Fixed 8 s")])
        self.clip_mode.changed.connect(self._clip_mode)
        r.addWidget(labeled("Clip duration", self.clip_mode))
        self.spins = {}
        for attr, name in (("min_scene", "Min"), ("target_scene", "Target"), ("max_scene", "Max")):
            s = QDoubleSpinBox()
            s.setRange(2.0, 15.0)
            s.setSingleStep(0.5)
            s.setSuffix(" s")
            s.valueChanged.connect(lambda v, a=attr: self._spin(a, v))
            self.spins[attr] = s
            r.addWidget(labeled(name, s))
        r.addStretch(1)
        self.plan_btn = button("Plan scenes", "scenes", "primary", on_click=self._plan)
        self.plan_btn.setObjectName("btnPlanScenes")
        r.addWidget(self.plan_btn, 0, Qt.AlignmentFlag.AlignBottom)
        pc.add(r)
        self.plan_note = label("", "Help", wrap=True)
        pc.add(self.plan_note)
        top.addWidget(pc, 3)

        prc = Card("Prompt writing", "", "sparkles")
        self.llm_badge = prc.add_action(Badge())
        r2 = QHBoxLayout()
        r2.setSpacing(8)
        self.llm_all = button("Write all with LLM", "sparkles", "primary", on_click=lambda: self._llm(None))
        self.llm_all.setObjectName("btnPromptsLLM")
        r2.addWidget(self.llm_all)
        self.llm_missing = button("Only missing", None, "soft", on_click=self._llm_missing)
        r2.addWidget(self.llm_missing)
        self.draft_btn = button("Draft from narration", "wand", None, "Offline template: combines the style bible with each "
                                "scene's narration. Good starting point when no LLM is configured.", on_click=self._draft)
        self.draft_btn.setObjectName("btnDraftPrompts")
        r2.addWidget(self.draft_btn)
        r2.addStretch(1)
        prc.add(r2)
        self.review_cb = QCheckBox(t("Review prompts before generating images"))
        self.review_cb.setToolTip(t("In automatic mode the run pauses here so you can check the prompts."))
        self.review_cb.toggled.connect(self._review)
        prc.add(self.review_cb)
        self.llm_note = label("", "Help", wrap=True)
        prc.add(self.llm_note)
        top.addWidget(prc, 4)
        body.addWidget(top)

        self.warn = Banner("warn", "")
        body.addWidget(self.warn)

        # table + editor
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        tcard = Card("Scenes", "", None, margins=12)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([t("#"), t("Time"), t("Dur."), t("Narration"), t("Prompts"), t("Model")])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(True)
        hh = self.table.horizontalHeader()
        for c in (0, 1, 2, 4, 5):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(560)
        self.table.itemSelectionChanged.connect(self._selected)
        tcard.add(self.table, 1)
        split.addWidget(tcard)

        self.editor = Card("Scene", "", None, accent=True)
        self.ed_meta = label("", "Help", wrap=True)
        self.editor.add(self.ed_meta)
        self.ed_text = label("", None, wrap=True, selectable=True)
        self.ed_text.setStyleSheet(f"background:{C['surface2']}; border-radius:8px; padding:10px; font-size:13px;")
        self.editor.add(labeled("Narration in this scene", self.ed_text))
        self.ed_src = Badge()
        self.ed_img = QPlainTextEdit()
        self.ed_img.setObjectName("imagePrompt")
        self.ed_img.setMinimumHeight(110)
        self.ed_img.textChanged.connect(lambda: self._prompt("image_prompt", self.ed_img.toPlainText()))
        self.editor.add(labeled("Image prompt", self.ed_img, "Describe one still frame: subject, setting, composition, "
                                "lighting. No on-screen text."))
        self.ed_mot = QPlainTextEdit()
        self.ed_mot.setObjectName("motionPrompt")
        self.ed_mot.setMinimumHeight(80)
        self.ed_mot.textChanged.connect(lambda: self._prompt("motion_prompt", self.ed_mot.toPlainText()))
        self.editor.add(labeled("Motion prompt", self.ed_mot, "What moves and how the camera moves during the clip."))
        self.ed_err = Banner("error", "")
        self.editor.add(self.ed_err)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self.ed_src)
        row.addStretch(1)
        self.ed_regen = button("Regenerate prompt", "sparkles", "soft", on_click=lambda: self._llm([self._sid]))
        row.addWidget(self.ed_regen)
        row.addWidget(button("Draft", "wand", "ghost", on_click=lambda: self._draft([self._sid], True)))
        self.editor.add(row)

        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(8)
        self.ov_img = QComboBox()
        self.ov_img.currentIndexChanged.connect(self._ov_img)
        g.addWidget(labeled("Image model (this scene)", self.ov_img), 0, 0)
        self.ov_vid = QComboBox()
        self.ov_vid.currentIndexChanged.connect(self._ov_vid)
        g.addWidget(labeled("Video option (this scene)", self.ov_vid), 0, 1)
        self.ov_mode = QComboBox()
        self.ov_mode.currentIndexChanged.connect(self._ov_mode)
        g.addWidget(labeled("Video mode", self.ov_mode), 1, 0)
        self.ov_start = QDoubleSpinBox()
        self.ov_start.setDecimals(2)
        self.ov_start.setSuffix(" s")
        self.ov_start.setSingleStep(0.1)
        self.ov_start.setToolTip(t("Move the cut between this scene and the previous one."))
        self.ov_start.editingFinished.connect(self._boundary)
        g.addWidget(labeled("Scene starts at", self.ov_start), 1, 1)
        self.editor.add(g)
        self.ed_plan = label("", "Help", wrap=True)
        self.editor.add(self.ed_plan)
        self.ed_refs_box = QVBoxLayout()
        self.ed_refs_box.setSpacing(4)
        self.editor.add(self.ed_refs_box)
        act = QHBoxLayout()
        act.setSpacing(6)
        act.addWidget(button("Split", "split", "ghost", "Split at the best sentence/pause boundary",
                             on_click=lambda: self._scene_op("split")))
        act.addWidget(button("Merge with next", "merge", "ghost", on_click=lambda: self._scene_op("merge")))
        act.addWidget(button("Delete", "trash", "danger", "Remove scene (its time joins the neighbour)",
                             on_click=lambda: self._scene_op("delete")))
        act.addStretch(1)
        act.addWidget(tool_button("up", "Previous scene", lambda: self._step(-1)))
        act.addWidget(tool_button("down", "Next scene", lambda: self._step(1)))
        self.editor.add(act)
        split.addWidget(self.editor)
        split.setSizes([620, 520])
        body.addWidget(split, 1)

        self.bible = StyleBibleCard(self)
        body.addWidget(self.bible)

        ctrl.project_loaded.connect(self._reset)
        ctrl.project_closed.connect(self._reset)
        ctrl.changed.connect(lambda a: a in ("scenes", "subtitles", "catalog", "setup", "videos", "images") and self.mark_stale())
        ctrl.task_changed.connect(lambda k: k == "prompts" and self.mark_stale())
        ctrl.scene_changed.connect(lambda sid: self.mark_stale())

    def _reset(self) -> None:
        self._sid = ""
        self.mark_stale()

    # ------------------------------------------------------------- planning
    def _clip_mode(self, v: str) -> None:
        if self.project:
            self.project.settings.clip_mode = v
            self.edit("setup")
            self._spins_enabled()

    def _spin(self, attr: str, v: float) -> None:
        if self.project:
            setattr(self.project.settings, attr, v)
            self.edit("setup")

    def _spins_enabled(self) -> None:
        flex = self.project is not None and self.project.settings.clip_mode == "flexible"
        for s in self.spins.values():
            s.setEnabled(flex)

    def _plan(self) -> None:
        p = self.project
        if not p:
            return
        if p.scenes:
            has_assets = any(s.images or s.videos for s in p.scenes)
            msg = ("Re-planning replaces all scenes and their prompts." +
                   (" Generated images/clips stay on disk in assets/, but will no longer be linked to scenes." if has_assets else ""))
            if not confirm(self, "Re-plan scenes?", msg, "Re-plan", danger=has_assets):
                return
        if not p.alignment.reviewed and p.settings.run_mode == "manual":
            if not confirm(self, "Subtitles not reviewed", "Scenes follow subtitle timing. Plan anyway without reviewing "
                                                           "the subtitles?", "Plan anyway"):
                return
        self._sid = ""
        self.ctrl.plan_scenes()

    def _review(self, v: bool) -> None:
        if self.project:
            self.project.settings.review_prompts = v
            self.edit("setup")

    # ------------------------------------------------------------- prompts
    def _llm(self, ids: list[str] | None) -> None:
        p = self.project
        if not p:
            return
        if ids is None and any(s.image_prompt.strip() for s in p.scenes):
            if not confirm(self, "Rewrite all prompts?", "Replace existing prompts (including your edits) in every scene?",
                           "Rewrite all"):
                return
        self.ctrl.generate_prompts(ids)
        self.mark_stale()

    def _llm_missing(self) -> None:
        p = self.project
        if p:
            ids = [s.id for s in p.scenes if not (s.image_prompt.strip() and s.motion_prompt.strip())]
            if ids:
                self.ctrl.generate_prompts(ids)
            else:
                self.ctrl.notify.emit("info", "Every scene already has both prompts.")

    def _draft(self, ids: list[str] | None = None, overwrite: bool = False) -> None:
        if ids and ids[0] and self.project.scene(ids[0]) and self.project.scene(ids[0]).image_prompt.strip():
            if not confirm(self, "Replace prompt?", "Replace this scene's prompts with a draft?", "Replace"):
                return
            overwrite = True
        n = self.ctrl.draft_prompts(ids, overwrite)
        self.ctrl.notify.emit("info" if n else "warning", f"Drafted prompts for {n} scene(s)." if n else
                              "All selected scenes already have prompts.")
        self.mark_stale()

    def _scene(self):
        return self.project.scene(self._sid) if self.project and self._sid else None

    def _prompt(self, attr: str, v: str) -> None:
        s = self._scene()
        if s and getattr(s, attr) != v:
            setattr(s, attr, v)
            s.prompt_source = "manual"
            self.edit("scenes")
            self._update_row(self.project.scene_index(s.id))
            self.ed_src.set(*SOURCE_LABELS.get(s.prompt_source, SOURCE_LABELS[""]))

    # ------------------------------------------------------------- overrides
    def _ov_img(self) -> None:
        s = self._scene()
        if s:
            s.image_model = self.ov_img.currentData() or ""
            self.edit("scenes")
            self._update_row(self.project.scene_index(s.id))

    def _ov_vid(self) -> None:
        s = self._scene()
        if s and self.ov_vid.currentData() is not None:
            s.video_option = self.ov_vid.currentData() or ""
            self.ctrl.update_gen_lengths()
            self.edit("scenes")
            fill_mode_combo(self.ov_mode, self.ctrl.video_entry_for(s), s.video_mode, include_default=True)
            self._update_plan()
            self._update_row(self.project.scene_index(s.id))

    def _ov_mode(self) -> None:
        s = self._scene()
        if s:
            s.video_mode = self.ov_mode.currentData() or ""
            self.ctrl.update_gen_lengths()
            self.edit("scenes")
            self._update_plan()

    def _boundary(self) -> None:
        p, s = self.project, self._scene()
        if not s:
            return
        i = p.scene_index(s.id)
        if i <= 0:
            return
        if not self.ctrl.set_boundary(i, self.ov_start.value()):
            self.ctrl.notify.emit("warning", "That cut point would make a scene shorter than 0.5 s.")
        self.mark_stale()

    def _ref_toggle(self, name: str, on: bool) -> None:
        s = self._scene()
        p = self.project
        if not s:
            return
        current = s.ref_names if s.ref_names is not None else [r.name for r in p.style.references if r.use_by_default]
        current = [n for n in current if n != name] + ([name] if on else [])
        s.ref_names = current
        self.edit("scenes")

    def _scene_op(self, op: str) -> None:
        s = self._scene()
        p = self.project
        if not s:
            return
        i = p.scene_index(s.id)
        if op == "split":
            self.ctrl.split_scene(s.id)
        elif op == "merge":
            if i + 1 >= len(p.scenes):
                return
            nxt = p.scenes[i + 1]
            if (nxt.images or nxt.videos) and not confirm(self, "Merge scenes?", "The next scene has generated assets; they "
                                                          "will be unlinked (files stay on disk).", "Merge", danger=True):
                return
            self.ctrl.merge_scene_with_next(s.id)
        elif op == "delete":
            if len(p.scenes) < 2:
                return
            if not confirm(self, "Delete scene?", f"Delete scene {i + 1}? Its time span joins the neighbouring scene."
                           + (" Its generated files stay on disk." if s.images or s.videos else ""), "Delete", danger=True):
                return
            self.ctrl.delete_scene(s.id)
            self._sid = p.scenes[max(0, i - 1)].id if p.scenes else ""
        self.mark_stale()

    def _step(self, d: int) -> None:
        p = self.project
        if not p or not p.scenes:
            return
        i = max(0, min(len(p.scenes) - 1, p.scene_index(self._sid) + d))
        self.table.selectRow(i)

    # ------------------------------------------------------------- refresh
    def _selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        p = self.project
        if not p or not rows or rows[0] >= len(p.scenes):
            return
        self._sid = p.scenes[rows[0]].id
        self._load_editor()

    def selected_ids(self) -> list[str]:
        p = self.project
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [p.scenes[r].id for r in rows if p and r < len(p.scenes)]

    def _row_values(self, i: int) -> list[str]:
        s = self.project.scenes[i]
        busy = s.prompt_task.state == "running"
        pr = ("⏳ " + t("writing…")) if busy else (
            ("✓ " + t("both") if s.image_prompt.strip() and s.motion_prompt.strip() else
             "◐ " + t("partial") if s.image_prompt.strip() or s.motion_prompt.strip() else "— " + t("none")))
        if s.prompt_task.state == "failed":
            pr = "✖ " + t("failed")
        model = (s.image_model or "·") + " / " + (s.video_option or "·")
        return [str(i + 1), f"{fmt_short(s.start)}–{fmt_short(s.end)}", f"{s.duration:.1f}s", s.text, pr, model]

    def _update_row(self, i: int) -> None:
        if not (0 <= i < self.table.rowCount()):
            return
        for c, v in enumerate(self._row_values(i)):
            it = self.table.item(i, c)
            if it:
                it.setText(v)

    def _update_plan(self) -> None:
        p, s = self.project, self._scene()
        if not s:
            return
        i = p.scene_index(s.id)
        info = self.ctrl.video_plan(i)
        e = info["entry"]
        if e is None:
            self.ed_plan.setText("⚠ " + "; ".join(info["problems"]))
            return
        bits = [f"{t('Generation')}: {e.label} · {info['mode_key'] or '—'}"]
        if info["gen_length"]:
            bits.append(f"{t('native length')} {info['gen_length']}s")
        if info["trim"] > 0.05:
            bits.append(f"✂ {t('trimmed by')} {info['trim']:.2f}s {t('to fit the scene')}")
        if info["hold"] > 0.05:
            bits.append(f"⏸ {t('last frame held')} {info['hold']:.2f}s")
        if info["chained"]:
            bits.append("🔗 " + t("starts from previous clip's last frame"))
        txt = " · ".join(bits)
        if info["problems"]:
            txt += "\n⚠ " + "; ".join(info["problems"])
        self.ed_plan.setText(txt)

    def _load_editor(self) -> None:
        p, s = self.project, self._scene()
        self.editor.setEnabled(s is not None)
        if not s:
            self.editor.title_label.setText(t("Select a scene"))
            return
        i = p.scene_index(s.id)
        self.editor.title_label.setText(f"{t('Scene')} {i + 1} {t('of')} {len(p.scenes)}")
        self.ed_meta.setText(f"{fmt_short(s.start)} → {fmt_short(s.end)} · {s.duration:.2f}s")
        self.ed_text.setText(s.text or t("(no narration words in this span)"))
        for w, v in ((self.ed_img, s.image_prompt), (self.ed_mot, s.motion_prompt)):
            if w.toPlainText() != v:
                with QSignalBlocker(w):
                    w.setPlainText(v)
        self.ed_src.set(*SOURCE_LABELS.get(s.prompt_source, SOURCE_LABELS[""]))
        pt = s.prompt_task
        self.ed_err.set("error" if pt.state == "failed" else "info",
                        (pt.error + (f" → {pt.hint}" if pt.hint else "")) if pt.state == "failed" else
                        (t("The LLM is writing this scene's prompts…") if pt.state == "running" else ""))
        self.ed_regen.setEnabled(self.ctrl.llm_ready() and not self.ctrl.jobs.is_running("prompts"))
        fill_image_combo(self.ov_img, self.ctrl.catalog, s.image_model, t("Project default"))
        fill_video_combo(self.ov_vid, self.ctrl.catalog, s.video_option, t("Project default"))
        fill_mode_combo(self.ov_mode, self.ctrl.video_entry_for(s), s.video_mode, include_default=True)
        with QSignalBlocker(self.ov_start):
            self.ov_start.setRange(0.0, max(0.0, p.voice.duration or s.end))
            self.ov_start.setValue(s.start)
            self.ov_start.setEnabled(i > 0)
        self._update_plan()
        clear_layout(self.ed_refs_box)
        if p.style.references:
            self.ed_refs_box.addWidget(label(t("References sent with this scene's image"), "FieldLabel"))
            current = s.ref_names if s.ref_names is not None else [r.name for r in p.style.references if r.use_by_default]
            for r in p.style.references:
                cb = QCheckBox(f"{r.name or Path(r.path).name}  ·  {r.role}")
                cb.setChecked(r.name in current)
                cb.toggled.connect(lambda on, n=r.name: self._ref_toggle(n, on))
                self.ed_refs_box.addWidget(cb)

    def refresh(self) -> None:
        p = self.project
        ready = bool(p and (p.cues or p.scenes))
        self.empty.setVisible(not ready)
        self.body_w.setVisible(ready)
        self.next_btn.setVisible(bool(p and p.scenes))
        if not p or not ready:
            return
        st = p.settings
        self.clip_mode.set_value(st.clip_mode)
        for attr, s in self.spins.items():
            with QSignalBlocker(s):
                s.setValue(getattr(st, attr))
        self._spins_enabled()
        with QSignalBlocker(self.review_cb):
            self.review_cb.setChecked(st.review_prompts)
        mx = self.ctrl.max_scene_len()
        e = self.ctrl.video_entry_for()
        self.plan_note.setText(
            (f"{t('Max scene length')} {mx:g}s — {t('limited by the longest native clip of')} {e.label}. " if e else "") +
            t("Clips are generated at a supported native length and trimmed to each scene; scenes longer than the clip hold "
              "the last frame."))
        self.plan_btn.setText(t("Re-plan scenes") if p.scenes else t("Plan scenes"))
        busy = self.ctrl.jobs.is_running("prompts")
        ready_llm = self.ctrl.llm_ready()
        self.llm_all.setEnabled(ready_llm and not busy and bool(p.scenes))
        self.llm_missing.setEnabled(ready_llm and not busy and bool(p.scenes))
        self.draft_btn.setEnabled(bool(p.scenes))
        s = self.ctrl.settings
        if ready_llm:
            self.llm_badge.set(f"{s.llm_provider} · {s.llm_model or 'default'}" if not busy else t("Writing…"),
                               "primary" if busy else "ok")
            self.llm_note.setText(t("Prompts are generated from the narration, style bible, aspect ratio and project context."))
        else:
            self.llm_badge.set("No LLM configured", "neutral")
            self.llm_note.setText(t("No prompt LLM is configured (Settings → Prompt generation). You can draft prompts from "
                                    "the narration or write them yourself and continue."))
        missing = sum(1 for sc in p.scenes if not (sc.image_prompt.strip() and sc.motion_prompt.strip()))
        warn = []
        if p.scenes and missing:
            warn.append(f"{missing} {t('scene(s) still need prompts.')}")
        if not p.alignment.reviewed and p.cues:
            warn.append(t("Subtitles have not been marked reviewed yet."))
        self.warn.set("warn", " ".join(warn))
        with QSignalBlocker(self.table):
            self.table.setRowCount(len(p.scenes))
            for i in range(len(p.scenes)):
                for c, v in enumerate(self._row_values(i)):
                    it = self.table.item(i, c)
                    if it is None:
                        it = QTableWidgetItem()
                        self.table.setItem(i, c, it)
                    it.setText(v)
                    if c == 4:
                        sc = p.scenes[i]
                        it.setForeground(QColor(C["danger"] if sc.prompt_task.state == "failed" else
                                                C["success"] if sc.image_prompt.strip() and sc.motion_prompt.strip() else C["warning"]))
            self.table.resizeRowsToContents()
        if p.scenes:
            idx = p.scene_index(self._sid)
            if idx < 0:
                idx = 0
                self._sid = p.scenes[0].id
            with QSignalBlocker(self.table):
                self.table.selectRow(idx)
        else:
            self._sid = ""
        self._load_editor()
        self.bible.refresh()
