"""NFL legs under the NBA picker's "pk1" rules (owner, 2026-11-08: NFL gets the full NBA treatment).

Catalogue rows (PointsBet; the NFL player model of melbcup/nfl_model.py is blended in at a small weight) become the same leg dicts
nba_legs builds, then go through nba_legs itself: event-aware bet_key, margin removed only inside a
native over/under pair, alternate "N+" rungs priced by the margin table, identical bets
deduplicated, ladders made monotone, OVER_SHADE. Nothing here re-implements those rules.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import UTC, datetime

from . import nba_legs as N
from . import nfl_model as M

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


GAME_FAMILIES = ("line", "total")  # no head-to-head: owner policy, it wins less often than priced
_PERIOD_WORDS = re.compile(r"1st|first|2nd|second|half|3rd|4th|quarter|\bq[1-4]\b", re.I)


def game_leg_of_row(r: dict) -> dict | None:
    """A full-game h2h / point spread / total leg from a catalogue row, or None. The game's two
    sides share one slot so bet_key / _pair_id pair them natively: win and spread use player
    "Game winner" / "Game spread" with line = the AWAY team's handicap (0 for the win) and
    under = "the away team"; a total is "Game total" at its line with the usual under flag."""
    fam = r.get("market_family")
    price = r.get("price_decimal")
    if fam not in GAME_FAMILIES or r.get("is_player_prop") or not price or price <= 1.0 or r.get("suspended"):
        return None
    if (r.get("period") or "full_game") != "full_game" or _PERIOD_WORDS.search(str(r.get("market_name_raw") or "")):
        return None
    mkt = str(r.get("market_name_raw") or "")
    if fam == "h2h" and mkt.strip().lower() != "moneyline":  # two-way only: no 3-way (tie) or drive markets
        return None
    game = r.get("event_name") or str(r.get("event_id"))
    side, ln = str(r.get("side") or "").lower(), r.get("line_numeric")
    if fam == "total":
        if side not in ("over", "under") or ln is None or not 20 <= float(ln) <= 80:
            return None  # a full-game points total only (owner, 2026-11-09: an "Over 3.5" slipped in)
        stat, player, line, under = "total", "Game total", float(ln), side == "under"
        label = f"{'Under' if under else 'Over'} {r.get('line_raw') or ln} Total Points"
    else:
        if side not in ("home", "away"):
            return None
        team = (r.get("participant_name") or "").strip()
        if not team:
            return None
        away = side == "away"
        if fam == "h2h":
            stat, player, line = "win", "Game winner", 0.0
            label = f"{team} to win"
        else:
            if ln is None or abs(float(ln)) > 30:
                return None
            stat, player = "spread", "Game spread"
            line = float(ln) if away else -float(ln)
            label = f"{team} {float(ln):+g}"
        under = away
    c = min(1 / float(price) / N.OVERROUND, 0.999)
    return {
        "game": game, "event": str(r.get("event_id")), "startsAt": r.get("event_start_utc"),
        "player": player, "team": "", "stat": stat, "line": line, "under": under, "src": "ou",
        "period": "full", "label": label, "price": float(price), "model": None, "market": None,
        "chance": round(c, 4), "fair": round(1 / c, 2), "ev": round(c * float(price) - 1, 4),
        "seen": r.get("quote_observed_at_utc"), "sport": "nfl", "gameline": True, "mkt": mkt,
    }


def legs_from_rows(rows) -> list[dict]:
    """pk1 legs: the market chance of each bet across the feed (native pairs de-vigged, rungs by
    the margin table, ladders monotone), over/under lean applied. Dedupe is left to _auto/dedupe."""
    props = [g for g in map(leg_of_row, rows) if g]
    M.annotate(props)  # model chance + team where the player has a mean; blended below at M.BLEND_W
    N.apply_market(props, N.market_probs({"pb": props}), M.BLEND_W)
    return props + game_lines(rows)


def game_lines(rows) -> list[dict]:
    """Full-game win / spread / total legs, each priced only from its own two-way market: the two
    sides at the same line in the same game, margin removed in proportion (owner, 2026-11-09: the
    prop pairing gave a $2.20 win 85%). A side without its opposite is left out, never guessed."""
    pairs: dict = {}
    for g in map(game_leg_of_row, rows):
        if g:
            key = (g["event"], g["mkt"], g["stat"], round(g["line"], 2))
            pairs.setdefault(key, {})[g["under"]] = g  # one leg per side (the last quote wins)
    out = []
    for sides in pairs.values():
        if len(sides) != 2:
            continue
        book = sum(1 / s["price"] for s in sides.values())
        if not 1.0 <= book <= 1.25:  # not a real two-way market (or a stale side): skip it
            continue
        for s in sides.values():
            c = (1 / s["price"]) / book
            s.update(chance=round(c, 4), raw=round(c, 4), fair=round(1 / c, 2), ev=round(c * s["price"] - 1, 4))
            out.append(s)
    return out


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
            rows += [
                r for r in cv._shard(key, comp)
                if r.get("is_player_prop") or r.get("market_family") in GAME_FAMILIES
            ]
    legs = [
        g
        for g in legs_from_rows(rows)
        if g["startsAt"] and now.isoformat() < str(g["startsAt"]).replace("Z", "+00:00")
    ]
    _cache.update(at=time.monotonic(), legs=legs)
    return legs


def same_game(legs: list[dict], target: float, stake: float = 10.0) -> list[dict]:
    """The likeliest one-game multi (one leg per player) paying `target`x or more, per game.
    Legs are correlated by the fitted NFL relations (melbcup/nfl_model.CORR, a Gaussian copula) when the
    player has a model mean (team known); a leg with no mean is independent of the rest."""
    return [m | {"independent": False} for m in N.same_game_for(legs, target, stake)]


def cross_game(legs: list[dict], target: float, stake: float = 10.0) -> dict | None:
    """The likeliest one-leg-per-game multi paying `target`x or more."""
    return N.stack_for(legs, target, stake)


def _page_view(now: datetime | None = None) -> tuple[dict, dict]:
    """(view, report) in the shape the NBA page reads (nba_feed view / nba_legs.report), built
    from the NFL legs, so /sports?sport=nfl renders the same templates as the NBA tab."""
    now = now or datetime.now(UTC)
    legs = [g | {"expected": None, "minutes": None} for g in current_legs(now)]
    by_event: dict = {}
    for g in legs:
        by_event.setdefault(g["event"], g)
    cross, same = N.stacks(legs, 10.0)
    ok = [g for g in N._auto(legs) if g["chance"] >= 0.75 and g["ev"] >= 0.03]
    rep = {
        "stacks": cross,
        "stacks_same": [m | {"independent": True} for m in same],
        "by_game": N.by_game(legs),
        "day": now.date().isoformat(),
        "min_chance": 0.75,
        "min_ev": 0.03,
        "stake": 10.0,
        "games_priced": len(by_event),
        "legs_seen": len(legs),
        "value_legs": sorted(ok, key=lambda g: -g["chance"]),
        "all_legs": legs,
    }
    games = [
        {"name": g["game"], "when": g["startsAt"]}
        for g in sorted(by_event.values(), key=lambda g: g["startsAt"] or "")
    ]
    v = {
        "board": {"games": games, "day": rep["day"]} if games else None,
        "source": "",
        "stale": False,
        "games": len(games),
        "priced_at": now,
        "error": None if games else "No NFL lines in the catalogue yet.",
        "agencies": {},
        "report": rep,
    }
    return v, rep


_PV: dict = {"at": 0.0, "val": None, "busy": False}
_PV_TTL_S = 120
_PV_LOCK = threading.Lock()


def _refresh_pv() -> None:
    try:
        val = _page_view()
        with _PV_LOCK:
            _PV.update(at=time.monotonic(), val=val)
    finally:
        _PV["busy"] = False


def page_view(now: datetime | None = None) -> tuple[dict, dict]:
    """The NFL page's (view, report), served from memory (owner, 2026-11-10: NFL took 6-7 s a load
    against NBA's 1 s). Older than two minutes: the last one is served at once and a fresh one is
    worked out behind it. Only the very first load after a start waits. `now` given: computed fresh."""
    if now is not None:
        return _page_view(now)
    if _PV["val"] is None:
        _refresh_pv()
        return _PV["val"]
    if time.monotonic() - _PV["at"] > _PV_TTL_S and not _PV["busy"]:
        _PV["busy"] = True
        threading.Thread(target=_refresh_pv, daemon=True).start()
    return _PV["val"]
