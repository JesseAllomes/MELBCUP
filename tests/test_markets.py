# ruff: noqa: E501
"""Canonical market layer (melbcup/markets.py): PointsBet + Sportsbet raw payloads."""

import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from melbcup import markets as M

FX = os.path.join(os.path.dirname(__file__), "fixtures")
NOW = datetime(2026, 11, 7, 9, 0, tzinfo=UTC)


def _load(n):
    with open(os.path.join(FX, n)) as f:
        return json.load(f)


def pb(now=NOW, fetched_at=None):
    fx = _load("pointsbet_nba_event.json")
    ev = [{**{k: fx["listing"][k] for k in ("key", "name", "startsAt")}, "detail": fx["detail"]}]
    return M.pointsbet_selections(ev, now, fetched_at)


def sb(extra=None):
    d = _load("sportsbet_nba_sample.json")
    mk = {k: list(v) for k, v in d["markets"].items()}
    if extra:
        mk[next(iter(mk))] += extra
    return M.sportsbet_selections(d["competition"], mk, NOW)


def types(sels):
    return {s.market_type for s in sels}


def test_pointsbet_every_market_type_parsed():
    t = types(pb())
    assert {"h2h", "line", "total", "player_points", "player_rebounds", "player_assists",
            "player_threes", "player_pra", "player_other", "other"} <= t  # fmt: skip
    h2h = [s for s in pb() if s.market_type == "h2h"]
    assert {s.side for s in h2h} == {"home", "away"}  # NBA H2H is representable


def test_pointsbet_fields():
    s = next(x for x in pb() if x.market_type == "player_points" and x.side == "under")
    assert s.provider == "pb" and s.participant_id and s.line is not None
    assert s.event_name == "Denver Nuggets @ Indiana Pacers" and s.canonical_event_id
    alt = next(x for x in pb() if x.market_name == "Alternate Points")
    assert alt.side == "over" and alt.line % 1 == 0.5
    pra = next(x for x in pb() if x.market_name.startswith("Player Pts + Rebs"))
    assert pra.market_type == "player_pra" and not pra.modelled
    combo = next(x for x in pb() if x.market_name == "Player Points + Assists Over/Under")
    assert combo.market_type == "player_other"


def test_sportsbet_player_markets_and_other():
    s = sb()
    assert {"player_points", "player_rebounds", "player_assists", "player_threes",
            "player_other"} <= types(s)  # fmt: skip
    assert all(x.provider == "sb" and x.event_name.count(" @ ") == 1 for x in s)
    g = [
        {"id": 1, "name": "Head to Head", "statusCode": "A", "selections": [
            {"name": "Philadelphia 76ers", "statusCode": "A", "price": {"winPrice": 1.5}},
            {"name": "Detroit Pistons", "statusCode": "A", "price": {"winPrice": 2.6}}]},
        {"id": 2, "name": "Line", "statusCode": "A", "selections": [
            {"name": "Philadelphia 76ers", "unformattedHandicap": "-4.5", "price": {"winPrice": 1.9}},
            {"name": "Detroit Pistons", "unformattedHandicap": "4.5", "price": {"winPrice": 1.9}}]},
        {"id": 3, "name": "Total Points", "statusCode": "A", "selections": [
            {"name": "Over", "unformattedHandicap": "220.5", "price": {"winPrice": 1.9}},
            {"name": "Under", "unformattedHandicap": "220.5", "price": {"winPrice": 1.9}}]},
        {"id": 4, "name": "Winning Margin", "statusCode": "A", "selections": [
            {"name": "Philadelphia 76ers 1-12", "price": {"winPrice": 3.0}}]},
    ]  # fmt: skip
    e = sb(g)
    new = [
        x for x in e if x.market_name in ("Head to Head", "Line", "Total Points", "Winning Margin")
    ]
    assert {x.market_type for x in new} == {"h2h", "line", "total", "other"}
    assert {x.side for x in new if x.market_type == "h2h"} == {"away", "home"}
    assert all(x.market_prob is not None for x in new if x.market_type != "other")


