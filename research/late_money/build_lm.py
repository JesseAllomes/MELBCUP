"""LATE-MONEY COPY of research/dataset/build.py (only SNAP_MINS and EXAMINED_CSV changed).
Incremental builder: racing.com meeting dumps -> runner-level + race-level tables.

Usage (system python, isolated mode):
    MELBCUP_ROOT=<folder> python3 -I build.py [--no-csv] [--max-files N] [--force-reparse]

Stage 1 (parse): each meetings/*.json.gz is parsed ONCE into a flat per-runner DataFrame cached in cache/<file>.pkl
                 (re-parsed only if the source size/mtime changes or PARSER_VER is bumped).
Stage 2 (assemble): all cached meetings are concatenated and every derived column (market normalisation,
                 point-in-time history, jockey/trainer form, race table) is recomputed from scratch (fast, a few minutes
                 at full size).  Outputs go to out/.
"""
import sys, os, re, hashlib, gzip, json, glob, time, pickle, calendar, datetime, bisect, argparse
import warnings
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore', category=pd.errors.PerformanceWarning)
warnings.filterwarnings('ignore', message='This pattern is interpreted')

ROOT = os.environ.get("MELBCUP_ROOT", "")   # folder holding big/meetings (dumps) and upsets/ (cache, out); the original run used the session scratchpad
if not ROOT:
    sys.exit("set MELBCUP_ROOT to the folder that holds big/meetings and upsets/")
SRC = f"{ROOT}/big/meetings"
BASE = f"{ROOT}/upsets"
CACHE = f"{BASE}/cache"
OUT = f"{BASE}/out"

PARSER_VER = 7            # bump when parse_meeting() output changes
HIST_BUFFER_DAYS = 90     # history features trusted only this many days after contiguous coverage start
MIN_QUOTE_COVERAGE = 0.80  # share of starters that must be quoted to normalise a market
FEED_STALE_MIN = 15.0      # book feed considered dead for a race if its last pre-start fluc is older than this
MIN_GAP_RUN_DAYS = 3       # >= this many consecutive days with zero AU meetings = collection gap
AU_STATES = {"NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT"}   # HK etc. dropped from outputs
COLLECTION_YEAR = 2026
EXAMINED_CSV = "/home/user/MELBCUP/research/examined.csv"      # read-only input
FEED_LIVE_S = 900          # protocol v0.5: each book needs >=1 fluc on any entry of the race in [T-900s, T]
BLOCKS = [("history_only", "2022-07-01", "2022-12-31"), ("train", "2023-01-01", "2025-06-30"), ("tune1", "2025-07-01", "2025-12-31"), ("tune2", "2026-01-01", "2026-04-30"), ("final", "2026-05-01", "2026-09-28"), ("excluded", "2026-09-29", "2026-10-29")]
SP_OVERROUND_MIN, SP_OVERROUND_MAX = 1.05, 1.50   # race SP book outside this range is flagged sp_quality_ok=False
SNAP_MINS = (60, 30, 10, 2)
PARSE_SNAP_MINS = (60, 30, 10, 5, 2)   # late-money study: the parse stage also keeps the raw T-5 quote (sb_t5, lb_t5, ages); the assembly stays at the original four times because more times run out of memory (15 GB); T-120, T-15 and the jump price come from extras.py
BOOKS = ("sb", "lb")
ODDS_CODES = ("V", "N", "Q", "BT", "PB3", "BTOTE", "OP")
_INTERN = {}
CAT_COLS = ["venue", "state", "class_raw", "class_rdc", "race_type", "group", "track_cond", "track_cond_src", "surface",
            "rail", "weather", "rainfall", "race_tempo", "race_timing_source", "sex", "sire", "dam", "jockey_id", "jockey", "trainer_id", "trainer",
            "horse_name", "sire_of_dam_code", "gear_changes", "race_name"]
INTERN_COLS = CAT_COLS + ["meeting_id", "date", "start_iso", "horse_code"]


def rss():
    try:
        d = dict(l.split(":", 1) for l in open("/proc/self/status").read().splitlines() if ":" in l)
        return f"rss {int(d['VmRSS'].split()[0])/1024:.0f}MB peak {int(d['VmHWM'].split()[0])/1024:.0f}MB"
    except Exception:
        return ""


# ----------------------------------------------------------------------------------------------- parsing helpers
def f_price(s):
    if s is None:
        return np.nan
    try:
        v = float(str(s).replace("$", "").strip())
    except ValueError:
        return np.nan
    return v if v > 1.0 else np.nan


def f_num(s):
    if s is None:
        return np.nan
    try:
        return float(s)
    except (TypeError, ValueError):
        return np.nan


def f_len(s):  # "1.5L" / "-13.38L" -> float lengths
    if s is None:
        return np.nan
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*L?\s*$", str(s))
    return float(m.group(1)) if m else np.nan


def f_kg(s):
    if s is None:
        return np.nan
    m = re.match(r"^\s*(\d+(?:\.\d+)?)", str(s))
    return float(m.group(1)) if m else np.nan


def f_pos(s):  # "4th" -> 4
    if s is None:
        return np.nan
    m = re.match(r"^\s*(\d+)", str(s))
    return float(m.group(1)) if m else np.nan


def f_dist(s):
    if s is None:
        return np.nan
    m = re.match(r"^\s*(\d+)", str(s))
    return float(m.group(1)) if m else np.nan


def f_age(s):
    if s is None:
        return np.nan
    m = re.match(r"^\s*(\d+)", str(s))
    return float(m.group(1)) if m else np.nan


def f_start(t):  # '2026-09-16T06:48:00.000Z' / '...00.0000000Z' -> (iso19, epoch)
    t19 = t[:19]
    return t19, calendar.timegm(time.strptime(t19, "%Y-%m-%dT%H:%M:%S"))


def snapshot(flucs, start_ts):
    """flucs: list of {updateTime, amount}. returns dict of open price/min and price at T-x (last fluc <= start-x*60)."""
    out = {}
    pts = []
    for x in flucs or []:
        p = f_price(x.get("amount"))
        t = x.get("updateTime")
        if t is not None and p == p:
            pts.append((t, p))
    pts.sort()
    times = [t for t, _ in pts]
    out["open"] = pts[0][1] if pts else np.nan
    out["open_min"] = (start_ts - pts[0][0]) / 60.0 if pts else np.nan
    out["n_flucs"] = len(pts)
    out["last_any"] = pts[-1][0] if pts else None   # last fluc ever (scratch dating)
    out["n_same_prev"] = sum(1 for k in range(1, len(pts)) if pts[k][1] == pts[k - 1][1])   # change-event check
    n_pre = bisect.bisect_right(times, start_ts)     # flucs at or before the scheduled start
    for T in PARSE_SNAP_MINS:
        cutoff = start_ts - T * 60
        i = bisect.bisect_right(times, cutoff) - 1
        out[f"t{T}"] = pts[i][1] if i >= 0 else np.nan
        out[f"t{T}_age_s"] = float(cutoff - times[i]) if i >= 0 else np.nan
        out[f"t{T}_n_later"] = float(max(0, n_pre - (i + 1))) if i >= 0 else np.nan   # flucs after the quote, up to the scheduled start
    pre = [t for t in times if t <= start_ts]
    out["last_pre"] = pre[-1] if pre else None
    out["final"] = pts[-1][1] if pts else np.nan   # last fluc ever seen (may include a few ticks after scheduled start)
    return out


def parse_meeting(path):
    d = json.load(gzip.open(path))
    mid = str(d["id"])
    tc_by_race = {}
    for x in d.get("trackConditions") or []:
        tc_by_race[x.get("raceNumber")] = x.get("condition")
    rows = []
    skipped = []
    for r in d.get("races") or []:
        if not r.get("time"):                    # a race with no scheduled start cannot be placed in time: skipped and counted
            skipped.append(dict(meeting_id=mid, date=d["date"], state=d.get("state"), race_number=r.get("raceNumber")))
            continue
        entries = r.get("formRaceEntries") or []
        start_iso, start_ts = f_start(r["time"])
        # ---- de-duplicate: some meetings list a race's entries twice (same horseCode)
        by_h = {}
        for e in entries:
            hc = str(e.get("horseCode") or e.get("horseName"))
            by_h.setdefault(hc, []).append(e)
        dup = any(len(v) > 1 for v in by_h.values())
        ents = []
        for hc, v in by_h.items():
            if len(v) > 1:
                # prefer non-scratched, then has result, then last listed
                v = sorted(enumerate(v), key=lambda ie: (not ie[1].get("scratched"), ie[1].get("finish") is not None, ie[0]))
                ents.append(v[-1][1])
            else:
                ents.append(v[0])
        # ---- starters
        anyfin = any((not e.get("scratched")) and e.get("finish") is not None and e["finish"] < 109 for e in ents)
        if anyfin:
            starter = lambda e: (not e.get("scratched")) and e.get("finish") is not None
        else:
            starter = lambda e: (not e.get("scratched")) and (not e.get("emergency"))
        # ---- race level sectional (identical for all runners) / winner time
        ts_vals = [e.get("timeSectional") for e in ents if starter(e) and e.get("timeSectional") not in (None, "0")]
        race_last600 = f_num(ts_vals[0]) / 100.0 if ts_vals else np.nan
        cond = r.get("trackCondition")
        cond_src = "race"
        rating = r.get("trackRating")
        if not cond:
            cond, cond_src = d.get("trackCondition"), "meeting"
            if rating is None:
                rating = d.get("trackRating")
            if not cond and tc_by_race.get(r["raceNumber"]):
                cond, cond_src = tc_by_race[r["raceNumber"]].split(" ")[0], "trackConditions"
        for e in ents:
            tm = e.get("timing") or {}
            secs = {x.get("distance"): x for x in (tm.get("times") or [])}
            def sec(k):
                return f_num((secs.get(k) or {}).get("sectionTime"))
            s4, s2, sf = sec("400m"), sec("200m"), sec("FINISH")
            last600 = s4 + s2 + sf  # NaN if any missing
            horse = e.get("horse") or {}
            row = dict(
                meeting_id=mid, date=d["date"], venue=d.get("venueName"), state=d.get("state"),
                race_number=int(r["raceNumber"]), start_iso=start_iso, start_ts=start_ts,
                race_name=r.get("name"),
                distance_m=f_dist(r.get("distance")), class_raw=r.get("class"), class_rdc=r.get("rdcClass"),
                race_type=r.get("raceType"), group=r.get("group"),
                track_cond=cond, track_cond_src=cond_src, track_rating=f_num(rating),
                surface=r.get("trackSurface"), runners_count_api=r.get("runnersCount"),
                rail=d.get("railPosition"), weather=d.get("weather"), penetrometer=f_num(d.get("penetrometer")),
                rainfall=d.get("rainfall"),
                dup_entries=dup, race_has_result=anyfin,
                # post-race race-level info
                race_tempo=r.get("tempo"), race_winning_time_s=f_num(r.get("winningTime")) / 100.0,
                race_has_sectionals=bool(r.get("hasSectionals")), race_timing_source=r.get("timingSource"),
                race_std_time_diff_len=f_len(r.get("standardTimeDifference")), race_last600_s=race_last600,
                # runner
                horse_code=str(e.get("horseCode") or e.get("horseName")), horse_name=e.get("horseName"),
                entry_no=e.get("raceEntryNumber"),
                scratched=bool(e.get("scratched")), emergency=bool(e.get("emergency")), starter=bool(starter(e)),
                barrier=(np.nan if not e.get("barrierNumber") else float(e["barrierNumber"])),
                weight_kg=f_kg(e.get("weightCarried")),
                jockey_id=(str(e["jockeyCode"]) if e.get("jockeyCode") else e.get("jockeyName")), jockey=e.get("jockeyName"),
                trainer_id=(str(e["trainerCode"]) if e.get("trainerCode") else e.get("trainerName")), trainer=e.get("trainerName"),
                handicap_rating=f_num(e.get("handicapRating")), gear_changes=e.get("gearChanges"),
                speed_value=f_num(e.get("speedValue")),
                age=f_age(horse.get("age")), sex=horse.get("sex"), sire=horse.get("sireHorseName"), dam=horse.get("damHorseName"),
                sire_of_dam_code=horse.get("sireOfDamHorseCode"),
                rc_fluc_open=f_price(e.get("bettingFluctuationsPriceOpen")), rc_fluc_m1=f_price(e.get("bettingFluctuationsPriceMoveOne")),
                rc_fluc_m2=f_price(e.get("bettingFluctuationsPriceMoveTwo")),
                # outcomes (post-race)
                finish_code=e.get("finish"),
                margin_raw_len=f_len(e.get("margin")),
                sp=f_price(e.get("startingPrice")),
                res_settled=f_pos(e.get("positionAtSettledAbv")), res_pos800=f_pos(e.get("positionAt800Abv")),
                res_pos400=f_pos(e.get("positionAt400Abv")),
                res_comment=e.get("commentStewards"),
                res_time_s=f_num(tm.get("finishTimeSeconds")) / 100.0 if tm else np.nan,
                res_top_speed=f_num(tm.get("topSpeed")), res_speed_early=f_num(tm.get("avgSpeedEarly")),
                res_speed_mid=f_num(tm.get("avgSpeedMid")), res_speed_late=f_num(tm.get("avgSpeedLate")),
                res_dist_travelled=f_num(tm.get("distanceTravelled")), res_dist_from_rail=f_num(tm.get("distanceFromRail")),
                res_std_time_diff_len=f_len(tm.get("standardTimeDifference")),
                res_time_sectional_raw=f_num(e.get("timeSectional")) / 100.0,
                res_last600_s=last600, res_last200_s=sf, res_last200_rank_api=f_num((secs.get("FINISH") or {}).get("rank")),
            )
            odds = {o.get("providerCode"): f_price(o.get("oddsWin")) for o in (e.get("odds") or [])}
            for c in ODDS_CODES:
                row[f"final_{c}"] = odds.get(c, np.nan)
            for b in BOOKS:
                fl = (e.get(b) or [{}])[0].get("flucsWin") if e.get(b) else None
                sn = snapshot(fl, start_ts)    # computed for every entry (scratched entries are used to infer late scratchings)
                row[f"{b}_final"] = sn["final"]
                row[f"{b}_open"] = sn["open"]
                row[f"{b}_open_min"] = sn["open_min"]
                row[f"{b}_n_flucs"] = sn["n_flucs"]
                row[f"{b}_last_fluc_min"] = (start_ts - sn["last_pre"]) / 60.0 if sn["last_pre"] is not None else np.nan
                row[f"{b}_last_rel_s"] = float(sn["last_any"] - start_ts) if sn["last_any"] is not None else np.nan
                row[f"{b}_n_same_prev"] = sn["n_same_prev"]
                for T in PARSE_SNAP_MINS:
                    row[f"{b}_t{T}"] = sn[f"t{T}"]
                    row[f"{b}_t{T}_age_s"] = sn[f"t{T}_age_s"]
                    row[f"{b}_t{T}_n_later"] = sn[f"t{T}_n_later"]
            rows.append(row)
    df = pd.DataFrame(rows)
    df.attrs["skipped_no_time"] = skipped
    # feed liveness: per race & book, the latest pre-start fluc among starters
    if len(df):
        for b in BOOKS:
            lm = df[f"{b}_last_fluc_min"].where(df["starter"])
            race_min = lm.groupby(df["race_number"]).transform("min")      # minutes before start of the latest pre-start fluc among starters
            stale = (race_min > FEED_STALE_MIN) | race_min.isna()
            df[f"{b}_feed_stale"] = stale          # flag only: raw quotes/ages are never blanked (ages are explicit)
            df[f"{b}_last_pre_min"] = race_min
    return df


