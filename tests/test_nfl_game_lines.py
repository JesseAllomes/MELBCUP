"""NFL full-game lines (h2h, spread, total) as pk1 legs, their multis and settlement."""

from datetime import UTC, datetime, timedelta

from melbcup import nba_legs as N
from melbcup import nba_live
from melbcup import nfl_legs, nfl_live, nfl_settle


AW, HM = ("Alpha", "Bravo"), ("Hotel", "India")


def _rows(n_games=2):
    soon = (datetime.now(UTC) + timedelta(hours=20)).isoformat()
    rows = []
    for e in range(n_games):
        game = f"{AW[e]} Team @ {HM[e]} Team"
        base = {"event_name": game, "event_id": f"ev{e}", "event_start_utc": soon, "period": "full_game"}

        def add(fam, side, price, who=None, line=None, raw=None, name="x"):
            rows.append(base | {"market_family": fam, "side": side, "price_decimal": price,
                                "participant_name": who, "line_numeric": line, "line_raw": raw,
                                "market_name_raw": name, "is_player_prop": False})

        add("h2h", "home", 1.60, f"{HM[e]} Team", name="Moneyline")
        add("h2h", "away", 2.40, f"{AW[e]} Team", name="Moneyline")
        add("line", "home", 1.91, f"{HM[e]} Team", -3.5, "-3.5")
        add("line", "away", 1.91, f"{AW[e]} Team", 3.5, "+3.5")
        add("total", "over", 1.90, None, 44.5, "44.5")
        add("total", "under", 1.90, None, 44.5, "44.5")
        add("line", "home", 1.91, f"{HM[e]} Team", -3.5, "-3.5", "1st Half Spread")  # ignored
    return rows


def test_legs_and_devig():
    legs = nfl_legs.legs_from_rows(_rows(1))
    assert len(legs) == 4  # no head-to-head (owner policy)
    by = {g["label"]: g for g in legs}
    assert set(by) == {"Hotel Team -3.5", "Alpha Team +3.5", "Over 44.5 Total Points", "Under 44.5 Total Points"}
    assert abs(by["Hotel Team -3.5"]["chance"] + by["Alpha Team +3.5"]["chance"] - 1) < 1e-3
    assert abs(by["Over 44.5 Total Points"]["chance"] - 0.5) < 0.02
    assert all(g["event"] == "ev0" and g["startsAt"] and g["gameline"] for g in legs)
    h, a = by["Hotel Team -3.5"], by["Alpha Team +3.5"]
    assert N.bet_key(h) != N.bet_key(a)


def test_cross_game_multi_from_two_games():
    legs = nfl_legs.legs_from_rows(_rows(2))
    m = nfl_legs.cross_game(legs, 2.0)
    assert m and m["legs"] == 2
    assert len({d["game"] for d in m["detail"]}) == 2


def test_same_game_has_one_game_line():
    legs = nfl_legs.legs_from_rows(_rows(1))
    for t in (2.0, 3.0, 5.0):
        for m in nfl_legs.same_game(legs, t):
            assert sum(1 for d in m["detail"] if d["label"] in {g["label"] for g in legs}) <= 1


def _summary(a, h):
    return {"header": {"competitions": [{"status": {"type": {"state": "post"}}, "competitors": [
        {"homeAway": "home", "score": str(h), "team": {"displayName": "Buffalo Bills"}},
        {"homeAway": "away", "score": str(a), "team": {"displayName": "Kansas City Chiefs"}}]}]}}


def _settle(g, a, h):
    nba_live._CACHE.clear()
    start = datetime.now(UTC) - timedelta(hours=5)
    leg = g | {"game": "Kansas City Chiefs @ Buffalo Bills", "startsAt": start.isoformat()}

    def fetch(url):
        return {"events": [{"id": "1", "name": "Kansas City Chiefs at Buffalo Bills"}]} if "scoreboard" in url else _summary(a, h)

    return nfl_settle.settle_leg(leg, fetch=fetch)["result"]


def test_settlement():
    win_away = {"stat": "win", "player": "Game winner", "line": 0.0, "under": True}
    win_home = win_away | {"under": False}
    assert _settle(win_away, 27, 24) == "won" and _settle(win_home, 27, 24) == "lost"
    sp_away = {"stat": "spread", "player": "Game spread", "line": 3.5, "under": True}  # Chiefs +3.5
    assert _settle(sp_away, 20, 23) == "won" and _settle(sp_away, 20, 24) == "lost"
    sp_home = {"stat": "spread", "player": "Game spread", "line": 3.5, "under": False}  # Bills -3.5
    assert _settle(sp_home, 20, 24) == "won" and _settle(sp_home, 20, 23) == "lost"
    over = {"stat": "total", "player": "Game total", "line": 44.5, "under": False}
    assert _settle(over, 30, 20) == "won" and _settle(over, 20, 20) == "lost"
    assert _settle(over | {"under": True}, 20, 20) == "won"
    assert _settle(over | {"line": 40.0}, 20, 20) == "void"


def test_live_label_eval():
    gl = nfl_live.gl_parse("Buffalo Bills -3.5")
    sc = nfl_live.scores(_summary(20, 24)["header"]["competitions"][0])
    assert nfl_live.gl_eval(gl, sc, True)[1] is True
    assert nfl_live.gl_eval(gl, sc, False)[1] is None
    assert nfl_live.gl_parse("Josh Allen Over 245.5 Passing Yards") is None


def test_game_lines_one_group_per_game():
    legs = nfl_legs.legs_from_rows(_rows(1))
    for g in legs:  # make every line eligible
        g["chance"], g["price"] = 0.8, 1.5
    assert len(N._player_groups(legs)) == 1


def test_game_line_chance_is_its_own_pair_devigged():
    """Owner 2026-11-09: each side priced only from its own two-way market; no head-to-head at all;
    an 'Over 3.5' (not a full-game points total) is out."""
    from melbcup import nfl_legs as L
    base = {"event_id": "e1", "event_name": "Jacksonville Jaguars @ Tennessee Titans", "period": "full_game",
            "event_start_utc": "2026-11-16T18:00:00Z"}
    rows = [
        base | {"market_family": "h2h", "market_name_raw": "Moneyline", "side": "away", "participant_name": "Jacksonville Jaguars", "price_decimal": 1.20},
        base | {"market_family": "h2h", "market_name_raw": "Moneyline", "side": "home", "participant_name": "Tennessee Titans", "price_decimal": 4.75},
        base | {"market_family": "total", "market_name_raw": "Alternate Totals", "side": "over", "line_numeric": 43.5, "line_raw": "43.5", "price_decimal": 1.53},
        base | {"market_family": "total", "market_name_raw": "Alternate Totals", "side": "under", "line_numeric": 43.5, "line_raw": "43.5", "price_decimal": 2.45},
        base | {"market_family": "total", "market_name_raw": "Alternate Totals", "side": "over", "line_numeric": 3.5, "line_raw": "3.5", "price_decimal": 5.0},
    ]
    legs = {g["label"]: g for g in L.game_lines(rows)}
    assert set(legs) == {"Over 43.5 Total Points", "Under 43.5 Total Points"}
    assert abs(legs["Over 43.5 Total Points"]["chance"] - 0.616) < 0.002
    assert all(0.85 <= g["chance"] * g["price"] <= 1.0 for g in legs.values())
