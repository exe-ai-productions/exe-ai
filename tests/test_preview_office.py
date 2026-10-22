"""The rail beside the chat and the reader over the window show a Word
document, a spreadsheet and a presentation: the pages of the document, a tab
for each sheet above its values as a table, the slides one under the other.

The real components (`ModulVorschau`, `Bildschau`) are built as shipped and
drawn in headless Chrome (tests/preview_harness.py) with three small files
written by hand (tests/office_files.py). The kinds of the endings and the
way the libraries are loaded are checked without a browser.

Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests import office_files, preview_harness as harness

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
LIB = FRONTEND / "src/lib"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no node or no frontend dependencies on this machine",
)
needs_browser = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "docx-preview").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]


def _node(script: str) -> str:
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60, cwd=FRONTEND
    )
    assert run.returncode == 0, (run.stdout + run.stderr)[-2000:]
    return run.stdout.strip()


# --- Which ending is which kind --------------------------------------------------


@needs_node
def test_the_endings_of_office_files_are_their_kinds_and_the_old_formats_have_none():
    script = f"""
import {{ fileKind, ADDRESS_KINDS, OFFICE_KINDS, dateizeichen }} from {json.dumps((LIB / "dateiarten.js").as_uri())}
const kinds = Object.fromEntries(['docx', 'xlsx', 'xls', 'pptx', 'DOCX', '.xlsx', 'doc', 'ppt', 'odt', 'key'].map((e) => [e, (fileKind(e) || {{}}).kind ?? null]))
console.log(JSON.stringify({{ kinds, address: ADDRESS_KINDS, office: OFFICE_KINDS, marks: ['docx', 'xlsx', 'pptx'].map((e) => dateizeichen(e).startsWith('<svg')) }}))
"""
    report = json.loads(_node(script))
    assert report["kinds"] == {
        "docx": "word", "xlsx": "sheet", "xls": "sheet", "pptx": "slides", "DOCX": "word", ".xlsx": "sheet",
        "doc": None, "ppt": None, "odt": None, "key": None,
    }, report["kinds"]
    assert set(report["office"]) <= set(report["address"]), "an Office file is drawn from its address"
    assert report["marks"] == [True, True, True]


def test_the_three_libraries_are_loaded_only_when_a_file_of_their_kind_opens():
    """No file of the program imports them at the top: each is a dynamic import
    in one place, so the first window never carries them."""
    for source in (FRONTEND / "src").rglob("*"):
        if source.suffix not in {".js", ".svelte"}:
            continue
        text = source.read_text(encoding="utf-8")
        for library in ("docx-preview", "xlsx", "pptx-preview"):
            assert not re.search(rf"""^\s*import\b[^;\n]*from\s+['"]{library}['"]""", text, re.M), (source, library)
    drawn = (LIB / "officeDocument.js").read_text(encoding="utf-8")
    for library in ("docx-preview", "xlsx", "pptx-preview"):
        assert f"await import('{library}')" in drawn, library


