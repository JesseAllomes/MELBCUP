"""Event-matched NBA settlement (independent review, 2026-11-07): a leg settles only against its
own game, only once that game is final; the original forward.jsonl is never changed."""

import datetime as dt
import json
import sys

sys.path.insert(0, "tools/nba")
import daily  # noqa: E402
from settle import Slate, settle_multi_v2, settle_one  # noqa: E402

NOW = dt.datetime(2026, 11, 6, 12, tzinfo=dt.UTC)


def player(pid, name, team, pts):
    return {
        "athlete": {"id": pid, "displayName": name},
        "starter": True,
        "stats": ["30", str(pts), "5", "5", "1-3"],
    }


def summary(*athletes):
    block = {"labels": ["MIN", "PTS", "REB", "AST", "3PT"], "athletes": list(athletes)}
    return {"boxscore": {"players": [{"team": {"abbreviation": "X"}, "statistics": [block]}]}}


# 4 Nov (US): Magic at Suns, final. 5 Nov: Magic at Warriors, still going. 6 Nov: none yet.
EVENTS = {
    "20261104": [
        {
            "id": "1",
            "name": "Orlando Magic at Phoenix Suns",
            "status": {"type": {"completed": True}},
        }
    ],
    "20261105": [
        {
            "id": "2",
            "name": "Orlando Magic at Golden State Warriors",
            "status": {"type": {"completed": False}},
        }
    ],
}
BOX = {"1": summary(player("9", "Anthony Black", "ORL", 4))}


def fetch(url):
    if "scoreboard" in url:
        return {"events": EVENTS.get(url.rsplit("=", 1)[1], [])}
    if "summary" in url:
        return BOX[url.rsplit("=", 1)[1]]
    raise AssertionError(url)


def leg(game, starts, pts=10, who="Anthony Black"):
    return {
        "game": game,
        "startsAt": starts,
        "player": who,
        "stat": "points",
        "line": pts,
        "k": pts,
        "under": False,
        "price": 1.5,
        "label": f"{who} {pts}+ {game}",
        "event": "e",
    }


SUNS = ("Orlando Magic @ Phoenix Suns", "2026-11-05T02:10:00Z")
WARRIORS = ("Orlando Magic @ Golden State Warriors", "2026-11-06T02:10:00Z")
LATER = ("Orlando Magic @ Utah Jazz", "2026-11-07T02:10:00Z")


def test_settles_only_against_its_own_final_game():
    s = Slate(fetch)
    assert settle_one(leg(*SUNS, pts=4), s, NOW, "20261104")["result"] == "won"
    out = settle_one(leg(*SUNS, pts=10), s, NOW, "20261104")
    assert out["result"] == "lost" and out["actual"] == 4 and out["espn_event"] == "1"


def test_future_and_unfinished_games_stay_pending_never_won_lost_or_void():
    s = Slate(fetch)
    later = settle_one(leg(*LATER, pts=1), s, NOW, "20261104")  # logged on the 4th, played the 6th
    assert later["result"] == "pending" and later["why"] == "not started"
    going = settle_one(leg(*WARRIORS, pts=1), s, NOW, "20261104")
    assert going["result"] == "pending" and going["why"] == "not final"


def test_did_not_play_is_void_only_in_a_final_game():
    s = Slate(fetch)
    assert settle_one(leg(*SUNS, who="Nobody Here"), s, NOW, "20261104")["result"] == "void"
    assert settle_one(leg(*WARRIORS, who="Nobody Here"), s, NOW, "20261104")["result"] == "pending"


def test_no_matching_game_is_unresolved_after_12_hours():
    s = Slate(fetch)
    g = leg("Boston Celtics @ New York Knicks", "2026-11-05T00:00:00Z")
    assert settle_one(g, s, NOW, "20261104")["result"] == "unresolved"
    assert (
        settle_one(g, s, dt.datetime(2026, 11, 5, 4, tzinfo=dt.UTC), "20261104")["result"]
        == "pending"
    )


def test_multi_lost_leg_settles_it_open_leg_keeps_it_pending():
    s = Slate(fetch)
    lost = settle_multi_v2(
        {"price": 3.0, "detail": [leg(*SUNS, pts=10), leg(*LATER)]}, s, NOW, "20261104"
    )
    assert lost["result"] == "lost"
    open_ = settle_multi_v2(
        {"price": 3.0, "detail": [leg(*SUNS, pts=4), leg(*LATER)]}, s, NOW, "20261104"
    )
    assert open_["result"] == "pending"


def test_forward_v2_rebuild_reconciles_and_leaves_v1_untouched(tmp_path):
    store = daily.LocalStore(str(tmp_path))
    v1 = [
        leg(*LATER, pts=1)
        | {"result": "won", "actual": 4, "kind": "leg", "agency": "pb", "day": "20261104"}
    ]
    v1_raw = "".join(json.dumps(x) + "\n" for x in v1).encode()
    store.write("forward.jsonl", v1_raw)
    log = {
        "agency": "pb",
        "day": "20261104",
        "legs": [leg(*LATER, pts=1), leg(*SUNS, pts=4)],
        "multis": [],
    }
    store.write("20261104/log-pb.json", json.dumps(log).encode())
    daily.forward_v2(store, Slate(fetch), NOW)
    rows = [json.loads(x) for x in store.read("forward-v2.jsonl").decode().splitlines()]
    assert [r["result"] for r in rows] == ["pending", "won"]
    assert store.read("forward.jsonl") == v1_raw  # the audit record is never rewritten
    assert store.read("20261104/settled-v2.jsonl") is None  # a day with an open leg is not frozen
    rec = json.loads(store.read("forward-v2-reconcile.json"))
    assert rec["was_won_now_pending"] == 1 and rec["new"] == 1


def test_repeated_bet_counted_once_via_latest(tmp_path):
    store = daily.LocalStore(str(tmp_path))
    for day in ("20261103", "20261104"):
        log = {"agency": "pb", "day": day, "legs": [leg(*SUNS, pts=4)], "multis": []}
        store.write(f"{day}/log-pb.json", json.dumps(log).encode())
    daily.forward_v2(store, Slate(fetch), NOW)
    rows = [json.loads(x) for x in store.read("forward-v2.jsonl").decode().splitlines()]
    assert [(r["day"], r["latest"]) for r in rows] == [("20261103", False), ("20261104", True)]
