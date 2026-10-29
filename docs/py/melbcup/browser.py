"""Entry point for the browser build (GitHub Pages, run by Pyodide in a Web Worker).

The page's JavaScript calls ``init`` once, then ``render`` for every page and ``act`` for every
button. There are no threads in the browser and API calls are synchronous XMLHttpRequests
(allowed inside a Web Worker), one at a time. So before a card load the page calls ``warm``,
which fetches the load's ~100 requests six at a time and caches them; the load then reads them
from the cache. The loaded
card, prices and results are handed back by ``save`` for the page to keep on the phone, so
reopening the page never re-spends credits.
"""

from __future__ import annotations

import base64
import pickle
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from melbcup import sources
from melbcup.archive import Archive
from melbcup.config import load_settings
from melbcup.live import LiveBoard
from melbcup.model.probability import assess
from melbcup.sources import http
from melbcup.sources.racingcom import RacingComClient
from melbcup.web.views import NotFound, Views

STATE_VERSION = 1
_views: Views | None = None
# (urls, headers, label) -> awaitable list of [status, text]: the page's parallel fetch.
FetchMany = Callable[[list[str], dict[str, str], str], Awaitable[Any]]
_fetch_many: FetchMany | None = None


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
    # Auto is not remembered: opening the page never spends credits by itself.
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
    fetch_many: FetchMany | None = None,
    history_password: str | None = None,
) -> None:
    global _views, _fetch_many
    _fetch_many = fetch_many
    sources.WORKERS = 1
    http.DEFAULT_REQUESTER = requester or xhr_requester(progress)
    settings = load_settings(
        {
            "PUNTERSEDGE_API_KEY": pe_key or "",
            "FORMFAV_API_KEY": ff_key or "",
            "APP_PASSWORD": "browser",
            "PRICE_MODE": "manual",  # Auto spends credits: off each time the page opens
        }
    )
    reader = archive_reader or (xhr_text if requester is None else None)
    # The owner's PuntersEdge key opens the saved meetings; friends with their own key use the
    # History password the owner gave them.
    archive = Archive(reader, pe_key, history_password) if reader else None
    board = LiveBoard(
        settings, archive=archive, rc=RacingComClient(), **({"clock": clock} if clock else {})
    )
    if saved:
        _restore(board, saved)
    board.check_credits()  # free: shows the balance before anything is spent
    _views = Views(settings, board, browser=True)


async def warm(manual: bool = False) -> int:
    """Before a card load, fetch its requests side by side and cache the replies, so the load
    itself runs from the cache instead of making ~100 calls one after another. Spends nothing
    the load would not (the acceptances are cached for it too). A request that fails here is
    simply made again by the load, which reports it as usual. Returns the replies cached."""
    board = _views.board if _views else None
    if _fetch_many is None or board is None or not board.load_due(board.clock(), manual=manual):
        return 0
    try:
        card = board.pe.acceptances(board.race_date, board.venue)
    except http.SourceError:
        return 0  # the load asks again and shows the reason
    cached = 0
    clients = (
        (board.pe, "recent form"),
        (board.ff, "form and stats"),
        (board.rc, "stewards' notes"),
    )
    for client, label in clients:
        if client is None:
            continue
        todo = client.src.missing(client.load_requests(card))
        if not todo:
            continue
        replies = await _fetch_many([url for _, url, _ in todo], client.src.headers, label)
        replies = replies.to_py() if hasattr(replies, "to_py") else replies
        for (key, _, ttl), (status, text) in zip(todo, replies, strict=True):
            if status == 200:
                cached += client.src.seed(key, text, ttl)
    return cached


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
