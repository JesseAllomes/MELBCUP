# ruff: noqa: E501, E702
"""NBA "$10 -> goal" challenge replayed on past seasons (owner, 2026-11-05). Token-free.

Usage: python3 tools/nba/backtest_challenge.py HISTORY.jsonl.gz [--step 2] [--out FILE]
A run starts on a game night, rolls the bank through N stages (one multi a night, one loss ends it).
  mode game : one same-game multi per stage (legs per player, copula chance, pays product x (1-HAIRCUT))
  mode multi: one leg per game across the night (pays the full product)
  S0 play the next game night every time; S1 skip tonight unless it is among the best `stages left`
  of the next 9 nights (later nights scored by game count only, nba_challenge.strength);
  S2 skip nights with fewer than 5 games.
Legs: model v3 chances, price = fair x 0.95. Stage target = nba_challenge.next_x (stage_x, keep=True),
quantised up to a 5% log grid so searches cache. Predicted finish = product of picked chances (after a
loss the run is carried on as if won, for the chance only). Finished = every stage won.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", ".."))
from backtest_multis import nights  # noqa: E402
from correlation import load_jsonl  # noqa: E402
from tune import build  # noqa: E402

from melbcup import nba_challenge as ch  # noqa: E402
from melbcup.nba_legs import same_game_many, stack_for  # noqa: E402

SEASONS = ("00223", "00224")
GOALS = (250, 1000)
STAGES = (2, 3, 4, 5, 6)
MODES = ("game", "multi")
STRATS = ("S0", "S1", "S2")
START = 10.0
PAID = 1 - ch.HAIRCUT
LOOKAHEAD = 9
MIN_GAMES = 5
TAIL = 8  # start dates in a season's last TAIL game nights are dropped (the window runs past the season)
WINDOWS = (3, 5, 7)  # S0/S1/S2 are all run at 5; 3 and 7 for S0 and S1 only


def grid(x):
    return 1.05 ** math.ceil(math.log(max(x, ch.MIN_X)) / math.log(1.05) - 1e-9)


class Season:
    def __init__(self, N):
        self.N = N
        self.nights = sorted(N)
        self.legs, self.won, self.games = {}, {}, {}
        for n in self.nights:
            self.legs[n] = [g | {"event": g["game"], "price": max(1.01, round(0.95 / g["chance"], 2))}
                            for gm in N[n].values() for g in gm]
            self.won[n] = {g["label"]: g["won"] for g in self.legs[n]}
            self.games[n] = len(N[n])
        self.sg, self.cross, self.str = {}, {}, {}

    def per_game(self, n, x):
        """Each game's likeliest same-game multi reaching x: [(chance, paid price, won)]."""
        k = (n, x)
        if k not in self.sg:
            ms = same_game_many(self.legs[n], [x / PAID], 10.0)[x / PAID]
            self.sg[k] = [(m["chance"], m["price"] * PAID, all(self.won[n][p] for p in m["picks"])) for m in ms]
        return self.sg[k]

    def pick(self, n, x, mode):
        if mode == "game":
            c = self.per_game(n, x)
            return max(c, key=lambda t: t[0]) if c else None
        k = (n, x)
        if k not in self.cross:
            m = stack_for(self.legs[n], x)
            self.cross[k] = (m["chance"], m["price"], all(self.won[n][p] for p in m["picks"])) if m else None
        return self.cross[k]

    def strength(self, n, x, g):
        k = (n, x, g)
        if k not in self.str:
            self.str[k] = ch.strength([c for c, _, _ in self.per_game(n, x)], g)
        return self.str[k]


