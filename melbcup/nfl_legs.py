"""NFL legs under the NBA picker's "pk1" rules (owner, 2026-11-08: NFL gets the full NBA treatment).

Catalogue rows (PointsBet, market-only: there is no NFL player model) become the same leg dicts
nba_legs builds, then go through nba_legs itself: event-aware bet_key, margin removed only inside a
native over/under pair, alternate "N+" rungs priced by the margin table, identical bets
deduplicated, ladders made monotone, OVER_SHADE. Nothing here re-implements those rules.
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime

from . import nba_legs as N

# catalogue market_family -> (stat id, words shown on a leg)
FAMILY = {
    "player_passing_yards": ("passingYards", "Passing Yards"),
    "player_rushing_yards": ("rushingYards", "Rushing Yards"),
    "player_receiving_yards": ("receivingYards", "Receiving Yards"),
    "player_rushing_receiving_yards": ("scrimmageYards", "Rushing + Receiving Yards"),
    "player_receptions": ("receptions", "Receptions"),
    "player_passing_tds": ("passingTouchdowns", "Passing TDs"),
    "player_rushing_tds": ("rushingTouchdowns", "Rushing TDs"),
    "player_receiving_tds": ("receivingTouchdowns", "Receiving TDs"),
    "player_pass_completions": ("completions", "Completions"),
    "player_interceptions": ("interceptions", "Interceptions"),
    "player_td_scorer": ("touchdowns", "Touchdowns"),  # anytime / N+ only
}
STAT_WORD = {s: w for s, w in FAMILY.values()}
SHORT = {s: s for s in STAT_WORD}  # ranker.is_player_leg: the stats this sport prices
YARDS = {"passingYards", "rushingYards", "receivingYards", "scrimmageYards"}
_TD_RUNG = re.compile(r"to score (\d+)\+ touchdowns", re.I)


def _line_k(r: dict) -> tuple[int, bool] | None:
    """(k, under): Over 245.5 is 246+, Under 245.5 is 245 or fewer; "250+" is already 250+."""
    side = str(r.get("side") or "").lower()
    ln = r.get("line_numeric")
    if r.get("market_family") == "player_td_scorer":
        name = str(r.get("market_name_raw") or "")
        if re.search(r"first|last|team", name, re.I):
            return None  # not a count of the game's touchdowns
        hit = _TD_RUNG.search(name)
        if hit:
            return int(hit[1]), False
        return (1, False) if re.search(r"anytime", name, re.I) and side in ("yes", "over") else None
    if ln is None or side not in ("over", "under"):
        return None
    return int(ln) + 1, side == "under"


def leg_of_row(r: dict) -> dict | None:
    """One pk1 leg from a catalogue row, or None (not a player count we settle)."""
    fam = FAMILY.get(r.get("market_family") or "")
    price = r.get("price_decimal")
    if not fam or not price or price <= 1.0 or r.get("suspended") or not r.get("participant_name"):
        return None
    name = str(r.get("market_name_raw") or "")
    if re.search(r"1st|first|2nd|second|half|3rd|4th|quarter\b", name.replace("Quarterback", ""), re.I) and not re.search(
        r"anytime|to score", name, re.I
    ):
        return None  # a period bet is another predicate: full game only
    kk = _line_k(r)
    if kk is None:
        return None
    k, under = kk
    stat, word = fam
    who = r["participant_name"]
    alt = r.get("market_subtype") in ("alternate", "yes_no", "yes")
    if stat == "touchdowns":
        label = f"{who} Anytime Touchdown" if k == 1 else f"{who} {k}+ Touchdowns"
    elif alt:
        label = f"{who} {k}+ {word}"
    else:
        label = f"{who} {'Under' if under else 'Over'} {r.get('line_raw') or r['line_numeric']} {word}"
    c = min(1 / float(price) / N.OVERROUND, 0.999)
    return {
        "game": r.get("event_name") or r.get("_ev") or str(r.get("event_id")),
        "event": str(r.get("event_id")),
        "startsAt": r.get("event_start_utc"),
        "player": who,
        "team": "",
        "stat": stat,
        "line": k,
        "under": under,
        "src": "alt" if alt else "ou",
        "period": "full",
        "label": label,
        "price": float(price),
        "model": None,
        "market": None,
        "chance": round(c, 4),
        "fair": round(1 / c, 2),
        "ev": round(c * float(price) - 1, 4),
        "seen": r.get("quote_observed_at_utc"),
        "sport": "nfl",
    }


def legs_from_rows(rows) -> list[dict]:
    """pk1 legs: the market chance of each bet across the feed (native pairs de-vigged, rungs by
    the margin table, ladders monotone), over/under lean applied. Dedupe is left to _auto/dedupe."""
    legs = [g for g in map(leg_of_row, rows) if g]
    N.apply_market(legs, N.market_probs({"pb": legs}))
    return legs


def auto(legs: list[dict]) -> list[dict]:
    """The legs automatic picks may use: one per bet, none whose ladder conflicts."""
    return N._auto(legs)


# ---- the sport's current legs (cached): what the SGM tab and the challenge read -----------------

_TTL_S = 120
_cache: dict = {"at": 0.0, "legs": []}


def current_legs(now: datetime | None = None, horizon_h: int = 72) -> list[dict]:
    """Upcoming, not-yet-started pk1 legs from the NFL catalogue. Cached two minutes."""
    if time.monotonic() - _cache["at"] < _TTL_S and _cache["legs"]:
        return _cache["legs"]
    from . import catalogue_view as cv

    now = now or datetime.now(UTC)
    rows = []
    for key, comp in cv._units("nfl"):
        if comp.get("shard"):
            rows += [r for r in cv._shard(key, comp) if r.get("is_player_prop")]
    legs = [
        g
        for g in legs_from_rows(rows)
        if g["startsAt"] and now.isoformat() < str(g["startsAt"]).replace("Z", "+00:00")
    ]
    _cache.update(at=time.monotonic(), legs=legs)
    return legs


def same_game(legs: list[dict], target: float, stake: float = 10.0) -> list[dict]:
    """The likeliest one-game multi (one leg per player) paying `target`x or more, per game.
    Legs are treated as independent (no NFL correlation model): an approximation, flagged."""
    return [m | {"independent": True} for m in N.same_game_for(legs, target, stake)]


def cross_game(legs: list[dict], target: float, stake: float = 10.0) -> dict | None:
    """The likeliest one-leg-per-game multi paying `target`x or more."""
    return N.stack_for(legs, target, stake)
