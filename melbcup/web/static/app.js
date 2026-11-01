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
      })
      .catch(function () { /* keep showing the last good page */ });
  }

  setInterval(refresh, seconds * 1000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
})();
