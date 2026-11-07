"""Canonical market/selection layer for NBA: every market PointsBet and Sportsbet return, as
`Selection`s. Probabilities are never invented: `market_prob` is a proportional no-vig of a
complete complementary set, `model_prob` is None here, and only the four player stats the model
covers are `modelled`. Field names map to the proposed selection.schema.json via `to_schema()`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime

MODELLED = frozenset({"player_points", "player_rebounds", "player_assists", "player_threes"})
STALE_AFTER_S = 900  # a quote older than this is "unverified"
_SIDES_PAIR = {
    frozenset({"over", "under"}),
    frozenset({"home", "away"}),
    frozenset({"odd", "even"}),
}


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", ts.replace("Z", "+00:00")))
    except (AttributeError, ValueError):
        return None


@dataclass(frozen=True)
class Selection:
    sport: str
    provider: str  # "pb", "sb", "us:<book>"
    event_id: str  # the provider's
    event_name: str  # "Away @ Home"
    starts_at: str  # UTC ISO
    market_type: str
    market_name: str  # the provider's raw name
    participant: str
    participant_id: str | None
    line: float | None
    side: str
    price: float | None  # decimal; None when the provider gave none
    quoted_at: str  # UTC ISO when read
    group: str = ""  # the complementary set this belongs to (provider's market + line)
    market_prob: float | None = None
    model_prob: float | None = None  # never set here: no model outside the four stats
    modelled: bool = False
    status: str = "verified"  # or "unverified"
    status_reason: str | None = None
    canonical_event_id: str | None = None
    market_status: str = "open"
    period: str = "full_game"
    stat: str | None = None
    provider_market_id: str | None = None
    provider_selection_id: str | None = None
    league: str = "NBA"

    def key(self) -> str:
        """Stable id: no price, no time."""
        pid = self.participant_id or ""
        ln = "" if self.line is None else f"{self.line:g}"
        return "|".join(
            (
                self.sport,
                self.provider,
                self.event_id,
                self.market_type,
                self.market_name,
                self.participant,
                pid,
                ln,
                self.side,
                self.period,
            )
        )

    def to_schema(self) -> dict:
        """The proposed canonical selection contract (selection.schema.json). The schema has no
        "unverified" status, so it shows as market_status "unknown" with a null price."""
        ok = self.status == "verified"
        mp = self.market_prob
        return {
            "selection_id": self.key(),
            "sport": self.sport,
            "league": self.league,
            "canonical_event_id": self.canonical_event_id or f"unresolved:{self.event_id or '?'}",
            "provider": self.provider,
            "provider_event_id": self.event_id or "?",
            "provider_market_id": self.provider_market_id,
            "provider_selection_id": self.provider_selection_id,
            "participant_id": self.participant_id,
            "market_type": self.market_type,
            "stat": self.stat,
            "threshold": self.line,
            "direction": self.side,
            "period": self.period,
            "quoted_decimal_odds": self.price if ok else None,
            "observed_at_utc": self.quoted_at,
            "market_status": self.market_status if ok else "unknown",
            "model_status": "experimental"
            if self.modelled
            else ("market_only" if mp is not None else "unavailable"),
            "market_probability_novig": mp,
            "independent_model_probability": self.model_prob,
            "probability_used": mp,
            "probability_version": "market-v1" if mp is not None else None,
        }


# ---- classification -------------------------------------------------------------------------


def stat_type(text: str) -> str:
    """Canonical market type of a player-stat description ("Points + Rebounds", "3-Pointers")."""
    t = text.lower()
    has = (
        bool(re.search(r"\b(pts|points?)\b", t)),
        bool(re.search(r"\b(rebs?|rebounds?)\b", t)),
        bool(re.search(r"\b(asts?|assists?)\b", t)),
    )
    if "+" in t or " and " in t:
        return "player_pra" if all(has) else "player_other"
    if has[0]:
        return "player_points"
    if has[1]:
        return "player_rebounds"
    if has[2]:
        return "player_assists"
    if re.search(r"three|3-?pt|3-pointer", t):
        return "player_threes"
    return "player_other"


def _period(text: str) -> str:
    t = text.lower()
    for pat, tag in (
        (r"1st half|first half|halftime", "1h"),
        (r"2nd half|second half", "2h"),
        (r"1st quarter|first quarter|quarter|\bq[1-4]\b", "quarter"),
    ):
        if re.search(pat, t):
            return tag
    return "full_game"


def _split_event(name: str) -> tuple[str, str]:
    m = re.match(r"^(.+?) (?:@|At|at|v|vs) (.+)$", name or "")
    return (m[1].strip(), m[2].strip()) if m else ("", "")


def _event_id(starts_at: str, away: str, home: str) -> str | None:
    t = _parse(starts_at)
    if not (t and away and home):
        return None
    slug = lambda s: re.sub(r"[^a-z0-9]+", "", s.lower())  # noqa: E731
    return f"nba:{t:%Y-%m-%d}:{slug(away)}@{slug(home)}"


def _num(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ---- builder --------------------------------------------------------------------------------


class _Ctx:
    def __init__(
        self, provider, event_id, name, starts_at, now, fetched_at=None, max_age=STALE_AFTER_S
    ):
        away, home = _split_event(name)
        self.provider, self.event_id, self.name = provider, str(event_id or ""), name or ""
        self.starts_at, self.away, self.home = starts_at or "", away, home
        self.canon = _event_id(self.starts_at, away, home)
        self.quoted_at = _iso(now)
        self.now, self.max_age = now, max_age
        self.fetched = fetched_at or now  # when the raw payload was read (snapshot age)

    def make(
        self,
        market_type,
        market_name,
        participant,
        side,
        price,
        line=None,
        *,
        group,
        participant_id=None,
        open_=True,
        mid=None,
        sid=None,
        stat=None,
        period=None,
    ):
        price = _num(price)
        reason = None
        if price is None or price <= 1:
            reason, price = "no valid price", (price if price and price > 1 else None)
        elif not self.canon or not self.event_id:
            reason = "invalid event identity"
        else:
            if (self.now - self.fetched).total_seconds() > self.max_age:
                reason = "stale snapshot"
        if reason is None and not open_:
            reason = "suspended"
        period = period or _period(market_name)
        if period != "full_game" and market_type in MODELLED:
            market_type = "player_other"  # the model covers full-game stats only
        return Selection(
            sport="basketball",
            provider=self.provider,
            event_id=self.event_id,
            event_name=self.name,
            starts_at=self.starts_at,
            market_type=market_type,
            market_name=market_name,
            participant=participant,
            participant_id=participant_id,
            line=line,
            side=side,
            price=price,
            quoted_at=self.quoted_at,
            group=f"{self.event_id}|{group}",
            modelled=market_type in MODELLED,
            status="unverified" if reason else "verified",
            status_reason=reason,
            canonical_event_id=self.canon,
            market_status="open" if open_ else "suspended",
            period=period,
            stat=stat,
            provider_market_id=mid,
            provider_selection_id=sid,
        )


def apply_no_vig(sels: list[Selection]) -> list[Selection]:
    """Set market_prob = (1/price) / sum(1/price) where a group is a complete complementary
    pair (over+under, home+away, odd+even) of verified prices; otherwise leave None."""
    groups: dict[str, list[int]] = {}
    for i, s in enumerate(sels):
        groups.setdefault(s.group, []).append(i)
    out = list(sels)
    for idx in groups.values():
        grp = [sels[i] for i in idx]
        sides = [s.side for s in grp]
        if (
            len(grp) == 2
            and frozenset(sides) in _SIDES_PAIR
            and all(s.status == "verified" for s in grp)
        ):
            tot = sum(1 / s.price for s in grp)
            for i in idx:
                out[i] = replace(sels[i], market_prob=round((1 / sels[i].price) / tot, 6))
    return out


# ---- PointsBet ------------------------------------------------------------------------------

_PB_OU = re.compile(r"^(?P<who>.+) (?P<side>Over|Under) (?P<line>\d+(?:\.\d+)?)$")
_PB_ALT = re.compile(r"^(?P<who>.+?) To (?:Score|Get|Record|Have|Make|Hit) (?P<k>\d+)\+")


def pointsbet_selections(
    events: list[dict], now: datetime | None = None, fetched_at: datetime | None = None
) -> list[Selection]:
    """`events`: [{"key","name","startsAt","detail": <GET /events/{key} payload>}] as saved by
    `fetch_pointsbet_raw`. Every market in fixedOddsMarkets + specialFixedOddsMarkets."""
    now = now or datetime.now(UTC)
    out: list[Selection] = []
    for ev in events:
        d = ev.get("detail") or {}
        c = _Ctx("pb", ev.get("key"), ev.get("name"), ev.get("startsAt"), now, fetched_at)
        for m in (d.get("fixedOddsMarkets") or []) + (d.get("specialFixedOddsMarkets") or []):
            cls = m.get("eventClass") or m.get("eventName") or ""
            mid = str(m.get("key") or "")
            for o in m.get("outcomes") or []:
                out.append(_pb_outcome(c, cls, mid, o))
    return apply_no_vig(out)


def _pb_outcome(c: _Ctx, cls: str, mid: str, o: dict) -> Selection:
    name, pts = o.get("name") or "", _num(o.get("points"))
    side = (o.get("side") or "").lower()
    kw = dict(
        open_=o.get("isOpenForBetting", True) is not False, mid=mid, sid=str(o.get("key") or "")
    )
    price = o.get("price")
    pid = str(o["playerId"]) if o.get("playerId") else None
    gname = f"{cls}"
    if pid:  # player markets
        ou, alt = _PB_OU.match(name), _PB_ALT.match(name)
        mt = stat_type(cls)
        if ou:
            line = float(ou["line"])
            return c.make(
                mt,
                cls,
                ou["who"],
                ou["side"].lower(),
                price,
                line,
                group=f"{mid}|{ou['who']}|{line:g}",
                participant_id=pid,
                stat=cls,
                **kw,
            )
        if alt:
            line = pts if pts is not None else int(alt["k"]) - 0.5
            return c.make(
                mt,
                cls,
                alt["who"],
                "over",
                price,
                line,
                group=f"{mid}|{alt['who']}|{line:g}",
                participant_id=pid,
                stat=cls,
                **kw,
            )
        who = name.split(" & ")[0]
        return c.make(
            "player_other",
            cls,
            who,
            "yes",
            price,
            None,
            group=f"{mid}|{name}",
            participant_id=pid,
            stat=cls,
            **kw,
        )
    if cls == "Moneyline":
        return c.make("h2h", cls, name, side or "other", price, None, group=mid, **kw)
    if cls in ("Point Spread", "Pick Your Own Line"):
        team = re.sub(r"\s*[+-]\d+(\.\d+)?$", "", name)
        home_line = None if pts is None else (pts if side == "home" else -pts)
        return c.make(
            "line",
            cls,
            team,
            side or "other",
            price,
            pts,
            group=f"{mid}|{home_line:g}" if home_line is not None else f"{mid}|{name}",
            **kw,
        )
    if cls in ("Total", "Alternate Totals", "Home Total", "Away Total"):
        m = re.match(r"^(Over|Under) ", name)
        team = {"Home Total": c.home, "Away Total": c.away}.get(cls, "")
        if m and pts is not None:
            return c.make(
                "total", cls, team, m[1].lower(), price, pts, group=f"{mid}|{pts:g}", **kw
            )
    return c.make(
        "other", cls, name, name.lower(), price, pts or None, group=f"{mid}|{gname}|{name}", **kw
    )


def fetch_pointsbet_raw() -> list[dict]:
    """Raw PointsBet NBA payloads (pre-game), reusing nba_legs' fetch and constants."""
    from concurrent.futures import ThreadPoolExecutor

    from . import nba_legs as N

    listing = [
        e
        for e in N.get(f"{N.PB}/events/featured/competition/7176?page=1").get("events", [])
        if not e.get("isLive")
    ][:20]

    def one(e):
        return {
            "key": str(e["key"]),
            "name": e.get("name"),
            "startsAt": e.get("startsAt"),
            "detail": N.get(f"{N.PB}/events/{e['key']}"),
        }

    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(one, listing))


