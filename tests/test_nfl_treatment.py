"""NFL gets the NBA treatment: pk1 picker, multis, labels, live tracking, live chance, settlement."""

import copy
import json
from datetime import UTC, datetime

from melbcup import catalogue, discover, live_chance, nba_legs as N, nba_live, nfl_legs, nfl_settle

FIX = "tests/fixtures/"
T0 = datetime(2026, 11, 7, tzinfo=UTC)


def rows_for_event(event_id="2729245", name=None):
    d = json.load(open(FIX + "catalogue/event_nfl.json"))
    rows, _ = catalogue.event_selections(d, d, "nfl", T0, T0)
    out = []
    for r in rows:
        r = copy.deepcopy(r)
        r["event_id"] = event_id
        if name:
            r["event_name"] = name
        out.append(r)
    return out


def legs():
    return nfl_legs.legs_from_rows([r for r in rows_for_event() if r.get("is_player_prop")])


def test_label_carries_stat_and_game():
    ls = legs()
    burrow = [g for g in ls if g["player"] == "Joe Burrow" and not g["under"] and g["src"] == "ou"]
    assert burrow[0]["label"] == "Joe Burrow Over 275.5 Passing Yards"
    assert burrow[0]["game"] == "Cincinnati Bengals @ Atlanta Falcons"
    assert any(g["label"] == "Bijan Robinson Anytime Touchdown" for g in ls)
    assert all(any(w in g["label"] for w in nfl_legs.STAT_WORD.values()) or "Touchdown" in g["label"] for g in ls)


def test_native_pair_is_devigged_and_overs_shaded():
    ls = {(g["player"], g["line"], g["under"]): g for g in legs() if g["src"] == "ou"}
    over, under = ls[("Joe Burrow", 276, False)], ls[("Joe Burrow", 276, True)]
    assert abs(over["market"] + under["market"] - 1) < 1e-3  # margin gone inside the pair
    assert over["chance"] < over["market"] and under["chance"] > under["market"]  # OVER_SHADE


def test_alternate_rung_is_not_paired_with_a_main_under():
    alt = next(g for g in legs() if g["player"] == "Joe Burrow" and g["src"] == "alt" and g["line"] == 230)
    # single-sided: 1/price less the rung margin, not the pair's proportional de-vig
    assert abs(alt["market"] - N.single_chance(alt["price"])) < 0.03


def test_identical_bets_deduplicated_and_ladders_monotone():
    base = [r for r in rows_for_event() if r.get("is_player_prop")]
    dup = copy.deepcopy(next(r for r in base if r["participant_name"] == "Bijan Robinson"
                             and r["market_family"] == "player_rushing_yards" and r["side"] == "over"
                             and r["market_subtype"] == "alternate"))
    dup.update(market_subtype="over_under", line_numeric=69.5, line_raw="69.5", price_decimal=1.30)
    ls = nfl_legs.legs_from_rows(base + [dup])
    same = [g for g in ls if g["player"] == "Bijan Robinson" and g["stat"] == "rushingYards" and g["line"] == 70]
    assert len(same) == 2 and len(N.dedupe(same)) == 1
    assert N.dedupe(same)[0]["price"] == 1.30  # the better price, the other quote listed on it
    ladder = sorted((g for g in ls if g["player"] == "Joe Burrow" and g["stat"] == "passingYards"
                     and not g["under"]), key=lambda g: g["line"])
    ps = [g["market"] for g in ladder]
    assert all(a >= b - 1e-9 for a, b in zip(ps, ps[1:])) and len(ps) >= 3


def three_games():
    out = []
    for i, name in enumerate(("A1 Bears @ A2 Lions", "B1 Jets @ B2 Bills", "C1 Colts @ C2 Rams")):
        out += [r for r in rows_for_event(f"g{i}", name) if r.get("is_player_prop")]
    return nfl_legs.legs_from_rows(out)


def test_multi_one_leg_per_game_and_same_game():
    ls = three_games()
    cross = nfl_legs.cross_game(ls, 3.0)
    assert cross and cross["legs"] >= 2 and cross["price"] >= 3.0
    games = [d["game"] for d in cross["detail"]]
    assert len(set(games)) == len(games)  # one per game
    assert all(d["sport"] == "nfl" for d in cross["detail"])
    sgm = nfl_legs.same_game(ls, 3.0)
    assert sgm and all(m["legs"] >= 2 and len({d["player"] for d in m["detail"]}) == m["legs"] for m in sgm)


def test_discover_bands_use_pk1_legs():
    now = datetime(2026, 11, 7, 20, tzinfo=UTC)
    seen = now.isoformat()
    ls = three_games()
    for g in ls:
        g["startsAt"], g["seen"] = "2026-11-08T14:30:00Z", seen
    found = [x for x in (discover.leg_of_pk1(g, now) for g in nfl_legs.auto(ls)) if x]
    best = discover.best_multis(discover.pool(found), legs=2)
    assert any(b.get("pick") for b in best)
    pk = next(b["pick"] for b in best if b.get("pick"))
    assert len({g["event_id"] for g in pk["legs"]}) == len(pk["legs"]) >= 2


# ---- live tracking ----------------------------------------------------------------------------

SUMMARY = json.load(open(FIX + "espn_nfl_summary.json"))
BOARD = {"events": [{"id": "401", "name": "Kansas City Chiefs at Buffalo Bills"}]}


