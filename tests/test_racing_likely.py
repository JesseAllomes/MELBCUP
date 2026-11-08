"""Likeliest racing singles and multis on synthetic races."""

import itertools
import math
from datetime import UTC, date, datetime, timedelta

from melbcup import racing_likely as RL
from melbcup.domain import Race, Runner, RunnerPrices
from melbcup.model.probability import Assessment, RaceModel

NOW = datetime(2026, 11, 7, 1, tzinfo=UTC)


def model(num, wins, scratched=(), jumped=False):
    race = Race("Flemington", date(2026, 11, 7), num)
    race.start_time = NOW + timedelta(hours=num if not jumped else -1)
    ass = {}
    for i, w in enumerate(wins, 1):
        race.runners.append(Runner(i, f"Horse{i}", scratched=i in scratched))
        place = min(0.95, w * 2.4)
        race.prices[i] = RunnerPrices(
            i,
            sportsbet_win=round(1 / w * 0.93, 2),
            sportsbet_place=round(1 / place * 0.93, 2),
            betfair_win=round(1 / w, 2),
            pointsbet_win=round(1 / w * 0.9, 2),
        )
        ass[i] = Assessment(i, w, place, w, None, w)
    return RaceModel(race, ass, [])


def test_singles_sorted_and_place_ge_win_and_scratched_out():
    m = model(1, [0.4, 0.25, 0.2, 0.15], scratched=(1,))
    out = RL.likeliest_singles([m], None, ("sportsbet",), NOW)
    bets = out["races"][1]
    assert len(bets) == 3
    assert [b["chance"] for b in bets] == sorted((b["chance"] for b in bets), reverse=True)
    assert all(b["runner"] != 1 for b in bets)
    for n in (2, 3, 4):
        a = m.runners[n]
        assert a.place >= a.win
    assert out["meeting_top"][0] == bets[0]


def test_jumped_race_excluded_and_betfair_net():
    done, live = model(1, [0.5, 0.5], jumped=True), model(2, [0.5, 0.5])
    out = RL.likeliest_singles([done, live], None, ("betfair",), NOW)
    assert list(out["races"]) == [2]
    win = next(b for b in out["races"][2] if b["kind"] == "win")
    assert win["price"] == round(1 + (2.0 - 1) * 0.92, 2)


def test_multis_one_leg_per_race_in_band_and_brute_force():
    ms = [model(n, [0.45, 0.3, 0.25]) for n in range(1, 5)]
    rows = RL.likeliest_multis(ms, None, "sportsbet", now=NOW)
    assert len(rows) == len(RL.BANDS)
    legs_by_race = [RL._bets(m, ("sportsbet",)) for m in ms]
    for row in rows:
        pk = row["pick"]
        if pk is None:
            assert row["reason"]
            continue
        races = [g["event_id"] for g in pk["legs"]]
        assert len(races) == len(set(races))
        assert row["lo"] <= pk["price"] < row["hi"] + 0.01
        best = 0.0
        for k in range(2, 5):
            for rs in itertools.combinations(range(4), k):
                for combo in itertools.product(*(legs_by_race[r] for r in rs)):
                    price = math.prod(b["price"] for b in combo)
                    if row["lo"] <= price < row["hi"]:
                        best = max(best, math.prod(b["chance"] for b in combo))
        assert abs(pk["p_all"] - best) / best < 0.05
