# ruff: noqa: E501
"""Token-free, read-only snapshot of RaceLens race predictions and results for one race day.

Damian agreed to this (owner, 2026-11-03). Only GET requests after the login. Each run saves, per race,
the prediction RaceLens holds right now (before the jump that is its final pre-race call) and the result
once one is in, so a meeting deleted later is not lost and the head-to-head can use true pre-jump calls.

Usage: RACELENS_URL=... RACELENS_PASSWORD=... python3 tools/racelens/snapshot.py --date 2026-11-05 --out DIR
Writes DIR/<date>/<meeting>/R<n>/<UTC HHMMSS>.json.gz only when the race's prediction or result changed,
plus DIR/<date>/packs.json. Never prints the URL or password.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import http.cookiejar
import json
import os
import pathlib
import sys
import urllib.parse
import urllib.request

PRED_KEYS = ("number", "name", "winProb", "placeProb", "marketWinProb", "bestOdds", "bestPlace", "fairOdds", "valueEdge", "rank")


def client(base: str, password: str):
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def req(path: str, body=None):
        r = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                   headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
        return json.loads(op.open(r, timeout=60).read())

    req("/api/login", {"password": password})  # the only POST: signing in
    return req


def slim(r: dict) -> dict:
    race, pred, res = r.get("race") or {}, r.get("prediction") or {}, r.get("result")
    return {
        "race": {k: race.get(k) for k in ("number", "name", "startTime", "distance", "trackCondition", "status", "fieldSize")}
        | {"runners": [{"number": x.get("number"), "name": x.get("name"), "scratched": x.get("scratched"),
                        "odds": [o for o in x.get("odds", []) if o.get("type") == "fixed"]} for x in race.get("runners", [])]},
        "prediction": pred and {k: pred.get(k) for k in ("generatedAt", "modelVersion", "summary", "betting", "dayPatternsApplied")}
        | {"ranked": [{k: x.get(k) for k in PRED_KEYS} for x in pred.get("ranked", [])]},
        "result": res,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    base, pw = os.environ.get("RACELENS_URL", "").rstrip("/"), os.environ.get("RACELENS_PASSWORD", "")
    if not base or not pw:
        print("RACELENS_URL and RACELENS_PASSWORD must be set", file=sys.stderr)
        return 2
    req = client(base, pw)
    now = dt.datetime.now(dt.UTC)
    day = pathlib.Path(a.out) / a.date
    day.mkdir(parents=True, exist_ok=True)
    packs = [p for p in req("/api/packs") if p["id"].startswith(a.date + ":")]
    (day / "packs.json").write_text(json.dumps(packs, indent=1))
    saved = 0
    for p in packs:
        q = urllib.parse.quote(p["id"], safe="")
        pack = req(f"/api/packs/{q}")
        for race in pack.get("races") or []:
            n = race.get("number") or race.get("raceNumber")
            folder = day / p["id"].split(":", 1)[1] / f"R{n}"
            try:
                data = slim(req(f"/api/packs/{q}/races/{n}"))
            except Exception as e:  # one race failing must not stop the rest
                print(f"{p['id']} R{n}: {type(e).__name__}", file=sys.stderr)
                continue
            key = hashlib.sha256(json.dumps([data["prediction"], data["result"]], sort_keys=True).encode()).hexdigest()
            stamp = folder / "last.sha"
            if stamp.exists() and stamp.read_text() == key:
                continue
            folder.mkdir(parents=True, exist_ok=True)
            with gzip.open(folder / f"{now:%H%M%S}.json.gz", "wt") as f:
                json.dump(data | {"fetchedAt": now.isoformat()}, f)
            stamp.write_text(key)
            saved += 1
    print(f"{a.date}: {len(packs)} meetings, {saved} race snapshots saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
