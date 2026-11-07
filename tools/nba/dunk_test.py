# ruff: noqa: E501, E702
"""Does the model beat real market prices? A real-price check on DunkAPI's history (owner, 2026-11-05).

    python3 tools/nba/dunk_test.py fetch HISTORY.jsonl.gz CACHE.json [--players 12 --budget 480]
    python3 tools/nba/dunk_test.py score HISTORY.jsonl.gz CACHE.json

fetch: the season's top scorers (most points in 2024-25), their last ~25 games of the regular
season, all four stats, from DunkAPI get_prop_history (10 credits per call of up to 25 games;
env DUNK_API_KEY). Every answer is cached, so no call is ever paid twice.
score: for each bet (the consensus over/under line of ~7 books, its prices and the real result),
the model's chance (v3, only games before that night) against the market's (the over/under pair
with the margin removed): log loss of model, market and blends, calibration, and what betting the
model's side cost or made at the real prices when the two disagree.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta  # noqa: F401
from zoneinfo import ZoneInfo

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from correlation import load_jsonl  # noqa: E402
from tune import STATS, build, nb_tail  # noqa: E402

SEASON = "00224"  # 2024-25: the check season, never fitted
WINDOW = ("2025-02-20", "2025-04-13")  # the regular season's last ~25 games
MARKETS = {"points": "player_points", "reboundsTotal": "player_rebounds", "assists": "player_assists", "threePointersMade": "player_threes"}
API = "https://mcp.dunkapi.com/v1/"


def _call(tool: str, body: dict) -> dict:
    req = urllib.request.Request(API + tool, data=json.dumps(body).encode(), method="POST",
                                 headers={"x-api-key": os.environ["DUNK_API_KEY"], "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def busiest(R, n: int) -> list[str]:
    idx = np.where(R["season"] == SEASON)[0]
    mins = defaultdict(float)
    for i in idx:
        mins[str(R["pid"][i])] += float(R["y_points"][i])  # the season's top scorers: lines in every market
    return [p for p, _ in sorted(mins.items(), key=lambda kv: -kv[1])[:n]]


def fetch(hist: str, cache_path: str, players: int = 12, budget: int = 480) -> None:
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    R = build([g for g in load_jsonl(hist) if g[1] <= SEASON])
    spent = 0
    for pid in busiest(R, players):
        for market in MARKETS.values():
            key = f"{pid}|{market}"
            if key in cache:
                continue
            if spent + 10 > budget:
                break
            body = {"player_id": pid, "market": market, "from_date": WINDOW[0], "to_date": WINDOW[1], "limit": 25}
            for attempt in range(4):
                try:
                    d = _call("get_prop_history", body)
                    break
                except urllib.error.HTTPError as e:
                    if e.code != 429 or attempt == 3:
                        print("stop:", e.code, e.read()[:200]); json.dump(cache, open(cache_path, "w")); return
                    time.sleep(30 * (attempt + 1))  # the free tier's rate limit
            time.sleep(7)
            cache[key] = d.get("data", d); spent += 10
            json.dump(cache, open(cache_path, "w"))
    print(f"cached {len(cache)} player-stats, about {spent} credits this run")


def _devig(over: float, under: float) -> float | None:
    def imp(a):  # American odds -> implied probability
        return 100 / (a + 100) if a > 0 else -a / (-a + 100)
    if not over or not under:
        return None
    po, pu = imp(over), imp(under)
    return po / (po + pu)


def _ll(p, y):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def _blend(m, k, w):
    lg = lambda x: math.log(min(max(x, 1e-4), 1 - 1e-4) / (1 - min(max(x, 1e-4), 1 - 1e-4)))  # noqa: E731
    return 1 / (1 + math.exp(-(w * lg(m) + (1 - w) * lg(k))))


def model_chances(R, v3):
    """{(pid, US date, stat): (mu, phi, ca, cb)}: v3's mean and spread for every 2024-25 row."""
    idx = np.where(R["season"] == SEASON)[0]
    out = {}
    for s in STATS:
        prm = v3[s]; hm, hr = prm["hl_minutes"], prm["hl_rate"]
        w, c_miss, a_opp, log_phi, ca, cb, g, c_blow, c_use = prm["theta"]
        n = R["n"][idx]; base = R[f"m{hm}"][idx]; starter = R["starter"][idx]
        role = np.where(starter > 0, R["m_start"][idx], R["m_bench"][idx]); role = np.where(np.isnan(role), base, role)
        mins = (g * role + (1 - g) * base) * (1 + c_miss * R["miss"][idx])
        mins = mins * (1 - c_blow * starter * np.minimum(np.abs(R["margin"][idx]), 25) / 10)
        rate = (n * R[f"r_{s}_{hr}"][idx] + w * R[f"car_{s}"][idx]) / (n + w) * (1 + c_use * R[f"use_{s}"][idx])
        mu = np.maximum(mins, 0) * rate * np.power(np.clip(R[f"opp_{s}"][idx], 0.5, 2.0), a_opp)
        for j, ix in enumerate(idx):
            when = datetime.fromisoformat(str(R["when"][ix]).replace("Z", "+00:00"))
            us = when.astimezone(ZoneInfo("America/New_York")).date().isoformat()  # the US game date (DST-correct)
            out[(str(R["pid"][ix]), us, s)] = (float(mu[j]), math.exp(log_phi), ca, cb)
    return out


