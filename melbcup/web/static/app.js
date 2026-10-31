// Live refresh in place (keeps scroll, open details and the race strip), a remembered budget,
// and a race number that opens the race it jumps to.
(function () {
  "use strict";

  var KEY = "melbcup.budget";

  function storedBudget() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }

  function remember(value) {
    try {
      if (value) localStorage.setItem(KEY, value); else localStorage.removeItem(KEY);
    } catch (e) { /* private mode: the URL still carries it */ }
  }

  var url = new URL(window.location.href);
  var fromUrl = url.searchParams.get("budget");
  if (fromUrl !== null) {
    remember(fromUrl.trim());
  } else if (storedBudget()) {
    url.searchParams.set("budget", storedBudget());
    window.location.replace(url.toString());
    return;
  }

  var main = document.getElementById("main");
  if (!main) return;
  var seconds = parseInt(main.getAttribute("data-refresh"), 10);

  function openTarget(id) {
    var el = id && document.getElementById(id.replace(/^#/, ""));
    if (el && el.tagName === "DETAILS") el.open = true;
  }
  main.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest(".racenav a[href^='#']");
    if (a) openTarget(a.getAttribute("href"));
  });
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

  function strip() { return main.querySelector(".racenav"); }

  function centreStrip(left) {
    var nav = strip();
    if (!nav) return;
    if (left !== undefined) { nav.scrollLeft = left; return; }
    var a = nav.querySelector("a.on, a.next");
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
        var y = window.scrollY;
        var nav = strip();
        var x = nav ? nav.scrollLeft : undefined;
        main.innerHTML = fresh.innerHTML;
        centreStrip(x);
        main.querySelectorAll("details").forEach(function (d, i) { if (open[i]) d.open = true; });
        window.scrollTo(0, y);
      })
      .catch(function () { /* keep showing the last good page */ });
  }

  setInterval(refresh, seconds * 1000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
})();
