"""The studio keeps a picture and a model that were set while no chat was open.

With no chat open, a picture laid in the generation area and a model chosen
stand in the studio. Opening a chat then filled every field from that chat's
store, and both were gone. They now stay, whichever chat it is — also when
its store only arrives later — and count as set in that chat. The other
values are the chat's, and between two chats each keeps its own.

Run rather than read: the studio's value store and the chat's store are
compiled with the Svelte compiler (they use runes) and run in node; the
service and the window's state are stand-ins. What the mounted column does
on a chat change — fill the values, show the start values for what the chat
has none of — is done by the stand-in that changes the chat.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
LIB = FRONTEND / "src/lib"
MODULES = ["chatanzeige.svelte.js", "studio.svelte.js"]

needs_node = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)

STUBS = """
import { proxy } from 'svelte/internal/client'
export const service = { stores: {} }
export const zustand = proxy({ aktiverChat: null, nachrichten: [], chats: [], pictureQueue: [], features: {} })
export const eineSeiteOffen = () => false
export const seitenSchliessen = () => {}
export const melde = () => {}
export const api = {
  einstellungAufgeloestViele: async (keys, { chat }) => ({
    bildfenster: { wert: structuredClone(service.stores[chat] ?? {}) },
  }),
  einstellungSetzen: async (scope, key, value) => {
    const chat = scope.slice(5)
    service.stores[chat] = { ...(service.stores[chat] ?? {}), ...value }
  },
  bildVorgaben: async () => ({}),
  bilderListe: async () => ({ bilder: [] }),
}
export const familyOf = () => null
export const imageFamilies = { list: [] }
export const loadImageFamilies = async () => {}
export const loadImageSwitches = async () => {}
export const columnsForStudio = () => {}
export const columnsBack = () => {}
"""

DRIVER = """
import { compileModule } from 'svelte/compiler'
import { readFileSync, writeFileSync } from 'fs'
const STAND_INS = ['api.js', 'zustand.svelte.js', 'imageFamilies.svelte.js', 'imageSwitches.svelte.js',
  'studioColumns.svelte.js']
const REAL = %(modules)s
for (const name of REAL) {
  let code = compileModule(readFileSync(%(lib)r + '/' + name, 'utf-8'), { filename: name, generate: 'client' }).js.code
  for (const other of STAND_INS) code = code.replaceAll(`from './${other}'`, "from './kept.stubs.mjs'")
  for (const other of REAL) code = code.replaceAll(`from './${other}'`, `from './kept.${other}.mjs'`)
  writeFileSync(`kept.${name}.mjs`, code)
}
const stubs = await import('./kept.stubs.mjs')
const chatanzeige = await import('./kept.chatanzeige.svelte.js.mjs')
const studio = await import('./kept.studio.svelte.js.mjs')
const { service } = stubs
const START = { modell: 'start-model', schritte: 8 }
// What the mounted column does for the open chat: fill the values from the
// store, then show the start values for those the chat has none of.
const mounted = () => {
  const missing = studio.werteFuellen()
  studio.werteVorschlagen(Object.fromEntries(Object.entries(START).filter(([name]) => missing.includes(name))))
}
// Opening a chat: the fill runs at once, with the store still on its way,
// and again when it has arrived.
const openChat = async (id) => {
  const read = chatanzeige.chatZustandLaden(id)
  mounted()
  await read
  mounted()
}
// Opening a chat whose store is read before the column fills for it.
const openChatRead = async (id) => {
  await chatanzeige.chatZustandLaden(id)
  mounted()
}
const noChat = async () => {
  await chatanzeige.chatZustandLaden(null)
  mounted()
}
// The studio writes into a chat's store a moment after a change; leaving the
// chat flushes what is waiting, without a timer in the test.
const settle = async () => {
  const waiting = chatanzeige.chatanzeige.chatId
  await chatanzeige.chatZustandLaden(null)
  await chatanzeige.chatZustandLaden(waiting)
}
const shown = () => ({
  startbild: studio.werte.startbild, modell: studio.werte.modell, prompt: studio.werte.prompt,
  schritte: studio.werte.schritte, stored: structuredClone(service.stores),
})
const report = await (async () => {
%(scenario)s
})()
console.log('---REPORT---' + JSON.stringify(report))
process.exit(0)
"""


def _run(scenario: str) -> dict:
    files = {
        FRONTEND / "kept.stubs.mjs": STUBS,
        FRONTEND / "kept.driver.mjs": DRIVER % {
            "modules": json.dumps(MODULES), "lib": str(LIB), "scenario": scenario,
        },
    }
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
    try:
        done = subprocess.run(
            ["node", "kept.driver.mjs"], cwd=FRONTEND, capture_output=True, text=True, timeout=120,
        )
    finally:
        for path in [*files, *(FRONTEND / f"kept.{name}.mjs" for name in MODULES)]:
            path.unlink(missing_ok=True)
    assert done.returncode == 0, (done.stdout + done.stderr)[-3000:]
    mark = "---REPORT---"
    assert mark in done.stdout, done.stdout[-3000:]
    return json.loads(done.stdout.split(mark, 1)[1].strip())


@needs_node
def test_a_picture_and_a_model_set_without_a_chat_stay_when_a_chat_opens():
    """Falls over without the fix: the chat's store (or the start values)
    fills over both — no picture, and the chat's model."""
    report = _run("""
    await noChat()
    studio.startbildWaehlen('a.png')
    studio.werte.modell = 'm.gguf'
    service.stores.X = { modell: 'n.gguf', prompt: 'a cat' }
    await openChat('X')
    await settle()
    return shown()
    """)
    assert report["startbild"] == "a.png" and report["modell"] == "m.gguf"
    # What the chat has of its own besides them is filled as before.
    assert report["prompt"] == "a cat"
    # They count as set in that chat: written into its store once it is read.
    assert report["stored"]["X"]["startbild"] == "a.png"
    assert report["stored"]["X"]["modell"] == "m.gguf"


