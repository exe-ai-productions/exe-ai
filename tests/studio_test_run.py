"""A run of the picture studio's own modules in node.

The studio's store, its values, its drawing module and the chat's store are
compiled with the Svelte compiler (they use runes) and run for real; the
service, the window's state and the small modules around them are stand-ins.
What the mounted left column does — fill the values from the store once it is
read, and show the model's start values for what the studio has none of —
is done by the stand-in ``mounted``; what the window does on a chat change
is done by ``openChat``, ``openNewChat`` and ``newChat``.

Tests import ``run`` and ``needs_node`` from here. Each run writes files of
its own and removes them again: tests of this and of other files run side by
side.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
LIB = FRONTEND / "src/lib"
MODULES = [
    "chatanzeige.svelte.js", "studioStore.svelte.js", "studio.svelte.js", "studiozeichnen.svelte.js",
]

needs_node = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)

STUBS = """
import { proxy } from 'svelte/internal/client'
export const calls = []
// What the service holds: the studio's store (global scope), the chats'
// stores, the studio's pictures and what a model starts at.
export const service = {
  stores: {}, studioList: [], vorgaben: { family: '' }, started: { modell: 'picture-model', schritte: 8 },
}
export const zustand = proxy({
  aktiverChat: null, nachrichten: [], chats: [], modellId: 'text-model', pictureQueue: [], features: {},
})
export const eineSeiteOffen = () => false
export const seitenSchliessen = () => {}
export const said = []
export const melde = (text, kind) => said.push([text, kind ?? ''])
export const t = (key) => key
export const seedlage = { letzter: null }
export const imageSwitches = { list: [] }
export const loadImageSwitches = async () => {}
export const imageFamilies = { list: [] }
export const loadImageFamilies = async () => {}
export const familyOf = () => null
export const columnsForStudio = () => {}
export const columnsBack = () => {}
export const videoFrames = async () => []
export const api = {
  einstellungAufgeloest: async (key) => {
    calls.push(['read', key])
    if (service.readDelay) await new Promise((r) => setTimeout(r, service.readDelay))
    if (service.readFails) throw new Error('store unreadable')
    return { wert: structuredClone(service.stores.global?.[key] ?? {}) }
  },
  einstellungAufgeloestViele: async (keys, { chat }) => {
    calls.push(['read-chat', chat, keys])
    return {}
  },
  einstellungSetzen: async (scope, key, value) => {
    calls.push(['write', scope, key])
    service.stores[scope] = { ...(service.stores[scope] ?? {}), [key]: structuredClone(value) }
  },
  bildVorgaben: async () => structuredClone(service.vorgaben),
  bilderListe: async (options = {}) => {
    calls.push(['list', JSON.stringify(options)])
    return { bilder: [...service.studioList] }
  },
  bildHochladen: async () => ({ bild: 'uploaded.png' }),
}
// The window opens a chat; it is never the studio that does.
export async function openNewChat(data) {
  calls.push(['create', data?.title ?? ''])
  throw new Error('the studio opened a chat')
}

// The compiled modules, handed in by the driver once they are loaded.
export const parts = {}
/* What the mounted column does: fill the values from the store whenever
   they still have to be filled, and show the model's start values for those
   the studio has none of its own for. */
let started = false
export function mounted() {
  // The column reads the store when it comes up and fills again when the
  // read has come back.
  if (!started) {
    started = true
    parts.speicher.readStudioStore().then(() => mounted())
  }
  if (!parts.studio.fillDue()) return
  const missing = parts.studio.werteFuellen()
  parts.studio.werteVorschlagen(
    Object.fromEntries(Object.entries(service.started).filter(([name]) => missing.includes(name))),
  )
}
/* What the mounted column does after any change of a value: writes what
   changed, once the store has been filled from. */
