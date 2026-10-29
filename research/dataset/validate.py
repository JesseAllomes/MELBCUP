"""Validation + baseline facts.  Reads out/*.pkl.gz, writes reports/validation.md + reports/*.csv and refreshes manifest.json.
Run: MELBCUP_ROOT=<folder> python3 -I validate.py

HARD RULE: no outcome statistic (win rate, A/E, log-loss, winner ranks ...) is ever computed on block 'final'.
Everything outcome-related goes through nf() below. Counts / coverage / market-only statistics may use all blocks.
"""
import json, os, sys, hashlib, datetime
import numpy as np
import pandas as pd

BASE = os.path.join(os.environ.get("MELBCUP_ROOT") or sys.exit("set MELBCUP_ROOT"), "upsets")
OUT, REP = f"{BASE}/out", f"{BASE}/reports"
os.makedirs(REP, exist_ok=True)
for f in os.listdir(REP):
    os.remove(os.path.join(REP, f))
meta = json.load(open(f"{OUT}/meta.json"))
NEED = ["race_id", "meeting_id", "date", "year", "block", "state", "starter", "race_resulted", "is_au", "examined", "won", "placed", "finish_pos",
        "n_starters", "sp", "sp_p", "sp_inv", "sp_rank", "res_comment", "res_last600_s", "res_settled", "res_pos800", "res_pos400", "res_top_speed",
        "res_dist_travelled", "handicap_rating", "weight_kg", "barrier", "jockey_id", "trainer_id", "class_rdc", "track_cond", "sire", "speed_value_unverified",
        "sb_n_flucs", "lb_n_flucs", "sb_feed_stale", "horse_code", "hist_ok", "ls_start_utc", "runs_in_ds", "scratched", "baseline_dummy"]
for b_ in ("sb", "lb"):
    for T_ in (60, 30, 10, 2):
        NEED += [f"{b_}_t{T_}", f"{b_}_t{T_}_age_s", f"{b_}_t{T_}_p", f"{b_}_t{T_}_later_fluc", f"cofav_{b_}_t{T_}", f"{b_}_t{T_}_usable"]
    NEED += [f"{b_}_open", f"{b_}_final", f"{b_}_final_p", f"{b_}_open_p"]
for T_ in (60, 30, 10, 2):
    NEED += [f"M_t{T_}", f"inU_t{T_}", f"late_scratch_t{T_}"]


def load(name):
    d = pd.read_pickle(f"{OUT}/{name}.pkl.gz")
    return d[[c for c in NEED if c in d.columns]].copy()


R_in = pd.read_pickle(f"{OUT}/races.pkl.gz")
R_ex = pd.read_pickle(f"{OUT}/races_excluded.pkl.gz")
RA = pd.concat([R_in, R_ex], ignore_index=True)            # every race
DA = pd.concat([load("runners"), load("runners_excluded")], ignore_index=True)     # every runner row (incl. HK), needed columns only
AU_STATES = ["NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT"]
lines = []


def nf(df):
    """outcome statistics only ever see block train (protocol v0.5 freeze: tune1/tune2/final/excluded/history_only never) and never examined races."""
    return df[df["block"].astype(str).isin(["train"]) & ~df["examined"].astype(bool)]


def md(df, floatfmt=3):
    d = df.copy()
    def fmt(x):
        if isinstance(x, (float, np.floating)):
            if np.isnan(x):
                return ""
            return f"{x:.0f}" if (float(x).is_integer() and abs(x) > 50) else f"{x:.{floatfmt}f}"
        return str(x)
    cols = [str(c) for c in d.columns]
    out = ["| " + " | ".join([d.index.name or ""] + cols) + " |", "|" + "---|" * (len(cols) + 1)]
    for i, r in d.iterrows():
        out.append("| " + " | ".join([str(i)] + [fmt(v) for v in r.values]) + " |")
    return "\n".join(out)


def sec(title, df=None, note=None, name=None, floatfmt=3):
    lines.append(f"\n### {title}\n")
    if note:
        lines.append(note + "\n")
    if df is not None:
        lines.append(md(df, floatfmt) + "\n")
        if name:
            df.to_csv(f"{REP}/{name}.csv")


