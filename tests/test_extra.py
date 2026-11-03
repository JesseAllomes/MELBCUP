"""Other bets (the extra cookie): parse, the day page card and form, and the money."""

import json
from datetime import date
from pathlib import Path
from urllib.parse import quote

from test_kids import DATE, make_views
from test_racecard import FakeBoard  # noqa: F401

from melbcup.web.racecard import parse_extras, parse_legs

CUP = date(2026, 11, 3)


def jar(*recs, **more):
    return {"extra": quote(json.dumps(list(recs), separators=(",", ":"))), **more}


def test_parse_legs():
    assert parse_legs("1:6w,7:4p,10:3w") == ((1, 6, "win"), (7, 4, "place"), (10, 3, "win"))
    assert parse_legs("1:6w") == () and parse_legs("1:6w,1:2w") == ()
    assert parse_legs("1:6x,2:3w") == () and parse_legs("") == ()
    assert len(parse_legs(",".join(f"{i}:1w" for i in range(1, 9)))) == 8
    assert parse_legs(",".join(f"{i}:1w" for i in range(1, 10))) == ()


def test_parse_extras_reads_both_kinds_and_drops_bad_records():
    raw = jar(
        [DATE, "multi", "1:6w,7:4p,10:3w", "sb", 5, 12.4, "", ""],
        [DATE, "other", "", "bf", 10, 6, "Quinella R5 3-7", 45.5],
        [DATE, "other", "", "pb", 10, 6, "pb", ""],
        ["2026-01-01", "multi", "1:6w,7:4p", "sb", 5, 3.0, "", ""],  # another day
        [DATE, "multi", "1:6w", "sb", 5, 3.0, "", ""],  # one leg
        [DATE, "multi", "1:6w,2:1w", "sb", 0, 3.0, "", ""],  # no stake
        [DATE, "multi", "1:6w,2:1w", "sb", 5, 1.0, "", ""],  # no odds
        "junk",
    )["extra"]
    xs = parse_extras(raw, CUP, False)
    assert [(x.bet.kind, x.bet.account, x.bet.stake, x.bet.odds) for x in xs] == [
        ("multi", "sportsbet", 5.0, 12.4),
        ("other", "betfair", 10.0, 6.0),
    ]
    assert xs[0].chips == "R1 6W · R7 4P · R10 3W" and xs[0].detail == "$5 @ 12.40 · SB"
    assert xs[1].bet.result == 45.5 and xs[1].chips == "Quinella R5 3-7"
    assert len(parse_extras(raw, CUP, True)) == 3
    assert parse_extras("not json", CUP) == [] and parse_extras(None, CUP) == []


def test_day_page_shows_form_and_card():
    views = make_views()
    html = views.page("/", {}, {})
    assert "Record another bet" in html and 'id="extra-races"' in html
    assert "record with changes" in html or "Multi picks" not in html
    html = views.page(
        "/",
        {},
        jar(
            [DATE, "multi", "1:6w,2:4p", "sb", 5, 12.4, "", ""],
            [DATE, "other", "", "sb", 10, 6, "Quinella R5 3-7", ""],
        ),
    )
    assert 'id="extra-h"' in html and "R1 <span" in html and "$5 @ 12.40 · SB" in html
    assert "Quinella R5 3-7" in html and "PENDING" in html and "returned $" in html
    typed = views.page("/", {}, jar([DATE, "other", "", "sb", 10, 6, "Q", 45.5]))
    assert "WON +$35.50" in typed


def test_extra_stakes_reduce_money_left_and_profit_counts():
    views = make_views()
    plain = views.page("/", {}, {"sb_budget": "100", "bf_budget": "0"})
    ctx = views._context(
        "/", {}, jar([DATE, "other", "", "sb", 30, 6, "Q", 100], sb_budget="100", bf_budget="0")
    )
    assert ctx["wallet"].sportsbet_used == 30 and ctx["wallet"].left == 70
    assert ctx["pnl"].profit == 70.0
    assert views._context("/", {}, {"sb_budget": "100", "bf_budget": "0"})["wallet"].left == 100
    assert plain


def test_a_tote_other_bet_needs_no_odds_and_a_link_can_import_it():
    from datetime import date

    from melbcup.web.racecard import parse_extras

    raw = '[["2026-11-03","other","","pb",10,0,"First Four R7",""]]'
    got = parse_extras(raw, date(2026, 11, 3), pointsbet=True)
    assert got and "@ tote" in got[0].detail
    base = (Path(__file__).resolve().parents[1] / "melbcup/web/templates/_bets_js.html").read_text()
    assert '#extra=' in base and "importExtra" in base
