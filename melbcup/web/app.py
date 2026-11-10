# ruff: noqa: E501
"""Phone-first web server (Render). Password-protected; pages refresh in place every minute.

Rendering and actions live in views.py, shared with the browser build.
"""

from __future__ import annotations

import json
import hmac
import html
import os
import secrets
import threading
import time
import zlib
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
    StreamingResponse,
)
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from melbcup import data_public, nba_challenge
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
  u.searchParams.forEach(function (v, k) { if (k !== "tab" && k !== "date" && k !== "sport") ok = false; });
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

    # The owner's datasets as plain links (owner, 2026-11-07): read straight from Blob, no login.
    # Phone alert records (push/) and the US switch are left out. Every file streams; a .gz file
    # also has a plain-text copy at /data/plain/<name> (?rows=N for the first N lines), so tools
    # that cannot unzip (ChatGPT's browser) can read it; /data/export/asynym-data.zip has it all.
    data_ok, data_about = data_public.DATA_OK, data_public.DATA_ABOUT

    def _about(name: str) -> str:
        return next(what for pre, what in data_about if name.startswith(pre))

    def _data_names() -> dict[str, int]:
        from melbcup.nba_feed import blob_sizes

        account = os.environ.get("NBA_ACCOUNT")
        if not account:
            raise HTTPException(404, "no data store here")
        sizes = blob_sizes(account, os.environ.get("AZURE_CLIENT_ID"))
        return {n: b for n, b in sizes.items() if data_ok.match(n)}

    @app.get("/robots.txt", response_class=PlainTextResponse)
    def robots():
        return "User-agent: *\nAllow: /data\nDisallow: /\n"

    @app.get("/data/index.json")
    def data_manifest(request: Request):
        base = str(request.base_url).rstrip("/").replace("http://", "https://", 1)  # behind TLS
        return JSONResponse(
            [
                {
                    "name": n,
                    "bytes": b,
                    "about": _about(n),
                    "url": f"{base}/data/{n}",
                    "plain": f"{base}/data/plain/{n}" if n.endswith(".gz") else None,
                }
                for n, b in sorted(_data_names().items())
            ],
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/data", response_class=HTMLResponse)
    def data_index():
        names = _data_names()
        groups: dict[str, list[str]] = {}
        for n in sorted(names):
            groups.setdefault(_about(n), []).append(n)

        def row(n: str) -> str:
            mb = f"{names[n] / 1e6:.1f} MB" if names[n] >= 1e5 else f"{names[n] / 1e3:.0f} KB"
            plain = (
                f' · <a href="/data/plain/{n}?rows=2000">first 2000 rows as text</a>'
                f' · <a href="/data/plain/{n}">all as text</a>'
                if n.endswith(".gz")
                else ""
            )
            return f'<li><a href="/data/{n}">{n}</a> ({mb}){plain}</li>'

        order = [what for _, what in data_about]
        body = "".join(
            f"<h3>{html.escape(what)}</h3><ul>{''.join(row(n) for n in groups[what])}</ul>"
            for what in order
            if what in groups
        )
        gh = "https://github.com/JesseAllomes/MELBCUP/tree/main/"
        code = "".join(
            f'<li><a href="{gh}{p}">{p}</a> {what}</li>'
            for p, what in (
                (
                    "research",
                    "every test and backtest result (research/sports: per-sport write-ups)",
                ),
                ("tools/sports", "per-sport data pullers, models and hold-out tests"),
                ("tools/nba", "NBA model, tuning, backtests (model_v3.json, model_v4.json)"),
                ("tools/racing", "racing learner"),
                ("melbcup", "the app: nba_legs.py (chances, multis), nba_challenge.py, live.py"),
            )
        )
        return HTMLResponse(
            "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            "<title>AsynymBet data</title><h1>AsynymBet data</h1>"
            "<p>Open, no login. Machine-readable list: <a href='/data/index.json'>/data/index.json</a>."
            " Compressed files (.gz) also open as plain text.</p>"
            f"{body}<h2>Code and write-ups (GitHub)</h2><ul>{code}</ul>"
        )

    def _kind(name: str) -> str:
        if name.endswith(".zip"):
            return "application/zip"
        if name.endswith(".gz"):
            return "application/gzip"
        if name.endswith(".json"):
            return "application/json"
        return "text/plain; charset=utf-8"

    def _open(name: str):
        from melbcup.nba_feed import blob_stream

        account = os.environ.get("NBA_ACCOUNT")
        if not account or not data_ok.match(name) or ".." in name:
            raise HTTPException(404, "not a dataset")
        got = blob_stream(account, os.environ.get("AZURE_CLIENT_ID"), name)
        if got is None:
            raise HTTPException(404, "not found")
        return got

    @app.get("/data/plain/{name:path}")
    def data_plain(name: str, rows: int = 0):
        """A .gz dataset unzipped on the fly as text (rows=N: only the first N lines)."""
        _, chunks = _open(name)

        def text():
            z = zlib.decompressobj(16 + zlib.MAX_WBITS) if name.endswith(".gz") else None
            left = rows if rows > 0 else None
            for c in chunks:
                out = z.decompress(c) if z else c
                if left is not None:
                    lines = out.split(b"\n")
                    if len(lines) - 1 >= left:
                        yield b"\n".join(lines[:left]) + b"\n"
                        getattr(chunks, "close", lambda: None)()  # stop the download
                        return
                    left -= len(lines) - 1
                yield out
            if z:
                yield z.flush()

        kind = "text/csv; charset=utf-8" if ".csv" in name else _kind(name.removesuffix(".gz"))
        return StreamingResponse(text(), media_type=kind, headers={"Cache-Control": "no-store"})

    @app.get("/data/{name:path}")
    def data_file(name: str):
        size, chunks = _open(name)
        headers = {"Cache-Control": "no-store"}
        if size:
            headers["Content-Length"] = str(size)
        if name.endswith((".zip", ".gz")):
            headers["Content-Disposition"] = f'attachment; filename="{name.rsplit("/", 1)[-1]}"'
        return StreamingResponse(chunks, media_type=_kind(name), headers=headers)

    @app.get("/api/nba/us-pretip")
    def nba_us_pretip():
        """The Function calls this about 30 min before a slate's first tip: the US books are pulled
        then if they are on and due (a pull not due costs nothing, so anyone may call it)."""
        return JSONResponse(
            {"pulled": views.nba_us_pretip()}, headers={"Cache-Control": "no-store"}
        )

    @app.get("/api/nba/stamp", dependencies=[Depends(require_login)])
    def nba_stamp():
        """When the NBA prices on the server were worked out: the page swaps in fresher ones."""
        return JSONResponse({"priced": views.nba_stamp()}, headers={"Cache-Control": "no-store"})

    @app.get("/api/sports/status", dependencies=[Depends(require_login)])
    def sports_status():
        """Bet-now multis: is a search running, how far, and when the last one was built."""
        from melbcup import discover

        return JSONResponse(discover.status(), headers={"Cache-Control": "no-store"})

    @app.post("/api/sports/refresh", dependencies=[Depends(require_login)])
    def sports_refresh():
        """Check now: start a multis search unless one is already running."""
        from melbcup import discover

        discover.refresh_now()
        return Response(status_code=204)

    @app.get("/api/challenge/plan", dependencies=[Depends(require_login)])
    def challenge_plan(
        sport: str = "nba", start: float = 10.0, goal: float = 1000.0, mode: str = "game", legs: int | None = None
    ):
        """The new-challenge planner sheet: stage rows, best count and the stage-1 pick."""
        try:
            data = views.challenge_plan(sport, start, goal, mode, legs)
        except Exception as exc:  # noqa: BLE001 - the sheet shows its own message
            data = {"error": str(exc)[:200], "rows": [], "best": None, "pick": None}
        return JSONResponse(data, headers={"Cache-Control": "no-store"})

    _chance_cache: dict = {}

    @app.post("/api/slip/chance", dependencies=[Depends(require_login)])
    async def slip_chance(request: Request):
        """The slip's joint chance with same-game correlation, multiplied across games."""
        try:
            legs = (await request.json()).get("legs") or []
            key = json.dumps(legs, sort_keys=True)
            if key not in _chance_cache:
                if len(_chance_cache) > 200:
                    _chance_cache.clear()
                _chance_cache[key] = views.slip_chance(legs)
            data = _chance_cache[key]
        except Exception:  # noqa: BLE001 - the slip falls back to "approx"
            data = {"p": None, "exact": False}
        return JSONResponse(data, headers={"Cache-Control": "no-store"})

    @app.get("/api/mybet/card", dependencies=[Depends(require_login)])
    def mybet_card(request: Request, id: int):
        """One own bet's live tiles (the My bets sheet loads it when a card opens)."""
        try:
            from melbcup.web.views import own_cards

            store = nba_challenge.load(request.cookies.get(nba_challenge.COOKIE))
            bets = [b for b in (store["own"] or {}).get("bets", []) if b.get("own") and b["id"] == id]
            data = own_cards(bets, views.track_for(bets)).get(id) or {}
        except Exception:  # noqa: BLE001 - never crash a poll
            data = {}
        return JSONResponse(data, headers={"Cache-Control": "no-store"})

    @app.get("/nba/challenges/live.json", dependencies=[Depends(require_login)])
    def nba_challenges_live(request: Request):
        """{challenge id: {pct, clock}} for the accordion's collapsed rows (polled every ~30 s)."""
        try:
            store = nba_challenge.load(request.cookies.get(nba_challenge.COOKIE))
            from melbcup.web.views import challenges_live

            data = challenges_live(store)
        except Exception:  # noqa: BLE001 - never crash a poll
            data = {}
        return JSONResponse(data, headers={"Cache-Control": "no-store"})

    @app.get("/nba", dependencies=[Depends(require_login)])
    def nba_redirect(request: Request):
        """The NBA page moved into the Sports hub: same query, 307 so forms and old links work."""
        q = request.url.query
        return RedirectResponse("/sports?sport=nba" + ("&" + q if q else ""), status_code=307)

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
        if (
            settings.asynym and path in ("nba", "sports") and query.get("us") in ("0", "1")
        ):  # US books toggle
            response.set_cookie("nba_us", query["us"], **keep)
        if (
            settings.asynym and path in ("nba", "sports") and "ch" in query
        ):  # challenges, wallet, recorded wagers
            before = nba_challenge.load(request.cookies.get(nba_challenge.COOKIE))
            store, changed, _ = nba_challenge.apply_store(
                before, query, melbourne_today().isoformat()
            )
            try:  # the cookie (the old single challenge) is dropped only once the store holds it
                if changed or (store.get("migrated") and nba_challenge._read() is None):
                    nba_challenge.save(store)
                safe = nba_challenge._read() is not None
            except nba_challenge.StoreUnavailable:
                safe = False
            if safe and request.cookies.get(nba_challenge.COOKIE):
                response.delete_cookie(nba_challenge.COOKIE)
        if settings.asynym:  # ASYNYM=1: which agencies are ON, and TAB, Ladbrokes, Neds money
            for name, value in asynym.cookie_changes(query).items():
                if value is None:
                    response.delete_cookie(name)
                else:
                    response.set_cookie(name, value, **keep)
        return response

    return app
