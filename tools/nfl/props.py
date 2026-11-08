# ruff: noqa: E501, E702, E741
"""NFL player-prop stats model: data loading, EWMA means, negative-binomial chances, calibration.

Token-free.  Library plus CLI:  python tools/nfl/props.py        (fits + writes the results)
Needs data/nfl/*.csv.gz from tools/nfl/history.py.  numpy/scipy are used here only (offline);
the runtime in melbcup/nfl_model.py is pure Python.

Design (see research/sports/nfl_props.md):
  mean   EWMA of the player's earlier games (decay lam), shrunk to the role mean with k_sh games;
         optional multiplicative opponent-allowed and home/away factors, kept only if 2024 select
         log loss improves.
  dist   negative binomial with variance mu*(s0 + b*mu)  (s0 = 1 is Poisson; yards are ~ gamma-like)
  calib  logistic on the logit of the NB tail: p = sigmoid(ca*logit(tail) + cb), like NBA
  eval   synthetic lines (no historical NFL prop prices exist in free data): the median of the
         player's last 8 games + 0.5 (TD and interception bets: the 1+ line).
Splits: dev 2018-2023 (fit), select 2024, sealed test 2025, forward 2026.
"""

from __future__ import annotations

import csv
import gzip
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats as sps

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "nfl"
TRAIN, SELECT, TEST, FWD = range(2018, 2024), 2024, 2025, 2026

# stat -> (role, value fn, k mode, eligibility threshold on the EWMA mean)
# role "qb": games with >= 10 pass attempts; "off": any offensive touch.
STATS = {
    "passingYards": ("qb", lambda r: r["passing_yards"], "med", 120.0),
    "completions": ("qb", lambda r: r["completions"], "med", 12.0),
    "passingTouchdowns": ("qb", lambda r: r["passing_tds"], "med", 0.8),
    "interceptions": ("qb", lambda r: r["passing_interceptions"], 1, 0.4),
    "rushingYards": ("off", lambda r: r["rushing_yards"], "med", 15.0),
    "receivingYards": ("off", lambda r: r["receiving_yards"], "med", 25.0),
    "receptions": ("off", lambda r: r["receptions"], "med", 2.5),
    "scrimmageYards": ("off", lambda r: r["rushing_yards"] + r["receiving_yards"], "med", 35.0),
    "rushingTouchdowns": ("off", lambda r: r["rushing_tds"], 1, 0.12),
    "receivingTouchdowns": ("off", lambda r: r["receiving_tds"], 1, 0.12),
    "touchdowns": ("off", lambda r: r["rushing_tds"] + r["receiving_tds"], 1, 0.2),
}
NUM = (
    "attempts completions passing_yards passing_tds passing_interceptions carries rushing_yards "
    "rushing_tds targets receptions receiving_yards receiving_tds"
).split()
MIN_PRIOR, MEDIAN_N = 4, 8


def load(seasons=range(2018, 2027)) -> list[dict]:
    """Regular-season offensive player-games, oldest first."""
    rows = []
    for y in seasons:
        p = DATA / f"stats_player_week_{y}.csv.gz"
        if not p.exists():
            continue
        with gzip.open(p, "rt", newline="") as f:
            for r in csv.DictReader(f):
                if r["season_type"] != "REG" or r["position"] not in ("QB", "RB", "WR", "TE", "FB"):
                    continue
                d = {k: float(r[k] or 0) for k in NUM}
                if d["attempts"] + d["carries"] + d["targets"] <= 0:
                    continue
                gid = r["game_id"]
                d.update(
                    pid=r["player_id"], name=r["player_display_name"], pos=r["position"],
                    team=r["team"], opp=r["opponent_team"], season=int(r["season"]), week=int(r["week"]),
                    game=gid, home=int(gid.rsplit("_", 1)[-1] == r["team"]),
                )
                rows.append(d)
    rows.sort(key=lambda d: (d["season"], d["week"]))
    return rows


def played(role, r):
    return r["attempts"] >= 10 if role == "qb" else True


