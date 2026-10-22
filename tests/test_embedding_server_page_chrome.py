"""The embedding server's page in a real browser, under its model card: a row
of two columns, "Memory" on the left (the window, the layers, the CPU threads
and the wired memory of the planned start) and "Advanced" on the right (the
pooling kind, the batch size, the memory lock, the parallel requests and the
port, in the order drawn) — and nothing of the chat servers' cache rows, no
card "Network". A changed value goes to ``PATCH /settings/global/embedding``
and stands again after the page is built anew; while the server runs every
field is shut.

The real page is built as shipped on the stub of ``tests/model_windows_page.py``,
which this file widens by the answers of the embedding server and the write of
its row (the shared file stays as it is). Skipped where there is no Chrome or
no node.
"""

from __future__ import annotations

import re
from unittest import mock

import pytest

from tests import model_windows_page as harness
from tests.model_windows_page import BROWSER_TESTS_POSSIBLE, ROOT, run_cases

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        not BROWSER_TESTS_POSSIBLE, reason="no node or no frontend dependencies on this machine"
    ),
]

TEILE = ROOT / "frontend" / "src" / "teile"

SHELL_IMPORTS = "  import Einbettungsserver from '../../src/teile/Einbettungsserver.svelte'\n"
SHELL_SCENES = "  {#if scene.show === 'embed'}<Einbettungsserver />{/if}\n"

# The service's answer of the embedding server and the write of its row, kept in the page.
STUB_METHODS = """stub.embedding = { context: 2048, batch: 2048, pooling: '', layers: null, threads: 0, mlock: false, parallel: null, model: 'embed.gguf', port: 8081 }
stub.embRunning = false
methods.einbettungAuskunft = async () => ({
  ...program, ordner: '/m', modelle: [{ name: 'embed.gguf', groesse_gb: 0.6 }, { name: 'other.gguf', groesse_gb: 1.2 }],
  laeuft: stub.embRunning, modell: 'embed.gguf', selected_model: 'embed.gguf',
  port: stub.embedding.port, belegt_gb: null, unknown_architecture: null,
  context: stub.embedding.context, batch: stub.embedding.batch, pooling: stub.embedding.pooling,
  layers: stub.embedding.layers, threads: stub.embedding.threads, mlock: stub.embedding.mlock, parallel: stub.embedding.parallel,
})
stub.patchDelay = 0
stub.failNext = 0
methods.einstellungMischen = async (bereich, schluessel, wert) => {
  stub.calls.push({ name: 'patch', bereich, key: schluessel, sent: JSON.parse(JSON.stringify(wert)) })
  if (stub.patchDelay) await new Promise((done) => setTimeout(done, stub.patchDelay))
  if (stub.failNext > 0) { stub.failNext -= 1; throw new Error('refused') }
  if (schluessel === 'embedding') Object.assign(stub.embedding, wert)
  return { wert }
}
methods.speicherBlick = async () => ({ wired_limit_gb: 20, gesamt_gb: 32 })
"""

