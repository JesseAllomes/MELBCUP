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

import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))
from espn_history import API, game_rows, get  # noqa: E402
from legs import norm as _norm  # noqa: E402


def norm(name: str | None) -> str:
    """Accents, Jr./III suffixes, punctuation and hyphens ignored: Karl-Anthony == Karl Anthony."""
    return _norm((name or "").replace("-", " ").replace("\u2010", " ").replace("\u2011", " "))

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


NY = ZoneInfo("America/New_York")


def us_day(starts: str) -> str:
    """The US (New York, DST-correct) date a game is played on, from its UTC start."""
    when = datetime.fromisoformat(starts.replace("Z", "+00:00"))
    return when.astimezone(NY).strftime("%Y%m%d")


def team_words(game: str) -> set[str]:
    words = re.sub(r"[^a-z0-9 ]", " ", (game or "").lower()).split()
    return {w for w in words if w not in ("at", "vs", "v")}


class Slate:
    """ESPN games, each fetched once per run. The ESPN event id is the identity: the first time a
    provider event ("<agency>:<id>") is matched to an ESPN game (US date + team names) the mapping
    goes into event_map; after that the game is read by id (summary?event=), its final state from
    the summary's own status. player_map ("<norm name>|<team>": athlete id) is learned from box
    scores. daily.forward_v2 loads and saves both (event-map.json, player-map.json)."""

    def __init__(self, fetch=get, event_map=None, player_map=None):
        self.fetch, self.days, self.byid = fetch, {}, {}
        self.event_map = {} if event_map is None else event_map
        self.player_map = {} if player_map is None else player_map
        self.dirty = False

    def scoreboard(self, day: str) -> list[dict]:
        if day not in self.days:
            self.days[day] = self.fetch(f"{API}/scoreboard?dates={day}").get("events", [])
        return self.days[day]

    def by_id(self, eid: str, hint_final: bool = False) -> dict | None:
        eid = str(eid)
        if eid not in self.byid:
            try:
                summ = self.fetch(f"{API}/summary?event={eid}")
            except Exception:  # noqa: BLE001 - ESPN down: the leg stays pending this run
                return {"id": eid, "final": False, "box": [], "teams": {}, "rows": {}}
            comp = (summ.get("header", {}).get("competitions") or [{}])[0]
            status = comp.get("status", {}).get("type") or {}
            final = bool(status["completed"]) if "completed" in status else (status.get("state") == "post" if "state" in status else hint_final)
            box_rows = game_rows(summ) if final else []
            names = {}
            for t in summ.get("boxscore", {}).get("players", []):
                tm = t.get("team", {})
                names[tm.get("abbreviation")] = team_words(" ".join(str(tm.get(k) or "") for k in ("displayName", "location", "name")))
            self.byid[eid] = {"id": eid, "final": final, "box": box_rows, "teams": names,
                              "rows": {norm(r["name"]): r for r in box_rows}}
        return self.byid[eid]

    def resolve(self, leg: dict, now: datetime | None = None) -> tuple[dict | None, str | None]:
        """(game, why). game None with why None: no ESPN game on that date yet (pending/unresolved
        by age); why set: more than one candidate, or ESPN could not be read."""
        key = f"{leg.get('agency')}:{leg['event']}" if leg.get("event") and leg.get("agency") else None
        if key and key in self.event_map:
            game = self.by_id(self.event_map[key]["espn_event"])
            return game, None
        want = team_words(leg["game"].replace("@", " "))
        hits = [e for e in self.scoreboard(us_day(leg["startsAt"]))
                if want and want <= team_words(e.get("name", ""))]
        if len(hits) > 1:
            return None, f"{len(hits)} ESPN games match {leg['game']} on {us_day(leg['startsAt'])}"
        if not hits:
            return None, None
        ev = hits[0]
        done = bool(ev.get("status", {}).get("type", {}).get("completed"))
        # a game the scoreboard shows unfinished is not fetched (final or not is read from the
        # summary only once it may be over)
        game = self.by_id(ev["id"], done) if done else {"id": str(ev["id"]), "final": False, "box": [], "teams": {}, "rows": {}}
        if key:
            self.event_map[key] = {"espn_event": str(ev["id"]), "matched_on": "date+teams", "at": (now or datetime.now(UTC)).isoformat()}
            self.dirty = True
        return game, None

    def game(self, leg: dict) -> dict | None:
        return self.resolve(leg)[0]

    def day_rows(self, day: str) -> dict:
        """Every finished game's box rows on a US date, by name (for legacy legs with no game)."""
        out = {}
        for e in self.scoreboard(day):
            if not e.get("status", {}).get("type", {}).get("completed"):
                continue
            g = self.by_id(e["id"], True)
            if g["final"]:
                out.update(g["rows"])
        return out


