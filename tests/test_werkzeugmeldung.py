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


# --- The call's row in the answer, from the first character on --------------
#
# A call the model is still writing has its row in the answer already, with
# its name and the number of characters so far; the complete call takes that
# very row over. Played through the shipped branches of the window's stream
# handler: they are cut out of App.svelte and run in node against a plain
# answer, with everything around them (notices, questions, scrolling) as
# stand-ins.

APP = QUELLE / "App.svelte"
MESSAGE = QUELLE / "teile" / "Nachricht.svelte"


def _cut(source: str, start: str, end: str) -> str:
    """The text from `start` up to, not including, `end`."""
    assert source.count(start) == 1, start
    rest = source[source.index(start):]
    assert end in rest, end
    return rest[: rest.index(end)]


def _play(steps: str) -> dict:
    """Run `steps` against the handler's own branches and read the report.

    `handle(event)` is the handler for the events a call's row depends on,
    `rows()` the tool rows of the answer in order: a row still being written
    says so, a row of a complete call names its id and how many entries of
    the tool log carry that id."""
    app = APP.read_text(encoding="utf-8")
    helpers = _cut(
        app,
        "    const werkzeugAnhaengen = (aufrufId, zeitpunktMs) => {",
        "    /* ONE notice for the whole answer",
    )
    assert "const dropRowsNeverBegun = () => {" in helpers
    questions = _cut(
        app,
        "        } else if (ereignis.typ === 'tool_confirm') {",
        "        } else if (ereignis.typ === 'job_confirm') {",
    )
    calls = _cut(
        app,
        "        } else if (ereignis.typ === 'tool_call_laeuft') {",
        "        } else if (ereignis.typ === 'tool_result') {",
    )
    script = (
        textwrap.dedent(
            """
            const platzhalter = { id: 'm', werkzeuge: [], abschnitte: [] }
            let scrolled = 0
            const runter = () => { scrolled += 1 }
            let werkzeugOffen = false
            let drawing = false
            const werkzeugSagen = () => {}
            const taetigkeitSetzen = () => {}
            const lesungenLeeren = () => {}
            const drawingStarted = () => {}
            const melden = () => {}
            const schreibendeMeldungSchliessen = () => {}
            const zielChat = 'c'
            const lauf = { generationId: 'g' }
            const zustand = { werkzeugfrage: {}, benutzerfrage: {}, jobfrage: {} }
            %s
            const handle = (ereignis) => {
              if (false) {
            %s
            %s
              }
            }
            const rows = () => platzhalter.abschnitte
              .filter((a) => a.art === 'werkzeug')
              .map((a) => a.writing
                ? { name: a.writing.name, written: a.writing.written }
                : {
                    id: a.aufruf_id,
                    entries: platzhalter.werkzeuge.filter((w) => w.aufruf_id === a.aufruf_id).length,
                    name: platzhalter.werkzeuge.find((w) => w.aufruf_id === a.aufruf_id)?.name,
                  })
            const writing = (index, name, zeichen) =>
              handle({ typ: 'tool_call_laeuft', index, name, zeichen, zeitpunkt_ms: 1000 + zeichen })
            const complete = (aufruf_id, name, argumente = {}) =>
              handle({ typ: 'tool_call', aufruf_id, name, server: 'own', argumente, zeitpunkt_ms: 9000 })
            const runEnds = () => dropRowsNeverBegun()
            void [werkzeugOffen, drawing]
            """
        )
        % (helpers, questions, calls)
        + textwrap.dedent(steps)
    )
    with _pruefordner() as folder:
        (folder / "play.mjs").write_text(script, encoding="utf-8")
        done = subprocess.run(
            ["node", "play.mjs"], cwd=folder, capture_output=True, text=True, timeout=60
        )
    assert done.returncode == 0, (done.stdout + done.stderr)[-2000:]
    mark = "---BERICHT---"
    assert mark in done.stdout, done.stdout[-2000:]
    return json.loads(done.stdout.split(mark, 1)[1].strip())


