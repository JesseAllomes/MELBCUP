"""Late-money study: shared code (conditional logit, features, Plackett-Luce chances, settlement, day bootstrap).
numpy/pandas only. Nothing here reads outcomes of a block by itself; the callers choose blocks."""
import itertools, os
import numpy as np
import pandas as pd

LM = os.environ.get("LM_DIR", "/tmp/claude-0/-home-user/418442d0-6a93-5b3f-a291-37c2b3744726/scratchpad/lm")
OUT = f"{LM}/raw/upsets/out"
DEV_START, DEV_END = "2023-01-01", "2025-12-31"          # train + tune1: every tuning decision is made here
TEST_START, TEST_END = "2026-01-01", "2026-04-30"        # tune2: the one test block for this claim (see RERUN.md section 1)
FOLDS = [("2024-01-01", "2024-03-31"), ("2024-04-01", "2024-06-30"), ("2024-07-01", "2024-09-30"), ("2024-10-01", "2024-12-31"),
         ("2025-01-01", "2025-03-31"), ("2025-04-01", "2025-06-30"), ("2025-07-01", "2025-09-30"), ("2025-10-01", "2025-12-31")]
TIMES = (120, 60, 30, 15, 10, 5, 2, 0)

# ------------------------------------------------------------------ conditional logit (softmax within race), Newton + ridge
class Races:
    def __init__(self, race_ids, y, offset):
        rid = np.asarray(race_ids)
        starts = np.r_[0, np.flatnonzero(rid[1:] != rid[:-1]) + 1]
        self.idx = np.repeat(np.arange(len(starts)), np.diff(np.r_[starts, len(rid)]))
        self.R = len(starts)
        self.y = np.asarray(y, float)
        self.off = np.asarray(offset, float)

    def probs(self, eta):
        m = np.full(self.R, -np.inf); np.maximum.at(m, self.idx, eta)
        e = np.exp(eta - m[self.idx]); s = np.bincount(self.idx, e, self.R)
        return e / s[self.idx]

    def race_ll(self, eta):                      # per-race log-likelihood of the winner
        p = self.probs(eta)
        out = np.zeros(self.R); np.add.at(out, self.idx[self.y == 1], np.log(p[self.y == 1]))
        return out


def newton(rc, X, offset, lam, penal, iters=60):
    k = X.shape[1]; w = np.zeros(k); pen = lam * penal.astype(float)
    obj = lambda w: rc.race_ll(offset + X @ w).mean() - 0.5 * (pen * w * w).sum()
    f = obj(w)
    for _ in range(iters):
        p = rc.probs(offset + X @ w)
        xbar = np.stack([np.bincount(rc.idx, p * X[:, j], rc.R) for j in range(k)], 1)
        g = (X[rc.y == 1].sum(0) - xbar.sum(0)) / rc.R - pen * w
        H = ((X * p[:, None]).T @ X - xbar.T @ xbar) / rc.R + np.diag(pen) + 1e-9 * np.eye(k)
        step = np.linalg.solve(H, g); t = 1.0
        while True:
            wn = w + t * step; fn = obj(wn)
            if fn >= f - 1e-12 or t < 1e-6: break
            t /= 2
        dec = fn - f; w, f = wn, fn
        if abs(dec) < 1e-10: break
    return w


def fit_alpha(rc):
    return float(newton(rc, rc.off[:, None], np.zeros(len(rc.off)), 0.0, np.array([False]))[0])


# ------------------------------------------------------------------ day-level bootstrap
def day_bootstrap(days, values, stat, n=2000, seed=7):
    """days: array of day labels per row; values: 2-D/1-D array of per-row quantities summed by day.
    stat(sums_over_resampled_days) -> float. Resamples DAYS with replacement."""
    days = np.asarray(days); vals = np.asarray(values, float)
    if vals.ndim == 1: vals = vals[:, None]
    u, inv = np.unique(days, return_inverse=True)
    S = np.zeros((len(u), vals.shape[1])); np.add.at(S, inv, vals)
    rng = np.random.default_rng(seed); out = np.empty(n)
    for b in range(n):
        out[b] = stat(S[rng.integers(0, len(u), len(u))].sum(0))
    return stat(S.sum(0)), np.quantile(out, [0.025, 0.975])


# ------------------------------------------------------------------ Plackett-Luce with discounted lower places (as tools/cup_signals.py)
EXPO = (1.0, 0.81, 0.65, 0.65)

def pl_seq(p, seq):
    """probability of the ordered finishing prefix seq (indices) under discounted Plackett-Luce."""
    out = 1.0; used = []
    for k, i in enumerate(seq):
        s = p ** EXPO[k]
        out *= s[i] / (s.sum() - s[used].sum()) if used else s[i] / s.sum()
        used.append(i)
    return out


def place_probs(p, k):
    """P(runner finishes in the first k), k in (2, 3), exact."""
    n = len(p); res = np.zeros(n)
    s1, s2, s3 = p ** EXPO[0], p ** EXPO[1], p ** EXPO[2]
    P1 = s1 / s1.sum()
    P2 = np.zeros(n); P3 = np.zeros(n)
    # P(a first, b second)
    pa = P1[:, None] * (s2[None, :] / (s2.sum() - s2[:, None])); np.fill_diagonal(pa, 0)
    P2 = pa.sum(0)
    if k >= 3 and n >= 3:
        # P(a,b,c) = pa[a,b] * s3[c] / (S3 - s3[a] - s3[b])
        den = s3.sum() - s3[:, None] - s3[None, :]
        w = pa / np.where(den > 0, den, np.inf)                 # (a,b)
        # sum over a,b != c of w[a,b]*s3[c]  == s3[c] * (sum_ab w - sum_{a or b = c})
        tot = w.sum(); rowc = w.sum(1); colc = w.sum(0); diag = np.diag(w)
        P3 = s3 * (tot - rowc - colc + diag)
    return P1 + P2 + (P3 if k >= 3 else 0)


def box_hit(p, top, kind):
    """hit probability of the exotic structure over the runners idx `top` (indices into p)."""
    top = list(top)
    if kind == "quin":      return sum(pl_seq(p, (a, b)) for a, b in itertools.permutations(top, 2))          # either order, all pairs in the set
    if kind == "exacta":    return sum(pl_seq(p, (a, b)) for a, b in itertools.permutations(top, 2))          # all ordered pairs (box)
    if kind == "exacta1":   return pl_seq(p, tuple(top[:2]))
    if kind == "tri":       return sum(pl_seq(p, s) for s in itertools.permutations(top, 3))
    if kind == "ff":        return sum(pl_seq(p, s) for s in itertools.permutations(top, 4))
    raise ValueError(kind)
