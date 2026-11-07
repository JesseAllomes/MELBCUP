"""The Sports hub (/sports): redirect, every tab, the coverage matrix, no invented prices."""

import re

import pytest
from test_asynym import ON, make

from melbcup import sports_hub

CODES = [
    "nba",
    "racing",
    "afl",
    "nrl",
    "nfl",
    "nhl",
    "football",
    "tennis",
    "nbl",
    "ncaab",
    "ncaaf",
    "aflw",
    "rugby-league",
    "cricket",
    "mlb",
    "rugby-union",
    "other",
    "all",
]
UNPRICED = [c for c in CODES if c not in ("nba", "racing", "other", "all")]


@pytest.fixture
def c():
    with make(ON) as client:
        yield client


def test_nba_redirects_with_params(c):
    r = c.get("/nba?tab=challenge&bk=pb", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/sports?sport=nba&tab=challenge&bk=pb"
    assert c.get("/nba", follow_redirects=False).headers["location"] == "/sports?sport=nba"
    assert c.get("/nba?tab=challenge").status_code == 200  # followed to the hub


@pytest.mark.parametrize("code", CODES)
def test_each_tab_renders(c, code):
    r = c.get(f"/sports?sport={code}")
    assert r.status_code == 200
    assert 'class="sp-tabs"' in r.text and ">Sports<" in r.text
    assert 'href="/sports" class="on"' in r.text  # the nav item is lit
    for label in ("NBA", "Racing", "AFL", "NRL", "NFL", "NHL", "Football", "Tennis", "All"):
        assert f">{label}</a>" in r.text


def test_default_is_best_multis_and_nba_still_there(c):
    assert "Best multis across every sport" in c.get("/sports").text  # the Sports home (owner)
    assert "NBA player props" in c.get("/sports?sport=nba").text


def test_matrix_has_every_sport(c):
    html = c.get("/sports?sport=all").text
    assert {s.code for s in sports_hub.SPORTS} == set(CODES) - {"all"}
    for s in sports_hub.SPORTS:
        assert f'href="/sports?sport={s.code}">{s.name}</a></th>' in html
    assert "blocks automated download" in html and "dataset is not finished" in html


@pytest.mark.parametrize("code", UNPRICED)
def test_no_prices_on_unpriced_sports(c, code):
    html = c.get(f"/sports?sport={code}").text
    card = _card(html)
    assert "No live prices yet" in card
    assert not re.search(r"\$\s?\d|\d%|\d\.\d\d\b", card)


def _card(html):
    start = html.index('<section class="card sp-card">')
    return re.sub(r"\d{4}(-\d{2,4})?", "", html[start : html.index("</section>", start)])
