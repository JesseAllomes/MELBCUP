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

import copy
import json
import os
import re
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from melbcup import wallet
except ImportError:  # the Function package: flat modules (tools/deploy_azure.py)
    import wallet

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


def _legs(text) -> int | None:
    """Legs per multi: 2-4, or None for the best chance at any count."""
    return int(text) if str(text) in ("2", "3", "4") else None


def fresh(
    start=10.0,
    goal=1000.0,
    past=None,
    mode="game",
    keep=True,
    bets=None,
    stages=DEFAULT_STAGES,
    per_night=1,
    legs=None,
) -> dict:
    return {
        "legs": legs,
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


SHOWN_KEYS = ("shown", "shown_sug")


def _unshown(state: dict) -> dict:
    """The state without the stage's frozen suggestion, so the next view picks afresh."""
    return {k: v for k, v in state.items() if k not in SHOWN_KEYS}


def shown_for(state: dict | None, key: str = "shown") -> dict | None:
    """The suggestion frozen for the current, unplaced stage (owner, 2026-11-07: a stage's chosen
    bet sticks until "Find best multi for this leg", a pick, or placing it)."""
    sh = (state or {}).get(key)
    if sh and sh.get("stage") == len((state or {}).get("steps", [])) and not state.get("placed"):
        return sh
    return None


def freeze(cid: str | None, state: dict, key: str, shown: dict) -> None:
    """Remember the suggestion first shown for this stage: idempotent (an existing frozen pick for
    the stage is never overwritten), one small write, and silent if the store is unavailable."""
    if shown_for(state, key):
        return
    state[key] = shown
    try:
        store = load()
        rec = find(store, cid)
        st = rec["state"] if rec else None
        if (
            st is None
            or st.get("placed")
            or shown_for(st, key)
            or len(st.get("steps", [])) != shown["stage"]
        ):
            return
        st[key] = shown
        save(store)
    except Exception:  # a failed freeze only means the next view picks again
        pass


DRIFT = 0.03  # picker v2 re-pick rule: a leg whose price has lengthened more than this has lost chance


def drifted(step: dict | None, legs_now: list[dict], tol: float = DRIFT) -> list[dict]:
    """The frozen pick's legs whose current price is more than `tol` longer than the price when it
    was picked (so its chance dropped): [{"leg", "game", "from", "to"}]. Matched by game and
    label; a leg no longer on the board is left to the ordinary live-differs note."""
    now = {(g.get("game"), g.get("label")): g.get("price") for g in legs_now}
    out = []
    for d in (step or {}).get("detail") or []:
        p1, p0 = now.get((d.get("game"), d.get("label"))), d.get("price")
        if p0 and p1 and p1 / p0 - 1 > tol:
            out.append({"leg": d.get("label"), "game": d.get("game"), "from": p0, "to": p1})
    return out


def repick_note(moves: list[dict]) -> str:
    m = moves[0]
    return f"re-picked: {m['leg']} drifted from ${m['from']:.2f} to ${m['to']:.2f}"


def refreeze(cid: str | None, state: dict, key: str, shown: dict, event: dict | None = None) -> None:
    """Replace the stage's frozen pick with a fresh one (the drift re-pick) and record the event in
    state["repicks"] for the A/B report. One small write, silent if the store is unavailable."""
    state[key] = shown
    if event:
        state.setdefault("repicks", []).append(event)
    try:
        store = load()
        rec = find(store, cid)
        st = rec["state"] if rec else None
        if st is None or st.get("placed") or len(st.get("steps", [])) != shown["stage"]:
            return
        st[key] = shown
        if event:
            st.setdefault("repicks", []).append(event)
        save(store)
    except Exception:  # a failed write only means the next view re-picks again
        pass


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
            state.get("legs"),
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
            _legs(query.get("chlegs")),
        )
        return run
    if (
        state is None
        or act
        not in (
            "chlegs",
            "place",
            "won",
            "lost",
            "lost1",
            "reset",
            "new",
            "skip",
            "isbonus",
            "undo",
            "addstage",
            "dropstage",
            "pick",
            "best",
            "chbet",
        )
        or state.get("active") is False
    ):
        return state
    if query.get("chs") != str(len(state["steps"])):
        return state  # a reload of an action already counted
    if act == "chlegs":  # legs per multi, any time before the stage is placed
        return (
            _unshown(state) | {"legs": _legs(query.get("chlegs"))}
            if not state.get("placed")
            else state
        )
    if act == "skip":  # a weak night: this stage waits for a later one (owner, 2026-11-05)
        night_ = str(query.get("chnight") or "")
        if state.get("placed") or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", night_):
            return state
        return state | {"skip": max(night_, state.get("skip") or "")}
    if act == "pick":  # stick to this game for the stage (owner, 2026-11-06)
        return (
            _unshown(state) | {"pick": str(query.get("chpick") or "")[:80]}
            if not state.get("placed")
            else state
        )
    if act == "best":  # back to the best multi on the current prices
        return {k: v for k, v in _unshown(state).items() if k != "pick"}
    if act in ("addstage", "dropstage"):  # change the plan mid-run (owner, 2026-11-05)
        n = state.get("stages", DEFAULT_STAGES) + (1 if act == "addstage" else -1)
        done = len(state["steps"]) + (1 if state.get("placed") else 0)
        return state | {"stages": max(min(n, max(STAGES)), done + 1, min(STAGES))}
    if (
        act == "undo"
    ):  # the last stage's result was put in wrong: back to placed (owner, 2026-11-05)
        if state.get("placed") or not state["steps"]:
            return state
        won = [b for b in state.get("bets", []) if not b.get("own") and b["state"] == "won"]
        if not won:
            return state
        last = won[-1] | {"state": "placed", "ret": 0.0}
        bets = [
            last if b.get("id") == last["id"] and not b.get("own") else b for b in state["bets"]
        ]
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
            "label": (query.get("chl") or "")[:400],
            "state": "placed",
            "ret": 0.0,
            "tip": (query.get("chtip") or "")[:32],
        }
        chances = []
        for x in str(query.get("chc") or "").split(","):  # each leg's pre-game chance (percent)
            try:
                chances.append({"chance": round(min(max(float(x), 0.1), 99.9) / 100, 4)})
            except ValueError:
                chances = []
                break
        if chances:
            bet["legs"] = chances[:12]
        if state.get("bonus") or query.get("chbonus") == "1":  # staked with a bonus bet
            bet["bonus"] = 1
        rest = {k: v for k, v in state.items() if k not in ("bonus", "pick", *SHOWN_KEYS)}
        return rest | {"placed": bet, "bets": (state.get("bets", []) + [bet])[-MAX_BETS:]}
    if not state.get("placed"):
        return state  # mark the stage as placed first
    if act == "chbet":  # fix the real stake / price / legs of the placed bet (owner, 2026-11-07)
        pl = state["placed"]
        stake, price = _money(query.get("chstake")), _money(query.get("chp"))
        if not stake or (price is not None and price <= 1):
            return state
        extra = round(max(stake - state["bank"], 0.0), 2)
        new = pl | {
            "stake": stake,
            "price": price or pl.get("price"),
            "rest": round(max(state["bank"] - stake, 0.0), 2),
        }
        if query.get("chl"):
            new["label"] = query["chl"][:400]
        if extra:
            new["added"] = extra  # topped up: cash added today
        bets = [b | new if b.get("id") == pl.get("id") else b for b in state.get("bets", [])]
        return state | {"placed": new, "bets": bets}
    if (
        act == "isbonus"
    ):  # the stake was a bonus bet after all: not money, and it pays winnings only
        placed = state["placed"] | {"bonus": 1}
        bets = [
            b | {"bonus": 1} if b.get("id") == placed.get("id") else b
            for b in state.get("bets", [])
        ]
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
    pl = state["placed"]
    if returned is None and pl.get("price") and "rest" in pl:
        returned = round(pl["stake"] * pl["price"], 2)
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
    bank = round(bank + pl.get("rest", 0.0), 2)  # money not staked stays in the bank
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
        label = (query.get("nbl") or "")[:300]
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
                **({"sport": s} if (s := query.get("sport")) in ("nba", "nfl") else {}),
            }
            | ({"bonus_if_win": bw} if (bw := _money(query.get("nbbw"))) else {})
            | ({"bonus": 1} if query.get("nbbonus") == "1" else {})  # staked with a bonus bet
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
        b | {"sport_of": bet_sport(b)}
        for b in (state or {}).get("bets", [])
        if b.get("own") and (b["state"] == "placed" or b.get("day") == today)
    ]