def p_over(m, k: int) -> float:
    mu, phi, ca, cb = m
    p = float(np.clip(nb_tail(np.array([mu]), phi, k)[0], 1e-5, 1 - 1e-5))
    return 1 / (1 + math.exp(-(ca * math.log(p / (1 - p)) + cb)))


def score(hist: str, cache_path: str) -> None:
    cache = json.load(open(cache_path))
    R = build([g for g in load_jsonl(hist) if g[1] <= SEASON])
    v3 = json.load(open(os.path.join(HERE, "model_v3.json")))
    M = model_chances(R, v3)
    stat_of = {v: k for k, v in MARKETS.items()}
    rows = []
    for key, d in cache.items():
        pid, market = key.split("|"); s = stat_of[market]
        for gm in d.get("games", []):
            if gm.get("actual") is None or gm.get("line") is None:
                continue
            m = M.get((pid, gm["game_date"], s))
            k_mkt = _devig(gm.get("over_odds"), gm.get("under_odds"))
            if m is None or k_mkt is None or float(gm["line"]).is_integer():
                continue
            k = math.floor(gm["line"]) + 1
            rows.append({"stat": s, "model": p_over(m, k), "market": k_mkt, "y": int(gm["actual"] >= k),
                         "over": gm["over_odds"], "under": gm["under_odds"]})
    n = len(rows)
    if not n:
        print("nothing matched"); return
    print(f"bets: {n} (players x stats: {len(cache)}), over hit rate {sum(r['y'] for r in rows) / n:.1%}")
    for name, f in (("model", lambda r: r["model"]), ("market", lambda r: r["market"]), ("50/50 blend", lambda r: _blend(r["model"], r["market"], 0.5))):
        print(f"  {name:12} log loss {sum(_ll(f(r), r['y']) for r in rows) / n:.4f}")
    best = min((w / 10 for w in range(11)), key=lambda w: sum(_ll(_blend(r["model"], r["market"], w), r["y"]) for r in rows))
    print(f"  best model weight: {best:.1f}")
    # paired gain of the market over the model, players' bets not independent: rough 95% range
    d = [_ll(r["model"], r["y"]) - _ll(r["market"], r["y"]) for r in rows]
    mean = sum(d) / n; sd = math.sqrt(sum((x - mean) ** 2 for x in d) / (n - 1))
    print(f"  market better than model by {mean:+.4f} ± {2 * sd / math.sqrt(n):.4f} per bet")
    print("  calibration (model said -> over came in):")
    for lo in (0.0, 0.3, 0.4, 0.5, 0.6, 0.7):
        b = [r for r in rows if lo <= r["model"] < lo + (0.3 if lo == 0 else 0.1 if lo < 0.7 else 0.31)]
        if b:
            print(f"    {lo:.1f}+  n {len(b):4}  said {sum(r['model'] for r in b) / len(b):.2f}  got {sum(r['y'] for r in b) / len(b):.2f}  market said {sum(r['market'] for r in b) / len(b):.2f}")
    for edge in (0.03, 0.05, 0.08):
        bets = []
        for r in rows:
            gap = r["model"] - r["market"]
            if abs(gap) < edge:
                continue
            side_over = gap > 0
            odds = r["over"] if side_over else r["under"]
            dec = 1 + (odds / 100 if odds > 0 else 100 / -odds)
            won = r["y"] == 1 if side_over else r["y"] == 0
            bets.append(dec - 1 if won else -1)
        if bets:
            print(f"  bet the model's side when it differs by {edge:.0%}+: {len(bets)} bets, return {sum(bets) / len(bets):+.1%} a bet at real prices")


if __name__ == "__main__":
    a = sys.argv
    if len(a) >= 4 and a[1] == "fetch":
        fetch(a[2], a[3])
    elif len(a) >= 4 and a[1] == "score":
        score(a[2], a[3])
    else:
        sys.exit(__doc__)
