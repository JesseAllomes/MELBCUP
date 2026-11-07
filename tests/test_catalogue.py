# ruff: noqa: E501
"""melbcup/catalogue.py: lossless, sport-agnostic PointsBet catalogue (T46-T56, ingestion side).
Offline: trimmed real PointsBet event payloads in tests/fixtures/catalogue/."""

from __future__ import annotations

import copy
import gzip
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from melbcup import catalogue as C

FIX = Path(__file__).parent / "fixtures" / "catalogue"
NOW = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
START = (NOW + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
LATE = (NOW + timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(name):
    return json.loads((FIX / f"event_{name}.json").read_text())


# sport -> (competition id, name, fixture, event key)
WORLD = {
    "basketball": [("7176", "NBA", "nba", "1"), ("9237", "NBA Futures", None, None)],
    "american-football": [("11444", "NFL", "nfl", "2")],
    "aussie-rules": [("7303", "AFLW", "afl", "3")],
    "soccer": [("136535", "English Premier League", "epl", "4")],
    "ice-hockey": [("158858", "NHL", "nhl", "5")],
    "tennis": [("185616", "ATP Stockholm", "atp", "6")],
}


class World:
    """A fake `fetch(url)` serving the fixtures; counts calls."""

    def __init__(self, details=None, starts=START, fail=()):
        self.calls = []
        self.details = details or {}
        self.starts = starts
        self.fail = set(fail)
        self.events = {}
        for comps in WORLD.values():
            for cid, _n, fx, key in comps:
                if fx:
                    self.events[key] = (cid, self.details.get(key) or load(fx))

    def __call__(self, url):
        self.calls.append(url)
        if url.endswith("/competitions") and "/sports/" in url:
            ps = url.split("/sports/")[1].split("/")[0]
            comps = [
                {"key": cid, "name": n, "numberOfEvents": 1 if fx else 3}
                for cid, n, fx, _k in WORLD.get(ps, [])
            ]
            return {"locales": [{"name": "Featured", "competitions": comps},
                                {"name": "Dup", "competitions": comps[:1]}]}  # fmt: skip
        if "/events/featured" in url:
            cid = url.split("/competitions/")[1].split("/")[0]
            evs = [
                {"key": k, "name": d["name"], "startsAt": self.starts, "isLive": False,
                 "competitionKey": cid}
                for k, (c, d) in self.events.items() if c == cid
            ]  # fmt: skip
            return {"events": evs, "nextPage": None}
        key = url.rsplit("/", 1)[1]
        if key in self.fail:
            raise OSError("boom")
        return self.events[key][1]


def run(world=None, keys=None, **kw):
    w = world or World()
    kw.setdefault("clock", lambda: NOW)
    return w, C.build(keys, w, NOW, **kw)


def rows(res, sport):
    return res["docs"][sport]["selections"]


def fams(res, sport):
    return {r["market_family"] for r in rows(res, sport)}


# ---- losslessness ---------------------------------------------------------------------------


def test_every_raw_outcome_is_displayed_and_reconciled():
    w, res = run()
    for sport in ("nba", "nfl", "aflw", "football", "nhl", "tennis"):
        raw = sum(
            len(m["outcomes"])
            for ev in res["raw"][sport]["events"]
            for m in ev["detail"]["fixedOddsMarkets"] + ev["detail"]["specialFixedOddsMarkets"]
        )
        cov = next(c for c in res["coverage"] if c["sport"] == sport)
        assert (
            raw > 0
            and len(rows(res, sport)) == raw == cov["raw_outcomes"] == cov["displayed_outcomes"]
        )
        assert cov["reconciled"] and cov["exceptions"] == [] and cov["feed"] == "connected"


def test_afl_aflw_split_and_core_keys_documented():
    assert C.sport_key("aussie-rules", "AFLW") == "aflw"
    assert C.sport_key("aussie-rules", "AFL State Of Origin") == "afl"
    assert C.sport_key("basketball", "NBA") == "nba"
    assert C.sport_key("basketball", "WNBL") == "nbl"
    assert C.sport_key("basketball", "NCAA") == "ncaab"
    assert C.sport_key("soccer", "MLS") == "football"
    assert C.sport_key("basketball", "Czech NBL") == "basketball-other"  # never dropped


def test_format_fields_present_and_key_unique():
    _, res = run()
    need = {"provider", "bookmaker", "sport_id", "league_id", "event_id", "event_start_utc", "event_status",
            "participant_id", "participant_name", "team_id", "market_id", "market_name_raw", "market_family",
            "market_subtype", "stat_key", "line_raw", "line_numeric", "side", "period", "outcome_id",
            "price_decimal", "quote_observed_at_utc", "quote_status", "suspended", "eligible_for_multis",
            "model_status", "market_prob", "is_player_prop", "mapped", "key"}  # fmt: skip
    for sport, doc in res["docs"].items():
        keys = [r["key"] for r in doc["selections"]]
        assert len(keys) == len(set(keys)), (
            sport
        )  # distinct players/lines/sides/periods never collide
        for r in doc["selections"]:
            assert need <= r.keys()
            assert r["provider"] == "pb" and r["bookmaker"] == "PointsBet"
        assert (
            doc["events"] == []
            or {"event_id", "event_name", "starts_at", "competition", "competition_id", "status"}
            <= doc["events"][0].keys()
        )


def test_futures_competitions_counted_not_fetched():
    w, res = run()
    cov = next(c for c in res["coverage"] if c["sport"] == "nba")
    assert cov["futures_competitions"] == 1 and cov["futures_events_counted"] == 3
    assert not any("9237" in u for u in w.calls if "/events/featured" in u)


# ---- families (T46-T52) ---------------------------------------------------------------------


def test_nba_steals_pra_alternate_and_model_status():
    _, res = run()
    r = rows(res, "nba")
    f = fams(res, "nba")
    assert {"player_steals", "player_pra", "player_points_assists", "player_points", "player_rebounds",
            "player_assists", "player_threes", "player_double_double", "player_first_scorer"} <= f  # fmt: skip
    alt = [x for x in r if x["market_name_raw"] == "Alternate Points"]
    assert alt and all(x["market_subtype"] == "alternate" and x["side"] == "over" for x in alt)
    assert any(x["market_name_raw"] == "Alternate Points + Rebounds + Assists" and x["market_family"] == "player_pra" for x in r)  # fmt: skip
    for x in r:
        modelled = x["market_family"] in C.MODELLED and x["period"] == "full_game"
        assert x["model_status"] == ("model-experimental" if modelled else "market-only")
    assert all(
        x["model_status"] == "market-only" for x in r if x["market_family"] == "player_steals"
    )
    # game markets are catalogued too
    assert any(
        not x["is_player_prop"] and x["market_family"] in ("h2h", "line", "total") for x in r
    )


def test_nba_over_under_pairs_get_no_vig_only_when_complete():
    _, res = run()
    ou = [x for x in rows(res, "nba") if x["market_name_raw"] == "Player Points Over/Under"]
    paired = [x for x in ou if x["market_prob"] is not None]
    assert paired and all(0 < x["market_prob"] < 1 for x in paired)
    assert all(
        x["market_prob"] is None for x in rows(res, "nba") if x["market_subtype"] == "alternate"
    )


def test_nfl_passing_rushing_receiving_td():
    _, res = run()
    f = fams(res, "nfl")
    assert {"player_passing_yards", "player_passing_tds", "player_rushing_yards", "player_receiving_yards",
            "player_receptions", "player_td_scorer", "player_rushing_receiving_yards"} <= f  # fmt: skip
    anytime = [x for x in rows(res, "nfl") if x["market_name_raw"] == "Anytime Touchdown Scorer"]
    assert anytime and all(
        x["side"] == "yes" and x["is_player_prop"] and x["mapped"] for x in anytime
    )


def test_afl_nhl_soccer_tennis_families():
    _, res = run()
    assert {"player_disposals", "player_goals"} <= fams(res, "aflw")
    assert {"player_shots", "player_points", "player_assists", "player_goals"} <= fams(res, "nhl")
    assert {
        "player_goalscorer",
        "player_shots_on_target",
        "player_cards",
        "player_tackles",
    } <= fams(res, "football")
    t = rows(res, "tennis")  # tennis: game markets kept, no player-prop feed in this event
    assert t and not any(x["is_player_prop"] for x in t)
    assert next(c for c in res["coverage"] if c["sport"] == "tennis")["feed"] == "connected"


# ---- unmapped / never invent ----------------------------------------------------------------


def _with_unknown():
    d = load("nba")
    d["fixedOddsMarkets"].append(
        {"key": "999", "name": "Player Zorbs Over/Under (A @ B)", "eventName": "Player Zorbs Over/Under",
         "eventClass": "Player Zorbs Over/Under", "groupName": "Player Zorb Markets",
         "outcomes": [
             {"key": "1", "name": "Zed Zorb Over 3.5", "price": 1.87, "points": 3.5, "fixedMarketId": "9", "playerId": "77",
              "side": "Home", "isOpenForBetting": True, "priceLastUpdated": "2026-11-07T09:58:00.123456Z"},
             {"key": "2", "name": "Zed Zorb Under 3.5", "price": 1.95, "points": 3.5, "fixedMarketId": "9", "playerId": "77",
              "side": "Home", "isOpenForBetting": True, "priceLastUpdated": "2026-11-07T09:58:00.123456Z"}]}
    )  # fmt: skip
    return d


def test_unknown_market_kept_unmapped_with_raw_label_and_price():
    _, res = run(World(details={"1": _with_unknown()}), keys=["nba"])
    z = [x for x in rows(res, "nba") if x["market_name_raw"] == "Player Zorbs Over/Under"]
    assert len(z) == 2
    assert all(
        x["mapped"] is False and x["market_family"] == "other" and x["is_player_prop"] for x in z
    )
    assert {x["price_decimal"] for x in z} == {1.87, 1.95}
    assert {x["participant_name"] for x in z} == {"Zed Zorb"} and {x["side"] for x in z} == {
        "over",
        "under",
    }
    assert z[0]["model_status"] == "market-only"
    log = res["unmapped"]["nba"]
    assert any(
        u["market_name_raw"] == "Player Zorbs Over/Under" and u["count"] == 1 and u["example_event"]
        for u in log
    )
    cov = next(c for c in res["coverage"] if c["sport"] == "nba")
    assert cov["unmapped_groups"] >= 1 and cov["mapped_groups"] >= 1


def test_no_probability_invented_for_one_sided_or_incomplete_groups():
    _, res = run()
    for sport in ("nfl", "football", "aflw"):
        for x in rows(res, sport):
            if x["side"] in ("yes", "no") or x["market_subtype"] == "alternate":
                assert x["market_prob"] is None
            assert x["model_status"] == "market-only"


def test_policy_filters_never_remove_entries():
    """Suspended, unpriced, very long and head-to-head outcomes are all catalogued."""
    d = load("nba")
    outs = d["fixedOddsMarkets"][0]["outcomes"]
    outs[0].update(price=1.0, isOpenForBetting=False)  # suspended, no valid price
    outs[1].update(price=500.0)  # long odds
    w, res = run(World(details={"1": d}), keys=["nba"])
    r = rows(res, "nba")
    n_raw = sum(len(m["outcomes"]) for m in d["fixedOddsMarkets"])
    assert len(r) == n_raw
    assert any(
        x["suspended"] and x["price_decimal"] is None and x["quote_status"] == "unverified"
        for x in r
    )
    assert any(x["price_decimal"] == 500.0 for x in r)
    assert any(
        x["market_family"] == "h2h" for x in r
    )  # NBA head-to-head: visible (exclusion is selection-only)
    cov = next(c for c in res["coverage"] if c["sport"] == "nba")
    assert cov["suspended_outcomes"] >= 1


def test_quote_time_preserved_and_stale_flag():
    t0 = datetime(2026, 11, 7, 9, 59, 30, tzinfo=UTC)
    _, res = run(clock=lambda: t0, keys=["nba"])
    for x in rows(res, "nba"):
        assert (
            x["quote_observed_at_utc"] == "2026-11-07T09:59:30Z"
        )  # the fetch time, not the build time
    assert any(x["price_updated_utc"] for x in rows(res, "nba"))  # the provider's own time kept
    assert {x["quote_status"] for x in rows(res, "nba")} == {"fresh"}
    _, old = run(clock=lambda: NOW - timedelta(hours=1), keys=["nba"])
    assert {x["quote_status"] for x in rows(old, "nba")} == {"stale"}  # flagged, still listed
    assert len(rows(old, "nba")) == len(rows(res, "nba"))


def test_duplicate_outcome_ids_never_collide():
    d = load("nba")
    m = d["fixedOddsMarkets"][5]
    m["outcomes"] = m["outcomes"] + copy.deepcopy(m["outcomes"])
    _, res = run(World(details={"1": d}), keys=["nba"])
    keys = [x["key"] for x in rows(res, "nba")]
    assert len(keys) == len(set(keys))
    assert len(keys) == sum(len(m["outcomes"]) for m in d["fixedOddsMarkets"])


def test_same_player_different_period_side_line_distinct_keys():
    d = load("nba")
    base = next(m for m in d["fixedOddsMarkets"] if m["eventClass"] == "Player Points Over/Under")
    q1 = copy.deepcopy(base)
    q1.update(
        key="1001",
        name="1st Quarter Player Points Over/Under (A @ B)",
        eventClass="1st Quarter Player Points Over/Under",
    )
    for o in q1["outcomes"]:
        o["fixedMarketId"] = "x" + str(o["fixedMarketId"])
    d["fixedOddsMarkets"].append(q1)
    _, res = run(World(details={"1": d}), keys=["nba"])
    r = rows(res, "nba")
    assert len({x["key"] for x in r}) == len(r)
    assert {"full_game", "q1"} <= {x["period"] for x in r}
    q1rows = [x for x in r if x["period"] == "q1"]
    assert q1rows and all(
        x["model_status"] == "market-only" for x in q1rows
    )  # model is full-game only


# ---- budget, politeness, errors -------------------------------------------------------------


def test_event_call_cap_recorded_not_dropped():
    w, res = run(max_event_calls=2)
    assert res["stats"]["event_calls"] == 2
    assert res["stats"]["events_in_window"] == 6
    skipped = [c for c in res["coverage"] if c["events_not_fetched"]]
    assert sum(c["events_not_fetched"] for c in skipped) == 4
    for c in skipped:
        assert all(n["reason"] == "not fetched this run: event-call cap" for n in c["not_fetched"])
    # the rest of the catalogue exists: events listed with fetched False
    flat = [e for d in res["docs"].values() for e in d["events"]]
    assert len(flat) == 6 and sum(1 for e in flat if not e["fetched"]) == 4


def test_deadline_records_not_fetched():
    w, res = run(deadline=time.monotonic() - 1)
    assert res["stats"]["event_calls"] == 0
    assert all(not rows(res, s) for s in res["docs"])
    assert sum(c["events_not_fetched"] for c in res["coverage"]) == 6
    assert any("time budget" in n["reason"] for c in res["coverage"] for n in c["not_fetched"])


def test_event_error_listed_and_others_still_built():
    w, res = run(World(fail={"2"}))
    nfl = next(c for c in res["coverage"] if c["sport"] == "nfl")
    assert nfl["events_not_fetched"] == 1 and any("event 2" in e for e in nfl["adapter_errors"])
    assert rows(res, "nba")  # one failing event never breaks the rest


def test_competition_error_listed():
    w = World()
    orig = w.__call__

    def bad(url):
        if "/sports/soccer/" in url:
            raise OSError("down")
        return orig(url)

    _, res = run(bad, keys=["football", "nba"])
    f = next(c for c in res["coverage"] if c["sport"] == "football")
    assert f["adapter_errors"] and f["feed"] == "none"
    assert rows(res, "nba")


def test_window_excludes_far_events_and_listing_dedupes():
    w, res = run(World(starts=LATE))
    assert res["stats"]["event_calls"] == 0 and res["stats"]["events_in_window"] == 0
    w2, res2 = run(keys=["nba"])
    assert (
        sum(1 for u in w2.calls if "/events/featured" in u) == 1
    )  # the duplicate locale listing is one call
    assert res2["stats"]["event_calls"] == 1
    _, res3 = run(World(starts=LATE), hours=100)
    assert res3["stats"]["events_in_window"] == 6  # configurable window


def test_only_requested_sports_are_fetched():
    w, res = run(keys=["nhl"])
    assert set(res["docs"]) == {"nhl"} and not any("/sports/basketball/" in u for u in w.calls)


# ---- writers --------------------------------------------------------------------------------


def test_write_build_to_folder_and_merge_coverage(tmp_path):
    w, res = run(keys=["nba"])
    names = C.write_build(res, C.dir_writer(tmp_path), C.dir_reader(tmp_path))
    assert "catalogue/nba/latest.json.gz" in names and "catalogue/unmapped/nba.json" in names
    assert any(n.startswith("catalogue/raw/nba/20261107/1000") for n in names)
    doc = json.loads(gzip.decompress((tmp_path / "catalogue/nba/latest.json.gz").read_bytes()))
    assert (
        doc["sport"] == "nba" and doc["provider"] == "pb" and doc["built"] == "2026-11-07T10:00:00Z"
    )
    assert len(doc["selections"]) == len(rows(res, "nba"))
    _, res2 = run(keys=["nhl"])
    C.write_build(res2, C.dir_writer(tmp_path), C.dir_reader(tmp_path))
    cov = json.loads((tmp_path / "catalogue/coverage.json").read_text())
    assert {r["sport"] for r in cov} == {"nba", "nhl"}  # rotation keeps the other sport's row


def test_expired_raw_names():
    names = [
        "catalogue/raw/nba/20261101/0900.json.gz",
        "catalogue/raw/nba/20261106/0900.json.gz",
        "catalogue/nba/latest.json.gz",
    ]
    assert C.expired_raw(names, NOW) == [names[0]]


def test_run_rotation_builds_in_turn_and_advances_cursor():
    store = {}
    w = World()
    out = C.run_rotation(0, time.monotonic() + 0.0, NOW, lambda n, b: store.__setitem__(n, b), store.get,
                         lambda: list(store), fetch=w, clock=lambda: NOW)  # fmt: skip
    assert out["built"] == ["basketball"] and out["cursor"] == 1  # at least one sport per run
    assert "catalogue/nba/latest.json.gz" in store
    out2 = C.run_rotation(out["cursor"], time.monotonic() + 600, NOW, lambda n, b: store.__setitem__(n, b),
                          store.get, lambda: list(store), fetch=w, clock=lambda: NOW)  # fmt: skip
    assert (
        out2["built"][0] == "american-football" and len(out2["built"]) == 10 and out2["cursor"] == 1
    )
    assert "catalogue/nfl/latest.json.gz" in store
    rows_ = json.loads(store["catalogue/coverage.json"])
    assert {"nba", "nfl", "nhl", "football", "tennis"} <= {r["sport"] for r in rows_}
