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
  if (!card || !("serviceWorker" in navigator) || !("PushManager" in window)) return;
  var on = document.getElementById("push-on"), test = document.getElementById("push-test");
  var state = document.getElementById("push-state");
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
    var ok = get("push_id") && Notification.permission === "granted";
    state.textContent = ok ? "on ✓" : (Notification.permission === "denied" ? "blocked in Chrome settings" : "off");
    on.hidden = !!ok || Notification.permission === "denied";
    test.hidden = !ok;
  }
  on.addEventListener("click", function () {
    on.disabled = true;
    navigator.serviceWorker.register("/sw.js", { scope: "/" })
      .then(function () { return Notification.requestPermission(); })
      .then(function (p) {
        if (p !== "granted") throw new Error("permission " + p);
        return navigator.serviceWorker.ready;
      })
      .then(function (reg) { return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key(card.dataset.key) }); })
      .then(function (sub) { return post("/api/push/subscribe", { subscription: sub.toJSON() }); })
      .then(function (r) { set("push_id", r.id); return reminders(); })
      .catch(function (e) { state.textContent = "could not turn on (" + e.message + ")"; })
      .then(function () { on.disabled = false; show(); });
  });
  test.addEventListener("click", function () {
    post("/api/push/test", { id: get("push_id") })
      .then(function () { state.textContent = "test on its way (within 10 min, 7am-7pm)"; })
      .catch(function () { state.textContent = "test failed: turn alerts on again"; });
  });
  if (get("push_id")) navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {});
  show();
  reminders();
})();
