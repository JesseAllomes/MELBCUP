# ruff: noqa: E501, E702
"""Daily NBA run for the Azure Container Apps job melbcup-nba (owner, 2026-11-04). Token-free.

Blob container `nba` (account from NBA_ACCOUNT, managed identity from AZURE_CLIENT_ID):
  history/games.jsonl.gz   every finished regular-season game, one JSON line each:
                           {"id", "gameTimeUTC", "season", "players": [box rows]}
  <day>/board.json         the model's expected counts for that US date's games (tools/nba/board.py)
  board-latest.json        the same, for the Function's legs step (tools/nba/legs.py)
  <day>/legs.json          written by the Function (prices change all day; the last copy is kept)
  <day>/settled.jsonl      v1: that day's legs settled by name against one day's box scores
  forward.jsonl            v1, frozen 2026-11-07: legs of later games were settled against the
                           wrong game (independent review); kept unchanged as the audit record
  <day>/settled-v2.jsonl   a day's legs settled by event, written once nothing is left open
  forward-v2.jsonl         every logged leg and multi, settled by event (pending until final)
  forward-v2-reconcile.json  v1 against v2, record by record

Steps, each bounded: (1) add the last few days' finished games to the history, (2) settle
yesterday's legs, (3) build the board for today, or for the next day with games. The US date is New York's, the NBA's own calendar.
Usage: python3 daily.py [--local DIR]   (DIR stands in for the container, for a dry run)
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import os
import re
import sys
from collections import Counter, defaultdict
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from board import load_v3, make_board  # noqa: E402
from espn_history import API, game_rows, get  # noqa: E402
from settle import (  # noqa: E402
    Slate,
    multi_key,
    settle,
    settle_log,
    settle_log_v2,
    settle_one,
    us_day,
)

NY = ZoneInfo("America/New_York")
LOOKBACK_DAYS = 3
AHEAD_DAYS = 3
HISTORY = "history/games.jsonl.gz"


class LocalStore:
    """A folder that behaves like the blob container, for dry runs and tests."""

    def __init__(self, root):
        self.root = root

    def read(self, name):
        p = os.path.join(self.root, name)
        return open(p, "rb").read() if os.path.exists(p) else None

    def write(self, name, data: bytes):
        p = os.path.join(self.root, name); os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        open(p, "wb").write(data)

    def names(self, prefix):
        d = os.path.join(self.root, prefix)
        return [prefix + f for f in sorted(os.listdir(d))] if os.path.isdir(d) else []


class BlobStore:
    def __init__(self, account):
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient
        svc = BlobServiceClient(f"https://{account}.blob.core.windows.net", credential=DefaultAzureCredential())
        self.c = svc.get_container_client("nba")

    def read(self, name):
        from azure.core.exceptions import ResourceNotFoundError
        try:
            return self.c.download_blob(name, timeout=120).readall()
        except ResourceNotFoundError:
            return None

    def write(self, name, data: bytes):
        self.c.upload_blob(name, data, overwrite=True, timeout=120)

    def names(self, prefix):
        return [b.name for b in self.c.list_blobs(name_starts_with=prefix)]


def season_label(ev):
    return f"002{(int(ev['season']['year']) - 1) % 100:02d}"


def read_history(store):
    raw = store.read(HISTORY)
    if raw is None:
        raise SystemExit(f"{HISTORY} is missing: upload the history pack first")
    return [json.loads(line) for line in gzip.decompress(raw).decode().splitlines() if line]


def add_recent(store, hist, today, fetch=get):
    """Append finished regular-season games from the last LOOKBACK_DAYS US dates. Returns new games and box rows by day."""
    have = {g["id"] for g in hist}
    added, boxes = 0, {}
    for back in range(1, LOOKBACK_DAYS + 1):
        day = (today - dt.timedelta(days=back)).strftime("%Y%m%d")
        rows_day = {}
        for ev in fetch(f"{API}/scoreboard?dates={day}").get("events", []):
            if not ev.get("status", {}).get("type", {}).get("completed"):
                continue
            rows = game_rows(fetch(f"{API}/summary?event={ev['id']}"))
            for r in rows:
                rows_day[r["name"]] = r
            if ev.get("season", {}).get("type") == 2 and ev["id"] not in have and rows:
                hist.append({"id": ev["id"], "gameTimeUTC": ev["date"], "season": season_label(ev), "players": rows}); added += 1
        boxes[day] = rows_day
    if added:
        hist.sort(key=lambda g: g["gameTimeUTC"])
        store.write(HISTORY, gzip.compress("\n".join(json.dumps(g) for g in hist).encode()))
    return added, boxes


def settle_day(store, day, rows_by_name):
    """Settle every priced leg of `day` once. Returns the number of legs settled (0 if none or done)."""
    if store.read(f"{day}/settled.jsonl") is not None:
        return 0
    from legs import norm
    rows = {norm(n): r for n, r in rows_by_name.items()}
    logs = [json.loads(raw) for ag in ("pb", "sb") if (raw := store.read(f"{day}/log-{ag}.json"))]
    if not rows_by_name:
        return 0
    if logs:  # the agencies' logs: legs and multis
        done = [x for lg in logs for x in settle_log(lg, rows)]
    else:  # a day logged before the logs existed: PointsBet legs only
        raw = store.read(f"{day}/legs.json")
        if raw is None:
            return 0
        d = json.loads(raw)
        value = {(g["event"], g["label"]) for g in d.get("value_legs", []) + d.get("closed_value_legs", [])}
        done = [x | {"day": day, "agency": "pb", "kind": "leg", "value": (x["event"], x["label"]) in value} for x in settle(d.get("all_legs", []), rows)]
    body = "".join(json.dumps(x) + "\n" for x in done).encode()
    store.write(f"{day}/settled.jsonl", body)
    store.write("forward.jsonl", (store.read("forward.jsonl") or b"") + body)
    return len(done)


def logged_days(store) -> list[str]:
    return sorted({n.split("/")[0] for n in store.names("") if re.fullmatch(r"\d{8}", n.split("/")[0])})


def day_legs_v2(store, day, slate, now):
    """One logged day settled by event (settle.settle_log_v2). Legacy days (legs.json only, no
    start times) settle against that day's finished games by name, as before."""
    logs = [json.loads(raw) for ag in ("pb", "sb") if (raw := store.read(f"{day}/log-{ag}.json"))]
    if logs:
        return [x for lg in logs for x in settle_log_v2(lg, slate, now)]
    raw = store.read(f"{day}/legs.json")
    if raw is None:
        return []
    d = json.loads(raw)
    value = {(g["event"], g["label"]) for g in d.get("value_legs", []) + d.get("closed_value_legs", [])}
    return [settle_one(g, slate, now, day) | {"day": day, "agency": "pb", "kind": "leg", "value": (g["event"], g["label"]) in value}
            for g in d.get("all_legs", [])]


