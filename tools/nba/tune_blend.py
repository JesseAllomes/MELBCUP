"""Fit melbcup.nba_legs.BLEND_W by log loss on settled legs (owner, 2026-11-04).

Usage: python3 tools/nba/tune_blend.py forward.jsonl
forward.jsonl is the log tools/nba/settle.py appends to: one JSON line per settled leg with
"model" (pure model chance), "market" (de-vigged market chance, null when unpriced) and "result"
("won" / "lost" / "void"). A line may instead carry "won": 0/1. Legs with no market or a void
result are skipped. The blend is sigmoid(w*logit(model) + (1-w)*logit(market)). Token-free.
"""
from __future__ import annotations

import json
import math
import sys


def logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def load(path: str) -> list[tuple[float, float, int]]:
    rows = []
    for line in open(path):
        if not line.strip():
            continue
        x = json.loads(line)
        if x.get("model") is None or x.get("market") is None or not x.get("latest", True):
            continue
        won = x["won"] if "won" in x else {"won": 1, "lost": 0}.get(x.get("result"))
        if won is None:
            continue
        rows.append((float(x["model"]), float(x["market"]), int(won)))
    return rows


def loss(rows, w: float) -> float:
    total = 0.0
    for m, k, won in rows:
        p = 1 / (1 + math.exp(-(w * logit(m) + (1 - w) * logit(k))))
        p = min(max(p, 1e-9), 1 - 1e-9)
        total -= math.log(p if won else 1 - p)
    return total / len(rows)


def main():
    rows = load(sys.argv[1])
    if not rows:
        print("n 0: no settled legs with both a model and a market chance")
        return
    best = min((i / 100 for i in range(101)), key=lambda w: loss(rows, w))
    print(f"n {len(rows)}  best w {best:.2f}  log loss {loss(rows, best):.4f}")
    for w in (0.0, 0.5, 1.0):
        print(f"  w={w:.1f}  log loss {loss(rows, w):.4f}")


if __name__ == "__main__":
    main()