@needs_node
def test_the_same_when_the_store_was_read_before_the_column_filled():
    report = _run("""
    await noChat()
    studio.startbildWaehlen('a.png')
    studio.werte.modell = 'm.gguf'
    service.stores.X = { modell: 'n.gguf' }
    await openChatRead('X')
    await settle()
    return shown()
    """)
    assert report["startbild"] == "a.png" and report["modell"] == "m.gguf"
    assert report["stored"]["X"]["startbild"] == "a.png"


@needs_node
def test_silence_between_two_chats_each_keeps_its_own_picture_and_model():
    report = _run("""
    service.stores.A = { startbild: 'a1.png', modell: 'mA' }
    service.stores.B = { startbild: 'b1.png', modell: 'mB' }
    await openChat('A')
    const first = shown()
    await openChat('B')
    return { first, second: shown() }
    """)
    assert (report["first"]["startbild"], report["first"]["modell"]) == ("a1.png", "mA")
    assert (report["second"]["startbild"], report["second"]["modell"]) == ("b1.png", "mB")


@needs_node
def test_silence_a_chat_opened_where_nothing_was_set_fills_as_before():
    """Only the model's start values were shown with no chat: the chat's own
    model and picture show, nothing is written."""
    report = _run("""
    await noChat()
    service.stores.X = { modell: 'n.gguf', startbild: 'x1.png' }
    await openChat('X')
    await settle()
    return shown()
    """)
    assert report["startbild"] == "x1.png" and report["modell"] == "n.gguf"
    assert report["stored"] == {"X": {"modell": "n.gguf", "startbild": "x1.png"}}


@needs_node
def test_the_mask_painted_on_the_picture_goes_with_it_under_the_chat():
    report = _run("""
    await noChat()
    studio.startbildWaehlen('a.png')
    const mask = studio.maskeDesChats(null, 'a.png')
    await openChat('X')
    return { same: studio.maskeDesChats('X', 'a.png') === mask }
    """)
    assert report["same"] is True


@needs_node
def test_what_was_set_without_a_chat_does_not_reach_a_chat_after_another_chat():
    """No chat → chat A (the picture goes there) → chat B: B is not given
    A's picture; it fills from its own store."""
    report = _run("""
    await noChat()
    studio.startbildWaehlen('a.png')
    service.stores.A = {}
    await openChat('A')
    service.stores.B = { startbild: 'b1.png' }
    await openChat('B')
    return shown()
    """)
    assert report["startbild"] == "b1.png"
