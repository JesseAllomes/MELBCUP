"""NBA box-score history for the props backtest (owner, 2026-11-03). Token-free.

Each run downloads the next batch of past regular-season box scores from the NBA's public CDN
(it answers from Australia, not from US cloud ranges) into the `nba-history` container as
<season>/<gameId>.json.gz. Progress lives in progress.json, so a run that stops early loses
nothing; games the CDN does not have are recorded and skipped.
"""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.request

SEASONS = ("00224", "00225")  # 2024-25 and 2025-26 regular seasons (game ids 0022400001..)
GAMES_PER_SEASON = 1230
URL = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
TIMEOUT_S = 5
BATCH = 60


def game_ids():
    for season in SEASONS:
        for n in range(1, GAMES_PER_SEASON + 1):
            yield season, f"{season}{n:05d}"


def fetch(gid: str) -> bytes | None:
    req = urllib.request.Request(URL.format(gid=gid), headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return None
        raise


def run_batch(container, budget_s: float = 45.0) -> dict:
    """Download up to BATCH missing games within budget_s. Returns the updated progress."""
    deadline = time.monotonic() + budget_s
    prog_blob = container.get_blob_client("progress.json")
    try:
        progress = json.loads(prog_blob.download_blob().readall())
    except Exception:  # first run
        progress = {"next": 0, "saved": 0, "missing": []}
    ids = list(game_ids())
    done = 0
    while progress["next"] < len(ids) and done < BATCH and time.monotonic() < deadline:
        season, gid = ids[progress["next"]]
        body = fetch(gid)
        if body is None:
            progress["missing"].append(gid)
        else:
            container.get_blob_client(f"{season}/{gid}.json.gz").upload_blob(
                gzip.compress(body), overwrite=True
            )
            progress["saved"] += 1
        progress["next"] += 1
        done += 1
    progress["finished"] = progress["next"] >= len(ids)
    prog_blob.upload_blob(json.dumps(progress).encode(), overwrite=True)
    return progress
