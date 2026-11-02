"""PointsBet as a third betting account, behind POINTSBET=1.

Off (the default) the app is as it was: no PointsBet pill, bar, input, cookie or text, and the
same allocation. On, a single goes to whichever account pays most within that account's money,
no account is overspent, and the Melbourne Cup page notes the best "Run 2nd, You Win" value.
"""

import json
import pickle
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pytest
from conftest import rc_market
from fastapi.testclient import TestClient
from test_bets import FIELD, make_model
from test_racecard import PLACES, PRICES, FakeBoard

from melbcup import archive
from melbcup.bets import build_picks
from melbcup.bets.allocate import Placed, allocate_accounts
from melbcup.config import MELBOURNE, load_settings
from melbcup.domain import RunnerPrices
from melbcup.model.probability import top_k_probs
from melbcup.sources.racingcom import parse_market
from melbcup.web.app import create_app
from melbcup.web.racecard import PB_COOKIE, cup_note, parse_placed, pick_pointsbet, pills, wallet
from melbcup.web.views import Views

AUTH = ("u", "x")
PB_FACTOR = 1.25  # PointsBet pays 25% more than Sportsbet on every runner
ENV = {"APP_PASSWORD": "x"}


def models(n=8, pb=True, cup=5):
    out = []
    for i in range(1, n + 1):
        m = make_model(i, FIELD, PRICES, PLACES)
        m.race.name = "Lexus Melbourne Cup" if i == cup else f"Race {i} Stakes"
        m.race.start_time = datetime(2026, 11, 3, 11, 45, tzinfo=MELBOURNE) + timedelta(
            minutes=35 * i
        )
        for p in m.race.prices.values():
            p.betfair_win = p.sportsbet_win * 0.9  # Betfair is the worst of the three
            if pb:
                p.pointsbet_win = round(p.sportsbet_win * PB_FACTOR, 2)
                p.pointsbet_place = round(p.sportsbet_place * PB_FACTOR, 2)
        out.append(m)
    return out


RACE_DATE = models()[0].race.race_date


def views(on, **kw):
    env = ENV | ({"POINTSBET": "1"} if on else {})
    return Views(load_settings(env), FakeBoard(models(**kw)))


def day_picks(pointsbet, **kw):
    return build_picks(models(**kw), 200, pointsbet)


def summary(routed):
    return [
        (r.pick.race, r.pick.kind, r.account, r.pick.stake, r.price, r.placed) for r in routed
    ]


def spent(routed):
    out = {"sportsbet": 0, "betfair": 0, "pointsbet": 0}
    for r in routed:
        out[r.account] += r.pick.stake
    return out


def no_clock(html):
    """Page text without the "in 3 h 02 min" countdowns, which move with the wall clock."""
    return re.sub(r"in \d+ h \d+ min|in \d+ min", "", html)


# -- the switch ---------------------------------------------------------------------------------


def test_switch_is_off_unless_pointsbet_is_1():
    assert load_settings({}).pointsbet is False
    assert load_settings({"POINTSBET": "0"}).pointsbet is False
    assert load_settings({"POINTSBET": "yes"}).pointsbet is False
    assert load_settings({"POINTSBET": " 1 "}).pointsbet is True


# -- prices -------------------------------------------------------------------------------------


def test_racingcom_keeps_pointsbet_prices_beside_sportsbet():
    snap = parse_market({}, rc_market(1))
    six = snap.prices[6]  # PointsBet quotes the best win price on runner 6
    assert six.pointsbet_win == 51.0 and six.best_win.bookmaker == "pointsbetau"
    assert all(p.sportsbet_win for p in snap.prices.values())  # Sportsbet's are kept as before


def test_cards_saved_before_pointsbet_prices_still_load():
    """A pickled card from an older build has no pointsbet fields: they read as None."""
    old = RunnerPrices(1, sportsbet_win=3.0)
    del old.__dict__["pointsbet_win"], old.__dict__["pointsbet_place"]
    clone = pickle.loads(archive._unpack(archive._pack(pickle.dumps(old))))
    assert clone.pointsbet_win is None and clone.pointsbet_place is None
    assert clone.sportsbet_win == 3.0


# -- judging and routing ------------------------------------------------------------------------


def test_off_judging_and_allocation_ignore_pointsbet_prices():
    """Switch off: PointsBet prices on the card change nothing, and an allocation with no
    PointsBet amount is the same as before."""
    with_pb, without = day_picks(False, pb=True), day_picks(False, pb=False)
    for a, b in zip(with_pb.races, without.races, strict=True):
        for x, y in zip(a.singles, b.singles, strict=True):
            assert (x.price, x.bookmaker, x.ev, x.shown, x.value) == (
                y.price,
                y.bookmaker,
                y.ev,
                y.shown,
                y.value,
            )
    base = summary(allocate_accounts(with_pb, 150, 50))
    assert base == summary(allocate_accounts(without, 150, 50))
    assert not any(row[2] == "pointsbet" for row in base)


