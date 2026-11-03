# ruff: noqa: E501, E702
"""Daily NBA run for the Azure Container Apps job melbcup-nba (owner, 2026-11-04). Token-free.

Blob container `nba` (account from NBA_ACCOUNT, managed identity from AZURE_CLIENT_ID):
  history/games.jsonl.gz   every finished regular-season game, one JSON line each:
                           {"id", "gameTimeUTC", "season", "players": [box rows]}
  <day>/board.json         the model's expected counts for that US date's games (tools/nba/board.py)
  board-latest.json        the same, for the Function's legs step (tools/nba/legs.py)
  <day>/legs.json          written by the Function (prices change all day; the last copy is kept)
  <day>/settled.jsonl      that day's legs settled against ESPN (tools/nba/settle.py)
  forward.jsonl            every settled leg so far: the forward test on real prices

Steps, each bounded: (1) add the last few days' finished games to the history, (2) settle
yesterday's legs, (3) build today's board. The US date is New York's, the NBA's own calendar.
Usage: python3 daily.py [--local DIR]   (DIR stands in for the container, for a dry run)
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from board import load_v3, make_board  # noqa: E402
from espn_history import API, game_rows, get  # noqa: E402
from settle import settle  # noqa: E402

NY = ZoneInfo("America/New_York")
LOOKBACK_DAYS = 3
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
    from legs import norm
    if store.read(f"{day}/settled.jsonl") is not None:
        return 0
    raw = store.read(f"{day}/legs.json")
    if raw is None or not rows_by_name:
        return 0
    d = json.loads(raw)
    value = {(g["event"], g["label"]) for g in d.get("value_legs", []) + d.get("closed_value_legs", [])}
    rows = {norm(n): r for n, r in rows_by_name.items()}
    done = [x | {"day": day, "value": (x["event"], x["label"]) in value} for x in settle(d.get("all_legs", []), rows)]
    body = "".join(json.dumps(x) + "\n" for x in done).encode()
    store.write(f"{day}/settled.jsonl", body)
    store.write("forward.jsonl", (store.read("forward.jsonl") or b"") + body)
    return len(done)


def run(store, now, fetch=get):
    today = now.astimezone(NY).date()
    hist = read_history(store)
    added, boxes = add_recent(store, hist, today, fetch)
    yday = (today - dt.timedelta(days=1)).strftime("%Y%m%d")
    settled = settle_day(store, yday, boxes.get(yday, {}))
    day = today.strftime("%Y%m%d")
    games = [(g["gameTimeUTC"], g["season"], g["players"]) for g in hist]
    board = make_board(games, day, fetch(f"{API}/scoreboard?dates={day}"), fetch(f"{API}/injuries"), load_v3())
    board["built"] = now.isoformat()
    body = json.dumps(board).encode()
    store.write(f"{day}/board.json", body); store.write("board-latest.json", body)
    msg = f"nba daily {day}: history +{added} ({len(hist)} games), settled {settled} legs of {yday}, board {len(board['games'])} games / {len(board['players'])} players"
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
