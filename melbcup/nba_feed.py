"""The NBA page's data (AsynymBet, ASYNYM=1): today's board, PointsBet's live props, the legs.

The board (the model's expected counts per player) is built each morning by the melbcup-nba job
and kept in the Blob container ``nba``. The page reads it with the container app's managed
identity (NBA_ACCOUNT names the storage account; AZURE_CLIENT_ID picks the identity) over plain
HTTP, so the web image needs no Azure libraries. Without that, or when the read fails, it uses the
board shipped with the app (data/nba/board-latest.json), and says so.

PointsBet is read live when the page opens (kept 90 seconds), and every leg is priced through
melbcup/nba_legs.py: the same code the Azure Function and the tools run.
"""

from __future__ import annotations

import gzip
import json
import os
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from melbcup import nba_legs

NY = ZoneInfo("America/New_York")
BUNDLED = Path(__file__).resolve().parents[1] / "data" / "nba" / "board-latest.json"
PRICES_TTL_S = 90
STAGED_MAX_AGE = timedelta(minutes=30)  # older than this, the page works prices out itself
AGENCY_NAMES = {"sb": "Sportsbet", "pb": "PointsBet"}
BOARD_TTL_S = 600
TIMEOUT_S = 8


_TOKEN: dict[str, tuple[float, str]] = {}


def _token(client_id: str | None) -> str:
    """A storage token for the app's managed identity (Container Apps endpoint), kept 30 min."""
    stamp, tok = _TOKEN.get(client_id or "", (0.0, ""))
    if tok and time.monotonic() - stamp < 1800:
        return tok
    endpoint, secret = os.environ.get("IDENTITY_ENDPOINT"), os.environ.get("IDENTITY_HEADER")
    if not endpoint or not secret:
        raise httpx.HTTPError("no managed identity here")
    params = {"resource": "https://storage.azure.com/", "api-version": "2019-08-01"}
    if client_id:
        params["client_id"] = client_id
    resp = httpx.get(
        endpoint, params=params, headers={"X-IDENTITY-HEADER": secret}, timeout=TIMEOUT_S
    )
    resp.raise_for_status()
    tok = resp.json()["access_token"]
    _TOKEN[client_id or ""] = (time.monotonic(), tok)
    return tok


