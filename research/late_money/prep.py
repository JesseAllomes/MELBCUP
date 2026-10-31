"""Step 1: price paths and per-T runner tables. Reads the build_lm.py output and extras.py output, writes
$LM_DIR/prep/runners_T{T}.pkl (one row per starter of every eligible race) and $LM_DIR/prep/paths.pkl (all runners, price path).
Eligible race at T: in the T-30 eligible sample (protocol feed-liveness etc.), exactly one winner, every runner in the universe U at T
is a starter (no late scratchings or emergencies: those races are skipped, as protocol claim B skips late-scratching races),
both books quote every runner in U at T, and both books were live in [T-15 min, T]."""
import os, pickle, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lm_lib as L

os.makedirs(f"{L.LM}/prep", exist_ok=True)
FAM_COLS = ["f1_last", "f1_avg3", "f1_gap", "f2_last", "f2_avg3", "f3_count3", "f3_any", "f4_bad", "f5_avg3", "f6_last", "f6_avg3",
            "f7_style", "f7_L", "f12_fav", "f12_G", "f13_jockey", "f13_change", "f14_14d", "f14_365d", "f15_pair", "f16_dr",
            "f17_newdist", "f17_newtrack", "f18_cell", "f11_sb_lb", "f11_abs",
            "jk90_ae", "tr90_ae", "jk365_ae", "ls_margin_behind", "ls_finish_pct", "last3_avg_finish_pct", "last3_avg_sp_p", "ls_sp_p",
            "chg_class_level", "chg_distance_m", "chg_weight_kg", "chg_handicap_rating", "days_since_last_run", "runs_in_ds",
            "weight_kg", "handicap_rating", "barrier"]
BASE = ["race_id", "meeting_id", "date", "mel_date", "block", "examined", "horse_code", "entry_no", "starter", "scratched", "finish_pos", "won",
        "sp", "sb_open", "lb_open", "sb_open_min", "lb_open_min", "sb_last_rel_s", "lb_last_rel_s", "sb_final", "lb_final",
        "sb_t60", "lb_t60", "sb_t30", "lb_t30", "sb_t10", "lb_t10", "sb_t5", "lb_t5", "sb_t2", "lb_t2",
        "sb_t10_age_s", "lb_t10_age_s", "sb_t5_age_s", "lb_t5_age_s", "sb_t2_age_s", "lb_t2_age_s", "sb_t30_age_s", "lb_t30_age_s",
        "inU_t30", "M_t30", "M_t10", "M_t2", "venue", "state", "distance_m", "group", "class_cat", "race_number", "start_ts"]
F12X = {"f12_fav": 0}


