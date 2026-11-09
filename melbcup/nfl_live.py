"""NFL pieces of the live tracker (nba_live.track routes here by sport): leg labels, ESPN's NFL box
score, the 60 minute game clock. Same shapes as the NBA's so the challenge UI and live_chance work
unchanged. ESPN: site.api.espn.com/apis/site/v2/sports/football/nfl (scoreboard, summary?event=)."""

from __future__ import annotations

import re

API = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
GAME_SECS = 60 * 60
NICKNAMES = frozenset(
    "cardinals falcons ravens bills panthers bears bengals browns cowboys broncos lions packers "
    "texans colts jaguars chiefs raiders chargers rams dolphins vikings patriots saints giants "
    "jets eagles steelers ers seahawks buccaneers titans commanders".split()
)
LEG = re.compile(
    r"^(?P<who>.+?) (?:(?P<any>Anytime Touchdown)|(?:(?P<k>\d+)\+ |(?P<side>Over|Under) "
    r"(?P<line>\d+(?:\.\d+)?) )(?P<what>.+))$",
    re.I,
)
YARDS = ("passingYards", "rushingYards", "receivingYards", "scrimmageYards")


def norm(name: str) -> str:
    n = re.sub(r"[^a-z ]", "", (name or "").lower().replace("-", " "))
    return " ".join(w for w in n.split() if w not in ("jr", "sr", "ii", "iii", "iv"))


def stat_of(what: str) -> str | None:
    w = (what or "").lower()
    for pat, stat in (
        (r"rush\w*\s*\+\s*rec", "scrimmageYards"),
        (r"pass\w* y", "passingYards"),
        (r"rush\w* y", "rushingYards"),
        (r"rec\w* y", "receivingYards"),
        (r"reception", "receptions"),
        (r"pass\w* (td|touchdown)", "passingTouchdowns"),
        (r"rush\w* (td|touchdown)", "rushingTouchdowns"),
        (r"rec\w* (td|touchdown)", "receivingTouchdowns"),
        (r"touchdown|\btds?\b", "touchdowns"),
        (r"completion", "completions"),
        (r"interception", "interceptions"),
    ):
        if re.search(pat, w):
            return stat
    return None


def parse(label: str) -> tuple[str, list[dict]]:
    """('Away @ Home', [{player, stat, k, under, label}]) from a bet's label. Over 245.5 is 246+
    (yards compare on the integer, like the NBA's counts); Under 245.5 is 245 or fewer."""
    game, sep, rest = (label or "").partition(": ")
    if not sep:
        game, rest = "", label or ""
    legs = []
    for part in rest.split(", "):
        gl = gl_parse(part)
        if gl:
            legs.append(gl | {"player": "", "stat": gl["gl"], "k": 0, "under": gl.get("under", False)})
            continue
        m = LEG.match(part.strip())
        if not m:
            continue
        if m["any"]:
            stat, k, under = "touchdowns", 1, False
        else:
            stat = stat_of(m["what"])
            if not stat:
                continue
            if m["k"]:
                k, under = int(m["k"]), False
            else:
                k, under = int(float(m["line"])) + 1, m["side"].lower() == "under"
        legs.append({"player": m["who"], "stat": stat, "k": k, "under": under, "label": part.strip()})
    return game, legs


GL_TOTAL = re.compile(r"^(Over|Under) (\d+(?:\.\d+)?) Total Points$", re.I)
GL_WIN = re.compile(r"^(.+?) to win$", re.I)
GL_SPREAD = re.compile(r"^(.+?) ([+-]\d+(?:\.\d+)?)$")


def gl_parse(part: str) -> dict | None:
    """A game-line leg from its label ("Kansas City Chiefs to win", "Buffalo Bills -3.5",
    "Over 44.5 Total Points"), or None. A player prop never matches these shapes."""
    part = part.strip()
    if m := GL_TOTAL.match(part):
        return {"gl": "total", "under": m[1].lower() == "under", "line": float(m[2]), "label": part}
    if m := GL_WIN.match(part):
        return {"gl": "win", "team": m[1], "label": part}
    if (m := GL_SPREAD.match(part)) and not LEG.match(part):
        return {"gl": "spread", "team": m[1], "line": float(m[2]), "label": part}
    return None