def fetch(url):
    return BOARD if "scoreboard" in url else SUMMARY


LABEL = ("Kansas City Chiefs @ Buffalo Bills: Josh Allen Under 250.5 Passing Yards, "
         "James Cook 90+ Rushing Yards, Khalil Shakir Over 5.5 Receptions, "
         "Khalil Shakir Anytime Touchdown, James Cook Over 120.5 Rushing + Receiving Yards")


def test_track_nfl_summary_fixture():
    nba_live._CACHE.clear()
    t = nba_live.track(LABEL, now=datetime(2026, 11, 9, 1, tzinfo=UTC), fetch=fetch)
    assert t["state"] == "in" and t["sport"] == "nfl" and t["period"] == 4 and t["clock_s"] == 120
    assert t["margin"] == 3 and abs(t["frac_left"] - 2 / 60) < 1e-9
    got = [(g["now"], g["ok"]) for g in t["legs"]]
    assert got == [(240, None), (96, True), (7, True), (1, True), (131, True)]
    assert t["failed"] == 0 and t["verdict"] is None


def test_track_nfl_multi_game_label_and_routing():
    nba_live._CACHE.clear()
    two = LABEL.split(", ")[0] + "; " + "Kansas City Chiefs @ Buffalo Bills: James Cook 90+ Rushing Yards"
    t = nba_live.track(two, now=datetime(2026, 11, 9, 1, tzinfo=UTC), fetch=fetch)
    assert t["games"] == 2 and len(t["legs"]) == 2
    assert nba_live.nfl_live.is_nfl("Atlanta Hawks @ Washington Wizards: Trae Young 8+ Assists") is False


# ---- live chance ------------------------------------------------------------------------------


def test_live_chance_yards_normal_approximation():
    under = live_chance.yards_chance(0.5, 251, True, 240, 2 / 60, 0.35)  # under 250.5 at 240
    assert 0.5 < under < 0.7 and live_chance.yards_chance(0.5, 251, True, 240, 0.5 / 60, 0.35) > 0.85
    assert live_chance.yards_chance(0.5, 251, True, 255, 0.5, 0.35) == 0.0  # already over
    assert live_chance.yards_chance(0.5, 251, False, 0, 1.0, 0.35) > 0.45  # pre-game ~ its price
    assert live_chance.yards_chance(0.5, 251, False, 240, 0.0, 0.35) == 0.0  # no time left


def test_live_chance_blowout_and_counts():
    track = {"state": "in", "sport": "nfl", "frac_left": 0.2, "period": 4, "margin": 24, "clock_s": 600,
             "legs": [{"stat": "receivingYards", "k": 80, "under": False, "now": 40, "ok": None},
                      {"stat": "receptions", "k": 6, "under": False, "now": 3, "ok": None}]}
    close = dict(track, margin=3)
    placed = {"legs": [{"chance": 0.5}, {"chance": 0.5}], "price": 4.0}
    blow, tight = live_chance.bet_live(track, placed), live_chance.bet_live(close, placed)
    assert blow["p"] < tight["p"] and "blowout" in blow["why"][0]
    assert 0 < blow["legs"][1] < 0.5  # Poisson count


# ---- settlement -------------------------------------------------------------------------------


def final(url):
    s = copy.deepcopy(SUMMARY)
    s["header"]["competitions"][0]["status"]["type"]["state"] = "post"
    return BOARD if "scoreboard" in url else s


def test_settle_nfl_leg_by_event_and_athlete():
    nba_live._CACHE.clear()
    now = datetime(2026, 11, 9, 12, tzinfo=UTC)
    g = {"game": "Kansas City Chiefs @ Buffalo Bills", "startsAt": "2026-11-08T18:00:00Z",
         "player": "James Cook", "stat": "rushingYards", "line": 90, "under": False, "sport": "nfl"}
    won = nfl_settle.settle_leg(g, now, final)
    assert (won["result"], won["actual"], won["espn_event"], won["espn_athlete"]) == ("won", 96, "401", "4567048")
    assert nfl_settle.settle_leg(g | {"under": True}, now, final)["result"] == "lost"
    assert nfl_settle.settle_leg(g | {"player": "Nobody Here"}, now, final)["result"] == "void"
    nba_live._CACHE.clear()
    assert nfl_settle.settle_leg(g, now, fetch)["result"] == "pending"  # game not final
    assert nfl_settle.settle_leg(g, datetime(2026, 11, 8, tzinfo=UTC), final)["result"] == "pending"


def test_settle_one_dispatches_nfl():
    import sys

    sys.path.insert(0, "tools/nba")
    from settle import settle_one

    nba_live._CACHE.clear()
    g = {"game": "Kansas City Chiefs @ Buffalo Bills", "startsAt": "2026-11-08T18:00:00Z",
         "player": "Khalil Shakir", "stat": "touchdowns", "line": 1, "under": False, "sport": "nfl"}
    assert nfl_settle.settle_leg(g, datetime(2026, 11, 9, 12, tzinfo=UTC), final)["result"] == "won"
    assert settle_one.__module__ == "settle"


def test_challenge_scope_nfl():
    from melbcup import nba_challenge as C

    assert "nfl" in C.SCOPES
