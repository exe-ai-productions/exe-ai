"""One notice for a whole answer, rewritten as the work moves on.

A tool call used to be reported three times over: a notice while the model
was still typing the arguments, that one CLOSED and a second opened when the
call really started, and a third state for the result. Two tools were six
notices appearing and vanishing in a few seconds, and with three the most
that stand at once, the stack shoved itself through the whole time.

Measured against the shipped reporting module, compiled the way the browser
gets it: the sequence of a real answer is played through it and what stands
at the end is counted.
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

WURZEL = Path(__file__).resolve().parents[1]
FRONTEND = WURZEL / "frontend"
QUELLE = FRONTEND / "src"
MODUL = QUELLE / "lib" / "meldewesen.svelte.js"

node_da = pytest.mark.skipif(
    not (FRONTEND / "node_modules" / "svelte").is_dir(),
    reason="svelte is not installed",
)


@contextmanager
def _pruefordner():
    ordner = FRONTEND / "node_modules" / f".pruefstand-wzmeldung-{uuid4().hex}"
    ordner.mkdir(parents=True)
    try:
        yield ordner
    finally:
        shutil.rmtree(ordner, ignore_errors=True)


def _lauf(js: str) -> dict:
    """Run a piece of JS against the shipped module and read its report."""
    with _pruefordner() as ordner:
        gebaut = ordner / "gebaut.mjs"
        (ordner / "api.mjs").write_text("export const api = {}\n", encoding="utf-8")
        (ordner / "klaenge.mjs").write_text("export function klingen() {}\n", encoding="utf-8")
        (ordner / "zustand.mjs").write_text("export function melde() { return 0 }\n", encoding="utf-8")
        (ordner / "texte.mjs").write_text(
            "export function t(pfad, werte) {\n"
            "  return pfad + (werte && werte.name ? ':' + werte.name : '')\n"
            "}\n"
            "export function teile(pfad, werte) {\n"
            "  return [{ fest: pfad + (werte && werte.name ? ':' + werte.name : '') }]\n"
            "}\n",
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
                  .replace('./zustand.svelte.js', './zustand.mjs')
                  .replace('./texte.svelte.js', './texte.mjs'))
                const m = await import('./gebaut.mjs')
                %s
                """
            )
            % (str(MODUL), str(gebaut), js),
            encoding="utf-8",
        )
        ergebnis = subprocess.run(
            ["node", treiber.name], cwd=ordner, capture_output=True, text=True, timeout=120
        )
    assert ergebnis.returncode == 0, (ergebnis.stdout + ergebnis.stderr)[-2000:]
    marke = "---BERICHT---"
    assert marke in ergebnis.stdout, ergebnis.stdout[-2000:]
    return json.loads(ergebnis.stdout.split(marke, 1)[1].strip())


# --- The module's own half of the arrangement -------------------------------


@node_da
def test_eine_meldung_wird_umgeschrieben_statt_ersetzt():
    """The whole sequence of an answer with two tools, through one notice.

    Nine steps — typing, running, done, and the same again for the second
    tool — and exactly one notice stands at the end. Before this the same
    nine steps left four notices behind, two of which had already been
    closed and reopened in front of the user.
    """
    js = """
    let id = 0
    const sagen = (pfad, name, art, dauerhaft) => {
      if (id && m.aktualisiereMeldung(id, {
        text: pfad + ':' + name, art, dauerhaft, schluessel: pfad, werte: { name },
        werkzeug: name,
      })) return
      id = m.melde(pfad + ':' + name, art, { dauerhaft, werkzeug: name })
    }
    sagen('werkzeug.schreibt', 'web_search', 'werkzeug', true)
    sagen('werkzeug.schreibt', 'web_search', 'werkzeug', true)
    sagen('werkzeug.schreibt', 'web_search', 'werkzeug', true)
    sagen('werkzeug.laeuft', 'web_search', 'werkzeug', true)
    sagen('werkzeug.fertig', 'web_search', 'erfolg', false)
    sagen('werkzeug.schreibt', 'run_command', 'werkzeug', true)
    sagen('werkzeug.laeuft', 'run_command', 'werkzeug', true)
    sagen('werkzeug.fertig', 'run_command', 'erfolg', false)
    const stand = m.meldungen.liste.map((x) => ({
      text: x.text, art: x.art, werkzeug: x.werkzeug,
    }))
    console.log('---BERICHT---' + JSON.stringify({ anzahl: stand.length, stand }))
    """
    bericht = _lauf(js)
    assert bericht["anzahl"] == 1, bericht["stand"]
    (uebrig,) = bericht["stand"]
    assert uebrig["text"] == "werkzeug.fertig:run_command"
    assert uebrig["art"] == "erfolg"
    # The mark travels with the text: a notice that walked from one tool to
    # the next must not still be drawing the first one's icon.
    assert uebrig["werkzeug"] == "run_command"


