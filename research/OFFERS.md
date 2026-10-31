# Offers check (m9)

Engine `melbcup/bets/offers.py`, JSON `GET /api/offer`, tests `tests/test_offers.py`. No page: UI waits for a design BUILD.
Advice only; nothing is placed. Same password as the pages (open when `PUBLIC_ACCESS=1`).

## Chances
Consensus win chances (margin-free), then P(exactly k-th), k = 1..5, by discounted Harville (`DISCOUNT` 1.0, 0.81, 0.65, 0.55 from
`probability.py`; the 5th repeats the 4th). Each place is enumerated exactly when its finishing orders are within `EXACT_LIMIT`
(15,000), else simulated: seeded, 200,000 draws, standard error sqrt(q(1-q)/n). A 24-runner Cup is exact for 1st-3rd, simulated for 4th-5th.

## Formulas (EV per $1 of total outlay; p1 = P(win), Tk = P(top k), O = price, f = fraction)
- each_way: stakes S and S. EV = 1/2 [p1 O + Tk (1 + (O-1) f)] - 1. Staked in even dollars.
- place_only: EV = Tk (1 + (O-1) f) - 1.
- money_back (refund as bonus bet if placed in `positions`, up to `cap`): EV = p1 O + c P(positions) min(S, cap)/S - 1.
  Break-even c = (1 - p1 O) / (P(positions) min(S, cap)/S). Below 0 = pays even if a bonus bet is worthless; above 1 = never pays.
- odds_boost: EV = p1 O_boosted - 1.

## Scenarios (every offer is priced under all six; the WORST EV decides)
a consensus; b price^1.14 renormalised (RERUN.md, the one proven calibration gain; the app keeps 1.0);
c Sportsbet-only margin-free (needs a price for every starter, else HOLD);
d, e discount exponents low (2nd 0.76, 3rd-4th 0.60) and high (0.86, 0.70);
f consensus with every paying chance lowered by 2 SE (equals a when everything is exact).
Exponents d/e are an ASSUMPTION, about +-0.05 on 2nd and 0.60-0.70 on 3rd-4th: CUP_TRENDS_2 §1 fitted 0.80/0.65/0.60 on 1,093 races
with no standard errors. They bracket both fits except the app's 4th (0.55), which scenario a covers.

## Decision
BET only if the runner has a Sportsbet price and a consensus, all scenarios exist, **min EV >= +2% of outlay** (`MIN_EV_BUFFER`,
the model-error buffer) and the stake is at least $1 ($2 each-way). Otherwise HOLD with a stake of 0 and a one-line reason.
Stake: maximise E[log growth] over the joint outcomes (win / placed-not-win / refund / lose) with the worst scenario's chances
(golden-section search; growth is concave), x 0.25 (`staking.KELLY_FRACTION`), capped at 5% of budget, rounded DOWN to whole dollars; a positive stake under $1 is lifted to $1 (owner, 2026-10-31).
Budget: `?budget=`, else the budget cookie, else $200. A capped refund is re-priced at the stake actually placed (`ev_stake`).
At $200 a long shot sizes under $1 and holds: the stake rule, not the edge. A $5,000 budget makes the same offer a BET.

## Default bonus value c = 0.70
A bonus bet pays winnings only: value = p (O-1) = (1 - 1/O) / (1 + m) of face. At m = 15%: $3 0.58, $4 0.65, $5 0.70, $6 0.72, $10 0.78.
0.70 is the $5 case, upper-middle of the $3-$6 range; the lower end is about 0.6. It is a parameter (`c=`), and every money-back
result returns the break-even c per scenario and the worst: if you would value a bonus bet below it, pass.

## What it found (synthetic 24-runner Cup, $5.50-$301, 118% book; plain tests in `test_offers.py`)
Matches CUP_TRENDS_2 §2.1: 1/4 odds with 4 places, the place half is +EV in every scenario from $21 to $101 (worst-case EV +8% to +41%);
1/4 odds 3 places each-way has a negative worst EV at every price (flb scenario -10% to -25%). Plain consensus alone flatters long
shots ($301 each-way 3 places reads +9%); scenario b is what takes it back below zero.

## Known limits
- Rule 4 deductions after a scratching change the terms (and the field, so the chances) after the bet: not modelled.
- Dead heats are neutral in expectation; a real dead heat for a place pays a reduced dividend.
- Terms change: field size under the places threshold, places added or removed, rules per bookmaker are the owner's to read; the
  engine takes terms as typed. `places` is limited to 1-5.
- Bonus bets: stake not returned, turnover, expiry, minimum odds and one-use rules are not modelled beyond c; boosts usually have a
  maximum stake (not asked for here).
- The 2% buffer and scenario band are judgement, not fitted; no edge over the price is proven (RERUN.md, VENUES.md).
- Prices are the live racing.com quotes, not a bookmaker's slip: check the app before betting.
