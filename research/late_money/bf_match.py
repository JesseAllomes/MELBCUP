"""Match racing.com races to Betfair races without relying on venue names (racing.com slugs carry sponsor prefixes and variants).
Candidates: same Melbourne meeting date, same race number, distance within 150 m, identical set of tab numbers. Ties are resolved by the
correlation between ln(Betfair SP) and ln(Sportsbet price at T-2) (prices only, no outcomes); accept only corr >= 0.9 and a clear winner."""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lm_lib as L, lm_model as M


def build_map(D):
    bf = pd.read_pickle(f"{L.LM}/prep/betfair.pkl")
    g = bf.groupby(["date", "venue", "race_number"])
    br = g.agg(bf_state=("bf_state", "first"), bf_dist=("bf_dist", "first"), tabs=("entry_no", lambda s: frozenset(s.dropna().astype(int))), n=("entry_no", "size")).reset_index()
    prices = {k: v for k, v in bf.groupby(["date", "venue", "race_number"])}
    by_key = {k: v for k, v in br.groupby(["date", "race_number"])}
    rows = []
    for rid, r in D.groupby("race_id", sort=False):
        key = (r["dstr"].iat[0], int(r["race_number"].iat[0]))
        cand = by_key.get(key)
        if cand is None:
            rows.append((rid, None, "no_bf_race")); continue
        tabs = frozenset(r["entry_no"].astype(int)); dist = r["distance_m"].iat[0]
        c = cand[(cand["tabs"] == tabs) & ((cand["bf_dist"] - dist).abs() <= 150)]
        if len(c) == 0:
            c = cand[(cand["tabs"].map(lambda t: tabs <= t)) & ((cand["bf_dist"] - dist).abs() <= 150)]   # Betfair lists a scratched runner we do not
        if len(c) == 0:
            rows.append((rid, None, "no_candidate")); continue
        if len(c) == 1:
            p = prices[(key[0], c["venue"].iat[0], key[1])][["entry_no", "bf_win"]].dropna()
            m = r[["entry_no", "q_sb"]].merge(p, on="entry_no")
            cor = np.corrcoef(np.log(m["q_sb"]), np.log(m["bf_win"]))[0, 1] if len(m) >= 3 else np.nan
            rows.append((rid, c["venue"].iat[0], "unique") if (cor >= 0.8 or not np.isfinite(cor)) else (rid, None, "low_price_corr")); continue
        sc = []
        for v in c["venue"]:
            p = prices[(key[0], v, key[1])][["entry_no", "bf_win"]].dropna()
            m = r[["entry_no", "q_sb"]].merge(p, on="entry_no")
            sc.append(np.corrcoef(np.log(m["q_sb"]), np.log(m["bf_win"]))[0, 1] if len(m) >= 3 else -1)
        o = np.argsort(sc)[::-1]
        if sc[o[0]] >= 0.9 and (len(sc) == 1 or sc[o[0]] - sc[o[1]] >= 0.05):
            rows.append((rid, c["venue"].iloc[o[0]], "price_tiebreak"))
        else:
            rows.append((rid, None, "ambiguous"))
    return pd.DataFrame(rows, columns=["race_id", "bf_venue", "how"])
