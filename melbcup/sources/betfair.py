"""Betfair Exchange prices, read only, from the owner's own account.

The owner's Betfair username and password come from Key Vault through the environment
(BETFAIR_USERNAME, BETFAIR_PASSWORD). The free delayed app key is read from the account itself
(getDeveloperAppKeys, created once if the account has none): its prices can be a minute or more
old and it cannot place bets, which is all the app needs. BETFAIR_APP_KEY, if set, is used
instead. Nothing here ever logs or returns a password, token or key.

Prices are the best back price on each runner. Winnings pay commission, so the app judges a
Betfair price after commission (``melbcup.domain.betfair_net``); the page shows Betfair's price.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from melbcup.config import MELBOURNE
from melbcup.sources.http import SourceError

LOGIN_URL = "https://identitysso.betfair.com.au/api/login"
ACCOUNT_URL = "https://api.betfair.com/exchange/account/json-rpc/v1"
BETTING_URLS = (
    "https://api.betfair.com.au/exchange/betting/json-rpc/v1",
    "https://api.betfair.com/exchange/betting/json-rpc/v1",
)
APP_NAME = "melbcup"
HORSE_RACING = "7"
BOOK_CHUNK = 20  # markets per listMarketBook call, well inside Betfair's request weight limit
SESSION_LIFE = timedelta(hours=3)

# (url, headers, body, is_json) -> (status, parsed JSON); raise OSError when unreachable.
Poster = Callable[[str, dict[str, str], Any, bool], tuple[int, Any]]


def _httpx_post(url: str, headers: dict[str, str], body: Any, is_json: bool) -> tuple[int, Any]:
    import httpx

    with httpx.Client(timeout=20.0) as client:
        if is_json:
            resp = client.post(url, headers=headers, content=json.dumps(body))
        else:
            resp = client.post(url, headers=headers, data=body)
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, None


@dataclass
class RacePrices:
    """Best back prices by saddlecloth number for one race, and the ids needed to bet on it."""

    win: dict[int, float]
    place: dict[int, float]
    win_market: str | None = None
    place_market: str | None = None
    selections: dict[int, int] = field(default_factory=dict)  # saddlecloth -> selection id


@dataclass
class Order:
    """Betfair's answer to one back bet."""

    status: str  # "SUCCESS" or Betfair's failure code
    bet_id: str | None = None
    matched: float = 0.0
    price: float | None = None


