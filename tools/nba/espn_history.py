# ruff: noqa: E501
"""Past NBA box scores from ESPN's public site API, for the props backtest (owner, 2026-11-03).

Token-free. For every day of the given regular seasons: the scoreboard lists the games, then each
game's summary gives the player box score. Each finished regular-season game is saved as
OUT/<season>/<espnId>.json.gz in the compact shape tools/nba/backtest.py reads. Resumable: games
already saved are skipped. About 2 requests a second.

Usage: python3 tools/nba/espn_history.py OUT [--season 2025:2024-10-22:2025-04-13 ...]
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import os
import time
import urllib.request

API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
UA = "Mozilla/5.0 (compatible; asynymbet-backtest)"
SEASONS = ("00224:2024-10-22:2025-04-13", "00225:2025-10-21:2026-04-12")
PAUSE_S = 0.5


def get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))
    return {}


def minutes(text: str) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def made(text: str) -> int:
    try:
        return int(str(text).split("-")[0])
    except ValueError:
        return 0


def game_rows(summary: dict) -> list[dict]:
    rows = []
    for team in summary.get("boxscore", {}).get("players", []):
        for block in team.get("statistics", []):
            labels = block.get("labels") or block.get("names") or []
            idx = {k: i for i, k in enumerate(labels)}
            if "MIN" not in idx or "PTS" not in idx:
                continue
            for a in block.get("athletes", []):
                st = a.get("stats") or []
                if a.get("didNotPlay") or not st:
                    continue
                mins = minutes(st[idx["MIN"]])
                if mins <= 0:
                    continue
                rows.append({
                    "id": a["athlete"]["id"],
                    "name": a["athlete"].get("displayName"),
                    "starter": bool(a.get("starter")),
                    "min": mins,
                    "points": int(st[idx["PTS"]] or 0),
                    "reboundsTotal": int(st[idx["REB"]] or 0),
                    "assists": int(st[idx["AST"]] or 0),
                    "threePointersMade": made(st[idx["3PT"]]) if "3PT" in idx else 0,
                    "team": team.get("team", {}).get("abbreviation"),
                })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--season", action="append")
    a = ap.parse_args()
    saved = skipped = 0
    for spec in a.season or SEASONS:
        season, start, end = spec.split(":")
        folder = os.path.join(a.out, season)
        os.makedirs(folder, exist_ok=True)
        day = dt.date.fromisoformat(start)
        while day <= dt.date.fromisoformat(end):
            board = get(f"{API}/scoreboard?dates={day:%Y%m%d}")
            time.sleep(PAUSE_S)
            for ev in board.get("events", []):
                if ev.get("season", {}).get("type") != 2 or not ev.get("status", {}).get("type", {}).get("completed"):
                    continue
                path = os.path.join(folder, f"{ev['id']}.json.gz")
                if os.path.exists(path):
                    skipped += 1
                    continue
                rows = game_rows(get(f"{API}/summary?event={ev['id']}"))
                time.sleep(PAUSE_S)
                with gzip.open(path, "wt") as f:
                    json.dump({"gameTimeUTC": ev["date"], "season": season, "players": rows}, f)
                saved += 1
            day += dt.timedelta(days=1)
        print(f"{season}: saved {saved}, already had {skipped}", flush=True)


if __name__ == "__main__":
    main()
