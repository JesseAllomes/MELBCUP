"""Do more bookmakers make the leg chances better? (owner, 2026-11-04)

    pull  BOARD.json OUT.json   snapshot US books' NBA player over/unders (The Odds API, env
                                ODDS_API_KEY: ~4 credits a game) and PointsBet, for the board's day
    score SNAP.json [...]       settle on ESPN box scores; log loss of the leg chance as: model,
                                model+PointsBet (today's blend), model+US books, model+all books

Each snapshot keeps the board it was priced with, so scoring needs no other state.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))

from melbcup import nba_legs as L  # noqa: E402
from melbcup.us_books import MARKETS, outcomes, us_books  # noqa: E402,F401


def snapshot(board: dict, key: str) -> dict:
    books = {"pb": L.live_events()} | us_books(key)
    return {"at": dt.datetime.now(dt.UTC).isoformat(), "board": board, "books": books}


def pull(board_path: str, out_path: str) -> None:
    snap = snapshot(json.loads(Path(board_path).read_text()), os.environ["ODDS_API_KEY"])
    Path(out_path).write_text(json.dumps(snap))
    print(out_path, {b: len(v) for b, v in snap["books"].items()})


def _ll(p: float, y: int) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def rows_for(snap: dict, legs_by_book: dict, box_rows: dict) -> list[dict]:
    """One row per bet the US books price: model chance, the markets, and the result."""
    from settle import settle

    us = {b: g for b, g in legs_by_book.items() if b != "pb"}
    m_us, m_pb = L.market_probs(us), L.feed_market(legs_by_book.get("pb", []))
    m_all = L.market_probs(legs_by_book)
    seen, out = set(), []
    for legs in us.values():
        for g in legs:
            key = L.bet_key(g)
            if key in seen or key not in m_us:
                continue
            seen.add(key)
            res = settle([g], box_rows)[0]["result"]
            if res == "void":
                continue
            out.append(
                {
                    "who": g["player"],
                    "y": int(res == "won"),
                    "model": g["model"],
                    "pb": m_pb.get(key),
                    "us": m_us[key],
                    "all": m_all[key],
                }
            )
    return out


def report(rows: list[dict]) -> str:
    """Log loss per way of setting the chance, and the gain of adding the US books with a rough
    95% range (players' bets grouped, since one player's lines move together)."""
    ways = {
        "model": lambda r: r["model"],
        "model+pb (now)": lambda r: L.blend(r["model"], r["pb"]),
        "model+us": lambda r: L.blend(r["model"], r["us"]),
        "model+all": lambda r: L.blend(r["model"], r["all"]),
        "us market alone": lambda r: r["us"],
    }
    n = len(rows)
    lines = [f"bets settled: {n}"]
    for name, f in ways.items():
        lines.append(f"  {name:16} log loss {sum(_ll(f(r), r['y']) for r in rows) / n:.4f}")
    by: dict = {}
    for r in rows:  # gain of all books over today's blend, per player
        d = _ll(L.blend(r["model"], r["pb"]), r["y"]) - _ll(L.blend(r["model"], r["all"]), r["y"])
        by.setdefault(r["who"], []).append(d)
    sums = [sum(v) for v in by.values()]
    mean = sum(sums) / n
    var = sum((s - mean * len(v)) ** 2 for s, v in zip(sums, by.values(), strict=True)) / n**2
    lines.append(f"  gain of all books over now: {mean:+.4f} ± {2 * math.sqrt(var):.4f} per bet")
    best = min(
        (w / 10 for w in range(11)),
        key=lambda w: sum(_ll(L.blend(r["model"], r["all"], w), r["y"]) for r in rows),
    )
    lines.append(f"  best model weight with all books: {best:.1f} (now {L.BLEND_W})")
    return "\n".join(lines)


def score(paths: list[str]) -> None:
    from settle import box

    latest: dict = {}  # one snapshot per night: the latest (closest to tip-off)
    for p in paths:
        snap = json.loads(Path(p).read_text())
        day = snap["board"]["day"]
        if day not in latest or snap["at"] > latest[day]["at"]:
            latest[day] = snap
    rows: list[dict] = []
    for day, snap in sorted(latest.items()):
        board = snap["board"]
        legs = {b: L.legs_from(evs, board)[0] for b, evs in snap["books"].items()}
        rows += rows_for(snap, legs, box(day))
    print(report(rows) if rows else "nothing settled yet")


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "pull":
        pull(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 3 and sys.argv[1] == "score":
        score(sys.argv[2:])
    else:
        sys.exit(__doc__)
