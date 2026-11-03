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
    if "three" in t or "3-point" in t or "3 point" in t or "threes" in t:
        return "threes"
    for s in ("points", "rebounds", "assists"):
        if s[:-1] in t:
            return s
    return None


def norm(name: str | None) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", "", s)
    return " ".join(w for w in s.split() if w not in ("jr", "sr", "ii", "iii", "iv"))


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
        return json.loads(r.read())


def live_events():
    out = []
    for e in get(f"{PB}/events/featured/competition/7176?page=1").get("events", []):
        if e.get("isLive"):
            continue
        f = get(f"{PB}/events/{e['key']}")
        ms = (f.get("fixedOddsMarkets") or []) + (f.get("specialFixedOddsMarkets") or [])
        out.append({"event": str(e["key"]), "name": e.get("name"), "startsAt": e.get("startsAt"),
                    "markets": [{"group": m.get("groupName"), "outcomes": m.get("outcomes") or []} for m in ms]})
    return out


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
            "ev": round(c * price - 1, 4), "returns": round(stake * price, 2), "picks": [g["label"] for g in legs]}


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


def report(board, events, min_chance=0.75, stake=10.0, min_ev=0.03):
    legs, unmatched = legs_from(events, board)
    ok, cross, same = build(legs, min_chance, stake, min_ev)
    return {"day": board["day"], "verdict": "take" if ok else "nothing worth taking today", "min_chance": min_chance, "min_ev": min_ev,
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
