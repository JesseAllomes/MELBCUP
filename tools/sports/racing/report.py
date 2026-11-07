# ruff: noqa: E501
"""Render the markdown tables of research/sports/racing.md from OUT/holdout_results.json."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import OUT  # noqa: E402


def g(x, d=4):
    return f"{x:+.{d}f}"


def gain_row(name, x):
    return (
        f"| {name} | {x['races']:,} | {x['base_ll']:.4f} | {x['new_ll']:.4f} | {g(x['gain'])} "
        f"({g(x['lo'])} to {g(x['hi'])}) | {'yes' if x['clears_95'] else 'no'} |"
    )


def main() -> None:
    r = json.load(open(os.path.join(OUT, "holdout_results.json")))
    o = []
    o.append(
        "### Log loss per race by price source (hold-out 2025-26, each on its own complete races)\n"
    )
    o.append(
        "| Source | Overround | Races | Proportional | Power (alpha from train) | Gain of power (95%) |"
    )
    o.append("|---|---|---|---|---|---|")
    for k, v in r["sources"].items():
        p = v["power_vs_proportional"]
        o.append(
            f"| {k} | {v['overround_mean']:.3f} | {v['holdout_races']:,} | {v['logloss_proportional']:.4f} "
            f"| {v['logloss_power']:.4f} (a={v['alpha_train']:.3f}) | {g(p['gain'])} ({g(p['lo'])} to {g(p['hi'])}) |"
        )
    o.append(
        "\n### Sources on identical races (Sportsbet, Ladbrokes, tote, Betfair BSP all present)\n"
    )
    o.append("| Source | Races | Log loss (proportional) | Gain vs Sportsbet (95%) |")
    o.append("|---|---|---|---|")
    for k, v in r["identical_races"].items():
        gg = v.get("vs_sb_gain")
        o.append(
            f"| {k} | {v['races']:,} | {v['logloss']:.4f} | "
            + (f"{g(gg['gain'])} ({g(gg['lo'])} to {g(gg['hi'])})" if gg else "baseline")
            + " |"
        )
    fm = r["feature_model"]
    o.append("\n### Model layers on Sportsbet prices (hold-out; positive gain = better)\n")
    o.append("| Comparison | Races | Base LL | New LL | Gain (95%) | Clears 95% |")
    o.append("|---|---|---|---|---|---|")
    o.append(gain_row("power vs proportional", fm["power_vs_proportional"]))
    o.append(gain_row("features vs proportional", fm["vs_proportional"]))
    o.append(gain_row("features vs power", fm["vs_power"]))
    f = r["forward_2026_27"]
    o.append(gain_row("FORWARD 2026-27: power vs proportional", f["power_vs_proportional"]))
    o.append(gain_row("FORWARD 2026-27: features vs proportional", f["feature_vs_proportional"]))
    o.append(
        "\nFeature coefficients (standardised): "
        + ", ".join(f"{k} {v:+.3f}" for k, v in fm["beta"].items())
    )
    o.append("\n### Calibration, Sportsbet power-corrected, hold-out\n")
    o.append("| Band | n | Said | Got | 95% range of got | Outside |")
    o.append("|---|---|---|---|---|---|")
    for x in r["calibration"]["power_overall"]:
        o.append(
            f"| {x['band']} | {x['n']:,} | {x['said']:.3f} | {x['got']:.3f} | {x['lo']:.3f}-{x['hi']:.3f} | {'**yes**' if x['outside'] else 'no'} |"
        )
    o.append("\n### Calibration by market type: cells outside their 95% range (n >= 300)\n")
    s = r["calibration_by_type_summary"]
    o.append(
        f"{s['cells_n>=300']} cells tested, {s['outside_95']} outside the range; chance alone gives about {s['expected_outside_by_chance']}.\n"
    )
    o.append("| Type | Group | Band | n | Said | Got | 95% range |")
    o.append("|---|---|---|---|---|---|---|")
    for t, rows in r["calibration_by_type"].items():
        for x in rows:
            if x["outside"] and x["n"] >= 300:
                o.append(
                    f"| {t} | {x['by']} | {x['band']} | {x['n']:,} | {x['said']:.3f} | {x['got']:.3f} | {x['lo']:.3f}-{x['hi']:.3f} |"
                )
    o.append("\n### Place market (fields of 8+, top 3), implied chance normalised to 3 places\n")
    o.append("| Book | Band | n | Said | Got | 95% range |")
    o.append("|---|---|---|---|---|---|")
    for bk, v in r["place"].items():
        for x in v["bands"]:
            o.append(
                f"| {bk} (overround {v['overround_mean']:.2f}) | {x['band']} | {x['n']:,} | {x['said']:.3f} | {x['got']:.3f} | {x['lo']:.3f}-{x['hi']:.3f} |"
            )
    o.append("\n### ROI at ONE book (Sportsbet price), flat $1, hold-out\n")
    o.append("| Rule | Bets | ROI | 95% | 99% |")
    o.append("|---|---|---|---|---|")

    def roi_row(name, x):
        if not x.get("bets"):
            return f"| {name} | 0 | | | |"
        return (
            f"| {name} | {x['bets']:,} | {x['roi'] * 100:+.1f}% | {x['lo'] * 100:+.1f} to {x['hi'] * 100:+.1f} "
            f"| {x['lo99'] * 100:+.1f} to {x['hi99'] * 100:+.1f} |"
        )

    ro = r["roi_sportsbet"]
    o.append(roi_row("back every runner", ro["all_runners"]))
    for b, x in ro["by_band"].items():
        o.append(roi_row(f"band {b} (fair chance)", x))
    for k, x in ro.items():
        if k.startswith("value"):
            o.append(roi_row(k.replace("_", " "), x))
    o.append("\nForward 2026-27 (rules fixed beforehand):\n")
    o.append("| Rule | Bets | ROI | 95% | 99% |")
    o.append("|---|---|---|---|---|")
    for k, x in r["roi_forward_2026_27"].items():
        o.append(roi_row(k.replace("_", " "), x))
    o.append(
        "\nBacking every runner at each book (shows the margin each one charges): "
        + ", ".join(f"{k} {x['roi'] * 100:+.1f}%" for k, x in r["roi_all_runners_by_book"].items())
    )
    bf = r["betfair_file"]
    o.append("\n### Betfair file, longer history (train 2019-20 to 2024-25, hold-out 2025-26)\n")
    o.append("| Price | Overround | Races | Proportional | Power | Gain of power (95%) |")
    o.append("|---|---|---|---|---|---|")
    for k in ("bsp", "preplay_wavg"):
        v = bf[k]
        p = v["power_vs_proportional"]
        o.append(
            f"| {k} | {v['overround_mean']:.3f} | {v['holdout_races']:,} | {v['logloss_proportional']:.4f} | {v['logloss_power']:.4f} (a={v['alpha_train']:.3f}) | {g(p['gain'], 5)} ({g(p['lo'], 5)} to {g(p['hi'], 5)}) |"
        )
    print("\n".join(o))


if __name__ == "__main__":
    main()
