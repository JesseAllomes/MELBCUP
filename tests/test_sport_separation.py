# ruff: noqa: E501
"""NFL and NBA pages are separate: own challenges, own legs, stage preview honours the form."""

import re

import pytest
from test_nfl_page import _rows
from test_asynym import ON, make

from melbcup import catalogue_view as cv
from melbcup import discover, nfl_legs


@pytest.fixture
def c(monkeypatch, tmp_path):
    monkeypatch.setenv("CATALOGUE_DIR", str(tmp_path))
    cv.clear_cache()
    monkeypatch.setattr(discover, "refresh_now", lambda: True)
    legs = nfl_legs.legs_from_rows(_rows())
    monkeypatch.setattr(nfl_legs, "current_legs", lambda now=None, horizon_h=72: legs)
    with make(ON) as client:
        client.get("/sports?sport=nba&tab=challenge&ch=newch&chname=NbaRun&chscope=nba&chmode=multi")
        client.get("/sports?sport=nfl&tab=challenge&ch=newch&chname=NflRun&chscope=nfl&chmode=multi")
        yield client
    cv.clear_cache()


def test_each_page_lists_only_its_own_challenges(c):
    nfl = c.get("/sports?sport=nfl&tab=challenge").text
    nba = c.get("/sports?sport=nba&tab=challenge").text
    assert "NflRun" in nfl and "NbaRun" not in nfl
    assert "NbaRun" in nba and "NflRun" not in nba


def test_other_sports_chid_is_ignored(c):
    nfl = c.get("/sports?sport=nfl&tab=challenge&chid=ch1").text  # ch1 is the NBA one
    assert "NbaRun" not in nfl and "NflRun" in nfl


def test_record_form_select_is_filtered(c):
    for page, mine, other in (("nfl", "NflRun", "NbaRun"), ("nba", "NbaRun", "NflRun")):
        html = c.get(f"/sports?sport={page}&tab=multis").text
        sel = re.search(r'<select name="nbch">(.*?)</select>', html, re.S).group(1)
        assert mine in sel and other not in sel


def test_new_challenge_sport_is_fixed(c):
    nfl = c.get("/sports?sport=nfl&tab=challenge").text
    assert '<input type="hidden" name="chscope" value="nfl">' in nfl
    assert 'name="chscope" value="nba"' not in nfl and "All Sports (I type" not in nfl
    nba = c.get("/sports?sport=nba&tab=challenge").text
    assert '<input type="hidden" name="chscope" value="nba">' in nba


def _table(html):
    return re.findall(r"<span>[\d.]+x</span><span>[^<]*</span><span>[^<]*</span>", html)


def test_preview_honours_mode_goal_and_preselects_best(c):
    base = "/sports?sport=nfl&tab=challenge&chpreview=1&chstart=10&chgoal=1000&chlegs="
    game = c.get(base + "&chmode=game").text
    multi = c.get(base + "&chmode=multi").text
    for html in (game, multi):
        assert "<dialog" in html and re.search(r"<dialog[^>]* open", html)
        assert "Best: " in html and "to finish" in html and "a stage at" in html
        best = re.search(r"<b>Best: (\d+) stages", html).group(1)
        assert re.search(rf'<option value="{best}" selected>', html.split('name="chn"')[1])
    assert _table(game) and _table(multi) and _table(game) != _table(multi)
    assert 'value="multi" checked' in multi
    small = c.get("/sports?sport=nfl&tab=challenge&chpreview=1&chstart=10&chgoal=100&chmode=game").text
    assert _table(small) != _table(game)


def test_nfl_pages_have_no_nba_teams(c):
    for tab in ("multis", "sgm", "games", "all", "challenge"):
        html = c.get(f"/sports?sport=nfl&tab={tab}").text
        for team in ("Lakers", "Celtics", "Warriors", "Knicks", "Nuggets"):
            assert team not in html


def test_push_url_for_nfl_challenge(monkeypatch, c):
    from melbcup.web import views

    seen = []
    orig = views.Views._challenge

    def spy(self, q, ctx):
        out = orig(self, q, ctx)
        seen.append(out.get("push_reminders"))
        return out

    monkeypatch.setattr(views.Views, "_challenge", spy)
    c.get("/sports?sport=nfl&tab=challenge")
    for p in [p for r in seen for p in (r or [])]:
        assert p["url"] == "/sports?sport=nfl&tab=challenge"
