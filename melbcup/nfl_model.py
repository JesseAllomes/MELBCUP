"""NFL player-prop model at runtime: pure Python, no numpy (it runs in the Azure Function).

Parameters and same-game correlations are fitted offline (tools/nfl/props.py, correlation.py) and live
in melbcup/nfl_fit.py.  Player means come from data/nfl/means.json, refreshed by a token-free script:

    python tools/nfl/history.py && python tools/nfl/means.py

Chance: the same negative-binomial tail + logistic calibration as the NBA legs (nba_legs.chance), with
variance mu*(s0 + b*mu).  It is blended with the market at BLEND_W (the model's weight in logit space).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import nba_legs as N
from . import nfl_fit as F

# No historical NFL prop prices exist in free data, so the weight cannot be fitted yet: 0.25 model is a
# conservative prior (NBA's real-price test chose 0).  tools/nfl/blend_fit.py refits it from the forward
# log of catalogue snapshots + settled outcomes as that accrues.
BLEND_W = 0.25
MIN_CORR = F.MIN_CORR
CORR = F.CORR
PARAMS = F.PARAMS
BUNDLED = Path(__file__).resolve().parents[1] / "data" / "nfl" / "means.json"
_means: dict = {}


def means() -> dict:
    """{normalised name: {team, pos, mu: {stat: mean}}} (empty if the file is missing)."""
    if not _means:
        try:
            _means.update(json.loads(Path(os.environ.get("NFL_MEANS", BUNDLED)).read_text())["players"])
        except (OSError, ValueError, KeyError):
            pass
    return _means


def player(name: str) -> dict | None:
    return means().get(N.norm(name))


def mean_chance(mu: float, stat: str, k: int) -> float | None:
    """Model chance of k or more of `stat` for a player averaging `mu` a game."""
    q = PARAMS.get(stat)
    if q is None or mu is None:
        return None
    return N.chance(mu, q["s0"] + q["b"] * mu, q["ca"], q["cb"], k)


def model_chance(name: str, stat: str, k: int, under: bool = False) -> tuple[float, dict] | None:
    """(chance the bet wins, the player record) or None when the model has no mean for this bet."""
    p = player(name)
    if not p or stat not in p["mu"]:
        return None
    c = mean_chance(p["mu"][stat], stat, k)
    return None if c is None else (1 - c if under else c, p)


def rho(a: dict, b: dict) -> float:
    """Correlation between two legs' normal scores (sign flipped when exactly one is an under)."""
    if a["player"] == b["player"]:
        rel = "self"
    elif not a.get("team") or not b.get("team"):
        return 0.0  # a player the model does not know: no relation to use
    else:
        rel = "team" if a["team"] == b["team"] else "opp"
    x, y = F.SHORT.get(a.get("stat"), ""), F.SHORT.get(b.get("stat"), "")
    r = CORR.get((rel, x, y), CORR.get((rel, y, x), 0.0))
    if abs(r) < MIN_CORR:
        return 0.0
    return -r if bool(a.get("under")) != bool(b.get("under")) else r


def annotate(legs: list[dict]) -> None:
    """Fill each leg's team and model chance from the player means (in place; no mean leaves them)."""
    for g in legs:
        hit = model_chance(g["player"], g["stat"], g["line"], bool(g["under"]))
        if hit is None:
            continue
        g["model"] = round(hit[0], 4)
        g["team"] = hit[1]["team"]
        g["expected"] = hit[1]["mu"][g["stat"]]


def blend(model: float, market: float | None) -> float:
    return N.blend(model, market, BLEND_W)


__all__ = ["BLEND_W", "CORR", "annotate", "blend", "mean_chance", "model_chance", "rho"]
