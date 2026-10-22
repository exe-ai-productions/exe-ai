"""The card of a finished chat, measured in a real browser.

When the answer of a chat ends while another chat is in front, the program
tells it with a card: the name of the chat in the first line, the beginning
of the answer in the second, each line one line high and ending in an
ellipsis where it is too long. The switch "Finished · popup" of the page
Notices decides whether the card is drawn; the sound and the dot in the rail
follow their own switches.

`Meldungen.svelte` is built as shipped with the global stylesheet and drawn in
headless Chrome. The notice list and the state are the program's own; only
the service is made up (it answers every request with an empty object).
Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

import pytest

from app import appfenster, prozessstopp

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

pytestmark = [
    pytest.mark.platforms("darwin", reason="the browser run of the interface is checked on macOS only"),
    pytest.mark.skipif(
        shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists(),
        reason="no node or no frontend dependencies on this machine",
    ),
]

SHELL = """<script>
  import Meldungen from '../../src/teile/Meldungen.svelte'
</script>

<div id="shell" style="position: relative; width: 1280px; height: 600px; overflow: hidden;">
  <Meldungen />
</div>
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import '../../src/stil/global.css'
import german from '@@GERMAN@@'
import { texte } from '../../src/lib/texte.svelte.js'
import { zustand, chatFertigMerken } from '../../src/lib/zustand.svelte.js'
import { meldungen, meldewesen, melde } from '../../src/lib/meldewesen.svelte.js'
import { answerPreview } from '../../src/lib/answerPreview.js'
import { KOPIER_ZEICHEN, TICK_SIGN } from '../../src/lib/markdown.js'

texte.katalog = german
texte.sprache = 'de'
window.__state = { zustand, meldungen, meldewesen, chatFertigMerken, melde, answerPreview, KOPIER_ZEICHEN, TICK_SIGN }
window.fetch = async () =>
  new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
mount(Shell, { target: document.getElementById('wurzel') })
"""

VITE_CONFIG = """import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte({ compilerOptions: { css: 'injected' } })],
  logLevel: 'error',
  build: {
    outDir: 'out',
    emptyOutDir: true,
    minify: false,
    lib: { entry: 'entry.js', formats: ['iife'], name: 'Measure', fileName: () => 'entry.js', cssFileName: 'style' },
  },
})
"""

CASES = r"""
const report = {}
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const { zustand, meldungen, meldewesen, chatFertigMerken, melde, answerPreview, KOPIER_ZEICHEN, TICK_SIGN } = window.__state
const rect = (node) => {
  if (!node) return null
  const r = node.getBoundingClientRect()
  return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom }
}
const style = (node) => {
  if (!node) return null
  const c = getComputedStyle(node)
  return { size: c.fontSize, weight: c.fontWeight, color: c.color, overflow: c.textOverflow, wrap: c.whiteSpace }
}
const probe = document.createElement('span')
document.body.appendChild(probe)
const colourOf = (name) => {
  probe.style.color = `var(${name})`
  return getComputedStyle(probe).color
}
report.tokens = { text: colourOf('--text'), leise: colourOf('--text-leise'), green: colourOf('--gruen') }

meldewesen.popupSekunden = 60
zustand.chats = [
  { id: 'a', title: 'Release-Notizen 0.7' },
  { id: 'b', title: 'Another chat' },
  { id: 'c', title: 'Short one' },
  { id: 'd', title: 'Markup' },
  { id: 'e', title: 'Off' },
  { id: 'f', title: 'Copied one' },
]
zustand.aktiverChat = 'b'
const cards = () => Array.from(document.querySelectorAll('.meldung'))
const describe = (card) => {
  if (!card) return { missing: true }
  const head = card.querySelector('.chat-name')
  const rest = card.querySelector('.answer-start')
  const mark = card.querySelector('.zeichen svg')
  return {
    card: rect(card),
    head: head && head.textContent,
    headStyle: style(head),
    headFits: head ? head.scrollWidth <= head.clientWidth : null,
    headRect: rect(head),
    rest: rest && rest.textContent,
    restStyle: style(rest),
    restClipped: rest ? rest.scrollWidth > rest.clientWidth : null,
    restRect: rect(rest),
    restChildren: rest ? rest.children.length : null,
    mark: rect(mark),
    markColour: mark ? getComputedStyle(mark.parentElement).color : null,
    twoLine: Boolean(card.querySelector('.two-lines')),
    textStyle: style(card.querySelector('.text')),
    lineClamp: card.querySelector('.text') ? getComputedStyle(card.querySelector('.text')).webkitLineClamp : null,
    cross: Boolean(card.querySelector('.zu')),
  }
}
const clear = async () => {
  meldungen.liste.splice(0)
  await wait(500)
}

