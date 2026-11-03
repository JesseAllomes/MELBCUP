// Live refresh in place (keeps scroll, open details, the field's "Show all" and the race strip).
// The day amounts and placed ticks live in cookies (see base.html).
(function () {
  "use strict";

  var main = document.getElementById("main");
  if (!main) return;
  var seconds = parseInt(main.getAttribute("data-refresh"), 10);

  function openTarget(id) {
    var el = id && document.getElementById(id.replace(/^#/, ""));
    if (el && el.tagName === "DETAILS") el.open = true;
  }
  openTarget(window.location.hash);
  centreStrip();
  if (!(seconds > 0)) return; // pages with forms being filled in opt out

  function openDetails() {
    return Array.prototype.map.call(main.querySelectorAll("details"), function (d) { return d.open; });
  }

  function typing() {
    var a = document.activeElement;
    if (a && main.contains(a) && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)) return true;
    return Array.prototype.some.call(main.querySelectorAll("input"), function (i) { return i.value !== i.defaultValue; });
  }

  function strip() { return main.querySelector(".strip"); }

  function centreStrip(left) {
    var nav = strip();
    if (!nav) return;
    if (left !== undefined) { nav.scrollLeft = left; return; }
    var a = nav.querySelector("a.on") || nav.querySelector("a.next");
    if (a) nav.scrollLeft = a.offsetLeft - (nav.clientWidth - a.offsetWidth) / 2;
  }

  function refresh() {
    if (document.hidden || typing()) return;
    fetch(window.location.href, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.text() : Promise.reject(r.status); })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, "text/html");
        var fresh = doc.getElementById("main");
        if (!fresh) return;
        if (typing()) return;
        var open = openDetails();
        var shown = Array.prototype.map.call(main.querySelectorAll("button[data-more]"), function (b) {
          return b.getAttribute("aria-expanded") === "true" ? b : null;
        }).filter(Boolean).map(function (b) { return b.getAttribute("data-more"); });
        var y = window.scrollY;
        var nav = strip();
        var x = nav ? nav.scrollLeft : undefined;
        main.innerHTML = fresh.innerHTML;
        centreStrip(x);
        main.querySelectorAll("details").forEach(function (d, i) { if (open[i]) d.open = true; });
        shown.forEach(function (id) {
          var b = main.querySelector('button[data-more="' + id + '"]');
          if (b) b.click();
        });
        window.scrollTo(0, y);
        document.dispatchEvent(new CustomEvent("melb:data", { detail: doc }));
      })
      .catch(function () { /* keep showing the last good page */ });
  }

  setInterval(refresh, seconds * 1000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
})();

// "R2 jumps in 4:12" strip: counts down to the next race, turns amber and says BET NOW at 3:00,
// then (once per race) vibrates, beeps, notifies and reloads so the latest picks show.
// ?now=<ISO time> fakes the clock for testing.
(function () {
  "use strict";
  var bar = document.getElementById("alertbar");
  if (!bar) return;
  var msg = bar.querySelector(".ab-msg"), btn = bar.querySelector(".ab-alerts");
  var ALERT_AT = 180; // seconds
  var offset = 0;
  try {
    var fake = new URLSearchParams(window.location.search).get("now");
    if (fake && !isNaN(Date.parse(fake))) offset = Date.parse(fake) - Date.now();
  } catch (e) { /* real clock */ }
  var races = [];

  function load(doc) {
    var el = (doc || document).getElementById("alert-data");
    try { races = el ? JSON.parse(el.textContent) : []; } catch (e) { races = []; }
    races.forEach(function (r) { r.at = Date.parse(r.t); });
  }
  function store(op, key, val) {
    try { return op === "get" ? window.sessionStorage.getItem(key) : window.sessionStorage.setItem(key, val); } catch (e) { return null; }
  }
  function clock(secs) {
    var h = Math.floor(secs / 3600), m = Math.floor(secs % 3600 / 60), s = secs % 60;
    return (h ? h + ":" + (m < 10 ? "0" : "") + m : m) + ":" + (s < 10 ? "0" : "") + s;
  }
  function beep() {
    try {
      var C = window.AudioContext || window.webkitAudioContext;
      if (!C) return;
      var ctx = new C(), o = ctx.createOscillator(), g = ctx.createGain();
      o.type = "sine"; o.frequency.value = 880; g.gain.value = 0.15;
      o.connect(g); g.connect(ctx.destination); o.start(); o.stop(ctx.currentTime + 0.35);
    } catch (e) { /* no sound */ }
  }
  function fire(r) {
    var key = "betnow:" + r.t + ":" + (r.label || r.n);
    if (store("get", key)) return;
    store("set", key, "1");
    try { if (navigator.vibrate) navigator.vibrate([200, 100, 200]); } catch (e) { /* no vibration */ }
    beep();
    try {
      if ("Notification" in window && Notification.permission === "granted") {
        new Notification(r.label ? r.label + (r.alert ? " in " + Math.round(r.alert / 60) + " min" : " now") : "Bet now: R" + r.n + " jumps in 3 min");
      }
    } catch (e) { /* no notifications */ }
    var rk = "betnow-reload:" + r.t + ":" + (r.label || r.n);
    if (!store("get", rk)) { store("set", rk, "1"); window.location.reload(); }
  }
  function tick() {
    var now = Date.now() + offset, next = null;
    for (var i = 0; i < races.length; i++) { if (races[i].at > now) { next = races[i]; break; } }
    if (!next) { bar.hidden = true; return; }
    bar.hidden = false;
    var at = next.alert != null ? next.alert : ALERT_AT;
    var secs = Math.ceil((next.at - now) / 1000), hot = secs <= at;
    var what = next.label || ("R" + next.n + " jumps");
    msg.textContent = hot && !next.label ? "BET NOW · R" + next.n + " in " + clock(secs) : what + " in " + clock(secs);
    msg.setAttribute("href", next.href || "/race/" + next.n);
    bar.classList.toggle("hot", hot);
    if (hot) fire(next);
  }
  function permission() {
    btn.hidden = !("Notification" in window && Notification.permission === "default");
  }
  btn.addEventListener("click", function () {
    try { Notification.requestPermission().then(permission, permission); } catch (e) { permission(); }
  });
  document.addEventListener("melb:data", function (e) { load(e.detail); tick(); });
  load(); permission(); tick();
  setInterval(tick, 1000);
})();
