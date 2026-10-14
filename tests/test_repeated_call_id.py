"""A server that gives its calls no ids of its own numbers every round from
zero, so one id stands for several calls. While the answer runs, each result
goes to the oldest call of its id that still waits for one, and each row shows
its own entry — the way a stored answer's rows do after the chat is opened
again (`frontend/src/App.svelte`, the `tool_result` branch of the stream;
`frontend/src/teile/Nachricht.svelte`, the running list of rows).

Both are lifted out of the files by their real text and run in node.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.test_hausregeln import _node, _stueck
from tests.test_result_without_announced_call import _script

MESSAGE = Path(__file__).resolve().parent.parent / "frontend/src/teile/Nachricht.svelte"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")


def _rows(cases: str) -> dict:
    block = _stueck(
        MESSAGE,
        r"      if \(live\) \{\n.*?\n          \.filter\(\(a\) => a\.art !== 'werkzeug' \|\| a\.werkzeug\)\n      \}\n",
        "the running list of rows",
    )
    return _node(f"""
const unbegunCall = (writing) => ({{ name: writing.name, written: writing.written, unbegun: true, ergebnis: null }})
const rowsOf = (eigene, werkzeuge) => {{
  const live = true
{block}
}}
const section = (id) => ({{ art: 'werkzeug', aufruf_id: id }})
const entry = (id, name, ergebnis = null) => ({{ aufruf_id: id, name, ergebnis }})
const results = {{}}
{cases}
console.log(JSON.stringify(results))
""")


@needs_node
def test_two_results_of_the_same_call_id_go_to_two_entries_in_order():
    got = _node(_script("""
{
  const m = make()
  // Two rounds, a call each, the server's id for both: `aufruf_0`.
  m.platzhalter.werkzeuge.push(call('aufruf_0', 'read_file'))
  m.platzhalter.abschnitte.push(section('aufruf_0'))
  m.platzhalter.werkzeuge.push(call('aufruf_0', 'list_dir'))
  m.platzhalter.abschnitte.push(section('aufruf_0'))
  m.handle({ typ: 'tool_result', aufruf_id: 'aufruf_0', name: 'read_file', text: 'first',
             fehlgeschlagen: false, zeitpunkt_ms: 5 })
  results.after_first = m.platzhalter.werkzeuge.map((w) => [w.name, w.ergebnis])
  m.handle({ typ: 'tool_result', aufruf_id: 'aufruf_0', name: 'list_dir', text: 'second',
             fehlgeschlagen: true, zeitpunkt_ms: 6 })
  results.after_second = m.platzhalter.werkzeuge.map((w) => [w.name, w.ergebnis, w.fehlgeschlagen])
  results.rows = m.platzhalter.abschnitte.length
}
"""))
    assert got["after_first"] == [["read_file", "first"], ["list_dir", None]]
    assert got["after_second"] == [["read_file", "first", False], ["list_dir", "second", True]]
    assert got["rows"] == 2


@needs_node
def test_an_entry_with_its_result_is_never_written_over():
    got = _node(_script("""
{
  const m = make()
  m.platzhalter.werkzeuge.push({ ...call('aufruf_0', 'read_file'), ergebnis: 'kept' })
  m.platzhalter.abschnitte.push(section('aufruf_0'))
  // A result of that id with no call left waiting for it: its own entry, as
  // for any result the service never announced a call for.
  m.handle({ typ: 'tool_result', aufruf_id: 'aufruf_0', name: 'ask_user', text: 'refused',
             fehlgeschlagen: true, zeitpunkt_ms: 5 })
  results.entries = m.platzhalter.werkzeuge.map((w) => [w.name, w.ergebnis])
  results.rows = m.platzhalter.abschnitte.length
}
{
  // Silence probe: a result of another id fills its own entry as before.
  const m = make()
  m.platzhalter.werkzeuge.push(call('a', 'read_file'))
  m.platzhalter.abschnitte.push(section('a'))
  m.platzhalter.werkzeuge.push(call('b', 'write_file'))
  m.platzhalter.abschnitte.push(section('b'))
  m.handle({ typ: 'tool_result', aufruf_id: 'b', name: 'write_file', text: 'done',
             fehlgeschlagen: false, zeitpunkt_ms: 5 })
  results.other_id = m.platzhalter.werkzeuge.map((w) => [w.aufruf_id, w.ergebnis])
}
"""))
    assert got["entries"] == [["read_file", "kept"], ["ask_user", "refused"]]
    assert got["rows"] == 2
    assert got["other_id"] == [["a", None], ["b", "done"]]


@needs_node
def test_the_running_answer_gives_rows_of_one_id_their_own_entries():
    got = _rows("""
{
  const a = entry('aufruf_0', 'read_file', 'first')
  const b = entry('aufruf_0', 'list_dir')
  const rows = rowsOf([section('aufruf_0'), section('aufruf_0')], [a, b])
  results.same_id = rows.map((r) => [r.werkzeug.name, r.werkzeug.ergebnis])
}
{
  // Silence probes: other ids map as before, a row whose entry is missing
  // draws nothing, a row being written keeps its own entry, and text and
  // thinking between rows stand where they stood.
  const a = entry('x', 'read_file', 'one')
  const b = entry('y', 'list_dir', 'two')
  const eigene = [
    section('y'),
    { art: 'content', text: 'between' },
    section('x'),
    section('missing'),
    { art: 'werkzeug', aufruf_id: null, writing: { name: 'run_command', written: 12 } },
  ]
  const rows = rowsOf(eigene, [a, b])
  results.others = rows.map((r) => r.art === 'content' ? r.text : [r.werkzeug.name, r.werkzeug.unbegun ?? false])
}
""")
    assert got["same_id"] == [["read_file", "first"], ["list_dir", None]]
    assert got["others"] == [["list_dir", False], "between", ["read_file", False], ["run_command", True]]


@needs_node
def test_only_the_call_without_a_result_shows_the_waiting_dot():
    block = _stueck(
        MESSAGE,
        r"  function werkzeugPunkt\(werkzeug, stand\) \{\n.*?\n  \}\n",
        "the dot of a tool call",
    )
    got = _node(f"""
const wartetAufNutzer = (id) => id === 'aufruf_0'
const punktPulsiert = () => false
const punktAtmet = () => false
const terminal = {{ laeufe: [] }}
const laufampel = () => 'gruen'
{block}
const done = {{ aufruf_id: 'aufruf_0', ergebnis: 'first', fehlgeschlagen: false }}
const asked = {{ aufruf_id: 'aufruf_0', ergebnis: null, fehlgeschlagen: false }}
const other = {{ aufruf_id: 'aufruf_1', ergebnis: null, fehlgeschlagen: false }}
console.log(JSON.stringify({{
  done: werkzeugPunkt(done, null).farbe,
  asked: werkzeugPunkt(asked, null).farbe,
  other: werkzeugPunkt(other, null).farbe,
}}))
""")
    assert got == {"done": "gruen", "asked": "gelb", "other": "blau"}
