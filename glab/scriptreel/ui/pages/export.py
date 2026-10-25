"""I. Edit & export page."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLineEdit, QProgressBar, QPushButton,
    QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from ...core.i18n import t
from ...core.project import RESOLUTIONS, render_dims
from ...services.srt import fmt_short
from ..media import CropPreview, VideoPlayer
from ..timeline import TLScene, Timeline
from ..widgets import (
    Badge, Banner, Card, EmptyState, Page, PathField, PosterCache, ResponsiveRow, Segmented, StatusLine, button, confirm,
    hbox, label, labeled, tool_button,
)


class ColorButton(QPushButton):
    def __init__(self, on_change) -> None:
        super().__init__()
        self._color = "#FFFFFF"
        self._cb = on_change
        self.setFixedWidth(70)
        self.clicked.connect(self._pick)

    def set_color(self, c: str) -> None:
        self._color = c
        self.setText(c.upper())
        fg = "#000000" if QColor(c).lightness() > 140 else "#FFFFFF"
        self.setStyleSheet(f"background:{c}; color:{fg}; border:1px solid #CED5E3; border-radius:8px; padding:6px;")

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self, t("Choose colour"))
        if c.isValid():
            self.set_color(c.name())
            self._cb(c.name())


class ExportPage(Page):
    title_text = "Edit & export"
    subtitle_text = ("Arrange clips on the narration timeline, frame them for the target ratio and render the final MP4 "
                     "with FFmpeg. Output length always matches the narration.")

    def __init__(self, ctrl, parent=None) -> None:
        super().__init__(ctrl, parent)
        L = self.layout_
        self._sid = ""
        self.posters = PosterCache(self)
        self.posters.ready.connect(lambda _v: self._load_inspector())
        self.open_btn = self.add_action(button("Open renders folder", "folder-open", "ghost", on_click=self._open_folder))
        self.empty = EmptyState("scissors", "Nothing to edit yet", "Generate narration and plan scenes first. Scenes without "
                                "clips render as a slow pan over their image, so you can export at any stage.",
                                "Go to Scenes", lambda: ctrl.request_page.emit("scenes"), "scenes")
        L.addWidget(self.empty)
        self.body_w = QWidget()
        body = QVBoxLayout(self.body_w)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)
        L.addWidget(self.body_w, 1)

        # preview + inspector
        top = ResponsiveRow(16)
        pc = Card("Preview", "", "play")
        self.src = Segmented([("final", "Final render"), ("clip", "Selected clip")], "final")
        self.src.changed.connect(lambda _v: self._load_preview())
        pc.add_action(self.src)
        self.player = VideoPlayer(300)
        self.player.position.connect(self._player_pos)
        pc.add(self.player, 1)
        self.preview_note = label("", "Help", wrap=True)
        pc.add(self.preview_note)
        top.addWidget(pc, 5)

        ic = Card("Scene inspector", "", "sliders")
        self.ins_title = ic.title_label
        self.crop = CropPreview()
        self.crop.setMinimumHeight(190)
        self.crop.focal_changed.connect(self._focal)
        ic.add(self.crop)
        ic.add(label(t("Drag the frame to move the focal point (Fill). Dashed lines: title-safe area and subtitle zone."),
                     "Faint", wrap=True))
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(8)
        self.crop_mode = QComboBox()
        self.crop_mode.addItem(t("Project default"), "")
        self.crop_mode.addItem(t("Fill (crop to frame)"), "fill")
        self.crop_mode.addItem(t("Fit (letterbox)"), "fit")
        self.crop_mode.currentIndexChanged.connect(self._crop_mode)
        g.addWidget(labeled("Crop mode", self.crop_mode), 0, 0)
        self.trim = QDoubleSpinBox()
        self.trim.setRange(0.0, 6.0)
        self.trim.setSingleStep(0.1)
        self.trim.setSuffix(" s")
        self.trim.setToolTip(t("Skip this much from the start of the clip (trim leading edge). Generation length accounts "
                               "for it."))
        self.trim.valueChanged.connect(self._trim)
        g.addWidget(labeled("Trim clip start", self.trim), 0, 1)
        self.fx = QDoubleSpinBox()
        self.fy = QDoubleSpinBox()
        for w, a in ((self.fx, "focal_x"), (self.fy, "focal_y")):
            w.setRange(0.0, 1.0)
            w.setSingleStep(0.05)
            w.setDecimals(2)
            w.valueChanged.connect(lambda v, attr=a: self._focal_spin(attr, v))
        g.addWidget(labeled("Focal X", self.fx), 1, 0)
        g.addWidget(labeled("Focal Y", self.fy), 1, 1)
        ic.add(g)
        self.ins_info = label("", "Help", wrap=True)
        ic.add(self.ins_info)
        ic.add(hbox(button("Move earlier", "left", "ghost", "Swap this scene's visuals with the previous scene (narration "
                           "timing stays)", on_click=lambda: self._move(-1)),
                    button("Move later", "right", "ghost", on_click=lambda: self._move(1)), None,
                    tool_button("eye", "Play this clip", self._play_clip)))
        top.addWidget(ic, 4)
        body.addWidget(top)

        # timeline
        tc = Card("Timeline", "Click to select a scene · drag a cut to retime it · ✂ = clip is trimmed to fit.", "film",
                  margins=14)
        self.tl_legend = tc.add_action(label(
            "<span style='color:#5B4BDB'>■</span> clip &nbsp; <span style='color:#2F6FEB'>■</span> image pan &nbsp; "
            "<span style='color:#A7B0C6'>■</span> title card &nbsp; <span style='color:#C9343F'>■</span> failed", "Faint"))
        self.timeline = Timeline()
        self.timeline.scene_clicked.connect(self._select)
        self.timeline.boundary_moved.connect(self._boundary)
        self.timeline.seek.connect(self._seek)
        tc.add(self.timeline)
        body.addWidget(tc)

        # settings
        row = ResponsiveRow(16)
        fc = Card("Format", "", "layers")
        self.aspect = Segmented([("16:9", "16:9"), ("9:16", "9:16")])
        self.aspect.changed.connect(self._aspect)
        fc.add(labeled("Aspect ratio", self.aspect))
        g2 = QGridLayout()
        g2.setHorizontalSpacing(10)
        g2.setVerticalSpacing(8)
        self.res = QComboBox()
        for r in RESOLUTIONS:
            self.res.addItem(r, r)
        self.res.currentIndexChanged.connect(lambda: self._r("resolution", self.res.currentData()))
        g2.addWidget(labeled("Resolution", self.res), 0, 0)
        self.fps = QComboBox()
        for f in (24, 25, 30, 50, 60):
            self.fps.addItem(f"{f} fps", f)
        self.fps.currentIndexChanged.connect(lambda: self._r("fps", self.fps.currentData()))
        g2.addWidget(labeled("Frame rate", self.fps), 0, 1)
        self.def_crop = Segmented([("fill", "Fill"), ("fit", "Fit")])
        self.def_crop.changed.connect(lambda v: self._r("crop_mode", v))
        g2.addWidget(labeled("Default framing", self.def_crop), 1, 0)
        self.fit_bg = QComboBox()
        self.fit_bg.addItem(t("Blurred background"), "blur")
        self.fit_bg.addItem(t("Black bars"), "black")
        self.fit_bg.currentIndexChanged.connect(lambda: self._r("fit_background", self.fit_bg.currentData()))
        g2.addWidget(labeled("Fit background", self.fit_bg), 1, 1)
        self.crf = QSpinBox()
        self.crf.setRange(14, 32)
        self.crf.setToolTip(t("H.264 quality (lower = better quality, bigger file). 18–22 is a good range."))
        self.crf.valueChanged.connect(lambda v: self._r("crf", v))
        g2.addWidget(labeled("Quality (CRF)", self.crf), 2, 0)
        self.preset = QComboBox()
        self.preset.addItems(["veryfast", "faster", "fast", "medium", "slow"])
        self.preset.currentTextChanged.connect(lambda v: self._r("preset", v))
        g2.addWidget(labeled("Encoder preset", self.preset), 2, 1)
        fc.add(g2)
        self.frame_note = label("", "Help", wrap=True)
        fc.add(self.frame_note)
        row.addWidget(fc)

        sc = Card("Subtitles", "", "captions")
        self.burn = QCheckBox(t("Burn subtitles into the video"))
        self.burn.toggled.connect(self._burn)
        sc.add(self.burn)
        self.soft = QCheckBox(t("Also add a selectable subtitle track (mov_text)"))
        self.soft.toggled.connect(lambda v: self._r("soft_subtitles", v))
        sc.add(self.soft)
        g3 = QGridLayout()
        g3.setHorizontalSpacing(10)
        g3.setVerticalSpacing(8)
        self.font_ed = QLineEdit()
        self.font_ed.editingFinished.connect(lambda: self._st("font", self.font_ed.text().strip() or "Arial"))
        g3.addWidget(labeled("Font", self.font_ed), 0, 0)
        self.size = QSpinBox()
        self.size.setRange(8, 48)
        self.size.valueChanged.connect(lambda v: self._st("size", v))
        g3.addWidget(labeled("Size", self.size), 0, 1)
        self.color = ColorButton(lambda c: self._st("color", c))
        g3.addWidget(labeled("Text", self.color), 1, 0)
        self.ocolor = ColorButton(lambda c: self._st("outline_color", c))
        g3.addWidget(labeled("Outline", self.ocolor), 1, 1)
        self.outline = QDoubleSpinBox()
        self.outline.setRange(0, 6)
        self.outline.setSingleStep(0.5)
        self.outline.valueChanged.connect(lambda v: self._st("outline", v))
        g3.addWidget(labeled("Outline width", self.outline), 2, 0)
        self.margin = QSpinBox()
        self.margin.setRange(0, 140)
        self.margin.setToolTip(t("Distance from the bottom edge (libass units, 288 = full height)."))
        self.margin.valueChanged.connect(lambda v: self._st("margin_v", v))
        g3.addWidget(labeled("Bottom margin", self.margin), 2, 1)
        sc.add(g3)
        self.bold = QCheckBox(t("Bold"))
        self.bold.toggled.connect(lambda v: self._st("bold", v))
        self.box = QCheckBox(t("Background box"))
        self.box.toggled.connect(lambda v: self._st("box", v))
        sc.add(hbox(self.bold, self.box, None))
        self.sub_note = label("", "Help", wrap=True)
        sc.add(self.sub_note)
        row.addWidget(sc)

        ac = Card("Audio", "", "music")
        self.nvol = QSlider(Qt.Orientation.Horizontal)
        self.nvol.setRange(0, 200)
        self.nvol.valueChanged.connect(lambda v: self._r("narration_volume", v / 100))
        self.nvol_l = label("", "Help")
        ac.add(labeled("Narration volume", hbox(self.nvol, self.nvol_l)))
        self.music = PathField("file", "Optional background music", "Audio (*.mp3 *.wav *.m4a *.aac *.ogg *.flac)")
        self.music.changed.connect(self._music)
        ac.add(labeled("Background music", self.music, "Copied into the project. Loops/trims to the narration length."))
        self.mvol = QSlider(Qt.Orientation.Horizontal)
        self.mvol.setRange(0, 100)
        self.mvol.valueChanged.connect(lambda v: self._r("music_volume", v / 100))
        self.mvol_l = label("", "Help")
        ac.add(labeled("Music volume", hbox(self.mvol, self.mvol_l)))
        self.duck = QCheckBox(t("Duck music under the narration"))
        self.duck.toggled.connect(lambda v: self._r("ducking", v))
        ac.add(self.duck)
        ac.add(button("Remove music", "trash", "ghost", on_click=lambda: self._music("")))
        row.addWidget(ac)
        body.addWidget(row)

        # render
        rc = Card("Render final video", "", "film", accent=True)
        self.render_badge = rc.add_action(Badge())
        rr = QHBoxLayout()
        rr.setSpacing(10)
        self.out_name = QLineEdit()
        self.out_name.setObjectName("outputName")
        self.out_name.editingFinished.connect(self._out_name)
        rr.addWidget(labeled("File name (saved in renders/)", self.out_name), 1)
        self.render_btn = button("Render final video", "film", "primary", on_click=self._render)
        self.render_btn.setObjectName("btnRender")
        rr.addWidget(self.render_btn, 0, Qt.AlignmentFlag.AlignBottom)
        self.cancel_btn = button("Cancel", "stop", "danger", on_click=lambda: ctrl.jobs.cancel("render"))
        rr.addWidget(self.cancel_btn, 0, Qt.AlignmentFlag.AlignBottom)
        rc.add(rr)
        self.readiness = Banner("info", "")
        rc.add(self.readiness)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        rc.add(self.progress)
        self.status = StatusLine()
        rc.add(self.status)
        self.report = label("", "Mono", wrap=True, selectable=True)
        rc.add(self.report)
        rc.add(hbox(button("Open video", "play", "soft", on_click=self._open_video),
                    button("Open folder", "folder-open", "ghost", on_click=self._open_folder), None))
        body.addWidget(rc)

        ctrl.project_loaded.connect(self._reset)
        ctrl.project_closed.connect(self._reset)
        ctrl.changed.connect(lambda a: self.mark_stale())
        ctrl.scene_changed.connect(lambda _s: self.mark_stale())
        ctrl.peaks_changed.connect(self.mark_stale)
        ctrl.task_changed.connect(lambda k: k == "render" and self.mark_stale())
        ctrl.jobs.progress.connect(self._progress)
        ctrl.about_to_render.connect(self.player.release)

    def _reset(self) -> None:
        self._sid = ""
        self.player.release()
        self.mark_stale()

    # ------------------------------------------------------------- helpers
    def _scene(self):
        p = self.project
        return p.scene(self._sid) if p and self._sid else None

    def _r(self, attr: str, v) -> None:
        p = self.project
        if p and v is not None and getattr(p.render, attr) != v:
            setattr(p.render, attr, v)
            self.edit("render")
            self._update_notes()
            self._load_inspector()

    def _st(self, attr: str, v) -> None:
        p = self.project
        if p and getattr(p.render.subtitle_style, attr) != v:
            setattr(p.render.subtitle_style, attr, v)
            self.edit("render")
            self._load_inspector()

    def _burn(self, v: bool) -> None:
        p = self.project
        if p:
            p.settings.burn_subtitles = v
            self.edit("setup")
            self._load_inspector()
            self._update_notes()

    def _aspect(self, v: str) -> None:
        p = self.project
        if not p or p.settings.aspect_ratio == v:
            return
        if any(s.images or s.videos for s in p.scenes):
            if not confirm(self, "Change aspect ratio?", "Existing images and clips were generated for "
                           f"{p.settings.aspect_ratio}. They will be cropped/letterboxed to {v}; regenerate them for best "
                           "results.", "Change"):
                self.aspect.set_value(p.settings.aspect_ratio)
                return
        p.settings.aspect_ratio = v
        self.edit("setup")
        self._update_notes()
        self._load_inspector()

    def _music(self, path: str) -> None:
        p = self.project
        if not p:
            return
        if not path:
            p.render.music_path = ""
            self.music.set_text("")
        else:
            import shutil
            src = Path(path)
            if not src.exists():
                self.ctrl.notify.emit("error", "Music file not found.")
                return
            try:
                rel = self.ctrl.rel_path(src)
                inside = not rel.startswith("..") and not Path(rel).is_absolute()
            except Exception:
                inside = False
            if not inside:
                dst = self.ctrl.folder / "assets" / "music" / src.name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
                rel = self.ctrl.rel_path(dst)
            p.render.music_path = rel
            self.music.set_text(rel)
        self.edit("render")

    def _out_name(self) -> None:
        p = self.project
        if p:
            p.render.output_name = self.out_name.text().strip() or "final_animated_explainer.mp4"
            self.edit("render")
            self._update_notes()

    # ------------------------------------------------------------- inspector
    def _select(self, sid: str) -> None:
        self._sid = sid
        self.timeline.set_selected(sid)
        self._load_inspector()
        if self.src.value() == "clip":
            self._load_preview()

    def _boundary(self, idx: int, tsec: float) -> None:
        if not self.ctrl.set_boundary(idx, tsec):
            self.ctrl.notify.emit("warning", "Scenes must stay at least 0.5 s long.")
        self.mark_stale()

    def _seek(self, sec: float) -> None:
        if self.src.value() == "final":
            self.player.seek_to(sec)
        self.timeline.set_playhead(sec)

    def _player_pos(self, sec: float) -> None:
        if self.src.value() == "final":
            self.timeline.set_playhead(sec)

    def _move(self, d: int) -> None:
        s = self._scene()
        if s:
            self.ctrl.move_visual(s.id, d)
            p = self.project
            j = p.scene_index(s.id) + d
            if 0 <= j < len(p.scenes):
                self._sid = p.scenes[j].id
            self.mark_stale()

    def _crop_mode(self) -> None:
        s = self._scene()
        if s:
            s.crop_mode = self.crop_mode.currentData() or ""
            self.edit("render")
            self._load_inspector()

    def _trim(self, v: float) -> None:
        s = self._scene()
        if s and abs(s.trim_in - v) > 1e-6:
            s.trim_in = round(v, 2)
            self.ctrl.update_gen_lengths()
            self.edit("render")
            self._load_inspector()

    def _focal(self, x: float, y: float) -> None:
        s = self._scene()
        if s:
            s.focal_x, s.focal_y = x, y
            with QSignalBlocker(self.fx), QSignalBlocker(self.fy):
                self.fx.setValue(x)
                self.fy.setValue(y)
            self.edit("render")

    def _focal_spin(self, attr: str, v: float) -> None:
        s = self._scene()
        if s:
            setattr(s, attr, round(v, 3))
            self.edit("render")
            self._load_inspector()

    def _visual_path(self, s) -> Path | None:
        ctrl = self.ctrl
        va = s.video_asset()
        if va:
            vp = ctrl.abs_path(va.path)
            if vp.exists():
                poster = self.posters.poster(ctrl.tools().ffmpeg, vp, ctrl.folder / "cache")
                if poster:
                    return poster
        ia = s.image_asset()
        if ia and ctrl.abs_path(ia.path).exists():
            return ctrl.abs_path(ia.path)
        return None

    def _load_inspector(self) -> None:
        p, s = self.project, self._scene()
        if not p or not s:
            self.ins_title.setText(t("Scene inspector"))
            self.crop.set_image(None)
            return
        i = p.scene_index(s.id)
        self.ins_title.setText(f"{t('Scene')} {i + 1} · {fmt_short(s.start)}–{fmt_short(s.end)}")
        st = p.render.subtitle_style
        cue = next((c.text for c in p.cues if c.start <= (s.start + s.end) / 2 < c.end), "")
        self.crop.set_image(self._visual_path(s))
        self.crop.configure(p.settings.aspect_ratio, s.crop_mode or p.render.crop_mode, p.render.fit_background,
                            s.focal_x, s.focal_y, cue, st.size, st.margin_v, p.settings.burn_subtitles)
        with QSignalBlocker(self.crop_mode):
            self.crop_mode.setCurrentIndex(max(0, self.crop_mode.findData(s.crop_mode)))
        with QSignalBlocker(self.trim), QSignalBlocker(self.fx), QSignalBlocker(self.fy):
            self.trim.setValue(s.trim_in)
            self.fx.setValue(s.focal_x)
            self.fy.setValue(s.focal_y)
        va = s.video_asset()
        info = self.ctrl.video_plan(i)
        if va:
            txt = f"{t('Clip')} v{s.selected_video + 1}" + (f" · {va.duration:.2f}s" if va.duration else "")
            if va.duration and va.duration - s.trim_in - (1 / max(1, p.render.fps) if va.chained else 0) > s.duration + 0.04:
                txt += f" · ✂ {t('trimmed to')} {s.duration:.2f}s"
            elif va.duration and va.duration - s.trim_in < s.duration - 0.04:
                txt += f" · ⏸ {t('last frame held')} {s.duration - (va.duration - s.trim_in):.2f}s"
            if va.chained:
                txt += " · " + t("first frame dropped (chain)")
        elif s.image_asset():
            txt = t("No clip — renders as a slow pan over the scene image.")
        else:
            txt = t("No clip or image — renders as a plain title card.")
        if info["problems"] and not va:
            txt += "\n" + "; ".join(info["problems"])
        self.ins_info.setText(txt)

    def _play_clip(self) -> None:
        self.src.set_value("clip")
        self._load_preview()

    # ------------------------------------------------------------- preview / render
    def _load_preview(self) -> None:
        p = self.project
        if not p:
            return
        if self.src.value() == "final":
            out = self.ctrl.abs_path(p.render.last_output) if p.render.last_output else None
            if out and out.exists() and not self.ctrl.jobs.is_running("render"):
                self.player.load(out)
                stamp = time.strftime('%Y-%m-%d %H:%M', time.localtime(p.render.last_render_at or 0))
                self.preview_note.setText(f"{out.name} · {t('rendered')} {stamp}")
            else:
                self.player.release()
                self.player.set_placeholder(t("Rendering…") if self.ctrl.jobs.is_running("render") else
                                            t("Render the final video to preview it here"))
                self.preview_note.setText("")
        else:
            s = self._scene()
            va = s.video_asset() if s else None
            if va and self.ctrl.abs_path(va.path).exists():
                self.player.load(self.ctrl.abs_path(va.path), autoplay=True)
                self.preview_note.setText(f"{t('Scene')} {p.scene_index(s.id) + 1} · {t('raw clip, before framing/trim')}")
            else:
                self.player.release()
                self.player.set_placeholder(t("This scene has no clip yet"))
                self.preview_note.setText("")

    def _progress(self, key: str, frac: float, msg: str) -> None:
        if key == "render" and self.project:
            self.progress.setValue(int(frac * 1000))
            self.status.set_task(self.project.render.task, msg)

    def _render(self) -> None:
        p = self.project
        if not p:
            return
        self._out_name()
        out = self.ctrl.output_path()
        if out.exists():
            if not confirm(self, "Replace video?", f"{out.name} already exists in renders/. Replace it? (Choose a new file "
                                                   "name above to keep both.)", "Replace"):
                return
        missing = [i + 1 for i, s in enumerate(p.scenes) if not s.video_asset()]
        if missing and not confirm(self, "Some scenes have no clip", f"Scene(s) {', '.join(map(str, missing[:15]))} have no "
                                   "clip and will render as an image pan or title card. Render anyway?", "Render"):
            return
        self.src.set_value("final")
        self.player.release()
        self.ctrl.render()
        self.mark_stale()

    def _open_folder(self) -> None:
        if self.ctrl.folder:
            d = self.ctrl.folder / "renders"
            d.mkdir(exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def _open_video(self) -> None:
        p = self.project
        if p and p.render.last_output:
            out = self.ctrl.abs_path(p.render.last_output)
            if out.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))

    def _update_notes(self) -> None:
        p = self.project
        if not p:
            return
        dur = p.voice.duration or 0.0
        fps = int(p.render.fps or 30)
        w, h = render_dims(p.settings.aspect_ratio, p.render.resolution)
        if dur:
            frames = max(1, round(dur * fps))
            out = frames / fps
            diff_ms = (out - dur) * 1000
            self.frame_note.setText(f"{w}×{h} · {t('Narration')} {dur:.3f}s → {frames} {t('frames')} @ {fps} fps = {out:.3f}s "
                                    f"({diff_ms:+.0f} ms {t('frame rounding')}).")
        else:
            self.frame_note.setText(f"{w}×{h}")
        info = self.ctrl.ffmpeg_info
        if p.settings.burn_subtitles and info and info.ok and not info.has_subtitles_filter:
            self.sub_note.setText(t("Your FFmpeg has no libass 'subtitles' filter, so subtitles will be added as a soft "
                                    "track instead of burned in."))
        else:
            self.sub_note.setText(t("subtitles.srt is always saved in the project folder.") if p.cues else
                                  t("No subtitles yet — align them on the Subtitles page."))

    def refresh(self) -> None:
        p = self.project
        has = bool(p and p.scenes and p.narration_take())
        self.empty.setVisible(not has)
        self.body_w.setVisible(has)
        self.open_btn.setVisible(has)
        if not has:
            self.player.release()
            return
        r = p.render
        st = r.subtitle_style
        if not p.scene(self._sid):
            self._sid = p.scenes[0].id
        # timeline
        tls = []
        for i, s in enumerate(p.scenes):
            va = s.video_asset()
            status = ("busy" if s.video_task.busy else "clip" if va else "error" if s.video_task.state == "failed"
                      else "image" if s.image_asset() else "empty")
            info = self.ctrl.video_plan(i) if va is None else None
            trimmed = bool(va and va.duration and va.duration - s.trim_in > s.duration + 0.05) or bool(info and info["trim"] > 0.05)
            tls.append(TLScene(s.id, s.start, s.end, (s.text[:60] or "—"), status, trimmed))
        self.timeline.set_data(tls, [(c.start, c.end, c.text) for c in p.cues], self.ctrl.peaks, p.voice.duration)
        self.timeline.set_selected(self._sid)
        # settings widgets
        self.aspect.set_value(p.settings.aspect_ratio)
        for w, v in ((self.res, r.resolution), (self.fps, r.fps), (self.fit_bg, r.fit_background)):
            with QSignalBlocker(w):
                w.setCurrentIndex(max(0, w.findData(v)))
        self.def_crop.set_value(r.crop_mode)
        with QSignalBlocker(self.crf):
            self.crf.setValue(r.crf)
        with QSignalBlocker(self.preset):
            self.preset.setCurrentText(r.preset)
        for w, v in ((self.burn, p.settings.burn_subtitles), (self.soft, r.soft_subtitles), (self.bold, st.bold),
                     (self.box, st.box), (self.duck, r.ducking)):
            with QSignalBlocker(w):
                w.setChecked(v)
        with QSignalBlocker(self.font_ed):
            self.font_ed.setText(st.font)
        for w, v in ((self.size, st.size), (self.margin, st.margin_v)):
            with QSignalBlocker(w):
                w.setValue(v)
        with QSignalBlocker(self.outline):
            self.outline.setValue(st.outline)
        self.color.set_color(st.color)
        self.ocolor.set_color(st.outline_color)
        with QSignalBlocker(self.nvol), QSignalBlocker(self.mvol):
            self.nvol.setValue(int(r.narration_volume * 100))
            self.mvol.setValue(int(r.music_volume * 100))
        self.nvol_l.setText(f"{int(r.narration_volume * 100)}%")
        self.mvol_l.setText(f"{int(r.music_volume * 100)}%")
        self.music.set_text(r.music_path)
        with QSignalBlocker(self.out_name):
            self.out_name.setText(r.output_name)
        # render state
        running = self.ctrl.jobs.is_running("render")
        self.render_btn.setEnabled(not running)
        self.cancel_btn.setVisible(running)
        self.progress.setVisible(running)
        self.status.set_task(r.task, self.ctrl.jobs.last_progress.get("render", (0, ""))[1])
        self.status.setVisible(r.task.state != "idle")
        done = bool(r.last_output and self.ctrl.abs_path(r.last_output).exists())
        self.render_badge.set("Rendering…" if running else "Rendered" if done else "Not rendered",
                              "primary" if running else "ok" if done else "neutral")
        self.report.setText(r.last_report or "")
        clips = sum(1 for s in p.scenes if s.video_asset())
        info = self.ctrl.ffmpeg_info
        msgs = []
        if info is not None and not info.ok:
            msgs.append("FFmpeg: " + " ".join(info.problems))
        msgs.append(f"{clips}/{len(p.scenes)} {t('scenes have clips')}.")
        if not p.alignment.reviewed and p.settings.burn_subtitles:
            msgs.append(t("Subtitles are not marked reviewed."))
        self.readiness.set("error" if info is not None and not info.ok else "info" if clips == len(p.scenes) else "warn",
                           " ".join(msgs))
        self._update_notes()
        self._load_inspector()
        if not self.player._path:
            self._load_preview()
        elif self.src.value() == "final" and done and self.player._path != self.ctrl.abs_path(r.last_output):
            self._load_preview()
