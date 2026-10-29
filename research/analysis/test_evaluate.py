"""Settlement and scoring checks for evaluate.py. Run: MELBCUP_DATA=x MELBCUP_RESULTS=/tmp/t python3 test_evaluate.py"""
import numpy as np
import pandas as pd
import evaluate as E


def race(rid, wins, prices, P, status, day="2025-08-01"):
    n = len(prices)
    return pd.DataFrame(dict(race_id=rid, date=day, mel_date=day, block="tune1", starter=True, inU_t30=True,
                             won=[i in wins for i in range(n)], M_t30=1.0 / n, fav_M_t30=[i == 0 for i in range(n)],
                             sb_t30=prices, lb_t30=prices, barrier=range(1, n + 1), scoring_status_t30=status)), P


def b_returns(frames):
    d = pd.concat([f for f, _ in frames], ignore_index=True)
    P = np.concatenate([p for _, p in frames])
    out = E.claims(d, P, P, P, 0.95)["B"]
    return out


def test_win_returns():
    # one of two joint winners backed: half the quote; several and all joint winners backed: each q/k
    assert np.allclose(E.win_returns([True], [10.0], [2]), [4.0])
    assert np.allclose(E.win_returns([True, True], [10.0, 6.0], [2, 2]), [4.0, 2.0])
    assert np.allclose(E.win_returns([True, True, True], [9.0, 9.0, 9.0], [3, 3, 3]), [2.0, 2.0, 2.0])
    assert np.allclose(E.win_returns([True, True], [9.0, 9.0], [3, 3]), [2.0, 2.0])     # two of three joint winners
    assert np.allclose(E.win_returns([False, True], [5.0, 4.0], [1, 1]), [-1.0, 3.0])   # no dead heat


def test_claims_dead_heat():
    hi = np.array([0.30, 0.30, 0.20, 0.20])          # P*q - 1 >= 0.05 at q=4 for the first two only
    q = [4.0, 4.0, 4.0, 4.0]
    # back one of two joint winners (runner 0 backed, runner 1 also backed? no: make runner 1 unbacked)
    one = race("r1", {0, 2}, q, hi, "dead_heat")
    r = b_returns([one])
    assert r["bets"] == 2 and np.isclose(r["roi"], ((4 / 2 - 1) + (-1)) / 2), r       # backed winner pays q/2; runner 1 lost
    # back both joint winners
    both = race("r2", {0, 1}, q, hi, "dead_heat")
    r = b_returns([both])
    assert r["bets"] == 2 and np.isclose(r["roi"], 4 / 2 - 1), r
    # three-way dead heat, all three backed
    p3 = np.array([0.30, 0.30, 0.30, 0.10])
    three = race("r3", {0, 1, 2}, q, p3, "dead_heat")
    r = b_returns([three])
    assert r["bets"] == 3 and np.isclose(r["roi"], 4 / 3 - 1), r


if __name__ == "__main__":
    test_win_returns()
    test_claims_dead_heat()
    print("all settlement tests passed")