def test_a_call_has_its_row_while_the_model_writes_it():
    """One row from the first report on, counting along; the complete call
    takes that row over — its place and its start stay, no second row."""
    report = _play(
        """
        writing(0, 'write_file', 0)
        const first = rows()
        writing(0, 'write_file', 400)
        writing(0, 'write_file', 6656)
        const grown = rows()
        const section = platzhalter.abschnitte[0]
        const began = section.seit
        const scrolledWhileWritten = scrolled
        complete('c1', 'write_file', { path: 'a.html' })
        console.log('---BERICHT---' + JSON.stringify({
          first, grown, done: rows(), scrolledWhileWritten,
          same: platzhalter.abschnitte[0] === section && section.seit === began,
          entry: platzhalter.werkzeuge[0],
        }))
        """
    )
    assert report["first"] == [{"name": "write_file", "written": 0}]
    assert report["grown"] == [{"name": "write_file", "written": 6656}]
    assert report["done"] == [{"id": "c1", "entries": 1, "name": "write_file"}]
    assert report["same"] is True
    # The window follows the new row down once, not with every report.
    assert report["scrolledWhileWritten"] == 1
    assert report["entry"]["argumente"] == {"path": "a.html"}
    assert report["entry"]["server"] == "own"


def test_two_calls_of_one_round_keep_their_rows_in_the_order_written():
    """The first complete call says the round's stream has ended: the call
    still waiting for its turn stops counting and keeps its name. Two calls
    of one name are taken over in the order they were written."""
    report = _play(
        """
        writing(0, 'read_file', 30)
        writing(1, 'read_file', 10)
        writing(1, 'read_file', 45)
        const both = rows()
        complete('c1', 'read_file', { path: 'one' })
        const between = rows()
        complete('c2', 'read_file', { path: 'two' })
        console.log('---BERICHT---' + JSON.stringify({
          both, between, done: rows(),
          paths: platzhalter.werkzeuge.map((w) => w.argumente.path),
        }))
        """
    )
    assert report["both"] == [
        {"name": "read_file", "written": 30},
        {"name": "read_file", "written": 45},
    ]
    assert report["between"] == [
        {"id": "c1", "entries": 1, "name": "read_file"},
        {"name": "read_file", "written": None},
    ]
    assert report["done"] == [
        {"id": "c1", "entries": 1, "name": "read_file"},
        {"id": "c2", "entries": 1, "name": "read_file"},
    ]
    assert report["paths"] == ["one", "two"]


def test_a_call_that_was_never_reported_while_written_appears_as_before():
    """Silence probe: a short call arrives complete and gets one row at the
    end, with one entry in the tool log."""
    report = _play(
        """
        complete('c1', 'get_current_time')
        console.log('---BERICHT---' + JSON.stringify({
          rows: rows(), sections: platzhalter.abschnitte, scrolled,
        }))
        """
    )
    assert report["rows"] == [{"id": "c1", "entries": 1, "name": "get_current_time"}]
    assert report["sections"] == [{"art": "werkzeug", "aufruf_id": "c1", "seit": 9000}]


def test_a_run_that_ends_while_a_call_is_written_leaves_no_half_row():
    """Silence probe: the row of a call that never became one goes with the
    run; the row of a call that ran stays."""
    report = _play(
        """
        writing(0, 'read_file', 20)
        complete('c1', 'read_file')
        writing(0, 'write_file', 300)
        const before = rows()
        runEnds()
        console.log('---BERICHT---' + JSON.stringify({ before, after: rows() }))
        """
    )
    assert report["before"] == [
        {"id": "c1", "entries": 1, "name": "read_file"},
        {"name": "write_file", "written": 300},
    ]
    assert report["after"] == [{"id": "c1", "entries": 1, "name": "read_file"}]
    # The run's end is the one place every ending passes: finished, stopped
    # or failed.
    app = APP.read_text(encoding="utf-8")
    ending = app[app.index("    } finally {\n      /* An answer that ends"):]
    assert "dropRowsNeverBegun()" in ending[: ending.index("if (belegt)")]


