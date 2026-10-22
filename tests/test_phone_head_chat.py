"""The head and the chat of the phone page: the mark in the head, the chat as a
tile, the buttons under one's own bubble, the foot of an answer, the plus sheet
with the model, the tools as rows of the chat list.

Two kinds of test. The shape of the files (the order of the rows of the sheet,
what the head holds and no longer holds, the tools as rows of the chat list)
is read from the sources. What a screen shows is measured: `Nachricht.svelte`
and `ContextRing.svelte` are built as they are shipped, with the very rule that
`ChatView.svelte` puts round every message, and drawn in headless Chrome at
the width of a phone:

* an own message is as wide as its text (at most 80 %), stands at the right
  edge, and the buttons under it stand at the right edge of the bubble — always,
  with no pointer over it — and "send again" only under the last question;
* the foot of an answer starts at the column of its text, not at the line;
* on the desktop page (no `data-phone`) both stay as they were;
* the ring is a button, the tap opens a window with the percentage and the
  tokens, a tap elsewhere shuts it, over four fifths it turns yellow.

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
PHONE = SRC / "phone"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ——— the shape of the files ———


def test_the_head_holds_the_mark_the_ring_and_a_new_chat_and_nothing_else():
    head = _source(PHONE / "Header.svelte")
    assert "<Wortmarke hoehe={26} />" in head
    assert "<ContextRing tippbar />" in head
    assert 'zeichen="plus"' in head and "if (!idle) neuerChat()" in head
    # no model pill, no wrench, no tool dot: the model is chosen in the plus
    # sheet, the tools are rows of the chat list
    for gone in ("class=\"pill\"", "ModelSheet", "workOpen", "workBusy", "Leuchtpunkt", 'zeichen="werkzeug"'):
        assert gone not in head, gone
    assert "grid-template-columns: 1fr auto 1fr" in head


def test_the_head_of_the_desktop_page_is_not_touched():
    app = _source(SRC / "App.svelte")
    assert "phone/Header" not in app and "tippbar" not in app


def test_the_chat_is_a_tile_on_the_frame_and_each_message_stands_in_a_flex_column():
    page = _source(PHONE / "Phone.svelte")
    assert "background: var(--frame, var(--bg))" in page
    chat = _source(PHONE / "ChatView.svelte")
    assert "box-shadow: var(--chat-edge, none)" in chat
    assert "html[data-modus='dunkel']) .chat" in chat
    assert re.search(r"\.spur > :global\(div:not\(\.tiles\)\) \{\s*display: flex;\s*flex-direction: column;", chat)


def test_the_plus_sheet_lists_camera_photos_files_then_model_thinking_mode_then_folders_and_skills():
    sheet = _source(PHONE / "AttachSheet.svelte")
    order = [
        "phone_chat.camera", "phone_chat.photos", "phone_chat.files",
        "modell.titel", "eingabe.denken", "berechtigungen.modus_beschriftung",
        "arbeitsordner.titel", "skills.quelle",
    ]
    main = sheet[sheet.index('<div class="tiles">'):]
    places = [main.index(f"t('{key}')") for key in order]
    assert places == sorted(places), dict(zip(order, places, strict=True))
    # the camera wears a camera, not an eye
    camera = sheet[sheet.index("camera?.click()"):sheet.index("phone_chat.camera")]
    assert 'zeichen="kamera"' in camera and 'zeichen="auge"' not in camera
    # the model's row leads to a second step of the same sheet, with a way back
    assert "onclick={() => (step = 'models')}" in sheet
    assert "<ModelList onpick={pickModel} />" in sheet
    assert "onclick={() => (step = 'main')}" in sheet


def test_the_model_is_chosen_nowhere_else_on_the_phone_page():
    assert not (PHONE / "ModelSheet.svelte").exists()
    for path in PHONE.rglob("*.svelte"):
        assert "ModelSheet" not in _source(path), path.name


def test_the_signs_the_sheet_and_the_head_ask_for_are_drawn():
    signs = _source(SRC / "teile" / "Hauszeichen.svelte")
    for name in ("kamera", "neu", "schild"):
        assert f"zeichen === '{name}'" in signs, name


def test_the_chat_list_has_one_row_per_tool_and_the_bar_opens_at_that_tool():
    drawer = _source(PHONE / "Drawer.svelte")
    assert "{#each TABS as tab (tab.name)}" in drawer
    assert "onclick={() => showTool(tab.name)}" in drawer
    assert re.search(r"async function showTool\(name\) \{\n    if \(!\(await pageClose\(\)\)\) return\n    drawerSet\(false\)\n    workOpen\(name\)", drawer)
    assert "{#if busy[tab.name]}<Leuchtpunkt" in drawer


# ——— what a screen shows ———

SHELL = """<script>
  import Nachricht from %(nachricht)r
  import ContextRing from %(ring)r
  import { scene } from './scene.svelte.js'
