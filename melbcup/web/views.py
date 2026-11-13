"""Pages and actions, independent of any web framework.

The FastAPI server (app.py) and the browser build (melbcup/browser.py, GitHub Pages) both route
requests here: ``page()`` renders a path to HTML, ``action()`` does what a button asks and says
where to go next.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from melbcup import catalogue_view, history
from melbcup.bets import LABELS, PRICE_VERDICTS, VALUE_KINDS, confidence, price_verdict
from melbcup.bets.grade import grade_day
from melbcup.bets.promos import PROMOS
from melbcup.bets.settle import DayResult, settle_all, settle_bet, settle_extra, signed
from melbcup.config import MELBOURNE, Settings
from melbcup.live import LiveBoard
from melbcup.web import asynym, racecard
from melbcup.web.racecard import (
    EXTRA_COOKIE,
    KIDS_COOKIE,
    PICKS_COOKIE,
    PLACED_COOKIE,
    build_day,
    cup_note,
    final_picks,
    open_picks,
    parse_extras,
    parse_kids,
    parse_placed,
    pick_amounts,
    pick_pointsbet,
    wallet,
)

HERE = Path(__file__).parent
BOOKMAKERS = {
    "sportsbet": "Sportsbet",
    "betfair": "Betfair",
    "tab": "TAB",
    "ladbrokes_au": "Ladbrokes",
    "neds": "Neds",
    "pointsbetau": "PointsBet",
    "betright": "BetRight",
    "playup": "PlayUp",
    "betr_au": "Betr",
    "unibet_au": "Unibet",
    "bet365_au": "bet365",
    "betdeluxe": "BetDeluxe",
    "betgold": "BetGold",
    "palmerbet": "Palmerbet",
    "picklebet": "Picklebet",
    "boombet": "BoomBet",
    "SP": "SP",
}
MAX_BUDGET = 100_000
DEFAULT_BUDGET = 200.0  # used when neither ?budget= nor the budget cookie says otherwise
BUDGET_COOKIE = "budget"
CARNIVAL = (  # Flemington, Melbourne Cup Carnival 2026: one tap, no lookup
    ("Derby Day", date(2026, 10, 31)),
    ("Cup Day", date(2026, 11, 3)),
    ("Oaks Day", date(2026, 11, 5)),
    ("Stakes Day", date(2026, 11, 7)),
)


def melbourne_today() -> date:
    return datetime.now(MELBOURNE).date()


def _date(text: str | None) -> date | None:
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def pct(p: float | None, digits: int = 0) -> str:
    return "–" if p is None else f"{100 * p:.{digits}f}%"


def money(x: float | None) -> str:
    if x is None:
        return "–"
    return f"${x:,.2f}" if x < 100 else f"${x:,.0f}"


def edge(ev: float | None) -> str:
    return "–" if ev is None else f"{100 * ev:+.0f}%"


def local_time(dt: datetime | None) -> str:
    if dt is None:
        return "–"
    t = dt.astimezone(MELBOURNE)
    return f"{t.hour % 12 or 12}:{t.minute:02d}{'am' if t.hour < 12 else 'pm'}"


AGENCY_NAMES = {"sportsbet": "Sportsbet", "pointsbet": "PointsBet", "betfair": "Betfair"}


def likely_view(board, day, race_n=None) -> dict:
    """The Likely and Multis tabs' data: LiveBoard.likely() with Melbourne jump times added.
    Multis keep this race's runners when any multi has one (``mine``), else the meeting's."""
    try:
        raw = board.likely() or {}
    except Exception:  # noqa: BLE001 - a bad board never breaks the page
        raw = {}
    starts = {rc.race.number: local_time(rc.race.start_time) for rc in (day.races if day else [])}

    def row(b):
        return {
            **b,
            "jump": starts.get(b["race"], "–"),
            "agency_name": AGENCY_NAMES.get(b["agency"], b["agency"]),
        }

    singles = {n: [row(b) for b in v] for n, v in (raw.get("singles") or {}).items()}
    groups = []
    for ag, bands in (raw.get("multis") or {}).items():
        rows = []
        for band in bands or []:
            pick = band.get("pick")
            legs = []
            for g in (pick or {}).get("legs", []):
                n = int(str(g.get("event", "R0")).lstrip("R") or 0)
                legs.append({**g, "race": n, "jump": starts.get(n, "–")})
            has = race_n is not None and any(g["race"] == race_n for g in legs)
            rows.append(
                {
                    "band": band,
                    "pick": pick,
                    "legs": legs,
                    "has_race": has,
                    "reason": band.get("reason"),
                }
            )
        groups.append({"agency": ag, "name": AGENCY_NAMES.get(ag, ag), "rows": rows})
    mine = race_n is not None and any(r["has_race"] for g in groups for r in g["rows"])
    if mine:
        for g in groups:
            g["rows"] = [r for r in g["rows"] if r["has_race"] or not r["pick"]]
    return {
        "singles": singles.get(race_n, []) if race_n is not None else [],
        "top": [row(b) for b in raw.get("meeting_top") or []],
        "multi_groups": groups,
        "multi_mine": mine,
        "loading": not raw or (not raw.get("meeting_top") and not any(singles.values())),
    }


def when(value) -> str:
    """A Melbourne day and time: "Today 11:00am", "Tomorrow 11:00am" or "Thu 6 Nov 11:00am".
    Takes a datetime or an ISO string (as PointsBet and ESPN send them)."""
    if not value:
        return "–"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    t = value.astimezone(MELBOURNE)
    days = (t.date() - melbourne_today()).days
    lead = {0: "Today", 1: "Tomorrow", -1: "Yesterday"}.get(days)
    if lead is None:
        lead = f"{t.strftime('%a')} {t.day} {t.strftime('%b')}"
    return f"{lead} {local_time(t)}"


# Dates without strftime's "%-d", which the browser build's C library does not support.
def day(d: date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def shortdate(d: date) -> str:
    return f"{d.day} {d:%b}"


def isoday(text: str) -> str:
    return day(date.fromisoformat(text))


def racename(name: str | None) -> str:
    """Racing Australia sends some names in capitals; show them in normal case."""
    if not name or not name.isupper():
        return name or ""
    small = {"And", "Of", "The", "At", "For", "On", "By"}
    words = [w.lower() if w[:1].isdigit() else w.capitalize() for w in name.split()]
    return " ".join(w.lower() if i and w in small else w for i, w in enumerate(words))


def longdate(d: date) -> str:
    return f"{day(d)} {d.year}"


def until(dt: datetime | None) -> str:
    if dt is None:
        return ""
    mins = int((dt - datetime.now(UTC)).total_seconds() // 60)
    if mins < -5:
        return "run"
    if mins <= 0:
        return "jumping"
    if mins < 60:
        return f"in {mins} min"
    return f"in {mins // 60} h {mins % 60:02d} min"


def book(key: str | None) -> str:
    return "–" if not key else BOOKMAKERS.get(key, key.replace("_au", "").title())


def statline(s) -> str:
    return "–" if s is None else f"{s.starts}: {s.wins}-{s.top3 - s.wins}"


@dataclass(frozen=True)
class Call:
    """One verdict for the page: bet (with its stake), hold, or skip.

    A bet is never shown without a dollar amount: a bet Call with no stake, or a stake of zero,
    becomes a hold. Build bets with ``Call.bet(stake)``.
    """

    kind: str  # "bet" | "hold" | "skip"
    stake: int | None = None

    def __post_init__(self) -> None:
        if self.kind == "bet" and not (self.stake and self.stake > 0):
            object.__setattr__(self, "kind", "hold")
        if self.kind != "bet":
            object.__setattr__(self, "stake", None)

    @classmethod
    def bet(cls, stake: int | None) -> Call:
        return cls("bet", stake)


def call(value: bool, stake: int | None, price: float | None, chance: float | None) -> Call:
    """The existing value rule says bet, and the stake makes it a bet; otherwise a price the
    verdict calls "Short: skip" is a skip and anything else is a hold. No new thresholds."""
    if value:
        return Call.bet(stake)
    verdict = price_verdict(price, chance)
    return Call("skip" if verdict and verdict.startswith(PRICE_VERDICTS[-1][1]) else "hold")


def single_call(s) -> Call:
    """Verdict for one Single (a win, place or each-way line)."""
    return call(s.value, s.stake, s.sportsbet or s.price, s.prob)


def runner_call(rp, number: int) -> Call:
    """One verdict for a runner: bet when any of its singles is value (with the stake the day's
    picks put on it), otherwise hold or skip on its win price."""
    mine = [s for s in rp.singles if s.number == number]
    value = [s for s in mine if s.value]
    if value:
        stake = next(
            (rp.best[s.kind].stake for s in value if rp.best.get(s.kind) is s and s.stake), None
        )
        return Call.bet(stake)
    a = next((a for a in rp.model.ranked() if a.number == number), None)
    prices = rp.model.race.prices.get(number)
    price = prices and (
        prices.sportsbet_win or (prices.best_win.price if prices.best_win else None)
    )
    return call(False, None, price, a.win if a else None)


def race_call(rp) -> Call:
    """One verdict for a race: bet when a win, place or each-way line is a value bet, carrying
    the dollars of those lines together; otherwise the verdict on its most likely winner.
    Exotics carry their own verdicts on their own lines."""
    lines = {id(s): s for k in VALUE_KINDS if (s := rp.best.get(k)) is not None}
    if lines:  # one runner can be the best win and the best each way: count each line once
        return Call.bet(sum(s.stake or 0 for s in lines.values()))
    top = rp.best.get("top_win")
    return runner_call(rp, top.number) if top else Call("hold")


def multis_call(picks) -> Call:
    """The summary verdict for quaddies and multis: the dollars on the recommended quaddies and
    the value multis that have stakes, or a hold when there are none."""
    total = sum(e.outlay or 0 for e in picks.quaddies if e.recommended)
    total += sum(m.stake or 0 for m in picks.multis if m.value)
    return Call.bet(total)


def open_races(picks) -> set[int]:
    """Numbers of the races still to run."""
    return {rp.model.race.number for rp in picks.races if betting_open(rp.model.race)}


def countdown(picks, now: datetime) -> list[dict]:
    """The open races that still have an advertised start ahead, soonest first: the data the
    "R2 jumps in 4:12" strip counts down to (number, start as ISO, seconds left at ``now``)."""
    if not picks:
        return []
    ahead = [
        rp.model.race
        for rp in picks.races
        if betting_open(rp.model.race)
        and rp.model.race.start_time is not None
        and rp.model.race.start_time > now
    ]
    ahead.sort(key=lambda r: r.start_time)
    return [
        {
            "n": r.number,
            "t": r.start_time.isoformat(),
            "left": int((r.start_time - now).total_seconds()),
        }
        for r in ahead
    ]


def betting_open(race) -> bool:
    """A race that has not run: no result yet and not started more than a few minutes ago."""
    return race.result is None and (race.start_time is None or until(race.start_time) != "run")


def asset_version(new_ui: bool = False) -> str:
    """Cache-buster for /static: the first 10 hex chars of the sha256 over the static assets, so a
    phone re-fetches app.css and app.js the moment either changes. Computed once per env. With
    the AsynymBet pages (ASYNYM=1) asynym.css and asynym.js count too."""
    digest = hashlib.sha256()
    names = sorted((HERE / "static").glob("app.*"))
    if new_ui:
        names += sorted((HERE / "static").glob("asynym.*"))
    for path in names:
        digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


def bet_tiles(tr, placed) -> tuple[list, dict]:
    """The live leg tiles of a placed bet (challenge stage or own bet): cls g hit / r failed / o in
    play / n not started, the count-up fill (unders fill toward the limit), and bet_live."""
    from melbcup import live_chance, nba_live

    live = live_chance.bet_live(tr, placed)
    legs = (tr or {}).get("legs")
    if not legs:
        parsed = nba_live.parse(placed.get("label", ""))[1]
        legs = [g | {"now": None, "ok": None} for g in parsed]
    state = (tr or {}).get("state", "pre")
    tiles = []
    for i, g in enumerate(legs):
        ok, now = g.get("ok"), g.get("now")
        cls = {True: "g", False: "r"}.get(ok, "o" if state == "in" else "n")
        lc = (live["legs"] + [None] * len(legs))[i]
        fill = min((now or 0) / g["k"], 1.0) * 100
        if cls == "g" and not g["under"]:
            fill = 100.0
        tiles.append(
            {
                "cls": cls,
                "name": g["player"],
                "line": g["label"].replace(g["player"], "", 1).strip(),
                "under": g["under"],
                "k": g["k"],
                "now": now or 0,
                "fill": round(fill),
                "chance": lc,
            }
        )
    return tiles, live


def bet_dead(tr) -> bool:
    return bool(
        tr
        and tr.get("failed")
        and (tr["state"] == "post" or any(g.get("ok") is False for g in tr["legs"]))
    )


def dead_tiles(tiles: list) -> list:
    """A failed bet: the failed leg first, the rest no longer count."""
    tiles = sorted(tiles, key=lambda t: t["cls"] != "r")
    for t in tiles:
        if t["cls"] != "r":
            t["cls"] = "x"
    return tiles


def own_cards(own, track) -> dict:
    """{own bet id: card data} for the My bets sheet: tiles, live %, clock, failed; never raises."""
    out: dict = {}
    for b in own or []:
        if b.get("state") != "placed":
            continue
        try:
            tr = (track or {}).get(b["id"])
            tiles, live = bet_tiles(tr, b)
            dead = bet_dead(tr)
            out[b["id"]] = {
                "tiles": dead_tiles(tiles) if dead else tiles,
                "p": live["p"],
                "live": bool(live["live"]),
                "approx": bool(live["approx"]),
                "clock": (tr or {}).get("clock", ""),
                "in_play": bool(tr and tr["state"] == "in"),
                "dead": dead,
                "verdict": (tr or {}).get("verdict"),
            }
        except Exception:  # noqa: BLE001 - a card without tiles still shows
            continue
    return out


def _iso(v) -> str:
    return v.isoformat() if hasattr(v, "isoformat") else str(v or "")


def slip_leg(d, sport: str = "") -> dict:
    """One leg in the slip's shape {id, sport, game, startsAt, label, price, chance, mk, side} from an
    NBA/NFL leg, a discover leg or a catalogue row (every card's legs share one slip)."""
    g = d.get if hasattr(d, "get") else (lambda k, default=None: getattr(d, k, default))
    if g("price_decimal") is not None:  # a catalogue row
        side = str(g("side") or "").lower()
        label = " ".join(
            str(x)
            for x in (g("participant_name"), side.title() if side else "", g("line_raw"), g("market_name_raw"))
            if x not in (None, "")
        )
        game = g("_ev") or g("event_name") or str(g("event_id") or "")
        p = g("market_prob")
        return {
            "id": f"{g('sport') or sport}|{g('selection_id') or g('key') or game + label}",
            "sport": g("sport") or sport,
            "game": game,
            "startsAt": _iso(g("event_start_utc")),
            "label": label,
            "price": float(g("price_decimal") or 0),
            "chance": p,
            "mk": f"{g('participant_name') or ''}|{g('market_name_raw') or ''}",
            "side": side,
        }
    if g("event") is not None and g("p") is not None:  # a discover leg
        return {
            "id": f"{g('sport') or sport}|{g('key') or g('event') + str(g('label'))}",
            "sport": g("sport") or sport,
            "game": g("event"),
            "startsAt": _iso(g("start")),
            "label": g("label"),
            "price": g("price"),
            "chance": g("p"),
            "mk": "",
            "side": "",
        }
    game = g("game") or ""  # an NBA / NFL leg
    return {
        "id": f"{sport}|{game}|{g('player')}|{g('stat')}|{g('line')}|{int(bool(g('under')))}"
        if g("player")
        else f"{sport}|{game}|{g('label')}",
        "sport": g("sport") or sport,
        "game": game,
        "startsAt": _iso(g("startsAt")),
        "label": g("label"),
        "price": g("price"),
        "chance": g("chance"),
        "mk": f"{g('player')}|{g('stat')}" if g("player") else "",
        "side": ("u" if g("under") else "o") if g("player") else "",
        "raw": {k: g(k) for k in ("player", "stat", "team", "line", "under", "sport") if g(k) is not None}
        if g("player")
        else None,
    }


def slip_cfg(chs, az, sport, tab="") -> dict:
    """What the bet slip sheets need (v13): bookmakers, credit left per bookmaker, the running
    challenges that can take a next leg (stage, bank, target x), and the form's op token."""
    out: dict = {"sport": sport or "", "tab": tab or "", "books": [], "credit": {}, "challenges": [], "op": ""}
    try:
        from melbcup import nba_challenge

        out["books"] = [{"code": a.code, "name": a.name} for a in (az.on if az else [])]
        for k in (chs or {}).get("credits", []):
            key = str(k["provider"]).lower()
            out["credit"][key] = round(out["credit"].get(key, 0.0) + float(k["amount"]), 2)
        out["op"] = (chs or {}).get("op", "")
        for it in (chs or {}).get("list", []):
            c, st = it["rec"], it["rec"]["state"]
            if st.get("active") is False or st.get("placed"):
                continue
            out["challenges"].append(
                {
                    "id": c["id"],
                    "name": c["name"],
                    "scope": c["scope"],
                    "stage": len(st["steps"]),
                    "stages": st.get("stages", 3),
                    "bank": st["bank"],
                    "goal": st["goal"],
                    "x": round(nba_challenge.next_x(st), 2),
                }
            )
    except Exception:  # noqa: BLE001 - the slip still works without challenges
        pass
    return out


def make_env(new_ui: bool = False) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(HERE / "templates")), autoescape=select_autoescape(["html"])
    )
    env.filters.update(
        pct=pct,
        money=money,
        edge=edge,
        local_time=local_time,
        until=until,
        book=book,
        statline=statline,
        day=day,
        shortdate=shortdate,
        longdate=longdate,
        isoday=isoday,
        racename=racename,
        confidence=confidence,
        verdict=price_verdict,
    )
    if new_ui:
        env.filters.update(ring_tone=asynym.tone, ring_pct=asynym.pct_of)
    env.globals.update(
        LABELS=LABELS,
        Call=Call,
        call_for=call,
        runner_call=runner_call,
        single_call=single_call,
        race_call=race_call,
        multis_call=multis_call,
        betting_open=betting_open,
        open_races=open_races,
    )
    env.globals["shown"] = history.shown
    env.globals["slip_cfg"] = slip_cfg
    env.globals["slip_leg"] = slip_leg
    env.globals["cat_flags"] = catalogue_view.flags
    env.globals["asset_v"] = asset_version(new_ui)
    env.filters.update(
        one_in=racecard.one_in,
        signed=signed,
        dollars=racecard.dollars,
        price=racecard.price_text,
        jump=racecard.jump,
        pills=racecard.pills,
        iso_time=when,
        when=when,
        before=lambda dt, minutes: local_time(dt - timedelta(minutes=minutes)) if dt else "",
    )
    return env


