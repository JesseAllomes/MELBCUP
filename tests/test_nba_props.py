"""NBA prop price collector (azure/function/nba_props.py): writes a game only when prices change."""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "azure" / "function"))
import nba_props  # noqa: E402
from test_racelens_snapshot import Container  # noqa: E402


def feed(price):
    market = {
        "key": "1",
        "name": "Player Points",
        "eventClass": "Player Points Over/Under",
        "groupName": "Player Points",
        "outcomes": [{"name": "J Embiid Over 25.5", "price": price, "points": 25.5, "playerId": "9"}],
    }

    def get(url):
        if "featured" in url:
            return {"events": [{"key": "77", "name": "A @ B", "startsAt": "x", "isLive": False}]}
        return {"fixedOddsMarkets": [market], "specialFixedOddsMarkets": []}

    return get


def test_only_changes_are_written(monkeypatch):
    box, now = Container(), dt.datetime(2026, 11, 5, 0, 0, tzinfo=dt.UTC)
    monkeypatch.setattr(nba_props, "get", feed(1.9))
    assert nba_props.collect(box, now) == (1, 1)
    assert nba_props.collect(box, now) == (1, 0)
    monkeypatch.setattr(nba_props, "get", feed(1.85))
    assert nba_props.collect(box, now + dt.timedelta(minutes=20)) == (1, 1)
    assert len([k for k in box.store if k.endswith(".gz")]) == 2