def _team_ok(leg_team: str, abbr: str | None, game: dict) -> bool:
    """Does the leg's team (a code like BOS or a name like Boston Celtics) fit this box team?"""
    t = (leg_team or "").strip()
    if not t:
        return True
    if t.upper() == (abbr or "").upper():
        return True
    return bool(team_words(t)) and team_words(t) <= game["teams"].get(abbr, set())


def find_player(g: dict, game: dict, slate: Slate | None = None) -> tuple[dict | None, str | None]:
    """The leg's player in this one game's box score (so on one of its two teams): by ESPN athlete
    id (on the leg, else learned in player_map), else by normalised name, narrowed by the leg's
    team when it names one. Two rows still matching: (None, why), "unresolved", never guessed."""
    box = game["box"]
    pid = str(g.get("espn_athlete") or g.get("athleteId") or "")
    if not pid and slate is not None:
        learned = {str(slate.player_map[k]) for ab in game["teams"] if (k := f"{norm(g['player'])}|{ab}") in slate.player_map}
        if len(learned) == 1:
            pid = learned.pop()
    if pid:
        by_id = [r for r in box if str(r.get("id")) == pid]
        if len(by_id) == 1:
            return by_id[0], None
    hits = [r for r in box if norm(r["name"]) == norm(g["player"])]
    team = str(g.get("team") or "")
    if team:
        fit = [r for r in hits if _team_ok(team, r.get("team"), game)]
        if hits and not fit and not any(_team_ok(team, ab, game) for ab in game["teams"]):
            fit = hits  # the leg's team text is not one we can read: do not reject on it
        if hits and not fit:
            return None, f"{g['player']} is on {hits[0].get('team')}, leg says {team}"
        hits = fit
    if len(hits) > 1:
        return None, f"ambiguous name: {len(hits)} box rows match {g['player']}"
    return (hits[0] if hits else None), None


def settle_one(g: dict, slate: Slate, now: datetime, day: str) -> dict:
    if not (g.get("startsAt") and g.get("game")):  # legacy leg: the log's own day, by name
        return settle([g], slate.day_rows(day))[0]
    start = datetime.fromisoformat(g["startsAt"].replace("Z", "+00:00"))
    if start > now:
        return g | {"result": "pending", "actual": None, "why": "not started"}
    game, why = slate.resolve(g, now)
    if why:
        return g | {"result": "unresolved", "actual": None, "why": why}
    if game is None:
        late = now - start > timedelta(hours=UNRESOLVED_AFTER_H)
        return g | {"result": "unresolved" if late else "pending", "actual": None, "why": "no matching ESPN game"}
    if not game["final"]:
        return g | {"result": "pending", "actual": None, "why": "not final", "espn_event": game["id"]}
    r, why = find_player(g, game, slate)
    if why:
        return g | {"result": "unresolved", "actual": None, "why": why, "espn_event": game["id"]}
    if r is None:
        return g | {"result": "void", "actual": None, "why": "did not play", "espn_event": game["id"]}
    out = settle([g], {norm(g["player"]): r})[0]
    pid = str(r.get("id"))
    if r.get("team"):
        if slate.player_map.get(f"{norm(r['name'])}|{r['team']}") != pid:
            slate.player_map[f"{norm(r['name'])}|{r['team']}"] = pid
            slate.dirty = True
    return out | {"espn_event": game["id"], "espn_athlete": pid, "participant_id": pid}


def leg_key(d: dict) -> tuple:
    return (d.get("game"), us_day(d["startsAt"]) if d.get("startsAt") else "", d.get("label"))


def multi_key(m: dict, agency: str | None = None) -> str:
    """Stable identity of a multi: sha1 of (agency, sorted leg keys), the same on every day it is logged."""
    keys = sorted(json.dumps(leg_key(d)) for d in m.get("detail", []))
    return hashlib.sha1(json.dumps([agency or m.get("agency"), keys]).encode()).hexdigest()


def settle_multi_v2(m: dict, slate: Slate, now: datetime, day: str) -> dict:
    """A lost leg loses the multi at once; otherwise any open leg keeps it pending; a void leg
    drops out (the price shrinks by its price); all void: void."""
    legs = [settle_one(d | {"line": d.get("line", d.get("k")), "agency": d.get("agency") or m.get("agency")}, slate, now, day) for d in m["detail"]]
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
    return m | {"detail": legs, "result": res, "price": round(price, 2), "stake_price": m["price"], "multi_key": multi_key(m)}


def settle_log_v2(log: dict, slate: Slate, now: datetime) -> list[dict]:
    ag, day = log.get("agency"), log.get("day")
    out = [settle_one(x, slate, now, day) | {"kind": "leg", "agency": ag, "day": day} for x in log.get("legs", [])]
    out += [
        settle_multi_v2(m | {"agency": m.get("agency") or ag}, slate, now, day) | {"agency": ag, "day": day, "mkind": m.get("kind"), "kind": "multi"}
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
