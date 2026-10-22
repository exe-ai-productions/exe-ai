"""The model server page says "Loading ..." until the service has answered, in a
real browser.

Before the first answer nothing is known about the program or the folder, yet
the page showed the set-up in three steps ("Server missing · Model missing ·
Not started") with the button to download the server — and kept showing it for
good when the first read failed. The set-up now stands only on an answer that
says no model lies in the folder; until then the page says "Loading ...", with
no button and no line in its head, and a failed read changes nothing but the
notice that says why.

The real page is built as shipped on the stub of ``tests/model_windows_page.py``,
which this file widens by a read that can be delayed and made to fail (what is
made up: every answer of the service). Skipped where there is no Chrome or no
node.
"""

from __future__ import annotations

import json
from pathlib import Path
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

GERMAN = json.loads(
    (Path(__file__).resolve().parent.parent / "app" / "locales" / "de.json").read_text(encoding="utf-8")
)

STUB_METHODS = """{
  const answer = methods.runnerAuskunft
  methods.runnerAuskunft = async () => {
    stub.reads = (stub.reads || 0) + 1
    if (stub.delay) await new Promise((done) => setTimeout(done, stub.delay))
    if (stub.failReads > 0) {
      stub.failReads -= 1
      throw new Error('read failed')
    }
    return answer()
  }
}
"""

CASES = r"""
const stub = window.__stub
texte.katalog = germanTexts
const pause = (ms) => new Promise((done) => setTimeout(done, ms))
const root = () => document.getElementById('root')
const snap = () => ({
  loading: root().querySelector('.laedt')?.textContent.trim() ?? null,
  journey: Boolean(root().querySelector('.erstetafel')),
  journeyText: root().querySelector('.erstetafel .skdetails')?.textContent.trim() ?? null,
  download: root().textContent.includes(germanTexts.modell.server_holen),
  form: Boolean(root().querySelector('.reihe, .abschnitt')) && !root().querySelector('.laedt')
    && !root().querySelector('.erstetafel'),
})
const open = async () => { scene.show = null; await pause(200); scene.show = 'modell' }
// Samples the page every 100 ms for ``ms`` and keeps every state it was in.
const watch = async (ms) => {
  const seen = []
  for (let spent = 0; spent < ms; spent += 100) { seen.push(snap()); await pause(100) }
  return seen
}
const report = {}

// 1. The first answer takes a while: loading, then the form.
stub.delay = 1500
await open()
await pause(500)
report.waiting = snap()
report.delayedSeen = await watch(2500)
stub.delay = 0

// 2. The first read fails, the next one gets through: loading, never the set-up, then the form.
stub.failReads = 1
await open()
report.failedSeen = await watch(5000)
report.failedReads = stub.reads

// 3. A read that fails once an answer is there leaves the form standing.
stub.failReads = 2
report.afterAnswerSeen = await watch(5000)

// 4. Answers that say no model lies there: the set-up, as before.
stub.noModels = true
stub.noProgram = true
await open()
await pause(1200)
report.noProgram = snap()
stub.noProgram = false
await open()
await pause(1200)
report.noModel = snap()
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    assert "export const setSessionKey = () => {}\n" in harness.API_STUB
    stub = harness.API_STUB.replace(
        "export const setSessionKey = () => {}\n", STUB_METHODS + "export const setSessionKey = () => {}\n"
    )
    with mock.patch.object(harness, "API_STUB", stub):
        return run_cases(CASES)


def test_before_the_first_answer_the_page_says_loading_and_no_set_up_or_download(report):
    waiting = report["waiting"]
    assert waiting["loading"] == GERMAN["bilder"]["laedt"], waiting
    assert not waiting["journey"] and not waiting["download"] and not waiting["form"], waiting


def test_once_the_answer_is_there_the_form_stands_and_the_set_up_never_did(report):
    seen = report["delayedSeen"]
    assert not any(state["journey"] or state["download"] for state in seen), seen
    assert seen[0]["loading"] and seen[-1]["form"] and not seen[-1]["loading"], (seen[0], seen[-1])


def test_a_failed_first_read_keeps_the_loading_sentence_and_the_next_answer_brings_the_form(report):
    seen = report["failedSeen"]
    assert seen[0]["loading"] == GERMAN["bilder"]["laedt"], seen[0]
    assert not any(state["journey"] or state["download"] for state in seen), seen
    assert seen[-1]["form"], seen[-1]
    assert report["failedReads"] >= 2


def test_silence_a_read_that_fails_after_an_answer_leaves_the_form_standing(report):
    seen = report["afterAnswerSeen"]
    assert all(state["form"] for state in seen), seen


def test_silence_an_answer_without_a_model_shows_the_set_up_as_before(report):
    assert report["noProgram"]["journey"] and not report["noProgram"]["loading"], report["noProgram"]
    assert report["noProgram"]["journeyText"] == GERMAN["modell"]["reise_stand_programm_fehlt"]
    assert report["noProgram"]["download"] is True
    assert report["noModel"]["journey"], report["noModel"]
    assert report["noModel"]["journeyText"] == GERMAN["modell"]["reise_stand_programm_da"]
