# ruff: noqa: E501, E702
"""NBA player-prop accuracy backtest (owner, 2026-11-03). Token-free; stdlib only.

Usage: python3 tools/nba/backtest.py BOXDIR [--test-season 00225]
BOXDIR holds <season>/<gameId>.json.gz box scores (the nba-history container). Games are replayed in
date order; every prediction uses only games played before tip-off. For each player who took the
court, the chance of reaching each milestone (points 10/15/20/25, rebounds 4/6/8/10, assists 3/5/7,
threes 1/2/3) is scored against what happened, for three models:
  base    season-to-date average as a Poisson mean (the naive line)
  form    the player's own hit rate over his last 10 games (smoothed)
  model   minutes-projected rate: EWMA minutes x EWMA per-minute rate, negative binomial spread
Output: log loss and Brier per stat and model, calibration buckets for `model`, on the test season
only (earlier seasons warm up the player histories). Players who did not play are void, as at the
agencies, and are left out.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import math
import os
from collections import defaultdict

LINES = {"points": (10, 15, 20, 25), "reboundsTotal": (4, 6, 8, 10), "assists": (3, 5, 7), "threePointersMade": (1, 2, 3)}
MIN_HISTORY = 5
HALF_LIFE_GAMES = 8


def minutes(text: str | None) -> float:
    if not text or not text.startswith("PT"):
        return 0.0
    m = text[2:].split("M")
    return float(m[0] or 0) + float((m[1].rstrip("S") if len(m) > 1 else "0") or 0) / 60


def load(boxdir: str):
    """Games from <season>/<id>.json.gz: ESPN compact files (tools/nba/espn_history.py) or NBA CDN box scores."""
    games = []
    for f in glob.glob(os.path.join(boxdir, "*", "*.json.gz")):
        d = json.loads(gzip.decompress(open(f, "rb").read()))
        season = os.path.basename(os.path.dirname(f))
        rows = []
        if "players" in d:  # ESPN compact
            for p in d["players"]:
                if p["min"] > 0:
                    rows.append((p["id"], p["min"], {k: p[k] for k in LINES}))
            games.append((d["gameTimeUTC"], season, rows))
            continue
        g = d["game"]
        for side in ("homeTeam", "awayTeam"):
            for p in g[side]["players"]:
                s = p.get("statistics") or {}
                mins = minutes(s.get("minutes"))
                if p.get("played") != "1" or mins <= 0:
                    continue
                rows.append((p["personId"], mins, {k: s.get(k, 0) for k in LINES}))
        games.append((g["gameTimeUTC"], season, rows))
    games.sort()
    return games


def poisson_tail(mu: float, k: int) -> float:
    """P(X >= k), X ~ Poisson(mu)."""
    mu = max(mu, 1e-6)
    term = math.exp(-mu); cdf = term
    for i in range(1, k):
        term *= mu / i; cdf += term
    return max(0.0, min(1.0, 1 - cdf))


def negbin_tail(mu: float, var: float, k: int) -> float:
    """P(X >= k) for a negative binomial with mean mu and variance var (Poisson if var <= mu)."""
    if var <= mu * 1.02:
        return poisson_tail(mu, k)
    r = mu * mu / (var - mu); p = r / (r + mu)
    prob = p ** r; cdf = prob
    for i in range(1, k):
        prob *= (i + r - 1) / i * (1 - p); cdf += prob
    return max(0.0, min(1.0, 1 - cdf))


def ewma(values, half_life=HALF_LIFE_GAMES):
    w = 0.5 ** (1 / half_life); num = den = 0.0
    for v in values:  # oldest first
        num = num * w + v; den = den * w + 1
    return num / den if den else 0.0


def predict(hist, stat, k):
    """hist: list of (minutes, stats) before this game, oldest first."""
    vals = [s[stat] for _, s in hist]
    n = len(vals)
    base = poisson_tail(sum(vals) / n, k)
    last = vals[-10:]
    form = (sum(v >= k for v in last) + 0.5) / (len(last) + 1)
    mins = ewma([m for m, _ in hist])
    rate = ewma([s[stat] / m for m, s in hist if m > 0])
    mu = mins * rate
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / max(n - 1, 1)
    disp = var / mean if mean > 0 else 1.0
    model = negbin_tail(mu, mu * max(disp, 1.0), k)
    return {"base": base, "form": form, "model": model}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("boxdir")
    ap.add_argument("--test-season", default="00225")
    a = ap.parse_args()
    games = load(a.boxdir)
    hist = defaultdict(list)
    score = defaultdict(lambda: [0.0, 0.0, 0])  # (model, stat) -> logloss, brier, n
    calib = defaultdict(lambda: [0, 0])  # (stat, bucket) -> n, hits
    for _, season, rows in games:
        for pid, _mins, stats in rows:
            h = hist[pid]
            if season == a.test_season and len(h) >= MIN_HISTORY:
                for stat, lines in LINES.items():
                    for k in lines:
                        hit = stats[stat] >= k
                        for name, p in predict(h, stat, k).items():
                            p = min(max(p, 1e-4), 1 - 1e-4)
                            s = score[(name, stat)]
                            s[0] += -math.log(p if hit else 1 - p); s[1] += (p - hit) ** 2; s[2] += 1
                            if name == "model":
                                c = calib[(stat, min(int(p * 10), 9))]; c[0] += 1; c[1] += hit
        for pid, mins, stats in rows:  # after the game: add to history
            hist[pid].append((mins, stats))
    print(f"games: {len(games)}  test season {a.test_season}")
    for stat in LINES:
        print(f"\n{stat}")
        for name in ("base", "form", "model"):
            ll, br, n = score[(name, stat)]
            if n:
                print(f"  {name:6} log loss {ll/n:.4f}  brier {br/n:.4f}  ({n} predictions)")
        print("  calibration (model): said -> happened")
        for b in range(10):
            n, h = calib[(stat, b)]
            if n >= 50:
                print(f"    {b*10:2d}-{b*10+9}%  {100*h/n:5.1f}%  ({n})")


if __name__ == "__main__":
    main()
