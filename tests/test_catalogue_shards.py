# ruff: noqa: E731
# ruff: noqa: E501
"""Sharded catalogue: index + per-competition shards, bounded memory, picker, Other bucket."""

import gzip
import json
import tracemalloc

import pytest

from melbcup import catalogue as C
from melbcup import catalogue_view as cv
from melbcup import sports_hub


def _row(sport, cid, comp, ev, i, player=True):
    return {
        "provider": "pb", "bookmaker": "PointsBet", "sport_id": sport, "league_id": cid,
        "event_id": ev, "event_start_utc": f"2026-11-08T{(int(cid) % 20):02d}:00:00Z",
        "event_status": "pre", "participant_id": f"p{i % 300}", "participant_name": f"Player {i % 300}",
        "team_id": "t1", "market_id": f"m{i // 4}", "market_name_raw": "Player Shots",
        "market_family": "player_shots", "market_subtype": "over_under", "stat_key": "player_shots",
        "line_raw": str(i % 9), "line_numeric": float(i % 9), "side": "over" if i % 2 else "under",
        "period": "full_game", "outcome_id": f"o{i}", "price_decimal": 1.9,
        "quote_observed_at_utc": "2026-11-07T09:00:00Z", "quote_status": "fresh", "suspended": False,
        "eligible_for_multis": None, "model_status": "market-only", "market_prob": None,
        "is_player_prop": player, "mapped": True, "key": f"pb|{ev}|m{i // 4}|o{i}|full_game|{i % 9}",
        "competition": comp, "event_name": f"Home {ev} v Away {ev}", "selection_id": "x" * 60,
        "canonical_event_id": "unresolved:" + ev, "provider_event_id": ev, "market_group_raw": "g",
        "market_class_raw": "c", "outcome_name_raw": f"Player {i % 300} Over {i % 9}.5",
        "price_updated_utc": "2026-11-07T08:59:00Z", "model_status_x": "market-only",
    }  # fmt: skip


def _write(root, sport, comps):
    """comps: [(cid, name, n_rows)] -> index.json + shards, written one competition at a time."""
    (root / sport).mkdir(parents=True, exist_ok=True)
    events, crow = [], []
    for cid, name, n in comps:
        evs = [f"{cid}{j}" for j in range(5)]
        rows = [_row(sport, cid, name, evs[i % 5], i) for i in range(n)]
        events += [{"event_id": e, "event_name": f"Home {e} v Away {e}", "starts_at": rows[0]["event_start_utc"],
                    "competition": name, "competition_id": cid, "status": "pre"} for e in evs]  # fmt: skip
        doc = {"built": "2026-11-07T09:00:00Z", "provider": "pb", "sport": sport, "competition_id": cid,
               "competition": name, "events": events[-5:], "selections": rows}  # fmt: skip
        (root / sport / f"comp-{cid}.json.gz").write_bytes(
            gzip.compress(json.dumps(doc).encode(), 1)
        )
        crow.append({"competition_id": cid, "competition": name, "events": 5, "first_start": rows[0]["event_start_utc"],
                     "outcomes": n, "player_outcomes": n, "families": ["player_shots"], "periods": ["full_game"],
                     "shard": f"comp-{cid}.json.gz"})  # fmt: skip
        del rows, doc
    idx = {"built": "2026-11-07T09:00:00Z", "provider": "pb", "sport": sport, "rows": sum(c[2] for c in comps),
           "player_rows": sum(c[2] for c in comps), "events": events,
           "competitions": sorted(crow, key=lambda c: c["first_start"])}  # fmt: skip
    (root / sport / "index.json").write_text(json.dumps(idx))


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALOGUE_DIR", str(tmp_path))
    cv.clear_cache()
    yield tmp_path
    cv.clear_cache()


