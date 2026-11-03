# ruff: noqa: E501
"""AsynymBet NBA page (/nba): board + live PointsBet props -> legs and multis, fast and offline-safe."""

import json
import time
from datetime import UTC, datetime

import pytest
from test_asynym import ON, make

from melbcup import nba_feed
from melbcup.nba_feed import NbaFeed, nearest

PARAMS = {s: {"phi": 1.2, "ca": 1.0, "cb": 0.0} for s in ("points", "rebounds", "assists", "threes")}
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


def test_feed_uses_azure_board_first_then_the_bundled_one(bundled):
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


def test_cold_start_shows_the_functions_last_pricing_then_goes_live(bundled):
    from melbcup import nba_legs

    saved = nba_legs.report(BOARD, events(1.25)()) | {"pricedAt": "2026-11-04T21:40:00+00:00"}
    blobs = {"board-latest.json": json.dumps(BOARD).encode(), "legs-latest.json": json.dumps(saved).encode()}
    feed = NbaFeed(read_blob=blobs.get, events=events(1.40), bundled=bundled, clock=lambda: NOW)
    first = feed.view()
    assert first["report"]["all_legs"][0]["price"] == 1.25  # at once, from the Function
    for _ in range(200):
        if feed._view[1] is not first:
            break
        time.sleep(0.01)
    assert feed._view[1]["report"]["all_legs"][0]["price"] == 1.40  # then live


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
        assert "Most likely to get up" in html and "3-leg multi" in html
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
