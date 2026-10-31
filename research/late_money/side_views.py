"""Side views (descriptive, nothing tuned): Melbourne Cups in the archive (prices only plus who won), and why the frozen win rule fires."""
import json, os, pickle, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lm_lib as L
rn = pd.read_pickle(f"{L.LM}/prep/paths.pkl")
cup = rn[(rn["venue"].astype(str) == "flemington") & rn["race_name"].astype(str).str.fullmatch(r"(?i)(lexus )?melbourne cup") & rn["starter"]].copy()
rows = []
for rid, g in cup.groupby("race_id"):
    g = g.copy()
    mv = lambda a, b: np.log(g[f"sb_{a}"] / g[f"sb_{b}"])
    g["firm_open_jump"] = np.exp(mv("open", "t0")) - 1; g["firm_60_jump"] = np.exp(mv("t60", "t0")) - 1; g["firm_15_jump"] = np.exp(mv("t15", "t0")) - 1
    w = g[g["won"] == True]
    if len(w) != 1:
        continue
    w = w.iloc[0]
    top3 = g.sort_values("sb_t0").head(3)["firm_open_jump"]
    g["rank_t0"] = g["sb_t0"].rank(method="min")
    rows.append(dict(date=str(g["date"].iloc[0])[:10], starters=len(g), winner=w["horse_code"], sb_open=w["sb_open"], sb_t60=w["sb_t60"], sb_t10=w["sb_t10"], sb_jump=w["sb_t0"], sp=w["sp"],
                     winner_rank_at_jump=int(g.loc[w.name, "rank_t0"]), winner_firm_open_to_jump=w["firm_open_jump"], winner_firm_last15=w["firm_15_jump"],
                     runners_firming_20pct=int((g["firm_open_jump"] >= 0.2 / 0.8 * 0.8).sum()), runners_drifting_25pct=int((g["firm_open_jump"] <= -0.25 / 1.25).sum())))
C = pd.DataFrame(rows).sort_values("date"); print(C.round(2).to_string(index=False))
# the cup winners' late move: did they firm? and the share of Cup runners that firmed 20%+ that won
c = cup.assign(f=lambda x: np.log(x["sb_open"] / x["sb_t0"]), f15=lambda x: np.log(x["sb_t15"] / x["sb_t0"]))
for name, m in (("firm >=20% open to jump", c["f"] >= np.log(1 / 0.8)), ("drift >=25% open to jump", c["f"] <= -np.log(1.25)), ("firm >=10% in last 15 min", c["f15"] >= np.log(1 / 0.9))):
    print(name, "runners", int(m.sum()), "wins", int(c.loc[m, "won"].sum()), "sum of jump-price chance (1/price)", round(float((1 / c.loc[m, "sb_t0"]).sum()), 2))
# why the frozen win rule fires: development bets' Sportsbet vs Ladbrokes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bets as B
O = pd.read_pickle(f"{L.LM}/out/oof_T2.pkl"); b = B.win_rule(O, "p_MS", 0.02, 0.10)
print("dev bets", len(b), "median SB/LB price ratio at T", round(float((b["q_sb"] / b["q_lb"]).median()), 3), "all-runner median", round(float((O["q_sb"] / O["q_lb"]).median()), 3),
      "bets where SB price >= 1.10 x LB", int(((b["q_sb"] / b["q_lb"]) >= 1.10).sum()), "median |open to T move| of bets", round(float(np.exp(b["mO"].abs()).median() - 1), 3))
C.to_json(f"{L.LM}/out/cups.json", orient="records")
