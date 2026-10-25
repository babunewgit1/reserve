"""HTTP client tests: documented request bodies, error mapping and task polling, using the local mock servers.

Only fake in-memory keys are used. No real Voice Studio / G-Labs Studio instance is contacted.
"""
from __future__ import annotations

import shutil
import struct
import zlib
from pathlib import Path

import pytest

import mock_glabs_servers as mock
from scriptreel.core.catalog import load_catalog
from scriptreel.services.glabs_client import GLabsClient, RefImage
from scriptreel.services.http_base import CancelToken, ServiceError
from scriptreel.services.voice_studio_client import VoiceStudioClient

BUNDLED = Path(__file__).resolve().parents[1] / "scriptreel" / "config" / "model_catalog.json"
CAT, _P, _W = load_catalog(BUNDLED)
FAKE_G = "test-glabs-key-not-real"
FAKE_V = "test-voice-key-not-real"
HAS_FF = shutil.which("ffmpeg") is not None


def _png(path: Path) -> Path:
    raw = b"\x00\xff\x00\x00"
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


# ----------------------------------------------------------------------------- request builders (no network)
def test_image_request_flow_model(tmp_path):
    c = GLabsClient("http://127.0.0.1:1", FAKE_G, reference_transfer="base64")
    route, body = c.build_image_request(CAT.image("nano_banana_pro"), prompt="a cat", aspect_ratio="16:9",
                                        refs=[RefImage(_png(tmp_path / "hero.png"), "hero")])
    assert route == "/api/image/generate"
    assert body["model"] == "nano_banana_pro" and body["aspect_ratio"] == "16:9"
    assert len(body["reference_images"]) == 1
    with pytest.raises(ServiceError):
        c.build_image_request(CAT.image("nano_banana_pro"), prompt="  ", aspect_ratio="16:9")


def test_video_request_veo_uses_model_and_mode(tmp_path):
    c = GLabsClient("http://127.0.0.1:1", FAKE_G, reference_transfer="path")
    img = _png(tmp_path / "s1.png")
    route, body = c.build_video_request(CAT.video("veo_31_fast"), prompt="slow pan", aspect_ratio="9:16",
                                        mode_key="start", start_ref=RefImage(img), duration=8)
    assert route == "/api/video/generate"
    assert body["model"] == "veo_31_fast" and body["mode"] == "start_image"
    assert body["reference_images"] == [{"path": str(img.resolve())}]
    assert body["video_length"] == 8


def test_video_request_grok_is_mode_not_model(tmp_path):
    c = GLabsClient("http://127.0.0.1:1", FAKE_G, reference_transfer="base64")
    route, body = c.build_video_request(CAT.video("grok_video"), prompt="zoom", aspect_ratio="16:9",
                                        mode_key="text", duration=6)
    assert route == "/api/grok/generate" and body["mode"] == "t2v" and "model" not in body
    route, body = c.build_video_request(CAT.video("grok_video"), prompt="zoom", aspect_ratio="16:9",
                                        mode_key="start", start_ref=RefImage(_png(tmp_path / "a.png")))
    assert body["mode"] == "i2v" and body["reference_images"][0].startswith("data:image/png;base64,")


def test_video_request_meta_start_image(tmp_path):
    c = GLabsClient("http://127.0.0.1:1", FAKE_G, reference_transfer="base64")
    route, body = c.build_video_request(CAT.video("meta_video"), prompt="drift", aspect_ratio="9:16",
                                        mode_key="start", start_ref=RefImage(_png(tmp_path / "a.png")))
    assert route == "/api/meta/generate" and body["mode"] == "i2v" and "start_image" in body and "model" not in body


def test_unsupported_mode_offers_fallback_but_never_switches():
    c = GLabsClient("http://127.0.0.1:1", FAKE_G)
    with pytest.raises(ServiceError) as ei:
        c.build_video_request(CAT.video("grok_video"), prompt="x", aspect_ratio="16:9", mode_key="start_end")
    assert ei.value.kind == "unsupported_mode" and ei.value.fallback == "start"


def test_unsupported_duration_and_ratio_rejected():
    c = GLabsClient("http://127.0.0.1:1", FAKE_G)
    with pytest.raises(ServiceError):
        c.build_video_request(CAT.video("veo_31_quality"), prompt="x", aspect_ratio="16:9", mode_key="text", duration=10)
    with pytest.raises(ServiceError):
        c.build_video_request(CAT.video("veo_31_quality"), prompt="x", aspect_ratio="1:1", mode_key="text")


def test_submit_refuses_undocumented_route():
    c = GLabsClient("http://127.0.0.1:1", FAKE_G)
    with pytest.raises(ServiceError) as ei:
        c.submit("/api/models", {"prompt": "x"})
    assert ei.value.kind == "config"


# ----------------------------------------------------------------------------- against mock servers
@pytest.fixture(scope="module")
def servers():
    g = mock.serve("glabs", 18775, FAKE_G, 0.2)
    v = mock.serve("voice", 18776, FAKE_V, 0.2)
    yield "http://127.0.0.1:18775", "http://127.0.0.1:18776"
    for s in (g, v):
        s.shutdown()
        s.server_close()


