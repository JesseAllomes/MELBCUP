"""Phone-first web server (Render). Password-protected; pages refresh in place every minute.

Rendering and actions live in views.py, shared with the browser build.
"""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from melbcup.archive import Archive
from melbcup.config import Settings, load_settings
from melbcup.live import LiveBoard
from melbcup.web.views import HERE, NotFound, Views

BASIC_AUTH = HTTPBasic(auto_error=False)


def create_app(
    settings: Settings | None = None,
    board: LiveBoard | None = None,
    *,
    start_background: bool = True,
) -> FastAPI:
    settings = settings or load_settings()
    if board is None:
        saved = HERE.parent.parent / "docs" / "data"

        def read(path: str) -> str | None:
            f = saved / path
            return f.read_text() if f.is_file() else None

        key = settings.puntersedge_api_key
        board = LiveBoard(settings, archive=Archive(read, key) if key else None)
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
            return views.page("/" + path, request.query_params)
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from exc

    return app