lines.append("# Validation report\n")
lines.append(f"- built_at {meta['built_at']}; source files seen {meta['source_files_seen']}; newly parsed this run {meta['parsed_now']}; failed {meta['failed']}; skipped-too-fresh {meta['skipped_fresh']}")
lines.append(f"- dates {meta['earliest_date']} .. {meta['latest_date']}; contiguous coverage starts {meta['contiguous_coverage_start']}; history trusted from {meta['history_complete_from']}")
lines.append(f"- non-Australian rows (routed to excluded tables): {meta['non_au_rows']} ({meta['non_au_states']})")
lines.append(f"- all races {len(RA)}; in-sample {len(R_in)}; excluded {len(R_ex)}; meetings {RA['meeting_id'].nunique()}; runner rows {len(DA)}")
lines.append("- outcome statistics below use block train only (tune1, tune2 and final are not opened before the protocol-v1 tag). Block 'final' appears in counts and coverage tables only.")

# ------------------------------------------------------------------ funnel
fo = pd.read_csv(f"{OUT}/funnel_overall.csv").set_index("step")
sec("0. PRE-DECISION funnel at T-30 (each race attributed to the FIRST rule it fails), then post-race scoring counts", fo.drop(columns=["description"]), name="funnel_overall",
    note="Rules in order: " + "; ".join(f"{r.rule} = {r.description}" for r in fo.reset_index().itertuples() if str(r.step).isdigit() and r.rule != "all races in dump") + ". Post-race rows are counts among pre-decision-eligible races, not exclusions.", floatfmt=0)
fy = pd.read_csv(f"{OUT}/funnel_by_year_state.csv").set_index(["year", "state"])
sec("0b. Funnel by year/state (races removed at each rule; INCLUDED = in-sample)", fy, name="funnel_by_year_state", floatfmt=0)
fb = pd.read_csv(f"{OUT}/funnel_by_block.csv").set_index("block")
sec("0c. Funnel by block (counts)", fb, name="funnel_by_block", floatfmt=0)
fp = pd.read_csv(f"{OUT}/funnel_post_race_by_year_state.csv").set_index(["year", "state"])
sec("0d. Post-race scoring status among pre-decision-eligible races, by year/state", fp, name="funnel_post_race_by_year_state", floatfmt=0)
fa = pd.read_csv(f"{OUT}/funnel_quote_age_sensitivity.csv")
fa = fa.set_index(["T", "year"])
sec("0e. Market-eligibility vs quote-age limit (races passing every other pre-decision rule; U = non-scratched + usably quoted late scratchings)", fa, name="funnel_quote_age_sensitivity", floatfmt=0,
    note="Quotes are change-only fluc series: a price that has not moved for hours is 'old' although it is still the live price, which is why protocol v0.5 counts the last fluc <= T at any age (market_ok_any_age is the protocol rule; feed liveness is applied separately). market_ok_age<=L counts races where EVERY runner in U has a quote from BOTH books no older than L seconds.")

# ------------------------------------------------------------------ A. counts
cnt = RA.groupby(["year", "state"], observed=True).agg(meetings=("meeting_id", "nunique"), races=("race_id", "size"), resulted=("race_resulted", "sum"),
                                                       in_sample=("in_sample", "sum"), one_winner=("one_winner", "sum"), starters=("n_starters", "sum"))
cnt = cnt.join(DA.groupby(["year", "state"], observed=True).size().rename("runner_rows_incl_scratched"))
cnt["share_one_winner_of_resulted"] = cnt["one_winner"] / cnt["resulted"]
cnt["share_in_sample"] = cnt["in_sample"] / cnt["races"]
sec("A. Row counts by year/state (all races incl. excluded and HK)", cnt, name="counts_year_state", floatfmt=3)
cb = RA.groupby("block", observed=True).agg(meetings=("meeting_id", "nunique"), races=("race_id", "size"), in_sample=("in_sample", "sum"), starters=("n_starters", "sum"))
sec("A2. Counts by block", cb, name="counts_block", floatfmt=0)

AU = RA[RA["is_au"]]
Rres = AU[AU["race_resulted"]]
wn = Rres.groupby("n_winners").size().rename("races").to_frame()
sec("A3. Winners per resulted AU race", wn, note="n_winners=0: a result exists but nobody has finish 1 (partial/odd result); 2+ = dead heat or duplicate data.")
iss = pd.Series({
    "AU races": len(AU), "AU resulted": len(Rres),
    "n_winners==0": int((Rres["n_winners"] == 0).sum()), "n_winners>=2": int((Rres["n_winners"] >= 2).sum()),
    "runnersCount != n_starters": int(Rres["field_mismatch_api"].fillna(False).sum()), "duplicate-entry races": int(Rres["dup_entries"].sum()),
    "AU races not resulted": int((~AU["race_resulted"]).sum()), "jumps races (flagged, not excluded)": int(AU["is_jumps"].sum()),
}).to_frame("n")
sec("A4. Race-level data issues", iss)

