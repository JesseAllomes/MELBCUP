// AsynymBet (ASYNYM=1): small touches on top of pages that already work without JavaScript.
// Live refresh and the "R2 jumps in 4:12" countdown come from app.js; bets are recorded by the
// script in _bets_js.html.
(function () {
  "use strict";

  // app.js skips a refresh while a form has an edited field. Mark one in the page while the
  // Agencies panel or the Mine amounts are being changed, so a refresh does not close them.
  function hold(on) {
    var h = document.getElementById("hold");
    if (h) h.value = on ? "1" : "";
  }

  // The Agencies panel: aria-expanded on the switch label, and a money box only while ON.
  document.addEventListener("change", function (e) {
    var t = e.target;
    if (!t || !t.classList) return;
    if (t.id === "agt") {
      var label = document.querySelector('label.set[for="agt"]');
      if (label) label.setAttribute("aria-expanded", String(t.checked));
      hold(t.checked);
    } else if (t.classList.contains("sw")) {
      var row = t.closest(".agrow");
      if (row) row.classList.toggle("off", !t.checked);
    }
  });

  // Mine: Edit turns every dollar amount into an input in place; Done saves (the form submits).
  // Without JavaScript the Edit link reloads the page with ?edit=1 and does the same.
  document.addEventListener("click", function (e) {
    var edit = e.target.closest && e.target.closest("#pool-edit");
    if (!edit) return;
    e.preventDefault();
    var pool = document.getElementById("pool");
    if (!pool) return;
    pool.classList.add("editing");
    hold(true);
    var first = pool.querySelector(".mi");
    if (first) first.focus();
  });
  var pool = document.getElementById("pool");
  if (pool && pool.classList.contains("editing")) hold(true);
})();


// No "Install app" banner, ever (owner): the page works as a website and alerts need no install.
window.addEventListener("beforeinstallprompt", function (e) { e.preventDefault(); });

// Phone alerts on the NBA Challenge tab (owner, 2026-11-04): register the service worker, ask
// Chrome for permission, subscribe with the site's public key, and hand the server the stage
// times (it pushes them from Azure, so they arrive with Chrome closed).
(function () {
  "use strict";
  var card = document.getElementById("push-card");
  if (!card) return;
  var canPush = ("serviceWorker" in navigator) && ("PushManager" in window) && ("Notification" in window);
  var on = document.getElementById("push-on"), test = document.getElementById("push-test");
  var state = document.getElementById("push-state");
  var tg = document.getElementById("tg-on"), tgNote = document.getElementById("tg-note");
  var linked = { web: false, telegram: false };
  function get(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } }
  function set(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* private mode */ } }
  function post(url, body) {
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }
  function key(b64) {
    var pad = "=".repeat((4 - b64.length % 4) % 4), raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }
  function reminders() {
    var el = document.getElementById("push-reminders"), id = get("push_id");
    if (!el || !id) return Promise.resolve();
    var list = [];
    try { list = JSON.parse(el.textContent); } catch (e) { list = []; }
    return post("/api/push/remind", { id: id, reminders: list }).catch(function () { /* next visit */ });
  }
  function show() {
    var web = canPush && get("push_id") && Notification.permission === "granted" && linked.web;
    var bits = [];
    if (web) bits.push("Chrome ✓");
    if (linked.telegram) bits.push("Telegram ✓");
    state.textContent = bits.length ? bits.join(" · ") : (canPush && Notification.permission === "denied" ? "Chrome alerts blocked in settings" : "off");
    on.hidden = !canPush || !!web || Notification.permission === "denied";
    tg.hidden = linked.telegram;
    test.hidden = !(web || linked.telegram);
  }
  function refresh() {
    var id = get("push_id");
    if (!id) { show(); return; }
    post("/api/push/status", { id: id }).then(function (s) {
      if (!s.known) { try { window.localStorage.removeItem("push_id"); } catch (e) { /* ignore */ } }
      linked = { web: !!s.web, telegram: !!s.telegram };
    }).catch(function () {}).then(show);
  }
  function watch(n) {  // after Start in Telegram the link is instant: show it as soon as it lands
    if (n > 40 || linked.telegram) return;
    window.setTimeout(function () {
      post("/api/push/status", { id: get("push_id") }).then(function (s) {
        linked = { web: !!s.web, telegram: !!s.telegram };
        if (linked.telegram) { tgNote.hidden = true; show(); } else watch(n + 1);
      }).catch(function () { watch(n + 1); });
    }, 3000);
  }
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
  tg.addEventListener("click", function () {
    var win = window.open("about:blank", "_blank");  // opened on the tap, so it is not blocked
    var id = get("push_id");
    (id ? Promise.resolve(id) : post("/api/push/link", {}).then(function (r) { set("push_id", r.id); return r.id; }))
      .then(function (pid) {
        var url = "https://t.me/AsynymBetBot?start=" + pid;
        if (win) win.location = url; else window.location = url;
        tgNote.hidden = false;
        watch(0);
        return reminders();
      })
      .catch(function () { if (win) win.close(); state.textContent = "could not start the Telegram link"; });
  });
  on.addEventListener("click", function () {
    on.disabled = true;
    navigator.serviceWorker.register("/sw.js", { scope: "/" })
      .then(function () { return Notification.requestPermission(); })
      .then(function (p) {
        if (p !== "granted") throw new Error("permission " + p);
        return navigator.serviceWorker.ready;
      })
      .then(function (reg) { return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key(card.dataset.key) }); })
      .then(function (sub) { return post("/api/push/subscribe", { subscription: sub.toJSON(), id: get("push_id") }); })
      .then(function (r) { set("push_id", r.id); linked.web = true; return reminders(); })
      .catch(function (e) { state.textContent = "could not turn on (" + e.message + ")"; })
      .then(function () { on.disabled = false; show(); });
  });
  test.addEventListener("click", function () {
    test.disabled = true;
    post("/api/push/test", { id: get("push_id") })
      .then(function (r) {
        state.textContent = r.sent ? "test sent ✓ (" + r.sent.join(", ") + ")" : "test on its way";
      })
      .catch(function () { state.textContent = "test failed: turn alerts on again"; refresh(); })
      .then(function () { test.disabled = false; });
  });
  refresh();
  reminders();
})();

