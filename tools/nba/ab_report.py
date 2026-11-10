"""Picker A/B report (owner, 2026-11-10): v1, v2 and the v3 shadow (weekly refit), token-free.

Reads forward-v2.jsonl (every logged leg and multi, settled by ESPN event; each multi row carries
"picker": "v1"|"v2", each leg row carries chance_v1 / chance_v2) and prints, per version:
said vs got, wins and return per $ of the suggested multis, then the paired difference (v2 - v1)
by slate and target with a bootstrap 95% interval, the leg-level said-vs-got for both versions'
chances, and the drift re-pick events and how they came out.

Usage: python3 tools/nba/ab_report.py forward-v2.jsonl [--repicks challenges.json] [--boot 4000]
Decision rule (fable_review_2026-11-10.md): decide at about 600 same-game game-targets; v2 stays if
the same-game $2 and $3 hit rate, v2 minus v1 paired by game, is positive with the interval clear
of zero; roll back (PICKER=v1) if the interval sits below zero or the leg-level gap closes.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict

DONE = ("won", "lost")


def load(path: str) -> list[dict]:
    with open(path) as f:
        return [json.loads(x) for x in f if x.strip()]


def multis(rows: list[dict]) -> list[dict]:
    """Settled multis, each bet once (the 'latest' copy), with a version tag (untagged = v1)."""
    out = []
    for x in rows:
        if x.get("kind") != "multi" or x.get("result") not in DONE or not x.get("latest", True):
            continue
        out.append(x | {"picker": x.get("picker") or "v1"})
    return out


def ret(x: dict) -> float:
    return (x["price"] if x["result"] == "won" else 0.0) - 1.0


def ci(vals: list[float], boot: int, seed: int = 7) -> tuple[float, float, float]:
    """mean and bootstrap 95% interval over the list (resampling the paired slates)."""
    n = len(vals)
    if not n:
        return 0.0, 0.0, 0.0
    mean = sum(vals) / n
    rng = random.Random(seed)
    ms = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(boot))
    return mean, ms[int(0.025 * boot)], ms[int(0.975 * boot) - 1]


def per_version(ms: list[dict]) -> None:
    print("\nMULTIS per version (settled, each bet once)")
    print(f"{'ver':4}{'n':>6}{'said':>8}{'got':>8}{'wins':>6}{'return/$':>10}")
    for v in ("v1", "v2", "v3"):
        r = [x for x in ms if x["picker"] == v]
        if not r:
            print(f"{v:4}{0:>6}")
            continue
        print(
            f"{v:4}{len(r):>6}{sum(x['chance'] for x in r) / len(r):>8.3f}"
            f"{sum(x['result'] == 'won' for x in r) / len(r):>8.3f}"
            f"{sum(x['result'] == 'won' for x in r):>6}{sum(map(ret, r)) / len(r):>+10.3f}"
        )


def paired(ms: list[dict], boot: int, hi: str = "v2", lo: str = "v1") -> None:
    """One value per (day, agency, kind, target): the version's mean over that slate/target's
    multis; the pair difference is v2 minus v1, over slates where both versions logged."""
    cell: dict = defaultdict(lambda: defaultdict(list))
    for x in ms:
        cell[(x.get("day"), x.get("agency"), x.get("mkind"), x.get("target"))][x["picker"]].append(x)
    print(f"\nPAIRED {hi} minus {lo} by slate and target (both versions logged)")
    for label, keep in (("same-game", lambda k: k[2] == "stacks_same"), ("cross-game", lambda k: k[2] == "stacks")):
        d_win, d_ret, d_said = [], [], []
        for k, by in cell.items():
            if not keep(k) or lo not in by or hi not in by:
                continue
            m = lambda v, f: sum(map(f, by[v])) / len(by[v])  # noqa: E731
            d_win.append(m(hi, lambda x: x["result"] == "won") - m(lo, lambda x: x["result"] == "won"))
            d_ret.append(m(hi, ret) - m(lo, ret))
            d_said.append(m(hi, lambda x: x["chance"]) - m(lo, lambda x: x["chance"]))
        if not d_win:
            print(f"  {label}: no paired slates yet")
            continue
        w, wl, wh = ci(d_win, boot)
        r, rl, rh = ci(d_ret, boot)
        s = sum(d_said) / len(d_said)
        print(
            f"  {label}: {len(d_win)} game-targets; said {s * 100:+.1f} pts; hit rate {w * 100:+.1f} pts "
            f"[{wl * 100:+.1f}, {wh * 100:+.1f}]; return/$ {r:+.3f} [{rl:+.3f}, {rh:+.3f}]"
        )


def legs(rows: list[dict]) -> None:
    ls = [x for x in rows if x.get("kind") == "leg" and x.get("result") in DONE and x.get("latest", True)]
    ls = [x for x in ls if x.get("chance_v1") is not None and x.get("chance_v2") is not None]
    print(f"\nLEGS said vs got, {len(ls)} settled legs carrying both chances")
    for name, f in (("all", lambda x: True), ("bench overs", lambda x: x.get("bench") and not x.get("under")),
                    ("bench unders", lambda x: x.get("bench") and x.get("under"))):
        r = [x for x in ls if f(x)]
        if not r:
            continue
        got = sum(x["result"] == "won" for x in r) / len(r)
        s1 = sum(x["chance_v1"] for x in r) / len(r)
        s2 = sum(x["chance_v2"] for x in r) / len(r)
        s3 = sum(x.get("chance_v3", x["chance_v2"]) for x in r) / len(r)
        print(f"  {name:13} n {len(r):>5}  got {got:.3f}  said v1 {s1:.3f} (gap {got - s1:+.3f})  said v2 {s2:.3f} (gap {got - s2:+.3f})  said v3 {s3:.3f} (gap {got - s3:+.3f})")


def repicks(path: str | None, ms: list[dict]) -> None:
    print("\nDRIFT RE-PICKS")
    if not path:
        print("  (pass --repicks challenges.json: a challenge store or a list of states/events)")
        return
    raw = json.load(open(path))
    states = raw if isinstance(raw, list) else raw.get("challenges") or raw.get("items") or [raw]
    events = []
    for s in states:
        events += (s.get("state") or s).get("repicks", []) if isinstance(s, dict) and "at" not in s else [s]
    res = {tuple(x.get("picks") or ()): x["result"] for x in ms}
    if not events:
        print("  none recorded")
        return
    for e in events:
        was, now = res.get(tuple(e.get("was") or ())), res.get(tuple(e.get("now") or ()))
        mv = e["moves"][0]
        print(f"  {e['at'][:16]} stage {e['stage']}: {mv['leg']} ${mv['from']:.2f} -> ${mv['to']:.2f}; "
              f"replaced pick {was or 'unscored'}, fresh pick {now or 'unscored'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--repicks")
    ap.add_argument("--boot", type=int, default=4000)
    a = ap.parse_args()
    rows = load(a.log)
    ms = multis(rows)
    print(f"{len(rows)} records, {len(ms)} settled multis")
    per_version(ms)
    paired(ms, a.boot)
    paired(ms, a.boot, "v3", "v2")  # the promotion test: v3 replaces v2 only if it beats it here
    legs(rows)
    repicks(a.repicks, ms)


if __name__ == "__main__":
    main()
