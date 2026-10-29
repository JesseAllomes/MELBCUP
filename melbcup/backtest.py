"""Backtest the model on resulted races and look for patterns winners share.

Input: a list of ``(Race, {number: (sp, position)})`` built from pre-race data (Racing
Australia acceptances + FormFav form, which is point-in-time) and the official result.

Three questions:
1. **Accuracy.** How well do the form model, FormFav's model, the market (starting prices) and
   the blend rank the winner? Measured by log loss on the winner and top-pick strike rate.
2. **Weights.** Fit the factor weights by maximum likelihood (conditional logit, one choice per
   race: the winner), with an L2 penalty, validated on races the fit never saw.
3. **Patterns ("the special sauce").** For yes/no patterns (a gear change, a weight drop,
   first-up, a class drop...), compare wins *actually* landed with wins the market *expected*
   (A/E). A/E above 1 means the market under-rates the pattern: that is where value lives.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass, replace

from melbcup.domain import PersonStats, Race, Runner, StatLine
from melbcup.model import probability
from melbcup.model.features import FACTORS, raw_factors, runs_since_spell
from melbcup.model.probability import blend

Result = dict[int, tuple[float | None, int | None]]


# --- market and outcomes -------------------------------------------------------------------


def sp_probs(result: Result, starters: set[int]) -> dict[int, float]:
    """Margin-free market probabilities from starting prices; {} if any starter lacks an SP."""
    inv = {n: 1.0 / sp for n, (sp, _) in result.items() if n in starters and sp and sp > 1}
    if set(inv) != starters:
        return {}
    total = sum(inv.values())
    return {n: v / total for n, v in inv.items()}


def winner(result: Result) -> int | None:
    wins = [n for n, (_, pos) in result.items() if pos == 1]
    return wins[0] if len(wins) == 1 else None  # skip dead heats


def _minus(line: StatLine | None, won: bool, placed: bool) -> StatLine | None:
    if line is None or line.starts <= 1:
        return None
    return StatLine(line.starts - 1, max(0, line.wins - won), max(0, line.top3 - placed))


def _without_this_race(stats: PersonStats | None, won: bool, placed: bool) -> PersonStats | None:
    """Jockey/trainer figures are fetched today, so they already include this race. Take it
    back out, or a winning trainer is credited with the very win being predicted."""
    if stats is None:
        return None
    return replace(
        stats,
        overall=_minus(stats.overall, won, placed),
        at_track=_minus(stats.at_track, won, placed),
        recent=_minus(stats.recent, won, placed),
    )


def remove_result_leak(race: Race, result: Result) -> None:
    for r in race.runners:
        pos = result.get(r.number, (None, None))[1]
        won, placed = pos == 1, pos is not None and pos <= 3
        r.jockey_stats = _without_this_race(r.jockey_stats, won, placed)
        r.trainer_stats = _without_this_race(r.trainer_stats, won, placed)


@dataclass
class Sample:
    race: Race
    result: Result
    winner: int
    market: dict[int, float]
    z: dict[int, dict[str, float]]  # standardised factors per starter


def prepare(data: list[tuple[Race, Result]]) -> list[Sample]:
    out = []
    for race, result in data:
        starters = {r.number for r in race.starters}
        w = winner(result)
        market = sp_probs(result, starters)
        if w is None or w not in starters or not market or len(starters) < 4:
            continue
        remove_result_leak(race, result)
        out.append(Sample(race, result, w, market, probability._zscores(raw_factors(race))))
    return out


# --- accuracy ------------------------------------------------------------------------------


def model_from_weights(s: Sample, weights: dict[str, float], scale: float) -> dict[int, float]:
    scores = {n: sum(weights.get(k, 0.0) * v for k, v in zs.items()) for n, zs in s.z.items()}
    top = max(scores.values())
    exp = {n: math.exp(scale * (v - top)) for n, v in scores.items()}
    total = sum(exp.values())
    return {n: v / total for n, v in exp.items()}


def feed_probs(s: Sample) -> dict[int, float]:
    feed = {r.number: r.feed_win_prob for r in s.race.starters if r.feed_win_prob is not None}
    if len(feed) != len(s.z):
        return {}
    total = sum(feed.values())
    return {n: p / total for n, p in feed.items()} if total else {}


@dataclass
class Score:
    name: str
    races: int
    log_loss: float  # mean -log p(winner); lower is better
    top_pick: float  # share of races where the top-rated runner won
    uniform: float  # log loss of picking at random, for scale


def score(name: str, samples: list[Sample], probs: Callable[[Sample], dict[int, float]]) -> Score:
    ll, hits, uni, n = 0.0, 0, 0.0, 0
    for s in samples:
        p = probs(s)
        if not p:
            continue
        n += 1
        ll -= math.log(max(p.get(s.winner, 0.0), 1e-6))
        uni += math.log(len(p))
        hits += max(p, key=p.get) == s.winner
    return Score(
        name, n, ll / n if n else math.nan, hits / n if n else math.nan, uni / n if n else math.nan
    )


def default_weights() -> dict[str, float]:
    return {f.key: f.weight for f in FACTORS}


def compare(
    samples: list[Sample], weights: dict[str, float] | None = None, scale: float | None = None
) -> list[Score]:
    w = weights or default_weights()
    sc = probability.SOFTMAX_SCALE if scale is None else scale

    def model(s: Sample) -> dict[int, float]:
        return model_from_weights(s, w, sc)

    def blended(s: Sample) -> dict[int, float]:
        return blend({"market": s.market, "feed": feed_probs(s), "model": model(s)})

    return [
        score("Form model", samples, model),
        score("FormFav model", samples, feed_probs),
        score("Market (SP)", samples, lambda s: s.market),
        score("Blend", samples, blended),
    ]


# --- fitting weights ------------------------------------------------------------------------


def fit_weights(
    samples: list[Sample],
    l2: float = 2.0,
    steps: int = 400,
    lr: float = 0.5,
    offset_market: bool = False,
) -> dict[str, float]:
    """Conditional logit by gradient ascent. With ``offset_market`` the market's log-odds are a
    fixed offset, so the weights learn only what the market misses (the residual edge)."""
    keys = [f.key for f in FACTORS]
    w = dict.fromkeys(keys, 0.0)
    for _ in range(steps):
        grad = dict.fromkeys(keys, 0.0)
        for s in samples:
            scores = {}
            for n, zs in s.z.items():
                v = sum(w[k] * zs.get(k, 0.0) for k in keys)
                if offset_market:
                    v += math.log(max(s.market[n], 1e-6))
                scores[n] = v
            top = max(scores.values())
            exp = {n: math.exp(v - top) for n, v in scores.items()}
            total = sum(exp.values())
            for k in keys:
                expected = sum(exp[n] / total * s.z[n].get(k, 0.0) for n in s.z)
                grad[k] += s.z[s.winner].get(k, 0.0) - expected
        for k in keys:
            w[k] += lr * (grad[k] - l2 * w[k]) / len(samples)
    return w


def split_by_day(samples: list[Sample], test_share: float = 0.3, seed: int = 1):
    days = sorted({s.race.race_date for s in samples})
    rng = random.Random(seed)
    test_days = set(rng.sample(days, max(1, round(len(days) * test_share))))
    train = [s for s in samples if s.race.race_date not in test_days]
    test = [s for s in samples if s.race.race_date in test_days]
    return train, test


def best_scale(samples: list[Sample], weights: dict[str, float]) -> float:
    grid = [x / 10 for x in range(3, 41)]
    return min(
        grid,
        key=lambda sc: score("", samples, lambda s: model_from_weights(s, weights, sc)).log_loss,
    )


def fit_mix(samples: list[Sample], weights: dict[str, float], scale: float) -> dict[str, float]:
    """Grid-search the blend exponents for market, FormFav model and form model."""
    cache = [(s, feed_probs(s), model_from_weights(s, weights, scale)) for s in samples]
    grid = [x / 20 for x in range(0, 25)]
    best, best_ll = dict(probability.BLEND), math.inf
    for m in grid:
        for f in grid:
            for d in grid:
                if m + f + d == 0 or m + f + d > 1.6:
                    continue
                mix = {"market": m, "feed": f, "model": d}
                ll = 0.0
                for s, feed, model in cache:
                    p = blend({"market": s.market, "feed": feed, "model": model}, mix)
                    ll -= math.log(max(p.get(s.winner, 0.0), 1e-6))
                if ll < best_ll:
                    best, best_ll = mix, ll
    return best


# --- patterns -------------------------------------------------------------------------------


Pattern = Callable[[Runner, Race], bool | None]


def _first_time_gear(r: Runner, race: Race) -> bool | None:
    return None if r.gear_changes is None else "FIRST TIME" in r.gear_changes.upper()


def _blinkers_on(r: Runner, race: Race) -> bool | None:
    g = (r.gear_changes or "").upper()
    return ("BLINKERS FIRST TIME" in g or "BLINKERS ON" in g) if r.gear_changes else False


def _weight_drop(kg: float) -> Pattern:
    def fn(r: Runner, race: Race) -> bool | None:
        if r.weight_kg is None or r.last_start_weight_kg is None:
            return None
        return (r.last_start_weight_kg - (r.weight_kg - (r.claim_kg or 0))) >= kg

    return fn


def _rating_drop(r: Runner, race: Race) -> bool | None:
    """Running in a race rated below the runner's last start (class drop by rating)."""
    if r.hcp_rating is None or r.last_start_rating is None:
        return None
    return r.hcp_rating < r.last_start_rating


