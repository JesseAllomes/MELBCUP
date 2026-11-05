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
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

COOKIE = "nba_challenge"
MIN_X = 1.2
STAGES = (2, 3, 4, 5, 6, 7, 8)
DEFAULT_STAGES = 3
PER_NIGHT = (1, 2)  # stages a night: 1 (one a game day) or 2 (an early game, then a later one)
GAME = timedelta(
    hours=2, minutes=15
)  # an NBA game's usual length (owner, 2026-11-05: 2h30 was too long)
BUFFER = timedelta(hours=1)  # after the result: time to be told, mark it and place the next (owner)
GAP = GAME + BUFFER  # tip to tip for two stages on one night
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


def fresh(
    start=10.0,
    goal=1000.0,
    past=None,
    mode="game",
    keep=True,
    bets=None,
    stages=DEFAULT_STAGES,
    per_night=1,
) -> dict:
    return {
        "start": start,
        "goal": goal,
        "bank": start,
        "steps": [],
        "past": past or [],
        "mode": mode,
        "keep": keep,
        "kept": 0.0,
        "placed": None,
        "bets": bets or [],
        "stages": stages,
        "per_night": per_night,
    }


def _again(state: dict, **extra) -> dict:
    """A new run with the same settings, history and bet log."""
    return (
        fresh(
            state["start"],
            state["goal"],
            state.get("past", []),
            state.get("mode", "game"),
            state.get("keep", True),
            state.get("bets", []),
            state.get("stages", DEFAULT_STAGES),
            state.get("per_night", 1),
        )
        | extra
    )


def _settle(state: dict, result: str, returned: float = 0.0) -> list:
    bets = [dict(b) for b in state.get("bets", [])]
    placed = state.get("placed")
    for b in bets:
        if placed and b.get("id") == placed.get("id"):
            b["state"], b["ret"] = result, returned
    return bets


def apply(state: dict | None, query: Mapping[str, str], today: str = "") -> dict | None:
    """The state after the action in `query` (?ch=start|place|won|lost|reset|new), or unchanged.
    `new` ends the run (keeping the history and bet log) so a challenge can be set up afresh.
    `today` (Melbourne date, ISO) stamps a placed bet for the day's money."""
    act = query.get("ch")
    if act in ("bet", "betwon", "betlost"):  # any multi the owner placed, outside the challenge
        return _own_bet(state, act, query, today)
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
        if old.get("placed") and old.get("active", True):
            return state  # a placed stage settles first
        run = fresh(
            start,
            max(goal, start * 2),
            old.get("past", []),
            mode,
            keep,
            old.get("bets", []),
            stages,
            per_night,
        )
        return run
    if (
        state is None
        or act not in ("place", "won", "lost", "lost1", "reset", "new", "skip", "isbonus", "undo", "addstage", "dropstage")
        or state.get("active") is False
    ):
        return state
    if query.get("chs") != str(len(state["steps"])):
        return state  # a reload of an action already counted
    if act == "skip":  # a weak night: this stage waits for a later one (owner, 2026-11-05)
        night_ = str(query.get("chnight") or "")
        if state.get("placed") or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", night_):
            return state
        return state | {"skip": max(night_, state.get("skip") or "")}
    if act in ("addstage", "dropstage"):  # change the plan mid-run (owner, 2026-11-05)
        n = state.get("stages", DEFAULT_STAGES) + (1 if act == "addstage" else -1)
        done = len(state["steps"]) + (1 if state.get("placed") else 0)
        return state | {"stages": max(min(n, max(STAGES)), done + 1, min(STAGES))}
    if act == "undo":  # the last stage's result was put in wrong: back to placed (owner, 2026-11-05)
        if state.get("placed") or not state["steps"]:
            return state
        won = [b for b in state.get("bets", []) if not b.get("own") and b["state"] == "won"]
        if not won:
            return state
        last = won[-1] | {"state": "placed", "ret": 0.0}
        bets = [last if b.get("id") == last["id"] and not b.get("own") else b for b in state["bets"]]
        steps = state["steps"][:-1]
        return state | {
            "placed": last,
            "bets": bets,
            "steps": steps,
            "bank": state["steps"][-1]["from"],
            "kept": state.get("kept", 0.0) if steps else 0.0,
        }
    if act == "reset":
        return state if state.get("placed") else _again(state)  # a placed stage settles first
    if act == "new":
        if state.get("placed"):
            return state  # a placed stage settles first: its stake is real money
        return _again(state) | {"active": False}
    if act == "place":
        if state.get("placed"):
            return state
        bet = {
            "id": max([b.get("id", 0) for b in state.get("bets", [])], default=0) + 1,
            "day": today,
            "ag": query.get("chag") or "sb",
            "stake": state["bank"],
            "price": _money(query.get("chp")),
            "label": (query.get("chl") or "")[:120],
            "state": "placed",
            "ret": 0.0,
            "tip": (query.get("chtip") or "")[:32],
        }
        if state.get("bonus") or query.get("chbonus") == "1":  # staked with a bonus bet
            bet["bonus"] = 1
        rest = {k: v for k, v in state.items() if k != "bonus"}
        return rest | {"placed": bet, "bets": (state.get("bets", []) + [bet])[-MAX_BETS:]}
    if not state.get("placed"):
        return state  # mark the stage as placed first
    if act == "isbonus":  # the stake was a bonus bet after all: not money, and it pays winnings only
        placed = state["placed"] | {"bonus": 1}
        bets = [b | {"bonus": 1} if b.get("id") == placed.get("id") else b for b in state.get("bets", [])]
        return state | {"placed": placed, "bets": bets}
    if act == "lost1" and not state["placed"].get("bonus"):
        # one leg failed on a 'money back as a bonus bet' multi (owner, 2026-11-05): the stage is
        # played again with the bonus bet, which pays its winnings only
        return state | {
            "bets": _settle(state, "lost"),
            "placed": None,
            "bonus": state["placed"]["stake"],
        }
    if act in ("lost", "lost1"):
        past = (
            state.get("past", [])
            + [{"steps": len(state["steps"]), "best": state["bank"], "made_it": False}]
        )[-MAX_HISTORY:]
        return _again(state | {"bets": _settle(state, "lost"), "past": past})
    returned = _money(query.get("chr"))
    bonus = bool(state["placed"].get("bonus"))  # a bonus bet pays its winnings only
    if returned is None or returned <= (0 if bonus else state["placed"]["stake"]):
        return state
    bets = _settle(state, "won", returned)
    steps = state["steps"] + [
        {"from": state["bank"], "to": returned, "tip": state["placed"].get("tip", "")}
    ]
    kept, bank = state.get("kept", 0.0), returned
    if state.get("keep", True) and not state["steps"] and not bonus:  # first win: start goes back
        kept, bank = state["start"], round(returned - state["start"], 2)
    if bank >= reach(state["goal"]):
        past = (state.get("past", []) + [{"steps": len(steps), "best": returned, "made_it": True}])[
            -MAX_HISTORY:
        ]
        return _again(state | {"bets": bets, "past": past}, last_win=returned)
    return state | {"bank": bank, "steps": steps, "kept": kept, "placed": None, "bets": bets}


