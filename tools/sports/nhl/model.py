"""NHL models: market baseline (margin removed), calibrated market, Elo, rest, scoring-rate stack.

Everything that predicts uses only information known before the game. `rows` are dicts as read by
`load_games` (dataset.csv.gz), in date order.
"""

from __future__ import annotations

import csv
import gzip
import math
from collections import defaultdict

import numpy as np

LN10 = math.log(10.0)
MARKETS = ("ml", "pl", "tot")
VARIANTS = ("market", "calibrated", "elo", "elo_rest")  # tried per market


def prob_from_american(o: float) -> float:
    return 100.0 / (o + 100.0) if o > 0 else -o / (-o + 100.0)


def decimal_from_american(o: float) -> float:
    return 1.0 + (o / 100.0 if o > 0 else 100.0 / -o)


def devig(oa: float, ob: float) -> float:
    """Proportional margin removal: chance of side A from a two-way price pair."""
    pa, pb = prob_from_american(oa), prob_from_american(ob)
    return pa / (pa + pb)


def overround(oa: float, ob: float) -> float:
    return prob_from_american(oa) + prob_from_american(ob)


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


def log_loss_each(p, y):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def _f(s: str):
    return float(s) if s not in ("", None) else None


def load_games(path: str) -> list[dict]:
    out = []
    with gzip.open(path, "rt", newline="") as f:
        for r in csv.DictReader(f):
            for k in ("away_g", "home_g"):
                r[k] = int(r[k])
            for k in ("ml_away", "ml_home", "ml_away_open", "ml_home_open", "pl_home",
                      "pl_home_odds", "pl_away_odds", "total", "over_odds", "under_odds",
                      "total_open"):
                r[k] = _f(r[k])
            out.append(r)
    return out


def valid_pair(a, b) -> bool:
    """A usable two-way price pair: both present and a sane margin (drops typing errors)."""
    return a is not None and b is not None and 1.0 < overround(a, b) < 1.15


class State:
    """Causal team state: Elo, scoring rates, last game date. Call `features` before `update`."""

    def __init__(self, k: float = 6.0, regress: float = 0.3, alpha: float = 0.04):
        self.k, self.regress, self.alpha = k, regress, alpha
        self.elo = defaultdict(lambda: 1500.0)
        self.gf = defaultdict(lambda: 3.0)
        self.ga = defaultdict(lambda: 3.0)
        self.last = {}
        self.season = None

    def features(self, g: dict) -> dict:
        h, a = g["home"], g["away"]
        proj = 0.5 * (self.gf[h] + self.ga[a]) + 0.5 * (self.gf[a] + self.ga[h])
        return {"elo": (self.elo[h] - self.elo[a]) * LN10 / 400.0,
                "b2b": float(self._rest(h, g["date"]) - self._rest(a, g["date"])),
                "b2b_sum": float(self._rest(h, g["date"]) + self._rest(a, g["date"])),
                "proj": proj}

    def _rest(self, t: str, date: str) -> int:
        d = self.last.get(t)
        if d is None:
            return 0
        return 1 if (_ord(date) - _ord(d)) <= 1 else 0

    def update(self, g: dict) -> None:
        if g["season"] != self.season:
            for t in list(self.elo):
                self.elo[t] += self.regress * (1500.0 - self.elo[t])
            self.season = g["season"]
        h, a = g["home"], g["away"]
        eh = 1.0 / (1.0 + 10 ** (-(self.elo[h] - self.elo[a]) / 400.0))
        diff = g["home_g"] - g["away_g"]
        res = 1.0 if diff > 0 else 0.0
        mult = math.log(abs(diff) + 1.0) + 0.6
        d = self.k * mult * (res - eh)
        self.elo[h] += d
        self.elo[a] -= d
        for t, f, c in ((h, g["home_g"], g["away_g"]), (a, g["away_g"], g["home_g"])):
            self.gf[t] += self.alpha * (f - self.gf[t])
            self.ga[t] += self.alpha * (c - self.ga[t])
            self.last[t] = g["date"]


def _ord(date: str) -> int:
    import datetime as dt
    return dt.date.fromisoformat(date).toordinal()


def market_rows(games: list[dict], k: float = 6.0):
    """Walk games in order; for each market return a list of dicts: market prob p, outcome y,
    causal features, season and the two prices (for ROI). Total pushes (score == line) dropped."""
    st = State(k=k)
    recs = {m: [] for m in MARKETS}
    for g in games:
        f = st.features(g)
        base = {"season": g["season"], "date": g["date"], **f}
        hw = g["home_g"] > g["away_g"]
        if valid_pair(g["ml_away"], g["ml_home"]):
            recs["ml"].append({**base, "p": devig(g["ml_home"], g["ml_away"]), "y": float(hw),
                               "o_a": g["ml_home"], "o_b": g["ml_away"]})
        if g["pl_home"] not in ("", None) and valid_pair(g["pl_home_odds"], g["pl_away_odds"]):
            cover = (g["home_g"] - g["away_g"] + g["pl_home"]) > 0
            recs["pl"].append({**base, "p": devig(g["pl_home_odds"], g["pl_away_odds"]),
                               "y": float(cover), "o_a": g["pl_home_odds"],
                               "o_b": g["pl_away_odds"], "line": g["pl_home"]})
        if g["total"] and valid_pair(g["over_odds"], g["under_odds"]):
            tg = g["home_g"] + g["away_g"]
            if tg != g["total"]:
                recs["tot"].append({**base, "p": devig(g["over_odds"], g["under_odds"]),
                                    "y": float(tg > g["total"]), "o_a": g["over_odds"],
                                    "o_b": g["under_odds"], "line": g["total"],
                                    "dproj": f["proj"] - g["total"]})
        st.update(g)
    return recs, st


def design(rec: list[dict], market: str, variant: str) -> np.ndarray:
    """Feature matrix for a stack variant (first col is always logit of market prob)."""
    cols = [logit(np.array([r["p"] for r in rec]))]
    if variant in ("elo", "elo_rest") and market in ("ml", "pl"):
        cols.append(np.array([r["elo"] for r in rec]))
    if variant in ("elo", "elo_rest") and market == "tot":
        cols.append(np.array([r["dproj"] for r in rec]))
    if variant == "elo_rest":
        cols.append(np.array([r["b2b"] if market != "tot" else r["b2b_sum"] for r in rec]))
    return np.column_stack(cols)


def fit_logistic(X: np.ndarray, y: np.ndarray, ridge: float = 1e-3, iters: int = 30):
    """Intercept + weights by Newton steps. Returns (a, w)."""
    A = np.column_stack([np.ones(len(X)), X])
    beta = np.zeros(A.shape[1])
    beta[1] = 1.0  # start from 'trust the market'
    R = ridge * np.eye(A.shape[1])
    R[0, 0] = 0.0
    for _ in range(iters):
        p = sigmoid(A @ beta)
        gr = A.T @ (p - y) + R @ (beta - np.r_[0.0, 1.0, np.zeros(A.shape[1] - 2)])
        H = (A * (p * (1 - p))[:, None]).T @ A + R
        step = np.linalg.solve(H, gr)
        beta -= step
        if np.abs(step).max() < 1e-8:
            break
    return float(beta[0]), [float(b) for b in beta[1:]]


def predict(a: float, w: list[float], X: np.ndarray) -> np.ndarray:
    return sigmoid(a + X @ np.array(w))


def predict_variant(params: dict | None, rec: list[dict], market: str, variant: str):
    if variant == "market" or params is None:
        return np.array([r["p"] for r in rec])
    return predict(params["a"], params["w"], design(rec, market, variant))