export function changed() {
  if (parts.studio.filledFromStore()) parts.studio.werteSchreiben()
}
// The window opens, switches to and leaves chats: nothing of it is the
// studio's, but the column is asked again at every change.
export async function openChat(id) {
  zustand.aktiverChat = id
  const read = parts.chatanzeige.chatZustandLaden(id)
  mounted()
  await read
  mounted()
}
export const newChat = () => openChat(null)
export const deleteChat = async (id) => {
  calls.push(['delete', id])
  if (zustand.aktiverChat === id) await newChat()
}
"""

DRIVER = """
import { compileModule } from 'svelte/compiler'
import { readFileSync, writeFileSync } from 'fs'
const STAND_INS = ['api.js', 'zustand.svelte.js', 'texte.svelte.js', 'bildseed.svelte.js', 'imageSwitches.svelte.js',
  'imageFamilies.svelte.js', 'studioColumns.svelte.js', 'videoFrames.js']
const REAL = %(modules)s
for (const name of REAL) {
  let code = compileModule(readFileSync(%(lib)r + '/' + name, 'utf-8'), { filename: name, generate: 'client' }).js.code
  for (const other of STAND_INS) code = code.replaceAll(`from './${other}'`, "from './tag.stubs.mjs'")
  for (const other of REAL) code = code.replaceAll(`from './${other}'`, `from './tag.${other}.mjs'`)
  writeFileSync(`tag.${name}.mjs`, code)
}
const stubs = await import('./tag.stubs.mjs')
const chatanzeige = await import('./tag.chatanzeige.svelte.js.mjs')
const speicher = await import('./tag.studioStore.svelte.js.mjs')
const studio = await import('./tag.studio.svelte.js.mjs')
const draw = await import('./tag.studiozeichnen.svelte.js.mjs')
Object.assign(stubs.parts, { chatanzeige, speicher, studio, draw })
const { zustand, service, calls, said } = stubs

// The studio is what the window shows, and the picture line is handed in:
// every wish is noted and waits in the line.
studio.studio.offen = true
const wishes = []
draw.zeichnung.losZeichnen = (wish) => { wishes.push(wish) }
const settled = async (ms = 0) => {
  for (let i = 0; i < 40; i += 1) await new Promise((r) => setTimeout(r, ms))
}
// The store writes a moment after a change (a typed sentence is one
// request): wait that moment out.
const flushed = () => new Promise((r) => setTimeout(r, 400))
const written = () => calls.filter((c) => c[0] === 'write')
// What the studio shows, as one reading.
const reading = () => ({
  startbild: studio.werte.startbild, maske: studio.werte.maske, modell: studio.werte.modell,
  prompt: studio.werte.prompt, breite: studio.werte.breite, schritte: studio.werte.schritte,
  stored: structuredClone(service.stores),
})
const report = await (async () => {
%(scenario)s
})()
console.log('---REPORT---' + JSON.stringify(report))
process.exit(0)
"""


def run(scenario: str) -> dict:
    tag = f"studiolauf-{uuid.uuid4().hex[:8]}"
    files = {
        FRONTEND / f"{tag}.stubs.mjs": STUBS,
        FRONTEND / f"{tag}.driver.mjs": DRIVER.replace("tag.", f"{tag}.") % {
            "modules": json.dumps(MODULES), "lib": str(LIB), "scenario": scenario,
        },
    }
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
    try:
        done = subprocess.run(
            ["node", f"{tag}.driver.mjs"], cwd=FRONTEND, capture_output=True, text=True,
            encoding="utf-8", timeout=120,
        )
    finally:
        for path in [*files, *(FRONTEND / f"{tag}.{name}.mjs" for name in MODULES)]:
            path.unlink(missing_ok=True)
    assert done.returncode == 0, (done.stdout + done.stderr)[-3000:]
    mark = "---REPORT---"
    assert mark in done.stdout, done.stdout[-3000:]
    return json.loads(done.stdout.split(mark, 1)[1].strip())
