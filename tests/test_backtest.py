import random
from datetime import timedelta

import pytest
from conftest import RACE_DATE, VENUE

from melbcup import backtest as bt
from melbcup.domain import PersonStats, Race, Runner, StatLine


def synthetic(n_races: int = 120, seed: int = 3):
    """Races where the higher handicap rating usually wins and SPs reflect it partly."""
    rng = random.Random(seed)
    data = []
    for i in range(n_races):
        race = Race(VENUE, RACE_DATE + timedelta(days=i % 12), 1 + i // 12)
        ratings = [rng.randint(60, 100) for _ in range(8)]
        for n, rating in enumerate(ratings, start=1):
            jockey = PersonStats("J", recent=StatLine(100, 15, 40), at_track=StatLine(50, 8, 20))
            race.runners.append(
                Runner(
                    n,
                    f"H{n}",
                    hcp_rating=rating,
                    jockey_stats=jockey,
                    sex="mare" if n % 2 else "gelding",
                )
            )
        strength = {n: 2.7 ** ((r - 80) / 8) for n, r in enumerate(ratings, start=1)}
        total = sum(strength.values())
        order = []
        pool = dict(strength)
        while pool:
            pick = rng.choices(list(pool), list(pool.values()))[0]
            order.append(pick)
            pool.pop(pick)
        result = {
            n: (round(1.2 * total / (0.5 * strength[n] + 0.5 * total / 8), 1), order.index(n) + 1)
            for n in strength
        }
        # Stats fetched "today" include this race, as FormFav's do for recent races.
        for r in race.runners:
            won, placed = result[r.number][1] == 1, result[r.number][1] <= 3
            r.jockey_stats = PersonStats(
                "J",
                recent=StatLine(101, 15 + won, 40 + placed),
                at_track=StatLine(51, 8 + won, 20 + placed),
            )
        data.append((race, result))
    return data


def test_prepare_never_mutates_and_removes_own_result():
    data = synthetic(10)
    race, result = data[0]
    winner = next(n for n, (_, pos) in result.items() if pos == 1)
    before = race.runner(winner).jockey_stats.recent
    s1 = bt.prepare(data)
    s2 = bt.prepare(data)
    assert race.runner(winner).jockey_stats.recent == before  # caller's data untouched
    adjusted = s1[0].race.runner(winner).jockey_stats.recent
    assert (adjusted.starts, adjusted.wins) == (before.starts - 1, before.wins - 1)
    assert s2[0].race.runner(winner).jockey_stats.recent == adjusted  # idempotent


def test_sp_probs_need_every_starter():
    assert bt.sp_probs({1: (2.0, 1), 2: (4.0, 2)}, {1, 2}) == pytest.approx({1: 2 / 3, 2: 1 / 3})
    assert bt.sp_probs({1: (2.0, 1), 2: (None, 2)}, {1, 2}) == {}


def test_fit_finds_the_signal_and_beats_random():
    samples = bt.prepare(synthetic())
    w = bt.fit_weights(samples, steps=300)
    assert max(w, key=lambda k: abs(w[k])) == "hcp" and w["hcp"] > 0
    scores = {x.name: x for x in bt.compare(samples, w, 1.0)}
    assert scores["Form model"].log_loss < scores["Form model"].uniform
    assert scores["Form model"].top_pick > 1 / 8


def test_patterns_report_actual_vs_expected():
    stats = {p.name: p for p in bt.patterns(bt.prepare(synthetic()))}
    top = stats["Top handicap rating in field"]
    assert top.runners >= 100 and top.wins > 0
    assert top.ae == pytest.approx(top.wins / top.expected)
