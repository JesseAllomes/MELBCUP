"""Models for NBA games and props: market baseline, favourite-longshot, Elo, logistic stack.

Everything that predicts uses only information known before the game.
"""

from __future__ import annotations

import csv
import gzip
import math

import numpy as np


def prob_from_american(o: float) -> float:
    return 100.0 / (o + 100.0) if o > 0 else -o / (-o + 100.0)


def decimal_from_american(o: float) -> float:
    return 1.0 + (o / 100.0 if o > 0 else 100.0 / -o)


def devig(oa: float, ob: float) -> float:
    """Proportional margin removal: chance of side A from a two-way price pair."""
    pa, pb = prob_from_american(oa), prob_from_american(ob)
    return pa / (pa + pb)


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


def fit_logit(X: np.ndarray, y: np.ndarray, ridge: float = 1e-3, iters: int = 50) -> np.ndarray:
    """Logistic regression with an intercept (first column of ones added), Newton steps."""
    A = np.column_stack([np.ones(len(X)), X])
    w = np.zeros(A.shape[1])
    R = ridge * np.eye(A.shape[1])
    R[0, 0] = 0.0
    for _ in range(iters):
        p = sigmoid(A @ w)
        g = A.T @ (p - y) + R @ w
        H = (A * (p * (1 - p))[:, None]).T @ A + R
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-9:
            break
    return w


def predict_logit(w: np.ndarray, X: np.ndarray) -> np.ndarray:
    return sigmoid(w[0] + X @ w[1:])


class Elo:
    """Margin-aware Elo from final scores; ratings regress to the mean each new season."""

    def __init__(self, k=20.0, home=100.0, carry=0.75):
        self.k, self.home, self.carry = k, home, carry
        self.r: dict[str, float] = {}
        self.season = None

    def _rating(self, t):
        return self.r.get(t, 1500.0)

    def diff(self, home: str, away: str) -> float:
        return self._rating(home) - self._rating(away) + self.home

    def new_season(self, season: str) -> None:
        if season != self.season:
            self.r = {t: 1500 + self.carry * (v - 1500) for t, v in self.r.items()}
            self.season = season

    def update(self, home, away, hp, ap):
        d = self.diff(home, away)
        exp = 1 / (1 + 10 ** (-d / 400))
        res = 1.0 if hp > ap else 0.0
        mov = abs(hp - ap)
        mult = ((mov + 3) ** 0.8) / (7.5 + 0.006 * (d if res else -d))
        delta = self.k * mult * (res - exp)
        self.r[home] = self._rating(home) + delta
        self.r[away] = self._rating(away) - delta


def load_games(path: str) -> list[dict]:
    out = []
    with gzip.open(path, "rt") as f:
        for r in csv.DictReader(f):
            for c in ("away_pts", "home_pts"):
                r[c] = int(r[c])
            for c in ("ml_away", "ml_home", "spread_home_close", "spread_home_open",
                      "total_close", "total_open"):
                r[c] = float(r[c]) if r[c] not in ("", None) else None
            out.append(r)
    return out


def game_features(games: list[dict]) -> dict[str, np.ndarray]:
    """Per game with a moneyline, in order: market chance of a home win (margin removed),
    pre-game Elo diff, label, index into games. Elo is rebuilt from scores alone, in date order."""
    elo = Elo()
    pm, ed, y, keep = [], [], [], []
    for i, g in enumerate(games):
        elo.new_season(g["season"])
        if g["ml_home"] and g["ml_away"]:
            pm.append(devig(g["ml_home"], g["ml_away"]))
            ed.append(elo.diff(g["home"], g["away"]))
            y.append(1.0 if g["home_pts"] > g["away_pts"] else 0.0)
            keep.append(i)
        elo.update(g["home"], g["away"], g["home_pts"], g["away_pts"])
    return {"pm": np.array(pm), "elo": np.array(ed), "y": np.array(y), "idx": np.array(keep)}


VARIANTS = {  # name -> feature builder (the count of these is the number of models tried)
    "market": None,
    "market_flb": lambda f: np.column_stack([logit(f["pm"])]),
    "elo_only": lambda f: np.column_stack([f["elo"] / 400.0]),
    "market_elo": lambda f: np.column_stack([logit(f["pm"]), f["elo"] / 400.0]),
}


def fit_variant(name: str, f: dict, mask: np.ndarray) -> list[float] | None:
    if VARIANTS[name] is None:
        return None
    X = VARIANTS[name](f)
    return fit_logit(X[mask], f["y"][mask]).tolist()


def predict_variant(name: str, w, f: dict, mask: np.ndarray) -> np.ndarray:
    if VARIANTS[name] is None:
        return f["pm"][mask]
    return predict_logit(np.array(w), VARIANTS[name](f)[mask])
