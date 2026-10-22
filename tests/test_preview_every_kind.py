"""The rail beside the chat and the reader over the window show a file by
what it is: code with colours and numbered lines, text as text, a picture as
a picture (a drawing through an image element, its source one switch away),
a clip and a sound in a player with its own controls that never starts by
itself.

The real components (`ModulVorschau`, `Bildschau`) are built as shipped and
drawn in headless Chrome, which is served the build and a few small files by
a web server of this test. The page reports what it drew. The pure parts —
which ending is which kind, the colours of the added grammars, the types the
service names — are run without a browser.

Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.agentendock import type_from_name
from tests import preview_harness as harness

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
LIB = FRONTEND / "src/lib"
ENGLISH = json.loads((ROOT / "app" / "locales" / "en.json").read_text(encoding="utf-8"))

needs_node = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no node or no frontend dependencies on this machine",
)
needs_browser = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

IS_PRIME = "def is_prime(n):\n    if n < 2:\n        return False\n    return all(n % i for i in range(2, n))\n"
NOTES = "Buy milk\nCall the bank\n"
LOGO = '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><script>window.parent.hacked = 1</script><circle cx="20" cy="20" r="18"/></svg>'
# One transparent pixel: a valid GIF.
# What the number before a row is: the row's own count, never text.
COUNTER = "counter(code-zeile)"
LONG_LINE = '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0' + " L1 1" * 1000 + '"/></svg>'
GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")


def _node(script: str) -> str:
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60, cwd=FRONTEND
    )
    assert run.returncode == 0, (run.stdout + run.stderr)[-2000:]
    return run.stdout.strip()


# --- Which ending is which kind --------------------------------------------------


@needs_node
def test_every_ending_is_the_kind_it_is():
    out = _node(f"""
import {{ fileKind, dateiart, dateizeichen, svgAddress }} from {json.dumps((LIB / "dateiarten.js").as_uri())}
const endings = ['py', 'PY', '.go', 'txt', 'log', 'srt', 'vtt', 'svg', 'gif', 'avif', 'bmp', 'ico', 'png',
  'mp4', 'mov', 'm4v', 'webm', 'mp3', 'wav', 'm4a', 'aac', 'ogg', 'oga', 'flac', 'opus', 'htm', 'html', 'md',
  'csv', 'json', 'pdf', 'zip', 'exe', '', 'dockerfile', 'makefile', 'diff']
console.log(JSON.stringify({{
  kinds: endings.map((e) => [e, fileKind(e)?.kind ?? null, fileKind(e)?.language ?? null]),
  marks: ['py', 'txt', 'gif', 'mp4', 'mp3', 'svg', 'zip'].map((e) => [e, dateizeichen(e).startsWith('<svg')]),
  fenceStaysABox: [dateiart('python'), dateiart('py'), dateiart('go'), dateiart('txt'), dateiart('mp4')],
  svgAddress: svgAddress('<svg/>'),
}}))
""")
    report = json.loads(out)
    kinds = {e: (kind, language) for e, kind, language in report["kinds"]}
    assert kinds["py"] == kinds["PY"] == ("code", "python")
    assert kinds[".go"] == ("code", "go")
    assert kinds["dockerfile"] == ("code", "dockerfile") and kinds["makefile"] == ("code", "makefile")
    assert kinds["diff"] == ("code", "diff")
    assert [kinds[e][0] for e in ("txt", "log", "srt", "vtt")] == ["text"] * 4
    assert [kinds[e][0] for e in ("gif", "avif", "bmp", "ico", "png")] == ["image"] * 5
    assert [kinds[e][0] for e in ("mp4", "mov", "m4v", "webm")] == ["video"] * 4
    assert [kinds[e][0] for e in ("mp3", "wav", "m4a", "aac", "ogg", "oga", "flac", "opus")] == ["audio"] * 8
    assert kinds["htm"] == ("doc", "html") and kinds["svg"] == ("doc", "svg")
    assert [kinds[e][0] for e in ("html", "md", "csv", "json")] == ["doc"] * 4
    assert kinds["pdf"][0] == "pdf"
    assert [kinds[e][0] for e in ("zip", "exe", "")] == [None] * 3
    assert all(has for _, has in report["marks"][:-1]) and report["marks"][-1] == ["zip", False]
    # A fence of code stays a box with a copy button: only documents become files.
    assert report["fenceStaysABox"] == [None] * 5
    assert report["svgAddress"] == "data:image/svg+xml;charset=utf-8,%3Csvg%2F%3E"


@needs_node
def test_the_added_grammars_colour_their_code():
    out = _node(f"""