def test_a_call_that_waits_for_a_yes_keeps_its_row_and_gets_no_second_one():
    """The permission question comes when the call is complete: the row it
    was written in is its row from there on, and the start that follows the
    answer adds neither a row nor an entry. A call that was not reported
    while written gets its row when it starts, as before."""
    report = _play(
        """
        writing(0, 'run_command', 40)
        handle({ typ: 'tool_confirm', aufruf_id: 'c1', name: 'run_command', argumente: { command: 'ls' }, zeitpunkt_ms: 5000 })
        const asked = rows()
        const waitsFor = zustand.werkzeugfrage.c.aufrufId
        complete('c1', 'run_command', { command: 'ls' })
        const started = rows()
        handle({ typ: 'tool_confirm', aufruf_id: 'c2', name: 'run_command', argumente: {}, zeitpunkt_ms: 6000 })
        const unreported = rows()
        complete('c2', 'run_command')
        console.log('---BERICHT---' + JSON.stringify({
          asked, waitsFor, started, unreported, done: rows(), log: platzhalter.werkzeuge.length,
          server: platzhalter.werkzeuge[0].server,
        }))
        """
    )
    assert report["asked"] == [{"id": "c1", "entries": 1, "name": "run_command"}]
    assert report["waitsFor"] == "c1"
    assert report["started"] == report["asked"]
    assert report["server"] == "own"
    assert report["unreported"] == report["asked"]
    assert report["done"] == [
        {"id": "c1", "entries": 1, "name": "run_command"},
        {"id": "c2", "entries": 1, "name": "run_command"},
    ]
    assert report["log"] == 2


def test_a_run_stopped_at_the_permission_question_leaves_no_row_of_that_call():
    """The call got its row at the question and never started: with the run
    its row and its entry in the tool log go. A call that ran before it
    keeps both."""
    report = _play(
        """
        writing(0, 'read_file', 20)
        complete('c1', 'read_file')
        // Its result is in (the result branch is no part of the cut).
        platzhalter.werkzeuge[0].ergebnis = 'text'
        writing(0, 'run_command', 40)
        handle({ typ: 'tool_confirm', aufruf_id: 'c2', name: 'run_command', argumente: { command: 'ls' }, zeitpunkt_ms: 5000 })
        const asked = rows()
        runEnds()
        console.log('---BERICHT---' + JSON.stringify({
          asked, after: rows(), log: platzhalter.werkzeuge.map((w) => w.aufruf_id),
        }))
        """
    )
    assert report["asked"] == [
        {"id": "c1", "entries": 1, "name": "read_file"},
        {"id": "c2", "entries": 1, "name": "run_command"},
    ]
    assert report["after"] == [{"id": "c1", "entries": 1, "name": "read_file"}]
    assert report["log"] == ["c1"]


def test_the_other_written_rows_stop_counting_when_a_permission_is_asked():
    """The question says the round's stream has ended, whether or not its
    own call was reported while it was written."""
    report = _play(
        """
        writing(1, 'write_file', 80)
        handle({ typ: 'tool_confirm', aufruf_id: 'c1', name: 'run_command', argumente: {}, zeitpunkt_ms: 5000 })
        console.log('---BERICHT---' + JSON.stringify({ rows: rows() }))
        """
    )
    assert report["rows"] == [{"name": "write_file", "written": None}]


def test_a_question_to_the_user_takes_the_row_it_was_written_in():
    """`ask_user` has no start event of its own: its question is the
    complete call."""
    report = _play(
        """
        writing(0, 'ask_user', 25)
        handle({ typ: 'user_ask', aufruf_id: 'q1', frage: 'Which one?', optionen: [], zeitpunkt_ms: 5000 })
        console.log('---BERICHT---' + JSON.stringify({ rows: rows() }))
        """
    )
    assert report["rows"] == [{"id": "q1", "entries": 1, "name": "ask_user"}]