# ---- Sportsbet ------------------------------------------------------------------------------

_SB_OU = re.compile(r"^(?P<who>.+?) - (?P<what>.+)$")
_SB_ALT = re.compile(r"^(?:To (?:Score|Record|Get|Have|Make) )?(?P<k>\d+)\+ (?P<what>.+)$")
_SB_H2H = {"head to head", "money line", "moneyline", "match result", "to win"}
_SB_LINE = {"line", "handicap", "match handicap", "point spread", "spread", "line betting"}
_SB_TOTAL = {"total points", "match total", "total", "over/under", "total points over/under"}


def sportsbet_selections(
    competition: dict,
    markets_by_event: dict,
    now: datetime | None = None,
    fetched_at: datetime | None = None,
) -> list[Selection]:
    """`competition`: Competitions/{id} payload; `markets_by_event`: {event id: Events/{id}/Markets}
    (what `nba_legs.live_sportsbet` fetches, kept raw by `fetch_sportsbet_raw`)."""
    now = now or datetime.now(UTC)
    out: list[Selection] = []
    for e in competition.get("events") or []:
        eid = str(e.get("id"))
        if eid not in markets_by_event:
            continue
        st = e.get("startTime")
        when = _iso(datetime.fromtimestamp(st, UTC)) if isinstance(st, (int, float)) else st
        name = re.sub(r" At ", " @ ", e.get("name") or "")
        c = _Ctx("sb", eid, name, when, now, fetched_at)
        for m in markets_by_event[eid]:
            out.extend(_sb_market(c, m))
    return apply_no_vig(out)


