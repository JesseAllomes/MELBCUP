"""Share the owner's day budget over every pick of the day (owner, 2026-11-01).

Each race has three horse picks, whether or not the price is good:
- Win: the win line paying closest to fair, among runners with at least a 4% chance (ties go to
  the likelier runner).
- Place: the runner most likely to place.
- Each way: the each-way line paying closest to fair, at a win price of $5 or more.

Money goes out in this order, and the day never goes over the budget:
1. Good-price lines (the model's value BETs) keep the model's own stake.
2. Recommended exotics keep their outlay (the quaddie counts in its first race).
3. What is left is shared over the remaining picks in proportion to the chance each pays
   (win: wins; place and each way: places), with no race taking more than RACE_CAP of the
   budget. Each way is rounded to an even number of dollars so it splits evenly.

Multis (owner, 2026-11-01): the five likeliest cross-race Sportsbet win multis of the races still
to run are picks of kind "multi", filed under their first leg's race and keyed by their legs.
They share the money by chance like the rest (never as a value BET) and always go to Sportsbet.

With two accounts (allocate_accounts), bets the owner ticked as placed keep their stake and
account, and only the money left in each account is shared over the unplaced picks in the races
still to run.

PointsBet (POINTSBET=1) is a third account: ``pointsbet_budget`` given to allocate_accounts turns
it on. A single goes to whichever account pays most (PointsBet at its fixed odds, no commission and
no minimum stake), within that account's money left; exotics and multis stay with Sportsbet.
"""

from __future__ import annotations

from dataclasses import dataclass

from melbcup.bets.multis import Multi, build_multi, day_multis
from melbcup.bets.singles import MIN_WIN_PROB, Single
from melbcup.domain import betfair_net

RACE_CAP = 0.20
EW_MIN_WIN_PRICE = 5.0
KINDS = ("win", "place", "each_way")


@dataclass
class Pick:
    race: int
    kind: str  # "win" | "place" | "each_way" | "quinella" | "trifecta"
    single: Single | None
    good_price: bool  # the model's value rule says BET at this price
    stake: int = 0
    exotic: object | None = None  # the Exotic for a quinella or trifecta pick
    multi: Multi | None = None  # the Multi for a "multi" pick

    @property
    def chance(self) -> float:
        """The chance this bet pays something: wins for a win bet, places for place and each
        way, lands for a quinella or trifecta."""
        if self.multi is not None:
            return self.multi.prob
        return self.exotic.prob if self.exotic is not None else self.single.prob

    @property
    def needs_dividend(self) -> float | None:
        """Quinella and trifecta: the average dividend (per $1 unit) that makes the bet pay
        its way. Worth a try only if the tote's estimate is above it."""
        return self.exotic.fair_dividend if self.exotic is not None else None


def _closest_to_fair(lines: list[Single]) -> Single | None:
    priced = [s for s in lines if s.ev is not None]
    return max(priced, key=lambda s: (round(s.ev, 2), s.prob), default=None)


def race_picks(rp) -> dict[str, Single | None]:
    """The race's win, place and each-way picks, good price or not."""
    win_p = {a.number: a.win for a in rp.model.ranked()}
    wins = [s for s in rp.singles if s.kind == "win" and win_p.get(s.number, 0) >= MIN_WIN_PROB]
    places = [s for s in rp.singles if s.kind == "place" and s.price is not None]
    ews = [
        s for s in rp.singles
        if s.kind == "each_way" and (s.price or 0) >= EW_MIN_WIN_PRICE
        and win_p.get(s.number, 0) >= MIN_WIN_PROB
    ]
    return {
        "win": _closest_to_fair(wins),
        "place": max(places, key=lambda s: s.prob, default=None),
        "each_way": _closest_to_fair(ews),
    }


FIXED_EXOTICS = ("first_four", "early_quaddie", "quaddie")  # keep their recommended outlay
# Tote bets and multis: the owner places these with Sportsbet only (there is no tote on
# Betfair, and a multi must sit with one bookie).
SPORTSBET_ONLY = ("quinella", "trifecta", "multi") + FIXED_EXOTICS