def load_or_parse(files, force=False, log=print):
    os.makedirs(CACHE, exist_ok=True)
    frames, nparsed, nfail, nskip = [], 0, 0, 0
    skipped_all = []
    now = time.time()
    t0 = time.time()
    for i, f in enumerate(files):
        st = os.stat(f)
        key = (PARSER_VER, st.st_size, int(st.st_mtime))
        cp = f"{CACHE}/{os.path.basename(f)}.pkl"
        df = None
        if not force and os.path.exists(cp):
            try:
                with open(cp, "rb") as fh:
                    blob = pickle.load(fh)
                if blob["key"] == key:
                    df = blob["df"]
            except Exception:
                df = None
        if df is None:
            if now - st.st_mtime < 20:      # file may still be being written by the collector
                nskip += 1
                continue
            try:
                df = parse_meeting(f)
            except Exception as ex:   # truncated gz etc.; will be retried next run
                nfail += 1
                log(f"  parse failed {os.path.basename(f)}: {ex!r}")
                continue
            with open(cp + ".tmp", "wb") as fh:
                pickle.dump({"key": key, "df": df}, fh, protocol=4)
            os.replace(cp + ".tmp", cp)
            nparsed += 1
            if nparsed % 200 == 0:
                log(f"  parsed {nparsed} new meetings ({time.time()-t0:.0f}s)")
        skipped_all.extend(df.attrs.get("skipped_no_time", []))
        if len(df):
            for c in INTERN_COLS:             # share identical string objects across meetings (memory)
                df[c] = [_INTERN.setdefault(v, v) for v in df[c].astype(object)]
            frames.append(df)
    log(f"parse stage: {len(files)} files, {nparsed} newly parsed, {nfail} failed, {nskip} skipped (too fresh)")
    out = pd.concat(frames, ignore_index=True)
    del frames
    log(f"  concatenated {len(out)} rows; {rss()}")
    return out, dict(files=len(files), parsed_now=nparsed, failed=nfail, skipped_fresh=nskip, races_skipped_no_start_time=len(skipped_all),
                     races_skipped_no_start_time_list=skipped_all[:200])


# ----------------------------------------------------------------------------------------------- assembly helpers
def rank_in_race(df, group, sort_cols, valid):
    """unique 1..n rank within group over rows where valid, ordering by sort_cols ascending (NaN last)."""
    sub = df.loc[valid, [group] + sort_cols].copy()
    sub = sub.sort_values([group] + sort_cols, na_position="last", kind="mergesort")
    r = sub.groupby(group, sort=False).cumcount() + 1
    out = pd.Series(np.nan, index=df.index)
    out.loc[r.index] = r.values
    return out


def market_block(df, price_col, prefix, tie_cols):
    """margin-free probability, unique rank (tie-broken) and favourite flag for a price column among starters."""
    price = df[price_col].where(df["starter"])
    q = 1.0 / price
    g = df["race_id"]
    n_q = q.groupby(g).transform("count")
    cov = n_q / df["n_starters"].where(df["n_starters"] > 0)
    s = q.groupby(g).transform("sum")
    ok = (cov >= MIN_QUOTE_COVERAGE)
    df[f"{prefix}_p"] = (q / s).where(ok)
    tmp = df[["race_id"]].copy()
    tmp["_p"] = price
    for i, c in enumerate(tie_cols):
        tmp[f"_t{i}"] = df[c]
    df[f"{prefix}_rank"] = rank_in_race(tmp, "race_id", ["_p"] + [f"_t{i}" for i in range(len(tie_cols))], price.notna() & ok)
    df[f"fav_{prefix}"] = pd.array(np.where(df[f"{prefix}_rank"].notna(), df[f"{prefix}_rank"] == 1, pd.NA), dtype="boolean")
    pmin = price.where(ok).groupby(g).transform("min")
    at_min = (price == pmin)
    n_min = at_min.groupby(g).transform("sum")
    df[f"cofav_{prefix}"] = pd.array(np.where(ok & price.notna(), at_min & (n_min > 1), pd.NA), dtype="boolean")   # tied for shortest price
    df[f"{prefix}_race_cov"] = cov
    return df


KW = {
    "slow_begin":   r"slow(ly)? (to )?(begin|jump|leave|start|get away|away|out)|dwelt|missed the (start|kick)",
    "awkward_start": r"began (very |rather |somewhat )?(awkward|poorly)|jumped awkward|blundered|stumbled|fumbled|lost ground at the start",
    "held_up":      r"held up",
    "no_clear_run": r"clear (running|run|passage)|short of room|restricted|tightened|shut off",
    "checked":      r"checked|steadied|hampered|bumped|crowded|jostled|interfered|inconvenienc|taken in|obstructed",
    "wide_no_cover": r"without cover|no cover|exposed",
    "raced_wide":   r"\bwide\b|forced wider",
    "raced_keenly": r"keen|pull(ed|ing)? (hard|up)|inclined to pull|over-?rac|fierce|resent|fractious|fought",
    "hung_or_laid": r"\bhung\b|laid (in|out)|laying|raced ungenerously|drifted",
    "eased":        r"\beased\b|eased down",
    "vet_issue":    r"\blame|\bbled|bleed|epistaxis|veterinar|\bvet\b|irregular|atrial|cardiac|heart|lost (a |its |his |her )?(plate|shoe)|\bsore|stiff|tied up|distress|\bblood|abnormal|swab|lacerat|injur|bruis|\bheat\b|fibrillat",
    "disappointing": r"disappoint|failed to (quicken|respond|sustain|extend)|did not (quicken|respond)|ran flat|weaken|lacked|performance (was )?(below|disappoint)",
    "stewards_action": r"inquir|warning|reprimand|\bfined\b|careless|penalis|suspend|trainer representative|explain",
}
COND_ORD = {"Fast": 1, "Firm": 1, "Good": 2, "Soft": 3, "Heavy": 4}


def class_cat(rdc, raw, group):
    g = group if isinstance(group, str) else ""
    if g.startswith("Group"):
        return g.replace("Group ", "G")
    if g == "Listed":
        return "Listed"
    r = rdc if isinstance(rdc, str) else ""
    if r.startswith("BM"):
        return "BM"
    if r in ("Maiden", "Open", "Picnic", "Quality"):
        return r
    # fall back to raw class text
    s = raw if isinstance(raw, str) else ""
    if "MDN" in s:
        return "Maiden"
    if s.startswith("BM") or re.match(r"^\d+ - \d+", s):
        return "BM"
    if s.startswith("CL"):
        return "Class"
    if s in ("HCP", "OPEN"):
        return "Open"
    return "Other"


def class_level(rdc, raw, group):
    """crude ordinal proxy of class (benchmark number where known)."""
    g = group if isinstance(group, str) else ""
    if g == "Group 1": return 110.0
    if g == "Group 2": return 105.0
    if g == "Group 3": return 100.0
    if g == "Listed": return 95.0
    r = rdc if isinstance(rdc, str) else ""
    m = re.match(r"^BM (\d+)$", r)
    if m: return float(m.group(1))
    if r == "BM 0-57": return 52.0
    if r == "Maiden": return 40.0
    if r == "Picnic": return 50.0
    if r == "Quality": return 85.0
    if r == "Open": return 78.0
    s = raw if isinstance(raw, str) else ""
    m = re.match(r"^BM\s?(\d+)", s)
    if m: return float(m.group(1))
    if "MDN" in s: return 40.0
    return np.nan


def grp_roll(x, grp, w, how="sum"):
    """rolling window w (incl. current row) within sorted groups, via cumsum differences. NaNs ignored."""
    v = x.fillna(0.0)
    cnt = x.notna().astype(float)
    cs = v.groupby(grp).cumsum()
    cc = cnt.groupby(grp).cumsum()
    cs_l = cs.groupby(grp).shift(w).fillna(0.0)
    cc_l = cc.groupby(grp).shift(w).fillna(0.0)
    s = cs - cs_l
    n = cc - cc_l
    return s if how == "sum" else (s / n.where(n > 0))


def asof_by(left, right, left_on, right_on, by, cols, allow_exact=True, prefix=""):
    """merge_asof wrapper: for each left row take the last right row (per `by`) with right_on <= left_on."""
    L = left[[by, left_on]].copy()
    L["_i"] = np.arange(len(L))
    L = L.sort_values(left_on, kind="mergesort")
    R = right[[by, right_on] + cols].sort_values(right_on, kind="mergesort")
    m = pd.merge_asof(L, R, left_on=left_on, right_on=right_on, by=by, direction="backward",
                      allow_exact_matches=allow_exact, suffixes=("", "_r"))
    m = m.sort_values("_i").reset_index(drop=True)
    m.index = left.index
    res = m[cols].copy()
    res.columns = [prefix + c for c in cols]
    if right_on != left_on:
        res[prefix + "_asof_time"] = m[right_on]
    return res


def mark_examined(df, meta):
    """research/examined.csv (read-only, owned by the research protocol): races whose outcome was seen during development."""
    rows = [l.rstrip("\n").split(",", 5) for l in open(EXAMINED_CSV) if l.strip()]      # the free-text reason may contain commas
    ex = pd.DataFrame(rows[1:], columns=rows[0])
    out = pd.Series(False, index=df.index)
    venue = df["venue"].astype(str).str.lower()
    log = []
    for r in ex.itertuples():
        m = (df["date"] >= pd.Timestamp(r.date_from)) & (df["date"] <= pd.Timestamp(r.date_to))
        v = str(r.venue)
        if v != "*":
            vv = v.lower()
            m &= (venue == vv) | venue.str.endswith("-" + vv)
        if str(r.race) != "*":
            m &= df["race_number"] == int(r.race)
        out |= m
        log.append(dict(scope=r.scope, date_from=r.date_from, date_to=r.date_to, venue=v, race=str(r.race), races_marked=int(df.loc[m, "race_id"].nunique())))
    meta["examined_rules"] = log
    return out


MEL_TZ = "Australia/Melbourne"
CCOLS = ["c_one", "c_won", "c_wp", "c_ep", "c_np"]

# FACTORS.md v0.3, exactly as written (case-insensitive)
F3_PATS = {
    "slow": r"slow(ly)?\s+(to\s+begin|away)|began\s+(awkwardly|slowly|poorly)|dwelt|missed\s+the\s+start",
    "held": r"held\s+up|(unable\s+to|could\s+not|did\s+not)\s+(obtain|get)\s+(clear\s+)?(running|a\s+run)|denied\s+(clear\s+)?(running|a\s+run)|blocked",
    "checked": r"checked|crowded|bumped|hampered|tightened|squeezed|inconvenienced|shifted\s+(in|out)\s+(abruptly|sharply)",
    "wide": r"wide\s+(throughout|without\s+cover|and\s+without\s+cover)|caught\s+wide|(three|four|five)\s+wide",
    "keen": r"over-?rac(ed|ing)|raced\s+(keenly|ungenerously|fiercely)|pulled\s+hard|hung\s+(in|out)",
}
F4_PAT = r"bled|bleed|blood|lame|cardiac|irregular\s+heart|arrhythm|pulled\s+up|eased\s+(down|out|right\s+down)|vet(erinary)?\s+(examination|inspection)|distressed|respiratory"


