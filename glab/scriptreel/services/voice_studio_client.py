"""G-Labs Voice Studio webhook client.

Documented API (WEBHOOK_INTEGRATION.en.md):
  GET  /api/health             (no auth)
  GET  /api/voices             (auth) → {"voices": [...], "count": n}
  POST /api/voice/design       (auth) → 202 {"task_id": ...}
  GET  /api/status/{task_id}   (auth)
  GET  /api/files/{name}       (no auth)
There is no cancel endpoint and the API returns audio only (no subtitles).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..core.logging_setup import shorten
from .http_base import BaseClient

log = logging.getLogger("scriptreel.voice")

LANGUAGE_CHOICES = [
    "Auto", "english", "bengali", "hindi", "urdu", "spanish", "french", "german", "portuguese",
    "italian", "arabic", "indonesian", "vietnamese", "japanese", "korean", "chinese", "russian", "turkish",
]


@dataclass
class VoicePreset:
    id: str
    name: str
    tags: list[str] = field(default_factory=list)
    is_factory: bool = False
    is_favorite: bool = False

    @property
    def label(self) -> str:
        star = "★ " if self.is_favorite else ""
        tags = f"  ·  {', '.join(self.tags)}" if self.tags else ""
        return f"{star}{self.name}{tags}"


class VoiceStudioClient(BaseClient):
    service_name = "Voice Studio"

    def list_voices(self) -> list[VoicePreset]:
        data = self.request_json("GET", "/api/voices")
        out = []
        for v in data.get("voices") or []:
            if not isinstance(v, dict) or not v.get("id"):
                continue
            out.append(VoicePreset(
                id=str(v["id"]),
                name=str(v.get("name") or v["id"]),
                tags=[str(t) for t in (v.get("tags") or [])],
                is_factory=bool(v.get("is_factory")),
                is_favorite=bool(v.get("is_favorite")),
            ))
        out.sort(key=lambda p: (not p.is_favorite, p.is_factory, p.name.lower()))
        return out

    def verify_key(self) -> int:
        """Authenticated call used by 'Test connection'. Returns preset count."""
        return len(self.list_voices())

    def submit(
        self,
        *,
        preset_id: str,
        script: str,
        language: str = "Auto",
        speed: float = 1.0,
        output_format: str = "wav",
        num_step: int | None = None,
        guidance_scale: float | None = None,
    ) -> str:
        if not preset_id:
            raise self._err("Choose a voice preset first.", kind="bad_request",
                            hint="Voice presets come from the Voice Bank in Voice Studio (GET /api/voices).")
        if not script.strip():
            raise self._err("The narration script is empty.", kind="bad_request")
        body: dict = {
            "preset_id": preset_id,
            "script": script,
            "language": language or "Auto",
            "speed": float(speed),
            "output_format": output_format if output_format in ("wav", "mp3") else "wav",
        }
        if num_step:
            body["num_step"] = int(num_step)
        if guidance_scale:
            body["guidance_scale"] = float(guidance_scale)
        log.info("Voice Studio: submit narration (%d chars, preset=%s, lang=%s, speed=%.2f, %s) «%s»",
                 len(script), preset_id, body["language"], body["speed"], body["output_format"], shorten(script, 40))
        data = self.request_json("POST", "/api/voice/design", body=body)
        task_id = data.get("task_id")
        if not task_id:
            raise self._err("Voice Studio accepted the request but returned no task_id.", kind="invalid_response")
        return str(task_id)

    def failure_hint(self, status: dict) -> str:
        err = str(status.get("error") or "").lower()
        if "preset" in err:
            return "Pick a voice that exists in the Voice Bank (press Refresh voices)."
        if "model" in err and ("load" in err or "download" in err):
            return "Open Voice Studio and run one generation there so the TTS model loads, then retry."
        if "mp3" in err:
            return "Switch the output format to WAV, or check Voice Studio's ffmpeg."
        if "script" in err:
            return "Provide a non-empty script."
        return "See Voice Studio's window for more details."