import {{ hervorheben }} from {json.dumps((LIB / "einfaerben.js").as_uri())}
const samples = {{
  go: 'func main() {{ fmt.Println("x") }}', kotlin: 'fun main() {{ println(1) }}', ruby: 'def x; puts 1; end',
  php: '<?php echo 1; ?>', swift: 'func f() -> Int {{ return 1 }}', lua: 'local x = 1',
  cpp: 'int main() {{ return 0; }}', csharp: 'class A {{ void B() {{}} }}', diff: '+ a\\n- b',
  dockerfile: 'FROM alpine', makefile: 'all:\\n\\techo 1', scss: '.a {{ .b {{ color: red }} }}',
}}
console.log(JSON.stringify(Object.fromEntries(Object.entries(samples).map(([l, c]) => [l, /hljs-/.test(hervorheben(c, l))]))))
""")
    assert all(json.loads(out).values()), out


def test_the_service_names_video_and_sound_the_same_way_on_every_system():
    expected = {
        "clip.mp4": "video/mp4", "clip.m4v": "video/mp4", "clip.webm": "video/webm", "clip.mov": "video/quicktime",
        "tone.mp3": "audio/mpeg", "tone.wav": "audio/wav", "tone.m4a": "audio/mp4", "tone.aac": "audio/aac",
        "tone.ogg": "audio/ogg", "tone.oga": "audio/ogg", "tone.flac": "audio/flac", "tone.opus": "audio/ogg",
    }
    assert {name: type_from_name(name) for name in expected} == expected
    # Silence probes: a picture and a text keep the types they had, and a
    # compressed name is no clip.
    assert type_from_name("anim.gif") == "image/gif" and type_from_name("notes.txt") == "text/plain"
    assert type_from_name("tone.mp3.gz") == ""


def test_a_clip_and_a_sound_are_handed_out_with_their_type_and_answer_a_range_with_206(client):
    """What the player asks for: the file under its type, the spooling by a
    range. Handed out as a file to save all the same — an element loads it
    nonetheless, and no address opens it as a page."""
    from app import dokumentablage

    chat = client.post("/api/v1/chats", json={"title": "Media"}).json()["id"]
    folder = dokumentablage.chatordner(client.app.state.config.datenverzeichnis, chat)
    folder.mkdir(parents=True, exist_ok=True)
    data = bytes(range(256)) * 4
    for name, kind in (("clip.mp4", "video/mp4"), ("tone.mp3", "audio/mpeg")):
        (folder / name).write_bytes(data)
        whole = client.get(f"/api/v1/chat-files/{chat}/{name}")
        assert whole.status_code == 200 and whole.headers["content-type"].startswith(kind), whole.headers
        assert whole.headers["content-disposition"].startswith("attachment")
        assert whole.headers.get("accept-ranges") == "bytes"
        part = client.get(f"/api/v1/chat-files/{chat}/{name}", headers={"Range": "bytes=0-99"})
        assert part.status_code == 206 and part.content == data[:100], part.status_code
        assert part.headers["content-range"] == f"bytes 0-99/{len(data)}"


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
import '../../src/stil/berichttext.css'
import '../../src/stil/codeblock.css'
import english from '../../../app/locales/en.json'
import { texte } from '../../src/lib/texte.svelte.js'
import { zustand } from '../../src/lib/zustand.svelte.js'
import { tabEinsortieren, tabWaehlen } from '../../src/lib/vorschautabs.svelte.js'
import { showPage, bildZeigen } from '../../src/lib/bildschau.svelte.js'

window.__errors = []
window.addEventListener('error', (e) => window.__errors.push(String(e.message)))
window.addEventListener('unhandledrejection', (e) => window.__errors.push(String(e.reason && e.reason.message || e.reason)))
texte.sprache = 'en'
texte.katalog = english
const answer = (body) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
const realFetch = window.fetch.bind(window)
window.fetch = async (address, ...rest) => {
  const url = String(address)
  if (url.includes('/api/v1/') && !/\\.(gif|mp4|mp3)$/.test(url)) return answer({})
  return realFetch(address, ...rest)
}
zustand.chats = [{ id: 'c1', title: 'Chat' }]
zustand.aktiverChat = 'c1'
const files = %(files)s
for (const file of files) tabEinsortieren('c1', file)
mount(Shell, { target: document.getElementById('wurzel') })
window.__files = files
window.__pick = (name) => tabWaehlen('c1', files.find((f) => f.name === name).art + ':' + name)
window.__page = (file) => showPage(file)
window.__picture = (address, more) => bildZeigen(address, more)
"""

