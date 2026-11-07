"""Tonight's Sportsbet board for the sport pages.

Same Sportsbook host the NBA page already calls. One book, the main markets
only, and a multi of one leg per game. The chance is the book's price with
the margin taken out. It is not a counted hit rate, and it does not replace
the football scan.

No fixture and no percent is invented. A competition with nothing up comes
back empty.
"""

from __future__ import annotations

import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from itertools import combinations, product
from zoneinfo import ZoneInfo

SB = "https://www.sportsbet.com.au/apigw/sportsbook-sports/Sportsbook/Sports"
_MEL = ZoneInfo("Australia/Melbourne")
_TTL = 75.0
_MAX_GAMES = 12
_MAX_LEGS = 8
_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, dict]] = {}

# Internal competition ids (NavHierarchy). Tennis is discovered: those ids
# change with the tournament.
COMPS = {
    "football": ("718", "2915", "1015", "1029", "876", "739"),
    "afl": ("4165",),
    "nrl": ("3436", "28801"),
    "nhl": ("29408",),
    "nfl": ("3073",),
}
# Exact market names, compared case-insensitively. Anything else (player
# ladders, quarters, alternate handicaps) stays off the phone.
SHOW = {
    "football": (
        "win-draw-win",
        "draw no bet",
        "both teams to score",
        "double chance",
        "half-time result",
        "over/under 0.5 goals",
        "over/under 1.5 goals",
        "over/under 2.5 goals",
        "over/under 3.5 goals",
        "handicap betting",
    ),
    "afl": ("head to head", "match betting", "win-draw-win", "line", "handicap", "total points"),
    "nrl": ("head to head", "match betting", "win-draw-win", "line", "handicap", "total points"),
    "nhl": ("moneyline", "puckline", "total goals", "60 min moneyline 3 way"),
    "nfl": ("match betting", "handicap", "total match points"),
    "tennis": ("match betting", "total sets", "match total games", "set betting"),
}
WINNER = {
    "football": "win-draw-win",
    "afl": "head to head",
    "nrl": "head to head",
    "nhl": "moneyline",
    "nfl": "match betting",
    "tennis": "match betting",
}
_FALLBACK = ("head to head", "match betting", "moneyline", "win-draw-win")
_NOTE = "Prices are Sportsbet. Each chance is that price with the margin taken out."
_EDGE = (
    "One leg per game, the highest chance whose prices still multiply to $2 or more. "
    "A tie goes to fewer legs. Each chance is Sportsbet's price with the margin taken out. "
    "It is not a counted hit rate."
)


def _tone(chance: float) -> str:
    pct = round(100 * chance)
    return "good" if pct >= 60 else "mid" if pct >= 30 else "low"


def _blank(empty: str | None = None, error: str | None = None) -> dict:
    return {
        "games": [],
        "singles": [],
        "ticket": None,
        "empty": empty,
        "note": _NOTE,
        "error": error,
    }


def devig(selections: list[dict]) -> None:
    """Share of the market after the overround is removed. Writes `chance`."""
    implied = [1 / row["price"] for row in selections if row["price"] > 1]
    total = sum(implied)
    for row in selections:
        row["chance"] = (1 / row["price"]) / total if total and row["price"] > 1 else 0.0
        row["pct"] = round(100 * row["chance"])
        row["tone"] = _tone(row["chance"])


def selection_label(selection: dict) -> str:
    """Selection name, with the line attached when the book left it off the name."""
    name = (selection.get("name") or "").strip()
    line = selection.get("unformattedHandicap")
    if isinstance(line, (int, float)) and not any(ch.isdigit() for ch in name):
        return f"{name} {line:g}"
    return name


def keep_markets(raw: list | None, sport: str) -> list[dict]:
    """Main markets for one event. Duplicate names keep the line closest to even."""
    allowed = set(SHOW.get(sport, ()))
    grouped: dict[str, list[dict]] = {}
    for market in raw or []:
        if market.get("statusCode", "A") != "A":
            continue
        name = (market.get("name") or "").strip()
        if "do not use" in name.casefold() or name.casefold() not in allowed:
            continue
        rows = []
        for selection in market.get("selections") or []:
            if selection.get("statusCode", "A") != "A":
                continue
            price = (selection.get("price") or {}).get("winPrice")
            if not price or price <= 1:
                continue
            rows.append({"name": selection_label(selection), "price": float(price)})
        if not 2 <= len(rows) <= 4:
            continue
        devig(rows)
        grouped.setdefault(name.casefold(), []).append({"name": name, "selections": rows})
    order = {name: index for index, name in enumerate(SHOW.get(sport, ()))}
    kept = []
    for key, markets in grouped.items():
        markets.sort(key=lambda row: sum(abs(s["price"] - 1.91) for s in row["selections"]))
        kept.append(markets[0] | {"key": key})
    kept.sort(key=lambda row: order.get(row["key"], 99))
    return kept


def winner_of(markets: list[dict], sport: str) -> tuple[str, list[dict]]:
    """The match-result market. One selection from it can enter the multi."""
    by = {market["key"]: market for market in markets}
    preferred = WINNER.get(sport, "")
    if preferred in by:
        market = by[preferred]
        return market["name"], market["selections"]
    for key in _FALLBACK:
        if key in by:
            market = by[key]
            return market["name"], market["selections"]
    return "", []


