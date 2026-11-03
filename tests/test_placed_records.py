"""Record a bet I placed: several placed records to a race and kind, an optional price taken, the
form on each race page and the Remove button."""

import json
import re
from urllib.parse import quote

import pytest
from test_racecard import FakeBoard, _models

from melbcup.bets import build_picks
from melbcup.bets.allocate import Placed, allocate_accounts
from melbcup.config import load_settings
from melbcup.web.racecard import parse_placed, wallet
from melbcup.web.views import Views

DATE = "2026-11-03"


@pytest.fixture
def views():
    return Views(load_settings({"APP_PASSWORD": "x"}), FakeBoard(_models()))


def cookie(*recs):
    return {"placed": quote(json.dumps(list(recs), separators=(",", ":")))}


def race_date():
    return _models()[0].race.race_date


def test_several_records_per_race_and_kind_parse():
    raw = cookie(
        [DATE, 1, "w", 2, "sb", 10], [DATE, 1, "w", 3, "bf", 5], [DATE, 1, "w", 2, "bf", 7]
    )["placed"]
    out = parse_placed(raw, race_date())
    assert [(p.key, p.account, p.stake) for p in out] == [
        (2, "sportsbet", 10), (3, "betfair", 5), (2, "betfair", 7)
    ]
    # the same race, kind, runner and account is a repeat
    dup = cookie([DATE, 1, "w", 2, "sb", 10], [DATE, 1, "w", 2, "sb", 4])["placed"]
    assert [p.stake for p in parse_placed(dup, race_date())] == [10]


def test_old_six_element_and_new_seven_element_records_parse():
    raw = cookie([DATE, 1, "w", 2, "sb", 10], [DATE, 2, "p", 4, "bf", 6, 2.35])["placed"]
    old, new = parse_placed(raw, race_date())
    assert old.price is None and new.price == 2.35 and new.stake == 6
    bad = cookie([DATE, 1, "w", 2, "sb", 10, "x"], [DATE, 1, "w", 3, "sb", 10, 1, 2, 3])["placed"]
    assert [p.price for p in parse_placed(bad, race_date())] == [None]


def test_two_win_records_in_one_race_both_count_and_both_show(views):
    jar = cookie([DATE, 1, "w", 2, "sb", 10], [DATE, 1, "w", 2, "bf", 8, 3.1])
    html = views.page("/race/1", {}, jar)
    assert html.count("Placed $10 on Sportsbet") == 1 and "✓ SB $10" in html
    assert html.count("Placed $8 on Betfair") == 1 and "✓ BF $8" in html
    assert html.count('class="pick is-placed"') == 2
    assert html.count(">remove<") == 2
    # no new win suggestion in that race: only the two placed lines are win lines
    board = html.split('class="board"')[1].split("board-foot")[0]
    assert board.count('<span class="type">Win</span>') == 2
    assert "Price taken $3.10" in html
    assert "$8 returns $24.80" in html
    # each account's money left is its amount less its own placed stakes
    assert '<b class="left">$140</b> left of $150' in html
    assert '<b class="left">$42</b> left of $50' in html


def test_money_left_per_account_is_amount_less_that_accounts_stakes():
    placed = [
        Placed(1, "win", 1, "sportsbet", 10),
        Placed(1, "win", 2, "betfair", 8),
        Placed(1, "win", 3, "sportsbet", 5),
    ]
    w = wallet(150, 50, placed)
    assert (w.sportsbet_used, w.betfair_used) == (15, 8)
    assert w.left == (150 - 15) + (50 - 8)
    day = Views(load_settings({"APP_PASSWORD": "x"}), FakeBoard(_models()))
    snap = day.board.snapshot()
    picks = build_picks(snap.models, 200)
    routed = allocate_accounts(picks, 150, 50, placed)
    held = [r for r in routed if r.placed]
    assert len(held) == 3
    spent = {
        a: sum(r.pick.stake for r in routed if r.account == a) for a in ("sportsbet", "betfair")
    }
    assert spent["sportsbet"] <= 150 and spent["betfair"] <= 50
    # a race and kind with any placed record gets no new suggestion
    assert [r for r in routed if (r.pick.race, r.pick.kind) == (1, "win") and not r.placed] == []


def test_seven_element_price_is_shown(views):
    html = views.page("/race/1", {}, cookie([DATE, 1, "p", 3, "sb", 12, 1.85]))
    assert "Price taken $1.85" in html and "$12 returns $22.20" in html


def test_a_placed_runner_without_a_pick_line_still_shows(views):
    html = views.page("/race/1", {}, cookie([DATE, 1, "e", 6, "sb", 6, 16.0]))
    assert "Placed $6 on Sportsbet" in html and "✓ SB $6" in html and "Price taken $16.00" in html


def test_record_form_renders_with_starters(views):
    html = views.page("/race/2", {}, {})
    assert 'class="record-bet"' in html and "+ Record a bet" in html
    form = html.split('class="record-bet"')[1].split("</form>")[0]
    assert 'data-race="2"' in form and f'data-date="{DATE}"' in form
    assert form.count("<option value=") >= 6 + 3 + 2
    assert re.search(r'<option value="1">1 [^<]+</option>', form)
    assert "Win</option>" in form and "Place</option>" in form and "Each way</option>" in form
    assert ">Sportsbet<" in form and ">Betfair<" in form and "PointsBet" not in form
    assert "total of both halves" in html and 'name="stake"' in form and 'name="price"' in form


def test_form_offers_pointsbet_only_when_on():
    on = Views(load_settings({"APP_PASSWORD": "x", "POINTSBET": "1"}), FakeBoard(_models()))
    assert "PointsBet</option>" in on.page("/race/1", {}, {})


def test_remove_and_tick_js_present(views):
    html = views.page("/race/1", {}, cookie([DATE, 1, "w", 2, "sb", 10, 3.1]))
    assert 'button[data-remove]' in html and 'closest("button[data-rec]")' in html
    assert 'classList.contains("record-bet")' in html and "function same(" in html
    rm = re.search(r'data-remove="([^"]+)"', html).group(1).replace("&#34;", '"')
    assert json.loads(rm) == [DATE, 1, "w", 2, "sb", 10, 3.1]
