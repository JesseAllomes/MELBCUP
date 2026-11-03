"""Read-only RaceLens snapshots for the head-to-head (owner and Damian agreed, 2026-11-03).

One GET per meeting returns every race's prediction and result, so a run fits the Function
timeout. A race is written only when its prediction or result changed, to
<date>/<meeting>/R<n>/<UTC HHMMSS>.json.gz in the `racelens` container, with the latest hash
beside it (last.sha). Before the jump the saved prediction is RaceLens' final pre-race call;
deleting a meeting on his side later loses nothing here.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import http.cookiejar
import json
import time
import urllib.parse
import urllib.request

PRED_KEYS = (
    "number",
    "name",
    "winProb",
    "placeProb",
    "marketWinProb",
    "bestOdds",
    "bestPlace",
    "fairOdds",
    "valueEdge",
    "rank",
)
REQUEST_TIMEOUT_S = 20


def client(base: str, password: str):
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )

    def req(path: str, body: dict | None = None):
        r = urllib.request.Request(
            base + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="GET" if body is None else "POST",
        )
        with opener.open(r, timeout=REQUEST_TIMEOUT_S) as resp:
            return json.loads(resp.read())

    req("/api/login", {"password": password})  # the only POST: signing in
    return req


def slim(race: dict, pred: dict | None, result: dict | None) -> dict:
    pred = pred or {}
    return {
        "race": {
            k: race.get(k)
            for k in (
                "number",
                "name",
                "startTime",
                "distance",
                "trackCondition",
                "status",
                "fieldSize",
            )
        }
        | {
            "runners": [
                {
                    "number": x.get("number"),
                    "name": x.get("name"),
                    "scratched": x.get("scratched"),
                    "odds": [o for o in x.get("odds", []) if o.get("type") == "fixed"],
                }
                for x in race.get("runners", [])
            ]
        },
        "prediction": pred
        and {
            k: pred.get(k)
            for k in ("generatedAt", "modelVersion", "summary", "betting", "dayPatternsApplied")
        }
        | {"ranked": [{k: x.get(k) for k in PRED_KEYS} for x in pred.get("ranked", [])]},
        "result": result,
    }


def snapshot_day(
    container, req, date: str, now: dt.datetime, budget_s: float = 45.0
) -> tuple[int, int]:
    """Save changed races of every `date` meeting. Returns (meetings seen, races written)."""
    deadline = time.monotonic() + budget_s
    packs = [p["id"] for p in req("/api/packs") if p["id"].startswith(date + ":")]
    # Start where the last run stopped, so a slow server still gets every meeting in turn.
    turn = int(now.timestamp() // 300) % max(len(packs), 1)
    order = packs[turn:] + packs[:turn]
    written = 0
    for pid in order:
        if time.monotonic() > deadline:
            break
        pack = req("/api/packs/" + urllib.parse.quote(pid, safe=""))
        venue = pid.split(":", 1)[1]
        for race in pack.get("races") or []:
            n = str(race.get("number"))
            data = slim(
                race, (pack.get("predictions") or {}).get(n), (pack.get("results") or {}).get(n)
            )
            key = hashlib.sha256(
                json.dumps([data["prediction"], data["result"]], sort_keys=True).encode()
            ).hexdigest()
            base = f"{date}/{venue}/R{n}"
            last = container.get_blob_client(f"{base}/last.sha")
            try:
                if last.download_blob().readall().decode() == key:
                    continue
            except Exception:  # first sight of this race
                pass
            body = gzip.compress(json.dumps(data | {"fetchedAt": now.isoformat()}).encode())
            container.get_blob_client(f"{base}/{now:%H%M%S}.json.gz").upload_blob(
                body, overwrite=True
            )
            last.upload_blob(key.encode(), overwrite=True)
            written += 1
    return len(packs), written
