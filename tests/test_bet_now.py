"""Bet now: the Sports home and sport pages, the status/refresh routes, the simplified wallet."""

import time
from pathlib import Path

import pytest
from test_asynym import ON, make

from melbcup import catalogue_view as cv
from melbcup import discover

FIX = Path(__file__).parent / "fixtures" / "catalogue_ui"


@pytest.fixture(params=["empty", "fixture"])
def c(request, monkeypatch, tmp_path):
    monkeypatch.setenv("CATALOGUE_DIR", str(tmp_path if request.param == "empty" else FIX))
    cv.clear_cache()
    monkeypatch.setattr(discover, "refresh_now", lambda: True)
    with make(ON) as client:
        yield client
    cv.clear_cache()


def test_home_and_sport_render(c):
    for url in ("/sports", "/sports?sport=nfl", "/sports?sport=football"):
        r = c.get(url)
        assert r.status_code == 200, url
        assert "Check now" in r.text


def test_status_and_refresh(c):
    s = c.get("/api/sports/status")
    assert s.status_code == 200
    assert set(s.json()) >= {"busy", "progress", "built", "age_s"}
    assert c.post("/api/sports/refresh").status_code == 204


def test_challenge_tab_has_no_funding_compare_or_split(c):
    t = c.get("/sports?sport=nba&tab=challenge").text
    assert "Compare how to fund a bet" not in t
    assert "Record split" not in t


def test_render_is_fast(c):
    c.get("/sports")
    t0 = time.perf_counter()
    c.get("/sports?sport=nfl")
    assert time.perf_counter() - t0 < 0.3
