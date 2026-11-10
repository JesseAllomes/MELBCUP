"""Shared loader for the picker review (token-free, stdlib only).
Usage from the scripts: python3 -I tools/nba/review/<script>.py forward-v2.jsonl
Dedupe legs by (espn_event or event, label, agency), keeping the `latest` row; only won/lost."""
import json, math, random, sys, os
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
B = 500
SEED = 20261110


def load(path):
    legs, multis = [], []
    for line in open(path):
        r = json.loads(line)
        (legs if r.get("kind") == "leg" else multis).append(r)
    return legs, multis


def gid(r):
    return str(r.get("espn_event") or r.get("event"))


def lkey(r):
    return (gid(r), r.get("label"), r.get("agency"))


def settled_legs(legs):
    """One row per (game, label, agency): the latest log wins; won/lost only."""
    best = {}
    for r in legs:
        if r.get("result") not in ("won", "lost") or not r.get("chance"):
            continue
        k = lkey(r)
        o = best.get(k)
        if o is None or (r.get("latest") and not o.get("latest")) or (
            bool(r.get("latest")) == bool(o.get("latest")) and r["day"] > o["day"]
        ):
            best[k] = r
    return list(best.values())


def ltype(r):
    lab = r.get("label") or ""
    return "ou" if (" Over " in lab or " Under " in lab) else "rung"


def side(r):
    return "under" if r.get("under") else "over"


def pband(p):
    for top, name in ((1.15, "<1.15"), (1.3, "1.15-1.3"), (1.5, "1.3-1.5"), (1.8, "1.5-1.8"),
                      (2.2, "1.8-2.2"), (3.0, "2.2-3"), (5.0, "3-5")):
        if p < top:
            return name
    return "5+"


def cband(c):
    for top, name in ((0.3, "<.30"), (0.45, ".30-.45"), (0.55, ".45-.55"), (0.65, ".55-.65"),
                      (0.75, ".65-.75"), (0.85, ".75-.85")):
        if c < top:
            return name
    return ".85+"


def roles(legs):
    """Pre-game role proxy per (game, player): the highest points line the market makes >= 50%
    (about the player's median points). star >= 20, starter 12-19, bench < 12, '?' when unknown."""
    med = {}
    for r in legs:
        if r.get("stat") == "points" and not r.get("under") and (r.get("market") or 0) >= 0.5:
            k = (gid(r), r.get("player"))
            med[k] = max(med.get(k, 0), r.get("line") or 0)
    def role(r):
        m = med.get((gid(r), r.get("player")))
        if m is None:
            return "?"
        return "star20+" if m >= 20 else "starter12-19" if m >= 12 else "bench<12"
    return role


def won(r):
    return 1 if r["result"] == "won" else 0


def stats(rows, said=lambda r: r["chance"]):
    """n, games, said, got, gap, ROI with a game-cluster bootstrap 95% interval for gap and ROI,
    and a two-sided z p-value for gap = 0 from the bootstrap standard error."""
    by = defaultdict(lambda: [0, 0.0, 0, 0.0])
    for r in rows:
        a = by[gid(r)]
        a[0] += 1; a[1] += said(r); a[2] += won(r); a[3] += (r["price"] if won(r) else 0.0) - 1
    g = list(by.values())
    n = sum(a[0] for a in g)
    if not n:
        return None
    S = sum(a[1] for a in g) / n; W = sum(a[2] for a in g) / n; R = sum(a[3] for a in g) / n
    rng = random.Random(SEED)
    gaps, rois = [], []
    m = len(g)
    for _ in range(B):
        nn = s = w = ret = 0.0
        for _ in range(m):
            a = g[rng.randrange(m)]
            nn += a[0]; s += a[1]; w += a[2]; ret += a[3]
        gaps.append((w - s) / nn); rois.append(ret / nn)
    gaps.sort(); rois.sort()
    lo, hi = int(0.025 * B), int(0.975 * B) - 1
    mean = sum(gaps) / B
    se = math.sqrt(sum((x - mean) ** 2 for x in gaps) / (B - 1)) or 1e-9
    z = (W - S) / se
    p = math.erfc(abs(z) / math.sqrt(2))
    return dict(n=n, games=m, said=S, got=W, gap=W - S, glo=gaps[lo], ghi=gaps[hi],
                roi=R, rlo=rois[lo], rhi=rois[hi], p=p)


def bh(rows, q=0.10):
    """Benjamini-Hochberg: marks rows (dicts with 'p') that survive a false-discovery rate q."""
    ps = sorted((r["p"], i) for i, r in enumerate(rows))
    m = len(ps); cut = -1
    for rank, (p, _i) in enumerate(ps, 1):
        if p <= q * rank / m:
            cut = rank
    keep = {i for rank, (_p, i) in enumerate(ps, 1) if rank <= cut}
    for i, r in enumerate(rows):
        r["fdr"] = i in keep
    return rows


HEAD = f"{'cell':34}{'n':>6}{'gms':>4}{'said':>6}{'got':>6}{'gap':>7} {'95% gap':>15}{'ROI':>7} {'95% ROI':>15}{'p':>7} fdr"


def line(name, s):
    return (f"{name[:34]:34}{s['n']:6}{s['games']:4}{s['said']:6.3f}{s['got']:6.3f}{s['gap']:+7.3f} "
            f"[{s['glo']:+.3f},{s['ghi']:+.3f}]{s['roi']:+7.3f} [{s['rlo']:+.3f},{s['rhi']:+.3f}]"
            f"{s['p']:7.3f} {'*' if s.get('fdr') else ''}")


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 1.0)
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)