@dataclass(frozen=True)
class Placed:
    """A bet the owner ticked as placed: it keeps this stake and account whatever the picks do
    afterwards. ``key`` is the runner number for a horse pick, 0 for an exotic and the legs'
    ``multi_key`` for a multi; a quaddie is filed under its first race, a multi under its first
    leg's."""

    race: int
    kind: str
    key: int
    account: str  # "sportsbet" | "betfair" | "pointsbet"
    stake: int
    price: float | None = None  # the price the owner took, when they gave it
    place_price: float | None = None  # each way: the place price taken, when given

    # Several records can share a race and kind (different runners, or the same runner with two
    # bookmakers); a multi's slot is its legs.


def _even(kind: str, dollars: float) -> int:
    return int(dollars // 2 * 2) if kind == "each_way" else int(dollars)


def _open(day, races: set[int] | None) -> set[int]:
    if races is not None:
        return set(races)
    return {rp.model.race.number for rp in day.races if rp.model.race.result is None}


def day_multi_list(day, races: set[int]) -> list[Multi]:
    """The day's multis over the races still to run."""
    return day_multis([rp.model for rp in day.races if rp.model.race.number in races])


def _exotic_fixed(day, races: set[int], skip: set) -> list[Pick]:
    """Recommended First Fours and quaddies at their outlay (a quaddie counts in its first
    race), in the races still to run and not already placed."""
    out: list[Pick] = []
    for rp in day.races:
        n = rp.model.race.number
        if n not in races or (n, "first_four") in skip:
            continue
        if e := next((e for e in rp.first_fours if e.recommended and e.outlay), None):
            out.append(Pick(n, "first_four", None, False, int(e.outlay), e))
    for q in day.quaddies:
        first = q.races[0] if q.races else None
        if q.recommended and q.outlay and first in races and (first, q.kind) not in skip:
            out.append(Pick(first, q.kind, None, False, int(q.outlay), q))
    return out


def allocate(
    day,
    budget: float,
    *,
    placed: list[Placed] | tuple = (),
    races: set[int] | None = None,
    cap_base: float | None = None,
) -> list[Pick]:
    """Every race's win, place and each-way pick, and its likeliest quinella and trifecta, with
    a whole-dollar stake from ``budget``.

    ``races`` are the races still to share in (default: those without a result). ``placed``
    picks are done: their slots get nothing more, and their dollars count toward their race's
    cap (but not against ``budget``, which is the money left). ``cap_base`` is the day amount
    the race cap is a share of (default ``budget``)."""
    return _plan(day, budget, placed, races, cap_base)[0]


def _plan(
    day, budget, placed, races, cap_base, multis: list[Multi] | None = None,
    room: dict[str, float] | None = None,
) -> tuple[list[Pick], list[Pick]]:
    """(horse, quinella, trifecta and multi picks with a stake; fixed First Fours and quaddies).
    ``multis`` are the day's multis if already worked out. ``room`` (PROMOS=1) is the money left in
    each account: a race's promo Win bet takes its stake from it, capped, else it is not used."""
    races = _open(day, races)
    skip = {(p.race, p.kind) for p in placed if p.kind != "multi"}
    placed_multis = {p.key for p in placed if p.kind == "multi"}
    cap = RACE_CAP * (budget if cap_base is None else cap_base)
    picks: list[Pick] = []
    for rp in day.races:
        n = rp.model.race.number
        if n not in races:
            continue
        chosen = race_picks(rp)
        promo_stake = 0
        if room is not None and (promo := getattr(rp, "promo", None)) is not None:
            acct = promo.promo.account  # promo is a Single; its PromoBet is ``.promo``
            promo_stake = min(int(promo.stake or 0), int(room.get(acct, 0)))
            if acct == "betfair":  # raised to Betfair's minimum while its money lasts
                promo_stake = int(BETFAIR_MIN) if room.get(acct, 0) >= BETFAIR_MIN else 0
                promo_stake = max(promo_stake, min(int(promo.stake or 0), int(room[acct])))
            if promo_stake > 0 and (n, "win") not in skip:
                room[acct] -= promo_stake
                chosen["win"] = promo
            else:
                promo_stake = 0
        for kind, s in chosen.items():
            if s is None or (n, kind) in skip:
                continue
            if promo_stake and kind == "win":  # the promo bet: a value bet at its own stake
                picks.append(Pick(n, kind, s, True, promo_stake))
                continue
            value = rp.best.get(kind)
            good = value is not None and value is s and bool(s.stake)
            picks.append(Pick(n, kind, s, good, int(s.stake) if good else 0))
        # Quinella and trifecta (owner, 2026-11-01): never a value BET, but each gets a share of
        # the day by its chance, as its likeliest structure, with the dividend it needs.
        for kind, group in (("quinella", rp.quinellas), ("trifecta", rp.trifectas)):
            if (n, kind) in skip:
                continue
            if likeliest := max(group, key=lambda e: e.prob, default=None):
                picks.append(Pick(n, likeliest.kind, None, False, 0, likeliest))

    for m in day_multi_list(day, races) if multis is None else multis:
        if m.key not in placed_multis:
            picks.append(Pick(m.race, "multi", None, False, 0, None, m))

    exotics = _exotic_fixed(day, races, skip)
    fixed_items = [p for p in picks if p.good_price] + exotics
    asked = sum(p.stake for p in fixed_items)
    if asked > budget:  # the money left cannot cover them: scale them down to fit
        for p in fixed_items:
            p.stake = _even(p.kind, p.stake * budget / asked)
    used = {n: 0.0 for n in races}  # per race: fixed stakes plus placed bets, for the cap
    for p in fixed_items:
        used[p.race] = used.get(p.race, 0.0) + p.stake
    committed = sum(p.stake for p in fixed_items)
    for p in placed:
        if p.race in used:
            used[p.race] += p.stake

    left = budget - committed
    shared = [p for p in picks if not p.good_price]
    room = {n: max(0.0, cap - u) for n, u in used.items()}
    want = {id(p): 0.0 for p in shared}
    # Water-fill: share by chance, clamp races at their cap, share the rest again.
    open_ = list(shared)
    while left > 0.5 and open_:
        weight = sum(p.chance for p in open_)
        if weight <= 0:
            break
        spill = 0.0
        by_race: dict[int, list[Pick]] = {}
        for p in open_:
            by_race.setdefault(p.race, []).append(p)
        next_open: list[Pick] = []
        for race, group in by_race.items():
            ask = sum(left * p.chance / weight for p in group)
            give = min(ask, room.get(race, cap))
            for p in group:
                want[id(p)] += give * p.chance / sum(q.chance for q in group)
            room[race] = room.get(race, cap) - give
            spill += ask - give
            if room[race] > 0.5:
                next_open.extend(group)
        left = spill
        open_ = next_open
    for p in shared:
        p.stake = _even(p.kind, want[id(p)])
    _spend_rounding(shared, want, budget - committed, used, cap)
    return [p for p in picks if p.stake > 0], [p for p in exotics if p.stake > 0]


def _spend_rounding(shared: list[Pick], want: dict, pot: float, used: dict, cap: float) -> None:
    """Rounding down leaves whole dollars unspent: give them back one at a time, first to any
    pick still at $0, then by the largest shortfall, never past a race's cap or the budget.
    ``used`` holds each race's dollars outside ``shared`` (fixed stakes and placed bets)."""
    spare = int(pot - sum(p.stake for p in shared))
    in_race = {}
    for p in shared:
        in_race[p.race] = in_race.get(p.race, 0) + p.stake
    while spare > 0:
        fits = [
            p for p in shared
            if (step := 2 if p.kind == "each_way" else 1) <= spare
            and used.get(p.race, 0) + in_race[p.race] + step <= cap
        ]
        if not fits:
            return
        p = max(fits, key=lambda p: (p.stake == 0, want[id(p)] - p.stake))
        step = 2 if p.kind == "each_way" else 1
        p.stake += step
        in_race[p.race] += step
        spare -= step


BETFAIR_MIN = 5.0  # Betfair Australia's smallest back bet


@dataclass
class Routed:
    """A pick with its stake and the account to place it with."""

    pick: Pick
    account: str  # "sportsbet" | "betfair" | "pointsbet"
    price: float | None  # as that account shows it (Betfair before commission)
    placed: bool = False  # the owner ticked it as placed: stake and account are theirs
    record: Placed | None = None  # the placed record this line stands for (placed lines only)


def _promo_first(gain):
    """Routing order: promo bets first, nearest race first (their stakes were reserved in race
    order, so a later race's bigger price gain must not spend them), then the rest by gain."""

    def key(p):
        if getattr(p.single, "promo", None) is not None:
            return (0, p.race, 0.0)
        return (1, 0, -gain(p))

    return key


def route(picks: list[Pick], betfair_budget: float) -> list[Routed]:
    """Send each pick to the account that pays more, within Betfair's money and minimum.

    A pick goes to Betfair only when Betfair's price (after commission) is the better one and
    the Betfair money is not used up; a stake under Betfair's $5 minimum (each way: $5 a half)
    is raised to it. The biggest price gains get the Betfair money first. Everything else goes
    to Sportsbet at Sportsbet's price."""
    def gain(p: Pick) -> float:
        s = p.single
        if s is None:
            return 0.0
        return (s.price or 0) / s.sportsbet if s.sportsbet else float("inf")

    left = betfair_budget
    out: dict[int, Routed] = {}
    better_on_betfair = sorted(
        (p for p in picks if p.single is not None and p.single.bookmaker == "betfair"),
        key=_promo_first(gain),
    )
    for p in better_on_betfair:
        minimum = 2 * BETFAIR_MIN if p.kind == "each_way" else BETFAIR_MIN
        # A smaller stake is raised to Betfair's minimum while Betfair money lasts (owner,
        # 2026-11-01): the better price is worth more than leaving that money unused.
        need = max(p.stake, minimum)
        if p.stake > 0 and need <= left:
            p.stake = int(need)
            out[id(p)] = Routed(p, "betfair", p.single.shown)
            left -= need
    return [
        out.get(id(p)) or Routed(p, "sportsbet", _sportsbet_price(p))
        for p in picks
    ]


POINTSBET_JUDGED = "pointsbetau"  # Single.bookmaker when PointsBet pays most
ACCOUNT_ORDER = {"sportsbet": 0, "pointsbet": 1, "betfair": 2}  # who keeps a tie on price


def route_three(
    day, picks: list[Pick], betfair_budget: float, pointsbet_budget: float
) -> list[Routed]:
    """``route`` with PointsBet as a third account (POINTSBET=1).

    A single goes to the account that pays most: Sportsbet, PointsBet (fixed odds, no minimum)
    or Betfair (after commission, $5 minimum as in ``route``), within the money that account has
    left; when the best account's money is used up it takes the next best. A tie stays with
    Sportsbet, then PointsBet. The biggest price gains get the Betfair and PointsBet money first.
    Only a single judged at Betfair or PointsBet is moved off Sportsbet. Exotics and multis go to
    Sportsbet."""
    left = {"betfair": betfair_budget, "pointsbet": pointsbet_budget}

    def offers(p: Pick) -> list[tuple[str, float]]:
        out = []
        for acct in ACCOUNT_ORDER:
            price = account_price(day, p, acct)
            if acct == "betfair":
                price = betfair_net(price)
            if price:
                out.append((acct, price))
        return sorted(out, key=lambda o: (-o[1], ACCOUNT_ORDER[o[0]]))

    def gain(p: Pick) -> float:
        s = p.single
        return (s.price or 0) / s.sportsbet if s.sportsbet else float("inf")

    moved = sorted(
        (
            p for p in picks
            if p.single is not None and p.single.bookmaker in ("betfair", POINTSBET_JUDGED)
        ),
        key=_promo_first(gain),
    )
    out: dict[int, Routed] = {}
    for p in moved:
        if p.stake <= 0:
            continue
        if getattr(p.single, "promo", None) is not None:  # a promo bet stays at its bookmaker
            acct = p.single.promo.account
            p.stake = int(min(p.stake, left.get(acct, 0)))
            out[id(p)] = Routed(p, acct, account_price(day, p, acct))
            left[acct] = left.get(acct, 0) - p.stake
            continue
        for acct, _ in offers(p):
            if acct == "sportsbet":
                break
            if acct == "betfair":
                minimum = 2 * BETFAIR_MIN if p.kind == "each_way" else BETFAIR_MIN
                need = max(p.stake, minimum)  # raised to Betfair's minimum while money lasts
            else:
                need = p.stake  # PointsBet has no minimum
            if need <= left[acct]:
                p.stake = int(need)
                out[id(p)] = Routed(p, acct, account_price(day, p, acct))
                left[acct] -= need
                break
    return [
        out.get(id(p)) or Routed(p, "sportsbet", _sportsbet_price(p))
        for p in picks
    ]


def _sportsbet_price(pick: Pick) -> float | None:
    if pick.multi is not None:
        return pick.multi.price
    return pick.single.sportsbet if pick.single else None


def account_price(day, pick: Pick, account: str) -> float | None:
    """The pick's price at ``account`` as the owner sees it there (Betfair before commission):
    the win price for win and each way, the place price for place; None for exotics."""
    if pick.multi is not None:
        return pick.multi.price if account == "sportsbet" else None
    s = pick.single
    if s is None:
        return None
    if account == "sportsbet":
        return s.sportsbet
    rp = next((r for r in day.races if r.model.race.number == pick.race), None)
    prices = rp.model.race.prices.get(s.number) if rp else None
    if prices is None:
        return None
    if account == "pointsbet":
        return prices.pointsbet_place if s.kind == "place" else prices.pointsbet_win
    return prices.betfair_place if s.kind == "place" else prices.betfair_win


def placed_pick(day, p: Placed) -> Pick:
    """The pick a placed record stands for, at the placed stake."""
    rp = next((r for r in day.races if r.model.race.number == p.race), None)
    single = exotic = multi = None
    if p.kind == "multi":
        multi = build_multi([r.model for r in day.races], p.key)
    if rp is not None:
        if p.kind in KINDS:
            single = next(
                (s for s in rp.singles if s.kind == p.kind and s.number == p.key), None
            )
        elif p.kind in ("quinella", "trifecta"):
            group = rp.quinellas if p.kind == "quinella" else rp.trifectas
            exotic = max(group, key=lambda e: e.prob, default=None)
        elif p.kind == "first_four":
            exotic = next((e for e in rp.first_fours if e.recommended), None)
    if p.kind in ("quaddie", "early_quaddie"):
        exotic = next(
            (q for q in day.quaddies
             if q.kind == p.kind and q.recommended and q.races and q.races[0] == p.race),
            None,
        )
    promo = getattr(rp, "promo", None)
    if promo is not None and p.kind == "win" and promo.number == p.key:
        if promo.promo.account == p.account:  # placed as the promo bet, at the promo bookmaker
            single = promo
    good = (
        rp is not None and single is not None and rp.best.get(p.kind) is single
        and bool(single.stake)
    ) or (single is not None and single is promo)
    return Pick(p.race, p.kind, single, good, p.stake, exotic, multi)


def allocate_accounts(
    day,
    sportsbet_budget: float,
    betfair_budget: float,
    placed: list[Placed] | tuple = (),
    races: set[int] | None = None,
    multis: list[Multi] | None = None,
    pointsbet_budget: float | None = None,
) -> list[Routed]:
    """Share both accounts' money over the day, then route each bet to an account.

    Bets the owner has placed come first, at their own stake and account. The money left in
    the two accounts together is shared over the unplaced picks in the races still to run
    (``races``; default: those without a result), with the recommended First Four and quaddies
    at their outlay on Sportsbet. Bets that cannot go to Betfair fall back to Sportsbet; if that
    would take Sportsbet past what it has left, the day is shared again with less, so no
    account ever goes over.

    ``pointsbet_budget`` (None: off, as before) adds PointsBet as a third account with its own
    day amount: bets go to whichever of the three pays most, within that account's money left."""
    placed = list(placed)
    sb_left = max(0.0, sportsbet_budget - sum(p.stake for p in placed if p.account == "sportsbet"))
    bf_left = max(0.0, betfair_budget - sum(p.stake for p in placed if p.account == "betfair"))
    three = pointsbet_budget is not None
    pb_left = (
        max(0.0, pointsbet_budget - sum(p.stake for p in placed if p.account == "pointsbet"))
        if three
        else 0.0
    )
    held = []
    for p in placed:
        pick = placed_pick(day, p)
        price = p.price or account_price(day, pick, p.account)
        held.append(Routed(pick, p.account, price, placed=True, record=p))
    budget = sb_left + bf_left + pb_left
    cap_base = sportsbet_budget + betfair_budget + (pointsbet_budget if three else 0.0)
    routed: list[Routed] = []
    if multis is None:  # ``multis``: the day's multis, if the caller already worked them out
        multis = day_multi_list(day, _open(day, races))
    for _ in range(40):
        room = (
            {"sportsbet": sb_left, "pointsbet": pb_left, "betfair": bf_left}
            if any(getattr(rp, "promo", None) for rp in day.races)
            else None
        )
        picks, exotics = _plan(day, budget, placed, races, cap_base, multis, room)
        routed = (
            route_three(day, picks, bf_left, pb_left) if three else route(picks, bf_left)
        ) + [Routed(e, "sportsbet", None) for e in exotics]
        on_sb = sum(r.pick.stake for r in routed if r.account == "sportsbet")
        over = on_sb - sb_left
        if over <= 0 or budget <= 0:
            break
        budget = max(0.0, budget - max(over, 1))
    return held + routed