_RACE = re.compile(r"\bR\d{1,2}\b|\bRace \d|Same Race Multi|\bTop \d\b")


def bet_sport(b: dict) -> str:
    """Which page an own bet belongs on: its recorded sport, else racing when the label reads like
    a race (owner, 2026-11-08: a horse bet showed on the NFL page), else NBA (the older records)."""
    if b.get("sport"):
        return b["sport"]
    return "racing" if _RACE.search(b.get("label") or "") else "nba"


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
    if state.get(
        "bonus"
    ):  # a bonus bet pays winnings only: one more unit of price for the same return
        x += 1
    return max(MIN_X, x)


# --- many challenges at once (owner, 2026-11-07) ------------------------------------------------
# One durable store holds every challenge. Each challenge keeps its own engine state (everything
# above: bank, steps, bets, past...), so an action on one never touches another's money.
#   {"v":1, "next":n, "challenges":[{"id","name","scope","state"}], "own": <state of the owner's own
#    multis>, "ledger":[wallet entries], "wagers":[...], "ops":[recent op ids], "migrated":bool}
# scope "nba" suggests NBA stages; "all" (All Sports) takes any leg the owner records by hand.
# Everything is recorded by the owner: the app never places a bet or moves money.

WALLET_ACTS = ("wgrant", "wsplit", "walloc", "wrel", "wred", "wexp")
STORE_BLOB = "challenges/state.json"
SCOPES = ("nba", "all", "nfl")
MAX_OPS = 200
MAX_WAGERS = 200
_CACHE: list = [0.0, None]  # [loaded at, store]: one page makes several reads
CACHE_S = 5.0


