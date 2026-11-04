# ruff: noqa: E501, E702
"""Gaussian-copula correlations between legs in one game (owner, 2026-11-04). Token-free.

Usage: python3 tools/nba/correlation.py GAMES.jsonl.gz [--fit-to 00222] [--since 00218]
Model v3 gives each player-game a mean; the actual count is turned into a normal score through the
negative-binomial CDF (randomised at the integer steps), z = Phi^-1(u). The correlation of those
scores is estimated by relation inside one game:
  self  same player, two stats          team  two teammates (same or different stats)
  opp   one player against an opponent's player
Seasons after --fit-to are never read, so the 2023-24 and 2024-25 backtests stay out of sample.
Prints the CORR dict to paste into melbcup/nba_legs.py.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from collections import defaultdict

import numpy as np
from scipy import stats as sps

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from tune import STATS, build  # noqa: E402

SHORT = {"points": "pts", "reboundsTotal": "reb", "assists": "ast", "threePointersMade": "3pm"}
SHORT_I = {SHORT[s]: i for i, s in enumerate(STATS)}


def load_jsonl(path):
    """Games as (time, season, players) from the history file, one game per line, oldest first."""
    games = []
    with gzip.open(path, "rt") as f:
        for line in f:
            d = json.loads(line)
            if d.get("players"):
                games.append((d["gameTimeUTC"], d["season"], d["players"]))
    games.sort(key=lambda g: g[0])
    return games


def expected(R, idx, s, v3):
    """Model v3's mean count for each row (predict() in tune_v3 stops at the line chances)."""
    w, c_miss, a_opp, log_phi, _ca, _cb, g, c_blow, c_use = v3[s]["theta"]
    hm, hr = v3[s]["hl_minutes"], v3[s]["hl_rate"]
    n = R["n"][idx]; base = R[f"m{hm}"][idx]; starter = R["starter"][idx]
    role = np.where(starter > 0, R["m_start"][idx], R["m_bench"][idx])
    role = np.where(np.isnan(role), base, role)
    mins = (g * role + (1 - g) * base) * (1 + c_miss * R["miss"][idx])
    mins = mins * (1 - c_blow * starter * np.minimum(np.abs(R["margin"][idx]), 25) / 10)
    rate = (n * R[f"r_{s}_{hr}"][idx] + w * R[f"car_{s}"][idx]) / (n + w)
    rate = rate * (1 + c_use * R[f"use_{s}"][idx])
    mu = np.maximum(mins, 0) * rate * np.power(np.clip(R[f"opp_{s}"][idx], 0.5, 2.0), a_opp)
    return np.maximum(mu, 1e-6), float(np.exp(log_phi))


def scores(R, idx, v3, rng):
    """{stat: normal score of each row's actual count under model v3}."""
    out = {}
    for s in STATS:
        mu, phi = expected(R, idx, s, v3)
        phi = max(phi, 1.0001); r = mu / (phi - 1); p = 1 / phi
        y = R[f"y_{s}"][idx]
        lo = sps.nbinom.cdf(y - 1, r, p); hi = sps.nbinom.cdf(y, r, p)
        u = np.clip(lo + rng.random(len(y)) * (hi - lo), 1e-6, 1 - 1e-6)
        out[s] = sps.norm.ppf(u)
    return out


def estimate(R, idx, Z):
    """{(relation, stat a, stat b): correlation} from every pair of rows in the same game."""
    tm = [str(R["team"][i]) for i in idx]
    op = [str(R["opp"][i]) for i in idx]
    game = np.array([f"{R['when'][i]}|{min(t, o)}|{max(t, o)}" for i, t, o in zip(idx, tm, op, strict=True)])
    team = np.array(tm)
    sd = {s: Z[s].std() for s in STATS}
    acc = defaultdict(lambda: [0.0, 0])
    order = np.argsort(game, kind="stable")
    gs = game[order]
    bounds = np.flatnonzero(np.r_[True, gs[1:] != gs[:-1], True])
    for lo, hi in zip(bounds[:-1], bounds[1:], strict=True):
        rows = order[lo:hi]
        if len(rows) < 4:
            continue
        mine = team[rows] == team[rows][0]
        M = np.column_stack([Z[s][rows] for s in STATS])
        A, B = M[mine], M[~mine]
        for ia, a in enumerate(STATS):
            for ib, b in enumerate(STATS):
                if ib < ia:
                    continue
                k = (SHORT[a], SHORT[b])
                for side in (A, B):
                    n = len(side)
                    both = (side[:, ia] * side[:, ib]).sum()
                    c = acc[("team", *k)]  # teammates: every ordered pair of different players
                    c[0] += side[:, ia].sum() * side[:, ib].sum() - both; c[1] += n * (n - 1)
                    if ia != ib:  # one player's two stats
                        c = acc[("self", *k)]; c[0] += both; c[1] += n
                c = acc[("opp", *k)]  # an opponent's players, both directions
                c[0] += A[:, ia].sum() * B[:, ib].sum()
                c[1] += len(A) * len(B)
                if ia != ib:
                    c[0] += A[:, ib].sum() * B[:, ia].sum(); c[1] += len(A) * len(B)
    return {k: round(v[0] / v[1] / (sd[STATS[SHORT_I[k[1]]]] * sd[STATS[SHORT_I[k[2]]]]), 3) for k, v in acc.items() if v[1] > 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("games"); ap.add_argument("--fit-to", default="00222"); ap.add_argument("--since", default="00218")
    a = ap.parse_args()
    games = [g for g in load_jsonl(a.games) if g[1] <= a.fit_to]
    R = build(games)
    v3 = json.load(open(os.path.join(HERE, "model_v3.json")))
    idx = np.where(np.array([s >= a.since for s in R["season"]]))[0]
    Z = scores(R, idx, v3, np.random.default_rng(7))
    table = estimate(R, idx, Z)
    print(f"# seasons {a.since}..{a.fit_to}, {len(idx)} player-games")
    print("CORR = {")
    for rel in ("self", "team", "opp"):
        for k in sorted(k for k in table if k[0] == rel):
            print(f'    ("{k[0]}", "{k[1]}", "{k[2]}"): {table[k]},')
    print("}")


if __name__ == "__main__":
    main()
