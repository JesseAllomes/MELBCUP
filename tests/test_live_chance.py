# ruff: noqa: E501
"""Live chance of a placed bet, and the challenge card that shows it (owner lock 2026-11-08)."""

import json
from urllib.parse import quote

import pytest

from melbcup import live_chance as L


def test_reached_and_passed():
    assert L.leg_chance(0.4, 10, False, 10, 0.5) == 1.0  # over reached
    assert L.leg_chance(0.4, 10, False, 12, 0.5) == 1.0
    assert L.leg_chance(0.8, 3, True, 3, 0.5) == 0.0  # under passed
    assert L.leg_chance(0.8, 3, True, 5, 0.5) == 0.0


def test_the_mean_matches_the_pregame_chance():
    for k, p, under in ((15, 0.33, False), (4, 0.7, True), (2, 0.5, False)):
        mu = L.implied_mean(p, k, under)
        assert L.leg_chance(p, k, under, 0, 1.0) == pytest.approx(p, abs=1e-3)
        assert mu > 0


def test_more_progress_and_less_time():
    assert L.leg_chance(0.4, 15, False, 9, 0.5) > L.leg_chance(0.4, 15, False, 5, 0.5)
    assert L.leg_chance(0.4, 15, False, 5, 0.25) < L.leg_chance(0.4, 15, False, 5, 0.5)  # behind
    assert L.leg_chance(0.8, 4, True, 2, 0.25) > L.leg_chance(0.8, 4, True, 2, 0.5)  # under
    assert L.leg_chance(0.4, 15, False, 5, 0.0) == 0.0 and L.leg_chance(0.8, 4, True, 2, 0.0) == 1.0


def test_frac_left():
    assert L.frac_left("pre", None, None) == 1.0 and L.frac_left("post", 4, 0) == 0.0
    assert L.frac_left("in", 3, 360) == pytest.approx((360 + 720) / 2880)
    assert L.frac_left("in", 5, 120) == pytest.approx(120 / 2880)  # overtime


def _tr(state, legs, **kw):
    return {"state": state, "legs": legs, "frac_left": kw.get("fl", 0.5), "clock": "Q3 4:12"}


def test_bet_chance_product_failed_and_hit():
    placed = {"price": 4.0, "legs": [{"chance": 0.5}, {"chance": 0.5}]}
    leg = {"k": 10, "under": False}
    pre = L.bet_live(_tr("pre", [leg | {"now": None, "ok": None}] * 2), placed)
    assert pre["p"] == pytest.approx(0.25) and not pre["approx"] and not pre["live"]
    dead = L.bet_live(
        _tr("in", [leg | {"now": 2, "ok": False}, leg | {"now": 3, "ok": None}]), placed
    )
    assert dead["p"] == 0.0
    won = L.bet_live(_tr("in", [leg | {"now": 10, "ok": True}] * 2), placed)
    assert won["p"] == 1.0
    approx = L.bet_live(_tr("in", [leg | {"now": 3, "ok": None}] * 2), {"price": 4.0})
    assert approx["approx"] and 0 < approx["p"] < 0.25


LABEL = "Houston Rockets @ Phoenix Suns: Alperen Sengun 15+ Points, Devin Booker Under 3.5 Rebounds"
STATES = {
    "placed": ("pre", None, [None, None], None),
    "inplay": ("in", None, [9, 2], None),
    "won": ("post", "won", [16, 2], [True, True]),
    "lost": ("post", "lost", [9, 5], [False, False]),
}


@pytest.mark.parametrize("name", list(STATES))
def test_challenge_page_renders_each_state(name, monkeypatch, tmp_path):
    from test_asynym import ON, make
    from test_nba_page import BOARD, NOW, events

    from melbcup import nba_feed, nba_live
    from melbcup.web import app as app_module
    from melbcup.web import views

    path = tmp_path / "board.json"
    path.write_text(json.dumps(BOARD))
    monkeypatch.setattr(
        nba_feed.NbaFeed.__init__, "__defaults__", (None, events(1.75), path, lambda: NOW)
    )
    day = __import__("datetime").date(2026, 11, 5)
    monkeypatch.setattr(views, "melbourne_today", lambda: day)
    monkeypatch.setattr(app_module, "melbourne_today", lambda: day)
    state, verdict, nows, oks = STATES[name]
    parse = nba_live.parse

    def track(label, now=None, fetch=None):
        oks_ = oks or [None, None]
        legs = [
            g | {"now": n, "ok": o} for g, n, o in zip(parse(label)[1], nows, oks_, strict=True)
        ]
        return {
            "state": state,
            "clock": "Q3 4:12",
            "legs": legs,
            "failed": sum(o is False for o in oks_),
            "verdict": verdict,
            "period": 3,
            "clock_s": 252,
            "frac_left": 0.4,
        }

    monkeypatch.setattr(nba_live, "track", track)
    with make(ON) as c:
        c.get("/?ag=1&on_pb=1&on_sb=1&pb=100")
        c.get("/nba?tab=challenge&ch=newch&chname=Run&chmode=multi")
        q = f"/nba?tab=challenge&chid=ch1&ch=place&chs=0&chag=pb&chp=5.0&chtip=2020-01-01T00:00:00Z&chc=40,80&chl={quote(LABEL)}"
        html = c.get(q).text
    assert 'id="chv9"' in html and 'class="tile' in html
    if name == "placed":
        assert 'class="tile n"' in html or 'class="tile o"' in html
    if name == "inplay":
        assert 'data-live="1"' in html and 'class="tile o"' in html and "Live estimate" in html
        assert "width:60%" in html  # 9 of 15, the count-up bar
    if name == "won":
        assert 'class="tile g"' in html and "All legs hit" in html
    if name == "lost":
        assert 'class="tile r"' in html and "Failed" in html and ">0%<" in html
    assert "Challenge actions" in html and 'value="won"' in html  # actions stay reachable


def _one(under, now=10, fl=0.2, track_kw=None, **leg_kw):
    leg = {"k": 20, "under": under, "now": now, "ok": None} | leg_kw
    tr = _tr("in", [leg], fl=fl) | {"period": 4, "clock_s": 400} | (track_kw or {})
    return L.bet_live(tr, {"legs": [{"chance": 0.5}]})


def test_fouled_out_under_is_certain_and_over_dead():
    assert _one(True, pf=6)["p"] == 1.0
    assert _one(False, pf=6)["p"] == 0.0


def test_dnp_over_is_dead():
    assert _one(False, now=0, dnp=True)["p"] == 0.0
    assert _one(True, now=0, dnp=True)["p"] == 1.0


def test_blowout_helps_an_under_and_hurts_an_over():
    base = {"min": 30, "starter": True}
    calm = _one(True, **base)
    blow = _one(True, track_kw={"margin": 25}, **base)
    assert blow["p"] > calm["p"]
    assert "blowout" in blow["why"][0]
    assert _one(False, track_kw={"margin": 25}, **base)["p"] < _one(False, **base)["p"]


def test_missing_fields_match_the_clock_only_chance():
    got = _one(False, fl=0.3)["p"]
    assert got == pytest.approx(L.leg_chance(0.5, 20, False, 10, 0.3))
