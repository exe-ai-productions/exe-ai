"""The two event lines of the window, run rather than read.

``lib/terminalfenster.svelte.js`` carries a chat's command runs and writes a
background run's ending onto the card of the call that started it;
``lib/ereignisstrom.svelte.js`` carries the service's own announcements and
turns an answer that started without this window into an owed
reattachment. Both used to be pinned by substrings of their source — a
match says a line exists, not that the branch computes the right thing.

Here the modules are compiled with the Svelte compiler (they use runes),
their imports are bent to stand-ins, and the events go in through the same
door the browser uses: a fake ``EventSource`` whose ``onmessage`` the
module itself hangs in.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"
TERMINAL = FRONTEND / "src/lib/terminalfenster.svelte.js"
LEITUNG = FRONTEND / "src/lib/ereignisstrom.svelte.js"

braucht_node = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)

# Everything the two modules import, as stand-ins that only record. Plain
# objects: the assertions read state, nothing here has to re-render.
STUBS = """
import { proxy } from 'svelte/internal/client'
export const protokoll = []
// A real state proxy, as in the window: a module writing into a dead copy
// — the mistake App.svelte warns about in three places — would pass on a
// plain object and fail here.
export const zustand = proxy({
  aktiverChat: null, nachrichten: [], laeuft: {}, sendet: {},
  wiederanhaengen: {}, laufenderPlatzhalter: {}, features: {},
})
// The real one hides `nachrichten` once its chat tag has drifted;
// neither module under test here reads or sets that tag, so
// this stand-in just hands the list straight through.
export const nachrichtenAnzeige = () => zustand.nachrichten
export const api = {
  laeufe: async (chatId) => { protokoll.push(['api.laeufe', chatId]); return globalThis.__laeufe ?? { laeufe: [], ab: 0 } },
  laeufeStrom: (chatId, ab) => `laeufe/${chatId}?ab=${ab}`,
  ereignisStrom: () => 'ereignisse',
}
export const anbieten = (was) => protokoll.push(['anbieten', was])
export const chatOeffnen = async (id) => protokoll.push(['chatOeffnen', id])
export const auftraegeStillLaden = () => protokoll.push(['auftraege'])
export const modelleLaden = () => protokoll.push(['modelle'])
export const auswahlLaden = () => protokoll.push(['auswahl'])
// The approvals for runs are read beside the choice of models; the sequences pinned here are the others.
export const loadRunApprovals = () => {}
export const standLaden = () => protokoll.push(['cronstand'])
export const laden = () => protokoll.push(['serverzustand'])
export const serverzustand = { geladen: true }
export const uebernehmen = (e) => protokoll.push(['serverzustand.uebernehmen', e])
"""

# Compiles both modules for the client, bends their imports, and runs the
# scenario handed in. The compiled module is rewritten, not the source: the
# compiler forbids nothing here, but the stand-ins live beside the driver,
# not beside the module.
TREIBER = """
import { compileModule } from 'svelte/compiler'
import { readFileSync, writeFileSync } from 'fs'
const bauen = (quelle, ziel, name) => {
  let code = compileModule(readFileSync(quelle, 'utf-8'), { filename: name, generate: 'client' }).js.code
  code = code
    .replace(/from '\\.\\/api\\.js'/g, "from './p751.stubs.mjs'")
    .replace(/from '\\.\\/arbeitsleiste\\.svelte\\.js'/g, "from './p751.stubs.mjs'")
    .replace(/from '\\.\\/zustand\\.svelte\\.js'/g, "from './p751.stubs.mjs'")
    .replace(/from '\\.\\/cronjobampel\\.svelte\\.js'/g, "from './p751.stubs.mjs'")
    .replace(/from '\\.\\/serverzustand\\.svelte\\.js'/g, "from './p751.stubs.mjs'")
    .replace(/from '\\.\\/modelle\\.svelte\\.js'/g, "from './p751.stubs.mjs'")
    .replace(/from '\\.\\/werkzeughistorie\\.js'/g, "from './src/lib/werkzeughistorie.js'")
  writeFileSync(ziel, code)
}
bauen(%(terminal)r, 'p751.terminal.mjs', 'terminalfenster.svelte.js')
bauen(%(leitung)r, 'p751.leitung.mjs', 'ereignisstrom.svelte.js')