def _last_start(pred: Callable[[int], bool]) -> Pattern:
    def fn(r: Runner, race: Race) -> bool | None:
        pos = r.last_start_position
        if pos is None:
            figs = [c for c in (r.last10 or "") if c.isdigit()]
            pos = (10 if figs[-1] == "0" else int(figs[-1])) if figs else None
        return None if pos is None else pred(pos)

    return fn


def _spell(n: int) -> Pattern:
    def fn(r: Runner, race: Race) -> bool | None:
        s = runs_since_spell(r)
        return None if s is None else s == n

    return fn


def _days(lo: int, hi: int) -> Pattern:
    def fn(r: Runner, race: Race) -> bool | None:
        if r.last_start_date is None:
            return None
        return lo <= (race.race_date - r.last_start_date).days <= hi

    return fn


def _rate(attr: str, scope: str, at_least: float, min_starts: int) -> Pattern:
    def fn(r: Runner, race: Race) -> bool | None:
        stats = getattr(r, attr)
        line = getattr(stats, scope) if stats else None
        if line is None or line.starts < min_starts:
            return None
        return line.wins / line.starts >= at_least

    return fn


def _record(attr: str, *, won: bool) -> Pattern:
    def fn(r: Runner, race: Race) -> bool | None:
        line = getattr(r, attr)
        if line is None:
            return None
        return line.wins > 0 if won else line.starts > 0 and line.wins == 0

    return fn


