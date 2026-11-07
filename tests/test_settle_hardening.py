# ruff: noqa: E501, E731
"""P0 settlement foundation: participant ids, immutable quotes, correction-safe re-check, live tracker."""

import datetime as dt
import json
import sys

sys.path.insert(0, "tools/nba")
sys.path.insert(0, "azure/function")
import daily  # noqa: E402
import nba_props  # noqa: E402
from settle import Slate, norm, settle_one  # noqa: E402

from melbcup import nba_live  # noqa: E402

NOW = dt.datetime(2026, 11, 6, 12, tzinfo=dt.UTC)


def ath(pid, name, pts):
    return {"athlete": {"id": pid, "displayName": name}, "starter": True,
            "stats": ["30", str(pts), "5", "5", "1-3"]}


def box(*teams):
    block = lambda a: {"labels": ["MIN", "PTS", "REB", "AST", "3PT"], "athletes": a}  # noqa: E731
    return {"boxscore": {"players": [
        {"team": {"abbreviation": ab}, "statistics": [block(a)]} for ab, a in teams]}}


EV = {"20261104": [{"id": "1", "name": "Orlando Magic at Phoenix Suns",
                    "status": {"type": {"completed": True}}}]}
SUMMARY = {"1": box(("ORL", [ath("9", "Anthony Black", 4), ath("20", "Jaren Jackson Jr.", 7)]),
                    ("PHX", [ath("30", "Karl-Anthony Towns", 22), ath("31", "Jalen Williams", 8)]))}


def mk(summary):
    def fetch(url):
        if "scoreboard" in url:
            return {"events": EV.get(url.rsplit("=", 1)[1], [])}
        return summary[url.rsplit("=", 1)[1]]
    return fetch


def leg(who, pts=5, **kw):
    return {"game": "Orlando Magic @ Phoenix Suns", "startsAt": "2026-11-05T02:10:00Z", "player": who,
            "stat": "points", "line": pts, "k": pts, "under": False, "price": 1.5,
            "label": f"{who} {pts}+", "event": "e"} | kw


def test_name_variants_match_and_athlete_id_recorded():
    s = Slate(mk(SUMMARY))
    for who in ("Jaren Jackson", "jaren jackson jr", "Karl Anthony Towns", "Kárl-Anthony Towns"):
        out = settle_one(leg(who, 5), s, NOW, "20261104")
        assert out["result"] == "won" and out["espn_athlete"] in ("20", "30"), who
    assert norm("Karl-Anthony Towns") == norm("Karl Anthony Towns")


def test_id_wins_over_a_different_name():
    s = Slate(mk(SUMMARY))
    out = settle_one(leg("Tony Towns", 30, espn_athlete="30"), s, NOW, "20261104")
    assert out["result"] == "lost" and out["actual"] == 22 and out["espn_athlete"] == "30"


def test_ambiguous_name_is_unresolved_and_team_code_splits_it():
    twins = {"1": box(("ORL", [ath("1", "Jalen Williams", 3)]), ("PHX", [ath("2", "Jalen Williams", 9)]))}
    s = Slate(mk(twins))
    out = settle_one(leg("Jalen Williams", 5), s, NOW, "20261104")
    assert out["result"] == "unresolved" and "ambiguous" in out["why"]
    out = settle_one(leg("Jalen Williams", 5, team="PHX"), s, NOW, "20261104")
    assert out["result"] == "won" and out["espn_athlete"] == "2"


def test_player_on_wrong_team_is_unresolved():
    s = Slate(mk(SUMMARY))
    out = settle_one(leg("Anthony Black", 1, team="PHX"), s, NOW, "20261104")
    assert out["result"] == "unresolved"


# --- immutable quotes ----------------------------------------------------------------------
def rep(price):
    g = {"event": "e", "label": "A 5+", "line": 5, "price": price, "chance": 0.5, "player": "A", "game": "g",
         "startsAt": "2026-11-07T00:00:00Z", "stat": "points"}
    return {"day": "20261106", "value_legs": [], "all_legs": [g], "stacks": [], "stacks_same": [],
            "by_game": [{"legs": [g, g | {"label": "B 5+"}], "startsAt": g["startsAt"]}]}


def test_first_quote_never_overwritten_and_multis_carry_component_price():
    t0 = dt.datetime(2026, 11, 6, 1, tzinfo=dt.UTC)
    log = nba_props.build_log("pb", rep(2.0), {}, t0)
    leg0 = log["legs"][0]
    assert leg0["price"] == 2.0 and leg0["quoted_at"] == t0.isoformat() and leg0["quotes"] == []
    m = log["multis"][0]
    assert m["component_price"] == 4.0 and m["accepted_price"] is None
    for i, p in enumerate([2.2, 2.2, 1.8], start=1):
        log = nba_props.build_log("pb", rep(p), log, t0 + dt.timedelta(hours=i))
    leg1 = log["legs"][0]
    assert leg1["price"] == 2.0 and leg1["quoted_at"] == t0.isoformat()
    assert [q["price"] for q in leg1["quotes"]] == [2.2, 1.8]
    assert log["multis"][0]["component_price"] == 4.0 and log["multis"][0]["accepted_price"] is None
    for i in range(40):
        log = nba_props.build_log("pb", rep(3 + i), log, t0 + dt.timedelta(hours=10 + i))
    assert len(log["legs"][0]["quotes"]) == 20 and log["legs"][0]["price"] == 2.0


