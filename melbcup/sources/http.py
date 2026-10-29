"""Shared JSON-over-HTTP client: API key header, TTL cache, typed errors."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import httpx


class SourceError(RuntimeError):
    """A data source could not answer. ``kind`` lets callers decide whether to retry."""

    def __init__(self, source: str, kind: str, message: str, status: int | None = None):
        super().__init__(f"{source}: {message}")
        self.source = source
        self.kind = kind
        self.status = status


def _kind(status: int) -> str:
    if status in (401, 403):
        return "auth"
    if status == 402:
        return "quota"
    if status == 429:
        return "rate_limit"
    if status == 404:
        return "not_found"
    if status >= 500:
        return "unavailable"
    return "bad_request"


class JsonSource:
    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.name = name
        self._clock = clock
        self._cache: dict[tuple, tuple[float, Any]] = {}
        self._http = httpx.Client(
            base_url=base_url,
            headers={"X-API-Key": api_key, "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )
        self.calls = 0
        self.last_headers: dict[str, str] = {}
        self._lock = threading.Lock()  # loads run on a thread pool

    def get(self, path: str, params: dict[str, Any] | None = None, *, ttl: float = 0) -> Any:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        key = (path, tuple(sorted((k, str(v)) for k, v in clean.items())))
        now = self._clock()
        with self._lock:
            hit = self._cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
        try:
            resp = self._http.get(path, params=clean)
        except httpx.HTTPError as exc:
            raise SourceError(self.name, "unavailable", f"{path}: {exc}") from exc
        with self._lock:
            self.calls += 1
            self.last_headers = {k.lower(): v for k, v in resp.headers.items()}
        if resp.status_code >= 400:
            detail = resp.text[:200].strip()
            raise SourceError(
                self.name,
                _kind(resp.status_code),
                f"{path} -> HTTP {resp.status_code} {detail}",
                resp.status_code,
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise SourceError(self.name, "bad_response", f"{path}: not JSON") from exc
        if ttl > 0:
            with self._lock:
                self._cache[key] = (now + ttl, data)
        return data

    def close(self) -> None:
        self._http.close()
