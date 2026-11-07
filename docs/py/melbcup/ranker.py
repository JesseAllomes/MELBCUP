"""Promotion-aware, honest multi ranker.

Candidates are combinations of priced legs whose product of quoted prices lands in
[target, target x band]. The champion leg chance is the market no-vig chance (leg["chance"], as
nba_legs.apply_market sets it with BLEND_W 0); same-game legs use nba_legs' Gaussian copula.
Every result states its objective. "No qualifying candidate" is a valid result (pick None).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from . import nba_legs as N

OBJ_CHANCE = "Highest calibrated chance at target price"
OBJ_EV = "Risk-adjusted EV"
OBJ_PROMO = "Promo value"
BAND = 1.15  # candidate price in [target, target * BAND]
BEAM = 400
MIN_LEG_CHANCE = 0.35
LEG_SD = 0.03  # default absolute uncertainty of a leg chance (EV objective)
Z = 1.28
MAX_AGE_S = 900  # a quote older than this at decision time is stale -> unverified
RESCORE = 40  # candidates re-scored with the full joint model

_NON_PLAYER = {"h2h", "match", "team", "total", "spread"}


def is_player_leg(g: dict) -> bool:
    """A player prop (points/rebounds/assists/threes). H2H and other team markets are not."""
    return (
        str(g.get("market_type", "player")).lower() not in _NON_PLAYER
        and bool(g.get("player"))
        and g.get("stat") in N.SHORT
    )


def joint(legs: list[dict]) -> float:
    """P(all win): legs in different games are independent, same-game legs use the copula."""
    games: dict = {}
    for g in legs:
        games.setdefault(g.get("game"), []).append(g)
    return math.prod(N.joint_chance(v) if len(v) > 1 else v[0]["chance"] for v in games.values())


def p_exactly_one_fail(legs: list[dict], p_all: float | None = None) -> float:
    """Exactly one leg fails = sum over i of P(all but i win) - P(all win), under the same joint
    model (the one-fail patterns enumerated leg by leg)."""
    p_all = joint(legs) if p_all is None else p_all
    return sum(max(joint(legs[:i] + legs[i + 1 :]) - p_all, 0.0) for i in range(len(legs)))


def quote_status(g, as_of=None, max_age_s=MAX_AGE_S):
    """ "verified" only with a price and (when as_of is given) a quote no older than max_age_s;
    quoted_at is epoch seconds. Anything else is "unverified" and never auto-recommended."""
    if not g.get("price") or g.get("price_verified") is False:
        return "unverified"
    if as_of is not None and (g.get("quoted_at") is None or as_of - g["quoted_at"] > max_age_s):
        return "unverified"
    return "verified"


def _eligible(legs, include_h2h, min_leg_chance, min_leg_price, as_of=None, max_age_s=MAX_AGE_S):
    out = []
    for g in legs:
        if quote_status(g, as_of, max_age_s) != "verified":
            continue
        if g["price"] < min_leg_price or g["chance"] < min_leg_chance:
            continue
        if not include_h2h and not is_player_leg(g):
            continue
        out.append(g)
    return out


def _compatible(stack, g):
    return all(
        not (h.get("player") == g.get("player") and h.get("stat") == g.get("stat")) for h in stack
    )


def candidates(legs, target, band=BAND, min_legs=2, max_legs=6, beam=BEAM) -> list[list[dict]]:
    """Beam search by chance per log-price; stack prices land in [target, target*band]."""
    lo, hi = math.log(target), math.log(target * band)
    pool = sorted(legs, key=lambda g: math.log(g["chance"]) / math.log(g["price"]), reverse=True)
    lp = [math.log(g["price"]) for g in pool]
    lc = [math.log(g["chance"]) for g in pool]
    states = [((), 0.0, 0.0, -1)]  # idxs, log price, log chance, last index
    found = []
    for depth in range(1, max_legs + 1):
        nxt = []
        for idxs, p, c, last in states:
            for j in range(last + 1, len(pool)):
                if p + lp[j] > hi + 1e-9:
                    continue
                if not _compatible([pool[i] for i in idxs], pool[j]):
                    continue
                nxt.append((idxs + (j,), p + lp[j], c + lc[j], j))
        nxt.sort(key=lambda s: s[2] / s[1], reverse=True)
        states = nxt[:beam]
        for idxs, p, _c, _l in states:
            if depth >= min_legs and p >= lo - 1e-9:
                found.append([pool[i] for i in idxs])
        if not states:
            break
    return found


def _lower_bound(stack, p_all, z=Z):
    rel = math.sqrt(sum((g.get("sd", LEG_SD) / g["chance"]) ** 2 for g in stack))
    return max(p_all * (1 - z * rel), 0.0)


def _value(objective, stack, price, p_all, p_one, payoff):
    if objective == "chance":
        return p_all
    if objective == "ev":
        return _lower_bound(stack, p_all) * price
    if objective == "promo":
        if payoff is None:
            raise ValueError("objective 'promo' needs a payoff(p_all, p_one_fail, price) function")
        return payoff(p_all, p_one, price)
    raise ValueError(f"unknown objective {objective!r}")


LABELS = {"chance": OBJ_CHANCE, "ev": OBJ_EV, "promo": OBJ_PROMO}


def _summary(stack, objective, payoff):
    price = math.prod(g["price"] for g in stack)
    p_all = joint(stack)
    p_one = p_exactly_one_fail(stack, p_all)
    return {
        "legs": [
            {
                k: g.get(k)
                for k in ("game", "player", "stat", "line", "under", "label", "price", "chance")
            }
            for g in stack
        ],
        "price": round(price, 3),
        "p_all": round(p_all, 5),
        "p_exactly_one_fail": round(p_one, 5),
        "p_all_win_low": round(_lower_bound(stack, p_all), 5),
        "quote_status": "estimated_product_price",  # product of leg prices, not a bookmaker multi quote
        "evidence_status": "unvalidated",
        "value": _value(objective, stack, price, p_all, p_one, payoff),
    }


def rank(
    legs,
    target,
    *,
    objective="chance",
    payoff=None,
    include_h2h=False,
    band=BAND,
    min_legs=2,
    max_legs=6,
    min_leg_chance=MIN_LEG_CHANCE,
    min_leg_price=N.LEG_MIN_PRICE,
    beam=BEAM,
    top=5,
    as_of=None,
    max_age_s=MAX_AGE_S,
) -> dict:
    """Best multi at the quoted target price. {"objective", "target", "band", "pick", "top",
    "n_candidates", "reason"}; pick is None (with a reason) when nothing qualifies."""
    res = {
        "objective": LABELS[objective],
        "target": target,
        "band": [target, round(target * band, 3)],
        "pick": None,
        "top": [],
        "n_candidates": 0,
        "reason": None,
    }
    res["n_unverified_legs"] = sum(quote_status(g, as_of, max_age_s) != "verified" for g in legs)
    pool = _eligible(legs, include_h2h, min_leg_chance, min_leg_price, as_of, max_age_s)
    if len(pool) < min_legs:
        res["reason"] = f"only {len(pool)} eligible legs"
        return res
    cands = candidates(pool, target, band, min_legs, max_legs, beam)
    res["n_candidates"] = len(cands)
    if not cands:
        res["reason"] = "no combination of priced legs lands in the target band"
        return res
    cands.sort(key=lambda s: sum(math.log(g["chance"]) for g in s), reverse=True)
    scored = [_summary(s, objective, payoff) for s in cands[:RESCORE]]
    scored.sort(key=lambda r: r["value"], reverse=True)
    res["top"], res["pick"] = scored[:top], scored[0]
    return res


def _alt_chance(g, name, w=None):
    under = bool(g.get("under"))
    if w is not None:
        if g.get("model") is None or g.get("market") is None:
            return g["chance"]
        return N.shade(N.blend(g["model"], g["market"], w), under)
    books = g.get("books") or {}
    others = [p for b, p in books.items() if b != g.get("book")]
    if g.get("book") in books and others:  # leave the quoting book out
        return N.shade(sum(others) / len(others), under)
    return g["chance"]


CHALLENGERS = {"blend_0.25": 0.25, "blend_0.5": 0.5, "loo_consensus": None}


def shadow_picks(legs, target, **kw) -> dict:
    """{challenger: rank() result} using other probability sources, for logging only. Prices and
    candidate rules are unchanged; only each leg's chance differs."""
    out = {}
    for name, w in CHALLENGERS.items():
        alt = [{**g, "chance": round(_alt_chance(g, name, w), 4)} for g in legs]
        out[name] = rank(alt, target, **kw)
    return out


def _slim(r):
    return (
        None
        if r["pick"] is None
        else {
            k: r["pick"][k]
            for k in ("legs", "price", "p_all", "p_exactly_one_fail", "quote_status")
        }
    )


def shadow_log_row(decision_time, target, champion, challengers) -> dict:
    """JSON-able record: decision time, candidates, champion pick, challenger picks (no storage)."""
    if isinstance(decision_time, datetime):
        decision_time = decision_time.astimezone(UTC).isoformat()
    return {
        "decision_time": decision_time,
        "target": target,
        "objective": champion["objective"],
        "n_candidates": champion["n_candidates"],
        "candidates": [_slim({"pick": c}) for c in champion["top"]],
        "champion": _slim(champion),
        "reason": champion["reason"],
        "challengers": {k: _slim(v) for k, v in challengers.items()},
    }
