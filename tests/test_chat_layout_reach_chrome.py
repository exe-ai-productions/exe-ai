"""What the chat layout reaches, and what the chat ships with, in a real browser.

`Nachricht.svelte` is built as it is shipped, with the real global stylesheet
and the real layout table, and drawn in headless Chrome. The page reports what
the layout says:

* the attachments of one's own message stand above the bubble: the cards in a
  row, under them the pictures two to a row across the column, every tile
  square and half the column less the gap; a lone picture stands on the side
  of the bubble; the bubble under them is the ordinary one;
* the code in an answer grows with the chat's font (12.8px at 17), and a code
  block outside the chat keeps its 12.8px;
* the bar under the chat is as wide as the text column above it;
* a picture in the chat takes the tile size of the layout mode as its cap;
* without any stored layout the column is 900px, the font 16px, the room
  between two messages 24px, and the dark look's own bubble is the grey with
  light ink; the other looks and a colour of the user's own stay as they were.

Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from app import appfenster
from tests.test_phone_terminal_sheet import PAGE, VITE_CONFIG, _measure

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SRC = FRONTEND / "src"

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

SHELL = """<script>
  import Nachricht from %(nachricht)r
  import { scene } from './scene.svelte.js'
</script>

<div class="spur" style="width: 600px; margin: 0 auto; display: flex; flex-direction: column; gap: var(--chat-abstand, 24px); font-size: var(--chat-schrift, 16px);">
  {#each scene.nachrichten as nachricht (nachricht.id)}
    <div class="row" data-id={nachricht.id}>
      <Nachricht {nachricht} istLetzte={false} istLetzteFrage={false} bildDeckel={scene.deckel}
                 neuErzeugen={() => {}} neuSenden={() => {}} />
    </div>
  {/each}
</div>
<style>
  .spur > :global(div) { display: flex; flex-direction: column; min-width: 0; }
</style>
"""

SCENE_JS = """export const scene = $state({ nachrichten: [], deckel: 512 })
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { scene } from './scene.svelte.js'
import { chatlayoutAnwenden, VORGABE_CHATLAYOUT } from '../../src/lib/chatlayout.js'
import %(global)r
import %(codeblock)r

window.scene = scene
window.layout = { anwenden: chatlayoutAnwenden, vorgabe: VORGABE_CHATLAYOUT }
mount(Shell, { target: document.getElementById('root') })
"""

CASES = r"""
const { scene, layout } = window
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const root = document.documentElement
const report = {}

const blobOf = (width, height) => new Promise((resolve) => {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  canvas.getContext('2d').fillRect(0, 0, width, height)
  canvas.toBlob((blob) => resolve(URL.createObjectURL(blob)))
})
const pictures = []
for (const [width, height] of [[800, 400], [100, 300], [1000, 2000], [400, 400]]) pictures.push(await blobOf(width, height))
const dokument = { id: 'd1', name: 'notes.md', typ: 'md', seiten: null, groesse: 1200 }
const rect = (el) => {
  const r = el.getBoundingClientRect()
  return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height }
}

// --- With no stored layout: the factory values reach the page.
layout.anwenden(layout.vorgabe)
report.factory = {
  column: root.style.getPropertyValue('--chat-breite'),
  font: root.style.getPropertyValue('--chat-schrift'),
  gap: root.style.getPropertyValue('--chat-abstand'),
}

// --- The attachments: a card, four pictures and text; three pictures; one picture.
const user = (id, content, extra) => ({ id, role: 'user', content, ...extra })
scene.nachrichten = [
  user('four', 'Look at these', { anhaenge: pictures, dokumente: [dokument] }),
  user('three', 'Three', { anhaenge: pictures.slice(0, 3) }),
  user('one', '', { anhaenge: pictures.slice(0, 1) }),
  user('plain', 'Just words'),
]
await wait(800)
const part = (id) => {
  const holder = document.querySelector(`[data-id="${id}"]`)
  const block = holder.querySelector('.attachment-block')
  const bubble = holder.querySelector('.von-mir')
  const style = bubble ? getComputedStyle(bubble) : null
  return {
    block: block ? rect(block) : null,
    cards: block ? rect(block.querySelector('.dok-reihe') || block) : null,
    hasCard: Boolean(holder.querySelector('.dok-reihe .dok-zeile')),
    grid: block && block.querySelector('.attachment-grid') ? rect(block.querySelector('.attachment-grid')) : null,
    tiles: [...holder.querySelectorAll('.bildrahmen')].map(rect),
    bubble: bubble ? rect(bubble) : null,
    bubbleStyle: style ? { background: style.backgroundColor, padding: style.padding, color: style.color } : null,
    insideBubble: Boolean(bubble && bubble.querySelector('.bildrahmen, .dok-reihe, .bildtext')),
  }
}
report.four = part('four')
report.three = part('three')
report.one = part('one')
report.plain = part('plain')
root.style.setProperty('--blase-eigen-stelle', '0')
await wait(100)
report.threeLeft = part('three')
report.oneLeft = part('one')
root.style.removeProperty('--blase-eigen-stelle')

