"""The tool list of the settings page, executed rather than read.

Two things are measured here, both in frontend/src/lib/werkzeuge.svelte.js:

* Loading. The list used to be fetched once per session — a server added or
  switched off under Connections was missing under Tools until the program
  reloaded. It is now fetched every time the settings open and every time
  the tools section is shown. Loading that often means two loads can be on
  the way at once, and a load can be on the way while a switch is flipped:
  the newest load wins, and a load that may have read the setting before a
  switch was stored leaves the switch alone.
* The selection of the tools view. A source and a tool used to share one
  plain text as their key: a server called "fetch" with a tool called
  "fetch" opened the wrong one, and two servers offering a tool of the same
  name always opened the first server's. The selection now carries its kind
  and, for a tool, the source row it was opened from.

The module is compiled with Svelte's own compiler and run in node, the way
tests/test_agentenampel.py runs its module. Only the HTTP client and the
server title lookup are stubbed; the HTTP calls are held open by the test so
the order in which answers arrive is the test's to choose.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
MODULE = FRONTEND / "src" / "lib" / "werkzeuge.svelte.js"
NAMES = FRONTEND / "src" / "lib" / "mcpWerkzeuge.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)

# Every HTTP call of the module is answered by hand: `calls` holds each one
# with its kind and the resolver of its promise.
API_STUB = """
export const calls = []
function held(kind, args) {
  let resolve, reject
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail })
  calls.push({ kind, args, resolve, reject })
  return promise
}
export const api = {
  werkzeuge: () => held('tools'),
  serverUebersicht: () => held('servers'),
  einstellungAufgeloest: (key) => held('setting', [key]),
  einstellungSetzen: (...args) => held('set', args),
  serverSchreiben: (...args) => held('write', args),
}
"""

CATALOGUE_STUB = "export function serverTitel(name) { return name }\n"

# Shared by every scenario: answer the three calls of one load.
HELPERS = """
const tick = () => new Promise((r) => setTimeout(r, 0))
function answerLoad(first, { tools = [], servers = [], off = [] }) {
  const three = stub.calls.slice(first, first + 3)
  for (const call of three) {
    if (call.kind === 'tools') call.resolve({ werkzeuge: tools })
    if (call.kind === 'servers') call.resolve(servers)
    if (call.kind === 'setting') call.resolve({ wert: off })
  }
}
function server(name, tools, extra = {}) {
  return {
    name, laeuft: true, enabled: true, allowed_tools: null,
    alle_werkzeuge: tools.map((t) => ({ name: t, beschreibung: '' })), ...extra,
  }
}
"""


@contextmanager
def _workdir():
    """A folder of this run's own under frontend/node_modules, so node finds
    svelte/compiler by walking up and an aborted run leaves nothing in the
    working tree."""
    folder = FRONTEND / "node_modules" / f".pruefstand-toollist-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _run(scenario: str):
    """Compile the module, run `scenario` with `m` (the module) and `stub`
    (the HTTP stub) in scope, and return what it passes to `report`."""
    with _workdir() as folder:
        (folder / "api.mjs").write_text(API_STUB, encoding="utf-8")
        (folder / "katalog.mjs").write_text(CATALOGUE_STUB, encoding="utf-8")
        # The name helper the module imports, as it ships.
        (folder / "mcp.mjs").write_text(NAMES.read_text(encoding="utf-8"), encoding="utf-8")
        driver = folder / "driver.mjs"
        driver.write_text(
            textwrap.dedent(
                """
                import { compileModule } from 'svelte/compiler'
                import { readFileSync, writeFileSync } from 'fs'
                const source = readFileSync(%r, 'utf-8')
                const built = compileModule(source, {
                  filename: 'werkzeuge.svelte.js', generate: 'client',
                })
                writeFileSync('./built.mjs', built.js.code
                  .replace("'./api.js'", "'./api.mjs'")
                  .replace("'./serverkatalog.js'", "'./katalog.mjs'")
                  .replace("'./mcpWerkzeuge.js'", "'./mcp.mjs'"))
                const m = await import('./built.mjs')
                const stub = await import('./api.mjs')
                const report = (value) =>
                  console.log('---REPORT---' + JSON.stringify(value))
                """
            )
            % str(MODULE)
            + HELPERS
            + scenario,
            encoding="utf-8",
        )
        result = subprocess.run(
            ["node", driver.name],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=120,
        )
    assert result.returncode == 0, (result.stdout + result.stderr)[-2000:]
    mark = "---REPORT---"
    assert mark in result.stdout, result.stdout[-2000:]
    return json.loads(result.stdout.split(mark, 1)[1].strip())


# --- Loading ---------------------------------------------------------------


def test_every_load_fetches_again_and_shows_a_new_server():
    """Silence probe of the counter: one load after another, nothing in
    between — each lands in full, and the second shows the server that came
    up in the meantime."""
    result = _run(
        """
        let done = m.werkzeugeLaden()
        answerLoad(0, { servers: [server('fetch', ['fetch'])], off: ['a'] })
        await done
        done = m.werkzeugeLaden()
        answerLoad(3, {
          servers: [server('fetch', ['fetch']), server('time', ['now'])],
          off: ['b'],
        })
        await done
        report({
          servers: m.werkzeugwahl.server.map((s) => s.name),
          off: m.werkzeugwahl.aus,
          calls: stub.calls.length,
        })
        """
    )
    assert result == {"servers": ["fetch", "time"], "off": ["b"], "calls": 6}


def test_an_older_load_answering_late_does_not_overwrite_a_newer_one():
    """Settings opened with the tools section showing start two loads. The
    first one's answer arriving last must not put the older list back."""
    result = _run(
        """
        const older = m.werkzeugeLaden()
        const newer = m.werkzeugeLaden()
        answerLoad(3, { servers: [server('time', ['now'])], off: ['new'] })
        await newer
        answerLoad(0, { servers: [], off: ['old'] })
        await older
        report({ servers: m.werkzeugwahl.server.map((s) => s.name), off: m.werkzeugwahl.aus })
        """
    )
    assert result == {"servers": ["time"], "off": ["new"]}