# ------------------------------------------------------------------ B. availability (coverage only; all blocks allowed)
S = DA[DA["starter"] & DA["race_resulted"] & DA["state"].astype(str).isin(AU_STATES)].copy()
S["has_sp"] = S["sp"].notna(); S["sp_p_ok"] = S["sp_p"].notna()
S["sb_flucs"] = S["sb_n_flucs"] > 0; S["lb_flucs"] = S["lb_n_flucs"] > 0
S["sb_feed_ok"] = ~S["sb_feed_stale"].astype(bool)
S["sb_t30_price"] = S["sb_t30"].notna(); S["sb_t30_prob"] = S["sb_t30_p"].notna(); S["lb_t30_prob"] = S["lb_t30_p"].notna()
S["sb_t2_prob"] = S["sb_t2_p"].notna(); S["sb_open_prob"] = S["sb_open_p"].notna()
S["stewards_comment"] = S["res_comment"].notna(); S["sectional_last600"] = S["res_last600_s"].notna()
S["handicap_rating_ok"] = S["handicap_rating"].notna(); S["weight_ok"] = S["weight_kg"].notna(); S["barrier_ok"] = S["barrier"].notna()
S["speed_value_ok"] = S["speed_value_unverified"].notna(); S["settled_pos"] = S["res_settled"].notna(); S["pos800"] = S["res_pos800"].notna()
S["jockey_ok"] = S["jockey_id"].notna(); S["class_rdc_ok"] = S["class_rdc"].notna(); S["track_cond_ok"] = S["track_cond"].notna()
acols = ["has_sp", "sp_p_ok", "sb_flucs", "lb_flucs", "sb_feed_ok", "sb_t30_price", "sb_t30_prob", "lb_t30_prob", "sb_t2_prob", "sb_open_prob",
         "stewards_comment", "sectional_last600", "handicap_rating_ok", "weight_ok", "barrier_ok", "speed_value_ok", "settled_pos", "pos800",
         "jockey_ok", "class_rdc_ok", "track_cond_ok"]
av = S.groupby(["year", "state"], observed=True)[acols].mean()
av.insert(0, "starters", S.groupby(["year", "state"], observed=True).size())
sec("B. Availability among starters of resulted AU races, by year/state", av, name="availability_year_state", floatfmt=2,
    note="sp_p_ok = margin-free SP prob present (needs >=80% of starters with SP). *_prob = margin-free prob present (needs >=80% quoted). sb_feed_ok = Sportsbet feed alive near the off. Coverage only (no outcomes).")
avy = S.groupby("year")[acols].mean()
avy.insert(0, "starters", S.groupby("year").size())
sec("B2. Availability by year", avy, name="availability_year", floatfmt=3)
RS = Rres.copy()
RS["sb_stale_but_has_flucs"] = RS["sb_has_flucs"] & RS["sb_feed_stale"]
rc_av = RS.groupby(["year"]).agg(races=("race_id", "size"), sp_complete=("sp_complete", "mean"), sp_quality_ok=("sp_quality_ok", "mean"),
                                 sb_has_flucs=("sb_has_flucs", "mean"), lb_has_flucs=("lb_has_flucs", "mean"), sb_stale_but_has_flucs=("sb_stale_but_has_flucs", "mean"),
                                 sb_t30_cov80=("sb_t30_coverage", lambda s: (s >= 0.8).mean()), lb_t30_cov80=("lb_t30_coverage", lambda s: (s >= 0.8).mean()),
                                 has_sectionals=("race_has_sectionals", "mean"))
sec("B3. Race-level availability by year (resulted AU races)", rc_av, name="availability_race_year", floatfmt=3)
rc_av2 = RS.groupby(["state"]).agg(races=("race_id", "size"), sp_complete=("sp_complete", "mean"), sp_quality_ok=("sp_quality_ok", "mean"),
                                   sb_has_flucs=("sb_has_flucs", "mean"), sb_stale_but_has_flucs=("sb_stale_but_has_flucs", "mean"),
                                   sb_t30_cov80=("sb_t30_coverage", lambda s: (s >= 0.8).mean()), has_sectionals=("race_has_sectionals", "mean"))
sec("B4. Race-level availability by state", rc_av2, name="availability_race_state", floatfmt=3)

