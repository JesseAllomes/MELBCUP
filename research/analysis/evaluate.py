"""Protocol v1: fit a model on given blocks, predict P over U at T-30, and score claims A, B, C with the
race-day bootstrap (section 6). Never touches blocks final / excluded / history_only for outcomes."""
import json
import numpy as np
import pandas as pd
import screen as S

ALLOWED = {"train", "tune1", "tune2"}
SEED, NBOOT = 20261031, 10000


def load_u(blocks):
    assert set(blocks) <= ALLOWED, blocks
    cols = ["race_id", "date", "mel_date", "block", "starter", "inU_t30", "won", "M_t30", "fav_M_t30", "sb_t30", "lb_t30",
            "barrier", "f7_L", "f12_G"]
    for c, fl in S.FAMILIES.values():
        cols += c + fl
    cols += list(S.MISS.values())
    df = pd.read_pickle(f"{S.DATA}/out/runners.pkl.gz")[cols]
    df = df[df["block"].astype(str).isin(blocks) & df["inU_t30"].astype(bool)].copy()
    st = pd.read_pickle(f"{S.DATA}/out/races.pkl.gz").set_index("race_id")["scoring_status_t30"]
    df["scoring_status_t30"] = df["race_id"].map(st)
    df["won"] = df["won"].fillna(False).astype(bool)
    df["starter"] = df["starter"].astype(bool)
    df["logM"] = np.log(df["M_t30"])
    return df.sort_values(["date", "race_id"]).reset_index(drop=True)


def train_rows(d):
    """training likelihood rows: scored races, starters only, exactly one winner."""
    d = d[d["scoring_status_t30"].isin(["ok", "late_scratching"]) & d["starter"]]
    d = d[d.groupby("race_id")["won"].transform("sum") == 1]
    return d.reset_index(drop=True)


def fit(d, fams, lam):
    tr = train_rows(d)
    rc = S.Races(tr)
    a = S.fit_alpha(rc)
    sc = S.fit_scalers(tr)
    X, names = S.design(tr, fams, sc)
    keep = X.std(0) > 0
    X = X * keep
    w = (S.newton(rc, X, a * rc.logM, lam, keep) * keep) if X.shape[1] else np.zeros(0)
    return dict(alpha=a, fams=list(fams), lam=lam, scalers={k: [float(v[0]), float(v[1])] for k, v in sc.items()},
                names=names, w=w.tolist(), n_train_races=rc.R)


def predict(m, d):
    """P and normalised M^alpha over U (all rows of d), per race."""
    sc = {k: tuple(v) for k, v in m["scalers"].items()}
    X, _ = S.design(d, m["fams"], sc)
    eta0 = m["alpha"] * d["logM"].to_numpy()
    eta = eta0 + (X @ np.array(m["w"]) if X.shape[1] else 0)
    rc = S.Races(d)
    return rc.probs(eta), rc.probs(eta0), rc.probs(d["logM"].to_numpy())


def boot(day, num, den, level):
    g = pd.DataFrame(dict(day=day, num=num, den=den)).groupby("day").sum()
    n, dn = g["num"].to_numpy(), g["den"].to_numpy()
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(g), size=(NBOOT, len(g)))
    stat = n[idx].sum(1) / dn[idx].sum(1)
    q = (1 - level) / 2
    return float(n.sum() / dn.sum()), float(np.quantile(stat, q)), float(np.quantile(stat, 1 - q)), int(len(g))


def verdict(lo, hi, claim):
    if claim == "A" or claim == "C":
        return "pass" if lo > 0 else ("fail" if hi <= 0 else "inconclusive")
    return "pass" if lo > 0 else ("fail" if hi <= 0 else "inconclusive")


