"""Build the GitHub Pages site in docs/: the Python package and templates the browser runs,
plus the stylesheet. Run after changing anything under melbcup/:

    python tools/build_pages.py          # write docs/py and docs/app.css
    python tools/build_pages.py --check  # exit 1 if docs/ is out of date (the tests run this)
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "melbcup"
DOCS = ROOT / "docs"
# Server-only or offline-only modules the browser never imports.
SKIP = {"melbcup/web/app.py", "melbcup/backtest.py"}


def wanted() -> dict[str, bytes]:
    files = {}
    for path in sorted(PACKAGE.rglob("*")):
        rel = path.relative_to(ROOT).as_posix()
        if "__pycache__" in rel or rel in SKIP or not path.is_file():
            continue
        if path.suffix == ".py" or (path.suffix == ".html" and "/templates/" in rel):
            files[f"py/{rel}"] = path.read_bytes()
    files["app.css"] = (PACKAGE / "web/static/app.css").read_bytes()
    digest = hashlib.sha256(b"".join(k.encode() + v for k, v in files.items())).hexdigest()[:12]
    manifest = {
        "build": digest,
        "files": [k.removeprefix("py/") for k in files if k.startswith("py/")],
    }
    files["py/manifest.json"] = (json.dumps(manifest, indent=1) + "\n").encode()
    return files


def stale(dest: Path = DOCS) -> list[str]:
    """Files that differ from a fresh build, are missing, or should no longer be there."""
    want = wanted()
    have = {
        f"py/{p.relative_to(dest / 'py').as_posix()}"
        for p in (dest / "py").rglob("*")
        if p.is_file()
    }
    diffs = [k for k, v in want.items() if not (dest / k).is_file() or (dest / k).read_bytes() != v]
    return diffs + sorted(have - set(want))


def build(dest: Path = DOCS) -> None:
    shutil.rmtree(dest / "py", ignore_errors=True)
    for rel, data in wanted().items():
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)


if __name__ == "__main__":
    if "--check" in sys.argv:
        diffs = stale()
        if diffs:
            print("docs/ is out of date; run python tools/build_pages.py:", *diffs[:10], sep="\n  ")
            sys.exit(1)
        print("docs/ is up to date")
    else:
        build()
        print("built docs/ (", wanted()["py/manifest.json"].decode().split('"')[3], ")")