CASES = r"""
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
await wait(600)
const stage = () => document.querySelector('#kasten .buehne')
const report = { tabs: [...document.querySelectorAll('#kasten .reiter-name')].map((b) => b.textContent) }
const read = async (name) => {
  [...document.querySelectorAll('#kasten .reiter-name')].find((b) => b.textContent === name).click()
  await wait(400)
  const root = stage()
  const code = root.querySelector('.codeblock')
  return {
    iframes: root.querySelectorAll('iframe').length,
    code: Boolean(code),
    rows: code ? [...code.querySelectorAll('.code-zeile')].map((r) => getComputedStyle(r, '::before').content.replace(/"/g, '')) : [],
    coloured: code ? code.querySelectorAll('[class*="hljs-"]').length : 0,
    text: (root.querySelector('.file-content-text') || {}).textContent ?? null,
    imgSrc: (root.querySelector('img') || {}).src ?? null,
    video: (() => { const v = root.querySelector('video'); return v ? { controls: v.controls, autoplay: v.autoplay, src: v.getAttribute('src') } : null })(),
    audio: (() => { const a = root.querySelector('audio'); return a ? { controls: a.controls, autoplay: a.autoplay, src: a.getAttribute('src') } : null })(),
    switchShown: Boolean(document.querySelector('#kasten button[aria-pressed]')),
    facts: (document.querySelector('#kasten .fakten') || {}).textContent ?? null,
  }
}
report.py = await read('is_prime.py')
report.txt = await read('notes.txt')
report.svg = await read('logo.svg')
document.querySelector('#kasten button[aria-pressed]').click()
await wait(300)
report.svgSource = { code: Boolean(stage().querySelector('.codeblock')), img: Boolean(stage().querySelector('img')), pressed: document.querySelector('#kasten button[aria-pressed]').getAttribute('aria-pressed') }
document.querySelector('#kasten button[aria-pressed]').click()
report.gif = await read('anim.gif')
report.mp4 = await read('clip.mp4')
// A drawing of one very long line: its source stands whole, broken into rows of the width, one number.
await read('long.svg')
document.querySelector('#kasten button[aria-pressed]').click()
await wait(300)
report.longSource = (() => {
  const holder = stage().querySelector('.quelle')
  const code = holder.querySelector('code')
  const rows = [...holder.querySelectorAll('.code-zeile')]
  return { rows: rows.length, number: getComputedStyle(rows[0], '::before').content.replace(/"/g, ''),
    sideways: Math.max(holder.scrollWidth - holder.clientWidth, code.scrollWidth - code.clientWidth),
    rowHeight: rows[0].getBoundingClientRect().height, held: code.textContent.length, firstHeight: 18 }
})()
report.mp3 = await read('tone.mp3')
report.hacked = window.hacked ?? null
report.html = await read('page.html')
report.md = await read('note.md')
report.mdPage = Boolean(stage().querySelector('.dokument'))
report.csv = await read('table.csv')
report.csvTable = stage().querySelectorAll('table tr').length
report.json = await read('data.json')

// The large view.
const reader = () => document.querySelector('.reader')
const readView = async () => {
  await wait(500)
  const root = reader()
  return root ? {
    code: Boolean(root.querySelector('.codeblock')),
    rows: [...root.querySelectorAll('.code-zeile')].map((r) => getComputedStyle(r, '::before').content.replace(/"/g, '')),
    sideways: (() => { const c = root.querySelector('.codeblock code'); return c ? c.scrollWidth - c.clientWidth : null })(),
    rowHeight: (() => { const r = root.querySelector('.code-zeile'); return r ? r.getBoundingClientRect().height : null })(),
    coloured: root.querySelectorAll('[class*="hljs-"]').length,
    text: (root.querySelector('.file-content-text') || {}).textContent ?? null,
    imgSrc: (root.querySelector('img') || {}).src ?? null,
    video: (() => { const v = root.querySelector('video'); return v ? { controls: v.controls, autoplay: v.autoplay } : null })(),
    audio: (() => { const a = root.querySelector('audio'); return a ? { controls: a.controls, autoplay: a.autoplay } : null })(),
  } : null
}
report.view = {}
window.__page({ name: 'is_prime.py', language: 'py', text: %(py)s })
report.view.py = await readView()
window.__page({ name: 'notes.txt', language: 'txt', text: %(txt)s })
report.view.txt = await readView()
window.__page({ name: 'long.svg', language: 'xml', text: %(long)s })
report.view.long = await readView()
window.__page({ name: 'logo.svg', language: 'svg', text: %(svg)s })
report.view.svg = await readView()
window.__picture('/api/v1/anim.gif', { name: 'anim.gif' })
report.view.gif = await readView()
window.__picture('/api/v1/clip.mp4', { name: 'clip.mp4', mediaKind: 'video' })
report.view.mp4 = await readView()
window.__picture('/api/v1/tone.mp3', { name: 'tone.mp3', mediaKind: 'audio' })
report.view.mp3 = await readView()
report.errors = window.__errors.slice(0, 6)
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

FILES = [
    {"name": "is_prime.py", "art": "py", "inhalt": IS_PRIME},
    {"name": "notes.txt", "art": "txt", "inhalt": NOTES},
    {"name": "logo.svg", "art": "svg", "inhalt": LOGO},
    {"name": "anim.gif", "art": "gif", "inhalt": "", "adresse": "/api/v1/anim.gif", "fakten": "GIF · 1 KB"},
    {"name": "clip.mp4", "art": "mp4", "inhalt": "", "adresse": "/api/v1/clip.mp4", "fakten": "MP4 · 1 KB"},
    {"name": "tone.mp3", "art": "mp3", "inhalt": "", "adresse": "/api/v1/tone.mp3", "fakten": "MP3 · 1 KB"},
    {"name": "long.svg", "art": "svg", "inhalt": LONG_LINE},
    # What was shown before and stays as it was.
    {"name": "page.html", "art": "html", "inhalt": "<h1>Hello</h1>"},
    {"name": "note.md", "art": "md", "inhalt": "# Title\n\nA line."},
    {"name": "table.csv", "art": "csv", "inhalt": "a,b\n1,2\n"},
    {"name": "data.json", "art": "json", "inhalt": '{"a": 1}'},
]


def _run() -> dict:
    # The page holds these inline: a closing tag inside one must not end its script.
    inline = lambda text: json.dumps(text).replace("</", "<\\/")  # noqa: E731
    cases = CASES % {"py": inline(IS_PRIME), "txt": inline(NOTES), "svg": inline(LOGO), "long": inline(LONG_LINE)}
    assets = {
        "anim.gif": GIF,
        "clip.mp4": b"\x00\x00\x00\x18ftypmp42" + bytes(64),
        "tone.mp3": b"ID3" + bytes(64),
    }
    return harness.run_page(SHELL, ENTRY_JS % {"files": json.dumps(FILES)}, cases, assets)


@pytest.fixture(scope="module")
def report() -> dict:
    return _run()


def browser(test):
    """The tests that read the page's report: only where there is a Chrome."""
    for mark in needs_browser:
        test = mark(test)
    return test


