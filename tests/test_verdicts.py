"""Every pick carries one verdict, derived from the value rule and the existing price verdict."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from melbcup.web.views import Call, betting_open, call, single_call


def test_value_is_a_bet_with_its_stake():
    assert call(True, 12, 3.0, 0.4) == Call("bet", 12)
    assert call(True, None, None, None) == Call("bet", None)


def test_short_prices_skip_and_the_rest_hold():
    assert call(False, None, 2.0, 0.40).kind == "skip"  # pays 80% of fair: "Short: skip"
    assert call(False, None, 2.4, 0.40).kind == "hold"  # 96% of fair
    assert call(False, None, None, 0.40).kind == "hold"  # no price yet


def test_single_call_prefers_the_sportsbet_price():
    s = SimpleNamespace(value=False, stake=None, sportsbet=2.0, price=3.0, prob=0.4)
    assert single_call(s).kind == "skip"
    s.sportsbet = None
    assert single_call(s).kind == "hold"


def test_betting_closes_once_a_race_has_run():
    now = datetime.now(UTC)
    ahead = SimpleNamespace(result=None, start_time=now + timedelta(minutes=20))
    gone = SimpleNamespace(result=None, start_time=now - timedelta(minutes=30))
    done = SimpleNamespace(result=object(), start_time=now + timedelta(minutes=20))
    assert betting_open(ahead) and not betting_open(gone) and not betting_open(done)


def test_value_multi_without_stake_holds_when_budget_set():
    from types import SimpleNamespace

    from melbcup.web.views import make_env

    macro = make_env().get_template("_chip.html").module.multi_row
    leg = SimpleNamespace(race=3, number=10, name="Tuscan Rose")
    m = SimpleNamespace(legs=[leg, leg], value=True, stake=None, price=20.0, prob=0.08)
    assert "chip hold" in str(macro(m, 200.0))
    assert "chip bet" in str(macro(m))
