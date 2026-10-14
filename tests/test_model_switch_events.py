"""The two switches of the model choice (`modelle_aus`, `katalog_wahl`) go
out over the line when they are written, and a window reads them again.

Service side: a write that was stored — PUT or PATCH — announces the key,
once; a refused write, a read and a write of any other key announce nothing.
Window side (frontend/src/lib/modelle.svelte.js, run in node): a load that
fails leaves what stands, the newest load wins, and a load that may have read
a switch before it was stored does not take it back.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
MODULE = FRONTEND / "src" / "lib" / "modelle.svelte.js"


@pytest.fixture
def announced():
    """The keys of every MODEL_SWITCHES_CHANGED the bus carries while the
    test runs."""
    from app.events import Ereignisse, bus

    seen: list[str] = []

    def collect(schluessel: str = "", **_rest) -> None:
        seen.append(schluessel)

    bus.abonnieren(Ereignisse.MODEL_SWITCHES_CHANGED, collect)
    yield seen
    bus.abbestellen(Ereignisse.MODEL_SWITCHES_CHANGED, collect)


def _arrived(seen: list[str], count: int, timeout: float = 5.0) -> list[str]:
    deadline = time.monotonic() + timeout
    while len(seen) < count and time.monotonic() < deadline:
        time.sleep(0.01)
    return list(seen)


def test_a_stored_put_and_a_stored_patch_are_announced_once_each(client, announced):
    put = client.put("/api/v1/settings/global/modelle_aus", json={"wert": ["lokal/ein-modell"]})
    assert put.status_code == 200
    assert _arrived(announced, 1) == ["modelle_aus"]

    patch = client.patch("/api/v1/settings/global/katalog_wahl", json={"wert": {"openai": ["gpt-x"]}})
    assert patch.status_code == 200
    assert _arrived(announced, 2) == ["modelle_aus", "katalog_wahl"]
    time.sleep(0.2)
    assert announced == ["modelle_aus", "katalog_wahl"]


def test_a_write_of_another_key_a_read_and_a_refused_write_say_nothing(client, announced):
    """Silence: the line carries these two keys and nothing else. The probe
    at the end is a real announcement; everything before it would have
    arrived before it."""
    assert client.get("/api/v1/settings/global/modelle_aus").status_code == 200
    assert client.put("/api/v1/settings/global/unbekannt_xyz", json={"wert": 1}).status_code == 400
    # A list is no set of values for PATCH: refused, nothing stored.
    assert client.patch("/api/v1/settings/global/modelle_aus", json={"wert": ["x"]}).status_code == 400
    assert client.put("/api/v1/settings/global/modelle_aus", json={"wert": []}).status_code == 200
    got = _arrived(announced, 1)
    assert got == ["modelle_aus"]


# --- the window --------------------------------------------------------------

pytestmark_node = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)

API_STUB = """
export const calls = []
function held(kind, args) {
  let resolve, reject
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail })
  calls.push({ kind, args, resolve, reject })
  return promise
}
export const api = {
  einstellungAufgeloest: (key) => held('read', [key]),
  einstellungSetzen: (...args) => held('write', args),
}
"""

STATE_STUB = """
export const zustand = { modelle: [], modellId: '' }
export const aktuellesModell = () => null
"""


@contextmanager
def _workdir():
    folder = FRONTEND / "node_modules" / f".pruefstand-modellwahl-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _run(scenario: str):
    with _workdir() as folder:
        (folder / "api.mjs").write_text(API_STUB, encoding="utf-8")
        (folder / "zustand.mjs").write_text(STATE_STUB, encoding="utf-8")
        driver = folder / "driver.mjs"
        driver.write_text(
            textwrap.dedent(
                """
                import { compileModule } from 'svelte/compiler'
                import { readFileSync, writeFileSync } from 'fs'
                const source = readFileSync(%r, 'utf-8')
                const built = compileModule(source, {
                  filename: 'modelle.svelte.js', generate: 'client',
                })
                writeFileSync('./built.mjs', built.js.code
                  .replace("'./api.js'", "'./api.mjs'")
                  .replace("'./zustand.svelte.js'", "'./zustand.mjs'"))
                const m = await import('./built.mjs')
                const stub = await import('./api.mjs')
                const report = (value) =>
                  console.log('---REPORT---' + JSON.stringify(value))
                // The two reads of one load: the first answers `off`, the second `pick`.
                function answerLoad(first, { off = [], pick = {} } = {}) {
                  stub.calls[first].resolve({ wert: off })
                  stub.calls[first + 1].resolve({ wert: pick })
                }
                """
            )
            % str(MODULE)
            + scenario,
            encoding="utf-8",
        )
        result = subprocess.run(
            ["node", driver.name], cwd=folder, capture_output=True, text=True, timeout=120
        )
    assert result.returncode == 0, (result.stdout + result.stderr)[-2000:]
    mark = "---REPORT---"
    assert mark in result.stdout, result.stdout[-2000:]
    return json.loads(result.stdout.split(mark, 1)[1].strip())


@pytestmark_node
def test_a_failed_load_leaves_what_stands_and_a_good_one_replaces_it():
    result = _run(
        """
        let done = m.auswahlLaden()
        answerLoad(0, { off: ['a'], pick: { openai: ['gpt'] } })
        await done
        done = m.auswahlLaden()
        stub.calls[2].reject(new Error('down'))
        stub.calls[3].reject(new Error('down'))
        await done
        const afterFailure = { off: [...m.modellwahl.aus], pick: m.modellwahl.gewaehlt }
        done = m.auswahlLaden()
        answerLoad(4, { off: ['b'], pick: {} })
        await done
        report({ afterFailure, off: [...m.modellwahl.aus], loaded: m.modellwahl.geladen })
        """
    )
    assert result == {
        "afterFailure": {"off": ["a"], "pick": {"openai": ["gpt"]}},
        "off": ["b"],
        "loaded": True,
    }


@pytestmark_node
def test_an_older_load_answering_late_does_not_overwrite_a_newer_one():
    result = _run(
        """
        const older = m.auswahlLaden()
        const newer = m.auswahlLaden()
        answerLoad(2, { off: ['new'] })
        await newer
        answerLoad(0, { off: ['old'] })
        await older
        report({ off: [...m.modellwahl.aus] })
        """
    )
    assert result == {"off": ["new"]}


@pytestmark_node
def test_a_switch_flipped_during_a_load_is_not_put_back():
    """The load read `modelle_aus` before the switch was stored; its answer
    would switch the model back on under the hand that had just switched it
    off."""
    result = _run(
        """
        const load = m.auswahlLaden()
        const flip = m.schalten('lokal/x', false)
        stub.calls.find((c) => c.kind === 'write').resolve({})
        await flip
        answerLoad(0, { off: [] })
        await load
        report({ off: [...m.modellwahl.aus] })
        """
    )
    assert result == {"off": ["lokal/x"]}


def test_the_windows_read_at_every_opening_and_on_the_line():
    teile = FRONTEND / "src" / "teile"
    for name in ("ModelleLokal.svelte", "ModelleCloud.svelte"):
        source = (teile / name).read_text(encoding="utf-8")
        assert "if (!offen) return\n    auswahlLaden()" in source, name
        assert "if (!modellwahl.geladen) auswahlLaden()" not in source, name
    picker = (teile / "Modellwahl.svelte").read_text(encoding="utf-8")
    assert "if (open || !modellwahl.geladen) auswahlLaden()" in picker
    line = (FRONTEND / "src" / "lib" / "ereignisstrom.svelte.js").read_text(encoding="utf-8")
    assert "model_switches_changed: () => {\n    auswahlLaden()\n  }," in line
    assert "      modelleLaden()\n      auswahlLaden()" in line
