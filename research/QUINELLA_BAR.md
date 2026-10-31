# Quinella bar (MIN_HIT = 0.30): blocked, no bar chosen

Run `python research/quinella_bar.py` to reproduce (exit 2 = stopped).

## Coverage (docs/data, Melbourne dates 2026-09-29 to 2026-10-29)
- 30 meeting days, 154 meetings, 1,160 races. All have placings and a start time.
- **Quinella (QN) dividends: none.** No race stores any exotic dividend
  (`RaceResult.exotics` is empty everywhere). `tools/build_archive.py` says so itself:
  "exotic dividends were not saved". Only fixed place dividends exist.
- **Prices are not pre-race.** 1,155 races carry prices, all of them the official starting
  price (`priced_from_sp`, `prices_at` is empty). So there is no pre-race price time to report.
  The app's quinella hit chances built from them are post-race-informed, not what the app
  would have shown before the jump.

## Result
Settling the recommended quinella at $1 per combo needs the real QN dividend. Using anything
else would be an invented number, so the fit, held-out test, bootstrap and trifecta
comparison were not run. The script does the coverage audit only.

## What would unblock it
Save QN (and TF) dividends and the pre-race price time on each card when the archive is built
(Racing.com already returns `exotics` in `GetBettingData`; `racingcom.py` parses it, the
archive just does not keep it), then collect days going forward with the live collector. The
fit/test method in the brief can then be added to this script.