def test_a_switch_flipped_during_a_load_is_not_put_back():
    """The race that kept the list from reloading at all: the load read the
    setting before the switch was stored, and its answer switched the tool
    back on under the hand that had just switched it off. The rest of the
    load — a new server — still arrives."""
    result = _run(
        """
        const load = m.werkzeugeLaden()
        const flip = m.schalten('fetch', false)
        stub.calls.find((c) => c.kind === 'set').resolve({})
        await flip
        answerLoad(0, { servers: [server('time', ['now'])], off: [] })
        await load
        report({ servers: m.werkzeugwahl.server.map((s) => s.name), off: m.werkzeugwahl.aus })
        """
    )
    assert result == {"servers": ["time"], "off": ["fetch"]}


def test_a_switch_still_being_stored_when_a_load_answers_is_kept():
    """The other half of the same race: the load starts while the switch is
    on its way to the server, and answers before it is stored."""
    result = _run(
        """
        const flip = m.schalten('fetch', false)
        await tick()
        const load = m.werkzeugeLaden()
        answerLoad(1, { off: [] })
        await load
        const during = [...m.werkzeugwahl.aus]
        stub.calls.find((c) => c.kind === 'set').resolve({})
        await flip
        report({ during, after: m.werkzeugwahl.aus })
        """
    )
    assert result == {"during": ["fetch"], "after": ["fetch"]}


def test_a_load_started_after_the_switch_was_stored_writes_the_setting():
    """Silence probe of the switch guard: once the switch is stored, the
    next load takes the setting as the server reports it."""
    result = _run(
        """
        const flip = m.schalten('fetch', false)
        stub.calls.find((c) => c.kind === 'set').resolve({})
        await flip
        const load = m.werkzeugeLaden()
        answerLoad(1, { off: ['other'] })
        await load
        report(m.werkzeugwahl.aus)
        """
    )
    assert result == ["other"]


