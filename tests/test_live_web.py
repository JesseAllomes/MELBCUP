from datetime import datetime, timedelta

import httpx
import pytest
from conftest import RACE_DATE, VENUE, Router
from fastapi.testclient import TestClient

from melbcup.config import MELBOURNE, load_settings
from melbcup.domain import Race
from melbcup.live import LiveBoard, price_interval
from melbcup.sources.formfav import FormFavClient
from melbcup.sources.puntersedge import PuntersEdgeClient
from melbcup.web.app import create_app, edge, local_time, money, pct

ENV = {"PUNTERSEDGE_API_KEY": "pe", "FORMFAV_API_KEY": "ff", "APP_PASSWORD": "cup2026"}
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


def test_price_interval_tightens_toward_the_jump():
    jump = datetime(2026, 11, 3, 15, 0, tzinfo=MELBOURNE)
    race = Race(VENUE, RACE_DATE, 7, start_time=jump)
    assert price_interval(race, jump - timedelta(hours=3), 60) == timedelta(minutes=15)
    assert price_interval(race, jump - timedelta(minutes=45), 60) == timedelta(minutes=5)
    assert price_interval(race, jump - timedelta(minutes=10), 60) == timedelta(seconds=60)
    assert price_interval(race, jump + timedelta(minutes=2), 60) == timedelta(seconds=60)
    assert price_interval(race, jump + timedelta(minutes=6), 60) is None
    assert price_interval(Race(VENUE, RACE_DATE, 1), jump, 60) == timedelta(minutes=15)


def test_tick_polls_card_prices_at_the_tightest_interval():
    router, clock = Router(), Clock(START)
    board = board_with(router, clock)
    board.tick()
    snap = board.snapshot()
    assert [m.race.number for m in snap.models] == [1, 2]
    assert all("market" in m.sources for m in snap.models)
    assert router.hits["/v1/racing/next-to-go"] == 1  # one call prices the whole card

    clock.t = START + timedelta(seconds=30)
    board.tick()  # R1 is 15 min out: 60 s polling, not due yet
    assert router.hits["/v1/racing/next-to-go"] == 1

    clock.t = START + timedelta(seconds=61)
    board.tick()
    assert router.hits["/v1/racing/next-to-go"] == 2
    assert router.hits["/v1/racing/acceptances"] == 1  # form is hourly

    clock.t = START + timedelta(minutes=21)  # 11:51: R1 has run; only the Cup (15 min) counts
    board.tick()
    assert router.hits["/v1/racing/next-to-go"] == 3
    clock.t = START + timedelta(minutes=30)
    board.tick()
    assert router.hits["/v1/racing/next-to-go"] == 3
    clock.t = START + timedelta(minutes=37)
    board.tick()
    assert router.hits["/v1/racing/next-to-go"] == 4


def test_form_reload_keeps_prices_and_scratchings():
    router, clock = Router(scratched={1: (3,)}), Clock(START)
    board = board_with(router, clock)
    board.tick()
    clock.t = START + timedelta(hours=1, minutes=1)
    router.scratched = {}
    board.tick()
    race = board.snapshot().card.race(1)
    assert race.prices and race.runner(3).scratched


def test_quota_exhaustion_pauses_polling():
    router, clock = Router(), Clock(START)
    board = board_with(router, clock)
    board.tick()

    def broke(request):
        return httpx.Response(402, json={"detail": "out of credits"})

    board.pe.src._http._transport = httpx.MockTransport(broke)
    clock.t = START + timedelta(minutes=2)
    board.tick()
    snap = board.snapshot()
    assert any("Paused" in e for e in snap.errors)
    assert snap.models  # last good board still served
    calls = board.pe.src.calls
    clock.t = START + timedelta(minutes=5)
    board.tick()
    assert board.pe.src.calls == calls


def test_board_without_keys_does_nothing():
    board = LiveBoard(load_settings({"APP_PASSWORD": "x"}))
    board.tick()
    board.start()
    assert board.snapshot().card is None


# --- web ----------------------------------------------------------------------------------


@pytest.fixture
def client():
    router, clock = Router(), Clock(START)
    board = board_with(router, clock)
    board.tick()
    app = create_app(load_settings(ENV), board, start_background=False)
    with TestClient(app) as c:
        yield c


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