def blob_reader(account: str, client_id: str | None) -> Callable[[str], bytes | None]:
    """Read a blob of container `nba` with the app's managed identity."""

    def read(name: str) -> bytes | None:
        if not os.environ.get("IDENTITY_ENDPOINT"):
            return None
        resp = httpx.get(
            f"https://{account}.blob.core.windows.net/nba/{name}",
            headers={"Authorization": f"Bearer {_token(client_id)}", "x-ms-version": "2021-08-06"},
            timeout=TIMEOUT_S,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.content

    return read


def nearest(legs: list[dict], min_chance: float = 0.75, n: int = 5) -> list[dict]:
    """When nothing is value: the likely legs whose price comes closest to fair."""
    likely = [g for g in legs if g["chance"] >= min_chance]
    return sorted(likely, key=lambda g: -g["ev"])[:n]


class NbaFeed:
    def __init__(
        self,
        read_blob: Callable[[str], bytes | None] | None = None,
        events: Callable[[], list[dict]] | dict | None = None,
        bundled: Path = BUNDLED,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        if read_blob is None and os.environ.get("NBA_ACCOUNT"):
            read_blob = blob_reader(os.environ["NBA_ACCOUNT"], os.environ.get("AZURE_CLIENT_ID"))
        if events is None:
            events = dict(nba_legs.AGENCY_EVENTS)  # every agency with NBA player lines
        elif callable(events):
            events = {"pb": events}
        self.read_blob, self.events, self.bundled, self.clock = read_blob, events, bundled, clock
        self._lock = threading.Lock()
        self._board: tuple[float, dict | None, str] = (0.0, None, "")
        self._view: tuple[float, dict | None] = (0.0, None)

    def board(self) -> tuple[dict | None, str]:
        stamp, board, source = self._board
        if board is not None and time.monotonic() - stamp < BOARD_TTL_S:
            return board, source
        board, source = None, ""
        if self.read_blob is not None:
            try:
                raw = self.read_blob("board-latest.json")
                if raw:
                    board, source = json.loads(raw), "azure"
            except (httpx.HTTPError, ValueError, KeyError):
                board = None
        if board is None and self.bundled.is_file():
            board, source = json.loads(self.bundled.read_text()), "bundled"
        self._board = (time.monotonic(), board, source)
        return board, source

    def schedule(self) -> dict:
        """{Melbourne night: [tip-offs]} for the coming week (the daily job's schedule.json),
        kept an hour; {} when it cannot be read."""
        stamp, sched = getattr(self, "_sched", (0.0, None))
        if sched is not None and time.monotonic() - stamp < 3600:
            return sched
        sched = {}
        if self.read_blob is not None:
            try:
                raw = self.read_blob("schedule.json")
                sched = json.loads(raw) if raw else {}
            except (httpx.HTTPError, ValueError, KeyError):
                sched = {}
        self._sched = (time.monotonic(), sched)
        return sched

    def view(self) -> dict:
        """The page's data. A copy older than PRICES_TTL_S is still served at once while a
        background refresh fetches new prices, so only the very first visit waits."""
        stamp, cached = self._view
        if cached is not None:
            if time.monotonic() - stamp >= PRICES_TTL_S and self._lock.acquire(blocking=False):
                threading.Thread(target=self._refresh_locked, daemon=True).start()
            return cached
        saved = self._saved(max_age=None)
        if (
            saved is not None
        ):  # the timer's page data, however old: shown at once (owner, 2026-11-04)
            self._view = (time.monotonic(), saved)
            if saved["age"] > STAGED_MAX_AGE and self._lock.acquire(blocking=False):
                threading.Thread(target=self._refresh_locked, daemon=True).start()
            return saved
        with self._lock:
            if self._view[1] is None:
                self._compute()
            return self._view[1]

    def _saved(self, max_age: timedelta | None = STAGED_MAX_AGE) -> dict | None:
        """The page data the Azure timer worked out on its last run (every 10 minutes, both
        agencies): used whenever it is under STAGED_MAX_AGE old, so this small web app only
        reads it and never does the heavy search itself (owner, 2026-11-04: pages must be fast)."""
        if self.read_blob is None:
            return None
        try:
            raw = self.read_blob("view-latest.json.gz")
            board, source = self.board()
            v = json.loads(gzip.decompress(raw)) if raw else None
        except (httpx.HTTPError, ValueError, KeyError, OSError):
            return None
        if not v or board is None or v.get("day") != board.get("day") or not v.get("agencies"):
            return None
        now = self.clock()
        priced = datetime.fromisoformat(v["pricedAt"]) if v.get("pricedAt") else None
        if priced is None or (max_age is not None and now - priced > max_age):
            return None
        agencies = v["agencies"]
        first = agencies.get("pb") or next(iter(agencies.values()))
        today = now.astimezone(NY).strftime("%Y%m%d")
        return {
            "today": today,
            "source": source,
            "board": board,
            "error": None,
            "report": first["report"],
            "agencies": agencies,
            "preview": v.get("preview") or {},
            "nearest": [],
            "games": first.get("games", 0),
            "priced_at": priced,
            "stale": board.get("day", "") < today,
            "staged": True,
            "age": now - priced,
        }

    def _refresh_locked(self) -> None:
        try:
            self._compute()
        finally:
            self._lock.release()

    def _compute(self) -> None:
        saved = self._saved()
        if saved is not None:  # the timer has fresh page data: read it, do not redo the search
            self._view = (time.monotonic(), saved)
            return
        now = self.clock()
        today = now.astimezone(NY).strftime("%Y%m%d")
        board, source = self.board()
        out: dict = {"today": today, "source": source, "board": board, "error": None}
        if board is None:
            out["error"] = "No board yet: the model has not priced today's games."
        else:
            from concurrent.futures import ThreadPoolExecutor

            from melbcup import nba_challenge

            def one(code):
                try:
                    return code, self.events[code](), None
                except (OSError, ValueError, KeyError) as exc:
                    name = AGENCY_NAMES.get(code, code)
                    return code, [], f"{name} did not answer ({type(exc).__name__})."

            with ThreadPoolExecutor(max_workers=len(self.events)) as pool:
                got = list(pool.map(one, self.events))
            xs = {n: nba_challenge.stage_x(10.0, 1000.0, n, True) for n in nba_challenge.STAGES}
            # one view over every agency: each leg's market price uses all the bookmakers
            v = nba_legs.view(board, {code: ev for code, ev, _ in got}, xs)
            out["agencies"], out["preview"] = v["agencies"], v.get("preview") or {}
            for code, _, error in got:
                out["agencies"][code]["error"] = error
            first = out["agencies"].get("pb") or next(iter(out["agencies"].values()))
            out["report"], out["games"], out["error"] = (
                first["report"],
                first["games"],
                first["error"],
            )
            out["nearest"] = (
                [] if first["report"]["value_legs"] else nearest(first["report"]["all_legs"])
            )
        out["priced_at"] = now
        # a board for tonight's or tomorrow's US games is current; one for an earlier day is not
        out["stale"] = board is not None and board.get("day", "") < today
        self._view = (time.monotonic(), out)
