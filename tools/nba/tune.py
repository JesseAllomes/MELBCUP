# ruff: noqa: E501, E702
"""NBA props model v2: build features, tune on old seasons, validate, report (owner, 2026-11-03).

Usage: python3 tools/nba/tune.py BOXDIR [--tune 00214-00222] [--validate 00223] [--check 00224]
Token-free. Every feature uses only games before tip-off, except one proxy: which regulars sit out
is read from the game's box score (in real use it comes from the injury report before the game).
The sealed season (00225) is never read unless --check names it.

Model: mu = projected minutes x per-minute rate x opponent factor
  minutes = EWMA(minutes, hl_m) x (1 + c_miss x team minutes missing) x (1 - c_b2b if back-to-back)
  rate    = (n x EWMA(rate, hl_r) + w x career rate) / (n + w)
  opp     = (opponent's allowed rate / league rate) ** a_opp
  count   ~ negative binomial, variance = phi x mu (phi per stat), then a logistic calibration per stat.
Tuned by coordinate search over half-lives and Nelder-Mead over the rest, minimising log loss on the
tune seasons; the validate season picks nothing, it only reports; check is reported once.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import gzip
import json
import os
from collections import defaultdict, deque

import numpy as np
from scipy import optimize
from scipy import stats as sps

STATS = ("points", "reboundsTotal", "assists", "threePointersMade")
LINES = {"points": (10, 15, 20, 25), "reboundsTotal": (4, 6, 8, 10), "assists": (3, 5, 7), "threePointersMade": (1, 2, 3)}
HLS = (1.5, 2, 3, 5, 8, 12, 20)
MIN_HISTORY = 5


def load(boxdir):
    games = []
    for f in glob.glob(os.path.join(boxdir, "*", "*.json.gz")):
        d = json.loads(gzip.decompress(open(f, "rb").read()))
        if "players" not in d or not d["players"]:
            continue
        games.append((d["gameTimeUTC"], os.path.basename(os.path.dirname(f)), d["players"]))
    games.sort(key=lambda g: g[0])
    return games


def build(games):
    """One row per player-game with >= MIN_HISTORY prior games. Returns dict of numpy arrays.

    Entries with season "upcoming" are fixtures to price: their players carry only id, team and
    starter; they get rows (y = nan) from the state built so far and change no state. Put them
    last, in time order."""
    decay = {h: 0.5 ** (1 / h) for h in HLS}
    P = {}  # player state
    team_last = {}  # team -> date of last game
    team_recent = defaultdict(lambda: deque(maxlen=5))  # team -> deque of sets of player ids
    opp_allowed = defaultdict(lambda: {s: [0.0, 0.0] for s in STATS})  # team -> stat -> [ewma stat allowed, ewma minutes]
    league = {s: [0.0, 0.0] for s in STATS}
    team_net = defaultdict(lambda: [0.0, 0.0])  # team -> [ewma points margin, weight]
    team_tot = defaultdict(lambda: {s: 0.0 for s in STATS})  # team -> ewma team stat per game
    rows = defaultdict(list)
    for when, season, players in games:
        day = dt.datetime.fromisoformat(when.replace("Z", "+00:00")).date()
        teams = sorted({p["team"] for p in players})
        if len(teams) != 2:
            continue
        by_team = {t: [p for p in players if p["team"] == t] for t in teams}
        present = {t: {p["id"] for p in by_team[t]} for t in teams}
        miss = {}
        miss_use = {}
        b2b = {}
        for t in teams:
            regs = defaultdict(int)
            for s_ in team_recent[t]:
                for pid in s_:
                    regs[pid] += 1
            missing = 0.0
            miss_use[t] = {s_: 0.0 for s_ in STATS}
            for pid, cnt in regs.items():
                st = P.get(pid)
                if cnt >= 3 and st and pid not in present[t]:
                    missing += st["m"][8] / st["w"][8]
                    for s_ in STATS:
                        miss_use[t][s_] += st["pg"][s_] / max(team_tot[t][s_], 1e-6)
            miss[t] = missing / 240.0
            last = team_last.get(t)
            b2b[t] = 1.0 if last is not None and (day - last).days == 1 else 0.0
        for t in teams:
            opp = teams[1] if t == teams[0] else teams[0]
            for p in by_team[t]:
                st = P.get(p["id"])
                if st and st["n"] >= MIN_HISTORY:
                    rows["season"].append(season); rows["miss"].append(miss[t]); rows["b2b"].append(b2b[t]); rows["n"].append(st["n"])
                    rows["pid"].append(p["id"]); rows["team"].append(t); rows["opp"].append(opp); rows["when"].append(when)
                    for h in HLS:
                        rows[f"m{h}"].append(st["m"][h] / st["w"][h])
                    rows["starter"].append(1.0 if p.get("starter") else 0.0)
                    rows["m_start"].append(st["ms"] / st["ws"] if st["ws"] > 0.5 else np.nan)
                    rows["m_bench"].append(st["mb"] / st["wb"] if st["wb"] > 0.5 else np.nan)
                    tn, on = team_net[t], team_net[opp]
                    rows["margin"].append((tn[0] / tn[1] if tn[1] else 0.0) - (on[0] / on[1] if on[1] else 0.0))
                    for s in STATS:
                        for h in HLS:
                            rows[f"r_{s}_{h}"].append(st["r"][s][h] / st["w"][h])
                        rows[f"car_{s}"].append(st["tot"][s] / max(st["totm"], 1e-6))
                        oa = opp_allowed[opp][s]; lg = league[s]
                        rows[f"opp_{s}"].append((oa[0] / oa[1]) / (lg[0] / lg[1]) if oa[1] > 0 and lg[1] > 0 and lg[0] > 0 else 1.0)
                        rows[f"var_{s}"].append(st["sq"][s] / st["n"] - (st["sum"][s] / st["n"]) ** 2)
                        rows[f"mean_{s}"].append(st["sum"][s] / st["n"])
                        rows[f"y_{s}"].append(p.get(s, np.nan))
                        rows[f"use_{s}"].append(miss_use[t][s])
        if season == "upcoming":  # a fixture to price: no result yet, so no state update
            continue
        # update states after the game
        for t in teams:
            opp = teams[1] if t == teams[0] else teams[0]
            tm = sum(p["min"] for p in by_team[t]) or 1.0
            pts = {x: sum(q["points"] for q in by_team[x]) for x in teams}
            tn = team_net[t]; tn[0] = tn[0] * 0.9 + (pts[t] - pts[opp]); tn[1] = tn[1] * 0.9 + 1
            for s in STATS:
                tot = sum(p[s] for p in by_team[t])
                team_tot[t][s] = team_tot[t][s] * 0.9 + 0.1 * tot if team_tot[t][s] else tot
                oa = opp_allowed[opp][s]; oa[0] = oa[0] * 0.95 + tot; oa[1] = oa[1] * 0.95 + tm
                league[s][0] = league[s][0] * 0.999 + tot; league[s][1] = league[s][1] * 0.999 + tm
            for p in by_team[t]:
                st = P.setdefault(p["id"], {"n": 0, "m": {h: 0.0 for h in HLS}, "w": {h: 0.0 for h in HLS},
                                            "r": {s: {h: 0.0 for h in HLS} for s in STATS}, "tot": {s: 0.0 for s in STATS},
                                            "totm": 0.0, "sum": {s: 0.0 for s in STATS}, "sq": {s: 0.0 for s in STATS},
                                            "ms": 0.0, "ws": 0.0, "mb": 0.0, "wb": 0.0, "pg": {s: 0.0 for s in STATS}})
                k3 = 0.5 ** (1 / 3)
                if p.get("starter"):
                    st["ms"] = st["ms"] * k3 + p["min"]; st["ws"] = st["ws"] * k3 + 1
                else:
                    st["mb"] = st["mb"] * k3 + p["min"]; st["wb"] = st["wb"] * k3 + 1
                for s in STATS:
                    st["pg"][s] = st["pg"][s] * 0.8 + 0.2 * p[s] if st["n"] else p[s]
                for h in HLS:
                    k = decay[h]
                    st["m"][h] = st["m"][h] * k + p["min"]; st["w"][h] = st["w"][h] * k + 1
                    for s in STATS:
                        st["r"][s][h] = st["r"][s][h] * k + p[s] / p["min"]
                for s in STATS:
                    st["tot"][s] += p[s]; st["sum"][s] += p[s]; st["sq"][s] += p[s] ** 2
                st["totm"] += p["min"]; st["n"] += 1
            team_last[t] = day
            team_recent[t].append(present[t])
    return {k: np.array(v) for k, v in rows.items()}


def nb_tail(mu, phi, k):
    """P(X >= k) for a negative binomial with mean mu, variance phi*mu (phi>1); Poisson when phi<=1."""
    mu = np.maximum(mu, 1e-6)
    phi = np.maximum(phi, 1.0001)
    r = mu / (phi - 1); p = 1 / phi
    return sps.nbinom.sf(k - 1, r, p)


def predict(R, idx, s, hm, hr, theta):
    w, c_miss, c_b2b, a_opp, log_phi, ca, cb = theta
    n = R["n"][idx]
    mins = R[f"m{hm}"][idx] * (1 + c_miss * R["miss"][idx]) * (1 - c_b2b * R["b2b"][idx])
    rate = (n * R[f"r_{s}_{hr}"][idx] + w * R[f"car_{s}"][idx]) / (n + w)
    mu = mins * rate * np.power(np.clip(R[f"opp_{s}"][idx], 0.5, 2.0), a_opp)
    out = {}
    for k in LINES[s]:
        p = np.clip(nb_tail(mu, np.exp(log_phi), k), 1e-5, 1 - 1e-5)
        z = ca * np.log(p / (1 - p)) + cb
        out[k] = 1 / (1 + np.exp(-z))
    return out


def loss(R, idx, s, hm, hr, theta):
    pr = predict(R, idx, s, hm, hr, theta)
    tot = 0.0; n = 0
    for k, p in pr.items():
        y = R[f"y_{s}"][idx] >= k
        p = np.clip(p, 1e-5, 1 - 1e-5)
        tot += -np.sum(np.where(y, np.log(p), np.log(1 - p))); n += len(p)
    return tot / n


def v1_loss(R, idx, s):
    """The v1 model (backtest.py): EWMA hl 8 minutes x rate, dispersion from the player's own spread."""
    mu = R["m8"][idx] * R[f"r_{s}_8"][idx]
    disp = np.where(R[f"mean_{s}"][idx] > 0, R[f"var_{s}"][idx] / np.maximum(R[f"mean_{s}"][idx], 1e-6), 1.0)
    tot = 0.0; n = 0
    for k in LINES[s]:
        p = np.clip(nb_tail(mu, np.maximum(disp, 1.0001), k), 1e-4, 1 - 1e-4)
        y = R[f"y_{s}"][idx] >= k
        tot += -np.sum(np.where(y, np.log(p), np.log(1 - p))); n += len(p)
    return tot / n