MAX_OWN = 20  # bets kept in the cookie (a cookie holds about 4 KB)


def _own_bet(state: dict | None, act: str, query: Mapping[str, str], today: str) -> dict:
    """Log a multi from the Multis / SGM / Games tabs (owner, 2026-11-05): placed at an agency
    for a stake at the price got, then won (it paid $x) or lost. It counts in the day's money
    like a challenge stage; no run is started."""
    base = state if state is not None else fresh() | {"active": False}
    bets = [dict(b) for b in base.get("bets", [])]
    if act == "bet":
        stake, price = _money(query.get("nbs")) or 10.0, _money(query.get("nbp"))
        label = (query.get("nbl") or "")[:90]
        key = f"{today}|{label}|{stake}|{price}"
        if any(b.get("k") == key for b in bets):
            return base  # the same page reloaded
        bets.append(
            {
                "id": max([b.get("id", 0) for b in bets], default=0) + 1,
                "own": 1,
                "k": key,
                "day": today,
                "ag": query.get("nbag") or "sb",
                "stake": stake,
                "price": price,
                "label": label,
                "state": "placed",
                "ret": 0.0,
                "tip": (query.get("nbtip") or "")[:32],
            }
        )
    else:
        for b in bets:
            if (
                b.get("own")
                and str(b.get("id")) == str(query.get("nbid"))
                and b["state"] == "placed"
            ):
                if act == "betwon":
                    b["state"] = "won"
                    b["ret"] = _money(query.get("nbr")) or round(
                        b["stake"] * (b.get("price") or 1), 2
                    )
                else:
                    b["state"] = "lost"
    own = [b for b in bets if b.get("own")][-MAX_OWN:]
    run = [b for b in bets if not b.get("own")]
    return base | {"bets": run[-(MAX_BETS - len(own)) :] + own if len(own) < MAX_BETS else own}


def own_bets(state: dict | None, today: str) -> list[dict]:
    """The owner's own bets to show: every one still open, and today's settled ones."""
    return [
        b
        for b in (state or {}).get("bets", [])
        if b.get("own") and (b["state"] == "placed" or b.get("day") == today)
    ]


