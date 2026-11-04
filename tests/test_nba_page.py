# ruff: noqa: E501
"""AsynymBet NBA page (/nba): board + live PointsBet props -> legs and multis, fast and offline-safe."""

import json
import time
from datetime import UTC, datetime

import pytest
from test_asynym import ON, make

from melbcup import nba_feed
from melbcup.nba_feed import NbaFeed, nearest

PARAMS = {s: {"phi": 1.2, "ca": 1.0, "cb": 0.0} for s in ("points", "reboundsTotal", "assists", "threePointersMade")}
GAMES = [
    ("Philadelphia 76ers", "PHI", "Detroit Pistons", "DET", "Joel Embiid"),
    ("Charlotte Hornets", "CHA", "Brooklyn Nets", "BKN", "LaMelo Ball"),
    ("Dallas Mavericks", "DAL", "San Antonio Spurs", "SA", "Victor Wembanyama"),
]
BOARD = {
    "day": "20261104",
    "params": PARAMS,
    "games": [{"name": f"{a} at {h}", "teams": {"home": hc, "away": ac}, "when": "x"} for a, ac, h, hc, _ in GAMES],
    "players": [{"name": p, "team": ac, "minutes": 32.0, "mu": {"points": 26.0}} for _, ac, _, _, p in GAMES],
}
NOW = datetime(2026, 11, 4, 22, 0, tzinfo=UTC)  # 5pm 4 Nov in New York


def events(price=1.30):
    def fetch():
        return [
            {"event": str(i), "name": f"{a} @ {h}", "startsAt": "2026-11-05T00:00:00Z",
             "markets": [{"group": "Player Points Markets",
                          "outcomes": [{"name": f"{p} To Score 10+ Points", "price": price, "unitType": "Points"}]}]}
            for i, (a, _, h, _, p) in enumerate(GAMES)
        ]
    return fetch


@pytest.fixture
def bundled(tmp_path):
    path = tmp_path / "board.json"
    path.write_text(json.dumps(BOARD))
    return path


def test_feed_uses_azure_board_first_then_the_bundled_one(bundled, monkeypatch):
    from melbcup import nba_legs

    monkeypatch.setattr(nba_legs, "BLEND_W", 0.5)  # the old blend, so this fixture still has value legs
    feed = NbaFeed(read_blob=lambda name: None, events=events(), bundled=bundled, clock=lambda: NOW)
    v = feed.view()
    assert v["source"] == "bundled" and not v["stale"] and v["error"] is None
    assert v["report"]["cross_game"][0]["legs"] == 3
    azure = NbaFeed(read_blob=lambda name: json.dumps(BOARD).encode(), events=events(), bundled=bundled, clock=lambda: NOW)
    assert azure.view()["source"] == "azure"


def test_feed_says_nothing_worth_it_and_shows_the_nearest(bundled):
    v = NbaFeed(read_blob=None, events=events(1.01), bundled=bundled, clock=lambda: NOW).view()
    assert v["report"]["verdict"] == "nothing worth taking today"
    assert v["nearest"] and all(g["ev"] < 0.03 for g in v["nearest"])


def test_feed_survives_pointsbet_down_and_old_boards(bundled):
    def down():
        raise OSError("timeout")

    v = NbaFeed(read_blob=None, events=down, bundled=bundled, clock=lambda: NOW).view()
    assert "PointsBet did not answer" in v["error"] and v["report"]["legs_seen"] == 0
    later = datetime(2026, 11, 6, 22, 0, tzinfo=UTC)
    assert NbaFeed(read_blob=None, events=events(), bundled=bundled, clock=lambda: later).view()["stale"]


def test_feed_serves_the_cached_copy_while_it_refreshes(bundled, monkeypatch):
    calls = []

    def counted():
        calls.append(1)
        return events()()

    feed = NbaFeed(read_blob=None, events=counted, bundled=bundled, clock=lambda: NOW)
    first = feed.view()
    assert feed.view() is first and len(calls) == 1  # inside the 90 s window: no new fetch
    monkeypatch.setattr(nba_feed, "PRICES_TTL_S", 0)
    assert feed.view() is first  # expired: the old copy is served at once ...
    for _ in range(100):
        if len(calls) == 2 and feed._view[1] is not first:
            break
        time.sleep(0.01)
    assert len(calls) == 2 and feed._view[1] is not first  # ... while a refresh replaces it


