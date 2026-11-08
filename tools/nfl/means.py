"""Refresh the NFL player means the app reads: data/nfl/means.json.  Token-free, no API keys.

Refresh (weekly in season, e.g. Tuesday after Monday night):
    python tools/nfl/history.py            # re-download the current season from nflverse
    python tools/nfl/means.py              # EWMA mean per player and stat -> data/nfl/means.json
Parameters come from melbcup/nfl_fit.py (fitted by tools/nfl/props.py + correlation.py).
A player is listed when he has a game in the last LIVE_WEEKS weeks of the data and enough history.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import props as P  # noqa: E402

from melbcup import nfl_fit  # noqa: E402
from melbcup.nba_legs import norm  # noqa: E402

LIVE_WEEKS = 4
OUT = ROOT / "data" / "nfl" / "means.json"


def build(rows) -> dict:
    last = max((r["season"], r["week"]) for r in rows)
    live = {r["pid"] for r in rows if r["season"] == last[0] and r["week"] > last[1] - LIVE_WEEKS}
    who = {}
    for r in rows:
        who[r["pid"]] = r  # the newest row wins: team, position, name
    players: dict = defaultdict(lambda: {"mu": {}})
    for stat, (role, val, _, thr) in P.STATS.items():
        prm = nfl_fit.PARAMS[stat]
        S, W, n = defaultdict(float), defaultdict(float), defaultdict(int)
        for r in rows:
            if P.played(role, r):
                S[r["pid"]] = prm["lam"] * S[r["pid"]] + val(r)
                W[r["pid"]] = prm["lam"] * W[r["pid"]] + 1
                n[r["pid"]] += 1
        for pid in live:
            if n[pid] < P.MIN_PRIOR or S[pid] / W[pid] < 0.7 * thr:
                continue
            r = who[pid]
            e = players[norm(r["name"])]
            e.update(name=r["name"], team=r["team"], pos=r["pos"])
            e["mu"][stat] = round((S[pid] + prm["k_sh"] * prm["pm"]) / (W[pid] + prm["k_sh"]), 3)
    return {
        "asof": f"{last[0]} week {last[1]}",
        "built": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
        "players": dict(sorted(players.items())),
    }


def main() -> None:
    d = build(P.load())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(d, separators=(",", ":")))
    print(f"{len(d['players'])} players, as of {d['asof']} -> {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
