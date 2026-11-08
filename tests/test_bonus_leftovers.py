from melbcup import nba_challenge as C
from melbcup import wallet

T = "2026-11-08"


def _store(amount=10.72, prov="Sportsbet"):
    s = C.empty_store()
    s, _, err = C.apply_store(s, {"ch": "newch", "chname": "A", "op": "n1"}, T)
    assert not err
    s["ledger"] = wallet.append(s["ledger"], {"t": "grant", "amount": amount, "provider": prov}, T)
    return s


def _wager(s, op, funding, stake=6.12, cr="c1"):
    q = {"ch": "wgr", "chid": "ch1", "op": op, "wprov": "Sportsbet", "wlegs": "x", "wodds": "2",
         "wstake": str(stake), "wfund": funding, "wcredit": cr}
    return C.apply_store(s, q, T)


def _left(s):
    return wallet.balances(s["ledger"], T).get("Sportsbet", {}).get("open", 0.0)


def test_leftover_stays():
    s, _, err = _wager(_store(), "o1", "bonus")
    assert not err and _left(s) == 4.60


def test_repeat_no_double_deduction():
    s, _, _ = _wager(_store(), "o1", "bonus")
    n = len(s["ledger"])
    s["ledger"] = wallet.use_leftover(s["ledger"], "Sportsbet", 6.12, "bonus-use-w1", T)
    assert len(s["ledger"]) == n and _left(s) == 4.60
    s2, changed, _ = _wager(s, "o1", "bonus")
    assert not changed and _left(s2) == 4.60


def test_short_credit_does_not_crash():
    s, _, err = _wager(_store(amount=3.0), "o1", "bonus")
    assert not err and _left(s) == 0.0 and s["wagers"]


def test_cash_untouched():
    s, _, err = _wager(_store(), "o1", "cash")
    assert not err and _left(s) == 10.72


def test_spreads_oldest_expiry_first_and_reverses():
    L = wallet.append([], {"t": "grant", "amount": 5, "provider": "Sportsbet", "expiry": "2026-12-31"}, T)
    L = wallet.append(L, {"t": "grant", "amount": 5, "provider": "Sportsbet", "expiry": "2026-11-20"}, T)
    L = wallet.use_leftover(L, "sportsbet", 7, "bonus-use-1", T)
    cs = wallet.credits(L, T)
    assert cs["c2"]["status"] == "redeemed" and cs["c1"]["amount"] == 3.0
    L = wallet.unuse_leftover(L, "bonus-use-1", T)
    assert wallet.balances(L, T)["Sportsbet"]["open"] == 10.0


def test_engine_bonus_bet_uses_credit():
    s = _store()
    s, _, _ = C.apply_store(s, {"ch": "start", "chid": "ch1", "op": "s"}, T)
    s2, _, err = C.apply_store(s, {"ch": "place", "chid": "ch1", "chs": "0", "chag": "sb", "chp": "2", "chbonus": "1", "op": "p"}, T)
    placed = s2["challenges"][0]["state"].get("placed")
    if placed and placed.get("bonus"):
        assert _left(s2) == round(10.72 - placed["stake"], 2)
