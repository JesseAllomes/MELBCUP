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

# Per-sport tabs lock (owner BUILD 2026-11-07): v8 direction 2 "Bottom bar" (+ 1's screen layout)
Spec: .grok/product-ui/v8/2-bottom-bar.html (layout of screens per v8/1-segmented-tabs.html).
- Every sport (NBA, NFL, NHL, Football, AFL, NRL, Cricket, ...) has the same tabs: Multis | Challenge | Games |
  SGM | All, as a fixed bottom tab bar on sport pages; the sport chip row stays at the top.
- Multis = the v7-3 Bet now layout for that sport. NBA uses its own picker (nba_legs, audit rules).
- Challenge = that sport's + All Sports challenges, stage timeline (v8-2), suggested bet per stage chosen
  automatically; only actions: I placed this / Won / Lost / One leg failed -> bonus; wallet list + "+ Add a bonus credit".
- Games = next games, main line + fair %, tap -> that game's markets and player props.
- SGM = NBA's same-game multis; other sports an honest state (no measured correlation model yet).
- All = every market (catalogue), search behind a link.

# Challenge screen lock (owner BUILD 2026-11-08): v9 direction 3 "Opened first"
Spec: .grok/product-ui/v9/3-opened-first.html.
- One challenge per screen with big live leg tiles; move between challenges (A, B, C, D...) by tabs/swipe chips.
- Each challenge shows: current leg odds, current bet chance (ring), % of challenge complete (bar, log of bank growth,
  labelled), stage blocks.
- Leg tiles: green = hit, red = failed, orange = in play with a COUNT-UP bar (stat so far vs line; for unders the bar
  fills toward the limit), grey = not started. Overs can go green mid-game; unders only at full time.
- Once placed, the chance updates live ("live estimate"): per leg, P(rest of game reaches/stays within the line)
  from the pre-game market chance scaled by time left; bet = product of live leg chances; 0 when a leg fails.

# Racing likely + multis lock (owner BUILD 2026-11-08): v10 direction 3 style, two tabs
Spec: .grok/product-ui/v10/3-likely-tab.html.
- Race tabs become Bet | Likely | Multis | Field | Result | Mine. Bet keeps the honest value verdict.
- Likely: the race's top 3 single bets by chance (Win/Place) with ring, best price + bookmaker, fair price, honest
  return line; meeting-level "Likeliest today" (5 singles) on the day page.
- Multis: most likely multis by odds range ($1.5-2 ... $10-20), one leg per race, one bookmaker, chance, price,
  exactly-one-fails, legs with race no, runner, Win/Place and jump time (Melbourne). Same on the day page.
- Data: LiveBoard.likely() (melbcup/racing_likely.py).
