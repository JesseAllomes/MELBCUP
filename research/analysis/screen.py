"""Protocol v1 section 5, steps 1-2 on the TRAIN block only: per-family screening over six quarterly
folds (alpha fitted per fold, lambda = 3, keep if validation log-loss beats offset-only in >= 4/6 folds),
then the combined fit of the kept families with lambda chosen from {0.3, 1, 3, 10, 30}.

Conditional logit, alpha*log M as a fixed offset, objective = mean per-race log-likelihood - (lambda/2)|w|^2,
solved by Newton's method. Reads $MELBCUP_DATA/out/runners.pkl.gz; writes $MELBCUP_RESULTS/screen_*.csv."""
import json, os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("MELBCUP_DATA", "")      # dataset folder holding out/ and manifest.json (built by research/dataset/build.py)
if not DATA:
    sys.exit("set MELBCUP_DATA to the dataset folder that holds out/ and manifest.json")
ORIGINAL = f"{HERE}/results"                    # the frozen v1 outputs (amendment A, tune2 look): never written to
RESULTS = os.environ.get("MELBCUP_RESULTS", "")  # where this run writes; must be a new location
if not RESULTS:
    sys.exit("set MELBCUP_RESULTS to the folder this run writes to (not results/, which holds the frozen v1 outputs)")
if os.path.realpath(RESULTS) == os.path.realpath(ORIGINAL):
    sys.exit("refusing to write into results/: it holds the frozen v1 outputs")
os.makedirs(RESULTS, exist_ok=True)


def out_path(name):
    """a new output file in RESULTS; refuses to overwrite anything that exists."""
    p = os.path.join(RESULTS, name)
    if os.path.exists(p):
        sys.exit(f"refusing to overwrite {p}")
    return p

FOLDS = [("2024-01-01", "2024-03-31"), ("2024-04-01", "2024-06-30"), ("2024-07-01", "2024-09-30"),
         ("2024-10-01", "2024-12-31"), ("2025-01-01", "2025-03-31"), ("2025-04-01", "2025-06-30")]
LAMBDAS = (0.3, 1, 3, 10, 30)
SCREEN_LAMBDA = 3.0
# family -> (continuous features, flag features); F7/F12 products built in design()
FAMILIES = {
    "F1": (["f1_last", "f1_avg3", "f1_gap"], []),
    "F2": (["f2_last", "f2_avg3"], []),
    "F3": (["f3_count3"], ["f3_any"]),
    "F4": ([], ["f4_bad"]),
    "F5": (["f5_avg3"], []),
    "F6": (["f6_last", "f6_avg3"], []),
    "F7": (["f7_style"], []),          # + f7_fit
    "F10": (["f10_move"], []),
    "F11": (["f11_sb_lb", "f11_abs"], []),
    "F12": ([], ["f12_fav"]),          # + f12_gap, f12_move
    "F13": (["f13_jockey", "f13_change"], []),
    "F14": (["f14_14d", "f14_365d"], []),
    "F15": (["f15_pair"], []),
    "F16": (["f16_dr"], []),
    "F17": ([], ["f17_newdist", "f17_newtrack"]),
    "F18": (["f18_cell"], []),
}
MISS = {f: f"f{f[1:]}_missing".lower() for f in FAMILIES}


def load(blocks=("train",)):
    cols = ["race_id", "date", "block", "starter", "inU_t30", "won", "M_t30", "f7_L", "f12_G"]
    for c, fl in FAMILIES.values():
        cols += c + fl
    cols += list(MISS.values())
    df = pd.read_pickle(f"{DATA}/out/runners.pkl.gz")[cols]
    st = pd.read_pickle(f"{DATA}/out/races.pkl.gz").set_index("race_id")["scoring_status_t30"]
    df["scoring_status_t30"] = df["race_id"].map(st)
    df = df[df["block"].astype(str).isin(blocks)]
    df = df[df["scoring_status_t30"].isin(["ok", "late_scratching"])]          # dead heats / no result excluded
    df = df[df["starter"].astype(bool) & df["inU_t30"].astype(bool)].copy()     # late scratchings dropped from their race
    df["won"] = df["won"].fillna(False).astype(bool)
    nw = df.groupby("race_id")["won"].transform("sum")
    df = df[nw == 1]
    df = df[df["M_t30"].notna() & (df["M_t30"] > 0)]
    df = df[df.groupby("race_id")["won"].transform("sum") == 1]
    df = df.sort_values(["date", "race_id"]).reset_index(drop=True)
    df["logM"] = np.log(df["M_t30"])
    return df