# ------------------------------------------------------------------ B4b. field availability by field / bookmaker / decision time / year
rows = []
for yr, grp in list(S.groupby("year")):
    n = len(grp)
    base = {"starting price (sp)": grp["sp"].notna(), "handicap_rating": grp["handicap_rating"].notna(), "weight_kg": grp["weight_kg"].notna(),
            "barrier": grp["barrier"].notna(), "jockey": grp["jockey_id"].notna(), "trainer": grp["trainer_id"].notna(), "class_rdc": grp["class_rdc"].notna(),
            "stewards comment": grp["res_comment"].notna(), "position settled": grp["res_settled"].notna(), "position at 800": grp["res_pos800"].notna(),
            "position at 400": grp["res_pos400"].notna(), "last-600 sectional (timing)": grp["res_last600_s"].notna(), "topSpeed": grp["res_top_speed"].notna(),
            "distanceTravelled": grp["res_dist_travelled"].notna(), "speedValue (never used)": grp["speed_value_unverified"].notna(), "sire": grp["sire"].notna()}
    for f_, m_ in base.items():
        rows.append(dict(field=f_, book="-", T="-", year=yr, share=m_.mean(), n=n))
    for b_ in ("sb", "lb"):
        for T_ in ("open", 60, 30, 10, 2, "final"):
            col = f"{b_}_open" if T_ == "open" else (f"{b_}_final" if T_ == "final" else f"{b_}_t{T_}")
            rows.append(dict(field="quote exists", book=b_, T=str(T_), year=yr, share=grp[col].notna().mean(), n=n))
            if isinstance(T_, int):
                rows.append(dict(field="quote usable (v0.5: any age)", book=b_, T=str(T_), year=yr, share=grp[f"{col}_usable"].astype(float).mean() if f"{col}_usable" in grp else np.nan, n=n))
fav_tab = pd.DataFrame(rows).pivot_table(index=["field", "book", "T"], columns="year", values="share", sort=False)
sec("B4b. Field availability by field / bookmaker / decision time / year (share of starters in resulted AU races)", fav_tab, name="field_availability", floatfmt=3,
    note="Rows 'quote exists' / 'quote usable' are per runner: usable = last fluc at or before T, any age (protocol v0.5).")

# ------------------------------------------------------------------ B4c. timing flags (all AU races; no outcomes)
AUr = RA[RA["is_au"]]
tf = AUr.groupby("year").agg(races=("race_id", "size"), timing_untrusted=("timing_untrusted", "mean"), no_fluc_3h=("timing_flag_no_fluc_3h", "mean"),
                              last_fluc_gt24h=("timing_flag_last_gt24h", "mean"), start_date_mismatch=("timing_flag_start_date_mismatch", "mean"),
                              first_fluc_gt1d=("timing_flag_first_gt1d", "mean"), first_fluc_gt7d=("timing_flag_first_gt7d", "mean"), first_fluc_after_start=("timing_flag_first_after_start", "mean"))
sec("B4c. Timing flags among AU races (share of races)", tf, name="timing_flags_year", floatfmt=4,
    note="no_fluc_3h includes races with no fluctuations at all (nothing within 3 h before the start). first_fluc_gt1d is true for most races because markets open 1-4 days ahead.")

# ------------------------------------------------------------------ B5. executability (market-only)
rows = {}
for b in ("sb", "lb"):
    for T in (60, 30, 10, 2):
        k = f"{b}_t{T}"
        q = S[k].notna()
        age = S.loc[q, f"{k}_age_s"]
        okp = S[f"{k}_p"].notna()
        rows[k] = dict(starters_with_quote=q.mean(), age_median_s=age.median(), age_p90_s=age.quantile(0.9), share_age_le_60s=(age <= 60).mean(),
                       share_age_le_300s=(age <= 300).mean(), share_replaced_before_start=S.loc[q, f"{k}_later_fluc"].astype(float).mean(),
                       share_cofav=S.loc[okp, f"cofav_{k}"].astype(float).mean())
ex = pd.DataFrame(rows).T
ex.index.name = "book_time"
sec("B5. Quote executability (starters of resulted AU races, all blocks; market-only)", ex, name="executability",
    note="age = seconds between the quote and the decision time T; replaced_before_start = a later fluc occurred before the scheduled start. share_cofav = share of runners that are co-favourites (tied shortest price) among runners with a usable market.")