def _key(x):
    return (x.get("day"), x.get("agency"), x.get("kind"), x.get("event"), x.get("label") or "|".join(x.get("picks") or []), x.get("mkind"), x.get("picker"))


def reconcile(v1: list[dict], v2: list[dict]) -> dict:
    """How the event-matched settlement differs from the original forward.jsonl, record by record."""
    old = {_key(x): x["result"] for x in v1}
    c = defaultdict(int)
    for x in v2:
        was, now_ = old.get(_key(x)), x["result"]
        if was is None:
            c["new"] += 1
        elif was == now_:
            c["clean"] += 1
        elif now_ in ("pending", "unresolved"):
            c[f"was_{was}_now_{now_}"] += 1
        else:
            c[f"corrected_{was}_to_{now_}"] += 1
    c["by_result_v2"] = dict(Counter(x["result"] for x in v2))
    c["v1_records"], c["v2_records"] = len(v1), len(v2)
    return dict(c)


RECHECK_FROM_H, RECHECK_TO_H = 24, 48


def last_start(rows: list[dict], day: str) -> dt.datetime:
    starts = [x["startsAt"] for r in rows for x in [r] + (r.get("detail") or []) if x.get("startsAt")]
    if starts:
        return max(dt.datetime.fromisoformat(s.replace("Z", "+00:00")) for s in starts)
    return dt.datetime.strptime(day, "%Y%m%d").replace(tzinfo=dt.UTC) + dt.timedelta(hours=36)


def _ckey(x) -> str:
    return "|".join(str(p) for p in _key(x))


