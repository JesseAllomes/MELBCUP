"""The GitHub Pages copy in docs/ must match the package, or the phone runs stale code."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_builder():
    spec = importlib.util.spec_from_file_location("build_pages", ROOT / "tools/build_pages.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_docs_match_the_package():
    stale = load_builder().stale()
    assert stale == [], f"run: python tools/build_pages.py ({stale[:5]})"


def test_browser_bundle_leaves_out_server_only_code():
    files = load_builder().wanted()
    assert "py/melbcup/browser.py" in files and "py/melbcup/web/views.py" in files
    assert "py/melbcup/web/app.py" not in files
    assert not any(
        "fastapi" in v.decode(errors="ignore") for k, v in files.items() if k.endswith(".py")
    )
    assert (ROOT / "docs/.nojekyll").exists()  # Jekyll would drop _pick.html and friends
