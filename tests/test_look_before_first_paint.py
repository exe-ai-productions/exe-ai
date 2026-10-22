"""The look stands from the first frame on.

The page's own script (`frontend/index.html`) puts the look the user chose on
the root element before the first paint. The app used to begin with the
default look in its state and wrote that over it in its first run, until the
service answered: every start showed Exe for a moment. The app now begins with
the look the page painted (`startModus` in `frontend/src/lib/anzeige.js`).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
ANZEIGE = FRONTEND / "src/lib/anzeige.js"
APP = FRONTEND / "src/App.svelte"
INDEX = FRONTEND / "index.html"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


def _start(storage_js: str) -> str:
    """What `startModus` answers for a storage built by `storage_js`."""
    script = f"""
import {{ startModus }} from {json.dumps(ANZEIGE.as_uri())}
const storage = {storage_js}
console.log(JSON.stringify(startModus(storage)))
"""
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=60, cwd=FRONTEND,
    )
    assert run.returncode == 0, run.stderr[-1500:]
    return json.loads(run.stdout)


def _kept(value: str | None) -> str:
    return "{ getItem: () => " + json.dumps(value) + " }"


@needs_node
@pytest.mark.parametrize("look", ["hell", "dunkel", "darkmatter", "heaven", "moune", "snow", "eigen"])
def test_the_app_begins_with_the_look_the_page_painted(look: str):
    assert _start(_kept(look)) == look


@needs_node
def test_auto_is_kept_so_that_the_device_decides():
    """"Auto" sets no `data-modus`: the state is "auto" from the start, the
    effect removes the attribute and the stylesheet follows the device."""
    assert _start(_kept("auto")) == "auto"


@needs_node
def test_without_a_chosen_look_the_app_starts_in_auto():
    """Silence probe: nothing kept, something unknown, or no storage at all
    is the default, Auto — the look that follows the device."""
    assert _start(_kept(None)) == "auto"
    assert _start(_kept("pearl-2000")) == "auto"
    assert _start("{ getItem: () => { throw new Error('blocked') } }") == "auto"
    assert _start("null") == "auto"


def test_the_app_state_begins_with_that_look_and_not_with_the_default():
    app = APP.read_text(encoding="utf-8")
    assert "let modus = $state(startModus())" in app
    assert "let modus = $state(VORGABE_MODUS)" not in app
    assert "VORGABE_MODUS" not in app
    # The page's own script reads the same key, and sets nothing for "auto".
    page = INDEX.read_text(encoding="utf-8")
    assert "localStorage.getItem('exe-modus')" in page
    assert "modus !== 'auto'" in page
    assert "export const MODUS_SCHLUESSEL = 'exe-modus'" in ANZEIGE.read_text(encoding="utf-8")


def test_the_app_looks_are_the_services_looks():
    """The list `startModus` accepts is the service's (`app/moduswahl.py`)."""
    from app.moduswahl import MODI

    source = ANZEIGE.read_text(encoding="utf-8")
    listed = source.split("const MODI = [", 1)[1].split("]", 1)[0]
    names = [part.strip().strip("'") for part in listed.split(",")]
    assert sorted(names) == sorted(MODI)
