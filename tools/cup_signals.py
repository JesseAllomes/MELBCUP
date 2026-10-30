"""Race-day bet signals from live prices: which bet, when, and the chance it collects.

Usage: python3 tools/cup_signals.py <meet code> [--race N] [--four-place-race N] [--sims 40000]
(Cup day 2026-11-03 at Flemington is meet 5195782; the Melbourne Cup is race 8.)

What the signals rest on (research/RESULTS.md, research/v2/*):
- No form factor beat the market, so a runner's chance is the market's: the margin-free consensus of the
  fixed-price books (Sportsbet, Ladbrokes, PointsBet, bet365 where priced), the same chance the app shows.
- Prices near the jump forecast better than morning prices, and the best price on offer is worth more than
  any model gain, so every bet is "at the best price, close to the jump".
- Place and exotic chances come from a Plackett-Luce simulation with the usual discounting of lower places
  (strength p for 1st, p^0.81 for 2nd, p^0.65 for 3rd and 4th).
- Each-way is only worth it where a bookmaker pays 1/4 odds and 4 places (3 places loses at every price in a
  24-horse Cup). Fixed place beats tote place. Exotics lose about 20% on average (long-shot-heavy ones
  40-55%); the least bad is boxing the market's top four, shown only when it comes in often enough.
These are the market's best estimates, not a proven edge.
"""
import argparse, json, math, urllib.request
import numpy as np

URL = "https://graphql.rmdprod.racing.com/"
KEY = "da2-6nsi4ztsynar3l3frgxf77q5fe"
ALPHA = 1.0     # plain market chance, as in the app; the 1.13 odds adjustment is promising but not deployed (research/RESULTS.md)
BOOKS = {"sb": ("SB2", "Sportsbet"), "lb": ("LB2", "Ladbrokes"), "pb": ("PB3", "PointsBet"), "bt": ("BT", "bet365")}
HOME = "sb"                # the owner bets only with Sportsbet: every pick shows Sportsbet's price and a verdict on it
EXOTIC_BAR = 0.20          # show a top-four trifecta box as "a try" only if it comes in at least this often
VALUE_EDGE = 0.05          # a price counts as above fair if price x chance - 1 >= 5%


