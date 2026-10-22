"""The layout of the Web App page, measured in a real browser.

`SettingsWebApp.svelte` is built as shipped and drawn inside its menu page
(`Menueseite.svelte`, the way the settings hold it) in headless Chrome, at the
width of a 2560 px window and again at 1100 px. The page answers its own
questions: the service's state comes from a made-up answer with a running
service and a small drawing as the code. Three columns stand side by side and
equally high, the code stands large and alone in its tile, each row of the
setup wears its sign, and the three steps are tiles of glass with their
pictures whole. Skipped where there is no Chrome or no node, like the other
browser tests.
"""

from __future__ import annotations

import functools
import http.server
import json
import shutil
import subprocess
import threading
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp
from tests import test_pdf_pages_chrome as harness

ROOT = harness.ROOT
FRONTEND = harness.FRONTEND

pytestmark = harness.pytestmark

SHELL = """<script>
  import Menueseite from '../../src/teile/Menueseite.svelte'
  import SettingsWebApp from '../../src/teile/SettingsWebApp.svelte'
</script>

<div id="shell" style="width: @@AREA@@px; height: 1100px; display: flex; flex-direction: column;">
  <Menueseite fuellen>
    {#snippet kopf()}<h1>Web-App</h1>{/snippet}
    {#snippet inhalt()}<SettingsWebApp />{/snippet}
  </Menueseite>
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import '../../src/stil/global.css'
import german from '@@GERMAN@@'
import english from '@@ENGLISH@@'
import { texte } from '@@TEXTE@@'

texte.katalog = german
texte.sprache = 'de'
window.__texte = texte
window.__english = english
const code = '<svg viewBox="0 0 29 29" xmlns="http://www.w3.org/2000/svg"><rect width="29" height="29" fill="#fff"/>'
  + '<path d="M0 0h7v7H0zM22 0h7v7h-7zM0 22h7v7H0z" fill="#000"/></svg>'
window.fetch = async (address) => {
  const path = String(address).replace(/^.*?\\/api\\/v1/, '').split('?')[0]
  const body = path === '/web-app'
    ? { password: true, password_min: 8, service: { running: true, address: 'https://mac.tailnet-name.ts.net', qr: code },
        tailscale: { connected: true, kind: 'running', login_url: '' } }
    : {}
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
mount(Shell, { target: document.getElementById('wurzel') })
"""

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
for (let k = 0; k < 100 && document.querySelectorAll('.row-icon').length < 4; k += 1) await wait(100)
await wait(400)
const box = (el) => { if (!el) return null; const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height, right: r.right, bottom: r.bottom } }
const style = (el, name) => (el ? getComputedStyle(el)[name] : null)
const text = (el) => (el ? el.textContent.trim() : null)
const page = document.querySelector('.content')
const column = document.querySelector('.column'), tile = document.querySelector('.qr-tile'), phone = document.querySelector('.field')
const report = {
  content: box(page), column: box(column), tile: box(tile), phone: box(phone),
  code: box(document.querySelector('.qr-tile .code')), codeSvg: box(document.querySelector('.qr-tile .code svg')),
  codePadding: style(document.querySelector('.qr-tile .code'), 'paddingTop'),
  tileHead: text(document.querySelector('.qr-tile .tafelkopf')), tileHeadBox: box(document.querySelector('.qr-tile .tafelkopf')),
  tileFilter: style(tile, 'backdropFilter'), tileRadius: style(tile, 'borderTopLeftRadius'),
  tileOpacity: style(tile, 'opacity'),
  icons: Array.from(document.querySelectorAll('.row .label')).filter((l) => l.querySelector('.row-icon')).map((l) => ({
    name: l.textContent.trim(), icon: box(l.querySelector('.row-icon')), svg: box(l.querySelector('.row-icon svg')),
    gap: getComputedStyle(l).columnGap,
    textStart: (() => { const r = document.createRange(); r.selectNodeContents(Array.from(l.childNodes).find((n) => n.nodeType === 3)); return r.getBoundingClientRect().x })(),
  })),
  steps: Array.from(document.querySelectorAll('.steps .step')).map((s) => ({
    tile: box(s), shot: box(s.querySelector('.shot')), frame: box(s.querySelector('.frame')),
    frameFill: style(s.querySelector('.frame'), 'backgroundColor'), frameRadius: style(s.querySelector('.frame'), 'borderTopLeftRadius'),
    number: box(s.querySelector('.number')), caption: box(s.querySelector('.caption')), captionText: text(s.querySelector('.caption')),
    radius: getComputedStyle(s).borderTopLeftRadius, overflow: s.scrollWidth > s.clientWidth + 1,
  })),
  text: document.body.textContent,
  rowGap: getComputedStyle(page).columnGap,
}
window.__texte.katalog = window.__english
window.__texte.sprache = 'en'
await wait(300)
report.tileHeadEnglish = text(document.querySelector('.qr-tile .tafelkopf'))
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


