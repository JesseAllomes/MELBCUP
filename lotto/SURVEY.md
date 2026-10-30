# Legal, rules-based mathematical edges in lotteries available to an Australian (Melbourne) player

Research date: 30 October 2026. Scope: only play that is inside the published game rules (buying tickets,
choosing numbers, timing, coverage, syndicates, promotions). Nothing here relies on fraud, tampering, RNG or
terminal access, insider information or breach of terms. Australian lottery prizes are not income-taxed for
individuals, so every expected-value (EV) figure below is pre-fee, post-tax, per dollar of retail price.

Working files: `work/scripts/ev_models.py` (all models, runnable), `work/ev_results.md` (its output),
`work/data/` (official rule PDFs converted to text, The Lott API draw files, transcribed dividend tables).

## 0. How the edges work, in one paragraph

A lottery ticket is positive-EV only when money that other people paid in earlier draws (a jackpot, a
reserve-funded guarantee, a promotional top-up) is on offer to the current draw's buyers at a price that
does not already attract enough extra buyers to dilute it. The three ways that happens are (a) a jackpot or
fixed prize that cannot be shared, so extra sales do not reduce your payout (Lucky Lotteries, Keno, charity
raffles); (b) a pari-mutuel pool that must be paid out while sales stay modest relative to the odds (the Cash
WinFall roll-down; in Australia the nearest analogue is a reserve-funded Superdraw, or Oz Lotto's 40% Division
1 share when the jackpot is huge); and (c) a fixed cost of buying every combination that is less than the
guaranteed return (Virginia 1992, done by a Melbourne syndicate; here only Super 66 is small enough to
cover, and it would need a jackpot that has never occurred).

## 1. Ranked table: realistic chance of a legal positive-EV situation

RTP = expected return per $1 of retail price. Break-even figures are from `ev_models.py`; inputs are the
official rules cited in section 4.

