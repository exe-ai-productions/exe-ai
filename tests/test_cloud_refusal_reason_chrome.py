"""A provider that refuses the check says why, in the table and in its card, in
a real browser.

``ModelleCloud.svelte`` is built as shipped on the harness of
``tests/test_cloud_not_responding_chrome.py``, with the answers of the service
made up in the page: a provider whose key was refused with a long sentence, one
with a short sentence, one that does not answer at all (no sentence), one that
answers but carries a sentence from before, and one whose key is missing. The
page reports what stands under the row of each in the table and under the head
of its card.
"""

from __future__ import annotations

from unittest import mock

import pytest

from tests import test_cloud_not_responding_chrome as harness

pytestmark = harness.pytestmark

LONG = (
    "Incorrect API key provided: sk-inval***. You can find your API key at the provider's "
    "page for keys, and you have to write it exactly as shown there, without a space."
)
SHORT = "Please pass a valid API key."
STALE = "A sentence from before."

DATA = """const all = [
  { ...base, id: 'longone/m', name: 'm', anbieter: 'longone', anbieter_name: 'Longone', erreichbar: false,
    schluessel_env: 'LONGONE_API_KEY', schluessel_gesetzt: true, grund: %(long)r },
  { ...base, id: 'shortone/m', name: 'm', anbieter: 'shortone', anbieter_name: 'Shortone', erreichbar: false,
    schluessel_env: 'SHORTONE_API_KEY', schluessel_gesetzt: true, grund: %(short)r },
  { ...base, id: 'silent/m', name: 'm', anbieter: 'silent', anbieter_name: 'Silent', erreichbar: false,
    schluessel_env: 'SILENT_API_KEY', schluessel_gesetzt: true, grund: null },
  { ...base, id: 'fine/m', name: 'm', anbieter: 'fine', anbieter_name: 'Fine', erreichbar: true,
    schluessel_env: 'FINE_API_KEY', schluessel_gesetzt: true, angeheftet: true, grund: %(stale)r },
  { ...base, id: 'nokey/m', name: 'm', anbieter: 'nokey', anbieter_name: 'Nokey', erreichbar: false,
    schluessel_env: 'NOKEY_API_KEY', schluessel_gesetzt: false, grund: null },
]
""" % {"long": LONG, "short": SHORT, "stale": STALE}

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const page = () => document.getElementById('seite')
const text = (node) => (node?.textContent || '').replace(/\s+/g, ' ').trim()
const look = (node) => getComputedStyle(node)
const px = (value) => Math.round(parseFloat(value) * 10) / 10
const probe = (token) => {
  const node = document.createElement('i')
  node.style.color = `var(${token})`
  document.body.appendChild(node)
  const value = getComputedStyle(node).color
  node.remove()
  return value
}
for (let k = 0; k < 60 && page().querySelectorAll('[role=row].line').length < 5; k += 1) await wait(100)
if (page().querySelectorAll('[role=row].line').length < 5) throw new Error('the page did not render the providers')
await wait(600)
const lines = Array.from(page().querySelectorAll('[role=row].line'))
const lineOf = (name) => lines.find((row) => text(row.querySelector('.name .text')) === name)
const measure = (node) => {
  if (!node) return null
  const box = node.getBoundingClientRect()
  return {
    text: text(node), size: px(look(node).fontSize), quiet: look(node).color === probe('--text-leise'),
    wraps: look(node).whiteSpace === 'normal', cut: node.scrollWidth > node.clientWidth + 1,
    height: Math.round(box.height), lineHeight: px(look(node).lineHeight === 'normal' ? parseFloat(look(node).fontSize) * 1.2 : look(node).lineHeight),
  }
}
const report = { table: {}, head: {} }
for (const name of ['Longone', 'Shortone', 'Silent', 'Fine', 'Nokey']) {
  const row = lineOf(name)
  const reason = row.querySelector('.reason')
  const state = row.querySelector('.state')
  const box = row.getBoundingClientRect()
  report.table[name] = {
    reason: measure(reason), state: text(state), rowHeight: Math.round(box.height),
    below: reason ? reason.getBoundingClientRect().top >= state.getBoundingClientRect().bottom - 1 : null,
    insideRow: reason ? box.top <= reason.getBoundingClientRect().top && reason.getBoundingClientRect().bottom <= box.bottom + 1 : null,
  }
  row.click()
  await wait(500)
  const head = page().querySelector('.provider-head')
  const sentence = page().querySelector('.reason-row .reason')
  report.head[name] = {
    reason: measure(sentence),
    below: sentence ? sentence.getBoundingClientRect().top >= head.getBoundingClientRect().bottom - 1 : null,
    state: text(page().querySelector('.provider-head .state-word')),
  }
}
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def measured() -> dict:
    entry = harness.ENTRY_JS
    start = entry.index("const all = [")
    end = entry.index("zustand.modelle")
    entry = entry[:start] + DATA + entry[end:]
    with mock.patch.object(harness, "ENTRY_JS", entry), mock.patch.object(harness, "CASES", CASES):
        return harness._run_case()


@pytest.mark.parametrize(("name", "sentence"), [("Longone", LONG), ("Shortone", SHORT)])
def test_the_sentence_of_the_provider_stands_whole_under_its_row_in_the_table(measured, name, sentence):
    row = measured["table"][name]
    assert row["reason"]["text"] == sentence, row
    assert row["reason"]["wraps"] and not row["reason"]["cut"], row
    assert row["reason"]["size"] == 12.5 and row["reason"]["quiet"], row
    assert row["below"] and row["insideRow"], row


def test_a_long_sentence_takes_more_than_one_line_and_the_row_grows_with_it(measured):
    long, short = measured["table"]["Longone"], measured["table"]["Shortone"]
    assert long["reason"]["height"] > short["reason"]["height"], (long, short)
    assert long["rowHeight"] > short["rowHeight"] > measured["table"]["Silent"]["rowHeight"], measured["table"]


@pytest.mark.parametrize(("name", "sentence"), [("Longone", LONG), ("Shortone", SHORT)])
def test_the_card_of_the_provider_carries_the_same_sentence_under_its_head(measured, name, sentence):
    head = measured["head"][name]
    assert head["reason"]["text"] == sentence, head
    assert head["reason"]["wraps"] and not head["reason"]["cut"], head
    assert head["reason"]["size"] == 12.5 and head["reason"]["quiet"] and head["below"], head


@pytest.mark.parametrize("name", ["Silent", "Nokey", "Fine"])
def test_silence_without_a_sentence_or_with_an_answering_provider_there_is_no_second_line(measured, name):
    assert measured["table"][name]["reason"] is None, measured["table"][name]
    assert measured["head"][name]["reason"] is None, measured["head"][name]


def test_silence_a_row_without_a_sentence_keeps_the_height_it_had(measured):
    assert measured["table"]["Silent"]["rowHeight"] == measured["table"]["Fine"]["rowHeight"], measured["table"]


def test_the_phone_shows_the_sentence_under_the_state_line_of_the_same_group():
    """The phone page is read at its source, like its neighbours: the sentence
    is one line of the group that holds the state, only for a provider that is
    not reachable and has one."""
    from pathlib import Path

    source = (Path(harness.FRONTEND) / "src" / "phone" / "cloud" / "ProviderView.svelte").read_text(encoding="utf-8")
    group = source.split("<Group>", 1)[1].split("</Group>", 1)[0]
    state = group.index("status.nicht_erreichbar")
    sentence = group.index("{#if !house.erreichbar && house.grund}")
    assert state < sentence and "<Line label={house.grund} />" in group