def test_the_page_reads_the_timers_page_data_and_does_no_work(bundled):
    import gzip

    from melbcup import nba_legs

    view = nba_legs.view(BOARD, {"pb": events(1.25)(), "sb": events(1.35)()}, {3: 5.0})
    view["pricedAt"] = "2026-11-04T21:55:00+00:00"  # 5 minutes before NOW
    blobs = {"board-latest.json": json.dumps(BOARD).encode(), "view-latest.json.gz": gzip.compress(json.dumps(view).encode())}
    calls = []

    def fetch():
        calls.append(1)
        return events(1.40)()

    feed = NbaFeed(read_blob=blobs.get, events={"pb": fetch}, bundled=bundled, clock=lambda: NOW)
    v = feed.view()
    assert v["staged"] and calls == []  # nothing fetched or searched here
    assert v["agencies"]["sb"]["report"]["all_legs"][0]["price"] == 1.35
    later = datetime(2026, 11, 4, 22, 40, tzinfo=UTC)  # 45 minutes old: shown at once, redone behind
    old = NbaFeed(read_blob=blobs.get, events={"pb": fetch}, bundled=bundled, clock=lambda: later)
    v = old.view()
    assert v["staged"] and v["agencies"]["sb"]["report"]["all_legs"][0]["price"] == 1.35
    old._lock.acquire()  # wait for the background refresh
    old._lock.release()
    v = old.view()
    assert calls == [1] and not v.get("staged") and v["report"]["all_legs"][0]["price"] == 1.40

def test_nearest_only_likely_legs():
    legs = [{"chance": 0.9, "ev": -0.01}, {"chance": 0.5, "ev": 0.5}, {"chance": 0.8, "ev": -0.2}]
    assert nearest(legs) == [legs[0], legs[2]]


def test_nba_page_renders_with_tabs_and_money_header(bundled, monkeypatch):
    monkeypatch.setattr(nba_feed, "BUNDLED", bundled)
    monkeypatch.setattr(nba_feed.nba_legs, "live_events", events())
    monkeypatch.setattr(nba_feed.NbaFeed.__init__, "__defaults__", (None, events(), bundled, lambda: NOW))
    with make(ON) as c:
        html = c.get("/nba").text
        assert 'class="hd"' in html and ">NBA<" in html and 'aria-current="page">NBA' in html
        assert "Most likely to get up" not in html and "3 legs" in html  # Multis first, picks only
        assert "Stage 1" not in html and "result due" not in html  # nothing of the challenge here
        for tab, text in (("stacks", "$10 → $"), ("games", "Joel Embiid To Score 10+ Points"),
                          ("same", "No game has enough lines"), ("all", "LaMelo Ball To Score 10+ Points")):
            r = c.get(f"/nba?tab={tab}")
            assert r.status_code == 200 and text in r.text, tab
        assert ">NBA<" in c.get("/").text


def test_nba_page_is_off_without_asynym():
    from test_asynym import ENV

    with make({**ENV, "PUBLIC_ACCESS": "1"}) as c:
        assert c.get("/nba").status_code == 404


def test_offline_copy_without_the_nba_code_explains(monkeypatch):
    import builtins

    real = builtins.__import__

    def no_feed(name, *a, **k):
        if name == "melbcup.nba_feed":
            raise ImportError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_feed)
    with make(ON) as c:
        r = c.get("/nba")
        assert r.status_code == 200 and "needs the live site" in r.text


def test_times_carry_their_day(monkeypatch):
    from datetime import date

    from melbcup.web import views

    monkeypatch.setattr(views, "melbourne_today", lambda: date(2026, 11, 4))
    assert views.when("2026-11-05T00:00:00Z") == "Tomorrow 11:00am"  # 11am Thursday in Melbourne
    assert views.when("2026-11-04T01:30:00Z") == "Today 12:30pm"
    assert views.when("2026-11-07T08:00:00Z") == "Sat 7 Nov 7:00pm"
    assert views.when(None) == "–"


