import importlib.util
import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from conftest import RACE_DATE, VENUE, Router, load_fixture, rc_market, rc_payload

from melbcup.domain import going_band, going_rating, parse_distance, parse_margin
from melbcup.sources import apply_market, load_card
from melbcup.sources.formfav import FormFavClient, parse_track_bias, track_slug
from melbcup.sources.http import JsonSource, SourceError
from melbcup.sources.racingcom import BOOKS, PRICE_FIELDS, RacingComClient, parse_market

ROOT = Path(__file__).resolve().parent.parent


def clients(router: Router, *, with_ff: bool = True):
    t = httpx.MockTransport(router)
    rc = RacingComClient(transport=t)
    ff = FormFavClient("ff-key", transport=t) if with_ff else None
    return rc, ff


# --- small parsers -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [("1.8L", 1.8), ("HD", 0.2), ("nk", 0.3), ("12", 12.0), ("", None), ("?", None)],
)
def test_parse_margin(text, expected):
    assert parse_margin(text) == expected


def test_going_helpers():
    assert going_band("Soft (6)") == "soft"
    assert going_rating("Soft (6)") == 6
    assert going_band("Good 4") == "good"
    assert going_band(None) is None
    assert parse_distance("3,200m") == 3200
    assert track_slug("Moonee Valley") == "moonee-valley"


# --- racing.com prices: recorded market records --------------------------------------------


def test_price_query_asks_for_what_the_live_collector_records():
    """The app reads the same GetBettingData fields tools/live_collector.py records, and the
    fixtures are trimmed copies of what it recorded."""
    spec = importlib.util.spec_from_file_location(
        "live_collector", ROOT / "tools/live_collector.py"
    )
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)
    assert {alias: code for alias, (code, _) in BOOKS.items()} == collector.BOOKS
    assert PRICE_FIELDS == collector.PRICE
    recorded = collector.market_query(False)
    for alias, code in collector.BOOKS.items():
        assert f'{alias}: oddsByProvider(providerCode:"{code}")' in recorded
    entry = load_fixture("rc_market")["race1"]["data"]["GetBettingData"]["formRaceEntries"][0]
    assert set(collector.BOOKS) <= set(entry) and set(entry["sb"][0]) == set(PRICE_FIELDS.split())


def test_recorded_market_gives_sportsbet_and_the_best_of_four_books():
    snap = parse_market({}, rc_market(1))
    assert set(snap.prices) == set(range(1, 9)) and not snap.scratched
    one = snap.prices[1]
    assert (one.sportsbet_win, one.sportsbet_place) == (2.9, 1.3)
    assert (
        one.best_win.price == 2.9 and one.best_win.bookmaker == "sportsbet"
    )  # a tie keeps Sportsbet
    assert (
        snap.prices[4].best_win.price == 7.5 and snap.prices[4].best_win.bookmaker == "ladbrokes_au"
    )
    assert (
        snap.prices[6].best_win.price == 51.0 and snap.prices[6].best_win.bookmaker == "pointsbetau"
    )
    assert snap.prices[1].best_place.price >= 1.3
    assert all(p.sportsbet_win for p in snap.prices.values())
    assert snap.start_time == datetime(2026, 11, 3, 0, 45, tzinfo=UTC)
    # the newest of the books' own update stamps (epoch seconds)
    entries = rc_market(1)["GetBettingData"]["formRaceEntries"]
    stamps = [
        o[t] for e in entries for b in BOOKS for o in e[b] for t in ("updated", "placeUpdated")
    ]
    assert snap.observed_at == datetime.fromtimestamp(max(stamps), UTC)
    assert snap.places_paid == 3  # eight starters


def test_unlisted_scratched_and_reserve_runners_are_left_out_of_the_market():
    snap = parse_market({"trackCondition": "Soft 6"}, {"GetBettingData": rc_market_mixed()})
    assert snap.scratched == {4}  # no quote from any book, and scratched
    assert set(snap.prices) == {1, 2, 3, 5}  # runner 11 is an emergency: a reserve, not a starter
    assert snap.condition == "Soft 6"
    assert sum(p.consensus_prob for p in snap.prices.values()) == pytest.approx(1.0)
    assert all(p.books == 4 for p in snap.prices.values())


def rc_market_mixed() -> dict:
    return load_fixture("rc_market")["mixed"]["data"]["GetBettingData"]


def test_a_book_with_no_price_for_a_runner_has_no_quote_from_it():
    data = rc_market(1)
    for e in data["GetBettingData"]["formRaceEntries"]:
        if e["raceEntryNumber"] == 2:
            e["sb"] = []  # Sportsbet lists no price for runner 2
        if e["raceEntryNumber"] == 3:
            e["sb"][0]["oddsWin"] = None
    snap = parse_market({}, data)
    assert snap.prices[2].sportsbet_win is None and snap.prices[2].best_win.price == 2.9
    assert snap.prices[3].sportsbet_win is None and snap.prices[3].best_win.price == 31.0


