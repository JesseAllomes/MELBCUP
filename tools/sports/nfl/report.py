"""Render holdout_results.json into markdown tables (used for research/sports/nfl.md)."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def f(x, nd=4):
    return "-" if x is None else f"{x:.{nd}f}"


def render(res: dict) -> str:
    o = []
    secs = (("dev", "Dev walk-forward 2016-2024"), ("holdout_res", "Sealed hold-out 2025"),
            ("forward_res", "Forward check 2026 (partial season)"))
    for sec, title in secs:
        o += [f"### {title}: log loss, variant vs raw no-vig market", "",
              "| market | variant | n | log loss | diff vs market | 95% range | beats market? |",
              "|---|---|---|---|---|---|---|"]
        for mk, vs in res[sec].items():
            for v, r in vs.items():
                o.append(f"| {mk} | {v} | {r['n']} | {f(r['logloss'])} | {f(r['diff'])} | "
                         f"{f(r['ci95'][0])} to {f(r['ci95'][1])} | "
                         f"{'yes' if r['beats_market'] else 'no'} |")
        o.append("")
    pers = (("holdout_2025", "Hold-out 2025"), ("pooled_2006_2025", "Pooled 2006-2025"))
    for per, title in pers:
        o += [f"### Calibration (said vs got), {title}; * = said outside 95% range of got", "",
              "| market | side | price band (said prob) | n | said | got | 95% range |",
              "|---|---|---|---|---|---|---|"]
        for mk, c in res["calibration"].items():
            for r in c[per]:
                o.append(f"| {mk} | {r['side']} | {r['band']} | {r['n']} | {f(r['said'], 3)} | "
                         f"{f(r['got'], 3)}{'*' if r['outside'] else ''} | "
                         f"{f(r['lo'], 3)} to {f(r['hi'], 3)} |")
        o.append("")
    o += ["### ROI at the single listed price (flat 1 unit, pushes refunded)", "",
          "| market | bet rule | bets | ROI | 95% range |", "|---|---|---|---|---|"]
    for mk, r in res["roi"].items():
        for k, v in r.items():
            if k == "model_edge_variant":
                continue
            ci = "-" if not v["ci95"] else f"{f(v['ci95'][0], 3)} to {f(v['ci95'][1], 3)}"
            o.append(f"| {mk} | {k} | {v['bets']} | {f(v['roi'], 3)} | {ci} |")
    return "\n".join(o) + "\n"


if __name__ == "__main__":
    print(render(json.loads(Path(sys.argv[1]).read_text())))
