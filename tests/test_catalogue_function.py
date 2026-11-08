"""The catalogue wiring in the existing NBA timer (azure/function/function_app.py): at most every
30 minutes, after the NBA work, and a catalogue error never breaks the NBA work."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
import time

import pytest
from test_azure_function import PKG, FakeService, azure_stubs

NOW = dt.datetime(2026, 11, 7, 10, 0, tzinfo=dt.UTC)


@pytest.fixture
def fa(monkeypatch):
    for name, mod in azure_stubs().items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.syspath_prepend(str(PKG))
    monkeypatch.delitem(sys.modules, "collector_runtime", raising=False)
    spec = importlib.util.spec_from_file_location("function_app_catalogue", PKG / "function_app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    service = FakeService()
    monkeypatch.setattr(module, "blobs", lambda: service)
    monkeypatch.setattr(module, "now_utc", lambda: NOW)
    module.service = service
    return module


def fake_rotation(calls):
    def run(cursor, deadline, now, write, read=None, list_names=None, **kw):
        calls.append((cursor, deadline))
        write("catalogue/nba/latest.json.gz", b"x")
        return {
            "built": ["basketball"],
            "cursor": cursor + 1,
            "stats": [],
            "expired": ["catalogue/raw/nba/20260101/0000.json.gz"],
        }

    return run


def test_tick_builds_every_run_not_twice_inside_9_minutes(fa, monkeypatch):
    calls = []
    monkeypatch.setattr(fa.catalogue, "run_rotation", fake_rotation(calls))
    nba = fa.service.get_container_client("nba")
    nba.data["catalogue/raw/nba/20260101/0000.json.gz"] = b"old"
    fa._catalogue_tick(NOW, time.monotonic())
    assert len(calls) == 1 and nba.data["catalogue/nba/latest.json.gz"] == b"x"
    state = json.loads(nba.data["catalogue/state.json"])
    assert state["cursor"] == 1 and state["last_build"].startswith("2026-11-07T10:00")
    assert "catalogue/raw/nba/20260101/0000.json.gz" not in nba.data  # raw kept 3 days
    fa._catalogue_tick(NOW + dt.timedelta(minutes=5), time.monotonic())
    assert len(calls) == 1  # not twice inside one 10-minute tick
    fa._catalogue_tick(NOW + dt.timedelta(minutes=10), time.monotonic())
    assert len(calls) == 2 and calls[1][0] == 1  # the rotation cursor carries on


def test_tick_deadline_is_inside_the_function_timeout(fa, monkeypatch):
    calls = []
    monkeypatch.setattr(fa.catalogue, "run_rotation", fake_rotation(calls))
    host = json.loads((PKG / "host.json").read_text())
    limit = int(host["functionTimeout"].split(":")[-1])
    started = time.monotonic()
    fa._catalogue_tick(NOW, started)
    assert calls[0][1] - started < limit - 5
    # the NBA work used the time: no catalogue run this tick
    calls.clear()
    fa._catalogue_tick(NOW + dt.timedelta(hours=1), started - 40)
    assert calls == []


def test_catalogue_error_never_breaks_the_nba_work(fa, monkeypatch):
    ran = []
    monkeypatch.setattr(fa, "_nba_work", lambda moment, props=True: ran.append("nba"))

    def boom(*a, **k):
        raise RuntimeError("catalogue down")

    monkeypatch.setattr(fa.catalogue, "run_rotation", boom)
    fa.nba_props_run(object())  # no exception
    assert ran == ["nba"]
    assert "catalogue/state.json" not in fa.service.get_container_client("nba").data


def test_catalogue_switch_off(fa, monkeypatch):
    calls = []
    monkeypatch.setattr(fa.catalogue, "run_rotation", fake_rotation(calls))
    monkeypatch.setenv("CATALOGUE", "0")
    fa._catalogue_tick(NOW, time.monotonic())
    assert calls == []


def test_rotation_saves_cursor_before_each_sport(monkeypatch):
    """A run killed mid-sport (Function timeout) must start on the next sport next time."""
    from melbcup import catalogue

    saved = []
    monkeypatch.setattr(catalogue, "build", lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
    try:
        catalogue.run_rotation(4, 0, None, lambda n, b: None, save_cursor=saved.append)
    except TimeoutError:
        pass
    assert saved == [5]



def test_catalogue_has_its_own_timer(fa, monkeypatch):
    seen = []
    monkeypatch.setattr(fa, "_catalogue_tick", lambda m, s: seen.append("cat"))
    fa.catalogue_run(None)
    assert seen == ["cat"]
