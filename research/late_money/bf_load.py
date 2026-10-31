"""Betfair data scientists' ANZ thoroughbred files (data branch betfair/raw) -> one table keyed by (date, venue slug, race no, tab number)."""
import glob, io, os, re, sys, zipfile
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lm_lib as L
COLS = ["LOCAL_MEETING_DATE", "TRACK", "STATE_CODE", "RACE_NO", "TAB_NUMBER", "SELECTION_NAME", "WIN_RESULT", "WIN_BSP", "PLACE_RESULT", "PLACE_BSP", "RACING_TYPE", "DISTANCE"]
frames = []
for f in sorted(glob.glob(f"{L.LM}/raw/betfair/raw/ANZ_Thoroughbreds_202[3-6]*")):
    if f.endswith(".zip"):
        z = zipfile.ZipFile(f)
        for n in z.namelist():
            frames.append(pd.read_csv(io.BytesIO(z.read(n)), usecols=COLS))
    else:
        frames.append(pd.read_csv(f, usecols=COLS))
b = pd.concat(frames, ignore_index=True)
b = b[b["RACING_TYPE"] == "Thoroughbred"]
slug = lambda s: re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")
b["venue"] = b["TRACK"].map(slug); d0 = b["LOCAL_MEETING_DATE"].astype(str)
d1 = pd.to_datetime(d0, format="%Y-%m-%d", errors="coerce").fillna(pd.to_datetime(d0, format="%d/%m/%Y", errors="coerce"))
assert d1.notna().all()
b["date"] = d1.dt.strftime("%Y-%m-%d")
b = b.rename(columns={"RACE_NO": "race_number", "TAB_NUMBER": "entry_no", "WIN_BSP": "bf_win", "PLACE_BSP": "bf_place", "DISTANCE": "bf_dist", "STATE_CODE": "bf_state", "WIN_RESULT": "bf_win_res", "PLACE_RESULT": "bf_place_res"})
b["entry_no"] = pd.to_numeric(b["entry_no"], errors="coerce")
b = b.drop_duplicates(["date", "venue", "race_number", "entry_no"])
b = b[["date", "venue", "bf_state", "bf_dist", "race_number", "entry_no", "bf_win", "bf_place", "bf_win_res", "bf_place_res"]]
os.makedirs(f"{L.LM}/prep", exist_ok=True)
b.to_pickle(f"{L.LM}/prep/betfair.pkl")
print(len(b), b["date"].min(), b["date"].max(), b["bf_win"].notna().mean(), b["bf_place"].notna().mean())
