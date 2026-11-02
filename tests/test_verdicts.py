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
from melbcup.web.racecard import DEFAULT_BETFAIR, DEFAULT_SPORTSBET, pick_amounts
from melbcup.web.views import (
    Call,
    betting_open,
    call,
    multis_call,
    pick_budget,
    race_call,
    single_call,
)

# Every stake the race card shows: a pick's stake, an exotic's amount, a race's total.
STAKE = re.compile(r'<span class="(?:stake (?:sb|bf)|amt)">(.*?)</span>', re.S)
TOTAL = re.compile(r'<span class="rt">\s*<b>(.*?)</b>', re.S)


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
    """The single budget, still read by /api/offer."""
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


PAGES = ["/", "/race/1", "/race/2", "/?budget=500", "/race/2?sb=20&bf=0", "/?sb=1&bf=1"]


def stakes(html):
    return STAKE.findall(html) + TOTAL.findall(html)


@pytest.mark.parametrize("path", PAGES)
def test_every_stake_shown_has_dollars(client, path):
    html = client.get(path, auth=AUTH).text
    # each way shows the bookmaker's unit ("$2 EW") with the total under it
    assert all(
        re.fullmatch(r"\$\d[\d,]*(<small>\w+</small>| EW<small>\$\d+ total · \w+</small>)?", x)
        for x in stakes(html)
    ), path
    # the old verdict words are gone from the race card
    for word in ("BET <b>", ">HOLD<", ">SKIP<", "For fun"):
        assert word not in html, word


def test_every_stake_shown_has_dollars_under_cookie_amounts(client):
    client.cookies.set("sb_budget", "30")
    client.cookies.set("bf_budget", "0")
    for path in PAGES:
        html = client.get(path, auth=AUTH).text
        assert all(re.match(r"\$\d", x) for x in stakes(html)), path


def test_a_pick_with_no_money_shows_no_dollars_and_no_placed_buttons(client):
    html = client.get("/race/2?sb=0&bf=0", auth=AUTH).text
    assert "Win, place, each way" in html
    assert STAKE.findall(html) == [] and "data-rec=" not in html
    assert 'class="stake none"' in html


def test_the_day_never_goes_over_the_two_amounts(client):
    for sb, bf in ((150, 50), (20, 0), (7, 3), (1000, 0)):
        html = client.get(f"/?sb={sb}&bf={bf}", auth=AUTH).text
        total = sum(int(x.strip("$").replace(",", "")) for x in TOTAL.findall(html))
        assert 0 < total <= sb + bf, (sb, bf, total)
        on = {"sb": 0, "bf": 0}
        for n in (1, 2):
            race = client.get(f"/race/{n}?sb={sb}&bf={bf}", auth=AUTH).text
            for acct, amount in re.findall(r'<span class="stake (sb|bf)">\$(\d+)', race):
                on[acct] += int(amount)
            on["sb"] += sum(int(x) for x in re.findall(r'<span class="amt">\$(\d+)', race))
        assert on["sb"] <= sb and on["bf"] <= bf, (sb, bf, on)


def test_default_amounts_are_150_sportsbet_and_50_betfair(client):
    assert (DEFAULT_SPORTSBET, DEFAULT_BETFAIR) == (150, 50)
    html = client.get("/", auth=AUTH).text
    assert 'value="$150"' in html and 'value="$50"' in html
    assert "$150</b> left of $150" in html and "$50</b> left of $50" in html
    assert "budget=" not in html.split("<main")[1]


def test_amounts_come_from_the_query_then_the_cookies():
    assert pick_amounts({}, {}) == (150, 50, False)
    assert pick_amounts({}, {"sb_budget": "300", "bf_budget": "0"}) == (300, 0, True)
    assert pick_amounts({"sb": "$80", "bf": "20"}, {"sb_budget": "300"}) == (80, 20, True)
    assert pick_amounts({"budget": "75"}, {"sb_budget": "300"}) == (75, 0, True)  # old ?budget=
    assert pick_amounts({"budget": "lots"}) == (150, 50, False)
    assert pick_amounts({"sb": "", "bf": ""}) == (150, 50, False)  # blank resets
    assert pick_amounts({}, {"sb_budget": "%24120"}) == (120, 50, True)  # set by the browser


def test_cookie_amounts_are_used(client):
    client.cookies.set("sb_budget", "350")
    client.cookies.set("bf_budget", "25")
    html = client.get("/", auth=AUTH).text
    assert 'value="$350"' in html and 'value="$25"' in html
    assert 'value="$40"' in client.get("/?sb=40&bf=0", auth=AUTH).text


def test_submitting_amounts_remembers_them(client):
    r = client.get("/?sb=75&bf=10", auth=AUTH)
    cookies = r.headers.get_list("set-cookie")
    assert any("sb_budget=75" in c for c in cookies) and any("bf_budget=10" in c for c in cookies)
    r = client.get("/?budget=60", auth=AUTH)  # the old form: all on Sportsbet
    cookies = r.headers.get_list("set-cookie")
    assert any("sb_budget=60" in c for c in cookies) and any("bf_budget=0" in c for c in cookies)
    assert any("budget=60" in c and "_budget" not in c for c in cookies)  # still for /api/offer
    assert "set-cookie" not in client.get("/", auth=AUTH).headers


def test_bigger_amounts_give_bigger_race_dollars(client):
    def dollars(path):
        return sorted(int(x.strip("$")) for x in TOTAL.findall(client.get(path, auth=AUTH).text))

    assert dollars("/?sb=2000&bf=0") != dollars("/?sb=20&bf=0")