def _run(area: int, window: int) -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-web-app-layout-{uuid4().hex}"
    folder.mkdir(parents=True)
    server = None
    try:
        (folder / "Shell.svelte").write_text(SHELL.replace("@@AREA@@", str(area)), encoding="utf-8")
        entry = (
            ENTRY_JS.replace("@@GERMAN@@", str(ROOT / "app" / "locales" / "de.json"))
            .replace("@@ENGLISH@@", str(ROOT / "app" / "locales" / "en.json"))
            .replace("@@TEXTE@@", "../../src/lib/texte.svelte.js")
        )
        (folder / "entry.js").write_text(entry, encoding="utf-8")
        (folder / "vite.config.js").write_text(harness.VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [str(FRONTEND / "node_modules" / ".bin" / "vite"), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        links = "\n".join(
            f'<link rel="stylesheet" href="out/{sheet.name}">' for sheet in sorted((folder / "out").glob("*.css"))
        )
        (folder / "measure.html").write_text(harness.PAGE % {"cases": CASES, "links": links}, encoding="utf-8")
        web_port = harness._free_port()
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", web_port), functools.partial(harness._Handler, directory=str(folder))
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = harness._free_port()
        browser = subprocess.Popen(
            [
                program, "--headless=new", "--no-first-run", "--disable-background-networking",
                "--mute-audio", "--use-mock-keychain", "--password-store=basic",
                f"--window-size={window},1200", f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}", f"http://127.0.0.1:{web_port}/measure.html",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            return harness.asyncio.run(harness._drive(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
    finally:
        if server:
            server.shutdown()
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture(scope="module")
def wide() -> dict:
    # A 2560 px window: the area right of the sidebar and the page's own padding.
    return _run(area=2230, window=2560)


@pytest.fixture(scope="module")
def narrow() -> dict:
    return _run(area=1100, window=1280)


def test_three_columns_stand_equally_high(wide):
    column, tile, phone = wide["column"], wide["tile"], wide["phone"]
    assert abs(column["h"] - tile["h"]) <= 1 and abs(tile["h"] - phone["h"]) <= 1, (column, tile, phone)
    assert abs(column["y"] - tile["y"]) <= 1 and abs(tile["y"] - phone["y"]) <= 1
    # Side by side, in this order, 40 px apart.
    assert column["right"] <= tile["x"] and tile["right"] <= phone["x"]
    assert abs(tile["x"] - column["right"] - 40) <= 1 and abs(phone["x"] - tile["right"] - 40) <= 1


def test_the_three_columns_stand_together_in_the_middle_of_the_page(wide):
    content, column = wide["content"], wide["column"]
    above, below = column["y"] - content["y"], content["bottom"] - column["bottom"]
    assert above > 20 and abs(above - below) <= 2, (above, below)


def test_the_code_is_large_and_alone_in_its_tile(wide):
    tile, code, svg = wide["tile"], wide["code"], wide["codeSvg"]
    assert abs(tile["w"] - 440) <= 1
    assert abs(svg["w"] - 320) <= 0.5 and abs(svg["h"] - 320) <= 0.5, svg
    assert wide["codePadding"] == "10px"
    assert abs((code["x"] + code["w"] / 2) - (tile["x"] + tile["w"] / 2)) <= 1
    assert abs((code["y"] + code["h"] / 2) - (tile["y"] + tile["h"] / 2)) <= 1
    assert abs(wide["tileHeadBox"]["x"] - tile["x"] - 20) <= 1 and abs(wide["tileHeadBox"]["y"] - tile["y"] - 18) <= 4
    assert wide["tileRadius"] == "16px" and wide["tileFilter"] == "blur(18px)"
    assert wide["tileOpacity"] == "1"
    # No sentences about the code any more, in either language.
    for sentence in ("Mit der Kamera des Handys scannen", "Geht zu Hause und unterwegs"):
        assert sentence not in wide["text"], sentence


def test_the_head_of_the_tile_says_scan_the_code_in_both_languages(wide):
    assert wide["tileHead"] == "QR-Code scannen"
    assert wide["tileHeadEnglish"] == "Scan QR code"


def test_each_row_of_the_setup_wears_its_sign_before_its_name(wide):
    rows = wide["icons"]
    assert [row["name"] for row in rows] == ["Status", "Tailscale", "Passwort", "Adresse"]
    for row in rows:
        assert (row["icon"]["w"], row["icon"]["h"]) == (20, 20), row
        assert abs(row["svg"]["w"] - 18) <= 0.5 and abs(row["svg"]["h"] - 18) <= 0.5, row
        assert row["gap"] == "12px"
        assert abs(row["textStart"] - row["icon"]["right"] - 12) <= 1, row


def test_the_three_steps_are_tiles_of_glass_with_their_pictures_whole(wide):
    steps = wide["steps"]
    assert len(steps) == 3
    assert len({round(step["tile"]["w"]) for step in steps}) == 1
    assert len({round(step["tile"]["h"]) for step in steps}) == 1
    for step in steps:
        shot = step["shot"]
        assert abs(shot["h"] - 322) <= 0.5, shot
        assert abs(shot["w"] / shot["h"] - 700 / 982) <= 700 / 982 * 0.01, shot
        assert step["frameFill"] == "rgb(11, 11, 11)" and step["frameRadius"] == "22px"
        assert step["radius"] == "16px"
        assert (round(step["number"]["w"]), round(step["number"]["h"])) == (22, 22)
        # The picture, its number and its sentence stand in the tile's middle.
        assert step["number"]["x"] > step["tile"]["x"] and step["caption"]["right"] <= step["tile"]["right"]
        assert abs(step["caption"]["h"] - 17) <= 3, step["caption"]
        assert not step["overflow"]
    # The tiles stand 16 px apart.
    assert abs(steps[1]["tile"]["x"] - steps[0]["tile"]["right"] - 16) <= 1
    assert [step["captionText"] for step in steps] == [
        "Teilen antippen", "„Zum Home-Bildschirm“ wählen", "Exe AI vom Home-Bildschirm öffnen",
    ]


def test_where_the_page_is_narrow_it_wraps_inside_the_page(narrow):
    column, tile, phone = narrow["column"], narrow["tile"], narrow["phone"]
    # 1036 px of room: the setup and the code's tile still fit side by side,
    # the phone no longer does and stands under them. All three stay inside
    # the page's side paddings.
    assert phone["y"] >= max(column["bottom"], tile["bottom"]) - 1, (column, tile, phone)
    for part in (column, tile, phone):
        assert part["x"] >= 32 - 1 and part["right"] <= 1100 - 32 + 1, part


def test_silence_where_the_page_is_narrow_nothing_leaves_its_tile_and_the_pictures_keep_their_shape(narrow):
    for step in narrow["steps"]:
        assert not step["overflow"], step
        assert step["caption"]["right"] <= step["tile"]["right"] + 1
        assert step["shot"]["h"] <= 322.5
        assert abs(step["shot"]["w"] / step["shot"]["h"] - 700 / 982) <= 700 / 982 * 0.01, step["shot"]