globalThis.__quellen = []
globalThis.EventSource = class {
  constructor(url) { this.url = url; globalThis.__quellen.push(this) }
  close() { this.geschlossen = true }
}
const stubs = await import('./p751.stubs.mjs')
const terminal = await import('./p751.terminal.mjs')
const leitung = await import('./p751.leitung.mjs')
const { zustand, protokoll } = stubs
const senden = (quelle, ereignis) => quelle.onmessage({ data: JSON.stringify(ereignis) })
const bericht = await (async () => {
%(szenario)s
})()
console.log('---BERICHT---' + JSON.stringify(bericht))
// The line's net is a live interval; without this, node waits for it.
process.exit(0)
"""


def _fahren(szenario: str) -> dict:
    dateien = {
        FRONTEND / "p751.stubs.mjs": STUBS,
        FRONTEND / "p751.pruefung.mjs": TREIBER % {
            "terminal": str(TERMINAL), "leitung": str(LEITUNG), "szenario": szenario,
        },
    }
    for pfad, inhalt in dateien.items():
        pfad.write_text(inhalt, encoding="utf-8")
    try:
        lauf = subprocess.run(
            ["node", "p751.pruefung.mjs"],
            cwd=FRONTEND, capture_output=True, text=True, timeout=120,
        )
    finally:
        for pfad in list(dateien) + [FRONTEND / "p751.terminal.mjs", FRONTEND / "p751.leitung.mjs"]:
            pfad.unlink(missing_ok=True)
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-3000:]
    marke = "---BERICHT---"
    assert marke in lauf.stdout, lauf.stdout[-3000:]
    return json.loads(lauf.stdout.split(marke, 1)[1].strip())


# The chat as the window holds it: one answer whose call started run #1 in
# the background, and a later answer whose file read failed.
CHAT = """
    zustand.aktiverChat = 'A'
    zustand.nachrichten = [
      { id: 'm1', role: 'assistant', stats: { werkzeuge: [
        { name: 'run_command', argumente: { command: 'npm install', background: true },
          lauf_nummer: 1, ergebnis: 'Started in the background as run #1.', fehlgeschlagen: false },
      ] } },
      { id: 'm2', role: 'assistant', stats: { werkzeuge: [
        { name: 'read_file', argumente: { path: 'fehlt.txt' }, ergebnis: 'no such file', fehlgeschlagen: true },
      ] } },
    ]
    globalThis.__laeufe = { laeufe: [
      { lauf: 1, befehl: 'npm install', hintergrund: true, art: 'befehl', zustand: 'laeuft',
        code: null, dauer_sekunden: null, ausgabe: '', gelesen: false },
    ], ab: 3 }
    await terminal.verbinden('A')
    const quelle = globalThis.__quellen.at(-1)