CASES = r"""
const stub = window.__stub
texte.katalog = germanTexts
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const text = (node) => node.textContent.replace(/\s+/g, ' ').trim()
const rect = (node) => { const r = node.getBoundingClientRect(); return { top: Math.round(r.top), left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width) } }
const cards = () => [...document.querySelectorAll('section.abschnitt')]
const headOf = (card) => text(card.querySelector(':scope > .kopf'))
const cardByHead = (name) => cards().find((card) => headOf(card) === name)
const labels = (card) => [...card.querySelectorAll('.karte > .zeile')].map((row) => {
  const label = row.querySelector('label, .name, .regelname, .zahlname, .wiredname')
  return label ? text(label) : text(row)
})
const mount = async (running) => {
  scene.show = null
  await wait(200)
  stub.embRunning = running
  scene.show = 'embed'
  for (let k = 0; k < 100 && !cardByHead('Speicher'); k += 1) await wait(100)
  await wait(500)
}
const report = {}

await mount(false)
const memory = cardByHead('Speicher'), advanced = cardByHead('Erweitert')
report.heads = cards().map(headOf)
report.memory = labels(memory)
report.advanced = labels(advanced)
report.sides = { memory: rect(memory), advanced: rect(advanced) }
report.network = Boolean(cardByHead('Netzwerk'))
report.defaults = {
  pooling: text(advanced.querySelector('button[role="combobox"]')),
  mlock: advanced.querySelector('button[role="switch"]').getAttribute('aria-checked'),
  batch: advanced.querySelector('input[id$="-batch"]')?.value,
  port: advanced.querySelector('input[id$="-port"]')?.value,
}
report.switches = [...advanced.querySelectorAll('button[role="switch"]')].map((b) => b.getAttribute('aria-label'))
report.wired = text(memory.querySelector('.wired'))

// The choices of the pooling picker.
advanced.querySelector('button[role="combobox"]').click()
await wait(400)
report.options = [...document.querySelectorAll('[role="option"]')].map(text)
// Choosing "Mean" and turning the memory lock on.
;[...document.querySelectorAll('[role="option"]')].find((o) => text(o) === 'Mean').click()
await wait(300)
advanced.querySelector('button[role="switch"]').click()
await wait(1200)
report.patches = stub.calls.filter((c) => c.name === 'patch').map((c) => ({ key: c.key, sent: c.sent }))

// The page built anew reads the stored values again.
await mount(false)
const advanced2 = cardByHead('Erweitert')
report.again = {
  pooling: text(advanced2.querySelector('button[role="combobox"]')),
  mlock: advanced2.querySelector('button[role="switch"]').getAttribute('aria-checked'),
}

// The batch is held to the window on the screen and never cut in what is stored.
const commit = async (input, value) => {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
  input.focus()
  set.call(input, String(value))
  input.dispatchEvent(new Event('input', { bubbles: true }))
  input.dispatchEvent(new Event('change', { bubbles: true }))
  input.blur()
  await wait(150)
}
const windowField = () => cardByHead('Speicher').querySelector('.kopfzeile input')
const batchField = () => document.querySelector('input[id$="-batch"]')
await mount(false)
stub.calls.length = 0
await commit(windowField(), 8192)
await commit(batchField(), 8192)
await wait(1000)
const afterRaise = stub.calls.filter((c) => c.name === 'patch').length
await commit(windowField(), 2048)
await wait(1000)
report.windowDown = {
  shown: batchField().value,
  stored: stub.embedding.batch,
  sent: stub.calls.filter((c) => c.name === 'patch').slice(afterRaise).map((c) => Object.keys(c.sent)),
}
await commit(windowField(), 8192)
await wait(300)
report.windowUp = { shown: batchField().value }
// Put the stand back for the next cases.
stub.embedding.context = 2048; stub.embedding.batch = 2048

// A write that failed takes back what it carried and not what was touched after it.
stub.embedding.pooling = ''; stub.embedding.mlock = false
await mount(false)
stub.calls.length = 0
stub.patchDelay = 500
stub.failNext = 1
const advancedNow = () => cardByHead('Erweitert')
advancedNow().querySelector('button[role="combobox"]').click()
await wait(300)
;[...document.querySelectorAll('[role="option"]')].find((o) => text(o) === 'CLS').click()
await wait(800)
advancedNow().querySelector('button[role="switch"]').click()
await wait(3000)
stub.patchDelay = 0
report.rollback = {
  pooling: text(advancedNow().querySelector('button[role="combobox"]')),
  mlock: advancedNow().querySelector('button[role="switch"]').getAttribute('aria-checked'),
  storedPooling: stub.embedding.pooling,
  storedMlock: stub.embedding.mlock,
  sent: stub.calls.filter((c) => c.name === 'patch').map((c) => Object.keys(c.sent).sort()),
}
stub.embedding.pooling = ''; stub.embedding.mlock = false

// While the server runs, every field is shut.
await mount(true)
const shut = (card) => [...card.querySelectorAll('input, button[role="switch"], button[role="combobox"]')]
  .map((node) => ({ id: node.id || node.getAttribute('aria-label'), shut: node.disabled || node.readOnly || node.getAttribute('aria-disabled') === 'true' }))
report.shut = { memory: shut(cardByHead('Speicher')), advanced: shut(cardByHead('Erweitert')) }

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


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
    with mock.patch.object(harness, "SHELL", shell), mock.patch.object(harness, "API_STUB", stub):
        return run_cases(CASES)


def test_the_page_has_the_two_cards_memory_and_advanced_and_no_network_card(report):
    assert report["memory"] and report["advanced"]
    assert "Speicher" in report["heads"] and "Erweitert" in report["heads"]
    assert report["network"] is False
    assert report["heads"].index("Speicher") < report["heads"].index("Erweitert")


def test_memory_stands_left_and_advanced_right_with_their_tops_flush(report):
    memory, advanced = report["sides"]["memory"], report["sides"]["advanced"]
    assert memory["left"] < advanced["left"] and memory["right"] <= advanced["left"], report["sides"]
    assert abs(memory["top"] - advanced["top"]) <= 1, report["sides"]
    assert abs(memory["width"] - advanced["width"]) <= 2, report["sides"]


def test_the_memory_card_holds_the_window_the_layers_the_threads_and_the_wired_memory(report):
    assert report["memory"] == ["Kontext", "GPU-Layer", "CPU-Threads", "Wired Memory"]
    # The plan of the model that is chosen: its file and the window.
    assert "GB von" in report["wired"], report["wired"]


def test_the_advanced_card_holds_its_rows_in_the_order_drawn(report):
    assert report["advanced"] == ["Pooling", "Stapelgröße", "Memory Lock", "Gleichzeitige Anfragen", "Leerlaufzeit", "Port"]
    # The cache rows of the chat servers are not here, nor the preload.
    assert report["switches"] == ["Memory Lock"]


def test_pooling_offers_default_mean_cls_and_last_and_stands_on_default_from_the_start(report):
    assert report["options"] == ["Standard", "Mean", "CLS", "Last"]
    assert report["defaults"]["pooling"] == "Standard"
    assert report["defaults"]["mlock"] == "false"
    assert report["defaults"]["batch"] == "2048" and report["defaults"]["port"] == "8081"


def test_the_window_runs_in_steps_from_2048_to_32768():
    source = (TEILE / "Einbettungsserver.svelte").read_text(encoding="utf-8")
    assert "const kontextstufen = [2048, 4096, 8192, 16384, 32768]" in source
    assert "kontextMin={2048}" in source and "kontextMax={32768}" in source


def test_a_changed_value_goes_to_the_embedding_row_and_only_what_changed(report):
    sent = {}
    for patch in report["patches"]:
        assert patch["key"] == "embedding"
        sent.update(patch["sent"])
    assert sent == {"pooling": "mean", "mlock": True}, report["patches"]


def test_the_values_stand_again_when_the_page_is_built_anew(report):
    assert report["again"] == {"pooling": "Mean", "mlock": "true"}


def test_the_batch_is_held_to_the_window_on_the_screen_and_never_cut_in_what_is_stored(report):
    down = report["windowDown"]
    # Window lowered to 2048 with a batch of 8192: the field shows 2048, the stored 8192 stays,
    # and nothing about the batch is written for the lowering.
    assert down["shown"] == "2048" and down["stored"] == 8192, down
    assert all("batch" not in keys for keys in down["sent"]), down
    # The window raised again finds the batch it had.
    assert report["windowUp"]["shown"] == "8192"


def test_a_failed_write_takes_back_what_it_carried_and_not_what_was_touched_after_it(report):
    rollback = report["rollback"]
    assert rollback["pooling"] == "Standard" and rollback["storedPooling"] == "", rollback
    assert rollback["mlock"] == "true" and rollback["storedMlock"] is True, rollback
    # The first write (the pooling) was refused; the next carried the lock alone.
    assert rollback["sent"][0] == ["pooling"] and rollback["sent"][-1] == ["mlock"], rollback


def test_while_the_server_runs_every_field_is_shut(report):
    fields = report["shut"]["memory"] + report["shut"]["advanced"]
    assert len(fields) >= 8, fields
    assert all(field["shut"] for field in fields), [f for f in fields if not f["shut"]]


def test_the_other_server_pages_keep_their_cache_rows_and_neither_pooling_nor_batch():
    """Silence: the advanced rows of the model, agent and speech servers are
    as they were — the new levers are the embedding page's alone."""
    regler = (TEILE / "Serverregler.svelte").read_text(encoding="utf-8")
    assert "kvZeilen = true" in regler and "pooling = $bindable(null)" in regler and "batch = $bindable(null)" in regler
    for name in ("Modellserver", "Agentserver", "Sprachserver"):
        source = (TEILE / f"{name}.svelte").read_text(encoding="utf-8")
        assert not re.search(r"\b(pooling|poolingauswahl|batch|kvZeilen)\b", source), name
    # The speech server keeps the card "Network" next to its memory.
    assert 'teil="netzwerk"' in (TEILE / "Sprachserver.svelte").read_text(encoding="utf-8")