def test_picker_defaults_to_soonest_competition_and_all_is_reachable(root):
    _write(root, "football", [("15", "Late League", 120), ("3", "EPL", 130), ("9", "Cup", 60)])
    q = cv.query("football", "players", {})
    assert q["comp"] == "football:3" and q["rows"][0]["competition"] == "EPL" and q["total"] == 130
    assert [o[0] for o in q["comp_opts"]][0] == "all" and len(q["comp_opts"]) == 4
    other = cv.query("football", "players", {"comp": "football:15"})
    assert other["total"] == 120 and other["groups"][0]["name"].startswith("Home 15")
    everything = cv.query("football", "players", {"comp": "all", "page": "7"})  # 310 rows, 7 pages
    assert everything["rows"] and everything["pages"] >= 7
    s = cv.query("football", "players", {"q": "Player 7"})  # a search crosses every competition
    assert s["comp"] == "all" and {r["competition"] for r in s["rows"]} >= {"EPL"}
    full = cv.query("football", "players", {"q": "Player 7", "comp": "all", "page": "99"})
    assert not full["link_next"] and full["rows"]  # the last page is clamped, nothing unreachable


def test_streaming_stops_early_and_reports_shard_counts(root):
    _write(root, "football", [(str(i), f"League {i}", 200) for i in range(1, 9)])
    q = cv.query("football", "markets", {"comp": "all"})
    assert q["partial"] and len(q["rows"]) == cv.PAGE_SIZE and q["link_next"] and not q["link_last"]
    assert len(q["shard_counts"]) == 1  # one shard was enough for page 1
    assert q["all_total"] == 1600 and len(cv._shards) <= cv.MAX_SHARDS_CACHED
    deep = cv.query("football", "markets", {"comp": "all", "page": "30"})
    assert deep["page"] == 30 and deep["rows"] and len(cv._shards) <= cv.MAX_SHARDS_CACHED


def test_memory_stays_bounded_on_a_200k_row_sport(root):
    _write(root, "football", [(str(i), f"League {i}", 5000) for i in range(1, 41)])  # 200k rows
    cv.clear_cache()
    tracemalloc.start()
    cv.query("football", "players", {})  # the default competition
    cv.query(
        "football", "players", {"q": "no such player anywhere"}
    )  # reads all 40 shards, one by one
    cv.query("all", "players", {"q": "Player 12", "page": "3"})
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert peak < 150 * 1024 * 1024, peak / 1e6
    assert len(cv._shards) <= cv.MAX_SHARDS_CACHED


def test_other_bucket_groups_the_extra_sports_with_a_picker(root):
    _write(root, "basketball-other", [("5", "Czech NBL", 40), ("2", "BNXT League", 30)])
    _write(root, "ice-hockey-other", [("8", "AHL", 25)])
    assert ("other", "Other") in sports_hub.TABS and sports_hub.pick("other") == "other"
    q = cv.query("other", "players", {})
    assert q["feed"] and q["n_rows"] == 95 and q["comp_opts"][0][0] == "all"
    assert {o[0] for o in q["comp_opts"]} >= {
        "basketball-other:5",
        "basketball-other:2",
        "ice-hockey-other:8",
    }
    every = cv.query("other", "players", {"comp": "all"})
    assert every["sports"] == ["basketball-other", "ice-hockey-other"] and every["all_total"] == 95


