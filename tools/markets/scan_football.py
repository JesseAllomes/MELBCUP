# ruff: noqa: E501, E702, E741
"""Market predictability scan, football (owner, 2026-11-03). Token-free.

Usage: python3 tools/markets/scan_football.py CACHE_DIR
Downloads football-data.co.uk season CSVs (closing prices from many bookmakers + results) for the
main leagues, 2012-13 to 2024-25, then asks, per market and price band: does the outcome happen more
often than the margin-free price says, and would betting it at the best available price have paid?
A band only counts as an edge if it pays in BOTH halves of the seasons (2012-18 and 2019-25).
Markets: home / draw / away, over / under 2.5 goals.
"""
from __future__ import annotations

import csv
import io
import math
import os
import sys
import time
import urllib.request
from collections import defaultdict

LEAGUES = "E0 E1 E2 E3 EC SC0 SC1 SC2 SC3 D1 D2 I1 I2 SP1 SP2 F1 F2 N1 B1 P1 T1 G1".split()
SEASONS = [f"{y % 100:02d}{(y + 1) % 100:02d}" for y in range(2012, 2025)]
BANDS = [1.01, 1.2, 1.35, 1.5, 1.7, 2.0, 2.5, 3.0, 4.0, 6.0, 10.0, 1000]


def fetch(cache, season, league):
    path = os.path.join(cache, f"{season}_{league}.csv")
    if not os.path.exists(path):
        url = f"https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
                open(path, "wb").write(r.read())
        except Exception:
            return []
        time.sleep(0.3)
    raw = open(path, "rb").read().decode("latin-1")
    return list(csv.DictReader(io.StringIO(raw)))


def f(x):
    try:
        v = float(x)
        return v if v > 1.0 else None
    except (TypeError, ValueError):
        return None


def first(row, *keys):
    for k in keys:
        v = f(row.get(k))
        if v:
            return v
    return None


def band(price):
    for lo, hi in zip(BANDS, BANDS[1:], strict=False):
        if lo <= price < hi:
            return f"{lo:.2f}-{hi:.2f}" if hi < 1000 else f"{lo:.0f}+"
    return None


def main():
    cache = sys.argv[1]; os.makedirs(cache, exist_ok=True)
    # key (market, band, half) -> [n, hits, sum_implied, stake_return_best]
    agg = defaultdict(lambda: [0, 0, 0.0, 0.0])
    files = 0
    for season in SEASONS:
        half = "early" if season < "1819" else "late"
        for lg in LEAGUES:
            rows = fetch(cache, season, lg)
            if rows:
                files += 1
            for r in rows:
                res = r.get("FTR")
                if res not in ("H", "D", "A"):
                    continue
                avg = [first(r, f"AvgC{x}", f"Avg{x}", f"BbAv{x}") for x in "HDA"]
                best = [first(r, f"MaxC{x}", f"Max{x}", f"BbMx{x}") for x in "HDA"]
                if all(avg) and all(best):
                    inv = [1 / x for x in avg]; s = sum(inv)
                    for i, x in enumerate("HDA"):
                        b = band(avg[i])
                        a = agg[(f"1X2 {x}", b, half)]
                        hit = res == x
                        a[0] += 1; a[1] += hit; a[2] += inv[i] / s; a[3] += best[i] if hit else 0.0
                try:
                    goals = int(r["FTHG"]) + int(r["FTAG"])
                except (KeyError, ValueError):
                    continue
                ao = first(r, "AvgC>2.5", "Avg>2.5", "BbAv>2.5"); au = first(r, "AvgC<2.5", "Avg<2.5", "BbAv<2.5")
                bo = first(r, "MaxC>2.5", "Max>2.5", "BbMx>2.5"); bu = first(r, "MaxC<2.5", "Max<2.5", "BbMx<2.5")
                if ao and au and bo and bu:
                    s = 1 / ao + 1 / au
                    for name, avgp, bestp, hit in (("Over 2.5", ao, bo, goals > 2.5), ("Under 2.5", au, bu, goals < 2.5)):
                        a = agg[(name, band(avgp), half)]
                        a[0] += 1; a[1] += hit; a[2] += (1 / avgp) / s; a[3] += bestp if hit else 0.0
    print(f"files: {files} (league-seasons)")
    print(f"{'market':10} {'avg price':12} {'bets':>7} {'happened':>9} {'price said':>10} {'ROI best price early / late':>30}")
    keys = sorted({(m, b) for m, b, _ in agg}, key=lambda k: (k[0], BANDS[[band(x) for x in BANDS[:-1]].index(k[1])] if k[1] in [band(x) for x in BANDS[:-1]] else 0))
    edges = []
    for m, b in keys:
        e, l = agg[(m, b, "early")], agg[(m, b, "late")]
        n = e[0] + l[0]
        if n < 300:
            continue
        hit = (e[1] + l[1]) / n; imp = (e[2] + l[2]) / n
        roi_e = e[3] / e[0] - 1 if e[0] else float("nan"); roi_l = l[3] / l[0] - 1 if l[0] else float("nan")
        se = math.sqrt(hit * (1 - hit) / n)
        flag = "  <== pays in both halves" if roi_e > 0 and roi_l > 0 else ""
        if flag:
            edges.append((m, b))
        print(f"{m:10} {b:12} {n:7d} {100*hit:8.1f}% {100*imp:9.1f}%  {100*roi_e:+7.1f}% / {100*roi_l:+6.1f}%  (±{200*se:.1f} pts){flag}")
    print(f"\nbands that paid at the best price in both halves: {edges or 'none'}")


if __name__ == "__main__":
    main()