def recheck_day(store, day, kept, slate, now) -> list[dict]:
    """A frozen day is re-checked once, 24-48 h after its last game, for ESPN stat corrections.
    A changed result is appended to corrections.jsonl ({key, was, now, at, why}); the day file is
    rewritten with the new result, the first-frozen copy kept in <day>/settled-v2.orig.jsonl.
    Returns the rows to use (the corrected ones, or the frozen ones)."""
    mark = f"{day}/recheck-v2.json"
    age = now - last_start(kept, day)
    if store.read(mark) is not None or not dt.timedelta(hours=RECHECK_FROM_H) <= age < dt.timedelta(hours=RECHECK_TO_H):
        return kept
    fresh = {_ckey(x): x for x in day_legs_v2(store, day, slate, now)}
    changes, out = [], []
    for old in kept:
        new = fresh.get(_ckey(old))
        if new is None or new["result"] in ("pending", "unresolved") or new["result"] == old["result"]:
            out.append(old); continue
        changes.append({"key": _ckey(old), "was": old["result"], "now": new["result"], "at": now.isoformat(),
                        "why": f"ESPN box score changed on re-check: actual {old.get('actual')} -> {new.get('actual')}"})
        out.append(new | {"result_revision": int(old.get("result_revision", 1)) + 1})
    if changes:
        if store.read(f"{day}/settled-v2.orig.jsonl") is None:
            store.write(f"{day}/settled-v2.orig.jsonl", "".join(json.dumps(x) + "\n" for x in kept).encode())
        store.write("corrections.jsonl", (store.read("corrections.jsonl") or b"") + "".join(json.dumps(c) + "\n" for c in changes).encode())
        store.write(f"{day}/settled-v2.jsonl", "".join(json.dumps(x) + "\n" for x in out).encode())
    store.write(mark, json.dumps({"at": now.isoformat(), "changes": len(changes)}).encode())
    return out


def forward_v2(store, slate, now) -> str:
    """forward_v2_rows with the ESPN event and athlete maps (event-map.json, player-map.json)
    loaded first and saved after if settlement learned anything."""
    for name, attr in (("event-map.json", "event_map"), ("player-map.json", "player_map")):
        raw = store.read(name)
        if raw:
            getattr(slate, attr).update(json.loads(raw))
    msg = _forward_v2(store, slate, now)
    if slate.dirty:
        store.write("event-map.json", json.dumps(slate.event_map, indent=1, sort_keys=True).encode())
        store.write("player-map.json", json.dumps(slate.player_map, indent=1, sort_keys=True).encode())
    return msg


def _forward_v2(store, slate, now) -> str:
    """Rebuild forward-v2.jsonl from every logged day (a day with nothing left open is kept in
    <day>/settled-v2.jsonl and not re-fetched). forward.jsonl, the original log, is never changed;
    forward-v2-reconcile.json records what changed and why."""
    rows = []
    for day in logged_days(store):
        done = store.read(f"{day}/settled-v2.jsonl")
        if done is not None:
            kept = [json.loads(x) for x in done.decode().splitlines() if x.strip()]
            rows += recheck_day(store, day, kept, slate, now)
            continue
        got = day_legs_v2(store, day, slate, now)
        if got and not any(x["result"] in ("pending", "unresolved") for x in got):
            store.write(f"{day}/settled-v2.jsonl", "".join(json.dumps(x) + "\n" for x in got).encode())
        rows += got
    # the same bet is logged on every day its game was on the board: flag the copy logged last
    # (priced closest to the start) so a calibration or return counts each bet once
    # (a multi is the same bet by multi_key: agency + its legs' game, NY date and label)
    last = {}
    for i, x in enumerate(rows):
        if x["kind"] == "multi":
            x["multi_key"] = x.get("multi_key") or multi_key(x, x.get("agency"))
            last[("multi", x["multi_key"])] = i
        elif x.get("startsAt"):
            last[(x["agency"], x.get("game"), us_day(x["startsAt"]), x["label"])] = i
    keep = set(last.values())
    rows = [x | {"latest": i in keep or (x["kind"] == "leg" and not x.get("startsAt"))} for i, x in enumerate(rows)]
    store.write("forward-v2.jsonl", "".join(json.dumps(x) + "\n" for x in rows).encode())
    v1 = [json.loads(x) for x in (store.read("forward.jsonl") or b"").decode().splitlines() if x.strip()]
    rec = reconcile(v1, rows) | {"built": now.isoformat()}
    store.write("forward-v2-reconcile.json", json.dumps(rec, indent=1).encode())
    left = sum(x["result"] in ("pending", "unresolved") for x in rows)
    return f"forward-v2 {len(rows)} records ({left} open); "


