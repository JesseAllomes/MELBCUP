"""GET /api/offer: request parsing for the offers check (melbcup/bets/offers.py).

JSON only, no page. It computes and places nothing. A bad request raises ``OfferRequestError``
(HTTP 400) with a message that says what to fix; a race that is not on the card raises
``OfferNotFound`` (HTTP 404, as the race pages do)."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from fractions import Fraction

from melbcup.bets.offers import (
    DEFAULT_BONUS_VALUE,
    PLACES,
    EachWay,
    MoneyBack,
    OddsBoost,
    Offer,
    PlaceOnly,
    check_offer,
)
from melbcup.live import Snapshot
from melbcup.web.views import (
    MAX_BUDGET,
    Call,
    betting_open,
    local_time,
    parse_budget,
    pick_budget,
)

COMMON = {"race", "runner", "type", "budget"}
PARAMS = {
    "each_way": COMMON | {"price", "fraction", "places"},
    "place_only": COMMON | {"price", "fraction", "places"},
    "money_back": COMMON | {"price", "positions", "cap", "c"},
    "odds_boost": COMMON | {"boosted_price"},
}


class OfferRequestError(ValueError):
    """The request is not valid: HTTP 400."""


class OfferNotFound(LookupError):
    """The race is not on the card: HTTP 404."""


def _whole(name: str, text: str | None, low: int, high: int | None = None) -> int:
    if text is None or not text.strip():
        raise OfferRequestError(f"{name} is required")
    try:
        value = int(text.strip())
    except ValueError:
        raise OfferRequestError(f"{name} must be a whole number, got {text!r}") from None
    if value < low or (high is not None and value > high):
        span = f"{low} to {high}" if high is not None else f"{low} or more"
        raise OfferRequestError(f"{name} must be {span}, got {value}")
    return value


def _number(name: str, text: str | None, *, above: float | None = None, low: float | None = None):
    if text is None or not text.strip():
        raise OfferRequestError(f"{name} is required")
    try:
        value = float(text.strip().lstrip("$"))
    except ValueError:
        raise OfferRequestError(f"{name} must be a number, got {text!r}") from None
    if not math.isfinite(value):
        raise OfferRequestError(f"{name} must be a finite number, got {text!r}")
    if above is not None and value <= above:
        raise OfferRequestError(f"{name} must be above {above:g}, got {value:g}")
    if low is not None and value < low:
        raise OfferRequestError(f"{name} must be at least {low:g}, got {value:g}")
    return value


def _fraction(text: str | None) -> float:
    """Each-way terms: ``1/4``, ``1:4`` or ``0.25``."""
    if text is None or not text.strip():
        raise OfferRequestError("fraction is required (each-way terms, e.g. 1/4)")
    try:
        value = float(Fraction(text.strip().replace(":", "/")))
    except (ValueError, ZeroDivisionError):
        raise OfferRequestError(f"fraction must look like 1/4 or 0.25, got {text!r}") from None
    if not 0 < value <= 1:
        raise OfferRequestError(f"fraction must be above 0 and at most 1, got {text!r}")
    return value


def _positions(text: str | None) -> frozenset[int]:
    if text is None or not text.strip():
        raise OfferRequestError("positions is required (places that refund, e.g. 2 or 2,3)")
    out = {_whole("positions", part, 2, PLACES) for part in text.split(",")}
    return frozenset(out)


def parse_offer(query: Mapping[str, str], default_price: float | None) -> Offer:
    """Build the offer a query describes. ``default_price`` is the runner's live Sportsbet
    price, used when no ``price`` is given."""
    kind = query.get("type", "")
    if kind not in PARAMS:
        raise OfferRequestError(f"type must be one of {', '.join(PARAMS)}, got {kind!r}")
    unknown = sorted(set(query) - PARAMS[kind])
    if unknown:
        raise OfferRequestError(
            f"{', '.join(unknown)} not valid for {kind}; allowed: {', '.join(sorted(PARAMS[kind]))}"
        )
    if kind == "odds_boost":
        return OddsBoost(_number("boosted_price", query.get("boosted_price"), above=1.0))
    if "price" in query:
        price = _number("price", query["price"], above=1.0)
    elif default_price:
        price = default_price
    else:
        raise OfferRequestError("price is required: the runner has no live Sportsbet price")
    if kind == "money_back":
        c = DEFAULT_BONUS_VALUE
        if "c" in query:
            c = _number("c", query["c"], low=0.0)
            if c > 1.0:
                raise OfferRequestError(
                    f"c (bonus bet value per $1 of face) must be 0 to 1, got {c:g}"
                )
        return MoneyBack(
            price,
            _positions(query.get("positions")),
            _number("cap", query.get("cap"), above=0.0),
            c,
        )
    terms = (
        price,
        _fraction(query.get("fraction")),
        _whole("places", query.get("places"), 1, PLACES),
    )
    return EachWay(*terms) if kind == "each_way" else PlaceOnly(*terms)


def offer_response(
    snap: Snapshot,
    params: Iterable[tuple[str, str]],
    cookies: Mapping[str, str] | None = None,
) -> dict:
    """The JSON for one offer check, from the live board's snapshot."""
    pairs = list(params)
    query = dict(pairs)
    if len(query) != len(pairs):
        raise OfferRequestError("each parameter may be given once")
    race_no = _whole("race", query.get("race"), 1)
    runner_no = _whole("runner", query.get("runner"), 1)
    if "budget" in query:
        budget = parse_budget(query["budget"])
        if budget is None:
            raise OfferRequestError(f"budget must be a number above 0 and at most {MAX_BUDGET:,}")
    else:
        budget, _ = pick_budget({}, cookies)
    model = next((m for m in snap.models if m.race.number == race_no), None)
    if model is None:
        raise OfferNotFound(f"Race {race_no} is not on the card yet")
    race = model.race
    if not betting_open(race):
        raise OfferRequestError(f"Race {race_no} has already run")
    runner = next((r for r in race.starters if r.number == runner_no), None)
    if runner is None:
        raise OfferRequestError(f"Runner {runner_no} is not a starter in race {race_no}")
    prices = race.prices.get(runner_no)
    offer = parse_offer(query, prices.sportsbet_win if prices else None)
    result = check_offer(model, runner_no, offer, budget)
    call = Call.bet(result.stake) if result.verdict == "bet" else Call("hold")
    body = result.as_dict()
    body.update(
        verdict=call.kind,
        stake=call.stake or 0,
        race=race_no,
        runner_name=runner.name,
        sportsbet_price=prices.sportsbet_win if prices else None,
        prices_as_at=local_time(race.prices_at) if race.prices_at else None,
    )
    return body
