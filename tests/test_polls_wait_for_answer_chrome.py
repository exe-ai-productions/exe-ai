"""The beats of the pages do not pile up their questions.

With answers that take five seconds, the memory pill (asked every two
seconds) and the catalogue (the same) asked the same path up to three times at
once. Now a beat asks again only after the answer. Real windows, built as they
ship, in a real Chrome; every answer is stood in by the page. Skipped where
there is no Chrome or no node.
"""

from __future__ import annotations

import pytest

from tests.loading_harness import run_page
from tests.test_speech_server_projector_memory import browser

SHELL = "<p></p>"

ENTRY_JS = """import { mount } from 'svelte'
import Speicherpille from '../src/teile/Speicherpille.svelte'
import Katalog from '../src/teile/Katalog.svelte'
import { texte } from '../src/lib/texte.svelte.js'
import { zustand } from '../src/lib/zustand.svelte.js'
import { meldungen } from '../src/lib/meldewesen.svelte.js'
import { ApiFehler } from '../src/lib/api.js'
import katalog from '../../app/locales/de.json'
import '../src/stil/global.css'

texte.katalog = katalog
window.zustand = zustand
window.meldungen = meldungen
window.ApiFehler = ApiFehler
const root = document.getElementById('root')
root.style.cssText = 'height: 1000px; display: flex; flex-direction: column;'
mount(Speicherpille, { target: root })
mount(Katalog, { target: root, props: { offen: true } })
"""

CASES = r"""
window.answers = {
  speicherorteLesen: [],
  speicherBlick: later(5000, { belegt_gb: 10, gesamt_gb: 32 }),
  runnerAuskunft: later(5000, { speicher_gb: 32, modelle: [], mmproj: [], mtp: [] }),
  modellHolenStand: null,
}
await wait(12000)
report.mostAtOnce = window.mostAtOnce
report.asked = ['speicherBlick', 'runnerAuskunft']
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    return run_page(SHELL, ENTRY_JS, CASES)


@browser
def test_the_windows_ran_without_a_script_error(report):
    assert report["errors"] == []


@browser
@pytest.mark.parametrize("path", ["speicherBlick", "runnerAuskunft"])
def test_a_path_is_never_asked_twice_at_once_while_its_answer_is_on_its_way(report, path):
    assert report["mostAtOnce"][path] == 1
