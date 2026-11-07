"""Said-vs-got report on the forward log (forward.jsonl from tools/nba/daily.py). Token-free.

Usage: python3 tools/nba/forward_report.py forward.jsonl
Legs and multis, by chance bucket, per agency, per stat (legs) or kind (multis): what the model
said, what the book said (1/price) and what happened. Void rows are left out. "ret" is the return
of $1 on every row at the logged price.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict

BUCKETS = [(0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 0.7),
           (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]  # fmt: skip


def bucket(c: float) -> int:
    return next(i for i, (lo, hi) in enumerate(BUCKETS) if lo <= c < hi)


def load(path: str) -> list[dict]:
    """Records of a forward log. forward-v2 rows still open (pending, unresolved) or repeated on a
    later day's log (latest false) are left out, so each settled bet counts once."""
    with open(path) as f:
        rows = [json.loads(line) for line in f if line.strip()]
    open_ = ("pending", "unresolved")
    return [x for x in rows if x["result"] not in open_ and x.get("latest", True)]


def table(rows: list[dict]) -> list[str]:
    acc = defaultdict(lambda: [0, 0, 0.0, 0.0, 0.0])  # n, won, said, book, return
    for x in rows:
        a = acc[bucket(x["chance"])]
        a[0] += 1
        a[1] += x["result"] == "won"
        a[2] += x["chance"]
        a[3] += 1 / x["price"] if x.get("price") else 0
        a[4] += x["price"] if x["result"] == "won" else 0
    out = []
    for b in sorted(acc):
        n, w, said, book, ret = acc[b]
        lo, hi = BUCKETS[b]
        out.append(
            f"  {lo * 100:3.0f}-{min(hi, 1) * 100:3.0f}%  n {n:5d}  said {100 * said / n:5.1f}%  "
            f"book {100 * book / n:5.1f}%  got {100 * w / n:5.1f}%  ret {ret / n:5.2f}"
        )
    return out


def report(log: list[dict]) -> str:
    lines = []
    for kind, label in (("leg", "legs"), ("multi", "multis")):
        rows = [
            x
            for x in log
            if x.get("kind", "leg") == kind and x.get("result") in ("won", "lost")
        ]
        groups = {"all": rows}
        for x in rows:
            groups.setdefault(f"agency {x.get('agency', 'pb')}", []).append(x)
            if kind == "leg":
                groups.setdefault(f"stat {x['stat']}", []).append(x)
            else:
                groups.setdefault(f"kind {x.get('mkind')}", []).append(x)
        for name in sorted(groups, key=lambda k: (k != "all", k)):
            lines.append(f"{label} / {name}: {len(groups[name])} settled")
            lines += table(groups[name])
    return "\n".join(lines)


def main() -> None:
    print(report(load(sys.argv[1])))


if __name__ == "__main__":
    main()
