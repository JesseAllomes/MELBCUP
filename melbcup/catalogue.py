# ruff: noqa: E501
"""Sport-agnostic PointsBet catalogue: every outcome of every market of every upcoming event, in every
supported sport, as `Selection`s plus the catalogue_format.md fields. Lossless by construction: an
outcome the mapping tables do not recognise is kept with `mapped=False`, market_family "other" and its
raw label. No probability is invented (`market_prob` is the proportional no-vig of a complete
two-way group only) and `model_status` is "market-only" except NBA's four modelled stats.

    build(sport_keys, fetch, now) -> {"docs", "coverage", "unmapped", "raw"}
    write_build(result, write)    # write(name, bytes): a blob container or a folder (CATALOGUE_DIR)

Visibility never depends on a model, a price, a stale quote or any recommendation policy.
"""

from __future__ import annotations

import gzip
import json
import re
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

try:
    from .markets import MODELLED, Selection, _iso, _parse, apply_no_vig
except ImportError:  # the deployed Function package: flat modules copied by azure-deploy.yml
    from markets import MODELLED, Selection, _iso, _parse, apply_no_vig

API = "https://api.au.pointsbet.com/api/v2"
PB = "https://api.au.pointsbet.com/api/mes/v3"
PROVIDER = "pb"
BOOKMAKER = "PointsBet"
STALE_AFTER_S = 900
MAX_EVENT_CALLS = 400
HOURS = 48
CONCURRENCY = 4
RAW_KEEP_DAYS = 3

# PointsBet sport key -> the catalogue sport keys (the first is the default for the sport)
PB_SPORTS = {
    "basketball": "basketball",
    "american-football": "american-football",
    "aussie-rules": "aussie-rules",
    "rugby-league": "rugby-league",
    "soccer": "soccer",
    "ice-hockey": "ice-hockey",
    "tennis": "tennis",
    "cricket": "cricket",
    "baseball": "baseball",
    "rugby-union": "rugby-union",
}
# catalogue sport key -> PointsBet sport; keys that only the league split produces are "<sport>-other"
SPORT_KEYS = {
    "nba": "basketball", "nbl": "basketball", "ncaab": "basketball", "basketball-other": "basketball",
    "nfl": "american-football", "ncaaf": "american-football", "american-football-other": "american-football",
    "afl": "aussie-rules", "aflw": "aussie-rules",
    "nrl": "rugby-league", "rugby-league": "rugby-league",
    "football": "soccer",
    "nhl": "ice-hockey", "ice-hockey-other": "ice-hockey",
    "tennis": "tennis", "cricket": "cricket",
    "mlb": "baseball", "baseball-other": "baseball",
    "rugby-union": "rugby-union",
}  # fmt: skip
CORE_KEYS = ("nba", "nfl", "nhl", "afl", "aflw", "nrl", "mlb", "nbl", "ncaab", "ncaaf", "rugby-league", "football",
             "cricket", "rugby-union", "tennis")  # fmt: skip


def sport_key(pb_sport: str, competition: str) -> str:
    """The catalogue sport key of a PointsBet competition."""
    c = (competition or "").lower()
    if pb_sport == "basketball":
        if c in ("nba", "nba cup", "nba summer league") or c.startswith("nba "):
            return "nba"
        if c in ("nbl", "wnbl") or c.startswith("nbl ") or c.startswith("wnbl"):
            return "nbl"
        if c.startswith("ncaa"):
            return "ncaab"
        return "basketball-other"
    if pb_sport == "american-football":
        if c == "nfl" or c.startswith("nfl "):
            return "nfl"
        if c.startswith("ncaa"):
            return "ncaaf"
        return "american-football-other"
    if pb_sport == "aussie-rules":
        return "aflw" if "aflw" in c else "afl"
    if pb_sport == "rugby-league":
        return "nrl" if c == "nrl" or c.startswith("nrl ") else "rugby-league"
    if pb_sport == "ice-hockey":
        return "nhl" if c == "nhl" or c.startswith("nhl ") else "ice-hockey-other"
    if pb_sport == "baseball":
        return "mlb" if c == "mlb" or c.startswith("mlb ") else "baseball-other"
    return {"soccer": "football"}.get(pb_sport, pb_sport)


def is_futures(name: str) -> bool:
    n = (name or "").lower()
    return "futures" in n or "outright" in n


# ---- classification tables ------------------------------------------------------------------