def _local_path() -> Path:
    return Path(
        os.environ.get("NBA_CHALLENGES_FILE")
        or Path.home() / ".asynymbet" / "challenges_state.json"
    )


def empty_store() -> dict:
    return {
        "v": 1,
        "next": 1,
        "challenges": [],
        "own": fresh() | {"active": False},
        "ledger": [],
        "wagers": [],
        "ops": [],
        "migrated": False,
    }


def migrate(cookie_raw: str | None) -> dict:
    """A store from the old one-challenge cookie: its run becomes challenge #1."""
    store, old = empty_store(), parse(cookie_raw)
    if old:
        own = [b for b in old.get("bets", []) if b.get("own")]
        store["own"] = store["own"] | {"bets": own}
        store["challenges"].append(
            {
                "id": "ch1",
                "name": "Challenge 1",
                "scope": "nba",
                "state": old | {"bets": [b for b in old.get("bets", []) if not b.get("own")]},
            }
        )
        store["next"], store["migrated"] = 2, True
    return store


class StoreUnavailable(RuntimeError):
    """The durable store could not be read (not the same as 'nothing stored yet')."""


def _read() -> dict | None:
    """The stored challenges, None only when nothing has been stored yet. Any other failure
    raises StoreUnavailable, so a read hiccup can never be mistaken for an empty store and
    saved over the owner's challenges."""
    account = os.environ.get("NBA_ACCOUNT")
    try:
        if account:
            from melbcup.nba_feed import blob_reader

            raw = blob_reader(account, os.environ.get("AZURE_CLIENT_ID"))(STORE_BLOB)
        else:
            p = _local_path()
            raw = p.read_bytes() if p.exists() else None
        return json.loads(raw) if raw else None
    except Exception as e:  # noqa: BLE001
        raise StoreUnavailable(str(e)) from e


