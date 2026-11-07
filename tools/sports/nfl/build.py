"""Clean raw nflverse games.csv into one row per game with no-vig market probabilities."""
from __future__ import annotations

import argparse
import gzip
import math
from pathlib import Path

import pandas as pd

from tools.sports.nfl.fetch import RAW_DEFAULT

OUT_DEFAULT = RAW_DEFAULT.parent / "out"  # full dataset stays out of git
SAMPLE_DIR = Path(__file__).resolve().parents[3] / "data" / "sports" / "nfl"  # small sample only


def american_to_decimal(a: float) -> float:
    """American odds to decimal odds. NaN passes through."""
    if a is None or (isinstance(a, float) and math.isnan(a)) or a == 0:
        return float("nan")
    return 1 + a / 100 if a > 0 else 1 + 100 / -a


def devig(d1: float, d2: float) -> tuple[float, float]:
    """Proportional margin removal from two decimal prices."""
    if not (d1 > 1 and d2 > 1):
        return float("nan"), float("nan")
    q1, q2 = 1 / d1, 1 / d2
    s = q1 + q2
    return q1 / s, q2 / s


def build(raw: Path = RAW_DEFAULT) -> pd.DataFrame:
    g = pd.read_csv(raw / "games.csv")
    g = g[g.away_score.notna() | g.away_moneyline.notna() | g.spread_line.notna()].copy()
    g["played"] = g.home_score.notna()
    g["gameday"] = pd.to_datetime(g.gameday)
    g = g.sort_values(["gameday", "game_id"]).reset_index(drop=True)
    rows = []
    for r in g.itertuples():
        dh, da = american_to_decimal(r.home_moneyline), american_to_decimal(r.away_moneyline)
        ph, pa = devig(dh, da)
        dsh = american_to_decimal(r.home_spread_odds)
        dsa = american_to_decimal(r.away_spread_odds)
        psh, _ = devig(dsh, dsa)
        dov, dun = american_to_decimal(r.over_odds), american_to_decimal(r.under_odds)
        pov, _ = devig(dov, dun)
        res = r.result if r.played else float("nan")
        rows.append(
            dict(
                game_id=r.game_id, season=r.season, week=r.week, game_type=r.game_type,
                date=r.gameday.date().isoformat(), home=r.home_team, away=r.away_team,
                home_score=r.home_score, away_score=r.away_score, played=r.played,
                neutral=int(r.location == "Neutral"), home_rest=r.home_rest, away_rest=r.away_rest,
                dec_home=dh, dec_away=da, p_home=ph, p_away=pa,
                spread=r.spread_line, dec_spread_home=dsh, dec_spread_away=dsa, p_spread_home=psh,
                total=r.total_line, dec_over=dov, dec_under=dun, p_over=pov,
                home_win=(
                    float("nan") if not r.played else (1.0 if res > 0 else 0.0 if res < 0 else 0.5)
                ),
                home_cover=(
                    float("nan") if not r.played or pd.isna(r.spread_line) or res == r.spread_line
                    else float(res > r.spread_line)
                ),
                over=(
                    float("nan") if not r.played or pd.isna(r.total_line) or r.total == r.total_line
                    else float(r.total > r.total_line)
                ),
            )
        )
    d = pd.DataFrame(rows)
    return d


def write(d: pd.DataFrame, out: Path = OUT_DEFAULT) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    p = out / "dataset.csv.gz"
    with gzip.open(p, "wt", newline="") as f:
        d.to_csv(f, index=False)
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    d[d.season == 2024].head(25).to_csv(SAMPLE_DIR / "sample.csv", index=False)
    return p


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=RAW_DEFAULT)
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    a = ap.parse_args()
    ds = build(a.raw)
    print(write(ds, a.out), len(ds), ds.season.min(), ds.season.max())
