"""Last-minute check: picks saved 25-35 minutes before the jump, again in the last 3 minutes,
then both graded against the result (owner, 2026-11-01). Fake clock, racing.com mocked."""

from datetime import datetime, timedelta

import pytest
from conftest import RACE_DATE, Router
from fastapi.testclient import TestClient
from test_live_web import AUTH, ENV, Clock, board_with

from melbcup.config import MELBOURNE, load_settings
from melbcup.domain import Race, RaceResult, betfair_net
from melbcup.live import CheckLine, RaceCheck, grade_check, line_return
from melbcup.web.app import create_app

CUP = datetime(2026, 11, 3, 15, 0, tzinfo=MELBOURNE)  # race 2 in the fixture


@pytest.fixture
def setup(monkeypatch):
    from melbcup.web import views

    monkeypatch.setattr(views, "melbourne_today", lambda: RACE_DATE)
    router, clock = Router(), Clock(CUP - timedelta(hours=2))
    board = board_with(router, clock)
    board.load_card_now(wait=True)
    return board, clock


def test_nothing_is_saved_outside_the_windows(setup):
    board, _ = setup
    assert board.snapshot().checks == {}


def test_early_is_saved_once_then_late_overwrites_until_the_jump(setup):
    board, clock = setup
    clock.t = CUP - timedelta(minutes=30)
    assert board.refresh_prices_now()
    early = board.snapshot().checks[2]
    assert early.early and early.early_at == clock.t and early.late is None
    assert all(x.stake > 0 and "$" not in x.key for x in early.early)
    assert {x.kind for x in early.early} >= {"win", "place"}
    assert 1 not in board.snapshot().checks  # race 1 has already jumped

    clock.t = CUP - timedelta(minutes=27)
    board.refresh_prices_now()
    assert board.snapshot().checks[2].early_at == CUP - timedelta(minutes=30)  # kept, once

    clock.t = CUP - timedelta(minutes=2, seconds=30)
    board.refresh_prices_now()
    first_late = board.snapshot().checks[2].late_at
    clock.t = CUP - timedelta(seconds=30)
    board.refresh_prices_now()
    check = board.snapshot().checks[2]
    assert first_late == CUP - timedelta(minutes=2, seconds=30)
    assert check.late_at == CUP - timedelta(seconds=30)  # overwritten at every check
    assert check.changed == 0  # same prices in the fixture: nothing moved

    clock.t = CUP + timedelta(minutes=1)
    board.refresh_prices_now()
    assert board.snapshot().checks[2].late_at == CUP - timedelta(seconds=30)  # jumped: no more


def test_both_snapshots_are_graded_once_the_result_is_in(setup):
    board, clock = setup
    for t in (CUP - timedelta(minutes=30), CUP - timedelta(minutes=1)):
        clock.t = t
        board.refresh_prices_now()
    clock.t = CUP + timedelta(minutes=10)
    assert board.fetch_results_now()
    check = board.snapshot().checks[2]
    assert check.graded and check.early_back is not None and check.late_back is not None
    assert check.winner.startswith("1 ")  # the fixture's runners finish in saddlecloth order
    totals = board.check_totals()
    assert totals["races"] == 1
    assert totals["early_staked"] == RaceCheck.staked(check.early)
    assert totals["late_back"] == check.late_back


def test_the_card_shows_each_state(setup):
    board, clock = setup
    app = create_app(load_settings(ENV), board, start_background=False)
    with TestClient(app) as c:
        html = c.get("/race/2", auth=AUTH).text
        assert "<b>Waiting.</b> At 2:30pm the app saves its picks. At about 2:59pm" in html
        clock.t = CUP - timedelta(minutes=30)
        board.refresh_prices_now()
        assert "Picks saved at 2:30pm." in c.get("/race/2", auth=AUTH).text
        clock.t = CUP - timedelta(minutes=1)
        board.refresh_prices_now()
        html = c.get("/race/2", auth=AUTH).text
        assert "No changes at 2:59pm." in html and "same: " in html
        clock.t = CUP + timedelta(minutes=10)
        board.fetch_results_now()
        html = c.get("/race/2", auth=AUTH).text
        assert "2:30pm picks</dt><dd><b>$" in html and "Last minute</dt><dd><b>$" in html
        assert " back from $" in html
        history = c.get("/history", auth=AUTH).text
        assert "Last-minute check, running total" in history and "Over 1 race " in history


