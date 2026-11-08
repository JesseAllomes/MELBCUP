# ruff: noqa: E501
"""Challenge list accordion rows: pct + bar, failed rows red, live.json that survives errors."""

import json
from urllib.parse import quote

from test_live_chance import LABEL

NOWS = {"ok": ("in", None, [9, 2], None), "failed": ("in", None, [13, 2], [False, None])}


c_track = [None]


def _client(monkeypatch, tmp_path, kind, boom=False):
    from test_asynym import ON, make
    from test_nba_page import BOARD, NOW, events

    from melbcup import nba_feed, nba_live
    from melbcup.web import app as app_module
    from melbcup.web import views

    path = tmp_path / "board.json"
    path.write_text(json.dumps(BOARD))
    monkeypatch.setattr(
        nba_feed.NbaFeed.__init__, "__defaults__", (None, events(1.75), path, lambda: NOW)
    )
    day = __import__("datetime").date(2026, 11, 5)
    monkeypatch.setattr(views, "melbourne_today", lambda: day)
    monkeypatch.setattr(app_module, "melbourne_today", lambda: day)
    state, verdict, nows, oks = NOWS[kind]
    parse = nba_live.parse

    def track(label, now=None, fetch=None):
        if boom and getattr(track, "armed", False):
            raise RuntimeError("feed down")
        legs = [
            g | {"now": n, "ok": o}
            for g, n, o in zip(parse(label)[1], nows, oks or [None, None], strict=True)
        ]
        return {
            "state": state, "clock": "Q3 4:12", "legs": legs, "verdict": verdict,
            "failed": sum(o is False for o in (oks or [])), "period": 3, "clock_s": 252,
            "frac_left": 0.4,
        }

    monkeypatch.setattr(nba_live, "track", track)
    c_track[0] = track
    c = make(ON)
    c.__enter__()
    c.get("/?ag=1&on_pb=1&on_sb=1&pb=100")
    c.get("/nba?tab=challenge&ch=newch&chname=Run&chmode=multi")
    c.get(f"/nba?tab=challenge&chid=ch1&ch=place&chs=0&chag=pb&chp=5.0&chtip=2020-01-01T00:00:00Z&chc=40,80&chl={quote(LABEL)}")
    return c


def test_list_rows_have_pct_and_bar(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, "ok")
    html = c.get("/sports?sport=nba&tab=challenge").text
    assert 'class="chs-row' in html and 'data-id="ch1"' in html
    assert "--p:" in html and 'class="chs-pct">' in html and "chs-head" in html
    assert 'class="chs-row failed' not in html
    c.__exit__(None, None, None)


def test_failed_row_is_red_and_says_failed(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, "failed")
    html = c.get("/sports?sport=nba&tab=challenge&chid=ch1").text
    assert "chs-row open failed" in html and ">Failed<" in html
    assert 'class="tile r"' in html and 'class="tile x"' in html and "no longer counts" in html
    assert html.index('class="tile r"') < html.index('class="tile x"')
    c.__exit__(None, None, None)


def test_live_json_returns_json_and_survives_tracker_error(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, "failed")
    r = c.get("/nba/challenges/live.json")
    assert r.status_code == 200 and r.json()["ch1"]["failed"] is True
    c.__exit__(None, None, None)
    c = _client(monkeypatch, tmp_path, "ok", boom=True)
    c_track[0].armed = True
    r = c.get("/nba/challenges/live.json")
    assert r.status_code == 200 and "ch1" in r.json()
    c.__exit__(None, None, None)