def _barrier(lo: int, hi: int, min_field: int = 12) -> Pattern:
    def fn(r: Runner, race: Race) -> bool | None:
        if r.barrier is None or len(race.starters) < min_field:
            return None
        return lo <= r.barrier <= hi

    return fn


def _top_rated(r: Runner, race: Race) -> bool | None:
    ratings = [x.hcp_rating for x in race.starters if x.hcp_rating]
    return None if not r.hcp_rating or not ratings else r.hcp_rating == max(ratings)


def _leader(r: Runner, race: Race) -> bool | None:
    return None if r.settling_position is None else r.settling_position <= 2


def _feed_top(r: Runner, race: Race) -> bool | None:
    probs = {x.number: x.feed_win_prob for x in race.starters if x.feed_win_prob is not None}
    return None if r.number not in probs else r.number == max(probs, key=probs.get)


def _sex(*codes: str) -> Pattern:
    def fn(r: Runner, race: Race) -> bool | None:
        return None if not r.sex else r.sex.lower() in codes

    return fn


PATTERNS: dict[str, Pattern] = {
    "Gear change first time": _first_time_gear,
    "Blinkers on first time": _blinkers_on,
    "Weight drop 2kg+ from last start": _weight_drop(2.0),
    "Weight drop 3.5kg+ from last start": _weight_drop(3.5),
    "Drops in rating from last start": _rating_drop,
    "Won last start": _last_start(lambda p: p == 1),
    "Placed last start (2nd-3rd)": _last_start(lambda p: p in (2, 3)),
    "Unplaced last start (4th+)": _last_start(lambda p: p >= 4),
    "First up from a spell": _spell(0),
    "Second up": _spell(1),
    "Third up": _spell(2),
    "Backing up within 7 days": _days(0, 7),
    "8-21 days since last run": _days(8, 21),
    "22-42 days since last run": _days(22, 42),
    "Has won at the track": _record("track", won=True),
    "Has won at the distance": _record("distance", won=True),
    "Has won on the going": _record("going", won=True),
    "Raced at distance, never won": _record("distance", won=False),
    "Jockey 18%+ wins last 90 days": _rate("jockey_stats", "recent", 0.18, 20),
    "Trainer 18%+ wins last 90 days": _rate("trainer_stats", "recent", 0.18, 20),
    "Jockey 15%+ wins at track": _rate("jockey_stats", "at_track", 0.15, 20),
    "Barrier 1-4 (12+ runners)": _barrier(1, 4),
    "Barrier 12+ (12+ runners)": _barrier(12, 30),
    "Top handicap rating in field": _top_rated,
    "Speed map: leads or on pace": _leader,
    "FormFav model's top pick": _feed_top,
    "Mare or filly": _sex("mare", "filly"),
}


