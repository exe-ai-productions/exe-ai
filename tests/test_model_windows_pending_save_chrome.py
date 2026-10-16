"""The model and agent server windows, in a real browser: a value changed a
moment before the window closes is written, and the engine levers of the
model window are written lever by lever and read again after a run.

The windows wrote a number a beat after its last change, and the clock was
taken down with the window — a change made in the last 600 ms before closing
was gone at the next opening. The levers went out as the whole row from this
window's copy, so a lever a second window had moved was put back, and after
the end of a run the window kept the run's values. The real windows are built
as they ship (``tests/model_windows_page.py``).

Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import pytest

from tests.model_windows_page import BROWSER_TESTS_POSSIBLE, run_cases

pytestmark = pytest.mark.skipif(
    not BROWSER_TESTS_POSSIBLE, reason="no node or no frontend dependencies on this machine"
)

CASES = r"""
const report = {}
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const stub = window.__stub
const portField = () => document.querySelector('input[id$="-port"]')
const type = (field, text) => {
  field.focus()
  field.value = text
  field.dispatchEvent(new Event('input', { bubbles: true }))
  field.dispatchEvent(new Event('change', { bubbles: true }))
}
const open = async (which) => {
  scene.show = which
  for (let k = 0; k < 80 && !(portField() && portField().value); k += 1) await wait(50)
  await wait(300)
}
const close = async () => {
  scene.show = null
  await wait(300)
}
const patches = (key) => stub.calls.filter((c) => c.name === 'patch' && c.key === key).map((c) => c.values)
const switchFor = (word) =>
  [...document.querySelectorAll('button[role="switch"]')].find((b) =>
    (b.getAttribute('aria-label') || '').toLowerCase().includes(word))

// 1. The model window: a port typed, the window gone within 100 ms.
await open('modell')
report.model_before = portField().value
type(portField(), '8190')
await wait(40)
await close()
report.model_closed = { patches: patches('runnermodell'), stored: { ...stub.settings.runnermodell } }
await open('modell')
report.model_reopened = portField().value
await close()

// 2. The agent window: the same, on the slot's own key.
stub.calls.length = 0
await open('agent')
report.agent_before = portField().value
type(portField(), '8191')
await wait(40)
await close()
report.agent_closed = { patches: patches('agentenmodell'), stored: { ...stub.settings.agentenmodell } }
await open('agent')
report.agent_reopened = portField().value
await close()

// 3. Silence: opened and left, nothing typed, nothing written.
stub.calls.length = 0
await open('modell')
await wait(800)
await close()
await open('agent')
await wait(800)
await close()
report.nothing_typed = stub.calls.filter((c) => c.name === 'patch' || c.name === 'put').length

// 4. A second window moved one lever; this window flips another one.
stub.calls.length = 0
stub.settings.feineinstellungen = {}
await open('modell')
stub.settings.feineinstellungen = { festnageln: true }
const kv = switchFor('kv')
report.kv_found = Boolean(kv)
kv.click()
await wait(1400)
report.lever_calls = stub.calls
  .filter((c) => c.key === 'feineinstellungen')
  .map((c) => ({ name: c.name, values: c.values }))
report.lever_stored = { ...stub.settings.feineinstellungen }
await close()

// 5. Silence: a lever nobody moved is not sent.
stub.calls.length = 0
stub.settings.feineinstellungen = { festnageln: true, kv_cache: 'q8_0' }
await open('modell')
await wait(1200)
report.lever_silence = stub.calls.filter((c) => c.key === 'feineinstellungen').length
await close()

// 6. After the end of a run the levers are read again.
stub.calls.length = 0
stub.settings.feineinstellungen = {}
stub.runFein = { kv_cache: 'f16', moe_auf_cpu: false, festnageln: false }
stub.running.chat = true
await open('modell')
await wait(2600)
stub.settings.feineinstellungen = { kv_cache: 'q8_0' }
stub.running.chat = false
await wait(5200)
const kvAfter = switchFor('kv')
report.after_run_kv_on = kvAfter ? kvAfter.getAttribute('aria-checked') : null
report.after_run_writes = stub.calls.filter((c) => c.key === 'feineinstellungen').length
await close()

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    return run_cases(CASES)


def test_the_port_typed_before_the_model_window_closes_is_written(report):
    assert report["model_before"] == "8080"
    assert report["model_closed"]["patches"] == [{"port": 8190}], report["model_closed"]
    assert report["model_closed"]["stored"]["port"] == 8190


def test_the_reopened_model_window_shows_it(report):
    assert report["model_reopened"] == "8190"


def test_the_port_typed_before_the_agent_window_closes_is_written(report):
    assert report["agent_before"] == "8083"
    patches = report["agent_closed"]["patches"]
    assert len(patches) == 1 and patches[0]["port"] == 8191, report["agent_closed"]
    assert report["agent_closed"]["stored"]["port"] == 8191
    assert report["agent_reopened"] == "8191"


def test_silence_nothing_typed_nothing_written(report):
    """Opening a window and leaving it writes no value: the shipped values
    are not stored as choices, at the closing any more than at the clock."""
    assert report["nothing_typed"] == 0


def test_a_lever_moved_here_leaves_the_one_moved_elsewhere(report):
    assert report["kv_found"] is True
    assert report["lever_calls"] == [{"name": "patch", "values": {"kv_cache": "q8_0"}}], report[
        "lever_calls"
    ]
    assert report["lever_stored"] == {"festnageln": True, "kv_cache": "q8_0"}


def test_silence_levers_nobody_moved_are_not_sent(report):
    assert report["lever_silence"] == 0


def test_the_levers_are_read_again_when_a_run_has_ended(report):
    assert report["after_run_kv_on"] == "true"
    # Reading is not writing: what was stored by somebody else stays theirs.
    assert report["after_run_writes"] == 0
