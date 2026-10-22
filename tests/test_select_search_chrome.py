"""The open list of a selection field with a search field stands whole rows
under the search field, in a real browser.

``Auswahlfeld.svelte`` is built as shipped on the stub of
``tests/image_window_page.py``. The list opens on the chosen entry; where that
entry lies far down, the walk to it used to stop in the middle of a row, and
that row stood cut through right under the search field, reading as lying
beneath it. Skipped where there is no Chrome or no node.
"""

from __future__ import annotations

from unittest import mock

import pytest

from tests import image_window_page as harness
from tests.image_window_page import needs_browser, run_cases

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    needs_browser,
]

SHELL = """<script>
  import Auswahlfeld from '../../src/teile/Auswahlfeld.svelte'
  import { scene } from './scene.svelte.js'
  const eintraege = Array.from({ length: 14 }, (_, k) => ({
    wert: 'model-' + k, text: 'model-' + k + '.safetensors · 0 GB', group: 'Without family',
  }))
  let wert = $state('')
  window.__choose = (k) => { wert = k === null ? '' : 'model-' + k }
</script>

<div style="width: 340px; margin: 40px auto 0;">
  {#if scene.show === 'down'}
    <Auswahlfeld bind:wert {eintraege} search searchLabel="Search" beschriftung="Model" />
  {/if}
  {#if scene.show === 'plain'}
    <Auswahlfeld bind:wert {eintraege} beschriftung="Model" />
  {/if}
</div>
{#if scene.show === 'up'}
  <div style="width: 340px; margin: 0 auto; position: absolute; top: 900px; left: 0; right: 0;">
    <Auswahlfeld bind:wert {eintraege} search searchLabel="Search" beschriftung="Model" />
  </div>
{/if}
"""

CASES = r"""
const field = () => document.querySelector('button[role="combobox"]')
const box = (node) => { const r = node.getBoundingClientRect(); return { top: r.top, bottom: r.bottom } }
const measure = () => {
  const klapp = document.querySelector('.klapp:popover-open')
  const list = klapp.querySelector('.liste')
  const search = klapp.querySelector('.search')
  const edge = box(list)
  const first = [...list.children].find((row) => row.getBoundingClientRect().bottom > edge.top + 0.5)
  const chosen = [...list.querySelectorAll('button')].find((b) => b.querySelector('.haken svg'))
  const field = box(document.querySelector('button[role="combobox"]'))
  return {
    up: klapp.getBoundingClientRect().bottom <= field.top + 1,
    cut: Math.max(0, edge.top - box(first).top),
    clearOfSearch: search ? box(search).bottom <= box(first).top + 0.5 : null,
    atEnd: list.scrollTop >= list.scrollHeight - list.clientHeight - 1,
    chosenWhole: chosen ? box(chosen).top >= edge.top - 0.5 && box(chosen).bottom <= edge.bottom + 0.5 : null,
    gap: search ? Math.round(box(list.querySelector('button, .group-name')).top - box(search).bottom) : null,
    scrolled: list.scrollTop,
    endRoom: list.style.paddingBottom,
  }
}
const run = async (what, choose) => {
  window.scene.show = ''
  await wait(300)
  window.__choose(choose)
  window.scene.show = what
  await wait(500)
  field().click()
  await wait(700)
  const result = measure()
  field().click()
  await wait(300)
  return result
}
report.rows = {}
for (const k of [null, 0, 3, 6, 7, 8, 9, 10, 11, 13]) {
  report.rows['down-' + k] = await run('down', k)
  report.rows['up-' + k] = await run('up', k)
}
report.plain = await run('plain', 7)

// The arrow keys walk down to the end and back: no step leaves a row cut under the search field.
window.scene.show = ''
await wait(300)
window.__choose(null)
window.scene.show = 'down'
await wait(500)
field().click()
await wait(700)
const input = document.querySelector('.klapp:popover-open .search')
report.walk = []
for (const key of [...Array(16).fill('ArrowDown'), ...Array(16).fill('ArrowUp')]) {
  input.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }))
  await wait(120)
  const list = document.querySelector('.klapp:popover-open .liste')
  const edge = list.getBoundingClientRect()
  const first = [...list.children].find((row) => row.getBoundingClientRect().bottom > edge.top + 0.5)
  const near = list.querySelector('button.dran').getBoundingClientRect()
  report.walk.push({
    key, cut: Math.max(0, edge.top - first.getBoundingClientRect().top),
    whole: near.top >= edge.top - 0.5 && near.bottom <= edge.bottom + 0.5,
  })
}
"""


@pytest.fixture(scope="module")
def report() -> dict:
    entry = harness.ENTRY_JS
    with mock.patch.object(harness, "SHELL", SHELL), mock.patch.object(harness, "ENTRY_JS", entry):
        return run_cases(CASES, limit=240.0, window="900,1000")


ROWS = [f"{where}-{'null' if k is None else k}" for k in (None, 0, 3, 6, 7, 8, 9, 10, 11, 13) for where in ("down", "up")]


def test_the_lists_open_in_both_directions(report):
    assert not report["rows"]["down-7"]["up"] and report["rows"]["up-7"]["up"], report["rows"]


@pytest.mark.parametrize("name", ROWS)
def test_no_row_stands_cut_through_under_the_search_field(report, name):
    row = report["rows"][name]
    assert row["clearOfSearch"] is True, row
    assert row["cut"] <= 0.5, row


@pytest.mark.parametrize("name", ROWS)
def test_the_chosen_entry_stays_whole_in_the_list(report, name):
    row = report["rows"][name]
    assert row["chosenWhole"] in (True, None), row


def test_walking_with_the_arrow_keys_never_cuts_a_row_or_the_entry_walked_to(report):
    assert len(report["walk"]) == 32
    for step in report["walk"]:
        assert step["cut"] <= 0.5 and step["whole"], step


def test_silence_a_list_at_rest_keeps_its_gap_under_the_search_field(report):
    # Nothing chosen: the list stands at its top, the gap is the one it always had.
    assert report["rows"]["down-null"]["gap"] == 4, report["rows"]["down-null"]


def test_silence_a_list_without_a_search_field_opens_as_before(report):
    row = report["plain"]
    assert row["chosenWhole"] is True, row
    # Nothing is added below the last entry of a list without a search field.
    assert row["endRoom"] == "", row
