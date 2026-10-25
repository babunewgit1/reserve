"""End-to-end pipeline test against the local mock servers (no real accounts, no real keys).

voice → alignment (estimate engine) → scene plan → drafted prompts → images → chained clips → render → YouTube.
Skipped automatically when FFmpeg is not installed.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                                reason="FFmpeg/ffprobe not installed")

SCRIPT = ("Plants make their own food. They use sunlight, water and air. This process is called photosynthesis. "
          "It happens inside tiny green parts called chloroplasts. The plant releases oxygen for us to breathe. "
          "That is why forests are so important for life on Earth.")


class MemorySecrets:
    """In-memory stand-in for the OS keyring so tests never touch real credentials."""
    persistent = False
    backend_name = "test memory"

    def __init__(self) -> None:
        self.d: dict[str, str] = {}

    def get(self, n: str) -> str:
        return self.d.get(n, "")

    def has(self, n: str) -> bool:
        return bool(self.d.get(n))

    def set(self, n: str, v: str) -> None:
        from scriptreel.core.logging_setup import Redactor
        Redactor.register(v)
        self.d[n] = v

    def delete(self, n: str) -> None:
        self.d.pop(n, None)

    def clear_all(self, extra=None) -> None:
        self.d.clear()


def wait_until(app, pred, timeout: float, what: str) -> None:
    t0 = time.time()
    while not pred():
        app.processEvents()
        time.sleep(0.02)
        if time.time() - t0 > timeout:
            raise AssertionError(f"Timed out waiting for {what}")


def test_full_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("SCRIPTREEL_CONFIG_DIR", str(tmp_path / "config"))
    import mock_glabs_servers as mock

    vport, gport = 18766, 18765
    v_srv = mock.serve("voice", vport, "test-voice", 0.4)
    g_srv = mock.serve("glabs", gport, "test-glabs", 0.4)
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])

        from scriptreel.app.controller import Controller
        from scriptreel.core import secrets as sec
        from scriptreel.core.settings import SettingsStore

        store = SettingsStore(tmp_path / "config" / "settings.json")
        s = store.settings
        s.voice_base_url = f"http://127.0.0.1:{vport}"
        s.glabs_base_url = f"http://127.0.0.1:{gport}"
        s.poll_interval_s = 0.3
        s.alignment_engine = "estimate"
        s.autosave = False
        secrets = MemorySecrets()
        secrets.set(sec.VOICE_KEY, "test-voice")
        secrets.set(sec.GLABS_KEY, "test-glabs")
        ctrl = Controller(store, secrets)  # type: ignore[arg-type]
        errors: list[str] = []
        ctrl.notify.connect(lambda lvl, msg: errors.append(msg) if lvl == "error" else None)

        # connections (health + key only)
        ctrl.refresh_connections()
        wait_until(app, lambda: not ctrl.jobs.is_running("conn") and ctrl.conn["voice"].state != "checking", 20, "connections")
        assert ctrl.conn["voice"].state == "ok", ctrl.conn["voice"].message
        assert ctrl.conn["glabs"].state == "ok", ctrl.conn["glabs"].message
        assert [v.id for v in ctrl.voices] == ["spk_demo01", "spk_demo02"]

        # project
        ctrl.new_project(tmp_path / "projects", "Photosynthesis demo")
        p = ctrl.project
        p.script = SCRIPT
        p.voice_settings.preset_id = "spk_demo01"
        p.settings.video_option = "omni_flash"
        p.settings.chain_frames = True
        p.settings.youtube_metadata = True
        p.render.resolution = "720p"
        p.render.preset = "ultrafast"

        # voice
        ctrl.generate_voice()
        wait_until(app, lambda: p.narration_take() is not None or p.voice.task.state == "failed", 60, "voice")
        assert p.narration_take() is not None, p.voice.task.error
        assert p.voice.duration > 5
        assert (ctrl.folder / p.voice.narration_file).exists()

        # alignment → cues → review
        ctrl.run_alignment("script", "estimate")
        wait_until(app, lambda: bool(p.cues) or p.alignment.task.state == "failed", 60, "alignment")
        assert p.cues, p.alignment.task.error
        assert p.alignment.precision_note
        assert ctrl.mark_subtitles_reviewed()
        assert (ctrl.folder / "subtitles.srt").read_text(encoding="utf-8").startswith("1\n")

        # scenes + prompts (offline draft, no LLM configured)
        assert ctrl.plan_scenes()
        assert len(p.scenes) >= 2
        assert all(sc.duration <= 10.0 + 1e-6 for sc in p.scenes)
        assert ctrl.draft_prompts() == len(p.scenes)

        # images
        n = ctrl.generate_images([sc.id for sc in p.scenes])
        assert n == len(p.scenes)
        wait_until(app, lambda: not ctrl.jobs.running_keys("img:"), 120, "images")
        assert all(sc.image_asset() for sc in p.scenes), [sc.image_task.error for sc in p.scenes]
        ctrl.set_image_approved([sc.id for sc in p.scenes], True)

        # chained clips
        assert ctrl.generate_videos([sc.id for sc in p.scenes]) == len(p.scenes)
        wait_until(app, lambda: not ctrl.jobs.running_keys("vid:"), 240, "videos")
        assert all(sc.video_asset() for sc in p.scenes), [sc.video_task.error for sc in p.scenes]
        assert all(sc.video_asset().chained for sc in p.scenes[1:])
        assert all(sc.chain_frame for sc in p.scenes[:-1]) or all(sc.chain_frame for sc in p.scenes[1:])

        # render
        assert ctrl.render()
        wait_until(app, lambda: not ctrl.jobs.is_running("render"), 300, "render")
        assert p.render.task.state == "completed", p.render.task.error
        out = ctrl.abs_path(p.render.last_output)
        assert out.name == "final_animated_explainer.mp4" and out.exists()
        from scriptreel.services.ffmpeg_tools import probe
        info = probe(shutil.which("ffprobe"), out)
        assert abs(info["duration"] - p.voice.duration) < 0.1, (info["duration"], p.voice.duration)

        # YouTube package without LLM → chapters only, never blocks
        ctrl.generate_youtube()
        wait_until(app, lambda: not ctrl.jobs.is_running("yt"), 30, "youtube")
        assert (ctrl.folder / "youtube_metadata.md").exists()

        # persistence: no secrets in project files, reload works
        assert ctrl.save()
        raw = (ctrl.folder / "project.json").read_text(encoding="utf-8")
        assert "test-voice" not in raw and "test-glabs" not in raw
        data = json.loads(raw)
        assert data["schema_version"] == 1
        folder = ctrl.folder
        ctrl.close_project()
        ctrl.open_project(folder)
        assert len(ctrl.project.scenes) == len(data["scenes"])
        assert not errors, errors
    finally:
        v_srv.shutdown()
        g_srv.shutdown()


if __name__ == "__main__":
    import tempfile

    class _MP:
        def setenv(self, k, v):
            os.environ[k] = v

    test_full_pipeline(Path(tempfile.mkdtemp()), _MP())
    print("E2E OK")