def calib(R, idx, s, hm, hr, theta):
    pr = predict(R, idx, s, hm, hr, theta)
    ps = np.concatenate(list(pr.values())); ys = np.concatenate([R[f"y_{s}"][idx] >= k for k in pr])
    rows = []
    for b in range(10):
        m = (ps >= b / 10) & (ps < (b + 1) / 10)
        if m.sum() >= 200:
            rows.append(f"{b*10:2d}-{b*10+9}%: {100*ys[m].mean():5.1f}% ({m.sum()})")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("boxdir")
    ap.add_argument("--tune", default="00214-00222")
    ap.add_argument("--validate", default="00223")
    ap.add_argument("--check", default="00224")
    ap.add_argument("--sample", type=int, default=3, help="tune on every Nth row for speed")
    a = ap.parse_args()
    lo, hi = a.tune.split("-")
    games = [g for g in load(a.boxdir) if g[1] != "00225" or a.check == "00225"]
    print(f"games loaded: {len(games)}")
    R = build(games)
    season = R["season"]
    tune = np.where((season >= lo) & (season <= hi))[0][:: a.sample]
    val = np.where(season == a.validate)[0]
    chk = np.where(season == a.check)[0]
    print(f"rows: tune {len(tune)} (every {a.sample}), validate {len(val)}, check {len(chk)}")
    result = {}
    for s in STATS:
        f = lambda th, hm, hr, s=s: loss(R, tune, s, hm, hr, th)  # noqa: E731
        nm = {"method": "Nelder-Mead", "options": {"maxiter": 300, "xatol": 1e-3, "fatol": 1e-6}}
        x0 = np.array([10.0, 0.5, 0.05, 0.5, np.log(1.5), 1.0, 0.0])
        th = optimize.minimize(f, x0, args=(3, 8), **nm).x  # stage 1: shape at half-lives 3/8
        hm = min(HLS, key=lambda h: f(th, h, 8))  # stage 2: half-lives, one at a time
        hr = min(HLS, key=lambda h: f(th, hm, h))
        r = optimize.minimize(f, th, args=(hm, hr), **nm)  # stage 3: refine
        best = (r.fun, hm, hr, r.x)
        _, hm, hr, th = best
        result[s] = {"hl_minutes": hm, "hl_rate": hr, "theta": [round(float(x), 5) for x in th]}
        print(f"\n{s}: hl_minutes {hm}, hl_rate {hr}, w {th[0]:.1f}, c_miss {th[1]:.2f}, c_b2b {th[2]:.3f}, a_opp {th[3]:.2f}, phi {np.exp(th[4]):.2f}, calib a {th[5]:.2f} b {th[6]:.2f}")
        for name, idx in (("tune", tune), ("validate", val), ("check", chk)):
            if len(idx):
                print(f"  {name:8} v1 {v1_loss(R, idx, s):.4f}  v2 {loss(R, idx, s, hm, hr, th):.4f}")
        if len(chk):
            print("  calibration v2 on check:", "; ".join(calib(R, chk, s, hm, hr, th)))
    json.dump(result, open(os.path.join(os.path.dirname(__file__), "model_v2.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