AR = RA[RA["is_au"] & RA["race_resulted"]]
ls = (AR[["n_late_scratch_t60", "n_late_scratch_t30", "n_late_scratch_t10", "n_late_scratch_t2"]] > 0).mean().to_frame("share_of_races")
ls.loc["any scratching (n_scratched>0)"] = (AR["n_scratched"] > 0).mean()
sec("B6. Late scratchings (inferred from Sportsbet price series; no scratching timestamps exist)", ls, floatfmt=3,
    note="Protocol rule: a scratched entry whose last fluc at either book is at or after T is a late scratching (v0.5). Deductions are NOT modelled.")

# ------------------------------------------------------------------ C. sanity (no outcomes)
R_base_ids = set(RA.loc[RA["baseline_ok"], "race_id"])
Sin = DA[DA["starter"] & DA["race_id"].isin(R_base_ids)]
sums = Sin[Sin["sp_p"].notna()].groupby("race_id")["sp_p"].sum()
sums30 = Sin[Sin["sb_t30_p"].notna()].groupby("race_id")["sb_t30_p"].sum()
san = pd.DataFrame({"races": [len(sums), len(sums30)], "min_sum": [sums.min(), sums30.min()], "max_sum": [sums.max(), sums30.max()],
                    "max_abs_dev_from_1": [(sums - 1).abs().max(), (sums30 - 1).abs().max()]}, index=["sp_p", "sb_t30_p"])
sec("C1. Probabilities sum to 1 within race (in-sample races)", san, floatfmt=9)
ovr = pd.DataFrame({"overround_sp (AU resulted, full SP)": Rres.loc[Rres["sp_complete"], "overround_sp"].describe(),
                    "overround_sb_t30": Rres["overround_sb_t30"].describe(), "overround_lb_t30": Rres["overround_lb_t30"].describe()})
sec("C2. Overround (sum of 1/price) among races with full coverage", ovr, name="overround", floatfmt=3)

# ================================================================== outcome statistics: non-final only
RN = nf(RA[RA["baseline_ok"]])      # descriptive baseline sample, train+tune1+tune2, examined races removed
DN = nf(DA[DA["race_id"].isin(RN["race_id"])])
lines.append(f"\n## Outcome statistics (block train only; in-sample races n={len(RN)}; dates {RN['date'].min().date()}..{RN['date'].max().date()})\n")
lines.append("- descriptive baseline sample (race flag baseline_ok) = AU, clean result, >=5 starters, exactly one winner, full SP with overround 1.05-1.50, legacy SB T-30 market (>=80% of starters quoted, feed alive; ANY quote age). This is NOT the protocol's eligible set (see funnel 0/0e). Ties on favourite price broken by SB final / LB final / barrier")
lines.append(f"- favourite (shortest SP) strike rate overall: **{RN['fav_sp_won'].astype(float).mean():.3f}** (n={len(RN)}); place rate {RN['fav_sp_placed'].astype(float).mean():.3f}; mean fav SP {RN['fav_sp_price'].mean():.2f}; mean fav margin-free p {RN['fav_sp_p'].mean():.3f}; fav tied on price in {RN['fav_tied_sp'].astype(float).mean():.4f} of races")
bk = RN.groupby("block", observed=True).agg(races=("race_id", "size"), fav_strike=("fav_sp_won", lambda s: s.astype(float).mean()), fav_place=("fav_sp_placed", lambda s: s.astype(float).mean()),
                                              mean_fav_sp=("fav_sp_price", "mean"), mean_fav_p=("fav_sp_p", "mean"))
sec("D0. Favourite strike by block (train only)", bk, name="fav_by_block")

bands = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0, 10.0, 15.0, 25.0, 50.0, 1e9]
labels = ["<1.5", "1.5-2", "2-2.5", "2.5-3", "3-4", "4-5", "5-7", "7-10", "10-15", "15-25", "25-50", "50+"]
Sa = DN[DN["starter"] & DN["sp_p"].notna() & DN["won"].notna()].copy()
Sa["won_f"] = Sa["won"].astype(float)
Sa["band"] = pd.cut(Sa["sp"], bands, labels=labels, right=False)
ae = Sa.groupby("band", observed=True).agg(runners=("won_f", "size"), wins=("won_f", "sum"), mean_sp=("sp", "mean"), exp_wins_normalised=("sp_p", "sum"), exp_wins_raw_1_over_sp=("sp_inv", "sum"))
ae["strike"] = ae["wins"] / ae["runners"]
ae["mean_p_norm"] = ae["exp_wins_normalised"] / ae["runners"]
ae["AE_vs_normalised_p"] = ae["wins"] / ae["exp_wins_normalised"]
ae["AE_vs_raw_1_over_sp"] = ae["wins"] / ae["exp_wins_raw_1_over_sp"]
ae["se_AE"] = np.sqrt(ae["wins"].clip(lower=1)) / ae["exp_wins_normalised"]
sec("C3. A/E of SP by price band (all starters, in-sample non-final races)", ae, name="ae_by_sp_band",
    note="Favourite-longshot bias would show as AE_vs_normalised_p >1 for short prices and <1 for long prices. se_AE ~ sqrt(wins)/expected.")

