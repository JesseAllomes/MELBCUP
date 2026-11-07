"""Cleaning and model code of tools/sports/racing, the racing store, learn.py and tuning."""

import gzip
import json
import os
import sys
import types
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools", "sports", "racing"))
sys.path.insert(0, os.path.join(HERE, ".."))
import build  # noqa: E402
import common  # noqa: E402
import model as M  # noqa: E402
import test as holdout  # noqa: E402  (tools/sports/racing/test.py)

from melbcup import racing_store  # noqa: E402
from melbcup.live import CheckLine, RaceCheck  # noqa: E402
from melbcup.model import probability  # noqa: E402


def test_season_and_price():
    assert common.season("2025-08-01") == "2025-26"
    assert common.season("2026-07-31") == "2025-26"
    assert common.season("2026-01-02") == "2025-26"
    assert common.price("$2.45") == 2.45
    assert common.price("1.00") is None and common.price(None) is None and common.price("x") is None


def _meeting(tmp_path):
    def runner(n, finish, sp, scratched=False):
        return {
            "raceEntryNumber": n,
            "horseCode": f"h{n}",
            "barrierNumber": n,
            "weightCarried": "56.5kg",
            "jockeyCode": "j",
            "trainerCode": "t",
            "scratched": scratched,
            "handicapRating": 60,
            "finish": finish,
            "startingPrice": sp,
            "bettingFluctuationsPriceOpen": "3.00",
            "odds": [{"providerCode": "SB2", "oddsWin": sp, "oddsPlace": "$1.50"}],
            "sb": [{"flucsWin": [{"amount": "$3.10"}]}],
            "horse": {"age": "5", "sex": "Gelding"},
        }

    ok = {
        "raceNumber": 1,
        "distance": "1200m",
        "class": "BM58",
        "group": "ungrouped",
        "trackCondition": "Good",
        "trackSurface": "Turf",
        "formRaceEntries": [
            runner(1, 1, "$2.00"),
            runner(2, 2, "$3.50"),
            runner(3, None, "$5.00", scratched=True),
            runner(4, 3, "$1.00"),
        ],
    }
    no_winner = {
        "raceNumber": 2,
        "distance": "1000m",
        "formRaceEntries": [runner(1, None, "$2.00")],
    }
    d = {
        "id": "9",
        "date": "2025-09-09",
        "venueName": "queanbeyan",
        "state": "NSW",
        "races": [ok, no_winner],
    }
    p = tmp_path / "2025-09-09_9.json.gz"
    with gzip.open(p, "wt") as f:
        json.dump(d, f)
    return str(p)


def test_parse_meeting_drops_scratched_and_winnerless(tmp_path):
    rows = build.parse_meeting(_meeting(tmp_path))
    assert [r["tab"] for r in rows] == [1, 2, 4]  # scratched runner 3 and race 2 gone
    assert all(r["field_size"] == 3 for r in rows)
    assert rows[0]["sb"] == 2.0 and rows[0]["sb_first"] == 3.1 and rows[0]["distance"] == "1200"
    assert rows[2]["sp"] is None  # a price of $1.00 is not a real price


def test_parse_meeting_unreadable_file(tmp_path):
    bad = tmp_path / "x.json.gz"
    bad.write_bytes(b"\x1f\x8b\x08\x00truncated")
    assert build.parse_meeting(str(bad)) == [{"_bad": "x.json.gz"}]


def _races(n_races=3):
    rows = []
    for r in range(n_races):
        for tab, (price, win) in enumerate([(2.0, r == 0), (4.0, r == 1), (4.0, r == 2)], 1):
            rows.append(
                {
                    "meeting_id": "m",
                    "race_no": r + 1,
                    "tab": tab,
                    "sb": price,
                    "win": int(win),
                    "date": "2025-01-01",
                }
            )
    return pd.DataFrame(rows)


def test_market_probs_sum_to_one_and_incomplete_races_are_nan():
    df = _races()
    df.loc[0, "sb"] = np.nan  # race 1 incomplete
    q = M.market_probs(df, "sb")
    assert q.iloc[:3].isna().all()
    assert q.iloc[3:6].sum() == pytest.approx(1.0)
    assert q.iloc[3] == pytest.approx(0.5)  # (1/2) / (1/2+1/4+1/4)