@node_da
def test_eine_verschwundene_meldung_kommt_zurueck():
    """Three is the most that stand at once. A notice pushed out by newer
    ones cannot be rewritten — and the caller has to be able to tell, or its
    line silently stops appearing for the rest of the run."""
    js = """
    const id = m.melde('werkzeug.laeuft:web_search', 'werkzeug', { dauerhaft: true })
    // Three more push it out.
    m.melde('a', 'hinweis'); m.melde('b', 'hinweis'); m.melde('c', 'hinweis')
    const nochDa = m.meldungen.liste.some((x) => x.id === id)
    const konnte = m.aktualisiereMeldung(id, { text: 'neu', dauerhaft: true })
    console.log('---BERICHT---' + JSON.stringify({ nochDa, konnte }))
    """
    bericht = _lauf(js)
    assert bericht["nochDa"] is False, "the cap did not push the notice out"
    assert bericht["konnte"] is False, (
        "a rewrite of a notice that is gone reported success — the caller "
        "would never create a new one and its line would stay missing"
    )


@node_da
def test_eine_laufende_uhr_wird_beim_umschreiben_gestoppt():
    """A notice rewritten from a finished call back into a running one must
    not close itself two seconds later, in the middle of the call it has just
    started reporting."""
    js = """
    const id = m.melde('fertig', 'erfolg')          // 2.4 s clock running
    m.aktualisiereMeldung(id, { text: 'laeuft', art: 'werkzeug', dauerhaft: true })
    await new Promise((r) => setTimeout(r, 2700))   // past the old clock
    const nochDa = m.meldungen.liste.some((x) => x.id === id)
    console.log('---BERICHT---' + JSON.stringify({ nochDa }))
    """
    bericht = _lauf(js)
    assert bericht["nochDa"] is True, (
        "the notice closed itself on the clock of the state it no longer has"
    )


@node_da
def test_der_haken_folgt_der_anzeigedauer():
    """Ten seconds set means ten seconds of tick, not the house's 1.5.

    Without the fix the module has no answer to this question at all: the
    tick carried `WERKZEUG_FERTIG_MS` written into the call site, and the
    setting reached every notice but this one.
    """
    js = """
    m.meldewesen.popupSekunden = 10
    console.log('---BERICHT---' + JSON.stringify({ dauer: m.werkzeugFertigDauer() }))
    """
    bericht = _lauf(js)
    assert bericht["dauer"] == 10_000, bericht


@node_da
def test_auf_auto_bleibt_dem_haken_seine_eigene_zeit():
    """Silence test: "Auto" is the field's 0, and it is not a duration.

    The house tick keeps its own short clock there instead of the kind's
    own `erfolg` (2400 ms) — it is the closing line of a commentary nobody
    stops to read.
    """
    js = """
    m.meldewesen.popupSekunden = 0
    console.log('---BERICHT---' + JSON.stringify({ dauer: m.werkzeugFertigDauer() }))
    """
    bericht = _lauf(js)
    assert bericht["dauer"] == 1500, bericht


# --- The caller's half ------------------------------------------------------


def test_der_haken_holt_seine_dauer_an_der_einen_stelle():
    """The second half of the same rule: a helper nobody calls changes
    nothing. Put `WERKZEUG_FERTIG_MS` back into the call site and the tick
    ignores the setting again — with every test above still green.

    So the call site is read here, the way this file reads App.svelte for
    the tool notice's other rules — and read for the expression itself:

    the tick's last argument is `: werkzeugFertigDauer()`, with the colon of
    the ternary in front of it. A test that only looked for the name would
    stay green on a rebuild, because the comment three lines above the call
    names the function too; a test that banned the constant's identifier
    would go red on a comment about it. This one names the call.
    """
    quelle = (QUELLE / "App.svelte").read_text(encoding="utf-8")
    assert ": werkzeugFertigDauer()" in quelle, (
        "the tick's clock is decided in the call site again"
    )