def scores(comp: dict) -> dict | None:
    """{"home": (name, pts), "away": (name, pts)} from an ESPN competition, or None."""
    out = {}
    try:
        for c in comp.get("competitors") or []:
            out[c["homeAway"]] = (c.get("team", {}).get("displayName", ""), int(c["score"]))
    except (KeyError, TypeError, ValueError):
        return None
    return out if len(out) == 2 else None


def gl_eval(leg: dict, sc: dict, final: bool) -> tuple[float | None, bool | None, bool]:
    """(now, ok, push) for a game-line leg against the score. ok is None while undecided (win and
    spread are decided at full time only; an over is won / an under lost as soon as passed).
    Unknown team: (None, None, False). push: a void (money back), reported as ok None."""
    a, h = sc["away"][1], sc["home"][1]
    if leg["gl"] == "total":
        t = a + h
        if t > leg["line"]:
            return t, not leg["under"], False
        if not final:
            return t, None, False
        return t, (bool(leg["under"]) if t < leg["line"] else None), t == leg["line"]
    want = norm(leg.get("team") or "").split()[-1:]
    side = next((k for k in ("away", "home") if want and want[0] in norm(sc[k][0]).split()), None)
    if side is None:
        return None, None, False
    mine, theirs = (a, h) if side == "away" else (h, a)
    now = mine - theirs
    if not final:
        return now, None, False
    adj = now + (leg["line"] if leg["gl"] == "spread" else 0)
    return now, (adj > 0 if adj else None), adj == 0


def is_nfl(label: str) -> bool:
    """An NFL bet: its game names an NFL team, or a leg is an NFL stat. NBA labels never match."""
    game, legs = parse(label)
    if game:
        return bool(set(norm(game).split()) & NICKNAMES)
    return bool(legs)


def _cell(row: list, idx: dict, key: str) -> int | None:
    try:
        v = str(row[idx[key]]).split("/")[0].replace(",", "")
        return int(v) if v.lstrip("-").isdigit() else None
    except (KeyError, IndexError):
        return None


def box(summary: dict) -> dict:
    """{normalised player: {stat: count}} from ESPN's NFL box score (passing, rushing, receiving).
    A player in the box has every stat, zero where he has no line; one absent from it did not
    record anything (a void at the bookmaker if he never took the field)."""
    out: dict = {}
    for team in summary.get("boxscore", {}).get("players", []):
        for block in team.get("statistics", []):
            cat = str(block.get("name") or "").lower()
            idx = {k: i for i, k in enumerate(block.get("labels") or block.get("names") or [])}
            want = {
                "passing": {"YDS": "passingYards", "TD": "passingTouchdowns", "INT": "interceptions", "C/ATT": "completions"},
                "rushing": {"YDS": "rushingYards", "TD": "rushingTouchdowns"},
                "receiving": {"REC": "receptions", "YDS": "receivingYards", "TD": "receivingTouchdowns"},
            }.get(cat)
            if not want:
                continue
            for a in block.get("athletes", []):
                st = a.get("stats") or []
                row = out.setdefault(norm(a.get("athlete", {}).get("displayName", "")), {})
                if a.get("athlete", {}).get("id") is not None:
                    row["_id"] = str(a["athlete"]["id"])
                for key, stat in want.items():
                    v = _cell(st, idx, key)
                    if v is not None:
                        row[stat] = v
    for row in out.values():
        for stat in (*YARDS, "receptions", "passingTouchdowns", "rushingTouchdowns",
                     "receivingTouchdowns", "completions", "interceptions"):
            row.setdefault(stat, 0)
        row["scrimmageYards"] = row["rushingYards"] + row["receivingYards"]
        row["touchdowns"] = row["rushingTouchdowns"] + row["receivingTouchdowns"]
    return out


def frac_left(state: str, period: int | None, clock_s: float | None) -> float:
    """Share of a 60 minute game left: quarters of 15 minutes, overtime 10 (sudden death: left
    counted as the period's clock at most)."""
    if state == "pre":
        return 1.0
    if state == "post" or not period:
        return 0.0 if state == "post" else 1.0
    clock_s = max(clock_s or 0.0, 0.0)
    if period <= 4:
        return min(1.0, (clock_s + (4 - period) * 900) / GAME_SECS)
    return min(clock_s, 600.0) / GAME_SECS