def test_writer_shards_by_competition_and_stubs_big_latest(tmp_path, monkeypatch):
    rows = [_row("football", "3", "EPL", "e1", i) for i in range(30)] + [
        _row("football", "9", "Cup", "e2", i) for i in range(10, 25)
    ]
    ev = [
        {"event_id": "e1", "event_name": "A v B", "starts_at": "2026-11-08T03:00:00Z", "competition": "EPL", "competition_id": "3", "status": "pre"},
        {"event_id": "e2", "event_name": "C v D", "starts_at": "2026-11-08T01:00:00Z", "competition": "Cup", "competition_id": "9", "status": "pre"},
        {"event_id": "e3", "event_name": "E v F", "starts_at": "2026-11-08T05:00:00Z", "competition": "Cup", "competition_id": "9", "status": "pre"},
    ]  # fmt: skip
    doc = {
        "built": "2026-11-07T10:00:00Z",
        "provider": "pb",
        "sport": "football",
        "events": ev,
        "selections": rows,
    }
    res = {"docs": {"football": doc}, "coverage": [{"sport": "football", "feed": "connected"}],
           "unmapped": {"football": []}, "raw": {"football": {}}}  # fmt: skip
    monkeypatch.setattr(C, "LATEST_MAX_ROWS", 20)
    names = C.write_build(res, C.dir_writer(tmp_path), include_raw=False)
    assert {
        "catalogue/football/index.json",
        "catalogue/football/comp-3.json.gz",
        "catalogue/football/comp-9.json.gz",
    } <= set(names)
    idx = json.loads((tmp_path / "catalogue/football/index.json").read_text())
    assert [c["competition_id"] for c in idx["competitions"]] == ["9", "3"]  # soonest first
    assert idx["rows"] == 45 and sum(c["outcomes"] for c in idx["competitions"]) == 45
    assert len(idx["events"]) == 3 and idx["coverage"]["sport"] == "football"
    stub = json.loads(
        gzip.decompress((tmp_path / "catalogue/football/latest.json.gz").read_bytes())
    )
    assert stub["sharded"] and stub["selections"] == []
    shard = json.loads(
        gzip.decompress((tmp_path / "catalogue/football/comp-3.json.gz").read_bytes())
    )
    assert len(shard["selections"]) == 30 and shard["competition"] == "EPL"
    monkeypatch.setattr(C, "LATEST_MAX_ROWS", 100)
    C.write_build(res, C.dir_writer(tmp_path), include_raw=False)
    full = json.loads(
        gzip.decompress((tmp_path / "catalogue/football/latest.json.gz").read_bytes())
    )
    assert len(full["selections"]) == 45 and "sharded" not in full
    # the reader works off the written folder
    monkeypatch.setenv("CATALOGUE_DIR", str(tmp_path / "catalogue"))
    cv.clear_cache()
    q = cv.query("football", "markets", {"comp": "all"})
    assert q["total"] == 45 and q["feed"]


def test_partial_run_keeps_previous_rows_of_games_it_did_not_reach(tmp_path):
    """A run cut short by its time limit must never empty a sport (owner: stable, populated)."""
    import gzip as _gz
    import json as _json

    from melbcup import catalogue as C

    def doc(built, events, rows):
        return {
            "built": built,
            "provider": "pb",
            "sport": "football",
            "events": events,
            "selections": rows,
        }

    ev = lambda i, f: {
        "event_id": str(i),
        "competition_id": "9",
        "competition": "EPL",  # noqa: E731
        "starts_at": "2026-11-08T15:00:00Z",
        "fetched": f,
    }
    row = lambda i, t: {
        "event_id": str(i),
        "league_id": "9",
        "market_family": "h2h",
        "key": f"{i}-{t}",  # noqa: E731
        "quote_observed_at_utc": t,
        "is_player_prop": False,
    }
    write, read = C.dir_writer(tmp_path), C.dir_reader(tmp_path)
    first = {
        "docs": {"football": doc("t1", [ev(1, True), ev(2, True)], [row(1, "t1"), row(2, "t1")])},
        "coverage": [{"sport": "football"}],
        "unmapped": {},
        "raw": {"football": {}},
    }
    C.write_build(first, write, read, include_raw=False)
    second = {
        "docs": {"football": doc("t2", [ev(1, True), ev(2, False)], [row(1, "t2")])},
        "coverage": [{"sport": "football"}],
        "unmapped": {},
        "raw": {"football": {}},
    }
    C.write_build(second, write, read, include_raw=False)
    shard = _json.loads(
        _gz.decompress((tmp_path / "catalogue/football/comp-9.json.gz").read_bytes())
    )
    got = {(r["event_id"], r["quote_observed_at_utc"]) for r in shard["selections"]}
    assert got == {("1", "t2"), ("2", "t1")}  # game 2 kept with its old (honest) quote time
    idx = _json.loads((tmp_path / "catalogue/football/index.json").read_bytes())
    assert idx["rows"] == 2 and [e.get("carried") for e in idx["events"]] == [None, True]
