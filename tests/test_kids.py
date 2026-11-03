"""Kids' bets (the kids cookie), the picks JSON on every page, the BACK badge colour and the
hash import of kids' records."""

import json
import re
from datetime import date
from urllib.parse import quote

import pytest
from test_racecard import FakeBoard, _models
from test_settle import race

from melbcup.bets.settle import settle_bet
from melbcup.config import load_settings
from melbcup.domain import RaceResult
from melbcup.web.racecard import parse_kids, wallet
from melbcup.web.views import Views

DATE = "2026-11-03"
CUP = date(2026, 11, 3)


def kids_cookie(*recs):
    return {"kids": quote(json.dumps(list(recs), separators=(",", ":")))}


def make_views(settings=None, finish=None):
    models = _models()
    if finish:
        models[6].race.result = RaceResult("final", finish, {}, {})
        models[6].race.places_paid = 4
    s = load_settings({"APP_PASSWORD": "x", "POINTSBET": "1", **(settings or {})})
    return Views(s, FakeBoard(models))


def test_kids_parse_like_placed_but_repeats_stay():
    raw = kids_cookie(
        [DATE, 7, "e", 4, "pb", 5, 17.0, 6.0, "Ava"],
        [DATE, 7, "e", 4, "pb", 5, 17.0, 6.0, "Ben"],  # two kids, the same bet: both stay
        [DATE, 7, "w", 3, "pb", 2, 9.0, None, ""],
        [DATE, 7, "p", 3, "pb", 2, 9.0, 2.5, ""],  # place bet: the place price
        ["2026-11-02", 7, "w", 3, "pb", 2, 9.0, None, ""],  # another day
        [DATE, 7, "q", 3, "pb", 2, 9.0, None, ""],  # not a horse bet
        [DATE, 7, "w", 3, "xx", 2, 9.0, None, ""],  # unknown account
    )["kids"]
    kids = parse_kids(raw, CUP, True)
    assert [(k.bet.kind, k.bet.key, k.name) for k in kids] == [
        ("each_way", 4, "Ava"), ("each_way", 4, "Ben"), ("win", 3, ""), ("place", 3, "")
    ]
    assert (kids[0].bet.price, kids[0].bet.place_price, kids[0].bet.stake) == (17.0, 6.0, 5)
    assert kids[3].bet.price == 2.5 and kids[0].detail == "EW $5 · PB 17.00/6.00"
    assert parse_kids(raw, CUP, False) == []  # PointsBet off: no pb records
    assert parse_kids("not json", CUP, True) == [] and parse_kids(None, CUP, True) == []


def test_kids_each_way_settles_half_win_half_place():
    r = race(7, {5: 1, 4: 2, 9: 3, 8: 4}, places_paid=4, n=24)
    kid = parse_kids(kids_cookie([DATE, 7, "e", 4, "pb", 5, 17.0, 6.0, ""])["kids"], CUP, True)[0]
    s = settle_bet(kid.bet, {7: r})
    # 2nd of 24, 4 places paid: the place half ($2.50) at 6.00 returns $15; profit $10
    assert (s.status, s.returns, s.profit) == ("settled", 15.0, 10.0)
    lost = parse_kids(kids_cookie([DATE, 7, "e", 12, "pb", 5, 5.5, 2.15, ""])["kids"], CUP, True)[0]
    assert settle_bet(lost.bet, {7: r}).profit == -5.0


def test_kids_card_renders_at_the_bottom_with_total_and_inputs():
    views = make_views(finish={1: 1, 4: 2, 3: 3, 2: 4})
    recs = [
        [DATE, 7, "e", 4, "pb", 5, 17.0, 6.0, "Ava"],
        [DATE, 7, "e", 5, "pb", 5, 11.0, 3.7, ""],
    ]
    html = views.page("/race/7", {}, kids_cookie(*recs))
    assert "Kids' bets" in html and html.count('class="pick kid"') == 2
    assert "EW $5 · PB 17.00/6.00" in html and "EW $5 · PB 11.00/3.70" in html
    assert 'class="kid-name"' in html and 'value="Ava"' in html and "data-kid-remove" in html
    assert "WON +$10.00" in html and "LOST −$5.00" in html
    assert re.search(r'Kids: <b class="pos">\+\$5\.00</b>', html)
    assert html.index("Last-minute check") < html.index('id="kids-h"')
    assert html.index('id="kids-h"') < html.index("Gambling Help Online")
    assert 'id="kids-h"' not in views.page("/race/6", {}, kids_cookie(*recs))
    assert 'id="kids-h"' not in views.page("/race/7", {}, {})


