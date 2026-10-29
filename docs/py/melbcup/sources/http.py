"""Shared JSON-over-HTTP client: API key header, TTL cache, typed errors.

On a server requests go through httpx. In the browser build (GitHub Pages) there is no httpx
and no threads: the page installs ``DEFAULT_REQUESTER``, a synchronous XMLHttpRequest from a Web
Worker, and everything above this module runs unchanged.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

if TYPE_CHECKING:
    import httpx


@dataclass
class RawResponse:
    status: int
    headers: dict[str, str]  # lower-case names
    text: str


# (url with query string, request headers) -> response; raise OSError when unreachable.
Requester = Callable[[str, dict[str, str]], RawResponse]
DEFAULT_REQUESTER: Requester | None = None


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
        requester: Requester | None = None,
    ):
        self.name = name
        self._clock = clock
        self._cache: dict[tuple, tuple[float, Any]] = {}
        self._base = base_url.rstrip("/")
        self._headers = {"X-API-Key": api_key, "Accept": "application/json"}
        self._requester = requester or (None if transport else DEFAULT_REQUESTER)
        self._http = None
        if self._requester is None:
            import httpx

            self._http = httpx.Client(
                base_url=base_url, headers=self._headers, timeout=timeout, transport=transport
            )
        self.calls = 0
        self.last_headers: dict[str, str] = {}
        self._lock = threading.Lock()  # loads run on a thread pool

    def _send(self, path: str, params: dict[str, Any]) -> RawResponse:
        if self._http is None:
            query = f"?{urlencode(params)}" if params else ""
            try:
                return self._requester(self._base + path + query, self._headers)
            except OSError as exc:
                raise SourceError(self.name, "unavailable", f"{path}: {exc}") from exc
        import httpx

        try:
            resp = self._http.get(path, params=params)
        except httpx.HTTPError as exc:
            raise SourceError(self.name, "unavailable", f"{path}: {exc}") from exc
        return RawResponse(
            resp.status_code, {k.lower(): v for k, v in resp.headers.items()}, resp.text
        )

    def get(self, path: str, params: dict[str, Any] | None = None, *, ttl: float = 0) -> Any:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        key = (path, tuple(sorted((k, str(v)) for k, v in clean.items())))
        now = self._clock()
        with self._lock:
            hit = self._cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
        resp = self._send(path, clean)
        with self._lock:
            self.calls += 1
            self.last_headers = resp.headers
        if resp.status >= 400:
            raise SourceError(
                self.name,
                _kind(resp.status),
                f"{path} -> HTTP {resp.status} {resp.text[:200].strip()}",
                resp.status,
            )
        try:
            import json

            data = json.loads(resp.text)
        except ValueError as exc:
            raise SourceError(self.name, "bad_response", f"{path}: not JSON") from exc
        if ttl > 0:
            with self._lock:
                self._cache[key] = (now + ttl, data)
        return data

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