class Races:
    """rows grouped contiguously by race."""

    def __init__(self, d):
        rid = d["race_id"].to_numpy()
        starts = np.r_[0, np.flatnonzero(rid[1:] != rid[:-1]) + 1]
        self.idx = np.repeat(np.arange(len(starts)), np.diff(np.r_[starts, len(rid)]))
        self.R = len(starts)
        self.y = d["won"].to_numpy().astype(float)
        self.logM = d["logM"].to_numpy()

    def probs(self, eta):
        m = np.full(self.R, -np.inf)
        np.maximum.at(m, self.idx, eta)
        e = np.exp(eta - m[self.idx])
        s = np.bincount(self.idx, e, self.R)
        return e / s[self.idx]

    def logloss(self, eta):
        p = self.probs(eta)
        return -np.log(p[self.y == 1]).mean()


def newton(rc, X, offset, lam, penal, iters=50):
    """maximise mean LL - lam/2 * sum(w[penal]^2)."""
    k = X.shape[1]
    w = np.zeros(k)
    pen = lam * penal.astype(float)

    def obj(w):
        eta = offset + X @ w
        return -rc.logloss(eta) - 0.5 * (pen * w * w).sum()

    f = obj(w)
    for _ in range(iters):
        eta = offset + X @ w
        p = rc.probs(eta)
        xbar = np.stack([np.bincount(rc.idx, p * X[:, j], rc.R) for j in range(k)], 1)
        g = (X[rc.y == 1].sum(0) - xbar.sum(0)) / rc.R - pen * w
        H = (X * p[:, None]).T @ X - xbar.T @ xbar
        H = H / rc.R + np.diag(pen) + 1e-10 * np.eye(k)
        step = np.linalg.solve(H, g)
        t = 1.0
        while True:
            wn = w + t * step
            fn = obj(wn)
            if fn >= f - 1e-12 or t < 1e-6:
                break
            t /= 2
        dec = fn - f
        w, f = wn, fn
        if abs(dec) < 1e-10:
            break
    return w


def fit_alpha(rc):
    X = rc.logM[:, None]
    return float(newton(rc, X, np.zeros(len(X)), 0.0, np.array([False]))[0])


def fit_scalers(tr):
    """fold-train moments: continuous features on training runners; F7 L on training races; F12 on training favourites."""
    sc = {}
    for fam, (cont, _) in FAMILIES.items():
        for c in cont:
            v = tr[c].astype(float)
            sc[c] = (v.mean(), v.std(ddof=0))
    L = tr.groupby("race_id")["f7_L"].first().astype(float)
    sc["f7_L"] = (L.mean(), L.std(ddof=0))
    fav = tr[tr["f12_fav"].fillna(0).astype(float) == 1]
    sc["f12_G"] = (fav["f12_G"].astype(float).mean(), fav["f12_G"].astype(float).std(ddof=0))
    sc["f12_move"] = (fav["f10_move"].astype(float).mean(), fav["f10_move"].astype(float).std(ddof=0))
    return sc


def z(v, ms):
    mu, sd = ms
    if not sd or not np.isfinite(sd):
        return np.zeros(len(v))
    return ((v.astype(float) - mu) / sd).fillna(0.0).to_numpy()


