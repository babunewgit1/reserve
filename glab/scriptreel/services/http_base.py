"""Shared HTTP plumbing for the two G-Labs webhook clients.

* Timeouts on every request.
* Retries only where safe: GETs on transient errors, and POSTs only when the
  connection was never established (request provably not received).
* Clear error kinds for 401/403/404/413/429/5xx and task failures.
* Nothing secret is logged (see core.logging_setup).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse, urlunparse

import httpx

from ..core.logging_setup import Redactor, redact

log = logging.getLogger("scriptreel.http")


class CancelledError(Exception):
    """Local cancellation. Remote G-Labs tasks cannot be cancelled (no documented endpoint)."""


class CancelToken:
    def __init__(self) -> None:
        self._ev = threading.Event()

    def cancel(self) -> None:
        self._ev.set()

    @property
    def cancelled(self) -> bool:
        return self._ev.is_set()

    def check(self) -> None:
        if self._ev.is_set():
            raise CancelledError("Cancelled")

    def sleep(self, seconds: float) -> None:
        if self._ev.wait(max(0.0, seconds)):
            raise CancelledError("Cancelled")


HTTP_HINTS = {
    400: "The server rejected the request as invalid.",
    401: "API key rejected. Copy the key shown in the app's Webhook tab into Settings → Connections.",
    403: "Access denied. G-Labs Studio's Webhook server requires a MAX plan; also check that the account/session is active.",
    404: "Not found on this server. Tasks are kept in memory only and disappear when the app restarts.",
    413: "Request too large (50 MB cap). Use fewer/smaller reference images, or set reference transfer to 'local file path'.",
    429: "Quota or rate limit reached on the logged-in account. Wait, enable more accounts in G-Labs, or retry later.",
    500: "The app reported an internal error. Check the app window for details.",
}

KIND_BY_STATUS = {400: "bad_request", 401: "auth", 403: "forbidden", 404: "not_found", 413: "payload_too_large", 429: "rate_limited"}


class ServiceError(Exception):
    def __init__(
        self,
        message: str,
        *,
        service: str = "",
        kind: str = "error",
        status: int | None = None,
        error_code: int | None = None,
        detail: str = "",
        hint: str = "",
        fallback: str = "",
    ) -> None:
        super().__init__(redact(message))
        self.service = service
        self.kind = kind
        self.status = status
        self.error_code = error_code
        self.detail = redact(detail)
        self.hint = hint
        self.fallback = fallback

    @property
    def message(self) -> str:
        return str(self)

    def user_text(self) -> str:
        parts = [str(self)]
        if self.hint:
            parts.append(self.hint)
        return "\n".join(parts)


def ext_from_url(url: str, default: str) -> str:
    name = unquote(urlparse(url).path.rsplit("/", 1)[-1])
    if "." in name:
        ext = "." + name.rsplit(".", 1)[-1].lower()
        if 1 < len(ext) <= 6 and ext[1:].isalnum():
            return ext
    return default


class BaseClient:
    service_name = "Service"

    def __init__(self, base_url: str, api_key: str = "", timeout: float = 30.0) -> None:
        self.base_url = (base_url or "").strip().rstrip("/")
        self.api_key = (api_key or "").strip()
        Redactor.register(self.api_key)
        self._timeout = float(timeout)
        # trust_env=False: never route loopback calls through a system proxy.
        self._http = httpx.Client(
            timeout=httpx.Timeout(self._timeout, connect=min(5.0, self._timeout)),
            trust_env=False,
            follow_redirects=False,
        )

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- request helpers ----------------------------------------------------
    def _headers(self, auth: bool) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if auth and self.api_key:
            h["X-API-Key"] = self.api_key
        return h

    def _err(self, message: str, **kw) -> ServiceError:
        return ServiceError(message, service=self.service_name, **kw)

    def request_json(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        auth: bool = True,
        retries: int | None = None,
        timeout: float | None = None,
    ) -> dict:
        if not self.base_url.startswith(("http://", "https://")):
            raise self._err(f"{self.service_name} base URL is not set or invalid.", kind="config",
                            hint="Open Settings → Connections and enter e.g. http://127.0.0.1:8765")
        idempotent = method.upper() == "GET"
        attempts = 1 + (retries if retries is not None else (2 if idempotent else 1))
        url = self.base_url + path
        last: ServiceError | None = None
        for attempt in range(attempts):
            try:
                resp = self._http.request(method, url, json=body, headers=self._headers(auth),
                                          timeout=timeout or self._timeout)
            except httpx.ConnectError as exc:
                # Connection never established → the server did not receive the request; safe to retry.
                last = self._err(
                    f"Cannot connect to {self.service_name} at {self.base_url}.",
                    kind="connection",
                    hint=f"Start {self.service_name}, open its Webhook tab and press Start. Check the base URL and port.",
                )
                if attempt < attempts - 1:
                    time.sleep(0.7 * (attempt + 1))
                    continue
                raise last from exc
            except httpx.TimeoutException as exc:
                last = self._err(f"{self.service_name} did not respond in time.", kind="timeout",
                                 hint="The app may be busy or frozen. Try again in a moment.")
                if idempotent and attempt < attempts - 1:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise last from exc
            except httpx.HTTPError as exc:
                raise self._err(f"{self.service_name} request failed ({type(exc).__name__}).", kind="connection") from exc

            if resp.status_code in (502, 503, 504) and idempotent and attempt < attempts - 1:
                time.sleep(1.0 * (attempt + 1))
                continue
            return self._parse(resp)
        assert last is not None
        raise last

    def _parse(self, resp: httpx.Response) -> dict:
        try:
            data: Any = resp.json()
        except ValueError:
            data = None
        code = resp.status_code
        if 200 <= code < 300:
            if not isinstance(data, dict):
                raise self._err(f"{self.service_name} returned an unexpected (non-JSON) response.", kind="invalid_response", status=code)
            return data
        msg = data.get("error") if isinstance(data, dict) else None
        msg = msg or resp.reason_phrase or f"HTTP {code}"
        kind = KIND_BY_STATUS.get(code, "server" if code >= 500 else "http")
        raise self._err(f"{self.service_name}: {msg} (HTTP {code})", kind=kind, status=code,
                        hint=HTTP_HINTS.get(code, HTTP_HINTS[500] if code >= 500 else ""))

    # -- documented common endpoints ------------------------------------------
    def health(self) -> dict:
        """GET /api/health (no auth)."""
        return self.request_json("GET", "/api/health", auth=False, retries=0, timeout=5.0)

    def get_status(self, task_id: str) -> dict:
        try:
            return self.request_json("GET", f"/api/status/{task_id}")
        except ServiceError as exc:
            if exc.status == 404:
                raise self._err(
                    f"Task {task_id} is no longer known to {self.service_name}.",
                    kind="task_lost",
                    status=404,
                    hint="Tasks live in the app's memory only, so it was probably restarted. Generate this item again.",
                ) from exc
            raise

    def failure_hint(self, status: dict) -> str:  # overridden per service
        return ""

    def wait_for_task(
        self,
        task_id: str,
        *,
        timeout_s: float,
        interval_s: float,
        cancel: CancelToken,
        on_status: Callable[[dict], None] | None = None,
    ) -> dict:
        """Poll /api/status/{task_id} until completed/failed. Returns the final status dict."""
        deadline = time.monotonic() + timeout_s
        conn_failures = 0
        while True:
            cancel.check()
            try:
                st = self.get_status(task_id)
                conn_failures = 0
            except ServiceError as exc:
                if exc.kind in ("connection", "timeout") and conn_failures < 6:
                    conn_failures += 1
                    if on_status:
                        on_status({"status": "reconnecting", "task_id": task_id})
                    cancel.sleep(interval_s * 1.5)
                    continue
                raise
            status = st.get("status", "")
            if on_status:
                on_status(st)
            if status == "completed":
                if not st.get("results"):
                    raise self._err(f"Task {task_id} completed but returned no files.", kind="invalid_response")
                return st
            if status == "failed":
                err = st.get("error") or "Task failed"
                code = st.get("error_code")
                raise self._err(
                    f"{self.service_name} task {task_id} failed: {err}",
                    kind="task_failed",
                    error_code=code if isinstance(code, int) else None,
                    detail=str(st.get("error_detail") or ""),
                    hint=self.failure_hint(st),
                )
            if time.monotonic() > deadline:
                raise self._err(
                    f"Timed out after {int(timeout_s)} s waiting for task {task_id}.",
                    kind="timeout",
                    hint="The task may still finish inside the app. Use 'Resume' later to keep polling it.",
                )
            cancel.sleep(interval_s)

    def download(self, url: str, dest: Path, *, cancel: CancelToken,
                 on_progress: Callable[[int, int], None] | None = None) -> Path:
        """Download a documented /api/files/... result (no API key required)."""
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.path.startswith("/api/files/"):
            raise self._err("Refusing to download an unexpected result URL.", kind="invalid_response")
        if parsed.hostname in (None, "", "0.0.0.0"):
            url = urlunparse(parsed._replace(netloc=urlparse(self.base_url).netloc))
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        for attempt in range(3):
            try:
                with self._http.stream("GET", url, timeout=httpx.Timeout(180.0, connect=5.0)) as r:
                    if r.status_code != 200:
                        raise self._err(
                            f"Download failed (HTTP {r.status_code}).",
                            kind="not_found" if r.status_code == 404 else "http",
                            status=r.status_code,
                            hint="Result files are local to the app and may be cleaned up. Generate again if needed.",
                        )
                    total = int(r.headers.get("content-length") or 0)
                    got = 0
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_bytes(1 << 16):
                            cancel.check()
                            f.write(chunk)
                            got += len(chunk)
                            if on_progress:
                                on_progress(got, total)
                os.replace(tmp, dest)
                return dest
            except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError, httpx.TimeoutException) as exc:
                if attempt == 2:
                    raise self._err(f"Download from {self.service_name} failed ({type(exc).__name__}).",
                                    kind="connection") from exc
                time.sleep(1.5 * (attempt + 1))
            finally:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
        raise self._err("Download failed.", kind="connection")
