"""Clean the raw downloads into two datasets.

    python3 tools/sports/nba/build.py [RAW_DIR] [OUT_DIR] [GAMES_JSONL_GZ] [DUNK_CACHE_JSON]

games.csv.gz  one row per game 2007-08..2022-23: scores, open/close spread (home), open/close total,
              closing moneyline both sides (US odds, one source: the archive's line).
props.csv.gz  one row per player-stat-game, 2024-25 (DunkAPI cache): consensus line, over/under
              US odds, result, plus prior-10-game minutes and starter rate from ESPN box scores.
"""

from __future__ import annotations

import csv
import gzip
import html
import json
import os
import re
import sys
from collections import defaultdict

RAW = "/tmp/claude-0/-home-user/418442d0-6a93-5b3f-a291-37c2b3744726/scratchpad/sports/nba/raw"
SCR = "/tmp/claude-0/-home-user/418442d0-6a93-5b3f-a291-37c2b3744726/scratchpad"
GCOLS = ["season", "date", "away", "home", "away_pts", "home_pts", "ml_away", "ml_home",
         "spread_home_close", "spread_home_open", "total_close", "total_open"]
PCOLS = ["game_id", "date", "player_id", "player", "stat", "line", "over_odds", "under_odds",
         "books", "actual", "result", "min_prior10", "starter_rate10"]


def num(s: str):
    s = s.strip().lower()
    if s in ("pk", "pick"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return None


def parse_page(text: str, season: str) -> list[dict]:
    """The archive's table: two rows a game (visitor then home). Of each row's open/close pair,
    the one under ~100 is the spread (on the favourite's row), the one over is the total."""
    rows = [[html.unescape(c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
            for r in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S)]
    rows = [r for r in rows if len(r) >= 12 and r[0].isdigit() and r[2] in ("V", "H")]
    y0 = int(season[:4])
    out = []
    for a, h in zip(rows[::2], rows[1::2], strict=False):
        if a[2] != "V" or h[2] != "H" or a[0] != h[0]:
            continue
        md = int(a[0])
        mo, dy = md // 100, md % 100
        date = f"{y0 if mo >= 9 else y0 + 1}-{mo:02d}-{dy:02d}"
        try:
            ap, hp = int(a[8]), int(h[8])
        except ValueError:
            continue
        ao, ac, ho, hc = num(a[9]), num(a[10]), num(h[9]), num(h[10])
        if None in (ao, ac, ho, hc):
            continue
        tot_c, tot_o = max(ac, hc), max(ao, ho)
        if tot_c < 100 or tot_o < 100:
            continue
        # the favourite's row carries the spread (the smaller number); the other row the total
        if hc < ac:
            sp_c, sp_o = -hc, -ho if ho < 100 else None
        else:
            sp_c, sp_o = ac, ao if ao < 100 else None
        if hc < ac:
            sp_o = -ho if ho < 100 else None
        mla, mlh = num(a[11]), num(h[11])
        out.append({"season": season, "date": date, "away": a[3], "home": h[3],
                    "away_pts": ap, "home_pts": hp, "ml_away": mla, "ml_home": mlh,
                    "spread_home_close": sp_c, "spread_home_open": sp_o,
                    "total_close": tot_c, "total_open": tot_o})
    return out


def build_games(raw: str) -> list[dict]:
    games = []
    for fn in sorted(os.listdir(raw)):
        m = re.match(r"sbro_(\d{4}-\d{2})\.html$", fn)
        if m:
            games += parse_page(open(os.path.join(raw, fn), encoding="utf-8").read(), m.group(1))
    games.sort(key=lambda g: (g["date"], g["home"]))
    return games


def build_props(games_jsonl: str, dunk_json: str) -> list[dict]:
    hist = defaultdict(list)  # player id -> [(date, min, starter)]
    with gzip.open(games_jsonl, "rt") as f:
        for ln in f:
            g = json.loads(ln)
            for p in g["players"]:
                if p.get("min") is not None:
                    hist[p["id"]].append((g["gameTimeUTC"][:10], p["min"], p.get("starter")))
    for v in hist.values():
        v.sort()
    rows = []
    for d in json.load(open(dunk_json)).values():
        pid = str(d["player_id"])
        for g in d["games"]:
            if g.get("over_odds") is None or g.get("under_odds") is None or g["result"] not in (
                    "over", "under"):
                continue
            prior = [x for x in hist.get(pid, []) if x[0] < g["game_date"]][-10:]
            mp = sum(x[1] for x in prior) / len(prior) if prior else ""
            sr = sum(1 for x in prior if x[2]) / len(prior) if prior else ""
            rows.append({"game_id": g["game_id"], "date": g["game_date"], "player_id": pid,
                         "player": d["player_name"], "stat": d["stat"], "line": g["line"],
                         "over_odds": g["over_odds"], "under_odds": g["under_odds"],
                         "books": g.get("books"), "actual": g["actual"], "result": g["result"],
                         "min_prior10": mp, "starter_rate10": sr})
    return rows


def write(path: str, cols: list[str], rows: list[dict]) -> None:
    with gzip.open(path, "wt", newline="") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        w.writerows(rows)


def main(raw=RAW, out=None, games_jsonl=None, dunk=None) -> None:
    out = out or os.path.join(os.path.dirname(raw), "data")
    os.makedirs(out, exist_ok=True)
    g = build_games(raw)
    write(os.path.join(out, "games.csv.gz"), GCOLS, g)
    print("games", len(g), "seasons", len({x["season"] for x in g}))
    p = build_props(games_jsonl or f"{SCR}/nba/store/history/games.jsonl.gz",
                    dunk or f"{SCR}/dunk_cache.json")
    write(os.path.join(out, "props.csv.gz"), PCOLS, p)
    print("props", len(p))


if __name__ == "__main__":
    main(*sys.argv[1:5])
