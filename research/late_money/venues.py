"""Venue comparison (NOT a selection test): the same bets settled at Sportsbet, Ladbrokes, the better of the two, the final tote dividend (V) and
Betfair SP (5% and 8% commission), for four bet sets, win and place, and the all-runner take of each venue. All blocks pooled, T-2 eligible races,
rules exactly as frozen (frozen.json, sha256 b94503d7...). Real archive data only."""
import json, os, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lm_lib as L, lm_model as M, bets as B

OUT = f"{L.LM}/out"
F = json.load(open(f"{OUT}/frozen.json"))
spec, model = M.load_model(F["models"]["T2_p_MS"])
ALPHA = model["alpha"]

# ---------------------------------------------------------------- base table, all blocks at T-2
cols = ["race_id", "entry_no", "final_V", "final_BTOTE"]
tote = pd.concat([pd.read_pickle(f"{L.OUT}/runners.pkl.gz")[cols], pd.read_pickle(f"{L.OUT}/runners_excluded.pkl.gz")[cols]])
tote["entry_no"] = pd.to_numeric(tote["entry_no"]); tote = tote.drop_duplicates(["race_id", "entry_no"])
bf = pd.read_pickle(f"{L.LM}/prep/betfair.pkl")
import bf_match
parts = []
for lab, (a, b, suf) in {"dev": ("2023-01-01", "2025-12-31", ""), "tune2": ("2026-01-01", "2026-04-30", ""), "final": ("2026-05-01", "2026-09-28", ""), "examined": ("2026-09-29", "2026-10-29", "_fwd")}.items():
    d = M.load_T(2, a, b, suf)
    rc = L.Races(d["race_id"], d["won"], d["logM"])
    d["p_raw"] = d["M"]; d["p0"] = rc.probs(ALPHA * d["logM"].to_numpy()); d["p_MS"] = rc.probs(spec.eta(model, d))
    d["blk"] = lab; parts.append(d)
D = pd.concat(parts, ignore_index=True)
D["entry_no"] = pd.to_numeric(D["entry_no"])
D = D.merge(tote, on=["race_id", "entry_no"], how="left")
D["dstr"] = D["date"].dt.strftime("%Y-%m-%d")
D["venue"] = D["venue"].astype(str)
mp = bf_match.build_map(D); print("Betfair race matching:", mp["how"].value_counts().to_dict())
D = D.merge(mp[["race_id", "bf_venue"]], on="race_id", how="left")
D = D.merge(bf.rename(columns={"date": "dstr", "venue": "bf_venue"})[["dstr", "bf_venue", "race_number", "entry_no", "bf_win", "bf_place", "bf_win_res", "bf_place_res"]], on=["dstr", "bf_venue", "race_number", "entry_no"], how="left")
D = D.sort_values(["date", "race_id", "entry_no"]).reset_index(drop=True)
D["q_best"] = np.fmax(D["q_sb"], D["q_lb"]); D["pl_best"] = np.fmax(D["sb_place"], D["lb_place"])
D["k"] = np.where(D["n_starters"] >= 8, 3, np.where(D["n_starters"] >= 5, 2, 0))
D["placed"] = (D["finish_pos"] <= D["places_paid"].where(D["places_paid"] > 0, D["k"])) & (D["finish_pos"].notna())
bfrace = D.groupby("race_id")["bf_win"].transform(lambda s: s.notna().all())
print(f"{D['race_id'].nunique()} races, {len(D)} runners; Betfair matched on {D['bf_win'].notna().mean():.3f} of runners; by block", D.groupby("blk")["bf_win"].apply(lambda s: round(s.notna().mean(), 3)).to_dict())


# ---------------------------------------------------------------- settlement
def win_profit(d, venue):
    won = d["won"].to_numpy()
    if venue in ("SB", "LB", "BEST", "TOTE"):
        q = d[{"SB": "q_sb", "LB": "q_lb", "BEST": "q_best", "TOTE": "final_V"}[venue]].to_numpy()
        return np.where(won, q - 1.0, -1.0), np.isfinite(q)
    c = {"BF5": 0.05, "BF8": 0.08}[venue]; q = d["bf_win"].to_numpy()
    return np.where(won, (q - 1.0) * (1 - c), -1.0), np.isfinite(q)


def place_profit(d, venue):
    pl = d["placed"].to_numpy()
    if venue in ("SB", "LB", "BEST", "TOTE"):
        q = d[{"SB": "sb_place", "LB": "lb_place", "BEST": "pl_best", "TOTE": "v_place"}[venue]].to_numpy()
        return np.where(pl, q - 1.0, -1.0), np.isfinite(q) & (d["k"].to_numpy() > 0)
    c = {"BF5": 0.05, "BF8": 0.08}[venue]; q = d["bf_place"].to_numpy(); r = (d["bf_place_res"] == "WINNER").to_numpy()
    return np.where(r, (q - 1.0) * (1 - c), -1.0), np.isfinite(q)