def test_a_race_with_no_prices_is_left_out_and_settled_races_are_skipped():
    def serve(status: str, *, with_prices: bool = True) -> RacingComClient:
        def handler(request):
            query = request.url.params["query"]
            body = rc_payload(query, json.loads(request.url.params["variables"]))
            if "oddsByProvider" in query:
                race = body["data"]["GetBettingData"]
                race["raceStatus"] = status
                for e in race["formRaceEntries"]:
                    for alias in BOOKS:
                        e[alias] = e[alias] if with_prices else []
            return httpx.Response(200, json=body)

        return RacingComClient(transport=httpx.MockTransport(handler))

    assert set(serve("Open").card_prices(RACE_DATE, VENUE, [1, 2])) == {1, 2}
    assert set(serve("FinalFields").card_prices(RACE_DATE, VENUE, [1, 2])) == {1, 2}  # pre-race
    assert serve("Paying").card_prices(RACE_DATE, VENUE, [1, 2]) == {}
    assert serve("Interim").card_prices(RACE_DATE, VENUE, [1, 2]) == {}
    assert serve("Abandoned").card_prices(RACE_DATE, VENUE, [1, 2]) == {}
    assert serve("Open", with_prices=False).card_prices(RACE_DATE, VENUE, [1, 2]) == {}


def test_racingcom_failure_surfaces_as_a_source_error():
    down = RacingComClient(transport=httpx.MockTransport(lambda r: httpx.Response(503, json={})))
    with pytest.raises(SourceError) as exc:
        down.card_prices(RACE_DATE, VENUE, [1])
    assert exc.value.kind == "unavailable"
    errors = RacingComClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"errors": [{"message": "boom"}], "data": None})
        )
    )
    with pytest.raises(SourceError, match="boom"):
        errors.card_prices(RACE_DATE, VENUE, [1])


# --- synthetic full card ------------------------------------------------------------------


def test_markets_consensus_is_margin_free_and_sums_to_one(router):
    rc, _ = clients(router)
    snap = rc.card_prices(RACE_DATE, VENUE, [1, 2])[2]  # the Cup: Grand Tempo at $2.30
    total = sum(p.consensus_prob for p in snap.prices.values())
    assert total == pytest.approx(1.0)
    fav = snap.prices[1]
    assert fav.sportsbet_win == 2.3 and fav.best_win.bookmaker == "sportsbet"
    assert fav.books == 4
    # Margin removed per book, then the median: the favourite stays the favourite and its
    # probability sits among the four books' own margin-free figures.
    assert max(snap.prices.values(), key=lambda p: p.consensus_prob) is fav
    entries = rc_market(2)["GetBettingData"]["formRaceEntries"]
    own = []
    for alias in BOOKS:
        win = {e["raceEntryNumber"]: float(e[alias][0]["oddsWin"][1:]) for e in entries}
        own.append((1 / win[1]) / sum(1 / p for p in win.values()))
    assert min(own) - 0.01 <= fav.consensus_prob <= max(own) + 0.01


def test_load_card_merges_both_feeds(router):
    rc, ff = clients(router)
    card = load_card(rc, ff, RACE_DATE, VENUE)
    assert [r.number for r in card.races] == [1, 2]
    assert card.warnings == []
    cup = card.race(2)
    assert cup.name == "Lexus Melbourne Cup" and cup.distance_m == 3200
    r = cup.runner(1)
    assert r.owner and r.jockey == "J McDonald"
    assert r.runs and r.runs[0].run_date >= r.runs[-1].run_date
    assert r.career.starts == 20
    assert r.going.starts == 12  # "Good 4" -> good split
    assert r.running_style == "leader"
    assert r.feed_win_prob is not None
    assert r.jockey_stats.at_track.starts == 80
    assert r.trainer_stats.recent.starts == 60
    assert cup.barrier_advantage[1] > cup.barrier_advantage[12]
    # one stats call per distinct person; the bias payload is fetched once and banded locally
    assert router.hits["/v1/stats/track-bias/flemington"] == 1
    jockey_calls = sum(v for k, v in router.hits.items() if k.startswith("/v1/stats/jockey/"))
    assert jockey_calls == 6


def test_load_card_degrades_without_formfav_pro():
    router = Router(ff_tier="free")
    rc, ff = clients(router)
    card = load_card(rc, ff, RACE_DATE, VENUE)
    r = card.race(1).runner(1)
    assert r.career.starts == 20  # /v1/form is on the free tier
    assert r.feed_win_prob is None and r.jockey_stats is None
    assert any("predictions" in w for w in card.warnings)
    assert any("Jockey stats" in w for w in card.warnings)


