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
import re
import unicodedata
import urllib.request

PB = "https://api.au.pointsbet.com/api/mes/v3"
UA = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148", "Accept": "application/json"}
LEG = re.compile(r"^(?P<who>.+?) To (?:Score|Get|Have|Record|Make|Hit) (?P<k>\d+)\+ (?P<what>.+)$", re.I)


def chance(mu: float, phi: float, ca: float, cb: float, k: int) -> float:
    """Model chance of k or more: negative-binomial tail (mean mu, variance phi x mu), then the
    logistic calibration. Pure Python, equal to tools/nba/board.chance (scipy), so it runs in the
    Azure Function without numpy."""
    mu = max(mu, 1e-6); phi = max(phi, 1.0001)
    r = mu / (phi - 1); p = 1 / phi
    below = sum(math.exp(math.lgamma(j + r) - math.lgamma(r) - math.lgamma(j + 1) + r * math.log(p) + j * math.log1p(-p)) for j in range(max(k, 0)))
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

    listing = [e for e in get(f"{PB}/events/featured/competition/7176?page=1").get("events", []) if not e.get("isLive")]

    def one(e):
        f = get(f"{PB}/events/{e['key']}")
        ms = (f.get("fixedOddsMarkets") or []) + (f.get("specialFixedOddsMarkets") or [])
        return {"event": str(e["key"]), "name": e.get("name"), "startsAt": e.get("startsAt"),
                "markets": [{"group": m.get("groupName"), "outcomes": m.get("outcomes") or []} for m in ms]}

    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(one, listing[:20]))


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
        cands = [p for k, p in players.items() if k.split()[-1] == parts[-1] and k[0] == parts[0][0] and p["team"] in teams]
        if len(cands) == 1:
            return cands[0]
    return None


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
                hit = LEG.match(o.get("name") or "")
                if not hit:
                    continue
                s = stat_of(hit["what"], o.get("unitType"))
                p = find(players, hit["who"], teams)
                if s is None:
                    continue
                if p is None or s not in p["mu"]:
                    unmatched.add(hit["who"]); continue
                k = int(hit["k"]); q = prm[s]
                c = chance(p["mu"][s], q["phi"], q["ca"], q["cb"], k)
                price = float(o["price"])
                legs.append({"game": ev["name"], "event": ev["event"], "startsAt": ev.get("startsAt"), "player": p["name"], "team": p["team"],
                             "stat": s, "line": k, "label": o["name"], "price": price, "chance": round(c, 4),
                             "fair": round(1 / c, 2), "ev": round(c * price - 1, 4), "expected": p["mu"][s], "minutes": p["minutes"]})
    return legs, sorted(unmatched)


def multi(legs, stake):
    c = 1.0; price = 1.0
    for g in legs:
        c *= g["chance"]; price *= g["price"]
    return {"legs": len(legs), "chance": round(c, 4), "price": round(price, 2), "fair": round(1 / c, 2),
            "ev": round(c * price - 1, 4), "returns": round(stake * price, 2), "picks": [g["label"] for g in legs],
            "detail": [{k: g[k] for k in ("label", "chance", "price", "game", "team")} for g in legs]}


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


def frontier(legs):
    """Drop a leg when another pays at least as much AND is at least as likely."""
    out, best = [], -1.0
    for g in sorted(legs, key=lambda g: (-g["price"], -g["chance"])):
        if g["chance"] > best:
            out.append(g); best = g["chance"]
    return out


def _keep(front, cand):
    """Add cand to a bucket's list unless one there is at least as likely AND pays at least as
    much; drop the ones cand beats on both. Exact: no stack that could still win is thrown away."""
    if any(o[0] >= cand[0] and o[1] >= cand[1] for o in front):
        return front
    return [o for o in front if not (cand[0] >= o[0] and cand[1] >= o[1])] + [cand]


