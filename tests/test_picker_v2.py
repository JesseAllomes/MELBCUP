"""Picker v2 behind the PICKER switch (owner, 2026-11-10; Fable review section 4): v1 is the picker as
it was, v2 adds the role-aware lean, raised rung margins and the drift re-pick; both are logged."""

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for sub in ("azure/function", "tools/nba", "tests"):
    sys.path.insert(0, str(ROOT / sub))
import nba_props  # noqa: E402
import settle as S  # noqa: E402
from test_nba_legs import BOARD, EVENTS, event, out, player  # noqa: E402

from melbcup import nba_challenge  # noqa: E402
from melbcup import nba_legs as N  # noqa: E402

BENCH_BOARD = BOARD | {"players": BOARD["players"] + [player("Ben Bench", "PHI", 7.0)]}
BENCH_EVENTS = [
    event(
        "1",
        "Philadelphia 76ers @ Detroit Pistons",
        [out(f"Ben Bench To Score {k}+ Points", p) for k, p in ((4, 1.15), (6, 1.5), (8, 2.4))]
        + [out("Joel Embiid To Score 20+ Points", 1.6), out("Joel Embiid To Score 10+ Points", 1.15)],
    )
]


def leg_of(legs, who, line):
    return next(g for g in legs if g["player"] == who and g["line"] == line and not g["under"])


def test_switch_reads_env_at_runtime(monkeypatch):
    monkeypatch.delenv("PICKER", raising=False)
    assert N.picker() == "v2"  # the default is live
    monkeypatch.setenv("PICKER", "v1")
    assert N.picker() == "v1"
    monkeypatch.setenv("PICKER", " V2 ")
    assert N.picker() == "v2"
    monkeypatch.setenv("PICKER", "junk")
    assert N.picker() == "v2"
    monkeypatch.setenv("PICKER", "v1")
    with N.use("v2"):
        assert N.picker() == "v2"
    assert N.picker() == "v1"


def test_rung_margin_values(monkeypatch):
    monkeypatch.setenv("PICKER", "v1")
    assert [N.rung_margin(p) for p in (1.2, 2.0, 2.5, 4.0, 7.0)] == [0.067, 0.076, 0.063, 0.10, 0.10]
    monkeypatch.setenv("PICKER", "v2")
    assert [N.rung_margin(p) for p in (1.2, 2.0, 2.5, 4.0, 7.0, 12.0)] == [0.067, 0.076, 0.15, 0.22, 0.32, 0.50]
    assert N.rung_margin(2.5, "v1") == 0.063  # an explicit version wins over the env