def test_load_card_without_formfav_key(router):
    rc, _ = clients(router, with_ff=False)
    card = load_card(rc, None, RACE_DATE, VENUE)
    r = card.race(1).runner(2)
    assert r.runs and r.career.starts == 10  # racing.com's records on each going
    assert any("No FormFav key" in w for w in card.warnings)


def test_apply_market_marks_late_scratchings():
    router = Router(scratched={1: (3,)})
    rc, ff = clients(router)
    card = load_card(rc, ff, RACE_DATE, VENUE)
    race = card.race(1)
    apply_market(race, rc.card_prices(RACE_DATE, VENUE, [1, 2])[1])
    assert race.runner(3).scratched
    assert 3 not in race.prices
    assert race.prices_at is not None


def test_track_bias_ignores_thin_samples_and_uses_distance_band():
    data = {
        "barrierStats": [{"barrierNumber": 1, "totalStarts": 500, "advantage": 0.01}],
        "distanceStats": [
            {
                "minDistance": 2800,
                "maxDistance": 3600,
                "barrierStats": [
                    {"barrierNumber": 1, "totalStarts": 50, "advantage": 0.03},
                    {"barrierNumber": 2, "totalStarts": 5, "advantage": 0.2},
                ],
            }
        ],
    }
    assert parse_track_bias(data, 3200) == {1: 0.03}
    assert parse_track_bias(data, 1200) == {1: 0.01}


# --- http layer ---------------------------------------------------------------------------


def test_json_source_caches_within_ttl_and_sends_key():
    seen = []

    def handler(request):
        seen.append(request.headers["X-API-Key"])
        return httpx.Response(200, json={"n": len(seen)})

    now = [0.0]
    src = JsonSource(
        "T", "https://x.test", "k1", transport=httpx.MockTransport(handler), clock=lambda: now[0]
    )
    assert src.get("/a", {"q": 1}, ttl=60) == {"n": 1}
    assert src.get("/a", {"q": 1}, ttl=60) == {"n": 1}
    now[0] = 61
    assert src.get("/a", {"q": 1}, ttl=60) == {"n": 2}
    assert seen == ["k1", "k1"]


@pytest.mark.parametrize(
    "status,kind",
    [
        (401, "auth"),
        (402, "quota"),
        (429, "rate_limit"),
        (500, "unavailable"),
        (422, "bad_request"),
    ],
)
def test_json_source_error_kinds(status, kind):
    src = JsonSource(
        "T",
        "https://x.test",
        "k",
        transport=httpx.MockTransport(lambda r: httpx.Response(status, text="no")),
    )
    with pytest.raises(SourceError) as exc:
        src.get("/a")
    assert exc.value.kind == kind and exc.value.status == status


def test_json_source_network_failure_is_unavailable():
    def boom(request):
        raise httpx.ConnectError("down")

    src = JsonSource("T", "https://x.test", "k", transport=httpx.MockTransport(boom))
    with pytest.raises(SourceError) as exc:
        src.get("/a")
    assert exc.value.kind == "unavailable"


def test_price_feed_corrects_start_time(router):
    rc, ff = clients(router)
    card = load_card(rc, ff, RACE_DATE, VENUE)
    race = card.race(1)
    race.start_time = race.start_time.replace(hour=8)  # as if read in the wrong time zone
    apply_market(race, rc.card_prices(RACE_DATE, VENUE, [1, 2])[1])
    assert race.start_time == datetime.fromisoformat("2026-11-03T00:45:00+00:00")


def test_formfav_stops_asking_after_a_refusal():
    router = Router(ff_tier="free")
    rc, ff = clients(router)
    load_card(rc, ff, RACE_DATE, VENUE)
    pro_calls = sum(
        v for k, v in router.hits.items() if k.startswith("/v1/stats/") or k == "/v1/predictions"
    )
    # one refused prediction call and one refused stats call (in-flight pool calls may add a few)
    assert pro_calls <= 2 + 8
    assert router.hits["/v1/form"] == 2  # form is on the free plan and still fetched per race


def test_formfav_over_quota_blocks_the_whole_key():
    def over(request):
        return httpx.Response(429, json={"detail": "over quota"})

    ff = FormFavClient("k", transport=httpx.MockTransport(over))
    with pytest.raises(SourceError):
        ff.form(RACE_DATE, VENUE, 1)
    calls = ff.src.calls
    with pytest.raises(SourceError):
        ff.track_bias(VENUE, 1200)
    assert ff.src.calls == calls
    ff.reset_blocks()
    with pytest.raises(SourceError):
        ff.form(RACE_DATE, VENUE, 1)
    assert ff.src.calls == calls + 1