def gql(query, variables):
    req = urllib.request.Request(URL, json.dumps({"query": query, "variables": variables}).encode(),
                                 {"x-api-key": KEY, "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["data"]


def money(x):
    try:
        v = float(str(x).replace("$", ""))
        return v if v > 1 else None
    except (TypeError, ValueError):
        return None


def race(meet, n):
    books = " ".join(f'{a}: oddsByProvider(providerCode:"{c}"){{oddsWin oddsPlace}}' for a, (c, _) in BOOKS.items())
    q = ("query($m:ID!,$n:Int!){GetBettingData(meetCode:$m,raceNumber:$n){name time officialTime distance "
         "formRaceEntries{raceEntryNumber horseName barrierNumber scratched emergency " + books + "}}}")
    d = gql(q, {"m": meet, "n": n})["GetBettingData"]
    runners = []
    for e in d["formRaceEntries"]:
        if e.get("scratched") or e.get("emergency"):
            continue
        win, place = {}, {}
        for a in BOOKS:
            o = e.get(a)
            o = (o[0] if isinstance(o, list) and o else o) or {}
            if money(o.get("oddsWin")):
                win[a] = money(o.get("oddsWin"))
            if money(o.get("oddsPlace")):
                place[a] = money(o.get("oddsPlace"))
        runners.append(dict(no=e["raceEntryNumber"], name=e["horseName"], barrier=e.get("barrierNumber"), win=win, place=place))
    return d, runners


def chances(runners):
    """market chance per runner: mean over books of each book's margin-free probability, then m^alpha."""
    books = [a for a in BOOKS if all(a in r["win"] for r in runners)]
    if not books:
        return None
    m = np.mean([np.array([1 / r["win"][a] for r in runners]) / sum(1 / r["win"][a] for r in runners) for a in books], axis=0)
    p = m ** ALPHA
    return p / p.sum(), books


def simulate(p, sims, rng):
    """finishing orders (first four) by Plackett-Luce with discounted strengths for lower places."""
    n = len(p)
    out = np.empty((sims, min(4, n)), dtype=int)
    for k, expo in enumerate((1.0, 0.81, 0.65, 0.65)[: out.shape[1]]):
        s = np.tile(p ** expo, (sims, 1))
        for j in range(k):
            s[np.arange(sims), out[:, j]] = 0
        s /= s.sum(1, keepdims=True)
        u = rng.random(sims)[:, None]
        out[:, k] = (s.cumsum(1) < u).sum(1).clip(max=n - 1)
    return out


def verdict(price, fair):
    """Sportsbet's price as a share of the fair price (1 / chance). Bookmakers normally pay 85-95% of fair."""
    if not price:
        return "no Sportsbet price"
    r = price / fair
    word = ("good value" if r >= 1.0 else "reasonable" if r >= 0.90 else "a bit short" if r >= 0.82 else "short: poor value")
    return f"${price:g} = {r:.0%} of fair, {word}"


def places_paid(n, four=False):
    return 4 if four else (3 if n >= 8 else 2 if n >= 5 else 1)


def best(prices):
    if not prices:
        return None, None
    a = max(prices, key=prices.get)
    return prices[a], BOOKS[a][1]


def sheet(meet, n, sims, four_place, rng):
    d, rs = race(meet, n)
    start = (d.get("officialTime") or d["time"])[11:16]
    head = f"Race {n} - {d['name']} ({d.get('distance')}, {len(rs)} runners, {start} UTC)"
    c = chances(rs) if rs else None
    if c is None:
        return head + "\n  No complete prices yet."
    p, books = c
    order = simulate(p, sims, rng)
    k = places_paid(len(rs), four_place)
    ks = places_paid(len(rs))      # places the normal place market pays (3, or 2 in small fields)
    placed = np.array([(order[:, :ks] == i).any(1).mean() for i in range(len(rs))])
    top = np.argsort(-p)
    lines = [head, f"  chances from {', '.join(BOOKS[b][1] for b in books)}; bet about 10 min before the jump"]
    for rank, i in enumerate(top[:4], 1):
        r = rs[i]
        wp, wb = best(r["win"])
        pp, pb = best(r["place"])
        conf = "High" if p[i] >= 0.40 else "Medium" if p[i] >= 0.30 else "Low"
        tag = []
        sw, sp = r["win"].get(HOME), r["place"].get(HOME)
        if sw and p[i] * sw - 1 >= VALUE_EDGE:
            tag.append("Sportsbet WIN price above fair")
        if sp and placed[i] * sp - 1 >= 0:
            tag.append("Sportsbet PLACE price at/above fair")
        placed3 = placed[i]
        lines.append(f"  {rank}. #{r['no']} {r['name']} (b{r['barrier']}): wins {p[i]:.0%} ({conf}), places {placed3:.0%} in the first {ks}")
        lines.append(f"     Sportsbet win {verdict(sw, 1 / p[i])} (fair ${1 / p[i]:.2f})"
                     + (f"; best elsewhere ${wp:g} {wb}" if wp and wb != "Sportsbet" else ""))
        lines.append(f"     Sportsbet place {verdict(sp, 1 / placed3)} (fair ${1 / placed3:.2f})")
        if tag:
            lines.append(f"     <- {'; '.join(tag)}")
        if four_place and sw:
            top4 = np.mean((order[:, :4] == i).any(1))
            ev = 0.5 * (p[i] * sw - 1) + 0.5 * (top4 * ((sw - 1) / 4 + 1) - 1)
            ev3 = 0.5 * (p[i] * sw - 1) + 0.5 * (placed3 * ((sw - 1) / 4 + 1) - 1)
            lines.append(f"     each-way at Sportsbet's ${sw:g}, 1/4 odds: {ev3:+.0%} per $ with 3 places, {ev:+.0%} if Sportsbet pays 4 places "
                         f"(places in first 4: {top4:.0%})")
    f4 = set(top[:4].tolist())
    tri = np.mean([set(o[:3]) <= f4 for o in order.tolist()])
    q3 = set(top[:3].tolist())
    quin = np.mean([set(o[:2]) <= q3 for o in order.tolist()])
    ff = np.mean([set(o[:4]) == f4 for o in order.tolist()]) if len(rs) >= 4 else 0.0
    nums = ",".join(str(rs[i]["no"]) for i in top[:4])
    if tri >= EXOTIC_BAR or four_place:
        lines.append(f"  Exotic try: trifecta box {nums} (24 combos) comes in {tri:.0%}; quinella box {','.join(str(rs[i]['no']) for i in top[:3])} "
                     f"(3 combos) {quin:.0%}; first-four box {nums} (24 combos) {ff:.1%}. Exotics average about -20%: a small fun bet only.")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("meet")
    ap.add_argument("--race", type=int)
    ap.add_argument("--four-place-race", type=int, default=None, help="race where a 4-place each-way promotion is assumed (the Cup)")
    ap.add_argument("--sims", type=int, default=40000)
    a = ap.parse_args()
    rng = np.random.default_rng(20261103)
    q = "query($m:ID!){getNoCacheRacesForMeet(meetCode:$m){raceNumber officialTime time}}"
    races = sorted(gql(q, {"m": a.meet})["getNoCacheRacesForMeet"], key=lambda r: r.get("officialTime") or r["time"])
    for r in races:
        if a.race and r["raceNumber"] != a.race:
            continue
        print(sheet(a.meet, r["raceNumber"], a.sims, a.four_place_race == r["raceNumber"], rng))
        print()


if __name__ == "__main__":
    main()
