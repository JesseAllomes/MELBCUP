"""Offers check: is a bookmaker offer worth taking, and for how many dollars?

The owner sees an offer in the Sportsbet or Ladbrokes app (each-way terms, a place-only price, a
money-back promotion, a boosted price). This module prices it. Advice only: nothing is placed.

Chances come from the agreed model: the margin-free consensus win chances, then finishing-order
chances by Harville with the Lo/Bacon-Shone discount (``probability.DISCOUNT``), enumerated
exactly where ``probability.EXACT_LIMIT`` allows and simulated (seeded, 200,000 draws, with its
standard error) beyond it. Every offer is priced under six chance scenarios and the WORST is
what decides; see ``SCENARIOS``. A BET needs that worst expected value to clear a buffer.
Dead heats are treated as neutral in expectation (the dead-heat reduction on a tied place
is, on average, offset by the tied winners it comes with).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

from melbcup.bets.staking import KELLY_FRACTION, MAX_SHARE_PER_BET
from melbcup.model import probability
from melbcup.model.probability import DISCOUNT, RaceModel, order_probs, simulate_positions

# A BET needs the worst-case EV to be at least this share of the total outlay. The model is
# not perfect (two rounds of research found no edge over the price except the 4th place), so a
# thin positive EV is more likely a model error than a bargain. A constant, not a setting.
MIN_EV_BUFFER = 0.02

PLACES = 5  # finishing positions reported: 1st to 5th
MC_DRAWS = 200_000  # simulation size when exact enumeration is over the limit
MC_SEED = 7  # the app's own seed for place simulations
SE_MULTIPLE = 2.0  # scenario "mc_2se": chances lowered by this many standard errors

# Favourite-longshot correction: chance proportional to (1 / price) ** 1.14, renormalised.
# The one calibration gain research/RERUN.md proved; the app itself keeps exponent 1.0.
FLB_ALPHA = 1.14

# Discount exponents for 1st, 2nd, 3rd, 4th (and 5th, which repeats the 4th). The app uses
# (1.0, 0.81, 0.65, 0.55); research/v2/CUP_TRENDS_2.md fitted (1.0, 0.80, 0.65, 0.60) on 1,093
# staying races. No standard errors were published, so the band below is an ASSUMPTION: about
# +-0.05 on 2nd (0.76-0.86) and 0.60-0.70 on 3rd-4th. The app's own and the research values
# are both inside it, except the app's 4th (0.55), which scenario "consensus" still covers.
DISCOUNT_LOW = (1.0, 0.76, 0.60, 0.60)
DISCOUNT_HIGH = (1.0, 0.86, 0.70, 0.70)

# What a bonus bet is worth per dollar of face value. A bonus bet pays its winnings, not its
# stake, so on a runner at price O with fair chance p and a bookmaker margin m it returns
# p * (O - 1) = (1 - 1/O) / (1 + m) of face. At m = 15%: $3 -> 0.58, $4 -> 0.65, $5 -> 0.70,
# $6 -> 0.72, $10 -> 0.78. So $3-$6 gives about 0.58-0.72 and 0.70 is the $5 case, in the upper
# half of that range: the lower end is about 0.6. The default is the owner's; the break-even c in
# every money-back result says how low a bonus bet's value can go before the offer stops paying.
DEFAULT_BONUS_VALUE = 0.70


# --- finishing positions ----------------------------------------------------------------------


@dataclass(frozen=True)
class Positions:
    """P(runner finishes exactly k-th) for k = 1..5, each exact or simulated.

    ``by_place[k][runner]``. Places in ``simulated`` come from ``draws`` Monte Carlo draws and
    carry a binomial standard error; the rest are exact (standard error 0)."""

    by_place: dict[int, dict[int, float]]
    simulated: frozenset[int]
    draws: int

    def chance(self, runner: int, places) -> float:
        return sum(self.by_place[k].get(runner, 0.0) for k in places if k in self.by_place)

    def top(self, runner: int, k: int) -> float:
        return self.chance(runner, range(1, k + 1))

    def se(self, runner: int, places) -> float:
        """Standard error of the chance of finishing in any of ``places``. The event is one
        yes/no per draw, so its error is sqrt(q (1 - q) / draws) on the simulated part."""
        q = sum(self.by_place[k].get(runner, 0.0) for k in places if k in self.simulated)
        return math.sqrt(max(q * (1 - q), 0.0) / self.draws) if q and self.draws else 0.0

    @property
    def method(self) -> str:
        if not self.simulated:
            return "exact"
        sim = f"Monte Carlo, {self.draws:,} draws, seed {MC_SEED}"
        first = min(self.simulated)
        return sim if first == 1 else f"places 1-{first - 1} exact; places {first}+ {sim}"


def position_probs(
    win: dict[int, float],
    discount: tuple[float, ...] = DISCOUNT,
    *,
    draws: int = MC_DRAWS,
    seed: int = MC_SEED,
    places: int = PLACES,
) -> Positions:
    """Chance each runner finishes exactly 1st..5th, by the app's own discounted Harville.

    Place k is enumerated exactly (``order_probs``) when the number of finishing orders of that
    depth is within ``probability.EXACT_LIMIT``; otherwise all such places come from one seeded
    simulation (``simulate_positions``) of at least 200,000 draws. ``places`` stops at that place
    (the promos need only the first two or three, which are exact and cheap); later places are 0."""
    return _positions(
        tuple(sorted(win.items())), tuple(discount), draws, seed, probability.EXACT_LIMIT, places
    )


@lru_cache(maxsize=256)
def _positions(
    items: tuple[tuple[int, float], ...],
    discount: tuple[float, ...],
    draws: int,
    seed: int,
    limit: int,
    places: int = PLACES,
) -> Positions:
    win = dict(items)
    live = {n: p for n, p in win.items() if p > 0}
    by_place = {k: dict.fromkeys(win, 0.0) for k in range(1, PLACES + 1)}
    simulated: list[int] = []
    for k in range(1, min(PLACES, places, len(live)) + 1):
        if math.perm(len(live), k) <= limit:
            for combo, p in order_probs(live, k, discount).items():
                by_place[k][combo[-1]] += p
        else:
            simulated.append(k)
    if simulated:
        counts = simulate_positions(live, max(simulated), sims=draws, seed=seed, discount=discount)
        for k in simulated:
            for n, c in counts[k - 1].items():
                by_place[k][n] = c / draws
    return Positions(by_place, frozenset(simulated), draws if simulated else 0)


# --- offer types ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Leg:
    """One way an offer pays: the finishing places that trigger it and its profit in dollars on
    a total outlay of ``s`` dollars. Losing everything (-s) is the implied last outcome."""

    name: str
    places: frozenset[int]
    net: Callable[[float], float]


class Offer:
    """Base for the offer types. ``legs()`` lists the paying outcomes, which never overlap
    (a runner finishes in one place), so the loss chance is one minus their sum."""

    kind = ""
    step = 1  # stakes are whole dollars in multiples of this
    stake_dependent = False  # EV per dollar changes with the stake (a capped refund)

    def legs(self) -> list[Leg]:
        raise NotImplementedError

    def describe(self) -> dict:
        return {"type": self.kind}


def _check_price(price: float, name: str = "price") -> None:
    if not (math.isfinite(price) and price > 1.0):
        raise ValueError(f"{name} must be a decimal price above 1.00, got {price!r}")


def _check_places(places: int) -> None:
    if not (isinstance(places, int) and 1 <= places <= PLACES):
        raise ValueError(f"places must be a whole number from 1 to {PLACES}, got {places!r}")


def _check_fraction(fraction: float) -> None:
    if not (math.isfinite(fraction) and 0 < fraction <= 1):
        raise ValueError(f"fraction must be above 0 and at most 1 (1/4 is 0.25), got {fraction!r}")


@dataclass(frozen=True)
class EachWay(Offer):
    """Each-way: two equal stakes S, one to win, one to place. Total outlay 2S.

    The win bet pays S x price. The place bet pays S x (1 + (price - 1) x fraction) when the
    runner finishes in the first ``places``. With p1 = P(win) and Tk = P(top k), per $1 of
    outlay:  EV = 1/2 [p1 x price + Tk x (1 + (price - 1) x fraction)] - 1.

    A scratching after the bet can bring a Rule 4 deduction and change the terms; that is not
    modelled. Staked in even dollars so the two halves are equal."""

    price: float
    fraction: float
    places: int
    kind = "each_way"
    step = 2

    def __post_init__(self) -> None:
        _check_price(self.price)
        _check_fraction(self.fraction)
        _check_places(self.places)

    def legs(self) -> list[Leg]:
        gain = (self.price - 1.0) * self.fraction  # profit on a place bet of 1
        out = [Leg("win", frozenset({1}), lambda s: s / 2 * (self.price - 1.0) + s / 2 * gain)]
        if self.places >= 2:
            out.append(
                Leg("placed", frozenset(range(2, self.places + 1)), lambda s: s / 2 * (gain - 1))
            )
        return out

    def describe(self) -> dict:
        return {
            "type": self.kind,
            "price": self.price,
            "fraction": self.fraction,
            "places": self.places,
        }


@dataclass(frozen=True)
class PlaceOnly(Offer):
    """Place only: the place half of an each-way bet, for bookmakers that sell it alone.

    Pays stake x (1 + (price - 1) x fraction) when the runner finishes in the first ``places``,
    and nothing otherwise. Per $1:  EV = Tk x (1 + (price - 1) x fraction) - 1, with Tk = P(top k)
    and ``price`` the runner's win price the place terms are taken from. Rule 4 and dead
    heats as for ``EachWay``."""

    price: float
    fraction: float
    places: int
    kind = "place_only"

    def __post_init__(self) -> None:
        _check_price(self.price)
        _check_fraction(self.fraction)
        _check_places(self.places)

    def legs(self) -> list[Leg]:
        gain = (self.price - 1.0) * self.fraction
        return [Leg("placed", frozenset(range(1, self.places + 1)), lambda s: s * gain)]

    def describe(self) -> dict:
        return {
            "type": self.kind,
            "price": self.price,
            "fraction": self.fraction,
            "places": self.places,
        }


@dataclass(frozen=True)
class MoneyBack(Offer):
    """Money back as a bonus bet: a win bet at ``price`` that, if the runner finishes in
    ``positions`` (for example {2} or {2, 3}), refunds min(stake, cap) as a bonus bet.

    A bonus bet is worth ``bonus_value`` (c) per dollar of face value. Per $1 of stake S:
    EV = p1 x price + c x P(positions) x min(S, cap) / S - 1. EV is linear in c, so the break-even
    c = (1 - p1 x price) / (P(positions) x min(S, cap) / S); the offer pays only if a bonus bet is
    worth more than that. The cap makes EV per dollar fall once the stake exceeds it."""

    price: float
    positions: frozenset[int]
    cap: float | None = None
    bonus_value: float = DEFAULT_BONUS_VALUE
    kind = "money_back"
    stake_dependent = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "positions", frozenset(self.positions))
        _check_price(self.price)
        if not self.positions or not all(
            isinstance(k, int) and 2 <= k <= PLACES for k in self.positions
        ):
            raise ValueError(f"positions must be places from 2 to {PLACES}, e.g. {{2}} or {{2, 3}}")
        if self.cap is not None and not (math.isfinite(self.cap) and self.cap > 0):
            raise ValueError(f"cap must be a positive dollar amount, got {self.cap!r}")
        if not (math.isfinite(self.bonus_value) and 0.0 <= self.bonus_value <= 1.0):
            raise ValueError(f"bonus_value must be between 0 and 1, got {self.bonus_value!r}")

    def refund(self, s: float) -> float:
        """Face value of the bonus bet for a stake of ``s`` dollars."""
        return s if self.cap is None else min(s, self.cap)

    def legs(self) -> list[Leg]:
        return [
            Leg("win", frozenset({1}), lambda s: s * (self.price - 1.0)),
            Leg(
                "refund",
                frozenset(self.positions),
                lambda s: -s + self.bonus_value * self.refund(s),
            ),
        ]

    def describe(self) -> dict:
        return {
            "type": self.kind,
            "price": self.price,
            "positions": sorted(self.positions),
            "cap": self.cap,
            "bonus_value": self.bonus_value,
        }


@dataclass(frozen=True)
class PaysAsWinner(Offer):
    """Run 2nd, You Win: a win bet at ``price`` that also pays as a winner if the runner finishes
    in any of ``positions`` (default 1st or 2nd).

    The bet returns ``price`` per $1 of stake on any of those finishes, so per $1:
    EV = P(positions) x price - 1, with P(positions) = P(1st) + P(2nd). Rule 4 and dead heats as
    for ``EachWay``. A maximum stake is the bookmaker's, applied by the caller."""

    price: float
    positions: frozenset[int] = frozenset({1, 2})
    kind = "pays_as_winner"

    def __post_init__(self) -> None:
        object.__setattr__(self, "positions", frozenset(self.positions))
        _check_price(self.price)
        if 1 not in self.positions or not all(
            isinstance(k, int) and 1 <= k <= PLACES for k in self.positions
        ):
            raise ValueError(f"positions must include 1st and be places 1 to {PLACES}")

    def legs(self) -> list[Leg]:
        def net(s: float) -> float:
            return s * (self.price - 1.0)

        out = [Leg("win", frozenset({1}), net)]
        if extra := self.positions - {1}:
            out.append(Leg("also_paid", frozenset(extra), net))
        return out

    def describe(self) -> dict:
        return {"type": self.kind, "price": self.price, "positions": sorted(self.positions)}


