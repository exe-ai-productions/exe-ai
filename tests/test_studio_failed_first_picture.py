"""A chat the studio opened for a picture stays when the picture fails.

Drawing in the studio without an open chat opens one. When the picture fails
or is stopped, nothing is deleted: the chat stays in the list and stays open,
the prompt stands in the prompt bar, the pictures, the mask and the values
stand in the studio, and the failed run stands in the terminal with what it
said. The next press draws with them, into the same chat. Only the person
deletes a chat.

Run rather than read: the studio's drawing module, its values, the chat's
store and the terminal are compiled with the Svelte compiler (they use
runes) and run in node; the window's state module, the service and the
picture line are stand-ins. What two components do on a chat change — the
studio's column refills the values, the window reconnects the terminal — is
done by the stand-in that changes the chat.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
LIB = FRONTEND / "src/lib"
MODULES = ["chatanzeige.svelte.js", "studio.svelte.js", "terminalfenster.svelte.js", "studiozeichnen.svelte.js"]

needs_node = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)

# The window's state module, the service and the small modules around the
# studio, as stand-ins. The chat functions do what the real ones do, in the
# same order, and then what the mounted components would do on the change.
STUBS = """
import { proxy } from 'svelte/internal/client'
export const calls = []
export const service = { chats: [], rows: {}, runs: {}, stores: {} }
export const zustand = proxy({
  aktiverChat: null, nachrichten: [], chats: [], modellId: 'text-model', seitenblatt: 'projekte',
  bildLaeuftChat: {}, laeuft: {}, sendet: {}, features: {},
})
export const nachrichtenAnzeige = () => zustand.nachrichten
export const eineSeiteOffen = () => false
export const seitenSchliessen = () => {}
export const istSeitenleisteSchmal = () => false
export const said = []
export const melde = (text, kind) => said.push([text, kind ?? ''])
export const t = (key) => key
export const seedlage = { letzter: null }
export const imageSwitches = { list: [] }
export const loadImageSwitches = async () => {}
export const imageFamilies = { list: [] }
export const loadImageFamilies = async () => {}
export const familyOf = () => null
export const leiste = { offen: false }
export const zeitweiseOeffnen = () => {}
export const columnsForStudio = () => {}
export const columnsBack = () => {}
export const anbieten = () => {}
export const videoFrames = async () => []
export const api = {
  laeufe: async (id) => {
    calls.push(['runs', id])
    return { laeufe: structuredClone(service.runs[id] ?? []), ab: 0 }
  },
  laeufeStrom: (id, ab) => `laeufe/${id}?ab=${ab}`,
  einstellungAufgeloestViele: async (keys, { chat }) => ({ bildfenster: { wert: service.stores[chat] ?? {} } }),
  einstellungSetzen: async (scope, key, value) => {
    service.stores[scope.slice(5)] = { ...(service.stores[scope.slice(5)] ?? {}), ...value }
  },
  bildVorgaben: async () => null,
  chatLoeschen: async (id) => {
    calls.push(['delete', id])
    service.chats = service.chats.filter((c) => c !== id)
    delete service.rows[id]
    delete service.runs[id]
  },
}

// The compiled modules, handed in by the driver once they are loaded.
export const parts = {}
/* What the mounted components do on a chat change: the studio's column
   fills the values for the chat and shows the model's start values for
   those the chat has none of its own for, the window reconnects the
   terminal. */
export const START_VALUES = { modell: 'picture-model', schritte: 8 }
function mounted() {
  const missing = parts.studio.werteFuellen()
  parts.studio.werteVorschlagen(
    Object.fromEntries(Object.entries(START_VALUES).filter(([name]) => missing.includes(name))),
  )
  parts.terminal.verbinden(zustand.aktiverChat)
}
const listChats = async () => { zustand.chats = service.chats.map((id) => ({ id })) }

