from datetime import date, datetime

import httpx
import pytest
from conftest import RACE_DATE, VENUE, Router, load_fixture

from melbcup.config import MELBOURNE
from melbcup.domain import going_band, going_rating, parse_distance, parse_margin
from melbcup.sources import apply_market, load_card
from melbcup.sources.formfav import FormFavClient, parse_track_bias, track_slug
from melbcup.sources.http import JsonSource, SourceError
from melbcup.sources.puntersedge import (
    PuntersEdgeClient,
    parse_acceptances,
    parse_form,
    parse_next_to_go,
)


def clients(router: Router, *, with_ff: bool = True):
    t = httpx.MockTransport(router)
    pe = PuntersEdgeClient("pe-key", transport=t)
    ff = FormFavClient("ff-key", transport=t) if with_ff else None
    return pe, ff


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


# --- vendor example payloads (shape checks) ------------------------------------------------


def test_vendor_acceptances_example_parses_owner_and_local_start():
    card = parse_acceptances(load_fixture("pe_acceptances"), "grafton", date(2026, 9, 29))
    race = card.races[0]
    assert race.number == 4 and race.distance_m == 1106
    runner = race.runner(2)
    assert runner.name == "Geegee Jet By"
    assert runner.owner.startswith("D J Dick")
    assert runner.gear_changes and runner.hcp_rating == 66
    assert race.start_time == datetime(2026, 9, 29, 14, 45, tzinfo=MELBOURNE)
    assert card.condition == "Soft 5"


def test_vendor_acceptances_missing_venue_warns():
    card = parse_acceptances(load_fixture("pe_acceptances"), "Flemington", RACE_DATE)
    assert card.races == []
    assert "No acceptances" in card.warnings[0]


def test_vendor_form_example():
    form = parse_form(load_fixture("pe_form"))
    runs, record = form[1]
    assert runs[0].venue == "Coffs Harbour" and runs[0].position == 3
    assert runs[0].margin_l == 1.8
    assert (record.starts, record.wins, record.top3) == (1, 0, 1)


def test_vendor_next_to_go_example():
    data = load_fixture("pe_next_to_go")
    snaps = parse_next_to_go(data, "northam", date(2026, 10, 29))
    assert set(snaps) == {4, 5}
    snap = snaps[4]
    assert snap.places_paid == 3
    priced = [p for p in snap.prices.values() if p.best_win]
    assert priced and all(p.best_win.price > 1 for p in priced)
    assert all(p.sportsbet_win for p in priced)
    assert sum(p.consensus_prob for p in snap.prices.values()) == pytest.approx(1.0)
    assert not set(snap.prices) & snap.scratched
    # another venue, or another day at this venue, yields nothing
    assert parse_next_to_go(data, "Flemington", date(2026, 10, 29)) == {}
    assert parse_next_to_go(data, "Northam", date(2026, 10, 30)) == {}


def test_stale_quotes_are_ignored():
    race = {
        "race_number": 1,
        "runners": [
            {
                "number": 1,
                "bookmakers": [
                    {"key": "tab", "win_price": 2.0, "place_price": 1.2},
                    {"key": "sportsbet", "win_price": 9.0, "stale": True},
                ],
            }
        ],
    }
    from melbcup.sources.puntersedge import parse_race_prices

    p = parse_race_prices(race).prices[1]
    assert p.best_win.price == 2.0 and p.sportsbet_win is None


# --- synthetic full card ------------------------------------------------------------------


def test_markets_consensus_is_margin_free_and_sums_to_one(router):
    pe, _ = clients(router)
    snap = pe.card_prices(RACE_DATE, VENUE)[1]
    total = sum(p.consensus_prob for p in snap.prices.values())
    assert total == pytest.approx(1.0)
    fav = snap.prices[1]
    assert fav.sportsbet_win == 3.2
    assert fav.best_win.price == 3.2 and fav.best_win.bookmaker == "sportsbet"
    assert snap.prices[2].best_win.bookmaker == "tab"
    assert fav.books == 2
    # Margin removed per book, then the median: the favourite stays the favourite and its
    # probability sits between the two books' own margin-free figures.
    assert max(snap.prices.values(), key=lambda p: p.consensus_prob) is fav
    sb = 1 / 3.2 / sum(1 / p for p in (3.2, 3.6, 15.0, 6.0, 31.0, 9.0))
    tab = 1 / 3.0 / sum(1 / p for p in (3.0, 3.8, 13.0, 6.5, 26.0, 10.0))
    assert min(sb, tab) <= fav.consensus_prob <= max(sb, tab) + 0.01


