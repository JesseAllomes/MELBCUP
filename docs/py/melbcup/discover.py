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
import re
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
PER_EVENT = 10  # legs kept per game (least margin first)
MAX_EVENTS = 150  # games kept for the search (speed: 18 s on the full catalogue)
BIN = 0.01  # log-price resolution of the search
REFRESH_S = 600

_lock = threading.Lock()
_state: dict = {"at": 0.0, "result": None, "busy": False, "progress": 0.0, "started": 0.0}


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


def _frontier(legs: list[dict]) -> list[dict]:
    """One game's legs worth searching: a leg is dropped only for another at the same price with
    at least its chance (independent review, 2026-11-07: dropping a cheaper leg for a dearer,
    likelier one breaks a range's upper limit). The PER_EVENT legs with least margin are kept."""
    best: dict[float, dict] = {}
    for g in legs:
        k = round(g["price"], 3)
        if k not in best or g["p"] > best[k]["p"]:
            best[k] = g
    keep = sorted(best.values(), key=value_at_price, reverse=True)
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


STATES_PER_BIN = 3


def _keep(states: list, cand: tuple) -> list:
    """The states worth keeping in one (legs, price bin): those no other state beats on chance at
    a price at least as low (they serve a range's upper limit) or at a price at least as high (they
    serve its lower limit). Exact within a bin up to STATES_PER_BIN; tested against brute force."""
    pool_ = states + [cand]

    def front(desc: bool) -> list:
        out, best = [], -math.inf
        for st in sorted(pool_, key=lambda s: s[1], reverse=desc):
            if st[0] > best:
                out.append(st)
                best = st[0]
        return out

    keep: list = []
    for st in front(False) + front(True):
        if not any(st is o for o in keep):
            keep.append(st)
    if len(keep) > STATES_PER_BIN:
        keep.sort(key=lambda s: s[0], reverse=True)
        keep = keep[:STATES_PER_BIN]
    return keep


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
    legs = [dict(g, cut=1 - g["p"] * g["price"]) for g in legs]  # margin each leg carries
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
            "cut": 1 - p_all * price,  # share of each dollar the book keeps on this multi
            "sports": sorted({g["sport"] for g in legs}),
            "first_start": legs[0]["start"],
            "last_start": legs[-1]["start"],
        },
    }


def _progress(v: float) -> None:
    with _lock:
        _state["progress"] = round(min(max(v, 0.0), 1.0), 3)


def _shared(bands: list[dict]) -> list[dict]:
    """Games that feed two or more of the picks: {event, n, of}, most-used first."""
    picks = [b["pick"] for b in bands if b.get("pick")]
    seen: dict[str, dict] = {}
    for pk in picks:
        for ev in {g["event_id"]: g for g in pk["legs"]}.values():
            row = seen.setdefault(ev["event_id"], {"event": ev["event"], "n": 0, "of": len(picks)})
            row["n"] += 1
    return sorted((r for r in seen.values() if r["n"] >= 2), key=lambda r: -r["n"])


def compute(now: datetime | None = None) -> dict:
    """Read every sport's catalogue one shard at a time (memory stays bounded) and search."""
    from melbcup import catalogue_view as cv

    now = now or datetime.now(UTC)
    t0 = time.monotonic()
    _progress(0.0)
    legs, sports, rows = [], [], 0
    units = sorted(cv.coverage())
    for i, sport in enumerate(units):
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
        _progress(0.5 * (i + 1) / max(len(units), 1))
    groups = pool(legs)
    by_legs: dict[str, list] = {}
    for g in legs:
        by_legs.setdefault(g["sport"], []).append(g)
    by_sport: dict[str, list] = {}
    for j, sport in enumerate(sorted(by_legs)):
        by_sport[sport] = best_multis(pool(by_legs[sport]))
        _progress(0.5 + 0.4 * (j + 1) / max(len(by_legs), 1))
    bands = best_multis(groups)
    _progress(0.95)
    return {
        "built": now.isoformat(),
        "rows_scanned": rows,
        "legs_usable": len(legs),
        "games": len(groups),
        "sports": sports,
        "bands": bands,
        "by_sport": by_sport,
        "shared": _shared(bands),
        "seconds": round(time.monotonic() - t0, 1),
    }


def _refresh() -> None:
    with _lock:
        _state.update(started=time.time(), progress=0.0)
    try:
        res = compute()
        with _lock:
            _state.update(at=time.monotonic(), result=res)
    except Exception:  # noqa: BLE001 - the page keeps the last good result
        log.warning("discover: compute failed", exc_info=True)
    finally:
        with _lock:
            _state.update(busy=False, progress=1.0)


def status() -> dict:
    """Progress of the running search and the age of the last result; never raises."""
    try:
        with _lock:
            res, busy, prog, at = _state["result"], _state["busy"], _state["progress"], _state["at"]
        return {
            "busy": bool(busy),
            "progress": float(prog),
            "built": res.get("built") if res else None,
            "age_s": round(time.monotonic() - at) if res else None,
        }
    except Exception:  # noqa: BLE001 - the status strip must never break the page
        return {"busy": False, "progress": 0.0, "built": None, "age_s": None}


