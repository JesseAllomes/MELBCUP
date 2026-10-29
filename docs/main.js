// MELBCUP in the browser: routes taps and forms to the Python app in worker.js, keeps the API
// keys, the day budget and the loaded card on this phone, and redraws the page.
(function () {
  "use strict";

  const KEYS = "melbcup.keys";
  const STATE = "melbcup.state";
  const BUDGET = "melbcup.budget";
  const ROUTE = "melbcup.route";

  const $ = (id) => document.getElementById(id);
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { if (v === null || v === "") localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* full or blocked */ } },
  };

  let worker = null;
  let nextId = 1;
  const pending = new Map();
  let busy = false;
  let ticking = false;
  let queued = null;  // a page tapped while the app was busy: shown when it is free
  let route = store.get(ROUTE) || "/";

  function send(type, data) {
    const id = nextId++;
    worker.postMessage(Object.assign({ id, type }, data || {}));
    return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
  }

  function setBusy(text) {
    busy = Boolean(text);
    $("busy").hidden = !busy;
    if (text) $("busy-text").textContent = text;
    if (!busy && queued) {
      const next = queued;
      queued = null;
      show(next, false);
    }
  }

  // The app does one thing at a time: a page tapped during a load opens as soon as it is done.
  function go(href) {
    if (!busy) { show(href, false); return; }
    queued = href;
    $("busy-text").textContent = "Opening that page once this finishes…";
    $("busy").hidden = false;
  }

  function withBudget(url) {
    const budget = store.get(BUDGET);
    const u = new URL(url, "https://x.invalid");
    if (budget && !u.searchParams.has("budget") && !u.pathname.startsWith("/actions/")) {
      u.searchParams.set("budget", budget);
    }
    return u.pathname + u.search;
  }

  function paint(html, keepScroll) {
    const doc = new DOMParser().parseFromString(html, "text/html");
    doc.querySelectorAll("script, link").forEach((n) => n.remove());
    const y = window.scrollY;
    const open = Array.from($("app").querySelectorAll("details")).map((d) => d.open);
    $("app").replaceChildren(...Array.from(doc.body.childNodes).map((n) => document.importNode(n, true)));
    if (keepScroll) {
      $("app").querySelectorAll("details").forEach((d, i) => { if (open[i]) d.open = true; });
      window.scrollTo(0, y);
    } else {
      window.scrollTo(0, 0);
    }
  }

  async function show(url, keepScroll) {
    route = withBudget(url);
    store.set(ROUTE, route);
    try {
      paint(await send("render", { url: route }), keepScroll);
    } catch (err) {
      showError(err);
    }
  }

  async function act(url) {
    setBusy("Working…");
    try {
      const next = await send("act", { url });
      store.set(STATE, await send("save"));
      await show(next, false);
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  }

  function showError(err) {
    const box = $("error");
    box.textContent = "Something went wrong: " + (err && err.message ? err.message : err) +
      ". Reload the page to try again.";
    box.hidden = false;
  }

  // --- taps and forms ------------------------------------------------------------------------

  $("app").addEventListener("click", (e) => {
    const a = e.target.closest("a");
    if (!a) return;
    const href = a.getAttribute("href") || "";
    if (href === "#keys") { e.preventDefault(); showKeys(); return; }
    if (href.startsWith("/")) { e.preventDefault(); go(href); }
  });

  $("app").addEventListener("submit", (e) => {
    const form = e.target;
    const action = form.getAttribute("action") || "/";
    e.preventDefault();
    if ((form.getAttribute("method") || "get").toLowerCase() === "post") {
      if (!busy) act(action);  // buttons spend credits: never queued behind another job
      return;
    }
    const params = new URLSearchParams(new FormData(form));
    if (params.has("budget")) {
      store.set(BUDGET, params.get("budget").trim());
      if (!params.get("budget").trim()) params.delete("budget");
    }
    const qs = params.toString();
    go(action + (qs ? (action.includes("?") ? "&" : "?") + qs : ""));
  });

  // --- API keys ------------------------------------------------------------------------------

  function readKeys() {
    try { return JSON.parse(store.get(KEYS) || "{}"); } catch (e) { return {}; }
  }

  function showKeys() {
    const keys = readKeys();
    $("pe-key").value = keys.pe || "";
    $("ff-key").value = keys.ff || "";
    $("keys").hidden = false;
    $("app").hidden = true;
    $("boot").hidden = true;
  }

  $("keys-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const pe = $("pe-key").value.trim();
    if (!pe) { $("keys-note").textContent = "The PuntersEdge key is required: it supplies the field and the prices."; return; }
    store.set(KEYS, JSON.stringify({ pe, ff: $("ff-key").value.trim() }));
    location.reload();
  });

  // --- start ---------------------------------------------------------------------------------

  async function start() {
    const keys = readKeys();
    if (!keys.pe) { showKeys(); return; }
    worker = new Worker("worker.js");
    worker.onmessage = (event) => {
      const msg = event.data;
      if (msg.type === "progress") {
        $("boot-text").textContent = msg.text;
        $("busy-text").textContent = (ticking ? "Updating: " : "") + msg.text;
        if (ticking) $("busy").hidden = false;
        if (queued) $("busy-text").textContent += " · then opening your page";
        return;
      }
      const p = pending.get(msg.id);
      if (!p) return;
      pending.delete(msg.id);
      if (msg.ok) p.resolve(msg.result); else p.reject(new Error(msg.error));
    };
    worker.onerror = (e) => showError(e.message || "the app could not start");
    try {
      await send("init", { pe: keys.pe, ff: keys.ff || "", saved: store.get(STATE) });
    } catch (err) {
      // A saved card from an older build can stop start-up: drop it once and retry.
      if (store.get(STATE)) { store.set(STATE, null); location.reload(); return; }
      $("boot-text").textContent = "Could not start: " + err.message;
      return;
    }
    $("boot").hidden = true;
    $("app").hidden = false;
    await show(route, false);

    // Redraw every minute (countdowns; costs nothing) and let Auto mode do its rounds.
    setInterval(() => {
      if (!busy && !document.hidden && !route.startsWith("/meetings")) show(route, true);
    }, 60000);
    const round = async () => {
      if (busy || document.hidden) return;
      busy = ticking = true;
      try {
        if (await send("tick")) {
          store.set(STATE, await send("save"));
          if (!route.startsWith("/meetings")) await show(route, true);
        }
      } catch (err) { /* the next round tries again */ }
      ticking = false;
      setBusy(null);
    };
    round();  // straight away: load the card, prices or results if they are due
    setInterval(round, 15000);
  }

  start();
})();
