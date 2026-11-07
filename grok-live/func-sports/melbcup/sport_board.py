"""Best-chance multis for each sport, from bands already measured.

Football v1 grouped a match by its average closing price and settled the best
price. The price on a ticket is that settled best price (the worse half), not
the middle of the average-price bucket. A settled price in the top 30% of the
bucket is the long tail: the bucket hit rate does not belong to it.

A ticket is then the fewest of those prices that multiply to at least $2, and
the board keeps the stack with the highest chance every leg wins. Football
figures are football_scan_v1 (286 league-seasons). Other sports stay empty
until their scan has been run. No fixture is invented.
"""

from __future__ import annotations

import importlib.util
from functools import cache
from pathlib import Path

SPORTS = (
    ("football", "Football"),
    ("afl", "AFL"),
    ("nrl", "NRL"),
    ("nhl", "NHL"),
    ("nfl", "NFL"),
    ("tennis", "Tennis"),
)
LABEL = {
    "1X2 H": "Home win",
    "1X2 A": "Away win",
    "1X2 D": "Draw",
    "Over 2.5": "Over 2.5 goals",
    "Under 2.5": "Under 2.5 goals",
}
# Best-price return, early then late, for bands that paid in both halves
# (football_scan_v1). The settled price is (1 + worse half) / hit.
# A band whose prices above that floor span less than 3c is dropped.
_ROI = {
    ("1X2 H", "1.01-1.20"): (0.018, 0.012),
    ("1X2 H", "1.20-1.35"): (0.059, 0.018),
    ("1X2 H", "1.35-1.50"): (0.019, 0.034),
    ("1X2 H", "4.00-6.00"): (0.073, 0.019),
    ("1X2 A", "1.20-1.35"): (0.028, 0.043),
    ("1X2 A", "2.00-2.50"): (0.019, 0.018),
    ("1X2 D", "2.50-3.00"): (0.073, 0.041),
    ("Under 2.5", "1.35-1.50"): (0.017, 0.004),
}
_MIN_WINDOW = 0.03
# Top 30% of an average-price bucket. The bucket hit rate was measured on the
# whole bucket, so a settled price up in this tail cannot wear it.
_TAIL = 0.30

# market, band, hit rate, bets. Open-ended bands (10+) have no finite top.
_FOOTBALL = (
    ("1X2 A", "1.20-1.35", 0.783, 1098),
    ("1X2 A", "1.35-1.50", 0.685, 1556),
    ("1X2 A", "1.50-1.70", 0.609, 2598),
    ("1X2 A", "1.70-2.00", 0.524, 5267),
    ("1X2 A", "2.00-2.50", 0.430, 13600),
    ("1X2 A", "2.50-3.00", 0.342, 17049),
    ("1X2 A", "3.00-4.00", 0.261, 27429),
    ("1X2 A", "4.00-6.00", 0.186, 19497),
    ("1X2 A", "6.00-10.00", 0.116, 7881),
    ("1X2 D", "2.50-3.00", 0.343, 5526),
    ("1X2 D", "3.00-4.00", 0.278, 77060),
    ("1X2 D", "4.00-6.00", 0.187, 13907),
    ("1X2 D", "6.00-10.00", 0.114, 3230),
    ("1X2 H", "1.01-1.20", 0.867, 1990),
    ("1X2 H", "1.20-1.35", 0.787, 3416),
    ("1X2 H", "1.35-1.50", 0.696, 4734),
    ("1X2 H", "1.50-1.70", 0.601, 8892),
    ("1X2 H", "1.70-2.00", 0.517, 17023),
    ("1X2 H", "2.00-2.50", 0.424, 28806),
    ("1X2 H", "2.50-3.00", 0.341, 15196),
    ("1X2 H", "3.00-4.00", 0.270, 11423),
    ("1X2 H", "4.00-6.00", 0.200, 5401),
    ("1X2 H", "6.00-10.00", 0.116, 2430),
    ("Over 2.5", "1.20-1.35", 0.746, 1416),
    ("Over 2.5", "1.35-1.50", 0.675, 4565),
    ("Over 2.5", "1.50-1.70", 0.592, 15622),
    ("Over 2.5", "1.70-2.00", 0.516, 36163),
    ("Over 2.5", "2.00-2.50", 0.427, 37210),
    ("Over 2.5", "2.50-3.00", 0.339, 4628),
    ("Over 2.5", "3.00-4.00", 0.311, 354),
    ("Under 2.5", "1.35-1.50", 0.672, 4053),
    ("Under 2.5", "1.50-1.70", 0.592, 23374),
    ("Under 2.5", "1.70-2.00", 0.514, 40265),
    ("Under 2.5", "2.00-2.50", 0.427, 25331),
    ("Under 2.5", "2.50-3.00", 0.339, 4800),
    ("Under 2.5", "3.00-4.00", 0.271, 1814),
    ("Under 2.5", "4.00-6.00", 0.179, 313),
)
HUB_TABS = (("top", "Top 5"), ("ladder", "Ladder"), ("build", "Build"), ("challenge", "Challenge"))
SPORT_TABS = (
    ("multis", "Multis"),
    ("singles", "Singles"),
    ("games", "Games"),
    ("build", "Build"),
    ("challenge", "Challenge"),
)