@dataclass(frozen=True)
class OddsBoost(Offer):
    """Odds boost: a plain win bet at the boosted price. Per $1:  EV = p1 x boosted_price - 1.

    A boost usually carries a maximum stake; the stake here is sized on the budget, so check
    the app's limit."""

    boosted_price: float
    kind = "odds_boost"

    def __post_init__(self) -> None:
        _check_price(self.boosted_price, "boosted_price")

    def legs(self) -> list[Leg]:
        return [Leg("win", frozenset({1}), lambda s: s * (self.boosted_price - 1.0))]

    def describe(self) -> dict:
        return {"type": self.kind, "boosted_price": self.boosted_price}


# --- expected value and stake -----------------------------------------------------------------


def ev_per_dollar(offer: Offer, chances: dict[str, float], stake: float = 1.0) -> float:
    """Expected profit per $1 of total outlay at a ``stake``, given each leg's chance by name."""
    legs = offer.legs()
    lose = max(0.0, 1.0 - sum(chances[leg.name] for leg in legs))
    return (sum(chances[leg.name] * leg.net(stake) for leg in legs) - lose * stake) / stake


def break_even_c(offer: MoneyBack, chances: dict[str, float], stake: float = 1.0) -> float | None:
    """The bonus-bet value c at which the money-back offer has EV 0 (None if it cannot refund).
    A result below 0 means the offer is +EV even if bonus bets were worthless; above 1, that no
    bonus-bet value makes it pay."""
    refund = chances["refund"] * offer.refund(stake) / stake
    if refund <= 0:
        return None
    return (1.0 - chances["win"] * offer.price) / refund


