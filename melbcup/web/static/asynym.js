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