def parse_budget(text: str | None) -> float | None:
    raw = (text or "").strip().lstrip("$")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if 0 < value <= MAX_BUDGET else None


def pick_budget(
    query: Mapping[str, str], cookies: Mapping[str, str] | None = None
) -> tuple[float, bool]:
    """The day budget and whether the owner chose it: ?budget=, else the budget cookie, else
    $200. A ?budget= that is blank or not a number puts the budget back to the default."""
    if "budget" in query:
        chosen = parse_budget(query["budget"])
        return (chosen or DEFAULT_BUDGET), chosen is not None
    remembered = parse_budget((cookies or {}).get(BUDGET_COOKIE))
    return (remembered or DEFAULT_BUDGET), remembered is not None


class NotFound(LookupError):
    pass


@dataclass
class TodayMoney:
    """The header's day profit or loss (today's racing bets and NBA challenge stages)."""

    profit: float

    def fill(self, total: float) -> float:
        if not self.profit:
            return 0.0
        return 100.0 if total <= 0 else min(100.0, 100.0 * abs(self.profit) / total)


def _nba_money(path, query, cookies, today):
    """The open challenge's state (with this request's action applied on /nba), today's money over
    every challenge, and the page's challenge data (see nba_challenge.apply_store)."""
    try:
        from melbcup import nba_challenge
    except ImportError:  # the phone's offline copy leaves the NBA code out
        return None, {}, 0.0, None
    day = today.isoformat()
    store = nba_challenge.load((cookies or {}).get(nba_challenge.COOKIE))
    err = ""
    if path in ("/nba", "/sports") and "ch" in query:
        store, _, err = nba_challenge.apply_store(store, query, day)
    used, profit = nba_challenge.store_money(store, day)
    open_id = query.get("chid")
    if not open_id and query.get("ch") == "newch" and store["challenges"]:
        open_id = store["challenges"][-1]["id"]
    rec = nba_challenge.find(store, open_id)
    ctx = _chs_ctx(store, rec, err, day)
    if query.get("pr"):
        ctx["promo"] = _promo(query)
    return (rec["state"] if rec else None), used, profit, ctx