// --- The code grows with the chat's font, and stays where it is outside the chat.
scene.nachrichten = [{
  id: 'code', rolle: 'assistant', content: '```js\nconst a = 1\n```', zustand: 'fertig',
  abschnitte: [{ art: 'content', text: '```js\nconst a = 1\n```' }], werkzeuge: [], stats: {},
}]
await wait(800)
const outside = document.createElement('div')
outside.className = 'codeblock nummeriert'
outside.innerHTML = '<pre><code>const b = 2</code></pre>'
document.body.appendChild(outside)
report.code = {}
for (const size of [17, 22]) {
  layout.anwenden({ ...layout.vorgabe, schrift: size })
  await wait(100)
  const code = document.querySelector('.spur .codeblock code')
  report.code[size] = {
    found: Boolean(code),
    inChat: code ? parseFloat(getComputedStyle(code).fontSize) : null,
    numbers: document.querySelector('.spur .code-nummern') ? parseFloat(getComputedStyle(document.querySelector('.spur .code-nummern')).fontSize) : null,
    outside: parseFloat(getComputedStyle(outside.querySelector('code')).fontSize),
  }
}
outside.remove()
layout.anwenden(layout.vorgabe)

// --- A picture of the chat is capped at the tile size.
scene.deckel = 300
scene.nachrichten = [{
  id: 'drawn', rolle: 'assistant', content: '', zustand: 'fertig', abschnitte: [], werkzeuge: [], stats: {},
  bild: pictures[0], bildMasse: { breite: 1000, hoehe: 1000 },
}]
await wait(800)
const stage = document.querySelector('.erzeugt-flaeche')
report.cap = stage ? rect(stage) : null
scene.deckel = 512

