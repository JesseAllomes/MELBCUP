"""Shared locations. Raw downloads and built datasets stay OUT of git (scratch dir)."""

import os
from pathlib import Path

BASE = Path(
    os.environ.get(
        "AFL_DATA_DIR",
        "/tmp/claude-0/-home-user/418442d0-6a93-5b3f-a291-37c2b3744726/scratchpad/sports/afl",
    )
)
RAW = BASE / "raw"
OUT = BASE / "out"
REPO_OUT = Path(__file__).resolve().parents[3] / "research" / "sports" / "afl"