def test_overround():
    df = _races()
    assert M.overround(df, "sb").iloc[0] == pytest.approx(1.0)
    df["sb"] = df["sb"] * 0.9
    assert M.overround(df, "sb").iloc[0] == pytest.approx(1.0 / 0.9)


def test_power_alpha_one_is_identity_and_alpha_shortens_favourite():
    df = _races()
    q = M.market_probs(df, "sb")
    rid = M.race_id(df)
    assert M.power_probs(q, rid, 1.0).equals(q)
    assert M.power_probs(q, rid, 1.2).iloc[0] > q.iloc[0]


def test_fit_alpha_recovers_favourite_bias():
    # Favourites (q=.6) win 80% of the time: the fit must push alpha above 1.
    rng = np.random.default_rng(1)
    rows = []
    for r in range(3000):
        fav_wins = rng.random() < 0.8
        rows += [
            {"meeting_id": "m", "race_no": r, "tab": 1, "sb": 1 / 0.6, "win": int(fav_wins)},
            {"meeting_id": "m", "race_no": r, "tab": 2, "sb": 1 / 0.4, "win": int(not fav_wins)},
        ]
    df = pd.DataFrame(rows)
    q = M.market_probs(df, "sb")
    assert M.fit_alpha(q, df["win"], M.race_id(df)) > 1.5


def test_prior_residuals_use_only_earlier_days():
    df = pd.DataFrame(
        {
            "date": ["2025-01-01", "2025-01-01", "2025-01-02"],
            "jockey": ["a", "a", "a"],
            "trainer": ["t"] * 3,
            "horse_code": ["h1", "h2", "h1"],
            "win": [1, 0, 0],
        }
    )
    q = pd.Series([0.5, 0.5, 0.5])
    out = M.add_prior_residuals(df, q)
    assert out["jockey_resid"].iloc[0] == 0.0 and out["jockey_resid"].iloc[1] == 0.0  # same day
    assert out["jockey_resid"].iloc[2] == pytest.approx(0.0)  # +0.5 and -0.5 cancel
    assert out["horse_resid"].iloc[2] > 0  # h1 beat the market on day one


def test_race_logloss_skips_dead_heats():
    df = _races(2)
    df.loc[1, "win"] = 1  # race 1 now has two winners
    p = pd.Series([0.5, 0.25, 0.25] * 2)
    ll = M.race_logloss(p, df)
    assert len(ll) == 1 and ll["ll"].iloc[0] == pytest.approx(-np.log(0.25))


def test_wilson_and_boot():
    lo, hi = holdout.wilson(50, 100)
    assert lo < 0.5 < hi and hi - lo < 0.21
    per_day = pd.DataFrame({"s": [1.0, 1.0, 1.0], "n": [1, 1, 1]})
    m, lo, hi = holdout.boot_mean(per_day, n=50)
    assert m == lo == hi == 1.0


def test_roi_single_book_flat_stake():
    df = pd.DataFrame({"date": ["d1", "d1", "d2"], "win": [1, 0, 0]})
    out = holdout.roi(df, pd.Series([3.0, 2.0, 5.0]), pd.Series([True, True, True]))
    assert out["bets"] == 3 and out["roi"] == pytest.approx((2 - 1 - 1) / 3)


# --- racing store, learn.py and tuning -------------------------------------------------------


class Mem:
    def __init__(self):
        self.d = {}

    def read(self, name):
        return self.d.get(name)

    def write(self, name, data):
        self.d[name] = data


def _check():
    jump = datetime(2026, 11, 7, 5, 0, tzinfo=UTC)
    line = CheckLine("win", "3", "Horse", "sportsbet", 4.2, 150, exotic=object())
    return RaceCheck(
        2,
        jump,
        early=(line,),
        early_at=jump,
        late=(line,),
        late_at=jump,
        early_back=0.0,
        late_back=630.0,
        graded=True,
        winner="3 Horse",
    )


def test_checks_round_trip():
    mem = Mem()
    store = racing_store.RacingStore(mem.read, mem.write)
    store.save_checks(date(2026, 11, 7), "Flemington", {2: _check()})
    assert "racing/2026-11-07/flemington/checks.json" in mem.d
    back = store.load_checks(date(2026, 11, 7), "Flemington", RaceCheck, CheckLine)
    assert back[2].early[0].price == 4.2 and back[2].late_back == 630.0
    assert back[2].jump == _check().jump and back[2].graded


