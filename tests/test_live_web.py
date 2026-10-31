from datetime import datetime, timedelta

import httpx
import pytest
from conftest import RACE_DATE, VENUE, Router, rc_market
from fastapi.testclient import TestClient

from melbcup.config import MELBOURNE, load_settings
from melbcup.domain import Race
from melbcup.live import LiveBoard, price_check_times
from melbcup.sources.formfav import FormFavClient
from melbcup.sources.racingcom import RacingComClient
from melbcup.web.app import create_app
from melbcup.web.views import edge, local_time, money, pct

ENV = {"FORMFAV_API_KEY": "ff", "APP_PASSWORD": "cup2026"}
AUTO = {**ENV, "PRICE_MODE": "auto"}
START = datetime(2026, 11, 3, 11, 30, tzinfo=MELBOURNE)  # R1 jumps 11:45, the Cup 3:00


class Clock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self) -> datetime:
        return self.t


def board_with(router: Router, clock: Clock, env=ENV) -> LiveBoard:
    t = httpx.MockTransport(router)
    return LiveBoard(
        load_settings(env),
        ff=FormFavClient("ff", transport=t),
        clock=clock,
        # racing.com's cache runs on the test's clock, so price checks are counted per check
        rc=RacingComClient(transport=t, clock=lambda: clock.t.timestamp()),
    )


def test_price_checks_are_fixed_points_shared_across_races():
    def race(n, h, m):
        return Race(VENUE, RACE_DATE, n, start_time=datetime(2026, 11, 3, h, m, tzinfo=MELBOURNE))

    one = price_check_times([race(7, 15, 0)])
    assert [t.strftime("%H:%M") for t in one] == ["14:00", "14:30", "14:45", "14:55", "14:58"]
    # Races 30 minutes apart: R8's 60-minute check is R7's 30-minute check.
    two = price_check_times([race(7, 15, 0), race(8, 15, 30)])
    assert len(two) == 9
    assert price_check_times([Race(VENUE, RACE_DATE, 1)]) == []


def test_auto_follows_the_checkpoints():
    router, clock = Router(), Clock(START)  # 11:30; R1 11:45, Cup 3:00pm
    board = board_with(router, clock, AUTO)
    board.tick()
    assert router.hits["rc/races"] == 1  # first price check on opening
    for minutes, expected in (
        (5, 1),
        (10, 2),
        (12, 2),
        (13, 3),
        (30, 3),
        (149, 3),
        (150, 4),
        (151, 4),
    ):
        clock.t = START + timedelta(minutes=minutes, seconds=10)
        board.tick()
        assert router.hits["rc/races"] == expected, minutes
    assert router.hits["rc/card_races"] == 1  # the card is loaded once


def test_reloading_the_card_keeps_prices_and_scratchings():
    router, clock = Router(scratched={1: (3,)}), Clock(START)
    board = board_with(router, clock, AUTO)
    board.tick()
    router.scratched = {}
    board.rc.src._cache.clear()
    clock.t = START + timedelta(minutes=1)
    board.load_card_now(wait=True)  # the Reload card button
    race = board.snapshot().card.race(1)
    assert race.prices and race.runner(3).scratched


def test_quota_exhaustion_pauses_polling():
    router, clock = Router(), Clock(START)
    board = board_with(router, clock, AUTO)
    board.tick()

    def limited(request):
        return httpx.Response(429, json={"message": "slow down"})

    board.rc.src._http._transport = httpx.MockTransport(limited)
    clock.t = START + timedelta(minutes=10, seconds=10)  # R1's 5-minute check
    board.tick()
    snap = board.snapshot()
    assert any("Paused automatic racing.com calls for 15 minutes" in e for e in snap.errors)
    assert snap.models  # last good board still served
    calls = board.rc.src.calls
    clock.t = START + timedelta(minutes=13, seconds=10)  # R1's 2-minute check: paused
    board.tick()
    assert board.rc.src.calls == calls