export async function openChat(id) {
  zustand.aktiverChat = id
  const read = parts.chatanzeige.chatZustandLaden(id)
  mounted()
  await read
  mounted()
}
let created = 0
export async function openNewChat(data) {
  created += 1
  const id = `new-${created}`
  service.chats.push(id)
  calls.push(['create', id, data.title])
  const held = parts.chatanzeige.chatless.pictureValues?.(id) ?? null
  if (held) await api.einstellungSetzen(`chat:${id}`, 'bildfenster', held)
  await openChat(id)
  await listChats()
  return { id }
}
export function neuerChat() {
  zustand.seitenblatt = 'chats'
  zustand.aktiverChat = null
  parts.chatanzeige.chatZustandLaden(null)
  mounted()
}
export async function chatLoeschen(id) {
  await api.chatLoeschen(id)
  if (zustand.aktiverChat === id) neuerChat()
  await listChats()
}
export const chatOeffnen = openChat
"""

DRIVER = """
import { compileModule } from 'svelte/compiler'
import { readFileSync, writeFileSync } from 'fs'
const STAND_INS = ['api.js', 'zustand.svelte.js', 'texte.svelte.js', 'bildseed.svelte.js', 'imageSwitches.svelte.js',
  'imageFamilies.svelte.js', 'arbeitsleiste.svelte.js', 'studioColumns.svelte.js', 'videoFrames.js']
const REAL = %(modules)s
for (const name of REAL) {
  let code = compileModule(readFileSync(%(lib)r + '/' + name, 'utf-8'), { filename: name, generate: 'client' }).js.code
  for (const other of STAND_INS) code = code.replaceAll(`from './${other}'`, "from './taken-back.stubs.mjs'")
  for (const other of REAL) code = code.replaceAll(`from './${other}'`, `from './taken-back.${other}.mjs'`)
  code = code.replaceAll("from './werkzeughistorie.js'", "from './src/lib/werkzeughistorie.js'")
  code = code.replaceAll("from './chatName.js'", "from './src/lib/chatName.js'")
  writeFileSync(`taken-back.${name}.mjs`, code)
}
// The run stream the terminal opens for the open chat: what the service
// reports for a run reaches the terminal over it.
const streams = []
globalThis.EventSource = class {
  constructor(url) { this.url = url; this.open = true; streams.push(this) }
  close() { this.open = false }
}
let reported = 0
const reports = (chat, event) => {
  for (const stream of streams) {
    if (stream.open && stream.url.startsWith(`laeufe/${chat}?`)) {
      stream.onmessage?.({ data: JSON.stringify({ ...event, n: 1000 + reported++ }) })
    }
  }
}
const stubs = await import('./taken-back.stubs.mjs')
const chatanzeige = await import('./taken-back.chatanzeige.svelte.js.mjs')
const studio = await import('./taken-back.studio.svelte.js.mjs')
const terminal = await import('./taken-back.terminalfenster.svelte.js.mjs')
const draw = await import('./taken-back.studiozeichnen.svelte.js.mjs')
Object.assign(stubs.parts, { chatanzeige, studio, terminal })
const { zustand, service, calls } = stubs