// A long answer in a chat that is not in front: Markdown, a thinking block and a fence in it.
const LONG = '<think>the secret reasoning</think>\n# Release notes 0.7\n\nHere are the **release notes** for version 0.7, sorted by [area](https://example.invalid/x) and `date` — and a long tail that cannot fit in one line of the card at all, so it has to end in an ellipsis.\n```js\nconst x = 1\n```\n- last item'
chatFertigMerken('a', LONG)
await wait(900)
report.long = { count: cards().length, ...describe(cards()[0]) }
report.preview = {
  long: answerPreview(LONG),
  tags: answerPreview('<b>bold</b> <img src=x onerror=alert(1)> done'),
  empty: answerPreview(''),
  onlyThinking: answerPreview('<think>only this'),
  fenceOnly: answerPreview('```\ncode line\n```'),
  names: answerPreview('I changed chat_run.py and 2*3 (see https://x.io/a_b_c)'),
  link: answerPreview('[Foo](https://en.wikipedia.org/wiki/Foo_(bar)) next'),
  lists: answerPreview('> - [ ] task one\n---\n| a | b |\n|---|---|\n1. second'),
}
await clear()

// A short answer: one line, no ellipsis.
chatFertigMerken('c', 'All done.')
await wait(900)
report.short = { count: cards().length, ...describe(cards()[0]) }
await clear()

// Text of the user and of the model is text: markup in it stays as written.
chatFertigMerken('d', '<b>bold</b> <img src=x onerror="window.__hit=1"> done')
await wait(900)
report.markup = { count: cards().length, ...describe(cards()[0]), hit: window.__hit ?? 0 }
await clear()

// A chat that has no name in the list, and an answer that has nothing to show: the card stays two lines high.
chatFertigMerken('zz', '<think>only thoughts')
await wait(900)
report.nameless = { count: cards().length, ...describe(cards()[0]) }
await clear()

// The switch "Finished · popup" off: no card, the dot of the rail still stands.
meldewesen.melder.fertig = false
chatFertigMerken('e', 'This must not show.')
await wait(700)
report.off = { count: cards().length, dot: zustand.fertigeChats.includes('e') }
meldewesen.melder.fertig = true
await clear()

// The other cards are as they were.
melde('A plain sentence that is not about a chat.', 'hinweis')
melde('Saved.', 'erfolg')
await wait(900)
report.others = cards().map(describe)
// A sentence of several lines shows two and ends in an ellipsis; its copy button puts the whole of it on the clipboard.
const SENTENCE = 'Another Exe AI service uses this data folder and holds its servers. Use its servers, or stop that service first. This one is longer still, so that it runs over a third line and a fourth, and its last word is the proof: finished.'
let clipboardText = null
Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: (text) => { clipboardText = text; return Promise.resolve() } } })
await clear()
melde(SENTENCE, 'fehler')
await wait(900)
const longCard = cards()[0]
const longText = longCard.querySelector('.text')
const lineHeight = parseFloat(getComputedStyle(longText).lineHeight)
report.sentence = {
  text: longText.textContent,
  cut: longText.scrollHeight > longText.clientHeight,
  lines: Math.round(longText.clientHeight / lineHeight),
  clamp: getComputedStyle(longText).webkitLineClamp,
  card: rect(longCard),
  twoLine: Boolean(longCard.querySelector('.two-lines')),
}
const copyButton = longCard.querySelector('.copy')
const signs = document.createElement('button')
signs.innerHTML = KOPIER_ZEICHEN + TICK_SIGN
const tickOpacity = () => getComputedStyle(copyButton.querySelector('.code-tick')).opacity
report.copy = {
  signs: copyButton.innerHTML.replace(/<!---->/g, '') === signs.innerHTML,
  title: copyButton.title,
  label: copyButton.getAttribute('aria-label'),
  box: rect(copyButton),
  cross: rect(longCard.querySelector('.zu')),
  before: tickOpacity(),
}
copyButton.click()
await wait(350)
report.copy.after = { text: clipboardText, copied: copyButton.classList.contains('copied'), tick: tickOpacity(), cards: cards().length }
await wait(1100)
report.copy.later = { copied: copyButton.classList.contains('copied'), tick: tickOpacity() }

