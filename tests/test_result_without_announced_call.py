"""A result for a call the service never announced stands live as it stands
after the chat is opened again: its own entry and its own row, at its place
in the answer (`frontend/src/App.svelte`, the `tool_result` branch of the
stream). The same branch reports a call that failed, but not one the person
stopped.

The branch and the helper that appends a row are lifted out of the file by
their real text and run in node with everything around them stubbed.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from tests.test_hausregeln import _node, _stueck

APP = Path(__file__).resolve().parent.parent / "frontend/src/App.svelte"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")


def _script(cases: str) -> str:
    rows = "".join(
        _stueck(APP, pattern, name)
        for pattern, name in (
            (r"    const werkzeugAnhaengen = \(aufrufId, zeitpunktMs\) => \{.*?\n    \}\n", "werkzeugAnhaengen"),
            (r"    let rowsWaiting = false\n", "rowsWaiting"),
            (r"    const writtenRow = \(aufrufId, name\) => \{.*?\n    \}\n", "writtenRow"),
            (r"    const rowOfCall = \(aufrufId, name, zeitpunktMs\) => \{.*?\n    \}\n", "rowOfCall"),
        )
    )
    branch = _stueck(
        APP,
        r"(?<=        \} else if \(ereignis\.typ === 'tool_result'\) \{\n).*?"
        r"(?=\n        \} else if \(ereignis\.typ === 'ziel'\) \{)",
        "the tool_result branch",
    )
    return f"""
