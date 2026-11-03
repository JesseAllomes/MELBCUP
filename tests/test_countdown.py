"""The "R2 jumps in 4:12" strip: markup and data for open races, absent when none are open."""

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_racecard import FakeBoard, _models

from melbcup.config import load_settings
from melbcup.domain import RaceResult
from melbcup.web.views import Views

STATIC = Path(__file__).resolve().parent.parent / "melbcup/web/static"


def views_at(*minutes, finished=()):
    models = _models(len(minutes))
    now = datetime.now(UTC)
    for m, mins in zip(models, minutes, strict=True):
        m.race.start_time = now + timedelta(minutes=mins)
        if m.race.number in finished:
            m.race.result = RaceResult("final", {1: 1, 2: 2, 3: 3}, {}, {})
    return Views(load_settings({"APP_PASSWORD": "x"}), FakeBoard(models))


def data(html):
    return json.loads(re.search(r'id="alert-data">(.*?)</script>', html, re.S).group(1))



@pytest.fixture(autouse=True)
def _web_clock_before_the_card():
    """These tests build their races relative to the real clock: no pinned clock here."""
    yield


def test_strip_counts_down_to_the_next_open_race_on_every_page():
    views = views_at(-30, 4, 40)  # R1 has run, R2 jumps in about 4 minutes
    for path in ("/", "/race/2", "/history", "/meetings"):
        html = views.page(path, {})
        assert 'id="alertbar"' in html and 'class="ab-alerts"' in html, path
        assert re.search(r'href="/race/2">R2 jumps in [34]:\d\d<', html), path
        assert [r["n"] for r in data(html)] == [2, 3], path
    assert data(views.page("/", {}))[0]["left"] in range(235, 241)


def test_strip_is_absent_when_no_race_is_ahead():
    for views in (views_at(-30, -10), views_at(5, 9, finished=(1, 2))):
        html = views.page("/", {})
        assert "alertbar" not in html and "alert-data" not in html


def test_strip_script_has_the_alert_behaviour():
    js = (STATIC / "app.js").read_text()
    for text in (
        "BET NOW · R", "jumps in", "navigator.vibrate([200, 100, 200])", "AudioContext",
        'Notification.permission === "granted"', '"Bet now: R" + r.n + " jumps in 3 min"',
        "sessionStorage", "window.location.reload()", "ALERT_AT = 180", 'get("now")',
    ):
        assert text in js, text
    assert ".alertbar.hot" in (STATIC / "app.css").read_text()