def plays(S, i, x, need, strat, jend):
    """Play night index i at stage target x? (need = stages left incl. this one; jend = last
    night index inside the window). Forced when no spare night is left."""
    n = S.nights[i]
    if strat == "S0" or jend - i + 1 <= need:
        return True
    if strat == "S2":
        return S.games[n] >= MIN_GAMES
    ch_ = [c for c, _, _ in S.per_game(n, x)]
    if not ch_:
        return False
    scored = [(ch.typical(ch_), 0, n)]
    for j in range(i + 1, min(jend, i + LOOKAHEAD - 1) + 1):
        scored.append((S.strength(n, x, S.games[S.nights[j]]), -(j - i), S.nights[j]))
    return n in [m for _, _, m in sorted(scored, reverse=True)[:need]]


def run(S, i0, goal, stages, mode, strat, window):
    """-> (finished, predicted chance, calendar nights used). The run lasts `window` calendar nights
    from the start; not finished by then = not finished (predicted 0 for those)."""
    start = S.nights[i0]
    last = ch._plus(start, window - 1)
    jend = max(j for j in range(i0, len(S.nights)) if S.nights[j] <= last)
    bank, i, alive, pred, done, used = START, i0, True, 1.0, 0, window
    while done < stages:
        left = stages - done
        x = grid(max(ch.MIN_X, ch.stage_x(bank, goal, left, done == 0)))
        p = None
        while i <= jend:
            p = S.pick(S.nights[i], x, mode) if plays(S, i, x, left, strat, jend) else None
            i += 1
            if p:
                break
        if not p:
            return False, 0.0, window
        c, price, won = p
        pred *= c
        if alive and not won:
            alive = False
            used = (datetime.fromisoformat(S.nights[i - 1]) - datetime.fromisoformat(start)).days + 1
        bank = START * (price - 1) if done == 0 else bank * price
        done += 1
    if alive:
        used = (datetime.fromisoformat(S.nights[i - 1]) - datetime.fromisoformat(start)).days + 1
    return alive, pred, used


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("history"); ap.add_argument("--step", type=int, default=2, help="every STEPth start night"); ap.add_argument("--out"); ap.add_argument("--season", help="one season only (00223 or 00224), to run seasons in parallel")
    a = ap.parse_args()
    games = [g for g in load_jsonl(a.history) if g[1] <= "00224"]
    R = build(games)
    v3 = json.load(open(os.path.join(HERE, "model_v3.json")))
    rows = []
    for season in ([a.season] if a.season else SEASONS):
        S = Season(nights(R, season, v3, 0.0))
        starts = list(range(0, len(S.nights) - TAIL, a.step))
        print(season, len(S.nights), "nights,", len(starts), "start dates", file=sys.stderr, flush=True)
        for goal in GOALS:
            for mode in MODES:
                for w in WINDOWS:
                    for strat in (STRATS if w == 5 else ("S0", "S1")):
                        for st in STAGES:
                            if st > w:
                                continue
                            rs = [run(S, i, goal, st, mode, strat, w) for i in starts]
                            n = len(rs)
                            rows.append((season, goal, mode, strat, w, st, n, 100 * sum(r[0] for r in rs) / n,
                                         sum(r[2] for r in rs) / n, 100 * sum(r[1] for r in rs) / n))
                            print(rows[-1], file=sys.stderr, flush=True)
    out = [f"NBA challenge backtest, start dates every {a.step} game nights; price = fair x 0.95, same-game x {PAID}; keep=True; per_night=1; window = calendar nights from start (nights = mean used)",
           f"{'season':6} {'goal':>5} {'mode':5} {'strat':>3} {'win':>3} {'stg':>3} {'runs':>5} {'fin%':>6} {'used':>6} {'pred%':>6}"]
    for r in rows:
        out.append(f"{r[0]:6} {r[1]:5d} {r[2]:5} {r[3]:>3} {r[4]:3d} {r[5]:3d} {r[6]:5d} {r[7]:6.1f} {r[8]:6.1f} {r[9]:6.1f}")
    text = "\n".join(out)
    print(text)
    if a.out:
        open(a.out, "w").write(text + "\n")
    if a.out:
        json.dump(rows, open(a.out.replace(".txt", ".json"), "w"))


if __name__ == "__main__":
    main()
