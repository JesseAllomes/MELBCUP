"""AFL model: start from the de-margined market, add adjustments only if they earn it.

Candidates (all fitted on seasons before the hold-out only):
  market       proportional margin removal of a single book's closing prices
  power(k)     favourite-longshot correction: p_i proportional to (1/odds_i)**k
  recal        logit(p) = a*logit(p_market) + c
  elo          recal plus a pre-game Elo term (results only)
  elo_rest     elo plus days-of-rest difference
Usage as library; test.py runs the honest evaluation.
"""

import math

import numpy as np
import pandas as pd
from scipy.optimize import minimize

EPS = 1e-6


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def expit(x):
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=float)))


def devig(o1, o2, k: float = 1.0):
    """Two-way margin removal. k=1 proportional; k>1 shrinks longshots (favourite-longshot)."""
    a = (1.0 / np.asarray(o1, dtype=float)) ** k
    b = (1.0 / np.asarray(o2, dtype=float)) ** k
    return a / (a + b)


def overround(o1, o2):
    return 1.0 / np.asarray(o1, dtype=float) + 1.0 / np.asarray(o2, dtype=float) - 1.0


def log_loss(p, y):
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    y = np.asarray(y, dtype=float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


# ---- Elo from results (pre-game ratings, no leakage) ----------------------------------------
def elo_run(d: pd.DataFrame, k: float = 20.0, hga: float = 30.0, carry: float = 0.75):
    """Return (pre-game home rating, away rating, final ratings). Margin-scaled updates."""
    rating: dict[str, float] = {}
    last_season = None
    rh, ra = [], []
    for r in d.itertuples():
        if last_season is not None and r.season != last_season:
            rating = {t: 1500 + carry * (v - 1500) for t, v in rating.items()}
        last_season = r.season
        h, a = rating.get(r.home, 1500.0), rating.get(r.away, 1500.0)
        rh.append(h)
        ra.append(a)
        exp = 1 / (1 + 10 ** (-(h + hga - a) / 400))
        mult = math.log(abs(r.margin) + 1) + 1.0
        delta = k * mult * (r.home_win - exp)
        rating[r.home] = h + delta
        rating[r.away] = a - delta
    return np.array(rh), np.array(ra), rating


def add_elo(d: pd.DataFrame, k: float = 20.0, hga: float = 30.0) -> pd.DataFrame:
    d = d.copy()
    rh, ra, _ = elo_run(d, k, hga)
    d["elo_h"], d["elo_a"] = rh, ra
    d["elo_p"] = 1 / (1 + 10 ** (-(rh + hga - ra) / 400))
    return d


def add_rest(d: pd.DataFrame, cap: float = 14.0) -> pd.DataFrame:
    """Days since each side's previous game (capped); NaN-free (cap at season start)."""
    d = d.copy()
    last: dict[str, pd.Timestamp] = {}
    rh, ra = [], []
    for r in d.itertuples():
        for team, out in ((r.home, rh), (r.away, ra)):
            prev = last.get(team)
            out.append(min((r.date - prev).days, cap) if prev is not None else cap)
            last[team] = r.date
    d["rest_h"], d["rest_a"] = rh, ra
    return d


# ---- logistic fit ----------------------------------------------------------------------------
def fit_logit(X: np.ndarray, y: np.ndarray, l2: float = 1e-3):
    """Logistic regression with intercept; returns coefficients [c, b1, b2, ...]."""
    X1 = np.column_stack([np.ones(len(X)), X])

    def nll(w):
        z = X1 @ w
        return np.sum(np.logaddexp(0, z) - y * z) + l2 * np.sum(w[1:] ** 2)

    w0 = np.zeros(X1.shape[1])
    if X1.shape[1] > 1:
        w0[1] = 1.0
    return minimize(nll, w0, method="BFGS").x


def predict_logit(w, X):
    return expit(np.column_stack([np.ones(len(X)), X]) @ w)


def fit_power_k(o1, o2, y) -> float:
    ks = np.arange(0.90, 1.4001, 0.01)
    ll = [log_loss(devig(o1, o2, k), y).mean() for k in ks]
    return float(ks[int(np.argmin(ll))])


def h2h_features(d: pd.DataFrame, kind: str, odds=("h_close", "a_close")):
    pm = devig(d[odds[0]], d[odds[1]])
    cols = [logit(pm)]
    if kind in ("elo", "elo_rest"):
        cols.append(logit(d["elo_p"]))
    if kind == "elo_rest":
        cols.append(np.clip(d["rest_h"] - d["rest_a"], -7, 7) / 7.0)
    return np.column_stack(cols)


def fit_model(train: pd.DataFrame, odds=("h_close", "a_close")) -> dict:
    """Fit every candidate on `train`; returns a json-able dict."""
    t = train.dropna(subset=list(odds))
    y = t["home_win"].to_numpy()
    out = {"n_train": int(len(t)), "seasons": [int(t.season.min()), int(t.season.max())]}
    out["power_k"] = fit_power_k(t[odds[0]], t[odds[1]], y)
    for kind in ("recal", "elo", "elo_rest"):
        out[kind] = fit_logit(h2h_features(t, kind, odds), y).tolist()
    return out


def predict_h2h(model: dict, d: pd.DataFrame, kind: str, odds=("h_close", "a_close")):
    if kind == "market":
        return devig(d[odds[0]], d[odds[1]])
    if kind == "power":
        return devig(d[odds[0]], d[odds[1]], model["power_k"])
    return predict_logit(np.array(model[kind]), h2h_features(d, kind, odds))


def tune_elo(d: pd.DataFrame, train_last: int):
    """Grid over (k, hga) on the training seasons only; returns best params and grid size."""
    tr = d[d.season <= train_last]
    best, n = None, 0
    for k in (10, 20, 30):
        for hga in (20, 30, 40):
            n += 1
            e = add_elo(d, k, hga)
            e = e[(e.season <= train_last) & (e.season >= 2013)]
            ll = log_loss(e["elo_p"], e["home_win"]).mean()
            if best is None or ll < best[0]:
                best = (ll, k, hga)
    del tr
    return {"k": best[1], "hga": best[2]}, n
