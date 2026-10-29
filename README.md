# MELBCUP

Preparing for the Melbourne Cup.

MELBCUP is a live, password-protected web app for your phone. It rates every runner on
Melbourne Cup day (Flemington, Tuesday 3 November 2026) using form, connections and market
data. It then shows the best bet in each category:

| Category | What you get |
|---|---|
| **Win** | Each runner's chance, the fair price for that chance, the best bookmaker price and its edge |
| **Place** | The same for the place, using the places the race actually pays |
| **Each way** | Half on the win and half on the place, at the best price for each part |
| **Trifecta** | Straight, box, standout and banker structures with hit chance and fair dividend |
| **First Four** | Box and standout structures for the first four in one race |
| **Quaddie** | The Early Quaddie and the Main Quaddie, picked to land as often as possible within a combination budget |
| **Multi** | 2-leg and 3-leg win multis at Sportsbet, valued as one bet |

You control the PuntersEdge credits. The top of every page shows the credits left, and nothing is
spent until you tap:

| Button | Credits | What it does |
|---|---|---|
| **Load card** / **Reload card** | about 2 + 3 per race (~32 for ten races) | Field, scratchings, recent runs, then prices |
| **Refresh prices** | 2 | Every bookmaker's price for the whole card, then new picks |
| **Auto** | varies | Hands-off: prices every 15 min early, every minute from 20 min before each race, and the form hourly |

The page itself re-reads the app every minute; that costs nothing.

**Any meeting, any day:** tap the meeting name at the top (**change**). The Cup Carnival days at
Flemington are one tap each. For any other day, pick the date and tap **Find meetings** (2 credits)
to list every Australian meeting with a published field, then tap one. Switching costs nothing;
**Load card** then fetches it. Bookmakers price a meeting from the evening before, so prices
exist only for today's and tomorrow's meetings. Form and picks work for any day with a field.

After Render wakes the app from sleep, it starts on `RACE_DATE`/`VENUE` (Cup day at Flemington
unless set), so choose the meeting again if you were on another.

## Backtest

`melbcup/backtest.py` replays 1,131 Australian races (29 September to 29 October 2026). It uses
only what was known before each race: Racing Australia acceptances and FormFav's point-in-time
form. It then compares the predictions with the official starting prices and results.

| On days the fit never saw (10 splits) | Log loss (lower is better) |
|---|---|
| Market starting prices | 1.725 |
| MELBCUP blend | 1.716 |

The market is the best single predictor. Its favourite won 38.7% of races, against 30% for
FormFav's model and 31% for the fitted form model alone. Win bets the app marks VALUE, at an
edge of +5% to +40% and $21 or shorter, returned **+9.8% at starting price** over 1,075 held-out
bets. Across the splits that ranged from −3% to +29%. It is promising, not proven: roughly 340
independent bets, about one standard error above break-even. Real fixed prices are usually
better than starting price. Edges above +40% and runners over $21 lost heavily, so the app
never calls them value.

What winners had in common, against what the market expected (A/E above 1 means under-rated):

| Pattern | A/E |
|---|---|
| FormFav's top pick | 1.18 (the strongest signal) |
| Top handicap rating in the field | 1.15 |
| Won last start | 1.13 |
| Jockey with 15%+ wins at the track | 1.08 |
| Mares and fillies | 0.95 |
| Unplaced last start | 0.93 |
| Third up from a spell | 0.82 |

The factor weights in `melbcup/model/features.py` are the fitted ones.

## How it decides

1. **Form model.** 24 factors per runner: recent finishing positions and margins, career, track,
   distance, track-and-distance and going records, first- and second-up records, handicap
   rating, class rating, weight, jockey and trainer form over the last 90 days and at
   Flemington, barrier bias at this distance, speed-map position, days since the last run, sex,
   last-start finish, weight and rating changes, first-time gear, and FormFav's own rating.
   Each factor is scored against the rest of the field, and weighted as the backtest found.
