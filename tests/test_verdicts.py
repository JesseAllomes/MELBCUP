"""Every pick carries one verdict, derived from the value rule and the existing price verdict."""

import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from conftest import Router
from fastapi.testclient import TestClient
from test_live_web import AUTH, ENV, START, Clock, board_with

from melbcup.config import load_settings
from melbcup.web.app import create_app
from melbcup.web.views import (
    DEFAULT_BUDGET,
    Call,
    betting_open,
    call,
    make_env,
    multis_call,
    pick_budget,
    race_call,
    single_call,
)

CHIP = re.compile(r'<span class="chip bet"[^>]*>(.*?)</span>', re.S)


def test_value_is_a_bet_with_its_stake():
    assert call(True, 12, 3.0, 0.4) == Call("bet", 12)
    assert Call.bet(12).stake == 12


def test_a_bet_with_no_stake_is_a_hold():
    assert call(True, None, None, None) == Call("hold")
    assert Call.bet(None).kind == "hold" and Call.bet(0).kind == "hold"
    assert Call("bet").kind == "hold" and Call("bet", 0).kind == "hold"
    assert Call("hold", 5).stake is None  # only a bet carries a stake


def test_short_prices_skip_and_the_rest_hold():
    assert call(False, None, 2.0, 0.40).kind == "skip"  # pays 80% of fair: "Short: skip"
    assert call(False, None, 2.4, 0.40).kind == "hold"  # 96% of fair
    assert call(False, None, None, 0.40).kind == "hold"  # no price yet


def test_single_call_prefers_the_sportsbet_price():
    s = SimpleNamespace(value=False, stake=None, sportsbet=2.0, price=3.0, prob=0.4)
    assert single_call(s).kind == "skip"
    s.sportsbet = None
    assert single_call(s).kind == "hold"


def test_betting_closes_once_a_race_has_run():
    now = datetime.now(UTC)
    ahead = SimpleNamespace(result=None, start_time=now + timedelta(minutes=20))
    gone = SimpleNamespace(result=None, start_time=now - timedelta(minutes=30))
    done = SimpleNamespace(result=object(), start_time=now + timedelta(minutes=20))
    assert betting_open(ahead) and not betting_open(gone) and not betting_open(done)


def test_zero_stake_value_multi_holds_and_a_staked_one_bets():
    macro = make_env().get_template("_chip.html").module.multi_row
    leg = SimpleNamespace(race=3, number=10, name="Tuscan Rose")
    m = SimpleNamespace(legs=[leg, leg], value=True, stake=None, price=20.0, prob=0.08)
    assert "chip hold" in str(macro(m)) and "chip bet" not in str(macro(m))
    m.stake = 0
    assert "chip bet" not in str(macro(m))
    m.stake = 7
    assert "BET <b>$7</b>" in str(macro(m))


def test_quaddie_row_without_outlay_holds():
    macro = make_env().get_template("_chip.html").module.quaddie_row
    e = SimpleNamespace(
        kind="quaddie", outlay=None, leg_labels=["a", "b"], combos=4, prob=0.01,
        flexi_pct=None, fair_dividend=100.0,
    )  # fmt: skip
    assert "chip bet" not in str(macro(e))
    e.outlay = 3
    assert "BET <b>$3</b>" in str(macro(e))


def _line(kind, stake):
    return SimpleNamespace(kind=kind, stake=stake, number=1, value=True)


def _race(**best):
    best.setdefault("top_win", None)
    return SimpleNamespace(best=best, singles=[], model=None)


def test_race_call_sums_the_win_place_and_each_way_stakes():
    win, place, ew = _line("win", 5), _line("place", 7), _line("each_way", 4)
    assert race_call(_race(win=win, place=place, each_way=ew)) == Call("bet", 16)
    assert race_call(_race(win=win)) == Call("bet", 5)


def test_race_call_counts_a_line_once_and_holds_at_zero():
    both = _line("win", 6)
    assert race_call(_race(win=both, place=both)) == Call("bet", 6)  # same object twice
    assert race_call(_race(win=_line("win", None), place=_line("place", 0))).kind == "hold"


def test_multis_call_sums_quaddies_and_value_multis():
    quaddie = SimpleNamespace(recommended=True, outlay=2)
    unlisted = SimpleNamespace(recommended=False, outlay=9)
    multis = [
        SimpleNamespace(value=True, stake=3),
        SimpleNamespace(value=True, stake=None),
        SimpleNamespace(value=False, stake=8),
    ]
    picks = SimpleNamespace(quaddies=[quaddie, unlisted], multis=multis)
    assert multis_call(picks) == Call("bet", 5)
    picks.quaddies, picks.multis = [], [SimpleNamespace(value=True, stake=0)]
    assert multis_call(picks).kind == "hold"


def test_budget_is_query_then_cookie_then_200():
    assert DEFAULT_BUDGET == 200
    assert pick_budget({}, {}) == (200, False)
    assert pick_budget({}, {"budget": "350"}) == (350, True)
    assert pick_budget({"budget": "50"}, {"budget": "350"}) == (50, True)
    assert pick_budget({"budget": "$75"}) == (75, True)
    assert pick_budget({"budget": ""}, {"budget": "350"}) == (200, False)  # blank resets
    assert pick_budget({"budget": "lots"}) == (200, False)
    assert pick_budget({}, {"budget": "0"}) == (200, False)


@pytest.fixture
def client():
    board = board_with(Router(), Clock(START))
    board.load_card_now(wait=True)
    app = create_app(load_settings(ENV), board, start_background=False)
    with TestClient(app) as c:
        yield c


PAGES = ["/", "/race/1", "/race/2", "/?budget=500", "/race/2?budget=20", "/?budget=1"]


@pytest.mark.parametrize("path", PAGES)
def test_no_page_shows_a_bet_without_dollars(client, path):
    html = client.get(path, auth=AUTH).text
    assert html.count('class="chip bet"') == len(CHIP.findall(html))
    assert all(re.search(r"\$\d", c) for c in CHIP.findall(html))
    # nothing renders a bare BET chip, whatever the markup
    assert not re.search(r"chip bet[^>]*>\s*BET\s*</span>", html)


def test_no_page_shows_a_bet_without_dollars_under_a_cookie_budget(client):
    client.cookies.set("budget", "30")
    for path in PAGES:
        html = client.get(path, auth=AUTH).text
        assert all(re.search(r"\$\d", c) for c in CHIP.findall(html)), path


def test_the_default_budget_is_200(client):
    html = client.get("/", auth=AUTH).text
    assert 'value="200"' in html
    assert "budget=" not in html.split("<main")[1]  # not chosen, so links stay plain


def test_a_cookie_budget_is_used(client):
    client.cookies.set("budget", "350")
    html = client.get("/", auth=AUTH).text
    assert 'value="350"' in html and "/race/1?budget=350" in html
    assert 'value="40"' in client.get("/?budget=40", auth=AUTH).text


def test_submitting_a_budget_remembers_it(client):
    r = client.get("/?budget=75", auth=AUTH)
    assert "budget=75" in r.headers["set-cookie"]
    r = client.get("/?budget=", auth=AUTH)
    assert 'budget=""' in r.headers["set-cookie"] or "Max-Age=0" in r.headers["set-cookie"]
    assert "set-cookie" not in client.get("/", auth=AUTH).headers


def test_a_bigger_budget_gives_bigger_race_dollars(client):
    def dollars(path):
        return sorted(
            int(x) for x in re.findall(r"BET <b>\$(\d+)</b>", client.get(path, auth=AUTH).text)
        )

    assert dollars("/?budget=2000") != dollars("/?budget=20")
