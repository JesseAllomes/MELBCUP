"""The race card as the owner sees it (BUILD 2026-11-01, .grok/product-ui/): wallet bars, SB/BF
price pills, Good/Short price, Placed buttons, the exotics on the right races."""

import json
import re
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from test_bets import FIELD, make_model

from melbcup.config import MELBOURNE, load_settings
from melbcup.live import Snapshot
from melbcup.web.racecard import dollars, one_in, parse_placed, pills
from melbcup.web.views import Views

PRICES = [3.5, 3.0, 6.0, 10.0, 13.0, 15.0]
PLACES = [1.4, 1.5, 2.0, 2.5, 3.0, 3.5]


def _models(n=8):
    models = []
    for i in range(1, n + 1):
        m = make_model(i, FIELD, PRICES, PLACES)
        m.race.name = f"Race {i} Stakes"
        m.race.start_time = datetime(2026, 11, 3, 11, 45, tzinfo=MELBOURNE) + timedelta(
            minutes=35 * i
        )
        m.race.distance_m = 1200
        m.race.condition = "Good 4"
        for p in m.race.prices.values():  # Betfair a little better than Sportsbet on runner 1
            p.betfair_win = p.sportsbet_win * (1.3 if p.number == 1 else 0.9)
        models.append(m)
    return models


class FakeBoard:
    can_fetch = False
    archive = None

    def __init__(self, models):
        self.models = models

    def snapshot(self):
        race_date = self.models[0].race.race_date
        return Snapshot(
            card=SimpleNamespace(condition="Good 4", races=[m.race for m in self.models]),
            models=self.models,
            updated_at=None,
            race_date=race_date,
            venue="Flemington",
        )

    def history(self):
        return []

    def check_totals(self):
        return None


@pytest.fixture
def views():
    return Views(load_settings({"APP_PASSWORD": "x"}), FakeBoard(_models()))


def page(views, path, query=None, cookies=None):
    return views.page(path, query or {}, cookies or {})


def test_race_page_has_the_locked_sections_in_order(views):
    html = page(views, "/race/5")
    order = [
        'class="wallet"',
        'class="strip"',
        'class="head"',
        "Win, place, each way",
        "Exotics in this race",
        "The field",
        "Last-minute check",
        "Gambling Help Online 1800 858 858",
    ]
    at = [html.index(x) for x in order]
    assert at == sorted(at)
    assert 'aria-current="page">R5<' in html
    assert "Race 5 Stakes" in html and "Tue 2:40pm · 1200m · 6 runners · Good 4" in html


def test_wallet_bars_on_every_page(views):
    for path in ("/", "/race/1", "/history"):
        html = page(views, path)
        assert "Sportsbet</b><span><b class=\"left\">$150</b> left of $150" in html, path
        assert "Betfair</b><span><b class=\"left\">$50</b> left of $50" in html, path


def test_price_pills_sportsbet_and_betfair_with_the_better_one_filled(views):
    html = page(views, "/race/1")
    assert '<span class="pill sb"><small>SB</small>$3.50</span>' in html
    assert '<span class="pill bf best"><small>BF</small>$4.55</span>' in html  # 4.55 net 4.27
    assert '<span class="pill sb best"><small>SB</small>$3.00</span>' in html
    assert '<span class="pill bf"><small>BF</small>$2.70</span>' in html


def test_pills_compare_betfair_after_commission():
    p = SimpleNamespace(
        sportsbet_win=5.0, betfair_win=5.3, sportsbet_place=None, betfair_place=None
    )
    sb, bf = pills(p)
    assert sb.best and not bf.best  # 5.30 on Betfair is 4.88 after 8% commission
    p.betfair_win = 5.6
    sb, bf = pills(p)
    assert bf.best and not sb.best
    assert pills(None) == []


def test_good_and_short_price_and_no_old_verdicts(views):
    html = page(views, "/race/1")
    assert 'class="verdict good">Good price<' in html
    assert 'class="verdict short">Short price<' in html
    for word in ("BET", "HOLD", "SKIP", "For fun"):
        assert not re.search(rf">\s*{word}\b", html), word


def test_placed_buttons_on_every_staked_pick_and_exotic(views):
    html = page(views, "/race/1")
    board = html.split('class="board"')[1].split("</section>")[0]
    assert board.count("Placed on Sportsbet") == board.count("Placed on Betfair") >= 3
    exotics = html.split("Exotics in this race")[1].split("The field")[0]
    assert "Placed on Sportsbet" in exotics and "Placed on Betfair" not in exotics


def test_quinella_and_trifecta_cards_say_what_dividend_they_need(views):
    html = page(views, "/race/3")
    for kind in ("Quinella", "Trifecta"):
        card = html.split(f"<h3>{kind}</h3>")[1].split("</article>")[0]
        assert re.search(r'<span class="amt">\$\d+</span>', card), kind
        assert "Lands " in card and "of the dividend" in card or "times the dividend" in card
        assert re.search(r"Worth a try only if Sportsbet&#39;s estimate is over \$[\d,]+\.", card)
    assert "On average quinellas pay less than that." in html
    assert "Trifectas lost money in testing." in html


def test_first_four_on_its_own_race(views):
    assert "First Four, race 3" in page(views, "/race/3")
    assert "First Four, race 3" not in page(views, "/race/4")


def test_quaddie_card_only_on_its_first_race_and_a_leg_line_after(views):
    # 8 races: the Early Quaddie is races 1-4 and the Quaddie races 5-8
    first = page(views, "/race/5")
    assert "Quaddie starts here, races 5 to 8" in first
    for n in (6, 7, 8):
        later = page(views, f"/race/{n}")
        assert "starts here" not in later
        assert f"Quaddie leg {n - 4} (races 5 to 8): your numbers" in later
    assert "Early quaddie starts here, races 1 to 4" in page(views, "/race/1")


