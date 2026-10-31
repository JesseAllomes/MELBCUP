# MELBCUP

Preparing for the Melbourne Cup.

MELBCUP is a live, password-protected web app for your phone. It rates every runner on
Melbourne Cup day (Flemington, Tuesday 3 November 2026) using form, connections and market
data. Each race shows two lines of picks:

- **Most likely**: the runner with the highest chance of winning, and of placing, whatever the
  price. When it is the same horse (almost always), it is shown once as *Win & place*.
- **Best price for chance**: win, place and each-way bets whose price beats the runner's chance
  by enough. Many races have none, and the page says so.

Then the exotics. In detail:

| Category | What you get |
|---|---|
| **Win** | Each runner's chance, the fair price for that chance, the best bookmaker price and its edge |
| **Place** | The same for the place, using the places the race actually pays |
| **Each way** | Half on the win and half on the place, at the best price for each part |
| **Trifecta** | Straight, box, standout and banker structures with hit chance and fair dividend |
| **First Four** | Box and standout structures for the first four in one race |
| **Quaddie** | The Early Quaddie and the Main Quaddie, picked to land as often as possible within a combination budget |
| **Multi** | 2-leg and 3-leg win multis at Sportsbet, valued as one bet |

Everything comes from racing.com, which is free and needs no key. Nothing is fetched until you
tap:

| Button | What it does |
|---|---|
| **Load card** / **Reload card** | Field and scratchings, recent runs and stewards' comments (racing.com) |
| **Refresh prices** | Sportsbet fixed-odds win and place prices (plus Ladbrokes, PointsBet and bet365) from racing.com, then new picks. At most once a minute |
| **Auto** | Hands-off: prices 60, 30, 15, 5 and 2 minutes before each race; results after each race |

The page itself re-reads the app every minute; that only redraws what the app already holds.

**Results and how the model went:** once races have run, tap **Get results**. Each race
then shows the placings with starting prices, where our top pick finished, and a tick or cross
with the return per $1 for the Win, Place, Each-way, Trifecta and First Four picks. Exotics are
paid at the official dividend, spread flexi across the structure. The top of the day page keeps
score: top pick wins and placings, profit on value bets and exotics, and whether each quaddie and
multi landed. A past meeting the app never priced is judged at starting prices, as in the backtest.

**History:** the History page (top right) lists every race the app holds results for: each
race's placings beside the model's Most likely, Value and exotic picks, ticked or crossed. At the
top, a tally per pick type gives picks, landed, missed, the rate and the return per $1. It starts with
the 1,160 saved races and adds each new meeting as its results come in.

**Any meeting, any day:** tap the meeting name at the top (**change**). The Cup Carnival days at
Flemington are one tap each. For any other day, pick the date and tap **Find meetings**
to list every Australian meeting with a published field, then tap one. Switching costs nothing;
**Load card** then fetches it. Bookmakers price a meeting a day or two before, so prices
appear once they are framed. Form and picks work for any day with a field.

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
FormFav's model and 31% for the fitted form model alone.

**Read these results as development figures, not proof.**

- **Same month throughout:** this one month was also used to choose the factor weights, the blend,
  the $21 cap and the 40% edge limit.
- **Starting price only:** results are measured at starting price, not at the prices the app sees
  before the jump.
- **Leaked people figures:** historical jockey and trainer figures were downloaded afterwards, so
  they include races run later.
- **What follows:** the earlier +9.8% return on VALUE win bets, and the pattern table that used to
  sit here (e.g. jockey at the track, A/E 1.08), are not evidence of an edge. The 1.716 against
  1.725 log-loss gap is within noise.
- **Head-to-head:** on held-out days the form factors did not beat the odds. Where the model's top
  pick was not the favourite, the favourite still won more often: 26.6% against 24.4%.

The replacement work runs on racing.com's national history from July 2022 (about 90,000 races):

