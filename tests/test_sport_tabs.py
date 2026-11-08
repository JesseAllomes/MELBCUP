# ruff: noqa: E501
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


def test_default_tab_is_multis_and_home_has_the_bar_too(c):
    """Owner 2026-11-08: Best multis lost its tabs; it has the same bottom bar now."""
    assert 'tab=multis" class="on"' in c.get("/sports?sport=nfl").text
    assert 'class="btm"' in c.get("/sports").text
    for tab in ("multis", "challenge", "games", "sgm", "all"):
        r = c.get(f"/sports?sport=home&tab={tab}")
        assert r.status_code == 200 and 'class="btm"' in r.text, tab


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


def test_challenge_tab_creates_an_nfl_challenge(c):
    t = c.get("/sports?sport=nfl&tab=challenge").text
    assert "+ Add a bonus credit" in t and "+ New challenge" in t
    made = c.get(
        "/sports?sport=nfl&tab=challenge&ch=newch&chscope=nfl&chname=Run&chstart=10&chgoal=100&chn=3"
    )
    assert made.status_code == 200
    assert "Run" in made.text
    assert "Stage 1" in made.text


def test_games_tab_links_to_the_all_tab(c):
    t = c.get("/sports?sport=football&tab=games").text
    assert "tab=all&event=" in t or "No games listed" in t


def test_new_nba_challenge_shows_planner_and_legs(c):
    t = c.get("/sports?sport=nba&tab=challenge&ch=newch&chscope=nba&chname=P&chstart=10.27&chgoal=100&chlegs=2").text
    assert "Legs per multi" in t and "10.27" in t


def _synthetic_disc():
    from datetime import UTC, datetime, timedelta

    t = (datetime.now(UTC) + timedelta(hours=5)).isoformat()
    legs = [
        {"label": f"Team{i} to win", "price": 1.6, "p": 0.6, "event": f"A{i} v B{i}", "event_id": f"e{i}", "start": t, "sport": "nba"}
        for i in range(3)
    ]
    pk = {"legs": legs, "price": 4.1, "p_all": 0.216, "fair_price": 4.6, "expected_return": -0.1, "cut": 0.1}
    rows = [{"lo": lo, "hi": lo * 1.15, "pick": pk if lo >= 2.0 else None, "reason": None} for lo in discover.LADDER]
    return {"ladder": rows, "by_sport_ladder": {}, "bands": [], "by_sport": {}, "by_legs": {}}


def test_pick_for_price_at_least_target():
    d = _synthetic_disc()
    r = discover.pick_for(2.3, None, None, d)
    assert r["band"]["pick"]["price"] >= 2.3 and r["band"]["lo"] >= 2.3
    assert discover.pick_for(99, None, None, d)["pick"] is None


def test_all_sports_challenge_on_the_afl_hub_tab_shows_suggestion(c, monkeypatch):
    monkeypatch.setattr(discover, "latest", lambda wait=False: _synthetic_disc())
    c.get("/sports?sport=afl&tab=challenge&ch=newch&chscope=all&chname=Run&chstart=10&chgoal=100&chn=3")
    page = c.get("/sports?sport=afl&tab=challenge").text
    import re

    cid = re.search(r"chid=([\w-]+)", page).group(1)
    t = c.get(f"/sports?sport=afl&tab=challenge&chid={cid}").text
    assert "no suggestion" not in t
    assert "I placed this" in t and "Team0 to win" in t


def test_record_a_bet_form_on_multis_and_sgm(c):
    for u in ("/sports?sport=football&tab=multis", "/sports?sport=nfl&tab=sgm", "/sports?sport=home&tab=multis"):
        t = c.get(u).text
        assert "+ Record a bet I placed" in t and 'name="nbbw"' in t, u
