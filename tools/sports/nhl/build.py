"""Clean the raw downloads into one dataset.

    python3 tools/sports/nhl/build.py [RAW_DIR] [OUT_DIR]

games.csv.gz  one row per game (regular season and playoffs): final score, how it ended (REG, OT,
              SO, from the NHL API), open/close moneyline (US odds), puck line (home side's line and
              both prices; 2014-15 onward only), open/close total with over/under prices.
              Odds are one source (the archive's line), not a best-of-books max.
"""

from __future__ import annotations

import csv
import glob
import gzip
import html
import json
import os
import re
import sys

RAW = "/tmp/claude-0/-home-user/418442d0-6a93-5b3f-a291-37c2b3744726/scratchpad/sports/nhl/raw"
COLS = ["season", "date", "game_id", "gtype", "away", "home", "away_g", "home_g", "ended",
        "ml_away", "ml_home", "ml_away_open", "ml_home_open", "pl_home", "pl_home_odds",
        "pl_away_odds", "total", "over_odds", "under_odds", "total_open"]

# archive team name -> franchise code; API codes that moved are folded in by canon()
TEAMS = {
    "anaheim": "ANA", "arizona": "ARI", "arizonas": "ARI", "phoenix": "ARI", "utah": "ARI",
    "atlanta": "WPG", "winnipeg": "WPG", "winnipegjets": "WPG", "boston": "BOS",
    "buffalo": "BUF", "calgary": "CGY", "carolina": "CAR", "chicago": "CHI", "colorado": "COL",
    "columbus": "CBJ", "dallas": "DAL", "detroit": "DET", "edmonton": "EDM", "florida": "FLA",
    "losangeles": "LAK", "minnesota": "MIN", "montreal": "MTL", "nyislanders": "NYI",
    "nyrangers": "NYR", "nashville": "NSH", "newjersey": "NJD", "ottawa": "OTT",
    "philadelphia": "PHI", "pittsburgh": "PIT", "sanjose": "SJS", "st.louis": "STL",
    "stlouis": "STL", "tampa": "TBL", "tampabay": "TBL", "toronto": "TOR", "vancouver": "VAN",
    "vegas": "VGK", "washington": "WSH", "seattle": "SEA", "seattlekraken": "SEA",
}
API_FOLD = {"PHX": "ARI", "UTA": "ARI", "ATL": "WPG", "TBL": "TBL", "T.B": "TBL", "L.A": "LAK",
            "N.J": "NJD", "S.J": "SJS"}


def canon(code: str) -> str:
    return API_FOLD.get(code, code)


def team(name: str) -> str | None:
    return TEAMS.get(re.sub(r"\s+", "", name).lower())


def num(s: str):
    s = s.strip().lower()
    if s in ("pk", "pick"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return None


def iso(season: str, mmdd: int) -> str:
    y0 = int(season[:4])
    mo, dy = mmdd // 100, mmdd % 100
    # the 2019-20 bubble finished in September; 2020-21 started in January
    late = mo >= 10 or (mo == 9 and season != "2019-20")
    return f"{y0 if late else y0 + 1}-{mo:02d}-{dy:02d}"


def parse_page(text: str, season: str) -> list[dict]:
    """Table: two rows a game (visitor then home). 14 cells (2007-14): no puck line; 16 cells
    (2014-15 on): puck line, its price, open total+price, close total+price. Over price sits on the
    visitor row, under price on the home row."""
    rows = [[html.unescape(c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
            for r in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S)]
    rows = [r for r in rows if len(r) in (14, 16) and r[0].isdigit() and r[2] in ("V", "H")]
    out = []
    for a, h in zip(rows[::2], rows[1::2], strict=False):
        if a[2] != "V" or h[2] != "H" or a[0] != h[0] or len(a) != len(h):
            continue
        ta, th = team(a[3]), team(h[3])
        try:
            ag, hg = int(a[7]), int(h[7])
        except ValueError:
            continue
        if ta is None or th is None:
            continue
        g = {"season": season, "date": iso(season, int(a[0])), "away": ta, "home": th,
             "away_g": ag, "home_g": hg, "ml_away_open": num(a[8]), "ml_home_open": num(h[8]),
             "ml_away": num(a[9]), "ml_home": num(h[9]), "pl_home": "", "pl_home_odds": "",
             "pl_away_odds": ""}
        k = 10
        if len(a) == 16:
            g["pl_home"], g["pl_home_odds"] = num(h[10]), num(h[11])
            g["pl_away_odds"] = num(a[11])
            k = 12
        g["total_open"] = num(a[k])
        g["total"], g["over_odds"], g["under_odds"] = num(a[k + 2]), num(a[k + 3]), num(h[k + 3])
        out.append(g)
    return out


def load_api(raw: str) -> dict:
    """(date, away, home) -> (game_id, gtype, ended, away_score, home_score) for finished games."""
    idx = {}
    for fn in glob.glob(os.path.join(raw, "api", "*.json")):
        try:
            d = json.load(open(fn))
        except ValueError:
            continue
        for day in d.get("gameWeek", []):
            for g in day.get("games", []):
                if g.get("gameState") not in ("OFF", "FINAL") or g.get("gameType") not in (2, 3):
                    continue
                at, ht = g["awayTeam"], g["homeTeam"]
                if "score" not in at or "score" not in ht:
                    continue
                ended = (g.get("gameOutcome") or {}).get("lastPeriodType", "")
                key = (day["date"], canon(at["abbrev"]), canon(ht["abbrev"]))
                idx[key] = (g["id"], g["gameType"], ended, at["score"], ht["score"])
    return idx


def add_days(d: str, n: int) -> str:
    import datetime as dt
    return (dt.date.fromisoformat(d) + dt.timedelta(days=n)).isoformat()


def build_games(raw: str) -> list[dict]:
    api = load_api(raw)
    games = []
    for fn in sorted(glob.glob(os.path.join(raw, "sbro_nhl_*.html"))):
        season = re.search(r"sbro_nhl_(\d{4}-\d{2})", fn).group(1)
        for g in parse_page(open(fn, encoding="utf-8").read(), season):
            m = None
            for off in (0, -1, 1):
                m = api.get((add_days(g["date"], off), g["away"], g["home"]))
                if m and (m[3], m[4]) == (g["away_g"], g["home_g"]):
                    g["date"] = add_days(g["date"], off)
                    break
                m = None
            g["game_id"], g["gtype"], g["ended"] = (m[0], m[1], m[2]) if m else ("", "", "")
            games.append(g)
    games.sort(key=lambda g: (g["date"], g["home"], g["away"]))
    return games


def write(path: str, cols: list[str], rows: list[dict]) -> None:
    with gzip.open(path, "wt", newline="") as f:
        w = csv.DictWriter(f, cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main(raw=RAW, out=None) -> None:
    out = out or os.path.join(os.path.dirname(raw), "data")
    os.makedirs(out, exist_ok=True)
    g = build_games(raw)
    write(os.path.join(out, "games.csv.gz"), COLS, g)
    matched = sum(1 for x in g if x["game_id"])
    print("games", len(g), "api-matched", matched, "seasons", len({x["season"] for x in g}))


if __name__ == "__main__":
    main(*sys.argv[1:3])
