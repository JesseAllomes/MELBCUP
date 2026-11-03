# ruff: noqa: E501
"""The $10 -> $1000 challenge on the NBA page (owner, 2026-11-04).

Start with a stake, roll the bank into the next multi each stage, stop at the goal or the first
loss. A stage is one game (a same-game multi: the owner's way, so a night can hold several stages,
early game into later game) or, if chosen, one leg per game across the night. The owner picks how
many stages (2-8); each stage aims for an even share of what is left to the goal, with the app's
likeliest stack for that payout ($10 -> $1000 in 3 stages, start kept: 5x each).

Money: a stage is first marked as placed at one agency, which takes the stake off that agency's
balance; its result then pays back into it (a win returns what it paid, a loss nothing). With
"keep" on, the first win gives the starting stake back to the pool and only the rest rolls on.

The state lives in one cookie on the phone, like the agencies and amounts. Every action carries the
stage number it was made on, so reloading a page never counts anything twice.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

COOKIE = "nba_challenge"
MIN_X = 1.2
STAGES = (2, 3, 4, 5, 6, 7, 8)
DEFAULT_STAGES = 3
PER_NIGHT = (1, 2)  # stages a night: 1 (one a game day) or 2 (an early game, then a later one)
GAP = timedelta(hours=3)  # tip to tip on one night: ~2.5 h of game, ~30 min to settle and place
GAME = timedelta(hours=2, minutes=30)  # a game's usual length, for "result due about"
MELBOURNE = ZoneInfo("Australia/Melbourne")
MAX_HISTORY = 20
MAX_BETS = 40
MODES = ("game", "multi")  # one game per stage (a same-game multi), or one leg per game


def parse(raw: str | None) -> dict | None:
    try:
        s = json.loads(raw) if raw else None
    except ValueError:
        return None
    if not isinstance(s, dict) or not all(k in s for k in ("start", "goal", "bank", "steps")):
        return None
    return s


def dump(state: dict | None) -> str | None:
    return None if state is None else json.dumps(state, separators=(",", ":"))


def _money(text: str | None) -> float | None:
    try:
        v = round(float(str(text).replace("$", "").replace(",", "")), 2)
    except (TypeError, ValueError):
        return None
    return v if 0 < v < 1_000_000 else None


def fresh(start=10.0, goal=1000.0, past=None, mode="game", keep=True, bets=None, stages=DEFAULT_STAGES, per_night=1) -> dict:
    return {"start": start, "goal": goal, "bank": start, "steps": [], "past": past or [], "mode": mode,
            "keep": keep, "kept": 0.0, "placed": None, "bets": bets or [], "stages": stages, "per_night": per_night}


def _again(state: dict, **extra) -> dict:
    """A new run with the same settings, history and bet log."""
    return fresh(state["start"], state["goal"], state.get("past", []), state.get("mode", "game"),
                 state.get("keep", True), state.get("bets", []), state.get("stages", DEFAULT_STAGES),
                 state.get("per_night", 1)) | extra


def _settle(state: dict, result: str, returned: float = 0.0) -> list:
    bets = [dict(b) for b in state.get("bets", [])]
    placed = state.get("placed")
    for b in bets:
        if placed and b.get("id") == placed.get("id"):
            b["state"], b["ret"] = result, returned
    return bets


def apply(state: dict | None, query: Mapping[str, str], today: str = "") -> dict | None:
    """The state after the action in `query` (?ch=start|place|won|lost|reset), or unchanged.
    `today` (Melbourne date, ISO) stamps a placed bet for the day's money."""
    act = query.get("ch")
    if act == "start" or (act and state is None):
        start = _money(query.get("chstart")) or 10.0
        goal = _money(query.get("chgoal")) or 1000.0
        mode = query.get("chmode") if query.get("chmode") in MODES else "game"
        keep = query.get("chkeep", "1") == "1"
        try:
            stages = int(query.get("chn") or DEFAULT_STAGES)
        except ValueError:
            stages = DEFAULT_STAGES
        stages = stages if stages in STAGES else DEFAULT_STAGES
        per_night = 2 if query.get("chpn") == "2" else 1
        old = state or {}
        if old.get("placed"):
            return state  # a placed stage settles first
        return fresh(start, max(goal, start * 2), old.get("past", []), mode, keep, old.get("bets", []), stages, per_night)
    if state is None or act not in ("place", "won", "lost", "reset"):
        return state
    if query.get("chs") != str(len(state["steps"])):
        return state  # a reload of an action already counted
    if act == "reset":
        return state if state.get("placed") else _again(state)  # a placed stage settles first
    if act == "place":
        if state.get("placed"):
            return state
        bet = {"id": max([b.get("id", 0) for b in state.get("bets", [])], default=0) + 1, "day": today,
               "ag": query.get("chag") or "sb", "stake": state["bank"], "price": _money(query.get("chp")),
               "label": (query.get("chl") or "")[:120], "state": "placed", "ret": 0.0,
               "tip": (query.get("chtip") or "")[:32]}
        return state | {"placed": bet, "bets": (state.get("bets", []) + [bet])[-MAX_BETS:]}
    if not state.get("placed"):
        return state  # mark the stage as placed first
    if act == "lost":
        past = (state.get("past", []) + [{"steps": len(state["steps"]), "best": state["bank"], "made_it": False}])[-MAX_HISTORY:]
        return _again(state | {"bets": _settle(state, "lost"), "past": past})
    returned = _money(query.get("chr"))
    if returned is None or returned <= state["placed"]["stake"]:
        return state
    bets = _settle(state, "won", returned)
    steps = state["steps"] + [{"from": state["bank"], "to": returned, "tip": state["placed"].get("tip", "")}]
    kept, bank = state.get("kept", 0.0), returned
    if state.get("keep", True) and not state["steps"]:  # first win: the starting stake goes back
        kept, bank = state["start"], round(returned - state["start"], 2)
    if bank >= state["goal"]:
        past = (state.get("past", []) + [{"steps": len(steps), "best": returned, "made_it": True}])[-MAX_HISTORY:]
        return _again(state | {"bets": bets, "past": past}, last_win=returned)
    return state | {"bank": bank, "steps": steps, "kept": kept, "placed": None, "bets": bets}


