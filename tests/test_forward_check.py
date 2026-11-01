"""tools/forward_check.py: picks from an observation snapshot and their grading."""

import datetime as dt
import importlib.util
import pathlib

import pytest

SPEC = importlib.util.spec_from_file_location(
    "forward_check", pathlib.Path(__file__).resolve().parents[1] / "tools" / "forward_check.py"
)
fc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fc)


def _runners():
    # eight runners, every book prices every runner; Sportsbet a touch longer on runner 3
    base = [2.5, 4.0, 7.0, 9.0, 12.0, 15.0, 26.0, 41.0]
    out = {}
    for i, q in enumerate(base, start=1):
        sb = q * (1.35 if i == 3 else 1.0)
        out[i] = dict(
            name=f"H{i}",
            prices={
                "sb": (sb, 1 + (sb - 1) / 4),
                "lb": (q, 1 + (q - 1) / 4),
                "pb": (q, None),
                "bt": (q, 1 + (q - 1) / 4),
            },
        )
    return out


def test_picks_follow_the_race_card_rules():
    start = dt.datetime(2026, 11, 3, 4, 0, tzinfo=dt.UTC)
    snap = (start - dt.timedelta(minutes=30), start, True, _runners())
    p = fc.picks(snap)
    assert p["_field"] == 8
    assert p["place"]["no"] == 1  # likeliest placer is the favourite
    assert p["win"]["no"] == 3  # the Sportsbet-longer runner pays closest to fair
    assert p["each_way"]["price"] >= fc.EW_MIN_PRICE
    assert p["each_way"]["no"] == 3
    # chances carry the favourite-long-shot correction: the favourite is above its raw market share
    assert p["place"]["chance"] > 0.5
    assert 0 < p["win"]["chance"] < 1


def test_grading_pays_win_place_and_each_way():
    finish = {"3": 1, "1": 2, "2": 3, "4": 4}
    win = dict(no=3, price=7.7)
    place = dict(no=1, price=1.4)
    ew = dict(no=3, price=7.7, place_price=2.675)
    assert fc.grade(win, "win", finish, 3) == pytest.approx(7.7)
    assert fc.grade(place, "place", finish, 3) == pytest.approx(1.4)
    assert fc.grade(ew, "each_way", finish, 3) == pytest.approx(0.5 * 7.7 + 0.5 * 2.675)
    assert fc.grade(dict(no=4, price=9.0), "win", finish, 3) == 0.0
    assert fc.grade(None, "win", finish, 3) is None


def test_snapshot_selection_takes_t30_and_the_last_open_price():
    start = dt.datetime(2026, 11, 3, 4, 0, tzinfo=dt.UTC)
    r = _runners()
    snaps = [
        (start - dt.timedelta(minutes=50), start, True, r),
        (start - dt.timedelta(minutes=31), start, True, r),
        (start - dt.timedelta(minutes=29), start, True, r),
        (start - dt.timedelta(minutes=2), start, True, r),
        (start - dt.timedelta(minutes=1), start, False, r),  # betting closed: not a usable price
        (start + dt.timedelta(minutes=1), start, False, r),
    ]
    early, late = fc.pick_snapshots(snaps)
    assert early[0] == start - dt.timedelta(minutes=29)
    assert late[0] == start - dt.timedelta(minutes=2)
