# ruff: noqa: E501, E702, B905
"""m7: the live race card's pick rules, replayed on the archive (DEVELOPMENT EVIDENCE, nothing fitted here).

Rules exactly as melbcup/bets/allocate.py and singles.py use them (2026-11-01), per race:
  win       the win line paying closest to fair among runners with chance >= WIN_FLOOR (ties to the likelier)
  place     the runner most likely to place (= the favourite under discounted Plackett-Luce)
  each way  the each-way line paying closest to fair at a win price >= EW_FLOOR (same chance floor)
  value BET the model's good-price rule: required_edge(price) <= edge <= 0.40, price <= $21, chance >= 0.04
Chance = margin-free consensus of Sportsbet and Ladbrokes at T (the archive has two books; the app uses four),
raised to ALPHA and renormalised (ALPHA 1.0 is the app; 1.14 is the favourite-long-shot correction).
Settlement: 1 unit at Sportsbet's price at T (win), the stored last Sportsbet place price (place), half/half (each way).
"Chance-weighted" stakes are proportional to the chance the bet pays (as the day budget is shared), scaled to average 1.

Blocks: dev (train + tune1, 2023-01-01..2025-12-31), tune2, final, fwd (the examined month 2026-09-29..10-29). The
rules were never fitted on any block, so every block is a fair read of the FIXED rules; but tune2/final/fwd are spent
and the variant grid is run on dev only, so nothing here is a new frozen claim.
Data: $LM_DIR/prep/runners_T{2,10}.pkl (+ _fwd) from research/late_money/prep.py. Output: research/m7/card_rules.json.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "late_money"))
import lm_lib as L  # noqa: E402

WIN_FLOOR, EW_FLOOR, MAX_EDGE_OK, MAX_PRICE = 0.04, 5.0, 0.40, 21.0
BLOCKS = {"dev": ("2023-01-01", "2025-12-31", ""), "tune2": ("2026-01-01", "2026-04-30", ""),
          "final": ("2026-05-01", "2026-09-28", ""), "fwd": ("2026-09-29", "2026-10-29", "_fwd")}
NBOOT = 1000


def required_edge(q):
    return np.minimum(0.25, 0.05 + 0.01 * np.maximum(0.0, q - 1.0))


def load(T, a, b, suf):
    d = pd.read_pickle(f"{L.LM}/prep/runners_T{T}{suf}.pkl")
    d = d[(d["date"] >= a) & (d["date"] <= b)].copy()
    d["k"] = np.where(d["n_starters"] >= 8, 3, np.where(d["n_starters"] >= 5, 2, 0))
    d["placed"] = d["finish_pos"].notna() & (d["finish_pos"] <= d["k"]) & (d["k"] > 0)
    return d.sort_values(["date", "race_id", "entry_no"]).reset_index(drop=True)


def chances(d, alpha, mcol="M"):
    m = d[mcol].to_numpy(dtype=float) ** alpha
    tot = pd.Series(m).groupby(d["race_id"].to_numpy()).transform("sum").to_numpy()
    p = m / tot
    P = np.full(len(d), np.nan)
    for a, b in zip(*_bounds(d)):
        k = int(d["k"].iat[a])
        if k:
            P[a:b] = L.place_probs(p[a:b], k)
    return p, P


def _bounds(d):
    rid = d["race_id"].to_numpy()
    st = np.r_[0, np.flatnonzero(rid[1:] != rid[:-1]) + 1, len(rid)]
    return st[:-1], st[1:]


def pick_per_race(d, score, ok):
    """index of the row with the highest score among ok rows, per race (None when no ok row)."""
    s = np.where(ok, score, -np.inf)
    out = []
    for a, b in zip(*_bounds(d)):
        j = a + int(np.argmax(s[a:b]))
        if np.isfinite(s[j]):
            out.append(j)
    return np.array(out, dtype=int)


def closest(ev, p):
    return np.round(ev, 2) * 1000.0 + p  # the app's key: (round(ev, 2), chance)


def card(d, p, P, q, pp, win_floor=WIN_FLOOR, ew_floor=EW_FLOOR, rule="closest"):
    """row indices of the win, place and each-way picks and the value BETs."""
    ev_w = p * q - 1.0
    ev_p = P * pp - 1.0
    ev_e = 0.5 * (ev_w + ev_p)
    fin_q = np.isfinite(q)
    fin_p = np.isfinite(pp) & (pp > 1.0)
    if rule == "closest":
        sw, se = closest(ev_w, p), closest(ev_e, p)
    elif rule == "favourite":
        sw, se = p, p
    else:  # best_ev: highest edge whatever its size
        sw, se = ev_w, ev_e
    win = pick_per_race(d, sw, fin_q & (p >= win_floor))
    place = pick_per_race(d, P, fin_p & (d["k"].to_numpy() > 0))
    ew = pick_per_race(d, se, fin_q & fin_p & (p >= win_floor) & (q >= ew_floor))
    value = np.flatnonzero(fin_q & (p >= 0.04) & (q <= MAX_PRICE) & (ev_w >= required_edge(q)) & (ev_w <= MAX_EDGE_OK))
    return dict(win=win, place=place, each_way=ew, value=value), dict(ev_w=ev_w, ev_p=ev_p, ev_e=ev_e)


def settle(d, idx, kind, p, P, q, pp):
    won = d["won"].to_numpy()[idx]
    pl = d["placed"].to_numpy()[idx]
    if kind in ("win", "value"):
        ret = np.where(won, q[idx], 0.0); ch = p[idx]
    elif kind == "place":
        ret = np.where(pl, pp[idx], 0.0); ch = P[idx]
    else:
        ret = 0.5 * np.where(won, q[idx], 0.0) + 0.5 * np.where(pl, pp[idx], 0.0); ch = P[idx]
    return pd.DataFrame(dict(day=d["day"].to_numpy()[idx], ret=ret, chance=ch, hit=(won if kind in ("win", "value") else pl),
                             price=q[idx], n=d["n_starters"].to_numpy()[idx], dist=d["distance_m"].to_numpy()[idx]))


def summary(b, days, weighted=False):
    if len(b) == 0:
        return dict(bets=0)
    w = b["chance"].to_numpy() if weighted else np.ones(len(b))
    w = w / w.mean()
    vals = np.c_[w * (b["ret"].to_numpy() - 1.0), w]
    g = pd.DataFrame(vals, columns=["profit", "stake"]).groupby(b["day"].to_numpy()).sum().reindex(days).fillna(0.0)
    roi, ci = L.day_bootstrap(g.index.to_numpy(), g.to_numpy(), lambda s: s[0] / s[1] if s[1] > 0 else np.nan, n=NBOOT, seed=11)
    return dict(bets=int(len(b)), strike=round(float(b["hit"].mean()), 3), roi=round(100 * float(roi), 1),
                lo=round(100 * float(ci[0]), 1), hi=round(100 * float(ci[1]), 1), med_price=round(float(np.nanmedian(b["price"])), 2))


def run_block(name, T=2, alpha=1.0, mcol="M", qcol="q_sb"):
    a, b, suf = BLOCKS[name]
    d = load(T, a, b, suf)
    if mcol != "M":  # the T-30 market on the same races, renormalised over starters
        d = d[d.groupby("race_id")[mcol].transform(lambda s: s.notna().all())].reset_index(drop=True)
    p, P = chances(d, alpha, mcol)
    q = d[qcol].to_numpy(dtype=float); pp = d["sb_place"].to_numpy(dtype=float)
    days = np.sort(d["day"].unique())
    out = dict(races=int(d["race_id"].nunique()), days=int(len(days)))
    picks, _ = card(d, p, P, q, pp)
    for kind, idx in picks.items():
        bets = settle(d, idx, kind, p, P, q, pp)
        out[kind] = summary(bets, days)
        out[kind + "_chance_weighted"] = summary(bets, days, weighted=True)
        big = bets[bets["n"] >= 14]
        out[kind + "_fields14plus"] = summary(big, days)
    fav = pick_per_race(d, p, np.isfinite(q))
    out["favourite_win"] = summary(settle(d, fav, "win", p, P, q, pp), days)
    out["all_runners_win"] = summary(settle(d, np.arange(len(d)), "win", p, P, q, pp), days)
    return out, (d, p, P, q, pp, days)


def variants(d, p, P, q, pp, days, alpha_p=None):
    """dev only: the knobs the card uses, one at a time."""
    res = {}
    for wf in (0.02, 0.04, 0.08, 0.15):
        picks, _ = card(d, p, P, q, pp, win_floor=wf)
        res[f"win_floor_{wf}"] = summary(settle(d, picks["win"], "win", p, P, q, pp), days)
        res[f"ew_win_floor_{wf}"] = summary(settle(d, picks["each_way"], "each_way", p, P, q, pp), days)
    for ef in (4.0, 5.0, 8.0, 10.0, 15.0):
        picks, _ = card(d, p, P, q, pp, ew_floor=ef)
        res[f"ew_price_floor_{ef:g}"] = summary(settle(d, picks["each_way"], "each_way", p, P, q, pp), days)
    for rule in ("closest", "favourite", "best_ev"):
        picks, _ = card(d, p, P, q, pp, rule=rule)
        res[f"win_rule_{rule}"] = summary(settle(d, picks["win"], "win", p, P, q, pp), days)
        res[f"ew_rule_{rule}"] = summary(settle(d, picks["each_way"], "each_way", p, P, q, pp), days)
    return res


def main():
    results = {"T2": {}, "T2_alpha114": {}, "T10": {}, "T30_market_same_races": {}}
    dev_tables = None
    for name in BLOCKS:
        results["T2"][name], tabs = run_block(name)
        if name == "dev":
            dev_tables = tabs
        results["T2_alpha114"][name], _ = run_block(name, alpha=1.14)
        results["T10"][name], _ = run_block(name, T=10)
        results["T30_market_same_races"][name], _ = run_block(name, mcol="M_t30", qcol="sb_t30")
        print(name, "done", flush=True)
    d, p, P, q, pp, days = dev_tables
    results["variants_dev_only"] = variants(d, p, P, q, pp, days)
    # how much does alpha 1.14 change the picks on dev?
    p2, P2 = chances(d, 1.14)
    a1, _ = card(d, p, P, q, pp); a2, _ = card(d, p2, P2, q, pp)
    results["alpha_pick_changes_dev"] = {k: round(float(np.mean(a1[k] != a2[k])), 3) if len(a1[k]) == len(a2[k]) else "n differs"
                                         for k in ("win", "each_way")}
    results["alpha_pick_changes_dev"]["value_bets_alpha1"] = int(len(a1["value"]))
    results["alpha_pick_changes_dev"]["value_bets_alpha114"] = int(len(a2["value"]))
    # calibration of the win picks by price band (actual / expected), alpha 1 and 1.14, dev
    for lab, pp_, pk in (("alpha1", p, a1), ("alpha114", p2, a2)):
        b = settle(d, pk["win"], "win", pp_, P, q, pp)
        band = pd.cut(b["price"], [1, 2, 3, 5, 8, 12, 21, 1000])
        g = b.groupby(band, observed=True).agg(n=("hit", "size"), ae=("hit", "sum"))
        g["ae"] = (g["ae"] / b.groupby(band, observed=True)["chance"].sum()).round(2)
        results[f"win_pick_AE_by_price_dev_{lab}"] = {str(k): [int(r.n), float(r.ae)] for k, r in g.iterrows()}
    json.dump(results, open(os.path.join(HERE, "card_rules.json"), "w"), indent=1, default=float)
    # short table
    def row(x):
        return f"{x.get('bets', 0):>6} {x.get('strike', float('nan')):>6} {x.get('roi', float('nan')):>7} [{x.get('lo', float('nan'))}, {x.get('hi', float('nan'))}]"
    for key in ("T2", "T2_alpha114", "T10", "T30_market_same_races"):
        print(f"\n== {key}  (bets strike ROI% [95%])")
        for name, r in results[key].items():
            print(f"-- {name}: {r['races']} races, {r['days']} days")
            for kind in ("win", "win_chance_weighted", "place", "each_way", "each_way_chance_weighted", "value", "favourite_win", "all_runners_win", "win_fields14plus", "each_way_fields14plus"):
                print(f"   {kind:<26}{row(r[kind])}")
    print("\n== variants (dev only)")
    for k, v in results["variants_dev_only"].items():
        print(f"   {k:<26}{row(v)}")
    print("\nalpha pick changes (dev):", results["alpha_pick_changes_dev"])
    for lab in ("alpha1", "alpha114"):
        print(f"win pick A/E by price, dev, {lab}:", results[f"win_pick_AE_by_price_dev_{lab}"])


if __name__ == "__main__":
    main()
