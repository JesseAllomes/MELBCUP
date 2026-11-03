# RaceLens vs MELBCUP: head to head (2026-11-03)

RaceLens is a friend's racing app. Its data was pulled read-only with `tools/racelens/pull.py ENVFILE OUTDIR`. The env file holds the URL and password and is kept outside the repo, and the data is not committed. The scoring script is `tools/racelens/score.py OUTDIR <repo>`.

## The test

- **Races:** 99, from 19 meetings (29 Oct to 3 Nov). A race was kept only if RaceLens made its prediction before the jump (2 minutes out) and the race has a final result.
- **Inputs:** both models used the same market snapshot, the one frozen inside RaceLens' prediction. The odds it stores are often refreshed after the jump, so they were not used.
- **MELBCUP:** `corrected_market` (alpha 1.14) applied to that snapshot.

## Results

| | log loss (nats/race) | Brier | top pick won |
|---|---|---|---|
| market | 1.9015 | 0.7484 | 40.4% |
| MELBCUP | **1.8906** | **0.7431** | **40.4%** |
| RaceLens | 1.9713 | 0.7735 | 36.4% |

- MELBCUP minus RaceLens is +0.081 nats per race, with a standard error of 0.035, in MELBCUP's favour.
- Blending RaceLens into MELBCUP gives the best weight as 0.00, both in sample and with one meeting left out each time. RaceLens' chances add nothing.

## Flat $1 win bets at the best fixed price at prediction time

| Rule | MELBCUP | RaceLens |
|---|---|---|
| Win line closest to fair | +15.7% | -57.6% |
| Likeliest placer | +20.4% | +17.2% |

RaceLens' "value" calls land on long shots because its chances are flatter than the market's.

## RaceLens' own suggested bets

| Bet type | Return |
|---|---|
| Win | +81% (7 winners, too few to trust) |
| Place | +38% |
| Exacta | +14% |
| Quinella | +4% |
| Each way | +2% |
| Trifecta | -62% |
| First 4 | -100% (0 from 31) |
| **Total** | **-28% on $1,335** |

## Limits

- 99 races is small, and the ROI figures are noisy.
- Taking the best fixed price across all books is optimistic.
- The test does not use MELBCUP's live pipeline or Betfair.
- There is no Cup-day Flemington pack on RaceLens.