| # | Game (operator, where a Victorian can play) | Mechanism that can push EV over 100% | Break-even condition (retail price) | Has it happened? / how often | Practical barriers | Sources |
|---|---|---|---|---|---|---|
| 1 | **Lucky Lotteries Mega Jackpot** ($5.50) and **Super Jackpot** ($2.20) (NSW Lotteries bloc, sold Australia-wide incl. Vic via The Lott online) | Raffle with a fixed pool of 200,000 / 270,000 numbers, fixed cash prizes equal to 36.1% of subscriptions, plus a jackpot funded by 26.1% of subscriptions that grows by $215-255k (Mega) / $120-137k (Super) per draw and is **never shared** and **never diluted by extra sales**; draws happen whenever the pool sells out. | Jackpot >= **$35.0M** (Mega) or **$27.2M** (Super). Fixed prizes return 32.9% / 32.8%; jackpot odds 1 in 9,483,167 / 18,385,876 per ticket. | **Yes.** Mega Jackpot was $96M when won on 26 Aug 2019 (draw 1447): RTP ~217% per ticket. March 2026: $27.5M after 99 rollover draws (RTP 86%). Super Jackpot advertised at $19.22M in May 2025 (RTP ~80%). Model: ~4.6% of jackpot cycles reach break-even; cycles average 47 (Mega, ~1 draw/week) and 68 draws (Super, ~2/week), so roughly once a decade across the two games, and it is visible weeks ahead. | None on quantity (no entry cap; a whole draw is $1.1M / $594k). Enormous variance: P(jackpot per draw) is 2.1% / 1.5% even if you own every ticket; risk of ruin near-certain for any bankroll a person has; the edge is real but only 'cashable' by a very large, patient capital pool. Ticket must be bought before the draw sells out. | Tatts Rules Sch. F Tables A/B [S1]; thelott help odds [S10]; $96M [S11][S12]; $27.5M [S13]; $19.22M [S14]; $8.82M after 65 draws [S15] |
| 2 | **Keno Mega Millions 10-spot** ($2/game; Keno NSW/VIC/ACT pooled jackpot; Vic venues and keno.com.au) | Fixed pay table (returns $0.81 of each $2) plus a pooled progressive jackpot starting at $5M that grows with sales and is shared only with same-game winners. New game every ~3 minutes; bet size does not change the jackpot (fixed per first $2), so you can buy as many $2 games as you like. | Jackpot >= **$10.6M** (odds 1 in 8,911,711). Classic 10-spot ($1): >= $4.1M; Classic 9-spot: >= $556k; 8-spot: >= $106k; 7-spot: >= $19.4k. | **Not yet.** Largest 10-spot prizes found: $8.86M (Jan 2026, QLD), $7.90M (2018), $6.59M (2019). Today (ACT feed, 30 Oct 2026): MM 10-spot $5.13M (RTP 69%), Classic 10-spot $1.17M (67%). A $10.6M+ jackpot would need a roll about 20% longer than the longest seen. | NSW Rules cap aggregate major prizes per game at $3M pro-rata (r.19(a)) and jackpot sharing is pro-rata by stake; max $9,999 per entry. Variance comparable to Lucky Lotteries. | NSW Keno Rules [S4]; NSW/VIC game guides [S5][S6]; ACT jackpot feed [S7]; records [S16][S17][S18] |
| 3 | **Oz Lotto** at very large jackpots ($1.45/game, Tuesdays, The Lott) | Division 1 gets 40% of a 55% prize fund and rolls indefinitely (roll-down only after 25 consecutive jackpots, never reached). The player base is about half Powerball's, so sharing dilutes a given jackpot less. | Jackpot x share-factor >= **$64M** 'effective' (share-factor = (1-e^-lam)/lam, lam = games sold / 62,891,499). $100M with <= ~45M games, or $150M with <= ~110M games. | **Close, never over.** 4 Feb 2025 $100M draw: ~99M games sold (inferred from pools), share-factor 0.50, effective $51M -> ex-ante RTP 85% (ex post 100% because one winner took it all). No Oz Lotto jackpot above $100M in 14 years. | Only timing and number choice; nothing to buy in bulk. Each extra $10M of jackpot attracts enough sales that the effective jackpot grows slowly. | Tatts Rules Sch. C [S1]; Lotterywest odds [S20]; dividends 4 Feb 2025 [S23]; sales context [S24] |
| 4 | **Charity / prize-home art unions** (RSL/Dream Home, Mater, yourtown, Endeavour, Deaf, RSPCA, Surf Life Saving; open to Vic residents) | Fixed, published ticket cap per draw and a fixed prize list; the draw proceeds on the date even if the cap is not sold. EV per ticket = prize value / (tickets actually sold x price), so a draw that is selling badly can exceed 100% of face value. | Tickets sold x price < realisable prize value (house less selling costs, or the gold/cash option). | **Unknown.** Operators publish the maximum ticket count in each draw's terms (yourtown confirms this) but not live sales, and none of the current T&C documents could be fetched from this environment (403/404). This is the one category where a short data-collection exercise could find a genuine >100% draw. | Prize is illiquid; 'value' is a retail valuation; 'draw proceeds regardless' must be checked clause by clause; no way to buy enough to matter for the big draws. | yourtown FAQ [S25]; Dream Home T&Cs [S26]; small-raffle example T&Cs [S27] |
| 5 | **Super 66** ($1/game, Saturdays, Tatts bloc incl. WA, not NSW) | Fixed Div 2-5 prizes (return $0.476) plus a pari-mutuel Division 1 (1 in 1,000,000) that jackpots; the whole combination space costs only $1,000,000, so a cover-all is physically possible. Roll-down to the next division after 26 consecutive carry-overs. | Jackpot >= **$626k** (with sharing at ~370k games/draw). Cover-all returns $476k fixed + 0.84 x jackpot. | **Never.** Largest found $380,724 (July 2017). Division 1 accrues ~$48k/draw; P(no winner) 0.69/draw; model gives ~1% of cycles reaching $626k (~once per 7 years at current, falling, sales). The 26-draw roll-down has probability ~7e-5 per cycle. | A cover-all means printing 1,000,000 Super 66 games on Saturday; ordinary buyers face the same variance as any 1-in-a-million game. | Tatts Rules Sch. B [S1]; Lotterywest Super66 [S19]; record [S28]; API dividends [S8] |
| 6 | **Saturday Lotto Superdraw / Megadraw** with unpopular numbers ($0.95/game) | Division 1 is topped up from the Prize Reserve Fund to a fixed $20M/$30M/$40M regardless of sales (5 Sep 2026 Superdraw: $9.8M top-up on a $31.3M prize fund), lifting RTP from 56% to 68%; a $40M Megadraw at ~55M games would reach ~85-90%. Because 8+ Division 1 winners are expected, picking a combination fewer people hold raises your share of the fixed pool. | Would need the reserve top-up to exceed ~45% of sales, i.e. a $40M Megadraw selling under ~40M games. | **No.** Ex-ante RTP 68% (2026 Superdraw); an unpopular combination (r=0.75 of average popularity) adds ~+10 points; r=0.5 (optimistic) +30 points. Never >100%. | None besides choosing numbers; 70% of entries are quick picks, which limits how 'unpopular' you can be. | Tatts Rules Sch. A, r.10.12 [S1]; API dividends [S8]; The Lott pattern data [S29]; Otago NZ study [S30]; Lotterywest Slikpik share [S31] |
| 7 | **Lotto Strike** (NSW/ACT only, $1.15 add-on to Mon/Wed/Sat Lotto; Victorians can buy only in NSW/ACT or via NSW-registered online account) | Tiny game (~108k games/draw), ordered 4-number match 1 in 3,575,880, Division 1 pool = 45% of a 60% prize pool, jackpots from a $100k guarantee by ~$30k/draw (3 draws/week) up to a 'Maximum Jackpot Drawing Prize'. Rolls are long and the jackpot is rarely shared. | Jackpot >= **$2.6M**. The reported maximum is $2.0M (resellers), and the rule retains money above the cap for future Division 1 prizes rather than rolling it down, so RTP tops out at ~84%. | **No.** Currently ~$1.5M (RTP ~73%) after ~50 rolling draws; model says ~15% of cycles reach the cap. Would become positive only if the Licensee raised the cap above $2.6M. | Jurisdiction (NSW/ACT); the cap. | NSW Lotto Strike Rules r.11 [S3]; prize table/cap [S32][S33]; API dividends [S8] |
| 8 | **Powerball** ($1.575/game, Thursdays) | 35% of a 55% prize fund to Division 1, rolls indefinitely (roll-down after 25 consecutive jackpots: never within sight; the record $200M run was ~7 draws). | Jackpot x share-factor >= **$145M** effective. | **Never, and structurally cannot.** $200M (1 Feb 2024): ~324M games sold, share-factor 0.38, effective $76M, ex-ante RTP 73% (78% realised). $150M (25 Jan 2024): 238M games, 71%. $100M (15 Oct 2026): 148M games, ~70%. Base weeks 32-36%. Sales grow faster than the jackpot. | None. | Tatts Rules Sch. E [S1]; SA Powerball Rules (25-draw clause) [S2]; dividends [S21][S22]; API [S8]; sales anecdotes [S24b] |
| 9 | **Weekday Windfall** (Mon/Wed/Fri, $0.67/game) and promo days | Division 1 is a fixed $1M per winner (up to 6), paid from reserve, not pari-mutuel; prize fund for Div 2-6 only 33%. 'Double Win Day' doubles Div 2-6 pools from reserve. | Never: RTP ~48% normally, ~77% on Double Win Day. | No. | None. | Tatts Rules Sch. D [S1]; Lotterywest [S34] |
| 10 | **Keno Classic 10-spot and lower spots** ($1) | As Keno MM but smaller jackpots. | 10-spot >= $4.1M (record $2.43M); 9-spot >= $556k; 8-spot >= $106k; 7-spot >= $19k (ACT now $5.3k). | No. | - | [S4][S5][S6][S7] |
| 11 | **Instant Scratch-Its** (all states) | US-style 'top prizes remaining' play needs the operator to publish remaining prizes by game. The Lott's rules only require publishing the prize structure before launch and state that all prizes 'are only available until won' and that games can be withdrawn at Tatts' discretion; no live remaining-prize table was found for The Lott or Lotterywest (only occasional media releases). Monthly 2nd Chance Draw is free EV on tickets already bought. | Would need a published remaining-prize ledger. | Not possible with published data. 55% prize fund. | - | Tatts Rules Sch. G r.4.1, 4.3, 10 [S1]; Lotterywest releases [S35] |
| 12 | **Set for Life** ($0.80/draw) | Fixed prizes, prize fund capped at 40% of subscriptions; Div 1 shared only above 4 winners. | Never. RTP ~40%, Division 1 PV about $3.3M. | No. | - | Tatts Rules Sch. H [S1]; Lotterywest [S36] |
| - | **Lottery betting (Lottoland-style)** | Would allow fixed-odds bets on foreign jackpots. | - | **Illegal to offer in Australia since Jan 2019** (Interactive Gambling Amendment (Lottery Betting) Act 2018); ACMA found Lottoland in breach. Excluded. | - | [S37][S38][S39] |

