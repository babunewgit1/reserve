"""Minimal localization: English source strings are the keys.

Add a language by creating `config/i18n/<code>.json` mapping English text to
the translation. Missing entries fall back to English.
"""
from __future__ import annotations

import json
import logging

from .paths import i18n_dir

log = logging.getLogger("scriptreel.i18n")

LANGUAGES = {"en": "English", "bn": "বাংলা (Bengali)"}
_table: dict[str, str] = {}
_lang = "en"


def set_language(code: str) -> None:
    global _table, _lang
    _lang = code if code in LANGUAGES else "en"
    _table = {}
    if _lang == "en":
        return
    p = i18n_dir() / f"{_lang}.json"
    try:
        _table = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Translation file %s unavailable: %s", p.name, exc)


def current_language() -> str:
    return _lang


def t(text: str) -> str:
    return _table.get(text, text)
