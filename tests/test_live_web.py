from datetime import datetime, timedelta

import httpx
import pytest
from conftest import RACE_DATE, VENUE, Router
from fastapi.testclient import TestClient

from melbcup.config import MELBOURNE, load_settings
from melbcup.domain import Race
from melbcup.live import LiveBoard, price_check_times
from melbcup.sources.formfav import FormFavClient
from melbcup.sources.puntersedge import PuntersEdgeClient
from melbcup.web.app import create_app
from melbcup.web.views import edge, local_time, money, pct

ENV = {"PUNTERSEDGE_API_KEY": "pe", "FORMFAV_API_KEY": "ff", "APP_PASSWORD": "cup2026"}
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
        pe=PuntersEdgeClient("pe", transport=t),
        ff=FormFavClient("ff", transport=t),
        clock=clock,
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
    assert router.hits["/v1/racing/next-to-go"] == 1  # first look on opening
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
        assert router.hits["/v1/racing/next-to-go"] == expected, minutes
    assert router.hits["/v1/racing/acceptances"] == 1  # the card is loaded once


def test_auto_credit_plan_counts_what_is_left():
    router, clock = Router(), Clock(START)
    board = board_with(router, clock, AUTO)
    board.tick()
    # R1: 11:40 and 11:43 left; Cup: five checks; two races still to be resulted
    assert board.snapshot().auto_credits_left == 2 * 7 + 2 * 2


def test_reloading_the_card_keeps_prices_and_scratchings():
    router, clock = Router(scratched={1: (3,)}), Clock(START)
    board = board_with(router, clock, AUTO)
    board.tick()
    router.scratched = {}
    board.pe.src._cache.clear()
    clock.t = START + timedelta(minutes=1)
    board.load_card_now(wait=True)  # the Reload card button
    race = board.snapshot().card.race(1)
    assert race.prices and race.runner(3).scratched


def test_quota_exhaustion_pauses_polling():
    router, clock = Router(), Clock(START)
    board = board_with(router, clock, AUTO)
    board.tick()

    def broke(request):
        return httpx.Response(402, json={"detail": "out of credits"})

    board.pe.src._http._transport = httpx.MockTransport(broke)
    clock.t = START + timedelta(minutes=10, seconds=10)  # R1's 5-minute check
    board.tick()
    snap = board.snapshot()
    assert any("Paused" in e for e in snap.errors)
    assert snap.models  # last good board still served
    calls = board.pe.src.calls
    clock.t = START + timedelta(minutes=13, seconds=10)  # R1's 2-minute check: paused
    board.tick()
    assert board.pe.src.calls == calls


def test_board_without_keys_does_nothing():
    board = LiveBoard(load_settings({"APP_PASSWORD": "x"}))
    board.tick()
    board.start()
    assert board.snapshot().card is None


# --- web ----------------------------------------------------------------------------------


def test_manual_mode_spends_nothing_until_asked():
    router, clock = Router(), Clock(START)
    board = board_with(router, clock)
    assert not board.auto
    board.tick()
    assert router.hits == {}
    assert board.refresh_prices_now() is False  # no card yet
    assert board.load_card_now(wait=True)
    assert router.hits["/v1/racing/acceptances"] == 1
    assert router.hits["/v1/racing/next-to-go"] == 1
    clock.t = START + timedelta(seconds=5)
    assert board.refresh_prices_now() is False  # double tap within 15 s
    clock.t = START + timedelta(seconds=20)
    assert board.refresh_prices_now() is True
    assert router.hits["/v1/racing/next-to-go"] == 2
    clock.t = START + timedelta(hours=3)
    board.tick()  # still manual: no hourly form reload, no polling
    assert router.hits["/v1/racing/acceptances"] == 1
    assert router.hits["/v1/racing/next-to-go"] == 2


def test_credits_come_from_balance_then_headers():
    router, clock = Router(), Clock(START)
    board = board_with(router, clock)
    board.check_credits()
    snap = board.snapshot()
    assert (snap.credits_remaining, snap.credits_limit) == (2999, 3000)
    board.load_card_now(wait=True)
    assert board.snapshot().credits_remaining < 2999


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


def test_buttons_and_credits_on_page(client):
    html = client.get("/?budget=50", auth=AUTH).text
    assert "PuntersEdge credits left" in html and "/ 3,000" in html
    assert "Refresh prices" in html and "Reload card" in html and "Auto off" in html
    assert "next=/%3Fbudget%3D50" in html


def test_refresh_button_spends_one_call_and_returns(board_and_router):
    board, router = board_and_router
    board._priced_at -= timedelta(minutes=1)
    app = create_app(load_settings(ENV), board, start_background=False)
    with TestClient(app) as c:
        r = c.post("/actions/prices?next=/race/2", auth=AUTH, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/race/2"
        assert router.hits["/v1/racing/next-to-go"] == 2
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
    assert "No card loaded yet" in html and "Load card" in html
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


def test_day_page_shows_every_race_and_sections(client):
    html = client.get("/", auth=AUTH).text
    assert "Furphy Sprint" in html and "Lexus Melbourne Cup" in html
    assert "Each way" in html and "Trifecta:" in html and "Quaddies" in html
    assert "Multis (Sportsbet)" in html
    assert "1800 858 858" in html
    assert "Bet $" not in html


def test_budget_sizes_bets(client):
    html = client.get("/?budget=500", auth=AUTH).text
    assert 'value="500"' in html
    assert "/race/1?budget=500" in html


def test_bad_budget_is_ignored(client):
    html = client.get("/?budget=lots", auth=AUTH).text
    assert 'value=""' in html


def test_race_page(client):
    r = client.get("/race/2", auth=AUTH)
    assert r.status_code == 200
    html = r.text
    assert "Grand Tempo" in html and "Racing Syndicate" in html  # owner shown
    assert "First Four" in html and "Fair div" in html
    assert "Sportsbet" in html or "SB" in html
    assert client.get("/race/9", auth=AUTH).status_code == 404


def test_setup_message_without_keys():
    app = create_app(load_settings({"APP_PASSWORD": "p"}), start_background=False)
    with TestClient(app) as c:
        html = c.get("/", auth=("", "p")).text
    assert "Add your data keys" in html


def test_filters():
    assert pct(0.1234, 1) == "12.3%" and pct(None) == "–"
    assert money(3.5) == "$3.50" and money(250) == "$250"
    assert edge(0.123) == "+12%" and edge(-0.05) == "-5%"
    assert local_time(datetime(2026, 11, 3, 4, 0, tzinfo=MELBOURNE)) == "4:00am"


def test_find_meetings_then_switch_and_load_share_one_call():
    router, clock = Router(), Clock(START)
    board = board_with(router, clock)
    assert board.find_meetings(RACE_DATE) == ["Flemington"]
    assert board.find_meetings(RACE_DATE) == ["Flemington"]  # cached per day
    assert board.set_meeting(RACE_DATE, "Flemington")
    board.load_card_now(wait=True)
    assert router.hits["/v1/racing/acceptances"] == 1  # lookup and load shared one call
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
    assert "Sat 31 Oct" in home and "No card loaded yet" in home
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
        assert router.hits["/v1/racing/results"] == 1
        html = c.get("/", auth=AUTH).text
        assert "How the model went" in html and "top pick won" in html and "✓" in html
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