</script>

<div class="head" style="width: 390px; margin: 0 auto; display: flex; justify-content: flex-end;">
  <ContextRing tippbar />
</div>
<div class="track" style="width: 374px; margin: 0 auto;">
  <div class="spur">
    {#each scene.nachrichten as nachricht (nachricht.id)}
      <div>
        <Nachricht {nachricht} istLetzte={nachricht.id === scene.letzteAntwort}
                   istLetzteFrage={nachricht.id === scene.letzteFrage}
                   neuErzeugen={() => {}} neuSenden={() => {}} />
      </div>
    {/each}
  </div>
</div>

<style>
  .spur { display: flex; flex-direction: column; gap: 10px; }
  %(rule)s
</style>
"""

SCENE_JS = """export const scene = $state({ nachrichten: [], letzteAntwort: null, letzteFrage: null })
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { scene } from './scene.svelte.js'
import { zustand } from %(zustand)r
import %(global)r

window.scene = scene
window.zustand = zustand
mount(Shell, { target: document.getElementById('root') })
"""

CASES = r"""
const { scene, zustand } = window
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const report = {}
const box = (el) => el.getBoundingClientRect()
const track = () => box(document.querySelector('.track'))

const question = (id, content) => ({ id, role: 'user', content })
const answer = (id, content, extra = {}) => ({
  id, role: 'assistant', rolle: 'assistant', content,
  abschnitte: [{ art: 'content', text: content }], werkzeuge: [], stats: {}, ...extra,
})
const long = 'This is a long question that has to run over more than one line of the chat, '
  + 'so that the bubble reaches the widest it may be and has to stop there, at four fifths.'
scene.nachrichten = [
  question('q1', 'Spaß'),
  answer('a1', 'Because it was stopped, this answer ends where it was.', { zustand: 'abgebrochen' }),
  question('q2', long),
]
scene.letzteFrage = 'q2'
scene.letzteAntwort = 'a1'

const measure = async () => {
  await wait(500)
  const bubbles = [...document.querySelectorAll('.von-mir')]
  const feet = [...document.querySelectorAll('.fuss.meine')]
  const reply = document.querySelector('.von-ki')
  const line = reply.querySelector('.antwortlinie')
  const foot = reply.querySelector(':scope > .fuss')
  return {
    track: track().width,
    short: { width: box(bubbles[0]).width, right: box(bubbles[0]).right },
    long: { width: box(bubbles[1]).width, right: box(bubbles[1]).right },
    trackRight: track().right,
    buttons: feet.map((f) => ({
      opacity: parseFloat(getComputedStyle(f).opacity),
      right: box(f).right,
      count: f.querySelectorAll('button').length,
      size: box(f.querySelector('button')).width,
    })),
    bubbleBottomToButtons: [0, 1].map((k) => box(feet[k]).top - box(bubbles[k]).bottom),
    footLeft: box(foot.firstElementChild).left - box(line).left,
    footWord: foot.textContent.includes('nachricht.stopped_hint'),
    footButton: box(foot.querySelector('button')).width,
  }
}

// 1. The desktop page: the buttons wait for the pointer, the foot starts at the line.
report.desktop = await measure()

// 2. The phone page.
document.documentElement.setAttribute('data-phone', '')
report.phone = await measure()

// 3. The ring: a tap opens the window, a tap elsewhere shuts it.
zustand.modellId = 'm1'
zustand.modelle = [{ id: 'm1', name: 'Test model', context_tokens: 32768 }]
zustand.aktiverChat = 'c1'
zustand.nachrichtenChatId = 'c1'
zustand.nachrichten = [answer('r1', 'x', { stats: { gesamt_tokens: 12160 } })]
await wait(300)
const ringButton = () => document.querySelector('.tippring')
report.ring = { stands: Boolean(ringButton()), size: ringButton() ? box(ringButton()).width : 0 }
ringButton().click()
await wait(200)
const pop = () => document.querySelector('.pop')
report.ring.open = Boolean(pop())
report.ring.expanded = ringButton().getAttribute('aria-expanded')
report.ring.text = pop() ? pop().textContent.replace(/\s+/g, ' ').trim() : ''
report.ring.under = pop() ? box(pop()).top >= 40 : false
document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
await wait(100)
report.ring.shutByTap = !pop()
ringButton().click()
await wait(100)
window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
await wait(100)
report.ring.shutByKey = !pop()
// a tap on the ring's own window does not shut it
ringButton().click()
await wait(100)
pop().dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
await wait(100)
report.ring.stayedOnOwnTap = Boolean(pop())
report.ring.fillBefore = getComputedStyle(document.querySelector('.tippring .fill')).stroke

// over four fifths the fill turns yellow
zustand.nachrichten = [answer('r1', 'x', { stats: { gesamt_tokens: 29000 } })]
await wait(300)
report.ring.fillFull = getComputedStyle(document.querySelector('.tippring .fill')).stroke
report.ring.fullClass = document.querySelector('.tippring .fill').classList.contains('voll')

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    if shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists():
        pytest.skip("no node or no frontend dependencies on this machine")
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    chat = _source(PHONE / "ChatView.svelte")
    found = re.search(r"\.spur > :global\(div:not\(\.tiles\)\) \{.*?\n  \}", chat, re.S)
    assert found, "the frame rule of the chat is gone"
    folder = FRONTEND / "node_modules" / f".harness-headchat-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(
            SHELL
            % {
                "nachricht": "../../src/teile/Nachricht.svelte",
                "ring": "../../src/teile/ContextRing.svelte",
                "rule": found.group(0),
            },
            encoding="utf-8",
        )
        (folder / "scene.svelte.js").write_text(SCENE_JS, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS
            % {"zustand": "../../src/lib/zustand.svelte.js", "global": "../../src/stil/global.css"},
            encoding="utf-8",
        )
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        built = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
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