def growth_stake(offer: Offer, chances: dict[str, float], budget: float) -> float:
    """The stake in dollars that maximises expected log growth of ``budget`` over the joint
    outcomes (each leg, and losing), before any Kelly fraction, cap or rounding. 0 when the
    first dollar has no edge. Growth is concave in the stake, so a golden-section search finds
    the single maximum."""
    legs = offer.legs()
    lose = max(0.0, 1.0 - sum(chances[leg.name] for leg in legs))

    def growth(s: float) -> float:
        g = lose * math.log1p(-s / budget)
        for leg in legs:
            g += chances[leg.name] * math.log1p(leg.net(s) / budget)
        return g

    if ev_per_dollar(offer, chances, budget * 1e-6) <= 0:
        return 0.0
    lo, hi = 0.0, budget * (1 - 1e-9)
    phi = (math.sqrt(5) - 1) / 2
    a, b = hi - phi * (hi - lo), lo + phi * (hi - lo)
    ga, gb = growth(a), growth(b)
    for _ in range(200):
        if ga < gb:
            lo, a, ga = a, b, gb
            b = lo + phi * (hi - lo)
            gb = growth(b)
        else:
            hi, b, gb = b, a, ga
            a = hi - phi * (hi - lo)
            ga = growth(a)
    return (lo + hi) / 2


