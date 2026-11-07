# ruff: noqa: E501
"""Payoff of one bet under each way of funding it (owner, 2026-11-07).

Every offer rule is typed in by the owner with a provenance note (where the rule came from);
nothing is inferred from a screenshot. Inputs: per-leg chances, the accepted price and the stake.
Objective, stated on every table: maximise expected net value = expected cash return + expected
bonus value received - cash staked - value of any bonus stake used. A bonus credit is valued at
the owner-set redemption rate (default 0.0 until set, so it counts as nothing until the owner
says what it is worth). Pull 'Em / cash-out is not modelled: it is not a free removal of a leg.
"""

from __future__ import annotations

from math import prod

OBJECTIVE = (
    "Objective: expected net value = expected cash return + expected bonus value received "
    "- cash staked - value of bonus stake used. Bonus credit counts at the redemption rate you set "
    "(0.0 until you set it)."
)


class PromoError(ValueError):
    pass


def p_all(chances: list[float]) -> float:
    return prod(chances)


def p_exactly_one_fails(chances: list[float]) -> float:
    return sum((1 - c) * prod(x for j, x in enumerate(chances) if j != i) for i, c in enumerate(chances))


def _row(name, note, p_win, p_one, cash_staked, cash_ret, bonus_in, bonus_used):
    return {
        "funding": name,
        "note": note,
        "p_all": p_win,
        "p_one_fail": p_one,
        "cash_staked": round(cash_staked, 2),
        "exp_cash_return": round(cash_ret, 2),
        "exp_bonus_value": round(bonus_in, 2),
        "bonus_used": round(bonus_used, 2),
        "net": round(cash_ret + bonus_in - cash_staked - bonus_used, 2),
    }


def payoff(
    chances: list[float],
    price: float,
    stake: float,
    *,
    boost_price: float | None = None,
    boost_fraction: float | None = None,
    max_extra_win: float | None = None,
    p_win: float | None = None,
    p_one: float | None = None,
    refund_cap: float | None = None,
    redeem_rate: float = 0.0,
    provenance: str = "",
    min_legs: int | None = None,
    min_leg_price: float | None = None,
    leg_prices: list[float] | None = None,
) -> dict:
    """{"objective", "redeem_rate", "rows": [...], "skipped": [...]}. Cash is always shown; each
    promotion row needs its owner-entered figure and a provenance note. The offer's own rules
    (min_legs, min_leg_price with leg_prices) bind only the promotion rows: a stack that breaks
    them keeps its cash row and the promotion rows are skipped, with the reason."""
    if not chances or any(not 0 < c < 1 for c in chances):
        raise PromoError("each leg chance must be between 0 and 1")
    if price <= 1 or stake <= 0:
        raise PromoError("price must be above 1 and stake above 0")
    if not 0 <= redeem_rate <= 1:
        raise PromoError("redemption rate is 0 to 1")
    pw = p_all(chances) if p_win is None else p_win  # p_win/p_one: a joint model's figures, if any
    p1 = p_exactly_one_fails(chances) if p_one is None else p_one
    if pw + p1 > 1 + 1e-9:
        raise PromoError("win and exactly-one-fail chances cannot add past 1")
    rows = [_row("Cash", "your cash, standard price", pw, p1, stake, pw * stake * price, 0.0, 0.0)]
    broken = []
    if min_legs and len(chances) < min_legs:
        broken.append(f"needs {min_legs}+ legs, this has {len(chances)}")
    if min_leg_price and leg_prices and min(leg_prices) < min_leg_price:
        broken.append(f"every leg must pay {min_leg_price:g}+, lowest is {min(leg_prices):g}")
    if broken:  # no promotion row: the offer would not pay on this stack
        return {
            "objective": OBJECTIVE,
            "redeem_rate": redeem_rate,
            "provenance": provenance,
            "rows": rows,
            "skipped": broken,
        }
    if boost_price or boost_fraction or refund_cap:
        if not provenance.strip():
            raise PromoError("say where this offer came from (provenance note)")
    if boost_price:
        if boost_price <= price:
            raise PromoError("a boosted price is above the accepted price")
        rows.append(
            _row("Boost / Power Up", f"boosted price ${boost_price:.2f} (as entered)", pw, p1, stake, pw * stake * boost_price, 0.0, 0.0)
        )
    if boost_fraction:  # a winnings boost lifts the profit only (pack: PROMOTIONS)
        extra = stake * (price - 1) * boost_fraction
        if max_extra_win is not None:
            extra = min(extra, max_extra_win)
        rows.append(
            _row("Winnings boost", f"+{boost_fraction:.0%} on profit (cap {max_extra_win if max_extra_win is not None else 'none'})", pw, p1, stake, pw * (stake * price + extra), 0.0, 0.0)
        )
    if refund_cap:
        refund = min(refund_cap, stake)
        rows.append(
            _row(
                "Exactly-one-fail money back (bonus)",
                f"refund up to ${refund:.2f} as bonus credit x rate {redeem_rate:g}",
                pw, p1, stake, pw * stake * price, p1 * refund * redeem_rate, 0.0,
            )
        )
    rows.append(
        _row(
            "Bonus-funded stake",
            f"stake ${stake:.2f} not returned on a win; counted at rate {redeem_rate:g}",
            pw, p1, 0.0, pw * stake * (price - 1), 0.0, stake * redeem_rate,
        )
    )
    return {
        "objective": OBJECTIVE,
        "redeem_rate": redeem_rate,
        "provenance": provenance,
        "rows": rows,
        "skipped": [],
    }
