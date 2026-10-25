"""Logging with secret redaction.

Every handler uses `RedactingFormatter`, which strips registered secrets (API
keys), header values, base64 payloads and very long text before anything is
written to disk or shown in the activity panel.
"""
from __future__ import annotations

import logging
import re
import threading
from logging.handlers import RotatingFileHandler

from .paths import logs_dir

_DATA_URI_RE = re.compile(r"data:[\w.+/-]+;base64,[A-Za-z0-9+/=\s]{16,}")
_RAW_B64_RE = re.compile(r"[A-Za-z0-9+/]{300,}={0,2}")
_HEADER_RE = re.compile(
    r"(?i)(x-api-key|authorization|x-goog-api-key|api[_-]?key|bearer)(\"?'?\s*[:=]?\s*\"?'?)(bearer\s+)?([A-Za-z0-9_\-\.=+/]{8,})"
)
MASK = "••••"


class Redactor:
    _lock = threading.Lock()
    _secrets: set[str] = set()

    @classmethod
    def register(cls, secret: str | None) -> None:
        if secret and len(secret) >= 4:
            with cls._lock:
                cls._secrets.add(secret)

    @classmethod
    def unregister(cls, secret: str | None) -> None:
        if secret:
            with cls._lock:
                cls._secrets.discard(secret)

    @classmethod
    def redact(cls, text: str) -> str:
        if not text:
            return text
        with cls._lock:
            secrets = sorted(cls._secrets, key=len, reverse=True)
        for s in secrets:
            if s in text:
                text = text.replace(s, MASK)
        text = _DATA_URI_RE.sub("<base64 omitted>", text)
        text = _RAW_B64_RE.sub("<base64 omitted>", text)
        text = _HEADER_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", text)
        return text


def redact(text: str) -> str:
    return Redactor.redact(str(text))


def shorten(text: str, limit: int = 80) -> str:
    """For logging prompts/scripts: never dump full user content."""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return Redactor.redact(super().format(record))


_configured = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    global _configured
    root = logging.getLogger("scriptreel")
    if _configured:
        return root
    root.setLevel(level)
    fmt = RedactingFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    try:
        fh = RotatingFileHandler(logs_dir() / "scriptreel.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh.setLevel(logging.WARNING)
    root.addHandler(sh)
    # Never let httpx log request headers/URLs with secrets at INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    _configured = True
    return root