def main():
    rn = pd.read_pickle(f"{L.OUT}/runners.pkl.gz")[BASE + [c for c in FAM_COLS if c not in BASE]]
    rc = pd.read_pickle(f"{L.OUT}/races.pkl.gz").set_index("race_id")
    rn = rn[rn["race_id"].isin(rc.index)].copy()                               # T-30 eligible sample (build's in_sample)
    ex = pickle.load(open(f"{L.LM}/extras/extras.pkl", "rb"))
    sn = pd.DataFrame(ex["snaps"], columns=ex["snap_cols"])
    sn["entry_no"] = pd.to_numeric(sn["entry_no"])
    pl = pd.DataFrame(ex["place"], columns=["race_id", "entry_no", "sb_place", "lb_place", "v_place", "n_place", "q_place"])
    pl["entry_no"] = pd.to_numeric(pl["entry_no"])
    rn["entry_no"] = pd.to_numeric(rn["entry_no"])
    sn = sn.drop_duplicates(["race_id", "entry_no"]); pl = pl.drop_duplicates(["race_id", "entry_no"])
    rn = rn.merge(sn, on=["race_id", "entry_no"], how="left").merge(pl, on=["race_id", "entry_no"], how="left")
    rn = rn.rename(columns={"sb_t120x": "sb_t120", "lb_t120x": "lb_t120", "sb_t15x": "sb_t15", "lb_t15x": "lb_t15", "sb_t0x": "sb_t0", "lb_t0x": "lb_t0"})
    rn["day"] = rn["mel_date"].dt.strftime("%Y-%m-%d")
    # ---- first-up / second-up (spell = 60+ days): from each horse's own sequence of starts in the dataset
    h = rn[rn["starter"]].sort_values(["horse_code", "date", "race_id"])
    prev_gap = h.groupby("horse_code", observed=True)["days_since_last_run"].shift(1)
    rn["first_up"] = (rn["days_since_last_run"] >= 60).astype(float).where(rn["days_since_last_run"].notna())
    sec = ((prev_gap >= 60) & (h["days_since_last_run"] < 60)).astype(float).where(prev_gap.notna() & h["days_since_last_run"].notna())
    rn["second_up"] = sec.reindex(rn.index)
    rn["log_days"] = np.log1p(rn["days_since_last_run"])
    rn["ls_margin_cap"] = rn["ls_margin_behind"].clip(upper=20)
    for c in ("weight_kg", "handicap_rating"):
        rn[c + "_rel"] = rn[c] - rn[c].where(rn["starter"]).groupby(rn["race_id"]).transform("mean")
    nst = rn["starter"].groupby(rn["race_id"]).transform("sum")
    rn["barrier_rel"] = rn["barrier"] / nst
    rn["n_starters"] = nst
    rn["n_winners"] = rn["race_id"].map(rc["n_winners"]); rn["places_paid"] = rn["race_id"].map(rc["places_paid"])
    rn["is_jumps"] = rn["race_id"].map(rc["is_jumps"]); rn["race_name"] = rn["race_id"].map(rc["race_name"])
    rn = rn.sort_values(["date", "race_id", "entry_no"]).reset_index(drop=True)
    pickle.dump(rn, open(f"{L.LM}/prep/paths.pkl", "wb"), protocol=4)
    race = rn["race_id"]
    for T in (10, 5, 2):
        d = rn.copy()
        last_rel = np.fmax(d["sb_last_rel_s"], d["lb_last_rel_s"])
        inU = (~d["scratched"]) | (d["scratched"] & (last_rel >= -T * 60))
        bad = (inU & ~d["starter"]).groupby(race).transform("sum") > 0                   # late scratching / non-starter in U
        nU = inU.groupby(race).transform("sum")
        ok = pd.Series(True, index=d.index)
        m = {}
        for b in ("sb", "lb"):
            q = d[f"{b}_t{T}"]; us = q.notna() & inU
            inv = (1.0 / q).where(us)
            m[b] = (inv / inv.groupby(race).transform("sum")).where(us)
            ok &= (us.groupby(race).transform("sum") == nU) & (nU > 0)
            ok &= d[f"{b}_t{T}_age_s"].where(inU).groupby(race).transform("min") <= 900     # live in [T-15min, T]
        d["M"] = ((m["sb"] + m["lb"]) / 2).where(inU)
        d["m_sb"], d["m_lb"] = m["sb"], m["lb"]
        keep = ok & ~bad & (d["n_winners"] == 1) & d["starter"] & (nU >= 5) & d["M"].notna()
        keep &= keep.groupby(race).transform("sum") == nU                                 # all of U kept
        d = d[keep].copy()
        d["won"] = d["won"].fillna(False).astype(bool)
        d = d[d.groupby("race_id")["won"].transform("sum") == 1]
        d["M"] = d["M"] / d.groupby("race_id")["M"].transform("sum")
        d["logM"] = np.log(d["M"])
        d["q_sb"] = d[f"sb_t{T}"]; d["q_lb"] = d[f"lb_t{T}"]
        # ---- moves, averaged over the books that have both ends; telescoping segments open -> 60 -> 15 -> T
        seg = {k: [] for k in ("sa", "sb", "sc", "mO", "m60", "m15", "m120", "mlast")}
        for b in ("sb", "lb"):
            o, q60, q15, qT, q120 = d[f"{b}_open"], d[f"{b}_t60"], d[f"{b}_t15"], d[f"{b}_t{T}"], d[f"{b}_t120"]
            x0 = o; x1 = q60.fillna(x0); x2 = q15.fillna(x1)
            seg["sa"].append(np.log(x0 / x1).where(o.notna() & qT.notna()))
            seg["sb"].append(np.log(x1 / x2).where(o.notna() & qT.notna()))
            seg["sc"].append(np.log(x2 / qT).where(o.notna() & qT.notna()))
            seg["mO"].append(np.log(o / qT)); seg["m60"].append(np.log(q60 / qT)); seg["m15"].append(np.log(q15 / qT))
            seg["m120"].append(np.log(q120 / qT)); seg["mlast"].append(np.log(qT / d[f"{b}_t0"]))   # mlast: T -> the last pre-jump price (look-ahead, descriptive only)
        for k, v in seg.items():
            d[k] = pd.concat(v, axis=1).mean(axis=1)
        for k in ("sa", "sb", "sc", "mO"):                                                 # race-centred: remove the race's M-weighted mean move
            wm = (d["M"] * d[k].fillna(0)).groupby(d["race_id"]).transform("sum")
            d[k + "_c"] = (d[k] - wm).where(d[k].notna())
        d["move_missing"] = d["mO"].isna().astype(float)
        d["spread"] = np.log(d["m_sb"] / d["m_lb"]); d["spread_abs"] = d["spread"].abs()
        d["f11_sb_lb"], d["f11_abs"] = d["spread"], d["spread_abs"]                          # F11 at this T
        d["T"] = T
        d = d.reset_index(drop=True)
        pickle.dump(d, open(f"{L.LM}/prep/runners_T{T}.pkl", "wb"), protocol=4)
        # sanity: agree with the build's own M where it exists
        ref = {10: "M_t10", 2: "M_t2"}.get(T)
        msg = ""
        if ref:
            r = d[ref].notna()
            msg = f"; max |M - build {ref}| over {int(r.sum())} runners = {np.nanmax(np.abs(d.loc[r, 'M'] - d.loc[r, ref])):.2e} (renormalised over starters)"
        print(f"T-{T}: {d['race_id'].nunique()} races, {len(d)} runners; by block {d.groupby('block', observed=True)['race_id'].nunique().to_dict()}{msg}", flush=True)


if __name__ == "__main__":
    main()
