"""The hand-over out of the browser, run for real instead of read.

A change moved the main model server's start choice from ``localStorage``
into a setting. What the store in the browser still has to do is the
one-time hand-over — and a hand-over is exactly the kind of code that looks
right and is not: it reads one place, writes another, and then DELETES the
first. Reading the source confirms the sentences; only running it says
whether somebody's window, layers, port and module pairings are still there
afterwards.

So the store is compiled with Svelte's own compiler and run in Node against
a stubbed ``localStorage`` and a stubbed settings route, the same way the
message queue is (test_warteschlange.py). What runs here is the file the
interface imports.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"
MODUL = FRONTEND / "src" / "lib" / "runnermodell.svelte.js"

# The store imports `./api.js`, which drags the whole service client in. The
# compiled module is put in a folder of its own with a stub next to it, so
# `./api.js` resolves to the stub and every call the store makes is on the
# record.
STUB_API = """
export const api = {
  async einstellungAufgeloest(schluessel) {
    globalThis.__ruf.push(['lesen', schluessel])
    if (globalThis.__lesefehler) throw new Error('kaputt')
    return { schluessel, wert: globalThis.__ablage }
  },
  async einstellungSetzen(bereich, schluessel, wert) {
    globalThis.__ruf.push(['setzen', wert])
    if (globalThis.__schreibfehler) throw new Error('kaputt')
    globalThis.__ablage = wert
    return { wert }
  },
  async einstellungMischen(bereich, schluessel, wert) {
    globalThis.__ruf.push(['mischen', wert])
    if (globalThis.__haltSchreiben) await globalThis.__haltSchreiben
    if (globalThis.__schreibfehler) throw new Error('kaputt')
    globalThis.__ablage = __mischen(globalThis.__ablage ?? {}, wert)
    return { wert: globalThis.__ablage }
  },
}

/* The same rule the route follows (app/db/repositories/einstellungen.py):
   key by key, one level down wherever both sides are sets. */
function __mischen(alt, neu) {
  const zusammen = { ...alt }
  for (const [name, wert] of Object.entries(neu)) {
    const vorher = zusammen[name]
    zusammen[name] =
      vorher && typeof vorher === 'object' && !Array.isArray(vorher) &&
      wert && typeof wert === 'object' && !Array.isArray(wert)
        ? __mischen(vorher, wert)
        : wert
  }
  return zusammen
}
"""

TREIBER = """
import { compileModule } from 'svelte/compiler'
import { readFileSync, writeFileSync, mkdirSync } from 'fs'

mkdirSync(%(ordner)r, { recursive: true })
writeFileSync(%(ordner)r + '/api.js', %(stub)r)
const quelle = readFileSync(%(modul)r, 'utf-8')
const gebaut = compileModule(quelle, {
  filename: 'runnermodell.svelte.js', generate: 'client',
})
writeFileSync(%(ordner)r + '/gebaut.mjs', gebaut.js.code)

/* A browser store that behaves like the real one, including the insertion
   order `localStorage.key(i)` walks. */
class Speicher {
  constructor(anfang) { this.d = new Map(Object.entries(anfang ?? {})) }
  get length() { return this.d.size }
  key(i) { return [...this.d.keys()][i] ?? null }
  getItem(k) { return this.d.has(k) ? this.d.get(k) : null }
  setItem(k, v) { this.d.set(k, String(v)) }
  removeItem(k) { this.d.delete(k) }
  alles() { return Object.fromEntries(this.d) }
}
globalThis.localStorage = new Speicher(%(browser)s)
globalThis.__ablage = %(ablage)s
globalThis.__ruf = []
globalThis.__lesefehler = false
globalThis.__schreibfehler = %(schreibfehler)s

