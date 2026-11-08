# ruff: noqa: E501
"""The NFL page is the NBA page: same templates and tabs, fed by NFL legs."""

from datetime import UTC, datetime, timedelta

import pytest
from test_asynym import ON, make

from melbcup import catalogue_view as cv
from melbcup import discover, nfl_legs


def _rows():
    soon = (datetime.now(UTC) + timedelta(hours=20)).isoformat()
    rows = []
    for e, game in enumerate(("Chiefs @ Bills", "Eagles @ Cowboys", "Jets @ Dolphins")):
        for p in range(4):
            for rung, price in ((40, 1.2), (60, 1.5), (80, 2.2)):
                rows.append(
                    {
                        "market_family": "player_receiving_yards",
                        "market_subtype": "alternate",
                        "market_name_raw": "Player Receiving Yards",
                        "side": "over",
                        "line_numeric": rung - 0.5,
                        "line_raw": f"{rung}+",
                        "price_decimal": price + 0.02 * p,
                        "participant_name": f"Player {e}{p}",
                        "event_name": game,
                        "event_id": f"ev{e}",
                        "event_start_utc": soon,
                        "is_player_prop": True,
                    }
                )
    return rows


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


def test_nfl_challenge_tab_is_the_nba_accordion(c):
    html = c.get("/sports?sport=nfl&tab=challenge").text
    assert "chs-list" in html
    assert "PICKED FOR YOU" not in html
    assert 'name="chscope" value="nfl"' in html


def test_nfl_multis_use_the_nba_slip_markup(c):
    nfl = c.get("/sports?sport=nfl&tab=multis").text
    assert 'class="pc' in nfl and "Bet this" in nfl and "I placed this" in nfl
    assert "Player 0" in nfl


def test_nfl_games_sgm_all_render_the_nba_templates(c):
    games = c.get("/sports?sport=nfl&tab=games").text
    assert "Chiefs @ Bills" in games and "nba-leg" in games
    sgm = c.get("/sports?sport=nfl&tab=sgm").text
    assert "nba-multi" in sgm or "No game has enough lines yet" in sgm


def test_nba_pages_unchanged_and_other_sports_keep_the_hub(c):
    assert c.get("/sports?sport=nba&tab=challenge").status_code == 200
    assert 'name="chscope" value="nba"' in c.get("/sports?sport=nba&tab=challenge").text
    afl = c.get("/sports?sport=afl&tab=challenge").text
    assert "Player 0" not in afl