def load(cookie_raw: str | None = None, fresh_read: bool = False) -> dict:
    """The durable store; the old cookie is read only when nothing is stored yet (migration)."""
    now = time.monotonic()
    if not fresh_read and _CACHE[1] is not None and now - _CACHE[0] < CACHE_S:
        return copy.deepcopy(_CACHE[1])
    try:
        store = _read()
    except StoreUnavailable:
        if _CACHE[1] is not None:  # serve the last good copy, read-only
            return copy.deepcopy(_CACHE[1]) | {"_unavailable": True}
        return migrate(None) | {"_unavailable": True}
    if not isinstance(store, dict) or "challenges" not in store:
        store = migrate(cookie_raw)
    _CACHE[:] = [now, copy.deepcopy(store)]
    return store


def save(store: dict) -> None:
    """Write the store. Refuses a store loaded while the real one was unreadable. Each save also
    refreshes that day's backup copy (challenges/backup-<YYYYMMDD>.json)."""
    if store.get("_unavailable"):
        raise StoreUnavailable("not saving: the stored challenges could not be read")
    data = json.dumps(store, separators=(",", ":")).encode()
    account = os.environ.get("NBA_ACCOUNT")
    if account:
        from melbcup.push_store import blob_writer

        w = blob_writer(account, os.environ.get("AZURE_CLIENT_ID"))
        w(STORE_BLOB, data)
        w(f"challenges/backup-{time.strftime('%Y%m%d', time.gmtime())}.json", data)
    else:
        p = _local_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)
    _CACHE[:] = [time.monotonic(), copy.deepcopy(store)]


def find(store: dict, cid: str | None) -> dict | None:
    return next((c for c in store["challenges"] if c["id"] == cid), None)


def status(rec: dict) -> str:
    """draft (no run), waiting_result (a stage placed), active (the contract's names)."""
    s = rec["state"]
    return (
        "draft" if s.get("active") is False else "waiting_result" if s.get("placed") else "active"
    )


def contract(rec: dict) -> dict:
    """The challenge in the pack's field names (contracts/challenge.schema.json), cents."""
    s = rec["state"]
    return {
        "challenge_id": rec["id"],
        "name": rec["name"],
        "scope": {
            "mode": "all_sports" if rec["scope"] == "all" else "single_sport",
            "sports": [] if rec["scope"] == "all" else [rec["scope"]],
        },
        "status": status(rec),
        "start_cash_cents": round(s["start"] * 100),
        "current_cash_cents": round(s["bank"] * 100),
        "goal_cash_cents": round(s["goal"] * 100),
        "stages_planned": s.get("stages", DEFAULT_STAGES),
        "stages_completed": len(s["steps"]),
    }


def store_money(store: dict, today: str) -> tuple[dict[str, float], float]:
    """Today's money across every challenge and the owner's own multis, by agency."""
    used: dict[str, float] = {}
    profit = 0.0
    for st in [c["state"] for c in store["challenges"]] + [store["own"]]:
        u, p = today_money(st, today)
        for k, v in u.items():
            used[k] = round(used.get(k, 0.0) + v, 2)
        profit += p
    return used, round(profit, 2)


def _edit(state: dict, q: Mapping[str, str]) -> dict:
    """Correct an open run's settings (owner, 2026-11-07): start, bank, goal, stages, legs, keep.
    The stage history stays; the next stage's target follows from the new bank, goal and stages."""
    if state.get("active") is False:
        raise ValueError("start a run first")
    if state.get("placed"):
        raise ValueError("settle the placed stage first")
    start = _money(q.get("chstart")) or state["start"]
    bank = _money(q.get("chbank")) or state["bank"]
    goal = _money(q.get("chgoal")) or state["goal"]
    done = len(state["steps"])
    try:
        n = int(q.get("chn") or state.get("stages", DEFAULT_STAGES))
    except ValueError:
        n = state.get("stages", DEFAULT_STAGES)
    n = max(min(n, max(STAGES)), done + 1, min(STAGES))
    keep = q.get("chkeep") == "1" if "chkeep" in q else state.get("keep", True)
    return state | {
        "start": start,
        "bank": bank,
        "goal": max(goal, bank * 1.01, start * 2 if not done else 0),
        "stages": n,
        "legs": _legs(q.get("chlegs")),
        "keep": keep,
    }


