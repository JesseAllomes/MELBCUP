# Layout lock (race page, phone column max 460px)
1. Wallet bars (sticky): Sportsbet, Betfair.
2. Race strip R1..R10.
3. Header: big saddlecloth race number, race name, day/time/distance/field/going.
4. Win, place, each way: two amount inputs (Sportsbet, Betfair), one-line split note, board of three picks (type, cloth+name, stake, verdict pill, price pills, chance + return line, Placed buttons).
5. Exotics in this race: First Four (this race), Quaddie on its first race ("starts here"), Quaddie leg line on later races, Quinella and Trifecta (stake, lands 1 in N, share of dividend, "worth a try only if estimate over $X", Placed on Sportsbet).
6. The field: cloth, name, price pills (SB/BF), "Wins 1 in N · places 1 in N"; top 6 then "Show all N runners".
7. Last-minute check card (bottom).
8. Gambling Help Online line.
Day page: wallet bars + race strip + list of races (time, this race's stake), then "Multi picks for the day" (owner, 2026-11-01): a card per multi, legs as rows, stake, SB price pill, Good/Short price, Placed on Sportsbet. No day-wide quaddie block.

## Sheet layout (v13)
Max width 460px, max height 92dvh, safe-area bottom padding, 44px+ touch targets, one primary button per sheet. Slip bar floats above the bottom tab bar (72px + safe area). My bets pill sits at the top of every sports page. Server forms live in `.sheet-src` blocks (hidden) opened by `[data-sheet-for]`.
