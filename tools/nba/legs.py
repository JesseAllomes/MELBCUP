# ruff: noqa: E501
"""CLI and import shim: the legs code lives in azure/function/nba_legs.py, so the Azure Function
that prices legs every 20 minutes and these tools run the same file.

Usage: python3 tools/nba/legs.py BOARD.json OUT.json [--snapdir DIR] [--min-chance 0.75] [--stake 10] [--min-ev 0.03]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "azure", "function"))
from nba_legs import *  # noqa: E402,F401,F403
from nba_legs import main  # noqa: E402

if __name__ == "__main__":
    main()