def test_load_checks_survives_bad_blob_and_failed_write():
    mem = Mem()
    mem.d["racing/2026-11-07/x/checks.json"] = b"{not json"
    store = racing_store.RacingStore(mem.read, mem.write)
    assert store.load_checks(date(2026, 11, 7), "x", RaceCheck, CheckLine) == {}

    def boom(*a):
        raise OSError("down")

    racing_store.RacingStore(mem.read, boom).save_checks(date(2026, 11, 7), "x", {2: _check()})


def test_log_race_replaces_same_race():
    mem = Mem()
    store = racing_store.RacingStore(mem.read, mem.write)
    d = date(2026, 11, 7)
    store.log_race(d, "Flemington", {"race": 1, "winners": [1], "runners": []})
    store.log_race(d, "Flemington", {"race": 2, "winners": [2], "runners": []})
    store.log_race(d, "Flemington", {"race": 1, "winners": [3], "runners": []})
    lines = [json.loads(x) for x in mem.d["racing/log/2026-11-07.jsonl"].decode().splitlines()]
    assert [(x["race"], x["winners"]) for x in lines] == [(2, [2]), (1, [3])]


def test_from_env_is_none_without_account(monkeypatch):
    monkeypatch.delenv("NBA_ACCOUNT", raising=False)
    assert racing_store.from_env() is None


def _log_rows(n, fav_win_rate, seed=3):
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n):
        fav = rng.random() < fav_win_rate
        rows.append(
            {
                "winners": [1 if fav else 2],
                "runners": [
                    {"no": 1, "market": 0.6, "won": bool(fav)},
                    {"no": 2, "market": 0.4, "won": not fav},
                ],
            }
        )
    return rows


def test_learn_keeps_prior_with_few_races_and_moves_with_many():
    sys.path.insert(0, os.path.join(HERE, "..", "tools", "racing"))
    import learn

    few = learn.tuned(_log_rows(50, 0.8))
    assert few["market_alpha"] == probability.MARKET_ALPHA and few["fitted_alpha"] is None
    many = learn.tuned(_log_rows(6000, 0.8))
    assert many["fitted_alpha"] > 1.5
    assert probability.MARKET_ALPHA < many["market_alpha"] <= probability.ALPHA_RANGE[1]
    assert learn.parse_log('{"a": 1}\nnot json\n\n') == [{"a": 1}]
    assert learn.usable([{"winners": [1, 2], "runners": [{"market": 0.5, "won": True}]}]) == []


def test_set_tuning_applies_and_rejects_bad_values():
    try:
        market = {1: 0.6, 2: 0.4}
        base = probability.corrected_market(market)[1]
        probability.set_tuning({"market_alpha": 1.25})
        assert probability.market_alpha() == 1.25
        assert probability.corrected_market(market)[1] > base
        probability.set_tuning({"market_alpha": 5.0})  # outside the band: ignored
        assert probability.market_alpha() == probability.MARKET_ALPHA
        probability.set_tuning({"market_alpha": "x"})
        probability.set_tuning(None)
        assert probability.market_alpha() == probability.MARKET_ALPHA
    finally:
        probability.set_tuning(None)


def test_board_restores_saved_checks_and_logs_graded_races(tmp_path):
    from test_archive import VENUE, Router, board  # reuse the archived-meeting fixture

    from melbcup.config import MELBOURNE

    day = date(2026, 10, 24)
    mem = Mem()
    store = racing_store.RacingStore(mem.read, mem.write)
    store.save_checks(day, VENUE, {1: _check()})
    b = board(tmp_path, day, datetime(2026, 10, 29, 12, 0, tzinfo=MELBOURNE), Router())
    b.store = store
    b.set_meeting(day, VENUE)
    b.tick()
    snap = b.snapshot()
    now = datetime(2026, 10, 29, 12, 0, tzinfo=MELBOURNE)
    b.rc = types.SimpleNamespace(results=lambda *a: {})  # the saved races are already final
    b._load_results(now)
    assert 1 in snap.checks and snap.checks[1].early[0].price == 4.2  # restored on load
    rows = [
        json.loads(x) for x in mem.d[f"racing/log/{day.isoformat()}.jsonl"].decode().splitlines()
    ]
    assert len(rows) == len(snap.card.races) and rows[0]["winners"]
    assert all(r["runners"] for r in rows)
    assert f"racing/{day.isoformat()}/{racing_store.slug(VENUE)}/checks.json" in mem.d