@cache
def _legs_for():
    path = Path(__file__).resolve().parents[1] / "tools" / "markets" / "scan_multis.py"
    spec = importlib.util.spec_from_file_location("melbcup_scan_multis", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.legs_for


def _slug(sport: str, market: str, band: str) -> str:
    raw = f"{sport}-{market}-{band}".lower()
    return "".join(ch if ch.isalnum() else "-" for ch in raw)


def _middle(band: str) -> float:
    lo, hi = (float(part) for part in band.split("-"))
    return (lo + hi) / 2


def _tone(chance: float) -> str:
    pct = round(100 * chance)
    return "good" if pct >= 60 else "mid" if pct >= 30 else "low"


def quotes() -> list[dict]:
    """Measured bands. Only football has been scanned."""
    names = dict(SPORTS)
    rows = []
    for market, band, hit, bets in _FOOTBALL:
        rows.append(
            {
                "id": _slug("football", market, band),
                "sport": "football",
                "sport_name": names["football"],
                "market": market,
                "band": band,
                "hit": hit,
                "bets": bets,
                "price": _middle(band),
                "label": LABEL[market],
            }
        )
    return rows


def _ends(band: str) -> tuple[float, float] | None:
    if "-" not in band:
        return None
    lo, hi = (float(part) for part in band.split("-"))
    return lo, hi


def _wilson(hit: float, bets: int, z: float = 1.96) -> float:
    """Lower 95% bound on a hit rate. Small samples stop outranking big ones."""
    if bets <= 0:
        return 0.0
    denom = 1 + z * z / bets
    centre = hit + z * z / (2 * bets)
    margin = z * ((hit * (1 - hit) + z * z / (4 * bets)) / bets) ** 0.5
    return max(0.0, (centre - margin) / denom)


def _settled(quote: dict) -> float | None:
    """Worse-half average best price. None unless both halves paid."""
    rois = _ROI.get((quote["market"], quote["band"]))
    hit = float(quote["hit"])
    if not rois or not 0 < hit < 1:
        return None
    worse = min(rois)
    if worse <= 0:
        return None
    return (1 + worse) / hit


def _in_body(price: float, lo: float, hi: float) -> bool:
    """True when `price` is below the top 30% of the bucket."""
    return price <= lo + (1 - _TAIL) * (hi - lo)


def offer(quote: dict, minimum: float = 2.0) -> tuple[int, float, float] | None:
    """Fewest legs at the settled best price that still reach `minimum`.

    The scan's profit was the best price, not the average. A price below 1/hit
    loses at this bucket's hit rate. The settled price has to sit in the body
    of the bucket, and the prices above it have to span at least 3c.
    """
    ends = _ends(quote["band"])
    hit = float(quote["hit"])
    settled = _settled(quote)
    if ends is None or not 0 < hit < 1 or settled is None:
        return None
    lo, hi = ends
    if not _in_body(settled, lo, hi):
        return None
    for count in range(1, 13):
        floor = max(lo, 1 / hit, settled, minimum ** (1 / count))
        if floor < hi and hi - floor >= _MIN_WINDOW and _in_body(floor, lo, hi):
            return count, floor, hi
    return None


def ticket(quote: dict, minimum: float = 2.0) -> dict | None:
    """The shortest +EV stack of this band that still reaches `minimum`."""
    found = offer(quote, minimum)
    if found is None:
        return None
    count, floor, hi = found
    hit = float(quote["hit"])
    chance = hit ** count
    low = _wilson(hit, int(quote["bets"])) ** count
    early, late = _ROI[(quote["market"], quote["band"])]
    edge = (
        f"Take the best price, and only at ${floor:.2f}–${hi:.2f}. "
        f"Matches were grouped by the average price. The worse half settled "
        f"the best price at ${floor:.2f}. Under ${1 / hit:.2f} this hit rate "
        f"is a losing price. Best price returned {early:+.1%} early and "
        f"{late:+.1%} late. The chance is the whole bucket, not a separate "
        f"count of this slice."
    )
    return {
        "id": quote["id"],
        "sport": quote["sport"],
        "sport_name": quote["sport_name"],
        "label": quote["label"],
        "band": quote["band"],
        "legs": count,
        "price": floor,
        "ceiling": hi,
        "multi": floor ** count,
        "chance": chance,
        "low": low,
        "hit": hit,
        "bets": quote["bets"],
        "line": f"{count} × {quote['label']} ${floor:.2f}–${hi:.2f}",
        "edge": edge,
        "href": f"/sports/{quote['sport']}?tab=multis",
        "pct": round(100 * chance),
        "tone": _tone(chance),
    }


def ranked(sport: str | None = None, minimum: float = 2.0) -> list[dict]:
    """Tickets at or above `minimum`, highest chance first."""
    rows = []
    for quote in quotes():
        if sport and quote["sport"] != sport:
            continue
        row = ticket(quote, minimum)
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda row: (-row["chance"], row["legs"], row["sport"]))
    return rows


