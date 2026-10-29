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

Prices refresh every minute in the 20 minutes before each race, and the page updates itself.

## How it decides

1. **Form model.** 18 factors per runner: recent finishing positions and margins, career, track,
   distance, track-and-distance and going records, first- and second-up records, handicap
   rating, class rating, weight, jockey and trainer form over the last 90 days and at
   Flemington, barrier bias at this distance, speed-map position, and days since the last run.
   Each factor is scored against the rest of the field.
2. **Blend.** That model is combined with FormFav's own prediction model and the bookmakers'
   combined market, with each bookmaker's margin removed first. The market carries half the
   weight because it is the hardest to beat.
3. **Value.** A price is marked **VALUE** only when it beats the fair price by enough. The bar is
   +5% at short prices and rises with the price, to +25% for long shots. That is because
   estimates are least reliable at big prices.
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

A ten-race day uses about 1,300 PuntersEdge credits when the app runs from mid-morning: about
1,000 on prices and about 300 on the hourly form reloads. Owner names come from Racing
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
5. Deploy. Open the `…onrender.com` address on your phone. When asked to log in, leave the
   username blank and enter your password.
6. On your phone, use **Share → Add to Home Screen** so it opens like an app.

On the free plan the app sleeps after 15 minutes without a visitor, and the first visit after
that takes about a minute to wake it. Keep the page open on race day and it stays awake.

To try it on a different meeting day before Cup day, set `RACE_DATE` (YYYY-MM-DD) and `VENUE`
in Render. FormFav serves race days from 30 days back to 7 days ahead.

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