2. **Blend.** That model is combined with the bookmakers' combined market, with each bookmaker's
   margin removed first. The backtest set the mix: market 1.0, form model 0.3.
3. **Value.** A price is marked **VALUE** only when it beats the fair price by enough. The bar is
   +5% at short prices and rises with the price. It is never given above +40% or over $21,
   where the backtest lost.
4. **Placings.** Place, trifecta, first four and quaddie chances come from the win chances. They
   use the Harville method with the standard discount for minor placings.
5. **Stakes (optional).** If you enter a day budget, stakes use quarter-Kelly sizing. No single
   bet takes more than 5% of the budget, each recommended exotic gets 1%, and the total never
   exceeds the budget. The app never places bets.

Exotic dividends are not known until a race is run, so for those the app shows the **fair
dividend**: what a $1 unit must pay to break even. If the TAB's approximate dividend is
higher, the structure is value.

These are estimates. They put the odds in your favour where the data allows; they do not
guarantee results. Gambling Help Online: **1800 858 858**.

## Data

| Source | Plan | Used for |
|---|---|---|
| [PuntersEdge](https://puntersedge.online/) | Free key (3,000 credits/month); $9/month Hobby if credits run out | The field, owners, gear changes, scratchings, recent runs, and win and place prices from 15 bookmakers including Sportsbet |
| [FormFav](https://formfav.com/) | Pro, $10/month with a 7-day free trial | Long-form career splits, speed maps, class ratings, predictions, jockey and trainer records, and track bias |

PuntersEdge is required. FormFav is optional, but without Pro the app loses jockey and trainer
records, predictions and track bias, and says so at the top of the page.

In manual mode a race day typically costs one card load (~32) plus 2 per price refresh: about 100
credits for a refresh before each race and a few extra near the big ones. Auto mode from
mid-morning costs about 1,100. FormFav calls are covered by its own allowance. Owner names come from Racing
Australia's acceptances and are shown, but not scored, because no feed has owner strike rates.

## Put it on your phone (Render, free)

1. Get the keys:
   - Sign up at puntersedge.online and copy your API key.
   - Sign up at formfav.com, start the Pro trial and copy your API key.
2. Go to [render.com](https://render.com) and sign in with GitHub.
3. Choose **New → Blueprint**, then pick the `MELBCUP` repository. Render reads `render.yaml`.
4. When it asks for environment variables, enter:
   - `PUNTERSEDGE_API_KEY`: your PuntersEdge key
   - `FORMFAV_API_KEY`: your FormFav key
   - `APP_PASSWORD`: a password you choose for the site
   - `PRICE_MODE`: leave as `manual`, or `auto` to start with Auto on
5. Deploy. Open the `…onrender.com` address on your phone. When asked to log in, leave the
   username blank and enter your password.
6. On your phone, use **Share → Add to Home Screen** so it opens like an app.

On the free plan the app sleeps after 15 minutes without a visitor, and the first visit after
that takes about a minute to wake it. Keep the page open on race day and it stays awake.

`RACE_DATE` (YYYY-MM-DD) and `VENUE` in Render set the meeting the app starts on. FormFav serves
race days from 30 days back to 7 days ahead.

## Run it locally

```bash
python3 -m venv ~/.venvs/melbcup && . ~/.venvs/melbcup/bin/activate
pip install -e ".[dev]"
export PUNTERSEDGE_API_KEY=... FORMFAV_API_KEY=... APP_PASSWORD=...
uvicorn melbcup.web.app:create_app --factory --reload
pytest && ruff check .
```

## Layout

```
melbcup/config.py         settings from environment variables
melbcup/domain.py         normalised race, runner and price types
melbcup/sources/          PuntersEdge and FormFav clients; card assembly
melbcup/model/            factors, form model, blend, place probabilities
melbcup/bets/             win/place/each-way, exotics, quaddies, multis, staking
melbcup/live.py           background refresh on a race-by-race schedule
melbcup/web/              FastAPI app, templates, styles
```