def _csv_floats(text: str | None) -> list[float]:
    return [v for v in (_money(x) for x in re.split(r"[,\s+]+", text or "") if x) if v]


def apply_store(store: dict, query: Mapping[str, str], today: str = "") -> tuple[dict, bool, str]:
    """(store after the action in `query`, changed, error message). Pure: `store` is not touched.
    An action carrying an `op` id already done does nothing (a reload or double tap)."""
    act = query.get("ch")
    if not act:
        return store, False, ""
    store = copy.deepcopy(store)
    op = str(query.get("op") or "")[:40]
    if op and op in store["ops"]:
        return store, False, ""
    err = ""
    before = json.dumps(store, sort_keys=True)
    try:
        _dispatch(store, act, query, today, op)
    except (wallet.WalletError, ValueError) as e:
        err = str(e)
    changed = json.dumps(store, sort_keys=True) != before
    if changed and op:
        store["ops"] = (store["ops"] + [op])[-MAX_OPS:]
    return store, changed, err


def _compose(q: Mapping[str, str]) -> Mapping[str, str]:
    """The record-a-bet form's Game + Legs lines become the label "Game: leg, leg" the live
    tracker parses (legs one per line or comma separated)."""
    what = q.get("nbwhat")
    if what is None:
        return q
    legs = [x.strip() for x in re.split(r"[\n;,]+", what) if x.strip()]
    game = (q.get("nbgame") or "").strip()
    return {**q, "nbl": (f"{game}: " if game else "") + ", ".join(legs)}


_AGENCY_PROVIDER = {"sb": "Sportsbet", "pb": "PointsBet"}


def _bonus_bets(state: dict) -> dict:
    return {b["id"]: b for b in (state or {}).get("bets", []) if b.get("bonus") and b.get("id") is not None}


def _use_bonus(store: dict, scope: str, before: dict, after: dict, today: str) -> None:
    """Bets that just became bonus bets use that bookmaker's credit; the leftover stays. Never fails
    the record. TODO: reverse (wallet.unuse_leftover) on delete/edit-to-cash: no such action exists
    for engine bets yet."""
    old = _bonus_bets(before)
    for bid, b in _bonus_bets(after).items():
        if bid in old:
            continue
        prov = _AGENCY_PROVIDER.get(b.get("ag"), b.get("provider") or b.get("book") or "")
        if prov and b.get("stake"):
            store["ledger"] = wallet.use_leftover(store["ledger"], prov, b["stake"], f"bonus-use-{scope}-{bid}", today)


