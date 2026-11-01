"""Betting: PIN, practice mode, auto's last-minute window, its own daily limit."""

from datetime import UTC, datetime, timedelta

import pytest
from test_bets import FIELD, make_model

from melbcup.autobet import BetError, Betting, PinError
from melbcup.config import load_settings
from melbcup.domain import Card
from melbcup.live import Snapshot
from melbcup.sources.betfair import Order, RacePrices

NOW = datetime(2026, 11, 3, 3, 59, 20, tzinfo=UTC)  # 2:59:20pm Melbourne, 40 s before the jump
JUMP = datetime(2026, 11, 3, 4, 0, tzinfo=UTC)


def exchange(win1=4.0, place1=1.6):
    """Runner 1 (35% chance) at $4.00 on Betfair pays 3.76 after commission: value."""
    return RacePrices(
        win={1: win1, 2: 3.2, 3: 6.0}, place={1: place1, 2: 1.3, 3: 1.6},
        win_market="1.10", place_market="1.11", selections={1: 11, 2: 12, 3: 13},
    )


class FakeBf:
    def __init__(self, ex=None, staked=0.0):
        self.ex = ex or exchange()
        self.orders = []
        self.staked = staked

    def meeting(self, race_date, venue):
        return {7: self.ex}

    def place(self, market, sel, price, stake, ref, strategy):
        self.orders.append((market, sel, price, stake, strategy))
        return Order("SUCCESS", "b1", stake, price)

    def staked_today(self, day, strategy):
        return self.staked


class FakeBoard:
    def __init__(self, bf, now=NOW):
        self.bf = bf
        self.now = now
        m = make_model(7, FIELD, [2.5, 3.0, 6.0, 10.0, 13.0, 15.0], [1.3, 1.5, 2.0, 2.5, 3.0, 3.5])
        m.race.start_time = JUMP
        self.model = m
        self.card = Card(venue="Flemington", race_date=JUMP.date(), races=[m.race])

    def clock(self):
        return self.now

    def snapshot(self):
        return Snapshot(card=self.card, models=[self.model], updated_at=self.now,
                        race_date=self.card.race_date, venue="Flemington")


def betting(bf=None, live=False, limit="500", pin="2468", now=NOW):
    env = {"AUTO_LIMIT": limit, "BET_PIN": pin} if pin else {"AUTO_LIMIT": limit}
    if live:
        env["BET_MODE"] = "live"
    board = FakeBoard(bf if bf is not None else FakeBf(), now)
    return Betting(load_settings(env), board), board


def test_pin_is_required_and_locks_after_five_misses():
    b, _ = betting()
    for _ in range(5):
        with pytest.raises(PinError):
            b.set_auto("0000", on=True)
    with pytest.raises(PinError, match="locked"):
        b.set_auto("2468", on=True)
    nopin, _ = betting(pin=None)
    with pytest.raises(PinError, match="no PIN"):
        nopin.set_auto("2468", on=True)


def test_auto_is_off_until_turned_on():
    b, board = betting()
    assert b.tick() == [] and board.bf.orders == []


def test_auto_practice_bets_betfair_value_in_the_last_minute_once():
    b, board = betting()
    b.set_auto("2468", on=True)
    placed = b.tick()
    assert placed and all(p.status == "practice" and p.mode == "practice" for p in placed)
    assert {p.number for p in placed} == {1}
    assert board.bf.orders == []  # practice places nothing
    assert b.tick() == []  # once per race
    assert b.status()["spent_today"] == sum(p.stake for p in placed)


def test_sportsbet_only_value_is_not_auto_bet():
    b, board = betting(FakeBf(exchange(win1=2.6, place1=1.2)))  # Betfair short: no value
    b.set_auto("2468", on=True)
    assert [p for p in b.tick() if p.status == "practice"] == []


def test_outside_the_window_nothing_happens():
    b, _ = betting(now=JUMP - timedelta(minutes=5))
    b.set_auto("2468", on=True)
    assert b.tick() == []


def test_auto_limit_caps_and_counts_betfair_record_when_live():
    bf = FakeBf(staked=498.0)
    b, _ = betting(bf, live=True)
    b.set_auto("2468", on=True)
    placed = b.tick()
    assert bf.orders == []
    assert placed and all(p.status == "skipped" and "limit" in p.note for p in placed)


def test_live_auto_places_on_betfair_within_limit():
    bf = FakeBf()
    b, _ = betting(bf, live=True)
    b.set_auto("2468", on=True)
    placed = b.tick()
    assert bf.orders and all(o[4] == "melbcup-auto" for o in bf.orders)
    assert sum(o[3] for o in bf.orders) <= 500
    assert all(p.status == "matched" for p in placed if p.status != "skipped")


def test_bet_by_hand_needs_pin_and_respects_practice():
    b, board = betting()
    with pytest.raises(PinError):
        b.bet_by_hand("1111", 7, 1, "win", 10)
    p = b.bet_by_hand("2468", 7, 1, "win", 10)
    assert p.status == "practice" and p.price == 4.0 and board.bf.orders == []
    with pytest.raises(BetError):
        b.bet_by_hand("2468", 7, 99, "win", 10)
    small = b.bet_by_hand("2468", 7, 1, "place", 2)
    assert small.status == "skipped" and "minimum" in small.note