def _old_module(tmp_path):
    src = subprocess.run(
        ["git", "show", "ccr-63b3240a-qdwy3g:melbcup/nba_legs.py"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if src.returncode:
        pytest.skip("pre-change nba_legs.py not in git history")
    f = tmp_path / "nba_legs_before.py"
    f.write_text(src.stdout)
    spec = importlib.util.spec_from_file_location("nba_legs_before", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _strip(x):
    """Drop the keys v2 added to leg dicts (chance_v1, chance_v2, bench)."""
    if isinstance(x, dict):
        return {k: _strip(v) for k, v in x.items() if k not in ("chance_v1", "chance_v2", "bench")}
    return [_strip(v) for v in x] if isinstance(x, list) else x


def _digest(rep):
    legs = [(g["label"], g["chance"], g["fair"], g["ev"], g["market"], g["raw"]) for g in rep["all_legs"]]
    return _strip([legs, rep["stacks"], rep["stacks_same"], rep["by_game"], rep["value_legs"] and [g["label"] for g in rep["value_legs"]]])


def test_v1_is_identical_to_the_picker_before(tmp_path, monkeypatch):
    old = _old_module(tmp_path)
    monkeypatch.setenv("PICKER", "v1")
    for board, events in ((BOARD, EVENTS), (BENCH_BOARD, BENCH_EVENTS)):
        before = old.report(board, events)
        now = N.report(board, events)
        assert json.dumps(_digest(now), sort_keys=True) == json.dumps(_digest(before), sort_keys=True)
        assert before["stacks"] == now["stacks"] and now["all_legs"]


def test_v2_lean_lowers_a_bench_over_and_raises_his_under():
    legs, _ = N.legs_from(BENCH_EVENTS, BENCH_BOARD)
    market = N.market_probs({"pb": legs})
    N.apply_market(legs, market)
    bench = leg_of(legs, "Ben Bench", 6)
    star = leg_of(legs, "Joel Embiid", 10)
    assert bench["bench"] and not star["bench"]
    assert bench["chance_v2"] < bench["chance_v1"] - 0.05  # about 9 points off a bench points over
    assert star["chance_v2"] == star["chance_v1"]  # starters keep the flat 0.013 lean
    # an under for the same bench player gains about 9 points under v2 and 1.3 under v1
    under = N.role_shade(0.4, True, "points", True)
    assert under == pytest.approx(0.49) and N.role_shade(0.4, True, "points", False) == pytest.approx(N.shade(0.4, True))
    assert N.role_shade(0.4, True, "assists", True) == pytest.approx(0.44)
    assert N.role_shade(0.6, False, "assists", True) == pytest.approx(0.55)


def test_live_chance_follows_the_switch(monkeypatch):
    legs, _ = N.legs_from(BENCH_EVENTS, BENCH_BOARD)
    mk = N.market_probs({"pb": legs})
    monkeypatch.setenv("PICKER", "v1")
    N.apply_market(legs, mk)
    g = leg_of(legs, "Ben Bench", 6)
    assert g["chance"] == g["chance_v1"] != g["chance_v2"]
    monkeypatch.setenv("PICKER", "v2")
    N.apply_market(legs, N.market_probs({"pb": legs}))
    assert g["chance"] == g["chance_v2"]


def test_drift_repick_triggers_above_three_percent_only():
    step = {"detail": [{"game": "G", "label": "A 20+ Points", "price": 2.00}, {"game": "G", "label": "B", "price": 1.5}]}
    now = lambda p: [{"game": "G", "label": "A 20+ Points", "price": p}, {"game": "G", "label": "B", "price": 1.5}]  # noqa: E731
    assert nba_challenge.drifted(step, now(2.04)) == []  # 2%: held
    assert nba_challenge.drifted(step, now(2.05)) == []  # 2.5%: held
    moves = nba_challenge.drifted(step, now(2.08))  # 4%: re-pick
    assert moves and moves[0]["from"] == 2.0 and moves[0]["to"] == 2.08
    assert nba_challenge.drifted(step, now(1.80)) == []  # a shorter price (more likely) is fine
    assert nba_challenge.repick_note(moves) == "re-picked: A 20+ Points drifted from $2.00 to $2.08"


def test_forward_log_carries_the_picker_tag_for_both_versions_through_settlement(monkeypatch):
    monkeypatch.setenv("PICKER", "v2")
    legs, _ = N.legs_from(BENCH_EVENTS, BENCH_BOARD)
    N.apply_market(legs, N.market_probs({"pb": legs}))
    pick = [leg_of(legs, "Joel Embiid", 10)]
    pick_b = [leg_of(legs, "Joel Embiid", 10) | {"chance": 0.5}]
    rep = {"day": "20261104", "picker": "v2", "all_legs": legs, "value_legs": [], "stacks": [N.multi(pick, 10.0)],
           "stacks_same": [], "by_game": []}
    shadow = {"picker": "v1", "stacks": [N.multi(pick_b, 10.0)], "stacks_same": [], "by_game": []}
    now = dt.datetime(2026, 11, 4, 20, tzinfo=dt.UTC)
    log = nba_props.build_log("pb", rep, {}, now, shadow)
    tags = sorted(m["picker"] for m in log["multis"])
    assert tags == ["v1", "v2"]  # same picks, both kept apart
    assert all("chance_v1" in x and "chance_v2" in x for x in log["legs"])
    rows = S.settle_log(json.loads(json.dumps(log)), {"joel embiid": {"min": 30, "points": 25}})
    multis = [x for x in rows if x["kind"] == "multi"]
    assert sorted(x["picker"] for x in multis) == ["v1", "v2"] and all(x["result"] == "won" for x in multis)
    assert S.multi_key(multis[0]) != S.multi_key(multis[1])  # each version is its own bet in forward-v2


def test_view_logs_the_other_version_as_shadow(monkeypatch):
    monkeypatch.setenv("PICKER", "v2")
    v = N.view(BENCH_BOARD, {"pb": BENCH_EVENTS})
    a = v["agencies"]["pb"]
    assert a["report"]["picker"] == "v2" and a["shadow"]["picker"] == "v1"
    monkeypatch.setenv("PICKER", "v1")
    v = N.view(BENCH_BOARD, {"pb": BENCH_EVENTS})
    assert v["agencies"]["pb"]["report"]["picker"] == "v1" and v["agencies"]["pb"]["shadow"]["picker"] == "v2"


def test_ab_report_runs_on_tagged_rows(tmp_path, capsys):
    import ab_report

    rows = []
    for d, win2 in (("20261104", True), ("20261105", False), ("20261106", True)):
        for v, w in (("v1", False), ("v2", win2)):
            rows.append({"kind": "multi", "mkind": "stacks_same", "target": 2.0, "day": d, "agency": "pb",
                         "picker": v, "chance": 0.4, "price": 2.1, "result": "won" if w else "lost"})
    p = tmp_path / "f.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    sys.argv = ["ab_report", str(p), "--boot", "200"]
    ab_report.main()
    text = capsys.readouterr().out
    assert "v1" in text and "v2" in text and "same-game: 3 game-targets" in text
