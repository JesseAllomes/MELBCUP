"""Bet rules and settlement, shared by tune.py (development, out-of-fold) and test.py (the one test block).
Win: settle at the Sportsbet price at T (q_sb), 1 unit stake. Place / each-way: settle at the stored last Sportsbet place price (the only
point-in-time place price in the archive; it is about the jump, so place and each-way are only meaningful at T-2). Exotics: settled at the
stored tote dividend per $1 unit, cost = number of combinations. Multis: product of the legs' Sportsbet prices at their own T."""
import itertools
import numpy as np
import pandas as pd
import lm_lib as L


def split_races(O):
    rid = O["race_id"].to_numpy()
    st = np.r_[0, np.flatnonzero(rid[1:] != rid[:-1]) + 1, len(rid)]
    return [(st[i], st[i + 1]) for i in range(len(st) - 1)]


def rank_in_race(O, col):
    return O.groupby("race_id")[col].rank(ascending=False, method="first")


# ------------------------------------------------------------------ win
def win_rule(O, pcol, edge, pmin, topk=None, price="q_sb"):
    p, q = O[pcol], O[price]
    sel = q.notna() & (p * q - 1 >= edge) & (p >= pmin)
    if topk:
        sel &= rank_in_race(O, pcol) <= topk
    b = O[sel].copy()
    b["stake"] = 1.0; b["ret"] = np.where(b["won"], b[price], 0.0); b["profit"] = b["ret"] - 1.0
    b["edge_est"] = (b[pcol] * b[price] - 1)
    return b


# ------------------------------------------------------------------ place and each-way (Plackett-Luce chances from the chosen win chances)
def place_chances(O, pcol):
    out = np.full(len(O), np.nan); kk = np.zeros(len(O), int)
    p = O[pcol].to_numpy(); n = O["n_starters"].to_numpy()
    for a, b in split_races(O):
        k = 3 if (b - a) >= 8 else 2 if (b - a) >= 5 else 0
        if k:
            out[a:b] = L.place_probs(p[a:b], k); kk[a:b] = k
    return out, kk


def place_rule(O, pcol, edge, pmin, topk=None, mode="place"):
    """mode place: back to place; ew: half win at q_sb, half place at the stored place price. pmin applies to the WIN chance."""
    P, k = place_chances(O, pcol) if "plc_" + pcol not in O else (O["plc_" + pcol].to_numpy(), O["plc_k"].to_numpy())
    q, pp = O["q_sb"].to_numpy(), O["sb_place"].to_numpy()
    placed = (O["finish_pos"].to_numpy() <= k) & (k > 0)
    p = O[pcol].to_numpy()
    if mode == "place":
        ev = P * pp - 1; ret = np.where(placed, pp, 0.0) - 1
    else:
        ev = 0.5 * (p * q - 1) + 0.5 * (P * pp - 1)
        ret = 0.5 * (np.where(O["won"].to_numpy(), q, 0.0) - 1) + 0.5 * (np.where(placed, pp, 0.0) - 1)
    sel = np.isfinite(ev) & (k > 0) & (ev >= edge) & (p >= pmin) & np.isfinite(pp) & (pp > 1) & np.isfinite(q)
    if topk:
        sel &= (rank_in_race(O, pcol) <= topk).to_numpy()
    b = O[sel].copy(); b["stake"] = 1.0; b["profit"] = ret[sel]; b["ret"] = b["profit"] + 1.0
    b["won"] = placed[sel]          # strike rate for place / each-way = placed
    return b


# ------------------------------------------------------------------ exotics
COMBOS = {"quin2": 1, "quin3": 3, "quin4": 6, "exa2": 1, "exaBox3": 6, "tri3": 6, "tri4": 24, "ff4": 24}
POOL = {"quin2": "Quinella", "quin3": "Quinella", "quin4": "Quinella", "exa2": "Exacta", "exaBox3": "Exacta", "tri3": "Trifecta", "tri4": "Trifecta", "ff4": "First Four"}


def exotic_table(O, pcol):
    """one row per race: hit chances of every structure and the chosen entry numbers, from win chances pcol."""
    rows = []
    p_all = O[pcol].to_numpy(); ent = O["entry_no"].to_numpy()
    for a, b in split_races(O):
        p = p_all[a:b]
        if len(p) < 5:
            continue
        o = np.argsort(-p)[:4]
        r = dict(race_id=O["race_id"].iat[a], day=O["day"].iat[a], date=O["date"].iat[a], ent_top=tuple(int(ent[a + i]) for i in o))
        r["quin2"] = L.box_hit(p, o[:2], "quin"); r["quin3"] = L.box_hit(p, o[:3], "quin"); r["quin4"] = L.box_hit(p, o[:4], "quin")
        r["exa2"] = L.box_hit(p, o[:2], "exacta1"); r["exaBox3"] = L.box_hit(p, o[:3], "exacta")
        r["tri3"] = L.box_hit(p, o[:3], "tri"); r["tri4"] = L.box_hit(p, o[:4], "tri"); r["ff4"] = L.box_hit(p, o[:4], "ff")
        rows.append(r)
    return pd.DataFrame(rows)