def _dispatch(store: dict, act: str, q: Mapping[str, str], today: str, op: str) -> None:
    q = _compose(q)
    if act == "bet" and q.get("nbch"):  # recorded against a challenge: the wager path
        rec = find(store, q.get("nbch"))
        if rec is None:
            raise ValueError("no such challenge")
        wq = {
            "wlegs": q.get("nbl"),
            "wprov": AGENCY_NAMES.get(q.get("nbag") or "", q.get("nbag")),
            "wodds": q.get("nbp"),
            "wstake": q.get("nbs"),
            "wbw": q.get("nbbw"),
        }
        _record_wager(store, rec, wq, today, op)
        return
    if act in ("bet", "betwon", "betlost"):
        before = store["own"]
        store["own"] = apply(store["own"], q, today)
        if act == "betwon":
            for b in (store["own"] or {}).get("bets", []):
                if str(b.get("id")) == str(q.get("nbid")) and b.get("own") and b["state"] == "won":
                    _bonus_credit(store, b, today, f"bw-own{b['id']}")

        _use_bonus(store, "own", before, store["own"], today)
        return
    if act == "newch":
        name = (q.get("chname") or "").strip()[:40] or f"Challenge {store['next']}"
        scope = q.get("chscope") if q.get("chscope") in SCOPES else "nba"
        run = apply(fresh() | {"active": False}, {**q, "ch": "start"}, today)
        store["challenges"].append(
            {"id": f"ch{store['next']}", "name": name, "scope": scope, "state": run}
        )
        store["next"] += 1
        return
    if act in WALLET_ACTS:
        _wallet_action(store, act, q, today, op)
        return
    rec = find(store, q.get("chid")) or (
        store["challenges"][0] if len(store["challenges"]) == 1 and not q.get("chid") else None
    )
    if rec is None:
        raise ValueError("no such challenge")
    if act == "wgr":
        _record_wager(store, rec, q, today, op)
    elif act in ("wgrwon", "wgrlost"):
        _settle_wager(store, rec, act, q)
    elif act == "chedit":
        rec["name"] = (q.get("chname") or "").strip()[:40] or rec["name"]
        rec["state"] = _edit(rec["state"], q)
    elif act == "renamech":
        rec["name"] = (q.get("chname") or "").strip()[:40] or rec["name"]
    elif act == "rmch":
        if rec["state"].get("placed") or any(
            w["challenge"] == rec["id"] and w["state"] == "placed" for w in store["wagers"]
        ):
            raise ValueError("settle its placed stage or wager first")
        for c in wallet.credits(store["ledger"], today).values():
            if c["challenge"] == rec["id"] and c["status"] == "reserved":
                store["ledger"] = wallet.append(
                    store["ledger"], {"t": "release", "credit": c["id"]}, today
                )
        store["challenges"].remove(rec)
    else:
        before = rec["state"]
        rec["state"] = apply(rec["state"], q, today) or rec["state"]
        _use_bonus(store, rec["id"], before, rec["state"], today)


AGENCY_NAMES = {
    "sb": "Sportsbet",
    "bf": "Betfair",
    "pb": "PointsBet",
    "tab": "TAB",
    "lb": "Ladbrokes",
    "neds": "Neds",
}


def _bonus_credit(store, b: dict, today: str, op: str) -> None:
    """A bet that pays a bonus bet when it wins (e.g. Jet Boost): add that credit to the wallet."""
    amt = b.get("bonus_if_win")
    if not amt:
        return
    prov = AGENCY_NAMES.get(b.get("ag"), b.get("ag") or b.get("provider") or "")
    entry = {
        "t": "grant",
        "amount": amt,
        "provider": prov,
        "note": "Bonus bet from a winning bet",
        "op": op,
    }
    store["ledger"] = wallet.append(store["ledger"], entry, today)


def _wallet_action(store, act, q, today, op) -> None:
    e: dict = {"op": op, "at": today}
    cid = q.get("wid")
    if act == "wgrant":
        e |= {
            "t": "grant",
            "amount": q.get("wamt"),
            "provider": q.get("wprov"),
            "expiry": q.get("wexp"),
            "note": q.get("wnote"),
        }
        if q.get("wplans"):  # e.g. "5+5;2+3+5": the splits the provider showed for this credit
            e["plans"] = [_csv_floats(p) for p in q["wplans"].split(";") if p.strip()]
    elif act == "wsplit":
        e |= {"t": "split", "credit": cid, "parts": _csv_floats(q.get("wparts"))}
    elif act == "walloc":
        if not find(store, q.get("chid")):
            raise ValueError("no such challenge")
        e |= {"t": "allocate", "credit": cid, "challenge": q.get("chid")}
    elif act == "wrel":
        e |= {"t": "release", "credit": cid}
    elif act == "wred":
        e |= {"t": "redeem", "credit": cid}
    elif act == "wexp":
        e |= {"t": "expire", "credit": cid}
    else:
        raise ValueError("unknown wallet action")
    store["ledger"] = wallet.append(
        store["ledger"], {k: v for k, v in e.items() if v not in (None, "")}, today
    )