// The studio is what the window shows, and the picture line is handed in:
// every wish waits until the scenario says how its picture ended.
studio.studio.offen = true
const wishes = []
draw.zeichnung.losZeichnen = (wish) => {
  // The service opens the picture's run under its chat as it begins.
  const runs = (service.runs[wish.chat_id] ??= [])
  const run = { lauf: runs.length + 1, befehl: wish.prompt, art: 'bild', zustand: 'laeuft', ausgabe: '' }
  runs.push(run)
  wishes.push({ wish, run })
  reports(wish.chat_id, { typ: 'lauf_start', lauf: run.lauf, befehl: wish.prompt, art: 'bild' })
}
// The service ends a picture's run and says so on the chat's stream.
const ends = (n, state, text = '') => {
  const { wish, run } = wishes[n]
  Object.assign(run, { zustand: state, ausgabe: text })
  if (text) reports(wish.chat_id, { typ: 'lauf_zeile', lauf: run.lauf, text, strom: 'stderr' })
  reports(wish.chat_id, { typ: 'lauf_ende', lauf: run.lauf, zustand: state, code: null })
}
const fails = (n, text = 'no tokenizer found') => ends(n, 'fehler', text)
const stops = (n) => ends(n, 'abgebrochen')
const draws = (n) => {
  service.rows[wishes[n].wish.chat_id] = [{ id: 1, role: 'assistant', bild: 'p.png' }]
  ends(n, 'fertig')
}
const settled = async () => { for (let i = 0; i < 40; i += 1) await new Promise((r) => setTimeout(r, 0)) }
const asked = (kind) => calls.filter((c) => c[0] === kind).length
// What the window shows, as one reading.
const reading = () => ({
  chats: zustand.chats.map((c) => c.id), open: zustand.aktiverChat, storeOf: chatanzeige.chatanzeige.chatId,
  prompt: studio.werte.prompt, width: studio.werte.breite, steps: studio.werte.schritte, model: studio.werte.modell,
  set: Object.keys(studio.setValues()).sort(), sheet: zustand.seitenblatt,
  runs: terminal.terminal.laeufe.map((l) => [l.lauf, l.zustand, l.ausgabe]),
  deleted: calls.filter((c) => c[0] === 'delete').map((c) => c[1]),
})
// The studio as somebody left it without a chat: a prompt and a width set
// by hand, the model's start values shown for the rest.
const setUp = async () => {
  stubs.neuerChat()
  zustand.seitenblatt = 'projekte'
  studio.werte.prompt = 'a cat on a roof'
  studio.werte.breite = 768
}
const report = await (async () => {
%(scenario)s
})()
console.log('---REPORT---' + JSON.stringify(report))
process.exit(0)
"""


def _run(scenario: str) -> dict:
    files = {
        FRONTEND / "taken-back.stubs.mjs": STUBS,
        FRONTEND / "taken-back.driver.mjs": DRIVER % {
            "modules": json.dumps(MODULES), "lib": str(LIB), "scenario": scenario,
        },
    }
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
    try:
        done = subprocess.run(
            ["node", "taken-back.driver.mjs"], cwd=FRONTEND, capture_output=True, text=True,
            encoding="utf-8", timeout=120,
        )
    finally:
        for path in [*files, *(FRONTEND / f"taken-back.{name}.mjs" for name in MODULES)]:
            path.unlink(missing_ok=True)
    assert done.returncode == 0, (done.stdout + done.stderr)[-3000:]
    mark = "---REPORT---"
    assert mark in done.stdout, done.stdout[-3000:]
    return json.loads(done.stdout.split(mark, 1)[1].strip())


@needs_node
def test_a_chat_opened_for_a_picture_that_fails_stays_open_with_everything_in_it():
    """No chat open, one picture, it fails: the chat is in the list and open,
    the studio's values stand, the mask stands with the chat, the failed run
    is in the terminal with what it said, and nothing was deleted. The next
    press draws with the same values into the same chat."""
    report = _run("""
    await setUp()
    const mask = studio.maskeDesChats(null, 'area.png')
    const before = reading()
    await draw.studioZeichnen()
    const drawing = reading()
    fails(0)
    await settled()
    const after = reading()
    const maskStays = studio.maskeDesChats('new-1', 'area.png') === mask
    await draw.studioZeichnen()
    await settled()
    return { before, drawing, after, maskStays, again: reading(), stored: service.stores['new-1'],
             wishes: wishes.map((w) => [w.wish.chat_id, w.wish.prompt, w.wish.breite]), created: asked('create') }
    """)
    assert report["drawing"]["chats"] == ["new-1"] and report["drawing"]["open"] == "new-1"

    after = report["after"]
    assert after["deleted"] == []
    assert after["chats"] == ["new-1"] and after["open"] == "new-1" and after["storeOf"] == "new-1"
    # The values as before the press: what was set is set, what was shown is shown.
    for name in ("prompt", "width", "steps", "model"):
        assert after[name] == report["before"][name], (name, after[name])
    assert after["prompt"] == "a cat on a roof" and after["width"] == 768 and after["steps"] == 8
    # What was set belongs to the chat now: its store holds it.
    assert report["before"]["set"] == ["breite", "prompt"] and after["set"] == []
    assert report["stored"] == {"breite": 768, "prompt": "a cat on a roof"}
    assert report["maskStays"]
    # The failed run with what it said.
    assert after["runs"] == [[1, "fehler", "no tokenizer found"]]
    # The next press: the same chat, the same values, no second chat.
    assert report["created"] == 1
    assert report["wishes"] == [["new-1", "a cat on a roof", 768], ["new-1", "a cat on a roof", 768]]
    assert report["again"]["deleted"] == []


@needs_node
def test_the_chat_a_picture_opens_is_named_at_a_word_end_like_every_new_chat():
    """No chat open, a prompt of sixty-two characters in words: the new chat
    is named by the one rule — at most 48 characters, cut where a word ends,
    then the mark. Silence probe: a prompt of exactly 48 stays whole, an
    empty one is refused before any chat is opened (a finished picture made
    larger, which has no prompt of its own, keeps the studio's word for a
    name), and a chat that is open stays the chat: none is made."""
    report = _run("""
    const named = async (prompt) => {
      await setUp()
      studio.werte.prompt = prompt
      const before = asked('create')
      await draw.studioZeichnen()
      draws(wishes.length - 1)
      await settled()
      return calls.filter((c) => c[0] === 'create').slice(before).map((c) => c[2])
    }
    const long = await named('Which seeds will still bloom well in a north facing garden bed')
    const exact = await named('Which seeds will still bloom well in a north bed')
    const empty = await named('')
    // A finished picture made larger has no prompt of its own: no chat is
    // open, so one is made, and it keeps the studio's word for a name.
    await setUp()
    studio.werte.prompt = ''
    const beforeUpscale = asked('create')
    await draw.studioZeichnen({ mode: 'upscale', prompt: 'a bloom' })
    await settled()
    const upscaled = calls.filter((c) => c[0] === 'create').slice(beforeUpscale).map((c) => c[2])
    service.chats.push('A')
    await stubs.openChat('A')
    studio.werte.prompt = 'a long prompt that would have named a chat of its own here'
    const before = asked('create')
    await draw.studioZeichnen()
    draws(wishes.length - 1)
    await settled()
    return { long, exact, empty, upscaled, openedWhileOpen: asked('create') - before }
    """)
    assert report["long"] == ["Which seeds will still bloom well in a north…"]
    assert report["exact"] == ["Which seeds will still bloom well in a north bed"]
    assert report["empty"] == []
    assert report["upscaled"] == ["eingabe.bild_titel"]
    assert report["openedWhileOpen"] == 0


@needs_node
def test_a_chat_that_was_open_before_stays_after_a_failed_picture():
    """Silence probe: a chat that was open before the press is left as it is."""
    report = _run("""
    service.chats.push('A')
    service.stores.A = { prompt: 'a dog' }
    await stubs.openNewChat({ title: 'not this one' })
    await stubs.openChat('A')
    await draw.studioZeichnen()
    fails(0)
    await settled()
    return reading()
    """)
    assert report["open"] == "A" and report["deleted"] == [] and report["chats"] == ["A", "new-1"]
    assert report["prompt"] == "a dog"


@needs_node
def test_a_chat_opened_for_a_picture_that_is_drawn_stays():
    """Silence probe: a drawn picture is in the chat — the only one, or one
    of several of the same press — and nothing is deleted."""
    report = _run("""
    await setUp()
    await draw.studioZeichnen()
    draws(0)
    await settled()
    const one = reading()
    await setUp()
    studio.werte.bilder_je_lauf = 3
    await draw.studioZeichnen()
    fails(1)
    draws(2)
    fails(3)
    await settled()
    return { one, several: reading(), pictures: wishes.length }
    """)
    assert report["one"]["open"] == "new-1" and report["one"]["deleted"] == []
    assert report["pictures"] == 4
    assert report["several"]["open"] == "new-2" and report["several"]["deleted"] == []


@needs_node
def test_every_picture_of_the_press_failing_leaves_the_chat_standing():
    report = _run("""
    await setUp()
    studio.werte.bilder_je_lauf = 3
    await draw.studioZeichnen()
    fails(0)
    fails(1)
    await settled()
    const meanwhile = reading()
    fails(2)
    await settled()
    return { meanwhile, after: reading() }
    """)
    assert report["meanwhile"]["open"] == "new-1" and report["meanwhile"]["deleted"] == []
    after = report["after"]
    assert after["deleted"] == [] and after["chats"] == ["new-1"] and after["open"] == "new-1"
    assert after["prompt"] == "a cat on a roof"
    assert [run[1] for run in after["runs"]] == ["fehler", "fehler", "fehler"]


@needs_node
def test_a_picture_that_fails_while_another_chat_is_open_touches_nothing_of_it():
    """The picture fails while another chat is open: the chat that was opened
    for it stays in the list, the open chat, its values and its runs stay as
    they are, and nothing is deleted."""
    report = _run("""
    await setUp()
    await draw.studioZeichnen()
    service.chats.push('B')
    service.stores.B = { prompt: 'a ship' }
    service.runs.B = [{ lauf: 1, befehl: 'ls', art: 'befehl', zustand: 'fertig', ausgabe: 'x' }]
    await stubs.openChat('B')
    fails(0)
    await settled()
    return { ...reading(), held: service.chats }
    """)
    assert report["deleted"] == [] and report["held"] == ["new-1", "B"] and report["open"] == "B"
    assert report["prompt"] == "a ship"
    assert report["runs"] == [[1, "fertig", "x"]]


@needs_node
def test_a_chat_deleted_by_hand_takes_its_runs_with_it():
    """Silence probe: the person's own deleting a chat empties the terminal
    as before; the chat's runs go with it."""
    report = _run("""
    service.chats.push('A')
    service.runs.A = [{ lauf: 1, befehl: 'a picture', art: 'bild', zustand: 'fehler', ausgabe: 'failed' }]
    await stubs.openChat('A')
    const open = reading()
    await stubs.chatLoeschen('A')
    return { open, gone: reading() }
    """)
    assert report["open"]["runs"] == [[1, "fehler", "failed"]]
    assert report["gone"]["open"] is None and report["gone"]["runs"] == []


