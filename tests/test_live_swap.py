from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "melbcup" / "web" / "static"
JS = (STATIC / "asynym.js").read_text()


def test_live_swap_exists():
    assert "window.liveSwap = function" in JS
    assert "fetch(location.href" in JS and "DOMParser" in JS


def test_no_reload_or_tap_in_refresh_paths():
    for name in ("asynym.js", "app.js"):
        src = (STATIC / name).read_text()
        assert "location.reload" not in src
        assert "location.replace" not in src
    assert "bn-toast" not in JS
    assert "ready · tap" not in JS


def test_accordion_delegated_and_idempotent():
    assert 'document.addEventListener("click", function (e) {\n    var head' in JS
    assert "initChallengeAccordion" in JS and "if (started) return;" in JS