Famous cases, legality check: Cash WinFall (Massachusetts, 2005-2012) was legal play of a published roll-down
rule; the Inspector General found no illicit activity, though some retailers broke store-level rules to
process bulk slips [S40][S41]. The Virginia 1992 cover-all (International Lotto Fund, Melbourne) was legal
[S42]. The Iowa Hot Lotto case (Tipton) was RNG tampering and is excluded. Scratch-card 'prizes remaining'
analysis is legal where the ledger is published (US/UK); Australia does not publish one.

## 2. Candidate detail

### 2.1 Lucky Lotteries (rank 1)

Mechanism (Tatts Rules, Schedule F; same rules bloc-wide): each Mega Jackpot draw sells numbers 000,001 to
200,000 at $5.00 subscription + $0.50 commission; Super Jackpot 270,000 numbers at $2.00 + $0.20. A draw is
conducted only when all numbers are sold (r.3.1). The drawing device picks 4,218 (Mega) / 3,965 (Super)
winning numbers for the fixed cash prizes (1st prize $200,000 / $100,000 down to $12 / $10), then one further
Jackpot Number; the jackpot is won only if the Jackpot Number equals one of the winning numbers (r.4.2(c)).
Consolation prizes go to numbers adjacent to winners (cash for 1st prize, free tickets otherwise). Prize fund
36.1425% (Mega) / 36.0870% (Super) of subscriptions equals the fixed prizes exactly: the script reproduces
$361,425 and $194,870 per draw to the dollar from Tables A/B. A further 26.1090% / 25.4339% of subscriptions
is the Prize Reserve contribution, which funds the guaranteed minimum jackpot ($1,000,000 / $500,000) and the
per-draw increment ($215,000-$255,000 / $120,000-$137,000). The jackpot is one indivisible prize.

EV per ticket = fixed return + jackpot x P(ticket wins jackpot):
- Mega: $1.807 + J x 1/9,483,167 per $5.50 -> break-even J = $35.0M (vs the $5.00 subscription: $30.3M).
- Super: $0.722 + J x 1/18,385,876 per $2.20 -> break-even J = $27.2M ($23.5M vs subscription).
- Ticket sales do not enter the formula: there is no sharing and a draw's prize count is fixed.