- jockey, trainer and track-bias figures rebuilt strictly as of each race date;
- bets chosen and paid at the timestamped prices 60, 30, 10 and 2 minutes before the jump;
- calibration tables and race- and day-level confidence intervals;
- an explicit upset model fitted against the market;
- the newest 20% of dates kept as an untouched final test.

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
| [racing.com](https://www.racing.com/) | Free, no key needed | The field and scratchings, each runner's recent runs with stewards' comments, fixed-odds win and place prices from Sportsbet (used for the verdicts and the multis), Ladbrokes, PointsBet and bet365, and results with tote dividends. National coverage |
| [FormFav](https://formfav.com/) | Pro | Long-form career splits, speed maps, class ratings, predictions, jockey and trainer records (with their record on each going), and track bias |

FormFav is optional, but without Pro the app loses jockey and trainer records, predictions and
track bias, and says so at the top of the page.

racing.com is read through the public data service its own form pages use, with the key those
pages send; the app reads it from your phone for personal use. If racing.com is down or changes
it, the page says so and keeps the last good board. racing.com publishes no First Four dividend, so a First
Four graded from its results is ticked or crossed with its return unknown.

Owner names are shown when racing.com has them but are not scored: tested on the saved month,
owner records added nothing.

## Share it with friends

Send them the link (https://jesseallomes.github.io/MELBCUP/). On first open the app asks for one optional key:

- **FormFav key:** optional. racing.com needs no key, so nobody spends anyone else's quota.

The 1,160 saved races and their graded picks open for everyone with no password.

## Put it on your phone (GitHub Pages, free)

MELBCUP runs entirely in your phone's browser: GitHub only serves the page, and your phone calls
racing.com and FormFav itself. Nothing sleeps, and nothing runs anywhere else.

One-time setup on GitHub:

1. **Make the repository public:** Settings → General → Danger Zone → Change visibility →
   Public. The code contains no keys or passwords.
2. **Turn on Pages:** Settings → Pages → Build and deployment → Source: *Deploy from a branch* →
   Branch: `main`, folder `/docs` → Save.
3. After a minute or two, open `https://<your-github-name>.github.io/melbcup/` on your phone and
   add it to the home screen.

On the phone, **Auto is off each time you open the page**, so opening it never fetches by itself.
Tap **Auto off** to switch it on for that visit: it loads the card once, checks prices 60, 30,
15, 5 and 2 minutes before each race, and fetches results about ten minutes after each race,
grading the picks. It runs only while the page is open. One price check covers the whole card,
so checks that fall in the same minute are shared. It prices any meeting whose field is out,
once the bookmakers have framed it.

A card load fetches its requests six at a time (about 100 for a full card with FormFav). Pages
tapped while it runs open as soon as it finishes.

**Saved meetings:** 154 meetings (about 1,160 races, 29 September to 29 October 2026) downloaded
for the backtest are stored in `docs/data` and open directly, with no password and no API calls,
results included. Rebuild with
`python tools/build_archive.py <folder of collected races>`.

On first open, the app asks for an optional FormFav key. It is saved on that phone only. The first start downloads the Python runtime (about 10 MB, from jsDelivr), and later
starts are quick. The loaded card, prices and results are kept on the phone too, so reopening the
page fetches nothing.

A card load runs one request at a time in the browser, so it takes 1 to 2 minutes with full
FormFav data; a progress bar shows each request.

After changing code under `melbcup/`, run `python tools/build_pages.py` to refresh `docs/`. The
tests fail if `docs/` is out of date.

### Or run it as a server

`render.yaml` deploys the same app as a password-protected server on Render: New → Blueprint, set
`FORMFAV_API_KEY` (optional) and `APP_PASSWORD`. On Render's free plan the server
sleeps after 15 minutes idle.

## Run it locally

```bash
python3 -m venv ~/.venvs/melbcup && . ~/.venvs/melbcup/bin/activate
pip install -e ".[dev]"
export FORMFAV_API_KEY=... APP_PASSWORD=...   # FORMFAV_API_KEY is optional
uvicorn melbcup.web.app:create_app --factory --reload
pytest && ruff check .
```

## Layout

```
melbcup/config.py         settings from environment variables
melbcup/domain.py         normalised race, runner and price types
melbcup/sources/          racing.com and FormFav clients; card assembly
melbcup/model/            factors, form model, blend, place probabilities
melbcup/bets/             win/place/each-way, exotics, quaddies, multis, staking
melbcup/live.py           background refresh on a race-by-race schedule
melbcup/web/views.py      pages and button actions, shared by server and browser
melbcup/web/app.py        FastAPI server (Render)
melbcup/web/templates/    the pages
melbcup/browser.py        browser entry point (Pyodide, GitHub Pages)
docs/                     the GitHub Pages site (index.html, main.js, worker.js + built copy)
tools/build_pages.py      refreshes docs/ from the package
```
