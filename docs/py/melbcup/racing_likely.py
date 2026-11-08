"""Likeliest racing bets: top singles per race and meeting, likeliest multis per bookie."""

from __future__ import annotations

from datetime import datetime

from melbcup import discover
from melbcup.domain import betfair_net

AGENCIES = ("sportsbet", "betfair", "pointsbet")
BANDS = ((1.5, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 10.0), (10.0, 20.0))


def _price(prices, agency: str, kind: str) -> float | None:
    if prices is None:
        return None
    p = getattr(prices, f"{agency}_{kind}", None)
    if p is None or p <= 1.0:
        return None
    return betfair_net(p) if agency == "betfair" else p


def _open(model, now: datetime) -> bool:
    race = model.race
    if race.result is not None:
        return False
    return not (race.start_time is not None and race.start_time <= now)


def _bets(model, agencies) -> list[dict]:
    race, out = model.race, []
    for num, a in model.runners.items():
        r = race.runner(num)
        if r is None or r.scratched or r.emergency:
            continue
        for kind, chance in (("win", a.win), ("place", a.place)):
            if not chance or chance <= 0:
                continue
            best = None
            for ag in agencies:
                pr = _price(race.prices.get(num), ag, kind)
                if pr is not None and (best is None or pr > best[0]):
                    best = (pr, ag)
            if best is None:
                continue
            out.append(
                {
                    "race": race.number,
                    "runner": num,
                    "name": r.name,
                    "kind": kind,
                    "chance": chance,
                    "price": round(best[0], 2),
                    "agency": best[1],
                    "fair_price": round(1 / chance, 2),
                    "expected_return": chance * best[0] - 1,
                }
            )
    return out


def likeliest_singles(models, races=None, agencies_on=AGENCIES, now=None, top=3, meeting_n=5):
    """Top `top` bets by chance per open race, and the `meeting_n` likeliest across the meeting."""
    now = now or datetime.now().astimezone()
    per_race, every = {}, []
    for m in models:
        if races is not None and m.race.number not in races:
            continue
        if not _open(m, now):
            continue
        bets = sorted(_bets(m, agencies_on), key=lambda b: -b["chance"])
        per_race[m.race.number] = bets[:top]
        every += bets
    every.sort(key=lambda b: -b["chance"])
    return {"races": per_race, "meeting_top": every[:meeting_n]}


def likeliest_multis(models, races=None, agency="sportsbet", bands=BANDS, now=None):
    """Best multi per band at one bookie: one leg (win or place) per race, independent."""
    now = now or datetime.now().astimezone()
    groups = []
    for m in models:
        if races is not None and m.race.number not in races:
            continue
        if not _open(m, now):
            continue
        start = m.race.start_time.isoformat() if m.race.start_time else ""
        grp = []
        for b in _bets(m, (agency,)):
            grp.append(
                {
                    "event_id": m.race.number,
                    "price": b["price"],
                    "p": b["chance"],
                    "label": f"R{b['race']} #{b['runner']} {b['name']} {b['kind'].title()}",
                    "start": start,
                    "sport": "racing",
                    "event": f"R{b['race']}",
                    "runner": b["runner"],
                    "kind": b["kind"],
                }
            )
        if grp:
            groups.append(grp)
    return discover.best_multis(groups, bands)


def build(models, agencies_on=AGENCIES, now=None) -> dict:
    now = now or datetime.now().astimezone()
    s = likeliest_singles(models, None, agencies_on, now)
    multis = {}
    for ag in ("sportsbet", "pointsbet"):
        if ag in agencies_on:
            multis[ag] = likeliest_multis(models, None, ag, now=now)
    return {
        "singles": s["races"],
        "meeting_top": s["meeting_top"],
        "multis": multis,
        "built": now.isoformat(),
    }
