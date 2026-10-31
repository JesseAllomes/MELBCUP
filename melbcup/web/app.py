"""Phone-first web server (Render). Password-protected; pages refresh in place every minute.

Rendering and actions live in views.py, shared with the browser build.
"""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from melbcup.archive import Archive
from melbcup.config import Settings, load_settings
from melbcup.live import LiveBoard
from melbcup.sources.racingcom import RacingComClient
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

    @app.get("/{path:path}", response_class=HTMLResponse, dependencies=[Depends(require_login)])
    def page(request: Request, path: str):
        try:
            html = views.page("/" + path, request.query_params, request.cookies)
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        response = HTMLResponse(html)
        if "budget" in request.query_params:  # the budget form was submitted: remember it
            chosen = parse_budget(request.query_params["budget"])
            if chosen:
                response.set_cookie(
                    BUDGET_COOKIE, f"{chosen:g}", max_age=365 * 86400, samesite="lax", httponly=True
                )
            else:
                response.delete_cookie(BUDGET_COOKIE)
        return response

    return app