B = RN.copy()
B["fav_won_f"] = B["fav_sp_won"].astype(float)
B["fav_placed_f"] = B["fav_sp_placed"].astype(float)


def fav_table(by, bins=None, labels_=None, name=None, title=None, minn=0, data=None):
    X = (B if data is None else data).copy()
    X["grp"] = pd.cut(X[by], bins, labels=labels_, right=False) if bins is not None else X[by]
    t = X.groupby("grp", observed=True).agg(races=("fav_won_f", "size"), fav_strike=("fav_won_f", "mean"), fav_place_rate=("fav_placed_f", "mean"),
                                            mean_fav_sp=("fav_sp_price", "mean"), mean_fav_p_norm=("fav_sp_p", "mean"))
    t["strike_minus_p"] = t["fav_strike"] - t["mean_fav_p_norm"]
    t["se"] = np.sqrt(t["fav_strike"] * (1 - t["fav_strike"]) / t["races"])
    t.index.name = by
    t = t[t["races"] >= minn]
    sec(title, t, name=name)
    return t


fav_table("fav_sp_price", [1.0, 1.5, 1.8, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 7.0, 1e9],
          ["<1.5", "1.5-1.8", "1.8-2", "2-2.5", "2.5-3", "3-3.5", "3.5-4", "4-5", "5-7", "7+"], "fav_by_price_band", "D1. Favourite strike rate by favourite SP band")
B["field_band"] = pd.cut(B["n_starters"], [0, 6, 8, 10, 12, 14, 99], labels=["<=6", "7-8", "9-10", "11-12", "13-14", "15+"])
fav_table("field_band", name="fav_by_field", title="D2. Favourite strike rate by field size (starters)")
fav_table("class_cat", name="fav_by_class", title="D3. Favourite strike rate by class category", minn=1)
fav_table("track_cond", name="fav_by_condition", title="D4. Favourite strike rate by track condition")
fav_table("state", name="fav_by_state", title="D5. Favourite strike rate by state")
B["dist_band"] = pd.cut(B["distance_m"], [0, 1100, 1300, 1500, 1800, 2200, 9999], labels=["<=1100", "1101-1300", "1301-1500", "1501-1800", "1801-2200", "2200+"])
fav_table("dist_band", name="fav_by_distance", title="D6. Favourite strike rate by distance")
fav_table("year", name="fav_by_year", title="D7. Favourite strike rate by year")

W = B["winner_sp_rank"].clip(upper=4)
wr = W.map({1: "1st fav", 2: "2nd fav", 3: "3rd fav", 4: "4th+ fav"}).value_counts().reindex(["1st fav", "2nd fav", "3rd fav", "4th+ fav"]).to_frame("races")
wr["share"] = wr["races"] / wr["races"].sum()
sec("D8. Winner's SP rank (1 = favourite)", wr, name="winner_sp_rank")
wr2 = pd.crosstab(pd.cut(B["n_starters"], [0, 7, 10, 13, 99], labels=["<=7", "8-10", "11-13", "14+"]), B["winner_sp_rank"].clip(upper=4), normalize="index")
wr2.columns = ["1st fav", "2nd fav", "3rd fav", "4th+ fav"]
wr2.index.name = "field size"
sec("D9. Winner's SP rank by field size (row shares)", wr2, name="winner_rank_by_field")
q = B["winner_sp"].quantile([0.05, 0.10, 0.25, 0.5, 0.75, 0.90, 0.95, 0.99]).to_frame("winner_sp")
q.index.name = "quantile"
sec("D10. Winner's SP distribution (quantiles)", q, name="winner_sp_quantiles", floatfmt=2)
wb = pd.cut(B["winner_sp"], bands, labels=labels, right=False).value_counts().reindex(labels).to_frame("winners")
wb["share"] = wb["winners"] / wb["winners"].sum()
wb["share_of_starters_in_band"] = ae["runners"].reindex(labels) / ae["runners"].sum()
sec("D11. Winners by SP band", wb, name="winner_sp_bands")