def test_on_with_no_pointsbet_money_changes_nothing():
    """POINTSBET=1 but a $0 PointsBet amount: the allocation is exactly the switched-off one."""
    d = day_picks(False)
    assert summary(allocate_accounts(d, 150, 50, pointsbet_budget=0.0)) == summary(
        allocate_accounts(d, 150, 50)
    )


def test_single_goes_to_pointsbet_when_it_pays_most_and_money_is_left():
    d = day_picks(True)
    routed = allocate_accounts(d, 100, 50, pointsbet_budget=100.0)
    on_pb = [r for r in routed if r.account == "pointsbet"]
    assert on_pb
    for r in on_pb:
        s = r.pick.single
        assert s.bookmaker == "pointsbetau" and r.pick.stake > 0
        assert r.price == pytest.approx(round(s.sportsbet * PB_FACTOR, 2))
        assert r.price > s.sportsbet and r.price > 0.9 * s.sportsbet  # beats SB and BF
    # exotics and multis stay with Sportsbet
    assert all(r.account == "sportsbet" for r in routed if r.pick.single is None)


def test_pointsbet_takes_nothing_when_another_account_pays_more():
    m = models()
    for mm in m:
        for p in mm.race.prices.values():
            p.pointsbet_win = p.sportsbet_win * 0.8
            p.pointsbet_place = p.sportsbet_place * 0.8
    d = build_picks(m, 200, True)
    routed = allocate_accounts(d, 150, 50, pointsbet_budget=100.0)
    assert not any(r.account == "pointsbet" for r in routed)


def test_pointsbet_has_no_minimum_stake_but_betfair_does():
    routed = allocate_accounts(day_picks(True), 10, 0.0, pointsbet_budget=12.0)
    assert any(r.account == "pointsbet" and r.pick.stake < 5 for r in routed)
    bf = allocate_accounts(day_picks(False), 40, 40.0)
    assert all(r.pick.stake >= 5 for r in bf if r.account == "betfair")


@pytest.mark.parametrize(
    "amounts", [(150, 50, 3), (10, 10, 7), (0, 0, 40), (80, 0, 25), (5, 5, 300), (0, 0, 2)]
)
def test_no_account_is_overspent(amounts):
    sb, bf, pb = amounts
    routed = allocate_accounts(day_picks(True), sb, bf, pointsbet_budget=pb)
    used = spent(routed)
    assert used["sportsbet"] <= sb and used["betfair"] <= bf and used["pointsbet"] <= pb


def test_placed_bets_count_against_their_own_account():
    d = day_picks(True)
    placed = [Placed(1, "win", 1, "pointsbet", 30), Placed(2, "win", 1, "sportsbet", 20)]
    routed = allocate_accounts(d, 100, 20, placed, pointsbet_budget=60.0)
    used = spent(routed)  # placed bets are in the routed list at their stake
    assert used["pointsbet"] <= 60 and used["sportsbet"] <= 100 and used["betfair"] <= 20
    held = [r for r in routed if r.placed]
    assert {(r.account, r.pick.stake) for r in held} == {("pointsbet", 30), ("sportsbet", 20)}


# -- the page -----------------------------------------------------------------------------------


def test_off_page_has_no_pointsbet_anywhere():
    v = views(False)
    cookies = {PB_COOKIE: "80", "placed": quote('[["2026-11-03",1,"w",1,"pb",9]]')}
    for path in ("/", "/race/1", "/race/5"):
        for query in ({}, {"pb": "50"}, {"sb": "40", "bf": "10", "pb": "50"}):
            html = v.page(path, query, cookies)
            assert "PointsBet" not in html and "pointsbet" not in html
            assert 'data-acct="pb"' not in html and 'class="pill pb' not in html
            assert 'name="pb"' not in html and "Run 2nd" not in html
            assert html.count('class="acct"') == 2
    assert parse_placed(cookies["placed"], RACE_DATE) == []


def test_off_page_is_unchanged_by_pointsbet_prices_cookies_and_query():
    plain, noisy = views(False, pb=False), views(False, pb=True)
    cookies = {PB_COOKIE: "80"}
    for path in ("/", "/race/1", "/race/5"):
        a, b = plain.page(path, {}, {}), noisy.page(path, {"pb": "9"}, cookies)
        assert no_clock(a) == no_clock(b)


def test_on_page_shows_pill_wallet_bar_and_amount_box():
    html = views(True).page("/race/1", {"pb": "60"}, {})
    assert html.count('class="acct"') == 3 and 'data-acct="pb"' in html
    assert "PointsBet</b>" in html and "left of $60" in html
    assert 'name="pb"' in html and 'value="$60"' in html
    assert 'class="pill pb' in html and "<small>PB</small>$4.38" in html  # 3.5 * 1.25
    assert "Placed on PointsBet" in html


