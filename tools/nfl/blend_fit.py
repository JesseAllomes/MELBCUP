"""Refit the NFL model/market blend weight from forward data.  Token-free (blob read + ESPN box scores).

Usage: python tools/nfl/blend_fit.py [--days 30]
Reads the PointsBet catalogue raw snapshots (blob container "nba", catalogue/raw/nfl/YYYYMMDD/HHMM.json.gz,
same BlobStore as tools/nba/daily.py; needs NBA_ACCOUNT and the AZURE_* identity env), takes each bet's
last quote before kick-off, settles it from the ESPN box score (melbcup/nfl_settle), and finds the model
weight w in sigmoid(w*logit(model) + (1-w)*logit(market)) with the lowest log loss.  Prints the result and
writes research/nfl/blend_fit.txt; it never edits BLEND_W: change melbcup/nfl_model.py by hand once the
sample is large enough (MIN_N).  Skips gracefully when the blob store is not reachable.

The raw blob keeps only a few days (catalogue RAW_KEEP_DAYS), so run it on a schedule and it appends the
settled pairs to data/nfl/blend_pairs.jsonl: the fit uses every pair collected so far.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "nba"))

PAIRS = ROOT / "data" / "nfl" / "blend_pairs.jsonl"
MIN_N = 400


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def ll_at(pairs: list[dict], w: float) -> float:
    tot = 0.0
    for g in pairs:
        p = 1 / (1 + math.exp(-(w * _logit(g["model"]) + (1 - w) * _logit(g["market"]))))
        p = min(max(p, 1e-4), 1 - 1e-4)
        tot -= math.log(p) if g["won"] else math.log(1 - p)
    return tot / len(pairs)


def fit_w(pairs: list[dict]) -> dict:
    """{"n", "w" (best on a 0.05 grid), "ll_market", "ll_model", "ll_best", "ll_prior"} or {"n"} if empty."""
    if not pairs:
        return {"n": 0}
    from melbcup import nfl_model

    grid = [i / 20 for i in range(21)]
    best = min(grid, key=lambda w: ll_at(pairs, w))
    return {"n": len(pairs), "w": best, "ll_market": ll_at(pairs, 0.0), "ll_model": ll_at(pairs, 1.0),
            "ll_best": ll_at(pairs, best), "ll_prior": ll_at(pairs, nfl_model.BLEND_W)}


def collect(store, days: int, now: datetime | None = None) -> list[dict]:
    """Settled (model, market, won) pairs from the raw snapshots: each bet's last quote before kick-off."""
    from melbcup import catalogue, nfl_legs, nfl_settle

    now = now or datetime.now(UTC)
    names = sorted(n for n in store.names("catalogue/raw/nfl/") if n.endswith(".json.gz"))
    last: dict = {}
    for n in names[-days * 24 * 4:]:
        raw = store.read(n)
        if raw is None:
            continue
        snap = json.loads(gzip.decompress(raw))
        fetched = datetime.fromisoformat(snap["built"].replace("Z", "+00:00"))
        rows = []
        for e in snap.get("events", []):
            ev = {"key": e["key"], "name": e.get("name"), "startsAt": e.get("startsAt"), "competitionName": e.get("competition")}
            rows += [r for r in catalogue.event_selections(ev, e["detail"], "nfl", fetched, fetched)[0] if r.get("is_player_prop")]
        for g in nfl_legs.legs_from_rows(rows):
            if g["model"] is not None and g["market"] is not None and g["startsAt"] and fetched.isoformat() < str(g["startsAt"]).replace("Z", "+00:00"):
                last[(g["event"], g["player"], g["stat"], g["line"], g["under"])] = g
    pairs = []
    for g in last.values():
        res = nfl_settle.settle_leg(g, now)
        if res["result"] in ("won", "lost"):
            pairs.append({"event": g["event"], "player": g["player"], "stat": g["stat"], "line": g["line"], "under": g["under"],
                          "model": g["model"], "market": g["market"], "won": res["result"] == "won"})
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    a = ap.parse_args()
    PAIRS.parent.mkdir(parents=True, exist_ok=True)
    have = [json.loads(x) for x in PAIRS.read_text().splitlines() if x] if PAIRS.exists() else []
    seen = {(p["event"], p["player"], p["stat"], p["line"], p["under"]) for p in have}
    try:
        from daily import BlobStore

        store = BlobStore(os.environ["NBA_ACCOUNT"])
        new = [p for p in collect(store, a.days) if (p["event"], p["player"], p["stat"], p["line"], p["under"]) not in seen]
    except Exception as e:  # no azure libs / no identity / no account: skip, fit what we have
        print(f"blob store not available ({e!r}): fitting the pairs already collected")
        new = []
    have += new
    if new:
        PAIRS.write_text("".join(json.dumps(p) + "\n" for p in have))
    r = fit_w(have)
    if r["n"] == 0:
        print("no settled pairs yet")
        return 0
    txt = (f"pairs {r['n']} (+{len(new)} new); log loss: market {r['ll_market']:.4f}, model {r['ll_model']:.4f}, "
           f"prior w {r['ll_prior']:.4f}, best w={r['w']:.2f} {r['ll_best']:.4f}\n"
           + ("sample too small (< %d): keep the prior weight" % MIN_N if r["n"] < MIN_N else f"suggest BLEND_W = {r['w']:.2f}"))
    print(txt)
    (ROOT / "research" / "nfl").mkdir(exist_ok=True)
    (ROOT / "research" / "nfl" / "blend_fit.txt").write_text(txt + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