# ---- performance on EXCLUDED races (non-final), AU resulted with SP-favourite defined
EX = nf(R_ex)
EX = EX[EX["is_au"] & EX["race_resulted"] & (EX["n_winners"] == 1) & EX["fav_sp_price"].notna()].copy()
EX["fav_won_f"] = EX["fav_sp_won"].astype(float); EX["fav_placed_f"] = EX["fav_sp_placed"].astype(float)
et = EX.groupby("excl_reason").agg(races=("fav_won_f", "size"), fav_strike=("fav_won_f", "mean"), fav_place_rate=("fav_placed_f", "mean"),
                                   mean_fav_sp=("fav_sp_price", "mean"), mean_fav_p_norm=("fav_sp_p", "mean"))
et["strike_minus_p"] = et["fav_strike"] - et["mean_fav_p_norm"]
sec("D12. SP-favourite performance on EXCLUDED races (non-final blocks; only races where an SP favourite exists)", et, name="fav_on_excluded",
    note="Compare with D0/D1. not_market_eligible = some U runner unquoted at T-30; feed_not_live = a book silent in the 900 s before T-30; u_lt5 are small fields.")
# ------------------------------------------------------------------ E. SP vs SB T-30 (non-final, in-sample => all have T-30)
C = B.copy()
C["changed"] = C["fav_changed_t30_sb_to_sp"].astype(float)
lines.append(f"\n### E. SP vs Sportsbet T-30 ({len(C)} in-sample non-final races, all with a usable SB T-30 market)\n")
lines.append(f"- favourite at SB T-30 differs from SP favourite in **{C['changed'].mean():.3f}** of these races")
x = C[C["changed"] == 1]
lines.append(f"- when they differ (n={len(x)}): SB T-30 favourite wins {x['fav_sb_t30_won'].astype(float).mean():.3f}, SP favourite wins {x['fav_sp_won'].astype(float).mean():.3f}")
y = C[C["changed"] == 0]
lines.append(f"- when same horse (n={len(y)}): fav strike {y['fav_sp_won'].astype(float).mean():.3f}")
lines.append(f"- SB T-30 favourite strike rate {C['fav_sb_t30_won'].astype(float).mean():.3f} vs SP favourite strike rate {C['fav_sp_won'].astype(float).mean():.3f} (same races); co-favourites at SB T-30 in {(C['n_cofav_sb_t30'] > 0).mean():.3f} of races")

cols = {"SP": "sp_p", "SB final": "sb_final_p", "LB final": "lb_final_p", "SB T-60": "sb_t60_p", "SB T-30": "sb_t30_p", "SB T-10": "sb_t10_p", "SB T-2": "sb_t2_p",
        "LB T-60": "lb_t60_p", "LB T-30": "lb_t30_p", "LB T-10": "lb_t10_p", "LB T-2": "lb_t2_p", "SB open": "sb_open_p"}
X = DN[DN["starter"] & DN["race_id"].isin(B["race_id"])].copy()
X["won_f"] = X["won"].astype(float)
avail = X.groupby("race_id")[list(cols.values())].agg(lambda s: s.notna().all())
winp = X[X["won_f"] == 1].drop_duplicates("race_id").set_index("race_id")


def race_ll(col):
    return -np.log(winp[col])


tab = {}
for nm, col in cols.items():
    ok = avail.index[avail[["sp_p", col]].all(axis=1)]
    ll = race_ll(col).reindex(ok)
    ll_sp = race_ll("sp_p").reindex(ok)
    dd = ll - ll_sp
    Xr = X[X["race_id"].isin(ok)]
    p = Xr[col]; w = Xr["won_f"]
    brier = ((p - w) ** 2).groupby(Xr["race_id"]).sum().mean()
    tab[nm] = dict(races=len(ok), race_logloss=ll.mean(), sp_race_logloss_same_races=ll_sp.mean(), diff_vs_SP=dd.mean(),
                   se_diff=dd.std() / np.sqrt(len(dd)) if len(dd) > 1 else np.nan, race_brier=brier)
ll = pd.DataFrame(tab).T
ll.index.name = "market"
sec("E1. Race-level log-loss (-log p(winner), lower = better) vs SP on the same races (non-final)", ll, name="logloss_markets", floatfmt=4,
    note="diff_vs_SP>0 means the snapshot is worse than SP; se_diff is the paired standard error across races. SP = racing.com startingPrice (the 'OP' feed).")