// The notice of a finished chat: its name and its text, one line each.
await clear()
chatFertigMerken('f', 'Nothing left.')
await wait(900)
cards()[0].querySelector('.copy').click()
await wait(350)
report.copyChat = clipboardText
await clear()

// A pointer on the card holds its clock; leaving gives it its time again.
melde('Held while the pointer is on it', 'hinweis', { dauer: 1000 })
await wait(300)
const heldCard = cards()[0]
heldCard.dispatchEvent(new PointerEvent('pointerenter', { pointerType: 'mouse' }))
await wait(1500)
const underPointer = cards().length
heldCard.dispatchEvent(new PointerEvent('pointerleave', { pointerType: 'mouse' }))
await wait(600)
const justAfter = cards().length
await wait(1200)
report.hold = { underPointer, justAfter, finally: cards().length }
// A finger does not hold the card: a touch pointer entering leaves the clock running.
melde('A finger does not hold this', 'hinweis', { dauer: 600 })
await wait(200)
cards()[0].dispatchEvent(new PointerEvent('pointerenter', { pointerType: 'touch' }))
await wait(1100)
report.touchHold = cards().length
// Without a pointer a notice closes after its time, as it always did.
melde('Nobody holds this', 'hinweis', { dauer: 600 })
await wait(1400)
report.plainGone = cards().length
await clear()
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="out/style.css">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 1280px; height: 600px; position: relative; }</style>
</head><body>
<div id="wurzel"></div>
<pre id="ergebnis" style="display: none"></pre>
<script src="out/entry.js"></script>
<script>
  window.addEventListener('load', async () => {
    try {
      @@CASES@@
    } catch (failure) {
      document.getElementById('ergebnis').textContent = JSON.stringify({ failure: String(failure && failure.stack || failure) })
    }
  })
</script>
</body></html>
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _drive(port: int, limit: float = 180.0) -> dict:
    """Read the page's report over the debug port."""
    websockets = pytest.importorskip("websockets")
    end = time.monotonic() + limit
    address = None
    while time.monotonic() < end and address is None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2) as response:
                for page in json.load(response):
                    if page.get("type") == "page" and "measure.html" in page.get("url", ""):
                        address = page["webSocketDebuggerUrl"]
        except OSError:
            pass
        if address is None:
            await asyncio.sleep(0.2)
    assert address, "Chrome did not open the page"
    async with websockets.connect(address, max_size=32 * 1024 * 1024) as connection:
        number = 0

        async def value_of(expression: str):
            nonlocal number
            number += 1
            await connection.send(
                json.dumps({"id": number, "method": "Runtime.evaluate",
                            "params": {"expression": expression, "returnByValue": True}})
            )
            while True:
                response = json.loads(await connection.recv())
                if response.get("id") == number:
                    return response.get("result", {}).get("result", {}).get("value")

        raw = ""
        while time.monotonic() < end and not raw:
            raw = await value_of("document.getElementById('ergebnis')?.textContent || ''")
            if not raw:
                await asyncio.sleep(0.5)
        assert raw, "the page reported nothing"
        report = json.loads(raw)
        assert "failure" not in report, report["failure"]
        return report