def test_a_restart_or_late_start_says_there_is_nothing_saved(setup):
    board, clock = setup
    clock.t = CUP + timedelta(minutes=10)
    board.fetch_results_now()
    app = create_app(load_settings(ENV), board, start_background=False)
    with TestClient(app) as c:
        assert "No saved picks for this race" in c.get("/race/2", auth=AUTH).text


# -- grading one line ---------------------------------------------------------------------------


def _race(finish, exotics=None, places=3):
    r = Race(venue="Flemington", race_date=RACE_DATE, number=7, places_paid=places)
    r.result = RaceResult("final", finish, {}, {n: f"Horse {n}" for n in finish}, {}, exotics or {})
    return r


def test_win_place_and_each_way_returns_at_the_saved_price():
    race = _race({20: 1, 2: 2, 5: 3, 9: 4})
    assert line_return(CheckLine("win", "20", "A", "sportsbet", 6.5, 4), race) == 26.0
    assert line_return(CheckLine("win", "2", "B", "sportsbet", 8.5, 4), race) == 0.0
    place = CheckLine("place", "5", "C", "sportsbet", 2.6, 6)
    assert line_return(place, race) == pytest.approx(15.6)
    assert line_return(CheckLine("place", "9", "D", "sportsbet", 3.0, 6), race) == 0.0
    ew = CheckLine("each_way", "2", "B", "sportsbet", 8.5, 6, place_price=3.2)
    assert line_return(ew, race) == pytest.approx(9.6)  # only places: the place half
    ew = CheckLine("each_way", "20", "A", "sportsbet", 6.5, 6, place_price=2.0)
    assert line_return(ew, race) == pytest.approx(3 * 6.5 + 3 * 2.0)
    assert line_return(CheckLine("win", "20", "A", "sportsbet", None, 4), race) is None


def test_betfair_returns_are_after_commission():
    race = _race({20: 1, 2: 2, 5: 3})
    got = line_return(CheckLine("win", "20", "A", "betfair", 7.4, 10), race)
    assert got == pytest.approx(10 * betfair_net(7.4))


def test_exotics_use_the_official_dividend_or_are_unknown():
    from types import SimpleNamespace

    box = SimpleNamespace(
        legs=[[1, 2, 3, 4]] * 3, combos=24, kind="trifecta", title="Box", leg_labels=["Box"]
    )
    line = CheckLine("trifecta", "Box", "T", "sportsbet", None, 6, exotic=box)
    race = _race({1: 1, 2: 2, 3: 3, 4: 4}, {"TF": ((1, 2, 3), 120.0)})
    assert line_return(line, race) == pytest.approx(120.0 / 24 * 6)
    assert line_return(line, _race({1: 1, 2: 2, 3: 3, 4: 4})) is None  # no dividend yet
    assert line_return(line, _race({9: 1, 2: 2, 3: 3, 4: 4})) == 0.0


def test_changes_compare_runner_and_account_by_kind():
    was = (CheckLine("win", "2", "Trustyourinstinct", "sportsbet", 8.5, 2),
           CheckLine("place", "20", "Point Of Law", "sportsbet", 2.6, 6))
    now = (CheckLine("win", "20", "Point Of Law", "betfair", 7.4, 2),
           CheckLine("place", "20", "Point Of Law", "sportsbet", 2.5, 6))
    check = RaceCheck(7, CUP, early=was, late=now)
    rows = {k: (n, w) for k, n, w in check.changes()}
    assert not rows["win"][0].same(rows["win"][1]) and rows["place"][0].same(rows["place"][1])
    assert check.changed == 1
    graded = grade_check(check, _race({20: 1, 2: 2, 5: 3}))
    assert graded.early_back == pytest.approx(0 + 6 * 2.6)
    assert graded.late_back == pytest.approx(2 * betfair_net(7.4) + 6 * 2.5)
    assert graded.winner == "20 Horse 20" and graded.graded
