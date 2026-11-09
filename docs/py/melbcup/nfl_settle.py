"""Settle an NFL leg the way the NBA's are (tools/nba/settle.settle_one): against its own ESPN game,
found by teams on the US date of its start, only once that game is final, by athlete id and box
score. A player who never appears in the box score is a void (did not play)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from . import nba_live, nfl_live

NY = ZoneInfo("America/New_York")
UNRESOLVED_AFTER_H = 12


def settle_leg(g: dict, now: datetime | None = None, fetch=None) -> dict:
    """g: a logged leg {game, startsAt, player, stat, line (k: N or more), under}. Returns g with
    result won|lost|void|pending|unresolved, actual, espn_event, espn_athlete."""
    now = now or datetime.now(UTC)
    if not (g.get("startsAt") and g.get("game")):
        return g | {"result": "unresolved", "actual": None, "why": "no game or start time"}
    start = datetime.fromisoformat(str(g["startsAt"]).replace("Z", "+00:00"))
    if start > now:
        return g | {"result": "pending", "actual": None, "why": "not started"}
    day = start.astimezone(NY).strftime("%Y%m%d")
    try:
        eid = nba_live._event(g["game"].replace(" @ ", " "), now, fetch, day, nfl_live.API)
        summary = nba_live._get(f"{nfl_live.API}/summary?event={eid}", fetch) if eid else None
    except (OSError, ValueError, KeyError):
        return g | {"result": "pending", "actual": None, "why": "ESPN unreachable"}
    if eid is None or summary is None:
        late = now - start > timedelta(hours=UNRESOLVED_AFTER_H)
        return g | {"result": "unresolved" if late else "pending", "actual": None,
                    "why": "no matching ESPN game"}
    comp = (summary.get("header", {}).get("competitions") or [{}])[0]
    if comp.get("status", {}).get("type", {}).get("state") != "post":
        return g | {"result": "pending", "actual": None, "why": "not final", "espn_event": eid}
    row = nfl_live.box(summary).get(nfl_live.norm(g["player"]))
    if row is None:
        return g | {"result": "void", "actual": None, "why": "did not play", "espn_event": eid}
    v = row.get(g["stat"], 0)
    over = v >= g["line"]
    res = "won" if over != bool(g.get("under")) else "lost"
    pid = row.get("_id")
    return g | {"result": res, "actual": v, "espn_event": eid, "espn_athlete": pid,
                "participant_id": pid}