def defence_factors(rows, stat, lam_d=0.9, k_d=4.0):
    """(team, season, week) -> allowed-so-far ratio to the league mean, from games before that one."""
    _, val, _, _ = STATS[stat]
    tg = defaultdict(float)
    for r in rows:
        tg[(r["opp"], r["season"], r["week"])] += val(r)  # what team r["opp"]'s defence allowed
    league = sum(v for k, v in tg.items() if k[1] in TRAIN) / max(1, sum(1 for k in tg if k[1] in TRAIN))
    by_team = defaultdict(list)
    for (t, s, w), v in tg.items():
        by_team[t].append((s, w, v))
    out = {}
    for t, gl in by_team.items():
        S = W = 0.0
        for s, w, v in sorted(gl):
            out[(t, s, w)] = ((S + k_d * league) / (W + k_d)) / league if league else 1.0
            S, W = lam_d * S + v, lam_d * W + 1
    return out


def observations(rows, stat, lam):
    """Per eligible player-game: arrays of what was known before the game.  S, W are the EWMA sums
    (so the shrunk mean is (S + k*pm)/(W + k)); line_k is the synthetic line's k."""
    role, val, kmode, _ = STATS[stat]
    hist = defaultdict(list)  # pid -> [(value)], and EWMA state
    state = defaultdict(lambda: [0.0, 0.0])
    cols = defaultdict(list)
    for i, r in enumerate(rows):
        if not played(role, r):
            continue
        x = val(r)
        h = hist[r["pid"]]
        S, W = state[r["pid"]]
        if len(h) >= MIN_PRIOR:
            last = h[-MEDIAN_N:]
            k = 1 if kmode == 1 else int(math.floor(statistics.median(last))) + 1
            cols["i"].append(i); cols["x"].append(x); cols["S"].append(S); cols["W"].append(W)
            cols["k"].append(k); cols["season"].append(r["season"]); cols["week"].append(r["week"])
            cols["rate"].append((sum(1 for v in last if v >= k) + 1) / (len(last) + 2))
        h.append(x)
        state[r["pid"]] = [lam * S + x, lam * W + 1]
    return {k: np.array(v) for k, v in cols.items()}


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def nb_tail(mu, s0, b, k):
    """P(X >= k): negative binomial, mean mu, variance mu*(s0 + b*mu)."""
    mu = np.maximum(mu, 1e-6)
    phi = np.maximum(s0 + b * mu, 1.0001)
    r, p = mu / (phi - 1), 1 / phi
    return np.clip(sps.nbinom.sf(k - 1, r, p), 1e-5, 1 - 1e-5)


def fit_var(x, mu):
    """Least squares (x-mu)^2 = s0*mu + b*mu^2 with s0 >= 1, b >= 0."""
    y = (x - mu) ** 2
    A = np.column_stack([mu, mu * mu])
    s0, b = np.linalg.lstsq(A, y, rcond=None)[0]
    if s0 < 1 or b < 0:
        s0 = 1.0
        b = max(0.0, float(((y - mu) * mu * mu).sum() / (mu**4).sum()))
    return float(s0), float(b)


def fit_logistic(t, y, iters=50):
    """ca, cb of sigmoid(ca*logit(t) + cb) by Newton (tiny ridge towards (1, 0))."""
    z = logit(t)
    th = np.array([1.0, 0.0])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(th[0] * z + th[1])))
        g = np.array([((p - y) * z).sum(), (p - y).sum()]) + 1e-3 * (th - [1, 0])
        w = p * (1 - p)
        H = np.array([[(w * z * z).sum(), (w * z).sum()], [(w * z).sum(), w.sum()]]) + 1e-3 * np.eye(2)
        step = np.linalg.solve(H, g)
        th -= step
        if abs(step).max() < 1e-8:
            break
    return float(th[0]), float(th[1])


def calibrated(t, ca, cb):
    return 1 / (1 + np.exp(-(ca * logit(t) + cb)))


def ll(p, y):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


