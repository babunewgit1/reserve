"""Prompt-generation providers (vendor neutral).

`PromptProvider` is the interface. Adapters use each vendor's documented
public HTTP API:
* OpenAI-compatible Chat Completions (`POST {base}/chat/completions`) — covers
  OpenAI, OpenRouter, Groq, local Ollama (`http://localhost:11434/v1`) and
  LM Studio (`http://localhost:1234/v1`).
* Google Gemini (`POST {base}/models/{model}:generateContent`).
* Anthropic Messages (`POST {base}/messages`).
* 9router — local OpenAI-compatible gateway (`http://localhost:20128/v1`) that
  routes to the accounts connected in its dashboard (Antigravity, Codex…).
* Google Antigravity CLI — runs the logged-in `agy` binary in print mode
  (prompt on stdin, `--output-format json`); models come from `agy models`.
If no provider is configured, `NoProvider` raises and the UI falls back to
manual prompt writing (with optional offline draft templates).
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from ..core.logging_setup import Redactor, redact
from .http_base import CancelToken

log = logging.getLogger("scriptreel.llm")


class PromptProviderError(Exception):
    pass


class PromptProvider(ABC):
    id = "base"
    label = "Base"
    needs_key = True
    default_base_url = ""
    default_model = ""
    key_help = ""
    base_label = "Base URL"
    base_help = "Leave empty for the provider default."
    can_list_models = False
    uses_temperature = True

    def __init__(self, *, api_key: str = "", model: str = "", base_url: str = "", temperature: float = 0.7,
                 timeout: float = 120.0) -> None:
        self.api_key = api_key or ""
        Redactor.register(self.api_key)
        self.model = model or self.default_model
        self.base_url = (base_url or self.default_base_url).rstrip("/")
        self.temperature = temperature
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.model and self.base_url and (self.api_key or not self.needs_key))

    @abstractmethod
    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        ...

    def complete_json(self, system: str, user: str):
        return extract_json(self.complete(system, user, json_mode=True))

    def list_models(self) -> list[tuple[str, str]]:
        """Return [(model_id, label)] from the provider's documented model listing."""
        raise PromptProviderError(f"{self.label}: this provider has no model-list API. Type the model ID.")

    def _post(self, url: str, body: dict, headers: dict) -> dict:
        try:
            with httpx.Client(timeout=httpx.Timeout(self.timeout, connect=10.0)) as c:
                r = c.post(url, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise PromptProviderError(f"{self.label}: request failed ({type(exc).__name__}). Check the base URL / network.") from exc
        if r.status_code >= 400:
            try:
                msg = r.json()
                msg = msg.get("error", msg)
                if isinstance(msg, dict):
                    msg = msg.get("message") or json.dumps(msg)[:300]
            except ValueError:
                msg = r.text[:300]
            hint = {401: " (API key rejected)", 403: " (access denied)", 404: " (model or URL not found)",
                    429: " (rate limit / quota)"}.get(r.status_code, "")
            raise PromptProviderError(redact(f"{self.label}: HTTP {r.status_code}{hint}: {msg}"))
        if "text/event-stream" in r.headers.get("content-type", "") or r.text.lstrip().startswith("data:"):
            return _assemble_sse(r.text)
        try:
            return r.json()
        except ValueError as exc:
            raise PromptProviderError(f"{self.label}: non-JSON response") from exc


def _assemble_sse(text: str) -> dict:
    """Fold an OpenAI-style SSE stream (chat.completion.chunk events) into one chat.completion dict."""
    parts: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            ev = json.loads(payload)
        except ValueError:
            continue
        for ch in ev.get("choices") or []:
            piece = (ch.get("delta") or {}).get("content") or (ch.get("message") or {}).get("content")
            if piece:
                parts.append(piece)
    return {"choices": [{"message": {"role": "assistant", "content": "".join(parts)}}]}


class NoProvider(PromptProvider):
    id = "none"
    label = "None — write prompts manually"
    needs_key = False

    @property
    def configured(self) -> bool:
        return False

    def complete(self, system, user, *, json_mode=False):
        raise PromptProviderError("No prompt LLM is configured. Write prompts manually, use offline drafts, "
                                  "or configure a provider in Settings → Prompt generation.")


class OpenAICompatibleProvider(PromptProvider):
    id = "openai_compatible"
    label = "OpenAI-compatible (OpenAI, OpenRouter, Ollama, LM Studio…)"
    needs_key = False  # local servers often need none
    default_base_url = "https://api.openai.com/v1"
    default_model = "gpt-4o-mini"
    key_help = "Leave empty for local servers such as Ollama or LM Studio."
    base_help = ("Leave empty for the provider default. For Ollama use http://127.0.0.1:11434/v1, "
                 "LM Studio http://127.0.0.1:1234/v1.")
    can_list_models = True

    def list_models(self) -> list[tuple[str, str]]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            with httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0)) as c:
                r = c.get(f"{self.base_url}/models", headers=headers)
        except httpx.HTTPError as exc:
            raise PromptProviderError(f"{self.label}: cannot reach {self.base_url} ({type(exc).__name__}). "
                                      "Is the server running?") from exc
        if r.status_code >= 400:
            raise PromptProviderError(redact(f"{self.label}: HTTP {r.status_code} from /models"))
        try:
            items = r.json().get("data") or []
        except (ValueError, AttributeError) as exc:
            raise PromptProviderError(f"{self.label}: unexpected /models response") from exc
        out = []
        for m in items:
            mid = str(m.get("id", "")).strip() if isinstance(m, dict) else ""
            if mid:
                out.append((mid, str(m.get("name") or mid)))
        return out

    def complete(self, system, user, *, json_mode=False):
        body = {"model": self.model, "temperature": self.temperature, "stream": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = f"{self.base_url}/chat/completions"
        try:
            data = self._post(url, {**body, **({"response_format": {"type": "json_object"}} if json_mode else {})}, headers)
        except PromptProviderError as exc:
            if json_mode and "HTTP 400" in str(exc):  # some servers reject response_format
                data = self._post(url, body, headers)
            else:
                raise
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise PromptProviderError(f"{self.label}: unexpected response shape") from exc


class GeminiProvider(PromptProvider):
    id = "gemini"
    label = "Google Gemini API"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"
    default_model = "gemini-2.5-flash"

    def complete(self, system, user, *, json_mode=False):
        cfg: dict = {"temperature": self.temperature}
        if json_mode:
            cfg["responseMimeType"] = "application/json"
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": cfg}
        data = self._post(f"{self.base_url}/models/{self.model}:generateContent", body,
                          {"Content-Type": "application/json", "x-goog-api-key": self.api_key})
        try:
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError, TypeError) as exc:
            raise PromptProviderError(f"{self.label}: empty or blocked response") from exc