# --- correction-safe settlement --------------------------------------------------------------
def test_frozen_day_rechecked_once_and_corrections_logged(tmp_path):
    store = daily.LocalStore(str(tmp_path))
    log = {"agency": "pb", "day": "20261104", "legs": [leg("Anthony Black", 4)], "multis": []}
    store.write("20261104/log-pb.json", json.dumps(log).encode())
    t1 = dt.datetime(2026, 11, 5, 12, tzinfo=dt.UTC)  # 10 h after tip: too early to recheck
    daily.forward_v2(store, Slate(mk(SUMMARY)), t1)
    frozen = store.read("20261104/settled-v2.jsonl")
    assert json.loads(frozen)["result"] == "won"
    # ESPN corrects Black to 3 points
    fixed = {"1": box(("ORL", [ath("9", "Anthony Black", 3)]), ("PHX", []))}
    daily.forward_v2(store, Slate(mk(fixed)), t1 + dt.timedelta(hours=1))
    assert store.read("20261104/settled-v2.jsonl") == frozen and store.read("corrections.jsonl") is None
    t2 = dt.datetime(2026, 11, 6, 12, tzinfo=dt.UTC)  # 34 h after the game's start: due
    daily.forward_v2(store, Slate(mk(fixed)), t2)
    cor = [json.loads(x) for x in store.read("corrections.jsonl").decode().splitlines()]
    assert len(cor) == 1 and cor[0]["was"] == "won" and cor[0]["now"] == "lost" and cor[0]["at"] and cor[0]["why"]
    assert json.loads(store.read("20261104/settled-v2.jsonl"))["result"] == "lost"
    assert store.read("20261104/settled-v2.orig.jsonl") == frozen  # original preserved
    again = {"1": box(("ORL", [ath("9", "Anthony Black", 9)]), ("PHX", []))}
    daily.forward_v2(store, Slate(mk(again)), t2 + dt.timedelta(hours=2))  # once only
    assert len(store.read("corrections.jsonl").decode().splitlines()) == 1


def test_no_future_start_is_won_or_lost(tmp_path):
    store = daily.LocalStore(str(tmp_path))
    legs = [leg("Anthony Black", 4, startsAt=f"2026-11-0{d}T23:00:00Z", label=f"l{d}") for d in (5, 6, 7, 8)]
    store.write("20261104/log-pb.json", json.dumps({"agency": "pb", "day": "20261104", "legs": legs, "multis": []}).encode())
    daily.forward_v2(store, Slate(mk(SUMMARY)), NOW)
    for x in map(json.loads, store.read("forward-v2.jsonl").decode().splitlines()):
        if x["result"] in ("won", "lost"):
            assert dt.datetime.fromisoformat(x["startsAt"].replace("Z", "+00:00")) <= NOW and x["espn_event"]


# --- live tracker ----------------------------------------------------------------------------
def live_fetch(state, other_day_game=False):
    sb = {"20261105": [{"id": "7", "name": "Atlanta Hawks at Washington Wizards"}],
          "20261106": [{"id": "8", "name": "Atlanta Hawks at Washington Wizards"}] if other_day_game else []}
    summ = box(("ATL", [ath("1", "Trae Young", 9)]))
    summ["header"] = {"competitions": [{"status": {"type": {"state": state, "shortDetail": "x"}}}]}

    def fetch(url):
        if "scoreboard" in url:
            return {"events": sb.get(url.rsplit("=", 1)[1], [])}
        return summ if url.endswith("event=7") else (_ for _ in ()).throw(AssertionError(url))
    return fetch


def test_live_dated_label_finds_its_own_game_and_verdict_only_at_post():
    nba_live._CACHE.clear()
    now = dt.datetime(2026, 11, 7, 3, tzinfo=dt.UTC)
    lab = "2026-11-05 Atlanta Hawks @ Washington Wizards: Trae Young 8+ Points, Trae Young Under 20.5 Points"
    r = nba_live.track(lab, now, live_fetch("in"))
    assert r["legs"][0]["ok"] is True and r["legs"][1]["ok"] is None and r["verdict"] is None
    nba_live._CACHE.clear()
    r = nba_live.track(lab, now, live_fetch("post"))
    assert r["verdict"] == "won"


def test_live_undated_label_needs_exactly_one_match():
    nba_live._CACHE.clear()
    now = dt.datetime(2026, 11, 6, 20, tzinfo=dt.UTC)  # US 6 Nov: today and yesterday both hold the game
    lab = "Atlanta Hawks @ Washington Wizards: Trae Young 8+ Points"
    assert nba_live.track(lab, now, live_fetch("post", other_day_game=True)) is None
    nba_live._CACHE.clear()
    assert nba_live.track(lab, now, live_fetch("post"))["verdict"] == "won"
