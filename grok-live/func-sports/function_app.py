# ruff: noqa: E501
"""Posted sports board. One HTTP page, no datastore, no odds feed.

The model lives in melbcup.sport_board. This file only renders it.
"""

from __future__ import annotations

import sys
from html import escape
from pathlib import Path

import azure.functions as func

_HERE = Path(__file__).resolve().parent
for _candidate in (_HERE, _HERE.parent, _HERE.parent.parent):
    if (_candidate / "melbcup").is_dir():
        sys.path.insert(0, str(_candidate))
        break

from melbcup.sport_board import SPORTS, ranked  # noqa: E402

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


def _page() -> str:
    rows = ranked("football")
    hero, rest = rows[0], rows[1:]
    others = "".join(
        f"<li><b>{escape(name)}</b><span>History not in yet</span></li>"
        for code, name in SPORTS
        if code != "football"
    )
    more = "".join(
        "<li><b>{pct}%</b><span>{line}</span></li>".format(
            pct=row["pct"], line=escape(row["line"])
        )
        for row in rest
    )
    return f"""<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sports multis</title>
<style>
  :root {{ --ground:#0A090E; --ink:#EEEAF8; --muted:#9D94B8; --rule:#2A2438; --brand:#A88BFF; --good:#4ED19A; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--ground); color:var(--ink);
    font:16px/1.4 "Segoe UI",system-ui,sans-serif; }}
  main {{ max-width:28rem; margin:0 auto; padding:28px 20px 48px; }}
  p.k {{ margin:0; color:var(--muted); font-size:11px; font-weight:700; letter-spacing:.14em; text-transform:uppercase; }}
  h1 {{ margin:4px 0 0; font-size:34px; letter-spacing:-.03em; }}
  .chance {{ margin:18px 0 0; font-size:84px; line-height:.85; letter-spacing:-.05em; font-weight:800; color:var(--brand); }}
  .chance small {{ font-size:.42em; }}
  .lead {{ margin:12px 0 0; font-size:18px; font-weight:700; }}
  .meta {{ margin:6px 0 0; color:var(--muted); font-size:14px; }}
  ol, ul {{ list-style:none; margin:22px 0 0; padding:0; }}
  li {{ display:flex; justify-content:space-between; gap:12px; padding:12px 0; border-top:1px solid var(--rule); }}
  li span {{ color:var(--muted); text-align:right; }}
  h2 {{ margin:28px 0 0; font-size:13px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); }}
</style>
</head>
<body>
<main>
  <p class="k">Best chance at $2 or more</p>
  <h1>Football</h1>
  <p class="chance">{hero["pct"]}<small>%</small></p>
  <p class="lead">{escape(hero["line"])}</p>
  <p class="meta">{hero["hit"] * 100:.1f}% of {hero["bets"]} bets. Lower bound {hero["low"] * 100:.1f}%.</p>
  <p class="meta">{escape(hero["edge"])}</p>
  <h2>Also clears $2</h2>
  <ol>{more}</ol>
  <h2>Other sports</h2>
  <ul>{others}</ul>
  <p class="meta">No fixture names. A sport stays blank until its scan has been run. Stake only what you can lose.</p>
</main>
</body>
</html>"""


@app.route(route="sports", methods=["GET"])
def sports(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(_page(), mimetype="text/html")
