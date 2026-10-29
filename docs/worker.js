// Runs the MELBCUP Python package in Pyodide, off the page's main thread. Synchronous
// XMLHttpRequest is allowed here, which is how the Python code calls PuntersEdge and FormFav.
importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js");

let app = null;

// A card load's requests, six at a time; Python caches the replies, then runs the load from the
// cache (the load itself makes its calls one at a time). Arguments arrive as Python proxies,
// which are only valid until the first await, so they are copied first.
async function fetchMany(urls, headers, label) {
  urls = urls.toJs ? urls.toJs() : urls;
  headers = headers.toJs ? headers.toJs({ dict_converter: Object.fromEntries }) : headers;
  const out = new Array(urls.length);
  let next = 0, done = 0;
  async function lane() {
    while (next < urls.length) {
      const i = next++;
      try {
        const res = await fetch(urls[i], { headers });
        out[i] = [res.status, await res.text()];
      } catch (err) {
        out[i] = [0, ""];
      }
      done += 1;
      postMessage({ type: "progress", text: "Fetching " + label + " (" + done + " of " + urls.length + ")" });
    }
  }
  await Promise.all(Array.from({ length: Math.min(6, urls.length) }, lane));
  return out;
}

async function boot(msg) {
  postMessage({ type: "progress", text: "Starting Python…" });
  const py = await loadPyodide();
  postMessage({ type: "progress", text: "Loading templates and time zones…" });
  await py.loadPackage(["jinja2", "tzdata"]);
  const manifest = await (await fetch("py/manifest.json", { cache: "no-cache" })).json();
  postMessage({ type: "progress", text: "Loading the model…" });
  await Promise.all(manifest.files.map(async (file) => {
    const res = await fetch("py/" + file + "?v=" + manifest.build);
    if (!res.ok) throw new Error("Could not load " + file + " (" + res.status + ")");
    const path = "/home/pyodide/" + file;
    py.FS.mkdirTree(path.substring(0, path.lastIndexOf("/")));
    py.FS.writeFile(path, await res.text());
  }));
  py.runPython("import sys; sys.path.insert(0, '/home/pyodide')");
  const browser = py.pyimport("melbcup.browser");
  postMessage({ type: "progress", text: "Checking your PuntersEdge balance…" });
  let calls = 0;
  const progress = (what) => {
    calls += 1;
    postMessage({ type: "progress", text: "Fetching " + what + " (" + calls + ")" });
  };
  browser.init.callKwargs(msg.pe, msg.ff, msg.saved || null, progress, { fetch_many: fetchMany });
  return { browser, build: manifest.build };
}

let booting = null;

self.onmessage = async (event) => {
  const msg = event.data;
  try {
    if (msg.type === "init") {
      booting = boot(msg);
      app = await booting;
      postMessage({ id: msg.id, ok: true, build: app.build });
      return;
    }
    if (!app) app = await booting;
    const b = app.browser;
    let result;
    if (msg.type === "render") result = b.render(msg.url);
    else if (msg.type === "act") {
      if (msg.url.startsWith("/actions/load")) await b.warm(true);
      result = b.act(msg.url);
    } else if (msg.type === "tick") {
      await b.warm(false);
      result = b.tick();
    }
    else if (msg.type === "save") result = b.save();
    postMessage({ id: msg.id, ok: true, result });
  } catch (err) {
    postMessage({ id: msg.id, ok: false, error: String(err && err.message ? err.message : err) });
  }
};
