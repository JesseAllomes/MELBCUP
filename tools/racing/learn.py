"""Learn the market-alpha tuning from the live graded-race log and write racing/tuning.json.

Token-free worker: run it from a scheduled job. Reads racing/log/<date>.jsonl (written by
melbcup/live.py as races are graded), fits the favourite-longshot exponent on the logged market
chances, shrinks it towards the frozen prior (research hold-out: 1.13-1.14) by how many races it
has seen, clamps it to melbcup.model.probability.ALPHA_RANGE, and writes the result.

  NBA_ACCOUNT=<storage account> python3 tools/racing/learn.py [--dir <local folder of .jsonl>]
  (with --dir it reads local files and writes <dir>/tuning.json instead: no Azure needed)
"""

import argparse
import json
import math
import os
import re
import sys
from datetime import UTC, datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from melbcup.model.probability import ALPHA_RANGE, MARKET_ALPHA  # noqa: E402

PRIOR_RACES = 3000  # the prior is worth this many races of evidence
MIN_RACES = 200  # below this the file just repeats the prior


def parse_log(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def usable(rows: list[dict]) -> list[list[tuple[float, bool]]]:
    """Per race: [(market chance, won)], for single-winner races with every market chance."""
    races = []
    for r in rows:
        runners = r.get("runners") or []
        if len(r.get("winners") or []) != 1 or not runners:
            continue
        if any(x.get("market") in (None, 0) for x in runners):
            continue
        races.append([(float(x["market"]), bool(x["won"])) for x in runners])
    return races


def loglik(races, alpha: float) -> float:
    total = 0.0
    for race in races:
        w = [m**alpha for m, _ in race]
        z = sum(w)
        total += sum(math.log(wi / z) for wi, (_, won) in zip(w, race, strict=True) if won)
    return total


def fit_alpha(races) -> float:
    lo, hi = 0.6, 1.8
    for _ in range(60):  # golden-section search on a concave function
        a, b = lo + (hi - lo) * 0.382, lo + (hi - lo) * 0.618
        if loglik(races, a) < loglik(races, b):
            lo = a
        else:
            hi = b
    return (lo + hi) / 2


def tuned(rows: list[dict]) -> dict:
    races = usable(rows)
    n = len(races)
    fitted = fit_alpha(races) if n >= MIN_RACES else None
    w = n / (n + PRIOR_RACES) if fitted is not None else 0.0
    alpha = (1 - w) * MARKET_ALPHA + w * (fitted if fitted is not None else MARKET_ALPHA)
    alpha = min(max(alpha, ALPHA_RANGE[0]), ALPHA_RANGE[1])
    return {
        "market_alpha": round(alpha, 4),
        "fitted_alpha": None if fitted is None else round(fitted, 4),
        "prior_alpha": MARKET_ALPHA,
        "races": n,
        "prior_races": PRIOR_RACES,
        "updated": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir")
    args = ap.parse_args()
    if args.dir:
        text = "\n".join(
            open(os.path.join(args.dir, f)).read()
            for f in sorted(os.listdir(args.dir))
            if re.fullmatch(r"\d{4}-\d\d-\d\d\.jsonl", f)
        )
        out = tuned(parse_log(text))
        with open(os.path.join(args.dir, "tuning.json"), "w") as f:
            json.dump(out, f, indent=1)
    else:
        from melbcup.nba_feed import blob_names, blob_reader
        from melbcup.push_store import blob_writer

        account, client = os.environ["NBA_ACCOUNT"], os.environ.get("AZURE_CLIENT_ID")
        read, write = blob_reader(account, client), blob_writer(account, client)
        names = [n for n in blob_names(account, client, "racing/log/") if n.endswith(".jsonl")]
        text = "\n".join((read(n) or b"").decode() for n in sorted(names))
        out = tuned(parse_log(text))
        write("racing/tuning.json", json.dumps(out, indent=1).encode())
    print(json.dumps(out))


if __name__ == "__main__":
    main()