def codes_for(left_keys, right_keys):
    """joint integer codes for two key Series (NaN -> -1)."""
    both = pd.concat([left_keys.astype(object), right_keys.astype(object)], ignore_index=True)
    codes, _ = pd.factorize(both)
    return codes[: len(left_keys)], codes[len(left_keys):]


def cum_table(keys_codes, dates, won, sp_p):
    """right-hand table of per-key cumulative counts, indexed for asof on calendar dates."""
    R = pd.DataFrame({"_ec": keys_codes, "_rs": dates.values, "_one": 1.0, "_won": won.astype(float).values})
    R["_wp"] = R["_won"].where(sp_p.notna().values)
    R["_ep"] = sp_p.values
    R["_np"] = sp_p.notna().astype(float).values
    R = R[R["_ec"] >= 0].sort_values(["_ec", "_rs"], kind="mergesort").reset_index(drop=True)
    for c in ("_one", "_won", "_wp", "_ep", "_np"):
        R["c" + c] = R.groupby("_ec")[c].cumsum()
    return R[["_ec", "_rs"] + CCOLS]


def windows(df, Rp, ec_left, Ns):
    """rolling stats over the previous N calendar days (dates in [d-N, d-1]) for each N; ec_left = key codes of the left rows."""
    L = pd.DataFrame({"_ec": np.asarray(ec_left), "_hi": df["mel_date"].values}, index=df.index)
    hi = asof_by(L, Rp, "_hi", "_rs", "_ec", CCOLS, allow_exact=False)
    hi = hi.drop(columns=[c for c in hi.columns if c.endswith("_asof_time")]).fillna(0)
    out = {}
    for N in Ns:
        L["_lo"] = (df["mel_date"] - pd.Timedelta(days=N + 1)).values
        lo = asof_by(L, Rp, "_lo", "_rs", "_ec", CCOLS, allow_exact=True)
        lo = lo.drop(columns=[c for c in lo.columns if c.endswith("_asof_time")]).fillna(0)
        d = (hi - lo).clip(lower=0)
        valid = pd.Series(np.asarray(ec_left) >= 0, index=df.index)
        out[N] = dict(n=d["c_one"].where(valid), w=d["c_won"].where(valid), wp=d["c_wp"].where(valid), ep=d["c_ep"].where(valid), npr=d["c_np"].where(valid))
    return out


def ae_k(st, k):
    return (st["wp"] + k) / (st["ep"] + k)


def build_history(df, log=print):
    """Point-in-time features. 'History' = the runner's own earlier runs on EARLIER CALENDAR DAYS (Australia/Melbourne), Australian races only."""
    base_cols = ["horse_code", "start_utc", "mel_date", "won", "placed", "finish_pos", "n_starters", "sp_p", "res_comment", "margin_behind_len",
                 "win_margin_len", "sp", "sp_rank", "res_settled", "res_pos800", "res_pos400", "res_last600_s", "res_last600_rank",
                 "res_last600_vs_best", "res_last200_s", "res_time_behind_winner_s", "res_std_time_diff_len", "res_speed_late",
                 "res_top_speed", "res_dist_travelled", "gear_changes", "distance_m", "class_rdc", "class_cat", "class_level", "venue", "state",
                 "track_cond", "cond_ord", "surface", "weight_kg", "jockey_id", "trainer_id", "sire", "barrier", "handicap_rating",
                 "meeting_id", "race_id", "race_number"]
    S = df.loc[df["starter"] & df["race_resulted"] & df["is_au"], base_cols].copy()
    S = S.sort_values(["horse_code", "start_utc"], kind="mergesort").reset_index(drop=True)
    g = S["horse_code"]
    rid = S["race_id"]
    S["_won"] = S["won"].astype(float)
    S["_placed"] = S["placed"].astype(float)
    S["_runs"] = S.groupby("horse_code").cumcount() + 1
    S["_wins"] = S.groupby("horse_code")["_won"].cumsum()
    S["_places"] = S.groupby("horse_code")["_placed"].cumsum()
    S["_pct"] = S["finish_pos"] / S["n_starters"]
    S["_pct3"] = grp_roll(S["_pct"], g, 3, "mean")
    S["_wins5"] = grp_roll(S["_won"], g, 5, "sum")
    S["_spp3"] = grp_roll(S["sp_p"], g, 3, "mean")
    # ---- F1 closing sectional: rank of the runner's last-600 among finishers with a sectional (n>=4)
    sec = S["res_last600_s"].where(S["finish_pos"].notna())
    n_sec = sec.groupby(rid).transform("count")
    rk = sec.groupby(rid).rank(method="min")
    S["_f1_s"] = (1 - (rk - 1) / (n_sec - 1)).where(n_sec >= 4)
    S["_f1_gap"] = S["_f1_s"] - (1 - (S["finish_pos"] - 1) / (S["n_starters"] - 1)).where(S["n_starters"] > 1)
    S["_f1_avg3"] = grp_roll(S["_f1_s"], g, 3, "mean")
    # ---- F2 ground made
    S["_f2_g"] = ((S["res_pos800"] - S["finish_pos"]) / S["n_starters"]).where(S["n_starters"] >= 2)
    S["_f2_avg3"] = grp_roll(S["_f2_g"], g, 3, "mean")
    # ---- F3 excuse flags / F4 bad sign (stewards' comment of that run)
    c = S["res_comment"].fillna("").str.lower()
    anyf = pd.Series(False, index=S.index)
    for k, pat in F3_PATS.items():
        m = c.str.contains(pat, regex=True)
        S[f"_f3_{k}"] = m.astype(float)
        anyf |= m
    S["_f3_any"] = anyf.astype(float)
    S["_f3_cnt3"] = grp_roll(S["_f3_any"], g, 3, "sum")
    S["_f4_bad"] = c.str.contains(F4_PAT, regex=True).astype(float)
    # my own wider keyword flags (original brief), kept as ls_kw_*
    has_c = S["res_comment"].notna()
    for k, pat in KW.items():
        S[f"_kw_{k}"] = c.str.contains(pat, regex=True).astype(float).where(has_c)
    S["_has_comment"] = has_c.astype(float)
    # ---- F5 distance travelled beyond race distance; F6 top speed relative to race median
    S["_f5_t"] = S["res_dist_travelled"] - S["distance_m"]
    S["_f5_avg3"] = grp_roll(S["_f5_t"], g, 3, "mean")
    ts = S["res_top_speed"]
    nts = ts.groupby(rid).transform("count")
    med = ts.groupby(rid).transform("median")
    S["_f6_v"] = (ts / med).where((nts >= 4) & (med > 0))
    S["_f6_avg3"] = grp_roll(S["_f6_v"], g, 3, "mean")
    # ---- F7 run style: mean over last 5 runs of (settled-1)/(field-1), >=2 runs
    style = ((S["res_settled"] - 1) / (S["n_starters"] - 1)).where(S["n_starters"] >= 2)
    st5 = grp_roll(style, g, 5, "mean")
    c5 = grp_roll(style.notna().astype(float), g, 5, "sum")
    S["_f7_style"] = st5.where(c5 >= 2)
    # ---- F17 helper flags
    S["_wet"] = S["track_cond"].astype(str).isin(["Soft", "Heavy"])
    pay = {
        "ls_start_utc": "start_utc", "ls_date": "mel_date", "ls_finish": "finish_pos", "ls_won": "_won", "ls_field": "n_starters",
        "ls_finish_pct": "_pct", "ls_margin_behind": "margin_behind_len", "ls_win_margin": "win_margin_len",
        "ls_sp": "sp", "ls_sp_p": "sp_p", "ls_sp_rank": "sp_rank",
        "ls_settled": "res_settled", "ls_pos800": "res_pos800", "ls_pos400": "res_pos400",
        "ls_last600_s": "res_last600_s", "ls_last600_rank": "res_last600_rank", "ls_last600_vs_best": "res_last600_vs_best",
        "ls_last200_s": "res_last200_s", "ls_time_behind_winner_s": "res_time_behind_winner_s",
        "ls_std_time_diff_len": "res_std_time_diff_len", "ls_speed_late": "res_speed_late",
        "ls_comment": "res_comment", "ls_gear_changes": "gear_changes", "ls_distance_m": "distance_m",
        "ls_class_rdc": "class_rdc", "ls_class_cat": "class_cat", "ls_class_level": "class_level",
        "ls_venue": "venue", "ls_state": "state", "ls_track_cond": "track_cond", "ls_cond_ord": "cond_ord",
        "ls_surface": "surface", "ls_weight_kg": "weight_kg", "ls_jockey_id": "jockey_id", "ls_barrier": "barrier",
        "ls_handicap_rating": "handicap_rating",
        "runs_in_ds": "_runs", "wins_in_ds": "_wins", "places_in_ds": "_places",
        "last3_avg_finish_pct": "_pct3", "last5_wins": "_wins5", "last3_avg_sp_p": "_spp3", "ls_has_comment": "_has_comment",
        "f1_last": "_f1_s", "f1_avg3": "_f1_avg3", "f1_gap": "_f1_gap", "f2_last": "_f2_g", "f2_avg3": "_f2_avg3",
        "f3_any": "_f3_any", "f3_count3": "_f3_cnt3", "f4_bad": "_f4_bad", "f5_avg3": "_f5_avg3",
        "f6_last": "_f6_v", "f6_avg3": "_f6_avg3", "f7_style": "_f7_style",
    }
    for k in F3_PATS:
        pay[f"ls_f3_{k}"] = f"_f3_{k}"
    for k in KW:
        pay[f"ls_kw_{k}"] = f"_kw_{k}"
    vals = sorted(set(pay.values()) - {"start_utc", "mel_date"})
    right = S[["horse_code", "start_utc", "mel_date"] + vals].copy()
    right = right.rename(columns={v: k for k, v in pay.items() if v not in ("start_utc", "mel_date")})
    right["ls_start_utc"] = S["start_utc"].values
    right["ls_date"] = S["mel_date"].values
    right = right.rename(columns={"mel_date": "_rdate"})
    rcols = [k for k in pay]
    hc_l, hc_r = codes_for(df["horse_code"], right["horse_code"])
    df["_hc"] = hc_l
    right["_hc"] = hc_r
    # PRIMARY history: strictly EARLIER CALENDAR DAYS; no same-day result is ever used
    h = asof_by(df, right, "mel_date", "_rdate", "_hc", rcols, allow_exact=False)
    h = h.drop(columns=[c for c in h.columns if c.endswith("_asof_time")], errors="ignore")
    del right
    new = {c: h[c] for c in h.columns}
    del h
    d = df.copy(deep=False)
    for c, v in new.items():
        d[c] = v
    df = d
    df["days_since_last_run"] = (df["start_utc"] - df["ls_start_utc"]).dt.total_seconds() / 86400.0
    for c in ("runs_in_ds", "wins_in_ds", "places_in_ds"):
        df[c] = df[c].fillna(0)
    nc = {}
    nc["chg_distance_m"] = df["distance_m"] - df["ls_distance_m"]
    nc["chg_class_level"] = df["class_level"] - df["ls_class_level"]
    nc["chg_class_cat"] = (df["class_cat"].astype(object) != df["ls_class_cat"].astype(object)).where(df["ls_class_cat"].notna())
    nc["chg_venue"] = (df["venue"].astype(object) != df["ls_venue"].astype(object)).where(df["ls_venue"].notna())
    nc["chg_surface"] = (df["surface"].astype(object) != df["ls_surface"].astype(object)).where(df["ls_surface"].notna())
    nc["chg_cond_ord"] = df["cond_ord"] - df["ls_cond_ord"]
    nc["chg_weight_kg"] = df["weight_kg"] - df["ls_weight_kg"]
    nc["chg_jockey"] = (df["jockey_id"].astype(object) != df["ls_jockey_id"].astype(object)).where(df["ls_jockey_id"].notna() & df["jockey_id"].notna())
    nc["chg_barrier"] = df["barrier"] - df["ls_barrier"]
    nc["chg_handicap_rating"] = df["handicap_rating"] - df["ls_handicap_rating"]       # rating at a past race may have been revised
    nc["f16_dr"] = nc["chg_handicap_rating"]
    nc["ls_gear_changed"] = df["ls_gear_changes"].notna().where(df["ls_start_utc"].notna())
    nc["gear_changed_today"] = df["gear_changes"].notna()
    nc["ls_pos_gain_800_to_finish"] = df["ls_pos800"] - df["ls_finish"]
    nc["ls_pos_gain_400_to_finish"] = df["ls_pos400"] - df["ls_finish"]

    # ---- connections: calendar-day windows ------------------------------------------------------------
    S["_dband"] = (S["distance_m"] / 200.0).round() * 200.0
    S["_bgrp"] = pd.cut(S["barrier"], [0, 3, 6, 9, 99], labels=["1-3", "4-6", "7-9", "10+"]).astype(object)
    dband_l = (df["distance_m"] / 200.0).round() * 200.0
    bgrp_l = pd.cut(df["barrier"], [0, 3, 6, 9, 99], labels=["1-3", "4-6", "7-9", "10+"]).astype(object)

    def tbl(keys_right, keys_left):
        el, er = codes_for(keys_left, keys_right)
        R = cum_table(er, S["mel_date"], S["_won"], S["sp_p"])
        return R, el

    # jockey (F13): windows 90/365, shrunk AE20 over 365; last-start jockey AE20
    R, el = tbl(S["jockey_id"], df["jockey_id"])
    ws = windows(df, R, el, (90, 365))
    for N in (90, 365):
        st = ws[N]
        nc[f"jk{N}_n"] = st["n"]; nc[f"jk{N}_wins"] = st["w"]; nc[f"jk{N}_sr"] = st["w"] / st["n"].where(st["n"] > 0)
        nc[f"jk{N}_ae"] = (st["wp"] / st["ep"].where(st["ep"] > 0)).where(st["npr"] >= 10)
    ae20 = ae_k(ws[365], 20).where(ws[365]["n"] >= 10)
    nc["f13_jockey"] = ae20
    nc["f13_n"] = ws[365]["n"]
    el2 = codes_for(df["ls_jockey_id"], S["jockey_id"])[0]
    ws2 = windows(df, R, el2, (365,))[365]
    ae20_ls = ae_k(ws2, 20).where(ws2["n"] >= 10)
    nc["f13_change"] = ae20 - ae20_ls
    # trainer (F14): 14 days AE5 (>=3 runners), 365 days AE20
    R, el = tbl(S["trainer_id"], df["trainer_id"])
    ws = windows(df, R, el, (14, 90, 365))
    for N in (90, 365):
        st = ws[N]
        nc[f"tr{N}_n"] = st["n"]; nc[f"tr{N}_wins"] = st["w"]; nc[f"tr{N}_sr"] = st["w"] / st["n"].where(st["n"] > 0)
        nc[f"tr{N}_ae"] = (st["wp"] / st["ep"].where(st["ep"] > 0)).where(st["npr"] >= 10)
    nc["f14_14d"] = ae_k(ws[14], 5).where(ws[14]["n"] >= 3)
    nc["f14_14d_n"] = ws[14]["n"]
    nc["f14_365d"] = ae_k(ws[365], 20)
    nc["f14_365d_n"] = ws[365]["n"]
    # jockey x trainer pair (F15): 730 days AE10, >=5 rides
    pk_r = S["jockey_id"].astype(object).where(S["jockey_id"].notna() & S["trainer_id"].notna()) .astype(str) + "|" + S["trainer_id"].astype(str)
    pk_r = pk_r.where(S["jockey_id"].notna() & S["trainer_id"].notna())
    pk_l = df["jockey_id"].astype(str) + "|" + df["trainer_id"].astype(str)
    pk_l = pk_l.where(df["jockey_id"].notna() & df["trainer_id"].notna())
    R, el = tbl(pk_r, pk_l)
    st = windows(df, R, el, (730,))[730]
    nc["f15_pair"] = ae_k(st, 10).where(st["n"] >= 5)
    nc["f15_n"] = st["n"]
    # F17 unproven conditions (inputs): prior runs in today's distance band / venue / on wet; sire progeny wet AE10 over 1095 days
    for nm, kr, kl in (("band", S["horse_code"].astype(str) + "|" + S["_dband"].astype(str), df["horse_code"].astype(str) + "|" + dband_l.astype(str)),
                       ("venue", S["horse_code"].astype(str) + "|" + S["venue"].astype(str), df["horse_code"].astype(str) + "|" + df["venue"].astype(str))):
        R, el = tbl(kr, kl)
        st = windows(df, R, el, (36500,))[36500]
        nc[f"f17_prior_runs_{nm}"] = st["n"]
        nc["f17_newdist" if nm == "band" else "f17_newtrack"] = (st["n"] == 0).where(df["distance_m"].notna() if nm == "band" else df["venue"].notna())
    wet = S["_wet"]
    el, er = codes_for(df["horse_code"], S["horse_code"].where(wet))
    R = cum_table(er, S["mel_date"], S["_won"], S["sp_p"])
    st = windows(df, R, el, (36500,))[36500]
    nc["f17_prior_wet_run"] = st["n"] > 0
    el, er = codes_for(df["sire"], S["sire"].where(wet))
    R = cum_table(er, S["mel_date"], S["_won"], S["sp_p"])
    st = windows(df, R, el, (1095,))[1095]
    nc["f17_sire_wet_ae10"] = ae_k(st, 10).where(st["n"] > 0)
    nc["f17_sire_wet_n"] = st["n"]
    # F18 barrier cell: (venue, distance band, barrier group); AE20 over 1095 days; >=30 runners
    cell_r = (S["venue"].astype(str) + "|" + S["_dband"].astype(str) + "|" + S["_bgrp"].astype(str)).where(S["barrier"].notna() & S["_dband"].notna())
    cell_l = (df["venue"].astype(str) + "|" + dband_l.astype(str) + "|" + bgrp_l.astype(str)).where(df["barrier"].notna() & dband_l.notna())
    R, el = tbl(cell_r, cell_l)
    st = windows(df, R, el, (1095,))[1095]
    nc["f18_cell"] = ae_k(st, 20).where(st["n"] >= 30)
    nc["f18_n"] = st["n"]

    # ---- EXPLORATORY same-day features (sameday_*): earlier races the same day, strictly earlier start ----------------------------
    S2 = S[["jockey_id", "trainer_id", "start_utc", "mel_date", "_won", "sp_p"]].copy()
    for ent, idcol in (("jk", "jockey_id"), ("tr", "trainer_id")):
        el, er = codes_for(df[idcol], S2[idcol])
        R = pd.DataFrame({"_ec": er, "_d": (S2["mel_date"] - pd.Timestamp("2000-01-01")).dt.days.astype("int64").values,
                          "_rs2": S2["start_utc"].values, "_one": 1.0, "_won": S2["_won"].values, "_ep": S2["sp_p"].fillna(0).values})
        R = R[R["_ec"] >= 0].copy()
        R["_dk"] = R["_ec"].astype("int64") * 100000 + R["_d"]
        R = R.sort_values(["_dk", "_rs2"], kind="mergesort").reset_index(drop=True)
        for c in ("_one", "_won", "_ep"):
            R["c" + c] = R.groupby("_dk")[c].cumsum()
        L = pd.DataFrame({"_dk": np.where(el < 0, -1, el.astype("int64") * 100000 + (df["mel_date"] - pd.Timestamp("2000-01-01")).dt.days.astype("int64").values),
                          "_st": df["start_utc"].values}, index=df.index)
        sd = asof_by(L, R[["_dk", "_rs2", "c_one", "c_won", "c_ep"]], "_st", "_rs2", "_dk", ["c_one", "c_won", "c_ep"], allow_exact=False)
        has = pd.Series(el >= 0, index=df.index)
        nc[f"sameday_{ent}_n"] = sd["c_one"].fillna(0).where(has)
        nc[f"sameday_{ent}_wins"] = sd["c_won"].fillna(0).where(has)
        nc[f"sameday_{ent}_exp_wins_sp"] = sd["c_ep"].fillna(0).where(has)
    W = S[S["won"].astype(bool)].drop_duplicates("race_id").set_index("race_id")
    RM = S.groupby("race_id", sort=False).agg(meeting_id=("meeting_id", "first"), start_utc=("start_utc", "first"), n=("horse_code", "size"))
    RM["w_barrier_rel"] = (W["barrier"] / RM["n"]).reindex(RM.index)
    RM["w_settled_rel"] = (W["res_settled"] / RM["n"]).reindex(RM.index)
    RM["w_front"] = (W["res_settled"] <= 3).astype(float).where(W["res_settled"].notna()).reindex(RM.index)
    RM["w_fav"] = (W["sp_rank"] == 1).astype(float).where(W["sp_rank"].notna()).reindex(RM.index)
    RM["w_logsp"] = np.log(W["sp"]).reindex(RM.index)
    RM = RM.sort_values(["meeting_id", "start_utc"], kind="mergesort")
    gm = RM.groupby("meeting_id", sort=False)
    sm = {"sameday_mtg_n_races": gm.cumcount().astype(float)}
    for c in ("w_barrier_rel", "w_settled_rel", "w_front", "w_fav", "w_logsp"):
        v = RM[c]
        cs = v.fillna(0).groupby(RM["meeting_id"], sort=False).cumsum() - v.fillna(0)
        cn = v.notna().astype(float).groupby(RM["meeting_id"], sort=False).cumsum() - v.notna().astype(float)
        sm[f"sameday_mtg_{c}_mean"] = cs / cn.where(cn > 0)
        if c == "w_fav":
            sm["sameday_mtg_fav_wins"] = cs
    smdf = pd.DataFrame(sm)
    for c in smdf.columns:
        nc[c] = df["race_id"].map(smdf[c])
    df = pd.concat([df, pd.DataFrame(nc, index=df.index)], axis=1)
    # F7 pace count L: number of runners in U (T-30) whose raw style S <= 0.25 (known style only). Race-level INPUT, never a feature on its own.
    df["f7_L"] = ((df["f7_style"] <= 0.25) & df["inU_t30"]).groupby(df["race_id"]).transform("sum")
    # per-family missing indicators (1 = at least one of the family's features cannot be computed). NO scaling of any kind is applied here.
    fam = {1: ["f1_last", "f1_avg3", "f1_gap"], 2: ["f2_last", "f2_avg3"], 3: ["f3_any", "f3_count3"], 4: ["f4_bad"], 5: ["f5_avg3"], 6: ["f6_last", "f6_avg3"],
           7: ["f7_style"], 10: ["f10_move"], 11: ["f11_sb_lb"], 12: ["f12_G"], 13: ["f13_jockey", "f13_change"], 14: ["f14_14d", "f14_365d"],
           15: ["f15_pair"], 16: ["f16_dr"], 18: ["f18_cell"]}
    miss = {f"f{n}_missing": df[cols].isna().any(axis=1) for n, cols in fam.items()}
    # F17: newdist/newtrack are computable for everyone (no prior run = True; only trustworthy when hist_ok) but f17_newwet / f17_sire_wet need the DECLARED
    # (earliest-record) wet flag, which the dumps do not contain -> historically always missing.
    miss["f17_missing"] = pd.Series(True, index=df.index)
    df = pd.concat([df, pd.DataFrame(miss, index=df.index)], axis=1)
    df = df.drop(columns=[c for c in df.columns if c.startswith("_")], errors="ignore")
    return df


