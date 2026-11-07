"""Clean racing datasets from the raw downloads (see fetch.py).

Writes to OUT:
  dataset.csv.gz   one row per starter (racing.com, Australia, 2022-07..2026-10), with results,
                   Sportsbet/Ladbrokes/tote win prices and a Betfair BSP join where matched.
  betfair.csv.gz   one row per runner from the Betfair public BSP files (ANZ, 2020..2026-09).
  build_meta.json  row counts, seasons, join rate.
Rules: scratched runners are dropped; a race is kept only if it has a recorded winner;
dead-heats give each winner win=1 (price stays the same, noted in meta); prices <= 1 are null.
"""

import glob
import gzip
import io
import json
import os
import re
import sys
import zipfile
from multiprocessing import Pool

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import OUT, RAW, price, season  # noqa: E402

PROV = {"SB2": "sb", "LB2": "lb", "N": "tote_n", "V": "tote_v", "Q": "tote_q"}
MEETINGS_FILE_RE = re.compile(r"(\d{4}-\d\d-\d\d)_")


BAD_FILES: list[str] = []


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def parse_meeting(path: str) -> list[dict]:
    """All starters of one racing.com meeting dump."""
    try:
        d = json.load(gzip.open(path))
    except (EOFError, OSError, ValueError):
        return [{"_bad": os.path.basename(path)}]
    out = []
    for r in d.get("races") or []:
        entries = [e for e in r.get("formRaceEntries") or [] if not e.get("scratched")]
        if not entries or not any(e.get("finish") == 1 for e in entries):
            continue
        dist = re.sub(r"\D", "", r.get("distance") or "") or None
        for e in entries:
            row = {
                "date": d["date"],
                "meeting_id": d["id"],
                "venue": d["venueName"],
                "state": d["state"],
                "race_no": r["raceNumber"],
                "distance": dist,
                "class": r.get("class"),
                "group": r.get("group"),
                "track_condition": r.get("trackCondition"),
                "surface": r.get("trackSurface"),
                "field_size": len(entries),
                "tab": e.get("raceEntryNumber"),
                "horse_code": e.get("horseCode"),
                "barrier": e.get("barrierNumber"),
                "weight_kg": (re.sub(r"[^0-9.]", "", e.get("weightCarried") or "") or None),
                "rating": e.get("handicapRating"),
                "jockey": e.get("jockeyCode"),
                "trainer": e.get("trainerCode"),
                "age": (e.get("horse") or {}).get("age"),
                "sex": (e.get("horse") or {}).get("sex"),
                "finish": e.get("finish"),
                "sp": price(e.get("startingPrice")),
                "bf_open": price(e.get("bettingFluctuationsPriceOpen")),
            }
            for o in e.get("odds") or []:
                k = PROV.get(o.get("providerCode"))
                if k:
                    row[k] = price(o.get("oddsWin"))
                    row[k + "_place"] = price(o.get("oddsPlace"))
            sb = (e.get("sb") or [{}])[0].get("flucsWin") or []
            row["sb_first"] = price(sb[0]["amount"]) if sb else None
            out.append(row)
    return out


