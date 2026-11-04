# ruff: noqa: E501, E702
"""Do the app's multis get up as often as it says? A season replayed night by night (owner, 2026-11-04).

Usage: python3 tools/nba/backtest_multis.py BOXDIR [--season 00224] [--margin 0.05] [--out FILE]
Token-free. For every night of the season, every player's lines (tools/nba/tune.py LINES) are
priced with model v3 using only games before that night (the backtest's own features), and the
app's search (melbcup/nba_legs.py best_stack) picks, for each payout target, the stack most likely
to get up: across games (one leg per game) and inside one game (one leg per player).

There are no past PointsBet prices, so each leg's price is assumed to be the model's fair price cut
by --margin (a bookmaker's typical take). That makes this a test of the CHANCES, not of value:
  1. stacks across games: said chance vs how often they actually got up
  2. same-game stacks: the same, which shows how much legs in one game move together
  3. $10 -> $1000 challenges rolled night after night at ~5x a step, at those assumed prices
2025-26 stays sealed; the real-price test is the forward log the daily job keeps from now on.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", ".."))
from correlation import load_jsonl  # noqa: E402
from tune import LINES, STATS, build, load  # noqa: E402
from tune_v3 import predict  # noqa: E402

from melbcup.nba_legs import best_same_game, best_stack, frontier  # noqa: E402

TARGETS = (2.0, 3.0, 5.0, 10.0)


def nights(R, season, v3, margin):
    """{night: {game: [leg]}} with model chance, assumed price and the real outcome."""
    idx = np.where(R["season"] == season)[0]
    out = defaultdict(lambda: defaultdict(list))
    for s in STATS:
        prm = v3[s]
        pr = predict(R, idx, s, prm["hl_minutes"], prm["hl_rate"], np.array(prm["theta"]))
        for k in LINES[s]:
            p = pr[k]; hit = R[f"y_{s}"][idx] >= k
            for j, ix in enumerate(idx):
                c = float(p[j])
                if c < 0.5:
                    continue
                night = str(R["when"][ix])[:10]
                game = "|".join(sorted((str(R["team"][ix]), str(R["opp"][ix]))))
                out[night][game].append({"player": R["pid"][ix], "label": f"{R['pid'][ix]} {s} {k}+", "chance": c,
                                         "price": max(1.01, round(1 / (c * (1 + margin)), 2)), "won": bool(hit[j]), "game": game, "stat": s, "team": str(R["team"][ix])})
    return out


def table(rows, title):
    """rows: (said chance, got up). Grouped by said chance."""
    print(f"\n{title}")
    print(f"  {'said':>9} {'stacks':>7} {'said avg':>9} {'got up':>8}")
    bands = defaultdict(list)
    for said, won in rows:
        bands[min(int(said * 10), 9)].append((said, won))
    for b in sorted(bands):
        xs = bands[b]; n = len(xs)
        said = sum(x[0] for x in xs) / n; got = sum(x[1] for x in xs) / n
        se = math.sqrt(max(got * (1 - got), 1e-9) / n)
        print(f"  {b*10:3d}-{b*10+9:2d}%  {n:7d} {100*said:8.1f}% {100*got:7.1f}%  (±{200*se:.1f})")
    if rows:
        n = len(rows)
        print(f"  all       {n:7d} {100*sum(r[0] for r in rows)/n:8.1f}% {100*sum(r[1] for r in rows)/n:7.1f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("boxdir"); ap.add_argument("--season", default="00224")
    ap.add_argument("--margin", type=float, default=0.05); ap.add_argument("--out")
    ap.add_argument("--copula", action="store_true", help="same-game stacks re-scored by the copula (melbcup.nba_legs.joint_chance)")
    a = ap.parse_args()
    if a.season >= "00225":
        raise SystemExit("2025-26 and later stay sealed")
    games = [g for g in (load_jsonl(a.boxdir) if os.path.isfile(a.boxdir) else load(a.boxdir)) if g[1] <= a.season]
    R = build(games)
    v3 = json.load(open(os.path.join(HERE, "model_v3.json")))
    N = nights(R, a.season, v3, a.margin)
    cross, same, same_indep, picks_log = [], [], [], []
    by_target = defaultdict(list)
    step_results = []  # (night, said chance, price, won) for the ~5x step, in date order
    for night in sorted(N):
        groups = [frontier(legs) for legs in N[night].values()]
        for t in TARGETS:
            st = best_stack(groups, t)
            if st:
                said = math.prod(g["chance"] for g in st); won = all(g["won"] for g in st)
                cross.append((said, won)); by_target[t].append((said, won, math.prod(g["price"] for g in st)))
                if t == 5.0:
                    step_results.append((night, said, math.prod(g["price"] for g in st), won))
                picks_log.append({"night": night, "target": t, "said": round(said, 4), "won": won, "legs": [g["label"] for g in st]})
        for legs in N[night].values():
            byp = defaultdict(list)
            for g in legs:
                byp[g["player"]].append(g)
            pg = [frontier([g for g in x if g["chance"] >= 0.6]) for x in byp.values()]
            pg = [x for x in pg if x]
            if a.copula:
                hit = best_same_game(pg, [3.0])[3.0]
                st, said = hit if hit else (None, 0.0)
                if st:
                    same_indep.append((math.prod(g["chance"] for g in st), all(g["won"] for g in st)))
            else:
                st = best_stack(pg, 3.0, max_legs=6)
                said = math.prod(g["chance"] for g in st) if st else 0.0
            if st:
                same.append((said, all(g["won"] for g in st)))
    print(f"season {a.season}: {len(N)} nights; leg prices assumed fair minus {a.margin:.0%}")
    table(cross, "1. Stacks across games (one leg per game), all payout targets")
    for t in TARGETS:
        xs = by_target[t]
        if xs:
            n = len(xs); got = sum(x[1] for x in xs) / n; said = sum(x[0] for x in xs) / n
            ret = sum(x[2] for x in xs if x[1]) / n
            print(f"   $10 -> ${10*t:.0f}: {n} nights, said {100*said:.1f}%, got up {100*got:.1f}%, return per $1 at assumed prices {ret:.2f}")
    table(same, "2. Same-game stacks ($10 -> ~$30, one leg per player): " + ("joint chance from the copula" if a.copula else "legs treated as separate"))
    if a.copula:
        table(same_indep, "2b. the same copula-picked stacks, chance as if legs were separate")
    # 3. challenges: start with $10, each night stake the whole bank on the ~5x stack; $1000 = done
    runs, bank, nights_used, lengths = [], 10.0, 0, []
    for _night, _said, price, won in step_results:
        nights_used += 1
        bank = bank * price if won else 0.0
        if bank >= 1000 or bank == 0:
            runs.append(bank >= 1000); lengths.append(nights_used)
            bank, nights_used = 10.0, 0
    if runs:
        print(f"\n3. $10 -> $1000 challenges at ~5x a night: {len(runs)} finished, {sum(runs)} reached $1000 ({100*sum(runs)/len(runs):.1f}%); a run lasted {sum(lengths)/len(lengths):.1f} nights on average")
        print(f"   (at the model's own chances a 5x-step run should reach $1000 about {100*np.mean([s for _, s, _, _ in step_results])**3:.1f}% of the time before the margin)")
    if a.out:
        json.dump(picks_log, open(a.out, "w"))


if __name__ == "__main__":
    main()
