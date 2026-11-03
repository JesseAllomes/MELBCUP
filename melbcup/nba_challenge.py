# ruff: noqa: E501
"""The $10 -> $1000 challenge on the NBA page (owner, 2026-11-04).

Start with a stake, roll the bank into the next multi each stage, stop at the goal or the first
loss. A stage is one game (a same-game multi: the owner's way, so a night can hold several stages,
early game into later game) or, if chosen, one leg per game across the night. The next stage aims
for about STEP_X times the bank (less near the goal) with the app's likeliest stack.

Money: a stage is first marked as placed at one agency, which takes the stake off that agency's
balance; its result then pays back into it (a win returns what it paid, a loss nothing). With
"keep" on, the first win gives the starting stake back to the pool and only the rest rolls on.

The state lives in one cookie on the phone, like the agencies and amounts. Every action carries the
stage number it was made on, so reloading a page never counts anything twice.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

COOKIE = "nba_challenge"
STEP_X = 5.0
MIN_X = 2.0
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


def fresh(start=10.0, goal=1000.0, past=None, mode="game", keep=True, bets=None) -> dict:
    return {"start": start, "goal": goal, "bank": start, "steps": [], "past": past or [],
            "mode": mode, "keep": keep, "kept": 0.0, "placed": None, "bets": bets or []}


def _again(state: dict, **extra) -> dict:
    """A new run with the same settings, history and bet log."""
    return fresh(state["start"], state["goal"], state.get("past", []), state.get("mode", "game"),
                 state.get("keep", True), state.get("bets", [])) | extra


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
        old = state or {}
        if old.get("placed"):
            return state  # a placed stage settles first
        return fresh(start, max(goal, start * MIN_X), old.get("past", []), mode, keep, old.get("bets", []))
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
               "ag": query.get("chag") or "pb", "stake": state["bank"], "price": _money(query.get("chp")),
               "label": (query.get("chl") or "")[:120], "state": "placed", "ret": 0.0}
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
    steps = state["steps"] + [{"from": state["bank"], "to": returned}]
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


def next_x(state: dict) -> float:
    """The payout multiple to aim for on the next stage: ~5x, or just what is left to the goal."""
    left = state["goal"] / state["bank"]
    return max(MIN_X, min(STEP_X, left))