# Player stat families, first match wins (the text is lower-cased "<market name>"). Combined stats
# first, then specific stats, then the generic ones.
_PLAYER = [
    (r"pts\s*\+\s*rebs\s*\+\s*asts|points\s*\+\s*rebounds\s*\+\s*assists", "player_pra"),
    (r"points\s*\+\s*rebounds|pts\s*\+\s*rebs", "player_points_rebounds"),
    (r"points\s*\+\s*assists|pts\s*\+\s*asts", "player_points_assists"),
    (r"rebounds\s*\+\s*assists|rebs\s*\+\s*asts", "player_rebounds_assists"),
    (r"steals\s*\+\s*blocks", "player_steals_blocks"),
    (r"rushing\s*\+\s*receiving", "player_rushing_receiving_yards"),
    (r"triple[- ]double", "player_triple_double"),
    (r"double[- ]double", "player_double_double"),
    (r"first basket|first field goal", "player_first_scorer"),
    (r"most points", "player_most_points"),
    (r"passing touchdowns|passing tds|pass tds", "player_passing_tds"),
    (r"rushing touchdowns|rushing tds", "player_rushing_tds"),
    (r"receiving touchdowns|receiving tds", "player_receiving_tds"),
    (r"touchdown", "player_td_scorer"),
    (r"passing yards|pass yards", "player_passing_yards"),
    (r"pass attempts|passing attempts", "player_pass_attempts"),
    (r"completions", "player_pass_completions"),
    (r"interceptions", "player_interceptions"),
    (r"rushing yards|rush yards", "player_rushing_yards"),
    (r"rushing attempts|carries|rush attempts", "player_rushing_attempts"),
    (r"receiving yards", "player_receiving_yards"),
    (r"receptions", "player_receptions"),
    (r"longest", "player_longest"),
    (r"sacks", "player_sacks"),
    (r"try assists?", "player_try_assists"),
    (r"line breaks?", "player_line_breaks"),
    (r"run metres|run meters|metres|meters", "player_run_metres"),
    (r"tries|\btry\b|try ?scorer", "player_tries"),
    (r"kicking goals|conversions", "player_kicking_goals"),
    (
        r"hat[- ]?trick|goalscorer|goal scorer|to score.*goals?|goals? scorer|to score in both halves",
        "player_goalscorer",
    ),
    (r"shots on target", "player_shots_on_target"),
    (r"shots on goal|shots", "player_shots"),
    (r"blocked shots", "player_blocked_shots"),
    (r"saves", "player_saves"),
    (r"red card|card|booked", "player_cards"),
    (r"passes", "player_passes"),
    (r"offsides?", "player_offsides"),
    (r"fouls (committed|drawn|won)", "player_fouls"),
    (r"penalty minutes", "player_penalty_minutes"),
    (r"power[- ]play", "player_power_play_points"),
    (r"disposals", "player_disposals"),
    (r"kicks", "player_kicks"),
    (r"handballs", "player_handballs"),
    (r"marks", "player_marks"),
    (r"hit[- ]?outs", "player_hitouts"),
    (r"clearances", "player_clearances"),
    (r"contested possessions", "player_contested_possessions"),
    (r"fantasy", "player_fantasy_points"),
    (r"behinds", "player_behinds"),
    (r"total bases", "player_total_bases"),
    (r"home runs?", "player_home_runs"),
    (r"\brbis?\b|runs batted", "player_rbi"),
    (r"strikeouts?", "player_strikeouts"),
    (r"outs recorded", "player_outs_recorded"),
    (r"earned runs", "player_earned_runs"),
    (r"walks", "player_walks"),
    (r"sixes", "player_sixes"),
    (r"boundaries|fours", "player_boundaries"),
    (r"wickets", "player_wickets"),
    (r"maidens", "player_maidens"),
    (r"economy", "player_economy"),
    (r"catches", "player_catches"),
    (
        r"top .*(batter|bowler|run ?scorer|wicket|scorer)|player of the match|first player dismissed",
        "player_top_performer",
    ),
    (r"run bands?", "player_runs"),
    (r"\bruns\b", "player_runs"),
    (r"\bhits\b", "player_hits"),
    (r"aces", "player_aces"),
    (r"double faults", "player_double_faults"),
    (r"break points", "player_break_points"),
    (r"games won|service holds", "player_games_won"),
    (r"three|3-?pointers?|3-?pt", "player_threes"),
    (r"steals", "player_steals"),
    (r"blocks", "player_blocks"),
    (r"turnovers", "player_turnovers"),
    (r"fouls", "player_fouls"),
    (r"minutes", "player_minutes"),
    (r"field goals", "player_field_goals"),
    (r"free throws", "player_free_throws"),
    (r"rebounds", "player_rebounds"),
    (r"assists", "player_assists"),
    (r"tackles", "player_tackles"),
    (r"goals?\b", "player_goals"),
    (r"\bpoints\b", "player_points"),
]
_PLAYER_RE = [(re.compile(p), f) for p, f in _PLAYER]
# a scorer market reads "goals" in AFL/NHL, "tries" in rugby league
_SCORER_ALIAS = {"afl": "player_goals", "aflw": "player_goals", "nhl": "player_goals",
                 "ice-hockey-other": "player_goals", "nrl": "player_tries",
                 "rugby-league": "player_tries"}  # fmt: skip