Historical frequency: P(jackpot is won in a given draw) = winning numbers / pool = 2.109% (Mega) / 1.469%
(Super), so cycles average 47 / 68 draws and the jackpot grows about $0.235M / $0.13M per draw; reaching
break-even needs ~145 / ~208 consecutive misses, probability 4.6% per cycle for either game. Draw numbers
(Mega 1447 on 26 Aug 2019 to 1781 in Mar 2026 = ~51/year; Super 10091 in Jul 2016 to 10988 in May 2025 =
~100/year) give cycle lengths of roughly 11 and 8 months, i.e. a positive-EV window about once per 15-20 years
per game. It has happened at least once in the modern game: the Mega Jackpot stood at $96M on 26 Aug 2019
(RTP 217%; EV of a whole $1.1M draw was $2.39M). Near misses: Mega $11.73M (Jan 2020), $27.5M (16 Mar 2026,
after 99 draws, RTP 86%); Super $8.82M (2016, 65 draws), $19.22M advertised May 2025 (RTP ~80%).

Exploitability: the jackpot amount is public and moves by a known increment, so the window is visible many
weeks ahead. There is no purchase cap (r.1.2(m): minimum one). Buying an entire Mega draw costs $1.1M and
returns $361,425 of fixed prizes plus a 2.1% shot at the jackpot; at J = $50M that is EV $1.42M, but 97.9%
of the time you lose ~$740k. Expected capital to run cycles until the jackpot is hit is ~47 draws x $0.74M
net = ~$35M, which is exactly why break-even sits at $35M. Per-ticket buyers get the same EV with even
larger relative variance. Fees: online purchase adds no fee beyond the embedded commission. A practical
limit is speed: when the jackpot is large the public buys faster, draws sell out quickly, and you must buy
before each sell-out (which is fine: your EV per ticket is unaffected by their buying).

Secondary edges: none from number choice (numbers are assigned). Free-ticket consolation prizes should be
taken as tickets, not cash, when the jackpot is above break-even.

### 2.2 Keno Mega Millions 10-spot (rank 2)

Mechanism: 20 of 80 numbers drawn every ~3 minutes; pay table per $2 game (NSW/VIC/ACT): 4 of 10 $2, 5 $4,
6 $7, 7 $50, 8 $600, 9 $11,000, 10 = jackpot ($5,000,000 base + pooled growth). Hypergeometric probabilities
give a fixed return of $0.810 per $2 and P(10/10) = 1/8,911,711, so RTP = 40.5% + J/17.8M per dollar and
break-even J = $10.6M. Classic 10-spot ($1: 4:$1, 5:$2, 6:$6, 7:$50, 8:$580, 9:$10,000, 10: $1M+) has fixed
return $0.539 and break-even $4.1M. Lower spots have much lower break-evens ($556k for 9-spot, $106k for
8-spot, $19k for 7-spot) but their jackpots are correspondingly small (ACT feed today: $235k, $32k, $5.3k).

Rules that matter: the jackpot fill/growth is paid on the first $1 (Classic) or $2 (Mega Millions) of a
game only (NSW Rules r.10(c)), so bet exactly $1/$2 per game and buy more games rather than bigger ones;
aggregate major-prize liability is capped at $3M per game with pro-rating (r.19(a)); jackpots are shared
pro-rata among same-game winners (r.19(f),(h)); maximum $9,999 per entry (r.9). Current jackpots are
published live (keno.com.au and the per-state API).

History: the largest 10-spot prizes found are $8.86M (Gladstone QLD, Jan 2026, described as the second
largest Keno win ever), $7.90M (Lambton NSW, 2018), $6.59M (Randwick, Apr 2019), $5.9M (Shelly Beach, 2023);
Classic 10-spot $2.43M (Kew, 2021). So the Mega Millions jackpot has reached ~84% of break-even. QLD is a
separate pool run by The Lott with its own pay table (not verified here).

Exploitability: anyone can play thousands of $2 games; a jackpot above $10.6M would make every $2 game +EV
with no sharing risk worth modelling (expected other winners per game is tiny). The variance is the same as
Lucky Lotteries: a 1-in-8.9M event. Watch the live jackpot; nothing else to do.

### 2.3 Oz Lotto at $100M+ (rank 3)

Mechanism: 7 of 47 plus 3 supplementaries, Division 1 odds 1 in 62,891,499, Division 1 = 40% of a prize
fund that is 55% of subscriptions; unlimited rollovers (roll-down only after 25 consecutive jackpots).
Expected Division 1 value per game = J x (1-e^-lam)/lam / N with lam = games sold / N; lower divisions return
0.55 x 0.60 x $1.30 = $0.43 per $1.45 game. Break-even: J x share-factor >= $64M.

Data: pools inferred from published dividends (pool / rule percentage) give games sold. 4 Feb 2025 ($100M):
~99M games, lam = 1.57, share-factor 0.50, effective $51M, ex-ante RTP 85%. Ordinary weeks: 10-40M games,
RTP 30% unless Division 1 falls. If a future $150M-$200M Oz Lotto jackpot attracted fewer than ~110-150M
games it would be +EV; by comparison Powerball's $200M attracted 324M games. Choosing numbers that avoid
birthdays/patterns adds ~+9 RTP points at these jackpot sizes (section 2.6).

### 2.4 Charity prize-home lotteries (rank 4, unverified)