def claims(d, P, Ma, Mraw, level):
    d = d.assign(P=P, Ma=Ma, Mraw=Mraw)
    rid = d["race_id"]
    out = {}
    nws = d.groupby("race_id")["won"].transform("sum")
    dns = (~d["starter"]).groupby(rid).transform("any")          # a runner in U did not start
    status = d["scoring_status_t30"]
    resulted = status.isin(["ok", "late_scratching", "dead_heat"])
    # ---- A: renormalise over starters; dead heats / no result excluded
    sA = d[status.isin(["ok", "late_scratching"]) & (nws == 1) & d["starter"]].copy()
    for c in ("P", "Ma", "Mraw"):
        sA[c] = sA[c] / sA.groupby("race_id")[c].transform("sum")
    wA = sA[sA["won"]]
    diff = -np.log(wA["Ma"]) + np.log(wA["P"])
    est, lo, hi, nd = boot(wA["mel_date"].to_numpy(), diff.to_numpy(), np.ones(len(wA)), level)
    raw = float((-np.log(wA["Mraw"]) + np.log(wA["Ma"])).mean())
    rr = boot(wA["mel_date"].to_numpy(), (-np.log(wA["Mraw"]) + np.log(wA["Ma"])).to_numpy(), np.ones(len(wA)), level)
    y = sA["won"].astype(float)
    brier = {c: float(((sA[c] - y) ** 2).groupby(sA["race_id"]).sum().mean()) for c in ("P", "Ma", "Mraw")}
    out["A"] = dict(races=len(wA), days=nd, mean_ll_gain=est, lo=lo, hi=hi, verdict=verdict(lo, hi, "A"),
                    logloss_P=float(-np.log(wA["P"]).mean()), logloss_Malpha=float(-np.log(wA["Ma"]).mean()),
                    logloss_raw=float(-np.log(wA["Mraw"]).mean()), malpha_gain_over_raw=raw, malpha_gain_over_raw_lo=rr[1], malpha_gain_over_raw_hi=rr[2],
                    brier_P=brier["P"], brier_Malpha=brier["Ma"], brier_raw=brier["Mraw"])
    # ---- B
    q = np.fmax(d["sb_t30"], d["lb_t30"])
    bet = (d["P"] * q - 1 >= 0.05) & (d["P"] >= 0.04) & (q <= 21)
    elig = resulted & (nws >= 1)
    bets = d[bet & elig].assign(q=q[bet & elig])
    excl = bets[(~bets["starter"]) | dns[bets.index]]             # races with a late scratching: excluded, published
    kb = bets.drop(excl.index)
    k = nws[kb.index]                                            # dead heat: all race winners, not just backed ones (fixed in amendment B)
    ret = np.where(kb["won"], kb["q"] / k, 0.0) - 1.0
    if len(kb):
        est, lo, hi, nd = boot(kb["mel_date"].to_numpy(), ret, np.ones(len(kb)), level)
    else:
        est = lo = hi = np.nan; nd = 0
    out["B"] = dict(bets=len(kb), races_with_bets=int(kb["race_id"].nunique()), days=nd, roi=est, lo=lo, hi=hi,
                    verdict=verdict(lo, hi, "B") if len(kb) else "inconclusive",
                    excluded_late_scratch_bets=len(excl), mean_price=float(kb["q"].mean()) if len(kb) else None,
                    strike=float(kb["won"].mean()) if len(kb) else None)
    # ---- C
    fav = d["fav_M_t30"].fillna(False).astype(bool)
    ratio = d["P"] / d["Ma"]
    cand = d[~fav & (d["P"] >= 0.10)].assign(ratio=ratio[~fav & (d["P"] >= 0.10)])
    nom = cand.sort_values(["race_id", "ratio"], ascending=[True, False]).drop_duplicates("race_id")
    nom = nom[nom["ratio"] >= 1.25]
    nf = d[~fav].assign(_negM=-d.loc[~fav, "M_t30"])
    bench = nf.sort_values(["race_id", "_negM", "barrier"]).drop_duplicates("race_id").set_index("race_id")
    nom = nom.set_index("race_id")
    b = bench.reindex(nom.index)
    st_ = status.groupby(rid).first().reindex(nom.index)
    nw_ = nws.groupby(rid).first().reindex(nom.index)
    scored = st_.isin(["ok", "late_scratching"]) & (nw_ == 1)
    void_nom = ~nom["starter"]
    void_bench = ~b["starter"].astype(bool)
    ok = scored & ~void_nom & ~void_bench
    dC = nom["won"].astype(float) - b["won"].astype(float)
    dC = dC[ok]
    if len(dC):
        est, lo, hi, nd = boot(nom.loc[ok, "mel_date"].to_numpy(), dC.to_numpy(), np.ones(len(dC)), level)
    else:
        est = lo = hi = np.nan; nd = 0
    qn = np.fmax(nom["sb_t30"], nom["lb_t30"])[ok]
    out["C"] = dict(nominations=int(ok.sum()), days=nd, mean_diff=est, lo=lo, hi=hi,
                    verdict=verdict(lo, hi, "C") if len(dC) else "inconclusive",
                    void_nominee=int((scored & void_nom).sum()), void_benchmark=int((scored & ~void_nom & void_bench).sum()),
                    nominee_strike=float(nom.loc[ok, "won"].mean()) if ok.any() else None,
                    benchmark_strike=float(b.loc[ok, "won"].astype(float).mean()) if ok.any() else None,
                    nominee_is_benchmark=int((nom.loc[ok, "M_t30"] == b.loc[ok, "M_t30"]).sum()),
                    nominee_roi=float((np.where(nom.loc[ok, "won"], qn, 0) - 1).mean()) if ok.any() else None)
    out["eligible_races"] = int(d["race_id"].nunique())
    return out
