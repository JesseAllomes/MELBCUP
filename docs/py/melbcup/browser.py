"""Entry point for the browser build (GitHub Pages, run by Pyodide in a Web Worker).

The page's JavaScript calls ``init`` once, then ``render`` for every page and ``act`` for every
button. There are no threads in the browser, so card loads run to completion one request at a
time, and API calls are synchronous XMLHttpRequests (allowed inside a Web Worker). The loaded
card, prices and results are handed back by ``save`` for the page to keep on the phone, so
reopening the page never re-spends credits.
"""

from __future__ import annotations

import base64
import pickle
from collections.abc import Callable
from datetime import datetime
from urllib.parse import parse_qsl, urlsplit

from melbcup import sources
from melbcup.archive import Archive
from melbcup.config import load_settings
from melbcup.live import LiveBoard
from melbcup.model.probability import assess
from melbcup.sources import http
from melbcup.web.views import NotFound, Views

STATE_VERSION = 1
_views: Views | None = None


def _parse_headers(raw: str) -> dict[str, str]:
    out = {}
    for line in raw.strip().splitlines():
        name, _, value = line.partition(":")
        if name:
            out[name.strip().lower()] = value.strip()
    return out


def xhr_text(path: str) -> str | None:
    """A same-origin file next to the page (the saved meetings), or None if absent."""
    from js import XMLHttpRequest  # type: ignore[import-not-found]

    xhr = XMLHttpRequest.new()
    xhr.open("GET", "data/" + path, False)
    try:
        xhr.send()
    except Exception:
        return None
    return str(xhr.responseText) if xhr.status == 200 else None


def xhr_requester(progress: Callable[[str], None] | None = None) -> http.Requester:
    """Synchronous XMLHttpRequest; only importable inside Pyodide."""
    from js import XMLHttpRequest  # type: ignore[import-not-found]

    def request(url: str, headers: dict[str, str]) -> http.RawResponse:
        if progress is not None:
            progress(url.split("?")[0].split("/v1/", 1)[-1])
        xhr = XMLHttpRequest.new()
        xhr.open("GET", url, False)
        for name, value in headers.items():
            xhr.setRequestHeader(name, value)
        try:
            xhr.send()
        except Exception as exc:  # a JsException: offline, DNS, CORS refusal
            raise OSError(str(exc)) from exc
        if xhr.status == 0:
            raise OSError("no response (offline?)")
        return http.RawResponse(
            int(xhr.status), _parse_headers(xhr.getAllResponseHeaders()), str(xhr.responseText)
        )

    return request


def _state(board: LiveBoard) -> dict:
    return {
        "version": STATE_VERSION,
        "race_date": board.race_date,
        "venue": board.venue,
        "card": board._card,
        "form_at": board._form_at,
        "priced_at": board._priced_at,
        "results_at": board._results_at,
        "meetings": board._meetings,
        "history": board._history,
    }


def _restore(board: LiveBoard, blob: str) -> None:
    try:
        state = pickle.loads(base64.b64decode(blob))
    except Exception:  # saved by an older version, or damaged: start clean
        return
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        return
    board.race_date, board.venue = state["race_date"], state["venue"]
    # Auto is the phone's normal state; it is switched off per visit, not remembered.
    board._card = state["card"]
    board._form_at, board._priced_at = state["form_at"], state["priced_at"]
    board._results_at, board._meetings = state["results_at"], state["meetings"]
    board._history = state.get("history", [])
    if board._card is not None:
        board._models = {r.number: assess(r) for r in board._card.races}
        board._updated_at = board._priced_at or board._form_at


def init(
    pe_key: str,
    ff_key: str,
    saved: str | None = None,
    progress: Callable[[str], None] | None = None,
    requester: http.Requester | None = None,
    archive_reader: Callable[[str], str | None] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> None:
    global _views
    sources.WORKERS = 1
    http.DEFAULT_REQUESTER = requester or xhr_requester(progress)
    settings = load_settings(
        {
            "PUNTERSEDGE_API_KEY": pe_key or "",
            "FORMFAV_API_KEY": ff_key or "",
            "APP_PASSWORD": "browser",
            "PRICE_MODE": "auto",  # on the phone it keeps itself up to date
        }
    )
    reader = archive_reader or (xhr_text if requester is None else None)
    archive = Archive(reader, pe_key) if pe_key and reader else None
    board = LiveBoard(settings, archive=archive, **({"clock": clock} if clock else {}))
    if saved:
        _restore(board, saved)
    board.check_credits()  # free: shows the balance before anything is spent
    _views = Views(settings, board, browser=True)


def _split(url: str) -> tuple[str, dict[str, str]]:
    parts = urlsplit(url)
    return parts.path or "/", dict(parse_qsl(parts.query))


def render(url: str) -> str:
    path, query = _split(url)
    try:
        return _views.page(path, query)
    except NotFound:
        return _views.page("/", query)


def act(url: str) -> str:
    """Run a button's action; returns the URL to show next."""
    path, query = _split(url)
    try:
        target = _views.action(path.removeprefix("/actions/"), query)
    except NotFound:
        return "/"
    if path.removeprefix("/actions/") in ("prices", "results", "load", "find"):
        _views.board.check_credits()  # the browser cannot read credit headers; this is free
    return target


def tick() -> bool:
    """Auto mode's heartbeat; True when anything changed and the page should redraw."""
    board = _views.board
    before = board._updated_at
    board.tick()
    return board._updated_at != before


def save() -> str:
    return base64.b64encode(pickle.dumps(_state(_views.board))).decode()
