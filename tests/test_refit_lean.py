"""Weekly lean refit (tools/nba/refit_lean.py) and picker v3 (shadow) in melbcup.nba_legs."""

import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "nba"))
import refit_lean as R  # noqa: E402

from melbcup import nba_legs as N  # noqa: E402


def leg(i, under, won, market=0.6, stat="points", line=8.5, day="d1"):
    return {"kind": "leg", "event": f"e{i}", "player": f"p{i}", "stat": stat, "line": line,
            "under": under, "market": market, "result": "won" if won else "lost", "day": day}


def anchor(i):  # the over points rung at >= 50% that makes a bench median
    return leg(i, False, True) | {"latest": False}


class Store:
    def __init__(self, rows):
        self.d = {"forward-v2.jsonl": "".join(json.dumps(x) + "\n" for x in rows).encode()}

    def read(self, n):
        return self.d.get(n)

    def write(self, n, b):
        self.d[n] = b


def test_shrinkage_and_cap():
    assert abs(R.shift(200, 0.6, 80, under=False) - 0.1) < 1e-9  # gap 0.2 over n=200, K=200
    assert R.shift(10**6, 0.9, 0, under=False) == R.CAP
    assert R.shift(200, 0.6, 160, under=True) > 0


def test_min_sample_no_move():
    rows = [anchor(i) for i in range(99)] + [leg(i, False, False) for i in range(99)]
    assert R.fit(rows) == {}
    rows += [anchor(99), leg(99, False, False)]
    f = R.fit(rows)
    assert f["bench|points|over"]["n"] == 100
    assert 0 < f["bench|points|over"]["shift"] < 0.6


def test_run_writes_blob_and_is_deterministic():
    rows = [anchor(i) for i in range(120)] + [leg(i, False, i % 4 == 0) for i in range(120)]
    a, b = Store(rows), Store(rows)
    now = dt.datetime(2026, 11, 9, tzinfo=dt.UTC)
    R.run(a, now)
    R.run(b, now)
    assert a.d[R.BLOB] == b.d[R.BLOB]
    assert json.loads(a.d[R.BLOB])["cells"]["bench|points|over"] > 0


def test_v3_lean_load_and_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("NBA_ACCOUNT", raising=False)
    monkeypatch.delenv("LEAN_V3_PATH", raising=False)
    N.set_lean_v3(None)
    assert N.lean_v3() == {}  # missing: v2's lean
    assert N.role_shade_v3(0.6, False, "points", "bench", True) == N.role_shade(0.6, False, "points", True)
    assert N.role_shade_v3(0.6, False, "points", "star", False) == N.shade(0.6, False)
    f = tmp_path / "lean.json"
    f.write_text(json.dumps({"cells": {"bench|points|over": 0.2, "star|points|under": 0.03}}))
    monkeypatch.setenv("LEAN_V3_PATH", str(f))
    N.set_lean_v3(None)
    assert abs(N.role_shade_v3(0.6, False, "points", "bench", True) - 0.4) < 1e-9
    assert abs(N.role_shade_v3(0.6, True, "points", "star", False) - 0.63) < 1e-9
    assert N.role_shade_v3(0.6, True, "rebounds", "star", False) == N.shade(0.6, True)  # no cell
    N.set_lean_v3(None)


def test_v3_tag_logged_not_live(monkeypatch):
    monkeypatch.delenv("PICKER", raising=False)
    assert N.picker() == "v2"
    with N.use("v3"):
        assert N.picker() == "v3"
        assert N.rung_margin(2.5) == N.rung_margin(2.5, "v2")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "azure", "function"))
    import nba_props

    part = {"stacks": [], "stacks_same": [], "by_game": []}
    log = nba_props.build_log(
        "pb", part | {"picker": "v2", "value_legs": [], "all_legs": [], "day": "20261110"}, {},
        dt.datetime(2026, 11, 10, tzinfo=dt.UTC),
        part | {"picker": "v1"}, part | {"picker": "v3", "stacks": [{
            "legs": 2, "chance": 0.5, "price": 2.0, "picks": ["a", "b"], "detail": [
                {"event": "e", "label": "a", "line": 1, "price": 1.4},
                {"event": "e", "label": "b", "line": 1, "price": 1.4}]}]},
    )
    assert "v3" in {m["picker"] for m in log["multis"]}


def test_daily_refit_only_on_monday_melbourne():
    import daily

    s = Store([])
    assert daily.weekly_refit(s, dt.datetime(2026, 11, 10, 3, tzinfo=dt.UTC)) == ""  # Tuesday
    assert daily.weekly_refit(s, dt.datetime(2026, 11, 9, 3, tzinfo=dt.UTC)).startswith("lean-v3 refit")
    assert R.BLOB in s.d
