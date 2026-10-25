"""Local mock of the documented G-Labs Voice Studio (:8766) and G-Labs Studio (:8765) webhook APIs.

FOR DEVELOPMENT AND TESTING ONLY. It implements just the documented endpoints the app uses, so the
full pipeline can be exercised without real accounts or quota:

  both:   GET /api/health · GET /api/status/{id} · GET /api/files/{name} · GET /api/tasks
  voice:  GET /api/voices · POST /api/voice/design
  glabs:  POST /api/image/generate · /api/openai/generate · /api/grok/generate · /api/meta/generate
          POST /api/video/generate

Generated media is synthetic: speech-like tone bursts (one per sentence, ~0.3 s gaps, like Voice Studio),
gradient images and slow-pan clips made with FFmpeg from the reference image when one is supplied.

Failure injection: put FAIL401/FAIL403/FAIL429/FAILTASK in a prompt or script.

Usage:
    python tools/mock_glabs_servers.py --voice-key test-voice --glabs-key test-glabs [--delay 3]
The keys are arbitrary test strings you choose — never real keys.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import random
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import uuid
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
OUT = Path(tempfile.gettempdir()) / "scriptreel_mock_files"
OUT.mkdir(parents=True, exist_ok=True)


class Store:
    def __init__(self) -> None:
        self.tasks: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.started = time.time()


def sentences(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"(?<=[.!?।])\s+", text.strip()) if p.strip()]
    return parts or [text.strip() or "silence"]


def synth_voice(script: str, speed: float, dest: Path) -> None:
    """Tone bursts with syllable-like modulation; 0.3 s pauses between sentences."""
    sr = 22050
    frames = bytearray()
    rnd = random.Random(len(script))
    for s in sentences(script):
        words = max(1, len(s.split()))
        dur = words * 0.36 / max(0.5, speed)
        n = int(dur * sr)
        f0 = 140 + rnd.random() * 60
        for i in range(n):
            tt = i / sr
            env = 0.55 + 0.45 * math.sin(2 * math.pi * 3.2 * tt) ** 2
            v = 0.32 * env * (math.sin(2 * math.pi * f0 * tt) + 0.4 * math.sin(2 * math.pi * 2 * f0 * tt))
            frames += struct.pack("<h", int(max(-1, min(1, v)) * 32767))
        frames += b"\x00\x00" * int(0.3 * sr)
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(bytes(frames))


def dims(aspect: str, base: int = 1280) -> tuple[int, int]:
    return (base, base * 9 // 16) if aspect != "9:16" else (base * 9 // 16, base)


def ff(args: list[str]) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], check=True, timeout=180)


def synth_image(aspect: str, seed: int, dest: Path) -> None:
    w, h = dims(aspect)
    rnd = random.Random(seed)
    c0 = "0x%06X" % rnd.randint(0x202060, 0x6060FF)
    c1 = "0x%06X" % rnd.randint(0xA04080, 0xFFD080)
    try:
        ff(["-f", "lavfi", "-i", f"gradients=s={w}x{h}:c0={c0}:c1={c1}:seed={seed}:speed=0", "-frames:v", "1", str(dest)])
    except Exception:
        ff(["-f", "lavfi", "-i", f"testsrc2=s={w}x{h}", "-frames:v", "1", str(dest)])


def synth_video(aspect: str, seconds: int, ref: Path | None, dest: Path) -> None:
    w, h = dims(aspect)
    fps = 24
    if ref and ref.exists():
        bw, bh = int(w * 1.15) // 2 * 2, int(h * 1.15) // 2 * 2
        vf = (f"scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
              f"crop={w}:{h}:x='(iw-ow)*t/{seconds}':y='(ih-oh)/2',fps={fps},format=yuv420p")
        ff(["-loop", "1", "-t", str(seconds), "-i", str(ref), "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast",
            "-an", str(dest)])
    else:
        ff(["-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:r={fps}:d={seconds}", "-vf", "format=yuv420p", "-c:v", "libx264",
            "-preset", "ultrafast", "-an", str(dest)])


def find_ref(body: dict) -> Path | None:
    """Accept {"path": ...}, data URIs, {"data": uri} in reference_images / start_image (documented forms)."""
    cands = []
    for k in ("reference_images",):
        v = body.get(k)
        if isinstance(v, list):
            cands += v
    for k in ("start_image", "character_image", "scene_image", "style_image"):
        if body.get(k):
            cands.append(body[k])
    for c in cands:
        if isinstance(c, dict) and c.get("path") and Path(c["path"]).exists():
            return Path(c["path"])
        uri = c.get("data") if isinstance(c, dict) else c
        if isinstance(uri, str) and uri.startswith("data:"):
            raw = base64.b64decode(uri.split(",", 1)[1])
            p = OUT / f"ref_{uuid.uuid4().hex[:8]}.png"
            p.write_bytes(raw)
            return p
    return None


def make_handler(kind: str, key: str, store: Store, delay: float, port: int):
    class H(BaseHTTPRequestHandler):
        server_version = "MockGLabs/1.0"

        def log_message(self, fmt, *args):  # quiet
            pass

        def _json(self, code: int, obj: dict) -> None:
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _auth(self) -> bool:
            got = self.headers.get("X-API-Key") or (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
            if got != key:
                self._json(401, {"error": "Invalid or missing API key"})
                return False
            return True

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?")[0].rstrip("/")
            if path == "/api/health":
                with store.lock:
                    pend = sum(1 for t in store.tasks.values() if t["status"] == "pending")
                    run = sum(1 for t in store.tasks.values() if t["status"] == "running")
                return self._json(200, {"status": "ok", "server": f"Mock {kind}", "uptime": int(time.time() - store.started),
                                        "tasks_pending": pend, "tasks_running": run})
            if path.startswith("/api/files/"):
                name = unquote(path[len("/api/files/"):])
                f = OUT / Path(name).name
                if not f.exists():
                    return self._json(404, {"error": "File not found"})
                data = f.read_bytes()
                ctype = {".png": "image/png", ".mp4": "video/mp4", ".wav": "audio/wav", ".mp3": "audio/mpeg"}.get(f.suffix,
                                                                                                                 "application/octet-stream")
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if not self._auth():
                return
            if path == "/api/voices" and kind == "voice":
                voices = [{"id": "spk_demo01", "name": "Calm Narrator", "tags": ["male", "warm"], "is_factory": False,
                           "is_favorite": True},
                          {"id": "spk_demo02", "name": "Bright Teacher", "tags": ["female", "clear"], "is_factory": True,
                           "is_favorite": False}]
                return self._json(200, {"voices": voices, "count": len(voices)})
            if path == "/api/tasks":
                with store.lock:
                    items = sorted(store.tasks.values(), key=lambda t: -t["created_at"])[:50]
                return self._json(200, {"tasks": [{k: t[k] for k in ("task_id", "type", "status", "created_at")} for t in items]})
            m = re.match(r"^/api/status/([\w-]+)$", path)
            if m:
                with store.lock:
                    t = store.tasks.get(m.group(1))
                    if not t:
                        return self._json(404, {"error": f"Task {m.group(1)} not found"})
                    out = {k: v for k, v in t.items() if not k.startswith("_")}
                return self._json(200, out)
            return self._json(404, {"error": "Not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?")[0].rstrip("/")
            n = int(self.headers.get("Content-Length") or 0)
            if n > 50 * 1024 * 1024:
                return self._json(413, {"error": "Request body too large"})
            if not self._auth():
                return
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return self._json(400, {"error": "Invalid JSON"})
            text = body.get("prompt") or body.get("script") or ""
            for code in (401, 403, 429):
                if f"FAIL{code}" in text:
                    msg = {401: "Invalid or missing API key", 403: "MAX license required",
                           429: "Too many requests"}[code]
                    return self._json(code, {"error": msg})
            routes_voice = {"/api/voice/design": "voice"}
            routes_glabs = {"/api/image/generate": "image", "/api/openai/generate": "image", "/api/grok/generate": None,
                            "/api/meta/generate": None, "/api/video/generate": "video"}
            routes = routes_voice if kind == "voice" else routes_glabs
            if path not in routes:
                return self._json(404, {"error": "Not found"})
            typ = routes[path] or ("video" if body.get("mode") in ("t2v", "i2v") else "image")
            if kind == "voice":
                if not body.get("preset_id") or not body.get("script"):
                    return self._json(400, {"error": "preset_id and script are required"})
            elif not text:
                return self._json(400, {"error": "prompt is required"})
            tid = uuid.uuid4().hex[:12]
            task = {"task_id": tid, "type": typ, "status": "pending", "prompt": text[:50], "created_at": time.time()}
            with store.lock:
                store.tasks[tid] = task
            threading.Thread(target=self._work, args=(tid, typ, body, text), daemon=True).start()
            return self._json(202 if kind == "voice" else 200, {"task_id": tid, "status": "pending",
                                                                "message": "Task queued", "poll_url": f"/api/status/{tid}"})

        def _work(self, tid: str, typ: str, body: dict, text: str) -> None:
            time.sleep(0.6)
            with store.lock:
                store.tasks[tid]["status"] = "running"
            time.sleep(delay * (1.6 if typ == "video" else 1.0))
            try:
                if "FAILTASK" in text:
                    raise RuntimeError("Simulated provider failure (FAILTASK)")
                aspect = body.get("aspect_ratio", "16:9")
                if typ == "voice":
                    dest = OUT / f"voice_{tid}.wav"
                    synth_voice(body["script"], float(body.get("speed") or 1.0), dest)
                    if body.get("output_format") == "mp3" and shutil.which(FFMPEG):
                        mp3 = dest.with_suffix(".mp3")
                        ff(["-i", str(dest), "-b:a", "128k", str(mp3)])
                        dest = mp3
                elif typ == "image":
                    dest = OUT / f"image_{tid}.png"
                    synth_image(aspect, int(tid[:6], 16), dest)
                else:
                    secs = int(body.get("video_length") or 8)
                    dest = OUT / f"video_{tid}.mp4"
                    synth_video(aspect, secs, find_ref(body), dest)
                url = f"http://127.0.0.1:{port}/api/files/{dest.name}"
                with store.lock:
                    store.tasks[tid].update(status="completed", results=[url], completed_at=time.time())
            except Exception as exc:
                with store.lock:
                    store.tasks[tid].update(status="failed", error=str(exc), error_code=500, error_detail=type(exc).__name__)

    return H


def serve(kind: str, port: int, key: str, delay: float) -> ThreadingHTTPServer:
    store = Store()
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(kind, key, store, delay, port))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--voice-port", type=int, default=8766)
    ap.add_argument("--glabs-port", type=int, default=8765)
    ap.add_argument("--voice-key", default=os.environ.get("MOCK_VOICE_KEY", "test-voice-key"))
    ap.add_argument("--glabs-key", default=os.environ.get("MOCK_GLABS_KEY", "test-glabs-key"))
    ap.add_argument("--delay", type=float, default=3.0, help="seconds a task stays 'running'")
    a = ap.parse_args()
    serve("voice", a.voice_port, a.voice_key, a.delay)
    serve("glabs", a.glabs_port, a.glabs_key, a.delay)
    print(f"Mock Voice Studio on http://127.0.0.1:{a.voice_port}  (key: {a.voice_key})")
    print(f"Mock G-Labs Studio on http://127.0.0.1:{a.glabs_port}  (key: {a.glabs_key})")
    print(f"Files in {OUT}. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