"""


@braucht_node
def test_das_ende_eines_hintergrundlaufs_landet_auf_der_karte():
    """Output, exit code, state and duration go onto the call's entry — and
    the chat is fetched again, because the service has added a report row."""
    bericht = _fahren(CHAT + """
    senden(quelle, { n: 3, typ: 'lauf_zeile', lauf: 1, text: 'added 70 packages' })
    senden(quelle, { n: 4, typ: 'lauf_ende', lauf: 1, code: 0, zustand: 'fertig', hintergrund: true, dauer_sekunden: 2.5 })
    const karte = zustand.nachrichten[0].stats.werkzeuge[0]
    return { karte, lauf: terminal.terminal.laeufe[0], protokoll }
    """)
    karte = bericht["karte"]
    assert karte["exit_code"] == 0
    assert karte["lauf_zustand"] == "fertig"
    assert karte["fehlgeschlagen"] is False
    assert karte["ergebnis"] == "added 70 packages"
    assert karte["dauer_sekunden"] == 2.5
    assert bericht["lauf"]["zustand"] == "fertig"
    assert ["chatOeffnen", "A"] in bericht["protokoll"]


@braucht_node
def test_ein_startender_lauf_fuellt_die_liste_und_bietet_die_spalte_nicht_an():
    """A command that starts changes nothing about the column: the list
    holds the run and follows its end, and no offer to come forward goes
    out. (The ones of the preview and the agents are not this module's.)"""
    bericht = _fahren(CHAT + """
    senden(quelle, { n: 3, typ: 'lauf_start', lauf: 2, befehl: 'ls', hintergrund: false })
    return {
      laeufe: terminal.terminal.laeufe.map((l) => [l.lauf, l.befehl, l.zustand]),
      klebt: terminal.terminal.klebt,
      angeboten: protokoll.filter((p) => p[0] === 'anbieten'),
    }
    """)
    assert bericht["laeufe"] == [[1, "npm install", "laeuft"], [2, "ls", "laeuft"]]
    assert bericht["klebt"] is True
    assert bericht["angeboten"] == []


@braucht_node
def test_ein_gestoppter_lauf_ist_auf_der_karte_kein_fehler():
    """No exit code, state "abgebrochen": the card says stopped, not failed —
    the reading the panel and the rail give the same run."""
    bericht = _fahren(CHAT + """
    senden(quelle, { n: 3, typ: 'lauf_ende', lauf: 1, code: null, zustand: 'abgebrochen', hintergrund: true, dauer_sekunden: 9 })
    return zustand.nachrichten[0].stats.werkzeuge[0]
    """)
    assert bericht["exit_code"] is None
    assert bericht["lauf_zustand"] == "abgebrochen"
    assert bericht["fehlgeschlagen"] is False
    assert bericht["ergebnis"] == ""


@braucht_node
def test_ein_wiederholtes_ereignis_wird_nicht_zweimal_gezeichnet():
    """The browser reconnects by resending from the original `ab`; what is
    numbered at or below the highest number seen is thrown away."""
    bericht = _fahren(CHAT + """
    senden(quelle, { n: 3, typ: 'lauf_zeile', lauf: 1, text: 'eins' })
    senden(quelle, { n: 3, typ: 'lauf_zeile', lauf: 1, text: 'eins' })
    senden(quelle, { n: 2, typ: 'lauf_zeile', lauf: 1, text: 'alt' })
    senden(quelle, { n: 4, typ: 'lauf_zeile', lauf: 1, text: 'zwei' })
    return terminal.terminal.laeufe[0].ausgabe
    """)
    assert bericht == "eins\nzwei"


@braucht_node
def test_gelesen_und_gesehen_werden_am_lauf_und_am_aufruf_vermerkt():
    """`lauf_gelesen` marks the run; opening the panel names the last failed
    line as seen — by key, so a line taken away by "regenerate" does not
    leave a stale count behind."""
    bericht = _fahren(CHAT + """
    senden(quelle, { n: 3, typ: 'lauf_gelesen', lauf: 1 })
    terminal.terminalGesehen()
    const vorher = terminal.terminal.gesehenerAufruf
    // The failed read is regenerated away: the mark must not point at it.
    zustand.nachrichten = zustand.nachrichten.slice(0, 1)
    terminal.terminalGesehen()
    return { gelesen: terminal.terminal.laeufe[0].gelesen, vorher, nachher: terminal.terminal.gesehenerAufruf }
    """)
    assert bericht["gelesen"] is True
    assert bericht["vorher"] == "m2#0"
    assert bericht["nachher"] is None


@braucht_node
def test_ein_zweiter_chatwechsel_vor_dem_ersten_abruf_gewinnt():
    """Switching twice before the first fetch lands: the first call must not
    attach the view to the other chat's stream."""
    bericht = _fahren("""
    let frei
    globalThis.__laeufe = { laeufe: [{ lauf: 7, befehl: 'x', zustand: 'fertig', art: 'befehl', ausgabe: '' }], ab: 1 }
    stubs.api.laeufe = (chatId) => new Promise((f) => { frei = f })
    const erster = terminal.verbinden('A')
    stubs.api.laeufe = async () => globalThis.__laeufe
    await terminal.verbinden('B')
    frei({ laeufe: [{ lauf: 99, befehl: 'fremd', zustand: 'fertig', art: 'befehl', ausgabe: '' }], ab: 5 })
    await erster
    return { laeufe: terminal.terminal.laeufe.map((l) => l.lauf), quellen: globalThis.__quellen.map((q) => q.url) }
    """)
    assert bericht["laeufe"] == [7]
    assert bericht["quellen"] == ["laeufe/B?ab=1"]


@braucht_node
def test_ein_fremder_antwortstart_wird_zum_wiederanhang():
    """The line says an answer started in chat B while this window sat idle
    on it: owed as a reattachment. Not for a chat this window already
    runs, not for one whose own send is still uploading, not without a run."""
    bericht = _fahren("""
    zustand.laeuft.C = { chatId: 'C' }
    zustand.sendet.D = true
    leitung.verbinden()
    const quelle = globalThis.__quellen.at(-1)
    quelle.onopen()
    const stand = leitung.leitung.steht
    senden(quelle, { typ: 'antwort_begonnen', chat_id: 'B', generation_id: 'g1', message_id: 'a1' })
    senden(quelle, { typ: 'antwort_begonnen', chat_id: 'C', generation_id: 'g2', message_id: 'a2' })
    senden(quelle, { typ: 'antwort_begonnen', chat_id: 'D', generation_id: 'g3', message_id: 'a3' })
    senden(quelle, { typ: 'antwort_begonnen', chat_id: 'E', message_id: 'a4' })
    quelle.onerror()
    return { stand, wiederanhaengen: zustand.wiederanhaengen, danach: leitung.leitung.steht }
    """)
    assert bericht["stand"] is True
    assert bericht["wiederanhaengen"] == {
        "B": {"chatId": "B", "generationId": "g1", "messageId": "a1"},
    }
    assert bericht["danach"] is False


@braucht_node
def test_der_wiederaufbau_fragt_auch_die_modelle_nach():
    """Nothing that happened while the line was down is replayed, so a
    RETURN has to ask for every state an announcement would have carried —
    and the model list was the one it did not ask for. Reachability rides on
    that list (`endpunkt_status`), so an endpoint that went down or came back
    in the meantime kept the mark it had until something else fetched it.

    The FIRST open does not ask for it: the window is loading its settings
    beside this, and a model list arriving before the remembered choice
    replaces that choice with the first of the list. The mount asks in the
    right order.

    And a line that merely DROPS asks for nothing: the browser reconnects by
    itself, and the open is where the asking belongs.
    """
    bericht = _fahren("""
    leitung.verbinden()
    const quelle = globalThis.__quellen.at(-1)
    protokoll.length = 0
    quelle.onopen()
    const erstes = protokoll.map((z) => z[0])
    protokoll.length = 0
    quelle.onerror()
    const nachAbbruch = protokoll.map((z) => z[0])
    quelle.onopen()
    const rueckkehr = protokoll.map((z) => z[0])
    return { erstes, nachAbbruch, rueckkehr }
    """)
    assert bericht["erstes"] == ["auftraege", "cronstand", "serverzustand"]
    assert bericht["nachAbbruch"] == []
    assert bericht["rueckkehr"] == [
        "auftraege", "cronstand", "serverzustand", "modelle", "auswahl",
    ]


@braucht_node
def test_die_rueckkehr_fragt_den_sichtbaren_chat_nach():
    """The line hands out FACTS and numbers nothing,
    so a burst of more than two hundred announcements is dropped rather than
    queued (app/ereignisstrom.py) — `antwort_begonnen` among them. The run
    goes on writing into a chat that never hears about it, and the answer
    looks like it never started.

    The RETURN therefore asks the chat that is on screen, exactly once, and
    through `chatOeffnen` — the one way this window picks up a running
    answer. Nothing new is built for it.

    The FIRST open leaves the chat alone: it races the settings the window
    is loading beside it, and the mount has already asked for the chat it
    wanted to show.
    """
    bericht = _fahren("""
    zustand.aktiverChat = 'c-77'
    leitung.verbinden()
    const quelle = globalThis.__quellen.at(-1)
    protokoll.length = 0
    quelle.onopen()
    const erstes = protokoll.map((z) => z[0])
    protokoll.length = 0
    quelle.onopen()
    const rueckkehr = protokoll.filter((z) => z[0] === 'chatOeffnen')
    return { erstes, rueckkehr }
    """)
    assert bericht["erstes"] == ["auftraege", "cronstand", "serverzustand"], (
        "the first opening already asks the chat again"
    )
    assert bericht["rueckkehr"] == [["chatOeffnen", "c-77"]], bericht["rueckkehr"]


@braucht_node
def test_ohne_sichtbaren_chat_wird_keiner_nachgefragt():
    """Silence probe: no chat on screen means nothing to reattach — and a
    chat that was left behind while the line was down is not the one the
    reader is looking at."""
    bericht = _fahren("""
    zustand.aktiverChat = null
    leitung.verbinden()
    const quelle = globalThis.__quellen.at(-1)
    protokoll.length = 0
    quelle.onopen()
    quelle.onopen()
    return { gerufen: protokoll.filter((z) => z[0] === 'chatOeffnen') }
    """)
    assert bericht["gerufen"] == []


@braucht_node
def test_die_uebrigen_abfragen_bleiben_wie_sie_waren():
    """The other four keep their calls — including `modelleLaden`, which is
    a RETURN question and not a first-open one."""
    bericht = _fahren("""
    zustand.aktiverChat = 'c-1'
    leitung.verbinden()
    const quelle = globalThis.__quellen.at(-1)
    protokoll.length = 0
    quelle.onopen()
    const erstes = protokoll.map((z) => z[0])
    protokoll.length = 0
    quelle.onopen()
    const rueckkehr = protokoll.map((z) => z[0])
    return { erstes, rueckkehr }
    """)
    assert bericht["erstes"] == ["auftraege", "cronstand", "serverzustand"]
    assert bericht["rueckkehr"] == [
        "auftraege", "cronstand", "serverzustand", "modelle", "auswahl", "chatOeffnen",
    ]
