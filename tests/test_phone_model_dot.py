"""The green dot before the model in the plus sheet of the phone page says the
model can be reached: it stands only while the chosen model is among the ones
the service offers. A model that is chosen but gone (the service does not list
it any more) is still named, without the dot — the line the desktop picker
draws between the offered model and the one only still named.

`AttachSheet.svelte` is built as it is shipped and drawn in headless Chrome.
Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from app import appfenster
from tests.test_phone_terminal_sheet import PAGE, VITE_CONFIG, _measure

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SRC = FRONTEND / "src"

SHELL = """<script>
  import AttachSheet from %(sheet)r
</script>

<AttachSheet open={true} onclose={() => {}} onskill={() => {}} />
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { zustand } from %(zustand)r
import %(global)r

window.zustand = zustand
mount(Shell, { target: document.getElementById('root') })
"""

CASES = r"""
const { zustand } = window
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const row = () => [...document.querySelectorAll('button.row')].find((b) => b.textContent.includes('modell.titel'))
const read = () => ({
  dot: Boolean(row()?.querySelector('.dot')),
  name: row()?.querySelector('.valuetext')?.textContent.trim() ?? null,
})
const report = {}

// 1. The chosen model is offered: it is reachable.
zustand.modelle = [{ id: 'm1', name: 'Reachable model', group: 'local' }]
zustand.modellId = 'm1'
zustand.unlistedModel = null
await wait(400)
report.offered = read()

// 2. The chosen model is gone from the list, but its name is kept: named, no dot.
zustand.modelle = []
zustand.unlistedModel = { id: 'm1', name: 'Reachable model' }
await wait(300)
report.unlisted = read()

// 3. Nothing at all: the empty word, no dot.
zustand.unlistedModel = null
zustand.modellId = null
await wait(300)
report.none = read()

// 4. Offered again: the dot is back.
zustand.modelle = [{ id: 'm1', name: 'Reachable model', group: 'local' }]
zustand.modellId = 'm1'
await wait(300)
report.again = read()

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    if shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists():
        pytest.skip("no node or no frontend dependencies on this machine")
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-modeldot-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {"sheet": "../../src/phone/AttachSheet.svelte"}, encoding="utf-8"
        )
        (folder / "entry.js").write_text(
            ENTRY_JS % {"zustand": "../../src/lib/zustand.svelte.js", "global": "../../src/stil/global.css"},
            encoding="utf-8",
        )
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        built = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert built.returncode == 0, (built.stdout + built.stderr)[-2000:]
        (folder / "measure.html").write_text(PAGE % {"cases": CASES}, encoding="utf-8")
        raw = _measure(program, folder, (folder / "measure.html").as_uri())
        assert raw, "the page wrote no report"
        out = json.loads(raw)
        assert "failure" not in out, out["failure"]
        return out
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_the_dot_stands_while_the_chosen_model_is_offered(report):
    assert report["offered"] == {"dot": True, "name": "Reachable model"}, report["offered"]
    assert report["again"] == {"dot": True, "name": "Reachable model"}, report["again"]


def test_a_chosen_model_the_service_no_longer_offers_is_named_without_the_dot(report):
    assert report["unlisted"] == {"dot": False, "name": "Reachable model"}, report["unlisted"]


def test_with_no_model_the_row_says_so_without_a_dot(report):
    assert report["none"] == {"dot": False, "name": "fehler.kein_modell_verfuegbar"}, report["none"]


def test_the_dot_hangs_on_the_offered_list_and_not_on_the_name_alone():
    sheet = (SRC / "phone" / "AttachSheet.svelte").read_text(encoding="utf-8")
    assert re.search(r"const reachable = \$derived\(Boolean\(model\) && sichtbare\(\)\.some\(", sheet)
    assert '{#if reachable}<span class="dot"' in sheet
    assert '{#if model}<span class="dot"' not in sheet