// --- The bubble colour of each look; a colour the user picked wins.
scene.nachrichten = [user('bubble', 'A bubble')]
await wait(500)
const bubbleOf = () => {
  const style = getComputedStyle(document.querySelector('[data-id="bubble"] .von-mir'))
  return { background: style.backgroundColor, color: style.color }
}
report.looks = {}
for (const look of ['dunkel', 'hell', 'snow', 'darkmatter']) {
  root.setAttribute('data-modus', look)
  await wait(150)
  report.looks[look] = bubbleOf()
  report.looks[look].house = getComputedStyle(root).getPropertyValue('--blase').trim()
}
root.setAttribute('data-modus', 'dunkel')
root.style.setProperty('--blase-eigen', '#123456')
await wait(150)
report.picked = bubbleOf()
root.style.removeProperty('--blase-eigen')

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-chatreach-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {"nachricht": "../../src/teile/Nachricht.svelte"}, encoding="utf-8"
        )
        (folder / "scene.svelte.js").write_text(SCENE_JS, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS
            % {"global": "../../src/stil/global.css", "codeblock": "../../src/stil/codeblock.css"},
            encoding="utf-8",
        )
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        built = subprocess.run(
            [str(FRONTEND / "node_modules" / ".bin" / "vite"), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert built.returncode == 0, (built.stdout + built.stderr)[-2000:]
        (folder / "measure.html").write_text(PAGE % {"cases": CASES}, encoding="utf-8")
        raw = _measure(program, folder, (folder / "measure.html").as_uri())
        assert raw, "the page wrote no report"
        out = json.loads(raw)
        assert "failure" not in out, out["failure"]
        return out
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_attachment_pictures_stand_two_in_a_row(report):
    four = report["four"]
    column = four["block"]["width"]
    tile = (column - 6) / 2
    assert len(four["tiles"]) == 4, four
    for box in four["tiles"]:
        assert abs(box["width"] - tile) <= 1, (box, tile)
        assert abs(box["height"] - box["width"]) <= 1, box
    first, second, third, fourth = four["tiles"]
    assert abs(first["top"] - second["top"]) <= 1 and abs(third["top"] - fourth["top"]) <= 1
    assert third["top"] > first["bottom"], "the second row stands under the first"
    assert abs(second["left"] - first["right"] - 6) <= 1, "the gap between two tiles is 6px"


def test_the_card_stands_above_the_pictures_and_the_bubble_under_both(report):
    four = report["four"]
    assert four["hasCard"] and four["cards"]["bottom"] <= four["grid"]["top"] + 1, four
    assert four["bubble"]["top"] >= four["grid"]["bottom"] - 1, four
    assert four["insideBubble"] is False, "no attachment stands inside the bubble"


def test_a_lone_picture_stands_on_the_side_of_the_bubble(report):
    three = report["three"]
    last = three["tiles"][2]
    assert abs(last["right"] - three["block"]["right"]) <= 1, three
    assert abs(last["width"] - three["tiles"][0]["width"]) <= 1, "as wide as the others, not stretched"
    assert abs(report["threeLeft"]["tiles"][2]["left"] - report["threeLeft"]["block"]["left"]) <= 1
    one = report["one"]
    assert abs(one["tiles"][0]["right"] - one["block"]["right"]) <= 1, one
    assert abs(report["oneLeft"]["tiles"][0]["left"] - report["oneLeft"]["block"]["left"]) <= 1


def test_a_message_of_pictures_alone_has_no_empty_bubble(report):
    assert report["one"]["bubble"] is None, report["one"]


def test_the_bubble_under_attachments_is_the_ordinary_one(report):
    assert report["four"]["bubbleStyle"] == report["plain"]["bubbleStyle"], (
        report["four"]["bubbleStyle"], report["plain"]["bubbleStyle"],
    )
    assert report["plain"]["block"] is None, "a message without attachments draws as before"


def test_code_grows_with_the_chat_font(report):
    seventeen, twenty_two = report["code"]["17"], report["code"]["22"]
    assert seventeen["found"] and twenty_two["found"], report["code"]
    assert abs(seventeen["inChat"] - 12.8) < 0.01, seventeen
    assert abs(twenty_two["inChat"] - 22 * 12.8 / 17) < 0.05, twenty_two


def test_code_outside_the_chat_keeps_its_size(report):
    assert report["code"]["17"]["outside"] == 12.8
    assert report["code"]["22"]["outside"] == 12.8


def test_the_bar_is_as_wide_as_the_text_column():
    """The same two rules, lifted out of the sources: the bar's width is the
    column's content width, where the chat is as wide as it is set and where
    the window is narrower than that."""
    bar = (SRC / "teile" / "Eingabeleiste.svelte").read_text(encoding="utf-8")
    rule = re.search(r"\.menueplatz,\s*\.eingabe \{\s*width: (min\([^;]*\));", bar)
    assert rule, "the bar's width rule is gone"
    assert rule.group(1) == "min(calc(var(--chat-breite, 900px) - 56px), calc(100% - 56px))"
    app = (SRC / "App.svelte").read_text(encoding="utf-8")
    column = re.search(r"\n  \.spur \{\s*max-width: var\(--chat-breite, 900px\);.*?padding: 46px 28px 84px;", app, re.S)
    assert column, "the column's width and side room changed: the bar's width follows them"
    # Chat width 900, window wide: 900 - 56 on both sides. Window narrower: its own width less 56.
    for chat, window in ((900, 1400), (900, 700), (1400, 1000)):
        text_column = min(chat, window) - 56
        bar_width = min(chat - 56, window - 56)
        assert bar_width == text_column, (chat, window)


def test_a_picture_of_the_chat_is_capped_at_the_tile_size(report):
    assert report["cap"] and report["cap"]["width"] <= 300 + 1, report["cap"]
    app = (SRC / "App.svelte").read_text(encoding="utf-8")
    assert app.count("bildDeckel={BILDLAUF_KACHEL}") >= 3, "a single message is capped like the tiles"


def test_the_factory_layout_and_bubble_colour(report):
    assert report["factory"] == {"column": "900px", "font": "16px", "gap": "24px"}, report["factory"]
    dark = report["looks"]["dunkel"]
    assert dark["background"] == "rgb(97, 97, 97)", dark
    red, green, blue = (int(v) for v in re.findall(r"\d+", dark["color"])[:3])
    assert min(red, green, blue) > 200, f"the ink is light: {dark['color']}"


def test_the_other_looks_and_a_colour_picked_stay_as_they_were(report):
    for look in ("hell", "snow"):
        assert report["looks"][look]["background"] != "rgb(97, 97, 97)", report["looks"][look]
    assert report["looks"]["darkmatter"]["background"] == "rgb(203, 188, 238)", report["looks"]["darkmatter"]
    assert report["picked"]["background"] == "rgb(18, 52, 86)", report["picked"]
