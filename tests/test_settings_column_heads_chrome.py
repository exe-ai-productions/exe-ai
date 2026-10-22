"""Two columns side by side have their headings on one line and their cards on
another, measured in a real browser.

The settings pages that stand in two columns with headings — the cloud
providers (the list of providers on the left, the table on the right) and the
server pages (rows of two sections, each with its heading over its card) — are
built as shipped and drawn in headless Chrome with the answers of the service
made up in the page: the cloud page at a window of 1440 x 900 and of 1920 x
1080, the model and the agent server (on the stand-in of
``tests/model_windows_page.py``) in its window. For every pair of columns the
top of the first heading and the top of the first card of the left column are
the same as those of the right one (0 px, 0.5 px for rounding). The pages of the
catalogue (the five kinds of model and the downloads) have a list on the left
whose first row stands 16 px under the top of its card, and a head on the
right that is as high as a row of that list: the top of the first row and the
top of the head, the middle of the row's text and the middle of the head's
text, and the tops of the two cards are the same, and the detail of a model
starts at the same height. The schedules and the agents stand in two columns
without a card: the tops of their two columns are the same. A page with one
column is not measured. The embedding, speech and picture server pages are measured
too, each in its window.

Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from unittest import mock
from urllib.parse import quote
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp
from tests import model_windows_page
from tests import test_catalog_cloud_columns_chrome as catalogue_columns
from tests import test_catalog_settings_list_chrome as catalogue_page
from tests import test_cronjobs_page_info_chrome as cronjobs_page
from tests import test_studio_generate_stays_chrome as page

FRONTEND = page.FRONTEND
ROOT = page.ROOT

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

PAGES = ["cloud"]
WINDOWS = {"1440": (1440, 900), "1920": (1920, 1080)}

SHELL = """<script>
  import ModelleCloud from '../../src/teile/ModelleCloud.svelte'
  import { zustand } from '../../src/lib/zustand.svelte.js'

  const q = JSON.parse(new URLSearchParams(location.search).get('s'))
</script>

