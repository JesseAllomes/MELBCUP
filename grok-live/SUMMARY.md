# Azure live vs GitHub main (read-only audit, 2026-11-07)

## Resources
- melbcup-web (container app): image ...@sha256:375dd04a..., top layer "deploy_azure.py code layer cb61125f" (cb61125f is NOT a commit in the repo),
  last modified 2026-11-06 06:53 UTC by jesseallomes@gmail.com (user, not CI SP; CI SP 8cfbb9d5 last wrote 2026-11-05 23:21). Env var names, 0.25cpu/0.5Gi, scale 0-1, secrets: match spec.
  Only ARM diffs are server-added (fqdn, exposedPort, ephemeralStorage, pollingInterval, identitySettings, registries.identity).
- melbcup-nba (job): image ...@sha256:17672d8f..., layer 427d7bbe (a real commit, 2026-11-05 20:59), by CI SP. Config == spec. Live is OLDER than main, not newer.
- func-personal-v5ethud2i3cfq: package a5c2d383 (deployed 2026-11-05 21:31 UTC), max 1 instance/512MB, settings names == app.json (+platform extras, COLLECTOR_DISABLED, NBA_HISTORY).
  Site lastModified 2026-11-06 13:50 is a settings/config touch, not code. Code == main except nba_challenge.py (older).
- NEW, not in repo: Function app func-sports-v5ethud2i3cfq (Flex, maxInstances 100, 512MB, python 3.12, one HTTP function `sports`, auth level FUNCTION).
  Created 2026-11-06 05:41-05:54 UTC by jesseallomes@gmail.com (new ASP, role assignments, container app-package-funcsportsv5ethud2i3cfq-9224792 in stpersonalv5ethud2i3cfq).
  Not covered by azure/function/app.json or cost guard.

## Web: files changed vs main (whitespace/CRLF ignored; live files are CRLF, 37 .py files differ only by formatting)
Live = an OLDER base tree (before main's last commits) + Grok's uncommitted Sports feature.
Missing from live (in main): /data + /data/{name} dataset endpoints (app.py), nba_feed.blob_names, challenge `pick`/`best` actions
(nba_challenge.py, views.py chosen=state.pick, nba.html links). Live reverts these to `chpick` query-param behaviour.
Added in live only (uncommitted): melbcup/sport_board.py (413 lines), melbcup/sport_lines.py (366), templates/asynym/sports.html, /sports route in views.py
(imports sport_board), "Sports" nav link in _header.html, ~60 lines asynym.css.
Also in the image: pyproject.toml/build dir from base (ignore).

## Job: nba_legs.py only (live lacks main's change)
Main has OVER_SHADE = 0.013; _SHIFT = OVER_SHADE/0.25; shade(c, under): logit(c) +/- _SHIFT (overs down, unders up), applied in apply_market after blend, g["raw"] kept.
Live has none of that (c = blend, chance = c). Not Grok's; just undeployed.

## Function personal: nba_challenge.py only (older, same pick/best difference as web)
## Function sports: function_app.py (84 lines, renders ranked("football") page) + melbcup/sport_board.py (397 lines, older than web's: no Sportsbet live card) + requirements azure-functions

## Maths in Grok's code (sport_lines.py / sport_board.py)
- devig (sport_lines): chance_i = (1/price_i) / sum_j(1/price_j)   (proportional margin removal)
- best_ticket: brute-force combinations/product, one winner-market leg per game, up to 8 legs; price = prod(price), chance = prod(chance) (independence);
  keep price >= 2.0 with highest chance, tie -> fewer legs (key = (chance, -count, price)).
- sport_board.offer: settled = (1 + min(roi_early, roi_late)) / hit ; returns None if worse ROI <= 0 or settled above bucket body
  (_in_body: price <= lo + 0.7*(hi-lo)); floor = max(lo, 1/hit, settled, 2.0**(1/count)); needs hi-floor >= 0.03; legs 1..12 fewest wins.
- ticket: chance = hit**count ; low = wilson(hit,bets)**count ; multi = floor**count.
  wilson lower bound: (hit + z^2/2n - z*sqrt((hit(1-hit)+z^2/4n)/n)) / (1+z^2/n), z=1.96.
- hard-coded tables: _ROI (8 market/band early/late best-price ROI pairs, e.g. 1X2 H 1.20-1.35 = (0.059, 0.018)), _FOOTBALL hit rates (e.g. 1X2 A 1.20-1.35 = 0.783 on 1098 bets), from football_scan_v1; _TAIL = 0.30, _MIN_WINDOW = 0.03.
- No stake sizing / Kelly found.
## Files
DIFF-web.patch (whitespace-insensitive, incl. new files), DIFF-web.raw-whitespace-noisy.patch, DIFF-job.patch, DIFF-function.patch,
extracted code: L-web/ L-job/ L-func/ S-func/ ; reference trees ref/ ; live ARM json *.live.json (no secrets printed).