def test_on_pointsbet_amount_is_zero_until_set_and_lives_in_the_cookie():
    v = views(True)
    assert 'value="$0"' in v.page("/", {}, {})
    assert pick_pointsbet({}, {}) == 0.0
    assert pick_pointsbet({"pb": "45"}, {PB_COOKIE: "10"}) == 45.0
    assert pick_pointsbet({}, {PB_COOKIE: "10"}) == 10.0
    assert pick_pointsbet({"pb": "junk"}, {PB_COOKIE: "10"}) == 0.0
    assert "left of $25" in v.page("/", {}, {PB_COOKIE: "25"})


def test_on_with_no_pointsbet_amount_bets_match_the_switched_off_page():
    """The bets and stakes shown are the same until an amount is set (only PointsBet's own
    pill, bar and box are added)."""
    off, on = views(False), views(True)
    take = lambda h: re.findall(r'<span class="stake[^"]*">.*?</span>', no_clock(h))  # noqa: E731
    for path in ("/", "/race/1", "/race/3"):
        assert take(off.page(path, {}, {})) == take(on.page(path, {}, {}))


def test_on_pointsbet_bets_appear_once_it_has_money():
    html = views(True).page("/race/2", {"pb": "200"}, {})
    assert 'class="stake pb"' in html and "<small>PointsBet</small>" in html


def test_ticking_placed_on_pointsbet():
    v = views(True)
    rec = json.dumps(["2026-11-03", 1, "w", 1, "pb", 12], separators=(",", ":"))
    cookies = {"placed": quote(f"[{rec}]"), PB_COOKIE: "60"}
    html = v.page("/race/1", {}, cookies)
    assert "✓ Placed $12 on PointsBet" in html
    assert '<b class="left">$48</b> left of $60' in html
    placed = parse_placed(cookies["placed"], RACE_DATE, True)
    assert [(p.account, p.stake) for p in placed] == [("pointsbet", 12)]
    # an exotic ticked on PointsBet is still a Sportsbet bet
    q = parse_placed(quote('[["2026-11-03",1,"q",0,"pb",5]]'), RACE_DATE, True)
    assert q[0].account == "sportsbet"


def test_wallet_and_pills_with_pointsbet():
    w = wallet(100, 50, [Placed(1, "win", 1, "pointsbet", 10)], 40)
    assert [a[0] for a in w.accounts()] == ["sb", "bf", "pb"]
    assert w.total == 190 and w.left == 180
    assert [a[0] for a in wallet(100, 50, []).accounts()] == ["sb", "bf"]
    prices = models()[0].race.prices[1]
    assert [p.account for p in pills(prices, "win", True)] == ["sb", "bf", "pb"]
    assert [p.account for p in pills(prices, "win", True) if p.best] == ["pb"]
    assert [p.account for p in pills(prices, "win")] == ["sb", "bf"]  # off: as before


# -- ?pb= and the cookie ------------------------------------------------------------------------


class ServerBoard(FakeBoard):
    bf = None

    def stop(self):
        pass

    @staticmethod
    def clock():
        return datetime.now(UTC)


def client_for(on):
    env = ENV | ({"POINTSBET": "1"} if on else {})
    app = create_app(load_settings(env), ServerBoard(models()), start_background=False)
    return TestClient(app)


def test_pb_query_sets_the_cookie_only_when_on():
    with client_for(True) as c:
        assert c.get("/?sb=100&bf=20&pb=35", auth=AUTH).status_code == 200
        assert c.cookies.get(PB_COOKIE) == "35" and c.cookies.get("sb_budget") == "100"
        assert "left of $35" in c.get("/", auth=AUTH).text  # remembered
        c.get("/?pb=", auth=AUTH)  # blank puts it back to $0
        assert c.cookies.get(PB_COOKIE) is None
    with client_for(False) as c:
        r = c.get("/?sb=100&bf=20&pb=35", auth=AUTH)
        assert PB_COOKIE not in r.headers.get("set-cookie", "") and not c.cookies.get(PB_COOKIE)
        assert "PointsBet" not in r.text
        assert c.cookies.get("sb_budget") == "100"  # the old cookies still work


# -- the Cup offer ------------------------------------------------------------------------------


def test_cup_note_names_the_best_run_second_you_win_value():
    rp = build_picks(models(), 200, False).races[4]
    note = cup_note(rp)
    race = rp.model.race
    top2 = top_k_probs({a.number: a.win for a in rp.model.ranked()}, 2)
    values = {n: top2[n] * p.pointsbet_win - 1 for n, p in race.prices.items()}
    assert note.number == max(values, key=values.get)
    assert note.value == pytest.approx(max(values.values()))
    assert note.price == race.prices[note.number].pointsbet_win


def test_cup_note_only_on_the_cup_with_pointsbet_prices():
    assert cup_note(build_picks(models(), 200, False).races[0]) is None  # not the Cup
    assert cup_note(build_picks(models(pb=False), 200, False).races[4]) is None  # no PB prices


def test_cup_page_shows_the_note_when_on_and_not_when_off():
    on = views(True).page("/race/5", {}, {})
    assert "Run 2nd, You Win" in on and "per $1" in on and "no stake is set" in on
    assert "Run 2nd" not in views(True).page("/race/4", {}, {})
    assert "Run 2nd" not in views(False).page("/race/5", {}, {})