class Fit:
    """One stat's fitted model: shrink prior pm, variance (s0, b), calibration, optional factors."""

    def __init__(self, rows, stat, lam, k_sh, opp_beta=0.0, home=False):
        self.stat, self.lam, self.k_sh, self.opp_beta, self.use_home = stat, lam, k_sh, opp_beta, home
        self.rows = rows
        self.o = observations(rows, stat, lam)
        o = self.o
        thr = STATS[stat][3]
        # eligibility: EWMA mean (S/W) at or above the threshold
        self.mean_raw = o["S"] / o["W"]
        self.elig = self.mean_raw >= thr
        tr = self.elig & np.isin(o["season"], list(TRAIN))
        self.pm = float(o["x"][tr].mean())
        meta = [rows[i] for i in o["i"]]
        self.home_flag = np.array([m["home"] for m in meta]) * 2 - 1
        self.h = 0.0
        if home:
            hx = o["x"][tr]; hf = self.home_flag[tr]
            self.h = float(0.5 * math.log(hx[hf > 0].sum() / hx[hf < 0].sum()))
        self.opp = np.ones(len(o["x"]))
        if opp_beta:
            df = defence_factors(rows, stat)
            self.opp = np.array([df.get((m["opp"], m["season"], m["week"]), 1.0) for m in meta])
        self.mu = self._mu()
        self.s0, self.b = fit_var(o["x"][tr], self.mu[tr])
        t = nb_tail(self.mu[tr], self.s0, self.b, o["k"][tr])
        y = (o["x"][tr] >= o["k"][tr]).astype(float)
        self.ca, self.cb = fit_logistic(t, y)
        self.base_rate = float(y.mean())

    def _mu(self):
        o = self.o
        mu = (o["S"] + self.k_sh * self.pm) / (o["W"] + self.k_sh)
        return mu * self.opp**self.opp_beta * np.exp(self.h * self.home_flag)

    def score(self, seasons):
        """(n, ll model, ll constant-rate baseline, ll rolling hit-rate baseline, mean p, hit rate)."""
        o = self.o
        m = self.elig & np.isin(o["season"], list(seasons))
        if not m.any():
            return None
        y = (o["x"][m] >= o["k"][m]).astype(float)
        p = calibrated(nb_tail(self.mu[m], self.s0, self.b, o["k"][m]), self.ca, self.cb)
        return dict(n=int(m.sum()), model=ll(p, y), const=ll(np.full(len(y), self.base_rate), y),
                    rolling=ll(o["rate"][m], y), p=float(p.mean()), hit=float(y.mean()))

    def params(self):
        return dict(lam=self.lam, k_sh=self.k_sh, pm=round(self.pm, 4), s0=round(self.s0, 4), b=round(self.b, 5),
                    ca=round(self.ca, 4), cb=round(self.cb, 4), thr=STATS[self.stat][3],
                    opp_beta=self.opp_beta, home=round(self.h, 4))


GRID = [(lam, k) for lam in (0.8, 0.88, 0.94) for k in (1.0, 3.0)]


def main():
    rows = load()
    out_txt, params = [], {}
    hdr = f"{'stat':20s} {'split':8s} {'n':>6s} {'model':>7s} {'const':>7s} {'roll':>7s} {'dBase':>7s}  mean_p  hit"
    out_txt.append(hdr)
    for stat in STATS:
        # 1. hyperparameters on dev (train years only)
        best = min((Fit(rows, stat, lam, k) for lam, k in GRID), key=lambda f: f.score(TRAIN)["model"])
        lam, k = best.lam, best.k_sh
        # 2. variants, selected on 2024
        variants = {"base": best}
        variants["home"] = Fit(rows, stat, lam, k, home=True)
        variants["opp"] = Fit(rows, stat, lam, k, opp_beta=0.5)
        variants["both"] = Fit(rows, stat, lam, k, opp_beta=0.5, home=True)
        sel = {n: v.score([SELECT])["model"] for n, v in variants.items()}
        # factors are reported, not adopted: the runtime has no schedule, so it serves the base mean
        pick = "base"
        f = variants[pick]
        out_txt.append(f"-- {stat}: lam={lam} k_sh={k} variant={pick} (select ll of the variants, none adopted: " + ", ".join(f"{n} {v:.4f}" for n, v in sel.items()) + ")")
        for nm, ss in (("dev", TRAIN), ("select", [SELECT]), ("TEST", [TEST]), ("fwd", [FWD])):
            s = f.score(ss)
            if s:
                out_txt.append(f"{stat:20s} {nm:8s} {s['n']:6d} {s['model']:7.4f} {s['const']:7.4f} {s['rolling']:7.4f} {s['model'] - s['const']:+7.4f}  {s['p']:.3f}  {s['hit']:.3f}")
        params[stat] = f.params() | {"variant": pick, "base_variant_params": best.params()}
    txt = "\n".join(out_txt)
    print(txt)
    (ROOT / "research" / "nfl").mkdir(exist_ok=True)
    (ROOT / "research" / "nfl" / "props_results.txt").write_text(txt + "\n")
    (ROOT / "tools" / "nfl" / "model_props.json").write_text(json.dumps(params, indent=1))


if __name__ == "__main__":
    sys.exit(main())