def today_money(state: dict | None, today: str) -> tuple[dict[str, float], float]:
    """Today's NBA money by agency: ({agency: stakes out minus returns}, profit of settled bets)."""
    used: dict[str, float] = {}
    profit = 0.0
    for b in (state or {}).get("bets", []):
        if b.get("day") != today:
            continue
        used[b["ag"]] = round(used.get(b["ag"], 0.0) + b["stake"] - (b.get("ret") or 0.0), 2)
        if b["state"] == "won":
            profit += b["ret"] - b["stake"]
        elif b["state"] == "lost":
            profit -= b["stake"]
    return used, round(profit, 2)


def _when(iso: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")) if iso else None
    except ValueError:
        return None


def night(when: datetime) -> str:
    """A game's night: its Melbourne date (NBA games tip off in the Melbourne morning)."""
    return when.astimezone(MELBOURNE).date().isoformat()


def next_window(state: dict) -> tuple[datetime | None, str | None]:
    """When the next stage's game may tip off: (no earlier than, and not on this night).
    Two a night: the second game tips at least GAP after the first. Once a night's stages are
    used, the next stage waits for a later night. Nothing played yet: no limit."""
    tips = [_when(s.get("tip")) for s in state["steps"]]
    tips = [t for t in tips if t]
    if not tips:
        return None, None
    last = tips[-1]
    same_night = sum(1 for t in tips if night(t) == night(last))
    if state.get("mode", "game") == "game" and same_night < state.get("per_night", 1):
        return last + GAP, None
    return last + GAP, night(last)


def allowed(state: dict, tip_iso: str | None) -> bool:
    """May a game tipping at `tip_iso` be this stage's game?"""
    earliest, not_night = next_window(state)
    when = _when(tip_iso)
    if when is None:
        return earliest is None
    return (earliest is None or when >= earliest) and (not_night is None or night(when) > not_night)


def result_due(state: dict) -> datetime | None:
    """About when the placed stage's game ends (tip + GAME)."""
    tip = _when((state.get("placed") or {}).get("tip"))
    return tip + GAME if tip else None


def finish_chance(stage_chance: float | None, state: dict) -> float | None:
    """The chance of winning every stage still to play, if each is about as likely as this one."""
    return None if stage_chance is None else stage_chance ** remaining(state)


def stage_x(start: float, goal: float, stages: int, keep: bool) -> float:
    """The even payout per stage that turns `start` into `goal` in `stages` wins; with keep the
    first win also hands the start back: start * (x - 1) * x ** (stages - 1) = goal."""
    if not keep:
        return (goal / start) ** (1 / stages)
    lo, hi = 1.0, goal / start + 1
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if start * (mid - 1) * mid ** (stages - 1) < goal else (lo, mid)
    return hi


def remaining(state: dict) -> int:
    return max(1, state.get("stages", DEFAULT_STAGES) - len(state["steps"]))


def next_x(state: dict) -> float:
    """The payout to aim for on the next stage: what is left to the goal spread evenly over the
    stages left (so a stage that paid more or less than planned re-balances the rest)."""
    keep_now = state.get("keep", True) and not state["steps"]
    x = stage_x(state["bank"], state["goal"], remaining(state), keep_now)
    return max(MIN_X, x)
