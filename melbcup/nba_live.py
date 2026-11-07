"""Leg-by-leg results for the owner's NBA bets, live and final (owner, 2026-11-05).

A bet keeps its legs as the label the page showed ("Atlanta Hawks @ Washington Wizards: Trae Young
8+ Assists, Aaron Wiggins Over 3.5 Rebounds"). The game is found on ESPN's scoreboard, its box score
read (kept a minute), and each leg's stat set against its line: won, failed or still going.
"""

from __future__ import annotations

import json
import math
import re
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
UA = "Mozilla/5.0 (compatible; asynymbet)"
TTL_S = 60
NY = ZoneInfo("America/New_York")  # only to derive the NBA's US game date
MELB = ZoneInfo("Australia/Melbourne")  # every time the owner sees
_CACHE: dict[str, tuple[float, dict]] = {}

LEG = re.compile(
    r"^(?P<who>.+?) (?:(?P<k>\d+)\+ |(?P<side>Over|Under) (?P<line>\d+(?:\.\d+)?) )(?P<what>.+)$",
    re.I,
)
FIELDS = {"PTS": "points", "REB": "reboundsTotal", "AST": "assists"}


def _get(url: str, fetch=None) -> dict:
    hit = _CACHE.get(url)
    if hit and time.monotonic() - hit[0] < TTL_S:
        return hit[1]
    if fetch is not None:
        data = fetch(url)
    else:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
    _CACHE[url] = (time.monotonic(), data)
    return data


def norm(name: str) -> str:
    n = re.sub(r"[^a-z ]", "", (name or "").lower().replace("-", " "))
    return " ".join(w for w in n.split() if w not in ("jr", "sr", "ii", "iii", "iv"))


def stat_of(what: str) -> str | None:
    w = what.lower()
    for word, stat in (
        ("three", "threePointersMade"),
        ("point", "points"),
        ("rebound", "reboundsTotal"),
        ("assist", "assists"),
    ):
        if word in w:
            return stat
    return None


def parse(label: str) -> tuple[str, list[dict]]:
    """('Away @ Home', [{player, stat, k, under, label}]) from a bet's label."""
    game, sep, rest = (label or "").partition(": ")
    if not sep:
        game, rest = "", label or ""
    legs = []
    for part in rest.split(", "):
        m = LEG.match(part.strip())
        if not m or not stat_of(m["what"]):
            continue
        if m["k"]:
            k, under = int(m["k"]), False
        else:
            k, under = math.floor(float(m["line"])) + 1, m["side"].lower() == "under"
        legs.append(
            {
                "player": m["who"],
                "stat": stat_of(m["what"]),
                "k": k,
                "under": under,
                "label": part.strip(),
            }
        )
    return game, legs


DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b|\b(\d{4})(\d{2})(\d{2})\b")


def label_day(label: str) -> str | None:
    """The US date (YYYYMMDD) written in a bet's label, if it has one."""
    m = DATE.search(label or "")
    if not m:
        return None
    return "".join(g for g in m.groups() if g)


def _event(game: str, now: datetime, fetch=None, day: str | None = None) -> str | None:
    """The one ESPN game with these teams: on the bet's own date when it has one, else today or
    yesterday (US). Zero or several matches: None, never a guess."""
    want = set(norm(game.replace(" @ ", " ").replace(" at ", " ")).split())
    if not want:
        return None
    us = now.astimezone(NY)  # the US (New York, DST-correct) date
    days = [day] if day else [f"{d:%Y%m%d}" for d in (us, us - timedelta(days=1))]
    hits = []
    for d in days:
        for e in _get(f"{API}/scoreboard?dates={d}", fetch).get("events", []):
            have = set(norm(e.get("name", "").replace(" at ", " ")).split())
            if want <= have and e["id"] not in hits:
                hits.append(e["id"])
    return hits[0] if len(hits) == 1 else None


def _box(summary: dict) -> dict:
    out = {}
    for team in summary.get("boxscore", {}).get("players", []):
        for block in team.get("statistics", []):
            idx = {k: i for i, k in enumerate(block.get("labels") or block.get("names") or [])}
            for a in block.get("athletes", []):
                st = a.get("stats") or []
                if not st or "PTS" not in idx:
                    continue
                row = {
                    f: int(st[idx[k]] or 0)
                    for k, f in FIELDS.items()
                    if k in idx and str(st[idx[k]]).isdigit()
                }
                if "3PT" in idx:
                    row["threePointersMade"] = int(str(st[idx["3PT"]]).split("-")[0] or 0)
                out[norm(a.get("athlete", {}).get("displayName", ""))] = row
    return out


def track(label: str, now: datetime | None = None, fetch=None) -> dict | None:
    """{"state": pre|in|post, "clock", "legs": [...], "failed", "verdict"} or None if the game
    cannot be found (or is not exactly one game: on the bet's own date if its label has one, else
    today or yesterday). A leg is won as soon as an over reaches its line, failed as soon as an
    under passes it; otherwise it is decided at full time. The bet's verdict only at full time
    ("post"): won, lost1 (exactly one leg failed: a 'money back if one leg fails' bet), lost."""
    game, legs = parse(label)
    day = label_day(label)
    game = DATE.sub("", game).strip(" ,-()") if day else game
    if not game or not legs:
        return None
    now = now or datetime.now(UTC)
    try:
        eid = _event(game, now, fetch, day)
        if eid is None:
            return None
        summary = _get(f"{API}/summary?event={eid}", fetch)
    except (OSError, ValueError, KeyError):
        return None
    status = (summary.get("header", {}).get("competitions") or [{}])[0].get("status", {})
    state = status.get("type", {}).get("state", "pre")
    box = _box(summary)
    out, failed = [], 0
    for g in legs:
        v = (box.get(norm(g["player"])) or {}).get(g["stat"])
        if v is None:
            ok = False if state == "post" else None  # did not play: a void at the bookmaker
        elif g["under"]:
            ok = False if v >= g["k"] else (True if state == "post" else None)
        else:
            ok = True if v >= g["k"] else (False if state == "post" else None)
        failed += ok is False
        out.append(g | {"now": v, "ok": ok})
    verdict = None
    if state == "post":
        verdict = "won" if failed == 0 else ("lost1" if failed == 1 else "lost")
    comp = (summary.get("header", {}).get("competitions") or [{}])[0]
    starts = str(comp.get("date") or "")
    clock = status.get("type", {}).get("shortDetail", "")
    if state == "pre":  # ESPN's pre-game text is US time: show the tip-off in Melbourne time
        try:
            tip = datetime.fromisoformat(starts.replace("Z", "+00:00")).astimezone(MELB)
            clock = f"Tip-off {tip:%a %-d %b %-I:%M %p} {tip.tzname()}"
        except ValueError:
            clock = ""
    return {
        "state": state,
        "starts_at": starts,  # UTC ISO as ESPN gives it
        "clock": clock,
        "legs": out,
        "failed": failed,
        "verdict": verdict,
    }
