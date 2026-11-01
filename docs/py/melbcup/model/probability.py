"""From factors to probabilities.

1. Each factor is standardised within the race (z-score); a runner missing a factor scores 0.
2. Weighted sum -> softmax gives the form model's win probability.
3. Production: with prices, a runner's chance is the margin-free bookmaker consensus alone,
   corrected for the favourite-long-shot bias (consensus ** MARKET_ALPHA, renormalised); the
   form model is used only before any prices exist, and is experimental. Its weights were fitted
   on one month that also shaped the design, with jockey and trainer figures that include later
   races, so it must not move priced chances until a clean, frozen test says it helps. BLEND
   (market 1.0, form 0.3) is kept for research only.
4. Finishing-order probabilities use Harville with the Lo/Bacon-Shone discount, which corrects
   Harville's known over-rating of long shots for the minor placings.
"""

from __future__ import annotations

import math
import random
from bisect import bisect
from dataclasses import dataclass, field
from itertools import accumulate, permutations

from melbcup.domain import Race
from melbcup.model.features import FACTORS, raw_factors

SOFTMAX_SCALE = 1.0
BLEND = {"market": 1.0, "feed": 0.0, "model": 0.3}
# Favourite-long-shot correction: a runner's chance is the margin-free consensus raised to this
# power and renormalised. The market under-rates favourites and over-rates long shots; 1.14 is
# the frozen value of research/RERUN.md, fitted on 2023-2025 and proven on tune2, the sealed
# block and the forward month (+0.005 to +0.008 nats per race at every T). On the race card's
# own pick rules (research/M7_RESULTS.md) it cut the win pick's loss by 4 to 10 points on every
# block it was not fitted on, because "closest to fair" at alpha 1 lands on $12-21 runners whose
# true chance is 25% below the market's.
MARKET_ALPHA = 1.14
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


def corrected_market(market: dict[int, float], alpha: float = MARKET_ALPHA) -> dict[int, float]:
    """The margin-free market with the favourite-long-shot correction: p ** alpha, renormalised."""
    return _normalise({n: max(p, 0.0) ** alpha for n, p in market.items()})


def model_probs(race: Race) -> tuple[dict[int, float], dict[int, dict[str, float]]]:
    """Form model win probabilities and each runner's weighted factor contributions."""
    z = _zscores(raw_factors(race))
    contrib = {n: {k: _WEIGHTS[k] * v for k, v in zs.items()} for n, zs in z.items()}
    scores = {n: sum(c.values()) for n, c in contrib.items()}
    if not scores:
        return {}, {}
    top = max(scores.values())
    return _normalise({n: math.exp(SOFTMAX_SCALE * (s - top)) for n, s in scores.items()}), contrib


def blend(
    components: dict[str, dict[int, float]], weights: dict[str, float] | None = None
) -> dict[int, float]:
    """Weighted geometric mean of the available probability sets, renormalised.

    With every weighted source present the fitted exponents apply as they are (their total may
    exceed 1, which sharpens). When one is missing, the rest are averaged with weights summing
    to 1, so a lone source is used as it stands rather than sharpened by weight meant for
    another."""
    weights = weights or BLEND
    wanted = {k for k, w in weights.items() if w > 0}
    present = {k: v for k, v in components.items() if v and k in wanted}
    if not present:
        return {}
    scale = 1.0 if wanted <= set(present) else 1.0 / sum(weights[k] for k in present)
    runners = set.intersection(*(set(v) for v in present.values()))
    logp = {}
    for n in runners:
        logp[n] = sum(weights[k] * scale * math.log(max(v[n], 1e-6)) for k, v in present.items())
    top = max(logp.values())
    return _normalise({n: math.exp(lp - top) for n, lp in logp.items()})


def order_probs(
    win: dict[int, float], depth: int, discount: tuple[float, ...] = DISCOUNT
) -> dict[tuple[int, ...], float]:
    """Probability of every exact finishing order of length ``depth`` (discounted Harville).

    ``discount`` is the exponent per place (the last one repeats); the default is the app's own."""
    depth = min(depth, len(win))
    if depth == 0:
        return {}
    powered = [
        {n: p ** discount[min(i, len(discount) - 1)] for n, p in win.items()} for i in range(depth)
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
    counts = dict.fromkeys(win, 0)
    for place in simulate_positions(win, k, sims=SIMULATIONS, seed=seed):
        for n, c in place.items():
            counts[n] += c
    return counts


def simulate_positions(
    win: dict[int, float],
    depth: int,
    *,
    sims: int = SIMULATIONS,
    seed: int = 7,
    discount: tuple[float, ...] = DISCOUNT,
) -> list[dict[int, int]]:
    """Seeded Monte Carlo of the first ``depth`` places: element i counts, per runner, the draws
    in which it finished (i+1)-th. The law is the discounted Harville of ``order_probs``: each
    place is drawn from the strengths ``p ** discount[i]`` of the runners still to be placed.
    A draw from all the strengths, redrawn when it lands on a placed runner, is exactly a draw
    from those still to be placed, and lets each place be drawn for every simulation in one go.
    Runners with no chance are never placed, so fewer than ``depth`` lists may come back."""
    runners = [n for n, p in win.items() if p > 0]
    depth = min(depth, len(runners))
    counts = [[0] * len(runners) for _ in range(depth)]
    if depth > 0:
        rng = random.Random(seed)
        cum = [
            list(accumulate(win[n] ** discount[min(i, len(discount) - 1)] for n in runners))
            for i in range(depth)
        ]
        index = range(len(runners))
        draws = [rng.choices(index, cum_weights=cum[i], k=sims) for i in range(depth)]
        last = len(runners) - 1
        for s in range(sims):
            placed: set[int] = set()
            for i in range(depth):
                j = draws[i][s]
                while j in placed:
                    j = bisect(cum[i], rng.random() * cum[i][-1], 0, last)
                placed.add(j)
                counts[i][j] += 1
    by_runner = {n: i for i, n in enumerate(runners)}
    return [{n: (c[by_runner[n]] if n in by_runner else 0) for n in win} for c in counts]


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
    if market:
        win, sources = corrected_market(market), ["market"]
    else:  # no prices yet: the experimental form model, until prices arrive
        win, sources = (
            (_normalise(dict(model)), ["form model (experimental)"]) if model else ({}, [])
        )
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