// liveSwap (owner, 2026-11-08): every page updates itself in place. Re-read this URL and swap the
// main content; scroll, open rows/details and the chip strip stay. Never navigates, never a pill.
(function () {
  "use strict";
  var busy = false;
  function blocked(main) {
    var a = document.activeElement;
    if (a && main.contains(a) && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)) return true;
    if (document.querySelector("dialog[open], [role=menu]:not([hidden]), [role=dialog]:not([hidden])")) return true;
    return Array.prototype.some.call(main.querySelectorAll("input,textarea"), function (i) {
      return !/^(hidden|checkbox|radio|button|submit)$/.test(i.type) && i.value !== i.defaultValue;
    });
  }
  window.liveSwap = function () {
    var main = document.getElementById("main");
    if (!main || busy || document.hidden || blocked(main)) return Promise.resolve(false);
    busy = true;
    return fetch(location.href, { cache: "no-store", credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.text() : Promise.reject(r.status); })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, "text/html");
        var fresh = doc.getElementById("main");
        if (!fresh || blocked(main)) return false;
        var y = window.scrollY;
        var openRow = main.querySelector(".chs-row.open");
        var rowId = openRow ? openRow.getAttribute("data-id") : null;
        var ds = Array.prototype.slice.call(main.querySelectorAll("details"));
        var openIds = ds.map(function (d) { return d.open ? d.id : null; });
        var openIdx = ds.map(function (d) { return d.open; });
        var nav = main.querySelector(".strip, .sp-tabs");
        var x = nav ? nav.scrollLeft : 0;
        main.innerHTML = fresh.innerHTML;
        main.querySelectorAll("details").forEach(function (d, i) {
          if (d.id ? openIds.indexOf(d.id) >= 0 : openIdx[i]) d.open = true;
        });
        var nav2 = main.querySelector(".strip, .sp-tabs");
        if (nav2) nav2.scrollLeft = x;
        if (rowId) {
          main.querySelectorAll(".chs-row").forEach(function (r) {
            var h = r.getAttribute("data-id") === rowId && r.querySelector(".chs-head");
            if (h) h.click();
          });
        }
        window.scrollTo(0, y);
        if (window.initChallengeAccordion) window.initChallengeAccordion();
        document.dispatchEvent(new CustomEvent("melb:data", { detail: doc }));
        var sv = document.getElementById("saved-copy-pill");
        if (sv) sv.remove();
        return true;
      })
      .catch(function () { return false; })
      .then(function (ok) { busy = false; return ok; });
  };
  // retry later when skipped (typing, menu open, tab hidden)
  window.liveSwapSoon = function (tries) {
    tries = tries || 0;
    window.liveSwap().then(function (ok) {
      if (!ok && tries < 40) window.setTimeout(function () { window.liveSwapSoon(tries + 1); }, 5000);
    });
  };
})();

// Saved copy (owner, 2026-11-04): the service worker keeps every page, so a sleeping server never
// leaves a blank screen. When this page is that saved copy, say so and swap in the fresh one.
(function () {
  "use strict";
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {});
  var at = document.body && document.body.getAttribute("data-saved");
  if (!at) return;
  var pill = document.createElement("button");
  pill.type = "button";
  pill.className = "saved-pill"; pill.id = "saved-copy-pill";
  var when = new Date(Number(at)).toLocaleTimeString("en-AU", { hour: "numeric", minute: "2-digit", timeZone: "Australia/Melbourne" });
  pill.textContent = "Saved copy " + when + " · updating…";
  document.body.appendChild(pill);
  (function poll(n) {
    fetch(location.href, { cache: "no-store", credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return window.liveSwap();
      })
      .then(function (ok) { if (!ok && n < 40) window.setTimeout(function () { poll(n + 1); }, 4000); })
      .catch(function () { if (n < 40) window.setTimeout(function () { poll(n + 1); }, 3000); });
  })(0);
})();

// Fresh NBA prices on every load (owner, 2026-11-06): the server shows its latest copy at once and
// works out new prices behind it; when they land, swap the page in place (no reload, no tap).
// The URL is never changed.
(function () {
  "use strict";
  var el = document.getElementById("nba-priced");
  if (!el) return;
  // the Challenge tab keeps its own live numbers: no reload there (owner, 2026-11-08)
  if (new URL(location.href).searchParams.get("tab") === "challenge" || document.querySelector(".chs-list")) return;
  var mine = Date.parse(el.getAttribute("data-priced") || "") || 0;
  (function poll(n) {
    if (n > 15) return;
    window.setTimeout(function () {
      fetch("/api/nba/stamp", { cache: "no-store", credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          var t = Date.parse(d.priced || "") || 0;
          if (t <= mine) { poll(n + 1); return; }
          mine = t;
          window.liveSwapSoon();
        })
        .catch(function () { poll(n + 1); });
    }, 3000);
  })(0);
})();

// Bet now (owner BUILD, 2026-11-07): the multis are searched on the server behind the page. Poll the
// status; show a slim bar while it works and swap the page in place when a newer result lands.
(function () {
  "use strict";
  if (location.pathname !== "/sports") return;
  var root = document.getElementById("bn");
  var mine = root ? root.getAttribute("data-built") || "" : null;
  var bar = null, timer = null;
  function barOf() {
    if (bar) return bar;
    bar = document.createElement("div");
    bar.className = "bn-bar"; bar.setAttribute("role", "status");
    bar.innerHTML = '<div class="ut"><b></b><span>shows the last result meanwhile</span></div><div class="bar"><i></i></div>';
    var h = document.querySelector("header") || document.body.firstElementChild;
    if (h && h.parentNode) h.parentNode.insertBefore(bar, h.nextSibling); else document.body.prepend(bar);
    return bar;
  }
  function age(s) {
    if (s == null) return "";
    return s < 60 ? "Updated just now" : s < 3600 ? "Updated " + Math.floor(s / 60) + " min ago" : "Updated " + Math.floor(s / 3600) + "h ago";
  }
  function tick() {
    if (timer) window.clearTimeout(timer);
    if (document.hidden) return;
    fetch("/api/sports/status", { cache: "no-store", credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (mine === null) mine = d.built || "";
        var b = document.getElementById("bn-check"), a = document.getElementById("bn-age");
        if (d.busy) {
          var el = barOf(), pc = Math.round((d.progress || 0) * 100);
          el.hidden = false;
          el.querySelector("b").textContent = "Updating multis · " + pc + "%";
          el.querySelector("i").style.width = pc + "%";
        } else if (bar) { bar.hidden = true; }
        if (b) b.disabled = !!d.busy;
        if (a && !d.busy && d.age_s != null) a.textContent = age(d.age_s);
        if (!d.busy && d.built && d.built !== mine) { mine = d.built; window.liveSwapSoon(); }
        timer = window.setTimeout(tick, d.busy ? 2000 : 15000);
      })
      .catch(function () { timer = window.setTimeout(tick, 15000); });
  }
  var chk = document.getElementById("bn-check");
  if (chk) chk.addEventListener("click", function () {
    chk.disabled = true;
    fetch("/api/sports/refresh", { method: "POST", credentials: "same-origin" })
      .catch(function () {}).then(function () { tick(); });
  });
  document.addEventListener("visibilitychange", function () { if (!document.hidden) tick(); });
  tick();
})();

