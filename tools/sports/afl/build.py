"""Clean the raw workbook into one row per game (full odds table, kept local only).

Writes OUT/games_with_odds.csv.gz (local, personal use) and OUT/dataset.csv.gz (results plus
pre-game Elo only, odds removed, safe to publish).
Usage: python -m tools.sports.afl.build
"""

import numpy as np
import pandas as pd

from tools.sports.afl.fetch import DEST, fetch
from tools.sports.afl.paths import OUT

ODDS_COLS = {
    "Home Odds": "h_avg",
    "Away Odds": "a_avg",
    "Bookmakers Surveyed": "n_books",
    "Home Odds Open": "h_open",
    "Away Odds Open": "a_open",
    "Home Odds Close": "h_close",
    "Away Odds Close": "a_close",
    "Home Line Close": "line_close",
    "Home Line Odds Close": "h_line_odds",
    "Away Line Odds Close": "a_line_odds",
    "Total Score Close": "total_close",
    "Total Score Over Close": "over_odds",
    "Total Score Under Close": "under_odds",
}
RESULT_COLS = {
    "Date": "date",
    "Home Team": "home",
    "Away Team": "away",
    "Venue": "venue",
    "Home Score": "h_score",
    "Away Score": "a_score",
    "Play Off Game?": "finals",
}
ODDS_NAMES = list(ODDS_COLS.values())


def clean(raw: pd.DataFrame) -> pd.DataFrame:
    d = raw.rename(columns={**RESULT_COLS, **ODDS_COLS})[list(RESULT_COLS.values()) + ODDS_NAMES]
    d = d.dropna(subset=["date", "home", "away", "h_score", "a_score"]).copy()
    d["date"] = pd.to_datetime(d["date"]).dt.normalize()
    d["finals"] = d["finals"].notna().astype(int)
    for c in ["h_score", "a_score", *ODDS_NAMES]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    # decimal odds must be > 1; anything else is a data error
    for c in [
        "h_avg",
        "a_avg",
        "h_open",
        "a_open",
        "h_close",
        "a_close",
        "h_line_odds",
        "a_line_odds",
        "over_odds",
        "under_odds",
    ]:
        d.loc[d[c] <= 1.0, c] = np.nan
    d = d.drop_duplicates(["date", "home", "away"]).sort_values(["date", "home"])
    d = d.reset_index(drop=True)
    d["season"] = d["date"].dt.year
    d["margin"] = d["h_score"] - d["a_score"]
    d["total"] = d["h_score"] + d["a_score"]
    d["home_win"] = np.where(d["margin"] == 0, 0.5, (d["margin"] > 0).astype(float))
    return d


def build() -> pd.DataFrame:
    from tools.sports.afl.model import add_elo, add_rest

    fetch()
    raw = pd.read_excel(DEST, sheet_name="Data", header=1)
    d = add_rest(add_elo(clean(raw)))
    OUT.mkdir(parents=True, exist_ok=True)
    d.to_csv(OUT / "games_with_odds.csv.gz", index=False)
    pub = d.drop(columns=ODDS_NAMES)
    pub.to_csv(OUT / "dataset.csv.gz", index=False)
    return d


if __name__ == "__main__":
    df = build()
    print(len(df), "games", df.season.min(), "-", df.season.max())