Why they are structurally interesting: the number of tickets is capped and printed in the draw's terms
(yourtown: "the maximum number of tickets sold in each draw can be found in the Terms & Conditions"), the
prizes are fixed, and the draw date is fixed, so EV = prize value / (tickets sold x price) is knowable if
sales can be observed, and a poorly selling draw hands buyers a positive expectation on face value. Every
operator page carrying the current numbers was blocked from this environment (403/404), so no draw could be
evaluated. Treat as the main item for the next data-collection pass: for each live draw record (max tickets,
price, total prize value, cash/gold alternative, the 'draw proceeds regardless' clause) and, where the site
shows a sales counter, the sell-through. Note prize homes are illiquid and valued at retail; use a 10-15%
haircut (agent fees, furniture, land tax timing) when comparing.

### 2.5 Super 66 (rank 5)

Fixed divisions (5/4/3/2 digits from either end: $6,666/$666/$66/$6.60 at 1 in 55,556/5,556/556/56) return
$0.476 per $1 game; the balance accrues to Division 1 (observed ~$48k/draw on ~370k games; a jackpot of
$193,627 was paid after four accruing draws in Sept 2026). P(no Division 1 winner) = 0.69 per draw, so the
jackpot usually resets within three weeks; break-even $626k needs ~13 consecutive misses (p ~1%). Record
found $380,724 (2017). A $1,000,000 cover-all would guarantee the $476k of fixed prizes plus 84% of the
jackpot in expectation (sharing), hence the same $626k threshold. The 26-draw roll-down clause (Schedule B
r.4.4-4.6) is unreachable (p ~7e-5). Declining sales make long cycles slowly more likely; worth monitoring
but not a plan.

### 2.6 Saturday Lotto Superdraws, Megadraws and unpopular numbers (rank 6)

From the API dividend tables: a 2026 base week has a prize fund of ~$16M (~34M games), Division 1 is topped
up from the reserve by ~$0.9M to the advertised $6M, realised RTP 56%; the 5 Sep 2026 $20M Superdraw had a
$31.3M prize fund (~67M games) and a $9.8M top-up, RTP 68%; a $40M New Year Megadraw would run ~85-90%.
Because the Division 1 pool is fixed and 4-9 winners are expected, your expected share is (1-e^-lam)/lam
with lam = (games sold / 8,145,060) x r, where r is your combination's popularity relative to average:
at r = 0.75 the Superdraw's Division 1 EV rises by $0.10 per $0.95 game (+10 points), at r = 0.5 by $0.29
(+30 points). Published evidence that r < 1 is achievable: The Lott reported 8,647 entries on one diagonal
pattern (8-15-22-29-36-43) in Oct 2024, which would have paid $2,312.94 each from a $20M pool; Lotterywest
reports ~70% of Division 1 winners hold Slikpiks (a proxy for the quick-pick share of entries, which bounds
r below at ~0.7); the Otago study of 70M NZ Lotto lines found some six-number sets chosen so often a win
would split dozens or hundreds of ways. The last 8 base-week Division 1 counts here are [4,7,1,4,5,1,3,10]
(mean 4.4, variance 9.1, dispersion index 2.1 versus 1.0 for uniform popularity), consistent with that
heterogeneity. None of this gets Saturday Lotto over 100%.

### 2.7 Lotto Strike, Powerball, Weekday Windfall, Keno Classic, Scratch-Its, Set for Life

See the table; the model outputs are in `work/ev_results.md`. Two rule facts worth keeping: Powerball and
Oz Lotto do contain a WinFall-style roll-down (Division 1 added to the next lower winning division) but only
after 25 consecutive jackpots (Tatts Schedules C and E; SA Lotteries (Powerball) Rules; NSW rules), which is
unreachable because sales explode long before; and Lotto Strike's cap clause keeps excess money for future
Division 1 prizes (r.11(f) Div 1 (iii)) rather than rolling it down, so the cap caps the EV at ~84%.

## 3. Best candidate and the concrete next step

Best candidate: Lucky Lotteries (Mega Jackpot first, Super Jackpot second). It is the only Australian game
with a documented positive-EV period (Aug 2019), the only one whose per-ticket EV is independent of how many
other people buy, and the only one where the trigger (jackpot >= $35.0M / $27.2M) is a single public number
that moves by a known increment each draw.

Next step (one afternoon of work, no money):
1. Build the jackpot history: scrape or hand-record the Mega and Super Jackpot amount for every draw
   (The Lott results pages / Oz Lotteries draw archive; the Lott API used here does not expose Lucky
   Lotteries). Fields: draw number, date, jackpot on offer, whether won, ticket-pool sell-out time if shown.
2. From it compute: increment per draw (should be $215-255k / $120-137k), empirical P(jackpot won per draw)
   versus the theoretical 2.109% / 1.469%, draw frequency as a function of jackpot size (does the pool sell
   out faster above $20M?), and the fraction of cycles that crossed $35.0M / $27.2M since the current prize
   tables began.
3. Set alerts at $30M (Mega) and $23M (Super) (the subscription-based break-evens) and decide the stake rule
   in advance using Kelly on the full distribution (fixed prizes ~33% return, jackpot win probability
   1/9.48M per ticket): for any personal bankroll the Kelly fraction is a few dollars, so treat it as a
   positive-EV lottery ticket, not an investment.