def assemble(holder, meta, log=print):
    t0 = time.time()
    raw = holder.pop()
    df = raw.reset_index(drop=True)
    del raw
    df["is_au"] = df["state"].astype(str).isin(AU_STATES)
    meta["non_au_rows"] = int((~df["is_au"]).sum())
    meta["non_au_states"] = df.loc[~df["is_au"], "state"].value_counts().to_dict()
    log(f"  rows {len(df)}; {rss()}")
    df = df.rename(columns={"speed_value": "speed_value_unverified"})   # protocol: may be written after the race -> never used in history
    for c in ("res_dist_travelled", "res_top_speed", "res_last600_s", "res_last200_s", "res_time_s"):     # zeros are placeholders (e.g. VIC distanceTravelled = 0 in ~64% of rows)
        df[c] = df[c].where(df[c] > 0)
    df["race_id"] = df["meeting_id"].astype(str) + "_" + df["race_number"].astype(str)
    df["start_utc"] = pd.to_datetime(df["start_iso"].astype(str))
    df["mel_date"] = df["start_utc"].dt.tz_localize("UTC").dt.tz_convert(MEL_TZ).dt.tz_localize(None).dt.normalize()
    df["year"] = df["date"].astype(str).str[:4].astype(int)
    df["date"] = pd.to_datetime(df["date"].astype(str))
    dm = (df["mel_date"] - df["date"]).dt.days.abs() > 1
    df["start_date_mismatch"] = dm        # recorded start more than 1 day from the meeting date (e.g. start typed in the wrong year): history uses the meeting date
    df.loc[dm, "mel_date"] = df.loc[dm, "date"]
    meta["races_with_start_date_mismatch"] = int(df.loc[dm, "race_id"].nunique())
    meta["races_where_melbourne_date_differs_from_meeting_date_by_1day"] = int(df.loc[(df["mel_date"] != df["date"]), "race_id"].nunique())
    df = df.drop(columns=["start_iso"])
    for c in CAT_COLS:
        df[c] = df[c].astype("category")
    log(f"  keys/categoricals done; {rss()}")

    # ---- race context
    rg = df.groupby("race_id")
    df["n_starters"] = rg["starter"].transform("sum").astype(int)
    df["n_scratched"] = rg["scratched"].transform("sum").astype(int)
    df["race_resulted"] = rg["race_has_result"].transform("max").astype(bool)
    df["class_cat"] = [class_cat(a, b, c) for a, b, c in zip(df["class_rdc"], df["class_raw"], df["group"])]
    df["class_level"] = [class_level(a, b, c) for a, b, c in zip(df["class_rdc"], df["class_raw"], df["group"])]
    df["cond_ord"] = df["track_cond"].map(COND_ORD).astype(float)
    df = df.rename(columns={"age": "horse_age_now", "sex": "horse_sex_now"})
    aug1 = pd.to_datetime(df["year"].astype(str) + "-08-01")
    n_aug = (COLLECTION_YEAR - df["year"]) + (df["date"] < aug1).astype(int)
    df["age_at_race_est"] = df["horse_age_now"] - n_aug
    df["places_paid"] = np.where(df["n_starters"] >= 8, 3, np.where(df["n_starters"] >= 5, 2, 1))
    df["field_mismatch_api"] = df["runners_count_api"].notna() & (df["runners_count_api"] != df["n_starters"])

    # ---- outcomes
    fin = pd.to_numeric(df["finish_code"], errors="coerce")
    rs = df["starter"] & df["race_resulted"]
    df["dnf"] = pd.array(np.where(rs, (fin >= 100) & (fin < 109), pd.NA), dtype="boolean")
    df["finish_pos"] = fin.where(rs & (fin < 100))
    df["won"] = pd.array(np.where(rs, df["finish_pos"] == 1, pd.NA), dtype="boolean")
    df["placed"] = pd.array(np.where(rs, df["finish_pos"] <= df["places_paid"], pd.NA), dtype="boolean")
    wonb = df["won"].fillna(False).astype(bool)
    df["n_winners"] = wonb.groupby(df["race_id"]).transform("sum").astype(int)
    df["win_margin_len"] = df["margin_raw_len"].where(wonb)
    df["margin_behind_len"] = df["margin_raw_len"].where(df["finish_pos"] > 1)
    df.loc[wonb, "margin_behind_len"] = 0.0
    df = df.drop(columns=["margin_raw_len", "race_has_result"])

    # ---- SP market (starters only)
    df["sp"] = df["sp"].where(df["starter"])
    df["_tie_sb"] = df["sb_final"]
    df["_tie_lb"] = df["lb_final"]
    df = market_block(df, "sp", "sp", ["_tie_sb", "_tie_lb", "barrier"])
    df["sp_inv"] = 1.0 / df["sp"]
    df["sp_race_sum_inv"] = df.groupby("race_id")["sp_inv"].transform("sum").where(df["starter"])
    _min = df.groupby("race_id")["sp"].transform("min")
    df["fav_tied_sp"] = ((df["sp"] == _min).groupby(df["race_id"]).transform("sum") > 1) & df["sp_rank"].notna()
    df = df.rename(columns={"sp_race_cov": "sp_coverage"})

    # ---- bookmaker quotes (raw columns keep ALL entries, scratched ones too) + legacy starter-based margin-free blocks
    for b in BOOKS:
        stale = df[f"{b}_feed_stale"].astype(bool)
        for T in ("open",) + tuple(f"t{T}" for T in SNAP_MINS):
            col = f"{b}_{T}"
            df["_leg"] = df[col] if T == "open" else df[col].where(~stale)    # legacy: price nulled when the race's feed was dead near the off
            df = market_block(df, "_leg", col, ["sp", "barrier"])
            df = df.rename(columns={f"{col}_race_cov": f"{col}_coverage"})
            if T != "open":
                df[f"{col}_later_fluc"] = (df[f"{col}_n_later"] > 0).where(df[f"{col}_n_later"].notna())
                df[f"{col}_usable"] = df[col].notna()     # v0.5: quotes are change events; the last fluc <= T counts whatever its age
        col = f"{b}_final"
        df[col] = df[col].where(df["starter"])
        df["_leg"] = df[col]
        df = market_block(df, "_leg", col, ["sp", "barrier"])
        df = df.rename(columns={f"{col}_race_cov": f"{col}_coverage"})
    df = df.drop(columns=["_tie_sb", "_tie_lb", "_leg"])
    df["fav_changed_t30_sb_to_sp"] = (df["fav_sb_t30"] != df["fav_sp"]).where(df["fav_sb_t30"].notna() & df["fav_sp"].notna())
    df["sp_over_sb_t30"] = df["sp"] / df["sb_t30"]
    df["first_fluc_min_before_start"] = np.fmax(df["sb_open_min"], df["lb_open_min"])

    # ---- protocol market: runner universe U and two-bookmaker margin-free consensus M, per decision time T
    race = df["race_id"]
    for T in SNAP_MINS:
        # v0.5 scratch dating: a recorded scratching is late (in U) if its last fluc at either book is at or after T
        last_rel = np.fmax(df["sb_last_rel_s"], df["lb_last_rel_s"])
        late = df["scratched"] & (last_rel >= -T * 60)
        inU = (~df["scratched"]) | late
        df[f"inU_t{T}"] = inU
        df[f"late_scratch_t{T}"] = late
        df[f"scratch_ambiguous_t{T}"] = df["scratched"] & (last_rel < -T * 60) & (last_rel > -T * 60 - FEED_LIVE_S)
        for b in BOOKS:   # v0.5 feed liveness: >=1 fluc on any entry of the race in [T-900s, T]
            df[f"feed_live_{b}_t{T}"] = df[f"{b}_t{T}_age_s"].groupby(race).transform("min") <= FEED_LIVE_S
        df[f"feed_live_t{T}"] = df[f"feed_live_sb_t{T}"] & df[f"feed_live_lb_t{T}"]
        nU = inU.groupby(race).transform("sum")
        df[f"U_size_t{T}"] = nU
        ok = {}
        for b in BOOKS:
            k = f"{b}_t{T}"
            us = df[f"{k}_usable"] & inU
            inv = (1.0 / df[k]).where(us)
            s_ = inv.groupby(race).transform("sum")
            df[f"m_{b}_t{T}"] = (inv / s_).where(us)          # margin-free over the usable-quoted members of U (full only if u_all_usable)
            ok[b] = (us.groupby(race).transform("sum") == nU) & (nU > 0)
            df[f"u_all_usable_{b}_t{T}"] = ok[b]
        mk = ok["sb"] & ok["lb"]
        df[f"mkt_ok_t{T}"] = mk
        df[f"mkt_sbonly_ok_t{T}"] = ok["sb"]
        M = ((df[f"m_sb_t{T}"] + df[f"m_lb_t{T}"]) / 2.0).where(mk & inU)
        df[f"M_t{T}"] = M
        tmp = df[["race_id", "barrier"]].copy()
        tmp["_negM"] = -M
        df[f"M_rank_t{T}"] = rank_in_race(tmp, "race_id", ["_negM", "barrier"], M.notna())
        Mmax = M.groupby(race).transform("max")
        favM = (M >= Mmax - 1e-9)
        df[f"fav_M_t{T}"] = pd.array(np.where(M.notna(), favM, pd.NA), dtype="boolean")
        df[f"cofav_M_t{T}"] = pd.array(np.where(M.notna(), favM & (favM.groupby(race).transform("sum") > 1), pd.NA), dtype="boolean")
        a = np.maximum(df[f"sb_t{T}_age_s"], df[f"lb_t{T}_age_s"]).fillna(np.inf).where(inU)
        am = a.groupby(race).transform("max")
        df[f"u_max_quote_age_s_t{T}"] = am.where(np.isfinite(am))        # NaN if any U runner lacks a quote from either book
        # F10 market move: ln(open / quote at T), mean over the available books
        mv = pd.concat([np.log(df[f"{b}_open"] / df[f"{b}_t{T}"]) for b in BOOKS], axis=1)
        df[f"f10_move_t{T}"] = mv.mean(axis=1)
    df["f10_move"] = df["f10_move_t30"]
    df["f11_sb_lb"] = np.log(df["m_sb_t30"] / df["m_lb_t30"])
    df["f11_abs"] = df["f11_sb_lb"].abs()
    fav = df["fav_M_t30"].fillna(False).astype(bool)
    M30 = df["M_t30"]
    nonfav_max = M30.where(~fav).groupby(race).transform("max")
    fav_M = M30.where(fav).groupby(race).transform("max")
    ok30 = M30.groupby(race).transform("count") > 0
    df["f12_fav"] = fav.astype(float).where(ok30)                 # 0/1 (co-favourites all 1); NaN where no usable market
    df["f12_G"] = (fav_M - nonfav_max).where(ok30)                # RAW race-level G = M_fav - M of best non-favourite (analysts standardise on training favourites)
    df["n_unscratched_nonstarters"] = ((~df["scratched"]) & (~df["starter"])).groupby(race).transform("sum")

    # ---- sectional rank within race (descriptive)
    n_sec = df["res_last600_s"].where(df["starter"]).groupby(race).transform("count")
    sec_ok = n_sec >= 0.8 * df["n_starters"]
    df["res_last600_rank"] = df.groupby("race_id")["res_last600_s"].rank(method="min").where(sec_ok)
    df["res_last600_vs_best"] = (df["res_last600_s"] - df.groupby("race_id")["res_last600_s"].transform("min")).where(sec_ok)
    wt = df["res_time_s"].where(wonb).groupby(race).transform("min")
    df["res_time_behind_winner_s"] = (df["res_time_s"] - wt).where(df["finish_pos"].notna())

    # ---- coverage / history completeness (Australian meetings only)
    d_all = pd.Series(df.loc[df["is_au"], "date"].unique()).sort_values()
    full = pd.date_range(d_all.min(), d_all.max(), freq="D")
    present = pd.Series(full.isin(d_all.values), index=full)
    gap_end, run, prev_missing_end = None, 0, None
    for dt, ok_ in present.items():
        if not ok_:
            run += 1
            prev_missing_end = dt
        else:
            if run >= MIN_GAP_RUN_DAYS:
                gap_end = prev_missing_end
            run = 0
    if run >= MIN_GAP_RUN_DAYS:
        gap_end = prev_missing_end
    coverage_start = (gap_end + pd.Timedelta(days=1)) if gap_end is not None else d_all.min()
    hist_from = coverage_start + pd.Timedelta(days=HIST_BUFFER_DAYS)
    meta.update(earliest_date=str(d_all.min().date()), latest_date=str(d_all.max().date()),
                contiguous_coverage_start=str(coverage_start.date()), history_complete_from=str(hist_from.date()),
                gap_note="coverage_start = day after the latest run of >=%d consecutive days with no AU meeting dump" % MIN_GAP_RUN_DAYS)
    df["block"] = "unassigned"
    for nm, a_, b_ in BLOCKS:
        df.loc[(df["date"] >= a_) & (df["date"] <= b_), "block"] = nm
    df["block"] = df["block"].astype("category")
    df["examined"] = mark_examined(df, meta)
    df["days_into_coverage"] = (df["date"] - coverage_start).dt.days
    df["hist_ok"] = df["date"] >= hist_from

    log(f"assemble: base columns done ({time.time()-t0:.0f}s); {rss()}; building history ...")
    df = build_history(df, log)
    log(f"assemble: history done ({time.time()-t0:.0f}s); {rss()}")
    return df


