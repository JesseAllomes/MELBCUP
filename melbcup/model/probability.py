"""From factors to probabilities.

1. Each factor is standardised within the race (z-score); a runner missing a factor scores 0.
2. Weighted sum -> softmax gives the form model's win probability.
3. Log-linear blend with FormFav's model and the margin-free bookmaker consensus.
4. Finishing-order probabilities use Harville with the Lo/Bacon-Shone discount, which corrects
   Harville's known over-rating of long shots for the minor placings.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from itertools import permutations

from melbcup.domain import Race
from melbcup.model.features import FACTORS, raw_factors

SOFTMAX_SCALE = 0.9
BLEND = {"market": 0.5, "feed": 0.25, "model": 0.25}
# Harville discount exponents for 1st, 2nd, 3rd, 4th place.
DISCOUNT = (1.0, 0.81, 0.65, 0.55)
EXACT_LIMIT = 15_000  # enumerate finishing orders up to this many; simulate beyond it
SIMULATIONS = 40_000

_LABELS = {f.key: f.label for f in FACTORS}
_WEIGHTS = {f.key: f.weight for f in FACTORS}


@dataclass
class Assessment:
    number: int
    win: float
    place: float
    model_win: float
    feed_win: float | None
    market_win: float | None
    reasons_for: list[str] = field(default_factory=list)
    reasons_against: list[str] = field(default_factory=list)


@dataclass
class RaceModel:
    race: Race
    runners: dict[int, Assessment]
    sources: list[str]

    def win_probs(self) -> dict[int, float]:
        return {n: a.win for n, a in self.runners.items()}

    def ranked(self) -> list[Assessment]:
        return sorted(self.runners.values(), key=lambda a: a.win, reverse=True)


def _zscores(raw: dict[int, dict[str, float]]) -> dict[int, dict[str, float]]:
    z: dict[int, dict[str, float]] = {n: {} for n in raw}
    for key in _WEIGHTS:
        vals = {n: v[key] for n, v in raw.items() if key in v}
        if len(vals) < 2:
            continue
        mean = sum(vals.values()) / len(vals)
        sd = math.sqrt(sum((x - mean) ** 2 for x in vals.values()) / len(vals))
        if sd < 1e-9:
            continue
        for n, x in vals.items():
            z[n][key] = max(-3.0, min(3.0, (x - mean) / sd))
    return z


def _normalise(p: dict[int, float]) -> dict[int, float]:
    total = sum(p.values())
    return {n: v / total for n, v in p.items()} if total > 0 else {}


def model_probs(race: Race) -> tuple[dict[int, float], dict[int, dict[str, float]]]:
    """Form model win probabilities and each runner's weighted factor contributions."""
    z = _zscores(raw_factors(race))
    contrib = {n: {k: _WEIGHTS[k] * v for k, v in zs.items()} for n, zs in z.items()}
    scores = {n: sum(c.values()) for n, c in contrib.items()}
    if not scores:
        return {}, {}
    top = max(scores.values())
    return _normalise({n: math.exp(SOFTMAX_SCALE * (s - top)) for n, s in scores.items()}), contrib


def blend(components: dict[str, dict[int, float]]) -> dict[int, float]:
    """Weighted geometric mean of the available probability sets, renormalised."""
    present = {k: v for k, v in components.items() if v}
    if not present:
        return {}
    total_w = sum(BLEND[k] for k in present)
    runners = set.intersection(*(set(v) for v in present.values()))
    logp = {}
    for n in runners:
        logp[n] = sum(BLEND[k] / total_w * math.log(max(v[n], 1e-6)) for k, v in present.items())
    top = max(logp.values())
    return _normalise({n: math.exp(lp - top) for n, lp in logp.items()})


def order_probs(win: dict[int, float], depth: int) -> dict[tuple[int, ...], float]:
    """Probability of every exact finishing order of length ``depth`` (discounted Harville)."""
    depth = min(depth, len(win))
    if depth == 0:
        return {}
    powered = [
        {n: p ** DISCOUNT[min(i, len(DISCOUNT) - 1)] for n, p in win.items()} for i in range(depth)
    ]
    out: dict[tuple[int, ...], float] = {}
    for combo in permutations(win, depth):
        prob = 1.0
        used: set[int] = set()
        for i, n in enumerate(combo):
            pw = powered[i]
            denom = sum(v for m, v in pw.items() if m not in used)
            prob *= pw[n] / denom
            used.add(n)
        out[combo] = prob
    return out


def _n_orders(n: int, depth: int) -> int:
    return math.perm(n, min(depth, n))


def top_k_probs(win: dict[int, float], k: int, *, seed: int = 7) -> dict[int, float]:
    """P(runner finishes in the first k)."""
    if k >= len(win):
        return dict.fromkeys(win, 1.0)
    if _n_orders(len(win), k) <= EXACT_LIMIT:
        acc = dict.fromkeys(win, 0.0)
        for combo, p in order_probs(win, k).items():
            for n in combo:
                acc[n] += p
        return acc
    return {n: c / SIMULATIONS for n, c in _simulate_counts(win, k, seed).items()}


def _simulate_counts(win: dict[int, float], k: int, seed: int) -> dict[int, int]:
    rng = random.Random(seed)
    counts = dict.fromkeys(win, 0)
    runners = list(win)
    for _ in range(SIMULATIONS):
        remaining = runners[:]
        for i in range(k):
            exp = DISCOUNT[min(i, len(DISCOUNT) - 1)]
            weights = [win[n] ** exp for n in remaining]
            pick = rng.choices(remaining, weights)[0]
            counts[pick] += 1
            remaining.remove(pick)
    return counts


def assess(race: Race) -> RaceModel:
    starters = race.starters
    numbers = {r.number for r in starters}
    model, contrib = model_probs(race)
    feed = _normalise({r.number: r.feed_win_prob for r in starters if r.feed_win_prob is not None})
    if len(feed) < len(starters):
        feed = {}
    market = _normalise(
        {
            n: p.consensus_prob
            for n, p in race.prices.items()
            if p.consensus_prob is not None and n in numbers
        }
    )
    if len(market) < len(starters):
        market = {}
    win = blend({"market": market, "feed": feed, "model": model})
    sources = [name for name, v in (("market", market), ("feed", feed), ("model", model)) if v]
    place = top_k_probs(win, race.places_paid) if win else {}

    runners = {}
    for n, p in win.items():
        c = contrib.get(n, {})
        ranked = sorted(c.items(), key=lambda kv: kv[1], reverse=True)
        runners[n] = Assessment(
            number=n,
            win=p,
            place=place.get(n, 0.0),
            model_win=model.get(n, 0.0),
            feed_win=feed.get(n),
            market_win=market.get(n),
            reasons_for=[_LABELS[k] for k, v in ranked[:3] if v > 0.05],
            reasons_against=[_LABELS[k] for k, v in reversed(ranked[-3:]) if v < -0.05],
        )
    return RaceModel(race=race, runners=runners, sources=sources)
