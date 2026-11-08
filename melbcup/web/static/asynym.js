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

// Saved copy (owner, 2026-11-04): the service worker keeps every page, so a sleeping server never
// leaves a blank screen. When this page is that saved copy, say so and swap in the fresh one.
(function () {
  "use strict";
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {});
  var at = document.body && document.body.getAttribute("data-saved");
  if (!at) return;
  var pill = document.createElement("button");
  pill.type = "button";
  pill.className = "saved-pill";
  var when = new Date(Number(at)).toLocaleTimeString("en-AU", { hour: "numeric", minute: "2-digit", timeZone: "Australia/Melbourne" });
  pill.textContent = "Saved copy " + when + " · updating…";
  pill.addEventListener("click", function () { location.reload(); });
  document.body.appendChild(pill);
  var touched = false;
  ["click", "touchstart", "keydown", "wheel"].forEach(function (ev) {
    window.addEventListener(ev, function () { touched = true; }, { once: true, passive: true });
  });
  (function poll(n) {
    fetch(location.href, { cache: "no-store", credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        if (!touched) { location.reload(); return; }
        pill.textContent = "Fresh prices ready · tap";
        pill.classList.add("ready");
      })
      .catch(function () { if (n < 20) window.setTimeout(function () { poll(n + 1); }, 3000); });
  })(0);
})();

// Fresh NBA prices on every load (owner, 2026-11-06): the server shows its latest copy at once and
// works out new prices behind it; when they land, reload once (or offer a tap if the page is in use).
// The reload keeps only the tab and agency, so a switch or an action in the address never repeats.
(function () {
  "use strict";
  var el = document.getElementById("nba-priced");
  if (!el) return;
  var mine = Date.parse(el.getAttribute("data-priced") || "") || 0;
  var touched = false;
  ["click", "touchstart", "keydown", "wheel"].forEach(function (ev) {
    window.addEventListener(ev, function () { touched = true; }, { once: true, passive: true });
  });
  function clean() {
    var u = new URL(location.href), keep = new URLSearchParams();
    ["tab", "bk"].forEach(function (k) { if (u.searchParams.get(k)) keep.set(k, u.searchParams.get(k)); });
    return u.pathname + (keep.toString() ? "?" + keep.toString() : "");
  }
  (function poll(n) {
    if (n > 15) return;
    window.setTimeout(function () {
      fetch("/api/nba/stamp", { cache: "no-store", credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          var t = Date.parse(d.priced || "") || 0;
          if (t <= mine) { poll(n + 1); return; }
          if (!touched) { location.replace(clean()); return; }
          var pill = document.createElement("button");
          pill.type = "button"; pill.className = "saved-pill ready"; pill.textContent = "Fresh prices ready · tap";
          pill.addEventListener("click", function () { location.replace(clean()); });
          document.body.appendChild(pill);
        })
        .catch(function () { poll(n + 1); });
    }, 3000);
  })(0);
})();

// Bet now (owner BUILD, 2026-11-07): the multis are searched on the server behind the page. Poll the
// status; show a slim bar while it works and a tap toast when a newer result than this page's lands.
(function () {
  "use strict";
  if (location.pathname !== "/sports") return;
  var root = document.getElementById("bn");
  var mine = root ? root.getAttribute("data-built") || "" : null;
  var bar = null, toast = null, timer = null;
  function barOf() {
    if (bar) return bar;
    bar = document.createElement("div");
    bar.className = "bn-bar"; bar.setAttribute("role", "status");
    bar.innerHTML = '<div class="ut"><b></b><span>shows the last result meanwhile</span></div><div class="bar"><i></i></div>';
    var h = document.querySelector("header") || document.body.firstElementChild;
    if (h && h.parentNode) h.parentNode.insertBefore(bar, h.nextSibling); else document.body.prepend(bar);
    return bar;
  }
  function showToast() {
    if (toast) return;
    toast = document.createElement("button");
    toast.type = "button"; toast.className = "bn-toast";
    toast.innerHTML = '<span class="dot"></span><span>Fresh multis ready</span><span>Tap</span>';
    toast.addEventListener("click", function () { location.reload(); });
    document.body.appendChild(toast);
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
        if (!d.busy && d.built && d.built !== mine) showToast();
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
  var list = document.querySelector(".chs-list");
  if (!list) return;
  function rows() { return list.querySelectorAll(".chs-row"); }
  function lazy(body) {
    if (!body.dataset.url) return;
    fetch(body.dataset.url, { cache: "no-store", credentials: "same-origin" })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        var fresh = new DOMParser().parseFromString(html, "text/html").getElementById("chv9");
        if (!fresh || body.hidden) return;
        var mine = body.querySelector(".chv9");
        if (mine) { mine.innerHTML = fresh.innerHTML; return; }
        var saved = body.querySelector(".chs-saved");
        if (saved) saved.remove();
        body.appendChild(document.importNode(fresh, true));
      })
      .catch(function () {});
  }
  list.addEventListener("click", function (e) {
    var head = e.target.closest(".chs-head");
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
  poll();
  window.setInterval(poll, 30000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) poll(); });
})();
