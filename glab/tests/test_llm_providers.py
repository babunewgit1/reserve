"""Prompt-provider tests for the Antigravity CLI (fake `agy` script) and 9router (local fake OpenAI-compatible server).

No real CLI, account or gateway is contacted.
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from scriptreel.services.prompt_provider import (
    PROVIDERS, AntigravityCLIProvider, NineRouterProvider, PromptProviderError, create_provider, find_agy,
)

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="fake agy is a POSIX shebang script")

FAKE_AGY = r'''
import json, os, sys
args = sys.argv[1:]
mode = os.environ.get("FAKE_AGY_MODE", "ok")
if args[:1] == ["models"]:
    if mode == "nologin":
        sys.stderr.write("Error: not logged in. Please sign in.\n"); sys.exit(3)
    print("Fetching available models...")
    print("gemini-3.8-flash-high\tGemini 3.8 Flash (High)")
    print("claude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)")
    sys.exit(0)
prompt = sys.stdin.read()
assert "--output-format" in args and "json" in args and "--sandbox" in args, args
model = args[args.index("--model") + 1] if "--model" in args else "default"
if mode == "fail":
    print(json.dumps({{"status": "ERROR", "error": "quota exhausted"}})); sys.exit(1)
reply = json.dumps({{"scenes": [{{"index": 1, "image_prompt": "img " + model, "motion_prompt": "push-in"}}]}}) \
    if "SCENES TO WRITE" in prompt else json.dumps({{"ok": True, "model": model, "cwd_empty": not os.listdir(".")}})
sys.stderr.write("warning: something harmless\n")
print(json.dumps({{"conversation_id": "x", "status": "SUCCESS", "response": "```json\n" + reply + "\n```\n"}}))
'''


@pytest.fixture()
def fake_agy(tmp_path, monkeypatch):
    script = tmp_path / "fake_agy.py"
    script.write_text(FAKE_AGY.replace("{{", "{").replace("}}", "}"), encoding="utf-8")
    p = tmp_path / "agy"  # shebangs cannot contain spaces, so wrap the interpreter call in sh
    p.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
    p.chmod(0o755)
    monkeypatch.delenv("FAKE_AGY_MODE", raising=False)
    return str(p)


def test_registry_has_new_providers():
    assert "antigravity_cli" in PROVIDERS and "9router" in PROVIDERS
    assert not AntigravityCLIProvider.needs_key and NineRouterProvider.needs_key
    assert NineRouterProvider.default_base_url == "http://localhost:20128/v1"


def test_find_agy_explicit_missing(tmp_path):
    assert find_agy(str(tmp_path / "nope" / "agy")) is None


@posix_only
def test_agy_models_parsed(fake_agy):
    p = create_provider("antigravity_cli", api_key="", model="", base_url=fake_agy, temperature=0.7)
    assert p.list_models() == [("gemini-3.8-flash-high", "Gemini 3.8 Flash (High)"),
                               ("claude-sonnet-4-6", "Claude Sonnet 4.6 (Thinking)")]


@posix_only
def test_agy_complete_json(fake_agy):
    p = create_provider("antigravity_cli", api_key="", model="claude-sonnet-4-6", base_url=fake_agy, temperature=0.7)
    data = p.complete_json("Reply with JSON only.", "Return ok")
    assert data == {"ok": True, "model": "claude-sonnet-4-6", "cwd_empty": True}


@posix_only
def test_agy_not_logged_in(fake_agy, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_MODE", "nologin")
    p = create_provider("antigravity_cli", api_key="", model="", base_url=fake_agy, temperature=0.7)
    with pytest.raises(PromptProviderError, match="not signed in"):
        p.list_models()


@posix_only
def test_agy_error_status(fake_agy, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_MODE", "fail")
    p = create_provider("antigravity_cli", api_key="", model="", base_url=fake_agy, temperature=0.7)
    with pytest.raises(PromptProviderError, match="quota exhausted"):
        p.complete("s", "u")


def test_agy_missing_binary(tmp_path):
    p = create_provider("antigravity_cli", api_key="", model="", base_url=str(tmp_path / "missing-agy"), temperature=0.7)
    with pytest.raises(PromptProviderError, match="not found"):
        p.list_models()


# ----------------------------------------------------------------------------- 9router (fake gateway)
class _Router(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):  # noqa: N802
        if self.path == "/v1/models":
            self._json(200, {"object": "list", "data": [{"id": "ag/gemini-3.8-flash-high"}, {"id": "cx/gpt-5.5"}]})
        else:
            self._json(404, {"error": "nf"})

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.headers.get("Authorization") != "Bearer fake-9r-key":
            self._json(401, {"error": {"message": "Missing API key"}})
            return
        self._json(200, {"choices": [{"message": {"content": json.dumps({"ok": True, "model": body["model"]})}}]})


@pytest.fixture(scope="module")
def router():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Router)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    srv.shutdown()


def test_9router_models_and_chat(router):
    p = create_provider("9router", api_key="", model="ag/gemini-3.8-flash-high", base_url=router, temperature=0.5)
    assert [m for m, _ in p.list_models()] == ["ag/gemini-3.8-flash-high", "cx/gpt-5.5"]
    with pytest.raises(PromptProviderError, match="401"):
        p.complete("s", "u")
    p = create_provider("9router", api_key="fake-9r-key", model="cx/gpt-5.5", base_url=router, temperature=0.5)
    assert p.complete_json("s", "u") == {"ok": True, "model": "cx/gpt-5.5"}


def test_9router_unreachable():
    p = create_provider("9router", api_key="k", model="m", base_url="http://127.0.0.1:1/v1", temperature=0.5)
    with pytest.raises(PromptProviderError, match="cannot reach"):
        p.list_models()


def test_sse_stream_is_assembled():
    from scriptreel.services.prompt_provider import _assemble_sse
    sse = ('data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
           'data: {"choices":[{"delta":{"content":"{\\"ok\\": "}}]}\n\n'
           'data: {"choices":[{"delta":{"content":"true}"}}]}\n\ndata: [DONE]\n')
    assert _assemble_sse(sse)["choices"][0]["message"]["content"] == '{"ok": true}'