4. In parallel, do the charity-lottery data pass described in 2.4 (ticket cap, price, prize value, clause,
   sell-through), because that is the one category that could show a draw well above 100% on face value.

Secondary data to collect while there: the Keno Mega Millions 10-spot jackpot (daily; alert at $10.6M) and
Oz Lotto jackpots above $100M (compute games sold from the Division 7 pool / 31.8% the morning after each
draw to track the effective jackpot against the $64M threshold).

## 4. Myths and non-edges

- Hot/cold/'due' numbers: draws are independent and uniform; frequency charts (Lotterywest publishes them)
  describe the past only. Picking frequently drawn numbers changes nothing; picking numbers other people
  avoid (over 31, no patterns, no sequences, not all from one row of the coupon) changes only how much you
  share a pari-mutuel prize, which is worth +5 to +10 RTP points in Saturday Lotto and at mega-jackpots and
  ~0 in base-week Powerball (section 2.6). It never makes a draw +EV on its own.
- Systems entries: a System 9 is 36 standard games on one ticket; same price per game, same EV per dollar,
  more chance of some prize because you bought more games. The 'Systems prize table' shows multiple small
  wins because many of your 36 games overlap, not because of extra value. Weekday Windfall's $1M-per-winner
  Division 1 is the only case where a system gives nothing extra at the top (fixed prize per winning game).
- Syndicates: divide cost and prize in the same ratio; EV per dollar is unchanged, variance is lower.
  Retailer syndicates add nothing; commercial online syndicates charge fees that lower EV.
- Buying when the jackpot is big: it does raise EV per ticket (Powerball base week 32-36%, $200M week 73%;
  Oz Lotto $100M 85%), but Australian jackpot games have never crossed 100% because sales rise faster than
  the jackpot. The 25-draw roll-down is a theoretical clause, not a strategy.
- Quick Pick vs own numbers: identical win probability; quick picks are uniform (average popularity), so a
  well-chosen unpopular self-pick is slightly better for sharing, a birthday pick slightly worse.
- Scratch-its 'tracking': without a published remaining-prize ledger there is nothing to track; the rules
  say prizes are available 'only until won' and games may be withdrawn. The free monthly 2nd Chance Draw is
  worth entering for tickets already bought.
- Second-chance draws, Players Club bonus draws, Double Win Day, Prize Boost: all raise EV at zero or small
  cost (Weekday Windfall 48% -> ~77% on Double Win Day) but none approaches 100%.
- Unclaimed prizes: the rules route them into prize/reserve funds that top up future prizes (Superdraws,
  guaranteed minimums); there is no published trigger a player can time beyond the advertised draws.
- Lottery betting / 'synthetic lotteries': prohibited in Australia since 2019.
- Set for Life and Keno 'spot 1-3' low-variance plays: lowest RTP in the market (~40%, ~60-75%).

## 5. Sources