class AnthropicProvider(PromptProvider):
    id = "anthropic"
    label = "Anthropic Claude API"
    default_base_url = "https://api.anthropic.com/v1"
    default_model = "claude-sonnet-4-5"

    def complete(self, system, user, *, json_mode=False):
        sys_prompt = system + ("\nRespond with JSON only." if json_mode else "")
        body = {"model": self.model, "max_tokens": 4096, "temperature": self.temperature, "system": sys_prompt,
                "messages": [{"role": "user", "content": user}]}
        data = self._post(f"{self.base_url}/messages", body,
                          {"Content-Type": "application/json", "x-api-key": self.api_key, "anthropic-version": "2023-06-01"})
        try:
            return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        except (KeyError, TypeError) as exc:
            raise PromptProviderError(f"{self.label}: unexpected response shape") from exc


class NineRouterProvider(OpenAICompatibleProvider):
    """9router (https://9router.com) — local OpenAI-compatible gateway, `npm i -g 9router`."""
    id = "9router"
    label = "9router (local AI gateway)"
    needs_key = True
    default_base_url = "http://localhost:20128/v1"
    default_model = "ag/gemini-3.8-flash-high"
    key_help = "Copy an API key from the 9router dashboard (http://localhost:20128)."
    base_help = "Default http://localhost:20128/v1. Start the gateway with `9router` in a terminal first."


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def find_agy(configured: str = "") -> str | None:
    """Locate the Antigravity CLI. GUI apps often lack ~/.local/bin on PATH, so check common spots."""
    cand = (configured or "").strip().strip('"')
    if cand and cand != "agy":
        p = Path(cand).expanduser()
        if p.is_file():
            return str(p)
        return shutil.which(cand)
    found = shutil.which("agy")
    if found:
        return found
    home = Path.home()
    extra = [home / ".local" / "bin" / "agy", Path("/usr/local/bin/agy"), Path("/opt/homebrew/bin/agy")]
    if sys.platform == "win32":
        la = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        extra = [home / ".local" / "bin" / "agy.exe", la / "Programs" / "agy" / "agy.exe",
                 la / "agy" / "agy.exe"] + extra
    for p in extra:
        if p.is_file():
            return str(p)
    return None