def test_the_libraries_stand_in_the_package_and_in_the_notices():
    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))["dependencies"]
    assert package["docx-preview"] == "0.4.1" and package["pptx-preview"] == "1.0.7"
    assert package["xlsx"] == "https://cdn.sheetjs.com/xlsx-0.20.3/xlsx-0.20.3.tgz", "the fixed version of SheetJS"
    notices = (FRONTEND.parent / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for heading in ("## docx-preview — Apache License 2.0", "## pptx-preview — ISC License", "## xlsx — Apache License 2.0"):
        assert heading in notices, heading


# --- What the two views draw -------------------------------------------------------

SHELL = """<script>
  import ModulVorschau from '../../src/teile/ModulVorschau.svelte'
  import Bildschau from '../../src/teile/Bildschau.svelte'
</script>

<div id="kasten" style="position: absolute; left: 0; top: 0; width: 420px; height: 620px; display: flex; flex-direction: column;">
  <ModulVorschau />
</div>
<Bildschau />
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import '../../src/stil/global.css'
import '../../src/stil/tiles.css'
import english from '../../../app/locales/en.json'
import { texte } from '../../src/lib/texte.svelte.js'
import { zustand } from '../../src/lib/zustand.svelte.js'
import { tabEinsortieren } from '../../src/lib/vorschautabs.svelte.js'
import { showPage } from '../../src/lib/bildschau.svelte.js'

window.__errors = []
window.addEventListener('error', (e) => window.__errors.push(String(e.message)))
window.addEventListener('unhandledrejection', (e) => window.__errors.push(String(e.reason && (e.reason.stack || e.reason.message) || e.reason)))
texte.sprache = 'en'
texte.katalog = english
const answer = (body) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
const realFetch = window.fetch.bind(window)
window.fetch = async (address, ...rest) => {
  const url = String(address)
  if (url.includes('/api/v1/') && !/\\.(docx|xlsx|pptx)$/.test(url)) return answer({})
  return realFetch(address, ...rest)
}
zustand.chats = [{ id: 'c1', title: 'Chat' }]
zustand.aktiverChat = 'c1'
for (const file of %(files)s) tabEinsortieren('c1', file)
mount(Shell, { target: document.getElementById('wurzel') })
window.__page = (file) => showPage(file)
"""

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const until = async (test, ms = 15000) => {
  const end = Date.now() + ms
  while (Date.now() < end) { try { if (test()) return true } catch {} await wait(100) }
  return false
}
await wait(500)
const stage = () => document.querySelector('#kasten .buehne')
const report = { tabs: [...document.querySelectorAll('#kasten .reiter-name')].map((b) => b.textContent) }
const pick = (name) => [...document.querySelectorAll('#kasten .reiter-name')].find((b) => b.textContent === name).click()
const links = (root) => [...root.querySelectorAll('a')].map((a) => ({ text: a.textContent, href: a.getAttribute('href'), target: a.target, rel: a.rel }))
const cells = (root) => [...root.querySelectorAll('td, th')].map((c) => c.textContent)

// Word, in the rail.
pick('plan.docx')
report.wordDrawn = await until(() => stage().querySelector('section'))
await wait(400)
{
  const root = stage()
  const host = root.querySelector('.office')
  const page = root.querySelector('section')
  report.word = {
    text: root.textContent,
    smuggled: Boolean(document.getElementById('smuggled')),
    links: links(root),
    hacked: window.hacked ?? null,
    images: root.querySelectorAll('.word img').length,
    zoom: root.querySelector('.word').style.zoom,
    pageRight: page.getBoundingClientRect().right,
    hostRight: host.getBoundingClientRect().right,
    sideways: host.scrollWidth - host.clientWidth,
    facts: (document.querySelector('#kasten .fakten') || {}).textContent ?? null,
  }
}

// Excel, in the rail: a tab for each sheet and the values as a table.
pick('sales.xlsx')
report.sheetDrawn = await until(() => stage().querySelector('table'))
await wait(200)
{
  const root = stage()
  report.sheet = {
    tabs: [...root.querySelectorAll('.sheet')].map((b) => b.textContent),
    cells: cells(root),
    markup: root.querySelectorAll('table b, table img').length,
    head: [...root.querySelectorAll('th')].map((c) => c.textContent),
  }
  root.querySelectorAll('.sheet')[1].click()
  await wait(300)
  report.sheet.second = cells(root)
  report.sheet.pressed = [...root.querySelectorAll('.sheet')].map((b) => b.getAttribute('aria-selected'))
}

// PowerPoint, in the rail: the slides one under the other.
pick('deck.pptx')
report.slidesDrawn = await until(() => stage().textContent.includes('Second slide'))
await wait(400)
{
  const root = stage()
  const host = root.querySelector('.office')
  const texts = [...root.querySelectorAll('.slides *')].filter((e) => e.children.length === 0 && /slide/.test(e.textContent)).map((e) => ({ text: e.textContent, top: Math.round(e.getBoundingClientRect().top), right: Math.round(e.getBoundingClientRect().right) }))
  const frame = root.querySelector('.pptx-preview-wrapper')
  const slides = [...root.querySelectorAll('.pptx-preview-slide-wrapper')]
  report.slides = { texts, hostRight: host.getBoundingClientRect().right, sideways: host.scrollWidth - host.clientWidth, count: slides.length, text: root.textContent, images: root.querySelectorAll('.slides img').length, hacked: window.hacked ?? null,
    frameHeight: frame.getBoundingClientRect().height, slideHeight: slides[0].getBoundingClientRect().height, frameBackground: getComputedStyle(frame).backgroundColor }
}

// The large view.
const reader = () => document.querySelector('.reader')
const view = async (file, ready) => {
  window.__page(file)
  await until(() => reader() && ready(reader()))
  await wait(400)
  return reader()
}
{
  const root = await view({ name: 'plan.docx', adresse: '/api/v1/plan.docx', mediaKind: 'word' }, (r) => r.querySelector('section'))
  report.view = { word: { text: root.textContent, links: links(root), smuggled: Boolean(document.getElementById('smuggled')) } }
}
{
  const root = await view({ name: 'sales.xlsx', adresse: '/api/v1/sales.xlsx', mediaKind: 'sheet' }, (r) => r.querySelector('table'))
  report.view.sheet = { tabs: [...root.querySelectorAll('.sheet')].map((b) => b.textContent), cells: cells(root) }
}
{
  const root = await view({ name: 'deck.pptx', adresse: '/api/v1/deck.pptx', mediaKind: 'slides' }, (r) => r.textContent.includes('Second slide'))
  report.view.slides = { text: root.textContent }
}
report.errors = window.__errors.slice(0, 6)
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

FILES = [
    {"name": "plan.docx", "art": "docx", "inhalt": "", "adresse": "/api/v1/plan.docx", "fakten": "DOCX · 2 KB"},
    {"name": "sales.xlsx", "art": "xlsx", "inhalt": "", "adresse": "/api/v1/sales.xlsx", "fakten": "XLSX · 2 KB"},
    {"name": "deck.pptx", "art": "pptx", "inhalt": "", "adresse": "/api/v1/deck.pptx", "fakten": "PPTX · 6 KB"},
]


@pytest.fixture(scope="module")
def report() -> dict:
    assets = {"plan.docx": office_files.docx(), "sales.xlsx": office_files.xlsx(), "deck.pptx": office_files.pptx()}
    return harness.run_page(SHELL, ENTRY_JS % {"files": json.dumps(FILES)}, CASES, assets, limit=170.0)


def browser(test):
    """The tests that read the page's report: only where there is a Chrome."""
    for mark in needs_browser:
        test = mark(test)
    return test


@browser
def test_every_office_file_stands_in_a_tab_of_the_rail(report):
    assert report["tabs"] == ["plan.docx", "sales.xlsx", "deck.pptx"], report["tabs"]


@browser
def test_a_word_document_stands_with_its_text_in_both_views_and_fits_the_rail(report):
    word = report["word"]
    assert report["wordDrawn"] and office_files.WORD_TEXT in word["text"], word["text"]
    assert word["facts"].startswith("DOCX"), word["facts"]
    # The pages are as wide as the rail at most: nothing rolls sideways.
    assert word["pageRight"] <= word["hostRight"] + 1 and word["sideways"] <= 1, word
    assert report["view"]["word"]["text"].count(office_files.WORD_TEXT) == 1, report["view"]["word"]


@browser
def test_a_word_document_draws_no_html_of_its_own_and_no_link_that_runs_a_script(report):
    for shown in (report["word"], report["view"]["word"]):
        assert shown["smuggled"] is False and office_files.WORD_CHUNK_TEXT not in shown.get("text", ""), shown
        by_text = {link["text"]: link for link in shown["links"]}
        assert office_files.WORD_SCRIPT_LINK not in by_text, "text now, no link"
        web = by_text[office_files.WORD_WEB_LINK]
        assert web["href"] == "https://example.com/page" and web["target"] == "_blank", web
        assert "noopener" in web["rel"]
    assert report["word"]["hacked"] is None


@browser
def test_text_that_reads_as_a_tag_is_text_in_a_document_and_in_a_presentation(report):
    markup = office_files.MARKUP
    assert markup in report["word"]["text"] and report["word"]["images"] == 0, report["word"]
    assert report["slides"]["text"].count(markup) == 4, "two runs on each slide, as text"
    assert report["slides"]["images"] == 0, "the slide library set it as markup"
    assert report["slides"]["hacked"] is None and report["word"]["hacked"] is None


@browser
def test_a_spreadsheet_has_a_tab_for_each_sheet_and_its_values_as_a_table(report):
    sheet = report["sheet"]
    one, two = office_files.SHEET_ONE, office_files.SHEET_TWO
    assert sheet["tabs"] == [one[0], two[0]], sheet["tabs"]
    assert sheet["head"] == one[1][0] and sheet["cells"] == [c for row in one[1] for c in row], sheet
    assert sheet["markup"] == 0, "a cell that holds markup is text"
    assert sheet["second"] == [c for row in two[1] for c in row], sheet["second"]
    assert sheet["pressed"] == ["false", "true"], sheet["pressed"]
    view = report["view"]["sheet"]
    assert view["tabs"] == [one[0], two[0]] and view["cells"] == sheet["cells"] == [c for row in one[1] for c in row], view


@browser
def test_a_presentation_stands_with_its_slides_one_under_the_other(report):
    slides = report["slides"]
    assert report["slidesDrawn"], slides
    first = next(t for t in slides["texts"] if t["text"] == office_files.SLIDE_ONE)
    second = next(t for t in slides["texts"] if t["text"] == office_files.SLIDE_TWO)
    assert second["top"] > first["top"], slides["texts"]
    assert slides["count"] == 2 and slides["frameHeight"] >= 2 * slides["slideHeight"], "the frame is not one slide high"
    assert slides["frameBackground"] == "rgba(0, 0, 0, 0)", "no black ground behind the slides"
    assert max(first["right"], second["right"]) <= slides["hostRight"] + 1 and slides["sideways"] <= 1, slides
    assert office_files.SLIDE_TWO in report["view"]["slides"]["text"] and office_files.SLIDE_ONE in report["view"]["slides"]["text"]


@browser
def test_nothing_was_refused_or_failed_while_drawing(report):
    assert report["errors"] == [], report["errors"]
