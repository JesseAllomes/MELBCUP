"""Step 3 (development only): for T in -10, -5, -2, screen each family's incremental out-of-fold log-loss gain over the T consensus,
then fit the combined models. Eight expanding-window quarterly folds, 2024Q1 to 2025Q4, all inside train + tune1.
Writes $LM_DIR/out/screen_T{T}.json and OOF predictions $LM_DIR/out/oof_T{T}.pkl. Never touches tune2 (2026) or final."""
import json, os, pickle, sys, time
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lm_lib as L, lm_model as M

LAMS = (0.1, 0.3, 1, 3, 10, 30)


def load(T):
    d = pd.read_pickle(f"{L.LM}/prep/runners_T{T}.pkl")
    d = d[(d["date"] >= L.DEV_START) & (d["date"] <= L.DEV_END)].copy()
    d["f12_fav"] = d["f12_fav"].astype("float64")
    d["f3_any"] = d["f3_any"].astype("float64"); d["f4_bad"] = d["f4_bad"].astype("float64")
    d["f17_newdist"] = d["f17_newdist"].astype("float64"); d["f17_newtrack"] = d["f17_newtrack"].astype("float64")
    return M.prepare(d).reset_index(drop=True)


def folds(d):
    out = []
    for a, b in L.FOLDS:
        tr = d[(d["date"] >= L.DEV_START) & (d["date"] < a)]; va = d[(d["date"] >= a) & (d["date"] <= b)]
        out.append((tr, va))
    return out


def oof(d, fams, lam, F):
    """out-of-fold eta for rows of the validation folds, in order; plus per-fold per-race ll."""
    etas, lls = [], []
    for tr, va in F:
        spec = M.Spec(fams); m = spec.fit(tr, lam)
        e = spec.eta(m, va); etas.append(e)
        lls.append(M.ll_by_race(va, e)[0])
    return etas, lls


def main(T):
    t0 = time.time()
    d = load(T); F = folds(d)
    print(f"T-{T}: dev {d['race_id'].nunique()} races; validation races {sum(v['race_id'].nunique() for _, v in F)}", flush=True)
    base_e, base_ll = oof(d, [], 0.0, F)
    rows = []
    for fam in M.FAMS:
        e, ll = oof(d, [fam], 3.0, F)
        g = [(b - a).mean() for a, b in zip(ll, base_ll)]                       # per-fold mean per-race gain (nats)
        rows.append(dict(family=fam, folds_better=int(sum(x > 0 for x in g)), mean_gain_millinats=1000 * float(np.mean(g)), min=1000 * min(g), max=1000 * max(g)))
        print(f"  {fam:12s} {rows[-1]['mean_gain_millinats']:+.3f} mn, better in {rows[-1]['folds_better']}/8", flush=True)
    S = pd.DataFrame(rows)
    S["kept"] = (S["folds_better"] >= 5) & (S["mean_gain_millinats"] > 0)
    kept = S.loc[S["kept"], "family"].tolist()
    res = dict(T=T, screen=S.round(4).to_dict("records"), kept=kept)
    cand = {"MS": ["MOVE", "SPREAD"], "ALL": sorted(set(kept) | {"MOVE", "SPREAD"}, key=list(M.FAMS).index)}
    if kept:
        cand["KEPT"] = kept
    models = {}
    for name, fams in cand.items():
        best = None
        for lam in LAMS:
            e, ll = oof(d, fams, lam, F)
            g = float(np.mean([np.concatenate(ll)]) - 0) if False else float(np.concatenate(ll).mean() - np.concatenate(base_ll).mean())
            if best is None or g > best[0]:
                best = (g, lam, e, ll)
        g, lam, e, ll = best
        folds_better = int(sum((b - a).mean() > 0 for a, b in zip(base_ll, ll)))
        models[name] = dict(fams=fams, lam=lam, gain_millinats=1000 * g, folds_better=folds_better, eta=np.concatenate(e), ll=np.concatenate(ll))
        print(f"  model {name:5s} lam={lam} gain {1000*g:+.3f} mn/race, folds better {folds_better}/8; fams={fams}", flush=True)
        res[f"model_{name}"] = dict(fams=fams, lam=lam, gain_millinats=1000 * g, folds_better=folds_better)
    va = pd.concat([v for _, v in F])
    keep_cols = ["race_id", "day", "date", "block", "entry_no", "won", "M", "logM", "q_sb", "q_lb", "sb_place", "lb_place", "mO", "m60", "m15", "sa", "sb", "sc",
                 "n_starters", "places_paid", "distance_m", "group", "venue", "finish_pos", "sb_t0", "sp", "mO_c", "sc_c"]
    O = va[keep_cols].reset_index(drop=True)
    O["eta0"] = np.concatenate(base_e)
    for k, m in models.items():
        O[f"eta_{k}"] = m["eta"]
    rc = L.Races(O["race_id"], O["won"], O["logM"])
    O["p_raw"] = O["M"]; O["p0"] = rc.probs(O["eta0"].to_numpy())
    for k in models:
        O[f"p_{k}"] = rc.probs(O[f"eta_{k}"].to_numpy())
    O.to_pickle(f"{L.LM}/out/oof_T{T}.pkl")
    json.dump(res, open(f"{L.LM}/out/screen_T{T}.json", "w"), indent=1)
    print(f"T-{T} done in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]))