# Pre-decision filters (knowable at T = scheduled start - 30 min), in the protocol's order. A race is attributed to the FIRST rule it fails.
EXCL_RULES = [
    ("non_au", "not an Australian state/territory meeting (Hong Kong etc.)"),
    ("trial_or_jumpout", "trial / jump-out meetings (excluded upstream at collection via isTrial/isJumpOut; none can appear in the dump)"),
    ("u_lt5", "fewer than 5 runners in the universe U at T-30 (non-scratched entries + scratched entries whose last fluc is at or after T-30)"),
    ("not_market_eligible", "some runner in U has no quote (no fluc at or before T-30) from Sportsbet or Ladbrokes"),
    ("feed_not_live", f"Sportsbet or Ladbrokes has no fluc on any entry of the race in [T-30 - {FEED_LIVE_S}s, T-30]"),
    ("timing_untrusted", "recorded start > 24h from the last fluc, or no fluc within 3h before the recorded start"),
    ("examined", "race listed in research/examined.csv (whole development month 2026-09-29..2026-10-29, Doomben 2026-08-01 R1)"),
]
AGE_LIMITS = (900, 1800, 3600, 7200, 14400, 43200, 86400)


def build_races(df):
    """one row per race (ALL races; excluded ones carry excl_reason)."""
    g = df.groupby("race_id", sort=False)
    first = g.first()
    keep = ["meeting_id", "date", "mel_date", "year", "block", "venue", "state", "race_number", "start_utc", "start_ts", "race_name", "distance_m", "class_raw",
            "class_rdc", "class_cat", "class_level", "race_type", "group", "track_cond", "track_cond_src", "track_rating", "surface", "rail",
            "weather", "n_starters", "n_scratched", "n_unscratched_nonstarters", "places_paid", "race_resulted", "n_winners", "dup_entries", "runners_count_api",
            "field_mismatch_api", "race_tempo", "race_winning_time_s", "race_has_sectionals", "race_timing_source",
            "race_std_time_diff_len", "race_last600_s", "hist_ok", "days_into_coverage", "examined", "is_au", "f7_L", "start_date_mismatch"]
    R = first[keep].copy()
    R["is_jumps"] = R["race_type"].astype(str).isin(["Hurdle", "Steeple"])
    S = df[df["starter"]]
    gs = S.groupby("race_id", sort=False)
    # --- timing
    R["first_fluc_days_before_start"] = g["first_fluc_min_before_start"].max() / 1440.0
    R["timing_flag_first_gt1d"] = (R["first_fluc_days_before_start"].abs() > 1.0).fillna(False)
    R["timing_flag_first_gt7d"] = (R["first_fluc_days_before_start"].abs() > 7.0).fillna(False)
    R["timing_flag_first_after_start"] = (R["first_fluc_days_before_start"] < 0).fillna(False)
    R["last_fluc_min_before_start"] = np.fmin(g["sb_last_fluc_min"].min(), g["lb_last_fluc_min"].min())
    R["timing_flag_last_gt24h"] = (R["last_fluc_min_before_start"] > 1440).fillna(False)
    R["timing_flag_no_fluc_3h"] = ~(R["last_fluc_min_before_start"] <= 180)
    R["timing_flag_start_date_mismatch"] = R["start_date_mismatch"].astype(bool)
    R["timing_untrusted"] = R["timing_flag_last_gt24h"] | R["timing_flag_no_fluc_3h"] | R["timing_flag_start_date_mismatch"]
    # --- SP book (post-off) + data checks
    R["n_sp"] = gs["sp"].count()
    R["sp_coverage"] = R["n_sp"] / R["n_starters"].where(R["n_starters"] > 0)
    R["sp_complete"] = (R["n_sp"] == R["n_starters"]) & (R["n_starters"] > 0)
    R["overround_sp"] = gs["sp_inv"].sum().where(R["sp_complete"])
    R["sum_sp_p"] = gs["sp_p"].sum(min_count=1)
    R["sp_quality_ok"] = R["sp_complete"] & R["overround_sp"].between(SP_OVERROUND_MIN, SP_OVERROUND_MAX)
    R["n_cofav_sp"] = gs["cofav_sp"].sum()
    R["one_winner"] = (R["n_winners"] == 1) & R["race_resulted"]
    R["race_clean"] = R["race_resulted"] & (R["n_winners"] >= 1) & ~R["field_mismatch_api"].fillna(False) & ~R["dup_entries"] & (R["n_starters"] >= 2)
    # --- winner
    W = S[S["won"].fillna(False).astype(bool)].sort_values(["race_id", "sp_rank"], na_position="last").drop_duplicates("race_id", keep="first").set_index("race_id")
    R["winner_horse"] = W["horse_name"]; R["winner_sp"] = W["sp"]; R["winner_sp_p"] = W["sp_p"]; R["winner_sp_rank"] = W["sp_rank"]; R["winner_barrier"] = W["barrier"]
    for T in SNAP_MINS:
        R[f"winner_M_t{T}"] = W[f"M_t{T}"]; R[f"winner_M_rank_t{T}"] = W[f"M_rank_t{T}"]
        for b in BOOKS:
            R[f"winner_{b}_t{T}"] = W[f"{b}_t{T}"]; R[f"winner_{b}_t{T}_p"] = W[f"{b}_t{T}_p"]; R[f"winner_{b}_t{T}_rank"] = W[f"{b}_t{T}_rank"]

    def fav_block(col, name, src=None):
        F = (S if src is None else src)
        F = F[F[col].fillna(False).astype(bool)].drop_duplicates("race_id").set_index("race_id")
        R[f"{name}_horse"] = F["horse_name"]; R[f"{name}_code"] = F["horse_code"]
        R[f"{name}_finish"] = F["finish_pos"]; R[f"{name}_won"] = F["won"]; R[f"{name}_placed"] = F["placed"]
        return F
    F = fav_block("fav_sp", "fav_sp")
    R["fav_sp_price"] = F["sp"]; R["fav_sp_p"] = F["sp_p"]; R["fav_tied_sp"] = F["fav_tied_sp"]
    R["fav_sp_sb_t30"] = F["sb_t30"]
    s2 = S[S["sp_rank"] == 2].drop_duplicates("race_id").set_index("race_id")
    R["second_fav_sp_price"] = s2["sp"]; R["second_fav_sp_p"] = s2["sp_p"]
    R["fav_gap_p"] = R["fav_sp_p"] - R["second_fav_sp_p"]
    for b in BOOKS:
        R[f"{b}_has_flucs"] = gs[f"{b}_n_flucs"].max() > 0
        R[f"{b}_feed_stale"] = gs[f"{b}_feed_stale"].first()
        for T in SNAP_MINS:
            k = f"{b}_t{T}"
            F2 = fav_block(f"fav_{k}", f"fav_{k}")
            R[f"fav_{k}_price"] = F2[k]; R[f"fav_{k}_p"] = F2[f"{k}_p"]; R[f"fav_{k}_sp"] = F2["sp"]; R[f"fav_{k}_sp_rank"] = F2["sp_rank"]
            R[f"{k}_coverage"] = gs[f"{k}_coverage"].first()
            R[f"n_cofav_{k}"] = gs[f"cofav_{k}"].sum()
            R[f"overround_{k}"] = (1.0 / S[k]).groupby(S["race_id"]).sum().where(R[f"{k}_coverage"] >= 0.999)
    # --- protocol market (U / M) per decision time
    for T in SNAP_MINS:
        R[f"U_size_t{T}"] = g[f"U_size_t{T}"].first()
        R[f"n_late_scratch_t{T}"] = g[f"late_scratch_t{T}"].sum()
        R[f"n_scratch_ambiguous_t{T}"] = g[f"scratch_ambiguous_t{T}"].sum()
        R[f"feed_live_t{T}"] = g[f"feed_live_t{T}"].first()
        R[f"mkt_ok_t{T}"] = g[f"mkt_ok_t{T}"].first()
        R[f"mkt_sbonly_ok_t{T}"] = g[f"mkt_sbonly_ok_t{T}"].first()
        R[f"u_max_quote_age_s_t{T}"] = g[f"u_max_quote_age_s_t{T}"].first()
        U = df[df[f"inU_t{T}"]]
        FM = fav_block(f"fav_M_t{T}", f"fav_M_t{T}", src=U)
        R[f"fav_M_t{T}_M"] = FM[f"M_t{T}"]
        R[f"n_cofav_M_t{T}"] = df.groupby("race_id", sort=False)[f"cofav_M_t{T}"].sum()
        nz = U[f"M_t{T}"].where(~U[f"fav_M_t{T}"].fillna(False).astype(bool))
        R[f"M_best_nonfav_t{T}"] = nz.groupby(U["race_id"]).max()
        R[f"fav_M_t{T}_gap"] = R[f"fav_M_t{T}_M"] - R[f"M_best_nonfav_t{T}"]
    R["fav_changed_t30_sb_to_sp"] = (R["fav_sb_t30_code"] != R["fav_sp_code"]).where(R["fav_sb_t30_code"].notna() & R["fav_sp_code"].notna())
    R["fav_sp_won"] = R["fav_sp_won"].astype("boolean")
    R["fav_sp_placed"] = R["fav_sp_placed"].astype("boolean")
    # --- legacy baseline sample (used for the descriptive baseline facts; independent of the protocol's 900s quote rule)
    R["baseline_ok"] = (R["is_au"] & R["race_clean"] & (R["n_starters"] >= 5) & (R["n_winners"] == 1) & R["sp_quality_ok"]
                        & (R["sb_t30_coverage"].fillna(0) >= MIN_QUOTE_COVERAGE) & ~R["sb_feed_stale"].fillna(True).astype(bool))
    # --- pre-decision funnel
    fail = {
        "non_au": ~R["is_au"],
        "trial_or_jumpout": pd.Series(False, index=R.index),
        "u_lt5": R["U_size_t30"] < 5,
        "not_market_eligible": ~R["mkt_ok_t30"].fillna(False).astype(bool),
        "feed_not_live": ~R["feed_live_t30"].fillna(False).astype(bool),
        "timing_untrusted": R["timing_untrusted"],
        "examined": R["examined"],
    }
    reason = pd.Series("", index=R.index, dtype=object)
    for code, _ in EXCL_RULES:
        reason = reason.where(reason != "", np.where(fail[code], code, ""))
    R["excl_reason"] = reason
    R["in_sample"] = R["excl_reason"] == ""
    # --- post-race scoring status (protocol precedence: late scratching, dead heat, no result); NOT exclusions from the table
    ss = pd.Series("ok", index=R.index, dtype=object)
    ss = ss.where(R["race_resulted"], "no_result")
    ss = ss.where(~(R["race_resulted"] & (R["n_winners"] >= 2)), "dead_heat")
    ss = ss.where(~(R["race_resulted"] & (R["n_winners"] == 0)), "no_winner_recorded")
    ss = ss.where(~(R["n_late_scratch_t30"] > 0), "late_scratching")
    R["scoring_status_t30"] = ss
    R = R.reset_index()
    return R