def test_no_vig_only_for_complete_markets():
    for s in pb() + sb():
        if s.market_prob is None:
            continue
        grp = [x for x in (pb() + sb()) if x.group == s.group and x.provider == s.provider]
        assert len(grp) == 2 and {x.side for x in grp} in ({"over", "under"}, {"home", "away"})
    o = next(x for x in pb() if x.market_name == "Player Points Over/Under" and x.side == "over")
    u = next(x for x in pb() if x.group == o.group and x.side == "under")
    assert abs(o.market_prob + u.market_prob - 1) < 1e-5
    assert abs(o.market_prob - (1 / o.price) / (1 / o.price + 1 / u.price)) < 1e-5
    # single-sided ladders, yes-only and multi-way markets never get one
    for s in pb():
        if (
            s.market_name in ("Alternate Points", "Player To Score First Basket")
            or s.market_type == "other"
        ):
            assert s.market_prob is None


def test_incomplete_pair_gets_no_prob():
    sels = [replace(s, market_prob=None) for s in pb() if s.market_name == "Moneyline"][:1]
    assert M.apply_no_vig(sels)[0].market_prob is None


def test_key_stable_and_unique():
    a, b = pb(), pb(now=NOW + timedelta(seconds=30))
    assert [x.key() for x in a] == [x.key() for x in b]
    assert len({x.key() for x in a}) == len(a)
    assert len({x.key() for x in sb()}) == len(sb())
    s = a[0]
    assert M.Selection.key(s.__class__(**{**s.__dict__, "price": 9.9, "quoted_at": "x"})) == s.key()


def test_unsupported_is_not_modelled_and_has_no_model_prob():
    for s in pb() + sb():
        assert s.model_prob is None
        assert s.modelled == (s.market_type in M.MODELLED)
    assert not any(s.modelled for s in pb() if s.market_type in ("other", "h2h", "player_pra"))
    assert not any(s.modelled for s in pb() if s.market_type == "player_other")
    rows = {r["market_type"]: r for r in M.coverage(pb() + sb())}
    assert rows["player_points"]["modelled"] is True and rows["h2h"]["modelled"] is False
    assert rows["player_points"]["providers"] == ["pb", "sb"]
    assert rows["h2h"]["with_market_prob"] == 2
    assert sum(r["count"] for r in rows.values()) == len(pb() + sb())


def test_period_props_are_not_modelled():
    s = M.Selection  # a quarter-scoped points market must not count as the full-game stat
    ctx = M._Ctx("pb", "1", "A @ B", "2026-11-07T22:00:00Z", NOW)
    x = ctx.make("player_points", "1st Quarter Points", "P", "over", 1.9, 5.5, group="g")
    assert isinstance(x, s) and x.market_type == "player_other" and not x.modelled


def test_unverified_status():
    stale = pb(fetched_at=NOW - timedelta(hours=1))
    assert all(s.status == "unverified" and s.market_prob is None for s in stale)
    assert stale[0].status_reason == "stale snapshot"
    assert stale[0].to_schema()["quoted_decimal_odds"] is None
    ctx = M._Ctx("pb", "1", "A @ B", "2026-11-07T22:00:00Z", NOW)
    assert ctx.make("h2h", "M", "A", "away", None, group="g").status_reason == "no valid price"
    assert ctx.make("h2h", "M", "A", "away", 1.0, group="g").status == "unverified"
    bad = M._Ctx("pb", "1", "no teams", "", NOW).make("h2h", "M", "A", "away", 2.0, group="g")
    assert bad.status_reason == "invalid event identity"
    one = M._Ctx("pb", "1", "A @ B", "2026-11-07T22:00:00Z", NOW)
    pair = [one.make("h2h", "M", n, sd, 2.0 if n == "A" else None, group="g")
            for n, sd in (("A", "away"), ("B", "home"))]  # fmt: skip
    assert M.apply_no_vig(pair)[0].market_prob is None


def test_to_schema_matches_contract():
    req = ["selection_id", "sport", "league", "canonical_event_id", "provider",
           "provider_event_id", "market_type", "direction", "market_status", "model_status",
           "observed_at_utc"]  # fmt: skip
    for s in pb()[:50] + sb()[:50]:
        d = s.to_schema()
        assert all(d.get(k) for k in req)
        assert d["model_status"] in {"validated", "market_only", "experimental", "unavailable"}