def test_field_shows_top_six_then_a_toggle(views):
    assert 'class="more"' not in page(views, "/race/2")  # six runners: nothing hidden
    big = [0.3, 0.2, 0.12, 0.1, 0.08, 0.07, 0.06, 0.04, 0.03]
    m = make_model(1, big, [3.0, 4.5, 8.0, 9.0, 12.0, 14.0, 15.0, 26.0, 34.0], None)
    html = page(Views(load_settings({"APP_PASSWORD": "x"}), FakeBoard([m])), "/race/1")
    field = html.split('id="field"')[1].split("</ul>")[0]
    assert field.count("<li ") == 9 and field.count(" hidden>") == 3
    assert 'data-more="field" data-label="Show all 9 runners"' in html
    assert "Wins 3 in 10 · places" in field and "Wins 1 in 33" in field


def test_placed_tick_shows_and_counts_against_its_account(views):
    html = page(views, "/race/1")
    win = re.search(r'data-acct="bf" data-rec="([^"]+)"', html).group(1)
    rec = json.loads(win.replace("&#34;", '"'))
    assert rec[:3] == ["2026-11-03", 1, "w"] and rec[5] > 0
    rec[4], rec[5] = "bf", 9
    jar = {"placed": quote(json.dumps([rec]))}
    html = page(views, "/race/1", cookies=jar)
    assert "Placed $9 on Betfair" in html and "✓ BF $9" in html
    assert "$41</b> left of $50" in html and "$150</b> left of $150" in html
    day = page(views, "/", cookies=jar)
    assert "1 placed" in day and "$41</b> left of $50" in day


def test_placed_records_for_other_dates_and_junk_are_ignored():
    when = datetime(2026, 11, 3).date()
    raw = quote(json.dumps([
        ["2026-11-02", 1, "w", 1, "sb", 5],  # yesterday
        ["2026-11-03", 1, "w", 1, "xx", 5],  # no such account
        ["2026-11-03", 2, "t", 7, "bf", 3],  # exotic: always Sportsbet, no runner
        ["2026-11-03", 2, "t", 0, "sb", 4],  # the same slot again
        "junk",
    ]))
    placed = parse_placed(raw, when)
    assert len(placed) == 1
    assert (placed[0].kind, placed[0].account, placed[0].key, placed[0].stake) == (
        "trifecta", "sportsbet", 0, 3
    )
    assert parse_placed("not json", when) == [] and parse_placed(None, when) == []


def test_day_page_lists_races_with_their_stakes(views):
    html = page(views, "/")
    assert "Quaddies and multis" not in html and "Bet now" not in html
    for n in range(1, 9):
        assert f'href="/race/{n}"' in html
    assert len(re.findall(r'<span class="rt"><b>\$\d+</b>', html)) == 8
    assert "Today&#39;s money" in html or "Today's money" in html


def test_chances_and_dollars_read_like_the_prototype():
    assert one_in(0.10) == "1 in 10" and one_in(0.125) == "1 in 8" and one_in(0.25) == "1 in 4"
    assert one_in(0.30) == "3 in 10" and one_in(0.28) == "3 in 10" and one_in(0.99) == "9 in 10"
    assert dollars(17) == "$17" and dollars(15.6) == "$15.60" and dollars(1285) == "$1,285"


def test_placed_multis_are_kept_by_their_legs():
    when = datetime(2026, 11, 3).date()
    raw = quote(json.dumps([
        ["2026-11-03", 1, "m", 101102011, "bf", 3],  # Betfair is not an option for a multi
        ["2026-11-03", 1, "m", 101202011, "sb", 2],  # same runner, but a place leg: its own slot
        ["2026-11-03", 1, "m", 101102011, "sb", 9],  # the same legs again
        ["2026-11-03", 1, "m", 1010201, "sb", 4],  # not a multi key (old four-digit legs)
    ]))
    placed = parse_placed(raw, when)
    assert [(p.kind, p.account, p.key, p.stake) for p in placed] == [
        ("multi", "sportsbet", 101102011, 3),
        ("multi", "sportsbet", 101202011, 2),
    ]


def test_day_page_shows_multi_picks_and_a_ticked_multi_drops_the_wallet(views):
    html = page(views, "/")
    assert "Multi picks for the day" in html
    assert html.index('id="races-h"') < html.index('id="multis-h"')
    cards = re.findall(r'<article class="bet multi.*?</article>', html, re.S)
    assert len(cards) == 5
    assert all('class="cloth sm"' in c and "Lands " in c for c in cards)
    assert all(re.search(r'class="lk">(Win|Place)</span>', c) for c in cards)
    assert all('class="pill sb best"' in c for c in cards)
    assert all(("Good price" in c) != ("Short price" in c) for c in cards)
    assert all('data-acct="sb"' in c and 'data-acct="bf"' not in c for c in cards)
    recs = [
        json.loads(r.replace("&#34;", '"'))
        for r in re.findall(r'data-acct="sb" data-rec="([^"]+)"', html.split('id="multis-h"')[1])
    ]
    assert len(recs) == 5 and all(r[2] == "m" and r[3] > 0 and r[5] > 0 for r in recs)
    ticked = [dict(zip("dkcnas", r, strict=True)) for r in recs[:2]]
    for r in recs[:2]:
        r[4] = "sb"
    jar = {"placed": quote(json.dumps(recs[:2]))}
    day = page(views, "/", cookies=jar)
    spent = sum(t["s"] for t in ticked)
    assert f"${150 - spent}</b> left of $150" in day
    assert day.count("aria-label=\"Placed $") == 2