const m = await import(%(import)r)
const bericht = await (async () => {
%(js)s
})()
console.log('---BERICHT---' + JSON.stringify(bericht))
"""


def _laufen(js: str, *, browser: dict, ablage, schreibfehler: bool = False) -> dict:
    ordner = FRONTEND / "pruef-runnermodell"
    treiber = FRONTEND / "runnermodell.pruefung.mjs"
    treiber.write_text(
        TREIBER % {
            "ordner": str(ordner),
            "stub": STUB_API,
            "modul": str(MODUL),
            "import": "./pruef-runnermodell/gebaut.mjs",
            "browser": json.dumps(browser),
            "ablage": json.dumps(ablage),
            "schreibfehler": "true" if schreibfehler else "false",
            "js": textwrap.indent(js, "  "),
        },
        encoding="utf-8",
    )
    try:
        lauf = subprocess.run(
            ["node", treiber.name],
            cwd=FRONTEND,
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        treiber.unlink(missing_ok=True)
        shutil.rmtree(ordner, ignore_errors=True)
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-2000:]
    marke = "---BERICHT---"
    assert marke in lauf.stdout, lauf.stdout[-2000:]
    return json.loads(lauf.stdout.split(marke, 1)[1].strip())


pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)


BESTAND = {
    "runner:modell": "gemma.gguf",
    "runner:kontext": "131072",
    "runner:schichten": "55",
    "runner:port": "8231",
    "runner:drafter:gemma.gguf": "mtp-gemma.gguf",
    "runner:vision:gemma.gguf": "",
    "runner:drafter:exe-guard.gguf": "",
}

LADEN = """
await m.standLaden()
return {
  ablage: globalThis.__ablage,
  browser: localStorage.alles(),
  store: {
    modell: m.runnermodell.modell,
    kontext: m.runnermodell.kontext,
    schichten: m.runnermodell.schichten,
    port: m.runnermodell.port,
    module: m.runnermodell.module,
  },
  ruf: globalThis.__ruf,
}
"""


def test_der_bestand_wandert_und_der_browser_wird_geraeumt():
    """The plain case: nothing stored yet, a whole choice in the browser."""
    bericht = _laufen(LADEN, browser=dict(BESTAND), ablage={})
    assert bericht["ablage"]["modell"] == "gemma.gguf"
    assert bericht["ablage"]["kontext"] == 131072
    assert bericht["ablage"]["schichten"] == 55
    assert bericht["ablage"]["port"] == 8231
    assert bericht["ablage"]["module"] == {
        "gemma.gguf": {"drafter": "mtp-gemma.gguf", "vision": ""},
        "exe-guard.gguf": {"drafter": ""},
    }
    assert bericht["browser"] == {}


def test_ein_start_aus_dem_katalog_kostet_die_wahl_nicht():
    """The finding.

    A user of a version before the move updates, opens the app, goes straight
    into the catalogue and presses start — never past the server page. The
    route records the file that started (``modell_merken``) into the very row
    the hand-over watches. The row is no longer empty, and "not empty" used
    to count as "already handed over": window, layers, port and every module
    pairing were then deleted unread.
    """
    bericht = _laufen(LADEN, browser=dict(BESTAND), ablage={"modell": "exe-guard.gguf"})
    ablage = bericht["ablage"]
    # The file that actually started stays — it is the newer answer.
    assert ablage["modell"] == "exe-guard.gguf"
    # And nothing else was lost.
    assert ablage["kontext"] == 131072
    assert ablage["schichten"] == 55
    assert ablage["port"] == 8231
    assert ablage["module"] == {
        "gemma.gguf": {"drafter": "mtp-gemma.gguf", "vision": ""},
        "exe-guard.gguf": {"drafter": ""},
    }
    assert bericht["browser"] == {}


def test_was_die_einstellung_beantwortet_gewinnt():
    """A value the setting has an answer for is not overwritten by the older
    browser copy — that is what makes clearing safe afterwards."""
    bericht = _laufen(
        LADEN,
        browser=dict(BESTAND),
        ablage={"kontext": 8192, "module": {"gemma.gguf": {"drafter": ""}}},
    )
    ablage = bericht["ablage"]
    assert ablage["kontext"] == 8192
    assert ablage["schichten"] == 55
    # The drafter row was already answered; the projector row was not.
    assert ablage["module"]["gemma.gguf"] == {"drafter": "", "vision": ""}


def test_ohne_bestaetigte_schreibung_wird_nichts_geraeumt():
    """A hand-over that did not get stored has not happened."""
    bericht = _laufen(
        LADEN, browser=dict(BESTAND), ablage={"modell": "exe-guard.gguf"},
        schreibfehler=True,
    )
    assert bericht["browser"] == BESTAND


def test_null_schichten_ueberleben_den_umzug():
    """0 GPU layers is "processor alone" — set on purpose, and the one number
    a falsy test hands back as 99 on the day somebody updates."""
    bericht = _laufen(
        LADEN, browser={"runner:modell": "a.gguf", "runner:schichten": "0"}, ablage={}
    )
    assert bericht["ablage"]["schichten"] == 0
    assert bericht["store"]["schichten"] == 0


def test_ein_leerer_browser_schreibt_nichts():
    bericht = _laufen(LADEN, browser={}, ablage={})
    assert [r[0] for r in bericht["ruf"]] == ["lesen"]


def test_geschrieben_wird_nur_was_sich_geaendert_hat():
    """The whole object is never sent again.

    It is what one window knew when it opened, and sending it means the next
    slider drag over here undoes the module the window next door just picked.
    """
    bericht = _laufen(
        """
        await m.standLaden()
        await m.werteSetzen({ kontext: 8192 })
        await m.modulSetzen('a.gguf', { vision: '' })
        return { ruf: globalThis.__ruf, ablage: globalThis.__ablage }
        """,
        browser={},
        ablage={"modell": "a.gguf", "kontext": 65536, "schichten": 40},
    )
    assert bericht["ruf"][1] == ["mischen", {"kontext": 8192}]
    assert bericht["ruf"][2] == ["mischen", {"module": {"a.gguf": {"vision": ""}}}]
    # Nothing this window did not touch was resent, so nothing of it could be
    # carried out stale.
    assert bericht["ablage"]["modell"] == "a.gguf"
    assert bericht["ablage"]["schichten"] == 40


def test_die_werte_stehen_bevor_irgendwer_sie_liest():
    """`geladen` is the page's signal, and it must not turn true early.

    Measured on the running program, not reasoned out: with the carried-over
    values applied only after the write came back, the server page filled its
    form from the defaults in between — and wrote 32768/99/8080 back over a
    window of 131072, 0 layers and port 8234 a debounce later. The hand-over
    had worked and the numbers were gone anyway.
    """
    bericht = _laufen(
        """
        let release
        globalThis.__haltSchreiben = new Promise((f) => (release = f))
        const laeuft = m.standLaden()
        /* Wait for the moment the page waits for — the write is still in
           flight, held open above. */
        while (!m.runnermodell.geladen) await new Promise((f) => setTimeout(f, 1))
        const while_open = {
          kontext: m.runnermodell.kontext,
          schichten: m.runnermodell.schichten,
          port: m.runnermodell.port,
          modul: m.modulFuer('gemma.gguf'),
        }
        const still_there = { ...localStorage.alles() }
        release()
        await laeuft
        return { while_open, keys_while_open: Object.keys(still_there).length }
        """,
        browser={
            "runner:modell": "gemma.gguf",
            "runner:kontext": "131072",
            "runner:schichten": "0",
            "runner:port": "8234",
            "runner:drafter:gemma.gguf": "mtp-gemma.gguf",
        },
        ablage={"modell": "gemma.gguf"},
    )
    assert bericht["while_open"]["kontext"] == 131072
    assert bericht["while_open"]["schichten"] == 0
    assert bericht["while_open"]["port"] == 8234
    assert bericht["while_open"]["modul"]["drafter"] == "mtp-gemma.gguf"
    # And the browser is still untouched while the write is open.
    assert bericht["keys_while_open"] == 5
