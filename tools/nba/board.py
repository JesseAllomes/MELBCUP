# ruff: noqa: E501, E702
"""NBA player board for a day's games with model v4 (v3 where v4 did not help) (owner, 2026-11-03). Token-free.

Usage: python3 tools/nba/board.py BOXDIR YYYYMMDD OUT.json
For each game on ESPN's scoreboard that day: the expected line-up (players who appeared in 2 of
the team's last 5 games, starters = who started its last game, minus anyone ESPN's injury report
lists as Out) is priced with the v3 model through the same feature code as the backtest
(tools/nba/tune.py build). Writes, per player and stat, the expected count and the model's chance
of reaching any line: chance(k) = calibrated negative-binomial tail, parameters in OUT.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import tune_v4 as V4  # noqa: E402
from tune import STATS, build, load, nb_tail  # noqa: E402

API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as r:
        return json.loads(r.read())


def chance(mu, phi, ca, cb, k):
    p = float(np.clip(nb_tail(np.array([mu]), phi, k)[0], 1e-5, 1 - 1e-5))
    return float(1 / (1 + np.exp(-(ca * np.log(p / (1 - p)) + cb))))


def make_board(games, day, scoreboard, injuries, model):
    """Price the day's fixtures; model maps stat -> hl_minutes, hl_rate, theta (v3's 9 numbers or v4's 16). games: history from tune.load (or an equivalent list), oldest first."""
    names, team_now = {}, {}
    recent = defaultdict(list)  # team -> list of (when, players) oldest first
    for when, _season, players in games:
        for t in {p["team"] for p in players}:
            recent[t].append((when, [p for p in players if p["team"] == t]))
        for p in players:
            names[p["id"]] = p.get("name"); team_now[p["id"]] = p["team"]  # a traded player counts for his latest team only
    out_names = {i["athlete"]["displayName"] for t in injuries.get("injuries", []) for i in t.get("injuries", []) if str(i.get("status", "")).lower() == "out"}
    fixtures = []
    for ev in scoreboard.get("events", []):
        comp = ev["competitions"][0]
        teams = {c["homeAway"]: c["team"]["abbreviation"] for c in comp["competitors"]}
        players = []
        for t in teams.values():
            last5 = recent[t][-5:]
            seen = defaultdict(int)
            for _, ps in last5:
                for p in ps:
                    seen[p["id"]] += 1
            starters = {p["id"] for p in (last5[-1][1] if last5 else []) if p.get("starter")}
            for pid, cnt in seen.items():
                if cnt >= 2 and team_now.get(pid) == t and names.get(pid) not in out_names:
                    players.append({"id": pid, "team": t, "starter": pid in starters, "name": names.get(pid)})
        fixtures.append((ev["date"], "upcoming", players, ev["name"], teams))
    res = {"day": day, "games": [{"name": n, "teams": t, "when": w} for w, _, _, n, t in fixtures], "params": {}, "players": []}
    if not fixtures:
        return res
    R = build(games + [(w, s, p) for w, s, p, _, _ in fixtures])
    up = np.where(R["season"] == "upcoming")[0]
    rows = {}
    for s in STATS:
        prm = model[s]; hm, hr = prm["hl_minutes"], prm["hl_rate"]
        th = np.array(prm["theta"] + V4.START[len(prm["theta"]) - V4.N3:])
        res["params"][s] = {"phi": float(np.exp(th[3])), "ca": float(th[4]), "cb": float(th[5])}
        mins, mu = V4.mean_mu(R, up, s, hm, hr, th)
        for i, ix in enumerate(up):
            r = rows.setdefault(R["pid"][ix], {"id": R["pid"][ix], "name": names.get(R["pid"][ix]), "team": R["team"][ix], "opp": R["opp"][ix],
                                               "starter": bool(R["starter"][ix]), "minutes": round(float(mins[i]), 1), "mu": {}})
            r["mu"][s] = round(float(mu[i]), 3)
    res["players"] = sorted(rows.values(), key=lambda r: (r["team"], -r["minutes"]))
    return res


def load_model():
    """Model v4 where it beat v3 (tools/nba/model_v4.json, per stat), v3 as the fallback."""
    here = os.path.dirname(__file__)
    model = json.load(open(os.path.join(here, "model_v3.json")))
    try:
        model.update(json.load(open(os.path.join(here, "model_v4.json"))))
    except (OSError, ValueError):
        pass
    return model


load_v3 = load_model  # name daily.py imports


def main():
    boxdir, day, out = sys.argv[1], sys.argv[2], sys.argv[3]
    res = make_board(load(boxdir), day, get(f"{API}/scoreboard?dates={day}"), get(f"{API}/injuries"), load_model())
    json.dump(res, open(out, "w"), indent=1)
    print(f"{day}: {len(res['games'])} games, {len(res['players'])} players priced")
    for r in res["players"][:6]:
        p = res["params"]["points"]
        print(f"  {r['team']} {r['name']:24} min {r['minutes']:5.1f} pts mu {r['mu']['points']:5.1f}  P(20+) {chance(r['mu']['points'], p['phi'], p['ca'], p['cb'], 20):.0%}")


if __name__ == "__main__":
    main()
