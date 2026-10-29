"""Phone-first web app. Password-protected; pages refresh themselves in place every minute."""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from melbcup.bets.grade import grade_day
from melbcup.config import MELBOURNE, Settings, load_settings
from melbcup.live import LiveBoard

HERE = Path(__file__).parent
BOOKMAKERS = {
    "sportsbet": "Sportsbet",
    "tab": "TAB",
    "ladbrokes_au": "Ladbrokes",
    "neds": "Neds",
    "pointsbetau": "PointsBet",
    "betright": "BetRight",
    "playup": "PlayUp",
    "betr_au": "Betr",
    "unibet_au": "Unibet",
    "bet365_au": "bet365",
    "betdeluxe": "BetDeluxe",
    "betgold": "BetGold",
    "palmerbet": "Palmerbet",
    "picklebet": "Picklebet",
    "boombet": "BoomBet",
}
KIND_LABELS = {"win": "Win", "place": "Place", "each_way": "Each way"}
MAX_BUDGET = 100_000
CARNIVAL = (  # Flemington, Melbourne Cup Carnival 2026: one tap, no lookup
    ("Derby Day", date(2026, 10, 31)),
    ("Cup Day", date(2026, 11, 3)),
    ("Oaks Day", date(2026, 11, 5)),
    ("Stakes Day", date(2026, 11, 7)),
)


def melbourne_today() -> date:
    return datetime.now(MELBOURNE).date()


def _date(text: str | None) -> date | None:
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


BASIC_AUTH = HTTPBasic(auto_error=False)


def pct(p: float | None, digits: int = 0) -> str:
    return "–" if p is None else f"{100 * p:.{digits}f}%"


def money(x: float | None) -> str:
    if x is None:
        return "–"
    return f"${x:,.2f}" if x < 100 else f"${x:,.0f}"


def edge(ev: float | None) -> str:
    return "–" if ev is None else f"{100 * ev:+.0f}%"


def local_time(dt: datetime | None) -> str:
    if dt is None:
        return "–"
    return dt.astimezone(MELBOURNE).strftime("%-I:%M%p").lower()


