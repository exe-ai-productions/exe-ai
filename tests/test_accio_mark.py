"""An Occamy model file wears the Accio logo wherever a logo stands for a file:
the places that read the mark from the file's name (quick pick, downloads, the
choice fields of the server pages, the server overview) ask the family list,
and that list knows Occamy.

The logo is the house's own vector (`frontend/src/lib/logos.js`); these tests
hold that the name finds it and that a file with no known family keeps its
letter. The choice field is also drawn in a real browser
(`tests/model_windows_page.py`).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.model_windows_page import BROWSER_TESTS_POSSIBLE, run_cases

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")

OCCAMY = "Occamy-1.0-APEX-I-MiniPlus-V2.1.gguf"


def _driver(code: str) -> object:
    """Runs `code` as a module of the frontend, so the real modules are
    imported the way the page imports them."""
    driver_file = FRONTEND / f"accio-{os.getpid()}.check.mjs"
    driver_file.write_text(code, encoding="utf-8")
    try:
        run = subprocess.run(
            ["node", driver_file.name], cwd=FRONTEND, capture_output=True, text=True, timeout=60,
        )
    finally:
        driver_file.unlink(missing_ok=True)
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    return json.loads(run.stdout.split("---REPORT---", 1)[1].strip())


@needs_node
def test_the_family_list_and_the_file_mark_give_an_occamy_file_the_accio_logo():
    answer = _driver(
        "import { LOGOS } from './src/lib/logos.js'\n"
        "import { modellMarke } from './src/lib/anbieterzeichen.js'\n"
        "import { fileMark } from './src/lib/fileMark.js'\n"
        f"const name = '{OCCAMY}'\n"
        "console.log('---REPORT---' + JSON.stringify({\n"
        "  family: modellMarke(name, '') === LOGOS.accio,\n"
        "  lower: modellMarke(name.toLowerCase(), '') === LOGOS.accio,\n"
        "  file: fileMark(name) === LOGOS.accio,\n"
        "  other: fileMark('Occamy-1.0-MiniPlus-V2.1.gguf') === LOGOS.accio,\n"
        "  catalogue: fileMark('Occamy-1.0.APEX-I-MiniPlus-V2.1.gguf') === LOGOS.accio,\n"
        "}))\n"
    )
    assert answer == {"family": True, "lower": True, "file": True, "other": True, "catalogue": True}


@needs_node
def test_the_other_families_keep_their_logos_and_an_unknown_file_has_none():
    """The silence probe: a file nothing knows still has no mark (so its
    letter stands), and the families named before keep theirs."""
    answer = _driver(
        "import { LOGOS } from './src/lib/logos.js'\n"
        "import { fileMark } from './src/lib/fileMark.js'\n"
        "console.log('---REPORT---' + JSON.stringify({\n"
        "  unknown: fileMark('a.gguf'),\n"
        "  unknown_name: fileMark('Nothingburger-7B-Q4_K_M.gguf'),\n"
        "  qwen: fileMark('Qwen3-8B-Q4_K_M.gguf') === LOGOS.qwen,\n"
        "  deepseek: fileMark('DeepSeek-R1-Distill-Q4_K_M.gguf') === LOGOS.deepseek,\n"
        "  mistral: fileMark('Mistral-7B-Instruct-Q4_K_M.gguf') === LOGOS.mistral,\n"
        "  distinct: LOGOS.accio !== LOGOS.qwen,\n"
        "}))\n"
    )
    assert answer == {
        "unknown": None, "unknown_name": None, "qwen": True,
        "deepseek": True, "mistral": True, "distinct": True,
    }


CASES = "const occamyName = " + json.dumps(OCCAMY) + r"""
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const stub = window.__stub
texte.katalog = germanTexts
stub.extraFiles = [{ name: occamyName, groesse_gb: 5 }, { name: 'Qwen3-8B-Q4_K_M.gguf', groesse_gb: 4.5 }]
scene.show = 'modell'
for (let k = 0; k < 80 && !document.querySelector('button[role="combobox"]'); k += 1) await wait(50)
await wait(500)
document.querySelector('button[role="combobox"]').click()
await wait(400)
const options = [...document.querySelectorAll('[role="option"]')].map((o) => ({
  text: o.textContent.replace(/\s+/g, ' ').trim(),
  logo: o.querySelector('svg.logo')?.innerHTML.includes('accio-verlauf') ?? false,
  anyLogo: Boolean(o.querySelector('svg.logo')),
  letter: o.querySelector('.letter')?.textContent ?? null,
}))
document.getElementById('ergebnis').textContent = JSON.stringify({ options })
"""


@pytest.fixture(scope="module")
def report() -> dict:
    return run_cases(CASES)


@pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only")
@pytest.mark.skipif(not BROWSER_TESTS_POSSIBLE, reason="no node or no frontend dependencies on this machine")
def test_the_open_model_field_draws_the_accio_logo_before_an_occamy_file(report):
    occamy = next(o for o in report["options"] if OCCAMY in o["text"])
    assert occamy["logo"] is True and occamy["letter"] is None, occamy
    # The silence probe: a file with no family keeps its letter, a known one its own logo.
    plain = next(o for o in report["options"] if " a.gguf ·" in o["text"])
    assert plain["letter"] == "A" and plain["anyLogo"] is False
    qwen = next(o for o in report["options"] if "Qwen3-8B" in o["text"])
    assert qwen["anyLogo"] is True and qwen["logo"] is False and qwen["letter"] is None
