# Candidate corrections f(X): what the market may underuse

Each family is built under PROTOCOL.md section 3:
- history comes only from earlier days at other meetings, or earlier races at the same meeting;
- only whitelisted per-run fields are used;
- features are computed event by event.

Coverage figures come from a 600-meeting sample (Apr–Sep 2026, 42,464 runners).
The final availability table is in the protocol.

**How it really ran last time (previous runs only)**

| Family | Built from | Coverage | Why the odds may miss it |
|---|---|---|---|
| Closing-sectional rank | last-600 `timeSectional` rank within its race; vs finish position | 86% | Punters read the finish, not the closing speed |
| Ground made | settled → 800 → 400 → finish positions | 87–89% | Effort hidden by an ordinary finish |
| Stewards' excuse | keyword flags on `commentStewards`: slow to begin, held up / checked / crowded, wide no cover, raced keenly, blundered | 47% | Casual money ignores excuses |
| Bad-sign comments | bled, lame, eased, vet, irregular heart rhythm | same | Short favourites with hidden problems |
| Wide run / distance travelled | `timing.distanceTravelled`, `distanceFromRail` | 17% | Rarely visible |
| Top speed / 200 m splits | `timing.topSpeed`, `times[]` | 26% | Not readably published |

**Today's race shape**

| Family | Built from | Coverage | Why the odds may miss it |
|---|---|---|---|
| Run style vs expected pace | each runner's settled positions over earlier runs; field's count of habitual leaders | from history | Pace is the most common reason favourites lose |
| Same-meeting bias | winners' settled position and barrier in earlier races at this meeting today | sequential | The market adapts slowly |
| Track / rail change | per-race `trackConditions` vs the morning; rail position | 98% | Early prices are set on old conditions |

**The market itself (quotes at or before T only)**

| Family | Built from | Coverage | Why the odds may miss it |
|---|---|---|---|
| Market move | each bookmaker's open → T price change | 93% | Informed money |
| Bookmaker disagreement | sb vs lb margin-free probabilities at T | 93% | One side knows something |
| Favourite strength | gap to second favourite; favourite's own move | 93% | Weak favourites |

**Connections in context (as of the race, from earlier days)**

| Family | Built from | Why the odds may miss it |
|---|---|---|
| Jockey up/downgrade | today's jockey's prior-180-day strike and A/E vs last start's jockey | Stable intent |
| Stable form | trainer's prior-14-day and 90-day strike and A/E | Faster than season stats |
| Jockey × trainer | prior A/E of the pair | Needs the big sample |

**Horse in context**

| Family | Built from | Why the odds may miss it |
|---|---|---|
| Class / rating change | race class and `handicapRating` vs last start (rating flagged as possibly revised) | Drops over- or under-bet |
| Unproven conditions | first time at the trip, track or going (from its earlier runs), plus the sire's prior wet A/E | Uncertainty |
| Barrier × field × distance × track | prior A/E by cell, shrunk | Specific combinations |

**Favourite-specific composites (exploratory unless fixed in amendment A)**

- **False favourite:** short price not backed by form, e.g. a soft last-start win, or big-name
  connections with a weak sectional.
- **Favourite exposed:** wide barrier, backmarker against a slow pace, unproven today, drifting
  from open to T.