def best_stack(groups, target, min_legs=3, max_legs=10):
    """The stack most likely to get up whose price reaches `target`, at most one leg per group.
    Search over a 1% log-price grid with each bucket holding only the stacks not beaten on both
    chance and price, so it is exact and a day's board takes milliseconds."""
    goal = math.log(target) - 1e-9
    top = math.ceil(goal / STEP)
    states = [dict() for _ in range(max_legs + 1)]  # k legs -> {bucket: [(log chance, log price, picks)]}
    states[0][0] = [(0.0, 0.0, ())]
    for group in groups:
        for k in range(max_legs - 1, -1, -1):  # downwards: one leg per group
            for front in list(states[k].values()):
                for lc, lp, picks in front:
                    for g in group:
                        lp2 = lp + math.log(g["price"])
                        b2 = min(top, int(lp2 / STEP))
                        if lp2 >= goal:
                            b2 = top + 1  # reached: price no longer matters, only the chance
                            lp2 = goal
                        states[k + 1][b2] = _keep(states[k + 1].get(b2, []), (lc + math.log(g["chance"]), lp2, picks + (g,)))
    done = [c for k in range(min_legs, max_legs + 1) for c in states[k].get(top + 1, [])]
    return list(max(done, key=lambda c: c[0])[2]) if done else None


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


def stacks(legs, stake=10.0, floor=0.5):
    """For each payout target, the most likely stack: across games (one leg per game, a normal
    multi) and inside one game (one leg per player, a same-game multi)."""
    usable = [g for g in legs if g["chance"] >= floor and g["price"] > 1.0]
    by_game = {}
    for g in usable:
        by_game.setdefault(g["event"], []).append(g)
    cross = []
    groups = [frontier(gs) for gs in by_game.values()]
    for t in TARGETS:
        picks = best_stack(groups, t)
        if picks:
            cross.append({"target": t} | multi(picks, stake))
    same = []
    for gs in by_game.values():
        by_player = {}
        for g in gs:
            by_player.setdefault(g["player"], []).append(g)
        pgroups = [frontier([g for g in x if g["chance"] >= SAME_FLOOR]) for x in by_player.values()]
        pgroups = [x for x in pgroups if x]
        for t in TARGETS:
            picks = best_stack(pgroups, t, max_legs=SAME_MAX_LEGS)
            if picks:
                same.append({"target": t, "game": gs[0]["game"]} | multi(picks, stake))
    same.sort(key=lambda m: (m["target"], -m["chance"]))
    best_same = {}
    for m in same:
        best_same.setdefault(m["target"], m)  # the best game for each target
    return cross, list(best_same.values())


def report(board, events, min_chance=0.75, stake=10.0, min_ev=0.03):
    legs, unmatched = legs_from(events, board)
    ok, cross, same = build(legs, min_chance, stake, min_ev)
    stack_cross, stack_same = stacks(legs, stake)
    return {"stacks": stack_cross, "stacks_same": stack_same, "by_game": by_game(legs),"day": board["day"], "verdict": "take" if ok else "nothing worth taking today", "min_chance": min_chance, "min_ev": min_ev,
            "stake": stake, "games_priced": len({g["event"] for g in legs}), "legs_seen": len(legs),
            "value_legs": sorted(ok, key=lambda g: -g["chance"]), "all_legs": legs, "cross_game": cross, "same_game": same,
            "unmatched_players": unmatched}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("board"); ap.add_argument("out")
    ap.add_argument("--snapdir"); ap.add_argument("--min-chance", type=float, default=0.75); ap.add_argument("--stake", type=float, default=10.0)
    ap.add_argument("--min-ev", type=float, default=0.03)
    a = ap.parse_args()
    board = json.load(open(a.board))
    events = saved_events(a.snapdir) if a.snapdir else live_events()
    res = report(board, events, a.min_chance, a.stake, a.min_ev)
    json.dump(res, open(a.out, "w"), indent=1)
    print(f"{board['day']}: {res['games_priced']} games, {res['legs_seen']} legs priced, {len(res['value_legs'])} likely AND above fair; unmatched names {len(res['unmatched_players'])}")
    for g in res["value_legs"][:12]:
        print(f"  {g['chance']:.0%} ${g['price']:.2f} (fair ${g['fair']:.2f}, EV {g['ev']:+.0%})  {g['label']}")
    for m in res["cross_game"]:
        print(f"  cross {m['legs']} legs: chance {m['chance']:.0%}  ${m['price']:.2f}  ${a.stake:.0f} returns ${m['returns']:.2f}  EV {m['ev']:+.0%}")
    if not res["value_legs"]:
        print("  nothing worth taking today")


if __name__ == "__main__":
    main()