<div style="display: flex; width: {q.w}px; height: {q.h}px;">
  <nav id="leiste" style="width: 300px; flex: none; overflow: auto;">
    {#if zustand.menuSections}{@render zustand.menuSections.snippet?.()}{/if}
  </nav>
  <main id="seite" style="flex: 1; min-width: 0; overflow: auto; position: relative;">
    {#if q.page === 'cloud'}<ModelleCloud offen={true} />{/if}
  </main>
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import %(global)r
import english from %(english)r
import { zustand } from %(zustand)r
import { texte } from %(texts)r

texte.sprache = 'en'
texte.katalog = english
const base = { group: 'cloud', capabilities: {}, timeout_enabled: true }
const provider = (id, name, keySet) => ({
  ...base, id: id + '/model-a', modell: 'model-a', name: 'model-a', anbieter: id, anbieter_name: name,
  erreichbar: true, schluessel_env: id.toUpperCase() + '_API_KEY', schluessel_gesetzt: keySet,
})
const all = [provider('openai', 'OpenAI', true), provider('anthropic', 'Anthropic', true), provider('deepseek', 'DeepSeek', false)]
zustand.modelle = all
window.fetch = async (address) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path === '/models' ? all : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
document.documentElement.dataset.modus = 'hell'
mount(Shell, { target: document.getElementById('wurzel') })
"""

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const q = JSON.parse(new URLSearchParams(location.search).get('s'))
await wait(2500)
const top = (el) => (el ? +el.getBoundingClientRect().top.toFixed(2) : null)
const headOf = (col) => col.querySelector('.tafelkopf, .column-head')
const cardOf = (col) => [...col.querySelectorAll('*')].find((e) => {
  const cs = getComputedStyle(e)
  return cs.boxShadow.includes('inset') && cs.borderRadius === '9px' && e.tagName !== 'BUTTON'
    && e.getBoundingClientRect().height > 40
})
const pairs = []
for (const box of document.querySelectorAll('.two-columns, .reihe')) {
  const columns = [...box.children].filter((c) => c.getBoundingClientRect().width > 100)
  if (columns.length < 2) continue
  const [left, right] = columns
  pairs.push({
    kind: String(box.className).split(' ')[0],
    leftHead: top(headOf(left)), rightHead: top(headOf(right)),
    leftHeadText: headOf(left)?.textContent.trim() ?? null, rightHeadText: headOf(right)?.textContent.trim() ?? null,
    leftCard: top(cardOf(left)), rightCard: top(cardOf(right)),
  })
}
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify({ q, pairs })
"""


@pytest.fixture(scope="module")
def reports() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-column-heads-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS % {
                "global": "../../src/stil/global.css",
                "english": str(ROOT / "app" / "locales" / "en.json"),
                "zustand": "../../src/lib/zustand.svelte.js",
                "texts": "../../src/lib/texte.svelte.js",
            },
            encoding="utf-8",
        )
        (folder / "vite.config.js").write_text(page.VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        (folder / "measure.html").write_text(page.PAGE % {"cases": CASES}, encoding="utf-8")
        out: dict = {}
        for name in PAGES:
            for label, (width, height) in WINDOWS.items():
                scenario = {"page": name, "w": width, "h": height}
                port = page._free_port()
                browser = subprocess.Popen(
                    [
                        program, "--headless=new", "--no-first-run", "--disable-background-networking",
                        "--allow-file-access-from-files", f"--window-size={width},{height}",
                        f"--remote-debugging-port={port}", f"--user-data-dir={folder / f'profile-{name}-{label}'}",
                        (folder / "measure.html").as_uri() + "?s=" + quote(json.dumps(scenario)),
                    ],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                )
                try:
                    out[(name, label)] = asyncio.run(page._drive(port))
                finally:
                    prozessstopp.beenden(browser, frist=5)
        return out
    finally:
        shutil.rmtree(folder, ignore_errors=True)


MEASURE_SERVERS = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const top = (el) => (el ? +el.getBoundingClientRect().top.toFixed(2) : null)
const headOf = (col) => col.querySelector('.tafelkopf, .column-head')
const cardOf = (col) => [...col.querySelectorAll('*')].find((e) => {
  const cs = getComputedStyle(e)
  return cs.boxShadow.includes('inset') && cs.borderRadius === '9px' && e.tagName !== 'BUTTON'
    && e.getBoundingClientRect().height > 40
})
const out = {}
for (const name of ['modell', 'agent', 'einbettung', 'sprache', 'bild']) {
  scene.show = name
  await wait(2000)
  const pairs = []
  for (const box of document.querySelectorAll('.reihe')) {
    const columns = [...box.children].filter((c) => c.getBoundingClientRect().width > 100)
    if (columns.length < 2) continue
    const [left, right] = columns
    pairs.push({
      leftHead: top(headOf(left)), rightHead: top(headOf(right)),
      leftCard: top(cardOf(left)), rightCard: top(cardOf(right)),
    })
  }
  out[name] = pairs
  scene.show = null
  await wait(300)
}
document.getElementById('ergebnis').textContent = JSON.stringify(out)
"""


@pytest.fixture(scope="module")
def servers() -> dict:
    # The shared harness carries two windows; the other server pages are put beside them here.
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
    anchors = ("  import { scene } from './scene.svelte.js'\n", "  {#if scene.show === 'modell'}")
    for anchor in anchors:
        assert anchor in model_windows_page.SHELL, f"the shared harness changed, widen it again: {anchor!r}"
    shell = model_windows_page.SHELL.replace(anchors[0], imports + anchors[0]).replace(anchors[1], scenes + anchors[1])
    with mock.patch.object(model_windows_page, "SHELL", shell):
        return model_windows_page.run_cases(MEASURE_SERVERS)


@pytest.mark.parametrize("label", list(WINDOWS))
@pytest.mark.parametrize("name", PAGES)
def test_the_headings_and_the_cards_of_two_columns_stand_on_one_line_each(reports, name, label):
    pairs = reports[(name, label)]["pairs"]
    for pair in pairs:
        if pair["leftHead"] is not None and pair["rightHead"] is not None:
            assert abs(pair["leftHead"] - pair["rightHead"]) <= 0.5, (name, label, pair)
        if pair["leftCard"] is not None and pair["rightCard"] is not None:
            assert abs(pair["leftCard"] - pair["rightCard"]) <= 0.5, (name, label, pair)


@pytest.mark.parametrize("label", list(WINDOWS))
def test_the_cloud_page_has_both_headings_and_both_cards_to_measure(reports, label):
    """The probe measures something: the providers on the left carry their heading and
    their card like the table on the right."""
    pair = next(p for p in reports[("cloud", label)]["pairs"] if p["kind"] == "two-columns")
    assert pair["leftHead"] is not None and pair["rightHead"] is not None, pair
    assert pair["leftCard"] is not None and pair["rightCard"] is not None, pair
    assert pair["leftHeadText"] == pair["rightHeadText"], pair


@pytest.mark.parametrize("name", ["modell", "agent", "einbettung", "sprache", "bild"])
def test_the_server_pages_stand_on_one_line_too(servers, name):
    """Silence probe: they stand on one line already; the run counts the pairs it
    measured (a page whose columns did not draw would measure nothing and pass)."""
    pairs = servers[name]
    assert len(pairs) >= (2 if name in ("modell", "agent") else 1), (name, pairs)
    for pair in pairs:
        assert pair["leftHead"] is not None and pair["rightHead"] is not None, (name, pair)
        assert abs(pair["leftHead"] - pair["rightHead"]) <= 0.5, (name, pair)
        assert abs(pair["leftCard"] - pair["rightCard"]) <= 0.5, (name, pair)


# --- The catalogue and the downloads ----------------------------------------------

CATALOGUE_CASES = r"""
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const top = (el) => (el ? +el.getBoundingClientRect().top.toFixed(2) : null)
const middleOfText = (el) => {
  if (!el) return null
  const range = document.createRange()
  range.selectNodeContents(el)
  const box = range.getBoundingClientRect()
  return +((box.top + box.bottom) / 2).toFixed(2)
}
for (let k = 0; k < 100 && !document.querySelector('.chatkopf'); k += 1) await wait(100)
await wait(600)
window.__show('katalog')
await wait(900)
const kindRows = () => [...document.querySelectorAll('nav.kinds .kind-rows .menuezeile')]
const probe = () => {
  const row = kindRows()[0]
  const head = document.querySelector('.page .vorauswahl')
  return {
    rowTop: top(row), headTop: top(head),
    rowText: middleOfText(row?.querySelector('.titel')), headText: middleOfText(head?.querySelector('span')),
    headHeight: head ? +head.getBoundingClientRect().height.toFixed(2) : null,
    leftCard: top(document.querySelector('nav.kinds')), rightCard: top(document.querySelector('.page')),
    firstOfPage: top(document.querySelector('.page > :first-child')),
    rowHeights: kindRows().map((r) => +r.getBoundingClientRect().height.toFixed(2)),
  }
}
const report = { views: {} }
const rows = kindRows()
const names = rows.map((r) => r.querySelector('.titel')?.textContent.trim())
report.names = names
for (let index = 0; index < rows.length; index += 1) {
  kindRows()[index].click()
  await wait(900)
  report.views[names[index]] = probe()
}
// The detail of a model opens from a card of a kind; the same height again.
kindRows()[0].click()
await wait(900)
document.querySelector('.raster .karte')?.click()
await wait(800)
report.detail = { ...probe(), shown: Boolean(document.querySelector('.detail')) }
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module", params=list(WINDOWS))
def catalogue_pages(request) -> dict:
    width, height = WINDOWS[request.param]
    page_html = catalogue_columns._replaced(
        catalogue_page.PAGE,
        ('<link rel="stylesheet" href="out/style.css">', "@@LINKS@@"),
        ("@@CASES@@", CATALOGUE_CASES),
        ("width: 1280px; height: 700px", f"width: {width}px; height: {height}px"),
    )
    files = {
        "entry.js": catalogue_page.ENTRY_JS.replace("@@GERMAN@@", str(ROOT / "app" / "locales" / "de.json")),
        "vite.config.js": catalogue_page.VITE_CONFIG,
    }
    report = catalogue_columns._build_and_run(f"column-heads-catalogue-{request.param}", files, page_html, f"{width},{height}")
    report["window"] = request.param
    return report


def test_the_catalogue_pages_start_their_list_and_their_head_on_one_line(catalogue_pages):
    """Every kind of model and the downloads: the first row on the left and the head on the
    right have the same top, the same middle of their text, and their cards the same top."""
    views = catalogue_pages["views"]
    assert len(views) >= 6, catalogue_pages["names"]
    for name, view in views.items():
        assert view["headTop"] is not None, (name, view)
        assert abs(view["rowTop"] - view["headTop"]) <= 0.5, (name, view)
        assert abs(view["rowText"] - view["headText"]) <= 0.5, (name, view)
        assert abs(view["leftCard"] - view["rightCard"]) <= 0.5, (name, view)


def test_the_head_of_the_page_is_as_high_as_a_row_of_the_list(catalogue_pages):
    for name, view in catalogue_pages["views"].items():
        # 40 px of the head, 1 px of its hairline.
        assert abs(view["headHeight"] - 41) <= 0.5, (name, view)


def test_silence_probe_the_rows_of_the_list_keep_their_height(catalogue_pages):
    for name, view in catalogue_pages["views"].items():
        assert view["rowHeights"] and all(abs(h - 40) <= 0.5 for h in view["rowHeights"]), (name, view)


def test_the_detail_of_a_model_starts_level_with_the_first_row(catalogue_pages):
    detail = catalogue_pages["detail"]
    assert detail["shown"], detail
    assert abs(detail["firstOfPage"] - detail["rowTop"]) <= 0.5, detail


# --- The schedules and the agents --------------------------------------------------

TWO_COLUMN_CASES = r"""
const wait = (ms) => new Promise((done) => setTimeout(done, ms))
const top = (el) => (el ? +el.getBoundingClientRect().top.toFixed(2) : null)
const root = document.getElementById('frame')
for (let k = 0; k < 80 && !root.querySelector('.zweispaltig'); k += 1) await wait(100)
await wait(900)
const box = root.querySelector('.zweispaltig')
const columns = [...box.children].filter((c) => c.getBoundingClientRect().width > 100)
const firstOf = (column) => column.querySelector(':scope > *')
document.getElementById('ergebnis').textContent = JSON.stringify({
  count: columns.length,
  columnTops: columns.map(top),
  firstTops: columns.map((c) => top(firstOf(c))),
})
"""


def _run_two_column_page(start: str, width: int, height: int) -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-column-heads-{start}-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            cronjobs_page.SHELL.replace("width: 1400px; height: 900px", f"width: {width}px; height: {height}px")
            % {"page": "../../src/teile/SystemPrompt.svelte"},
            encoding="utf-8",
        )
        (folder / "entry.js").write_text(
            cronjobs_page.ENTRY_JS % {
                "global": "../../src/stil/global.css",
                "english": "../../../app/locales/en.json",
                "german": "../../../app/locales/de.json",
                "zustand": "../../src/lib/zustand.svelte.js",
                "start": start,
                "texts": "../../src/lib/texte.svelte.js",
            },
            encoding="utf-8",
        )
        (folder / "vite.config.js").write_text(cronjobs_page.VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        links = "\n".join(
            f'<link rel="stylesheet" href="out/{sheet.name}">' for sheet in sorted((folder / "out").glob("*.css"))
        )
        assert links, "the build emitted no stylesheet"
        (folder / "measure.html").write_text(
            cronjobs_page.PAGE % {"cases": TWO_COLUMN_CASES, "links": links}, encoding="utf-8"
        )
        port = page._free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--no-first-run", "--disable-background-networking",
                "--allow-file-access-from-files", f"--window-size={width},{height}",
                f"--remote-debugging-port={port}", f"--user-data-dir={folder / 'profile'}",
                (folder / "measure.html").as_uri(),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            return asyncio.run(page._drive(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture(scope="module")
def two_column_pages() -> dict:
    return {
        (start, label): _run_two_column_page(start, width, height)
        for start in ("cronjobs", "agent")
        for label, (width, height) in WINDOWS.items()
    }


@pytest.mark.parametrize("label", list(WINDOWS))
@pytest.mark.parametrize("start", ["cronjobs", "agent"])
def test_the_schedules_and_the_agents_start_their_two_columns_on_one_line(two_column_pages, start, label):
    report = two_column_pages[(start, label)]
    assert report["count"] == 2, (start, label, report)
    assert abs(report["columnTops"][0] - report["columnTops"][1]) <= 0.5, (start, label, report)
    firsts = [t for t in report["firstTops"] if t is not None]
    if len(firsts) == 2:
        assert abs(firsts[0] - firsts[1]) <= 0.5, (start, label, report)
