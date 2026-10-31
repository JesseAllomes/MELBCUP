"""Feature families and the penalised conditional logit used in every step. alpha*log(M_T) is a fixed-per-fit offset (alpha fitted
on the training rows of each fit); family weights are ridge-penalised (lambda) on features standardised with the training rows only."""
import numpy as np
import pandas as pd
import lm_lib as L

# family -> list of (column, kind): z = standardise on training rows, f = 0/1 flag. Every family also gets an any-missing flag.
FAMS = {
    "MOVE":    [("sa_c", "z"), ("sb_c", "z"), ("sc_c", "z"), ("mO_pos", "z"), ("mO_neg", "z"), ("mO_x_logM", "z")],   # open->-60, -60->-15, -15->T, firm/drift split, move x price
    "SPREAD":  [("f11_sb_lb", "z"), ("f11_abs", "z")],                                                               # Sportsbet vs Ladbrokes chance
    "F1_SECT": [("f1_last", "z"), ("f1_avg3", "z"), ("f1_gap", "z")],                                                # closing sectionals
    "F2_GROUND": [("f2_last", "z"), ("f2_avg3", "z")],                                                               # ground made from 800m
    "F3_EXCUSE": [("f3_count3", "z"), ("f3_any", "f")],                                                              # stewards: excuses
    "F4_BAD":  [("f4_bad", "f")],                                                                                    # stewards: bad signs
    "F5_WIDE": [("f5_avg3", "z")],                                                                                   # distance travelled over race distance
    "F6_SPEED": [("f6_last", "z"), ("f6_avg3", "z")],                                                                # top speed
    "F7_PACE": [("f7_style", "z"), ("f7_fit", "z")],                                                                 # running style x race pace
    "F12_FAV": [("f12_fav", "f"), ("f12_gap", "z")],                                                                 # favourite and gap
    "JOCKEY":  [("f13_jockey", "z"), ("f13_change", "z"), ("jk90_ae", "z")],
    "TRAINER": [("f14_14d", "z"), ("f14_365d", "z"), ("tr90_ae", "z")],
    "PAIR":    [("f15_pair", "z")],
    "RATING_CLASS": [("f16_dr", "z"), ("handicap_rating_rel", "z"), ("chg_class_level", "z")],
    "TRACK_DIST": [("f17_newdist", "f"), ("f17_newtrack", "f"), ("chg_distance_m", "z")],
    "BARRIER": [("f18_cell", "z"), ("barrier_rel", "z")],
    "MARGIN":  [("ls_margin_cap", "z"), ("ls_finish_pct", "z"), ("last3_avg_finish_pct", "z")],
    "FRESH":   [("log_days", "z"), ("first_up", "f"), ("second_up", "f")],
    "WEIGHT":  [("weight_kg_rel", "z"), ("chg_weight_kg", "z")],
    "FORM_PRICE": [("ls_sp_p", "z"), ("last3_avg_sp_p", "z")],
}


def prepare(d):
    """add derived columns that depend only on the row's own race and T (no outcomes)."""
    d = d.copy()
    d["mO_pos"] = d["mO_c"].clip(lower=0); d["mO_neg"] = d["mO_c"].clip(upper=0)
    d["mO_x_logM"] = d["mO_c"] * d["logM"]
    # F7 fit and F12 gap as in research/analysis/screen.py, but with race-level pieces standardised later (here: raw products)
    d["f7_fit"] = np.nan
    d["f12_gap"] = d["f12_G"] * d["f12_fav"].astype(float)
    return d


class Spec:
    def __init__(self, fams):
        self.fams = list(fams)

    def fit_scalers(self, tr):
        sc = {}
        for f in self.fams:
            for c, k in FAMS[f]:
                if k == "z" and c != "f7_fit":
                    v = tr[c].astype(float); sc[c] = (v.mean(), v.std(ddof=0))
        L7 = tr.groupby("race_id")["f7_L"].first().astype(float)
        sc["f7_L"] = (L7.mean(), L7.std(ddof=0))
        sc["f7_style"] = (tr["f7_style"].astype(float).mean(), tr["f7_style"].astype(float).std(ddof=0))
        return sc

    def design(self, d, sc):
        cols = []
        z = lambda v, ms: np.zeros(len(v)) if not ms[1] or not np.isfinite(ms[1]) else ((v.astype(float) - ms[0]) / ms[1]).fillna(0.0).to_numpy()
        for f in self.fams:
            miss = np.zeros(len(d), bool)
            for c, k in FAMS[f]:
                if c == "f7_fit":
                    zs = z(d["f7_style"], sc["f7_style"]); zl = z(d["f7_L"], sc["f7_L"])
                    cols.append(zs * zl); miss |= d["f7_style"].isna().to_numpy()
                elif k == "z":
                    cols.append(z(d[c], sc[c])); miss |= d[c].isna().to_numpy()
                else:
                    cols.append(d[c].astype(float).fillna(0.0).to_numpy()); miss |= d[c].isna().to_numpy()
            cols.append(miss.astype(float))
        return np.column_stack(cols) if cols else np.zeros((len(d), 0))

    def fit(self, tr, lam):
        """returns dict(alpha, sc, w, keep)."""
        rc = L.Races(tr["race_id"], tr["won"], tr["logM"])
        a = L.fit_alpha(rc)
        sc = self.fit_scalers(tr)
        X = self.design(tr, sc)
        keep = X.std(0) > 0
        w = L.newton(rc, X * keep, a * rc.off, lam, keep) * keep if X.shape[1] else np.zeros(0)
        return dict(alpha=a, sc=sc, w=w, keep=keep)

    def eta(self, m, d):
        X = self.design(d, m["sc"]) * m["keep"]
        return m["alpha"] * d["logM"].to_numpy() + (X @ m["w"] if X.shape[1] else 0.0)


def probs_from_eta(d, eta):
    rc = L.Races(d["race_id"], d["won"], d["logM"])
    return rc.probs(eta)


def ll_by_race(d, eta):
    rc = L.Races(d["race_id"], d["won"], d["logM"])
    return rc.race_ll(eta), rc


def load_T(T, start, end):
    """per-T runner table for races dated start..end (inclusive), derived columns added."""
    d = pd.read_pickle(f"{L.LM}/prep/runners_T{T}.pkl")
    d = d[(d["date"] >= start) & (d["date"] <= end)].copy()
    for c in ("f12_fav", "f3_any", "f4_bad", "f17_newdist", "f17_newtrack"):
        d[c] = d[c].astype("float64")
    return prepare(d).reset_index(drop=True)


def dump_model(m, fams, lam):
    return dict(fams=list(fams), lam=lam, alpha=m["alpha"], sc={k: [float(v[0]), float(v[1])] for k, v in m["sc"].items()},
                w=[float(x) for x in m["w"]], keep=[bool(x) for x in m["keep"]])


def load_model(j):
    return Spec(j["fams"]), dict(alpha=j["alpha"], sc={k: tuple(v) for k, v in j["sc"].items()}, w=np.array(j["w"]), keep=np.array(j["keep"]))