_GAME = [
    (
        r"team total|home total|away total|hometeam total|awayteam total|player [ab] total|"
        r"home team total|away team total",
        "team_total",
    ),
    (r"handicap|spread|puck line|run line|\bline\b|pick your own line", "line"),
    (
        r"total.*(over/under|points|goals|runs|games|sets|corners|tries|match)|totals|alternate total|"
        r"over/under",
        "total",
    ),
    (r"odd/even|odd or even", "odd_even"),
    (
        r"money ?line|match result|match winner|win match|head to head|to win|\bresult\b|"
        r"winner|3 way|draw no bet",
        "h2h",
    ),
    (r"double chance", "double_chance"),
    (r"both teams to score", "btts"),
    (r"correct score", "correct_score"),
    (r"winning margin|margin", "margin"),
    (r"corner", "corners"),
    (r"clean sheet|to win to nil", "clean_sheet"),
    (r"half[- ]?time/full[- ]?time|ht/ft", "ht_ft"),
    (r"first (team|to) score|last (team|to) score|first scoring|race to", "first_to_score"),
    (r"set betting|set x|sets", "sets"),
    (r"premiership|outright|to win the", "outright"),
    (
        r"(teams?|team not) (not )?to score|score in both halves|win (either|both) halves|"
        r"exact number of goals|(1st|2nd) half goals|which half|first team to score",
        "team_scoring",
    ),
    (r"^total$|overtime|2 point conversion|highest scoring", "game_special"),
]
_GAME_RE = [(re.compile(p), f) for p, f in _GAME]

# markets with no playerId that are still player markets (the name says so)
_PLAYERISH = re.compile(
    r"scorer|player|batter|bowler|top (run|wicket)|disposals|hat-?trick|to be shown a card|"
    r"to (get|score|record|kick|make|hit) \d"
)
_OU = re.compile(r"^(?P<who>.+?) (?P<side>Over|Under) (?P<line>\d+(?:\.\d+)?)$")
_PLUS = re.compile(
    r"^(?P<who>.+?)(?: To (?:Get|Score|Record|Kick|Make|Have|Hit|Take|Win|Be))? (?P<k>\d+(?:\.\d+)?)\+(?: .*)?$"
)
_GAME_OU = re.compile(r"^(?P<side>Over|Under) (?P<line>\d+(?:\.\d+)?)")
_SIGNED = re.compile(r"([+-]\d+(?:\.\d+)?)$")
_PERIODS = [
    (r"1st half|first half|half-time|1h\b", "1h"),
    (r"2nd half|second half|2h\b", "2h"),
    (r"1st quarter|first quarter|\bq1\b", "q1"),
    (r"2nd quarter|second quarter|\bq2\b", "q2"),
    (r"3rd quarter|third quarter|\bq3\b", "q3"),
    (r"4th quarter|fourth quarter|\bq4\b", "q4"),
    (r"1st period", "p1"),
    (r"2nd period", "p2"),
    (r"3rd period", "p3"),
    (r"\bset [x\d]|current set", "set"),
    (r"innings|over \d", "innings"),
    (r"quarter", "quarter"),
]


def period_of(text: str) -> str:
    t = text.lower()
    for pat, tag in _PERIODS:
        if re.search(pat, t):
            return tag
    return "full_game"


def classify(sport: str, name: str, event_class: str, is_player: bool) -> tuple[str, bool]:
    """(market_family, mapped). Unrecognised markets are ("other", False), never dropped."""
    table = _PLAYER_RE if is_player else _GAME_RE
    for text in (name.lower(), event_class.lower()):
        for rx, fam in table:
            if not rx.search(text):
                continue
            if fam == "player_goalscorer":
                fam = _SCORER_ALIAS.get(sport, fam)
            elif fam == "player_td_scorer" and sport not in (
                "nfl",
                "ncaaf",
                "american-football-other",
            ):
                fam = _SCORER_ALIAS.get(sport, "player_goalscorer")
            return fam, True
    return "other", False