class BetfairClient:
    def __init__(
        self,
        username: str,
        password: str,
        app_key: str | None = None,
        post: Poster | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._username = username
        self._password = password
        self._app_key = app_key
        self._post = post or _httpx_post
        self._clock = clock
        self._token: str | None = None
        self._token_at: datetime | None = None
        self._betting_url: str | None = None

    def __repr__(self) -> str:  # never show the login
        return "BetfairClient()"

    # -- session ------------------------------------------------------------------------------
    def _login(self) -> None:
        headers = {
            "X-Application": self._app_key or APP_NAME,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        body = {"username": self._username, "password": self._password}
        try:
            status, data = self._post(LOGIN_URL, headers, body, False)
        except OSError as exc:
            raise SourceError("Betfair", "unavailable", "login could not reach Betfair") from exc
        if status != 200 or not isinstance(data, dict):
            raise SourceError("Betfair", "unavailable", f"login answered HTTP {status}", status)
        if data.get("status") != "SUCCESS" or not data.get("token"):
            reason = str(data.get("error") or data.get("status") or "unknown")
            raise SourceError("Betfair", "auth", f"login refused ({reason})")
        self._token = data["token"]
        self._token_at = self._clock()

    def _session(self) -> None:
        if self._token is None or self._clock() - self._token_at > SESSION_LIFE:
            self._login()
        if self._app_key is None:
            self._app_key = self._delayed_key()

    def _rpc(self, url: str, method: str, params: dict) -> Any:
        headers = {
            "X-Authentication": self._token or "",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._app_key is not None:
            # Fetching or creating the account's own keys works with the session alone; a made-up
            # app key there is refused (INVALID_APP_KEY, seen live 2026-11-01).
            headers["X-Application"] = self._app_key
        body = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        try:
            status, data = self._post(url, headers, body, True)
        except OSError as exc:
            raise SourceError(
                "Betfair", "unavailable", f"{method} could not reach Betfair"
            ) from exc
        if status != 200 or not isinstance(data, dict):
            raise SourceError("Betfair", "unavailable", f"{method} answered HTTP {status}", status)
        if "error" in data:
            err = data["error"]
            code = ""
            if isinstance(err, dict):
                detail = (err.get("data") or {}).values()
                code = next((d.get("errorCode", "") for d in detail if isinstance(d, dict)), "")
                code = code or str(err.get("message", ""))
            kind = (
                "auth"
                if re.search(r"SESSION|APP_KEY|PERMISSION|NO_SESSION", code)
                else "bad_request"
            )
            if kind == "auth":
                self._token = None  # log in again next time
            raise SourceError("Betfair", kind, f"{method.split('/')[-1]} refused ({code})")
        return data.get("result")

    def _delayed_key(self) -> str:
        """The account's delayed app key, created once if the account has none."""
        method = "AccountAPING/v1.0/getDeveloperAppKeys"
        apps = self._rpc(ACCOUNT_URL, method, {}) or []
        if not apps:
            self._rpc(
                ACCOUNT_URL, "AccountAPING/v1.0/createDeveloperAppKeys", {"appName": APP_NAME}
            )
            apps = self._rpc(ACCOUNT_URL, method, {}) or []
        versions = [v for app in apps for v in app.get("appVersions", [])]
        for want_delay in (True, False):
            for v in versions:
                if bool(v.get("delayData")) == want_delay and v.get("active", True):
                    if key := v.get("applicationKey"):
                        return key
        raise SourceError("Betfair", "auth", "the account has no active app key")

    def _betting(self, method: str, params: dict) -> Any:
        urls = (self._betting_url,) if self._betting_url else BETTING_URLS
        last: SourceError | None = None
        for url in urls:
            try:
                result = self._rpc(url, f"SportsAPING/v1.0/{method}", params)
            except SourceError as exc:
                if exc.kind == "auth":
                    raise
                last = exc
                continue
            self._betting_url = url
            return result
        raise last or SourceError("Betfair", "unavailable", f"{method} failed")

    # -- prices -------------------------------------------------------------------------------
    def meeting(self, race_date: date, venue: str) -> dict[int, RacePrices]:
        """Win and place back prices for every open race at one meeting, by race number."""
        self._session()
        start = datetime.combine(race_date, time(0), MELBOURNE).astimezone(UTC)
        end = start + timedelta(days=1)
        markets = (
            self._betting(
                "listMarketCatalogue",
                {
                    "filter": {
                        "eventTypeIds": [HORSE_RACING],
                        "marketCountries": ["AU"],
                        "marketTypeCodes": ["WIN", "PLACE"],
                        "venues": [venue],
                        "marketStartTime": {"from": _iso(start), "to": _iso(end)},
                    },
                    "marketProjection": [
                        "RUNNER_METADATA",
                        "MARKET_START_TIME",
                        "MARKET_DESCRIPTION",
                    ],
                    "maxResults": "200",
                },
            )
            or []
        )
        races = match_markets(markets)
        ids = [mid for win_id, place_id, _ in races.values() for mid in (win_id, place_id) if mid]
        books: dict[str, dict[int, float]] = {}
        for chunk in _chunks(ids, BOOK_CHUNK):
            for book in (
                self._betting(
                    "listMarketBook",
                    {"marketIds": chunk, "priceProjection": {"priceData": ["EX_BEST_OFFERS"]}},
                )
                or []
            ):
                books[book.get("marketId")] = back_prices(book)
        out: dict[int, RacePrices] = {}
        for number, (win_id, place_id, cloth) in races.items():
            win = {cloth[s]: p for s, p in books.get(win_id, {}).items() if s in cloth}
            place = {cloth[s]: p for s, p in books.get(place_id, {}).items() if s in cloth}
            if win or place:
                out[number] = RacePrices(
                    win, place, win_id, place_id, {c: s for s, c in cloth.items()}
                )
        return out

    # -- betting (needs the live app key: the delayed key is refused) --------------------------
    def place(
        self, market_id: str, selection_id: int, price: float, stake: float, ref: str, strategy: str
    ) -> Order:
        """Back one runner at ``price`` or better. The bet lapses if not matched by the jump.
        ``ref`` makes a retry within Betfair's window a no-op instead of a second bet."""
        self._session()
        result = (
            self._betting(
                "placeOrders",
                {
                    "marketId": market_id,
                    "customerRef": ref[:32],
                    "customerStrategyRef": strategy[:15],
                    "instructions": [
                        {
                            "selectionId": selection_id,
                            "handicap": 0,
                            "side": "BACK",
                            "orderType": "LIMIT",
                            "limitOrder": {
                                "size": round(stake, 2),
                                "price": price,
                                "persistenceType": "LAPSE",
                            },
                        }
                    ],
                },
            )
            or {}
        )
        reports = result.get("instructionReports") or [{}]
        rep = reports[0]
        if result.get("status") != "SUCCESS":
            code = (
                rep.get("errorCode") or result.get("errorCode") or result.get("status") or "FAILED"
            )
            return Order(str(code))
        return Order(
            "SUCCESS",
            rep.get("betId"),
            float(rep.get("sizeMatched") or 0.0),
            rep.get("averagePriceMatched"),
        )

    def staked_today(self, day: date, strategy: str) -> float:
        """Dollars staked today under ``strategy``: open bets plus bets already settled."""
        self._session()
        start = datetime.combine(day, time(0), MELBOURNE).astimezone(UTC)
        span = {"from": _iso(start), "to": _iso(start + timedelta(days=1))}
        current = (
            self._betting(
                "listCurrentOrders",
                {"customerStrategyRefs": [strategy], "dateRange": span, "orderProjection": "ALL"},
            )
            or {}
        )
        total = sum(
            float(o.get("sizeMatched") or 0) + float(o.get("sizeRemaining") or 0)
            for o in current.get("currentOrders", [])
        )
        cleared = (
            self._betting(
                "listClearedOrders",
                {
                    "betStatus": "SETTLED",
                    "customerStrategyRefs": [strategy],
                    "settledDateRange": span,
                },
            )
            or {}
        )
        total += sum(float(o.get("sizeSettled") or 0) for o in cleared.get("clearedOrders", []))
        return total


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


RACE_NO = re.compile(r"^R(\d+)\b")
CLOTH = re.compile(r"^(\d+)\.")


def _cloth(runner: dict) -> int | None:
    meta = runner.get("metadata") or {}
    for raw in (
        meta.get("CLOTH_NUMBER"),
        (CLOTH.match(runner.get("runnerName", "")) or [None, None])[1],
    ):
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return None


def match_markets(markets: list[dict]) -> dict[int, tuple[str, str | None, dict[int, int]]]:
    """Race number -> (win market id, place market id or None, selection id -> saddlecloth).

    The win market's name starts with the race number ("R7 3200m Hcap"); the place market
    ("To Be Placed") is the PLACE market that starts at the same time."""
    wins: dict[int, dict] = {}
    places: dict[str, dict] = {}
    for m in markets:
        kind = (m.get("description") or {}).get("marketType")
        if kind == "WIN" and (hit := RACE_NO.match(m.get("marketName", ""))):
            wins[int(hit.group(1))] = m
        elif kind == "PLACE":
            places[m.get("marketStartTime", "")] = m
    out = {}
    for number, w in wins.items():
        cloth = {r["selectionId"]: c for r in w.get("runners", []) if (c := _cloth(r)) is not None}
        place = places.get(w.get("marketStartTime", ""))
        out[number] = (w["marketId"], place["marketId"] if place else None, cloth)
    return out


def back_prices(book: dict) -> dict[int, float]:
    """Selection id -> best back price, for runners still running."""
    out = {}
    for r in book.get("runners", []):
        if r.get("status", "ACTIVE") != "ACTIVE":
            continue
        backs = (r.get("ex") or {}).get("availableToBack") or []
        if backs and backs[0].get("price"):
            out[r["selectionId"]] = float(backs[0]["price"])
    return out