def test_rain_on_the_day_switches_each_runners_going_record():
    from melbcup.domain import Race, Runner, StatLine
    from melbcup.model.probability import assess
    from melbcup.sources import update_going
    from melbcup.sources.racingcom import MarketSnapshot

    wet, dry = StatLine(6, 3, 5), StatLine(6, 0, 1)
    race = Race("Flemington", date(2026, 11, 3), 1, condition="Good 4")
    race.runners = [
        Runner(1, "Mudlark", going=dry, going_records={"good": dry, "soft": wet}),
        Runner(2, "Dry Track Dan", going=wet, going_records={"good": wet, "soft": dry}),
        Runner(3, "No Record"),
    ]
    update_going(race, "Good4")  # the same going, written another way: nothing changes
    assert race.condition_was is None and race.runner(1).going is dry
    before = assess(race).runners[1].win
    snap = MarketSnapshot({}, 3, None, set(), condition="Soft 6", weather="Showers")
    apply_market(race, snap)
    assert race.condition == "Soft 6" and race.condition_was == "Good 4"
    assert race.weather == "Showers"
    assert race.runner(1).going is wet and race.runner(2).going is dry
    assert race.runner(3).going is None
    assert assess(race).runners[1].win > before  # the wet-tracker's chance rises
    update_going(race, "Good 4")  # dries out again
    assert race.condition_was is None and race.runner(1).going is dry


def test_person_stats_keep_the_record_on_each_going():
    from conftest import ff_person_payload

    from melbcup.domain import StatLine
    from melbcup.sources.formfav import parse_person

    p = parse_person(ff_person_payload("Jamie Kah", "jockey"), VENUE)
    assert p.on_going("Soft 6") == StatLine(90, 9, 30)
    assert p.on_going("Good 4").starts == 400
    assert p.on_going("Heavy 9") is None and p.on_going(None) is None


def test_card_load_adds_racingcom_stewards_comments_from_before_race_day():
    router = Router()
    rc, ff = clients(router)
    card = load_card(rc, ff, RACE_DATE, VENUE)
    r1 = card.race(1).runner(1)
    assert r1.last_start_note == "Slow to begin. Held up in the straight."
    assert [n.run_date.isoformat() for n in r1.run_notes] == ["2026-10-17", "2026-09-26"]
    assert r1.run_notes[0].finish == 5 and r1.run_notes[0].settled == 4
    assert card.race(1).runner(2).last_start_note is None  # ran, no comment
    assert not any("racing.com" in w for w in card.warnings)
    run = r1.runs[0]  # the model's recent form comes from racing.com
    assert (run.position, run.margin_l, run.sp, run.weight_kg) == (5, 1.5, 6.5, 57.0)
    assert (run.field_size, run.race_class, run.jockey) == (12, "BM78", "J.Kah")


def test_racingcom_runs_outage_only_adds_a_warning():
    router = Router()

    def runs_down(request):
        if "GetRaceEntryItemByHorsePaged" in request.url.params["query"]:
            return httpx.Response(503, json={})
        return router(request)

    t = httpx.MockTransport(runs_down)
    card = load_card(RacingComClient(transport=t), None, RACE_DATE, VENUE)
    assert card.race(1).runner(1).run_notes is None and not card.race(1).runner(1).runs
    assert any("racing.com" in w for w in card.warnings)
    assert card.race(2).name == "Lexus Melbourne Cup"  # the field itself still loaded


def test_card_load_fails_loudly_when_racingcom_is_down():
    down = httpx.MockTransport(lambda request: httpx.Response(503, json={}))
    with pytest.raises(SourceError):
        load_card(RacingComClient(transport=down), None, RACE_DATE, VENUE)


def test_card_carries_names_distances_gear_and_owners_from_racingcom(router):
    rc, _ = clients(router)
    card = load_card(rc, None, RACE_DATE, VENUE)
    cup = card.race(2)
    assert cup.name == "Lexus Melbourne Cup" and cup.distance_m == 3200
    assert cup.start_time == datetime(2026, 11, 3, 4, 0, tzinfo=UTC)
    assert cup.runner(1).owner.endswith("Racing Syndicate")
    assert card.race(1).runner(3).gear_changes == "Blinkers FIRST TIME"
    assert card.race(1).runner(3).hcp_rating == 72


def test_racingcom_results_parse_finish_prices_and_dividends():
    router = Router()
    rc = RacingComClient(transport=httpx.MockTransport(router))
    results = rc.results(RACE_DATE, VENUE, [1, 2])
    r1 = results[1]
    assert r1.status == "final" and r1.finish[1] == 1 and r1.names[1] == "Swift Comet"
    assert r1.sp[1] == 3.0 and r1.place_dividend[2] == 2.0
    assert r1.exotics["TF"] == ((1, 2, 3), 60.0) and r1.exotics["FF"] == ((1, 2, 3, 4), 400.0)
    assert r1.placegetters(3) == [1, 2, 3]