def _num(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _strip_event(name: str) -> str:
    return re.sub(r"\s*\([^()]*\)\s*$", "", name or "").strip()


# ---- outcomes -> selections -----------------------------------------------------------------


def _parse_outcome(o: dict, is_player: bool) -> dict:
    """participant / side / line / subtype of one outcome, from the provider's own fields."""
    name = (o.get("name") or "").strip()
    pts, val = _num(o.get("points")), _num(o.get("value"))
    who, side, line, raw, sub = name, "", None, None, None
    if is_player:
        m, p = _OU.match(name), _PLUS.match(name)
        if m:
            who, side, line, raw, sub = (
                m["who"],
                m["side"].lower(),
                float(m["line"]),
                m["line"],
                "over_under",
            )
        elif p:
            who, side, raw, sub = p["who"], "over", p["k"] + "+", "alternate"
            line = val if val is not None else pts
            if line is None or line == 0:
                line = float(p["k"]) - 0.5
        else:
            who, side, sub = name.split(" & ")[0], "yes", "combo" if " & " in name else "yes_no"
            if o.get("side") == "Neither" or name.lower().startswith("no "):
                side = "no"
    else:
        g, s = _GAME_OU.match(name), _SIGNED.search(name)
        if g:
            side, line, raw, sub = g["side"].lower(), float(g["line"]), g["line"], "over_under"
            who = ""
        elif s:
            who = name[: s.start()].strip()
            line, raw = float(s[1]), s[1]
            side = (o.get("side") or "other").lower()
        else:
            side = (o.get("side") or "").lower()
            if side not in ("home", "away"):
                side = re.sub(r"\s+", " ", name.lower())[:60] or "other"
        if line is None and pts:
            line, raw = pts, str(pts)
    return {"who": who, "side": side, "line": line, "raw": raw, "sub": sub}


def event_selections(
    ev: dict, detail: dict, sport: str, fetched_at: datetime, now: datetime
) -> tuple[list[dict], dict]:
    """One event's selections (rows) and its raw/market stats. Every outcome becomes a row."""
    ek = str(ev["key"])
    starts, comp = (
        ev.get("startsAt") or detail.get("startsAt") or "",
        ev.get("competitionName") or "",
    )
    ename = ev.get("name") or detail.get("name") or ""
    sels: list[Selection] = []
    metas: list[dict] = []
    seen: Counter = Counter()
    groups: dict[str, dict] = {}
    markets = (detail.get("fixedOddsMarkets") or []) + (detail.get("specialFixedOddsMarkets") or [])
    raw_outcomes = 0
    quoted = _iso(fetched_at)
    age = (now - fetched_at).total_seconds()
    for m in markets:
        mid = str(m.get("key") or "")
        label = _strip_event(m.get("name") or "") or m.get("eventClass") or ""
        ec = m.get("eventClass") or ""
        outs = m.get("outcomes") or []
        player_group = any(o.get("playerId") for o in outs) or bool(
            _PLAYERISH.search(label.lower()) and not re.search(r"team total|margin", label.lower())
        )
        fam, mapped = classify(sport, label, ec, player_group)
        period = period_of(label)
        gkey = mid
        groups[gkey] = {"market_name_raw": label, "player": player_group, "mapped": mapped}
        for o in outs:
            raw_outcomes += 1
            p = _parse_outcome(o, player_group)
            price = _num(o.get("price"))
            ok = price is not None and price > 1
            oid = f"{o.get('fixedMarketId') or mid}:{o.get('key')}"
            ident = (mid, oid, period, p["line"])
            seen[ident] += 1
            if seen[ident] > 1:
                oid += f"#{seen[ident]}"
            modelled = sport == "nba" and fam in MODELLED and period == "full_game"
            line = p["line"]
            grp_line = abs(line) if fam == "line" and line is not None else line
            sels.append(
                Selection(
                    sport=sport,
                    provider=PROVIDER,
                    event_id=ek,
                    event_name=ename,
                    starts_at=starts,
                    market_type=fam,
                    market_name=label,
                    participant=p["who"],
                    participant_id=str(o["playerId"]) if o.get("playerId") else None,
                    line=line,
                    side=p["side"],
                    price=price if ok else None,
                    quoted_at=quoted,
                    group=f"{ek}|{mid}|{p['who'] if fam != 'line' else ''}|{grp_line}",
                    modelled=modelled,
                    status="verified" if ok else "unverified",
                    status_reason=None if ok else "no valid price",
                    canonical_event_id=None,
                    market_status="open"
                    if o.get("isOpenForBetting", True) is not False
                    else "suspended",
                    period=period,
                    stat=fam if player_group else None,
                    provider_market_id=mid,
                    provider_selection_id=oid,
                    league=comp,
                )
            )
            metas.append({"o": o, "p": p, "fam": fam, "mapped": mapped, "player": player_group,
                          "ec": ec, "gn": m.get("groupName") or "", "oid": oid, "mid": mid,
                          "oid_line": line})  # fmt: skip
    sels = apply_no_vig(sels)
    rows = []
    for s, x in zip(sels, metas, strict=True):
        o, p = x["o"], x["p"]
        base = s.to_schema()
        price_ok = s.price is not None
        susp = o.get("isOpenForBetting", True) is False
        row = {
            **base,
            "provider": PROVIDER,
            "bookmaker": BOOKMAKER,
            "sport_id": sport,
            "league_id": str(ev.get("competitionKey") or ""),
            "event_id": s.event_id,
            "event_start_utc": s.starts_at,
            "event_status": "live" if ev.get("isLive") else "pre",
            "participant_id": s.participant_id,
            "participant_name": s.participant or None,
            "team_id": str(o["teamId"]) if o.get("teamId") else None,
            "market_id": x["mid"],
            "market_name_raw": s.market_name,
            "market_family": x["fam"],
            "market_subtype": p["sub"],
            "stat_key": x["fam"] if x["player"] else None,
            "line_raw": p["raw"],
            "line_numeric": s.line,
            "side": s.side,
            "period": s.period,
            "outcome_id": x["oid"],
            "price_decimal": s.price,
            "quote_observed_at_utc": s.quoted_at,
            "quote_status": (
                "unverified" if not price_ok else "stale" if age > STALE_AFTER_S else "fresh"
            ),
            "suspended": susp,
            "eligible_for_multis": None,
            "model_status": "model-experimental" if s.modelled else "market-only",
            "market_prob": s.market_prob,
            "is_player_prop": x["player"],
            "mapped": x["mapped"],
            "market_group_raw": x["gn"],
            "market_class_raw": x["ec"],
            "outcome_name_raw": o.get("name"),
            "price_updated_utc": o.get("priceLastUpdated"),
            "competition": comp,
            "event_name": ename,
        }
        row["key"] = "|".join(
            (
                PROVIDER,
                s.event_id,
                x["mid"],
                x["oid"],
                s.period,
                "" if s.line is None else f"{s.line:g}",
            )
        )
        rows.append(row)
    stats = {"raw_outcomes": raw_outcomes, "groups": groups}
    return rows, stats


# ---- fetching -------------------------------------------------------------------------------


class Fetcher:
    """Polite urllib GET -> JSON: a shared small delay, retries with backoff on 429/5xx."""

    def __init__(self, delay: float = 0.05, retries: int = 3, timeout: float = 20.0):
        self.delay, self.retries, self.timeout = delay, retries, timeout
        self.calls = Counter()
        self._lock = threading.Lock()

    def __call__(self, url: str):
        kind = "event" if "/mes/v3/events/" in url else "list"
        with self._lock:
            self.calls[kind] += 1
        err: Exception | None = None
        for attempt in range(self.retries + 1):
            time.sleep(self.delay)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 asynymbet"})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                err = e
                if e.code not in (429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                err = e
            time.sleep(min(8.0, 0.5 * 2**attempt))
        raise err or RuntimeError("fetch failed")


def competitions_of(listing: dict) -> dict[str, dict]:
    """{competition key: {key,name,numberOfEvents}} deduplicated across locales."""
    out: dict[str, dict] = {}
    for loc in listing.get("locales") or []:
        for c in loc.get("competitions") or []:
            out.setdefault(str(c["key"]), {**c, "key": str(c["key"])})
    return out


def _listing(fetch, comp: dict, errors: list) -> list[dict]:
    evs, page = [], 1
    while page <= 6:
        try:
            d = fetch(
                f"{API}/competitions/{comp['key']}/events/featured?includeLive=false&page={page}"
            )
        except Exception as e:
            errors.append(f"competition {comp['key']} {comp.get('name')}: {e}")
            break
        for e in d.get("events") or []:
            evs.append({**e, "competitionKey": comp["key"], "competitionName": comp.get("name")})
        if not d.get("nextPage"):
            break
        page += 1
    return evs


# ---- build ----------------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _empty_cov(sport: str, built: str, feed: str) -> dict:
    return {
        "provider": PROVIDER, "sport": sport, "built": built, "events": 0,
        "raw_player_market_groups": 0, "mapped_groups": 0, "unmapped_groups": 0,
        "raw_outcomes": 0, "displayed_outcomes": 0, "suspended_outcomes": 0,
        "modelled_outcomes": 0, "stale_outcomes": 0, "adapter_errors": [], "feed": feed,
        "player_prop_outcomes": 0, "raw_game_market_groups": 0, "unmapped_game_groups": 0,
        "events_listed": 0, "events_not_fetched": 0, "not_fetched": [], "futures_competitions": 0,
        "futures_events_counted": 0, "exceptions": [], "reconciled": True,
    }  # fmt: skip


def build(
    sport_keys=None,
    fetch=None,
    now: datetime | None = None,
    *,
    hours: float = HOURS,
    max_event_calls: int = MAX_EVENT_CALLS,
    concurrency: int = CONCURRENCY,
    deadline: float | None = None,
    pb_sports: list[str] | None = None,
    clock=None,
) -> dict:
    """Build the catalogue for `sport_keys` (default: every sport). `fetch(url) -> dict`.
    `deadline` is a time.monotonic() value after which no new event call starts (the rest is
    recorded as not fetched). Returns {"docs": {sport: doc}, "coverage": [rows], "unmapped":
    {sport: [..]}, "raw": {sport: {...}}, "stats": {...}}."""
    fetch = fetch or Fetcher()
    now = now or datetime.now(UTC)
    built = _iso(now)
    wanted = list(sport_keys or SPORT_KEYS)
    sports = pb_sports or [s for s in PB_SPORTS if any(SPORT_KEYS.get(k) == s for k in wanted)]
    horizon = now + timedelta(hours=hours)
    docs: dict = {}
    cov: dict = {}
    unm: dict = {}
    raw: dict = {}
    ev_by: dict = {}
    t0 = time.monotonic()
    budget = {"calls": 0}
    lock = threading.Lock()

    def cov_of(k):
        return cov.setdefault(k, _empty_cov(k, built, "connected"))

    # 1. competitions -> events within the window
    candidates: list[tuple[str, dict, dict]] = []  # (sport key, competition, event)
    for ps in sports:
        try:
            comps = competitions_of(fetch(f"{API}/sports/{ps}/competitions"))
        except Exception as e:
            for k in {k for k, v in SPORT_KEYS.items() if v == ps and k in wanted}:
                cov_of(k)["adapter_errors"].append(f"sport {ps}: competitions: {e}")
                cov_of(k)["feed"] = "none"
            continue
        live = []
        for c in comps.values():
            k = sport_key(ps, c.get("name"))
            if k not in wanted:
                continue
            cv = cov_of(k)
            if is_futures(c.get("name")):
                cv["futures_competitions"] += 1
                cv["futures_events_counted"] += int(c.get("numberOfEvents") or 0)
            elif int(c.get("numberOfEvents") or 0) > 0:
                live.append((k, c))

        def listed(kc):
            errs: list = []
            return kc[0], _listing(fetch, kc[1], errs), errs

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            lists = list(pool.map(listed, live))
        for k, evs, errs in lists:
            cov_of(k)["adapter_errors"].extend(errs)
            for e in evs:
                candidates.append((k, {"key": e["competitionKey"]}, e))
    for k in wanted:
        cov_of(k)
    # dedupe (an event can sit in two competitions) and window-filter
    todo: list[tuple[str, dict]] = []
    seen_ev = set()
    for k, _c, e in candidates:
        if str(e["key"]) in seen_ev:
            continue
        seen_ev.add(str(e["key"]))
        cov_of(k)["events_listed"] += 1
        t = _parse(e.get("startsAt"))
        if e.get("isLive") or not t or t < now - timedelta(minutes=5) or t > horizon:
            continue
        todo.append((k, e))
    # player-prop sports first (CORE_KEYS order), the "-other" leagues last; nearest start first
    rank = {k: i for i, k in enumerate(CORE_KEYS)}
    todo.sort(key=lambda ke: (rank.get(ke[0], 99), ke[1].get("startsAt") or ""))

    # 2. event detail, capped and time-boxed; the rest is recorded, never dropped silently
    picked: list[tuple[str, dict]] = []
    skipped: list[tuple[str, dict, str]] = []
    for k, e in todo:
        if len(picked) >= max_event_calls:
            skipped.append((k, e, "not fetched this run: event-call cap"))
        else:
            picked.append((k, e))

    def one(ke):
        k, e = ke
        if deadline is not None and time.monotonic() > deadline:
            return k, e, None, None, "not fetched this run: time budget"
        try:
            with lock:
                budget["calls"] += 1
            return k, e, fetch(f"{PB}/events/{e['key']}"), (clock or _utcnow)(), None
        except Exception as ex:
            return k, e, None, None, f"error: {ex}"

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(one, picked))
    results += [(k, e, None, None, why) for k, e, why in skipped]

    # 3. selections
    rows_by: dict = {}
    raw_by: dict = {}
    umap: dict = {}
    for k, e, detail, fetched, why in results:
        cv = cov_of(k)
        info = {
            "event_id": str(e["key"]), "event_name": e.get("name"), "starts_at": e.get("startsAt"),
            "competition": e.get("competitionName"), "competition_id": str(e.get("competitionKey") or ""),
            "status": "pre" if e.get("isLive") is False else "live" if e.get("isLive") else "unknown",
        }  # fmt: skip
        ev_by.setdefault(k, []).append(info)
        if detail is None:
            cv["events_not_fetched"] += 1
            if len(cv["not_fetched"]) < 200:
                cv["not_fetched"].append(
                    {"event_id": info["event_id"], "event_name": info["event_name"], "reason": why}
                )
            if why and why.startswith("error"):
                cv["adapter_errors"].append(f"event {info['event_id']}: {why}")
            info["fetched"] = False
            continue
        info["fetched"] = True
        cv["events"] += 1
        try:
            rows, st = event_selections(e, detail, k, fetched, now)
        except Exception as ex:  # one malformed event must not drop the sport
            cv["adapter_errors"].append(f"event {info['event_id']}: parse: {ex!r}")
            cv["events_not_fetched"] += 1
            info["fetched"] = False
            continue
        rows_by.setdefault(k, []).extend(rows)
        raw_by.setdefault(k, []).append({"key": e["key"], "name": e.get("name"), "startsAt": e.get("startsAt"),
                                         "competition": e.get("competitionName"), "detail": detail})  # fmt: skip
        cv["raw_outcomes"] += st["raw_outcomes"]
        if st["raw_outcomes"] != len(rows):
            cv["reconciled"] = False
            cv["exceptions"].append(
                {"event_id": info["event_id"], "raw": st["raw_outcomes"], "displayed": len(rows)}
            )
        for g in st["groups"].values():
            if g["player"]:
                cv["raw_player_market_groups"] += 1
                cv["mapped_groups" if g["mapped"] else "unmapped_groups"] += 1
            else:
                cv["raw_game_market_groups"] += 1
                cv["unmapped_game_groups"] += 0 if g["mapped"] else 1
            if not g["mapped"]:
                u = umap.setdefault(k, {}).setdefault(
                    g["market_name_raw"], {"market_name_raw": g["market_name_raw"], "count": 0,
                                           "example_event": info["event_name"], "is_player_prop": g["player"]})  # fmt: skip
                u["count"] += 1
    for k, rows in rows_by.items():
        cv = cov_of(k)
        cv["displayed_outcomes"] = len(rows)
        cv["suspended_outcomes"] = sum(r["suspended"] for r in rows)
        cv["modelled_outcomes"] = sum(r["model_status"] == "model-experimental" for r in rows)
        cv["stale_outcomes"] = sum(r["quote_status"] == "stale" for r in rows)
        cv["player_prop_outcomes"] = sum(r["is_player_prop"] for r in rows)
        if cv["raw_outcomes"] != cv["displayed_outcomes"]:
            cv["reconciled"] = False
    for k in wanted:
        docs[k] = {"built": built, "provider": PROVIDER, "sport": k, "events": ev_by.get(k, []),
                   "selections": rows_by.get(k, [])}  # fmt: skip
        unm[k] = sorted(umap.get(k, {}).values(), key=lambda u: -u["count"])
        raw[k] = {"built": built, "provider": PROVIDER, "sport": k, "events": raw_by.get(k, [])}
    coverage = [cov[k] for k in sorted(cov, key=lambda x: (x not in CORE_KEYS, x))]
    return {
        "docs": docs, "coverage": coverage, "unmapped": unm, "raw": raw,
        "stats": {"event_calls": budget["calls"], "list_calls": (fetch.calls.get("list") if isinstance(getattr(fetch, "calls", None), Counter) else None),
                  "wall_s": round(time.monotonic() - t0, 1), "events_in_window": len(todo)},
    }  # fmt: skip


# ---- writers --------------------------------------------------------------------------------


def _gz(obj) -> bytes:
    return gzip.compress(json.dumps(obj, separators=(",", ":")).encode())


LATEST_MAX_ROWS = 20000


def shard_doc(doc: dict, cov: dict | None = None) -> tuple[dict, dict]:
    """(index, {competition_id: shard doc}) for one sport: the index is small (events, a row per
    competition with counts and facets, the coverage row); each shard holds one competition's rows."""
    by: dict[str, list] = {}
    for r in doc["selections"]:
        by.setdefault(str(r.get("league_id") or ""), []).append(r)
    comps: dict[str, dict] = {}
    for e in doc["events"]:
        cid = str(e.get("competition_id") or "")
        c = comps.setdefault(
            cid, {"competition_id": cid, "competition": e.get("competition"), "events": 0}
        )
        c["events"] += 1
        c["first_start"] = min(
            filter(None, [c.get("first_start"), e.get("starts_at")]), default=None
        )
    for cid in by:
        comps.setdefault(
            cid, {"competition_id": cid, "competition": by[cid][0].get("competition"), "events": 0}
        )
    shards = {}
    for cid, c in comps.items():
        rows = by.get(cid, [])
        c.update(
            outcomes=len(rows),
            player_outcomes=sum(1 for r in rows if r.get("is_player_prop")),
            families=sorted({r.get("market_family") or "other" for r in rows}),
            periods=sorted({r.get("period") or "" for r in rows} - {""}),
            shard=f"comp-{cid}.json.gz" if rows else None,
        )
        if rows:
            shards[cid] = {
                "built": doc["built"], "provider": doc["provider"], "sport": doc["sport"],
                "competition_id": cid, "competition": c["competition"],
                "events": [e for e in doc["events"] if str(e.get("competition_id") or "") == cid],
                "selections": rows,
            }  # fmt: skip
    index = {
        "built": doc["built"], "provider": doc["provider"], "sport": doc["sport"],
        "rows": len(doc["selections"]),
        "player_rows": sum(c["player_outcomes"] for c in comps.values()),
        "events": doc["events"],
        "competitions": sorted(comps.values(), key=lambda c: (c.get("first_start") or "~", c["competition_id"])),
        "coverage": cov,
    }  # fmt: skip
    return index, shards


def _carry_over(k: str, index: dict, shards: dict, doc: dict, read) -> None:
    """Keep the previous build's rows for games this run did not reach (a run stops at its time
    limit: basketball and soccer need more than one run), so a partial run never empties a sport.
    One competition's old shard is read at a time, so memory stays bounded. Carried games keep
    their old quote times (honest staleness) and are marked "carried"."""
    if read is None:
        return
    missing: dict[str, set] = {}
    for e in doc["events"]:
        if not e.get("fetched"):
            missing.setdefault(str(e.get("competition_id") or ""), set()).add(str(e["event_id"]))
    if not missing:
        return
    try:
        old = json.loads(read(f"catalogue/{k}/index.json") or b"null") or {}
    except (ValueError, OSError):
        return
    old_shard = {str(c.get("competition_id")): c.get("shard") for c in old.get("competitions", [])}
    carried_events: set = set()
    by_cid = {c["competition_id"]: c for c in index["competitions"]}
    # the old shards are fetched in parallel (owner, 2026-11-08: 81 reads one at a time took 27 s and
    # soccer ran past the Function's 55 s limit); only the gzip bytes are held, parsed one at a time
    want = {cid: old_shard[cid] for cid in missing if old_shard.get(cid)}

    def _get(name):
        try:
            return read(f"catalogue/{k}/{name}")
        except OSError:
            return None

    with ThreadPoolExecutor(max_workers=12) as pool:
        got = dict(zip(want, pool.map(_get, want.values())))
    for cid, evs in missing.items():
        if cid not in want:
            continue
        try:
            raw = got.pop(cid, None)
            rows = [
                r
                for r in (json.loads(gzip.decompress(raw)).get("selections", []) if raw else [])
                if str(r.get("event_id")) in evs
            ]
        except (ValueError, OSError):
            continue
        if not rows:
            continue
        c = by_cid.get(cid)
        if c is None:
            continue
        shard = shards.get(cid) or {
            "built": doc["built"], "provider": doc["provider"], "sport": doc["sport"],
            "competition_id": cid, "competition": c.get("competition"),
            "events": [e for e in doc["events"] if str(e.get("competition_id") or "") == cid],
            "selections": [],
        }  # fmt: skip
        shard["selections"] = shard["selections"] + rows
        shards[cid] = shard
        n_props = sum(1 for r in rows if r.get("is_player_prop"))
        c.update(
            outcomes=c.get("outcomes", 0) + len(rows),
            player_outcomes=c.get("player_outcomes", 0) + n_props,
            families=sorted(
                set(c.get("families") or []) | {r.get("market_family") or "other" for r in rows}
            ),
            periods=sorted(
                (set(c.get("periods") or []) | {r.get("period") or "" for r in rows}) - {""}
            ),
            shard=f"comp-{cid}.json.gz",
        )
        index["rows"] = index.get("rows", 0) + len(rows)
        index["player_rows"] = index.get("player_rows", 0) + n_props
        carried_events |= {str(r.get("event_id")) for r in rows}
    for e in index["events"]:
        if str(e.get("event_id")) in carried_events:
            e["carried"] = True


def write_build(result: dict, write, read=None, include_raw: bool = True) -> list[str]:
    """Write a build through `write(name, bytes)`. `read(name) -> bytes | None` lets coverage.json
    keep the rows of sports this run did not build (rotation). Returns the names written."""
    names, pending = [], []

    def put(name, data):  # queued; uploaded in parallel below (the order of `names` is kept)
        pending.append((name, data))
        names.append(name)

    built = next(iter(result["docs"].values()), {}).get("built") or _iso(datetime.now(UTC))
    stamp = _parse(built) or datetime.now(UTC)
    cov_by = {r["sport"]: r for r in result["coverage"]}
    for k, doc in result["docs"].items():
        index, shards = shard_doc(doc, cov_by.get(k))
        _carry_over(k, index, shards, doc, read)
        for cid, shard in shards.items():
            put(f"catalogue/{k}/comp-{cid}.json.gz", _gz(shard))
        put(f"catalogue/{k}/index.json", json.dumps(index, separators=(",", ":")).encode())
        small = len(doc["selections"]) <= LATEST_MAX_ROWS
        # a big sport keeps only a stub here: the rows live in the per-competition shards
        put(
            f"catalogue/{k}/latest.json.gz",
            _gz(doc if small else {**doc, "selections": [], "sharded": True}),
        )
        put(
            f"catalogue/unmapped/{k}.json",
            json.dumps(result["unmapped"].get(k, []), indent=1).encode(),
        )
        if include_raw and doc["events"]:
            put(f"catalogue/raw/{k}/{stamp:%Y%m%d}/{stamp:%H%M}.json.gz", _gz(result["raw"][k]))
    rows = {r["sport"]: r for r in result["coverage"]}
    if read:
        try:
            old = json.loads(read("catalogue/coverage.json") or b"[]")
        except (ValueError, OSError):
            old = []
        rows = {**{r["sport"]: r for r in old if isinstance(r, dict) and "sport" in r}, **rows}
    ordered = sorted(rows.values(), key=lambda r: (r["sport"] not in CORE_KEYS, r["sport"]))
    put("catalogue/coverage.json", json.dumps(ordered, indent=1).encode())
    # shards first in parallel; the index, latest and coverage files after, so a reader never sees
    # an index that points at shards not yet written
    later = [p for p in pending if not p[0].rsplit("/", 1)[-1].startswith("comp-")]
    first = [p for p in pending if p not in later]
    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(lambda p: write(*p), first))
    for p in later:
        write(*p)
    return names


