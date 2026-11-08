"""Live chance of a placed multi: each leg's pre-game market chance re-read against the count so
far and the time left (Poisson; owner lock 2026-11-08, "live estimate"). Pure functions."""

from __future__ import annotations

import math

GAME_SECS = 48 * 60


def _cdf(mu: float, n: int) -> float:
    """P(X <= n) for Poisson(mu)."""
    if n < 0:
        return 0.0
    term = total = math.exp(-mu)
    for i in range(1, n + 1):
        term *= mu / i
        total += term
    return min(1.0, total)


def implied_mean(p: float, k: int, under: bool) -> float:
    """The pre-game mean count whose Poisson chance matches p: P(X >= k) = p (over), or
    P(X < k) = p (under)."""
    p = min(max(p, 1e-4), 1 - 1e-4)
    lo, hi = 1e-6, max(10.0, 4.0 * k + 10)
    for _ in range(60):
        mid = (lo + hi) / 2
        over = 1 - _cdf(mid, k - 1)
        got = (1 - over) if under else over
        # the over chance rises with the mean, the under chance falls
        if (got < p) != under:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def leg_chance(
    pregame_p: float, k: int, under: bool, now: int | None, frac_left: float, left: float | None = None
) -> float:
    """Chance this leg lands given `now` so far and `frac_left` (0..1) of the game still to play."""
    now = now or 0
    if now >= k:
        return 0.0 if under else 1.0
    frac_left = min(max(frac_left, 0.0), 1.0)
    # `left`: player-aware share of the full-game mean still to come (see player_left)
    rest = implied_mean(pregame_p, k, under) * (frac_left if left is None else max(left, 0.0))
    need = k - now
    if under:
        return _cdf(rest, need - 1)  # rest <= (k - 1) - now
    return 1 - _cdf(rest, need - 1)  # rest >= k - now


FULL_MIN = 34.0  # fallback expected full-game minutes for a player


def player_left(g: dict, fl: float, track: dict) -> tuple[float, str]:
    """(effective share of a 48 minute game still to play for this player, why). Falls back to
    the game clock `fl` when the box score gave nothing about him. Never raises."""
    try:
        if g.get("dnp") or g.get("ejected") or (g.get("pf") or 0) >= 6:
            why = "did not play" if g.get("dnp") else "ejected" if g.get("ejected") else "fouled out"
            return 0.0, why
        mins = g.get("min")
        elapsed = 48.0 * (1 - fl)
        if not isinstance(mins, (int, float)) or elapsed < 6:
            rem, why = FULL_MIN * fl, ""  # same as scaling by the clock
        else:
            share = min(max(mins / elapsed, 0.0), 1.0)
            rem, why = share * 48.0 * fl, ""
        mult, tags = 1.0, []
        margin, period = track.get("margin"), track.get("period") or 0
        if isinstance(margin, (int, float)):
            m = abs(margin)
            late3 = period == 3 and (track.get("clock_s") or 720) <= 180
            big = (period >= 4 and m >= 20) or (late3 and m >= 25)
            if big and (g.get("starter") or not isinstance(mins, (int, float)) or mins >= 12):
                mult *= 0.15 if (period >= 4 and m >= 30) else 0.35
                tags.append("blowout")
        if (g.get("pf") or 0) == 5:
            mult *= 0.6
            tags.append("5 fouls")
        if g.get("active") is False:
            mult *= 0.8
            tags.append("on bench")
        rem *= mult
        if tags:
            why = f"{rem:.0f} min left for him ({', '.join(tags)})"
        return min(max(rem / FULL_MIN, 0.0), 1.5), why
    except (TypeError, ValueError):
        return fl, ""


def frac_left(state: str, period: int | None, clock_s: float | None) -> float:
    """Share of a 48 minute game left: 1 before tip-off, 0 after, else from period and clock.
    Overtime periods are 5 minutes."""
    if state == "pre":
        return 1.0
    if state == "post" or not period:
        return 0.0 if state == "post" else 1.0
    clock_s = max(clock_s or 0.0, 0.0)
    if period <= 4:
        return min(1.0, (clock_s + (4 - period) * 720) / GAME_SECS)
    return min(clock_s, 300.0) / GAME_SECS


def pregame_legs(placed: dict, n: int) -> tuple[list[float | None], bool]:
    """Pre-game chance per leg: the ones stored at place time, else 1/price^(1/n) (approx)."""
    stored = [g.get("chance") for g in (placed.get("legs") or []) if isinstance(g, dict)]
    if len(stored) == n and all(isinstance(c, (int, float)) and 0 < c < 1 for c in stored):
        return [float(c) for c in stored], False
    price = placed.get("price")
    if price and price > 1 and n:
        return [(1 / price) ** (1 / n)] * n, True
    return [None] * n, True


def bet_live(track: dict | None, placed: dict) -> dict:
    """{"p": bet chance, "legs": [chance per leg], "approx": bool, "live": bool}. p is the
    pre-game chance before tip-off, a live estimate in play, 0 if a leg failed, 1 if all hit."""
    legs = (track or {}).get("legs") or []
    n = len(legs) or len(placed.get("legs") or [])
    pre, approx = pregame_legs(placed, n)
    if not legs:
        known = [c for c in pre if c is not None]
        p = math.prod(known) if known and len(known) == len(pre) else None
        return {"p": p, "legs": pre, "approx": approx, "live": False}
    state = track.get("state", "pre")
    fl = track.get("frac_left")
    if fl is None:
        fl = frac_left(state, track.get("period"), track.get("clock_s"))
    out, why = [], []
    for g, p0 in zip(legs, pre, strict=False):
        w = ""
        if g.get("ok") is False:
            out.append(0.0)
        elif g.get("ok") is True:
            out.append(1.0)
        elif p0 is None:
            out.append(None)
        elif state == "pre":
            out.append(p0)
        else:
            left, w = player_left(g, fl, track)
            out.append(leg_chance(p0, g["k"], g["under"], g.get("now"), fl, left))
        why.append(w)
    known = None not in out
    return {
        "p": math.prod(out) if known else None,
        "legs": out,
        "approx": approx,
        "live": state == "in",
        "why": why,
    }