def boot_mean(day, x, n=2000, seed=3):
    """mean of x per row (ROI per unit staked); day-cluster bootstrap over the days present."""
    u, inv = np.unique(day, return_inverse=True)
    S = np.zeros((len(u), 2)); np.add.at(S, inv, np.c_[x, np.ones(len(x))])
    rng = np.random.default_rng(seed); k = len(u)
    idx = rng.integers(0, k, (n, k)); tot = S[idx].sum(1)
    est = x.mean(); ci = np.quantile(tot[:, 0] / tot[:, 1], [0.025, 0.975])
    return float(est), [float(ci[0]), float(ci[1])]


VEN = ("SB", "LB", "BEST", "TOTE", "BF5", "BF8")
NAMES = dict(SB="Sportsbet T-2", LB="Ladbrokes T-2", BEST="better of SB/LB", TOTE="tote final (V)", BF5="Betfair SP -5%", BF8="Betfair SP -8%")


def table(d, fn):
    """per venue: bets priced, coverage, ROI [CI] on the bets that venue priced; paired diff vs Sportsbet on bets both priced."""
    res = {}; psb, oksb = fn(d, "SB"); day = d["day"].to_numpy()
    for v in VEN:
        p, ok = fn(d, v); r = dict(bets=int(len(d)), priced=int(ok.sum()), coverage=float(ok.mean()))
        if ok.sum() >= 2:
            r["roi"], r["ci"] = boot_mean(day[ok], p[ok])
            both = ok & oksb
            if v != "SB" and both.sum() >= 2:
                r["diff_vs_sb"], r["diff_ci"] = boot_mean(day[both], p[both] - psb[both]); r["paired_n"] = int(both.sum())
            r["wins"] = int((p[ok] > -1).sum())
        res[v] = r
    return res


sets = {}
O = D
sets["1 current agreed rule"] = B.win_rule(O, "p_raw", 0.05, 0.0, topk=4)
sets["2 price^1.14 chance, edge 5%"] = B.win_rule(O, "p0", 0.05, 0.0, topk=4)
sets["3 frozen m8 win rule"] = B.win_rule(O, "p_MS", 0.02, 0.10)
fav = O[O.groupby("race_id")["M"].rank(ascending=False, method="first") == 1]
sets["4 back the T-2 favourite"] = fav
res = {"alpha": ALPHA, "races": int(D["race_id"].nunique()), "runners": int(len(D)), "sets": {}}
for name, b in sets.items():
    r = dict(bets=int(len(b)), by_block=b["blk"].value_counts().to_dict(), win=table(b, win_profit), place=table(b, place_profit))
    res["sets"][name] = r
    print("==", name, r["bets"], r["by_block"])
    for kind in ("win", "place"):
        for v, x in r[kind].items():
            if "roi" in x:
                print(f"   {kind:5s} {NAMES[v]:18s} priced {x['priced']:6d} ({x['coverage']:.0%}) ROI {100*x['roi']:+6.1f}% [{100*x['ci'][0]:+.1f}, {100*x['ci'][1]:+.1f}]"
                      + (f"  diff vs SB {100*x['diff_vs_sb']:+.1f}pt [{100*x['diff_ci'][0]:+.1f}, {100*x['diff_ci'][1]:+.1f}] n={x['paired_n']}" if "diff_vs_sb" in x else ""))

# ---------------------------------------------------------------- effective take: every runner, one unit each, common sample (all venues priced)
tk = {}
for kind, fn in (("win", win_profit), ("place", place_profit)):
    prof = {v: fn(D, v) for v in VEN}
    common = np.logical_and.reduce([prof[v][1] for v in VEN])
    day = D["day"].to_numpy()[common]
    tk[kind] = dict(n_common=int(common.sum()), coverage={v: float(prof[v][1].mean()) for v in VEN})
    for v in VEN:
        e, ci = boot_mean(day, prof[v][0][common], n=500); tk[kind][v] = dict(roi=e, ci=ci)
    print(kind, "all-runner take (common sample", int(common.sum()), "runners):", {v: round(100 * tk[kind][v]["roi"], 1) for v in VEN}, "coverage", {v: round(tk[kind]["coverage"][v], 3) for v in VEN})
res["take"] = tk
# sensitivity: best-of-tote (BTOTE) and per-block take of Sportsbet for the frozen rule
b3 = sets["3 frozen m8 win rule"]
res["btote_sensitivity_all_runner_win"] = float(np.where(D["won"], D["final_BTOTE"] - 1, -1.0)[D["final_BTOTE"].notna()].mean())
res["rule3_by_block_sb"] = {k: dict(bets=int(len(g)), roi=float(win_profit(g, "SB")[0].mean())) for k, g in b3.groupby("blk")}
json.dump(res, open(f"{OUT}/venues.json", "w"), indent=1, default=float)
print(res["rule3_by_block_sb"], res["btote_sensitivity_all_runner_win"])