def build_racing() -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(RAW, "big", "meetings", "*.json.gz")))
    with Pool(4) as p:
        rows = [r for part in p.imap(parse_meeting, files, chunksize=50) for r in part]
    bad = [r["_bad"] for r in rows if "_bad" in r]
    rows = [r for r in rows if "_bad" not in r]
    df = pd.DataFrame(rows)
    BAD_FILES[:] = bad
    for c in ["distance", "weight_kg", "age"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["win"] = (df["finish"] == 1).astype(int)
    df["top3"] = (df["finish"].between(1, 3)).astype(int)
    df["season"] = df["date"].map(season)
    df["vkey"] = df["venue"].map(norm)
    return df.sort_values(["date", "meeting_id", "race_no", "tab"]).reset_index(drop=True)


def read_betfair() -> pd.DataFrame:
    frames = []
    for p in sorted(glob.glob(os.path.join(RAW, "betfair", "raw", "ANZ_Thoroughbreds_*"))):
        if p.endswith(".zip"):
            with zipfile.ZipFile(p) as z:
                for n in z.namelist():
                    frames.append(pd.read_csv(io.BytesIO(z.read(n))))
        else:
            frames.append(pd.read_csv(p))
    b = pd.concat(frames, ignore_index=True)
    iso = b["LOCAL_MEETING_DATE"].astype(str).str.match(r"^\d{4}-\d\d-\d\d$")
    # one monthly file (2025-04) uses d/mm/yyyy
    b.loc[~iso, "LOCAL_MEETING_DATE"] = pd.to_datetime(
        b.loc[~iso, "LOCAL_MEETING_DATE"], format="%d/%m/%Y"
    ).dt.strftime("%Y-%m-%d")
    b = b[b["RACING_TYPE"] == "Thoroughbred"]
    out = pd.DataFrame(
        {
            "date": b["LOCAL_MEETING_DATE"],
            "track": b["TRACK"],
            "state": b["STATE_CODE"],
            "race_no": b["RACE_NO"],
            "distance": b["DISTANCE"],
            "tab": b["TAB_NUMBER"],
            "selection": b["SELECTION_NAME"],
            "win": (b["WIN_RESULT"] == "WINNER").astype(int),
            "bsp": b["WIN_BSP"],
            "bsp_volume": b["WIN_BSP_VOLUME"],
            "preplay_wavg": b["WIN_PREPLAY_WEIGHTED_AVERAGE_PRICE_TAKEN"],
            "preplay_volume": b["WIN_PREPLAY_VOLUME"],
            "back_at_off": b["BEST_AVAIL_BACK_AT_SCHEDULED_OFF"],
            "lay_at_off": b["BEST_AVAIL_LAY_AT_SCHEDULED_OFF"],
            "place_win": (b["PLACE_RESULT"] == "WINNER").astype(int),
            "place_bsp": b["PLACE_BSP"],
        }
    )
    for c in ["bsp", "preplay_wavg", "back_at_off", "lay_at_off", "place_bsp"]:
        out[c] = out[c].where(out[c] > 1.0)
    out = out[out["bsp"].notna() | out["preplay_wavg"].notna()]
    out = out.drop_duplicates(["date", "track", "race_no", "tab", "selection"])
    out["season"] = out["date"].map(season)
    out["vkey"] = out["track"].map(norm)
    # keep only races with a winner
    has_w = out.groupby(["date", "vkey", "race_no"])["win"].transform("max")
    return out[has_w == 1].reset_index(drop=True)


MANUAL_ALIAS = {"thevalley": "mooneevalley"}


def venue_alias(df: pd.DataFrame, bf: pd.DataFrame) -> dict[str, str]:
    """racing.com venue key -> Betfair track key. Sponsored names ('ladbrokes-geelong',
    'royal-randwick') contain the Betfair name; resolved by same-date containment, most common
    winner per venue, plus a small manual list."""
    on_date = bf.groupby("date")["vkey"].agg(lambda s: sorted(set(s))).to_dict()
    votes: dict[str, dict[str, int]] = {}
    for date, vk in df[["date", "vkey"]].drop_duplicates().itertuples(index=False):
        for b in on_date.get(date, []):
            if len(b) >= 4 and (b == vk or b in vk or vk in b):
                votes.setdefault(vk, {}).setdefault(b, 0)
                votes[vk][b] += 1
    alias = {vk: max(v.items(), key=lambda kv: (kv[1], len(kv[0])))[0] for vk, v in votes.items()}
    alias.update(MANUAL_ALIAS)
    return alias


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    df, bf = build_racing(), read_betfair()
    alias = venue_alias(df, bf)
    df["vkey"] = df["vkey"].map(lambda v: alias.get(v, v))
    key = ["date", "vkey", "race_no", "tab"]
    j = bf[key + ["bsp", "preplay_wavg", "bsp_volume"]].drop_duplicates(key)
    df = df.merge(j, on=key, how="left")
    meta = {
        "racing_rows": len(df),
        "racing_races": int(df.groupby(["meeting_id", "race_no"]).ngroups),
        "racing_seasons": sorted(df["season"].unique().tolist()),
        "racing_rows_by_season": df["season"].value_counts().sort_index().to_dict(),
        "betfair_rows": len(bf),
        "betfair_races": int(bf.groupby(["date", "vkey", "race_no"]).ngroups),
        "betfair_rows_by_season": bf["season"].value_counts().sort_index().to_dict(),
        "betfair_join_rate_of_racing_rows": float(df["bsp"].notna().mean()),
        "sportsbet_price_coverage": float(df["sb"].notna().mean()),
        "unreadable_meeting_files": BAD_FILES,
        "dead_heat_races": int((df.groupby(["meeting_id", "race_no"])["win"].sum() > 1).sum()),
    }
    df.drop(columns=["vkey"]).to_csv(os.path.join(OUT, "dataset.csv.gz"), index=False)
    bf.drop(columns=["vkey"]).to_csv(os.path.join(OUT, "betfair.csv.gz"), index=False)
    json.dump(meta, open(os.path.join(OUT, "build_meta.json"), "w"), indent=1, default=int)
    print(json.dumps(meta, indent=1, default=int))


if __name__ == "__main__":
    main()