// Sports: keep the chosen sport in view in the chip row (owner 2026-11-08: it snapped back to the
// start after every tap, so the next sport had to be scrolled to again).
(function () {
  var on = document.querySelector(".sp-tabs a.on");
  if (!on || !on.parentNode) return;
  var row = on.parentNode;
  row.scrollLeft = on.offsetLeft - (row.clientWidth - on.offsetWidth) / 2;
})();

// Challenge card (owner lock 2026-11-08): while a game is in play, re-read the page every 60 s and
// swap in just the card, so the live count, bars and chance move without a reload. Only the tab and
// challenge are repeated (never an action in the address).
(function () {
  "use strict";
  var card = document.getElementById("chv9");
  if (!card || card.getAttribute("data-live") !== "1") return;
  var u = new URL(location.href), keep = new URLSearchParams();
  ["sport", "tab", "chid", "bk"].forEach(function (k) { if (u.searchParams.get(k)) keep.set(k, u.searchParams.get(k)); });
  var url = u.pathname + "?" + keep.toString();
  function tick() {
    if (document.hidden) return;
    fetch(url, { cache: "no-store", credentials: "same-origin" })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        var next = new DOMParser().parseFromString(html, "text/html").getElementById("chv9");
        var cur = document.getElementById("chv9");
        if (next && cur) cur.innerHTML = next.innerHTML;
        if (!next || next.getAttribute("data-live") !== "1") window.clearInterval(timer);
      })
      .catch(function () {});
  }
  var timer = window.setInterval(tick, 60000);
})();

// Challenge accordion (owner, 2026-11-08): rows open in place from saved figures; the card with
// live numbers is fetched after; collapsed rows poll live.json every 30 s while the page is visible.
(function () {
  "use strict";
  var started = false;
  function rows() { return document.querySelectorAll(".chs-list .chs-row"); }
  function lazy(body) {
    if (!body.dataset.url) return;
    fetch(body.dataset.url, { cache: "no-store", credentials: "same-origin" })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, "text/html");
        var fresh = doc.getElementById("chv9"), whole = doc.getElementById(body.id);
        if (!fresh || body.hidden) return;
        var mine = body.querySelector(".chv9");
        if (mine) { mine.innerHTML = fresh.innerHTML; return; }
        // the card plus this challenge's next-stage bet, place, results and edit (owner, 2026-11-08)
        if (whole) { body.innerHTML = whole.innerHTML; return; }
        var saved = body.querySelector(".chs-saved");
        if (saved) saved.remove();
        body.appendChild(document.importNode(fresh, true));
      })
      .catch(function () {});
  }
  document.addEventListener("click", function (e) {
    var head = e.target.closest && e.target.closest(".chs-list .chs-head");
    if (!head) return;
    var row = head.parentNode, body = row.querySelector(".chs-body");
    var was = head.getAttribute("aria-expanded") === "true";
    rows().forEach(function (r) {
      r.classList.remove("open");
      r.querySelector(".chs-head").setAttribute("aria-expanded", "false");
      r.querySelector(".chs-body").hidden = true;
    });
    if (was) return;
    row.classList.add("open");
    head.setAttribute("aria-expanded", "true");
    body.hidden = false;
    lazy(body);
  });
  function poll() {
    if (document.hidden) return;
    fetch("/nba/challenges/live.json", { cache: "no-store", credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        rows().forEach(function (row) {
          var v = d[row.dataset.id];
          if (!v) return;
          row.classList.toggle("failed", !!v.failed);
          if (v.failed) {
            row.querySelector(".chs-pct").textContent = "Failed";
          } else if (v.pct !== null && v.pct !== undefined) {
            row.style.setProperty("--p", v.pct + "%");
            row.querySelector(".chs-pct").textContent = v.pct + "%";
          }
          row.querySelector(".chs-clock").textContent = v.clock || "";
        });
      })
      .catch(function () {});
  }
  // idempotent: starts the 30 s poll once; safe to call again after a swap
  window.initChallengeAccordion = function () {
    if (!document.querySelector(".chs-list")) return;
    poll();
    if (started) return;
    started = true;
    window.setInterval(poll, 30000);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) poll(); });
  };
  window.initChallengeAccordion();
})();

