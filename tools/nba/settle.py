# ruff: noqa: E501, E702
"""Settle a day's NBA legs and multis against ESPN box scores; keep the forward test (owner, 2026-11-04).

Usage: python3 tools/nba/settle.py LEGS.json LOG.jsonl
LEGS.json is tools/nba/legs.py output. Every priced leg (not only the value ones) is settled, so
the log measures two things on real prices: is the model's chance honest (calibration), and would
the value legs and multis have paid at PointsBet's price. A player who did not play settles as
"void" (books refund, or remove the leg from a multi). One JSON line per leg is appended to LOG,
then the running totals are printed. Token-free.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from espn_history import API, game_rows, get  # noqa: E402
from legs import norm  # noqa: E402

FIELD = {"points": "points", "reboundsTotal": "reboundsTotal", "assists": "assists", "threePointersMade": "threePointersMade"}


def box(day: str) -> dict:
    """norm(name) -> box row, for every finished game on ESPN's US date."""
    out = {}
    for ev in get(f"{API}/scoreboard?dates={day}").get("events", []):
        if ev.get("status", {}).get("type", {}).get("completed"):
            for r in game_rows(get(f"{API}/summary?event={ev['id']}")):
                out[norm(r["name"])] = r
    return out


def settle(legs: list[dict], rows: dict) -> list[dict]:
    out = []
    for g in legs:
        r = rows.get(norm(g["player"]))
        if r is None or not r.get("min"):
            res = "void"
        else:
            over = r[FIELD[g["stat"]]] >= g["line"]
            res = "won" if over != bool(g.get("under")) else "lost"  # an under wins below the line
        out.append(g | {"result": res, "actual": None if r is None else r.get(FIELD[g["stat"]])})
    return out


def summary(log: list[dict]) -> None:
    done = [x for x in log if x["result"] != "void"]
    print(f"settled legs {len(done)} (void {len(log) - len(done)})")
    bands = defaultdict(lambda: [0, 0, 0.0, 0.0])  # n, won, model chance sum, book chance sum
    for x in done:
        b = min(int(x["chance"] * 10), 9)
        a = bands[b]; a[0] += 1; a[1] += x["result"] == "won"; a[2] += x["chance"]; a[3] += 1 / x["price"]
    print("model says / book says / happened, by model chance band:")
    for b in sorted(bands):
        n, w, m, k = bands[b]
        print(f"  {b*10:2d}-{b*10+9}%  n {n:5d}  model {100*m/n:5.1f}%  book {100*k/n:5.1f}%  happened {100*w/n:5.1f}%")
    val = [x for x in done if x.get("value")]
    if val:
        ret = sum(x["price"] for x in val if x["result"] == "won")
        print(f"value legs (single $1 each): {len(val)} bets, won {sum(x['result'] == 'won' for x in val)}, return {ret:.2f}, profit {ret - len(val):+.2f}")


def main():
    legs_path, log_path = sys.argv[1], sys.argv[2]
    d = json.load(open(legs_path))
    value = {(g["event"], g["label"]) for g in d["value_legs"]}
    allp = d.get("all_legs") or d["value_legs"]
    rows = box(d["day"])
    if not rows:
        print(f"{d['day']}: no finished games on ESPN yet"); return
    new = [x | {"day": d["day"], "value": (x["event"], x["label"]) in value} for x in settle(allp, rows)]
    with open(log_path, "a") as f:
        for x in new:
            f.write(json.dumps(x) + "\n")
    summary([json.loads(line) for line in open(log_path)])


if __name__ == "__main__":
    main()