def dir_writer(root: str | Path):
    root = Path(root)

    def write(name: str, data: bytes) -> None:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    return write


def dir_reader(root: str | Path):
    root = Path(root)

    def read(name: str):
        p = root / name
        return p.read_bytes() if p.exists() else None

    return read


def expired_raw(names, now: datetime, days: int = RAW_KEEP_DAYS) -> list[str]:
    """Raw snapshot names (catalogue/raw/<sport>/<YYYYMMDD>/<HHMM>.json.gz) older than `days`."""
    cut = (now - timedelta(days=days)).strftime("%Y%m%d")
    out = []
    for n in names:
        m = re.match(r"^catalogue/raw/[^/]+/(\d{8})/", n)
        if m and m[1] < cut:
            out.append(n)
    return out


def run_rotation(
    cursor, deadline, now, write, read=None, list_names=None, fetch=None, save_cursor=None, **kw
) -> dict:
    """One scheduled run: build PointsBet sports one at a time, in rotation from `cursor`, until the
    monotonic `deadline` (at least one sport per run). Each sport is written as soon as it is built,
    coverage.json keeps the other sports' rows, and raw snapshots older than 3 days are listed for
    deletion. Returns {"built": [pb sports], "cursor": next, "stats": [...], "expired": [names]}."""
    fetch = fetch or Fetcher()
    order = list(PB_SPORTS)
    built, stats, i = [], [], int(cursor or 0) % len(order)
    for _ in range(len(order)):
        ps = order[i]
        keys = [k for k, v in SPORT_KEYS.items() if v == ps]
        if save_cursor:  # saved first: a run killed mid-sport starts on the next sport, never sticks
            save_cursor((i + 1) % len(order))
        res = build(keys, fetch, now, deadline=deadline, pb_sports=[ps], **kw)
        write_build(res, write, read)
        built.append(ps)
        stats.append({ps: res["stats"]})
        i = (i + 1) % len(order)
        if time.monotonic() > deadline - 3:
            break
    expired = expired_raw(list_names(), now) if list_names else []
    return {"built": built, "cursor": i, "stats": stats, "expired": expired}