def test_the_once_per_session_gate_is_gone():
    """Where the loads are started is markup, not module logic: the settings
    page loads on every opening, the tools section on every mount."""
    page = (FRONTEND / "src" / "teile" / "SystemPrompt.svelte").read_text(encoding="utf-8")
    view = (FRONTEND / "src" / "teile" / "Werkzeuge.svelte").read_text(encoding="utf-8")
    module = MODULE.read_text(encoding="utf-8")
    assert "geladen" not in module
    assert "werkzeugwahl.geladen" not in page
    assert "    werkzeugeLaden()\n" in page
    assert "onMount(() => {\n    werkzeugeLaden()\n  })" in view


# --- The selection ---------------------------------------------------------

SELECTION = """
answerLoad(0, {
  tools: [
    { name: 'get_current_time', server: 'clock', builtin: true },
    { name: 'fetch', server: 'fetch', builtin: false },
  ],
  servers: [
    server('clock', ['now']),
    server('fetch', ['fetch']),
    server('mirror', ['fetch']),
  ],
})
await loading
const list = m.quellen()
const show = (selection) => {
  const r = m.auswahlAufloesen(list, selection)
  return {
    tool: r.werkzeug ? r.werkzeug.name : null,
    source: r.quelle ? r.quelle.id : null,
  }
}
"""


def _selection(cases: str):
    return _run("const loading = m.werkzeugeLaden()\n" + SELECTION + cases)


def test_a_server_and_its_tool_of_the_same_name_are_told_apart():
    result = _selection(
        """
        report({
          source: show({ art: 'quelle', id: 'mcp:fetch' }),
          tool: show({ art: 'werkzeug', name: 'mcp__fetch__fetch', quelle: 'mcp:fetch' }),
        })
        """
    )
    assert result == {
        "source": {"tool": None, "source": "mcp:fetch"},
        "tool": {"tool": "mcp__fetch__fetch", "source": "mcp:fetch"},
    }


def test_two_servers_with_a_tool_of_the_same_name_each_open_their_own():
    result = _selection(
        """
        report([
          show({ art: 'werkzeug', name: 'mcp__fetch__fetch', quelle: 'mcp:fetch' }),
          show({ art: 'werkzeug', name: 'mcp__mirror__fetch', quelle: 'mcp:mirror' }),
        ])
        """
    )
    assert result == [
        {"tool": "mcp__fetch__fetch", "source": "mcp:fetch"},
        {"tool": "mcp__mirror__fetch", "source": "mcp:mirror"},
    ]


def test_a_built_in_source_and_a_server_of_the_same_name_stay_apart():
    result = _selection(
        """
        report([
          show({ art: 'quelle', id: 'builtin:clock' }),
          show({ art: 'quelle', id: 'mcp:clock' }),
          show({ art: 'werkzeug', name: 'get_current_time', quelle: 'builtin:clock' }),
          show({ art: 'werkzeug', name: 'mcp__clock__now', quelle: 'mcp:clock' }),
        ])
        """
    )
    assert result == [
        {"tool": None, "source": "builtin:clock"},
        {"tool": None, "source": "mcp:clock"},
        {"tool": "get_current_time", "source": "builtin:clock"},
        {"tool": "mcp__clock__now", "source": "mcp:clock"},
    ]


def test_a_selection_that_no_longer_exists_falls_back_to_the_first_source():
    """Silence probe: nothing selected, a source gone, a tool gone, or a tool
    asked for in a source that does not offer it — the first source, never
    some other source's tool of the same name."""
    result = _selection(
        """
        report([
          show(null),
          show({ art: 'quelle', id: 'mcp:gone' }),
          show({ art: 'werkzeug', name: 'gone', quelle: 'mcp:fetch' }),
          show({ art: 'werkzeug', name: 'now', quelle: 'mcp:fetch' }),
        ])
        """
    )
    first = {"tool": None, "source": "builtin:clock"}
    assert result == [first, first, first, first]
