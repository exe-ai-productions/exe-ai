"""The two columns of a server page end on one line at the bottom, measured in
a real browser.

Every server page that stands in rows of two columns (`Serverreihe.svelte`) is
built as shipped and drawn in headless Chrome on the stand-in of
`tests/model_windows_page.py`, with the German texts the window shows. For
every row the lowest card of the left column and the lowest card of the right
column end on the same line (1 px for rounding); the tops stay on one line too.
Under the break of 900 px the columns stand one under the other and nothing is
measured there.

Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

from unittest import mock

import pytest

from tests import model_windows_page

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        not model_windows_page.BROWSER_TESTS_POSSIBLE,
        reason="no node or no frontend dependencies on this machine",
    ),
]

# The speech page stays last: it does not leave the document when the scene is cleared,
# and every page after it would be measured with its rows.
PAGES = ["modell", "agent", "einbettung", "bild", "sprache"]

MEASURE = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
window.texte.katalog = window.germanTexts
const isCard = (e) => {
  const cs = getComputedStyle(e)
  return cs.boxShadow.includes('inset') && cs.borderRadius === '9px' && e.tagName !== 'BUTTON'
    && e.getBoundingClientRect().height > 40
}
const lowest = (col) => {
  const cards = [...col.querySelectorAll('*')].filter(isCard)
  return cards.length ? Math.max(...cards.map((c) => c.getBoundingClientRect().bottom)) : null
}
const topOf = (col) => {
  const cards = [...col.querySelectorAll('*')].filter(isCard)
  return cards.length ? Math.min(...cards.map((c) => c.getBoundingClientRect().top)) : null
}
const round = (n) => (n == null ? null : +n.toFixed(2))
// The height of the rows of the lowest section of a column, and whether any section of the column
// carries a weight (those columns spread the height over their rows by the weights, as before).
const rowHeights = (col) => {
  const last = col.querySelector(':scope > .abschnitt:last-child')
  const rows = last ? [...last.querySelectorAll(':scope > .karte > .zeile')] : []
  return rows.map((r) => round(r.getBoundingClientRect().height))
}
const weighted = (col) => Boolean(col.querySelector(':scope > .abschnitt.weighted'))
const out = { width: innerWidth }
for (const name of %(pages)s) {
  scene.show = name
  await wait(2000)
  const rows = []
  for (const box of document.querySelectorAll('.reihe')) {
    const [left, right] = [...box.children]
    if (!left || !right) continue
    const a = left.getBoundingClientRect()
    const b = right.getBoundingClientRect()
    rows.push({
      stacked: a.bottom <= b.top + 1,
      leftBottom: round(lowest(left)), rightBottom: round(lowest(right)),
      leftTop: round(topOf(left)), rightTop: round(topOf(right)),
      columnBottom: round(a.bottom),
      leftWeighted: weighted(left), rightWeighted: weighted(right),
      leftRows: rowHeights(left), rightRows: rowHeights(right),
    })
  }
  // The same rows with the growth of the lowest section switched off: their natural height.
  const off = document.createElement('style')
  off.textContent = '.abschnitt:not(.weighted) { flex-grow: 0 !important; }'
  document.head.appendChild(off)
  await wait(300)
  document.querySelectorAll('.reihe').forEach((box, i) => {
    const [left, right] = [...box.children]
    if (!rows[i]) return
    rows[i].leftNatural = rowHeights(left)
    rows[i].rightNatural = rowHeights(right)
  })
  off.remove()
  out[name] = rows
  scene.show = null
  await wait(300)
}
document.getElementById('ergebnis').textContent = JSON.stringify(out)
"""


def _run(width: int) -> dict:
    """The pages in a window `width` px wide; the shell is as wide as the window, up to 1400."""
    imports = (
        "  import Einbettungsserver from '../../src/teile/Einbettungsserver.svelte'\n"
        "  import Sprachserver from '../../src/teile/Sprachserver.svelte'\n"
        "  import Bildserver from '../../src/teile/Bildserver.svelte'\n"
    )
    scenes = (
        "  {#if scene.show === 'einbettung'}<Einbettungsserver />{/if}\n"
        "  {#if scene.show === 'sprache'}<Sprachserver />{/if}\n"
        "  {#if scene.show === 'bild'}<Bildserver />{/if}\n"
    )
    anchors = (
        "  import { scene } from './scene.svelte.js'\n",
        "  {#if scene.show === 'modell'}",
        '<div style="width: 1100px; margin: 0 auto;">',
    )
    for anchor in anchors:
        assert anchor in model_windows_page.SHELL, f"the shared harness changed, widen it again: {anchor!r}"
    shell = (
        model_windows_page.SHELL
        .replace(anchors[0], imports + anchors[0])
        .replace(anchors[1], scenes + anchors[1])
        .replace(anchors[2], '<div style="width: min(1400px, 100vw); margin: 0 auto;">')
    )
    with mock.patch.object(model_windows_page, "SHELL", shell):
        return model_windows_page.run_cases(MEASURE % {"pages": repr(PAGES)}, window_size=f"{width},1000")


@pytest.fixture(scope="module")
def wide() -> dict:
    return _run(1400)


@pytest.fixture(scope="module")
def narrow() -> dict:
    return _run(800)


def test_the_lowest_cards_of_two_columns_end_on_one_line(wide):
    for name in PAGES:
        rows = wide[name]
        assert rows, f"{name}: no row of two columns was measured"
        for number, row in enumerate(rows):
            assert not row["stacked"], (name, number, row)
            assert row["leftBottom"] is not None and row["rightBottom"] is not None, (name, number, row)
            assert abs(row["leftBottom"] - row["rightBottom"]) <= 1, (name, number, row)


def test_the_lowest_card_ends_on_the_bottom_of_its_column(wide):
    """The shorter column's last card grows to the foot of the column, it does not stop above it."""
    for name in PAGES:
        for number, row in enumerate(wide[name]):
            assert row["columnBottom"] - max(row["leftBottom"], row["rightBottom"]) <= 1, (name, number, row)


def test_what_stands_in_a_grown_card_stays_at_the_top(wide):
    """The card grows, its rows do not: in a column without weights every row of the lowest card
    is as high as it is without the growth, so the extra height is the empty foot of the card."""
    seen = 0
    for name in PAGES:
        for number, row in enumerate(wide[name]):
            for side in ("left", "right"):
                if row[f"{side}Weighted"] or not row[f"{side}Rows"]:
                    continue
                seen += 1
                grown, natural = row[f"{side}Rows"], row[f"{side}Natural"]
                assert len(grown) == len(natural), (name, number, side, row)
                assert all(abs(g - n) <= 1 for g, n in zip(grown, natural, strict=True)), (name, number, side, row)
    assert seen, "no column without weights was measured"


def test_the_tops_of_the_cards_stay_on_one_line(wide):
    for name in PAGES:
        for number, row in enumerate(wide[name]):
            assert abs(row["leftTop"] - row["rightTop"]) <= 0.5, (name, number, row)


def test_under_the_break_the_columns_stand_one_under_the_other_and_nothing_is_asked_of_them(narrow):
    """Silence probe: below 900 px the rule does not apply; the rows are stacked, so there is
    no common bottom to hold, and the run counts the rows it saw."""
    assert narrow["width"] < 900
    for name in PAGES:
        rows = narrow[name]
        assert rows, f"{name}: no row was measured"
        assert all(row["stacked"] for row in rows), (name, rows)
