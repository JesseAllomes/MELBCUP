# ruff: noqa: E501
"""Phone-first web server (Render). Password-protected; pages refresh in place every minute.

Rendering and actions live in views.py, shared with the browser build.
"""

from __future__ import annotations

import hmac
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from melbcup import nba_challenge
from melbcup.archive import Archive
from melbcup.autobet import BetError, Betting, PinError, start_loop
from melbcup.config import Settings, load_settings
from melbcup.live import LiveBoard
from melbcup.sources.racingcom import RacingComClient
from melbcup.web import asynym
from melbcup.web.offer_api import OfferNotFound, OfferRequestError, offer_response
from melbcup.web.racecard import BF_COOKIE, PB_COOKIE, SB_COOKIE, parse_amount, pick_amounts
from melbcup.web.views import (
    BUDGET_COOKIE,
    HERE,
    NotFound,
    Views,
    melbourne_today,
    parse_budget,
)

BASIC_AUTH = HTTPBasic(auto_error=False)


SERVICE_WORKER = """// AsynymBet: alerts, and a saved copy of each page (owner, 2026-11-04: the app sleeps when idle,
// so a page that takes over WAIT_MS shows the phone's last copy at once and the fresh one follows).
var PAGES = "pages-v1", STATIC = "static-v1", WAIT_MS = 1500, KEEP = 40;
self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (e) { e.waitUntil(self.clients.claim()); });
function plain(u) {  // only plain views are kept; an action link (any other query key) always asks the server
  if (u.pathname.indexOf("/api/") === 0 || u.pathname.indexOf("/actions") === 0) return false;
  var ok = true;
  u.searchParams.forEach(function (v, k) { if (k !== "tab" && k !== "date") ok = false; });
  return ok;
}
function save(url, r) {
  if (!r || !r.ok || (r.headers.get("content-type") || "").indexOf("text/html") !== 0) return null;
  var copy = r.clone();
  return caches.open(PAGES).then(function (c) {
    return copy.text().then(function (t) {
      return c.put(url, new Response(t, { headers: { "content-type": "text/html; charset=utf-8", "x-saved": String(Date.now()) } }));
    }).then(function () { return c.keys(); }).then(function (ks) {
      return Promise.all(ks.slice(0, Math.max(0, ks.length - KEEP)).map(function (k) { return c.delete(k); }));
    });
  });
}
self.addEventListener("fetch", function (e) {
  var req = e.request, u = new URL(req.url);
  if (req.method !== "GET" || u.origin !== self.location.origin) return;
  if (u.pathname.indexOf("/static/") === 0 && u.search) {  // versioned (?v=): never changes
    e.respondWith(caches.open(STATIC).then(function (c) {
      return c.match(req).then(function (hit) {
        return hit || fetch(req).then(function (r) { if (r.ok) c.put(req, r.clone()); return r; });
      });
    }));
    return;
  }
  if (req.mode !== "navigate" || !plain(u)) return;
  var net = fetch(req);
  e.waitUntil(net.then(function (r) { return save(req.url, r); }).catch(function () {}));
  e.respondWith(caches.open(PAGES).then(function (c) { return c.match(req.url); }).then(function (hit) {
    if (!hit) return net;
    var wait = new Promise(function (res) { setTimeout(res, WAIT_MS, null); });
    return Promise.race([net.catch(function () { return null; }), wait]).then(function (r) {
      if (r && r.status < 500) return r;
      var at = hit.headers.get("x-saved") || "0";
      return hit.text().then(function (t) {
        return new Response(t.replace("<body", '<body data-saved="' + at + '"'), { headers: { "content-type": "text/html; charset=utf-8" } });
      });
    });
  }));
});
self.addEventListener("push", function (e) {
  var d = {};
  try { d = e.data ? e.data.json() : {}; } catch (x) { d = { body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.title || "AsynymBet", {
    body: d.body || "", tag: d.title || "asynym", renotify: true, vibrate: [200, 100, 200],
    data: { url: d.url || "/nba?tab=challenge" }
  }));
});
self.addEventListener("notificationclick", function (e) {
  e.notification.close();
  var url = (e.notification.data && e.notification.data.url) || "/nba?tab=challenge";
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (ws) {
    for (var i = 0; i < ws.length; i++) { if ("focus" in ws[i]) { ws[i].navigate(url); return ws[i].focus(); } }
    return self.clients.openWindow(url);
  }));
});
"""


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
    betting = Betting(settings, board) if settings.autobet else None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        stop_auto = None
        if start_background:
            board.start()
            stop_auto = start_loop(betting) if betting is not None else None
            if settings.asynym:  # warm the NBA page data while the first visitor waits for nothing
                threading.Thread(target=views.warm_nba, daemon=True).start()
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

    # Betfair auto-betting: off unless AUTOBET=1 (the owner does not use it, 2026-11-04). While
    # off, the loop never starts and these routes do not exist (404).
    if settings.autobet:

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
            return forwarded.split(",")[-1].strip() or (
                request.client.host if request.client else ""
            )

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
            """One bet by hand on Betfair: race, runner, kind (win or place), stake. Needs PIN."""
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

    if (
        settings.asynym
    ):  # phone alerts (owner, 2026-11-04): melbcup/push_store.py, sent by the Function
        from melbcup.push_store import PushError, PushStore

        push = PushStore()

        @app.get("/sw.js")
        def service_worker():
            """The service worker that shows a pushed alert, at the root so it covers every page."""
            return Response(
                SERVICE_WORKER,
                media_type="application/javascript",
                headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
            )

        def _push(fn):
            if not push.ready:
                raise HTTPException(503, "alerts need the Azure storage")
            try:
                return JSONResponse(fn(), headers={"Cache-Control": "no-store"})
            except PushError as exc:
                raise HTTPException(400, str(exc)) from exc

        @app.post("/api/push/subscribe", dependencies=[Depends(require_login)])
        async def push_subscribe(request: Request):
            data = await request.json()
            return _push(
                lambda: {"id": push.subscribe(data.get("subscription") or data, data.get("id"))}
            )

        @app.post("/api/push/link", dependencies=[Depends(require_login)])
        async def push_link(request: Request):
            return _push(lambda: {"id": push.link()})

        @app.post("/api/push/status", dependencies=[Depends(require_login)])
        async def push_status(request: Request):
            data = await request.json()
            return _push(lambda: push.status(data.get("id")))

        @app.post("/api/push/remind", dependencies=[Depends(require_login)])
        async def push_remind(request: Request):
            data = await request.json()
            return _push(
                lambda: {"saved": push.remind(data.get("id"), data.get("reminders") or [])}
            )

        @app.post("/api/push/test", dependencies=[Depends(require_login)])
        async def push_test(request: Request):
            data = await request.json()
            return _push(lambda: push.test(data.get("id")))

        @app.post("/api/telegram")
        async def telegram_hook(request: Request):
            """@AsynymBetBot's webhook: links a chat the moment Start is pressed. Telegram sends the
            secret set with setWebhook in a header; anything else is refused."""
            secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
            given = request.headers.get("x-telegram-bot-api-secret-token", "")
            if not secret or not push.ready or not hmac.compare_digest(given, secret):
                raise HTTPException(404)
            update = await request.json()
            done = await run_in_threadpool(push.telegram, update)
            return JSONResponse({"ok": True, "done": done})

    @app.get("/api/nba/us-pretip")
    def nba_us_pretip():
        """The Function calls this about 30 min before a slate's first tip: the US books are pulled
        then if they are on and due (a pull not due costs nothing, so anyone may call it)."""
        return JSONResponse({"pulled": views.nba_us_pretip()}, headers={"Cache-Control": "no-store"})

    @app.get("/api/nba/stamp", dependencies=[Depends(require_login)])
    def nba_stamp():
        """When the NBA prices on the server were worked out: the page swaps in fresher ones."""
        return JSONResponse({"priced": views.nba_stamp()}, headers={"Cache-Control": "no-store"})

    @app.get("/{path:path}", response_class=HTMLResponse, dependencies=[Depends(require_login)])
    def page(request: Request, path: str):
        started = time.perf_counter()
        try:
            html = views.page("/" + path, request.query_params, request.cookies)
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        response = HTMLResponse(html)
        # where the server's time went, for the browser's network panel and for tuning
        timing = dict(getattr(views, "timing", {}) or {})
        timing["total"] = time.perf_counter() - started
        response.headers["Server-Timing"] = ", ".join(
            f"{k};dur={v * 1000:.0f}" for k, v in timing.items()
        )
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
        if settings.asynym and path == "nba" and query.get("us") in ("0", "1"):  # US books toggle
            response.set_cookie("nba_us", query["us"], **keep)
        if settings.asynym and path == "nba" and "ch" in query:  # the $10 -> $1000 challenge
            state = nba_challenge.apply(
                nba_challenge.parse(request.cookies.get(nba_challenge.COOKIE)),
                query,
                melbourne_today().isoformat(),
            )
            if state is None:
                response.delete_cookie(nba_challenge.COOKIE)
            else:
                response.set_cookie(nba_challenge.COOKIE, nba_challenge.dump(state), **keep)
        if settings.asynym:  # ASYNYM=1: which agencies are ON, and TAB, Ladbrokes, Neds money
            for name, value in asynym.cookie_changes(query).items():
                if value is None:
                    response.delete_cookie(name)
                else:
                    response.set_cookie(name, value, **keep)
        return response

    return app
