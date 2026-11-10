"""Weekly token-free refit of the picker's role-aware lean (picker v3, shadow).

Reads settled legs from forward-v2.jsonl (blob nba/forward-v2.jsonl, or a local path), fits one
probability shift per cell (role bucket by median points line, stat, over/under), shrunk toward 0
by n/(n+K), and writes {"cells": {"bench|points|over": shift, ...}} to blob picker/lean-v3.json.
A cell under MIN_N legs does not move (it is left out, so v3 keeps v2's lean there).
Shift convention (as in nba_legs): an over's chance is the market's minus the shift, an under's is
the market's plus it. Fitted on each bet once ("latest"), against the market chance, which is the
pre-lean number. Deterministic, stdlib only.

Usage: python3 tools/nba/refit_lean.py [forward-v2.jsonl] [--out lean-v3.json]
Without a path it reads the blob (NBA_ACCOUNT) and writes the blob.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

MIN_N = 100  # a cell with fewer settled legs does not move
K = 200.0  # shrinkage: shift = raw gap * n / (n + K)
CAP = 0.15  # no shift beyond 15 points
BLOB = "picker/lean-v3.json"
BENCH_LINE = 12  # nba_legs.BENCH_LINE (kept literal: stdlib-only)


def bucket(median):
    if median is None:
        return "?"
    return "star" if median >= 20 else "starter" if median >= BENCH_LINE else "bench"


def settled(rows):
    """Settled legs that carry a market chance, each bet once."""
    return [
        x for x in rows
        if x.get("kind") == "leg" and x.get("result") in ("won", "lost")
        and x.get("latest", True) and x.get("market") is not None
    ]


def _game(x):
    return x.get("event") or x.get("game")


def keyed(legs, all_rows=None):
    """[(cell key, day, market, won)] with each leg's role bucket from its player's median line."""
    med = {}
    for r in all_rows if all_rows is not None else legs:
        if (r.get("kind") == "leg" and r.get("stat") == "points" and not r.get("under")
                and (r.get("market") or 0) >= 0.5):
            k = (_game(r), r.get("player"))
            med[k] = max(med.get(k, 0), r.get("line") or 0)
    out = []
    for x in legs:
        b = bucket(med.get((_game(x), x.get("player"))))
        if b == "?":
            continue
        side = "under" if x.get("under") else "over"
        out.append((f"{b}|{x.get('stat')}|{side}", x.get("day"), x["market"], 1 if x["result"] == "won" else 0))
    return out


def shift(n, mean_market, wins, under):
    """Shrunk probability shift for a cell: the market's miss times n/(n+K), capped."""
    gap = (wins / n - mean_market) if under else (mean_market - wins / n)
    return max(-CAP, min(CAP, gap * n / (n + K)))


def fit(rows, min_n=MIN_N):
    """{cell: {"shift", "n", "gap"}} for cells with at least min_n settled legs."""
    cells: dict = {}
    for key, _day, m, w in keyed(settled(rows), rows):
        c = cells.setdefault(key, [0, 0.0, 0])
        c[0] += 1
        c[1] += m
        c[2] += w
    out = {}
    for key in sorted(cells):
        n, sm, wins = cells[key]
        if n < min_n:
            continue
        under = key.endswith("|under")
        out[key] = {"shift": round(shift(n, sm / n, wins, under), 4), "n": n,
                    "gap": round(wins / n - sm / n, 4)}
    return out


def loo(rows, min_n=MIN_N):
    """Leave-one-day-out: mean squared miss of the market, and of the market with the fitted lean,
    each held-out day scored with a fit that never saw it. Returns (n, mse_market, mse_lean)."""
    items = keyed(settled(rows), rows)
    n = se0 = se1 = 0
    for day in sorted({d for _, d, _, _ in items}):
        f = fit([x for x in rows if x.get("day") != day], min_n)
        for key, d, m, w in items:
            if d != day:
                continue
            s = f.get(key, {}).get("shift", 0.0)
            c = min(max(m + s if key.endswith("|under") else m - s, 0.0), 1.0)
            n += 1
            se0 += (m - w) ** 2
            se1 += (c - w) ** 2
    return n, (se0 / n if n else 0.0), (se1 / n if n else 0.0)


def build(rows, now=None, min_n=MIN_N):
    f = fit(rows, min_n)
    return {
        "built": (now or dt.datetime.now(dt.UTC)).isoformat(),
        "min_n": min_n, "k": K, "cap": CAP, "legs": len(settled(rows)),
        "cells": {k: v["shift"] for k, v in f.items()},
        "detail": f,
    }


def summary(doc, loo_res=None) -> str:
    lines = [f"lean-v3 refit: {doc['legs']} settled legs, {len(doc['cells'])} cells moved (min n {doc['min_n']}, k {doc['k']})"]
    for k, v in doc["detail"].items():
        lines.append(f"  {k:28} n {v['n']:>5}  gap {v['gap']:+.3f}  shift {v['shift']:+.3f}")
    if loo_res and loo_res[0]:
        lines.append(f"  leave-one-day-out mse over {loo_res[0]} legs: market {loo_res[1]:.4f}  with lean {loo_res[2]:.4f}")
    return "\n".join(lines)


def parse(raw):
    return [json.loads(x) for x in (raw or b"").decode().splitlines() if x.strip()]


def run(store, now=None) -> str:
    """Refit from the store's forward-v2.jsonl and write picker/lean-v3.json. Returns the summary."""
    rows = parse(store.read("forward-v2.jsonl"))
    doc = build(rows, now)
    store.write(BLOB, json.dumps(doc, indent=1, sort_keys=True).encode())
    return summary(doc, loo(rows))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.path:
        rows = parse(open(a.path, "rb").read())
        doc = build(rows)
        if a.out:
            json.dump(doc, open(a.out, "w"), indent=1, sort_keys=True)
        print(summary(doc, loo(rows)))
        return
    from daily import BlobStore
    print(run(BlobStore(os.environ["NBA_ACCOUNT"])))


if __name__ == "__main__":
    main()
