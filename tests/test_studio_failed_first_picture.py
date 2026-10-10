"""A chat the studio opened for a picture goes again when the picture fails.

Drawing in the studio without an open chat opens one. When none of the
pictures of that press is drawn, the chat is taken back: it would stand in
the list holding nothing but the prompt. The window then looks as it did
before the press — the prompt and every value set in the studio stand, the
failed run stays in the terminal with what it said until another chat is
opened. A chat that was there before the press always stays.

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
export const service = { chats: [], rows: {}, runs: {}, stores: {}, silent: false, keepsChats: false }
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
export const anbieten = () => {}
export const videoFrames = async () => []
export const api = {
  nachrichten: async (id) => {
    calls.push(['rows', id])
    if (service.silent) throw new Error('the service does not answer')
    return { nachrichten: service.rows[id] ?? [] }
  },
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
    if (service.keepsChats) throw new Error('the chat cannot be deleted')
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
  'imageFamilies.svelte.js', 'arbeitsleiste.svelte.js', 'videoFrames.js']
const REAL = %(modules)s
for (const name of REAL) {
  let code = compileModule(readFileSync(%(lib)r + '/' + name, 'utf-8'), { filename: name, generate: 'client' }).js.code
  for (const other of STAND_INS) code = code.replaceAll(`from './${other}'`, "from './taken-back.stubs.mjs'")
  for (const other of REAL) code = code.replaceAll(`from './${other}'`, `from './taken-back.${other}.mjs'`)
  code = code.replaceAll("from './werkzeughistorie.js'", "from './src/lib/werkzeughistorie.js'")
  writeFileSync(`taken-back.${name}.mjs`, code)
}
// The run streams the window opens, so a scenario can say what the service
// reports on them and count who is listening.
const streams = []
globalThis.EventSource = class {
  constructor(url) { this.url = url; this.open = true; streams.push(this) }
  close() { this.open = false }
}
const listening = (chat) => streams.filter((s) => s.open && s.url.startsWith(`laeufe/${chat}?`))
const reports = (chat, event) => {
  for (const stream of listening(chat)) stream.onmessage?.({ data: JSON.stringify(event) })
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
  let settle
  const outcome = new Promise((resolve) => { settle = resolve })
  // The service opens the picture's run under its chat as it begins.
  const runs = (service.runs[wish.chat_id] ??= [])
  const run = { lauf: runs.length + 1, befehl: wish.prompt, art: 'bild', zustand: 'laeuft', ausgabe: '' }
  runs.push(run)
  wishes.push({ wish, settle, run })
  return outcome
}
const fails = (n, text = 'no tokenizer found') => {
  Object.assign(wishes[n].run, { zustand: 'fehler', ausgabe: text })
  wishes[n].settle(false)
}
const draws = (n) => {
  wishes[n].run.zustand = 'fertig'
  service.rows[wishes[n].wish.chat_id] = [{ id: 1, role: 'assistant', bild: 'p.png' }]
  wishes[n].settle(true)
}
const settled = async () => { for (let i = 0; i < 40; i += 1) await new Promise((r) => setTimeout(r, 0)) }
// The service ends a run and says so on the chat's stream, in that order.
let reported = 0
const ends = (n, state, text = '') => {
  Object.assign(wishes[n].run, { zustand: state, ausgabe: text })
  reports(wishes[n].wish.chat_id, { typ: 'lauf_ende', lauf: wishes[n].run.lauf, zustand: state, code: null, n: reported++ })
}
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
            ["node", "taken-back.driver.mjs"], cwd=FRONTEND, capture_output=True, text=True, timeout=120,
        )
    finally:
        for path in [*files, *(FRONTEND / f"taken-back.{name}.mjs" for name in MODULES)]:
            path.unlink(missing_ok=True)
    assert done.returncode == 0, (done.stdout + done.stderr)[-3000:]
    mark = "---REPORT---"
    assert mark in done.stdout, done.stdout[-3000:]
    return json.loads(done.stdout.split(mark, 1)[1].strip())


@needs_node
def test_a_chat_opened_for_a_picture_that_fails_is_taken_back():
    """No chat open, one picture, it fails: the chat list is as long as
    before, the studio's values stand as they stood, and the failed run is
    still in the terminal — until another chat is opened."""
    report = _run("""
    await setUp()
    const mask = studio.maskeDesChats(null, 'area.png')
    const before = reading()
    await draw.studioZeichnen()
    const drawing = reading()
    fails(0)
    await settled()
    const after = reading()
    const maskStays = studio.maskeDesChats(null, 'area.png') === mask
    service.chats.push('B')
    await stubs.openChat('B')
    return { before, drawing, after, maskStays, other: reading(), sent: wishes[0].wish.prompt }
    """)
    assert report["drawing"]["chats"] == ["new-1"] and report["drawing"]["open"] == "new-1"
    assert report["sent"] == "a cat on a roof"

    after = report["after"]
    assert after["deleted"] == ["new-1"]
    assert after["chats"] == [] and after["open"] is None and after["storeOf"] is None
    # The values as before the press: what was set is set, what was shown is shown.
    for name in ("prompt", "width", "steps", "model", "set", "sheet"):
        assert after[name] == report["before"][name], (name, after[name])
    assert after["prompt"] == "a cat on a roof" and after["width"] == 768 and after["steps"] == 8
    assert after["set"] == ["breite", "prompt"]
    assert report["maskStays"]
    # The failed run with what it said, though its chat is gone.
    assert after["runs"] == [[1, "fehler", "no tokenizer found"]]
    # Another chat opened: the terminal is that chat's.
    assert report["other"]["open"] == "B" and report["other"]["runs"] == []


@needs_node
def test_a_chat_that_was_open_before_stays_after_a_failed_picture():
    """Silence probe: only a chat this press opened is ever taken back."""
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
    """Silence probe: one drawn picture keeps the chat — the only one, or
    one of several of the same press."""
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
def test_every_picture_of_the_press_failing_takes_the_chat_back():
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
    assert after["deleted"] == ["new-1"] and after["chats"] == []
    assert after["prompt"] == "a cat on a roof"
    assert [run[1] for run in after["runs"]] == ["fehler", "fehler", "fehler"]


@needs_node
@pytest.mark.parametrize("holds", ["a row", "a picture in the line", "an answer on its way", "nobody can say"])
def test_a_chat_that_holds_something_is_not_taken_back(holds):
    """Silence probe: the chat goes only while it holds nothing. A row the
    service keeps for it, a picture still waiting for it, an answer being
    written into it — or a service that cannot say — leaves it standing."""
    prepare = {
        "a row": "service.rows['new-1'] = [{ id: 7, role: 'user', content: 'and a text question' }]",
        "a picture in the line": "zustand.bildLaeuftChat = { 'new-1': true }",
        "an answer on its way": "zustand.laeuft = { 'new-1': true }",
        "nobody can say": "service.silent = true",
    }[holds]
    report = _run(f"""
    await setUp()
    await draw.studioZeichnen()
    {prepare}
    fails(0)
    await settled()
    return reading()
    """)
    assert report["deleted"] == [] and report["open"] == "new-1" and report["chats"] == ["new-1"]
    assert report["prompt"] == "a cat on a roof"


@needs_node
def test_a_second_press_into_the_opened_chat_asks_again_once_it_has_ended():
    """A second press while the first picture still draws goes into the chat
    the first one opened. The first failing leaves the chat, a picture is
    still in the line for it; the second failing takes it back. A picture
    drawn by either keeps it for good."""
    report = _run("""
    await setUp()
    await draw.studioZeichnen()
    await draw.studioZeichnen()
    zustand.bildLaeuftChat = { 'new-1': true }
    fails(0)
    await settled()
    const first = reading()
    zustand.bildLaeuftChat = {}
    fails(1)
    await settled()
    const second = reading()
    await setUp()
    await draw.studioZeichnen()
    await draw.studioZeichnen()
    draws(2)
    await settled()
    service.rows['new-2'] = []
    fails(3)
    await settled()
    return { first, second, kept: reading(), created: calls.filter((c) => c[0] === 'create').length }
    """)
    assert report["created"] == 2
    assert report["first"]["open"] == "new-1" and report["first"]["deleted"] == []
    assert report["second"]["deleted"] == ["new-1"] and report["second"]["open"] is None
    assert report["second"]["prompt"] == "a cat on a roof"
    assert report["kept"]["open"] == "new-2" and report["kept"]["deleted"] == ["new-1"]


@needs_node
def test_a_chat_left_meanwhile_goes_without_touching_what_the_window_shows():
    """The picture fails while another chat is open: the empty chat goes,
    the open chat, its values and its runs stay as they are."""
    report = _run("""
    await setUp()
    await draw.studioZeichnen()
    service.chats.push('B')
    service.stores.B = { prompt: 'a ship' }
    service.runs.B = [{ lauf: 1, befehl: 'ls', art: 'befehl', zustand: 'fertig', ausgabe: 'x' }]
    await stubs.openChat('B')
    fails(0)
    await settled()
    return reading()
    """)
    assert report["deleted"] == ["new-1"] and report["chats"] == ["B"] and report["open"] == "B"
    assert report["prompt"] == "a ship"
    assert report["runs"] == [[1, "fertig", "x"]]


@needs_node
def test_a_chat_that_cannot_be_deleted_stays_in_the_list_and_nothing_fails():
    report = _run("""
    await setUp()
    await draw.studioZeichnen()
    service.keepsChats = true
    fails(0)
    await settled()
    return { ...reading(), said: stubs.said }
    """)
    assert report["deleted"] == ["new-1"] and report["chats"] == ["new-1"]
    assert report["open"] is None and report["prompt"] == "a cat on a roof"
    assert report["said"] == []


@needs_node
def test_a_chat_deleted_by_hand_takes_its_runs_with_it():
    """Silence probe: only the studio's own taking back leaves runs
    standing. Any other way out of a chat empties the terminal as before."""
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


def test_the_picture_line_says_how_each_picture_ended():
    """The line in the window answers every wish once: after its own
    bookkeeping when the picture was worked off, and at once when the wish
    leaves the line undrawn — taken out, or stopped with the rest. What it
    answers with never travels to the service."""
    source = (FRONTEND / "src/App.svelte").read_text(encoding="utf-8")
    enqueue = re.search(r"\n  function bildLokalZeichnen\(wunsch\) \{.*?\n  \}\n", source, re.S)
    assert enqueue, "the way into the picture line was not found"
    assert "new Promise((resolve) => { settle = resolve })" in enqueue.group(0)
    assert "return outcome" in enqueue.group(0)
    line = re.search(r"\n  async function workPictureLine\(\) \{.*?\n  \}\n", source, re.S)
    assert line, "the loop of the picture line was not found"
    worked = line.group(0)
    assert worked.index("await bildEinesZeichnen(naechste)") < worked.index("bildChatsAktualisieren()\n        //") \
        < worked.index("naechste.settle(Boolean(naechste.drawn))")
    taken_out = re.search(r"\n  function removeWaitingPicture\(id\) \{.*?\n  \}\n", source, re.S).group(0)
    assert "gone.settle(false)" in taken_out
    stopped = re.search(r"\n  function bildStoppen\(\) \{.*?\n  \}\n", source, re.S).group(0)
    assert stopped.index("waiting.settle(false)") < stopped.index("bildQueue = []")
    assert "const { queue_id: _, settle: _settle, ...request } = wunsch" in source


# --- The chat only goes once the service has reported the end of its runs ---


@needs_node
def test_a_chat_whose_run_still_goes_is_only_taken_back_when_its_end_is_reported():
    """The picture line says "not drawn" while the service still holds the
    run as going: the chat stays, and the window listens on the chat's run
    stream instead of asking again. The moment the end is reported the chat
    goes — with the run as it ended in the terminal."""
    report = _run("""
    await setUp()
    await draw.studioZeichnen()
    const listeners = listening('new-1').length
    wishes[0].settle(false)
    await settled()
    const waiting = { ...reading(), listeners: listening('new-1').length, runsAsked: asked('runs') }
    await settled()
    const stillWaiting = { deleted: reading().deleted, runsAsked: asked('runs') }
    ends(0, 'fehler', 'no tokenizer found')
    await settled()
    return { listeners, waiting, stillWaiting, after: reading(), left: listening('new-1').length }
    """)
    waiting = report["waiting"]
    assert waiting["deleted"] == [] and waiting["chats"] == ["new-1"] and waiting["open"] == "new-1"
    # One listener more than the terminal's own, and no asking again while it waits.
    assert waiting["listeners"] == report["listeners"] + 1
    assert report["stillWaiting"] == {"deleted": [], "runsAsked": waiting["runsAsked"]}
    after = report["after"]
    assert after["deleted"] == ["new-1"] and after["chats"] == [] and after["open"] is None
    assert after["prompt"] == "a cat on a roof" and after["width"] == 768
    assert after["runs"] == [[1, "fehler", "no tokenizer found"]]
    # Nobody listens on a chat that is gone.
    assert report["left"] == 0
    # Waiting is listening: the module keeps no clock to ask again by.
    source = (LIB / "studiozeichnen.svelte.js").read_text(encoding="utf-8")
    assert "setTimeout" not in source and "setInterval" not in source


@needs_node
@pytest.mark.parametrize("state", ["fehler", "abgebrochen"])
def test_a_run_that_has_ended_when_looked_at_takes_the_chat_back_without_waiting(state):
    """Silence probe: the ordinary way — the service ends the run before it
    answers. Nobody listens for an end that has been reported already."""
    report = _run("""
    await setUp()
    await draw.studioZeichnen()
    const listeners = listening('new-1').length
    let most = listeners
    const watch = setInterval(() => { most = Math.max(most, listening('new-1').length) }, 0)
    Object.assign(wishes[0].run, { zustand: '%s', ausgabe: '' })
    wishes[0].settle(false)
    await settled()
    clearInterval(watch)
    return { listeners, most, after: reading() }
    """ % state)
    assert report["most"] == report["listeners"]
    assert report["after"]["deleted"] == ["new-1"]
    assert report["after"]["runs"] == [[1, state, ""]]


@needs_node
def test_a_first_picture_the_user_stops_takes_the_chat_back_once_its_end_is_reported():
    """Stopping is no drawing: the line tells every waiting picture "not
    drawn", and the chat goes — after the service has said that the stopped
    run has ended, not while the painter is still letting go."""
    report = _run("""
    await setUp()
    studio.werte.bilder_je_lauf = 2
    await draw.studioZeichnen()
    // Stop: the waiting picture is told at once, the drawing one when its request comes back.
    wishes[1].run.zustand = 'abgebrochen'
    wishes[1].settle(false)
    wishes[0].settle(false)
    await settled()
    const stopping = reading()
    ends(0, 'abgebrochen')
    await settled()
    return { pictures: wishes.length, stopping, after: reading() }
    """)
    assert report["pictures"] == 2
    assert report["stopping"]["deleted"] == [] and report["stopping"]["open"] == "new-1"
    after = report["after"]
    assert after["deleted"] == ["new-1"] and after["chats"] == [] and after["open"] is None
    assert after["prompt"] == "a cat on a roof"
    assert after["runs"] == [[1, "abgebrochen", ""], [2, "abgebrochen", ""]]


@needs_node
def test_a_run_that_ends_with_a_picture_after_all_leaves_the_chat_standing():
    """Everything is looked at afresh once the end is reported: a stopped
    picture the painter finished anyway is a row the chat holds."""
    report = _run("""
    await setUp()
    await draw.studioZeichnen()
    wishes[0].settle(false)
    await settled()
    service.rows['new-1'] = [{ id: 1, role: 'assistant', bild: 'p.png' }]
    ends(0, 'fertig')
    await settled()
    return { after: reading(), left: listening('new-1').length }
    """)
    assert report["after"]["deleted"] == [] and report["after"]["chats"] == ["new-1"]
    # Only the terminal still reads the open chat's stream.
    assert report["left"] == 1


@needs_node
def test_a_run_that_starts_while_the_window_waits_is_waited_for_as_well():
    """The chat goes when every run of it has ended, not when the first one
    it waited for has."""
    report = _run("""
    await setUp()
    await draw.studioZeichnen()
    wishes[0].settle(false)
    await settled()
    service.runs['new-1'].push({ lauf: 2, befehl: 'later', art: 'bild', zustand: 'laeuft', ausgabe: '' })
    reports('new-1', { typ: 'lauf_start', lauf: 2, befehl: 'later', art: 'bild', n: 90 })
    ends(0, 'fehler')
    await settled()
    const one = reading().deleted
    service.runs['new-1'][1].zustand = 'fehler'
    reports('new-1', { typ: 'lauf_ende', lauf: 2, zustand: 'fehler', code: null, n: 91 })
    await settled()
    return { one, both: reading().deleted }
    """)
    assert report["one"] == []
    assert report["both"] == ["new-1"]


@needs_node
def test_a_picture_drawn_while_the_window_waits_keeps_the_chat_for_good():
    """A second press into the chat draws while the first run's end is
    still awaited: the chat is no longer one to take back, and the end
    reported later deletes nothing."""
    report = _run("""
    await setUp()
    await draw.studioZeichnen()
    wishes[0].settle(false)
    await settled()
    await draw.studioZeichnen()
    draws(1)
    await settled()
    ends(0, 'abgebrochen')
    await settled()
    return { after: reading() }
    """)
    assert report["after"]["deleted"] == [] and report["after"]["chats"] == ["new-1"]


@needs_node
def test_every_press_into_the_chat_shares_the_one_wait():
    """Pressed and stopped again and again while the first stopped picture
    is still being let go of: the window listens once, not once per press —
    a browser gives one address only a handful of connections."""
    report = _run("""
    await setUp()
    await draw.studioZeichnen()
    const terminalOnly = listening('new-1').length
    wishes[0].settle(false)
    await settled()
    for (const n of [1, 2, 3]) {
      await draw.studioZeichnen()
      wishes[n].settle(false)
      await settled()
    }
    const waiting = { listeners: listening('new-1').length, deleted: reading().deleted }
    for (const n of [0, 1, 2, 3]) ends(n, 'abgebrochen')
    await settled()
    return { terminalOnly, waiting, after: reading(), left: listening('new-1').length }
    """)
    assert report["waiting"] == {"listeners": report["terminalOnly"] + 1, "deleted": []}
    assert report["after"]["deleted"] == ["new-1"]
    assert report["left"] == 0


@needs_node
def test_a_wait_for_a_chat_that_is_no_longer_the_one_is_given_up():
    """The opened chat was deleted by hand while its run's end was awaited,
    and the next press opens another: the first wait's stream is closed —
    its end will never be reported — and only the new chat is listened for."""
    report = _run("""
    await setUp()
    await draw.studioZeichnen()
    wishes[0].settle(false)
    await settled()
    await stubs.chatLoeschen('new-1')
    // Deleting by hand empties the studio for no chat; the prompt is typed again.
    studio.werte.prompt = 'a dog in a boat'
    await draw.studioZeichnen()
    wishes[1].settle(false)
    await settled()
    const waiting = { first: listening('new-1').length, second: listening('new-2').length }
    ends(1, 'fehler')
    await settled()
    return { waiting, after: reading(), left: listening('new-2').length }
    """)
    # The second chat: the terminal's stream and the one wait.
    assert report["waiting"] == {"first": 0, "second": 2}
    assert report["after"]["deleted"] == ["new-1", "new-2"]
    assert report["left"] == 0