def _sb_market(c: _Ctx, m: dict) -> list[Selection]:
    mname, mid = m.get("name") or "", str(m.get("id") or "")
    low = mname.lower().strip()
    mopen = m.get("statusCode", "A") == "A"
    out = []
    ou, alt = _SB_OU.match(mname), _SB_ALT.match(mname)
    for s in m.get("selections") or []:
        sname = (s.get("name") or "").strip()
        price = (s.get("price") or {}).get("winPrice")
        hc = _num(s.get("unformattedHandicap"))
        kw = dict(
            open_=mopen and s.get("statusCode", "A") == "A", mid=mid, sid=str(s.get("id") or "")
        )
        if alt and not low.startswith(("head", "line")):
            line = int(alt["k"]) - 0.5
            out.append(
                c.make(
                    stat_type(alt["what"]),
                    mname,
                    sname,
                    "over",
                    price,
                    line,
                    group=f"{mid}|{sname}|{line:g}",
                    stat=alt["what"],
                    **kw,
                )
            )
        elif ou and hc is not None and sname.endswith(("Over", "Under")):
            side = sname.split()[-1].lower()
            who = ou["who"]
            out.append(
                c.make(
                    stat_type(ou["what"]),
                    mname,
                    who,
                    side,
                    price,
                    hc,
                    group=f"{mid}|{who}|{hc:g}",
                    stat=ou["what"],
                    **kw,
                )
            )
        elif low in _SB_H2H:
            out.append(
                c.make("h2h", mname, sname, _team_side(c, sname), price, None, group=mid, **kw)
            )
        elif low in _SB_LINE and hc is not None:
            side = _team_side(c, sname)
            hl = hc if side == "home" else -hc
            out.append(c.make("line", mname, sname, side, price, hc, group=f"{mid}|{hl:g}", **kw))
        elif low in _SB_TOTAL and hc is not None and sname.endswith(("Over", "Under")):
            out.append(
                c.make(
                    "total",
                    mname,
                    "",
                    sname.split()[-1].lower(),
                    price,
                    hc,
                    group=f"{mid}|{hc:g}",
                    **kw,
                )
            )
        else:
            out.append(
                c.make(
                    "other", mname, sname, sname.lower(), price, hc, group=f"{mid}|{sname}", **kw
                )
            )
    return out