def today_money(state: dict | None, today: str) -> tuple[dict[str, float], float]:
    """Today's NBA money by agency: ({agency: stakes out minus returns}, profit of settled bets)."""
    used: dict[str, float] = {}
    profit = 0.0
    for b in (state or {}).get("bets", []):
        if b.get("day") != today:
            continue
        cash = 0.0 if b.get("bonus") else b["stake"]  # a bonus bet's stake is not money
        used[b["ag"]] = round(used.get(b["ag"], 0.0) + cash - (b.get("ret") or 0.0), 2)
        if b["state"] == "won":
            profit += b["ret"] - cash
        elif b["state"] == "lost":
            profit -= cash
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
    skip = state.get("skip") or None  # a night the owner skipped: wait for a later one
    tips = [_when(s.get("tip")) for s in state["steps"]]
    tips = [t for t in tips if t]
    if not tips:
        return None, skip
    last = tips[-1]
    same_night = sum(1 for t in tips if night(t) == night(last))
    if state.get("mode", "game") == "game" and same_night < state.get("per_night", 1):
        return last + GAP, skip
    return last + GAP, max(night(last), skip or "")


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


HAIRCUT = 0.035  # a same-game multi pays about this much under its legs multiplied (Sportsbet: $2.30 for $2.38)
TYPICAL_OF = 3  # a later stage is about as likely as tonight's third-best games, not the very best


def typical(chances: list[float]) -> float | None:
    """What a later stage is likely to offer: the mean of tonight's TYPICAL_OF best games."""
    top = sorted(chances, reverse=True)[:TYPICAL_OF]
    return sum(top) / len(top) if top else None


def finish_chance(
    stage_chance: float | None, state: dict, later: float | None = None
) -> float | None:
    """The chance of winning every stage still to play: this stage at its own chance, the rest at
    `later` (a typical stage, see typical()); without `later`, all at this one's."""
    if stage_chance is None:
        return None
    rest = remaining(state) - 1
    return stage_chance * (later if later is not None else stage_chance) ** rest


def plan(start: float, goal: float, keep: bool, chances_for) -> list[dict]:
    """For each stage count: the payout a stage, tonight's best and typical stage chance (searched
    HAIRCUT above the payout, as the bookmaker prices the multi lower), and the chance to finish
    at the typical one. chances_for({n: price}) -> {n: [one chance per game]}."""
    xs = {n: stage_x(start, goal, n, keep) for n in STAGES}
    got = chances_for({n: x / (1 - HAIRCUT) for n, x in xs.items()})
    out = []
    for n, x in xs.items():
        cs = got.get(n) or []
        t = typical(cs)
        out.append(
            {
                "n": n,
                "x": x,
                "stage": max(cs) if cs else None,
                "typical": t,
                "run": t**n if t else None,
            }
        )
    return out


def recommend(options: list[dict]) -> tuple[dict | None, str]:
    """The stage count with the best chance to finish (fewer stages on a near tie), and why."""
    ok = [o for o in options if o["run"]]
    if not ok:
        return None, ""
    best = max(ok, key=lambda o: (round(o["run"], 4), -o["n"]))
    close = [o for o in ok if o is not best and o["run"] >= best["run"] * 0.9]
    head = (
        f"{best['n']} stages: about {best['x']:.1f}x a stage, each about {best['typical']:.0%} to "
        f"get up, so {best['run']:.1%} to finish. "
    )
    ns = [o["n"] for o in ok]
    if best["n"] == min(ns):
        why = head + (
            "Fewest stages wins tonight: every extra stage takes the bookmaker's margin again, "
            "and that costs more than the easier multis gain."
        )
    elif best["n"] == max(ns):
        why = head + (
            "Most stages wins tonight: the big multis that fewer stages need rarely get up, "
            "more than the extra wins in a row cost."
        )
    else:
        why = head + (
            "Fewer stages need bigger multis that rarely get up; more stages need more wins in "
            f"a row, each paying the bookmaker's margin. {best['n']} is where the two balance "
            "on tonight's lines."
        )
    if close:
        why += " Close: " + ", ".join(f"{o['n']} stages {o['run']:.1%}" for o in close) + "."
    return best, why


GOAL_SLACK = (
    0.02  # aim 2% under the goal: safer legs beat squeezing out the last $20 (owner, 2026-11-04)
)


def reach(goal: float) -> float:
    """What the stages actually aim for, and what counts as made it: the goal less GOAL_SLACK."""
    return round(goal * (1 - GOAL_SLACK), 2)


def stage_x(start: float, goal: float, stages: int, keep: bool) -> float:
    """The even payout per stage that turns `start` into `goal` in `stages` wins; with keep the
    first win also hands the start back: start * (x - 1) * x ** (stages - 1) = goal. The goal
    here is reach(goal), GOAL_SLACK under the one the owner set."""
    goal = reach(goal)
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
    x = stage_x(state["bank"], state["goal"], remaining(state), keep_now and not state.get("bonus"))
    if state.get("bonus"):  # a bonus bet pays winnings only: one more unit of price for the same return
        x += 1
    return max(MIN_X, x)