def funnel_tables(R):
    order = [c for c, _ in EXCL_RULES]
    desc = dict(EXCL_RULES)
    rows, rem = [], len(R)
    rows.append(dict(step=0, rule="all races in dump", description="", removed=0, remaining=rem))
    for i, c in enumerate(order, 1):
        n = int((R["excl_reason"] == c).sum())
        rem -= n
        rows.append(dict(step=i, rule=c, description=desc[c], removed=n, remaining=rem))
    inc = R[R["excl_reason"] == ""]
    for j, (st, n) in enumerate(inc["scoring_status_t30"].value_counts().items(), len(order) + 1):
        rows.append(dict(step=f"post-race: {st}", rule=f"scoring_status={st}", description="post-race scoring count among pre-decision-eligible races (not an exclusion)", removed=np.nan, remaining=int(n)))
    overall = pd.DataFrame(rows)
    X = R.copy()
    X["state"] = X["state"].astype(str)
    X["excl_reason"] = X["excl_reason"].replace("", "INCLUDED")
    by = X.pivot_table(index=["year", "state"], columns="excl_reason", values="race_id", aggfunc="count", fill_value=0)
    for c in order + ["INCLUDED"]:
        if c not in by.columns:
            by[c] = 0
    by = by[order + ["INCLUDED"]]
    by.insert(0, "total_races", by.sum(axis=1))
    byblock = X.pivot_table(index="block", columns="excl_reason", values="race_id", aggfunc="count", fill_value=0)
    for c in order + ["INCLUDED"]:
        if c not in byblock.columns:
            byblock[c] = 0
    byblock = byblock[order + ["INCLUDED"]]
    byblock.insert(0, "total_races", byblock.sum(axis=1))
    # post-race scoring counts among pre-decision-eligible races by year/state
    Y = X[X["excl_reason"] == "INCLUDED"]
    post = Y.pivot_table(index=["year", "state"], columns="scoring_status_t30", values="race_id", aggfunc="count", fill_value=0)
    post.insert(0, "pre_decision_eligible", post.sum(axis=1))
    # sensitivity: how many races would pass the market-eligibility rule at other quote-age limits (T-30 and other T), among races passing every OTHER pre-decision rule
    rows2 = []
    for T in SNAP_MINS:
        other = (X["state"].isin(AU_STATES)) & (X[f"U_size_t{T}"] >= 5) & (~X["timing_untrusted"]) & (~X["examined"])
        o = X[other]
        for yr, grp in list(o.groupby("year")) + [("all", o)]:
            r = dict(T=f"T-{T}", year=yr, races_passing_other_rules=len(grp))
            for L in AGE_LIMITS:
                r[f"market_ok_age<={L}s"] = int((grp[f"u_max_quote_age_s_t{T}"] <= L).sum())
            r["market_ok_any_age(all U quoted by both)"] = int(grp[f"u_max_quote_age_s_t{T}"].notna().sum())
            rows2.append(r)
    age_sens = pd.DataFrame(rows2)
    return overall, by, byblock, post, age_sens



