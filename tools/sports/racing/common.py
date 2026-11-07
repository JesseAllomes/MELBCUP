"""Shared paths and helpers for the racing study (tools/sports/racing)."""

import os

SCRATCH = "/tmp/claude-0/-home-user/418442d0-6a93-5b3f-a291-37c2b3744726/scratchpad/sports/racing"
ROOT = os.environ.get("RACING_WORK", SCRATCH)
RAW = os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "out")
HOLDOUT_SEASON = "2025-26"  # most recent full season (1 Aug 2025 - 31 Jul 2026), sealed


def season(date: str) -> str:
    """Racing season label: 1 Aug to 31 Jul. '2025-08-01' -> '2025-26'."""
    y, m = int(date[:4]), int(date[5:7])
    s = y if m >= 8 else y - 1
    return f"{s}-{str(s + 1)[2:]}"


def price(text) -> float | None:
    """'$2.45' -> 2.45; junk or <=1 -> None."""
    if text is None:
        return None
    try:
        v = float(str(text).replace("$", "").strip())
    except ValueError:
        return None
    return v if v > 1.0 else None