BOOKS_TEST_UNTIL = "2026-11-08"  # US-books test (owner, 2026-11-04): ~56 Odds API credits a night


def books_snapshot(store, board, now, snap=None) -> str:
    """US books' prices next to PointsBet for the coming slate (tools/nba/books_test.py), while
    the test runs and the job has ODDS_API_KEY. Never stops the board."""
    key = os.environ.get("ODDS_API_KEY")
    if now.hour < 18:  # the morning run (22:30 UTC) only: the 06:30 UTC board run spends no credits
        return ""
    if not key or now.date().isoformat() > os.environ.get("BOOKS_TEST_UNTIL", BOOKS_TEST_UNTIL):
        return ""
    try:
        if snap is None:
            from books_test import snapshot as snap
        body = json.dumps(snap(board, key)).encode()
        store.write(f"bookstest/books-{now:%Y%m%dT%H%M}.json", body)
        return "books snapshot saved; "
    except Exception as exc:  # the Odds API down or out of credits
        return f"books snapshot failed ({type(exc).__name__}); "


def learn_racing(store) -> str:
    """Refit the racing favourite-longshot tuning from the graded-race log (tools/racing/learn.py).
    A failure here never stops the NBA run."""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "racing"))
        from learn import parse_log, tuned
        names = sorted(n for n in store.names("racing/log/") if n.endswith(".jsonl"))
        out = tuned(parse_log("\n".join((store.read(n) or b"").decode() for n in names)))
        store.write("racing/tuning.json", json.dumps(out, indent=1).encode())
        return f"racing tuning {out.get('market_alpha')} from {out.get('races', '?')} races; "
    except Exception as e:  # noqa: BLE001
        return f"racing learn skipped ({type(e).__name__}); "


MELB = ZoneInfo("Australia/Melbourne")


def weekly_refit(store, now) -> str:
    """Mondays (Melbourne): refit picker v3's lean from the settled forward log (shadow only)."""
    if now.astimezone(MELB).weekday() != 0:
        return ""
    try:
        import refit_lean
        return refit_lean.run(store, now).splitlines()[0] + "; "
    except Exception as e:  # never let the refit stop the daily job
        return f"lean refit failed ({type(e).__name__}); "


def run(store, now, fetch=get):
    today = now.astimezone(NY).date()
    seen = {}

    def cached(url):  # one ESPN call per URL per run, shared by the history and settlement steps
        if url not in seen:
            seen[url] = fetch(url)
        return seen[url]

    hist = read_history(store)
    added, boxes = add_recent(store, hist, today, cached)
    settled = forward_v2(store, Slate(cached), now)
    # the next US date with games (today, or up to AHEAD_DAYS later on a night off), so the page
    # always has the coming slate; that day's own run rebuilds it with the latest injuries
    for ahead in range(AHEAD_DAYS + 1):
        day = (today + dt.timedelta(days=ahead)).strftime("%Y%m%d")
        scoreboard = cached(f"{API}/scoreboard?dates={day}")
        if scoreboard.get("events"):
            break
    games = [(g["gameTimeUTC"], g["season"], g["players"]) for g in hist]
    board = make_board(games, day, scoreboard, cached(f"{API}/injuries"), load_v3())
    board["built"] = now.isoformat()
    body = json.dumps(board).encode()
    store.write(f"{day}/board.json", body); store.write("board-latest.json", body)
    msg = learn_racing(store) + weekly_refit(store, now) + books_snapshot(store, board, now) + settled + f"nba daily {day}: history +{added} ({len(hist)} games), board {len(board['games'])} games / {len(board['players'])} players"
    print(msg, flush=True)
    return msg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local")
    a = ap.parse_args()
    store = LocalStore(a.local) if a.local else BlobStore(os.environ["NBA_ACCOUNT"])
    run(store, dt.datetime.now(dt.UTC))


if __name__ == "__main__":
    main()