def _promo(q) -> dict:
    """The promotion table for the form's figures (all typed in by the owner)."""
    from melbcup import promos

    def num(k):
        try:
            return float(str(q.get(k) or "").replace("$", "").replace("%", "")) or None
        except ValueError:
            return None

    try:
        chances = [float(x) / 100 for x in str(q.get("pc") or "").replace(" ", "").split(",") if x]
        pf = num("pf")
        return promos.payoff(
            chances,
            num("pp") or 0,
            num("ps") or 0,
            boost_price=num("pb"),
            boost_fraction=pf / 100 if pf else None,
            refund_cap=num("pk"),
            redeem_rate=num("pr_rate") or 0.0,
            provenance=str(q.get("pn") or ""),
        )
    except (promos.PromoError, ValueError) as e:
        return {"error": str(e)}


def _chs_ctx(store, rec, err, day) -> dict:
    from melbcup import nba_challenge, wallet

    cs = wallet.credits(store["ledger"], day)
    return {
        "list": [
            {
                "rec": c,
                "row": nba_challenge.row(c) | _LIVE_ROWS["rows"].get(c["id"], {}),
                "status": nba_challenge.status(c),
                "held": [
                    k
                    for k in cs.values()
                    if k["challenge"] == c["id"] and k["status"] == "reserved"
                ],
            }
            for c in store["challenges"]
        ],
        "open": rec,
        "open_status": nba_challenge.status(rec) if rec else None,
        "credits": [c for c in cs.values() if c["status"] in ("available", "reserved")],
        "balances": wallet.balances(store["ledger"], day),
        "wagers": [
            w
            for w in store["wagers"]
            if rec and (rec["id"] == w["challenge"] or rec["id"] in w["refs"])
        ][-10:],
        "open_wagers": [w for w in store["wagers"] if w["state"] == "placed"][-10:],
        "err": err,
        "op": secrets.token_hex(4),  # fresh each render: the same form twice does nothing
        "own": store["own"],
    }


_LIVE_ROWS: dict = {"rows": {}}  # last live.json answer: the list renders with it at once


def challenges_live(store, now=None) -> dict:
    """{challenge id: {pct, clock}} for the list's collapsed rows. Saved figures first; the
    tracker (cached a minute) only for placed stages that have tipped off. Never raises."""
    from melbcup import nba_challenge, nba_live

    now = now or datetime.now(UTC)
    out: dict = {}
    for c in (store or {}).get("challenges", []):
        try:
            placed = (c.get("state") or {}).get("placed") or {}
            t = None
            tip = nba_challenge._when(placed.get("tip"))
            if placed.get("state") == "placed" and (tip is None or tip <= now):
                try:
                    t = nba_live.track(placed.get("label", ""), now)
                except Exception:  # noqa: BLE001 - a bad feed must not break the list
                    t = None
            r = nba_challenge.row(c, t, now)
            out[c["id"]] = {"pct": r["pct"], "clock": r["clock"], "failed": r["failed"]}
        except Exception:  # noqa: BLE001
            continue
    _LIVE_ROWS["rows"] = out
    return out


def _scope_chs(chs, ch_state, page, chid):
    """This page's challenges only (NBA page: scope nba; NFL page: scope nfl). The opened one is
    the requested chid when it is this page's, else the newest of this page's, else none."""
    if not chs:
        return chs, ch_state
    mine = [it for it in chs["list"] if it["rec"]["scope"] == page]
    opened = chs.get("open")
    if not opened or opened["scope"] != page or (chid and opened["id"] != chid):
        opened = next((it["rec"] for it in mine if it["rec"]["id"] == chid), None)
        opened = opened or (mine[-1]["rec"] if mine else None)
    out = {
        **chs,
        "list": mine,
        "open": opened,
        "wagers": [
            w
            for w in chs.get("wagers", [])
            if opened and (opened["id"] == w["challenge"] or opened["id"] in w["refs"])
        ],
    }
    if opened is None:
        out["open_status"] = None
    elif opened["id"] != (chs.get("open") or {}).get("id"):
        from melbcup import nba_challenge

        out["open_status"] = nba_challenge.status(opened)
    return out, (opened["state"] if opened else None)


_HG: dict = {"at": 0.0, "val": None, "busy": False}


def _home_games(discover, catalogue_view) -> list[dict]:
    """Home's next games across every sport, from memory (owner, 2026-11-10: 6 s a load reading
    every sport's shards). Over a minute old: served at once, refreshed behind."""
    import threading

    def build():
        try:
            every = []
            for s_ in catalogue_view.coverage():
                every += [g | {"sport": s_} for g in discover.next_games(s_, 3)]
            _HG.update(at=time.monotonic(), val=sorted(every, key=lambda g: g.get("start") or "~")[:12])
        finally:
            _HG["busy"] = False

    if _HG["val"] is None:
        build()
    elif time.monotonic() - _HG["at"] > 60 and not _HG["busy"]:
        _HG["busy"] = True
        threading.Thread(target=build, daemon=True).start()
    return _HG["val"] or []


def _own_bets(state, today) -> list[dict]:
    try:
        from melbcup import nba_challenge
    except ImportError:  # the phone's offline copy leaves the NBA code out
        return []
    return nba_challenge.own_bets(state, today.isoformat())