const make = () => {{
  const platzhalter = {{ werkzeuge: [], abschnitte: [] }}
  const log = {{ abgenommen: [], zeichnen: [], said: [], closed: [] }}
  const zustand = {{ werkzeugfrage: {{}}, benutzerfrage: {{}}, jobfrage: {{}} }}
  const zielChat = 'A'
  const WERKZEUG_FEHLER_MS = 5000
  let werkzeugOffen = true
  let drawing = false
  const werkzeugFertigDauer = () => 1500
  const werkzeugSagen = (...args) => log.said.push(args[0])
  const werkzeugMeldungen = new Map([['werkzeug:A', 'standing']])
  const werkzeugToast = 'werkzeug:A'
  const schliesseMeldung = (m) => {{ log.closed.push(m); werkzeugMeldungen.delete(werkzeugToast) }}
  const sharedByModel = () => {{}}
  const taetigkeitSetzen = () => {{}}
  const isDrawingTool = () => false
  const drawingDone = () => {{}}
  const frageAbnehmen = (id) => log.abgenommen.push(id)
  {rows}
  const handle = (ereignis) => {{
{branch}
  }}
  return {{ platzhalter, handle, log }}
}}
const call = (id, name) => ({{ aufruf_id: id, name, server: '', argumente: {{ a: 1 }}, ergebnis: null, fehlgeschlagen: false }})
const section = (id) => ({{ art: 'werkzeug', aufruf_id: id, seit: 1 }})
const results = {{}}
{cases}
console.log(JSON.stringify(results))
"""


@needs_node
def test_a_result_without_an_announced_call_gets_its_own_entry_and_row():
    got = _node(_script("""
{
  const m = make()
  // An earlier call that was announced and has its result already.
  m.platzhalter.werkzeuge.push({ ...call('c1', 'read_file'), ergebnis: 'fine' })
  m.platzhalter.abschnitte.push(section('c1'))
  m.handle({ typ: 'tool_result', aufruf_id: 'q9', name: 'ask_user', text: 'refused: no question',
             fehlgeschlagen: true, dauer_sekunden: 0.2, zeitpunkt_ms: 5 })
  results.refused = {
    entries: m.platzhalter.werkzeuge.map((w) => [w.aufruf_id, w.name, w.ergebnis, w.fehlgeschlagen, w.dauer_sekunden ?? null]),
    rows: m.platzhalter.abschnitte.map((a) => [a.art, a.aufruf_id]),
    abgenommen: m.log.abgenommen,
  }
}
"""))
    assert got["refused"]["entries"] == [
        ["c1", "read_file", "fine", False, None],
        ["q9", "ask_user", "refused: no question", True, 0.2],
    ]
    # The row stands behind the one before it: the place of the result.
    assert got["refused"]["rows"] == [["werkzeug", "c1"], ["werkzeug", "q9"]]
    # The question card of that call comes down, as it did before.
    assert got["refused"]["abgenommen"] == ["q9"]


@needs_node
def test_a_result_takes_over_the_row_the_call_was_written_in():
    got = _node(_script("""
{
  const m = make()
  // The model began to write the call: a row without a call id yet.
  m.platzhalter.abschnitte.push({ art: 'werkzeug', aufruf_id: null, writing: { index: 0, name: 'ask_user', written: 0 }, seit: 1 })
  m.handle({ typ: 'tool_result', aufruf_id: 'q9', name: 'ask_user', text: 'refused',
             fehlgeschlagen: true, zeitpunkt_ms: 5 })
  results.taken = {
    rows: m.platzhalter.abschnitte.map((a) => [a.aufruf_id, 'writing' in a]),
    entries: m.platzhalter.werkzeuge.map((w) => [w.aufruf_id, w.ergebnis]),
  }
}
"""))
    # One row, no second: the written row is the call's row now.
    assert got["taken"] == {"rows": [["q9", False]], "entries": [["q9", "refused"]]}


@needs_node
def test_a_result_of_an_announced_call_makes_no_second_entry():
    got = _node(_script("""
{
  const m = make()
  m.platzhalter.werkzeuge.push(call('c1', 'read_file'))
  m.platzhalter.abschnitte.push(section('c1'))
  m.handle({ typ: 'tool_result', aufruf_id: 'c1', name: 'read_file', text: 'the text',
             fehlgeschlagen: false, dauer_sekunden: 1.5, zeitpunkt_ms: 5 })
  results.announced = {
    entries: m.platzhalter.werkzeuge.map((w) => [w.aufruf_id, w.ergebnis, w.dauer_sekunden ?? null]),
    rows: m.platzhalter.abschnitte.length,
  }
}
{
  // Silence probe: the result of a job a call started still lands in its row.
  const m = make()
  m.platzhalter.werkzeuge.push(call('j1', 'start_job'))
  m.platzhalter.abschnitte.push(section('j1'))
  m.handle({ typ: 'tool_result', aufruf_id: 'j1', name: 'start_job', text: 'started',
             fehlgeschlagen: false, auftrag_id: 'job-7', lauf_nummer: 3, zeitpunkt_ms: 5 })
  const w = m.platzhalter.werkzeuge[0]
  results.job = { entries: m.platzhalter.werkzeuge.length, auftrag: w.auftrag_id, lauf: w.lauf_nummer }
}
"""))
    assert got["announced"] == {"entries": [["c1", "the text", 1.5]], "rows": 1}
    assert got["job"] == {"entries": 1, "auftrag": "job-7", "lauf": 3}


def test_the_branch_is_the_one_the_stream_runs():
    """The lifted text is the real branch: it still writes the fields the
    row reads, from the event."""
    branch = _stueck(
        APP,
        r"(?<=        \} else if \(ereignis\.typ === 'tool_result'\) \{\n).*?"
        r"(?=\n        \} else if \(ereignis\.typ === 'ziel'\) \{)",
        "the tool_result branch",
    )
    for field in ("eintrag.ergebnis = ereignis.text", "eintrag.fehlgeschlagen = ereignis.fehlgeschlagen"):
        assert field in branch
    assert re.search(r"rowOfCall\(ereignis\.aufruf_id, ereignis\.name, ereignis\.zeitpunkt_ms\)", branch)


@needs_node
def test_a_stop_by_the_person_during_a_question_reports_no_failure():
    got = _node(_script("""
{
  const m = make()
  m.platzhalter.werkzeuge.push(call('q1', 'ask_user'))
  m.platzhalter.abschnitte.push(section('q1'))
  m.handle({ typ: 'tool_result', aufruf_id: 'q1', name: 'ask_user', text: 'stopped',
             fehlgeschlagen: true, stopped: true, dauer_sekunden: 3, zeitpunkt_ms: 5 })
  results.stopped = {
    said: m.log.said, closed: m.log.closed,
    row: m.platzhalter.werkzeuge.map((w) => [w.ergebnis, w.fehlgeschlagen]),
  }
}
{
  // Silence probes: a call that really failed reports red, an answered one
  // reports done, as before.
  const failed = make()
  failed.platzhalter.werkzeuge.push(call('c1', 'read_file'))
  failed.platzhalter.abschnitte.push(section('c1'))
  failed.handle({ typ: 'tool_result', aufruf_id: 'c1', name: 'read_file', text: 'no such file',
                  fehlgeschlagen: true, zeitpunkt_ms: 5 })
  const answered = make()
  answered.platzhalter.werkzeuge.push(call('q2', 'ask_user'))
  answered.platzhalter.abschnitte.push(section('q2'))
  answered.handle({ typ: 'tool_result', aufruf_id: 'q2', name: 'ask_user', text: 'Left',
                    fehlgeschlagen: false, zeitpunkt_ms: 5 })
  results.failed = { said: failed.log.said, closed: failed.log.closed }
  results.answered = { said: answered.log.said, closed: answered.log.closed }
}
"""))
    # No notice of a failure, the standing notice goes, the row keeps its
    # failed result.
    assert got["stopped"] == {"said": [], "closed": ["standing"], "row": [["stopped", True]]}
    assert got["failed"] == {"said": ["werkzeug.fehlgeschlagen"], "closed": []}
    assert got["answered"] == {"said": ["werkzeug.fertig"], "closed": []}
