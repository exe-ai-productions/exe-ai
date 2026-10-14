"""A language switch that does not arrive must not change what the service
hears.

The interface claims one language at a time, and every request carries it
(`X-Ui-Language`, app/api/abhaengigkeiten.py). A switch happens in two steps:
the catalogue is fetched, and only when its texts are there does the new
language stand. Measured on the shipped pair of modules — `texte.svelte.js`
compiled the way the browser gets it, `api.js` UNCHANGED beside it (the house
form from tests/test_meldungsteile.py: a hand-written stand-in would only
prove things about the copy). The requests are read off a fetch of this
file's own, the same way the network tab shows them.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.test_agentenampel import _pruefordner

WURZEL = Path(__file__).resolve().parents[1]
FRONTEND = WURZEL / "frontend"
QUELLE = FRONTEND / "src"
MODUL = QUELLE / "lib" / "texte.svelte.js"

node_da = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)


def _lauf(koerper: str) -> dict:
    """The shipped stand in node. `koerper` runs inside the driver with `m`
    (the compiled text module) and `api` (the real one) in reach; it answers
    what the test wants to see.

    The catalogue answers are the test's own: `globalThis.__antworten(pfad)`
    returns the body, the word 'haengt' for a request that never answers, or
    the word 'scheitert' for one that fails.
    """
    with _pruefordner() as ordner:
        (ordner / "api.mjs").write_text(
            (QUELLE / "lib" / "api.js").read_text(encoding="utf-8"), encoding="utf-8"
        )
        treiber = ordner / "pruefung.mjs"
        treiber.write_text(
            textwrap.dedent(
                """
                import { compileModule } from 'svelte/compiler'
                import { readFileSync, writeFileSync } from 'fs'

                /* What api.js touches of a browser. Everything is behind
                   `typeof window` there, so nothing else has to stand. */
                const gesehen = []
                globalThis.__gesehen = gesehen
                Object.defineProperty(globalThis, 'document', {
                  configurable: true,
                  value: { documentElement: { lang: '' } },
                })
                Object.defineProperty(globalThis, 'navigator', {
                  configurable: true,
                  value: { language: 'de-DE' },
                })
                globalThis.window = {
                  __SITZUNGSSCHLUESSEL__: 'key',
                  location: { reload() {} },
                  dispatchEvent() {},
                }
                globalThis.CustomEvent = class { constructor(type) { this.type = type } }
                const speicher = {}
                globalThis.sessionStorage = {
                  getItem: (k) => (k in speicher ? speicher[k] : null),
                  setItem: (k, v) => { speicher[k] = String(v) },
                  removeItem: (k) => { delete speicher[k] },
                }
                globalThis.fetch = async (url, optionen = {}) => {
                  const pfad = String(url).replace('/api/v1', '')
                  const kopf = optionen.headers || {}
                  const rumpf = optionen.body ? JSON.parse(optionen.body) : null
                  gesehen.push([
                    pfad,
                    kopf['X-Ui-Language'] ?? null,
                    rumpf?.wert?.sprache ?? null,
                  ])
                  const gestellt = globalThis.__antworten(pfad)
                  if (gestellt === 'haengt') return new Promise(() => {})
                  if (gestellt === 'scheitert') throw new Error('kein Netz')
                  return { ok: true, status: 200, json: async () => gestellt }
                }

                const quelle = readFileSync(%r, 'utf-8')
                const gebaut = compileModule(quelle, {
                  filename: 'texte.svelte.js', generate: 'client',
                })
                writeFileSync(%r, gebaut.js.code.replace('./api.js', './api.mjs'))
                const m = await import('./gebaut.mjs')
                const { api, spracheMerken } = await import('./api.mjs')
                console.log('---BERICHT---' + JSON.stringify(await (async () => { %s })()))
                """
            )
            % (str(MODUL), str(ordner / "gebaut.mjs"), koerper),
            encoding="utf-8",
        )
        lauf = subprocess.run(
            ["node", treiber.name], cwd=ordner, capture_output=True, text=True, timeout=120
        )
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-2000:]
    marke = "---BERICHT---"
    assert marke in lauf.stdout, lauf.stdout[-2000:]
    return json.loads(lauf.stdout.split(marke, 1)[1].strip())


@node_da
def test_nur_der_katalog_abruf_traegt_die_neue_sprache():
    """The one call that speaks the language being switched TO is the
    catalogue — it asks for exactly those texts, and the window still shows
    the old ones while it runs."""
    bericht = _lauf(
        """
        globalThis.__antworten = () => ({ texte: {}, sprache: 'en' })
        spracheMerken('en')
        await api.uebersetzungen('de')
        await api.modelle()
        await api.werkzeuge()
        return { gesehen }
        """
    )
    assert bericht["gesehen"] == [
        ["/translations/de", "de", None],
        ["/models", "en", None],
        ["/tools", "en", None],
    ]


@node_da
def test_ein_haengender_wechsel_laesst_die_anfragen_bei_der_alten_sprache():
    """While the catalogue for the new language is still on its way, every
    other request keeps the language on screen — the model check every 30 s,
    say. Went out in the new one, the service would answer in a language
    nobody is looking at."""
    bericht = _lauf(
        """
        globalThis.__antworten = (pfad) => pfad.includes('/translations/en')
          ? 'haengt'
          : ({ texte: { gruss: 'Hallo' }, sprache: 'de' })
        await m.texteLaden('de')
        const unterwegs = m.texteLaden('en')
        await new Promise((fertig) => setTimeout(fertig, 50))
        await api.modelle()
        return { gesehen, sprache: m.texte.sprache }
        """
    )
    assert bericht["gesehen"] == [
        ["/translations/de", "de", None],
        ["/translations/en", "en", None],
        ["/models", "de", None],
    ]
    assert bericht["sprache"] == "de"


@node_da
def test_ein_gescheiterter_wechsel_laesst_alles_wie_es_war():
    """German window, switch to English, the English catalogue never arrives:
    the switch did not happen. The requests keep German, and the stored
    choice goes back to German — it is how the service knows which language
    to write its own texts in, and the next start reads it."""
    bericht = _lauf(
        """
        globalThis.__antworten = (pfad) => pfad.includes('/translations/en')
          ? 'scheitert'
          : ({ texte: { gruss: 'Hallo' }, sprache: 'de' })
        await m.spracheWaehlen('de')
        let gefallen = false
        try { await m.spracheWaehlen('en') } catch { gefallen = true }
        await api.modelle()
        return { gesehen, gefallen, sprache: m.texte.sprache, wahl: m.texte.wahl }
        """
    )
    assert bericht["gefallen"] is True
    assert bericht["sprache"] == "de"
    assert bericht["wahl"] == "de"
    # The choice is stored only after its catalogue arrived: the failed
    # switch writes nothing, so there is nothing to take back — and the
    # language of the requests never moved.
    assert bericht["gesehen"] == [
        ["/translations/de", "de", None],
        ["/settings/global/sprache", "de", "de"],
        ["/translations/en", "en", None],
        ["/models", "de", None],
    ]


@node_da
def test_ein_haengender_wechsel_aendert_weder_wahl_noch_gespeichertes():
    """German window, the English catalogue never answers: the pill's value
    (`texte.wahl`) stays German and `en` is never stored. Before, both were
    written ahead of the request and stayed — English over a German window,
    and the next start loaded English."""
    bericht = _lauf(
        """
        globalThis.__antworten = (pfad) => pfad.includes('/translations/en')
          ? 'haengt'
          : ({ texte: { gruss: 'Hallo' }, sprache: 'de' })
        await m.spracheWaehlen('de')
        const unterwegs = m.spracheWaehlen('en')
        await new Promise((fertig) => setTimeout(fertig, 50))
        return { gesehen, wahl: m.texte.wahl, sprache: m.texte.sprache }
        """
    )
    assert bericht["wahl"] == "de"
    assert bericht["sprache"] == "de"
    assert ["/settings/global/sprache", "de", "en"] not in bericht["gesehen"]
    assert bericht["gesehen"][-1] == ["/translations/en", "en", None]


@node_da
def test_der_juengere_wechsel_gewinnt_auch_wenn_der_aeltere_katalog_spaeter_kommt():
    """Two switches shortly after each other, the older catalogue arrives
    last: the newer catalogue, the newer choice and the newer stored value
    stand — the late one changes nothing."""
    bericht = _lauf(
        """
        let freigeben
        const spaet = new Promise((fertig) => { freigeben = fertig })
        globalThis.__antworten = (pfad) => {
          if (pfad.includes('/translations/en')) return spaet.then(() => ({ texte: { gruss: 'Hello' }, sprache: 'en' }))
          return ({ texte: { gruss: 'Hallo' }, sprache: 'de' })
        }
        const aelter = m.spracheWaehlen('en')
        await m.spracheWaehlen('de')
        freigeben()
        await aelter
        return { gesehen, wahl: m.texte.wahl, sprache: m.texte.sprache, gruss: m.texte.katalog.gruss }
        """
    )
    assert bericht["wahl"] == "de"
    assert bericht["sprache"] == "de"
    assert bericht["gruss"] == "Hallo"
    # Only the newer choice was ever stored.
    gespeichert = [z[2] for z in bericht["gesehen"] if z[0] == "/settings/global/sprache"]
    assert gespeichert == ["de"]


@node_da
def test_ein_gelungener_wechsel_gilt_danach_ueberall():
    """The silence probe: once the texts are there, the new language stands —
    for the window and for every request after it."""
    bericht = _lauf(
        """
        globalThis.__antworten = (pfad) => pfad.includes('/translations/de')
          ? 'scheitert'
          : ({ texte: { gruss: 'Hello' }, sprache: 'en' })
        await m.texteLaden('en')
        await api.modelle()
        return { gesehen, sprache: m.texte.sprache }
        """
    )
    assert bericht["sprache"] == "en"
    assert bericht["gesehen"][-1] == ["/models", "en", None]


@node_da
def test_die_gemerkte_wahl_steht_im_reaktiven_zustand():
    """The stored choice lives IN the reactive state: the settings
    tile reads it from there, so a choice made anywhere — the first-start
    window, the load at program start — reaches the tile without a click. A
    plain module variable, the state before the fix, is invisible to every
    reader outside the module."""
    bericht = _lauf(
        """
        globalThis.__antworten = () => ({ texte: { gruss: 'Hallo' }, sprache: 'de' })
        await m.spracheWaehlen('de')
        return {
          wahl: m.texte.wahl,
          eigen: Object.prototype.hasOwnProperty.call(m.texte, 'wahl'),
        }
        """
    )
    assert bericht["wahl"] == "de"
    assert bericht["eigen"] is True


def test_die_pille_liest_nur_die_gespeicherte_wahl():
    """The pill is a field that, left to itself, keeps the entry that was
    clicked. Bound for reading only, it shows `texte.wahl` and nothing else:
    a switch that never arrives leaves the pill where it was."""
    huelle = (QUELLE / "teile" / "SystemPrompt.svelte").read_text(encoding="utf-8")
    assert "bind:wert={() => sprachwahl, () => {}}" in huelle
    assert "const sprachwahl = $derived(texte.wahl)" in huelle
