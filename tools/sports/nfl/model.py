"""NFL model: start from the no-vig market; optional logistic adjustments (numpy only).

Markets: moneyline (home win), spread (home covers), total (over). Every variant is a logistic
regression on logit(market prob) plus optional extras; variant "mkt" is the raw market.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ELO_K, ELO_HFA, ELO_REVERT, ELO_PTS = 20.0, 48.0, 1 / 3, 25.0  # 25 elo points ~ 1 point margin

MARKETS = {
    "ml": dict(p="p_home", y="home_win", extras=["elo", "rest"]),
    "spread": dict(p="p_spread_home", y="home_cover", extras=["elo_resid", "rest", "fav"]),
    "total": dict(p="p_over", y="over", extras=["tline", "week"]),
}
# variant name -> list of extra features; "slope" = no intercept; "mkt" = raw market
VARIANTS = {
    "ml": {
        "mkt": None, "slope": [], "platt": [], "platt+elo": ["elo"], "platt+rest": ["rest"],
        "platt+elo+rest": ["elo", "rest"],
    },
    "spread": {
        "mkt": None, "platt": [], "platt+elo_resid": ["elo_resid"], "platt+rest": ["rest"],
        "platt+fav": ["fav"],
    },
    "total": {
        "mkt": None, "platt": [], "platt+tline": ["tline"], "platt+week": ["week"],
    },
}


def logit(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sigmoid(z):
    return 1 / (1 + np.exp(-z))


def add_elo(d: pd.DataFrame) -> pd.DataFrame:
    """Pre-game Elo difference (home minus away, incl. home field) - no look-ahead."""
    d = d.sort_values(["date", "game_id"]).reset_index(drop=True).copy()
    rt: dict[str, float] = {}
    cur = None
    diffs = []
    for r in d.itertuples():
        if r.season != cur:
            for k in rt:
                rt[k] = 1500 + (rt[k] - 1500) * (1 - ELO_REVERT)
            cur = r.season
        h, a = rt.get(r.home, 1500.0), rt.get(r.away, 1500.0)
        diff = h - a + (0 if r.neutral else ELO_HFA)
        diffs.append(diff)
        if r.played and not np.isnan(r.home_score):
            exp = 1 / (1 + 10 ** (-diff / 400))
            mov = r.home_score - r.away_score
            res = 1.0 if mov > 0 else 0.0 if mov < 0 else 0.5
            mult = np.log(abs(mov) + 1) * 2.2 / ((abs(diff) * 0.001) + 2.2) if mov else 1.0
            delta = ELO_K * mult * (res - exp)
            rt[r.home], rt[r.away] = h + delta, a - delta
    d["elo_diff"] = diffs
    return d


def features(d: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=d.index)
    f["elo"] = d.elo_diff / 400
    f["elo_resid"] = (d.elo_diff / ELO_PTS - d.spread) / 10  # elo margin minus market margin
    f["rest"] = ((d.home_rest - d.away_rest).clip(-7, 7).fillna(0)) / 7
    f["fav"] = np.sign(d.spread).fillna(0)  # home favourite flag
    f["tline"] = (d.total - 45) / 10
    f["week"] = (d.week.clip(1, 18) - 9) / 9
    return f


def design(d, market, variant):
    cfg = MARKETS[market]
    f = features(d)
    cols = [logit(d[cfg["p"]].values)[:, None]]
    if variant != "slope":
        cols.insert(0, np.ones((len(d), 1)))
    for e in VARIANTS[market][variant]:
        cols.append(f[e].values[:, None])
    return np.hstack(cols)


def fit_logit(X, y, ridge=1e-4, iters=50):
    w = np.zeros(X.shape[1])
    if X.shape[1] and np.allclose(X[:, 0], 1):
        w[1] = 1.0  # start at the market
    else:
        w[0] = 1.0
    for _ in range(iters):
        p = sigmoid(X @ w)
        g = X.T @ (p - y) + ridge * w
        H = (X * (p * (1 - p))[:, None]).T @ X + ridge * np.eye(len(w))
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-9:
            break
    return w


def usable(d, market):
    cfg = MARKETS[market]
    m = d[cfg["p"]].notna() & d[cfg["y"]].notna() & d.spread.notna()
    if market == "ml":
        m &= d[cfg["y"]] != 0.5
    return d[m]


class Fitted:
    def __init__(self, market, variant, w):
        self.market, self.variant, self.w = market, variant, w

    def predict(self, d):
        if self.variant == "mkt":
            return d[MARKETS[self.market]["p"]].values
        return sigmoid(design(d, self.market, self.variant) @ self.w)

    def to_json(self):
        return dict(market=self.market, variant=self.variant,
                    extras=VARIANTS[self.market][self.variant],
                    weights=None if self.w is None else [float(x) for x in self.w])


def fit(d, market, variant) -> Fitted:
    if variant == "mkt":
        return Fitted(market, variant, None)
    tr = usable(d, market)
    return Fitted(market, variant, fit_logit(design(tr, market, variant),
                                             tr[MARKETS[market]["y"]].values))


def logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))