def best_ticket(games: list[dict], minimum: float = 2.0) -> dict | None:
    """Highest chance at `minimum` or better. One winner-market leg per game.

    Fewer legs wins when two tickets have the same chance. A game with no
    result price is left out. None when nothing reaches `minimum`.
    """
    usable = [game for game in games if game.get("winner")]
    found = None
    rank = None
    limit = min(_MAX_LEGS, len(usable))
    for count in range(1, limit + 1):
        for group in combinations(usable, count):
            pools = [game["winner"] for game in group]
            for pick in product(*pools):
                price = 1.0
                chance = 1.0
                for leg in pick:
                    price *= leg["price"]
                    chance *= leg["chance"]
                if price + 1e-9 < minimum:
                    continue
                key = (chance, -count, price)
                if rank is not None and key <= rank:
                    continue
                rank = key
                found = (group, pick, price, chance, count)
    if found is None:
        return None
    group, pick, price, chance, count = found
    legs = []
    for game, leg in zip(group, pick, strict=True):
        legs.append(
            {
                "game": game["name"],
                "market": game.get("winner_market") or "",
                "name": leg["name"],
                "price": leg["price"],
                "chance": leg["chance"],
                "pct": leg["pct"],
                "tone": leg["tone"],
            }
        )
    return {
        "legs": legs,
        "count": count,
        "multi": price,
        "chance": chance,
        "pct": round(100 * chance),
        "tone": _tone(chance),
        "line": " · ".join(f"{leg['name']} ${leg['price']:.2f}" for leg in legs),
        "edge": _EDGE,
    }


def _get(url: str):
    from melbcup.nba_legs import get

    try:
        return get(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _when(start) -> str:
    if not isinstance(start, (int, float)):
        return ""
    moment = datetime.fromtimestamp(start, _MEL)
    clock = moment.strftime("%I:%M%p").lstrip("0").lower()
    return f"{moment.strftime('%a')} {moment.day} {moment.strftime('%b')}, {clock}"


def _comp_events(comp_id: str) -> list[dict]:
    data = _get(
        f"{SB}/Competitions/{comp_id}?displayType=default&includeTopMarkets=false&eventFilter=matches"
    )
    if not data:
        return []
    now = time.time()
    comp = data.get("name") or ""
    rows = []
    for event in data.get("events") or []:
        if event.get("bettingStatus") not in (None, "PRICED"):
            continue
        start = event.get("startTime")
        if isinstance(start, (int, float)) and start < now - 120:
            continue
        name = (event.get("name") or "").replace(" At ", " v ")
        rows.append(
            {
                "id": str(event["id"]),
                "name": name,
                "comp": comp,
                "start": start if isinstance(start, (int, float)) else 0,
                "when": _when(start),
            }
        )
    return rows


def _tennis_ids() -> tuple[str, ...]:
    """Current tour events. Grand-slam and doubles nodes are futures pages."""
    nav = _get(f"{SB}/NavHierarchy") or {}
    ids = []
    for item in nav.get("navItems") or []:
        if item.get("id") != 13:
            continue
        for child in item.get("navItems") or []:
            if child.get("idType") != "competition":
                continue
            name = (child.get("name") or "").casefold()
            if any(word in name for word in ("double", "future", "open", "davis", "united cup")):
                continue
            ids.append(str(child["id"]))
            if len(ids) >= 4:
                return tuple(ids)
    return tuple(ids)


def _event_markets(event_id: str):
    try:
        data = _get(f"{SB}/Events/{event_id}/Markets")
    except (urllib.error.URLError, TimeoutError, OSError):
        return []
    return data if isinstance(data, list) else []


def _build(sport: str) -> dict:
    names = {
        "football": "Football",
        "afl": "AFL",
        "nrl": "NRL",
        "nhl": "NHL",
        "nfl": "NFL",
        "tennis": "Tennis",
    }
    title = names.get(sport, "This sport")
    ids = _tennis_ids() if sport == "tennis" else COMPS.get(sport, ())
    if not ids:
        return _blank(f"{title} has no matches up at Sportsbet.")
    with ThreadPoolExecutor(max_workers=6) as pool:
        batches = list(pool.map(_comp_events, ids))
    events = [event for batch in batches for event in batch]
    events.sort(key=lambda event: event["start"] or 0)
    events = events[:_MAX_GAMES]
    if not events:
        return _blank(f"{title} has no matches up at Sportsbet.")
    with ThreadPoolExecutor(max_workers=8) as pool:
        boards = list(pool.map(_event_markets, [event["id"] for event in events]))
    games = []
    for event, raw in zip(events, boards, strict=True):
        markets = keep_markets(raw, sport)
        if not markets:
            continue
        winner_market, winner = winner_of(markets, sport)
        games.append(
            {
                "id": event["id"],
                "name": event["name"],
                "comp": event["comp"],
                "when": event["when"],
                "markets": markets,
                "winner": winner,
                "winner_market": winner_market,
            }
        )
    if not games:
        return _blank(f"{title} matches are up, and the main markets are not priced yet.")
    singles = []
    for game in games:
        for market in game["markets"]:
            for selection in market["selections"]:
                singles.append(
                    {
                        "game": game["name"],
                        "when": game["when"],
                        "market": market["name"],
                        "name": selection["name"],
                        "price": selection["price"],
                        "chance": selection["chance"],
                        "pct": selection["pct"],
                        "tone": selection["tone"],
                    }
                )
    singles.sort(key=lambda row: -row["chance"])
    return {
        "games": games,
        "singles": singles[:48],
        "ticket": best_ticket(games),
        "empty": None,
        "note": _NOTE,
        "error": None,
    }


def card(sport: str) -> dict:
    """One sport's board, reused for about a minute so the page does not refetch."""
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(sport)
        if hit and now - hit[0] < _TTL:
            return hit[1]
    try:
        built = _build(sport)
    except (urllib.error.URLError, TimeoutError, OSError):
        built = _blank(error="Sportsbet did not answer.")
    with _LOCK:
        _CACHE[sport] = (time.monotonic(), built)
    return built
