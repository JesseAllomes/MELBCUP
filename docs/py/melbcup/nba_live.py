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

API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
UA = "Mozilla/5.0 (compatible; asynymbet)"
TTL_S = 60
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


def _event(game: str, now: datetime, fetch=None) -> str | None:
    want = set(norm(game.replace(" @ ", " ").replace(" at ", " ")).split())
    us = now - timedelta(hours=5)
    for day in (us, us - timedelta(days=1)):
        for e in _get(f"{API}/scoreboard?dates={day:%Y%m%d}", fetch).get("events", []):
            have = set(norm(e.get("name", "").replace(" at ", " ")).split())
            if want and want <= have:
                return e["id"]
    return None


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
    cannot be found. A leg is won as soon as an over reaches its line, failed as soon as an under
    passes it; otherwise it is decided at full time. Verdict at full time: won, lost1 (exactly one
    leg failed: a 'money back if one leg fails' bet), lost."""
    game, legs = parse(label)
    if not game or not legs:
        return None
    now = now or datetime.now(UTC)
    try:
        eid = _event(game, now, fetch)
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
    return {
        "state": state,
        "clock": status.get("type", {}).get("shortDetail", ""),
        "legs": out,
        "failed": failed,
        "verdict": verdict,
    }