def test_a_row_left_over_from_a_cut_round_goes_when_the_model_goes_on():
    """A round cut short answers only the call it was cut at. The rows of
    the calls written before it never begin; they go as soon as the model
    writes a call, thinks or writes text again, not only when the run ends —
    and not before: while the round's calls still run, a written row waits
    for its turn."""
    report = _play(
        """
        writing(0, 'read_file', 30)
        writing(1, 'write_file', 80)
        complete('c2', 'write_file')
        const cut = rows()
        writing(0, 'list_dir', 5)
        const nextCall = rows()
        complete('c3', 'list_dir')
        writing(0, 'read_file', 30)
        writing(1, 'write_file', 80)
        complete('c5', 'write_file')
        modelGoesOn()
        console.log('---BERICHT---' + JSON.stringify({ cut, nextCall, nextText: rows() }))
        """
    )
    assert report["cut"] == [
        {"name": "read_file", "written": None},
        {"id": "c2", "entries": 1, "name": "write_file"},
    ]
    assert report["nextCall"] == [
        {"id": "c2", "entries": 1, "name": "write_file"},
        {"name": "list_dir", "written": 5},
    ]
    assert report["nextText"] == [
        {"id": "c2", "entries": 1, "name": "write_file"},
        {"id": "c3", "entries": 1, "name": "list_dir"},
        {"id": "c5", "entries": 1, "name": "write_file"},
    ]
    # Thinking and text are the two other signs that the model goes on.
    app = APP.read_text(encoding="utf-8")
    assert "if (ereignis.typ === 'reasoning' || ereignis.typ === 'content') modelGoesOn()" in app


def test_the_answer_draws_the_written_call_as_a_running_tool_row():
    """Read off the answer's component: a section still being written is
    drawn from its name and count as a call without a result — the running
    row's dot — and says the notice's own sentence, no new text; the count
    stands in figures of one width. A bundle names the call being written
    instead of calling it running."""
    message = MESSAGE.read_text(encoding="utf-8")
    assert "? { ...a, werkzeug: unbegunCall(a.writing) }" in message
    unbegun_call = _cut(message, "  function unbegunCall(writing) {", "\n  }\n")
    for field in ("name: writing.name", "written: writing.written", "unbegun: true", "ergebnis: null"):
        assert field in unbegun_call, field
    snippet = _cut(message, "{#snippet beingWritten(werkzeug)}", "{/snippet}")
    assert "textPieces('werkzeug.schreibt', { name: werkzeug.name, zeichen: werkzeug.written })" in snippet
    assert '<span class="werkzeugname">{piece.wert}</span>' in snippet
    assert '<span class="wz-count">{piece.wert}</span>' in snippet
    row = _cut(message, "{#snippet werkzeugEintrag(teil, i, imBuendel)}", "{/snippet}")
    assert "{#if teil.werkzeug.written != null}\n        {@render beingWritten(teil.werkzeug)}" in row
    # Nothing to unfold before the call has begun.
    assert "disabled={teil.werkzeug.unbegun}" in row
    assert "{#if offeneTeile.has(i) && !teil.werkzeug.unbegun}" in row
    count = _cut(message, "  .werkzeug-kopf .wz-count {", "}")
    assert "font-variant-numeric: tabular-nums" in count
    assert "font-family: var(--schrift-fest)" in count
    bundle = _cut(message, "{#if eintrag.art === 'buendel'}", "{#if offen}")
    assert "laufenderAufruf(eintrag.eintraege.filter(({ teil }) => !teil.werkzeug?.unbegun))" in bundle
    assert "{#if written}\n                {@render beingWritten(written)}" in bundle
    # The sentence is the one the notice over the input says, in both languages.
    for language in ("de", "en"):
        catalogue = json.loads((WURZEL / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))
        sentence = catalogue["werkzeug"]["schreibt"]
        assert "{name}" in sentence and "{zeichen}" in sentence, sentence