DICT = [
 # (columns, kind, description)   -- "x_*" = prefix match
 ("race_id", "key", "meeting_id + '_' + race_number; unique per race"),
 ("meeting_id, date, venue, state, race_number", "key", "date = local meeting date (used for blocks); venue = racing.com slug; state NSW/VIC/QLD/SA/WA/TAS/NT/ACT or HK (HK rows are in runners_excluded only)"),
 ("mel_date", "key", "calendar date of the scheduled start in Australia/Melbourne - the clock for ALL history windows ('earlier calendar days')"),
 ("start_utc, start_ts", "key", "recorded scheduled race start, UTC (naive datetime) / epoch seconds. The recorded start is the last schedule racing.com holds; the actual jump is often a few minutes later"),
 ("year, is_au", "key", "calendar year of date; Australian state/territory meeting"),
 ("block", "key", "by race date: history_only 2022-07-01..2022-12-31 (never scored), train 2023-01-01..2025-06-30, tune1 2025-07-01..2025-12-31, tune2 2026-01-01..2026-04-30, final 2026-05-01..2026-09-28 (sealed: no outcome statistics are reported on it), excluded 2026-09-29..2026-10-29 (development month)"),
 ("examined", "key", "True for races listed in research/examined.csv: every race 2026-09-29..2026-10-29 and Doomben 2026-08-01 R1. Never use in confirmatory tests"),
 ("horse_code, horse_name, entry_no", "key", "horse id (racing.com horseCode), name, raceEntryNumber"),
 ("scratched, emergency, starter", "pre", "scratched = recorded as withdrawn. starter = actually ran (resulted race: not scratched and has a finish code; unresulted race: not scratched and not an emergency). Analyses of outcomes should filter starter==True"),
 ("race_name, distance_m, class_raw, class_rdc, race_type, group", "context", "racing.com race descriptors. class_rdc = racing.com's normalised class"),
 ("class_cat, class_level", "context", "class_cat: Maiden/BM/Class/Open/Picnic/Quality/Listed/G1-G3/Other. class_level = CRUDE ordinal proxy (BM number where known) used only for 'class change'"),
 ("track_cond, track_cond_src, track_rating, cond_ord", "context (FINAL values)", "FINAL surface condition for the race (race value, falling back to the meeting value). It is the end-of-day record, NOT what was known at T: never use today's value as a primary feature. cond_ord Firm/Fast 1, Good 2, Soft 3, Heavy 4"),
 ("surface, rail, weather, penetrometer, rainfall", "context (FINAL values)", "meeting-level context as last recorded (rail = railPosition text); not point-in-time"),
 ("n_starters, n_scratched, n_unscratched_nonstarters, places_paid, race_resulted", "context", "actual starters; scratchings; entries not scratched but that did not start (emergencies); places_paid 3 if >=8 starters, 2 if 5-7, else 1; any starter has a finish"),
 ("runners_count_api, field_mismatch_api, dup_entries", "dq", "API runnersCount; flag if it disagrees with n_starters; dup_entries = racing.com listed the horses twice in the race (de-duplicated; barrier/jockey may be unreliable)"),
 ("barrier, weight_kg, jockey, jockey_id, trainer, trainer_id, handicap_rating, gear_changes, sire, dam, sire_of_dam_code", "pre", "declared pre-race attributes. barrier 0 -> NaN. handicap_rating at a PAST race may have been revised: flagged, report with and without"),
 ("speed_value_unverified", "do not use", "racing.com speedValue: may be written after the race -> never used in any history feature"),
 ("horse_age_now, horse_sex_now", "AS-OF-NOW (do not use)", "racing.com horse.age / horse.sex are the CURRENT profile at collection (2026-10-29), constant over a horse's career in the dumps (mean age falls 8.3 -> 5.4 across 2023..2026 races). Not point-in-time"),
 ("age_at_race_est", "pre (estimate)", "estimated racing age at the race = horse_age_now - number of 1-Aug rollovers between race and 2026-10-29"),
 ("excl_reason, race_in_sample", "dq", "excl_reason = first PRE-DECISION filter the race fails (blank = eligible); runners.* holds the eligible races, runners_excluded.* the rest (same columns, includes HK)"),
 ("rc_fluc_open, rc_fluc_m1, rc_fluc_m2", "pre?", "racing.com bettingFluctuationsPriceOpen/MoveOne/MoveTwo; timing semantics undocumented - unverified"),
 ("finish_code, finish_pos, dnf, won, placed", "outcome", "finish_code raw (109=scratched, 100-107 did not finish). finish_pos NaN for DNF. won = finish_pos==1 (dead heats give 2 winners). placed per places_paid"),
 ("win_margin_len, margin_behind_len, n_winners", "outcome", "racing.com margin is cumulative lengths behind the winner (the winner's own value is its winning margin): margin_behind_len = 0 for winner; win_margin_len = winner's margin over 2nd; n_winners = runners with finish 1"),
 ("sp, sp_inv, sp_p, sp_rank, fav_sp, sp_coverage, fav_tied_sp, sp_race_sum_inv, cofav_sp", "market (post-off)", "sp = racing.com startingPrice (== provider 'OP' price in ~99% of cases; fixed-odds style closing price, NOT a tote dividend; can be stale/odd on bush meetings). sp_p = margin-free probability over starters (NaN if <80% starters have SP). sp_rank unique (ties: sb_final, lb_final, barrier). Starting price NEVER fills a missing quote"),
 ("sb_open, lb_open, sb_open_min, lb_open_min", "market", "first recorded fluc per entry (Sportsbet/Ladbrokes) and minutes before start; the first price the collector saw, not necessarily the bookmaker's true opening"),
 ("sb_t60, sb_t30, sb_t10, sb_t2, lb_t60, lb_t30, lb_t10, lb_t2", "market (quote at T)", "RAW quote live at T = last fluc at or before (scheduled start - T min), for ALL entries incl. scratched ones. Companion columns: <col>_age_s (seconds T minus quote time), <col>_n_later (flucs after T up to the scheduled start), <col>_later_fluc (n_later>0), <col>_usable (quote exists: v0.5 change events, any age)"),
 ("sb_t60_p, sb_t30_p, sb_t10_p, sb_t2_p, lb_t60_p, lb_t30_p, lb_t10_p, lb_t2_p, sb_open_p, lb_open_p, sb_final_p, lb_final_p", "market (legacy, starters)", "DESCRIPTIVE margin-free probability over ACTUAL STARTERS, any quote age, NaN if <80% of starters quoted or the race's feed was dead near the off (feed_stale). Not the protocol market; use m_*/M_* for that"),
 ("fav_sb_t60, fav_sb_t30, fav_sb_t10, fav_sb_t2, fav_lb_t60, fav_lb_t30, fav_lb_t10, fav_lb_t2, cofav_sb_t60, cofav_sb_t30, cofav_sb_t10, cofav_sb_t2, cofav_lb_t60, cofav_lb_t30, cofav_lb_t10, cofav_lb_t2", "market (legacy, starters)", "favourite flag (rank 1, ties broken by SP then barrier) and co-favourite flag (tied shortest price) in the legacy starters-based market"),
 ("sb_t60_rank, sb_t30_rank, sb_t10_rank, sb_t2_rank, lb_t60_rank, lb_t30_rank, lb_t10_rank, lb_t2_rank, sb_open_rank, lb_open_rank, sb_final_rank, lb_final_rank", "market (legacy, starters)", "unique price rank among starters (1 = shortest)"),
 ("sb_t60_coverage, sb_t30_coverage, sb_t10_coverage, sb_t2_coverage, lb_t60_coverage, lb_t30_coverage, lb_t10_coverage, lb_t2_coverage, sb_open_coverage, lb_open_coverage, sb_final_coverage, lb_final_coverage", "dq", "share of starters quoted"),
 ("sb_final, lb_final", "market (post-off)", "last fluc ever seen (may include ticks after the scheduled start)"),
 ("sb_last_rel_s, lb_last_rel_s, sb_n_same_prev, lb_n_same_prev", "dq", "seconds from scheduled start to the entry's LAST fluc ever (negative = before start; scratch dating); number of flucs whose price equals the previous fluc (change-event check)"),
 ("sb_n_flucs, lb_n_flucs, sb_feed_stale, lb_feed_stale, sb_last_pre_min, lb_last_pre_min, sb_last_fluc_min, lb_last_fluc_min", "dq", "number of flucs; feed-stale flag (no starter's price changed in the 15 min before the start); race-level / entry-level minutes before start of the last pre-start fluc"),
 ("final_V, final_N, final_Q, final_BT, final_PB3, final_BTOTE, final_OP", "market (post-off)", "final win prices by provider from odds[]"),
 ("inU_t60, inU_t30, inU_t10, inU_t2", "protocol universe", "entry is in the runner universe U at T: not scratched, OR scratched with its last fluc at either book at or after T (v0.5 late scratching). NB: unscratched entries that never started (emergencies) are in U by the literal rule: see n_unscratched_nonstarters"),
 ("late_scratch_t60, late_scratch_t30, late_scratch_t10, late_scratch_t2", "protocol universe", "scratched entry whose last fluc at either book is at or after T (v0.5 dating). scratch_ambiguous_t*: last fluc in (T-900s, T), the cases this dating can misclassify. feed_live_<b>_t*/feed_live_t*: race-level, >=1 fluc on any entry in [T-900s, T]. No scratching timestamps exist; deductions are NOT modelled"),
 ("U_size_t60, U_size_t30, U_size_t10, U_size_t2, mkt_ok_t60, mkt_ok_t30, mkt_ok_t10, mkt_ok_t2, mkt_sbonly_ok_t60, mkt_sbonly_ok_t30, mkt_sbonly_ok_t10, mkt_sbonly_ok_t2, u_all_usable_*, u_max_quote_age_s_*", "protocol market", "race-level (repeated on each row): |U|; market-eligible = EVERY runner in U has a usable quote from both books; sb-only variant; u_max_quote_age_s = max quote age (s) over U across both books (NaN if some U runner has no quote at all), so any age limit can be applied: eligible at limit L iff u_max_quote_age_s <= L"),
 ("m_sb_t60, m_sb_t30, m_sb_t10, m_sb_t2, m_lb_t60, m_lb_t30, m_lb_t10, m_lb_t2", "protocol market", "bookmaker margin-free probability (1/q)/sum over U of 1/q, over the usable-quoted members of U (equals the protocol m_b,i only where the race is fully covered by that book: u_all_usable_<b>)"),
 ("M_t60, M_t30, M_t10, M_t2, M_rank_t60, M_rank_t30, M_rank_t10, M_rank_t2, fav_M_t60, fav_M_t30, fav_M_t10, fav_M_t2, cofav_M_t60, cofav_M_t30, cofav_M_t10, cofav_M_t2", "protocol market", "M = mean of the two books' m (only where mkt_ok); rank 1 = highest M; favourite = within 1e-9 of the max M (co-favourites all True); NaN where race not market-eligible"),
 ("fav_changed_t30_sb_to_sp, sp_over_sb_t30", "market", "T-30 Sportsbet favourite (legacy) differs from the SP favourite; SP / sb_t30 ratio"),
 ("first_fluc_min_before_start", "dq", "minutes before the recorded start of the entry's earliest fluc (either book)"),
 ("start_date_mismatch", "dq", "recorded start more than 1 day from the meeting date (e.g. typed in the wrong year); mel_date is then set to the meeting date; counted in timing_untrusted"),
 ("res_*", "post-race", "THIS race's own post-race data: res_settled/res_pos800/res_pos400, res_comment (stewards), res_time_s, res_top_speed, res_speed_early/mid/late, res_dist_travelled, res_dist_from_rail, res_std_time_diff_len, res_last600_s (sum of the 400m+200m+FINISH `timing` sections; sectional races only), res_last200_s, res_time_sectional_raw (racing.com per-runner timeSectional: in practice identical for all runners of a race), res_last600_rank, res_last600_vs_best, res_time_behind_winner_s. NEVER a feature for the same race"),
 ("race_tempo, race_winning_time_s, race_has_sectionals, race_timing_source, race_std_time_diff_len, race_last600_s", "post-race", "race-level post-race info; `tempo` must never be used"),
 ("ls_*", "history", "LAST START = the horse's most recent earlier run on an EARLIER CALENDAR DAY (Australia/Melbourne), Australian races only: ls_date, ls_start_utc, finish, field, finish_pct, margin_behind, win_margin, sp, sp_p, sp_rank, settled/800/400 positions, last600 (+rank, vs_best), last200, time_behind_winner, std_time_diff, speed_late, comment text, ls_f3_* (FACTORS F3 flags), ls_kw_* (my wider keyword flags; 1/0, NaN if no comment recorded), gear, distance, class, venue, state, condition, surface, weight, jockey, barrier, handicap rating"),
 ("runs_in_ds, wins_in_ds, places_in_ds, days_since_last_run, last3_avg_finish_pct, last5_wins, last3_avg_sp_p", "history", "prior runs inside the dataset only (NOT career); only trustworthy when hist_ok"),
 ("chg_*, ls_gear_changed, gear_changed_today, ls_pos_gain_*", "history", "change today vs last start (distance, class, venue, surface, condition (final values), weight, jockey, barrier, handicap rating)"),
 ("jk90_*, jk365_*, tr90_*, tr365_*", "history", "jockey / trainer record over the previous 90/365 calendar days (dates in [d-N, d-1]): _n rides, _wins, _sr, _ae = wins/sum margin-free SP prob (NaN if <10 priced rides). All Australian venues in the dataset"),
 ("f1_last, f1_avg3, f1_gap, f1_missing", "FACTORS F1", "closing sectional score s = 1-(rank-1)/(n-1) of the run's last-600 (from `timing` sections; n>=4 finishers with sectionals) at last start / mean of last 3 / s minus finishing-position score. RAW values"),
 ("f2_last, f2_avg3, f2_missing", "FACTORS F2", "ground made g = (pos at 800 - finish)/field, last start / mean of last 3. RAW"),
 ("f3_any, f3_count3, f3_missing", "FACTORS F3", "any excuse flag (slow/held/checked/wide/keen regexes exactly as in FACTORS.md) at last start / count in last 3"),
 ("f4_bad, f4_missing", "FACTORS F4", "bad-sign regex at last start"),
 ("f5_avg3, f5_missing", "FACTORS F5", "mean over last 3 of distanceTravelled - race distance (m)"),
 ("f6_last, f6_avg3, f6_missing", "FACTORS F6", "topSpeed / race median topSpeed (>=4 values), last start / mean of last 3"),
 ("f7_style, f7_L, f7_missing", "FACTORS F7 inputs", "f7_style = RAW style S (mean over last 5 runs of (settled-1)/(field-1), >=2 runs). f7_L = RAW race-level pace count: number of runners in U (T-30) with S <= 0.25. L is an INPUT only, not a feature on its own; analysts form z(S) and z(S)*z_L on training data"),
 ("f10_move, f10_move_t60, f10_move_t30, f10_move_t10, f10_move_t2, f10_missing", "FACTORS F10", "RAW ln(open/quote at T) averaged over the available books (f10_move = T-30)"),
 ("f11_sb_lb, f11_abs, f11_missing", "FACTORS F11", "ln(m_sb/m_lb) at T-30 and its absolute value (NaN unless both m available)"),
 ("f12_fav, f12_G, f12_missing", "FACTORS F12 inputs", "f12_fav = favourite indicator (highest M at T-30; co-favourites all 1). f12_G = RAW race-level gap M_fav - M of the best non-favourite (identical for every runner of a race; NaN if no market-eligible M). Analysts build fav*(G-mu)/sigma and fav*(f10_move-mu)/sigma with training-favourite moments"),
 ("f13_jockey, f13_change, f13_n, f13_missing", "FACTORS F13", "shrunk AE20 (=(W+20)/(E+20)) of today's jockey over the prior 365 days (>=10 rides) and its difference to last start's jockey"),
 ("f14_14d, f14_14d_n, f14_365d, f14_365d_n, f14_missing", "FACTORS F14", "trainer AE5 over prior 14 days (>=3 runners) and AE20 over prior 365 days"),
 ("f15_pair, f15_n, f15_missing", "FACTORS F15", "jockey x trainer pair AE10 over prior 730 days (>=5 rides)"),
 ("f16_dr, f16_missing", "FACTORS F16", "today's handicapRating minus last start's (possibly revised ratings)"),
 ("f17_newdist, f17_newtrack, f17_prior_runs_band, f17_prior_runs_venue, f17_prior_wet_run, f17_sire_wet_ae10, f17_sire_wet_n, f17_missing", "FACTORS F17 inputs", "no prior run in today's 200 m distance band / at this venue (True also for a horse with no history: only trustworthy when hist_ok); prior wet-run flag and sire progeny AE10 on wet races over 1095 days are INPUTS. f17_newwet and f17_sire_wet need the DECLARED wet flag in the earliest record before T, which the dumps do not contain (only final conditions): historically missing for every runner (f17_missing = True)"),
 ("f18_cell, f18_n, f18_missing", "FACTORS F18", "(venue, 200 m distance band, barrier group) A/E shrunk AE20 over prior 1095 days (>=30 runners)"),
 ("sameday_*", "EXPLORATORY ONLY", "same-day information, never primary: sameday_jk_*/sameday_tr_* = the connection's earlier rides the same Melbourne day (start strictly earlier; n, wins, exp_wins_sp); sameday_mtg_* = results of earlier races at the same meeting (n_races, mean winner barrier/field, winner settled position/field, share of winners settled <=3, favourite wins, mean log SP of winners). Results of races that jumped minutes earlier may not have been known at T"),
 ("hist_ok, days_into_coverage", "dq", "hist_ok = race date >= contiguous_coverage_start + 90 days (out/meta.json). When False the history features are truncated"),
]