def _money(text: str | None, default: float) -> float:
    try:
        value = float(str(text).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return default
    return value if 0 < value < 1_000_000 else default


def _count(query, quote_id: str) -> int:
    raw = query.get(f"n_{quote_id}")
    try:
        count = int(raw) if raw else 0
    except (TypeError, ValueError):
        return 0
    return max(0, min(count, 12))


def built(query, sport: str | None = None) -> dict | None:
    """The legs the owner typed. None when every count is still zero."""
    lines = []
    price = 1.0
    chance = 1.0
    legs = 0
    for quote in quotes():
        if sport and quote["sport"] != sport:
            continue
        count = _count(query, quote["id"])
        if not count:
            continue
        price *= quote["price"] ** count
        chance *= quote["hit"] ** count
        legs += count
        lines.append(f"{count} × {quote['label']} {quote['band']}")
    if not lines:
        return None
    return {
        "lines": lines,
        "legs": legs,
        "multi": price,
        "chance": chance,
        "pct": round(100 * chance),
        "tone": _tone(chance),
        "ready": price >= 2,
    }


def challenge(query, sport: str | None = None) -> dict:
    """One stage of the shared roll-up: the likeliest ticket at that stage's price."""
    from melbcup.nba_challenge import DEFAULT_STAGES, STAGES, stage_x

    try:
        stages = int(query.get("chn") or DEFAULT_STAGES)
    except (TypeError, ValueError):
        stages = DEFAULT_STAGES
    if stages not in STAGES:
        stages = DEFAULT_STAGES
    start = _money(query.get("chstart"), 10.0)
    goal = _money(query.get("chgoal"), 1000.0)
    if goal < start * 2:
        goal = start * 2
    multiple = stage_x(start, goal, stages, True)
    found = ranked(sport, multiple)
    plain = ranked(sport, 2.0)
    return {
        "stages": stages,
        "stage_choices": STAGES,
        "start": start,
        "goal": goal,
        "x": multiple,
        "ticket": found[0] if found else None,
        "plain": plain[0] if plain else None,
    }


def _sport(path: str) -> str | None | bool:
    """Sport code, None for the hub, False when the path is not this board."""
    parts = [part for part in path.split("/") if part]
    if not parts or parts[0] != "sports" or len(parts) > 2:
        return False
    if len(parts) == 1:
        return None
    code = parts[1]
    return code if code in dict(SPORTS) else False


def page(path: str, query) -> dict | None:
    """Template context for /sports and /sports/<code>. None when the path is unknown."""
    sport = _sport(path)
    if sport is False:
        return None
    hub = sport is None
    allowed = dict(HUB_TABS if hub else SPORT_TABS)
    tab = query.get("tab") or ("top" if hub else "multis")
    if tab not in allowed:
        tab = "top" if hub else "multis"
    best = ranked(sport)[:5]
    singles = [quote for quote in quotes() if hub or quote["sport"] == sport]
    singles.sort(key=lambda quote: -quote["hit"])
    for quote in singles:
        quote["count"] = _count(query, quote["id"])
        quote["pct"] = round(100 * quote["hit"])
        quote["tone"] = _tone(quote["hit"])
        found = offer(quote)
        if found:
            quote["floor"], quote["ceiling"] = found[1], found[2]
    names = dict(SPORTS)
    best_by = {}
    for row in ranked(None):
        best_by.setdefault(row["sport"], row)
    return {
        "title": "All sports" if hub else names[sport],
        "kicker": "Best chance at $2 or more",
        "heading": "All sports" if hub else names[sport],
        "sport": sport,
        "hub": hub,
        "tab": tab,
        "tabs": HUB_TABS if hub else SPORT_TABS,
        "here": "/sports" if hub else f"/sports/{sport}",
        "hero": best[0] if best else None,
        "rest": best[1:],
        "ladder": [
            {"code": code, "name": name, "best": best_by.get(code)} for code, name in SPORTS
        ],
        "singles": singles,
        "singles_main": [quote for quote in singles if quote["hit"] >= 0.6],
        "singles_rest": [quote for quote in singles if quote["hit"] < 0.6],
        "built": built(query, sport),
        "challenge": challenge(query, sport),
        "sports": [{"code": code, "name": name} for code, name in SPORTS],
        "empty": (
            "Nothing measured reaches $2 yet."
            if hub
            else f"{names[sport]} has no measured hit rate yet, so this page shows no percent."
        ),
        "games_note": (
            "No fixture list is loaded. Singles are the prices that won most often, "
            "not tonight's matches."
            if best
            else f"{names.get(sport, 'This sport')} has no scan yet, so there is no game list."
        ),
    }
