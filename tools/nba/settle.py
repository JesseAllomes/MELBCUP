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
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta

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


# --- event-matched settlement (independent review, 2026-11-07) ---------------------------------
# A day's log holds the bookmaker's whole board, which runs a day or two ahead. Settling every leg
# against that one day's box scores by player name gave later games' legs an earlier game's result
# (1,492 legs) or a false void (6,397). Now a leg with a start time and game is settled only
# against its own game: the ESPN game on its US date whose teams match, and only once that game is
# final. Not started or not final: "pending". Final, but no matching game after 12 hours:
# "unresolved". Final and the player is not in the box score: "void" (did not play).
UNRESOLVED_AFTER_H = 12


def us_day(starts: str) -> str:
    when = datetime.fromisoformat(starts.replace("Z", "+00:00"))
    return (when - timedelta(hours=5)).strftime("%Y%m%d")  # the US evening the game is played


def team_words(game: str) -> set[str]:
    words = re.sub(r"[^a-z0-9 ]", " ", (game or "").lower()).split()
    return {w for w in words if w not in ("at", "vs", "v")}


class Slate:
    """ESPN's games by US date, each fetched once per run; box scores only for finished games."""

    def __init__(self, fetch=get):
        self.fetch, self.days = fetch, {}

    def games(self, day: str) -> list[dict]:
        if day not in self.days:
            out = []
            for ev in self.fetch(f"{API}/scoreboard?dates={day}").get("events", []):
                final = bool(ev.get("status", {}).get("type", {}).get("completed"))
                rows = {norm(r["name"]): r for r in game_rows(self.fetch(f"{API}/summary?event={ev['id']}"))} if final else {}
                out.append({"id": str(ev.get("id")), "words": team_words(ev.get("name", "")), "final": final, "rows": rows})
            self.days[day] = out
        return self.days[day]

    def game(self, leg: dict) -> dict | None:
        want = team_words(leg["game"].replace("@", " "))
        hits = [g for g in self.games(us_day(leg["startsAt"])) if want and want <= g["words"]]
        return hits[0] if len(hits) == 1 else None

    def day_rows(self, day: str) -> dict:
        """Every finished game's box rows on a US date, by name (for legacy legs with no game)."""
        return {n: r for g in self.games(day) if g["final"] for n, r in g["rows"].items()}


def settle_one(g: dict, slate: Slate, now: datetime, day: str) -> dict:
    if not (g.get("startsAt") and g.get("game")):  # legacy leg: the log's own day, by name
        return settle([g], slate.day_rows(day))[0]
    start = datetime.fromisoformat(g["startsAt"].replace("Z", "+00:00"))
    if start > now:
        return g | {"result": "pending", "actual": None, "why": "not started"}
    game = slate.game(g)
    if game is None:
        late = now - start > timedelta(hours=UNRESOLVED_AFTER_H)
        return g | {"result": "unresolved" if late else "pending", "actual": None, "why": "no matching ESPN game"}
    if not game["final"]:
        return g | {"result": "pending", "actual": None, "why": "not final", "espn_event": game["id"]}
    r = game["rows"].get(norm(g["player"]))
    if r is None:
        return g | {"result": "void", "actual": None, "why": "did not play", "espn_event": game["id"]}
    out = settle([g], {norm(g["player"]): r})[0]
    return out | {"espn_event": game["id"]}


def settle_multi_v2(m: dict, slate: Slate, now: datetime, day: str) -> dict:
    """A lost leg loses the multi at once; otherwise any open leg keeps it pending; a void leg
    drops out (the price shrinks by its price); all void: void."""
    legs = [settle_one(d | {"line": d.get("line", d.get("k"))}, slate, now, day) for d in m["detail"]]
    res_of = [d["result"] for d in legs]
    price = m["price"]
    if "lost" in res_of:
        res = "lost"
    elif any(r in ("pending", "unresolved") for r in res_of):
        res = "pending"
    elif all(r == "void" for r in res_of):
        res = "void"
    else:
        res = "won"
        for d in legs:
            if d["result"] == "void" and d.get("price"):
                price /= d["price"]
    return m | {"detail": legs, "result": res, "price": round(price, 2), "stake_price": m["price"]}


def settle_log_v2(log: dict, slate: Slate, now: datetime) -> list[dict]:
    ag, day = log.get("agency"), log.get("day")
    out = [settle_one(x, slate, now, day) | {"kind": "leg", "agency": ag, "day": day} for x in log.get("legs", [])]
    out += [
        settle_multi_v2(m, slate, now, day) | {"agency": ag, "day": day, "mkind": m.get("kind"), "kind": "multi"}
        for m in log.get("multis", [])
    ]
    return out


def settle_multi(m: dict, rows: dict) -> dict:
    """A multi wins only if every leg wins; one lost leg loses it. A void leg is dropped (the price
    shrinks by that leg's price); if every leg is void the multi is void."""
    legs = settle([d | {"line": d.get("line", d.get("k"))} for d in m["detail"]], rows)
    live = [d for d in legs if d["result"] != "void"]
    if not live:
        res, price = "void", m["price"]
    else:
        res = "won" if all(d["result"] == "won" for d in live) else "lost"
        price = m["price"]
        for d in legs:
            if d["result"] == "void" and d.get("price"):
                price /= d["price"]
    return m | {"detail": legs, "result": res, "price": round(price, 2), "stake_price": m["price"]}


def settle_log(log: dict, rows: dict) -> list[dict]:
    """Settle one agency's day log ({"agency", "day", "legs", "multis"}) into forward-log rows."""
    ag, day = log.get("agency"), log.get("day")
    out = [x | {"kind": "leg", "agency": ag, "day": day} for x in settle(log.get("legs", []), rows)]
    out += [
        settle_multi(m, rows) | {"agency": ag, "day": day, "mkind": m.get("kind"), "kind": "multi"}
        for m in log.get("multis", [])
    ]
    return out


def summary(log: list[dict]) -> None:
    log = [x for x in log if x.get("kind", "leg") == "leg"]
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
