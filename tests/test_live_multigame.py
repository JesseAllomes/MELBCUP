"""Owner 2026-11-08: a multi across several games is tracked too ("Game A: legs; Game B: legs")."""

from melbcup import nba_live as L


def _one(state, legs, failed=0):
    return {"state": state, "clock": state, "legs": legs, "failed": failed, "verdict": None}


def test_two_games_merge(monkeypatch):
    games = {
        "Houston Rockets @ Phoenix Suns: Fred VanVleet Under 2.5 Threes": _one(
            "post", [{"ok": True}]
        ),
        "San Antonio Spurs @ Portland Trail Blazers: Stephon Castle Over 1.5 Threes": _one(
            "in", [{"ok": None}]
        ),
    }
    monkeypatch.setattr(L, "_track_one", lambda label, now=None, fetch=None: games[label])
    label = "; ".join(games)
    t = L.track(label)
    assert t["state"] == "in" and len(t["legs"]) == 2 and t["verdict"] is None and t["games"] == 2
    games["San Antonio Spurs @ Portland Trail Blazers: Stephon Castle Over 1.5 Threes"] = _one(
        "post", [{"ok": False}], 1
    )
    t = L.track(label)
    assert t["state"] == "post" and t["verdict"] == "lost1"


def test_one_game_label_unchanged(monkeypatch):
    monkeypatch.setattr(L, "_track_one", lambda label, now=None, fetch=None: _one("pre", []))
    assert L.track("Houston Rockets @ Phoenix Suns: A 10+ Points")["state"] == "pre"


def test_event_matches_on_team_nicknames():
    """'Los Angeles Clippers' in a label must find ESPN's 'New Orleans Pelicans at LA Clippers'."""
    from datetime import datetime, UTC
    from melbcup import nba_live

    board = {"events": [{"id": "1", "name": "New Orleans Pelicans at LA Clippers"},
                        {"id": "2", "name": "New Orleans Pelicans at Golden State Warriors"}]}
    eid = nba_live._event("New Orleans Pelicans @ Los Angeles Clippers", datetime(2026, 11, 9, 6, tzinfo=UTC),
                          fetch=lambda url: board, day="20261108")
    assert eid == "1"