@dataclass
class PatternStat:
    name: str
    runners: int
    wins: int
    expected: float  # wins the market (SP) expected
    strike: float
    ae: float  # actual / expected
    z: float  # how surprising A-E is if the market were right
    roi_sp: float  # level $1 stakes at SP


def patterns(samples: list[Sample]) -> list[PatternStat]:
    out = []
    for name, fn in PATTERNS.items():
        n = wins = 0
        exp = var = ret = 0.0
        for s in samples:
            for r in s.race.starters:
                if r.number not in s.market or not fn(r, s.race):
                    continue
                p = s.market[r.number]
                won = r.number == s.winner
                n += 1
                wins += won
                exp += p
                var += p * (1 - p)
                sp = s.result[r.number][0] or 0.0
                ret += (sp if won else 0.0) - 1.0
        if n < 30:
            continue
        out.append(
            PatternStat(
                name,
                n,
                wins,
                exp,
                wins / n,
                wins / exp if exp else math.nan,
                (wins - exp) / math.sqrt(var) if var else 0.0,
                ret / n,
            )
        )
    return sorted(out, key=lambda p: p.ae, reverse=True)


# --- value-bet simulation -------------------------------------------------------------------


def value_bets_at_sp(
    samples: list[Sample], weights: dict[str, float], scale: float, edge: Callable[[float], float]
) -> tuple[int, int, float]:
    """Level $1 win bets where the blend beats SP by the app's value bar. Market in the blend is
    the SP itself, so this is a conservative proxy: on the day the app compares with the best
    fixed price, usually longer than SP."""
    bets = wins = 0
    ret = 0.0
    for s in samples:
        p = blend(
            {
                "market": s.market,
                "feed": feed_probs(s),
                "model": model_from_weights(s, weights, scale),
            }
        )
        for n, prob in p.items():
            sp = s.result[n][0]
            if not sp or prob < 0.04 or prob * sp - 1 < edge(sp):
                continue
            bets += 1
            won = n == s.winner
            wins += won
            ret += (sp if won else 0.0) - 1.0
    return bets, wins, ret