def _team_side(c: _Ctx, name: str) -> str:
    if name and name == c.home:
        return "home"
    if name and name == c.away:
        return "away"
    return "other"


def fetch_sportsbet_raw() -> tuple[dict, dict]:
    """Raw Sportsbet (competition, markets_by_event), same calls as nba_legs.live_sportsbet.
    Australian addresses only."""
    from concurrent.futures import ThreadPoolExecutor

    from . import nba_legs as N

    comp = N.get(f"{N.SB}/Competitions/{N.SB_NBA}?displayType=default&includeTopMarkets=false")
    ids = [
        str(e["id"]) for e in comp.get("events") or [] if e.get("bettingStatus") in (None, "PRICED")
    ][:20]
    with ThreadPoolExecutor(max_workers=8) as pool:
        mk = dict(
            zip(ids, pool.map(lambda i: N.get(f"{N.SB}/Events/{i}/Markets"), ids), strict=True)
        )
    return comp, mk


# ---- coverage -------------------------------------------------------------------------------


def coverage(selections: list[Selection]) -> list[dict]:
    """Per market_type: count, providers, how many carry a no-vig market_prob, modelled yes/no."""
    rows: dict[str, dict] = {}
    for s in selections:
        r = rows.setdefault(
            s.market_type,
            {
                "market_type": s.market_type,
                "count": 0,
                "providers": set(),
                "with_market_prob": 0,
                "unverified": 0,
                "modelled": s.market_type in MODELLED,
            },
        )
        r["count"] += 1
        r["providers"].add(s.provider)
        r["with_market_prob"] += s.market_prob is not None
        r["unverified"] += s.status != "verified"
    return [{**r, "providers": sorted(r["providers"])} for _, r in sorted(rows.items())]
