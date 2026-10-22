"""The choice fields of the cleaning, embedding and speech server pages, in a
real browser: in front of every model file a maker's mark (or the first
letter), behind its name the size with the decimal sign of the language — the
way the model and the agent server write them. The choices that name no file
(the empty one, "No voice") carry nothing.

The real pages are built as they ship with the harness of
``tests/model_windows_page.py``; this file widens that harness by the three
pages and their answers for the run (nothing in the shared file changes), and
the service's answers are made up: the model folder holds two files of the
stub, one a family with a logo (Qwen) and one nothing knows (a letter).

Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

from unittest import mock

import pytest

from tests import model_windows_page as harness
from tests.model_windows_page import BROWSER_TESTS_POSSIBLE, run_cases

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        not BROWSER_TESTS_POSSIBLE, reason="no node or no frontend dependencies on this machine"
    ),
]

SHELL_IMPORTS = """  import Bereinigungsserver from '../../src/teile/Bereinigungsserver.svelte'
  import Einbettungsserver from '../../src/teile/Einbettungsserver.svelte'
  import Sprachserver from '../../src/teile/Sprachserver.svelte'
"""

SHELL_PAGES = """  {#if scene.show === 'bereinigung'}<Bereinigungsserver />{/if}
  {#if scene.show === 'einbettung'}<Einbettungsserver />{/if}
  {#if scene.show === 'sprache'}<Sprachserver />{/if}
"""

STUB_METHODS = """  bereinigungAuskunft: async () => { window.__asked = (window.__asked || 0) + 1; return auskunft('chat') },
  einbettungAuskunft: async () => { window.__asked = (window.__asked || 0) + 1; return auskunft('chat') },
  spracheAuskunft: async () => { window.__asked = (window.__asked || 0) + 1; return auskunft('chat') },
"""

CASES = r"""
const report = {}
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const stub = window.__stub
texte.katalog = germanTexts
// One file of a family with a logo and one nothing knows, beside the stub's a.gguf and b.gguf.
stub.extraFiles = [
  { name: 'Qwen3-8B-Q4_K_M.gguf', groesse_gb: 4.9 },
  { name: 'zebra-model.gguf', groesse_gb: 1.5 },
]
const markOf = (node) => ({
  logo: Boolean(node.querySelector('svg.logo')),
  letter: node.querySelector('.letter')?.textContent ?? null,
})
const combos = () => [...document.querySelectorAll('button[role="combobox"]')]
const options = () =>
  [...document.querySelectorAll('[role="option"]')].map((o) => ({
    text: o.textContent.replace(/\s+/g, ' ').trim(), ...markOf(o),
    markFirst: o.querySelector('.logo, .letter') === [...o.children].find((c) => c.matches('.logo, .letter')),
  }))
for (const page of ['bereinigung', 'einbettung', 'sprache']) {
  window.__asked = 0
  scene.show = page
  // The page has asked the service and the answer has been drawn.
  for (let k = 0; k < 100 && !(window.__asked > 0 && combos().length > 0); k += 1) await wait(50)
  await wait(600)
  const lists = []
  for (let index = 0; index < combos().length; index += 1) {
    combos()[index].click()
    await wait(400)
    lists.push(options())
    document.body.click()
    await wait(200)
  }
  report[page] = { fields: combos().length, lists }
  scene.show = null
  await wait(300)
}
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    anchors = {
        harness.SHELL: ("  import { scene } from './scene.svelte.js'\n", "  {#if scene.show === 'agent'}<Agentserver />{/if}\n"),
        harness.API_STUB: ("  runnerProtokoll: async () => [],\n",),
    }
    for source, lines in anchors.items():
        for line in lines:
            assert line in source, f"the shared harness changed, widen it again: {line!r}"
    shell = harness.SHELL.replace("  import { scene } from './scene.svelte.js'\n", SHELL_IMPORTS + "  import { scene } from './scene.svelte.js'\n")
    shell = shell.replace("  {#if scene.show === 'agent'}<Agentserver />{/if}\n", "  {#if scene.show === 'agent'}<Agentserver />{/if}\n" + SHELL_PAGES)
    stub = harness.API_STUB.replace("  runnerProtokoll: async () => [],\n", "  runnerProtokoll: async () => [],\n" + STUB_METHODS)
    assert "Sprachserver" in shell and "spracheAuskunft" in stub
    with mock.patch.object(harness, "SHELL", shell), mock.patch.object(harness, "API_STUB", stub):
        return run_cases(CASES)


def _plain(text: str) -> str:
    return text.replace(" ", " ")


def _files(page: dict) -> list[dict]:
    """The entries of the lists that name files — the lists with a named file in them."""
    return [entry for lst in page["lists"] for entry in lst if ".gguf" in entry["text"]]


@pytest.mark.parametrize("name", ["bereinigung", "einbettung", "sprache"])
def test_every_file_of_the_page_stands_with_its_mark_in_front_and_the_size_with_a_comma(report, name):
    page = report[name]
    assert page["fields"] >= 1, page
    files = _files(page)
    assert files, page
    texts = {_plain(entry["text"]) for entry in files}
    # A family with a logo wears the logo and no letter; a file nothing knows wears its first letter.
    qwen = [entry for entry in files if "Qwen3-8B" in entry["text"]]
    zebra = [entry for entry in files if "zebra" in entry["text"]]
    assert qwen and zebra, texts
    for entry in qwen:
        assert (entry["logo"], entry["letter"], entry["markFirst"]) == (True, None, True), entry
        assert _plain(entry["text"]) == "Qwen3-8B-Q4_K_M.gguf · 4,9 GB"
    for entry in zebra:
        assert (entry["logo"], entry["letter"], entry["markFirst"]) == (False, "Z", True), entry
        assert _plain(entry["text"]).endswith("zebra-model.gguf · 1,5 GB")
    # Every file entry carries a mark, and no size is written with the point.
    for entry in files:
        assert entry["logo"] or entry["letter"], entry
        assert "." not in _plain(entry["text"]).split("·")[-1], entry["text"]


def test_the_empty_entry_of_the_cleaning_server_stays_without_a_mark(report):
    empty = [entry for lst in report["bereinigung"]["lists"] for entry in lst if entry["text"] == "-"]
    assert empty, report["bereinigung"]
    for entry in empty:
        assert not entry["logo"] and entry["letter"] is None, entry


def test_the_no_voice_choice_of_the_speech_server_stays_without_a_mark(report):
    entries = [entry for lst in report["sprache"]["lists"] for entry in lst]
    none = [entry for entry in entries if entry["text"] == "-"]
    assert none, "the speech page shows no 'no voice' entry"
    for entry in none:
        assert not entry["logo"] and entry["letter"] is None, entry
    # The only entries with a mark on the speech page name a file.
    assert [e for e in entries if ".gguf" not in e["text"] and (e["logo"] or e["letter"])] == []