def design(d, fams, sc):
    cols, names = [], []
    for fam in fams:
        cont, flags = FAMILIES[fam]
        for c in cont:
            cols.append(z(d[c], sc[c])); names.append(c)
        for c in flags:
            cols.append(d[c].astype(float).fillna(0.0).to_numpy()); names.append(c)
        if fam == "F7":
            zs = z(d["f7_style"], sc["f7_style"])
            zl = z(d["f7_L"], sc["f7_L"])
            cols.append(zs * zl); names.append("f7_fit")
        if fam == "F12":
            fav = d["f12_fav"].astype(float).fillna(0.0).to_numpy()
            cols.append(fav * z(d["f12_G"], sc["f12_G"])); names.append("f12_gap")
            cols.append(fav * z(d["f10_move"], sc["f12_move"])); names.append("f12_move")
        cols.append(d[MISS[fam]].astype(float).fillna(0.0).to_numpy()); names.append(MISS[fam])
    return np.column_stack(cols) if cols else np.zeros((len(d), 0)), names


def fold_fit(tr, va, fams, lam):
    """returns (alpha, w, names, validation logloss, offset-only validation logloss)."""
    rtr, rva = Races(tr), Races(va)
    a = fit_alpha(rtr)
    sc = fit_scalers(tr)
    Xtr, names = design(tr, fams, sc)
    Xva, _ = design(va, fams, sc)
    keep = Xtr.std(0) > 0                      # a zero-variance column (constant missing flag) is set to 0
    Xtr, Xva = Xtr * keep, Xva * keep
    w = newton(rtr, Xtr, a * rtr.logM, lam, keep) if Xtr.shape[1] else np.zeros(0)
    w = w * keep
    return a, w, names, rva.logloss(a * rva.logM + Xva @ w), rva.logloss(a * rva.logM)


def main():
    df = load()
    print(f"train scored: {df['race_id'].nunique()} races, {len(df)} runners", flush=True)
    folds = []
    for a_, b_ in FOLDS:
        tr = df[(df["date"] >= "2023-01-01") & (df["date"] < a_)]
        va = df[(df["date"] >= a_) & (df["date"] <= b_)]
        folds.append((tr, va))
    rows = []
    for k, (tr, va) in enumerate(folds, 1):
        for fam in FAMILIES:
            a, w, names, ll, ll0 = fold_fit(tr, va, [fam], SCREEN_LAMBDA)
            rows.append(dict(fold=k, family=fam, alpha=a, n_train_races=tr["race_id"].nunique(), n_val_races=va["race_id"].nunique(),
                             val_logloss=ll, val_logloss_offset=ll0, gain=ll0 - ll, weights=json.dumps(dict(zip(names, np.round(w, 4).tolist())))))
        print(f"fold {k} screened (alpha {a:.4f})", flush=True)
    S = pd.DataFrame(rows)
    S.to_csv(out_path("screen_folds.csv"), index=False)
    summ = S.groupby("family").agg(folds_better=("gain", lambda g: int((g > 0).sum())), mean_gain=("gain", "mean"),
                                   min_gain=("gain", "min"), max_gain=("gain", "max")).reset_index()
    summ["kept"] = summ["folds_better"] >= 4
    summ = summ.sort_values("mean_gain", ascending=False)
    summ.to_csv(out_path("screen_summary.csv"), index=False)
    print(summ.to_string(index=False), flush=True)
    kept = summ.loc[summ["kept"], "family"].tolist()
    comb = []
    if kept:
        for lam in LAMBDAS:
            for k, (tr, va) in enumerate(folds, 1):
                a, w, names, ll, ll0 = fold_fit(tr, va, kept, lam)
                comb.append(dict(lam=lam, fold=k, val_logloss=ll, val_logloss_offset=ll0, gain=ll0 - ll))
        C = pd.DataFrame(comb)
        C.to_csv(out_path("combined_folds.csv"), index=False)
        cs = C.groupby("lam").agg(mean_val_logloss=("val_logloss", "mean"), mean_gain=("gain", "mean"),
                                  folds_better=("gain", lambda g: int((g > 0).sum()))).reset_index()
        cs.to_csv(out_path("combined_summary.csv"), index=False)
        print(cs.to_string(index=False))
        best = float(cs.loc[cs["mean_val_logloss"].idxmin(), "lam"])
        print(f"kept {kept}; lambda {best}")
        json.dump(dict(kept=kept, lam=best), open(out_path("selection_train.json"), "w"))
    else:
        json.dump(dict(kept=[], lam=None), open(out_path("selection_train.json"), "w"))
        print("no family kept")


if __name__ == "__main__":
    main()
