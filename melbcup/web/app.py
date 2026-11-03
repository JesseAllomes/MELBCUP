"""Phone-first web server (Render). Password-protected; pages refresh in place every minute.

Rendering and actions live in views.py, shared with the browser build.
"""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from melbcup.archive import Archive
from melbcup.autobet import BetError, Betting, PinError, start_loop
from melbcup.config import Settings, load_settings
from melbcup.live import LiveBoard
from melbcup.sources.racingcom import RacingComClient
from melbcup.web import asynym
from melbcup.web.offer_api import OfferNotFound, OfferRequestError, offer_response
from melbcup.web.racecard import BF_COOKIE, PB_COOKIE, SB_COOKIE, parse_amount, pick_amounts
from melbcup.web.views import BUDGET_COOKIE, HERE, NotFound, Views, parse_budget

BASIC_AUTH = HTTPBasic(auto_error=False)


def create_app(
    settings: Settings | None = None,
    board: LiveBoard | None = None,
    *,
    start_background: bool = True,
) -> FastAPI:
    settings = settings or load_settings()
    if board is None:
        # Next to the source tree, or under the working directory: Render installs the
        # package into site-packages but runs from the repository root.
        candidates = [HERE.parent.parent / "docs" / "data", Path.cwd() / "docs" / "data"]
        saved = next((c for c in candidates if (c / "index.json").is_file()), candidates[-1])

        def read(path: str) -> str | None:
            f = saved / path
            return f.read_text() if f.is_file() else None

        board = LiveBoard(settings, archive=Archive(read), rc=RacingComClient())
    views = Views(settings, board)
    betting = Betting(settings, board)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        stop_auto = None
        if start_background:
            board.start()
            stop_auto = start_loop(betting)
        yield
        if stop_auto is not None:
            stop_auto.set()
        board.stop()

    app = FastAPI(title="MELBCUP", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    def require_login(
        creds: Annotated[HTTPBasicCredentials | None, Depends(BASIC_AUTH)],
    ) -> None:
        if settings.public:
            return
        if not settings.app_password:
            raise HTTPException(503, "APP_PASSWORD is not set. Add it in the host's settings.")
        ok = creds is not None and secrets.compare_digest(
            creds.password.encode(), settings.app_password.encode()
        )
        if not ok:
            raise HTTPException(401, "Password required", {"WWW-Authenticate": "Basic"})

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz() -> str:
        return "ok"

    @app.post("/actions/{name}", dependencies=[Depends(require_login)])
    def action(request: Request, name: str):
        try:
            target = views.action(name, request.query_params)
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        return RedirectResponse(target, status_code=303)

    @app.get("/api/offer", dependencies=[Depends(require_login)])
    def offer(request: Request):
        """Offers check as JSON (see melbcup/bets/offers.py). Computes only; places nothing."""
        try:
            body = offer_response(
                board.snapshot(), request.query_params.multi_items(), request.cookies
            )
        except OfferNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except OfferRequestError as exc:
            raise HTTPException(400, str(exc)) from exc
        return JSONResponse(body, headers={"Cache-Control": "no-store"})

    def _betting_answer(fn):
        try:
            return JSONResponse(fn(), headers={"Cache-Control": "no-store"})
        except PinError as exc:
            raise HTTPException(403, str(exc)) from exc
        except BetError as exc:
            raise HTTPException(400, str(exc)) from exc

    async def _body(request: Request) -> dict:
        if request.headers.get("content-type", "").startswith("application/json"):
            data = await request.json()
            return data if isinstance(data, dict) else {}
        return dict(await request.form())

    def _number(data: dict, key: str, kind=float):
        raw = data.get(key)
        if raw in (None, ""):
            return None
        try:
            return kind(raw)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"{key} must be a number") from exc

    @app.get("/api/betting")
    def betting_status():
        """Auto and betting status: mode, limit, spent today, recent bets. No secrets."""
        return _betting_answer(betting.status)

    def _client(request: Request) -> str:
        """The caller's address: the last X-Forwarded-For hop (added by the ingress), else
        the socket peer."""
        forwarded = request.headers.get("x-forwarded-for", "")
        return forwarded.split(",")[-1].strip() or (request.client.host if request.client else "")

    @app.post("/api/betting/auto")
    async def betting_auto(request: Request):
        """Switch auto on for one race with that race's limit, or off. Needs the PIN."""
        data = await _body(request)
        race = _number(data, "race", int)
        if race is None:
            raise HTTPException(400, "race is required")
        on = str(data.get("on", "")).lower() in ("1", "true", "on", "yes")
        limit = _number(data, "limit")
        client = _client(request)
        return _betting_answer(
            lambda: betting.set_auto(data.get("pin"), race, on, limit, client=client)
        )

    @app.post("/api/betting/bet")
    async def betting_bet(request: Request):
        """One bet by hand on Betfair: race, runner, kind (win or place), stake. Needs the PIN."""
        data = await _body(request)
        race, runner = _number(data, "race", int), _number(data, "runner", int)
        stake = _number(data, "stake")
        if race is None or runner is None or stake is None:
            raise HTTPException(400, "race, runner and stake are required")
        kind = str(data.get("kind") or "win")
        return _betting_answer(
            lambda: _placed(
                betting.bet_by_hand(
                    data.get("pin"), race, runner, kind, stake, client=_client(request)
                )
            )
        )

    def _placed(p) -> dict:
        return {k: v for k, v in betting.status()["bets"][-1].items()} if p else {}

    @app.get("/{path:path}", response_class=HTMLResponse, dependencies=[Depends(require_login)])
    def page(request: Request, path: str):
        try:
            html = views.page("/" + path, request.query_params, request.cookies)
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        response = HTMLResponse(html)
        query = request.query_params
        keep = {"max_age": 365 * 86400, "samesite": "lax", "httponly": True}
        if "budget" in query:  # the old single budget: remembered for /api/offer too
            chosen = parse_budget(query["budget"])
            if chosen:
                response.set_cookie(BUDGET_COOKIE, f"{chosen:g}", **keep)
            else:
                response.delete_cookie(BUDGET_COOKIE)
        if "sb" in query or "bf" in query or "budget" in query:
            # The day amounts were submitted (or ?budget= alone: all on Sportsbet): remember them
            sb, bf, chosen = pick_amounts(query)
            if chosen:
                response.set_cookie(SB_COOKIE, f"{sb:g}", **keep)
                response.set_cookie(BF_COOKIE, f"{bf:g}", **keep)
            else:
                response.delete_cookie(SB_COOKIE)
                response.delete_cookie(BF_COOKIE)
        if (settings.pointsbet or settings.asynym) and "pb" in query:  # PointsBet's day amount
            pb = parse_amount(query["pb"])
            if pb is not None:
                response.set_cookie(PB_COOKIE, f"{pb:g}", **keep)
            else:
                response.delete_cookie(PB_COOKIE)
        if settings.asynym:  # ASYNYM=1: which agencies are ON, and TAB, Ladbrokes, Neds money
            for name, value in asynym.cookie_changes(query).items():
                if value is None:
                    response.delete_cookie(name)
                else:
                    response.set_cookie(name, value, **keep)
        return response

    return app
