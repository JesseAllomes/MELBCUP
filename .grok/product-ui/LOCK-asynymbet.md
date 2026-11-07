# AsynymBet design lock (owner, 2026-11-03): prototype E
Spec: .grok/product-ui/v4/e-merged.html (https://claude.ai/artifact/T941cW9hBenvPRje3Svgz3). Supersedes design.md, layout.md, theme.md for the AsynymBet UI.
- Name AsynymBet; address bet.asynym.dev (cup.asynym.dev keeps working).
- Dark purples and blacks only; no bookie brand colours; green/red only for profit/loss and WON/LOST.
- Fixed header on every screen: logo, Agencies button, today's P&L with centred bar, a chip per agency that is ON (money left / today's money).
- Agencies panel: every agency we pull prices from; ON/OFF is for money tracking only; the model always uses every price.
- Nav: Home | Race days | Mine. Meetings and races open inline under the header (no covering sheets).
- Race: header with countdown, tabs Bet | Field | Result | Mine. Bet = verdict card: TAKE THIS BET (ring with chance, stake, fair, best, "only worth it at $X or better", one button per agency ON) or NOTHING WORTH TRYING HERE pointing at the best bet left; then Top picks worth a shot (up to 4, edge %), then a multi card with a ring when one is worth it.
- Mine: Betting pool card with Edit; Edit makes every $ amount editable until Done.
- Ring meter (RaceLens style) = chance the bet or multi gets up: green 60%+, purple 30-59%, amber under 30%.

# Sports "Bet now" lock (owner BUILD 2026-11-07): v7 direction 3 "Top two"
Spec: .grok/product-ui/v7/3-top-two.html (rounds: v5 -> owner mix 1+2+4; v6 -> A then D; v7 -> 3).
- Sports home = Bet now, fully automatic, no inputs. Status strip under the header: "Updated N min ago" + Check now;
  while the server recomputes: slim progress bar "Updating multis · NN%", page stays usable; when a new result
  lands: bottom toast "Fresh multis ready · Tap" (tap reloads). Never block or blank the page.
- Top: two hero slips side by side, "Bet this" (highest chance) and "Or this" (next), each: ring (chance), price,
  kick-off countdown, legs, Why strip (leg chance bars, bookie cut per leg = 1 - p x price, pays vs fair scale,
  games independent marker, price age), negative-expected-return line in plain words.
- Shared-game risk banner when one game feeds several multis ("N of M multis ride on X").
- Below: D-style calm ruled rows for the other odds ranges, grouped under kick-off times on A's time spine.
- Bonus note: the credit's bookmaker vs the multis' bookmaker, said plainly; never invented returns.
- Sport page: same layout for that sport's own multis (designed empty state when none), then Next games with
  the main line (closest to 50/50) and fair %, "N player props" into the Players view; search behind a link.
- Challenge tab: no promo-compare form, no split/hold/expired controls; wallet = list + one collapsed
  "+ Add a bonus credit" + "Used".
- Times Melbourne; ring colours per the base lock (green 60%+, purple 30-59%, amber <30%).