// ===== v13 bottom sheets + bet slip (owner BUILD 2026-11-10) =====
(function () {
  "use strict";
  document.documentElement.classList.add("js");
  var RM = !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  var stack = [];
  function esc(t) { return String(t == null ? "" : t).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function lockBody() { document.body.style.overflow = stack.length ? "hidden" : ""; }
  function topS() { return stack[stack.length - 1]; }

  // The sheet: slides up, follows the finger down, closes past 30% of its height or on a flick
  // (> 0.5 px/ms), springs back otherwise. Drag starts from the head, or the body at scroll top.
  function openSheet(title, content, onOpen) {
    var layer = document.createElement("div");
    layer.className = "sh-layer";
    layer.innerHTML = '<div class="sh-bd"></div><div class="sh-sheet" role="dialog" aria-modal="true" aria-label="' + esc(title) + '"><div class="sh-head"><div class="sh-grab"></div><div class="sh-title"><h2>' + esc(title) + '</h2><button type="button" class="sh-x" data-close aria-label="Close">✕</button></div></div><div class="sh-body"></div></div>';
    var sheet = layer.querySelector(".sh-sheet"), body = layer.querySelector(".sh-body"), head = layer.querySelector(".sh-head");
    if (typeof content === "string") body.innerHTML = content; else if (content) body.appendChild(content);
    document.body.appendChild(layer);
    var S = { layer: layer, sheet: sheet, body: body, y: 0, h: 0 };
    S.render = function (html) { body.innerHTML = html; };
    S.close = function () { closeSheet(S); };
    stack.forEach(function (x) { x.layer.classList.add("under"); });
    stack.push(S); lockBody();
    layer.querySelector("[data-close]").onclick = S.close;
    layer.querySelector(".sh-bd").onclick = function () { if (topS() === S) S.close(); };
    var set = function (y) { S.y = y; sheet.style.transform = "translateY(" + y + "px)"; };
    S.set = set;
    S.h = sheet.offsetHeight; sheet.getBoundingClientRect();
    sheet.classList.add("anim"); layer.classList.add("in"); set(0);
    sheet.addEventListener("transitionend", function () { sheet.classList.remove("anim"); }, { once: true });
    var d = null;
    var pt = function (e) { return e.touches ? e.touches[0] : e; };
    function start(e) {
      if (topS() !== S || (e.touches && e.touches.length > 1)) return;
      var p = pt(e);
      d = { y0: p.clientY, x0: p.clientX, inHead: head.contains(e.target), on: false, s: [{ t: performance.now(), y: p.clientY }] };
    }
    function move(e) {
      if (!d) return;
      var p = pt(e), dy = p.clientY - d.y0;
      if (!d.on) {
        var can = d.inHead || body.scrollTop <= 0;
        if (can && dy > 6 && Math.abs(dy) > Math.abs(p.clientX - d.x0)) { d.on = true; d.y0 = p.clientY; S.h = sheet.offsetHeight; sheet.classList.remove("anim", "out"); } else return;
      }
      if (e.cancelable) e.preventDefault();
      var dd = p.clientY - d.y0;
      set(dd >= 0 ? dd : dd * 0.15);
      d.s.push({ t: performance.now(), y: p.clientY });
      while (d.s.length > 2 && d.s[0].t < performance.now() - 120) d.s.shift();
    }
    function end() {
      if (!d) return;
      var was = d; d = null;
      if (!was.on) return;
      var a = was.s[0], b = was.s[was.s.length - 1], v = b.t > a.t ? (b.y - a.y) / (b.t - a.t) : 0;
      sheet.classList.add("anim");
      if (S.y > S.h * 0.3 || v > 0.5) closeSheet(S, true); else set(0);
    }
    sheet.addEventListener("touchstart", start, { passive: true });
    sheet.addEventListener("touchmove", move, { passive: false });
    sheet.addEventListener("touchend", end); sheet.addEventListener("touchcancel", end);
    sheet.addEventListener("mousedown", function (e) {
      if (e.target.closest("input,select,textarea,button")) return;
      start(e);
      var mm = function (ev) { move(ev); }, mu = function () { removeEventListener("mousemove", mm); removeEventListener("mouseup", mu); end(); };
      addEventListener("mousemove", mm); addEventListener("mouseup", mu);
    });
    if (onOpen) onOpen(S);
    return S;
  }
  function closeSheet(S, fromDrag) {
    var i = stack.indexOf(S);
    if (i < 0) return;
    stack.splice(i, 1);
    S.layer.classList.remove("in");
    if (!fromDrag) S.sheet.classList.add("anim");
    S.sheet.classList.add("out");
    S.set(S.sheet.offsetHeight + 40);
    setTimeout(function () { S.layer.remove(); lockBody(); }, RM ? 30 : 300);
    var t = topS(); if (t) t.layer.classList.remove("under");
    lockBody();
  }
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && topS()) topS().close(); });
  window.AzSheet = { open: openSheet, close: function () { var t = topS(); if (t) t.close(); }, count: function () { return stack.length; } };

  // Server-rendered forms live in <div class="sheet-src" id=...>; a [data-sheet-for] button opens
  // them in a sheet (the form keeps its own server action).
  function fromSrc(id) {
    var src = document.getElementById(id);
    if (!src) return null;
    var wrap = document.createElement("div");
    wrap.innerHTML = src.innerHTML;
    var S = openSheet(src.getAttribute("data-title") || "Details", wrap);
    if (src.getAttribute("data-filter")) mbFilter(S.body, src.getAttribute("data-filter"));
    return S;
  }
  // My bets sheet: "this sport" / "all sports" chips over the collapsible bet cards.
  function mbFilter(root, f) {
    var sp = (document.getElementById("slip-cfg") ? (JSON.parse(document.getElementById("slip-cfg").textContent || "{}").sport || "") : "");
    root.querySelectorAll(".mb-card").forEach(function (c) { c.hidden = f === "this" && sp !== "home" && c.getAttribute("data-sport") !== sp; });
    root.querySelectorAll("[data-mbf]").forEach(function (b) { b.classList.toggle("on", b.getAttribute("data-mbf") === f); });
  }
  function tileHtml(t) {
    var st = t.cls === "g" ? "hit" : t.cls === "r" ? "failed" : t.cls === "x" ? "no longer counts" : t.chance != null ? "win " + Math.round(t.chance * 100) + "%" : "not started";
    return '<div class="tile ' + esc(t.cls) + '"><b>' + esc(t.name) + "</b><small>" + esc(t.line) + '</small><div class="v">' + esc(t.now) + "<small> / " + esc(t.k) + '</small></div><div class="lb"><u style="width:' + (+t.fill || 0) + '%"></u></div><small>' + st + (t.under && t.cls !== "x" ? " · bar fills toward the limit" : "") + "</small></div>";
  }
  // a My bets card opens: re-read its live tiles, live % and clock (cheap, cached server side)
  document.addEventListener("toggle", function (e) {
    var d = e.target;
    if (!d.classList || !d.classList.contains("mb-card") || !d.open || !d.getAttribute("data-bet")) return;
    fetch("/api/mybet/card?id=" + encodeURIComponent(d.getAttribute("data-bet")), { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (j) {
      if (!j || !j.tiles) return;
      var box = d.querySelector(".mb-tiles");
      if (box) box.innerHTML = j.tiles.map(tileHtml).join("");
      var p = d.querySelector(".mb-p"); if (p && j.p != null) p.textContent = Math.round(j.p * 100) + "%" + (j.live ? " live" : "");
      var c = d.querySelector(".mb-clock"); if (c) c.textContent = j.clock || "";
      d.classList.toggle("dead", !!j.dead);
    }).catch(function () { /* keep what the page rendered */ });
  }, true);
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-mbf]");
    if (b) mbFilter(b.closest(".sh-body"), b.getAttribute("data-mbf"));
  });
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-sheet-for]");
    if (b) { e.preventDefault(); fromSrc(b.getAttribute("data-sheet-for")); }
  });
  function autoOpen() { var a = document.querySelector(".sheet-src[data-open]"); if (a && !topS()) { a.removeAttribute("data-open"); fromSrc(a.id); } }

  // ---------- the slip ----------
  var KEY = "asynym.slip.v1", mem = [];
  function load() { try { var v = JSON.parse(localStorage.getItem(KEY) || "null"); if (Array.isArray(v)) return v; } catch (x) { /* none */ } return mem; }
  function save(a) { mem = a; try { localStorage.setItem(KEY, JSON.stringify(a)); } catch (x) { /* kept in memory */ } }
  var cfg = {};
  function readCfg() { try { var ce = document.getElementById("slip-cfg"); if (ce) cfg = JSON.parse(ce.textContent || "{}"); } catch (x) { /* keep the last */ } }
  readCfg();
  function money(n) { return "$" + (+n).toFixed(2); }
  function mel(iso) {
    if (!iso) return "";
    try { return new Date(iso).toLocaleString("en-AU", { timeZone: "Australia/Melbourne", weekday: "short", hour: "numeric", minute: "2-digit", hour12: true }); } catch (x) { return ""; }
  }
  function normLeg(l) {
    var o = { id: l.id || "", sport: String(l.sport || cfg.sport || "").toLowerCase(), game: l.game || "", startsAt: l.startsAt || "", label: String(l.label || ""), price: +l.price || 0, chance: l.chance == null || l.chance === "" ? null : +l.chance, mk: l.mk || "", side: l.side == null ? "" : String(l.side), raw: l.raw || null };
    if (!o.id) o.id = [o.sport, o.game, o.label].join("|");
    if (!o.mk) {
      var t = o.label, u = /\bunder\b/i.test(t);
      if (u || /\bover\b/i.test(t) || /\d\+/.test(t)) { o.mk = t.replace(/\b(over|under)\b/ig, "").replace(/[\d.]+\+?/g, "").replace(/\s+/g, " ").trim().toLowerCase(); o.side = u ? "u" : "o"; }
    }
    return o;
  }
  function has(id) { return load().some(function (l) { return l.id === id; }); }
  function add(l) { var a = load(), n = normLeg(l); if (!a.some(function (x) { return x.id === n.id; })) { a.push(n); save(a); } sync(); }
  function remove(id) { save(load().filter(function (l) { return l.id !== id; })); sync(); }
  function toggle(l) { var n = normLeg(l); if (has(n.id)) remove(n.id); else add(n); }
  function clear() { save([]); sync(); }
  function analyse(a) {
    var price = a.reduce(function (x, l) { return x * (l.price || 1); }, 1);
    var chance = a.reduce(function (x, l) { return x * (l.chance != null ? l.chance : (l.price ? 1 / l.price : 1)); }, 1);
    var games = {}, sports = {}, marks = {}, clash = [];
    a.forEach(function (l) {
      var g = l.game || "(no game)";
      (games[g] = games[g] || []).push(l);
      if (l.sport) sports[l.sport] = 1;
      if (l.mk) { var k = g + "|" + l.mk; if (marks[k] && marks[k].side !== l.side) clash.push([marks[k], l]); else if (!marks[k]) marks[k] = l; }
    });
    var linked = Object.keys(games).filter(function (g) { return games[g].length > 1; });
    var sp = Object.keys(sports);
    return { price: price, chance: chance, games: games, linked: linked, clash: clash, sport: sp.length > 1 ? "multi" : (sp[0] || cfg.sport || ""), n: a.length };
  }
  function label(a) {
    var order = [], by = {};
    a.forEach(function (l) { var g = l.game || ""; if (!by[g]) { by[g] = []; order.push(g); } by[g].push(l.label); });
    if (order.length === 1 && !order[0]) return a.map(function (l) { return l.label; }).join(", ");
    return order.map(function (g) { return (g ? g + ": " : "") + by[g].join(", "); }).join("; ");
  }
  var exactMemo = {};
  function exactChance(a, done) {
    var key = JSON.stringify(a.map(function (l) { return l.id; }));
    if (exactMemo[key] !== undefined) return exactMemo[key];
    exactMemo[key] = null;
    fetch("/api/slip/chance", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ legs: a }) })
      .then(function (r) { return r.json(); }).then(function (j) { exactMemo[key] = j && j.exact && j.p != null ? j.p : false; done(); }).catch(function () { exactMemo[key] = false; done(); });
    return null;
  }
  function pct(c) { return (c * 100 >= 10 ? Math.round(c * 100) : (c * 100).toFixed(1)) + "%"; }

  var bar = document.getElementById("slip-bar");
  function shownChance(a, z) {
    var own = a.some(function (l) { return l.chance == null; });  // a typed leg: its price is the only guide
    if (!z.linked.length) return { c: z.chance, approx: own };
    var e = exactChance(a, sync);
    return e ? { c: e, approx: false } : { c: z.chance, approx: e !== false || true && exactMemo[JSON.stringify(a.map(function (l) { return l.id; }))] === false };
  }
  function sync() {
    readCfg();
    var a = load();
    document.querySelectorAll(".tk[data-leg]").forEach(function (b) {
      try { var l = normLeg(JSON.parse(b.getAttribute("data-leg"))); b.setAttribute("aria-pressed", a.some(function (x) { return x.id === l.id; }) ? "true" : "false"); } catch (x) { /* bad leg */ }
    });
    if (bar) {
      if (!a.length) { bar.hidden = true; } else {
        var z = analyse(a), sc = shownChance(a, z);
        bar.hidden = false;
        bar.innerHTML = "<span>Slip · " + z.n + " leg" + (z.n === 1 ? "" : "s") + " · " + money(z.price) + " · " + pct(sc.c) + (sc.approx ? " approx" : "") + "</span><span>▲</span>";
      }
    }
    var top = topS();
    if (top && top.slipView) top.slipView();
  }
  function toast(t) {
    var e = document.createElement("div"); e.className = "sh-toast"; e.textContent = t; document.body.appendChild(e);
    setTimeout(function () { e.remove(); }, 1600);
  }
  document.addEventListener("click", function (e) {
    var t = e.target.closest && e.target.closest(".tk[data-leg]");
    if (t) { e.preventDefault(); try { toggle(JSON.parse(t.getAttribute("data-leg"))); } catch (x) { /* bad leg */ } return; }
    var ed = e.target.closest && e.target.closest(".tk-edit[data-legs]");
    if (ed) {  // a challenge stage's legs into the slip, to change them (owner, 2026-11-11)
      e.preventDefault();
      try { save([]); JSON.parse(ed.getAttribute("data-legs")).forEach(add); try { localStorage.setItem(KEY + "-for", ed.getAttribute("data-chid") || ""); } catch (x) { /* storage off */ } slipSheet(); } catch (x) { /* bad legs */ }
      return;
    }
    var all = e.target.closest && e.target.closest("[data-legs]");
    if (all) {
      e.preventDefault();
      try { JSON.parse(all.getAttribute("data-legs")).forEach(add); toast("Added to slip"); } catch (x) { /* bad legs */ }
    }
    var np = e.target.closest && e.target.closest("[data-plan]");
    if (np) { e.preventDefault(); planSheet(); }
    var rm = e.target.closest && e.target.closest("[data-record]");
    if (rm) { e.preventDefault(); recordSheet(load()); }
  });
  if (bar) bar.addEventListener("click", function () { slipSheet(); });

  function url(params) {
    var q = [];
    Object.keys(params).forEach(function (k) { if (params[k] !== "" && params[k] != null) q.push(encodeURIComponent(k) + "=" + encodeURIComponent(params[k])); });
    return "/sports?" + q.join("&");
  }
  function pageSport() { return cfg.sport || "home"; }

  function slipSheet() {
    readCfg();
    openSheet("Slip", "", function (S) {
      S.slipView = function () {
        var a = load();
        if (!a.length) { S.render('<p class="say">The slip is empty. Tick legs on any card to add them.</p>'); return; }
        var z = analyse(a), sc = shownChance(a, z), h = "";
        a.forEach(function (l) {
          h += '<div class="sh-leg"><span><b>' + esc(l.label) + '</b><small>' + esc((l.sport ? l.sport.toUpperCase() + " · " : "") + (l.game || "") + (l.startsAt ? " · " + mel(l.startsAt) : "")) + '</small></span><b class="px">' + (l.price ? l.price.toFixed(2) : "") + '</b><button type="button" class="sh-x" data-rm="' + esc(l.id) + '" aria-label="Remove leg">✕</button></div>';
        });
        h += '<div class="sh-kv"><span>Price</span><b>' + money(z.price) + '</b></div><div class="sh-kv"><span>Chance every leg wins</span><b>' + pct(sc.c) + (sc.approx ? " (approx)" : "") + '</b></div>';
        if (z.linked.length && sc.approx) h += '<div class="sh-warn">Linked: ' + esc(z.linked.join(", ")) + ' has more than one leg. Legs in one game move together, so the chance is approximate and the bookmaker may price the combination lower.</div>';
        z.clash.forEach(function (c) { h += '<div class="sh-warn sh-bad">Clash: "' + esc(c[0].label) + '" and "' + esc(c[1].label) + '" are opposite sides of the same bet.</div>'; });
        h += '<details class="sh-own"><summary>+ Add my own leg</summary><label>Leg<input id="ow-l" placeholder="e.g. Jalen Brunson Over 24.5 Points"></label><div class="sh-chips"><label style="flex:1">Game<input id="ow-g" placeholder="Knicks @ Celtics"></label><label style="flex:1">Price $<input id="ow-p" inputmode="decimal"></label></div><button type="button" class="sh-btn" data-act="own">Add leg</button></details>';
        h += '<button type="button" class="sh-btn pri" data-act="record">Record as my bet</button><button type="button" class="sh-btn" data-act="chal">Use in a challenge</button><button type="button" class="sh-btn" data-act="clear">Clear slip</button>';
        S.render(h);
        S.body.querySelectorAll("[data-rm]").forEach(function (b) { b.onclick = function () { remove(b.getAttribute("data-rm")); }; });
        S.body.querySelector('[data-act="record"]').onclick = function () { recordSheet(load()); };
        S.body.querySelector('[data-act="chal"]').onclick = function () { challengeSheet(load()); };
        S.body.querySelector('[data-act="clear"]').onclick = function () { clear(); S.close(); };
        S.body.querySelector('[data-act="own"]').onclick = function () {
          var lb = S.body.querySelector("#ow-l").value.trim(), pr = parseFloat(S.body.querySelector("#ow-p").value);
          if (!lb || !(pr > 1)) { toast("Enter the leg and a price above 1"); return; }
          add({ id: "own|" + lb.toLowerCase(), label: lb, price: pr, game: S.body.querySelector("#ow-g").value.trim() });
          S.slipView();
        };
      };
      S.slipView();
    });
  }

  function bookSelect(id, def) {
    var o = (cfg.books || []).map(function (b) { return '<option value="' + esc(b.code) + '"' + (b.code === def ? " selected" : "") + ">" + esc(b.name) + "</option>"; }).join("");
    return '<select id="' + id + '">' + (o || '<option value="sb">Sportsbet</option><option value="pb">PointsBet</option>') + "</select>";
  }
  function bookName(code) { var b = (cfg.books || []).filter(function (x) { return x.code === code; })[0]; return b ? b.name : code; }
  function creditFor(code) { var n = bookName(code).toLowerCase(), c = cfg.credit || {}; return c[n] || 0; }

  function recordSheet(a) {
    readCfg();
    if (!a.length) return;
    var z = analyse(a), R = { bk: ((cfg.books || [])[0] || {}).code || "sb" };
    openSheet("Record as my bet", "", function (S) {
      var h = '<p class="say">' + esc(label(a)) + '</p><label>Bookmaker' + bookSelect("rc-bk", R.bk) + '</label><div class="sh-kv"><span>Stake</span><span></span></div><div class="sh-chips" id="rc-chips">' +
        [5, 10, 20, 50].map(function (v) { return '<button type="button" class="sh-chip' + (v === 10 ? " on" : "") + '" data-s="' + v + '">$' + v + "</button>"; }).join("") + '</div>' +
        '<label>Custom stake $<input id="rc-stake" inputmode="decimal" value="10.00"></label><label>Price got $<input id="rc-price" inputmode="decimal" value="' + z.price.toFixed(2) + '"></label>' +
        '<label class="ch-mode"><input type="checkbox" id="rc-bonus"> Staked with a bonus bet <small id="rc-cr"></small></label><label>Bonus if it wins $<input id="rc-bw" inputmode="decimal" placeholder="e.g. Jet Boost 2"></label>' +
        '<button type="button" class="sh-btn pri" id="rc-go">Save bet</button>';
      S.render(h);
      var q = function (s) { return S.body.querySelector(s); };
      var cr = function () { var c = creditFor(q("#rc-bk").value); q("#rc-cr").textContent = "· " + bookName(q("#rc-bk").value) + " credit left " + money(c); };
      cr(); q("#rc-bk").onchange = cr;
      q("#rc-chips").onclick = function (e) {
        var b = e.target.closest("[data-s]"); if (!b) return;
        q("#rc-stake").value = (+b.getAttribute("data-s")).toFixed(2);
        q("#rc-chips").querySelectorAll(".sh-chip").forEach(function (c) { c.classList.toggle("on", c === b); });
      };
      q("#rc-stake").oninput = function () { q("#rc-chips").querySelectorAll(".sh-chip").forEach(function (c) { c.classList.remove("on"); }); };
      q("#rc-go").onclick = function () {
        var stake = parseFloat(q("#rc-stake").value), price = parseFloat(q("#rc-price").value);
        if (!(stake > 0) || !(price > 1)) { toast("Enter a stake and a price"); return; }
        var tip = a.map(function (l) { return l.startsAt || ""; }).sort().pop() || "";
        var u = url({ sport: pageSport(), nbsport: z.sport, tab: cfg.tab || "", ch: "bet", nbs: stake.toFixed(2), nbp: price.toFixed(2), nbag: q("#rc-bk").value, nbl: label(a), nbtip: tip, nbbonus: q("#rc-bonus").checked ? "1" : "", nbbw: q("#rc-bw").value, op: cfg.op || "" });
        clear();
        window.location.assign(u);
      };
    });
  }

  function challengeSheet(a) {
    readCfg();
    if (!a.length) return;
    var z = analyse(a), sp = pageSport();
    var list = (cfg.challenges || []).filter(function (c) { return sp === "home" || c.scope === "all" || c.scope === sp; });
    openSheet("Use in a challenge", "", function (S) {
      var pick = null, book = ((cfg.books || [])[0] || {}).code || "sb";
      try { var f = localStorage.getItem(KEY + "-for"); if (f && list.some(function (c) { return c.id === f; })) pick = f; } catch (x) { /* storage off */ }
      var draw = function () {
        var h = '<div class="sh-kv"><b>Challenge next leg</b><span>' + money(z.price) + " · " + pct(z.chance) + '</span></div>';
        h += list.length ? list.map(function (c) { return '<button type="button" class="sh-pick' + (pick === c.id ? " on" : "") + '" data-c="' + esc(c.id) + '">' + esc(c.name) + '<small>Stage ' + (c.stage + 1) + " of " + c.stages + " · bank " + money(c.bank) + " · target " + c.x.toFixed(1) + "x</small></button>"; }).join("") : '<p class="say">No running challenge for this sport.</p>';
        var c = list.filter(function (x) { return x.id === pick; })[0];
        if (c) {
          var fit = z.price >= c.x ? "sh-good" : "";
          h += '<div class="sh-card"><div class="sh-kv"><span>Price vs target</span><b class="' + fit + '">' + z.price.toFixed(2) + "x vs " + c.x.toFixed(1) + 'x</b></div><div class="sh-kv"><span>Chance</span><b>' + pct(z.chance) + (z.linked.length ? " (approx)" : "") + '</b></div><div class="sh-kv"><span>Bank to payout</span><b>' + money(c.bank) + " → " + money(c.bank * z.price) + '</b></div>' +
            '<label>At' + bookSelect("ch-bk", book) + '</label><button type="button" class="sh-btn pri" id="ch-place">Place · ' + money(c.bank) + "</button></div>";
        }
        h += '<button type="button" class="sh-btn" data-plan2>New challenge</button>';
        S.render(h);
        S.body.querySelectorAll("[data-c]").forEach(function (b) { b.onclick = function () { pick = b.getAttribute("data-c"); draw(); }; });
        S.body.querySelector("[data-plan2]").onclick = function () { planSheet(); };
        var pl = S.body.querySelector("#ch-place");
        if (pl) {
          S.body.querySelector("#ch-bk").onchange = function (e) { book = e.target.value; };
          pl.onclick = function () {
            var tip = a.map(function (l) { return l.startsAt || ""; }).sort().pop() || "";
            var u = url({ sport: sp, tab: "challenge", chid: c.id, op: cfg.op || "", ch: "place", chs: c.stage, chp: z.price.toFixed(2), chl: label(a), chag: S.body.querySelector("#ch-bk").value, chtip: tip });
            clear();
            window.location.assign(u);
          };
        }
      };
      draw();
    });
  }

  function melb(iso) { try { return new Date(iso).toLocaleString("en-AU", { weekday: "short", hour: "numeric", minute: "2-digit", timeZone: "Australia/Melbourne" }); } catch (e) { return ""; } }
  // ---------- new challenge planner ----------
  function planSheet() {
    readCfg();
    var sp = pageSport(), scope = sp === "nba" || sp === "nfl" ? sp : "all";
    openSheet("New challenge", "", function (S) {
      var P = { start: "10", goal: "1000", mode: "game", legs: "", n: null }, data = null, timer = null;
      S.render('<label>Name<input id="pl-name" maxlength="40" placeholder="e.g. $10 to $1000"></label><div class="sh-chips"><label style="flex:1">Start $<input id="pl-start" inputmode="decimal" value="10.00"></label><label style="flex:1">Goal $<input id="pl-goal" inputmode="decimal" value="1000.00"></label></div>' +
        '<div class="sh-chips" id="pl-mode"><button type="button" class="sh-chip on" data-m="game">One game</button><button type="button" class="sh-chip" data-m="multi">One leg per game</button></div>' +
        '<div class="sh-kv"><span>Legs per multi</span><span></span></div><div class="sh-chips" id="pl-legs"><button type="button" class="sh-chip on" data-l="">Any</button><button type="button" class="sh-chip" data-l="2">2</button><button type="button" class="sh-chip" data-l="3">3</button><button type="button" class="sh-chip" data-l="4">4</button></div>' +
        '<div class="sh-kv"><span>Chance to finish, by stages</span><span></span></div><div id="pl-chart" class="say">Working it out…</div><div id="pl-card"></div><div id="pl-pick"></div><button type="button" class="sh-btn pri" id="pl-go">Start challenge</button>');
      var q = function (s) { return S.body.querySelector(s); };
      function draw() {
        var r = (data && data.rows) || [], best = data && data.best ? data.best.n : null;
        if (P.n == null && best) P.n = best;
        if (P.n == null && r.length) P.n = 3;
        var mx = Math.max.apply(null, r.map(function (o) { return o.run || 0; }).concat([0.0001]));
        q("#pl-chart").innerHTML = r.length ? '<div class="sh-bars">' + r.map(function (o) { return '<button type="button" data-n="' + o.n + '" class="' + (o.n === P.n ? "on " : "") + (o.n === best ? "best" : "") + '"><i style="height:' + Math.max(2, Math.round(((o.run || 0) / mx) * 64)) + 'px"></i>' + (o.run ? (o.run * 100).toFixed(1) + "%" : "–") + "<br>" + o.n + "</button>"; }).join("") + "</div>" : (data && data.error ? esc(data.error) : "Working it out…");
        var cur = r.filter(function (o) { return o.n === P.n; })[0];
        q("#pl-card").innerHTML = cur ? '<div class="sh-card"><b>' + cur.n + " stages · " + cur.x.toFixed(1) + "x each · " + (cur.typical ? Math.round(cur.typical * 100) + "% a stage" : "no model for this sport yet") + (cur.run ? " · " + (cur.run * 100).toFixed(1) + "% to finish" : "") + "</b>" + (cur.n === best ? '<small class="sh-good"> best</small>' : "") + "</div>" : "";
        var pk = data && data.pick;
        q("#pl-pick").innerHTML = pk ? '<div class="sh-card"><small>Stage 1 best pick for ' + (data.pick_n || P.n) + " stages" + (pk.game ? " · " + esc(pk.game) : "") + "</small>" + pk.legs.map(function (l) { return '<div class="sh-kv"><span>' + esc(l.label) + (P.mode === "multi" && l.game ? '<br><small>' + esc(l.game) + (l.startsAt ? " · " + esc(melb(l.startsAt)) : "") + "</small>" : "") + "</span><b>" + (+l.price).toFixed(2) + "</b></div>"; }).join("") + '<div class="sh-kv"><span>' + pct(pk.chance) + " chance</span><b>" + (+pk.price).toFixed(2) + "x</b></div></div>" : "";
        q("#pl-chart").querySelectorAll("[data-n]").forEach(function (b) { b.onclick = function () { P.n = +b.getAttribute("data-n"); draw(); fetchPlan(true); }; });
      }
      function fetchPlan(keepN) {
        clearTimeout(timer);
        if (!keepN) P.n = null;
        var pk = q("#pl-pick"); if (pk && data) pk.style.opacity = "0.5";
        timer = setTimeout(function () {
          fetch("/api/challenge/plan?" + ["sport=" + encodeURIComponent(sp), "start=" + encodeURIComponent(P.start), "goal=" + encodeURIComponent(P.goal), "mode=" + P.mode, P.legs ? "legs=" + P.legs : "", P.n ? "n=" + P.n : ""].filter(Boolean).join("&"), { credentials: "same-origin" })
            .then(function (r) { return r.json(); }).then(function (j) { data = j; if (!keepN) P.n = null; var e = q("#pl-pick"); if (e) e.style.opacity = ""; draw(); }).catch(function () { data = { rows: [], error: "Could not work out the plan." }; draw(); });
        }, 250);
      }
      q("#pl-start").oninput = function () { P.start = this.value; fetchPlan(); };
      q("#pl-goal").oninput = function () { P.goal = this.value; fetchPlan(); };
      q("#pl-mode").onclick = function (e) { var b = e.target.closest("[data-m]"); if (!b) return; P.mode = b.getAttribute("data-m"); this.querySelectorAll(".sh-chip").forEach(function (c) { c.classList.toggle("on", c === b); }); fetchPlan(); };
      q("#pl-legs").onclick = function (e) { var b = e.target.closest("[data-l]"); if (!b) return; P.legs = b.getAttribute("data-l"); this.querySelectorAll(".sh-chip").forEach(function (c) { c.classList.toggle("on", c === b); }); fetchPlan(); };
      q("#pl-go").onclick = function () {
        var s = parseFloat(P.start), g = parseFloat(P.goal);
        if (!(s > 0) || !(g > s)) { toast("Goal must be above the start"); return; }
        window.location.assign(url({ sport: sp, tab: "challenge", op: cfg.op || "", ch: "newch", chscope: scope, chname: q("#pl-name").value, chstart: s.toFixed(2), chgoal: g.toFixed(2), chn: P.n || 3, chlegs: P.legs, chmode: P.mode, chkeep: "1" }));
      };
      fetchPlan();
    });
  }
  window.AzSlip = { add: add, remove: remove, toggle: toggle, clear: clear, legs: load, analyse: analyse, open: slipSheet, plan: planSheet };

  sync(); autoOpen();
  // the page swaps its own content in place (liveSwap): re-mark the ticks after it
  var mainEl = document.getElementById("main"), mt = null;
  if (mainEl && window.MutationObserver) new MutationObserver(function () { clearTimeout(mt); mt = setTimeout(function () { sync(); autoOpen(); }, 60); }).observe(mainEl, { childList: true, subtree: true });
  window.addEventListener("storage", function (e) { if (e.key === KEY) sync(); });
})();
