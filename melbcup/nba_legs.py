# ruff: noqa: E501, E702
"""NBA value legs and multis from PointsBet player props (owner, 2026-11-04). Token-free.

Usage: python3 tools/nba/legs.py BOARD.json OUT.json [--snapdir DIR] [--min-chance 0.75] [--stake 10]
BOARD.json comes from tools/nba/board.py (model v3 expected counts per player and stat).
Prices: PointsBet's NBA games, fetched live unless --snapdir points at saved snapshots
(the nba-props blobs, unzipped or .json.gz). Each "X To Score 20+ Points" style outcome becomes a
leg: model chance, price, fair price (1 / chance) and EV per $1 (chance x price - 1).

A leg qualifies for a multi only if it is highly likely (chance >= --min-chance) AND priced above
fair by at least --min-ev (default +3%: a smaller gap is inside the model's own error). Multis, 3 to 10 legs:
  across games  one leg per game (a normal multi takes one leg per game); price = product of
                prices; chance = product of chances (games are independent).
  same game     one leg per player, best EV first; chance shown as the product of the legs (legs
                in one game are linked, so treat it as a guide); PointsBet prices a same-game multi
                itself, so the fair price is what to compare its quote against.
No qualifying legs means "nothing worth taking today", said plainly in OUT.
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import math
import os
import random
import re
import unicodedata
import urllib.request
from datetime import UTC, datetime
from operator import mul
from statistics import NormalDist

PB = "https://api.au.pointsbet.com/api/mes/v3"
UA = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
    "Accept": "application/json",
}
LEG = re.compile(
    r"^(?P<who>.+?) To (?:Score|Get|Have|Record|Make|Hit) (?P<k>\d+)\+ (?P<what>.+)$", re.I
)


def chance(mu: float, phi: float, ca: float, cb: float, k: int) -> float:
    """Model chance of k or more: negative-binomial tail (mean mu, variance phi x mu), then the
    logistic calibration. Pure Python, equal to tools/nba/board.chance (scipy), so it runs in the
    Azure Function without numpy."""
    mu = max(mu, 1e-6)
    phi = max(phi, 1.0001)
    r = mu / (phi - 1)
    p = 1 / phi
    below = sum(
        math.exp(
            math.lgamma(j + r)
            - math.lgamma(r)
            - math.lgamma(j + 1)
            + r * math.log(p)
            + j * math.log1p(-p)
        )
        for j in range(max(k, 0))
    )
    t = min(max(1 - below, 1e-5), 1 - 1e-5)
    return 1 / (1 + math.exp(-(ca * math.log(t / (1 - t)) + cb)))


def stat_of(what: str, unit: str | None) -> str | None:
    t = f"{what} {unit or ''}".lower()
    # the board's own stat names (tools/nba/tune.py STATS)
    if "three" in t or "3-point" in t or "3 point" in t:
        return "threePointersMade"
    if "rebound" in t:
        return "reboundsTotal"
    if "assist" in t:
        return "assists"
    if "point" in t:
        return "points"
    return None


def norm(name: str | None) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", "", s)
    return " ".join(w for w in s.split() if w not in ("jr", "sr", "ii", "iii", "iv"))


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
        return json.loads(r.read())


def live_events():
    """PointsBet's NBA games that have not started, each with its markets. Games are fetched in
    parallel (a handful of calls), so the page waits for one round trip, not six."""
    from concurrent.futures import ThreadPoolExecutor

    listing = [
        e
        for e in get(f"{PB}/events/featured/competition/7176?page=1").get("events", [])
        if not e.get("isLive")
    ]

    def one(e):
        f = get(f"{PB}/events/{e['key']}")
        ms = (f.get("fixedOddsMarkets") or []) + (f.get("specialFixedOddsMarkets") or [])
        return {
            "event": str(e["key"]),
            "name": e.get("name"),
            "startsAt": e.get("startsAt"),
            "markets": [
                {"group": m.get("groupName"), "outcomes": m.get("outcomes") or []} for m in ms
            ],
        }

    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(one, listing[:20]))


SB = "https://www.sportsbet.com.au/apigw/sportsbook-sports/Sportsbook/Sports"
SB_NBA = "6927"
SB_STAT = {
    "Points": "points",
    "Rebounds": "reboundsTotal",
    "Assists": "assists",
    "Made Threes": "threePointersMade",
}
SB_ALT = re.compile(
    r"^(?:To (?:Score|Record) )?(?P<k>\d+)\+ (?P<what>Points|Rebounds|Assists|Made Threes)$"
)
SB_OU = re.compile(r"^(?P<who>.+?) - (?P<what>Points|Rebounds|Assists|Made Threes)$")
WORD = {
    "points": "Points",
    "reboundsTotal": "Rebounds",
    "assists": "Assists",
    "threePointersMade": "Threes",
}


def sportsbet_outcomes(markets: list[dict]) -> list[dict]:
    """Sportsbet's player markets as parsed outcomes. Two kinds: alternate lines ("To Score 20+
    Points", one selection per player) and over/under lines ("Joel Embiid - Points", Over and
    Under 19.5). Combined stats (Pts + Reb) are left out: the model prices single stats only."""
    out = []
    for m in markets:
        if m.get("statusCode", "A") != "A":
            continue
        name = m.get("name") or ""
        alt, ou = SB_ALT.match(name), SB_OU.match(name)
        for sel in m.get("selections") or []:
            price = (sel.get("price") or {}).get("winPrice")
            if sel.get("statusCode", "A") != "A" or not price or price <= 1:
                continue
            if alt:
                k, stat, who = int(alt["k"]), SB_STAT[alt["what"]], sel.get("name") or ""
                out.append(
                    {
                        "name": f"{who} {k}+ {WORD[stat]}",
                        "price": price,
                        "player": who,
                        "stat": stat,
                        "k": k,
                        "under": False,
                    }
                )
            elif ou:
                try:
                    line = float(sel.get("unformattedHandicap"))
                except (TypeError, ValueError):
                    continue
                under = (sel.get("name") or "").strip().endswith("Under")
                stat, who = SB_STAT[ou["what"]], ou["who"]
                side = "Under" if under else "Over"
                out.append(
                    {
                        "name": f"{who} {side} {line:g} {WORD[stat]}",
                        "price": price,
                        "player": who,
                        "stat": stat,
                        "k": math.floor(line) + 1,
                        "under": under,
                    }
                )
    return out


def sportsbet_events(competition: dict, markets_by_event: dict) -> list[dict]:
    """Sportsbet's NBA games that have not started, in the shape legs_from reads."""
    out = []
    for e in competition.get("events") or []:
        if e.get("bettingStatus") not in (None, "PRICED") or str(e["id"]) not in markets_by_event:
            continue
        start = e.get("startTime")
        when = (
            datetime.fromtimestamp(start, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            if isinstance(start, (int, float))
            else start
        )
        name = re.sub(r" At ", " @ ", e.get("name") or "")
        out.append(
            {
                "event": f"sb{e['id']}",
                "name": name,
                "startsAt": when,
                "markets": [
                    {
                        "group": "sportsbet",
                        "outcomes": sportsbet_outcomes(markets_by_event[str(e["id"])]),
                    }
                ],
            }
        )
    return out


def live_sportsbet():
    """Sportsbet's NBA games and their player markets, fetched in parallel. Sportsbet answers
    Australian addresses only (the web app and the Function run in Australia East)."""
    from concurrent.futures import ThreadPoolExecutor

    comp = get(f"{SB}/Competitions/{SB_NBA}?displayType=default&includeTopMarkets=false")
    ids = [
        str(e["id"]) for e in comp.get("events") or [] if e.get("bettingStatus") in (None, "PRICED")
    ][:20]
    with ThreadPoolExecutor(max_workers=8) as pool:
        markets = dict(
            zip(ids, pool.map(lambda i: get(f"{SB}/Events/{i}/Markets"), ids), strict=True)
        )
    return sportsbet_events(comp, markets)


AGENCY_EVENTS = {"pb": live_events, "sb": live_sportsbet}  # the agencies with NBA player lines


def saved_events(snapdir):
    latest = {}
    for p in sorted(glob.glob(os.path.join(snapdir, "**", "*.json*"), recursive=True)):
        raw = open(p, "rb").read()
        d = json.loads(gzip.decompress(raw) if p.endswith(".gz") else raw)
        latest[d["event"]] = d  # sorted paths: the last snapshot of a game wins
    return list(latest.values())


def game_teams(board):
    """PointsBet 'Away @ Home' name -> the two ESPN team codes, from the board's games."""
    return {norm(g["name"].replace(" at ", " ")): set(g["teams"].values()) for g in board["games"]}


def find(players, who, teams):
    """Full-name match first; else 'S. Gilgeous-Alexander' style: first initial + surname, same game."""
    n = norm(who)
    hit = players.get(n)
    if hit and hit["team"] in teams:
        return hit
    parts = n.split()
    if len(parts) >= 2:
        cands = [
            p
            for k, p in players.items()
            if k.split()[-1] == parts[-1] and k[0] == parts[0][0] and p["team"] in teams
        ]
        if len(cands) == 1:
            return cands[0]
    return None


BLEND_W = 0.5  # weight on the model in the blend; tools/nba/tune_blend.py fits it on settled legs
OVERROUND = 1.07  # a feed's overround when it has no over/under pairs to estimate it from


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def blend(model: float, market: float | None, w: float | None = None) -> float:
    """sigmoid(w logit(model) + (1-w) logit(market)); no market price keeps the model chance."""
    if market is None:
        return model
    w = BLEND_W if w is None else w
    return 1 / (1 + math.exp(-(w * _logit(model) + (1 - w) * _logit(market))))


def feed_market(legs: list[dict]) -> dict:
    """One agency's implied chance per bet_key. An over/under pair on the same line has its margin
    removed; a single-sided leg (an alternate "N+" ladder) is 1/price over the feed's overround,
    estimated from its own pairs (OVERROUND when it has none)."""
    sides: dict = {}
    for g in legs:
        sides.setdefault((g["player"], g["stat"], g["line"]), {})[bool(g["under"])] = g["price"]
    books = [1 / v[False] + 1 / v[True] for v in sides.values() if len(v) == 2]
    over = sum(books) / len(books) if books else OVERROUND
    out = {}
    for (who, stat, line), v in sides.items():
        for under, price in v.items():
            key = (who, stat, line, under)
            if len(v) == 2:
                out[key] = (1 / price) / (1 / v[False] + 1 / v[True])
            else:
                out[key] = min((1 / price) / max(over, 1.0), 0.999)
    return out


def market_probs(legs_by_agency: dict) -> dict:
    """{bet_key: mean implied chance over every agency that prices the bet}."""
    acc: dict = {}
    for legs in legs_by_agency.values():
        for k, p in feed_market(legs).items():
            acc.setdefault(k, []).append(p)
    return {k: sum(v) / len(v) for k, v in acc.items()}


def apply_market(legs: list[dict], market: dict) -> None:
    """Blend each leg's model chance with the market's (in place). "model" stays the pure model
    value, "market" is None when nobody prices the bet; chance, fair and ev use the blend."""
    for g in legs:
        m = market.get(bet_key(g))
        c = blend(g["model"], m)
        g["market"] = None if m is None else round(m, 4)
        g["chance"] = round(c, 4)
        g["fair"] = round(1 / c, 2)
        g["ev"] = round(c * g["price"] - 1, 4)


def legs_from(events, board):
    players = {norm(p["name"]): p for p in board["players"]}
    gteams = game_teams(board)
    prm = board["params"]
    legs, unmatched = [], set()
    for ev in events:
        teams = gteams.get(norm((ev.get("name") or "").replace(" @ ", " ")))
        if not teams:
            continue  # not one of the board's games (another day's game, or a name we cannot place)
        for m in ev["markets"]:
            for o in m["outcomes"]:
                if o.get("isOpenForBetting") is False or not o.get("price"):
                    continue
                if "stat" in o:  # already parsed (Sportsbet): player, stat, k, under
                    who, s, k, under = o["player"], o["stat"], int(o["k"]), bool(o.get("under"))
                else:  # "X To Score 20+ Points" (PointsBet)
                    hit = LEG.match(o.get("name") or "")
                    if not hit:
                        continue
                    who, s, k, under = (
                        hit["who"],
                        stat_of(hit["what"], o.get("unitType")),
                        int(hit["k"]),
                        False,
                    )
                p = find(players, who, teams)
                if s is None:
                    continue
                if p is None or s not in p["mu"]:
                    unmatched.add(who)
                    continue
                q = prm[s]
                c = chance(p["mu"][s], q["phi"], q["ca"], q["cb"], k)
                if under:  # "Under 19.5" wins on 19 or fewer: the other side of "20+"
                    c = 1 - c
                price = float(o["price"])
                legs.append(
                    {
                        "game": ev["name"],
                        "event": ev["event"],
                        "startsAt": ev.get("startsAt"),
                        "player": p["name"],
                        "team": p["team"],
                        "stat": s,
                        "line": k,
                        "under": under,
                        "label": o["name"],
                        "price": price,
                        "model": round(c, 4),
                        "market": None,
                        "chance": round(c, 4),
                        "fair": round(1 / c, 2),
                        "ev": round(c * price - 1, 4),
                        "expected": p["mu"][s],
                        "minutes": p["minutes"],
                    }
                )
    apply_market(legs, {})
    return legs, sorted(unmatched)


def multi(legs, stake, chance=None):
    """`chance`: the legs' joint chance when they are correlated; else they multiply."""
    c = math.prod(g["chance"] for g in legs) if chance is None else chance
    price = math.prod(g["price"] for g in legs)
    return {
        "legs": len(legs),
        "chance": round(c, 4),
        "price": round(price, 2),
        "fair": round(1 / c, 2),
        "ev": round(c * price - 1, 4),
        "returns": round(stake * price, 2),
        "picks": [g["label"] for g in legs],
        "detail": [
            {
                k: g.get(k)
                for k in (
                    "label",
                    "chance",
                    "price",
                    "game",
                    "team",
                    "startsAt",
                    "player",
                    "stat",
                    "line",
                    "under",
                )
            }
            for g in legs
        ],
        "tip": max(
            (g.get("startsAt") or "" for g in legs), default=""
        ),  # when the last leg tips off
    }


def build(legs, min_chance, stake, min_ev=0.03):
    ok = [g for g in legs if g["chance"] >= min_chance and g["ev"] >= min_ev]
    best_per = {}
    for g in sorted(ok, key=lambda g: (-g["ev"], -g["chance"])):
        best_per.setdefault((g["event"], g["player"]), g)  # one leg per player
    pool = list(best_per.values())
    per_game = {}
    for g in sorted(pool, key=lambda g: (-g["chance"], -g["ev"])):
        per_game.setdefault(g["event"], g)  # the surest value leg of each game
    cross_pool = sorted(per_game.values(), key=lambda g: -g["chance"])
    cross = [multi(cross_pool[:n], stake) for n in range(3, min(10, len(cross_pool)) + 1)]
    same = []
    for ev in sorted({g["event"] for g in pool}):
        gl = sorted((g for g in pool if g["event"] == ev), key=lambda g: -g["chance"])
        for n in range(3, min(10, len(gl)) + 1):
            same.append({"game": gl[0]["game"]} | multi(gl[:n], stake))
    return ok, cross, same


TARGETS = (2.0, 3.0, 5.0, 10.0, 20.0)  # payouts: $10 returns $20, $30, $50, $100, $200
STEP = 0.01  # price grid on a log scale (1% steps)
SAME_MAX_LEGS = 6  # a same-game multi longer than this almost never gets up
SAME_FLOOR = 0.6


def bet_key(g: dict) -> tuple:
    """The same bet at any agency: player, stat, line and side."""
    return (g.get("player"), g.get("stat"), g.get("line"), bool(g.get("under")))


def better_elsewhere(item: dict, prices: dict, code: str) -> dict | None:
    """Does another agency pay more for this exact leg, or for every leg of this multi?
    `prices`: that agency's {bet_key: price}. Returns {"code", "diff"} when it pays more."""
    legs = item.get("detail") or [item]
    mine, theirs = 1.0, 1.0
    for g in legs:
        other = prices.get(bet_key(g))
        if other is None:
            return None  # a leg it does not offer: not the same bet
        mine *= g["price"]
        theirs *= other
    diff = round(theirs - mine, 2)
    return {"code": code, "diff": diff} if diff > 0 else None


def frontier(legs):
    """Drop a leg when another pays at least as much AND is at least as likely."""
    out, best = [], -1.0
    for g in sorted(legs, key=lambda g: (-g["price"], -g["chance"])):
        if g["chance"] > best:
            out.append(g)
            best = g["chance"]
    return out


FRONT_CAP = 3  # partial stacks kept per 1% price step (the likeliest); keeps the search fast


def _keep(front, cand):
    """Add cand to a bucket's list unless one there is at least as likely AND pays at least as
    much; drop the ones cand beats on both; keep the FRONT_CAP likeliest."""
    lc, lp = cand[0], cand[1]
    for o in front:
        if o[0] >= lc and o[1] >= lp:
            return front
    front = [o for o in front if not (lc >= o[0] and lp >= o[1])]
    front.append(cand)
    if len(front) > FRONT_CAP:
        front.sort(key=lambda o: -o[0])
        del front[FRONT_CAP:]
    return front


def _search(groups, targets, max_legs):
    """The 1% log-price grid pass: states[k] = {bucket: [(log chance, log price, picks)]}."""
    cap = math.log(targets[-1]) + 1e-9
    top = int(cap / STEP)
    # logs once per leg, not once per partial stack
    lgroups = [[(math.log(g["chance"]), math.log(g["price"]), g) for g in group] for group in groups]
    states = [dict() for _ in range(max_legs + 1)]  # k legs -> {bucket: [(log chance, log price, picks)]}
    states[0][0] = [(0.0, 0.0, ())]
    for group in lgroups:
        for k in range(max_legs - 1, -1, -1):  # downwards: one leg per group
            nxt = states[k + 1]
            for front in list(states[k].values()):
                for lc, lp, picks in front:
                    for glc, glp, g in group:
                        lp2 = lp + glp
                        b2 = int(lp2 / STEP)
                        if b2 >= top:
                            b2, lp2 = top, min(lp2, cap)
                        nxt[b2] = _keep(nxt.get(b2, []), (lc + glc, lp2, picks + (g,)))
    return states


def top_stacks(groups, targets, n=1, min_legs=3, max_legs=10) -> dict:
    """For every payout target at once: the n likeliest stacks (as the legs multiply) whose price
    reaches it, at most one leg per group, likeliest first. One pass over a 1% log-price grid
    (prices above the largest target share its top bucket); each bucket keeps the likeliest
    stacks not beaten on both chance and price (FRONT_CAP of them)."""
    targets = sorted(set(targets))
    if not targets:
        return {}
    states = _search(groups, targets, max_legs)
    out = {}
    for t in targets:
        goal = math.log(t) - 1e-9
        lo = int(goal / STEP)
        found = [
            c
            for k in range(min_legs, max_legs + 1)
            for b, front in states[k].items()
            if b >= lo
            for c in front
            if c[1] >= goal
        ]
        found.sort(key=lambda c: -c[0])
        out[t] = [list(c[2]) for c in found[:n]]
    return out


def best_stacks(groups, targets, min_legs=3, max_legs=10) -> dict:
    """For every payout target at once: the stack most likely to get up whose price reaches it
    (top_stacks with n=1); None when nothing reaches it."""
    found = top_stacks(groups, targets, 1, min_legs, max_legs)
    return {t: (v[0] if v else None) for t, v in found.items()}


def best_stack(groups, target, min_legs=3, max_legs=10):
    """The likeliest stack reaching one payout target (see best_stacks)."""
    return best_stacks(groups, [target], min_legs, max_legs)[target]


# Same-game correlation (Gaussian copula). Legs in one game move together a little: the normal-score
# correlation of actual vs model-v3-expected counts, by relation (self: one player's two stats;
# team: two teammates; opp: a player and an opposing player) and stat pair, fitted by
# tools/nba/correlation.py on seasons 2018-19 to 2022-23 (out of sample for the 2023-24+ backtests).
MIN_CORR = 0.05  # |r| below this fitted as indistinguishable from 0 (2023-25 box scores)
CORR = {
    ("self", "ast", "3pm"): 0.102,
    ("self", "pts", "3pm"): 0.555,
    ("self", "pts", "ast"): 0.201,
    ("self", "pts", "reb"): 0.348,
    ("self", "reb", "3pm"): 0.132,
    ("self", "reb", "ast"): 0.211,
    ("team", "3pm", "3pm"): -0.003,
    ("team", "ast", "3pm"): 0.03,
    ("team", "ast", "ast"): -0.005,
    ("team", "pts", "3pm"): -0.011,
    ("team", "pts", "ast"): 0.035,
    ("team", "pts", "pts"): -0.011,
    ("team", "pts", "reb"): 0.006,
    ("team", "reb", "3pm"): 0.0,
    ("team", "reb", "ast"): 0.001,
    ("team", "reb", "reb"): -0.005,
    ("opp", "3pm", "3pm"): 0.005,
    ("opp", "ast", "3pm"): 0.007,
    ("opp", "ast", "ast"): 0.01,
    ("opp", "pts", "3pm"): 0.011,
    ("opp", "pts", "ast"): 0.013,
    ("opp", "pts", "pts"): 0.026,
    ("opp", "pts", "reb"): -0.001,
    ("opp", "reb", "3pm"): -0.003,
    ("opp", "reb", "ast"): -0.005,
    ("opp", "reb", "reb"): 0.012,
}
SHORT = {"points": "pts", "reboundsTotal": "reb", "assists": "ast", "threePointersMade": "3pm"}
MC_DRAWS = 4000  # copula draws per re-score (the same draws for every candidate, so they compare fairly)
MC_SEED = 20261104
MC_TOP = 20  # same-game candidates per target re-scored by the copula
_DRAWS: list = []


def _rho(a: dict, b: dict) -> float:
    """Correlation between two legs' normal scores: sign flipped when exactly one is an under."""
    if a["player"] == b["player"]:
        rel = "self"
    elif a.get("team") == b.get("team"):
        rel = "team"
    else:
        rel = "opp"
    x, y = SHORT.get(a.get("stat"), ""), SHORT.get(b.get("stat"), "")
    r = CORR.get((rel, x, y), CORR.get((rel, y, x), 0.0))
    if abs(r) < MIN_CORR:  # fitted noise: treat as independent and skip the Monte Carlo
        return 0.0
    return -r if bool(a.get("under")) != bool(b.get("under")) else r


def _cholesky(m):
    """Lower-triangular L with L L' = m; the off-diagonals are shrunk until m is positive definite."""
    n = len(m)
    shrink = 1.0
    while True:
        lo = [[0.0] * n for _ in range(n)]
        try:
            for i in range(n):
                for j in range(i + 1):
                    v = (m[i][j] if i == j else shrink * m[i][j]) - sum(
                        lo[i][k] * lo[j][k] for k in range(j)
                    )
                    if i == j:
                        if v <= 1e-9:
                            raise ValueError
                        lo[i][i] = math.sqrt(v)
                    else:
                        lo[i][j] = v / lo[j][j]
            return lo
        except ValueError:
            shrink *= 0.8


def joint_chance(legs) -> float:
    """Chance every leg wins, the legs' normal scores correlated by CORR (a Gaussian copula) and
    each leg keeping its own chance. Monte Carlo over MC_DRAWS fixed, seeded draws, so the same
    legs always give the same answer; no correlation at all gives the plain product exactly."""
    legs = sorted(legs, key=lambda g: g["chance"])  # the least likely first: most draws stop early
    n = len(legs)
    prod = math.prod(g["chance"] for g in legs)
    rho = [[1.0 if i == j else _rho(legs[i], legs[j]) for j in range(n)] for i in range(n)]
    if n < 2 or all(rho[i][j] == 0 for i in range(n) for j in range(i)):
        return prod
    if len(_DRAWS) < MC_DRAWS or len(_DRAWS[0]) < n:
        rng = random.Random(MC_SEED)
        _DRAWS[:] = [tuple(rng.gauss(0, 1) for _ in range(max(n, 12))) for _ in range(MC_DRAWS)]
    lo = _cholesky(rho)
    nd = NormalDist()
    # a leg wins when its score clears the point that leaves exactly its chance above it
    thr = [nd.inv_cdf(1 - min(max(g["chance"], 1e-6), 1 - 1e-6)) for g in legs]
    rows = list(zip(lo, thr, strict=True))
    hits = 0
    for e in _DRAWS:
        for li, t in rows:
            if sum(map(mul, li, e)) < t:
                break
        else:
            hits += 1
    return hits / MC_DRAWS


def best_same_game(groups, targets, top=MC_TOP, max_legs=SAME_MAX_LEGS) -> dict:
    """{target: (legs, joint chance) | None}: the additive search's `top` likeliest stacks per
    target, re-scored by joint_chance, the likeliest first."""
    found = top_stacks(groups, targets, top, max_legs=max_legs)
    cache: dict = {}
    out = {}
    for t, cands in found.items():
        best = None
        for st in cands:
            key = tuple(sorted(id(g) for g in st))
            if key not in cache:
                cache[key] = joint_chance(st)
            if best is None or cache[key] > best[1]:
                best = (st, cache[key])
        out[t] = best
    return out


LEG_MIN_PRICE = 1.15  # a leg paying less barely moves a multi's price


def by_game(legs, n=6):
    """Per game, each player's surest line that still pays LEG_MIN_PRICE or more; the most likely first."""
    games = {}
    for g in legs:
        if g["price"] >= LEG_MIN_PRICE:
            best = games.setdefault(g["event"], {}).get(g["player"])
            if best is None or (g["chance"], g["price"]) > (best["chance"], best["price"]):
                games[g["event"]][g["player"]] = g
    out = []
    for players in games.values():
        top = sorted(players.values(), key=lambda g: -g["chance"])[:n]
        out.append({"game": top[0]["game"], "startsAt": top[0].get("startsAt"), "legs": top})
    return sorted(out, key=lambda x: (x["startsAt"] or "", x["game"]))


def stack_for(legs, target, stake=10.0, floor=0.5):
    """The likeliest one-leg-per-game stack paying at least `target` times the stake (or None)."""
    by_game = {}
    for g in legs:
        if g["chance"] >= floor and g["price"] > 1.0:
            by_game.setdefault(g["event"], []).append(g)
    picks = best_stack([frontier(gs) for gs in by_game.values()], target)
    return ({"target": target} | multi(picks, stake)) if picks else None


def _player_groups(gs):
    by_player = {}
    for g in gs:
        if g["chance"] >= SAME_FLOOR and g["price"] > 1.0:
            by_player.setdefault(g["player"], []).append(g)
    return [f for f in (frontier(x) for x in by_player.values()) if f]


def same_game_many(legs, targets, stake=10.0) -> dict:
    """{target: [each game's likeliest same-game stack reaching it, soonest tip-off first]},
    one search per game for all the targets."""
    by_game = {}
    for g in legs:
        by_game.setdefault(g["event"], []).append(g)
    out = {t: [] for t in targets}
    for gs in by_game.values():
        found = best_same_game(_player_groups(gs), targets)
        for t, hit in found.items():
            if hit:
                out[t].append(
                    {"target": t, "game": gs[0]["game"], "startsAt": gs[0].get("startsAt")}
                    | multi(hit[0], stake, hit[1])
                )
    for t in out:
        out[t].sort(key=lambda m: (m["startsAt"] or "", -m["chance"]))
    return out


def same_game_for(legs, target, stake=10.0):
    """For each game, the likeliest same-game stack (one leg per player) whose legs multiply to at
    least `target`; soonest tip-off first."""
    return same_game_many(legs, [target], stake)[target]


def stacks(legs, stake=10.0, floor=0.5):
    """For each payout target, the most likely stack: across games (one leg per game, a normal
    multi) and inside one game (one leg per player, a same-game multi)."""
    usable = [g for g in legs if g["chance"] >= floor and g["price"] > 1.0]
    by_game = {}
    for g in usable:
        by_game.setdefault(g["event"], []).append(g)
    found = best_stacks([frontier(gs) for gs in by_game.values()], TARGETS)
    cross = [{"target": t} | multi(p, stake) for t, p in found.items() if p]
    many = same_game_many(usable, TARGETS, stake)
    same = [
        max(many[t], key=lambda m: m["chance"]) for t in TARGETS if many[t]
    ]  # the best game per target
    return cross, same


def stage_preview(legs, xs: dict) -> dict:
    """{stage count: chance of the likeliest one-game multi paying that stage's share}, for the
    challenge's set-up table: xs is {stages: payout per stage}. One search per game."""
    many = same_game_many(legs, list(set(xs.values())))
    return {n: max((g["chance"] for g in many[x]), default=None) for n, x in xs.items()}


def view(board, events_by_agency: dict, xs: dict | None = None) -> dict:
    """Everything the NBA page shows, worked out once (by the Azure timer) so the web app only
    reads it: per agency the report, and the challenge's stage table."""
    out = {"day": board.get("day"), "agencies": {}, "preview": {}}
    prepared = {code: legs_from(ev, board) for code, ev in events_by_agency.items()}
    market = market_probs({code: p[0] for code, p in prepared.items()})
    for code, events in events_by_agency.items():
        rep = report(board, events, prepared=prepared[code], market=market)
        out["agencies"][code] = {"report": rep, "games": len(events), "error": None}
        if xs:
            out["preview"][code] = stage_preview(rep["all_legs"], xs)
    return out


def report(board, events, min_chance=0.75, stake=10.0, min_ev=0.03, prepared=None, market=None):
    """`prepared`: this agency's legs_from() result when the caller has it; `market`: bet_key to
    implied chance across all agencies (default: this feed's own prices)."""
    legs, unmatched = prepared or legs_from(events, board)
    apply_market(legs, market if market is not None else market_probs({"": legs}))
    ok, cross, same = build(legs, min_chance, stake, min_ev)
    stack_cross, stack_same = stacks(legs, stake)
    return {
        "stacks": stack_cross,
        "stacks_same": stack_same,
        "by_game": by_game(legs),
        "day": board["day"],
        "verdict": "take" if ok else "nothing worth taking today",
        "min_chance": min_chance,
        "min_ev": min_ev,
        "stake": stake,
        "games_priced": len({g["event"] for g in legs}),
        "legs_seen": len(legs),
        "value_legs": sorted(ok, key=lambda g: -g["chance"]),
        "all_legs": legs,
        "cross_game": cross,
        "same_game": same,
        "unmatched_players": unmatched,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("board")
    ap.add_argument("out")
    ap.add_argument("--snapdir")
    ap.add_argument("--min-chance", type=float, default=0.75)
    ap.add_argument("--stake", type=float, default=10.0)
    ap.add_argument("--min-ev", type=float, default=0.03)
    a = ap.parse_args()
    board = json.load(open(a.board))
    events = saved_events(a.snapdir) if a.snapdir else live_events()
    res = report(board, events, a.min_chance, a.stake, a.min_ev)
    json.dump(res, open(a.out, "w"), indent=1)
    print(
        f"{board['day']}: {res['games_priced']} games, {res['legs_seen']} legs priced, {len(res['value_legs'])} likely AND above fair; unmatched names {len(res['unmatched_players'])}"
    )
    for g in res["value_legs"][:12]:
        print(
            f"  {g['chance']:.0%} ${g['price']:.2f} (fair ${g['fair']:.2f}, EV {g['ev']:+.0%})  {g['label']}"
        )
    for m in res["cross_game"]:
        print(
            f"  cross {m['legs']} legs: chance {m['chance']:.0%}  ${m['price']:.2f}  ${a.stake:.0f} returns ${m['returns']:.2f}  EV {m['ev']:+.0%}"
        )
    if not res["value_legs"]:
        print("  nothing worth taking today")


if __name__ == "__main__":
    main()