def until(dt: datetime | None) -> str:
    if dt is None:
        return ""
    mins = int((dt - datetime.now(UTC)).total_seconds() // 60)
    if mins < -5:
        return "run"
    if mins <= 0:
        return "jumping"
    if mins < 60:
        return f"in {mins} min"
    return f"in {mins // 60} h {mins % 60:02d} min"


def book(key: str | None) -> str:
    return "–" if not key else BOOKMAKERS.get(key, key.replace("_au", "").title())


def statline(s) -> str:
    return "–" if s is None else f"{s.starts}: {s.wins}-{s.top3 - s.wins}"


def _templates() -> Jinja2Templates:
    t = Jinja2Templates(directory=HERE / "templates")
    t.env.filters.update(
        pct=pct,
        money=money,
        edge=edge,
        local_time=local_time,
        until=until,
        book=book,
        statline=statline,
    )
    t.env.globals["KIND_LABELS"] = KIND_LABELS
    return t


def _budget(request: Request) -> float | None:
    raw = request.query_params.get("budget", "").strip().lstrip("$")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if 0 < value <= MAX_BUDGET else None


def create_app(
    settings: Settings | None = None,
    board: LiveBoard | None = None,
    *,
    start_background: bool = True,
) -> FastAPI:
    settings = settings or load_settings()
    board = board or LiveBoard(settings)
    templates = _templates()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if start_background:
            board.start()
        yield
        board.stop()

    app = FastAPI(title="MELBCUP", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    def require_login(
        creds: Annotated[HTTPBasicCredentials | None, Depends(BASIC_AUTH)],
    ) -> None:
        if not settings.app_password:
            raise HTTPException(503, "APP_PASSWORD is not set. Add it in the host's settings.")
        ok = creds is not None and secrets.compare_digest(
            creds.password.encode(), settings.app_password.encode()
        )
        if not ok:
            raise HTTPException(401, "Password required", {"WWW-Authenticate": "Basic"})

    def context(request: Request) -> dict:
        snap = board.snapshot()
        budget = _budget(request)
        return {
            "settings": settings,
            "snap": snap,
            "card": snap.card,
            "budget": budget,
            "budget_q": f"?budget={budget:g}" if budget else "",
            "picks": (picks := snap.picks(budget) if snap.models else None),
            "grade": grade_day(picks)
            if picks and any(rp.model.race.result for rp in picks.races)
            else None,
            "today": melbourne_today(),
            "here": request.url.path + (f"?budget={budget:g}" if budget else ""),
            "load_cost": 2 + 3 * (len(snap.card.races) if snap.card else 10),
            "now": datetime.now(UTC),
        }

    def back(request: Request) -> RedirectResponse:
        target = request.query_params.get("next", "/")
        if not target.startswith("/") or target.startswith("//"):
            target = "/"
        return RedirectResponse(target, status_code=303)

    @app.post("/actions/prices", dependencies=[Depends(require_login)])
    def refresh_prices(request: Request):
        board.refresh_prices_now()
        return back(request)

    @app.post("/actions/results", dependencies=[Depends(require_login)])
    def results(request: Request):
        board.fetch_results_now()
        return back(request)

    @app.post("/actions/load", dependencies=[Depends(require_login)])
    def load(request: Request):
        board.load_card_now()
        return back(request)

    @app.get("/meetings", response_class=HTMLResponse, dependencies=[Depends(require_login)])
    def meetings(request: Request):
        ctx = context(request)
        pick = _date(request.query_params.get("date")) or ctx["snap"].race_date
        ctx.update(
            pick=pick,
            found=ctx["snap"].meetings.get(pick),
            carnival=CARNIVAL,
            here=f"/meetings?date={pick.isoformat()}",
        )
        return templates.TemplateResponse(request, "meetings.html", ctx)

    @app.post("/actions/find", dependencies=[Depends(require_login)])
    def find(request: Request):
        pick = _date(request.query_params.get("date"))
        if pick is not None:
            board.find_meetings(pick)
            return RedirectResponse(f"/meetings?date={pick.isoformat()}", status_code=303)
        return RedirectResponse("/meetings", status_code=303)

    @app.post("/actions/meeting", dependencies=[Depends(require_login)])
    def meeting(request: Request):
        pick = _date(request.query_params.get("date"))
        venue = request.query_params.get("venue", "")
        if pick is not None and board.set_meeting(pick, venue):
            return RedirectResponse("/", status_code=303)
        return RedirectResponse("/meetings", status_code=303)

    @app.post("/actions/auto", dependencies=[Depends(require_login)])
    def auto(request: Request):
        board.set_auto(request.query_params.get("on") == "1")
        return back(request)

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz() -> str:
        return "ok"

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_login)])
    def day(request: Request):
        ctx = context(request)
        if ctx["picks"]:
            singles = [
                s
                for rp in ctx["picks"].races
                if rp.model.race.result is None  # only races still to run
                for s in rp.best.values()
                if s and s.value
            ]
            ctx["top_value"] = sorted(singles, key=lambda s: s.ev or 0, reverse=True)[:6]
        return templates.TemplateResponse(request, "day.html", ctx)

    @app.get("/race/{number}", response_class=HTMLResponse, dependencies=[Depends(require_login)])
    def race(request: Request, number: int):
        ctx = context(request)
        rp = (
            next((r for r in ctx["picks"].races if r.model.race.number == number), None)
            if ctx["picks"]
            else None
        )
        if rp is None:
            raise HTTPException(404, f"Race {number} is not on the card yet")
        ctx["rp"] = rp
        ctx["race"] = rp.model.race
        return templates.TemplateResponse(request, "race.html", ctx)

    return app