def _record_wager(store, rec, q, today, op) -> None:
    """The owner's record of a bet placed outside the app. `refs` are other challenges that share
    the exposure: only the primary challenge claims the bankroll, so there is one money record."""
    legs, provider = (q.get("wlegs") or "").strip()[:300], (q.get("wprov") or "").strip()[:40]
    odds, stake = _money(q.get("wodds")), _money(q.get("wstake"))
    funding = q.get("wfund") if q.get("wfund") in ("cash", "bonus", "boost") else "cash"
    if not (legs and provider and odds and odds > 1 and stake):
        raise ValueError("provider, legs, odds (above 1) and stake needed")
    w = {
        "id": max([x["id"] for x in store["wagers"]], default=0) + 1,
        "challenge": rec["id"],
        "refs": [
            r
            for r in dict.fromkeys((q.get("wrefs") or "").replace(" ", "").split(","))
            if r and r != rec["id"] and find(store, r)
        ],
        "provider": provider,
        "legs": legs,
        "odds": odds,
        "stake": stake,
        "funding": funding,
        "day": today,
        "at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "state": "placed",
        "ret": 0.0,
        "op": op,
    }
    if bw := _money(q.get("wbw")):
        w["bonus_if_win"] = bw
    if funding == "boost":
        w["boost_price"] = _money(q.get("wboost"))
        if not w["boost_price"]:
            raise ValueError("enter the boosted price")
    if funding == "bonus":
        c = wallet.credits(store["ledger"], today).get(q.get("wcredit"))
        if c is None or c["provider"].lower() != provider.lower():
            raise ValueError("pick a credit from that provider")
        # automatic leftovers (owner, 2026-11-08): the stake comes off the credit, the rest stays
        store["ledger"] = wallet.use_leftover(store["ledger"], provider, stake, f"bonus-use-w{w['id']}", today, rec["id"])
        w["credit"] = c["id"]
    store["wagers"] = (store["wagers"] + [w])[-MAX_WAGERS:]


def _settle_wager(store, rec, act, q) -> None:
    for w in store["wagers"]:
        if (
            str(w["id"]) == str(q.get("wid"))
            and w["challenge"] == rec["id"]
            and w["state"] == "placed"
        ):
            w["state"] = "won" if act == "wgrwon" else "lost"
            if act == "wgrwon" and w.get("bonus_if_win"):
                _bonus_credit(store, w, w["day"], f"bw-w{w['id']}")
            if act == "wgrwon":
                win = w["odds"] - 1 if w["funding"] == "bonus" else w["odds"]
                w["ret"] = _money(q.get("wret")) or round(w["stake"] * win, 2)


MELB = ZoneInfo("Australia/Melbourne")


def game_left(track: dict | None, tip: datetime | None, now: datetime) -> str:
    """Game time left as text, Melbourne time: "Q3 4:12 · 18 min left", "starts 7:30pm", "final"."""
    state = (track or {}).get("state")
    if state == "post":
        return "final"
    if state == "in":
        q, secs = track.get("period"), track.get("clock_s")
        if q and secs is not None and q <= 4:
            left = max(0, 4 - q) * 12 + int((secs + 59) // 60)
            return f"Q{q} {int(secs // 60)}:{int(secs % 60):02d} \u00b7 {left} min left"
        if q:
            return f"OT{q - 4}" if q > 4 else f"Q{q}"
        return "in play"
    start = tip or _when((track or {}).get("starts_at"))
    if start and start > now:
        return f"starts {start.astimezone(MELB):%-I:%M%p}".lower()
    return "in play" if start else ""


def row(rec: dict, track: dict | None = None, now: datetime | None = None) -> dict:
    """The collapsed list row's figures from saved state (and a live track when given): the
    leg odds, the chance now as a percent, the game time left."""
    from melbcup import live_chance

    now = now or datetime.now(UTC)
    placed = (rec.get("state") or {}).get("placed") or {}
    if not placed:
        return {"odds": None, "pct": None, "clock": "", "failed": False}
    p = live_chance.bet_live(track, placed)["p"]
    legs = (track or {}).get("legs") or []
    failed = bool(
        any(g.get("ok") is False for g in legs)
        or (track or {}).get("verdict") in ("lost", "lost1")
    )
    return {
        "failed": failed,
        "odds": placed.get("price"),
        "pct": round(p * 100) if p is not None else None,
        "clock": game_left(track, _when(placed.get("tip")), now),
    }
