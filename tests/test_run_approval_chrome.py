"""The approval switch "use for agents" of the two local servers, as the real
window part draws it (`Serverregler`), clicked in headless Chrome
(tests/preview_harness.py), and the places the cloud window and the stores
read and write it.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests import preview_harness as harness

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
ENGLISH = json.loads((ROOT / "app" / "locales" / "en.json").read_text(encoding="utf-8"))["modell"]

needs_browser = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

SHELL = """<script>
  import Serverregler from '../../src/teile/Serverregler.svelte'

  let fein = $state({ kv_cache: 'f16', flash_attention: 'auto', moe_auf_cpu: false, festnageln: false,
                      kv_unified: true, idle_minutes: null })
  let vorladen = $state(true)
  let parallel = $state(null)
  let port = $state(8080)
  let free = $state(true)
  const heardList = []
  window.__heard = heardList
  window.__free = () => free
</script>

<div id="withrow" style="width: 560px; padding: 16px;">
  <Serverregler kennung="a" teil="fein" gesperrt={true} bind:fein bind:vorladen bind:parallel bind:port idle={null}
                useForRuns={free} onuseforruns={(neu) => { heardList.push(neu); free = neu }} />
</div>
<div id="norow" style="width: 560px; padding: 16px;">
  <Serverregler kennung="b" teil="fein" bind:fein bind:vorladen bind:parallel bind:port idle={null} />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import '../../src/stil/global.css'
import '../../src/stil/tiles.css'
import english from '../../../app/locales/en.json'
import { texte } from '../../src/lib/texte.svelte.js'

window.__errors = []
window.addEventListener('error', (e) => window.__errors.push(String(e.message)))
window.addEventListener('unhandledrejection', (e) => window.__errors.push(String(e.reason && (e.reason.stack || e.reason.message) || e.reason)))
texte.sprache = 'en'
texte.katalog = english
mount(Shell, { target: document.getElementById('wurzel') })
"""

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
await wait(500)
const report = {}
const switchOf = (root) => [...document.querySelectorAll(`${root} [role=switch]`)]
  .find((b) => b.getAttribute('aria-label') === '__LABEL__')
const withRow = switchOf('#withrow')
report.withRow = Boolean(withRow)
report.withDisabled = withRow ? withRow.disabled : null
report.withOn = withRow ? withRow.getAttribute('aria-checked') : null
report.without = Boolean(switchOf('#norow'))
withRow.click()
await wait(150)
report.heard = window.__heard
report.afterOff = switchOf('#withrow').getAttribute('aria-checked')
switchOf('#withrow').click()
await wait(150)
report.afterOn = switchOf('#withrow').getAttribute('aria-checked')
report.errors = window.__errors.slice(0, 6)
document.getElementById('ergebnis').textContent = JSON.stringify(report)
""".replace("__LABEL__", "__LABEL_TEXT__")


@pytest.fixture(scope="module")
def report() -> dict:
    cases = CASES.replace("__LABEL_TEXT__", ENGLISH["fuer_agenten"])
    return harness.run_page(SHELL, ENTRY_JS, cases, {})


def browser(test):
    for mark in needs_browser:
        test = mark(test)
    return test


@browser
def test_the_row_is_there_where_a_server_has_runs_and_not_where_it_has_none(report):
    assert report["withRow"] is True and report["without"] is False, report


@browser
def test_the_switch_works_while_the_server_runs_and_says_its_new_state(report):
    """The start values are locked while the server runs; the approval is
    none of them, the next run reads it."""
    assert report["withDisabled"] is False and report["withOn"] == "true", report
    assert report["heard"] == [False, True], report["heard"]
    assert report["afterOff"] == "false" and report["afterOn"] == "true", report


@browser
def test_nothing_was_refused_or_failed_while_drawing(report):
    assert report["errors"] == [], report["errors"]


def test_the_two_pages_and_the_cloud_window_carry_the_switch_and_write_it_at_once():
    teile = FRONTEND / "src" / "teile"
    for datei, speicher in (("Modellserver.svelte", "runnermodell"), ("Agentserver.svelte", "agentenmodell")):
        quelle = (teile / datei).read_text(encoding="utf-8")
        assert f"useForRuns={{{speicher}.use_for_runs ??" in quelle, datei
        assert "werteSetzen({ use_for_runs: neu })" in quelle, datei
        # Not among the numbers the debounce writes: those stand still while a server runs.
        assert not [z for z in quelle.splitlines() if "JSON.stringify(" in z and "use_for_runs" in z], datei
    cloud = (teile / "ModelleCloud.svelte").read_text(encoding="utf-8")
    assert "setUseForRuns(paramsModel.id, neu)" in cloud and "isUsedForRuns(paramsModel.id)" in cloud
    assert "loadRunApprovals()" in cloud


def test_the_approvals_have_a_place_in_the_search_list_and_in_both_catalogues():
    liste = (FRONTEND / "src" / "lib" / "einstellungsliste.js").read_text(encoding="utf-8")
    assert "titel: 'modell.fuer_agenten'" in liste
    de = json.loads((ROOT / "app" / "locales" / "de.json").read_text(encoding="utf-8"))["modell"]
    assert ENGLISH["fuer_agenten"] and de["fuer_agenten"] and ENGLISH["fuer_agenten"] != de["fuer_agenten"]
