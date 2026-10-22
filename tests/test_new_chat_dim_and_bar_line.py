"""Small things on the phone page and one left alone on the desktop page, drawn as
shipped in headless Chrome:

* the microphone and the send arrow of the phone's input bar stand on one centre
  line (with the plus beside them), for one line of text and for several;
* the phone's button for a new chat (the plus of the head) stands dimmed while a
  click would change nothing, and is whole again as soon as it would;
* the desktop's plus for a new chat is never dimmed: a page for the phone does not
  change the desktop page.

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

SHELL = """<script>
  import Header from '../../src/phone/Header.svelte'
  import InputBar from '../../src/phone/InputBar.svelte'
  import Seitenleiste from '../../src/teile/Seitenleiste.svelte'
</script>

<div id="phone" style="width: 390px"><Header /><InputBar questions={{ pushedAway: [], questionHidden: false, resume() {} }} /></div>
<div id="desktop"><Seitenleiste /></div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { zustand, seiteZeigen, seitenSchliessen } from '../../src/lib/zustand.svelte.js'
import '../../src/stil/global.css'

window.zustand = zustand
window.seiteZeigen = seiteZeigen
window.seitenSchliessen = seitenSchliessen
try {
  mount(Shell, { target: document.getElementById('root') })
} catch (failure) {
  window.__mountError = String(failure && failure.stack || failure)
}
"""

CASES = r"""
const { zustand } = window
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const pen = () => document.querySelector('#phone header button[aria-label="chat.neu"]')
const plus = () => document.querySelector('#desktop button[aria-label="chat.neu"]')
const state = (button) => ({
  disabled: button.getAttribute('aria-disabled'),
  opacity: getComputedStyle(button).opacity,
  idle: button.classList.contains('idle'),
})
const centre = (el) => { const r = el.getBoundingClientRect(); return r.top + r.height / 2 }
const bar = () => ({
  plus: centre(document.querySelector('#phone .row .plus')),
  mic: centre(document.querySelector('#phone .row .mic')),
  micButton: centre(document.querySelector('#phone .row .mic button')),
  send: centre(document.querySelector('#phone .row .act')),
})
const report = {}

await wait(500)
if (window.__mountError) throw new Error(window.__mountError)
// 1. A new, empty chat: a click would change nothing.
report.empty = { pen: state(pen()), plus: state(plus()) }

// 2. A chat stands open with a message: the buttons are whole, and the pen works.
zustand.aktiverChat = 'c1'
zustand.nachrichten = [{ id: 'm1', role: 'user', content: 'hello' }]
await wait(300)
report.open = { pen: state(pen()), plus: state(plus()) }
pen().click()
await wait(300)
report.afterClick = { chat: zustand.aktiverChat, messages: zustand.nachrichten.length, pen: state(pen()) }

// 3. The empty chat with a page over the main area: the desktop plus is the same.
window.seiteZeigen('prompt')
await wait(300)
report.page = { plus: state(plus()) }
window.seitenSchliessen()

// 4. The side sheet shows another sheet: a click would bring the chat list.
zustand.seitenblatt = 'jobs'
await wait(300)
report.sheet = { pen: state(pen()), plus: state(plus()) }
zustand.seitenblatt = 'chats'
await wait(200)

// 5. The head of the phone page draws the very sign the desktop plus draws.
const sign = (button) => button.querySelector('svg')
report.signs = {
  phone: sign(pen()).innerHTML,
  desktop: sign(plus()).innerHTML,
  phoneSize: sign(pen()).getAttribute('width'),
  desktopSize: sign(plus()).getAttribute('width'),
}

// 6. The input bar: one line, then four.
report.lineOne = bar()
const field = document.querySelector('#phone textarea')
field.value = 'one\ntwo\nthree\nfour'
field.dispatchEvent(new Event('input', { bubbles: true }))
await wait(400)
report.lineFour = bar()
report.fieldHeight = field.getBoundingClientRect().height

document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    if shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists():
        pytest.skip("no node or no frontend dependencies on this machine")
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-newchat-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "entry.js").write_text(ENTRY_JS, encoding="utf-8")
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


DIM = {"disabled": "true", "opacity": "0.5", "idle": True}
WHOLE = {"disabled": "false", "opacity": "1", "idle": False}
# The desktop plus: no `aria-disabled`, no `idle`, full strength — in every state.
PLAIN = {"disabled": None, "opacity": "1", "idle": False}


def test_a_new_empty_chat_leaves_the_pen_dimmed_and_the_desktop_plus_alone(report):
    assert report["empty"] == {"pen": DIM, "plus": PLAIN}, report["empty"]


def test_silence_with_a_chat_open_the_pen_is_whole_and_works(report):
    assert report["open"] == {"pen": WHOLE, "plus": PLAIN}, report["open"]
    # The click went through: the chat is closed, the list empty — and the
    # button is dimmed again, because another click would change nothing.
    assert report["afterClick"] == {"chat": None, "messages": 0, "pen": DIM}, report["afterClick"]


def test_silence_the_desktop_plus_stays_plain_over_a_page_and_with_another_sheet(report):
    assert report["page"] == {"plus": PLAIN}, report["page"]
    assert report["sheet"] == {"pen": WHOLE, "plus": PLAIN}, report["sheet"]


def test_the_phone_head_draws_the_plus_the_desktop_draws(report):
    signs = report["signs"]
    assert signs["phone"] == signs["desktop"], signs
    assert signs["phoneSize"] == "24" and signs["desktopSize"] == "24", signs


def test_the_phone_head_names_the_plus_and_not_the_pen():
    head = (SRC / "phone" / "Header.svelte").read_text(encoding="utf-8")
    assert '<Hauszeichen zeichen="plus"' in head
    assert 'zeichen="neu"' not in head


def test_the_sidebar_does_not_know_the_idle_state():
    bar = (SRC / "teile" / "Seitenleiste.svelte").read_text(encoding="utf-8")
    for word in ("newChatIdle", "plusIdle", "aria-disabled", ".zk.idle"):
        assert word not in bar, word


def test_microphone_send_arrow_and_plus_share_one_centre_line(report):
    for key in ("lineOne", "lineFour"):
        bar = report[key]
        assert abs(bar["mic"] - bar["send"]) < 0.5, (key, bar)
        assert abs(bar["plus"] - bar["send"]) < 0.5, (key, bar)
        # The 30 px button sits in the middle of its 36 px box.
        assert abs(bar["micButton"] - bar["send"]) < 0.5, (key, bar)
    assert report["fieldHeight"] > 60, report["fieldHeight"]


def test_the_microphone_box_is_as_big_as_its_neighbours():
    bar = (SRC / "phone" / "InputBar.svelte").read_text(encoding="utf-8")
    box = re.search(r"\.mic \{[^}]*\}", bar).group(0)
    assert "width: 36px" in box and "height: 36px" in box
    assert re.search(r'<span class="mic">\s*<Mikrofonknopf', bar)
