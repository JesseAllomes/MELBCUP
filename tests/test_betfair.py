"""Betfair client: login, the delayed app key, market matching and prices, with no network."""

from datetime import date

import pytest

from melbcup.domain import Race, RunnerPrices
from melbcup.sources import apply_exchange
from melbcup.sources.betfair import BetfairClient, RacePrices, back_prices, match_markets
from melbcup.sources.http import SourceError

CATALOGUE = [
    {
        "marketId": "1.10",
        "marketName": "R7 3200m Hcap",
        "marketStartTime": "2026-11-03T04:00:00.000Z",
        "description": {"marketType": "WIN"},
        "runners": [
            {"selectionId": 501, "runnerName": "20. Point Of Law", "metadata": {"CLOTH_NUMBER": "20"}},
            {"selectionId": 502, "runnerName": "2. Trustyourinstinct", "metadata": {}},
        ],
    },
    {
        "marketId": "1.11",
        "marketName": "To Be Placed",
        "marketStartTime": "2026-11-03T04:00:00.000Z",
        "description": {"marketType": "PLACE"},
        "runners": [],
    },
]
BOOKS = [
    {"marketId": "1.10", "runners": [
        {"selectionId": 501, "status": "ACTIVE", "ex": {"availableToBack": [{"price": 7.2, "size": 50}]}},
        {"selectionId": 502, "status": "REMOVED", "ex": {"availableToBack": [{"price": 9.0}]}},
    ]},
    {"marketId": "1.11", "runners": [
        {"selectionId": 501, "status": "ACTIVE", "ex": {"availableToBack": [{"price": 2.9}]}},
    ]},
]


class FakeBetfair:
    def __init__(self, apps=None, login_status="SUCCESS"):
        self.calls = []
        self.apps = apps if apps is not None else []
        self.login_status = login_status

    def __call__(self, url, headers, body, is_json):
        if not is_json:
            self.calls.append(("login", headers["X-Application"]))
            return 200, {"token": "tok", "status": self.login_status, "error": "INVALID_USERNAME_OR_PASSWORD" if self.login_status != "SUCCESS" else None}
        method = body["method"].split("/")[-1]
        self.calls.append((method, headers["X-Application"]))
        if method == "getDeveloperAppKeys":
            return 200, {"result": self.apps}
        if method == "createDeveloperAppKeys":
            self.apps = [{"appName": "melbcup", "appVersions": [
                {"applicationKey": "LIVEKEY", "delayData": False, "active": False},
                {"applicationKey": "DELAYKEY", "delayData": True, "active": True},
            ]}]
            return 200, {"result": self.apps[0]}
        if method == "listMarketCatalogue":
            assert body["params"]["filter"]["venues"] == ["Flemington"]
            return 200, {"result": CATALOGUE}
        if method == "listMarketBook":
            return 200, {"result": [b for b in BOOKS if b["marketId"] in body["params"]["marketIds"]]}
        raise AssertionError(method)


def test_creates_and_uses_the_delayed_key_then_reads_prices():
    fake = FakeBetfair()
    client = BetfairClient("me", "pw", post=fake)
    got = client.meeting(date(2026, 11, 3), "Flemington")
    assert got == {7: RacePrices({20: 7.2}, {20: 2.9}, "1.10", "1.11", {20: 501, 2: 502})}
    methods = [m for m, _ in fake.calls]
    assert methods[:4] == ["login", "getDeveloperAppKeys", "createDeveloperAppKeys", "getDeveloperAppKeys"]
    assert all(key == "DELAYKEY" for m, key in fake.calls if m.startswith("list"))
    assert "pw" not in repr(client) and "me" not in repr(client)


def test_given_app_key_skips_key_lookup():
    fake = FakeBetfair()
    BetfairClient("me", "pw", app_key="MINE", post=fake).meeting(date(2026, 11, 3), "Flemington")
    assert ("getDeveloperAppKeys", "MINE") not in fake.calls
    assert fake.calls[0] == ("login", "MINE")


def test_refused_login_is_an_auth_error_without_the_password():
    client = BetfairClient("me", "secretpw", post=FakeBetfair(login_status="FAIL"))
    with pytest.raises(SourceError) as err:
        client.meeting(date(2026, 11, 3), "Flemington")
    assert err.value.kind == "auth" and "secretpw" not in str(err.value)


def test_match_and_back_prices():
    races = match_markets(CATALOGUE)
    assert races == {7: ("1.10", "1.11", {501: 20, 502: 2})}
    assert back_prices(BOOKS[0]) == {501: 7.2}


def test_apply_exchange_sets_and_clears():
    race = Race(venue="Flemington", race_date=date(2026, 11, 3), number=7)
    race.prices[20] = RunnerPrices(20, sportsbet_win=6.5)
    apply_exchange(race, RacePrices({20: 7.2}, {20: 2.9}))
    assert race.prices[20].betfair_win == 7.2 and race.prices[20].betfair_place == 2.9
    apply_exchange(race, None)
    assert race.prices[20].betfair_win is None