class Views:
    def __init__(self, settings: Settings, board: LiveBoard, *, browser: bool = False):
        self.settings = settings
        self.board = board
        self.browser = browser  # no threads: loads run to completion before the page renders
        self.env = make_env(settings.asynym)
        self._nba = None  # NbaFeed, made on the first visit to /nba
        self._agencies_on: set[str] = set()

    def _sport_challenge(self, query: Mapping[str, str], ctx: dict, sport: str, disc) -> dict:
        """A non-NBA sport's Challenge tab: the All Sports challenges (NBA ones stay on the NBA
        tab), the stage timeline, and the pick whose odds range holds the stage's target."""
        chs = ctx.get("chs")
        if not chs:
            return {"ch": None, "ch_step": None, "ch_tl": [], "ch_sug": None}
        scopes = ("all", sport) if sport == "nfl" else ("all",)  # NFL challenges ride its own tab
        mine = [it for it in chs["list"] if it["rec"]["scope"] in scopes]
        opened = chs["open"] if chs["open"] and chs["open"]["scope"] in scopes else None
        opened = opened or (mine[-1]["rec"] if mine else None)
        sub = {
            **ctx,
            "chs": {**chs, "list": mine, "open": opened},
            "ch_state": opened["state"] if opened else None,
        }
        out = self._challenge(query, sub)
        out["chs"] = sub["chs"]
        out["ch_state"] = sub["ch_state"]
        out["ch_tl"] = self._stage_timeline(out.get("ch"), out.get("ch_x"))
        sug = (
            self._stage_pick(disc, sport, out.get("ch_x"), (out.get("ch") or {}).get("legs"))
            if out["ch_tl"]
            else None
        )
        st = out.get("ch")
        out["ch_sug_live"] = None
        out["ch_sug_at"] = None
        if st and not st.get("placed") and out["ch_tl"]:
            from melbcup import nba_challenge

            sh = nba_challenge.shown_for(st, "shown_sug")
            if sug and not sh:
                sh = {"stage": len(st["steps"]), "at": datetime.now(UTC).isoformat(), "sug": sug}
                cid = (opened or {}).get("id")
                nba_challenge.freeze(cid, st, "shown_sug", sh)
            if sh:
                if sug and sh["sug"] != sug:
                    out["ch_sug_live"] = sug
                sug = sh["sug"]
                out["ch_sug_at"] = sh["at"]
        out["ch_sug"] = sug
        return out

    @staticmethod
    def _stage_timeline(run: dict | None, x: float | None) -> list[dict]:
        """The run's stages for the v8-2 timeline: done (from -> to), the current, those to come."""
        if not run or x is None:
            return []
        steps = run.get("steps") or []
        out = []
        for i in range(max(run.get("stages", 3), len(steps) + 1)):
            if i < len(steps):
                out.append(
                    {"n": i + 1, "st": "done", "frm": steps[i]["from"], "to": steps[i]["to"]}
                )
            else:
                out.append({"n": i + 1, "st": "cur" if i == len(steps) else "todo", "x": x})
        return out

    @staticmethod
    def _stage_pick(disc, sport: str | None, x: float | None, legs: int | None = None):
        """The automatic pick for a stage aiming at x times the stake: the likeliest multi priced
        at x or more (fine ladder), this sport's else all sports'; None when none."""
        if x is None or not disc:
            return None
        from melbcup import discover

        r = discover.pick_for(x, sport if sport not in (None, "home", "all") else None, legs, disc)
        return r if r.get("band") else None

    def _challenge(self, query: Mapping[str, str], ctx: dict) -> dict:
        """The $10 -> $1000 challenge (cookie on the phone; app.py saves the change)."""
        try:
            from melbcup import nba_challenge, nba_legs
        except ImportError:  # the phone's offline copy leaves the NBA code out
            return {"ch": None, "ch_step": None}
        state = ctx.get("ch_state")
        opened = (ctx.get("chs") or {}).get("open")
        previewing = bool(query.get("chpreview"))
        if opened is None and not previewing:
            return {"ch": None, "ch_step": None}
        page = "nfl" if ctx.get("sport") == "nfl" else "nba"
        if opened is not None and opened["scope"] != page and not previewing:  # another sport or All: legs typed in
            # (a "Best stages" preview for a new challenge on this page is never blocked by it)
            run = state if state and state.get("active") is not False else None
            return {
                "ch": run,
                "ch_step": None,
                "ch_plan": {"start": 10.0, "goal": 1000.0, "keep": True, "legs": None},
                "ch_games": [],
                "ch_preview": [],
                "ch_best": None,
                "ch_why": "",
                "ch_wait": None,
                "ch_alt_agency": None,
                "ch_finish": None,
                "ch_due": None,
                "ch_night": None,
                "ch_typed": True,
                "ch_x": nba_challenge.next_x(run) if run else None,
                "ch_left": nba_challenge.remaining(run) if run else None,
                "push_reminders": [],
            }
        if state is not None and state.get("active") is False:
            state = None  # no run on: the start screen (history and bets stay in the cookie)
        if previewing and opened is not None and opened["scope"] != page:
            state = None  # previewing a new challenge: never pick (or save) a stage for the other sport's run
        ch_url = "/sports?sport=nfl&tab=challenge" if page == "nfl" else "/nba?tab=challenge"
        legs_now = (ctx.get("nba_rep") or {}).get("all_legs") or []
        own = {} if previewing else (state or {})  # a preview is for the NEW challenge's form values
        want = own.get("legs") or nba_challenge._legs(query.get("chlegs"))
        # the stage plan follows the mode chosen in the form (a started run keeps its own)
        mode = own.get("mode") or ("multi" if query.get("chmode") == "multi" else "game")
        run_want = (state or {}).get("legs") or want
        lim = {"min_legs": run_want, "max_legs": run_want} if run_want else {}
        p_start = nba_challenge._money(query.get("chstart")) or 10.0
        p_goal = max(nba_challenge._money(query.get("chgoal")) or 1000.0, p_start * 2)
        p_keep = query.get("chkeep", "1") == "1" if (query.get("chplan") or previewing) else True
        fresh_run = state is None or not (state["steps"] or state.get("placed"))
        if state is not None and fresh_run and not previewing:  # a just-created run
            p_start, p_goal, p_keep = state["start"], state["goal"], state.get("keep", True)
        preview = (
            self._stage_preview(
                legs_now, nba_challenge, nba_legs, p_start, p_goal, p_keep, want, mode
            )
            if fresh_run
            else []
        )
        best, why = nba_challenge.recommend(preview) if preview else (None, "")
        step, games, wait, push, alt_agency = None, [], None, [], None
        live_step = None
        if state is not None:
            x = nba_challenge.next_x(state)
            # only games this stage may use: spaced from tonight's earlier stage, or a later night
            legs = [g for g in legs_now if nba_challenge.allowed(state, g.get("startsAt"))]
            # the searches only change when the prices do (every 10 min): remembered until then
            # (owner, 2026-11-13: the Challenge tab spent ~0.6 s per load re-searching)
            ck = (id(legs_now), len(legs_now), len(legs), round(x, 4), round(state["bank"], 2), state.get("mode", "game"),
                  json.dumps(lim, sort_keys=True), ctx.get("nba_agency"), state.get("pick"))
            memo = self.__dict__.setdefault("_ch_memo", {})
            if ck in memo:
                step, games, alt_agency = memo[ck]
            else:
                if state.get("mode", "game") == "game":
                    games = nba_legs.same_game_for(legs, x, stake=state["bank"], **lim)
                    step = max(games, key=lambda m: m["chance"]) if games else None
                    chosen = state.get("pick")  # a game the owner stuck to for this stage
                    if chosen:
                        step = next((m for m in games if m.get("game") == chosen), step)
                    alt_agency = self._best_elsewhere(state, x, step, nba_challenge, nba_legs)
                else:
                    step = nba_legs.stack_for(legs, x, stake=state["bank"], **lim)
                if len(memo) > 64:
                    memo.clear()
                memo[ck] = (step, games, alt_agency)
            sh = nba_challenge.shown_for(state)
            ag = ctx.get("nba_agency")
            if step and not sh:
                at = datetime.now(UTC).isoformat()
                sh = {"stage": len(state["steps"]), "at": at, "step": step, "ag": ag}
                cid = ((ctx.get("chs") or {}).get("open") or {}).get("id")
                nba_challenge.freeze(cid, state, "shown", sh)
            elif sh and step and ag and sh.get("ag", ag) != ag:
                # the owner switched bookmaker: that bookmaker's own lines (owner, 2026-11-11: a
                # Sportsbet pick had Turner Under 5.5 rebounds; PointsBet only had 4.5)
                sh = {"stage": len(state["steps"]), "at": datetime.now(UTC).isoformat(), "step": step, "ag": ag}
                nba_challenge.refreeze(((ctx.get("chs") or {}).get("open") or {}).get("id"), state, "shown", sh)
            if sh and step:
                # re-pick when a leg's line is gone from the board (any picker: a bet the bookmaker
                # no longer offers can't be placed), and on picker v2 when its price lengthened >3%
                moves = nba_challenge.drifted(sh["step"], legs_now)
                if nba_legs.picker() != "v2":
                    moves = [m for m in moves if m.get("gone")]
                if moves:
                    at = datetime.now(UTC).isoformat()
                    ev = {"at": at, "stage": len(state["steps"]), "picker": "v2", "was": sh["step"].get("picks"),
                          "now": step.get("picks"), "moves": moves, "was_chance": sh["step"].get("chance"),
                          "now_chance": step.get("chance")}
                    sh = {"stage": len(state["steps"]), "at": at, "step": step, "repick": nba_challenge.repick_note(moves)}
                    cid = ((ctx.get("chs") or {}).get("open") or {}).get("id")
                    nba_challenge.refreeze(cid, state, "shown", sh, ev)
            if sh and step:
                if sh["step"] != step:
                    live_step = step
                step = sh["step"]
            earliest, not_night = nba_challenge.next_window(state)
            if not step and (earliest or not_night):
                wait = {"after": earliest, "night": not_night}
            n = len(state["steps"]) + 1
            due = nba_challenge.result_due(state)
            alerts = []
            if due:
                alerts.append(
                    {
                        "n": n,
                        "t": due.isoformat(),
                        "label": f"Stage {n} result due",
                        "href": ch_url,
                        "alert": 0,
                    }
                )
            elif step and step.get("startsAt"):
                alerts.append(
                    {
                        "n": n,
                        "t": step["startsAt"],
                        "label": f"Stage {n} tips off",
                        "href": ch_url,
                        "alert": 900,
                    }
                )
            # the same times, for the phone alerts the Function pushes (melbcup/push_store.py)
            for a in alerts:
                when = datetime.fromisoformat(a["t"].replace("Z", "+00:00"))
                if a["label"].endswith("result due"):
                    push.append(
                        {
                            "at": when.isoformat(),
                            "title": f"Stage {n} result due",
                            "body": "Mark it won or lost and the next stage is ready.",
                            "url": ch_url,
                        }
                    )
                else:
                    game = (step or {}).get("game") or "the next game"
                    push.append(
                        {
                            "at": (when - timedelta(minutes=15)).isoformat(),
                            "title": f"Stage {n} tips off in 15 min",
                            "body": f"{game}: place it now.",
                            "url": ch_url,
                        }
                    )
            now = datetime.now(UTC)
            for a in alerts:
                when = datetime.fromisoformat(a["t"].replace("Z", "+00:00"))
                if when > now:
                    ctx["countdown"] = sorted(
                        ctx["countdown"] + [a | {"left": int((when - now).total_seconds())}],
                        key=lambda r: r["t"],
                    )
        return {
            "push_reminders": push,
            "ch": state,
            "ch_step": step,
            "ch_live": live_step,
            "ch_shown_at": ((state or {}).get("shown") or {}).get("at") if step else None,
            "ch_repick": ((state or {}).get("shown") or {}).get("repick") if step else None,
            "ch_alt_agency": alt_agency,
            "ch_games": games,
            "ch_preview": preview,
            "ch_best": best,
            "ch_pv": previewing,
            "ch_pname": query.get("chname", ""),
            "ch_night": nba_challenge.night(nba_challenge._when(step.get("startsAt")))
            if (state and step and nba_challenge._when(step.get("startsAt")))
            else None,
            "ch_why": why,
            "ch_mode": mode,
            "ch_plan": {"start": p_start, "goal": p_goal, "keep": p_keep, "legs": want},
            "ch_wait": wait,
            "ch_finish": nba_challenge.finish_chance(
                step["chance"], state, nba_challenge.typical([g["chance"] for g in games])
            )
            if (state and step)
            else None,
            "ch_due": nba_challenge.result_due(state) if state else None,
            "ch_x": nba_challenge.next_x(state) if state else None,
            "ch_left": nba_challenge.remaining(state) if state else None,
        }

    @staticmethod
    def _chcard(ctx: dict) -> dict | None:
        """What the opened challenge's card (asynym/_chcard.html) shows: ring, bar, stage
        blocks and leg tiles, with the live estimate once in play (owner lock 2026-11-08)."""
        import math

        try:
            from melbcup import live_chance, nba_live
        except ImportError:  # the phone's offline copy leaves the NBA code out
            return None
        chs = ctx.get("chs") or {}
        rec = chs.get("open")
        ch = ctx.get("ch")
        if not rec or not ch:
            return None
        placed = ch.get("placed")
        tr = (ctx.get("track") or {}).get(placed["id"]) if placed else None
        tabs = [
            {
                "letter": chr(65 + i % 26),
                "id": it["rec"]["id"],
                "name": it["rec"]["name"],
                "on": it["rec"]["id"] == rec["id"],
                "price": (it["rec"]["state"].get("placed") or {}).get("price"),
            }
            for i, it in enumerate(chs.get("list") or [])
        ]
        start, bank, goal = ch["start"], ch["bank"], ch["goal"]
        pct = 0.0
        if start > 0 and goal > start and bank > 0:
            pct = min(max(math.log(bank / start) / math.log(goal / start), 0.0), 1.0) * 100
        n_done, n_all = len(ch["steps"]), ch.get("stages", 3)
        live = bet = None
        tiles = []
        if placed:
            tiles, live = bet_tiles(tr, placed)
            bet = live["p"]
        ring = bet
        if ring is None and not placed:
            step = ctx.get("ch_step") or {}
            ring = step.get("chance")
        verdict = (tr or {}).get("verdict")
        dead = bet_dead(tr)
        if dead:
            tiles = dead_tiles(tiles)
        blocks = []
        for i in range(n_all):
            if i < n_done:
                st = ch["steps"][i]
                blocks.append({"cls": "done", "k": f"Stage {i + 1}", "v": f"${st['to']:.2f}"})
            elif i == n_done:
                blocks.append(
                    {"cls": "bad" if dead else "now", "k": f"Stage {i + 1}", "v": f"${bank:.2f}"}
                )
            else:
                blocks.append({"cls": "next", "k": f"Stage {i + 1}", "v": "next"})
        odds = placed.get("price") if placed else (ctx.get("ch_step") or {}).get("price")
        return {
            "tabs": tabs,
            "name": rec["name"],
            "pct": round(pct),
            "goal": goal,
            "stages_done": n_done,
            "stages": n_all,
            "blocks": blocks,
            "tiles": tiles,
            "ring": None if ring is None else round(ring * 100),
            "ring_cls": ""
            if ring is None
            else ("g" if ring >= 0.6 else "p" if ring >= 0.3 else "a"),
            "odds": odds,
            "placed": bool(placed),
            "dead": dead,
            "verdict": verdict,
            "in_play": bool(tr and tr["state"] == "in"),
            "clock": (tr or {}).get("clock", ""),
            "live": bool(live and live["live"]),
            "approx": bool(live and live["approx"]),
            "bonus": bool(placed and placed.get("bonus")),
            "tip": placed.get("tip") if placed else None,
            "any_play": bool(tr and tr["state"] == "in"),
        }

    @staticmethod
    def _track(ctx: dict) -> dict:
        """Leg-by-leg results of the placed challenge stage and your own bets, once their game
        has tipped off ({bet id: nba_live.track()}; owner, 2026-11-05)."""
        try:
            from melbcup import nba_challenge, nba_live
        except ImportError:  # the phone's offline copy leaves the NBA code out
            return {}
        state = ctx.get("ch_state") or {}
        bets = list(ctx.get("nba_own") or [])
        if state.get("placed"):
            bets.append(state["placed"])
        now, out = datetime.now(UTC), {}
        for b in bets:
            tip = nba_challenge._when(b.get("tip"))
            if b.get("state") == "placed" and (tip is None or tip <= now):
                t = nba_live.track(b.get("label", ""), now)
                if t:
                    out[b["id"]] = t
        return out

    @staticmethod
    def _own_live(ctx: dict) -> dict:
        """{own bet id: live_chance.bet_live()} for the My bets sheet; never raises."""
        out: dict = {}
        try:
            from melbcup import live_chance

            for b in ctx.get("nba_own") or []:
                if b.get("state") == "placed":
                    out[b["id"]] = live_chance.bet_live((ctx.get("track") or {}).get(b["id"]), b)
        except Exception:  # noqa: BLE001 - the live chance is optional
            return {}
        return out

    def _bonus_credits(self) -> list[dict]:
        """Open bonus credits (read-only), for the Bet now note; [] when none or unreadable."""
        try:
            from melbcup import nba_challenge, wallet

            day = datetime.now(MELBOURNE).date().isoformat()
            cs = wallet.credits(nba_challenge.load()["ledger"], day)
            return [c for c in cs.values() if c["status"] == "available" and c["amount"]]
        except Exception:  # noqa: BLE001 - the note is optional
            return []

    def _best_elsewhere(self, state, x, step, nba_challenge, nba_legs) -> dict | None:
        """The same stage at the other agencies: their likeliest same-game multi for this payout.
        Returned when one beats the shown pick (owner, 2026-11-05: place where it pays most, as a
        better price means safer legs for the same stage)."""
        view = (self._nba._view[1] or {}) if self._nba else {}
        names = {"sb": "Sportsbet", "pb": "PointsBet"}
        best = None
        for code, a in (view.get("agencies") or {}).items():
            if code == getattr(self, "_nba_pick", None):
                continue
            legs = [
                g
                for g in ((a.get("report") or {}).get("all_legs") or [])
                if nba_challenge.allowed(state, g.get("startsAt"))
            ]
            n = state.get("legs")
            lim = {"min_legs": n, "max_legs": n} if n else {}
            found = nba_legs.same_game_for(legs, x, stake=state["bank"], **lim)
            top = max(found, key=lambda m: m["chance"]) if found else None
            if top and (best is None or top["chance"] > best["chance"]):
                left = getattr(self, "_agency_left", {}).get(code, 0.0)
                best = top | {
                    "code": code,
                    "name": names.get(code, code),
                    "on": code in self._agencies_on,
                    # money already there: switching is practical; else it means moving money
                    "funded": left >= state["bank"],
                }
        if best and (step is None or best["chance"] > step["chance"] + 0.01):
            return best
        return None

    def _stage_preview(
        self,
        legs,
        nba_challenge,
        nba_legs,
        start=10.0,
        goal=1000.0,
        keep=True,
        want=None,
        mode="game",
    ):
        """The set-up table for this start and goal (nba_challenge.plan): per stage count, the
        payout a stage, tonight's best and typical stage chance and the run's. Kept per lines and
        goal, so only a new goal does the search (about a second)."""
        key = (id(legs), len(legs), round(goal / start, 3), keep, want, mode)
        cache = self.__dict__.setdefault("_plan_cache", {})
        if key not in cache:

            def chances_for(xmap):
                lim = {"min_legs": want, "max_legs": want} if want else {}
                find = nba_legs.stacks_many if mode == "multi" else nba_legs.same_game_many
                many = find(legs, list(set(xmap.values())), **lim)
                return {n: [g["chance"] for g in many[x]] for n, x in xmap.items()}

            if len(cache) > 8:
                cache.clear()
            cache[key] = nba_challenge.plan(start, goal, keep, chances_for)
        return cache[key]

    def challenge_plan(self, sport: str, start: float, goal: float, mode: str, legs: int | None, n: int | None = None) -> dict:
        """The new-challenge planner's numbers (v13): the same _stage_preview rows the server
        form uses, the best stage count, and the best stage-1 pick (NBA / NFL legs; other sports
        have no leg model yet, so only the payouts a stage come back)."""
        from melbcup import nba_challenge, nba_legs

        start = max(start, 1.0)
        goal = max(goal, start * 2)
        mode = "multi" if mode == "multi" else "game"
        want = legs if legs in (2, 3, 4) else None
        rows, pick, best, why = [], None, None, ""
        legs_now: list = []
        if sport in ("nba", "nfl"):
            self._agencies_on = getattr(self, "_agencies_on", set())
            legs_now = (self._nba_view({"tab": "all"}, sport).get("nba_rep") or {}).get("all_legs") or []
        if legs_now:
            rows = self._stage_preview(legs_now, nba_challenge, nba_legs, start, goal, True, want, mode)
            best, why = nba_challenge.recommend(rows)
            # the stage-1 pick for the stage count the owner chose, else the best (owner, 2026-11-10)
            chosen = next((r for r in rows if n and r.get("n") == n), None) or best
            x = chosen["x"] if chosen else None
            lim = {"min_legs": want, "max_legs": want} if want else {}
            if x:
                if mode == "game":
                    games = nba_legs.same_game_for(legs_now, x, stake=start, **lim)
                    m = max(games, key=lambda g: g["chance"]) if games else None
                else:
                    m = nba_legs.stack_for(legs_now, x, stake=start, **lim)
                if m:
                    pick = {
                        "game": m.get("game", ""),
                        "price": m["price"],
                        "chance": m["chance"],
                        "legs": [
                            {"label": d["label"], "price": d["price"], "chance": d["chance"], "game": d.get("game", ""), "startsAt": d.get("startsAt", "")}
                            for d in m.get("detail", [])
                        ],
                    }
        else:
            rows = nba_challenge.plan(start, goal, True, lambda xmap: {})
        return {"sport": sport, "start": start, "goal": goal, "mode": mode, "legs": want,
                "rows": rows, "best": best, "why": why, "pick": pick,
                "pick_n": (chosen or {}).get("n") if legs_now else None}

    @staticmethod
    def slip_chance(legs: list) -> dict:
        """The slip's chance every leg wins: per game the copula joint chance (NBA CORR, NFL
        relations), multiplied across games. {"p", "exact"}; exact False when a leg has no model."""
        from melbcup import nba_legs

        by: dict = {}
        for g in legs:
            by.setdefault(g.get("game") or "", []).append(g)
        p, exact = 1.0, True
        for gs in by.values():
            if len(gs) == 1:
                p *= float(gs[0].get("chance") or 1 / float(gs[0]["price"]))
                continue
            if not all(g.get("raw") and g.get("chance") for g in gs):
                exact = False
                p *= math.prod(float(g.get("chance") or 1 / float(g["price"])) for g in gs)
                continue
            p *= nba_legs.joint_chance(
                [{**g["raw"], "chance": float(g["chance"]), "game": g.get("game")} for g in gs]
            )
        return {"p": round(p, 6), "exact": exact}

    def track_for(self, bets: list) -> dict:
        return self._track({"nba_own": bets})

    def nba_us_pretip(self) -> bool:
        try:
            from melbcup.nba_feed import NbaFeed
        except ImportError:
            return False
        if self._nba is None:
            self._nba = NbaFeed()
        return self._nba.us_pretip()

    def nba_stamp(self) -> str:
        """When the NBA page's prices were worked out (the page checks this to swap in fresher)."""
        v = (self._nba._view[1] or {}) if self._nba else {}
        p = v.get("priced_at")
        return p.isoformat() if hasattr(p, "isoformat") else str(p or "")

    def warm_nba(self) -> None:
        """Load the NBA page data in the background when the app starts (owner: fast pages)."""
        try:
            from melbcup.nba_feed import NbaFeed

            if self._nba is None:
                self._nba = NbaFeed()
            self._nba.view()
        except Exception:  # the page loads it on first visit instead
            pass

    def _nba_view(self, query: Mapping[str, str], sport: str = "nba") -> dict:
        if sport == "nfl":  # same page, NFL legs (one source, no agency switch)
            from melbcup import nfl_legs

            v, rep = nfl_legs.page_view()
            tab = query.get("tab")
            tab = tab if tab in ("stacks", "challenge", "games", "same", "all") else "stacks"
            self._nba_pick = None
            return {
                "alt_pay": lambda item: None,
                "nba": v,
                "nba_us_note": None,
                "nba_tab": tab,
                "nba_rep": rep,
                "nba_games": {},
                "nba_agency": None,
                "nba_agency_name": "PointsBet",
                "nba_chips": [],
                "nba_agency_games": v["games"],
                "nba_agency_error": None,
            }
        try:
            from melbcup.nba_feed import NbaFeed
        except ImportError:  # the phone's offline copy (GitHub Pages) leaves the live NBA code out
            v = {
                "board": None,
                "source": "",
                "stale": False,
                "games": 0,
                "priced_at": None,
                "error": "The NBA page needs the live site: open bet.asynym.dev.",
            }
            return {"nba": v, "nba_tab": "legs", "nba_rep": {}, "nba_games": {}}
        if self._nba is None:
            self._nba = NbaFeed()
        self._nba.set_us(getattr(self, "_us_on", False), force=query.get("us") == "1")
        v = self._nba.view()
        us_note = (v.get("us") or {}).get("error")
        tab = query.get("tab")
        tab = tab if tab in ("stacks", "challenge", "games", "same", "all") else "stacks"
        # Prices from the agency picked here (?bk=), else the first agency switched ON in Agencies
        # that has NBA lines (Sportsbet first), else whichever has lines: the chances are the
        # model's either way; the lines and prices are that agency's.
        agencies = v.get("agencies") or {}
        on = self._agencies_on
        has = [c for c in ("sb", "pb") if (agencies.get(c) or {}).get("report", {}).get("all_legs")]
        pick = query.get("bk") if query.get("bk") in agencies else None
        pick = pick or next((c for c in has if c in on), None) or (has[0] if has else None)
        pick = pick or next(iter(agencies), None)
        chosen = agencies.get(pick) or {}
        self._nba_pick = pick
        rep = chosen.get("report") or v.get("report") or {}
        games = {g["name"].replace(" at ", " @ "): g for g in (v["board"] or {}).get("games", [])}
        names = {"sb": "Sportsbet", "pb": "PointsBet"}
        chips = [
            {
                "code": c,
                "name": names.get(c, c),
                "lines": len((agencies[c].get("report") or {}).get("all_legs") or []),
                "on": c in on,
            }
            for c in ("sb", "pb")
            if c in agencies
        ]
        # With both agencies switched on: a bubble when the other one pays more for the same bet
        alt_prices, alt_code = {}, None
        other = next((c for c in ("sb", "pb") if c != pick and c in agencies), None)
        if other and other in on and pick in on:
            from melbcup.nba_legs import bet_key, better_elsewhere

            alt_code = other.upper()
            for g in (agencies[other].get("report") or {}).get("all_legs") or []:
                alt_prices[bet_key(g)] = max(g["price"], alt_prices.get(bet_key(g), 0))

            def alt_pay(item):
                return better_elsewhere(item, alt_prices, alt_code) if item else None
        else:

            def alt_pay(item):
                return None

        return {
            "alt_pay": alt_pay,
            "nba": v,
            "nba_us_note": us_note,
            "nba_tab": tab,
            "nba_rep": rep,
            "nba_games": games,
            "nba_agency": pick,
            "nba_agency_name": names.get(pick, "PointsBet"),
            "nba_chips": chips,
            "nba_agency_games": chosen.get("games", v.get("games")),
            "nba_agency_error": chosen.get("error"),
        }

    def _context(
        self, path: str, query: Mapping[str, str], cookies: Mapping[str, str] | None = None
    ) -> dict:
        snap = self.board.snapshot()
        now = datetime.now(UTC)
        cookies = cookies or {}
        sb, bf, chosen = pick_amounts(query, cookies)
        # PointsBet (POINTSBET=1): a third account, $0 until the owner sets an amount. It is
        # judged in the picks only once it has money, so the switch alone changes no price.
        pb = pick_pointsbet(query, cookies) if self.settings.pointsbet else None
        az = None
        if self.settings.asynym:  # ASYNYM=1: an OFF account gets $0, so nothing routes there
            az = asynym.choose(query, cookies, self.settings)
            sb, bf, pb = az.routed()
            chosen = True
        placed = parse_placed(cookies.get(PLACED_COOKIE), snap.race_date, pb is not None)
        day_total = sb + bf + (pb or 0.0)
        if snap.models and self.settings.promos:  # PROMOS=1: promos that beat the Win pick
            picks = snap.picks(day_total or None, bool(pb), PROMOS)
        elif snap.models:
            picks = snap.picks(day_total or None, True) if pb else snap.picks(day_total or None)
        else:
            picks = None
        grade = (
            grade_day(picks) if picks and any(rp.model.race.result for rp in picks.races) else None
        )
        races = (
            {rp.model.race.number: rp.model.race for rp in picks.races}
            if picks
            else {r.number: r for r in (snap.card.races if snap.card else [])}
        )
        marks = {rg.race: {g.kind: g for g in rg.lines} for rg in (grade.races if grade else [])}
        card = (
            build_day(
                picks, sb, bf, placed, open_races(picks), snap.race_date, pb, self.settings.promos
            )
            if picks
            else None
        )
        # The kids' bets (their own cookie) come off the wallet and count in the day's profit
        # and loss, but they are not the owner's own bets: nothing else treats them as placed.
        kids = parse_kids(cookies.get(KIDS_COOKIE), snap.race_date, pb is not None)
        for k in kids:
            k.settled = settle_bet(k.bet, races)
        extras = parse_extras(cookies.get(EXTRA_COOKIE), snap.race_date, pb is not None)
        for x in extras:
            x.settled = settle_extra(x.bet, races)
        mine = settle_all(placed, races)
        kids_by_race: dict[int, list] = {}
        for k in kids:
            kids_by_race.setdefault(k.bet.race, []).append(k)
        wal = wallet(sb, bf, placed + [k.bet for k in kids] + [x.settled.bet for x in extras], pb)
        if az is not None:
            az.apply_wallet(wal)
        # The header's "Today": only today's bets. A meeting from another day (yesterday's card
        # still loaded) keeps its bets on Mine but neither its loss nor its stakes count today;
        # NBA challenge stakes come off their agency and wins pay back into it.
        today = melbourne_today()
        racing_today = snap.race_date == today
        day_bets = DayResult(mine.bets + [k.settled for k in kids] + [x.settled for x in extras])
        ch_state, nba_used, nba_profit, chs = _nba_money(path, query, cookies, today)
        if az is not None:
            for a in az.agencies:
                a.used = (a.used if racing_today else 0.0) + nba_used.get(a.code, 0.0)
        day_pnl = TodayMoney((day_bets.profit if racing_today else 0.0) + nba_profit)
        return {
            "push_key": os.environ.get("VAPID_PUBLIC_KEY", ""),  # phone alerts, in Settings
            "day_pnl": day_pnl,
            "ch_state": ch_state,
            "nba_own": _own_bets((chs or {}).get("own"), today),
            "chs": chs,
            "nba_us_cookie": (cookies or {}).get("nba_us"),
            "az": az,
            "settings": self.settings,
            "browser": self.browser,
            "snap": snap,
            "card": snap.card,
            "day": card,
            "wallet": wal,
            "pnl": DayResult(mine.bets + [k.settled for k in kids] + [x.settled for x in extras]),
            "extras": extras,
            "extra_races": {
                n: [[r.number, r.name] for r in rc.starters] for n, rc in sorted(races.items())
            },
            "pnl_own": mine,
            "kids": kids_by_race,
            "kids_in": bool(kids),
            "finals": final_picks(cookies.get(PICKS_COOKIE), snap.race_date, pb is not None, races),
            "amounts_chosen": chosen,
            "race_date_iso": snap.race_date.isoformat() if snap.race_date else "",
            "budget": day_total,
            "budget_q": "",
            "picks": picks,
            "grade": grade,
            "marks": marks,
            "checks": snap.checks,
            "today": melbourne_today(),
            "here": path,
            "can_fetch": self.board.can_fetch,
            "now": now,
            "countdown": countdown(picks, now),
            "picks_data": open_picks(card, snap.race_date),
        }

    def page(
        self, path: str, query: Mapping[str, str], cookies: Mapping[str, str] | None = None
    ) -> str:
        """HTML for a page path; raises NotFound. ``cookies`` carries the remembered budget."""
        t0 = time.perf_counter()
        ctx = self._context(path, query, cookies)
        self.timing = {"context": time.perf_counter() - t0}
        ctx["cookies"] = cookies or {}
        if self.settings.asynym and path != "/history":
            html = self._asynym_page(path, query, ctx)
            # where the time went, as an HTML comment (owner, 2026-11-13: "slow and clunky")
            tt = getattr(self, "_tt", {}) or {}
            self._tt = {}
            return html + "<!-- t total %.2f %s -->" % (time.perf_counter() - t0, " ".join(f"{k} {v:.2f}" for k, v in sorted(tt.items(), key=lambda kv: -kv[1])[:10]))
        if path == "/":
            return self.env.get_template("day.html").render(ctx)
        if path == "/history":
            archive = self.board.archive
            saved = archive.history() if archive is not None else []
            record = history.merge(saved, self.board.history())
            ctx.update(
                record=record,
                tallies=history.tally(record),
                by_confidence=history.by_confidence(record),
                h2h=history.head_to_head(record),
                groups=history.meetings(record),
                saved_count=len(saved),
                check_totals=self.board.check_totals(),
            )
            return self.env.get_template("history.html").render(ctx)
        if path == "/meetings":
            ctx.update(self._meetings(ctx, query))
            return self.env.get_template("meetings.html").render(ctx)
        if path.startswith("/race/"):
            self._race_context(path, ctx)
            rp = ctx["rp"]
            ctx["cup_note"] = cup_note(rp) if self.settings.pointsbet and ctx["rc"].open else None
            if ctx["cup_note"] and any(x.promo for x in ctx["rc"].board):
                ctx["cup_note"] = None  # the Win bet already is the promo bet, shown on its line
            return self.env.get_template("race.html").render(ctx)
        raise NotFound(path)

    def _meetings(self, ctx: dict, query: Mapping[str, str]) -> dict:
        """The meeting lists for a date (?date=, else the loaded meeting's): the meetings found
        for it and the Cup Carnival days."""
        pick = _date(query.get("date")) or ctx["snap"].race_date
        archive = self.board.archive
        saved = archive.venues(pick) if archive and pick < ctx["today"] else []
        return dict(
            pick=pick,
            found=saved or ctx["snap"].meetings.get(pick),
            carnival=CARNIVAL,
            here=f"/meetings?date={pick.isoformat()}",
        )

    def _asynym_page(self, path: str, query: Mapping[str, str], ctx: dict) -> str:
        """The AsynymBet pages (ASYNYM=1): Home, Race days, a meeting's races, a race, Mine."""
        day, snap = ctx["day"], ctx["snap"]
        ctx["pb_on"] = ctx["az"].get("pb").on
        ctx["tab_q"] = query.get("tab", "")
        ctx["path"] = path
        ctx["keep"] = {k: query[k] for k in ("tab", "date", "sport") if k in query}
        ctx["nav"] = {"/": "home", "/mine": "mine", "/sports": "sports"}.get(path, "days")
        if path == "/sports":
            from melbcup import sports_hub

            ctx["sport"] = sport = sports_hub.pick(query.get("sport"))
            ctx.update(hub_tabs=sports_hub.TABS, hub_sports=sports_hub.SPORTS)
            ctx["hub"] = sports_hub.BY_CODE.get(sport)
            tab = sports_hub.pick_tab(sport, query.get("tab"), query.get("view"))
            ctx["sp_tab"] = tab
            ctx["sp_tabs"] = sports_hub.SPORT_TABS
            ctx["hub_bar"] = bool(tab)
            view = sports_hub.pick_view(sport, query.get("view"))
            if tab == "all":
                view = view or "markets"  # every market; Players is a link at its top
            ctx["view"] = view
            if view:  # Best multis' All tab is every sport's markets
                ctx["cat"] = catalogue_view.query("all" if sport == "home" else sport, view, query)
            ctx["cov_by_sport"] = catalogue_view.coverage() if sport == "all" else {}
            if sport in ("nba", "nfl") and not view:  # the NBA page's own tab names
                query = {**query, "tab": {"multis": "stacks", "sgm": "same"}.get(tab, tab)}
            if sport == "home" or (sport not in ("nba", "racing", "all") and not view):
                from melbcup import discover

                disc = discover.latest()
                ctx["disc"] = disc
                bands = (
                    (disc or {}).get("bands")
                    if sport == "home"
                    else ((disc or {}).get("by_sport") or {}).get(sport)
                )
                ctx["bn"] = discover.layout(bands)
                ctx["bonus"] = self._bonus_credits() if sport == "home" else []
                ctx["games"] = []
                if tab == "games" and sport == "home":  # the next games across every sport
                    ctx["games"] = _home_games(discover, catalogue_view)
                elif tab == "games":
                    ctx["games"] = discover.next_games(sport)
                # the record form's game list: names from the small per-sport indexes only, never
                # the big shards (owner 2026-11-08: /sports took 4.6 s reading every sport's shards)
                ctx["rec_games"] = discover.upcoming_names(
                    list(catalogue_view.coverage()) if sport == "home" else [sport],
                    per_sport=3 if sport == "home" else 12,
                )
                ctx["no_feed"] = (
                    catalogue_view.NO_FEED
                    if sport != "home" and not catalogue_view.coverage_line(sport)
                    else ""
                )
                if tab == "challenge" and sport != "nfl":  # NFL: the NBA page's challenge (owner, 2026-11-08)
                    ctx.update(self._sport_challenge(query, ctx, sport, disc))
                ctx["sgm"] = []
                if tab == "sgm" and sport == "nfl":  # one-game multis: pk1 legs, one per player
                    from melbcup import nfl_legs

                    legs_ = nfl_legs.current_legs()
                    for x_ in (2.0, 3.0, 5.0):
                        ctx["sgm"] += nfl_legs.same_game(legs_, x_)[:2]
            if sport not in ("nba", "nfl") or view:
                ctx["track"] = self._track(ctx)
                ctx["own_live"] = self._own_live(ctx)
                ctx["own_cards"] = own_cards(ctx.get("nba_own"), ctx.get("track"))
                return self.env.get_template("asynym/sports.html").render(ctx)
            path = "/nba"  # the NBA content below, rendered inside the hub
            ctx["path"] = "/sports"
        if path == "/nba":
            self._agencies_on = set(ctx["az"].codes_on) if ctx.get("az") else set()
            self._agency_left = {a.code: a.left for a in ctx["az"].on} if ctx.get("az") else {}
            t0 = time.perf_counter()
            self._us_on = (query.get("us") or ctx.get("nba_us_cookie")) == "1"
            ctx.update(self._nba_view(query, "nfl" if ctx.get("sport") == "nfl" else "nba"))
            ctx["chs"], ctx["ch_state"] = _scope_chs(
                ctx.get("chs"),
                ctx.get("ch_state"),
                "nfl" if ctx.get("sport") == "nfl" else "nba",
                query.get("chid"),
            )
            ctx["nba_us_on"] = self._us_on
            ctx["nba_us_ready"] = bool(os.environ.get("ODDS_API_KEY"))
            self.timing["nba"] = time.perf_counter() - t0
            if ctx["nba_tab"] == "challenge":  # the challenge lives on its own tab only (owner)
                t0 = time.perf_counter()
                ctx.update(self._challenge(query, ctx))
                ctx["ch_tl"] = self._stage_timeline(ctx.get("ch"), ctx.get("ch_x"))
                if ((ctx.get("chs") or {}).get("open") or {}).get("scope") == "all":
                    from melbcup import discover

                    ctx["ch_sug"] = self._stage_pick(
                        discover.latest(), None, ctx.get("ch_x"), (ctx.get("ch") or {}).get("legs")
                    )
                self.timing["challenge"] = time.perf_counter() - t0
            ctx["track"] = self._track(ctx)
            ctx["own_live"] = self._own_live(ctx)
            ctx["own_cards"] = own_cards(ctx.get("nba_own"), ctx.get("track"))
            ctx["chcard"] = self._chcard(ctx)
            return self.env.get_template("asynym/sports.html").render(ctx)
        if path == "/":
            ctx.update(self._meetings(ctx, {}))
            ctx["takes"] = asynym.home_takes(day, race_call, snap.race_date) if day else []
            return self.env.get_template("asynym/home.html").render(ctx)
        if path == "/meetings":
            ctx.update(self._meetings(ctx, query))
            today = ctx["today"]
            dates = {today, today + timedelta(days=1), ctx["pick"]}
            dates |= {d for _label, d in CARNIVAL if d >= today}
            ctx["chips"] = sorted(dates)
            ctx["carnival_names"] = {d: label for label, d in CARNIVAL}
            return self.env.get_template("asynym/meetings.html").render(ctx)
        if path == "/meeting":
            ctx["rows"] = asynym.race_rows(day, race_call, snap.race_date) if day else []
            ctx["lk"] = likely_view(self.board, day)
            return self.env.get_template("asynym/meeting.html").render(ctx)
        if path == "/mine":
            ctx["mine_lines"] = self._my_lines(day)
            ctx["race_objs"] = (
                {rp.model.race.number: rp.model.race for rp in ctx["picks"].races}
                if ctx["picks"]
                else {}
            )
            ctx["kids_all"] = [k for _n, ks in sorted(ctx["kids"].items()) for k in ks]
            ctx["editing"] = query.get("edit") == "1"
            return self.env.get_template("asynym/mine.html").render(ctx)
        if path.startswith("/race/"):
            self._race_context(path, ctx)
            ctx["tab"] = asynym.race_tab(query.get("tab"), ctx["rc"].open)
            if ctx["tab"] in ("likely", "multis"):
                ctx["lk"] = likely_view(self.board, day, ctx["race"].number)
            takes = asynym.takes(ctx["rc"], snap.race_date) if ctx["rc"].open else []
            ctx["verdict_take"] = bool(takes) and race_call(ctx["rp"]).kind == "bet"
            ctx["takes"] = takes if ctx["verdict_take"] else []
            ctx["elsewhere"] = (
                None
                if ctx["verdict_take"]
                else asynym.best_elsewhere(day, ctx["race"].number, race_call, snap.race_date)
            )
            ctx["top_picks"] = asynym.top_picks(ctx["rc"]) if ctx["rc"].open else []
            ctx["multi"] = asynym.race_multi(day, ctx["race"].number) if ctx["rc"].open else None
            ctx["rows"] = asynym.race_rows(day, race_call, snap.race_date)
            ctx["race_extras"] = [
                x
                for x in ctx["extras"]
                if x.bet.kind == "multi" and any(leg[0] == ctx["race"].number for leg in x.bet.legs)
            ]
            ctx["my_lines"] = self._my_lines(day, ctx["race"].number)
            return self.env.get_template("asynym/race.html").render(ctx)
        raise NotFound(path)

    @staticmethod
    def _my_lines(day, race: int | None = None) -> list:
        """The owner's recorded bets (a race's, or the day's), as card lines."""
        if day is None:
            return []
        lines = [x for rc in day.races for x in rc.board + rc.exotics if x.placed]
        lines += [m for m in day.multis if m.placed]
        return [x for x in lines if race is None or x.race == race]

    def _race_context(self, path: str, ctx: dict) -> None:
        """The race page's own pieces (raises NotFound): shared by the old and new pages."""
        try:
            number = int(path.removeprefix("/race/"))
        except ValueError as exc:
            raise NotFound(path) from exc
        rp = (
            next((r for r in ctx["picks"].races if r.model.race.number == number), None)
            if ctx["picks"]
            else None
        )
        if rp is None:
            raise NotFound(f"Race {number} is not on the card yet")
        ctx["rp"] = rp
        ctx["race"] = rp.model.race
        ctx["rc"] = ctx["day"].race(number)
        ctx["check"] = ctx["checks"].get(number)

    def action(self, name: str, query: Mapping[str, str]) -> str:
        """Do what a button asks; return the path to show next."""
        board = self.board
        back = query.get("next", "/")
        if not back.startswith("/") or back.startswith("//"):
            back = "/"
        if name == "prices":
            board.refresh_prices_now()
        elif name == "results":
            board.fetch_results_now()
        elif name == "load":
            board.load_card_now(wait=self.browser)
        elif name == "auto":
            board.set_auto(query.get("on") == "1")
        elif name == "find":
            pick = _date(query.get("date"))
            if pick is None:
                return "/meetings"
            board.find_meetings(pick)
            return f"/meetings?date={pick.isoformat()}"
        elif name == "meeting":
            pick = _date(query.get("date"))
            ok = pick is not None and board.set_meeting(pick, query.get("venue", ""))
            if self.settings.asynym:  # on to the meeting's races
                return "/meeting" if ok else "/meetings"
            return "/" if ok else "/meetings"
        else:
            raise NotFound(name)
        return back



def _timed(name):
    """Add a method's run time to the page's timing comment (see Views.page)."""
    import functools

    def wrap(fn):
        @functools.wraps(fn)
        def inner(self, *a, **k):
            t = time.perf_counter()
            try:
                return fn(self, *a, **k)
            finally:
                tt = self.__dict__.setdefault("_tt", {})
                tt[name] = tt.get(name, 0.0) + time.perf_counter() - t
        return inner
    return wrap


for _n in ("_context", "_nba_view", "_challenge", "_best_elsewhere", "_stage_preview", "_sport_challenge", "_bonus_credits"):
    if hasattr(Views, _n):
        setattr(Views, _n, _timed(_n.strip("_"))(getattr(Views, _n)))