class AntigravityCLIProvider(PromptProvider):
    """Google Antigravity CLI (`agy`). Uses the account you are signed into in the CLI — no API key.

    Documented CLI surface used: `agy models` (list), print mode with the prompt on stdin,
    `--output-format json` (returns {"status", "response", ...}), `--model`, `--sandbox`,
    `--disable-slash-commands` and `--print-timeout`.
    """
    id = "antigravity_cli"
    label = "Google Antigravity CLI (agy)"
    needs_key = False
    default_base_url = "agy"
    default_model = "gemini-3.8-flash-high"
    base_label = "agy executable"
    base_help = "Leave empty to auto-detect agy (PATH, ~/.local/bin). Sign in once by running `agy` in a terminal."
    can_list_models = True
    uses_temperature = False

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.timeout = max(self.timeout, 300.0)  # a CLI agent turn is slower than a raw HTTP call

    def _exe(self) -> str:
        exe = find_agy(self.base_url)
        if not exe:
            raise PromptProviderError("Antigravity CLI (agy) was not found. Install it, run `agy` once in a terminal to "
                                      "sign in, or set the agy executable path in Settings.")
        return exe

    def _run(self, args: list[str], stdin: str | None, timeout: float) -> subprocess.CompletedProcess:
        exe = self._exe()
        env = dict(os.environ)
        env.setdefault("NO_COLOR", "1")
        with tempfile.TemporaryDirectory(prefix="scriptreel-agy-") as work:  # empty, so the agent has nothing to edit
            try:
                return subprocess.run([exe, *args], input=stdin, capture_output=True, text=True, encoding="utf-8",
                                      errors="replace", timeout=timeout, cwd=work, env=env,
                                      creationflags=_no_window())
            except subprocess.TimeoutExpired as exc:
                raise PromptProviderError(f"Antigravity CLI did not answer within {int(timeout)} s.") from exc
            except OSError as exc:
                raise PromptProviderError(f"Could not start agy ({exc.strerror or type(exc).__name__}).") from exc

    @staticmethod
    def _fail_text(proc: subprocess.CompletedProcess) -> str:
        err = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        low = err.lower()
        if any(k in low for k in ("login", "log in", "sign in", "signin", "unauthenticated", "credentials")):
            return "Antigravity CLI is not signed in. Run `agy` in a terminal and sign in, then retry."
        tail = " ".join(err.splitlines()[-3:])[:300]
        return redact(f"agy exited with code {proc.returncode}: {tail or 'no output'}")

    def list_models(self) -> list[tuple[str, str]]:
        proc = self._run(["models"], None, 60.0)
        if proc.returncode != 0:
            raise PromptProviderError(self._fail_text(proc))
        out = []
        for line in (proc.stdout or "").splitlines():
            parts = [p.strip() for p in line.split("\t") if p.strip()]
            if len(parts) >= 2 and re.fullmatch(r"[A-Za-z0-9._:/-]+", parts[0]):
                out.append((parts[0], parts[1]))
        if not out:
            raise PromptProviderError("`agy models` returned no models. Is the CLI signed in?")
        return out

    def complete(self, system, user, *, json_mode=False):
        rules = ("Answer directly in this reply. Do not use tools, run commands, browse or create files.")
        if json_mode:
            rules += " Respond with JSON only — no markdown fences, no commentary."
        prompt = f"{system}\n\n{rules}\n\n---\n\n{user}"
        args = ["--output-format", "json", "--sandbox", "--disable-slash-commands",
                "--print-timeout", f"{int(self.timeout)}s"]
        if self.model:
            args += ["--model", self.model]
        proc = self._run(args, prompt, self.timeout + 30)
        data = None
        for line in reversed((proc.stdout or "").splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    break
                except ValueError:
                    continue
        if data is None:
            if proc.returncode != 0:
                raise PromptProviderError(self._fail_text(proc))
            raise PromptProviderError("Antigravity CLI returned no JSON result.")
        status = str(data.get("status", "")).upper()
        if status and status != "SUCCESS":
            msg = data.get("error") or data.get("message") or status
            raise PromptProviderError(redact(f"Antigravity CLI: {str(msg)[:300]}"))
        return str(data.get("response") or "")


PROVIDERS: dict[str, type[PromptProvider]] = {
    p.id: p for p in (NoProvider, AntigravityCLIProvider, NineRouterProvider, OpenAICompatibleProvider, GeminiProvider,
                      AnthropicProvider)
}


def create_provider(provider_id: str, *, api_key: str, model: str, base_url: str, temperature: float) -> PromptProvider:
    cls = PROVIDERS.get(provider_id, NoProvider)
    return cls(api_key=api_key, model=model, base_url=base_url, temperature=temperature)


def extract_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except ValueError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start = text.find(open_c)
        while start != -1:
            depth, in_str, esc = 0, False, False
            for i in range(start, len(text)):
                ch = text[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                elif ch == '"':
                    in_str = True
                elif ch == open_c:
                    depth += 1
                elif ch == close_c:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except ValueError:
                            break
            start = text.find(open_c, start + 1)
    raise PromptProviderError("The LLM did not return valid JSON. Try again or lower the temperature.")


# ---------------------------------------------------------------- scene prompts
@dataclass
class PromptContext:
    title: str
    aspect_ratio: str
    visual_style: str = ""
    characters: str = ""
    setting: str = ""
    palette: str = ""
    avoid: str = ""
    ref_tags: list[str] = field(default_factory=list)  # @names usable in prompts (Flow/Veo only)
    script: str = ""


SCENE_SYSTEM = """You are the visual director of a short educational explainer video.
For each scene you receive its narration. Write:
- image_prompt: ONE richly detailed still-image description that illustrates the narration: subject, action,
  composition for the given aspect ratio, camera angle, lighting, mood and the project's visual style.
  Keep characters, palette and setting consistent with the style bible. Do not ask for on-screen text,
  captions, letters or logos.
- motion_prompt: 1–2 sentences describing how this still image comes alive over the clip: camera movement
  (push-in, pan, orbit, crane) and subject motion. Smooth, physically plausible, no scene cuts.
Return ONLY JSON: {"scenes": [{"index": <int>, "image_prompt": "...", "motion_prompt": "..."}]}"""


def _bible(ctx: PromptContext) -> str:
    lines = [f"Visual style: {ctx.visual_style or 'clean modern explainer illustration'}"]
    if ctx.characters:
        lines.append(f"Recurring characters: {ctx.characters}")
    if ctx.setting:
        lines.append(f"Setting/world: {ctx.setting}")
    if ctx.palette:
        lines.append(f"Colour palette: {ctx.palette}")
    if ctx.avoid:
        lines.append(f"Avoid: {ctx.avoid}")
    if ctx.ref_tags:
        lines.append("Reference images can be bound in image prompts with these tags: " + ", ".join("@" + t for t in ctx.ref_tags))
    return "\n".join(lines)


def build_scene_request(ctx: PromptContext, scenes: list[dict], previous: str = "") -> tuple[str, str]:
    script = ctx.script if len(ctx.script) < 4000 else ctx.script[:4000] + " …"
    body = [f"Project: {ctx.title}", f"Aspect ratio: {ctx.aspect_ratio}", "", "STYLE BIBLE", _bible(ctx), "",
            "FULL NARRATION (context)", script, ""]
    if previous:
        body += ["Previous scene image prompt (for continuity):", previous, ""]
    body.append("SCENES TO WRITE")
    for s in scenes:
        body.append(f"- index {s['index']} ({s['duration']:.1f}s): {s['text'] or '(no narration — visual bridge)'}")
    return SCENE_SYSTEM, "\n".join(body)


def generate_scene_prompts(provider: PromptProvider, ctx: PromptContext, scenes: list[dict], *, cancel: CancelToken,
                           progress=None, batch_size: int = 8) -> dict[int, tuple[str, str]]:
    out: dict[int, tuple[str, str]] = {}
    previous = ""
    for b in range(0, len(scenes), batch_size):
        cancel.check()
        batch = scenes[b:b + batch_size]
        if progress:
            progress(b / max(1, len(scenes)), f"Writing prompts for scenes {batch[0]['index']}–{batch[-1]['index']}")
        system, user = build_scene_request(ctx, batch, previous)
        data = provider.complete_json(system, user)
        items = data.get("scenes") if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise PromptProviderError("LLM response is missing the 'scenes' list.")
        for it in items:
            try:
                idx = int(it["index"])
                out[idx] = (str(it.get("image_prompt", "")).strip(), str(it.get("motion_prompt", "")).strip())
            except (KeyError, ValueError, TypeError):
                continue
        last = batch[-1]["index"]
        previous = out.get(last, ("", ""))[0]
    return out


def draft_prompts_offline(ctx: PromptContext, text: str) -> tuple[str, str]:
    """Template prompts when no LLM is available. Meant as an editable starting point."""
    subject = text.strip() or "a visual bridge between ideas"
    framing = "wide cinematic 16:9 composition" if ctx.aspect_ratio == "16:9" else "vertical 9:16 composition, subject centered"
    parts = [ctx.visual_style or "Clean modern explainer illustration", f"illustrating: {subject}", framing,
             "clear focal subject, soft depth of field"]
    if ctx.characters:
        parts.append(ctx.characters)
    if ctx.setting:
        parts.append(ctx.setting)
    if ctx.palette:
        parts.append(f"palette: {ctx.palette}")
    if ctx.avoid:
        parts.append(f"no {ctx.avoid}")
    image = ". ".join(p.strip().rstrip(".") for p in parts if p) + "."
    motion = "Slow, smooth push-in toward the main subject with subtle natural motion in the scene; steady camera, no cuts."
    return image, motion