RACE_DICT = [
 ("race_id, meeting_id, date, mel_date, year, block, examined, venue, state, race_number, start_utc, start_ts, race_name", "key", "as runners table"),
 ("distance_m, class_raw, class_rdc, class_cat, class_level, race_type, group, track_cond, track_cond_src, track_rating, surface, rail, weather", "context (FINAL values)", "race context; condition/rail are final values, not point-in-time"),
 ("n_starters, n_scratched, n_unscratched_nonstarters, places_paid, race_resulted, n_winners", "context/outcome", "actual starters; scratchings; unscratched non-starters; places paid; any result; winners (dead heat = 2)"),
 ("is_au, is_jumps, excl_reason, in_sample", "key/dq", "excl_reason = first PRE-DECISION filter failed: non_au, trial_or_jumpout, u_lt5, not_market_eligible (some U runner unquoted at T-30), feed_not_live, timing_untrusted, examined; blank = in_sample. is_jumps flagged only"),
 ("scoring_status_t30", "post-race", "post-race scoring status (precedence late_scratching > dead_heat/no_winner_recorded > no_result; else ok). A COUNT, not an exclusion from the table"),
 ("U_size_t*, n_late_scratch_t*, mkt_ok_t*, mkt_sbonly_ok_t*, u_max_quote_age_s_t*", "protocol market", "|U|, inferred late scratchings, market eligibility (every U runner usable quote from both books / sb only), max quote age over U (apply any age limit)"),
 ("fav_M_t*, n_cofav_M_t*, M_best_nonfav_t*, winner_M_t*, winner_M_rank_t*", "protocol favourite", "favourite by highest M (ties within 1e-9 all favourites; the *_horse/_code/_finish/_won/_placed columns describe one of them), co-favourite count, best non-favourite M, G = fav_M_t*_gap, and where the winner stood"),
 ("timing_flag_first_gt1d, timing_flag_first_gt7d, timing_flag_first_after_start, first_fluc_days_before_start", "dq (timing)", "recorded start vs the earliest fluc of any entry (days). Markets open 1-4 days ahead so gt1d is true for most races; gt7d / after_start are the plausible anomaly flags"),
 ("last_fluc_min_before_start, timing_flag_last_gt24h, timing_flag_no_fluc_3h, timing_untrusted", "dq (timing)", "protocol timing rule: recorded start > 24h from the last fluc, or no fluc within 3h before the start -> timing_untrusted (counted and excluded from the eligible table)"),
 ("baseline_ok", "dq", "descriptive baseline sample flag (AU, clean result, >=5 starters, one winner, full SP with sane overround, usable legacy SB T-30 market). Independent of the protocol's 900 s rule"),
 ("n_cofav_sp, n_cofav_*", "market", "number of runners tied for the shortest price (SP / legacy snapshot)"),
 ("fav_sb_t60_*, fav_sb_t30_*, fav_sb_t10_*, fav_sb_t2_*, fav_lb_t60_*, fav_lb_t30_*, fav_lb_t10_*, fav_lb_t2_*", "favourite (legacy)", "favourite in the legacy starters-based book market at each decision time: horse, code, finish, won, placed, price, p, sp, sp_rank"),
 ("sb_t60_coverage, sb_t30_coverage, sb_t10_coverage, sb_t2_coverage, lb_t60_coverage, lb_t30_coverage, lb_t10_coverage, lb_t2_coverage, overround_sb_t60, overround_sb_t30, overround_sb_t10, overround_sb_t2, overround_lb_t60, overround_lb_t30, overround_lb_t10, overround_lb_t2", "dq/market", "share of starters quoted; overround only when 100% quoted"),
 ("sb_t60_fresh900_cov, sb_t30_feed_age_s", "dq", "(legacy) see runners dictionary"),
 ("one_winner, race_clean", "dq", "one_winner = resulted and exactly one winner. race_clean = resulted, >=1 winner, runnersCount == n_starters, no duplicate-entry artefact, >=2 starters"),
 ("dup_entries, runners_count_api, field_mismatch_api", "dq", "see runners dictionary"),
 ("n_sp, sp_coverage, sp_complete, overround_sp, sum_sp_p, sp_quality_ok", "dq/market", "SP availability; sp_quality_ok = sp_complete and overround in [1.05,1.50]"),
 ("fav_sp_*, fav_tied_sp", "favourite", "favourite by SP (unique rank 1). _price = SP; _p = margin-free prob"),
 ("second_fav_sp_price, second_fav_sp_p, fav_gap_p", "favourite", "second favourite and probability gap"),
 ("winner_*", "outcome", "the winner (lowest SP rank if a dead heat) and where each market had it"),
 ("sb_has_flucs, lb_has_flucs, sb_feed_stale, lb_feed_stale", "dq/market", "any flucs at all; feed dead near the off"),
 ("fav_changed_t30_sb_to_sp", "market", "legacy SB T-30 favourite differs from SP favourite"),
 ("race_tempo, race_winning_time_s, race_has_sectionals, race_timing_source, race_std_time_diff_len, race_last600_s", "post-race", "race-level post-race timing info"),
 ("hist_ok, days_into_coverage, f7_L", "dq / F7 input", "history trust flag for the race date; f7_L = pace count (see runners dictionary)"),
]

def full_dictionary(table, groups):
    """per-column dictionary: dtype, non-null share and the DICT group that covers the column (by name / prefix match)."""
    toks = []
    for gi, (names, kind, desc) in enumerate(groups):
        names = re.sub(r"\([^)]*\)", "", names)
        for t in [x.strip() for x in names.split(",") if x.strip()]:
            toks.append((t.replace("/", ""), gi))
    rows = []
    for c in table.columns:
        gi = None
        for t, g in toks:
            if t.endswith("*"):
                if c.startswith(t[:-1]):
                    gi = g; break
            elif c == t or c.startswith(t + "_") or c.startswith("fav_" + t) or c == f"fav_{t}":
                gi = g; break
        names, kind, desc = groups[gi] if gi is not None else ("", "unassigned", "")
        rows.append(dict(column=c, dtype=str(table[c].dtype), non_null_share=round(float(table[c].notna().mean()), 4), kind=kind, group=names, description=desc))
    return pd.DataFrame(rows)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(extra_dirs=(), log=print):
    """manifest.json: sha256 + size of every output file (out/, reports/ and the two scripts)."""
    files = []
    for d in (OUT,) + tuple(extra_dirs):
        if os.path.isdir(d):
            files += [os.path.join(d, f) for f in sorted(os.listdir(d))]
    files += [f"{BASE}/build.py", f"{BASE}/validate.py"]
    man = {os.path.relpath(f, BASE): dict(sha256=sha256_file(f), bytes=os.path.getsize(f)) for f in files if os.path.isfile(f)}
    dest = f"{BASE}/manifest.json" if OUT == f"{BASE}/out" else f"{OUT}/manifest.json"   # test runs (--max-files) never touch the real manifest
    with open(dest, "w") as fh:
        json.dump(dict(generated=datetime.datetime.now(datetime.timezone.utc).isoformat(), files=man), fh, indent=1)
    log(f"manifest: {len(man)} files")


def write_outputs(df, races, meta, csv=True, log=print):
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):                      # no stale files from earlier builds
        os.remove(os.path.join(OUT, f))
    # route races / runners
    key = races.set_index("race_id")
    df["excl_reason"] = df["race_id"].map(key["excl_reason"]).astype("category")
    df["race_in_sample"] = df["race_id"].map(key["in_sample"]).astype(bool)
    overall, by, byblock, post, age_sens = funnel_tables(races)
    overall.to_csv(f"{OUT}/funnel_overall.csv", index=False)
    by.to_csv(f"{OUT}/funnel_by_year_state.csv")
    byblock.to_csv(f"{OUT}/funnel_by_block.csv")
    post.to_csv(f"{OUT}/funnel_post_race_by_year_state.csv")
    age_sens.to_csv(f"{OUT}/funnel_quote_age_sensitivity.csv", index=False)
    meta["funnel_overall"] = overall.to_dict("records")
    parts = {"runners": df[df["race_in_sample"]], "runners_excluded": df[~df["race_in_sample"]],
             "races": races[races["in_sample"]], "races_excluded": races[~races["in_sample"]]}
    shapes = {}
    for name, t in parts.items():
        t = t.reset_index(drop=True)
        t.to_pickle(f"{OUT}/{name}.pkl.gz", compression={"method": "gzip", "compresslevel": 3})
        if csv:
            t.to_csv(f"{OUT}/{name}.csv.gz", index=False, compression={"method": "gzip", "compresslevel": 3})
        shapes[name] = list(t.shape)
        log(f"wrote {name}: {t.shape}")
    pd.DataFrame(DICT, columns=["columns", "kind", "description"]).to_csv(f"{OUT}/column_dictionary.csv", index=False)
    pd.DataFrame(RACE_DICT, columns=["columns", "kind", "description"]).to_csv(f"{OUT}/column_dictionary_races.csv", index=False)
    full_dictionary(df, DICT).to_csv(f"{OUT}/columns_runners_full.csv", index=False)
    full_dictionary(races, RACE_DICT).to_csv(f"{OUT}/columns_races_full.csv", index=False)
    meta["shapes"] = shapes
    same = sum(float(df[f"{b}_n_same_prev"].sum()) for b in BOOKS)
    pairs = sum(float((df[f"{b}_n_flucs"] - 1).clip(lower=0).sum()) for b in BOOKS)
    meta["change_event_check"] = dict(consecutive_pairs=pairs, same_price_pairs=same, share_same=same / pairs if pairs else None)
    meta["built_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    meta["columns_runners"] = list(df.columns)
    meta["columns_races"] = list(races.columns)
    meta["blocks"] = BLOCKS
    with open(f"{OUT}/meta.json", "w") as fh:
        json.dump(meta, fh, indent=1, default=str)
    write_manifest(log=log)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-csv", action="store_true")
    ap.add_argument("--max-files", type=int, default=0)
    ap.add_argument("--force-reparse", action="store_true")

    a = ap.parse_args()
    global OUT
    if a.max_files:          # test runs never overwrite the real outputs
        OUT = f"{BASE}/out_test"
    files = sorted(glob.glob(f"{SRC}/*.json.gz"))
    if a.max_files:
        files = files[: a.max_files]
    t0 = time.time()
    raw, meta = load_or_parse(files, a.force_reparse)
    holder = [raw]
    del raw
    meta["source_files_seen"] = len(files)
    df = assemble(holder, meta)
    races = build_races(df)
    write_outputs(df, races, meta, csv=not a.no_csv)
    print(f"done in {time.time()-t0:.0f}s; coverage start {meta['contiguous_coverage_start']}, history ok from {meta['history_complete_from']}")


if __name__ == "__main__":
    main()
