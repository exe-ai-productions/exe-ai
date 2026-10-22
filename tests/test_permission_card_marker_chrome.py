"""The permission card marks the place its reason points at, in a real browser.

`teile/QuestionBox.svelte` (the window) and `phone/QuestionCard.svelte` (the
phone) are built as shipped and drawn in headless Chrome. A call that reaches
outside the shared folders is asked about with a reason and a value (the path,
the address, the program word). The sentence names no place: under the command
stands one quiet line of the command's own face, with no box and no ground,
and the value lies in the command under a soft marker, one surface for the
whole value across the colours of the highlighting and across a line break.
Where the command does not carry the value as written, it follows the sentence
after a colon. The mark of a question and its pill stand in the text colour.
The page makes up the questions; the shared question store is a stand-in of
the same shape. Skipped where there is no Chrome or no node.
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

SENTENCE = "Outside the shared folders"
LONG_PATH = "/tmp/" + "/".join(["a-long-folder-name"] * 6) + "/notes.txt"

ENTRY_JS = """import { mount } from 'svelte'
import QuestionBox from '../../src/teile/QuestionBox.svelte'
import QuestionCard from '../../src/phone/QuestionCard.svelte'
import '../../src/stil/global.css'
import english from '@@ENGLISH@@'
import { texte } from '../../src/lib/texte.svelte.js'

texte.katalog = english
texte.sprache = 'en'
window.fetch = async () => new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })

const LONG = @@LONG@@
const CASES = {
  hosts: { command: 'cat /etc/hosts', grund: '@@SENTENCE@@', grundWert: '/etc/hosts' },
  plain: { command: 'cat /etc/hosts' },
  resolved: { command: 'cat /etc/hosts', grund: '@@SENTENCE@@', grundWert: '/private/etc/hosts' },
  lying: { command: 'cat /other/hosts', grund: '@@SENTENCE@@', grundWert: '/private/other/hosts' },
  quoted: { command: 'echo "/etc/hosts"', grund: '@@SENTENCE@@', grundWert: '/etc/hosts' },
  quotedPlain: { command: 'echo "/etc/hosts"' },
  wrapped: { command: 'cat ' + LONG, grund: '@@SENTENCE@@', grundWert: LONG },
  home: { command: 'ls ~/notes', grund: '@@SENTENCE@@', grundWert: '/Users/x/notes' },
  word: { command: 'cd /tmp/exe-ai && exe settings', grund: 'Runs Exe AI\\'s own command line', grundWert: 'exe' },
  twice: { command: 'cp /etc/hosts /etc/hosts.bak && cat /etc/hosts', grund: '@@SENTENCE@@', grundWert: '/etc/hosts' },
  dollar: { command: 'cat "/tmp/$HOME/x"', grund: '@@SENTENCE@@', grundWert: '/tmp/$HOME/x' },
  none: { command: 'ls -la' },
  confirmation: { command: 'ls -la', grund: 'Requires your approval before running', grundWert: '' },
}
const wurzel = document.getElementById('wurzel')
for (const [key, extra] of Object.entries(CASES)) {
  const question = {
    name: 'run_command', chatId: 'c-' + key, aufrufId: key,
    argumente: { command: extra.command },
    grund: extra.grund ?? '', grundWert: extra.grundWert ?? '',
  }
  const windowHolder = document.createElement('div')
  windowHolder.id = 'w-' + key
  windowHolder.style.cssText = 'position: relative; width: 640px; min-height: 620px; margin: 0 0 16px'
  wurzel.appendChild(windowHolder)
  mount(QuestionBox, {
    target: windowHolder,
    props: { kind: 'tool', question, answerTool() {}, answerAsk() {}, onLater() {} },
  })
  const phoneHolder = document.createElement('div')
  phoneHolder.id = 'p-' + key
  phoneHolder.style.cssText = 'width: 360px; margin: 0 0 16px'
  wurzel.appendChild(phoneHolder)
  mount(QuestionCard, {
    target: phoneHolder,
    props: {
      questions: {
        standing: { kind: 'tool', question },
        modelName: 'Model',
        answerTool() {},
        answerAsk() {},
        later() {},
      },
    },
  })
}
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
const text = (node) => (node?.textContent || '').replace(/\s+/g, ' ').trim()
await wait(1200)

// What a value of a custom property computes to, in the card's own place.
const resolved = (root, property, value) => {
  const probe = document.createElement('i')
  probe.style.cssText = property + ': ' + value
  root.appendChild(probe)
  const computed = getComputedStyle(probe)[property === 'font-family' ? 'fontFamily' : 'color']
  probe.remove()
  return computed
}
const spans = (command) =>
  Array.from(command.querySelectorAll('span:not(.quiet):not(.unfold)')).map((n) => n.className + '=' + n.textContent)

// The text of the command up to the place where a node stands.
const textBefore = (command, node) => {
  const range = document.createRange()
  range.setStart(command, 0)
  range.setEndBefore(node)
  return range.toString()
}

const read = (id) => {
  const root = document.getElementById(id)
  const command = root.querySelector('.command')
  const reason = root.querySelector('.reason')
  const marks = Array.from(command?.querySelectorAll('mark.outside') ?? [])
  const first = marks[0]
  const reasonStyle = reason ? getComputedStyle(reason) : null
  return {
    command: text(command),
    marks: marks.map(text),
    before: first ? textBefore(command, first).slice(-6) : null,
    rects: first ? first.getClientRects().length : 0,
    height: first ? Math.round(first.getBoundingClientRect().height * 10) / 10 : 0,
    markColour: first ? getComputedStyle(first).color : null,
    commandColour: command ? getComputedStyle(command).color : null,
    markGround: first ? getComputedStyle(first).backgroundColor : null,
    inner: first ? Array.from(first.querySelectorAll('span')).map((n) => n.className + '=' + n.textContent) : [],
    spans: command ? spans(command) : [],
    reason: reason ? text(reason) : null,
    reasonGround: reasonStyle?.backgroundColor ?? null,
    reasonShadow: reasonStyle?.boxShadow ?? null,
    reasonBorder: reasonStyle?.borderTopWidth ?? null,
    reasonFont: reasonStyle?.fontFamily ?? null,
    reasonColour: reasonStyle?.color ?? null,
    expectedFont: resolved(root, 'font-family', 'var(--schrift-fest)'),
    expectedColour: resolved(root, 'color', 'var(--text-still)'),
    textColour: resolved(root, 'color', 'var(--text)'),
    badge: root.querySelector('.badge') ? getComputedStyle(root.querySelector('.badge')).color : null,
    pill: root.querySelector('.pill') ? getComputedStyle(root.querySelector('.pill')).color : null,
    sign: reason?.querySelector('svg') ? getComputedStyle(reason.querySelector('svg')).color : null,
    signGap: reason?.querySelector('svg') ? Math.round((reason.querySelector('svg').getBoundingClientRect().top - reason.getBoundingClientRect().top) * 10) / 10 : null,
    dollarLeft: command?.querySelector('.quiet') ? Math.round(command.querySelector('.quiet').getBoundingClientRect().left) : null,
    reasonLeft: reason?.querySelector('svg') ? Math.round(reason.querySelector('svg').getBoundingClientRect().left) : null,
    yellow: resolved(root, 'color', 'var(--gelb)'),
  }
}
for (const side of ['w', 'p']) {
  report[side] = {}
  for (const key of ['hosts', 'plain', 'resolved', 'lying', 'quoted', 'quotedPlain', 'wrapped', 'home', 'word', 'twice', 'dollar', 'none', 'confirmation']) {
    report[side][key] = read(side + '-' + key)
  }
}
document.title = 'open'
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="out/style.css">
<style>html { --stufenfaktor: 1; } html, body { margin: 0; background: #2a2a28; } #wurzel { width: 700px; padding: 12px; }</style>
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


async def _drive(port: int, limit: float = 150.0) -> dict:
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
                await asyncio.sleep(0.25)
        assert raw, "the page reported nothing"
        report = json.loads(raw)
        assert "failure" not in report, report["failure"]
        return report


def _run_case() -> dict:
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-permission-card-marker-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        entry = (
            ENTRY_JS.replace("@@ENGLISH@@", str(ROOT / "app" / "locales" / "en.json"))
            .replace("@@LONG@@", json.dumps(LONG_PATH))
            .replace("@@SENTENCE@@", SENTENCE)
        )
        (folder / "entry.js").write_text(entry, encoding="utf-8")
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        build = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=240,
        )
        assert build.returncode == 0, (build.stdout + build.stderr)[-2000:]
        (folder / "measure.html").write_text(PAGE.replace("@@CASES@@", CASES), encoding="utf-8")
        port = _free_port()
        browser = subprocess.Popen(
            [
                program,
                "--headless=new",
                "--mute-audio",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-file-access-from-files",
                "--window-size=900,900",
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
def report() -> dict:
    return _run_case()


@pytest.fixture(params=["w", "p"], ids=["window", "phone"])
def side(request, report) -> dict:
    return report[request.param]


def test_the_path_outside_is_marked_in_the_command_and_its_colours_stay(side):
    card = side["hosts"]
    assert card["marks"] == ["/etc/hosts"], card
    # The colouring of the command is the same as without a marker (the phone
    # never colours, so there both lists are empty).
    assert card["spans"] == side["plain"]["spans"], (card["spans"], side["plain"]["spans"])
    assert card["command"] == "$ cat /etc/hosts" == side["plain"]["command"], card
    assert card["markColour"] == card["commandColour"], card
    assert card["markGround"] not in ("rgba(0, 0, 0, 0)", "transparent"), card
    assert 14 <= card["height"] <= 18, card


def test_the_warning_line_has_no_box_no_ground_the_fixed_face_and_the_quiet_colour(side):
    card = side["hosts"]
    assert card["reason"] == SENTENCE, card
    assert card["reasonGround"] == "rgba(0, 0, 0, 0)", card
    assert card["reasonShadow"] == "none" and card["reasonBorder"] == "0px", card
    assert card["reasonFont"] == card["expectedFont"], card
    assert card["reasonColour"] == card["expectedColour"], card
    # The sign is the waiting colour, and the line stands under the dollar sign.
    assert card["sign"] == card["yellow"], card
    assert abs(card["reasonLeft"] - card["dollarLeft"]) <= 1, card
    # Centred on the first line of an 18 px line: a 13 px sign sits 2.5 px down.
    assert 2 <= card["signGap"] <= 3, card


def test_a_path_that_breaks_over_lines_is_one_marker_with_a_surface_on_each_line(side):
    card = side["wrapped"]
    assert card["marks"] == [LONG_PATH], card
    assert card["rects"] >= 2, card
    assert card["reason"] == SENTENCE, card


def test_a_place_the_service_names_resolved_is_marked_where_the_command_wrote_it(side):
    # A Mac keeps /etc under /private: the service names /private/etc/hosts,
    # the command wrote /etc/hosts — the same place, marked where it stands.
    card = side["resolved"]
    assert card["marks"] == ["/etc/hosts"], card
    assert card["reason"] == SENTENCE, card
    # Only the three folders the system links are read that way.
    lying = side["lying"]
    assert lying["marks"] == [], lying
    assert lying["reason"] == f"{SENTENCE}: /private/other/hosts", lying


def test_a_path_the_command_does_not_carry_follows_the_sentence_after_a_colon(side):
    card = side["home"]
    assert card["marks"] == [], card
    assert card["reason"] == f"{SENTENCE}: /Users/x/notes", card


def test_the_program_word_is_marked_alone_and_not_inside_a_longer_word(side):
    card = side["word"]
    assert card["marks"] == ["exe"], card
    assert card["before"].endswith("&& "), card
    assert card["reason"] == "Runs Exe AI's own command line", card


def test_a_place_that_stands_twice_is_marked_at_each_stand(side):
    card = side["twice"]
    assert card["marks"] == ["/etc/hosts", "/etc/hosts"], card
    assert card["reason"] == SENTENCE, card


def test_a_dollar_sign_in_the_path_stays_a_dollar_sign(side):
    card = side["dollar"]
    assert card["marks"] == ["/tmp/$HOME/x"], card
    assert card["command"] == '$ cat "/tmp/$HOME/x"', card


def test_the_mark_of_a_question_and_its_pill_stand_in_the_text_colour(report):
    card = report["w"]["hosts"]
    assert card["badge"] == card["textColour"], card
    assert card["pill"] == card["textColour"], card


def test_silence_no_reason_no_line_and_a_reason_without_a_place_has_no_colon(side):
    assert side["none"]["reason"] is None and side["none"]["marks"] == [], side["none"]
    assert side["confirmation"]["reason"] == "Requires your approval before running", side["confirmation"]
    assert side["confirmation"]["marks"] == [], side["confirmation"]


def test_a_place_inside_a_quoted_string_keeps_the_colour_of_the_string(report):
    card = report["w"]["quoted"]
    plain = report["w"]["quotedPlain"]
    assert card["marks"] == ["/etc/hosts"], card
    # The colour of the string is closed before the marker and opened again
    # inside it: what is marked still reads in the string's colour.
    assert any(item.endswith("=/etc/hosts") and "hljs-string" in item for item in card["inner"]), card
    assert "".join(item.split("=", 1)[1] for item in card["spans"]) == "".join(
        item.split("=", 1)[1] for item in plain["spans"]
    ), (card["spans"], plain["spans"])