@browser
def test_every_file_stands_in_a_tab_of_the_rail(report):
    assert report["tabs"] == [f["name"] for f in FILES], report["tabs"]


@browser
def test_code_stands_in_both_views_with_colours_and_a_number_on_every_line(report):
    rail, view = report["py"], report["view"]["py"]
    for shown in (rail, view):
        assert shown["code"] is True and shown["coloured"] > 3, shown
        # One row per written line, each drawing its own number from the counter.
        assert shown["rows"] == [COUNTER] * 5, shown["rows"]
    assert rail["iframes"] == 0 and rail["switchShown"] is False, "code has no second view"
    assert rail["facts"].startswith("PY"), rail["facts"]


@browser
def test_a_long_line_breaks_in_both_views_and_wears_one_number(report):
    """A line of 5000 characters stands whole, row after row of the width, no
    sideways roll to hide the rest (the page shows no scrollbar), one number
    before its start."""
    source = report["longSource"]
    assert len(LONG_LINE) >= 5000 and source["held"] == len(LONG_LINE), source
    assert source["rows"] == 1 and source["number"] == COUNTER, source
    assert source["sideways"] <= 1, source
    assert source["rowHeight"] > 2 * 18, "the line did not break into several rows"
    view = report["view"]["long"]
    assert view["rows"] == [COUNTER] and view["sideways"] <= 1 and view["rowHeight"] > 2 * 18, view