def test_a_racingcom_outage_pauses_auto_for_a_minute_and_keeps_the_board():
    router, clock = Router(), Clock(START)
    board = board_with(router, clock, AUTO)
    board.tick()
    board.rc.src._http._transport = httpx.MockTransport(lambda r: httpx.Response(503, json={}))
    clock.t = START + timedelta(minutes=10, seconds=10)  # R1's 5-minute check fails
    board.tick()
    assert any("racing.com" in e for e in board.snapshot().errors) and board.snapshot().models
    calls = board.rc.src.calls
    clock.t += timedelta(seconds=30)
    board.tick()  # still inside the minute: no retry
    assert board.rc.src.calls == calls
    clock.t += timedelta(seconds=31)
    board.tick()  # retried, and still down
    assert board.rc.src.calls > calls


def test_board_without_a_source_does_nothing():
    board = LiveBoard(load_settings({"APP_PASSWORD": "x"}))
    board.tick()
    board.start()
    assert board.snapshot().card is None


# --- web ----------------------------------------------------------------------------------


def test_manual_mode_fetches_nothing_until_asked():
    router, clock = Router(), Clock(START)
    board = board_with(router, clock)
    assert not board.auto
    board.tick()
    assert router.hits == {}
    assert board.refresh_prices_now() is False  # no card yet
    assert board.load_card_now(wait=True)
    assert router.hits["rc/card_races"] == 1
    assert router.hits["rc/races"] == 1 and router.hits["rc/prices"] == 2
    clock.t = START + timedelta(seconds=20)
    assert board.refresh_prices_now() is False  # a tap within a minute is refused
    clock.t = START + timedelta(seconds=59)
    assert board.refresh_prices_now() is False
    clock.t = START + timedelta(seconds=61)
    assert board.refresh_prices_now() is True
    assert router.hits["rc/races"] == 2 and router.hits["rc/prices"] == 4
    clock.t = START + timedelta(hours=3)
    board.tick()  # still manual: no hourly form reload, no polling
    assert router.hits["rc/card_races"] == 1
    assert router.hits["rc/races"] == 2


def test_a_failed_manual_refresh_still_counts_toward_the_minute():
    router, clock = Router(), Clock(START)
    board = board_with(router, clock)
    board.load_card_now(wait=True)
    board.rc.src._http._transport = httpx.MockTransport(lambda r: httpx.Response(503, json={}))
    clock.t = START + timedelta(seconds=70)
    assert board.refresh_prices_now() is True and board.snapshot().errors
    calls = board.rc.src.calls
    clock.t += timedelta(seconds=10)
    assert board.refresh_prices_now() is False  # hammering a failing racing.com is refused too
    assert board.rc.src.calls == calls
    clock.t += timedelta(seconds=61)
    assert board.refresh_prices_now() is True


def test_manual_results_are_limited_to_once_a_minute():
    router, clock = Router(), Clock(START)
    board = board_with(router, clock)
    board.load_card_now(wait=True)
    assert board.fetch_results_now() is True
    assert router.hits["rc/results"] == 2
    clock.t = START + timedelta(seconds=30)
    assert board.fetch_results_now() is False and router.hits["rc/results"] == 2
    clock.t = START + timedelta(seconds=61)
    assert board.fetch_results_now() is True


def test_there_is_no_credit_counter_and_no_puntersedge_anywhere_on_the_board():
    router, clock = Router(), Clock(START)
    board = board_with(router, clock)
    board.load_card_now(wait=True)
    snap = board.snapshot()
    assert not hasattr(snap, "credits_remaining") and not hasattr(board, "pe")


@pytest.fixture
def board_and_router():
    router, clock = Router(), Clock(START)
    board = board_with(router, clock)
    board.load_card_now(wait=True)
    return board, router


@pytest.fixture
def client(board_and_router):
    board, _ = board_and_router
    app = create_app(load_settings(ENV), board, start_background=False)
    with TestClient(app) as c:
        yield c