def test_load_card_merges_both_feeds(router):
    pe, ff = clients(router)
    card = load_card(pe, ff, RACE_DATE, VENUE)
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
    pe, ff = clients(router)
    card = load_card(pe, ff, RACE_DATE, VENUE)
    r = card.race(1).runner(1)
    assert r.career.starts == 20  # /v1/form is on the free tier
    assert r.feed_win_prob is None and r.jockey_stats is None
    assert any("predictions" in w for w in card.warnings)
    assert any("Jockey stats" in w for w in card.warnings)


def test_load_card_without_formfav_key(router):
    pe, _ = clients(router, with_ff=False)
    card = load_card(pe, None, RACE_DATE, VENUE)
    r = card.race(1).runner(2)
    assert r.runs and r.career.starts == 4  # from PuntersEdge form summary
    assert any("No FormFav key" in w for w in card.warnings)


def test_apply_market_marks_late_scratchings():
    router = Router(scratched={1: (3,)})
    pe, ff = clients(router)
    card = load_card(pe, ff, RACE_DATE, VENUE)
    race = card.race(1)
    apply_market(race, pe.card_prices(RACE_DATE, VENUE)[1])
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
    pe, ff = clients(router)
    card = load_card(pe, ff, RACE_DATE, VENUE)
    race = card.race(1)
    race.start_time = race.start_time.replace(hour=8)  # as if read in the wrong time zone
    apply_market(race, pe.card_prices(RACE_DATE, VENUE)[1])
    assert race.start_time == datetime.fromisoformat("2026-11-03T00:45:00+00:00")


def test_formfav_stops_asking_after_a_refusal():
    router = Router(ff_tier="free")
    pe, ff = clients(router)
    load_card(pe, ff, RACE_DATE, VENUE)
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
    from datetime import date

    from melbcup.domain import Race, Runner, StatLine
    from melbcup.model.probability import assess
    from melbcup.sources import update_going
    from melbcup.sources.puntersedge import MarketSnapshot

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
    from melbcup.sources.racingcom import RacingComClient

    router = Router()
    pe, ff = clients(router)
    rc = RacingComClient(transport=httpx.MockTransport(router))
    card = load_card(pe, ff, RACE_DATE, VENUE, rc)
    r1 = card.race(1).runner(1)
    assert r1.last_start_note == "Slow to begin. Held up in the straight."
    assert [n.run_date.isoformat() for n in r1.run_notes] == ["2026-10-17", "2026-09-26"]
    assert r1.run_notes[0].finish == 5 and r1.run_notes[0].settled == 4
    assert card.race(1).runner(2).last_start_note is None  # ran, no comment
    assert not any("racing.com" in w for w in card.warnings)
    run = r1.runs[0]  # the model's recent form now comes from racing.com
    assert (run.position, run.margin_l, run.sp, run.weight_kg) == (5, 1.5, 6.5, 57.0)
    assert (run.field_size, run.race_class, run.jockey) == (12, "BM78", "J.Kah")
    assert "/v1/racing/form" not in router.hits  # no PuntersEdge form credits spent


def test_racingcom_outage_only_adds_a_warning():
    from melbcup.sources.racingcom import RacingComClient

    router = Router()
    pe, ff = clients(router)
    down = httpx.MockTransport(lambda request: httpx.Response(503, json={}))
    card = load_card(pe, ff, RACE_DATE, VENUE, RacingComClient(transport=down))
    assert card.race(1).runner(1).run_notes is None
    assert any("racing.com" in w for w in card.warnings)
    assert router.hits["/v1/racing/form"] == len(card.races)  # PuntersEdge fills in
    assert card.race(1).runner(1).runs


def test_racingcom_results_parse_finish_prices_and_dividends():
    from melbcup.sources.racingcom import RacingComClient

    router = Router()
    rc = RacingComClient(transport=httpx.MockTransport(router))
    results = rc.results(RACE_DATE, VENUE, [1, 2])
    r1 = results[1]
    assert r1.status == "final" and r1.finish[1] == 1 and r1.names[1] == "Swift Comet"
    assert r1.sp[1] == 3.0 and r1.place_dividend[2] == 2.0
    assert r1.exotics["TF"] == ((1, 2, 3), 60.0) and r1.exotics["FF"] == ((1, 2, 3, 4), 400.0)
