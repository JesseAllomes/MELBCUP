"""The AsynymBet pages (ASYNYM=1): the same data under new templates, and the old pages when off."""

import pytest
from conftest import Router
from fastapi.testclient import TestClient
from test_live_web import ENV, START, Clock, board_with

from melbcup.config import load_settings
from melbcup.web.app import create_app
from melbcup.web.asynym import tone

ON = {**ENV, "ASYNYM": "1", "PUBLIC_ACCESS": "1"}


def make(env):
    board = board_with(Router(), Clock(START))
    board.load_card_now(wait=True)
    return TestClient(create_app(load_settings(env), board, start_background=False))


@pytest.fixture
def off():
    with make({**ENV, "PUBLIC_ACCESS": "1"}) as c:
        yield c


@pytest.fixture
def on():
    with make(ON) as c:
        yield c


def test_asynym_off_is_the_old_page(off):
    html = off.get("/").text
    assert "<title>MELBCUP</title>" in html and "AsynymBet" not in html
    assert 'class="topnav"' in html and "asynym.css" not in html
    assert off.get("/mine").status_code == 404


@pytest.mark.parametrize("path", ["/", "/meetings", "/meeting", "/race/1", "/race/2", "/mine"])
def test_asynym_pages_have_header_nav_and_no_500(on, path):
    r = on.get(path)
    assert r.status_code == 200
    html = r.text
    assert "AsynymBet</title>" in html and "asynym.css" in html
    assert 'class="hd"' in html and "Agencies" in html and 'class="topnav"' in html
    assert ">Home<" in html and ">Race days<" in html and ">Mine<" in html
    assert 'data-agency="sb"' in html and 'data-agency="bf"' in html
    if path.startswith("/race/"):
        for tab in ("bet", "field", "result", "mine"):
            assert f"?tab={tab}" in html
            assert on.get(f"{path}?tab={tab}").status_code == 200


def test_a_take_race_and_a_nothing_race(on):
    take = on.get("/race/2").text
    assert "Take this bet" in take and "Only worth it at" in take and 'class="ring' in take
    assert "data-rec=" in take and "Nothing worth trying here" not in take
    assert "Top picks worth a shot" in take
    nothing = on.get("/race/1").text
    assert "Nothing worth trying here" in nothing and "Take this bet" not in nothing
    assert 'href="/race/2"' in nothing  # points at the best bet still open


def test_home_lists_take_bets_and_meeting_choice_goes_to_the_races(on):
    home = on.get("/").text
    assert "Bets to take" in home and "/race/2" in home and "/actions/meeting?date=" in home
    r = on.post("/actions/meeting?date=2026-11-03&venue=Flemington", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] in ("/meeting", "/meetings")


def test_agencies_off_hides_the_chip_and_zeroes_the_money(on):
    assert 'data-agency="bf"' in on.get("/").text
    on.cookies.set("agencies", "sb")
    html = on.get("/").text
    assert 'data-agency="sb"' in html and 'data-agency="bf"' not in html
    race = on.get("/race/2").text
    assert 'data-agency="bf"' not in race and 'data-acct="bf"' not in race


def test_the_agencies_form_sets_cookies(on):
    r = on.get("/?ag=1&on_sb=1&on_tab=1&sb=80&bf=10&tb=25")
    cookies = r.headers.get_list("set-cookie")
    assert any(c.startswith("agencies=") and "sb" in c and "tab" in c for c in cookies)
    assert any(c.startswith("tab_budget=25") for c in cookies)
    assert any(c.startswith("sb_budget=80") for c in cookies)
    assert 'data-agency="tab"' in r.text and 'data-agency="bf"' not in r.text


def test_mine_has_the_betting_pool_and_edit(on):
    html = on.get("/mine").text
    assert "Betting pool" in html and "Total" in html and 'id="pool-edit"' in html
    assert 'class="card pool editing"' in on.get("/mine?edit=1").text


@pytest.mark.parametrize(
    "pct,name", [(0, "low"), (29.9, "low"), (30, "mid"), (59, "mid"), (60, "good"), (95, "good")]
)
def test_ring_colours(pct, name):
    assert tone(pct) == name


def test_no_kids_bets_card(on):
    """Removed at the owner's request (2026-11-04): Mine and the race page carry no kids' card."""
    for path in ("/mine", "/race/1?tab=mine"):
        html = on.get(path).text
        assert 'id="kids-h"' not in html and "kid-name" not in html
