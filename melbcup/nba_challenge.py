"""The $10 -> $1000 challenge on the NBA page (owner, 2026-11-04).

Start with a stake, roll the whole bank into the next multi each stage, stop at the goal or the
first loss. A stage is one game (a same-game multi: the owner's way, so a night can hold several
stages, early game into later game) or, if chosen, one leg per game across the night. The next
stage aims for about STEP_X times the bank (less near the goal) with the app's likeliest stack.
The state lives in one cookie on the phone, like the agencies and amounts. Every action carries
the stage number it was made on, so reloading a page never counts a win or a loss twice.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

COOKIE = "nba_challenge"
STEP_X = 5.0
MIN_X = 2.0
MAX_HISTORY = 20


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


MODES = ("game", "multi")  # one game per stage (a same-game multi), or one leg per game


def fresh(
    start: float = 10.0, goal: float = 1000.0, past: list | None = None, mode: str = "game"
) -> dict:
    return {
        "start": start,
        "goal": goal,
        "bank": start,
        "steps": [],
        "past": past or [],
        "mode": mode,
    }


def apply(state: dict | None, query: Mapping[str, str]) -> dict | None:
    """The state after the action in `query` (?ch=start|won|lost|reset), or unchanged."""
    act = query.get("ch")
    if act == "start" or (act and state is None):
        start = _money(query.get("chstart")) or 10.0
        goal = _money(query.get("chgoal")) or 1000.0
        mode = query.get("chmode") if query.get("chmode") in MODES else "game"
        return fresh(start, max(goal, start * MIN_X), (state or {}).get("past", []), mode)
    if state is None or act not in ("won", "lost", "reset"):
        return state
    if query.get("chs") != str(len(state["steps"])):
        return state  # a reload of an action already counted
    past = state.get("past", [])
    mode = state.get("mode", "game")
    if act == "reset":
        return fresh(state["start"], state["goal"], past, mode)
    if act == "lost":
        past = (past + [{"steps": len(state["steps"]), "best": state["bank"], "made_it": False}])[
            -MAX_HISTORY:
        ]
        return fresh(state["start"], state["goal"], past, mode)
    returned = _money(query.get("chr"))
    if returned is None or returned <= state["bank"]:
        return state
    steps = state["steps"] + [{"from": state["bank"], "to": returned}]
    if returned >= state["goal"]:
        past = (past + [{"steps": len(steps), "best": returned, "made_it": True}])[-MAX_HISTORY:]
        return fresh(state["start"], state["goal"], past, mode) | {"last_win": returned}
    return state | {"bank": returned, "steps": steps}


def next_x(state: dict) -> float:
    """The payout multiple to aim for on the next step: ~5x, or just what is left to the goal."""
    left = state["goal"] / state["bank"]
    return max(MIN_X, min(STEP_X, left))
