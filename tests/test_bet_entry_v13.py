# ruff: noqa: E501
"""v13 bottom sheets, slip, My bets and the challenge planner endpoint."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from test_asynym import ON, make
from test_nfl_page import _rows

from melbcup import catalogue_view as cv
from melbcup import discover, nfl_legs, nba_challenge
from melbcup.web import views as views_mod


@pytest.fixture
def c(monkeypatch, tmp_path):
    monkeypatch.setenv("CATALOGUE_DIR", str(tmp_path))
    cv.clear_cache()
    monkeypatch.setattr(discover, "refresh_now", lambda: True)
    legs = nfl_legs.legs_from_rows(_rows())
    monkeypatch.setattr(nfl_legs, "current_legs", lambda now=None, horizon_h=72: legs)
    with make(ON) as client:
        yield client
    cv.clear_cache()


def test_sport_pages_render_sheet_slip_and_ticks(c):
    for url in ("/sports?sport=nfl&tab=multis", "/sports?sport=nfl&tab=all", "/sports?sport=afl", "/sports?sport=home"):
        html = c.get(url).text
        assert 'id="slip-bar"' in html and 'id="slip-cfg"' in html, url
        assert "asynym.js" in html and 'id="mybets-btn"' in html, url
    nfl = c.get("/sports?sport=nfl&tab=multis").text
    assert 'class="tk"' in nfl and "Add to slip" in nfl and "I placed this" not in nfl
    assert "Bet this" in nfl and 'class="pc' in nfl  # the suggested multis still render
    assert 'class="nb-own"' not in nfl and "Your bets" not in nfl
    js = c.get("/static/asynym.js").text
    assert "openSheet" in js and "translateY" in js and "Escape" in js and "prefers-reduced-motion" in js
    css = c.get("/static/asynym.css").text
    assert ".sh-sheet" in css and "safe-area-inset-bottom" in css and ".slip-bar" in css


def test_challenge_tab_uses_sheets_not_dialogs(c):
    html = c.get("/sports?sport=nfl&tab=challenge").text
    assert "<dialog" not in html and "chs-list" in html
    assert 'data-sheet-for="ch-dlg-new"' in html or "data-plan" in html


@pytest.mark.parametrize("sport,tag,want", [("nfl", "", "nfl"), ("afl", "", "afl"), ("nba", "", "nba"), ("nfl", "multi", "multi")])
def test_own_bet_records_the_sport(c, sport, tag, want):
    q = f"/sports?sport={sport}&tab=multis&ch=bet&nbs=10&nbp=3.5&nbag=sb&nbl=Chiefs+@+Bills:+A+Over+10;+Jets+@+Dolphins:+B+Over+20&nbtip=2030-01-01T00:00:00Z&op=x"
    if tag:
        q += f"&nbsport={tag}"
    c.get(q)
    store = nba_challenge.load(c.cookies.get(nba_challenge.COOKIE))
    bets = [b for b in store["own"]["bets"] if b.get("own")]
    assert bets and bets[-1]["sport"] == want
    assert bets[-1]["label"].count("; ") == 1


def test_my_bets_sheet_lists_own_bets_with_tracker_markup(c, monkeypatch):
    from melbcup import nba_live

    now = datetime.now(UTC)
    tip = (now - timedelta(hours=1)).isoformat()
    monkeypatch.setattr(
        nba_live,
        "track",
        lambda label, now=None, fetch=None: {
            "state": "in", "clock": "Q2 5:00", "failed": 0, "verdict": None, "sport": "nfl",
            "legs": [{"label": "A Over 10", "ok": None, "now": 4, "k": 10, "under": False}],
        },
    )
    c.get(f"/sports?sport=nfl&tab=multis&ch=bet&nbs=10&nbp=3&nbag=sb&nbl=Chiefs+@+Bills:+A+Over+10&nbtip={tip}&op=y")
    html = c.get("/sports?sport=nfl&tab=multis").text
    assert 'id="mybets"' in html and "mb-card" in html and 'class="nb-track"' in html
    assert "in play" in html and "Chiefs @ Bills: A Over 10" in html
    assert 'name="ch" value="betwon"' in html  # one-tap Won / Lost kept
    assert "mb-live" in html  # the live indicator on the button
    home = c.get("/sports?sport=home").text  # all sports, on Home too
    assert 'class="nb-track"' in home


def test_place_from_slip_uses_the_stage_guard(c):
    c.get("/sports?sport=nfl&tab=challenge&ch=newch&chname=Run&chscope=nfl&chstart=10&chgoal=100&chn=3&op=a")
    store = nba_challenge.load(c.cookies.get(nba_challenge.COOKIE))
    cid = store["challenges"][0]["id"]
    cfg = views_mod.slip_cfg(
        {"op": "o", "credits": [], "list": [{"rec": r, "status": "active"} for r in store["challenges"]]}, None, "nfl"
    )
    ch = cfg["challenges"][0]
    assert ch["id"] == cid and ch["stage"] == 0 and ch["x"] > 1
    # a stale stage count does nothing; the right one places
    c.get(f"/sports?sport=nfl&tab=challenge&chid={cid}&op=b&ch=place&chs=5&chp=3.00&chl=G:+A+Over+10&chag=sb")
    st = nba_challenge.find(nba_challenge.load(c.cookies.get(nba_challenge.COOKIE)), cid)["state"]
    assert not st.get("placed")
    c.get(f"/sports?sport=nfl&tab=challenge&chid={cid}&op=c&ch=place&chs=0&chp=3.00&chl=G:+A+Over+10&chag=sb")
    st = nba_challenge.find(nba_challenge.load(c.cookies.get(nba_challenge.COOKIE)), cid)["state"]
    assert st["placed"]["price"] == 3.0


def test_plan_endpoint_matches_stage_preview(c, monkeypatch):
    seen = []
    orig = views_mod.Views._stage_preview

    def spy(self, *a, **k):
        out = orig(self, *a, **k)
        seen.append(out)
        return out

    monkeypatch.setattr(views_mod.Views, "_stage_preview", spy)
    r = c.get("/api/challenge/plan?sport=nfl&start=10&goal=1000&mode=game")
    assert r.status_code == 200
    j = r.json()
    assert j["rows"] and {"n", "x", "typical", "run"} <= set(j["rows"][0])
    assert j["best"] is None or j["best"]["n"] in [o["n"] for o in j["rows"]]
    assert seen and [o["n"] for o in seen[0]] == [o["n"] for o in j["rows"]]
    assert [round(o["x"], 6) for o in seen[0]] == [round(o["x"], 6) for o in j["rows"]]
    other = c.get("/api/challenge/plan?sport=afl&start=10&goal=500").json()
    assert other["rows"] and other["pick"] is None
