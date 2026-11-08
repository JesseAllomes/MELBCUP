# ruff: noqa: E501, E702
"""NFL same-game correlations (Gaussian copula), fitted like tools/nba/correlation.py.  Token-free.

Usage: python tools/nfl/correlation.py        (needs tools/nfl/model_props.json from props.py)
Each eligible player-game's actual count becomes a normal score through its model negative-binomial
CDF (randomised at the integer steps), z = Phi^-1(u).  The correlation of those scores is estimated by
relation inside one game: self (one player, two stats), team (two teammates), opp (a player and an
opposing player).  Fitted on 2018-2023 only; 2024 and 2025 are checked out of sample.  A pair is kept
only if |fit| >= MIN_CORR and the out-of-sample sign agrees and is at least half as large.
Writes melbcup/nfl_fit.py (PARAMS, CORR) and research/nfl/correlation.txt.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats as sps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import props as P  # noqa: E402

MIN_CORR = 0.05
SHORT = {
    "passingYards": "pyd", "completions": "cmp", "passingTouchdowns": "ptd", "interceptions": "int",
    "rushingYards": "ryd", "receivingYards": "cyd", "receptions": "rec", "scrimmageYards": "syd",
    "rushingTouchdowns": "rtd", "receivingTouchdowns": "ctd", "touchdowns": "td",
}
NAMES = list(SHORT)


def scores(rows, fits, rng):
    """{game: [(pid, team, {stat index: z})]} for every eligible player-game, plus season per game."""
    games: dict = defaultdict(dict)
    season = {}
    for si, stat in enumerate(NAMES):
        f = fits[stat]
        o = f.o
        mu = np.maximum(f.mu, 1e-6)
        phi = np.maximum(f.s0 + f.b * mu, 1.0001)
        r, p = mu / (phi - 1), 1 / phi
        lo, hi = sps.nbinom.cdf(o["x"] - 1, r, p), sps.nbinom.cdf(o["x"], r, p)
        z = sps.norm.ppf(np.clip(lo + rng.random(len(lo)) * (hi - lo), 1e-6, 1 - 1e-6))
        for j in np.flatnonzero(f.elig):
            row = rows[int(o["i"][j])]
            g = games[row["game"]]
            e = g.setdefault(row["pid"], (row["team"], {}))
            e[1][si] = float(z[j])
            season[row["game"]] = row["season"]
    return games, season


def estimate(games, season, seasons, sd):
    """{(rel, a, b): correlation} over games in `seasons` (sd: per-stat normal-score sd)."""
    n = len(NAMES)
    acc = defaultdict(lambda: [0.0, 0.0])
    for gid, players in games.items():
        if season[gid] not in seasons:
            continue
        teams = sorted({t for t, _ in players.values()})
        if len(teams) != 2:
            continue
        side = {t: [] for t in teams}
        for t, zs in players.values():
            Z = np.zeros(n); M = np.zeros(n)
            for si, z in zs.items():
                Z[si], M[si] = z, 1
            side[t].append((Z, M))
        mats = {t: (np.array([a for a, _ in v]), np.array([m for _, m in v])) for t, v in side.items()}
        for t, (Z, M) in mats.items():
            for ia in range(n):
                for ib in range(ia, n):
                    both = float((Z[:, ia] * Z[:, ib]).sum()); cnt = float((M[:, ia] * M[:, ib]).sum())
                    k = (SHORT[NAMES[ia]], SHORT[NAMES[ib]])
                    c = acc[("team", *k)]
                    c[0] += Z[:, ia].sum() * Z[:, ib].sum() - both
                    c[1] += M[:, ia].sum() * M[:, ib].sum() - cnt
                    if ia != ib:
                        c = acc[("self", *k)]; c[0] += both; c[1] += cnt
        (ZA, MA), (ZB, MB) = mats[teams[0]], mats[teams[1]]
        for ia in range(n):
            for ib in range(ia, n):
                c = acc[("opp", SHORT[NAMES[ia]], SHORT[NAMES[ib]])]
                c[0] += ZA[:, ia].sum() * ZB[:, ib].sum() + (ZA[:, ib].sum() * ZB[:, ia].sum() if ia != ib else 0)
                c[1] += MA[:, ia].sum() * MB[:, ib].sum() + (MA[:, ib].sum() * MB[:, ia].sum() if ia != ib else 0)
    short = {SHORT[s]: i for i, s in enumerate(NAMES)}
    return {k: (v[0] / v[1] / (sd[short[k[1]]] * sd[short[k[2]]]), v[1]) for k, v in acc.items() if v[1] > 200}


def main():
    rows = P.load()
    prm = json.load(open(Path(__file__).with_name("model_props.json")))
    fits = {s: P.Fit(rows, s, prm[s]["lam"], prm[s]["k_sh"]) for s in NAMES}
    games, season = scores(rows, fits, np.random.default_rng(7))
    allz = defaultdict(list)
    for gid, pl in games.items():
        if season[gid] in P.TRAIN:
            for _, zs in pl.values():
                for si, z in zs.items():
                    allz[si].append(z)
    sd = {si: float(np.std(v)) for si, v in allz.items()}
    fit = estimate(games, season, set(P.TRAIN), sd)
    oos = estimate(games, season, {P.SELECT, P.TEST}, sd)
    fwd = estimate(games, season, {P.FWD}, sd)
    keep, lines = {}, ["relation a b      fit(<=2023)  n_pairs   oos(2024-25)  fwd(2026)  kept"]
    for k in sorted(fit, key=lambda k: -abs(fit[k][0])):
        r = fit[k][0]
        o = oos.get(k, (float("nan"), 0))[0]
        w = fwd.get(k, (float("nan"), 0))[0]
        ok = abs(r) >= MIN_CORR and np.sign(o) == np.sign(r) and abs(o) >= 0.5 * abs(r)
        if ok:
            keep[k] = round(r, 3)
        if abs(r) >= 0.03 or abs(o) >= 0.05:
            lines.append(f"{k[0]:5s} {k[1]:4s} {k[2]:4s}   {r:+.3f}   {int(fit[k][1]):9d}   {o:+.3f}   {w:+.3f}   {'Y' if ok else '-'}")
    big = [k for k in fit if abs(fit[k][0]) >= MIN_CORR]
    agree = sum(np.sign(oos[k][0]) == np.sign(fit[k][0]) for k in big if k in oos)
    lines.append(f"pairs with |fit|>={MIN_CORR}: {len(big)}; same sign out of sample: {agree}")
    rr = np.array([(fit[k][0], oos[k][0]) for k in big if k in oos])
    lines.append(f"corr(fit, oos) over those pairs: {np.corrcoef(rr[:, 0], rr[:, 1])[0, 1]:.3f}; mean |oos|/|fit|: {np.mean(abs(rr[:, 1]) / abs(rr[:, 0])):.2f}")
    txt = "\n".join(lines)
    print(txt)
    (P.ROOT / "research" / "nfl").mkdir(exist_ok=True)
    (P.ROOT / "research" / "nfl" / "correlation.txt").write_text(txt + "\n")
    keys = ("lam", "k_sh", "pm", "s0", "b", "ca", "cb")
    out = ['"""Fitted NFL player-prop model parameters and same-game correlations.', "", "Generated by tools/nfl/correlation.py from tools/nfl/props.py output (data: nflverse 2018-2025;",
           "params fitted on 2018-2023). Do not edit by hand.", '"""', "", "MIN_CORR = 0.05", "PARAMS = {"]
    for s in NAMES:
        out.append(f'    "{s}": {{' + ", ".join(f'"{k}": {prm[s][k]}' for k in keys) + "},")
    out += ["}", "CORR = {"]
    for k in sorted(keep):
        out.append(f'    ("{k[0]}", "{k[1]}", "{k[2]}"): {keep[k]},')
    out += ["}", "SHORT = " + json.dumps(SHORT), ""]
    (P.ROOT / "melbcup" / "nfl_fit.py").write_text("\n".join(out))


if __name__ == "__main__":
    main()
