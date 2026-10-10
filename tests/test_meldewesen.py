"""One place decides whether something is heard, and it is not the caller.

The rule this file holds down is a source rule, so it is measured on the
source: nobody outside frontend/src/lib/meldewesen.svelte.js reaches for a
sound. A caller that rings its own bell is a policy nobody can switch off,
which is exactly what the reporting module exists to end.

The settings half is checked the way every other stored choice is — through
the checker that vouches for it (app/meldewahl.py).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

from app import meldewahl

WURZEL = Path(__file__).resolve().parents[1]
QUELLE = WURZEL / "frontend" / "src"

# Where a sound may be reached for at all: the module that owns playing it,
# and the module that decides it is wanted.
ERLAUBT = {"lib/klaenge.svelte.js", "lib/meldewesen.svelte.js"}

RUFT_KLINGEN = re.compile(r"\bklingen\s*\(")


def _quelldateien():
    for pfad in sorted(QUELLE.rglob("*")):
        if pfad.suffix in (".svelte", ".js") and pfad.is_file():
            yield pfad


# --- The source rule -------------------------------------------------------


def test_kein_aufrufer_klingt_selbst():
    schuldige = []
    for pfad in _quelldateien():
        name = pfad.relative_to(QUELLE).as_posix()
        if name in ERLAUBT:
            continue
        if RUFT_KLINGEN.search(pfad.read_text(encoding="utf-8")):
            schuldige.append(name)
    assert not schuldige, (
        "these reach for a sound instead of reporting what happened: "
        + ", ".join(schuldige)
    )


def test_das_meldemodul_ist_der_einzige_weg_hinein():
    """The four places that stop and wait report an occurrence now."""
    app = (QUELLE / "App.svelte").read_text(encoding="utf-8")
    zustand = (QUELLE / "lib" / "zustand.svelte.js").read_text(encoding="utf-8")
    assert app.count("melden({ was: 'wartet'") == 3
    assert "melden({ was: 'wartet'" in zustand
    assert "melden({ was: 'fertig'" in zustand


# --- What is stored --------------------------------------------------------


def test_vorgabe_ist_angeschaltet():
    """Shipped switched on: everything is reported, every dot pulses, and
    the notice waits to be read rather than for a clock."""
    vorgabe = meldewahl.aufgeloest(None)
    assert vorgabe["popup_sekunden"] == 0
    assert all(vorgabe[name] is True for name in (*meldewahl.PUNKTE, *meldewahl.MELDER))


def test_eine_abgeschaltete_meldung_ueberlebt_das_speichern():
    """The three occurrence switches moved here from the sound key when
    they started governing the whole notice. A bare False must not read as
    "nothing set" here either."""
    gespeichert = meldewahl.wahl_pruefen({"melde_fehler": False})
    assert gespeichert == {"melde_fehler": False}
    aufgeloest = meldewahl.aufgeloest(gespeichert)
    assert aufgeloest["melde_fehler"] is False
    assert aufgeloest["melde_fertig"] is True


def test_ein_ausgeschalteter_punkt_ueberlebt_das_speichern():
    """The reason this key is one object: a bare False must not read as
    'nothing set' and let the default switch the dot back on."""
    gespeichert = meldewahl.wahl_pruefen({"punkt_chat": False})
    assert gespeichert == {"punkt_chat": False}
    assert meldewahl.aufgeloest(gespeichert)["punkt_chat"] is False
    assert meldewahl.aufgeloest(gespeichert)["punkt_agenten"] is True


def test_die_null_bleibt_die_null():
    """Zero is 'Auto', not 'nothing set' — it has to survive a round trip."""
    gespeichert = meldewahl.wahl_pruefen({"popup_sekunden": 0, "punkt_chat": False})
    assert meldewahl.aufgeloest(gespeichert)["popup_sekunden"] == 0


def test_unfug_faellt_heraus():
    assert meldewahl.wahl_pruefen("acht") is None
    assert meldewahl.wahl_pruefen({}) is None
    assert meldewahl.wahl_pruefen({"punkt_chat": "ja"}) is None
    # True is an int in Python, and a bool must not slip through as seconds.
    assert meldewahl.wahl_pruefen({"popup_sekunden": True}) is None


def test_sekunden_werden_in_die_grenzen_geholt():
    assert meldewahl.wahl_pruefen({"popup_sekunden": -4})["popup_sekunden"] == 0
    assert (
        meldewahl.wahl_pruefen({"popup_sekunden": 9999})["popup_sekunden"]
        == meldewahl.POPUP_MAX
    )


# --- Which dot moves, and when ---------------------------------------------

FRONTEND = WURZEL / "frontend"
MODUL = QUELLE / "lib" / "meldewesen.svelte.js"

node_da = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)


@contextmanager
def _pruefordner():
    """A folder of this run's own, under node_modules so the compiled module
    can resolve `svelte/internal/client` by walking up — the same stand
    tests/test_agentenampel.py builds, and for the same two reasons."""
    ordner = FRONTEND / "node_modules" / f".pruefstand-meldewesen-{uuid4().hex}"
    ordner.mkdir(parents=True)
    try:
        yield ordner
    finally:
        shutil.rmtree(ordner, ignore_errors=True)


def _atmet(faelle: list[tuple[str, str]], *, aus: list[str] | None = None) -> list[bool]:
    """Run the shipped decision against (dot, colour) pairs. `aus` names the
    dots whose switch is off."""
    with _pruefordner() as ordner:
        gebaut = ordner / "gebaut.mjs"
        (ordner / "api.mjs").write_text("export const api = {}\n", encoding="utf-8")
        # The catalogue, stubbed: `meldeText` reads it to build its sentence,
        # and none of these measurements is about words.
        (ordner / "texte.mjs").write_text(
            "export function t(pfad) { return pfad }\n"
            "export function teile(pfad) { return [{ fest: pfad }] }\n",
            encoding="utf-8",
        )
        (ordner / "klaenge.mjs").write_text(
            "export function klingen() {}\n", encoding="utf-8"
        )
        (ordner / "zustand.mjs").write_text(
            "export function melde() { return 0 }\n", encoding="utf-8"
        )
        treiber = ordner / "pruefung.mjs"
        treiber.write_text(
            textwrap.dedent(
                """
                import { compileModule } from 'svelte/compiler'
                import { readFileSync, writeFileSync } from 'fs'
                const quelle = readFileSync(%r, 'utf-8')
                const gebaut = compileModule(quelle, {
                  filename: 'meldewesen.svelte.js', generate: 'client',
                })
                // Only what the module talks TO is stubbed — the decision
                // itself is the shipped one.
                writeFileSync(%r, gebaut.js.code
                  .replace('./api.js', './api.mjs')
                  .replace('./klaenge.svelte.js', './klaenge.mjs')
                  .replace('./zustand.svelte.js', './zustand.mjs')
                  .replace('./texte.svelte.js', './texte.mjs'))
                const m = await import('./gebaut.mjs')
                for (const name of %s) m.meldewesen.punkte[name] = false
                const antwort = %s.map(([welcher, farbe]) =>
                  m.punktAtmet(welcher, farbe))
                console.log('---BERICHT---' + JSON.stringify(antwort))
                """
            )
            % (str(MODUL), str(gebaut), json.dumps(aus or []), json.dumps(faelle)),
            encoding="utf-8",
        )
        ergebnis = subprocess.run(
            ["node", treiber.name], cwd=ordner, capture_output=True, text=True, encoding="utf-8", timeout=120
        )
    assert ergebnis.returncode == 0, (ergebnis.stdout + ergebnis.stderr)[-2000:]
    marke = "---BERICHT---"
    assert marke in ergebnis.stdout, ergebnis.stdout[-2000:]
    return json.loads(ergebnis.stdout.split(marke, 1)[1].strip())


@node_da
def test_ein_zustand_bewegt_sich_eine_tatsache_nicht():
    """Three of the four state colours want a hand and move for it. Blue
    does not: it only says a run is going, which needs nobody — and a run
    can go for an hour, so a mark pulsing for it would pulse in the corner
    of the eye for an hour and teach the eye to look away. The grey disc and
    the empty one are a fact and a placeholder, and neither moves either."""
    assert _atmet(
        [
            ("agenten", "gruen"), ("agenten", "rot"),
            ("agenten", "gelb"), ("agenten", "blau"),
            ("agenten", "still"), ("chat", "leer"), ("chat", ""),
        ]
    ) == [True, True, True, False, False, False, False]


@node_da
def test_je_schalter_steht_genau_ein_punkt_still():
    """The measurement from the order: one switch off, and the other three
    keep moving."""
    faelle = [
        ("agenten", "gruen"), ("cronjob", "gruen"),
        ("terminal", "gruen"), ("chat", "gruen"),
    ]
    assert _atmet(faelle) == [True, True, True, True]
    assert _atmet(faelle, aus=["cronjob"]) == [True, False, True, True]
    assert _atmet(faelle, aus=["agenten", "cronjob", "terminal", "chat"]) == [
        False, False, False, False
    ]


# --- All four are actually wired to a switch -------------------------------


def test_alle_vier_punkte_haengen_an_ihrem_schalter():
    """A dot that draws itself without asking is a dot nobody can quiet."""
    erwartet = {
        "teile/ToolSigns.svelte": ["punktAtmet('agenten'", "punktAtmet('cronjob'",
                                   "punktAtmet('terminal'"],
        "teile/Chatzeile.svelte": ["punktAtmet('chat'"],
        "teile/ModulTerminal.svelte": ["punktAtmet('terminal'"],
    }
    for name, stuecke in erwartet.items():
        quelle = (QUELLE / name).read_text(encoding="utf-8")
        for stueck in stuecke:
            assert stueck in quelle, f"{name} is missing {stueck}"


# --- A switch that is off means nothing happens ----------------------------


def _gemeldet(faelle: list[dict], *, aus: list[str] | None = None) -> dict:
    """Run `melden()` for each case against the shipped module and report
    what reached the sound and what reached the notice list."""
    with _pruefordner() as ordner:
        gebaut = ordner / "gebaut.mjs"
        (ordner / "api.mjs").write_text("export const api = {}\n", encoding="utf-8")
        # The catalogue, stubbed: `meldeText` reads it to build its sentence,
        # and none of these measurements is about words.
        (ordner / "texte.mjs").write_text(
            "export function t(pfad) { return pfad }\n"
            "export function teile(pfad) { return [{ fest: pfad }] }\n",
            encoding="utf-8",
        )
        (ordner / "klaenge.mjs").write_text(
            "export const gehoert = []\n"
            "export function klingen(name) { gehoert.push(name) }\n",
            encoding="utf-8",
        )
        treiber = ordner / "pruefung.mjs"
        treiber.write_text(
            textwrap.dedent(
                """
                import { compileModule } from 'svelte/compiler'
                import { readFileSync, writeFileSync } from 'fs'
                const quelle = readFileSync(%r, 'utf-8')
                const gebaut = compileModule(quelle, {
                  filename: 'meldewesen.svelte.js', generate: 'client',
                })
                writeFileSync(%r, gebaut.js.code
                  .replace('./api.js', './api.mjs')
                  .replace('./klaenge.svelte.js', './klaenge.mjs')
                  .replace('./texte.svelte.js', './texte.mjs'))
                const m = await import('./gebaut.mjs')
                const { gehoert } = await import('./klaenge.mjs')
                for (const name of %s) m.meldewesen.melder[name] = false
                for (const fall of %s) m.melden(fall)
                console.log('---BERICHT---' + JSON.stringify({
                  gehoert,
                  meldungen: m.meldungen.liste.map((n) => n.text),
                }))
                """
            )
            % (str(MODUL), str(gebaut), json.dumps(aus or []), json.dumps(faelle)),
            encoding="utf-8",
        )
        ergebnis = subprocess.run(
            ["node", treiber.name], cwd=ordner, capture_output=True, text=True, encoding="utf-8", timeout=120
        )
    assert ergebnis.returncode == 0, (ergebnis.stdout + ergebnis.stderr)[-2000:]
    marke = "---BERICHT---"
    assert marke in ergebnis.stdout, ergebnis.stdout[-2000:]
    return json.loads(ergebnis.stdout.split(marke, 1)[1].strip())


@node_da
def test_angeschaltet_kommt_text_und_ton():
    ergebnis = _gemeldet(
        [
            {"was": "fertig", "text": "Rechercheur · fertig"},
            {"was": "fehler", "text": "Sammler · gescheitert"},
        ]
    )
    assert ergebnis["gehoert"] == ["fertig", "fehler"]
    assert ergebnis["meldungen"] == ["Rechercheur · fertig", "Sammler · gescheitert"]


@node_da
def test_ein_ausgeschalteter_melder_schweigt_ganz():
    """Not a quieter version of the notice — none of it. The switch is
    called "Failed", not "Failure sound"."""
    ergebnis = _gemeldet(
        [
            {"was": "fertig", "text": "Rechercheur · fertig"},
            {"was": "fehler", "text": "Sammler · gescheitert"},
        ],
        aus=["fehler"],
    )
    assert ergebnis["gehoert"] == ["fertig"]
    assert ergebnis["meldungen"] == ["Rechercheur · fertig"]


@node_da
def test_ein_fehler_klingt_genau_einmal():
    """`melden()` rings the occurrence and `melde()` rings the toast kind.
    Both used to fire for the same failure — two tables judging one event,
    inaudible only because the second call restarts the first."""
    assert _gemeldet([{"was": "fehler", "text": "einmal"}])["gehoert"] == ["fehler"]


@node_da
def test_ein_fehlertoast_ohne_umweg_haengt_am_selben_schalter():
    """A failure is one of the three wherever it comes from — including a
    bare `melde(text, 'fehler')` from whoever could not save."""
    with _pruefordner() as ordner:
        gebaut = ordner / "gebaut.mjs"
        (ordner / "api.mjs").write_text("export const api = {}\n", encoding="utf-8")
        # The catalogue, stubbed: `meldeText` reads it to build its sentence,
        # and none of these measurements is about words.
        (ordner / "texte.mjs").write_text(
            "export function t(pfad) { return pfad }\n"
            "export function teile(pfad) { return [{ fest: pfad }] }\n",
            encoding="utf-8",
        )
        (ordner / "klaenge.mjs").write_text(
            "export const gehoert = []\n"
            "export function klingen(name) { gehoert.push(name) }\n",
            encoding="utf-8",
        )
        treiber = ordner / "pruefung.mjs"
        treiber.write_text(
            textwrap.dedent(
                """
                import { compileModule } from 'svelte/compiler'
                import { readFileSync, writeFileSync } from 'fs'
                const quelle = readFileSync(%r, 'utf-8')
                const gebaut = compileModule(quelle, {
                  filename: 'meldewesen.svelte.js', generate: 'client',
                })
                writeFileSync(%r, gebaut.js.code
                  .replace('./api.js', './api.mjs')
                  .replace('./klaenge.svelte.js', './klaenge.mjs')
                  .replace('./texte.svelte.js', './texte.mjs'))
                const m = await import('./gebaut.mjs')
                const { gehoert } = await import('./klaenge.mjs')
                m.melde('could not save', 'fehler')
                m.melde('saved', 'erfolg')
                m.meldewesen.melder.fehler = false
                m.melde('still could not save', 'fehler')
                console.log('---BERICHT---' + JSON.stringify({
                  gehoert, meldungen: m.meldungen.liste.map((n) => n.text),
                }))
                """
            )
            % (str(MODUL), str(gebaut)),
            encoding="utf-8",
        )
        ergebnis = subprocess.run(
            ["node", treiber.name], cwd=ordner, capture_output=True, text=True, encoding="utf-8", timeout=120
        )
    assert ergebnis.returncode == 0, (ergebnis.stdout + ergebnis.stderr)[-2000:]
    bericht = json.loads(ergebnis.stdout.split("---BERICHT---", 1)[1].strip())
    assert bericht["gehoert"] == ["fehler"]
    assert bericht["meldungen"] == ["could not save", "saved"]


@node_da
def test_ein_umschreiben_auf_fehler_haengt_am_selben_schalter():
    """`aktualisiereMeldung` is the second door into the same rule
    `melde()` already keeps at the top of this file: a rewrite that turns a
    running notice into a failure is a failure just the same, and the
    switch says the whole notice stays away — not that its last running
    text should keep standing once the switch judged it."""
    with _pruefordner() as ordner:
        gebaut = ordner / "gebaut.mjs"
        (ordner / "api.mjs").write_text("export const api = {}\n", encoding="utf-8")
        (ordner / "texte.mjs").write_text(
            "export function t(pfad) { return pfad }\n"
            "export function teile(pfad) { return [{ fest: pfad }] }\n",
            encoding="utf-8",
        )
        (ordner / "klaenge.mjs").write_text("export function klingen() {}\n", encoding="utf-8")
        treiber = ordner / "pruefung.mjs"
        treiber.write_text(
            textwrap.dedent(
                """
                import { compileModule } from 'svelte/compiler'
                import { readFileSync, writeFileSync } from 'fs'
                const quelle = readFileSync(%r, 'utf-8')
                const gebaut = compileModule(quelle, {
                  filename: 'meldewesen.svelte.js', generate: 'client',
                })
                writeFileSync(%r, gebaut.js.code
                  .replace('./api.js', './api.mjs')
                  .replace('./klaenge.svelte.js', './klaenge.mjs')
                  .replace('./texte.svelte.js', './texte.mjs'))
                const m = await import('./gebaut.mjs')

                // Switch off: a standing "wird geschrieben" notice rewritten
                // into a failure disappears whole, not just its sound.
                const einsId = m.melde('read_file wird geschrieben', 'werkzeug', { dauerhaft: true })
                m.meldewesen.melder.fehler = false
                const einsGeaendert = m.aktualisiereMeldung(einsId, {
                  text: 'read_file fehlgeschlagen', art: 'fehler',
                })
                const einsMeldungen = m.meldungen.liste.map((n) => n.text)

                // Gegenprobe: switch back on, the same rewrite shows.
                m.meldewesen.melder.fehler = true
                const zweiId = m.melde('write_file wird geschrieben', 'werkzeug', { dauerhaft: true })
                m.aktualisiereMeldung(zweiId, { text: 'write_file fehlgeschlagen', art: 'fehler' })
                const zweiMeldungen = m.meldungen.liste.map((n) => n.text)

                // Schweigeprobe: switch off again, but the rewrite is to a
                // DIFFERENT kind — only 'fehler' is this switch's business.
                m.meldewesen.melder.fehler = false
                const dreiId = m.melde('run_command wird geschrieben', 'werkzeug', { dauerhaft: true })
                m.aktualisiereMeldung(dreiId, { text: 'run_command fertig', art: 'erfolg' })
                const dreiMeldungen = m.meldungen.liste.map((n) => n.text)

                console.log('---BERICHT---' + JSON.stringify({
                  einsGeaendert, einsMeldungen, zweiMeldungen, dreiMeldungen,
                }))
                """
            )
            % (str(MODUL), str(gebaut)),
            encoding="utf-8",
        )
        ergebnis = subprocess.run(
            ["node", treiber.name], cwd=ordner, capture_output=True, text=True, encoding="utf-8", timeout=120
        )
    assert ergebnis.returncode == 0, (ergebnis.stdout + ergebnis.stderr)[-2000:]
    bericht = json.loads(ergebnis.stdout.split("---BERICHT---", 1)[1].strip())
    assert bericht["einsGeaendert"] is True
    assert bericht["einsMeldungen"] == [], (
        "the running notice stayed instead of disappearing with the switch off"
    )
    assert "write_file fehlgeschlagen" in bericht["zweiMeldungen"]
    assert "run_command fertig" in bericht["dreiMeldungen"]
