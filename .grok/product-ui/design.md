# Design lock
- Saddlecloth chips: white, black number, 1.5px border, every runner number on the page.
- Price pills: navy outline = Sportsbet, amber outline = Betfair; the better price is filled.
- Verdict pills: "Good price" rose filled; "Short price" muted outline. Never BET/HOLD/SKIP/For fun.
- Stakes: large condensed "$N"; every pick and exotic shows its $ from the day amounts.
- Placed buttons: "Placed on Sportsbet" / "Placed on Betfair" pills; pressed = filled in that bookie colour, text "✓ Placed $N on …". Exotics: Sportsbet only.
- Wallet bars: Sportsbet navy, Betfair amber; "$X left of $Y"; sticky at the very top.
- Last-minute check card: silk sash in the corner; records only.

## Bottom sheet (v13)
All forms and detail open in a bottom sheet: slides up (cubic-bezier .2,1.15,.3,1), follows the finger, closes past 30% of its height or on a flick over 0.5 px/ms, else springs back. Backdrop tap and Esc close; sheets stack (lower one dimmed); body scroll locked; drag-to-close only from the head or scroll top; reduced motion respected. Tick control (32px) on every leg; floating slip bar; "My bets" pill with count and live dot.
