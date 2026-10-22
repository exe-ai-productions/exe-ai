"""The window "New task" settles before it speaks, in a real browser.

The agent list and the answers for the two entries of the model row come over
the wire while the window is already open. The window used to say "No agents"
with the button "Agents" for the moment the list was on its way, then, with
the list in, "No model reachable" with the button "Models" for the moment the
answers were on their way, and finally the real rows — a window that jumped
twice and offered a wrong button on the way. Now the frame stands without rows
and without a button until all of it is in, and the content appears once.

The real window is built as shipped on the stub of ``tests/model_windows_page.py``,
which this file widens by the answers of the agent list and the model preview
(the shared file stays as it is); the list is delayed by 300 ms and the preview
by 1 s, and the page is measured every 50 ms. Skipped where there is no Chrome
or no node.
"""

from __future__ import annotations

import json
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

SHELL_IMPORTS = "  import AuftragStarten from '../../src/teile/AuftragStarten.svelte'\n"
SHELL_SCENES = "  <AuftragStarten bind:offen={scene.open} />\n"

STUB_METHODS = """stub.task = { agents: [{ name: 'recherche', tools: [] }], answer: { endpoint_id: 'deepseek', name: 'deepseek-chat' },
  agentsDelay: 300, answerDelay: 1000, agentsFail: false, answerFail: false, asked: [] }
const later = (ms, value, fail) => new Promise((done, broke) => setTimeout(() => (fail ? broke(new Error('down')) : done(value)), ms))
methods.agenten = () => later(stub.task.agentsDelay, copy(stub.task.agents), stub.task.agentsFail)
methods.laufmodell = (endpoint, needsTools) => {
  stub.task.asked.push({ endpoint, needsTools })
  return later(stub.task.answerDelay, copy(stub.task.answer), stub.task.answerFail)
}
"""

CASES_TEMPLATE = r"""
const stub = window.__stub
texte.katalog = germanTexts
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const text = (node) => (node ? node.textContent.replace(/\s+/g, ' ').trim() : '')

// What the window says right now: the head state, whether a button stands in
// the left corner of the foot, and where the task field starts.
const look = () => {
  const dialog = document.querySelector('.popup')
  if (!dialog) return { open: false }
  const body = text(dialog)
  const left = dialog.querySelector('.fusslinks')
  return {
    open: true,
    noAgents: body.includes(%(no_agents)s),
    noModel: body.includes(%(no_model)s),
    rows: dialog.querySelectorAll('.zeile').length,
    busy: Boolean(dialog.querySelector('[aria-busy="true"]')),
    cornerButtons: left ? [...left.querySelectorAll('button.button')].map(text) : [],
    fieldTop: Math.round(dialog.querySelector('textarea')?.getBoundingClientRect().top ?? -1),
  }
}
const key = (state) => JSON.stringify({ ...state, at: undefined, fieldTop: undefined })
const run = async (setup) => {
  scene.open = false
  await wait(300)
  setup()
  stub.task.asked.length = 0
  scene.open = true
  const frames = []
  const start = performance.now()
  while (performance.now() - start <= 2200) {
    const frame = { at: performance.now() - start, ...look() }
    if (frame.open) frames.push(frame)
    await wait(50)
  }
  const states = []
  for (const frame of frames) if (!states.length || key(states.at(-1)) !== key(frame)) states.push(frame)
  return { frames, states, last: frames.at(-1) }
}
const summary = (r) => ({
  untrueBeforeAnswers: r.frames.filter((f) => f.at < 1250).some((f) => f.noAgents || f.noModel || f.cornerButtons.length),
  changes: r.states.length - 1,
  last: { noAgents: r.last.noAgents, noModel: r.last.noModel, rows: r.last.rows, busy: r.last.busy, corner: r.last.cornerButtons },
  fieldMoved: new Set(r.frames.filter((f) => f.at >= 300 && f.fieldTop > 0).map((f) => f.fieldTop)).size,
})
const report = {}

report.normal = summary(await run(() => {}))
report.noAgents = summary(await run(() => { stub.task.agents = [] }))
stub.task.agents = [{ name: 'recherche', tools: [] }]
report.noModel = summary(await run(() => { stub.task.answer = { endpoint_id: '', name: '' } }))
stub.task.answer = { endpoint_id: 'deepseek', name: 'deepseek-chat' }
report.previewFails = summary(await run(() => { stub.task.answerFail = true }))
stub.task.answerFail = false
report.agentsFail = summary(await run(() => { stub.task.agentsFail = true }))
stub.task.agentsFail = false

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


# The window's own sentences, as the German catalogue words them; they stand
# outside the script text so that the script reads as plain English.
CASES = CASES_TEMPLATE % {"no_agents": json.dumps("Keine Agenten"), "no_model": json.dumps("Kein Modell erreichbar")}


@pytest.fixture(scope="module")
def report() -> dict:
    for anchor in ("  import { scene } from './scene.svelte.js'\n", "  {#if scene.show === 'modell'}"):
        assert anchor in harness.SHELL, f"the shared harness changed, widen it again: {anchor!r}"
    assert "export const setSessionKey = () => {}\n" in harness.API_STUB
    shell = harness.SHELL.replace(
        "  import { scene } from './scene.svelte.js'\n", SHELL_IMPORTS + "  import { scene } from './scene.svelte.js'\n"
    ).replace("  {#if scene.show === 'modell'}", SHELL_SCENES + "  {#if scene.show === 'modell'}")
    stub = harness.API_STUB.replace(
        "export const setSessionKey = () => {}\n", STUB_METHODS + "export const setSessionKey = () => {}\n"
    )
    scene = harness.SCENE_JS.replace("{ show: null }", "{ show: null, open: false }")
    with (
        mock.patch.object(harness, "SHELL", shell),
        mock.patch.object(harness, "API_STUB", stub),
        mock.patch.object(harness, "SCENE_JS", scene),
    ):
        return run_cases(CASES)


def test_nothing_untrue_is_said_and_no_button_stands_until_everything_is_in(report):
    assert report["normal"]["untrueBeforeAnswers"] is False


def test_the_window_changes_once_from_the_empty_frame_to_its_rows(report):
    normal = report["normal"]
    assert normal["changes"] == 1
    assert normal["last"] == {"noAgents": False, "noModel": False, "rows": 2, "busy": False, "corner": []}


def test_the_task_field_does_not_move_more_than_the_rows_make_it(report):
    # One position while the frame waits, one when the rows have come (the
    # first 300 ms are the window opening itself): not one for "No agents",
    # another for "No model" and a third for the rows.
    assert report["normal"]["fieldMoved"] == 2


def test_no_agents_is_said_only_when_the_list_says_so(report):
    case = report["noAgents"]
    assert case["untrueBeforeAnswers"] is False
    assert case["last"]["noAgents"] is True
    assert case["last"]["corner"] == ["Agenten"]


def test_no_model_is_said_only_when_the_answers_say_so(report):
    case = report["noModel"]
    assert case["untrueBeforeAnswers"] is False
    assert case["last"]["noModel"] is True
    assert case["last"]["corner"] == ["Modelle"]


def test_a_failed_question_does_not_hold_the_window_in_waiting(report):
    for name in ("previewFails", "agentsFail"):
        assert report[name]["last"]["busy"] is False, name
        assert report[name]["changes"] == 1, name