@needs_node
def test_a_first_picture_the_user_stops_leaves_the_chat_standing():
    """Stopping is no drawing, and no reason to delete: the chat stays, open,
    with the prompt, and the stopped runs stand in the terminal."""
    report = _run("""
    await setUp()
    studio.werte.bilder_je_lauf = 2
    await draw.studioZeichnen()
    stops(1)
    stops(0)
    await settled()
    return { pictures: wishes.length, after: reading() }
    """)
    assert report["pictures"] == 2
    after = report["after"]
    assert after["deleted"] == [] and after["chats"] == ["new-1"] and after["open"] == "new-1"
    assert after["prompt"] == "a cat on a roof"
    assert after["runs"] == [[1, "abgebrochen", ""], [2, "abgebrochen", ""]]


def test_the_studio_deletes_no_chat():
    """Nothing in the drawing module asks the service to delete a chat, and
    it keeps no wait for a run's end to do it by."""
    source = (LIB / "studiozeichnen.svelte.js").read_text(encoding="utf-8")
    for word in ("chatLoeschen", "takeBackUnlessDrawn", "openedUndrawn", "EventSource", "laeufeStrom"):
        assert word not in source, word


@needs_node
def test_an_enlarging_without_a_prompt_writes_no_question_into_the_chat():
    """The wish goes out with `frage_erstellen` false when it has no prompt
    (the picture then stands in the chat without a message of the person),
    and true when it has one."""
    report = _run("""
    await setUp()
    const wish = (prompt) => ({ mode: 'upscale', startbild: 'p.png', maske: null, upscale_model: 'x.pth', prompt })
    await draw.studioZeichnen(wish(''))
    await draw.studioZeichnen(wish('a bloom'))
    return wishes.map((w) => [w.wish.prompt, w.wish.frage_erstellen, w.wish.mode])
    """)
    assert report == [["", False, "upscale"], ["a bloom", True, "upscale"]]