def test_an_own_bubble_is_as_wide_as_its_text_and_stands_at_the_right_edge(report):
    phone = report["phone"]
    assert phone["short"]["width"] < phone["track"] * 0.3, phone["short"]
    assert abs(phone["short"]["right"] - phone["trackRight"]) <= 1.5, phone
    assert phone["long"]["width"] <= phone["track"] * 0.8 + 0.5, phone["long"]
    assert abs(phone["long"]["right"] - phone["trackRight"]) <= 1.5, phone


def test_the_buttons_under_an_own_bubble_always_show_at_its_right_edge(report):
    phone = report["phone"]
    first, second = phone["buttons"]
    assert first["opacity"] == 1 and second["opacity"] == 1, phone["buttons"]
    assert abs(first["right"] - phone["short"]["right"]) <= 1.5, (first, phone["short"])
    assert abs(second["right"] - phone["long"]["right"]) <= 1.5, (second, phone["long"])
    assert all(0 <= gap <= 12 for gap in phone["bubbleBottomToButtons"]), phone["bubbleBottomToButtons"]
    assert first["size"] == second["size"] == 32


def test_send_again_stands_under_the_last_question_only(report):
    first, second = report["phone"]["buttons"]
    assert first["count"] == 1 and second["count"] == 2, (first, second)


def test_the_foot_of_an_answer_starts_at_the_column_of_its_text(report):
    phone = report["phone"]
    assert abs(phone["footLeft"] - 22) <= 1.5, phone["footLeft"]
    assert phone["footWord"] is True
    assert phone["footButton"] == 32


def test_silence_the_desktop_page_keeps_the_buttons_for_the_pointer_and_the_foot_at_the_line(report):
    desktop = report["desktop"]
    assert [b["opacity"] for b in desktop["buttons"]] == [0, 0], desktop["buttons"]
    assert abs(desktop["footLeft"]) <= 1.5, desktop["footLeft"]
    assert desktop["footButton"] < 32


def test_the_ring_is_a_button_that_opens_the_figures_and_shuts_on_a_tap_elsewhere(report):
    ring = report["ring"]
    assert ring["stands"] is True and ring["size"] == 44, ring
    assert ring["open"] is True and ring["expanded"] == "true", ring
    # 12 160 of 32 768 tokens is 37 per cent; the page carries no catalog, so
    # the sentence with the figures shows as its key
    for part in ("modell.kontext", "37 %", "kontext.auslastung"):
        assert part in ring["text"], (part, ring["text"])
    assert "Test model" in ring["text"], ring["text"]
    assert ring["shutByTap"] is True and ring["shutByKey"] is True, ring
    assert ring["stayedOnOwnTap"] is True, ring


def test_the_fill_of_the_ring_turns_yellow_over_four_fifths(report):
    ring = report["ring"]
    assert ring["fullClass"] is True, ring
    assert ring["fillFull"] != ring["fillBefore"], ring
