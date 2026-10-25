"""Unit tests for pure logic: SRT, scene planning, catalog rules, schema, redaction, frame plan."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scriptreel.core import catalog as catmod
from scriptreel.core.catalog import ModelCatalog, load_catalog, validate_catalog
from scriptreel.core.logging_setup import Redactor, redact
from scriptreel.core.project import SCHEMA_VERSION, Project, migrate, render_dims
from scriptreel.services import project_store, scene_planner, srt
from scriptreel.services.video_renderer import RenderScene, frame_plan

BUNDLED = Path(__file__).resolve().parents[1] / "scriptreel" / "config" / "model_catalog.json"


# ----------------------------------------------------------------------------- SRT
def test_timestamp_roundtrip():
    assert srt.fmt_ts(3723.456) == "01:02:03,456"
    assert srt.parse_ts("01:02:03,456") == pytest.approx(3723.456)
    assert srt.parse_ts("00:00:01.5") == pytest.approx(1.5)
    assert srt.parse_ts("2.25") == pytest.approx(2.25)
    with pytest.raises(ValueError):
        srt.parse_ts("abc")


def test_srt_write_parse_roundtrip(tmp_path):
    cues = [srt.SrtCue(0.0, 1.2, "Hello world."), srt.SrtCue(1.3, 3.0, "Second line of text here.")]
    p = srt.write_srt(tmp_path / "a.srt", cues)
    back = srt.parse_srt(p.read_text(encoding="utf-8"))
    assert [(c.start, c.end, c.text) for c in back] == [(c.start, c.end, c.text) for c in cues]


def test_parse_srt_tolerates_bom_crlf_and_garbage():
    text = "\ufeff1\r\n00:00:00,000 --> 00:00:01,000\r\nA\r\n\r\nnot a cue\r\n\r\n2\r\n00:00:01,000 --> 00:00:02,000 X1:0\r\nB\r\nC\r\n"
    cues = srt.parse_srt(text)
    assert len(cues) == 2
    assert cues[1].text == "B C"


def test_validate_flags_overlap_negative_and_order():
    cues = [srt.SrtCue(0, 2, "a"), srt.SrtCue(1.5, 3, "b"), srt.SrtCue(1.0, 0.5, "c")]
    issues = srt.validate(cues)
    msgs = " | ".join(i.message for i in issues if i.severity == "error")
    assert "Overlaps" in msgs and "not after start" in msgs and "out of order" in msgs


def test_auto_fix_produces_valid_cues():
    cues = [srt.SrtCue(2, 3, "b"), srt.SrtCue(-1, 2.5, "a"), srt.SrtCue(3, 12, "c")]
    fixed = srt.auto_fix(cues, duration=10)
    assert [c.text for c in fixed] == ["a", "b", "c"]
    assert not [i for i in srt.validate(fixed, 10) if i.severity == "error"]
    assert fixed[-1].end <= 10


# ----------------------------------------------------------------------------- scene planning
def _words(n_sent=8, words_per=6, wdur=0.35, gap=0.05, sent_gap=0.4):
    out, t = [], 0.0
    for s in range(n_sent):
        for w in range(words_per):
            txt = f"w{s}_{w}" + ("." if w == words_per - 1 else "")
            out.append((t, t + wdur, txt))
            t += wdur + (sent_gap if w == words_per - 1 else gap)
    return out, t


def test_flexible_plan_tiles_timeline_within_bounds():
    words, dur = _words()
    scenes = scene_planner.plan(words, dur, "flexible", min_s=3, target_s=6, max_s=10)
    assert scenes[0].start == 0 and scenes[-1].end == pytest.approx(dur, abs=1e-3)
    for a, b in zip(scenes, scenes[1:]):
        assert a.end == pytest.approx(b.start)
    for s in scenes[:-1]:
        assert 3 - 1e-6 <= s.duration <= 10.5
    # every word is assigned to exactly one scene
    joined = " ".join(s.text for s in scenes).split()
    assert len(joined) == len(words)


def test_flexible_cuts_prefer_sentence_ends():
    words, dur = _words()
    scenes = scene_planner.plan(words, dur, "flexible", min_s=3, target_s=5, max_s=10)
    for s in scenes[:-1]:
        assert s.text.endswith("."), s.text


def test_fixed_plan_uses_8s_blocks_without_sliver():
    words, dur = _words(n_sent=10)
    scenes = scene_planner.plan(words, dur, "fixed8", min_s=3, target_s=6, max_s=10)
    for s in scenes[:-1]:
        assert s.duration == pytest.approx(8.0)
    assert scenes[-1].duration >= 0.5


@pytest.mark.parametrize("dur,choices,expect", [
    (5.0, [4, 6, 8, 10], (6, 1.0, 0.0)),
    (8.0, [8], (8, 0.0, 0.0)),
    (9.5, [8], (8, 0.0, 1.5)),
    (3.0, [], (None, 0.0, 0.0)),
])
def test_choose_generation_length(dur, choices, expect):
    d, trim, hold = scene_planner.choose_generation_length(dur, choices, None)
    assert d == expect[0]
    assert trim == pytest.approx(expect[1]) and hold == pytest.approx(expect[2])


def test_best_split_prefers_pause_near_middle():
    words, dur = _words(n_sent=2)
    t = scene_planner.best_split_time(words, 0.0, dur)
    sent_end = words[5][1]
    assert abs(t - (sent_end + words[6][0]) / 2) < 0.01


# ----------------------------------------------------------------------------- catalog
def test_bundled_catalog_is_valid_and_documented():
    cat = ModelCatalog.model_validate(json.loads(BUNDLED.read_text(encoding="utf-8")))
    problems = validate_catalog(cat)
    assert problems == [], problems
    ids = {m.id for m in cat.image_models}
    assert {"nano_banana_pro", "nano_banana_2", "nano_banana_2_lite"} <= ids
    vids = {v.id: v for v in cat.video_options}
    for mid in ("veo_31_fast", "veo_31_lite", "veo_31_quality", "veo_31_lite_relaxed", "omni_flash", "omni_vids"):
        assert vids[mid].route == "/api/video/generate" and vids[mid].model == mid
    # Grok/Meta are modes on their own routes, never model ids
    assert vids["grok_video"].route == "/api/grok/generate" and vids["grok_video"].model is None
    assert set(vids["grok_video"].modes.values()) == {"t2v", "i2v"}
    assert vids["meta_video"].route == "/api/meta/generate" and vids["meta_video"].model is None
    assert cat.catalog_version and cat.sources


def test_catalog_rejects_invented_routes_and_model_on_mode_routes():
    data = json.loads(BUNDLED.read_text(encoding="utf-8"))
    data["video_options"][0]["route"] = "/api/models"
    grok = next(v for v in data["video_options"] if v["id"] == "grok_video")
    grok["model"] = "grok_t2v"
    cat = ModelCatalog.model_validate(data)
    problems = validate_catalog(cat)
    assert any("not a documented" in p for p in problems)
    assert cat.video_options[0].enabled is False
    assert cat.video("grok_video").model is None


def test_load_catalog_falls_back_on_broken_file(tmp_path):
    bad = tmp_path / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    cat, _p, warnings = load_catalog(bad)
    assert warnings and not cat.video_options


def test_ultra_durations_and_resolutions():
    cat, _p, _w = load_catalog(BUNDLED)
    veo = cat.video("veo_31_fast")
    assert ModelCatalog.durations(veo, False) == sorted(veo.durations)
    assert set(ModelCatalog.durations(veo, True)) >= set(veo.durations)
    for r in veo.ultra_resolutions:
        assert r not in ModelCatalog.resolutions(veo, False)


# ----------------------------------------------------------------------------- project schema / store
def test_project_roundtrip_has_no_secrets_and_relative_paths(tmp_path):
    project, folder = project_store.create_project(tmp_path, "My Test: Video?")
    assert folder.parent == tmp_path and (folder / "project.json").exists()
    for sub in ("assets/images", "assets/videos", "renders"):
        assert (folder / sub).is_dir()
    project.script = "Hello."
    project_store.save_project(project, folder)
    loaded, notes = project_store.load_project(folder)
    assert loaded.script == "Hello." and loaded.schema_version == SCHEMA_VERSION
    raw = (folder / "project.json").read_text(encoding="utf-8").lower()
    for word in ("api_key", "x-api-key", "password", "secret"):
        assert word not in raw
    assert project_store.rel_path(folder, folder / "assets" / "images" / "a.png") == "assets/images/a.png"


def test_versioned_paths_never_overwrite(tmp_path):
    p1 = project_store.next_version_path(tmp_path, "assets/images", "scene_01", ".png")
    p1.parent.mkdir(parents=True, exist_ok=True)
    p1.write_bytes(b"x")
    p2 = project_store.next_version_path(tmp_path, "assets/images", "scene_01", ".png")
    assert p1 != p2 and not p2.exists()


def test_migrate_v0_and_future():
    data, notes = migrate({"title": "Old", "schema_version": 0})
    assert data["settings"]["title"] == "Old" and data["schema_version"] == SCHEMA_VERSION and notes
    Project.model_validate(data)
    _d, notes = migrate({"schema_version": SCHEMA_VERSION + 5})
    assert "newer" in notes[0]


def test_load_corrupt_project_raises_clear_error(tmp_path):
    (tmp_path / "project.json").write_text("{oops", encoding="utf-8")
    with pytest.raises(project_store.ProjectLoadError):
        project_store.load_project(tmp_path)


def test_render_dims():
    assert render_dims("16:9", "1080p") == (1920, 1080)
    assert render_dims("9:16", "720p") == (720, 1280)


# ----------------------------------------------------------------------------- redaction
def test_redaction_masks_keys_headers_and_base64():
    Redactor.register("sk-THIS-IS-A-FAKE-TEST-KEY-123")
    try:
        text = ("calling with sk-THIS-IS-A-FAKE-TEST-KEY-123 and X-API-Key: abcdefgh12345678 "
                "img=data:image/png;base64," + "A" * 400)
        out = redact(text)
        assert "sk-THIS-IS-A-FAKE" not in out
        assert "abcdefgh12345678" not in out
        assert "AAAA" * 10 not in out and "<base64 omitted>" in out
    finally:
        Redactor.unregister("sk-THIS-IS-A-FAKE-TEST-KEY-123")


# ----------------------------------------------------------------------------- frame plan
def test_frame_plan_sums_to_narration_frames():
    scenes = [RenderScene(0, 0, 3.333), RenderScene(1, 3.333, 7.01), RenderScene(2, 7.01, 10.0417)]
    counts, total = frame_plan(scenes, 10.0417, 30)
    assert total == round(10.0417 * 30) == sum(counts)
    assert all(c > 0 for c in counts)
    counts24, total24 = frame_plan(scenes, 10.0417, 24)
    assert sum(counts24) == total24 == 241


def test_catalog_module_exposes_documented_routes_only():
    for r in catmod.ALLOWED_ROUTES:
        assert r.startswith("/api/") and "models" not in r