Primary (read directly):
- [S1] Tattersall's Sweeps, Rules of Authorised Lotteries (TattsLotto, Super 66, Weekday Windfall, Oz Lotto,
  Powerball, Lucky Lotteries, Instant Scratch-Its, Set for Life), current PDF:
  https://mlaunetlottoendpoint01-axd3ftd8bnd8bfa4.z01.azurefd.net/nl-content-prod/pdf/Tatts_Rules_of_Authorised_Lotteries.pdf
  (older NT-gazetted copy with the same 24/25-draw and percentage clauses:
  https://legislation.nt.gov.au/api/sitecore/SubordinateLegislation/PDF?id=4192). Local text:
  work/data/tatts_rules_azure.txt.
- [S2] SA Lotteries (Powerball) Rules under the State Lotteries Act 1966 (25 consecutive draws then added to
  the next lower winning division): https://www.treasury.sa.gov.au/__data/assets/pdf_file/0019/518113/Lotteries-Powerball-Rules.pdf
  (clause text via search extract; direct download blocked).
- [S3] NSW Government Gazette No 107, 2019: Lotto Strike Rules Issue 4.0 (Rule 11 prize allocation, Maximum
  Jackpot Drawing Prize), plus NSW Saturday Lotto/Oz Lotto/Powerball rules with the 4- and 25-draw clauses:
  https://gazette.nsw.gov.au/gazette/2019/9/2019-107.pdf (work/data/nsw_gazette_2019_107.txt).
- [S4] NSW Keno Rules effective 19 May 2017 (Schedule of Prizes r.18, jackpot r.10, pro-rating r.19):
  https://stmarysleagues.com.au/wp-content/uploads/2022/08/Keno-Rules-19-May-17.pdf (current 23 Feb 2026
  rules at https://www.keno.com.au/keno-pdfs/nsw_rule.pdf were blocked from this environment).
- [S5] Keno NSW Game Guide (Classic and Mega Millions pay tables):
  https://www.thewestportclub.com.au/wp-content/uploads/2020/09/NSW_Game-Guide.pdf (also https://www.keno.com.au/keno-pdfs/NSW_Game%20Guide.pdf).
- [S6] Keno VIC/NSW Game Guide: https://s3-ap-southeast-2.amazonaws.com/keno-pdfs/VIC_NSW_Game+Guide.pdf
- [S7] Keno live jackpot feed (ACT jurisdiction): https://api-info-act.keno.com.au/v2/info/jackpots?jurisdiction=ACT
- [S8] The Lott public results API (winners and dividends per division, last 10 draws per game):
  POST https://data.api.thelott.com/sales/vmax/web/data/lotto/latestresults and .../opendraws
  (work/data/latest10_*.json, opendraws.json).
- [S9] Lotterywest game prices (include retailer commission): https://cdn.sanity.io/files/cabqvweh/lw-corp-production/97241028a689ab84b14fada4a9226e92e277d9b3.pdf
  and https://cdn.sanity.io/files/cabqvweh/lw-corp-production/571b091fd0b137b1c6d90d9baa528e93ed649ddf.pdf ;
  Powerball $1.20 -> $1.40 subscription from 6 Nov 2025: https://www.lotterywest.wa.gov.au/games/powerball-update
- [S19] Lotterywest Super66 (divisions, odds, WA $66,666 minimum): https://www.lotterywest.wa.gov.au/games/super66
- [S20] Lotterywest Oz Lotto odds: https://www.lotterywest.wa.gov.au/games/oz-lotto ; Saturday Lotto:
  https://www.lotterywest.wa.gov.au/games/saturday-lotto ; Powerball odds: https://www.lotterywest.wa.gov.au/games/powerball
- [S34] Lotterywest Weekday Windfall (fixed $1M Division 1): https://www.lotterywest.wa.gov.au/games/weekday-windfall
- [S36] Lotterywest Set for Life (prizes, 4-winner cap): https://lotterywest.wa.gov.au/games/set-for-life
- [S26] Dream Home Art Union general T&Cs: https://dreamhomeartunion.com.au/about/terms-and-conditions
- [S27] Example small art-union T&Cs (NSW authority GOCAU/2450): https://www.seslhd.health.nsw.gov.au/sites/default/files/groups/The_Sutherland_Hospital/documents/Terms_Conditions_Authority_Number_GOCAU_2450.pdf
- [S37] Interactive Gambling Amendment (Lottery Betting) Act 2018: https://legislation.gov.au/C2018A00073/asmade/2018-07-09/text/original/pdf ;
  [S38] Bills Digest: https://www.aph.gov.au/Parliamentary_Business/Bills_Legislation/bd/bd1718a/18bd106 ;
  [S39] ACMA finding against Lottoland: https://www.gtlaw.com.au/insights/acma-finds-lottoland-has-engaged-lottery-betting

Dividend tables (third-party mirror of The Lott's published results; transcribed in work/data/big_draws.json):
- [S21] Powerball 1 Feb 2024 ($200M): https://www.lotteryextreme.com/australia/powerball-dividends(2024-02-01)
- [S22] Powerball 25 Jan 2024, 28 Dec 2023, 30 May 2024: https://www.lotteryextreme.com/australia/powerball-dividends(2024-01-25) ,
  https://www.lotteryextreme.com/australia/powerball-dividends(2023-12-28) , https://www.lotteryextreme.com/australia/powerball-dividends(2024-05-30)
- [S23] Oz Lotto 4 Feb 2025 ($100M): https://www.lotteryextreme.com/australia/ozlotto-dividends(2025-02-04)

Secondary (news, operator blogs, help pages; several only via search extracts because the sites block fetches):
- [S10] The Lott help, odds of each game (Lucky Lotteries jackpot odds 1 in 9,483,168 / 18,385,876):
  https://help.thelott.com/hc/en-us/articles/35525459564441-What-are-the-odds-of-each-game ;
  https://help.thelott.com/hc/en-us/articles/4422500461337-What-are-the-chances-of-winning-division-one
- [S11] $96M Mega Jackpot, draw 1447, 26 Aug 2019: https://www.ozlotteries.com/blog/lucky-lotteries-winner-96-million-richer ;
  https://www.ozlotteries.com/mega-jackpot-lottery/results/draw/1447 ; [S12] https://thenewdaily.com.au/news/good-news/2019/08/27/sydney-dad-big-lottery/
- [S13] $27.5M Mega Jackpot after 99 draws, 16 Mar 2026: https://newcastleweekly.com.au/nelson-bay-resident-pockets-life-changing-27-5m/
- [S14] Super Jackpot advertised $19.22M, draw 10988, May 2025: https://lilydale.mailcommunity.com.au/news/2025/05/27/mt-evelyn-man-scores-the-lottery/
- [S15] Super Jackpot $8.82M after 65 draws (draw 10091, 2016): https://www.centralwesterndaily.com.au/story/4043876/golden-ticket-8m-win-for-nan
- Lucky Lotteries prize tables (consistent with Schedule F): https://www.lotterypros.com/lotteries/lucky-lotteries/ ;
  Mega Jackpot $11.73M Jan 2020 and yearly totals via search of https://www.ozlotteries.com/blog/
- [S16] Keno $8.86M, Gladstone, Jan 2026: https://www.broomead.com.au/lifestyle/like-a-movie-queensland-tradie-snags-nations-second-biggest-keno-win-in-history-taking-home-88m-c-21224925 ;
  https://thedrop.com.au/8-8-million-keno-win/
- [S17] Keno $7.9M Lambton 2018: https://nbnnews.com.au/?p=320881 ; [S18] $6.59M Randwick 2019: https://thedrop.com.au/p/8383 ;
  Classic 10-spot $2.43M Kew: https://www.portnews.com.au/story/7288149/mystery-kew-keno-winner-sitting-on-a-24-million-ticket
- [S24] Oz Lotto $100M Feb 2025 ('up to a third of adults'): https://www.indailysa.com.au/news/just-in/2025/02/04/oz-lotto-jackpot-100m ;
  nine-week Oz Lotto run Dec 2023: https://www.canberratimes.com.au/story/8466149/
- [S24b] Powerball $150M Jan 2024 ('fifth consecutive week', 'half of adults'): https://aapnews.aap.com.au/news/powerball-jackpot-jumps-to-150-million ;
  Powerball record list: https://en.wikipedia.org/wiki/Powerball_(Australia)
- [S25] yourtown FAQ on maximum tickets per draw: https://support.yourtown.com.au/hc/en-us/articles/360000830493-What-are-the-odds-of-winning-First-Prize ;
  Mater lottery T&C index: https://support.materlotteries.com.au/hc/en-au/articles/360037877293-Terms-and-Conditions
- [S28] Super 66 record $380,724 (22 Jul 2017): https://lotteryguru.com/australia-lottery-results/au-super66
- [S29] The Lott diagonal-pattern data (8,647 entries; $2,312.94 each): https://www.thesenior.com.au/story/9057978/maximise-your-lotto-win-by-avoiding-these-number-mistakes/
- [S30] Crack and Whigham (Univ. of Otago), NZ Lotto number-popularity study: https://www.yourlifechoices.com.au/life/can-picking-personal-lotto-lines-change-the-odds-of-winning-we-ran-the-numbers/ ;
  https://www.1news.co.nz/2026/07/08/lotto-whats-better-a-lucky-dip-or-your-own-numbers/
- [S31] Lotterywest: ~70% of Division 1 winners on Slikpik: https://lotterywest.wa.gov.au/lotterywest/media-centre/most-popular-lotto-ticket-making-superdraw-millionaires-revealed ;
  most-drawn numbers 1985-2025: https://www.broomead.com.au/news/lotto/lotto-luckiest-saturday-lotto-numbers-of-last-forty-years-revealed-ahead-of-30-million-mega-draw-on-july-26-c-19399665
- [S32] Lotto Strike prize table, 45/10/45 pool split, $1.15, current jackpot: https://au.lottonumbers.com/lotto-strike ;
  [S33] $2,000,000 maximum jackpot: https://www.ozlotteries.com/lotto-strike
- [S35] Lotterywest Scratch'n'Win remaining-prize statements (media releases only): https://lotterywest.wa.gov.au/lotterywest/media-centre/south-west-and-kimberley-revealed-as-wa2019s-scratchie-hot-spots-1
- [S40] Cash WinFall analysis: https://www.bostonglobe.com/metro/2011/10/15/game-chance-became-anything-but/wWOhnxW8Z7aJxZfEGKTAmN/story.html ;
  [S41] Massachusetts OIG report on Cash WinFall: https://archives.lib.state.ma.us/server/api/core/bitstreams/ea1512d5-cb14-4881-a5c1-67fc2cfabcb5/content
- [S42] Virginia February 1992 cover-all by the Melbourne-based International Lotto Fund (Stefan Mandel; 7,059,052
  combinations for a ~$27M jackpot; investigated and found lawful, after which Virginia changed its rules):
  https://www.qedcat.com/archive_cleaned/102.html ; https://thehustle.co/the-man-who-won-the-lottery-14-times-part-1 ;
  https://mymodernmet.com/stefan-mandel-lottery . Australian Powerball EV discussion:
  https://thomasthethinkengine.com/2022/02/22/should-you-play-powerball-the-three-levels-of-naivety-plus-one-bonus-level/

Blocked from this environment (could not be fetched; all facts above come from the alternatives listed):
thelott.com game pages and rule PDFs (incl. NSWL Lucky Lotteries Game Rules June 2025), help.thelott.com,
ozlotteries.com, keno.com.au PDFs and NSW/VIC/QLD jackpot feeds, treasury.sa.gov.au PDFs, charity operators'
draw T&C PDFs.

## 6. Assumptions and uncertainty

- Retail prices are Lotterywest's (WA) published prices including commission; The Lott's Victorian prices
  can differ by a few cents. Commission is taken as 11.1% of retail (exact for Powerball; assumed for others).
- Sales (games sold) are inferred as pool / rule percentage for non-jackpot divisions, taking the median
  across divisions; the bloc may vary allocations within +/-5 points (r.10.8), so sales are +/-5-10%.
- Keno pay tables are the NSW/VIC/ACT ones; QLD's differ. Jackpot records are from news reports, not a
  complete ledger.
- The Lotto Strike $2M cap comes from resellers, not from the gazetted rule, which only says 'as approved by
  the Licensee from time to time'.
- No fairness test was run (optional in the brief); the only bulk history reachable was 10 draws per game.
