"""Racing win model: start from the de-margined market, adjust only where the data says so.

Layers (each fitted on train seasons only):
  proportional   q_i = (1/odds_i) / sum_j (1/odds_j) within a race
  power          p_i ~ q_i**alpha, renormalised (favourite-longshot correction; alpha<1 lifts
                 longshots, alpha>1 shortens them)
  features       conditional logit  u_i = alpha*log q_i + beta . x_i  (softmax within race)
                 x = barrier fraction, weight vs race mean, rating vs race mean, age, sex, and
                 prior-only jockey / trainer / horse residuals (wins minus market expectation,
                 shrunk), so the extra terms measure what the market did NOT already price.
"""

import json
import math
import os

import numpy as np
import pandas as pd
from scipy.optimize import minimize

FEATURES = [
    "barrier_frac",
    "wt_diff",
    "rating_diff",
    "age_c",
    "gelding",
    "mare",
    "jockey_resid",
    "trainer_resid",
    "horse_resid",
]
SHRINK = {"jockey_resid": 100.0, "trainer_resid": 100.0, "horse_resid": 6.0}


def race_id(df: pd.DataFrame) -> pd.Series:
    return df["meeting_id"].astype(str) + "_" + df["race_no"].astype(str)


def market_probs(df: pd.DataFrame, col: str) -> pd.Series:
    """Proportional de-margining. NaN for every runner of a race with any missing/invalid price."""
    inv = 1.0 / df[col].where(df[col] > 1.0)
    rid = race_id(df)
    tot = inv.groupby(rid).transform("sum")  # NaN-skipping, so check completeness separately
    complete = inv.notna().groupby(rid).transform("all")
    return (inv / tot).where(complete)


def overround(df: pd.DataFrame, col: str) -> pd.Series:
    inv = 1.0 / df[col].where(df[col] > 1.0)
    rid = race_id(df)
    complete = inv.notna().groupby(rid).transform("all")
    return inv.groupby(rid).transform("sum").where(complete)


def power_probs(q: pd.Series, rid: pd.Series, alpha: float) -> pd.Series:
    w = q**alpha
    return w / w.groupby(rid).transform("sum")


def fit_alpha(q: pd.Series, win: pd.Series, rid: pd.Series) -> float:
    """Alpha maximising winner log-likelihood on the given (train) rows."""
    mask = q.notna()
    q, win, rid = q[mask], win[mask], rid[mask]

    def nll(a: float) -> float:
        p = power_probs(q, rid, a)
        return float(-np.log(p[win == 1].clip(1e-9)).sum())

    grid = np.linspace(0.7, 1.4, 36)
    best = min(grid, key=nll)
    return float(minimize(lambda x: nll(x[0]), [best], method="Nelder-Mead").x[0])


def add_prior_residuals(df: pd.DataFrame, q: pd.Series) -> pd.DataFrame:
    """Jockey/trainer/horse (win - market prob) summed over STRICTLY EARLIER dates, shrunk.
    Uses only information known before the race day."""
    df = df.copy()
    df["_r"] = (df["win"] - q).fillna(0.0)
    df["_n"] = q.notna().astype(float)
    for name, key in [
        ("jockey_resid", "jockey"),
        ("trainer_resid", "trainer"),
        ("horse_resid", "horse_code"),
    ]:
        daily = df.groupby([key, "date"], sort=True)[["_r", "_n"]].sum().reset_index()
        daily[["_cr", "_cn"]] = daily.groupby(key)[["_r", "_n"]].cumsum()
        daily[["_pr", "_pn"]] = daily[["_cr", "_cn"]] - daily[["_r", "_n"]].values
        m = df[[key, "date"]].merge(
            daily[[key, "date", "_pr", "_pn"]], on=[key, "date"], how="left"
        )
        df[name] = (m["_pr"] / (m["_pn"] + SHRINK[name])).fillna(0.0).to_numpy()
    return df.drop(columns=["_r", "_n"])


def feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    rid = race_id(df)
    x = pd.DataFrame(index=df.index)
    x["barrier_frac"] = (df["barrier"] / df["field_size"]).fillna(0.5) - 0.5
    for src, dst in [("weight_kg", "wt_diff"), ("rating", "rating_diff")]:
        v = pd.to_numeric(df[src], errors="coerce")
        d = v - v.groupby(rid).transform("mean")
        x[dst] = d.fillna(0.0)
    x["age_c"] = (pd.to_numeric(df["age"], errors="coerce") - 4).fillna(0.0)
    x["gelding"] = (df["sex"] == "Gelding").astype(float)
    x["mare"] = df["sex"].isin(["Mare", "Filly"]).astype(float)
    for c in ["jockey_resid", "trainer_resid", "horse_resid"]:
        x[c] = df[c]
    return x[FEATURES]


class FeatureModel:
    """Conditional logit on top of log market probability."""

    def __init__(self, l2: float = 50.0):
        self.l2, self.alpha, self.beta, self.mu, self.sd = (
            l2,
            1.0,
            np.zeros(len(FEATURES)),
            None,
            None,
        )

    def _prep(self, df, q):
        x = feature_frame(df).to_numpy(float)
        return (x - self.mu) / self.sd, np.log(q.to_numpy(float))

    def fit(self, df: pd.DataFrame, q: pd.Series):
        m = q.notna().to_numpy()
        d, q = df[m].reset_index(drop=True), q[m].reset_index(drop=True)
        x = feature_frame(d).to_numpy(float)
        self.mu, self.sd = x.mean(0), x.std(0) + 1e-9
        xs, lq = (x - self.mu) / self.sd, np.log(q.to_numpy(float))
        rid = pd.factorize(race_id(d))[0]
        starts = np.flatnonzero(np.r_[True, rid[1:] != rid[:-1]])
        win = d["win"].to_numpy(float)
        # one winner per race for fitting: use the first winner row of each race
        first = np.zeros(len(d), bool)
        wi = np.flatnonzero(win == 1)
        first[wi[np.unique(rid[wi], return_index=True)[1]]] = True
        k = len(FEATURES)

        def fg(theta):
            a, b = theta[0], theta[1:]
            u = a * lq + xs @ b
            mx = np.maximum.reduceat(u, starts)
            e = np.exp(u - np.repeat(mx, np.diff(np.r_[starts, len(u)])))
            z = np.add.reduceat(e, starts)
            p = e / np.repeat(z, np.diff(np.r_[starts, len(u)]))
            ll = -(np.log(p[first].clip(1e-12))).sum() + 0.5 * self.l2 * (b @ b)
            r = p - first
            g = np.r_[(r * lq).sum(), xs.T @ r + self.l2 * b]
            return ll, g

        res = minimize(fg, np.r_[1.0, np.zeros(k)], jac=True, method="L-BFGS-B")
        self.alpha, self.beta = float(res.x[0]), res.x[1:]
        return self

    def predict(self, df: pd.DataFrame, q: pd.Series) -> pd.Series:
        xs, lq = self._prep(df, q.fillna(0.5))
        u = self.alpha * lq + xs @ self.beta
        s = pd.Series(np.exp(u - u.max()), index=df.index)
        p = s / s.groupby(race_id(df)).transform("sum")
        return p.where(q.notna())

    def to_json(self) -> dict:
        return {
            "alpha": self.alpha,
            "l2": self.l2,
            "features": FEATURES,
            "mean": self.mu.tolist(),
            "sd": self.sd.tolist(),
            "beta": self.beta.tolist(),
            "shrink": SHRINK,
        }


def race_logloss(p: pd.Series, df: pd.DataFrame) -> pd.DataFrame:
    """Per-race -log p(winner), one row per single-winner race with complete p."""
    rid = race_id(df)
    w = df.assign(_p=p, _rid=rid)
    w = w[w["_p"].notna()]
    nw = w.groupby("_rid")["win"].transform("sum")
    w = w[(w["win"] == 1) & (nw == 1)]
    return pd.DataFrame(
        {
            "race": w["_rid"].to_numpy(),
            "date": w["date"].to_numpy(),
            "ll": -np.log(w["_p"].clip(1e-9)).to_numpy(),
        }
    )


def save_json(obj: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(
            obj,
            f,
            indent=1,
            default=lambda o: None if (isinstance(o, float) and math.isnan(o)) else float(o),
        )