def test_buttons_and_data_source_on_page(client):
    html = client.get("/?budget=50", auth=AUTH).text
    assert "Live data from racing.com" not in html and "Sportsbet prices" not in html
    assert "credits" not in html.lower() and "PuntersEdge" not in html
    assert "Refresh prices" in html and "Reload card" in html and "Auto off" in html
    assert "next=/%3Fbudget%3D50" in html


def test_refresh_button_spends_one_call_and_returns(board_and_router):
    board, router = board_and_router
    board.clock.t += timedelta(minutes=2)  # past the one-a-minute limit and racing.com's cache
    app = create_app(load_settings(ENV), board, start_background=False)
    with TestClient(app) as c:
        r = c.post("/actions/prices?next=/race/2", auth=AUTH, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/race/2"
        assert router.hits["rc/races"] == 2
        r = c.post("/actions/auto?on=1&next=//evil.example", auth=AUTH, follow_redirects=False)
        assert r.headers["location"] == "/" and board.auto
        c.post("/actions/auto?on=0", auth=AUTH)
        assert not board.auto
        assert c.post("/actions/prices", follow_redirects=False).status_code == 401


def test_empty_manual_board_offers_load_button():
    router, clock = Router(), Clock(START)
    app = create_app(load_settings(ENV), board_with(router, clock), start_background=False)
    with TestClient(app) as c:
        html = c.get("/", auth=AUTH).text
    assert "No card loaded yet" not in html and "Load card" in html
    assert router.hits == {}


AUTH = ("", "cup2026")


def test_healthz_is_open(client):
    assert client.get("/healthz").text == "ok"


def test_password_required(client):
    assert client.get("/").status_code == 401
    assert client.get("/", auth=("x", "wrong")).status_code == 401
    assert client.get("/", auth=AUTH).status_code == 200


def test_no_password_configured_refuses():
    app = create_app(load_settings({}), start_background=False)
    with TestClient(app) as c:
        r = c.get("/", auth=("a", "b"))
    assert r.status_code == 503 and "APP_PASSWORD" in r.text


def test_public_access_needs_no_password():
    app = create_app(load_settings({"PUBLIC_ACCESS": "1"}), start_background=False)
    with TestClient(app) as c:
        assert c.get("/").status_code == 200


def test_day_page_shows_every_race_and_sections(client):
    html = client.get("/", auth=AUTH).text
    assert "Furphy Sprint" in html and "Lexus Melbourne Cup" in html
    assert (
        "Trifecta" in html and "First four" in html
    )  # each ways appear only when a price beats its chance
    assert "None: no two races" not in html  # empty sections are hidden, not explained
    assert "1800 858 858" in html
    assert "Bet $" not in html


def test_budget_sizes_bets(client):
    html = client.get("/?budget=500", auth=AUTH).text
    assert 'value="500"' in html
    assert "/race/1?budget=500" in html


def test_bad_budget_falls_back_to_the_default(client):
    html = client.get("/?budget=lots", auth=AUTH).text
    assert 'value="200"' in html


def test_race_page(client):
    r = client.get("/race/2", auth=AUTH)
    assert r.status_code == 200
    html = r.text
    assert "Grand Tempo" in html and "Racing Syndicate" in html  # owner shown
    assert "First Four" in html and "Fair div" in html
    assert "Sportsbet" in html or "SB" in html
    assert client.get("/race/9", auth=AUTH).status_code == 404


def test_runs_on_racingcom_without_any_keys():
    app = create_app(load_settings({"APP_PASSWORD": "p"}), start_background=False)
    with TestClient(app) as c:
        html = c.get("/", auth=("", "p")).text
    assert "Live data from racing.com" not in html and "credits" not in html.lower()


def test_filters():
    assert pct(0.1234, 1) == "12.3%" and pct(None) == "–"
    assert money(3.5) == "$3.50" and money(250) == "$250"
    assert edge(0.123) == "+12%" and edge(-0.05) == "-5%"
    assert local_time(datetime(2026, 11, 3, 4, 0, tzinfo=MELBOURNE)) == "4:00am"


def test_find_meetings_then_switch_and_load():
    router, clock = Router(), Clock(START)
    board = board_with(router, clock)
    assert board.find_meetings(RACE_DATE) == ["Flemington"]
    assert board.find_meetings(RACE_DATE) == ["Flemington"]  # cached per day
    assert router.hits["rc/meetings"] == 8  # one call per state, once
    assert board.set_meeting(RACE_DATE, "Flemington")
    board.load_card_now(wait=True)
    assert router.hits["rc/meeting"] == 0 if "rc/meeting" in router.hits else True
    assert board.snapshot().models


def test_switching_meeting_drops_the_old_card():
    router, clock = Router(), Clock(START)
    board = board_with(router, clock)
    board.load_card_now(wait=True)
    assert board.snapshot().card is not None
    other = RACE_DATE - timedelta(days=3)
    assert board.set_meeting(other, "Flemington")
    snap = board.snapshot()
    assert snap.card is None and snap.models == [] and snap.priced_at is None
    assert (snap.race_date, snap.venue) == (other, "Flemington")
    assert not board.set_meeting(other, "  ")


def test_meetings_page_and_switch(client):
    html = client.get("/meetings", auth=AUTH).text
    assert "Derby Day" in html and "Cup Day" in html and 'type="date"' in html
    assert 'data-refresh="0"' in html
    r = client.post(
        "/actions/meeting?date=2026-10-31&venue=Flemington", auth=AUTH, follow_redirects=False
    )
    assert r.status_code == 303 and r.headers["location"] == "/"
    home = client.get("/", auth=AUTH).text
    assert "Sat 31 Oct" in home and "No card loaded yet" not in home
    r = client.post("/actions/find?date=2026-11-03", auth=AUTH, follow_redirects=False)
    assert r.headers["location"] == "/meetings?date=2026-11-03"
    listed = client.get("/meetings?date=2026-11-03", auth=AUTH).text
    assert "venue=Flemington" in listed and "1 meeting on" in listed
    bad = client.post("/actions/meeting?date=nope&venue=X", auth=AUTH, follow_redirects=False)
    assert bad.headers["location"] == "/meetings"


def test_results_button_hidden_before_race_day(client):
    assert "Get results" not in client.get("/", auth=AUTH).text  # Cup day is still ahead


def test_results_button_grades_the_day(board_and_router, monkeypatch):
    from melbcup.web import views

    monkeypatch.setattr(views, "melbourne_today", lambda: RACE_DATE)
    board, router = board_and_router
    app = create_app(load_settings(ENV), board, start_background=False)
    with TestClient(app) as c:
        assert "Get results" in c.get("/", auth=AUTH).text
        r = c.post("/actions/results?next=/", auth=AUTH, follow_redirects=False)
        assert r.status_code == 303
        assert router.hits["rc/results"] == 2
        html = c.get("/", auth=AUTH).text
        assert "So far today: top pick won" in html and "✓" in html
        assert "Best value right now" not in html  # every race has run
        race = c.get("/race/2", auth=AUTH).text
        assert "Our picks before the race" in race and "1st" in race


def test_dates_render_without_platform_specific_formats():
    from datetime import date

    from melbcup.web.views import day, longdate, shortdate

    assert day(date(2026, 11, 3)) == "Tue 3 Nov"
    assert shortdate(date(2026, 10, 7)) == "7 Oct"
    assert longdate(date(2026, 11, 3)) == "Tue 3 Nov 2026"
    assert local_time(datetime(2026, 11, 3, 15, 0, tzinfo=MELBOURNE)) == "3:00pm"
    assert local_time(datetime(2026, 11, 3, 0, 5, tzinfo=MELBOURNE)) == "12:05am"


def test_race_names_in_capitals_are_shown_in_normal_case():
    from melbcup.web.views import book, racename

    assert racename("CASINO BEEF WEEK CUP FRI 28TH MAY") == "Casino Beef Week Cup Fri 28th May"
    assert racename("TAB RACE OF THE DAY") == "Tab Race of the Day"
    assert racename("Lexus Melbourne Cup") == "Lexus Melbourne Cup"
    assert book("SP") == "SP"


def test_prices_results_and_card_all_come_from_racingcom():
    router, clock = Router(), Clock(START)
    board = board_with(router, clock)
    board.load_card_now(wait=True)
    assert not any(k.startswith("/v1/racing") for k in router.hits)
    race1 = board.snapshot().card.race(1)
    # racing.com's Sportsbet fixed odds, and the best of its four books
    assert race1.prices[1].sportsbet_win == 2.9 and race1.prices[1].best_win.price == 2.9
    assert race1.prices[4].sportsbet_win == 7.0 and race1.prices[4].best_win.price == 7.5
    assert board.fetch_results_now()
    assert all(r.result is not None for r in board.snapshot().card.races)


def test_multis_use_racingcoms_sportsbet_prices():
    router, clock = Router(), Clock(START)
    board = board_with(router, clock)
    board.load_card_now(wait=True)
    day = board.snapshot().picks(None)
    assert day.multis and all(m.bookmaker == "sportsbet" for m in day.multis)
    legs = {(leg.race, leg.number): leg.price for m in day.multis for leg in m.legs}
    assert legs  # each leg is priced at the recorded Sportsbet win price
    recorded = {
        (race, e["raceEntryNumber"]): float(e["sb"][0]["oddsWin"][1:])
        for race in (1, 2)
        for e in rc_market(race)["GetBettingData"]["formRaceEntries"]
    }
    assert all(price == recorded[key] for key, price in legs.items())


def test_racingcom_down_for_results_is_reported_not_swallowed():
    router, clock = Router(), Clock(START)
    board = board_with(router, clock)
    board.load_card_now(wait=True)
    board.rc.src._http._transport = httpx.MockTransport(lambda r: httpx.Response(503))
    clock.t = START + timedelta(minutes=2)
    assert board.fetch_results_now()
    assert any("racing.com" in e for e in board.snapshot().errors)
    assert all(r.result is None for r in board.snapshot().card.races)


NOTES = (
    "No FormFav key",
    "unavailable (",
    "Paused automatic",
    "No prices yet",
    "No data source",
    "form only",
    "Bet about 10 minutes",
    "Check your bookmaker",
    "Runs on this phone",
    "Switching is free",
    "Fields come out",
    "Racing Australia publishes",
)


def test_pages_carry_no_source_notes_or_warnings(client, board_and_router):
    board, _ = board_and_router
    board._errors = ["FormFav quota exhausted", "racing.com refused the request"]
    board._card.warnings.append("Jockey stats unavailable (quota)")
    pages = ["/", "/race/1", "/meetings", "/history", "/meetings?date=2026-11-10"]
    for path in pages:
        html = client.get(path, auth=AUTH).text
        assert 'class="warn"' not in html and 'class="alert"' not in html, path
        assert "quota" not in html.lower() and "refused" not in html.lower(), path
        assert not any(note in html for note in NOTES), path
        assert "1800 858 858" in html, path  # the responsible-gambling footer stays


def test_source_problems_are_logged_not_shown(caplog):
    router, clock = Router(), Clock(START)
    board = board_with(router, clock, AUTO)
    board.tick()
    board.rc.src._http._transport = httpx.MockTransport(lambda r: httpx.Response(429, json={}))
    clock.t = START + timedelta(minutes=10, seconds=10)
    with caplog.at_level("WARNING", logger="melbcup.live"):
        board.tick()
    assert any("Paused automatic racing.com calls" in r.message for r in caplog.records)
