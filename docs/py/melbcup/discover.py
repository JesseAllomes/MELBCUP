"""Best multis across every sport, by odds range (owner, 2026-11-07).

For each odds range the multi with the highest chance that every leg wins, from the whole
PointsBet catalogue (melbcup/catalogue.py), so the multi can be placed at one bookmaker.

Honesty rules (independent review, owner-agreed):
- A leg's chance is the bookmaker's own price with its margin removed, and only where the market
  is a complete two-way pair (market_prob in the catalogue). No model chance, no invented ones.
- At most one leg per game: only NBA has a measured same-game correlation, so mixing games keeps
  the legs independent and the joint chance a plain product.
- NBA head-to-head is left out of automatic picks (owner's policy), still visible elsewhere.
- Stale (older than MAX_AGE_S), suspended, started or far-off legs are not used.
- The price shown is the product of the legs' prices; the bookmaker's accepted multi price can
  differ. Expected return is shown as it is (normally negative): this ranks chance at a price,
  it does not claim value.
- An odds range with nothing that fits says so; it is never padded.

The search is a multiple-choice knapsack over log-price bins (one leg per game, up to MAX_LEGS)
keeping several exact-price states per bin, maximising the sum of log chances; the exact product
is checked against each range. Tests compare it with brute force on small slates.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import UTC, datetime, timedelta

log = logging.getLogger(__name__)

BANDS = ((1.5, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 10.0), (10.0, 20.0))
MAX_LEGS = 6
MIN_LEGS = 2
MAX_AGE_S = 3 * 3600  # a price older than this is not used
HORIZON_H = 48  # games starting within this many hours
MIN_LEAD_S = 5 * 60  # and not about to start
MIN_CHANCE = 0.30  # a leg below this is never worth its place at these ranges
PER_EVENT = 12  # legs kept per game from its price frontier (least margin first)
MAX_EVENTS = 250  # games kept for the search
BIN = 0.01  # log-price resolution of the search
REFRESH_S = 600

_lock = threading.Lock()
_state: dict = {"at": 0.0, "result": None, "busy": False}


def _when(text: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")) if text else None
    except ValueError:
        return None


def leg_of(r: dict, sport: str, now: datetime) -> dict | None:
    """A usable leg from one catalogue row, or None."""
    p, price = r.get("market_prob"), r.get("price_decimal")
    if p is None or not price or price <= 1.01 or r.get("suspended"):
        return None
    if p < MIN_CHANCE or p >= 0.995:
        return None
    if sport == "nba" and (r.get("market_family") or r.get("market_type")) == "h2h":
        return None  # owner's policy: NBA head-to-head stays out of automatic picks
    start, seen = _when(r.get("event_start_utc")), _when(r.get("quote_observed_at_utc"))
    if start is None or seen is None:
        return None
    if not (now + timedelta(seconds=MIN_LEAD_S) < start < now + timedelta(hours=HORIZON_H)):
        return None
    if (now - seen).total_seconds() > MAX_AGE_S:
        return None
    label = " ".join(
        str(x)
        for x in (
            r.get("participant_name"),
            r.get("market_name_raw"),
            r.get("line_raw"),
            r.get("side"),
        )
        if x not in (None, "")
    )
    return {
        "key": r.get("key") or r.get("selection_id"),
        "sport": sport,
        "event_id": str(r.get("event_id")),
        "event": r.get("_ev") or str(r.get("event_id")),
        "start": r.get("event_start_utc"),
        "label": label,
        "price": float(price),
        "p": float(p),
        "seen": r.get("quote_observed_at_utc"),
        "player": bool(r.get("is_player_prop")),
    }


def value_at_price(g: dict) -> float:
    """log(chance x price): 0 for a margin-free leg, more negative the more margin it carries.
    At the same price the higher chance always scores higher (independent review, 2026-11-07:
    an earlier ratio ranked this backwards)."""
    return math.log(g["p"] * g["price"])


LOCAL_DOM = 1.10  # a leg is dropped only for one at most 10% dearer with at least its chance


def _frontier(legs: list[dict]) -> list[dict]:
    """One game's legs that can matter at some target: drop a leg only when another leg priced
    above it, but by no more than LOCAL_DOM, has at least its chance (a dearer, likelier leg is
    better at a lower price limit, and the 10% cap keeps cheaper legs an upper limit may need).
    The PER_EVENT legs with least margin are kept."""
    pts = sorted(legs, key=lambda g: g["price"])
    keep = [
        g
        for i, g in enumerate(pts)
        if not any(
            h["p"] >= g["p"] and g["price"] < h["price"] <= g["price"] * LOCAL_DOM
            for h in pts[i + 1 :]
        )
    ]
    keep.sort(key=value_at_price, reverse=True)
    return keep[:PER_EVENT]


def pool(legs: list[dict]) -> list[list[dict]]:
    """Legs grouped by game (each game's price frontier), the MAX_EVENTS games whose best leg
    carries the least margin."""
    by: dict[str, list[dict]] = {}
    for g in legs:
        by.setdefault(g["event_id"], []).append(g)
    groups = [_frontier(v) for v in by.values()]
    groups = [v for v in groups if v]
    groups.sort(key=lambda v: max(value_at_price(g) for g in v), reverse=True)
    return groups[:MAX_EVENTS]


def _keep(states: list, cand: tuple) -> list:
    """Up to three states per (legs, bin): the best chance, the dearest exact price and the
    cheapest exact price, so a combination just across a range boundary is never lost."""
    pool_ = states + [cand]
    out: list = []
    for s_ in (
        max(pool_, key=lambda s: s[0]),
        max(pool_, key=lambda s: s[1]),
        min(pool_, key=lambda s: s[1]),
    ):
        if not any(s_ is o for o in out):
            out.append(s_)
    return out


def best_multis(groups: list[list[dict]], bands=BANDS) -> list[dict]:
    """For each (lo, hi) odds range: the highest-chance multi whose exact price is in [lo, hi),
    one leg per game, MIN_LEGS to MAX_LEGS legs; or none, with a reason. Searched over log-price
    bins keeping several exact-price states per bin; checked against brute force in the tests."""
    top = math.log(max(hi for _, hi in bands))
    # dp[k][bin] = [(sum log p, exact sum log price, legs), ...]
    dp: list[dict[int, list]] = [{} for _ in range(MAX_LEGS + 1)]
    dp[0][0] = [(0.0, 0.0, ())]
    for group in groups:
        steps = [(g, math.log(g["price"]), math.log(g["p"])) for g in group]
        for k in range(MAX_LEGS - 1, -1, -1):  # downwards: a game adds at most one leg
            nxt = dp[k + 1]
            for states in list(dp[k].values()):
                for lp, lpr, legs in states:
                    for g, dpr, dlp in steps:
                        tot = lpr + dpr
                        if tot > top + BIN:
                            continue
                        b = int(tot / BIN)
                        nxt[b] = _keep(nxt.get(b, []), (lp + dlp, tot, legs + (g,)))
    out = []
    for lo, hi in bands:
        best = None
        for k in range(MIN_LEGS, MAX_LEGS + 1):
            for states in dp[k].values():
                for lp, _lpr, legs in states:
                    price = math.prod(g["price"] for g in legs)
                    if lo <= price < hi and (best is None or lp > best[0]):
                        best = (lp, legs)
        out.append(_summary(lo, hi, best))
    return out


def _summary(lo: float, hi: float, best) -> dict:
    if best is None:
        return {
            "lo": lo,
            "hi": hi,
            "pick": None,
            "reason": "No multi of fresh, fairly priced legs lands in this range right now.",
        }
    legs = sorted(best[1], key=lambda g: g["start"] or "")
    p_all = math.prod(g["p"] for g in legs)
    price = math.prod(g["price"] for g in legs)
    p_one = sum(p_all * (1 - g["p"]) / g["p"] for g in legs)  # independent legs
    return {
        "lo": lo,
        "hi": hi,
        "reason": None,
        "pick": {
            "legs": legs,
            "price": round(price, 2),
            "p_all": p_all,
            "p_one_fail": p_one,
            "fair_price": round(1 / p_all, 2),
            "expected_return": price * p_all - 1,  # per $1 staked, at the product price
            "sports": sorted({g["sport"] for g in legs}),
            "first_start": legs[0]["start"],
            "last_start": legs[-1]["start"],
        },
    }


def compute(now: datetime | None = None) -> dict:
    """Read every sport's catalogue one shard at a time (memory stays bounded) and search."""
    from melbcup import catalogue_view as cv

    now = now or datetime.now(UTC)
    t0 = time.monotonic()
    legs, sports, rows = [], [], 0
    for sport in sorted(cv.coverage()):
        n0 = len(legs)
        for key, comp in cv._units(sport):
            if not comp.get("shard"):
                continue
            for r in cv._shard(key, comp):
                rows += 1
                g = leg_of(r, key, now)
                if g is not None:
                    legs.append(g)
        if len(legs) > n0:
            sports.append(sport)
    groups = pool(legs)
    return {
        "built": now.isoformat(),
        "rows_scanned": rows,
        "legs_usable": len(legs),
        "games": len(groups),
        "sports": sports,
        "bands": best_multis(groups),
        "seconds": round(time.monotonic() - t0, 1),
    }


def _refresh() -> None:
    try:
        res = compute()
        with _lock:
            _state.update(at=time.monotonic(), result=res)
    except Exception:  # noqa: BLE001 - the page keeps the last good result
        log.warning("discover: compute failed", exc_info=True)
    finally:
        with _lock:
            _state["busy"] = False


def latest(wait: bool = False) -> dict | None:
    """The last result; starts a background refresh when it is older than REFRESH_S."""
    with _lock:
        due = time.monotonic() - _state["at"] > REFRESH_S and not _state["busy"]
        if due:
            _state["busy"] = True
    if due:
        if wait:
            _refresh()
        else:
            threading.Thread(target=_refresh, daemon=True, name="discover").start()
    with _lock:
        return _state["result"]
