"""Secure credential storage.

Keys are stored in the OS credential vault through `keyring`:
Windows Credential Manager on Windows (Keychain on macOS, Secret Service on
Linux). Nothing here is ever written to settings files, project files or logs.
If no secure backend exists, keys are kept for the current session only.
"""
from __future__ import annotations

import logging

from .logging_setup import Redactor

log = logging.getLogger("scriptreel.secrets")

SERVICE = "ScriptReel Studio"
VOICE_KEY = "voice_studio_api_key"
GLABS_KEY = "glabs_studio_api_key"


def llm_key(provider_id: str) -> str:
    return f"llm_api_key:{provider_id}"


class SecretStore:
    def __init__(self) -> None:
        self._cache: dict[str, str] = {}
        self._keyring = None
        self.persistent = False
        self.backend_name = "session only (no secure store found)"
        try:
            import keyring  # noqa: WPS433
            from keyring.backends import fail

            kr = keyring.get_keyring()
            name = type(kr).__module__ + "." + type(kr).__name__
            if isinstance(kr, fail.Keyring) or "fail" in name.lower() or "null" in name.lower():
                log.warning("No secure credential backend available; keys will not persist.")
            else:
                self._keyring = keyring
                self.persistent = True
                pretty = type(kr).__name__
                if "Windows" in name or "WinVault" in name:
                    pretty = "Windows Credential Manager"
                elif "macOS" in name or "OS_X" in name:
                    pretty = "macOS Keychain"
                elif "SecretService" in name:
                    pretty = "Secret Service"
                self.backend_name = pretty
        except Exception as exc:  # pragma: no cover - backend import issues
            log.warning("keyring unavailable: %s", type(exc).__name__)

    def get(self, name: str) -> str:
        if name in self._cache:
            return self._cache[name]
        value = ""
        if self._keyring is not None:
            try:
                value = self._keyring.get_password(SERVICE, name) or ""
            except Exception as exc:
                log.warning("Could not read credential '%s' (%s)", name, type(exc).__name__)
        self._cache[name] = value
        Redactor.register(value)
        return value

    def has(self, name: str) -> bool:
        return bool(self.get(name))

    def set(self, name: str, value: str) -> None:
        value = (value or "").strip()
        if not value:
            self.delete(name)
            return
        Redactor.register(value)
        self._cache[name] = value
        if self._keyring is not None:
            try:
                self._keyring.set_password(SERVICE, name, value)
                log.info("Stored credential '%s' in %s", name, self.backend_name)
            except Exception as exc:
                log.error("Could not store credential '%s' (%s); kept for this session only", name, type(exc).__name__)

    def delete(self, name: str) -> None:
        old = self._cache.pop(name, None)
        if self._keyring is not None:
            try:
                self._keyring.delete_password(SERVICE, name)
            except Exception:
                pass
        if old:
            log.info("Removed credential '%s'", name)

    def clear_all(self, extra_names: list[str] | None = None) -> None:
        names = {VOICE_KEY, GLABS_KEY, *(extra_names or [])}
        for n in names:
            self.delete(n)