def test_connection_refused_is_reported():
    c = GLabsClient("http://127.0.0.1:9", FAKE_G)
    with pytest.raises(ServiceError) as ei:
        c.health()
    assert ei.value.kind == "connection" and "Start G-Labs Studio" in ei.value.hint


def test_health_and_bad_key(servers):
    gurl, vurl = servers
    assert GLabsClient(gurl, FAKE_G).health()
    with pytest.raises(ServiceError) as ei:
        GLabsClient(gurl, "wrong-key-123").verify_key()
    assert ei.value.kind == "auth" and ei.value.status == 401
    assert "wrong-key-123" not in ei.value.user_text()
    with pytest.raises(ServiceError):
        VoiceStudioClient(vurl, "nope-nope-nope").list_voices()


def test_voice_list_submit_poll_download(servers, tmp_path):
    _g, vurl = servers
    c = VoiceStudioClient(vurl, FAKE_V)
    voices = c.list_voices()
    assert voices and voices[0].id.startswith("spk_")
    if not HAS_FF:
        pytest.skip("mock voice synthesis needs ffmpeg")
    tid = c.submit(preset_id=voices[0].id, script="Hello there. This is a test.", language="English")
    st = c.wait_for_task(tid, timeout_s=30, interval_s=0.2, cancel=CancelToken())
    out = c.download(st["results"][0], tmp_path / "n.wav", cancel=CancelToken())
    assert out.exists() and out.stat().st_size > 1000


@pytest.mark.skipif(not HAS_FF, reason="mock media needs ffmpeg")
def test_image_task_and_provider_failure(servers, tmp_path):
    gurl, _v = servers
    c = GLabsClient(gurl, FAKE_G)
    route, body = c.build_image_request(CAT.image("nano_banana_2"), prompt="a tree", aspect_ratio="16:9")
    st = c.wait_for_task(c.submit(route, body), timeout_s=30, interval_s=0.2, cancel=CancelToken())
    assert c.download(st["results"][0], tmp_path / "i.png", cancel=CancelToken()).exists()

    route, body = c.build_image_request(CAT.image("nano_banana_2"), prompt="FAILTASK tree", aspect_ratio="16:9")
    with pytest.raises(ServiceError) as ei:
        c.wait_for_task(c.submit(route, body), timeout_s=30, interval_s=0.2, cancel=CancelToken())
    assert ei.value.kind == "task_failed"


@pytest.mark.parametrize("code,kind", [(403, "forbidden"), (429, "rate_limited")])
def test_http_error_kinds(servers, code, kind):
    gurl, _v = servers
    c = GLabsClient(gurl, FAKE_G)
    route, body = c.build_image_request(CAT.image("nano_banana_2"), prompt=f"FAIL{code} x", aspect_ratio="16:9")
    with pytest.raises(ServiceError) as ei:
        c.submit(route, body)
    assert ei.value.kind == kind and ei.value.status == code and ei.value.hint


def test_unknown_task_is_lost(servers):
    gurl, _v = servers
    with pytest.raises(ServiceError) as ei:
        GLabsClient(gurl, FAKE_G).get_status("does-not-exist")
    assert ei.value.kind == "task_lost"


def test_cancel_stops_polling(servers):
    gurl, _v = servers
    c = GLabsClient(gurl, FAKE_G)
    tok = CancelToken()
    tok.cancel()
    with pytest.raises(Exception):
        c.wait_for_task("anything", timeout_s=5, interval_s=0.1, cancel=tok)


def test_download_refuses_non_files_url(tmp_path):
    c = GLabsClient("http://127.0.0.1:1", FAKE_G)
    with pytest.raises(ServiceError):
        c.download("http://evil.example/steal", tmp_path / "x", cancel=CancelToken())


def test_path_upload_denied_falls_back_to_base64(tmp_path, monkeypatch):
    """macOS privacy protection: G-Labs cannot read the reference path -> resubmit once with base64."""
    from scriptreel.services import tasks as T

    c = GLabsClient("http://127.0.0.1:1", FAKE_G, reference_transfer="path")
    img = _png(tmp_path / "scene_001_v1.png")
    sent: list[object] = []

    def fake_submit(route, body):
        sent.append(body)
        return f"task{len(sent)}"

    def fake_poll(ctx, client, conn, task_id, timeout_s, dest_stem, ext, label):
        if task_id == "task1":
            raise ServiceError("G-Labs Studio task task1 failed: Upload failed for image 1: UPLOAD_ERROR|0: "
                               "[Errno 1] Operation not permitted: '/Users/x/Documents/a.png'", kind="task_failed")
        return dest_stem.with_suffix(ext)

    monkeypatch.setattr(c, "submit", fake_submit)
    monkeypatch.setattr(T, "_poll_and_download", fake_poll)

    class Ctx:
        cancel = CancelToken()
        def emit(self, p): pass
        def progress(self, f, m=""): pass

    build = lambda: c.build_image_request(CAT.image("nano_banana_pro"), prompt="p", aspect_ratio="16:9",
                                          refs=[RefImage(img, "hero")])
    path, tid = T._submit_with_fallback(Ctx(), c, None, build, "", 10, tmp_path / "out", ".png", "Scene 1 image", {})
    assert tid == "task2" and len(sent) == 2
    assert '"path"' in __import__("json").dumps(sent[0]) and "base64," in __import__("json").dumps(sent[1])
