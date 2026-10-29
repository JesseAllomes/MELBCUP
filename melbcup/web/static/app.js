// Live refresh in place (keeps scroll and open details) and a remembered budget.
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
  var seconds = parseInt(main.getAttribute("data-refresh"), 10) || 60;

  function openDetails() {
    return Array.prototype.map.call(main.querySelectorAll("details"), function (d) { return d.open; });
  }

  function refresh() {
    if (document.hidden) return;
    fetch(window.location.href, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.text() : Promise.reject(r.status); })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, "text/html");
        var fresh = doc.getElementById("main");
        if (!fresh) return;
        var open = openDetails();
        var y = window.scrollY;
        main.innerHTML = fresh.innerHTML;
        main.querySelectorAll("details").forEach(function (d, i) { if (open[i]) d.open = true; });
        window.scrollTo(0, y);
      })
      .catch(function () { /* keep showing the last good page */ });
  }

  setInterval(refresh, seconds * 1000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
})();