def test_kids_stakes_come_off_pointsbet_left_and_count_in_today():
    views = make_views(finish={1: 1, 4: 2, 3: 3, 2: 4})
    jar = {"pb_budget": "30", **kids_cookie([DATE, 7, "e", 4, "pb", 5, 17.0, 6.0, ""],
                                            [DATE, 7, "e", 5, "pb", 5, 11.0, 3.7, ""])}
    html = views.page("/", {}, jar)
    assert re.search(r'<b class="left">\$20</b> / \$30', html)
    assert re.search(r'Today <b class="pos">|<b class="pos">Today \+\$5\.00', html)
    assert "incl. kids" in html
    assert "incl. kids" not in views.page("/", {}, {"pb_budget": "30"})
    w = wallet(150, 50, [], 30)
    assert w.pointsbet_used == 0


def test_kids_stakes_do_not_show_in_the_owners_race_pnl():
    views = make_views(finish={1: 1, 4: 2, 3: 3, 2: 4})
    html = views.page("/race/7", {}, kids_cookie([DATE, 7, "e", 4, "pb", 5, 17.0, 6.0, ""]))
    assert "Your bets this race" not in html


def test_back_badge_is_red_for_a_loss_and_green_for_a_profit():
    from melbcup.web.views import make_env

    badge = make_env().get_template("_card.html").module.badge
    from types import SimpleNamespace

    from melbcup.bets.allocate import Placed
    from melbcup.bets.settle import Settled

    def line(returns, stake=8):
        bet = Placed(1, "each_way", 1, "sportsbet", stake)
        return SimpleNamespace(settled=Settled(bet, "settled", returns))

    assert 'class="outcome neg">BACK $6.48' in str(badge(line(6.48)))
    assert "BACK $6.48 · −$1.52" in str(badge(line(6.48)))
    assert 'class="outcome pos">WON' in str(badge(line(12.0)))


def test_picks_json_is_on_every_page_for_open_races():
    views = make_views()
    for path in ("/", "/history", "/meetings", "/race/3"):
        html = views.page(path, {}, {})
        m = re.search(r'<script type="application/json" id="picks-data">(.*?)</script>', html)
        assert m, path
        data = json.loads(m.group(1))
        assert data["date"] == DATE and sorted(data["open"]) == list(range(1, 9))
        assert {r[1] for r in data["picks"]} == set(range(1, 9)), path
        for rec in data["picks"]:
            assert rec[0] == DATE and rec[2] in ("w", "p", "e") and rec[5] > 0
            assert rec[4] in ("sb", "bf", "pb")


def test_picks_json_holds_placed_kinds_and_leaves_run_races_out():
    views = make_views(finish={1: 1, 4: 2, 3: 3, 2: 4})
    html = views.page("/", {}, {"placed": quote(json.dumps([[DATE, 1, "w", 2, "sb", 10]]))})
    data = json.loads(re.search(r'id="picks-data">(.*?)</script>', html).group(1))
    assert 7 not in data["open"] and all(r[1] != 7 for r in data["picks"])
    assert [1, "w"] in data["held"] and not any(r[1] == 1 and r[2] == "w" for r in data["picks"])


def test_js_saves_picks_from_the_json_and_imports_kids_from_the_hash():
    html = make_views().page("/history", {}, {})
    assert 'getElementById("picks-data")' in html
    assert '"#kids="' in html and "decodeURIComponent(location.hash.slice(6))" in html
    assert 'history.replaceState(null, "", location.pathname + location.search)' in html
    assert 'write(list, "kids")' in html and "location.reload()" in html


@pytest.mark.parametrize("path", ["/", "/history", "/meetings"])
def test_pages_still_render_with_kids_and_no_card(path):
    assert make_views().page(path, {}, kids_cookie([DATE, 7, "w", 3, "pb", 2, 9.0, None, ""]))