@browser
def test_text_stands_as_text_in_both_views(report):
    assert report["txt"]["text"] == NOTES and report["txt"]["code"] is False
    assert report["view"]["txt"]["text"] == NOTES


@browser
def test_a_drawing_is_a_picture_through_an_image_element_and_its_source_is_one_switch_away(report):
    rail = report["svg"]
    assert rail["iframes"] == 0 and rail["imgSrc"].startswith("data:image/svg+xml"), rail
    assert rail["switchShown"] is True
    assert report["svgSource"] == {"code": True, "img": False, "pressed": "true"}, report["svgSource"]
    # The script inside it did not run, and the reader draws it the same way.
    assert report["hacked"] is None
    assert report["view"]["svg"]["imgSrc"].startswith("data:image/svg+xml"), report["view"]["svg"]


@browser
def test_a_gif_is_a_picture_from_its_address_in_both_views(report):
    assert report["gif"]["imgSrc"].endswith("/anim.gif") and report["gif"]["code"] is False
    assert report["view"]["gif"]["imgSrc"].endswith("/anim.gif")


@browser
def test_a_clip_and_a_sound_stand_in_a_player_with_controls_that_does_not_start_by_itself(report):
    assert report["mp4"]["video"] == {"controls": True, "autoplay": False, "src": "/api/v1/clip.mp4"}, report["mp4"]
    assert report["mp3"]["audio"] == {"controls": True, "autoplay": False, "src": "/api/v1/tone.mp3"}, report["mp3"]
    assert report["view"]["mp4"]["video"] == {"controls": True, "autoplay": False}, report["view"]["mp4"]
    assert report["view"]["mp3"]["audio"] == {"controls": True, "autoplay": False}, report["view"]["mp3"]


@browser
def test_silence_html_markdown_csv_and_json_are_drawn_as_before(report):
    assert report["html"]["iframes"] == 1 and report["html"]["code"] is False, report["html"]
    assert report["mdPage"] is True and report["md"]["code"] is False, report["md"]
    assert report["csvTable"] == 2 and report["csv"]["code"] is False, report["csv"]
    # The source of a document, as the reader has always shown it: coloured and numbered.
    assert report["json"]["code"] is True and report["json"]["coloured"] > 0, report["json"]


@browser
def test_nothing_was_refused_or_failed_while_drawing(report):
    ignored = ("media", "decode", "demuxer", "failed to load", "net::")
    assert [e for e in report["errors"] if not any(word in e.lower() for word in ignored)] == [], report["errors"]


def test_the_components_draw_a_file_through_one_shared_component():
    """One way for both views: neither draws code or a picture of its own."""
    rail = (FRONTEND / "src/teile/ModulVorschau.svelte").read_text(encoding="utf-8")
    reader = (FRONTEND / "src/teile/Bildschau.svelte").read_text(encoding="utf-8")
    for source in (rail, reader):
        assert "import FileContent from './FileContent.svelte'" in source
        assert "hervorheben(" not in source and "nummernspalte(" not in source
    assert "<pre class=\"quelle\">" not in rail
    shared = (FRONTEND / "src/teile/FileContent.svelte").read_text(encoding="utf-8")
    assert "autoplay" not in shared.replace("never starting by itself", "")
