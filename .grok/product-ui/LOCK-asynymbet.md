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