def size_stake(offer: Offer, chances: dict[str, float], budget: float) -> int:
    """Quarter Kelly on the log-growth stake, capped at 5% of the budget, rounded down to whole
    dollars (to whole multiples of the offer's step). 0 means hold. Owner (2026-10-31): a
    positive stake that rounds below one step is lifted to one step ($1), so a small budget still
    gets the bet; the verdict still needs the worst-case EV to clear MIN_EV_BUFFER."""
    if not (budget > 0 and math.isfinite(budget)):
        return 0
    raw = min(KELLY_FRACTION * growth_stake(offer, chances, budget), MAX_SHARE_PER_BET * budget)
    if raw <= 0:
        return 0
    return max(offer.step, int(raw // offer.step) * offer.step)


# --- scenarios --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    key: str
    label: str
    win: dict[int, float] | None  # None: cannot be built from the prices on hand
    discount: tuple[float, ...] = DISCOUNT
    se_multiple: float = 0.0
    note: str = ""


def _normalise(p: dict[int, float]) -> dict[int, float]:
    total = sum(p.values())
    return {n: v / total for n, v in p.items()}


def scenarios(model: RaceModel) -> list[Scenario]:
    """The six chance scenarios every offer is priced under; the worst EV decides.

    consensus        the plain margin-free consensus (uncorrected), app discount exponents
    flb_1_14         the app's chance: consensus corrected for the favourite-long-shot bias,
                     p ** 1.14 (melbcup.model.probability.MARKET_ALPHA)
    sportsbet_only   Sportsbet's own prices with the margin taken out (needs a price for every
                     starter; otherwise the scenario cannot run and the offer is held)
    discount_low     2nd 0.76, 3rd-4th 0.60 (flatter minor places)
    discount_high    2nd 0.86, 3rd-4th 0.70 (more favourite-heavy minor places)
    mc_2se           consensus with every paying chance lowered by 2 standard errors of the
                     simulation (the same as consensus when places are enumerated exactly)
    """
    corrected = _normalise(model.win_probs())  # the app's chance: consensus ** MARKET_ALPHA
    prices = model.race.prices
    raw = {n: a.market_win for n, a in model.runners.items() if a.market_win}
    if len(raw) == len(corrected):
        consensus = _normalise(raw)
    else:  # chances not built from a market (saved cards, tests): correct them here instead
        consensus = corrected
        corrected = _normalise({n: p**FLB_ALPHA for n, p in consensus.items()})
    sb = {n: prices[n].sportsbet_win if n in prices else None for n in consensus}
    missing = sorted(n for n, v in sb.items() if not v)
    sportsbet = None if missing else _normalise({n: 1.0 / v for n, v in sb.items()})
    return [
        Scenario("consensus", "plain consensus", consensus),
        Scenario("flb_1_14", "price^1.14 corrected", corrected),
        Scenario(
            "sportsbet_only",
            "Sportsbet-only margin-free",
            sportsbet,
            note=f"no Sportsbet price for runner(s) {', '.join(map(str, missing))}"
            if missing
            else "",
        ),
        Scenario("discount_low", "discount low (0.76, 0.60)", consensus, DISCOUNT_LOW),
        Scenario("discount_high", "discount high (0.86, 0.70)", consensus, DISCOUNT_HIGH),
        Scenario("mc_2se", "consensus minus 2 SE", consensus, DISCOUNT, SE_MULTIPLE),
    ]


def leg_chances(
    offer: Offer, pos: Positions, runner: int, se_multiple: float = 0.0
) -> dict[str, float]:
    """Each leg's chance for ``runner``, lowered by ``se_multiple`` standard errors (never
    below zero)."""
    return {
        leg.name: max(
            0.0, pos.chance(runner, leg.places) - se_multiple * pos.se(runner, leg.places)
        )
        for leg in offer.legs()
    }


# --- the check --------------------------------------------------------------------------------


@dataclass
class ScenarioResult:
    key: str
    label: str
    ev: float | None  # per $1 of total outlay; None when the scenario could not be built
    positions: list[float] | None = None  # P(finish 1st..5th)
    break_even_c: float | None = None
    note: str = ""


@dataclass
class OfferCheck:
    verdict: str  # "bet" | "hold"
    stake: int  # whole dollars; 0 whenever the verdict is hold
    offer: dict
    runner: int
    budget: float
    min_ev: float | None
    binding: str | None  # the scenario with the worst EV
    buffer: float
    reason: str
    scenarios: list[ScenarioResult] = field(default_factory=list)
    break_even_c: float | None = None  # money back: the highest c any scenario needs
    positions_used: dict | None = None
    ev_stake: float | None = None  # money back: the stake the EVs refer to (the cap bites)

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "stake": self.stake,
            "reason": self.reason,
            "offer": self.offer,
            "runner": self.runner,
            "budget": self.budget,
            "min_ev": _r(self.min_ev),
            "binding_scenario": self.binding,
            "buffer": self.buffer,
            "ev": {s.key: _r(s.ev) for s in self.scenarios},
            "scenarios": [
                {
                    "key": s.key,
                    "label": s.label,
                    "ev": _r(s.ev),
                    "positions": None
                    if s.positions is None
                    else [round(x, 5) for x in s.positions],
                    "break_even_c": _r(s.break_even_c),
                    "note": s.note,
                }
                for s in self.scenarios
            ],
            "break_even_c": _r(self.break_even_c),
            "ev_stake": self.ev_stake,
            "positions_used": self.positions_used,
        }


def _r(x: float | None, digits: int = 5) -> float | None:
    return None if x is None else round(x, digits)


def _pct(x: float) -> str:
    return f"{x:+.1%}"


def _hold(offer: Offer, runner: int, budget: float, reason: str) -> OfferCheck:
    return OfferCheck(
        "hold", 0, offer.describe(), runner, budget, None, None, MIN_EV_BUFFER, reason
    )


def check_offer(
    model: RaceModel, runner: int, offer: Offer, budget: float, places: int = PLACES
) -> OfferCheck:
    """Price ``offer`` on ``runner`` of ``model``'s race and say BET (with dollars) or HOLD.

    HOLD unless the runner has both a Sportsbet price and a consensus chance, every scenario
    can be built, the worst-case EV across the scenarios is at least ``MIN_EV_BUFFER`` of the
    outlay, and quarter Kelly (capped at 5% of the budget) sizes to at least one whole dollar
    (one even-dollar step for each-way). The stake is sized on the worst-case scenario's chances."""
    prices = model.race.prices.get(runner)
    if model.sources != ["market"]:
        return _hold(offer, runner, budget, "HOLD: chances are not from bookmaker prices yet.")
    if runner not in model.runners:
        return _hold(offer, runner, budget, f"HOLD: runner {runner} is not a starter.")
    if prices is None or not prices.sportsbet_win:
        return _hold(offer, runner, budget, f"HOLD: runner {runner} has no Sportsbet price.")
    if prices.consensus_prob is None:
        return _hold(offer, runner, budget, f"HOLD: runner {runner} has no consensus chance.")

    cases = scenarios(model)

    def evaluate(stake: float) -> tuple[list[ScenarioResult], dict[str, dict[str, float]]]:
        results, chances = [], {}
        for case in cases:
            if case.win is None:
                results.append(ScenarioResult(case.key, case.label, None, note=case.note))
                continue
            pos = position_probs(case.win, case.discount, places=places)
            c = leg_chances(offer, pos, runner, case.se_multiple)
            chances[case.key] = c
            results.append(
                ScenarioResult(
                    case.key,
                    case.label,
                    ev_per_dollar(offer, c, stake),
                    [pos.chance(runner, [k]) for k in range(1, PLACES + 1)],
                    break_even_c(offer, c, stake) if isinstance(offer, MoneyBack) else None,
                    case.note,
                )
            )
        return results, chances

    def worst(results: list[ScenarioResult]) -> ScenarioResult:
        return min((r for r in results if r.ev is not None), key=lambda r: r.ev)

    # EV per dollar is the same at any stake unless a refund cap bites; then price at the
    # largest stake allowed, size on that, and re-price at the stake that will be placed.
    eval_stake = MAX_SHARE_PER_BET * budget if offer.stake_dependent and budget > 0 else 1.0
    results, chances = evaluate(eval_stake)
    binding = worst(results)
    stake = size_stake(offer, chances[binding.key], budget)
    if stake and offer.stake_dependent:
        eval_stake = float(stake)
        results, chances = evaluate(eval_stake)
        binding = worst(results)

    complete = all(r.ev is not None for r in results)
    min_ev = binding.ev
    gaps = [r.note for r in results if r.ev is None]
    if not complete:
        verdict_reason = f"HOLD: the {gaps[0]}, so the Sportsbet-only check cannot run."
        stake = 0
    elif min_ev < MIN_EV_BUFFER:
        verdict_reason = (
            f"HOLD: worst-case EV {_pct(min_ev)} ({binding.label}) is below the "
            f"{_pct(MIN_EV_BUFFER)} buffer."
        )
        stake = 0
    elif stake == 0:
        verdict_reason = (
            f"HOLD: worst-case EV {_pct(min_ev)} clears the buffer but a quarter-Kelly stake "
            f"on ${budget:g} rounds to $0."
        )
    else:
        verdict_reason = (
            f"BET ${stake}: worst-case EV {_pct(min_ev)} ({binding.label}) clears the "
            f"{_pct(MIN_EV_BUFFER)} buffer; quarter Kelly, max 5% of ${budget:g}."
        )
    bec = None
    if isinstance(offer, MoneyBack):
        needed = [r.break_even_c for r in results if r.break_even_c is not None]
        bec = max(needed) if needed else None
        if bec is not None:
            verdict_reason += (
                f" Break-even bonus value c = {bec:.2f} (worst case); "
                f"you assumed {offer.bonus_value:.2f}."
            )
    used = next(c for c in cases if c.key == binding.key)
    pos = position_probs(used.win, used.discount, places=places)
    positions_used = {
        "scenario": binding.key,
        "method": pos.method,
        "finish": [round(pos.chance(runner, [k]), 5) for k in range(1, PLACES + 1)],
        "top": [round(pos.top(runner, k), 5) for k in range(1, PLACES + 1)],
        "se": [round(pos.se(runner, range(1, k + 1)), 6) for k in range(1, PLACES + 1)],
    }
    verdict = "bet" if stake > 0 and complete and min_ev >= MIN_EV_BUFFER else "hold"
    return OfferCheck(
        verdict,
        stake if verdict == "bet" else 0,
        offer.describe(),
        runner,
        budget,
        min_ev,
        binding.key,
        MIN_EV_BUFFER,
        verdict_reason,
        results,
        bec,
        positions_used,
        round(eval_stake, 2) if offer.stake_dependent else None,
    )


__all__ = [
    "DEFAULT_BONUS_VALUE",
    "MIN_EV_BUFFER",
    "EachWay",
    "MoneyBack",
    "OddsBoost",
    "Offer",
    "OfferCheck",
    "PaysAsWinner",
    "PlaceOnly",
    "Positions",
    "break_even_c",
    "check_offer",
    "ev_per_dollar",
    "growth_stake",
    "leg_chances",
    "position_probs",
    "scenarios",
    "size_stake",
]
