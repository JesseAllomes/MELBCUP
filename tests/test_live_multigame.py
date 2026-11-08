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