def refresh_now() -> bool:
    """Start a refresh now unless one is running. True when one was started."""
    try:
        with _lock:
            if _state["busy"]:
                return False
            _state["busy"] = True
        threading.Thread(target=_refresh, daemon=True, name="discover").start()
        return True
    except Exception:  # noqa: BLE001
        log.warning("discover: refresh_now failed", exc_info=True)
        return False


def eta(start: str | None, now: datetime | None = None) -> str:
    """ "in 5h 00m" until an ISO start, "" when unknown or past."""
    t = _when(start)
    if t is None:
        return ""
    secs = int((t - (now or datetime.now(UTC))).total_seconds())
    if secs <= 0:
        return ""
    h, m = divmod(secs // 60, 60)
    return f"in {h}h {m:02d}m" if h else f"in {m}m"


def layout(bands: list[dict] | None, now: datetime | None = None) -> dict:
    """The Bet now page from a list of band summaries: the two likeliest picks, the others
    grouped by first kick-off, and the games that feed two or more picks."""
    now = now or datetime.now(UTC)
    have = [dict(b, eta=eta(b["pick"]["first_start"], now)) for b in bands or [] if b.get("pick")]
    have.sort(key=lambda b: -b["pick"]["p_all"])
    top, rest = have[:2], have[2:]
    rest.sort(key=lambda b: b["pick"]["first_start"] or "")
    groups: list[dict] = []
    for b in rest:
        key = b["pick"]["first_start"]
        if groups and groups[-1]["start"] == key:
            groups[-1]["items"].append(b)
        else:
            groups.append({"start": key, "eta": b["eta"], "items": [b]})
    return {
        "top": top,
        "groups": groups,
        "shared": _shared(have),
        "none": not have,
        "age_s": status()["age_s"],
    }


MAIN_FAMILIES = ("total", "totals", "line", "spread", "handicap", "h2h")


# a game's main line is a full-game market, never an alternate, pick-your-own, half, quarter or
# period line (those can sit nearer 50/50 by chance)
_NOT_MAIN = re.compile(
    r"alt|pick your own|half|quarter|period|1st|2nd|3rd|4th|team total|touchdown|race to|margin",
    re.I,
)


def next_games(sport: str, n: int = 8, now: datetime | None = None) -> list[dict]:
    """The next n games of a sport by start: each with its main line (the total, line or
    head-to-head leg closest to 50/50) and how many player props it has. Reads only the
    competition shards those games sit in. Never raises."""
    from melbcup import catalogue_view as cv

    now = now or datetime.now(UTC)
    try:
        evs = [
            e
            for k in cv.GROUPS.get(sport) or (sport,)
            for e in ((cv._index(k) or {}).get("events") or [])
            if (_when(e.get("starts_at")) or now) > now
        ]
        evs.sort(key=lambda e: e.get("starts_at") or "~")
        evs = evs[:n]
        units = {(c["competition_id"]): (k, c) for k, c in cv._units(sport)}
        shards: dict[str, list[dict]] = {}
        out = []
        for e in evs:
            cid = e.get("competition_id") or ""
            unit = units.get(cid) or units.get("")
            rows: list[dict] = []
            if unit and unit[1].get("shard"):
                key = f"{unit[0]}:{unit[1]['shard']}"
                if key not in shards:
                    shards[key] = cv._shard(*unit)
                rows = [r for r in shards[key] if str(r.get("event_id")) == str(e["event_id"])]
            props = sum(1 for r in rows if r.get("is_player_prop"))
            main = [
                r
                for r in rows
                if not r.get("is_player_prop")
                and r.get("market_prob") is not None
                and r.get("price_decimal")
                and (r.get("market_family") or r.get("market_type")) in MAIN_FAMILIES
                and (r.get("period") in (None, "", "full_game"))
                and not _NOT_MAIN.search(str(r.get("market_name_raw") or ""))
            ]
            m = min(main, key=lambda r: abs(r["market_prob"] - 0.5), default=None)
            out.append(
                {
                    "id": e["event_id"],
                    "name": e.get("event_name") or str(e["event_id"]),
                    "start": e.get("starts_at"),
                    "comp": e.get("competition"),
                    "props": props,
                    "main": None
                    if m is None
                    else {
                        "label": " ".join(
                            str(x)
                            for x in (
                                m.get("participant_name"),
                                m.get("market_name_raw"),
                                m.get("line_raw"),
                                m.get("side"),
                            )
                            if x not in (None, "")
                        ),
                        "p": float(m["market_prob"]),
                        "price": float(m["price_decimal"]),
                    },
                }
            )
        return out
    except Exception:  # noqa: BLE001 - the page shows no games rather than failing
        log.warning("discover: next_games failed", exc_info=True)
        return []


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
