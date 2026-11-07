"""The deployed Function is a flat package (tools/deploy_azure.py): every module it imports must load
without the `melbcup` package. A `from melbcup import ...` with no flat fallback left the Function
with zero functions loaded on 7 Nov 2026 (nothing ran for 14 hours)."""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_function_package_imports_without_melbcup(tmp_path):
    pytest.importorskip("azure.functions")
    spec = importlib.util.spec_from_file_location("deploy_azure", ROOT / "tools/deploy_azure.py")
    d = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(d)
    pkg = tmp_path / "pkg"
    (pkg / "tools").mkdir(parents=True)
    for f in d.FUNC_FILES:
        shutil.copy(ROOT / f, pkg)
    shutil.copy(ROOT / "tools/live_collector.py", pkg / "tools/live_collector.py")
    (pkg / "tools/__init__.py").touch()
    src = (ROOT / "tools/deploy_azure.py").read_text()
    for line in src.splitlines():  # the same flat copies deploy_function makes
        if 'shutil.copy(ROOT / "melbcup/' in line:
            name = line.split('"melbcup/')[1].split('"')[0]
            shutil.copy(ROOT / "melbcup" / name, pkg / name)
    code = (
        "import sys; sys.modules['melbcup'] = None; sys.path.insert(0, sys.argv[1]); "
        "import function_app; print('ok')"
    )
    r = subprocess.run([sys.executable, "-c", code, str(pkg)], capture_output=True, text=True, timeout=120)
    assert r.stdout.strip() == "ok", r.stderr[-800:]
