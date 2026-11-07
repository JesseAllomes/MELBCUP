"""Per-sport tabs (v8-2): the bottom bar, every sport x tab, old NBA links, the honest SGM state."""

from pathlib import Path

import pytest
from test_asynym import ON, make

from melbcup import catalogue_view as cv
from melbcup import discover, sports_hub

FIX = Path(__file__).parent / "fixtures" / "catalogue_ui"
TABS = [k for k, _ in sports_hub.SPORT_TABS]
SPORTS = [s.code for s in sports_hub.SPORTS]


@pytest.fixture(params=["empty", "fixture"])
def c(request, monkeypatch, tmp_path):
    monkeypatch.setenv("CATALOGUE_DIR", str(tmp_path if request.param == "empty" else FIX))
    cv.clear_cache()
    monkeypatch.setattr(discover, "refresh_now", lambda: True)
    with make(ON) as client:
        yield client
    cv.clear_cache()


def test_every_sport_and_tab_renders_with_the_bar(c):
    for sport in SPORTS:
        for tab in TABS:
            r = c.get(f"/sports?sport={sport}&tab={tab}")
            assert r.status_code == 200, (sport, tab)
            if sport != "racing":
                assert 'class="btm"' in r.text, (sport, tab)
                assert f'tab={tab}" class="on"' in r.text, (sport, tab)


def test_default_tab_is_multis_and_home_has_no_bar(c):
    assert 'tab=multis" class="on"' in c.get("/sports?sport=nfl").text
    assert 'class="btm"' not in c.get("/sports").text
    assert 'class="btm"' not in c.get("/sports?sport=home").text


def test_old_nba_links_still_work(c):
    for url in (
        "/nba?tab=stacks",
        "/nba?tab=same",
        "/nba?tab=challenge",
        "/nba?tab=games",
        "/sports?sport=nba&tab=stacks",
        "/sports?sport=nba&view=players",
        "/sports?sport=afl&view=markets",
    ):
        assert c.get(url).status_code == 200, url
    assert 'tab=all" class="on"' in c.get("/sports?sport=afl&view=markets").text
    assert 'tab=sgm" class="on"' in c.get("/sports?sport=nba&tab=same").text
    assert 'tab=multis" class="on"' in c.get("/sports?sport=nba&tab=stacks").text


def test_non_nba_sgm_is_honest(c):
    t = c.get("/sports?sport=nhl&tab=sgm").text
    assert "Same-game multis need a measured correlation model" in t and "NBA only for now" in t


def test_challenge_tab_creates_an_all_sports_challenge(c):
    t = c.get("/sports?sport=nfl&tab=challenge").text
    assert "+ Add a bonus credit" in t and "+ New challenge" in t
    made = c.get(
        "/sports?sport=nfl&tab=challenge&ch=newch&chscope=all&chname=Run&chstart=10&chgoal=100&chn=3"
    )
    assert made.status_code == 200
    assert "Run" in made.text
    assert "Stage 1" in made.text


def test_games_tab_links_to_the_all_tab(c):
    t = c.get("/sports?sport=football&tab=games").text
    assert "tab=all&event=" in t or "No games listed" in t