def parse_exo(exo_rows):
    """exo_rows from extras.pkl -> {(race_id, pool): (tuple of entry numbers, dividend)} for the plain pools only."""
    d = {}
    for rid, pool, sel, _amt, raw in exo_rows:
        if pool in ("Quinella", "Exacta", "Trifecta", "First Four") and raw and sel:
            try:
                s = tuple(int(x) for x in sel.split("/"))
                amt = float(str(raw).replace("$", "").replace(",", ""))      # dividends of $1,000+ carry a thousands comma
            except ValueError:
                continue
            if not amt > 0:
                continue
            if (rid, pool) in d:
                d[(rid, pool)] = None          # two dividend lines (dead heat): not settled
            else:
                d[(rid, pool)] = (s, float(amt))
    return d


def exotic_settle(T, kind, thr, exo, race_set=None):
    """T: exotic_table; bet kind when its hit chance >= thr. Races whose pool dividend is not stored are not bets."""
    rows = []
    for r in T.itertuples(index=False):
        h = getattr(r, kind)
        if h < thr:
            continue
        dv = exo.get((r.race_id, POOL[kind]))
        if not dv:
            continue
        s, div = dv
        top = r.ent_top
        if kind in ("quin2", "quin3", "quin4"):
            n = int(kind[-1]); hit = set(s) <= set(top[:n])
        elif kind == "exa2":
            hit = tuple(s) == tuple(top[:2])
        elif kind == "exaBox3":
            hit = set(s) <= set(top[:3])
        elif kind == "tri3":
            hit = set(s) <= set(top[:3])
        elif kind == "tri4":
            hit = set(s) <= set(top[:4])
        else:
            hit = set(s) <= set(top[:4])
        cost = COMBOS[kind]
        rows.append(dict(race_id=r.race_id, day=r.day, date=r.date, hit_chance=h, stake=float(cost), ret=div if hit else 0.0, profit=(div if hit else 0.0) - cost, won=hit))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ summaries
def summarise(b, all_days, n_boot=2000, seed=11):
    """b: bets with day, stake, profit, won. all_days: every race day with eligible races in the block (zero-bet days included)."""
    if len(b) == 0:
        return dict(bets=0, wins=0, strike=np.nan, roi=np.nan, roi_lo=np.nan, roi_hi=np.nan, per_day=0.0, per_day_lo=0.0, per_day_hi=0.0, staked=0.0, profit=0.0)
    g = b.groupby("day").agg(profit=("profit", "sum"), stake=("stake", "sum"), wins=("won", "sum"), n=("stake", "size"))
    g = g.reindex(all_days).fillna(0.0)
    vals = g[["profit", "stake", "wins", "n"]].to_numpy()
    nd = len(all_days)
    roi, ci = L.day_bootstrap(g.index.to_numpy(), vals, lambda s: s[0] / s[1] if s[1] > 0 else np.nan, n=n_boot, seed=seed)
    pd_, cd = L.day_bootstrap(g.index.to_numpy(), vals, lambda s: s[0] / nd, n=n_boot, seed=seed)
    return dict(bets=int(len(b)), wins=int(b["won"].sum()), strike=float(b["won"].mean()), roi=float(roi), roi_lo=float(ci[0]), roi_hi=float(ci[1]),
                per_day=float(pd_), per_day_lo=float(cd[0]), per_day_hi=float(cd[1]), staked=float(b["stake"].sum()), profit=float(b["profit"].sum()))


def growth(b, f=0.01):
    """declared dev objective: expected log growth at a fixed fraction f of bankroll per unit staked (per-bet return r = profit/stake)."""
    if len(b) == 0:
        return 0.0
    r = (b["profit"] / b["stake"]).to_numpy()
    return float(np.log1p(f * r).sum())


# ------------------------------------------------------------------ multis (doubles of consecutive legs, each leg its best frozen win bet)
def doubles(wb, race_no):
    """wb: win bets (one or more per race); race_no: Series race_id -> (meeting_id, race_number). Best bet (highest estimated edge) per race;
    pair consecutive race numbers in the same meeting."""
    best = wb.sort_values("edge_est", ascending=False).drop_duplicates("race_id").copy()
    best["mtg"] = best["race_id"].map(lambda r: r.split("_")[0]); best["rn"] = best["race_id"].map(lambda r: int(r.split("_")[1]))
    best = best.sort_values(["mtg", "rn"])
    rows = []
    for _, g in best.groupby("mtg"):
        g = g.sort_values("rn").to_dict("records")
        for x, y in zip(g[:-1], g[1:]):
            if y["rn"] - x["rn"] == 1:
                won = bool(x["won"] and y["won"]); price = x["q_sb"] * y["q_sb"]
                rows.append(dict(race_id=x["race_id"], day=x["day"], stake=1.0, profit=(price if won else 0.0) - 1.0, won=won))
    return pd.DataFrame(rows)