def test_der_chat_meldet_werkzeuge_durch_eine_einzige_meldung():
    """A rule nobody applies is a rule that does not exist: the answer's
    three tool events all have to go through the one rewriting helper."""
    quelle = (QUELLE / "App.svelte").read_text(encoding="utf-8")
    assert "werkzeugSagen(" in quelle, "the rewriting helper is gone"
    # Three events, one helper, no second way in.
    for zeile in ("werkzeug.schreibt", "werkzeug.laeuft", "werkzeug.fertig"):
        treffer = [z for z in quelle.splitlines() if zeile in z and "werkzeugSagen" not in z]
        offen = [z for z in treffer if "melde" in z or "aktualisiereMeldung" in z]
        assert not offen, f"{zeile} still reports past the helper: {offen}"
    # A rewrite never rings, so the creation beside it must not either —
    # or the same failure would sound or not by whether its notice happened
    # to have been pushed out a moment earlier.
    assert "stumm: true" in quelle, (
        "the tool notice can ring when it is created and never when it is "
        "rewritten"
    )
    # And nothing closes a tool notice to open another in its place. The one
    # place that may close it is the helper for a call that asks for an
    # answer (permission, question, job): the call is complete, "is being
    # written" is no longer true, and the box above the field is what says
    # "waiting" — the notice for the running call opens afresh once allowed.
    for treffer in re.finditer(
        r"schliesseMeldung\([^)]*\)\s*\n\s*werkzeugMeldungen\.delete", quelle
    ):
        davor = quelle[max(0, treffer.start() - 400):treffer.start()]
        assert "function schreibendeMeldungSchliessen()" in davor, (
            "a tool notice is still being closed and reopened"
        )
    # Each branch up to the point where it files the question.
    enden = {
        "tool_confirm": "zustand.werkzeugfrage[zielChat] = {",
        "user_ask": "platzhalter.werkzeuge.push(",
        "job_confirm": "platzhalter.werkzeuge.push(",
    }
    for ereignis_typ, ende in enden.items():
        abschnitt = quelle[quelle.index(f"ereignis.typ === '{ereignis_typ}') {{"):]
        abschnitt = abschnitt[:abschnitt.index(ende)]
        assert "schreibendeMeldungSchliessen()" in abschnitt, (
            f"a {ereignis_typ} question must take the 'is being written' notice down"
        )


@node_da
def test_ein_gescheiterter_werkzeugaufruf_bleibt_fuenf_sekunden():
    """A failed tool call is always up for exactly
    five seconds.

    It carried no duration of its own and fell back to the kind's 7 s; the
    notice-duration field never reached that way. It carries
    `WERKZEUG_FEHLER_MS` now — and that number does not move with the
    field, whatever the field stands on.

    Read where it lives: the constant itself while the field is set, beside
    the tick's own helper, which DOES follow the field.
    """
    js = """
    m.meldewesen.popupSekunden = 10
    console.log('---BERICHT---' + JSON.stringify({
      konstante: m.WERKZEUG_FEHLER_MS,
      haken: m.werkzeugFertigDauer(),
    }))
    """
    bericht = _lauf(js)
    assert bericht["konstante"] == 5000, bericht
    # Silence probe: the tick beside it still follows the field.
    assert bericht["haken"] == 10_000, bericht


def test_der_fehlerfall_liest_die_anzeigedauer_nicht():
    """The other half, at the call site: a constant nobody reads changes
    nothing. The failure's clock is the constant, the tick's is the helper.

    Read off the expression, the way this file reads the tick's line — the
    names around it stand in the comment above, so a test looking for
    `werkzeugFertigDauer` alone would go red on prose and green on a
    rebuild that put the helper back into the failure's argument.
    """
    quelle = (QUELLE / "App.svelte").read_text(encoding="utf-8")
    assert "WERKZEUG_FEHLER_MS : werkzeugFertigDauer()" in quelle, (
        "the error case follows the display duration again"
    )
    # And the kind's own failure duration is untouched. What this reads is
    # the table entry, not every failure path: a run failure goes through
    # `melden({ was: 'fehler' })` and follows the notice-duration field —
    # turned off by hand it does not stand at all. Untouched here means: the
    # entry the plain `melde(..., 'fehler')` callers use is still 7000.
    modul = MODUL.read_text(encoding="utf-8")
    assert "fehler: 7000" in modul, (
        "the duration of the other error notices was changed along with it"
    )


def test_der_helfer_reicht_die_dauer_an_beide_wege_weiter():
    """The third link in the chain, and the one the tests above cannot see.

    `WERKZEUG_FEHLER_MS` at the call site and the constant in the module are
    both worthless if `werkzeugSagen` drops its `dauer` argument on the way:
    the notice would fall back to the kind's 7 s again, with both tests above
    still green. Read off the helper's body — the duration has to reach BOTH
    ways it can take, the rewrite and the fresh notice.
    """
    quelle = (QUELLE / "App.svelte").read_text(encoding="utf-8")
    treffer = re.search(r"const werkzeugSagen = \(([\s\S]*?)\n    \}\n", quelle)
    assert treffer, "werkzeugSagen no longer reads as expected"
    rumpf = treffer.group(1)
    assert "dauer = 0" in rumpf, "the duration is no longer an argument of the helper"
    # Once for the rewrite and once for the fresh notice: two ways, one number.
    assert rumpf.count("dauer,") >= 2, (
        "the helper does not pass the duration on to both ways"
    )