def test_prices_come_from_the_agency_switched_on(bundled, monkeypatch):
    def sb_events():
        return [{"event": f"sb{i}", "name": f"{a} @ {h}", "startsAt": "2026-11-05T00:10:00Z",
                 "markets": [{"group": "sportsbet", "outcomes": [
                     {"name": f"{p} 10+ Points", "price": 1.4, "player": p, "stat": "points", "k": 10, "under": False}]}]}
                for i, (a, _, h, _, p) in enumerate(GAMES)]

    agencies = {"pb": events(1.30), "sb": sb_events}
    monkeypatch.setattr(nba_feed.NbaFeed.__init__, "__defaults__", (None, agencies, bundled, lambda: NOW))
    with make(ON) as c:
        c.get("/?ag=1&on_sb=1&on_bf=1")  # Sportsbet and Betfair on, PointsBet off
        html = c.get("/nba?tab=all").text
        assert "with Sportsbet lines" in html and "$1.40" in html and 'aria-label="Prices from"' in html
        html = c.get("/nba?tab=all&bk=pb").text  # switch to PointsBet's prices
        assert "with PointsBet lines" in html and "$1.30" in html
        c.get("/?ag=1&on_pb=1")  # only PointsBet on
        assert "with PointsBet lines" in c.get("/nba?tab=all").text


def test_a_bubble_shows_when_the_other_agency_pays_more(bundled, monkeypatch):
    def sb_events():
        return [{"event": f"sb{i}", "name": f"{a} @ {h}", "startsAt": "2026-11-05T00:10:00Z",
                 "markets": [{"group": "sportsbet", "outcomes": [
                     {"name": f"{p} 10+ Points", "price": 1.4, "player": p, "stat": "points", "k": 10, "under": False}]}]}
                for i, (a, _, h, _, p) in enumerate(GAMES)]

    monkeypatch.setattr(nba_feed.NbaFeed.__init__, "__defaults__", (None, {"pb": events(1.30), "sb": sb_events}, bundled, lambda: NOW))
    with make(ON) as c:
        c.get("/?ag=1&on_sb=1&on_pb=1")
        on_pb = c.get("/nba?tab=all&bk=pb").text
        assert 'class="alt-pay"' in on_pb and "SB +0.10" in on_pb  # $1.40 at Sportsbet vs $1.30
        assert "SB +0.55" in c.get("/nba?tab=stacks&bk=pb").text  # 1.4^3 - 1.3^3 on the 3-leg multi
        assert 'class="alt-pay"' not in c.get("/nba?tab=all&bk=sb").text  # PointsBet pays less: no bubble
        c.get("/?ag=1&on_pb=1")  # Sportsbet off: no comparison
        assert 'class="alt-pay"' not in c.get("/nba?tab=all&bk=pb").text


def test_a_stage_that_is_likelier_at_the_other_agency_is_pointed_out():
    from types import SimpleNamespace

    from melbcup import nba_challenge
    from melbcup.web.views import Views

    def legs(c):
        return {"report": {"all_legs": [{"c": c, "startsAt": "2026-11-06T00:10:00Z"}]}}

    fake_legs = SimpleNamespace(same_game_for=lambda ls, x, stake: [{"chance": ls[0]["c"], "game": "G", "price": 2.4}] if ls else [])
    me = SimpleNamespace(_nba=SimpleNamespace(_view=(0, {"agencies": {"sb": legs(0.60), "pb": legs(0.70)}})), _nba_pick="sb", _agencies_on={"sb"})
    state = nba_challenge.fresh(stages=4)
    best = Views._best_elsewhere(me, state, 2.4, {"chance": 0.60}, nba_challenge, fake_legs)
    assert best["code"] == "pb" and best["chance"] == 0.70 and best["on"] is False
    assert Views._best_elsewhere(me, state, 2.4, {"chance": 0.695}, nba_challenge, fake_legs) is None  # within 1 point: stay