chg = C["fav_sb_t30_sp_rank"].clip(upper=4).map({1: "same", 2: "2nd SP fav", 3: "3rd SP fav", 4: "4th+ SP fav"}).value_counts().reindex(["same", "2nd SP fav", "3rd SP fav", "4th+ SP fav"]).to_frame("races")
chg["share"] = chg["races"] / chg["races"].sum()
sec("E2. Where the T-30 Sportsbet favourite ends up in the SP ranking", chg, name="fav_change_t30_to_sp")
wsb = C["winner_sb_t30_rank"].clip(upper=4).map({1: "1st fav", 2: "2nd fav", 3: "3rd fav", 4: "4th+ fav"}).value_counts().reindex(["1st fav", "2nd fav", "3rd fav", "4th+ fav"]).to_frame("races_by_SB_T30_rank")
wsb["share_SB_T30"] = wsb["races_by_SB_T30_rank"] / wsb["races_by_SB_T30_rank"].sum()
wsb["share_SP"] = C["winner_sp_rank"].clip(upper=4).map({1: "1st fav", 2: "2nd fav", 3: "3rd fav", 4: "4th+ fav"}).value_counts(normalize=True).reindex(wsb.index)
sec("E2b. Winner's rank in the market: SB T-30 vs SP (same races)", wsb, name="winner_rank_sbt30_vs_sp")
d = C.copy()
d["fav_t30_move"] = d["fav_sb_t30_sp"] / d["fav_sb_t30_price"]
d["move_band"] = pd.cut(d["fav_t30_move"], [0, 0.85, 0.95, 1.05, 1.15, 10], labels=["shortened >15%", "shortened 5-15%", "within +-5%", "drifted 5-15%", "drifted >15%"])
mt = d.groupby("move_band", observed=True).agg(races=("fav_sb_t30_won", "size"), t30_fav_strike=("fav_sb_t30_won", lambda s: s.astype(float).mean()), mean_t30_p=("fav_sb_t30_p", "mean"))
mt["strike_minus_p"] = mt["t30_fav_strike"] - mt["mean_t30_p"]
sec("E3. SB T-30 favourite strike rate by how its price moved T-30 -> SP", mt, name="t30_fav_move",
    note="Bucketing uses the SP, which is only known at the off - descriptive, not a tradeable signal.")

# ------------------------------------------------------------------ D14. the protocol's eligible races (non-final)
EL = nf(R_in)
lines.append(f"\n### D14. Protocol-eligible races (pre-decision filters at T-30), train only: n={len(EL)}\n")
if len(EL):
    lines.append("scoring status: " + ", ".join(f"{k}={v}" for k, v in EL["scoring_status_t30"].value_counts().items()))
    E2 = EL[(EL["scoring_status_t30"] == "ok") & (EL["n_winners"] == 1)]
    if len(E2):
        lines.append(f"- scored races {len(E2)}: M-favourite strike {E2['fav_M_t30_won'].astype(float).mean():.3f}; SP-favourite strike {E2['fav_sp_won'].astype(float).mean():.3f}; co-favourite races {(E2['n_cofav_M_t30'] > 1).mean():.3f}")

# ------------------------------------------------------------------ F. history readiness (coverage only)
H = DA[DA["starter"] & DA["race_resulted"] & DA["state"].astype(str).isin(AU_STATES)]
hh = H.groupby("hist_ok").agg(starters=("horse_code", "size"), has_ls=("ls_start_utc", lambda s: s.notna().mean()), mean_runs_in_ds=("runs_in_ds", "mean"))
sec("F. History features: share of starters with a previous run in the dataset, by hist_ok", hh, name="history_readiness",
    note=f"hist_ok=True only for races on/after {meta['history_complete_from']} (contiguous coverage start {meta['contiguous_coverage_start']} + 90 days). hist_ok=False rows have truncated history.")

open(f"{REP}/validation.md", "w").write("\n".join(lines))


# ------------------------------------------------------------------ manifest (out/, reports/, scripts)
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


files = []
for d_ in (OUT, REP):
    files += [os.path.join(d_, f) for f in sorted(os.listdir(d_))]
files += [f"{BASE}/build.py", f"{BASE}/validate.py"]
man = {os.path.relpath(f, BASE): dict(sha256=sha256_file(f), bytes=os.path.getsize(f)) for f in files if os.path.isfile(f)}
json.dump(dict(generated=datetime.datetime.now(datetime.timezone.utc).isoformat(), files=man), open(f"{BASE}/manifest.json", "w"), indent=1)
print("\n".join(lines))
print(f"\nmanifest.json: {len(man)} files")