def _run_case() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-finished-card-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "Shell.svelte").write_text(SHELL, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS.replace("@@GERMAN@@", str(ROOT / "app" / "locales" / "de.json")), encoding="utf-8")
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        assert (folder / "out" / "style.css").exists(), "the build made no stylesheet"
        (folder / "measure.html").write_text(PAGE.replace("@@CASES@@", CASES), encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                "--window-size=1280,600",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={folder / 'profile'}",
                (folder / "measure.html").as_uri(),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            return asyncio.run(_drive(port))
        finally:
            prozessstopp.beenden(browser, frist=5)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture(scope="module")
def measured() -> dict:
    return _run_case()


def test_the_harness_has_the_house_colours(measured):
    assert measured["tokens"]["text"] != measured["tokens"]["leise"]
    assert measured["tokens"]["green"] not in ("rgb(0, 0, 0)", "")


def test_a_finished_answer_in_another_chat_shows_exactly_one_card(measured):
    assert measured["long"]["count"] == 1
    assert measured["long"]["twoLine"]


def test_the_first_line_is_the_name_of_the_chat_in_13_px_semi_bold(measured):
    card = measured["long"]
    assert card["head"] == "Release-Notizen 0.7"
    assert card["headStyle"]["size"] == "13px" and card["headStyle"]["weight"] == "600"
    assert card["headStyle"]["color"] == measured["tokens"]["text"]


def test_the_second_line_is_the_beginning_of_the_answer_in_13_px_quiet(measured):
    card = measured["long"]
    assert card["rest"].startswith("Release notes 0.7 Here are the release notes for version 0.7")
    assert card["restStyle"]["size"] == "13px" and card["restStyle"]["weight"] == "400"
    assert card["restStyle"]["color"] == measured["tokens"]["leise"]


def test_a_long_answer_ends_in_an_ellipsis_on_one_line(measured):
    card = measured["long"]
    assert card["restClipped"] and card["restStyle"]["overflow"] == "ellipsis"
    assert card["restStyle"]["wrap"] == "nowrap"
    assert card["restRect"]["height"] <= 20 and card["headRect"]["height"] <= 20, card


def test_the_card_is_460_wide_and_62_high_with_the_tick_and_the_cross(measured):
    card = measured["long"]
    assert abs(card["card"]["width"] - 460) <= 1 and abs(card["card"]["height"] - 62) <= 1, card["card"]
    assert abs(card["mark"]["width"] - 20) <= 0.5 and abs(card["mark"]["height"] - 20) <= 0.5, card["mark"]
    assert card["markColour"] == measured["tokens"]["green"]
    assert card["cross"]


def test_markdown_marks_and_the_thinking_block_do_not_stand_on_the_card(measured):
    preview = measured["preview"]["long"]
    for mark in ("#", "**", "`", "](", "```", "secret reasoning", "<think>"):
        assert mark not in preview, (mark, preview)
    assert "\n" not in preview and "  " not in preview
    assert "area" in preview and "const x = 1" in preview
    assert measured["preview"]["onlyThinking"] == ""
    assert measured["preview"]["empty"] == ""
    assert measured["preview"]["fenceOnly"] == "code line"


def test_a_short_answer_stands_whole_in_one_line(measured):
    card = measured["short"]
    assert card["count"] == 1 and card["head"] == "Short one" and card["rest"] == "All done."
    assert card["restClipped"] is False
    assert abs(card["card"]["height"] - 62) <= 1, card["card"]


def test_what_the_user_and_the_model_wrote_is_text_never_markup(measured):
    card = measured["markup"]
    assert card["count"] == 1
    assert card["restChildren"] == 0
    assert "<b>bold</b>" in card["rest"] and "<img" in card["rest"]
    assert card["hit"] == 0, "a handler in the answer ran"


def test_with_the_switch_off_no_card_is_drawn_but_the_dot_stays(measured):
    assert measured["off"] == {"count": 0, "dot": True}


def test_silence_the_other_cards_are_as_they_were(measured):
    others = measured["others"]
    assert len(others) == 2
    for card in others:
        assert not card["twoLine"] and card["head"] is None
        assert abs(card["card"]["width"] - 460) <= 1


def test_the_finished_chat_reaches_the_card_with_its_answer_and_only_when_nobody_watched():
    source = (FRONTEND / "src" / "lib" / "chatlauf.svelte.js").read_text(encoding="utf-8")
    guard = source.split("const fertigerChat = zielChat", 1)[1].split("platzhalter.zustand =", 1)[0]
    assert "(fertigerChat !== zustand.aktiverChat || !document.hasFocus())" in guard
    assert "chatFertigMerken(fertigerChat, platzhalter.content)" in guard


def test_the_marks_of_markdown_go_but_the_signs_of_a_name_stay(measured):
    preview = measured["preview"]
    assert preview["names"] == "I changed chat_run.py and 2*3 (see https://x.io/a_b_c)"
    assert preview["link"] == "Foo next"
    assert preview["lists"] == "task one | a | b | second"


def test_a_chat_without_a_name_in_the_list_still_says_which_kind_of_chat_it_is(measured):
    german = json.loads((ROOT / "app" / "locales" / "de.json").read_text(encoding="utf-8"))
    card = measured["nameless"]
    assert card["count"] == 1 and card["head"] == german["chat"]["unbenannt"]
    # No words to show: the card keeps the height of two lines.
    assert card["rest"] is None
    assert abs(card["card"]["height"] - 62) <= 1, card["card"]


def test_a_sentence_of_several_lines_shows_two_and_the_card_keeps_its_width(measured):
    sentence = measured["sentence"]
    assert sentence["text"].endswith("finished."), sentence  # the whole sentence is in the card
    assert sentence["cut"], sentence  # but only two lines of it are shown
    assert sentence["lines"] == 2 and sentence["clamp"] == "2", sentence
    for card in measured["others"]:
        assert card["lineClamp"] == "2"
    assert abs(sentence["card"]["width"] - 460) <= 1
    assert not sentence["twoLine"]


def test_silence_a_short_notice_is_one_line_high_as_before(measured):
    for card in measured["others"]:
        assert card["card"]["height"] < 50, card["card"]


def test_the_card_carries_the_copy_button_of_the_code_block_beside_the_cross(measured):
    copy = measured["copy"]
    assert copy["signs"], "the copy mark and the tick are the code block's own"
    assert copy["title"] == copy["label"] and copy["title"]
    assert abs(copy["box"]["width"] - copy["cross"]["width"]) <= 0.5
    assert abs(copy["box"]["height"] - copy["cross"]["height"]) <= 0.5
    assert copy["box"]["right"] <= copy["cross"]["x"] + 0.5, "beside the cross, before it"
    assert copy["before"] == "0"


def test_a_press_puts_the_whole_sentence_on_the_clipboard_and_the_tick_stays_a_second(measured):
    copy = measured["copy"]
    assert copy["after"]["text"].endswith("finished.") and copy["after"]["text"].startswith("Another Exe AI service")
    assert copy["after"]["copied"] and copy["after"]["tick"] == "1"
    assert copy["after"]["cards"] == 1, "no second notice says it was copied"
    assert not copy["later"]["copied"] and copy["later"]["tick"] == "0"


def test_the_card_of_a_chat_copies_its_name_and_its_text_one_line_each(measured):
    assert measured["copyChat"] == "Copied one\nNothing left."


def test_under_the_pointer_the_card_stays_and_leaving_gives_it_its_time_again(measured):
    hold = measured["hold"]
    assert hold == {"underPointer": 1, "justAfter": 1, "finally": 0}, hold
    assert measured["touchHold"] == 0, "a touch must not hold the card"
    assert measured["plainGone"] == 0
