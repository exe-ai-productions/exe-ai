"""The cloud window lists every provider that was created, reachable or not.

A provider whose key is missing or refused, or whose server is switched off,
answers no model list, so the chat's list (``zustand.modelle``, the service's
answer without ``alle``) never named it. The cloud window read that list and
showed nothing for it: no state, no way to take it away, and its name stayed
taken for a new provider. The window now reads the full list instead; the
chat's own choice keeps reading only what answers.

The module runs for real in node, compiled with Svelte's own compiler (it
uses runes); only the state container and the service's answers are
stand-ins.
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
LIB = FRONTEND / "src" / "lib"
CLOUD_WINDOW = FRONTEND / "src" / "teile" / "ModelleCloud.svelte"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)

STAND_INS = {
    "zustand.mjs": """
import { proxy } from 'svelte/internal/client'
export const zustand = proxy({ modelle: [], modellId: '' })
export const aktuellesModell = () => null
""",
    # `globalThis.answer` is what the service says to `/models?alle=true`;
    # `globalThis.failure` makes the read fail.
    "api.mjs": """
export const api = {
  modelleAlle: async () => {
    if (globalThis.failure) throw new Error('service away')
    return globalThis.answer
  },
  einstellungAufgeloest: async () => null,
}
""",
}


@contextmanager
def _harness_folder():
    """A folder of this call's own under ``frontend/node_modules``: node
    resolves the compiler and the runtime by walking up from the importing
    file, and an ignored folder cannot leave a stray file in the tree."""
    folder = FRONTEND / "node_modules" / f".harness-cloudwindow-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _run(scenario: str) -> dict:
    """Compile the module, run `scenario` (a function body with `modelle`
    and `zustand` in scope), return what it returns."""
    with _harness_folder() as folder:
        for name, source in STAND_INS.items():
            (folder / name).write_text(source, encoding="utf-8")
        (folder / "harness.mjs").write_text(
            textwrap.dedent(
                """
                import { compileModule } from 'svelte/compiler'
                import { readFileSync, writeFileSync } from 'fs'
                const built = compileModule(readFileSync(%r, 'utf-8'),
                  { filename: 'modelle.svelte.js', generate: 'client' })
                writeFileSync('modelle.mjs', built.js.code
                  .replaceAll('./zustand.svelte.js', './zustand.mjs')
                  .replaceAll('./api.js', './api.mjs'))
                const modelle = await import('./modelle.mjs')
                const { zustand } = await import('./zustand.mjs')
                const scenario = async () => { %s }
                console.log('---BERICHT---' + JSON.stringify(await scenario()))
                """
            )
            % (str(LIB / "modelle.svelte.js"), scenario),
            encoding="utf-8",
        )
        outcome = subprocess.run(
            ["node", "harness.mjs"],
            cwd=folder,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
        )
    assert outcome.returncode == 0, (outcome.stdout + outcome.stderr)[-2000:]
    marker = "---BERICHT---"
    assert marker in outcome.stdout, outcome.stdout[-2000:]
    return json.loads(outcome.stdout.split(marker, 1)[1].strip())


# A reachable provider with two catalogue models, and one whose key was
# refused: that one answers no list, so the service names it once, by itself.
_BEFORE = """
const answers = (modell) => ({
  id: 'good/' + modell, name: modell, anbieter: 'good', anbieter_name: 'Good',
  group: 'cloud', erreichbar: true, modell, angeheftet: true,
  capabilities: {}, context_tokens: null, timeout_enabled: true,
})
const good = [answers('m1'), answers('m2')]
const broken = {
  id: 'broken', name: 'broken', anbieter: 'broken', anbieter_name: 'Broken',
  group: 'cloud', erreichbar: false, capabilities: {}, context_tokens: null,
  timeout_enabled: true,
}
zustand.modelle = good
globalThis.answer = [...good, broken]
"""


def test_an_unreachable_provider_stands_in_the_cloud_windows_list():
    seen = _run(
        _BEFORE
        + """
        await modelle.alleAnbieterLaden()
        return { ids: modelle.anbieterAlle().map((h) => [h.id, h.erreichbar]) }
        """
    )
    assert seen["ids"] == [["good", True], ["broken", False]]


def test_the_chats_choice_does_not_get_the_unreachable_provider():
    """Silence: loading the full list writes nothing into the chat's list,
    and the models offered there stay the reachable ones."""
    seen = _run(
        _BEFORE
        + """
        const before = zustand.modelle
        await modelle.alleAnbieterLaden()
        return {
          same: zustand.modelle === before,
          ids: zustand.modelle.map((m) => m.id),
          anbieter: modelle.anbieter().map((h) => h.id),
          visible: modelle.sichtbare().map((m) => m.id),
        }
        """
    )
    assert seen["same"] is True
    assert seen["ids"] == ["good/m1", "good/m2"]
    assert seen["anbieter"] == ["good"]
    assert seen["visible"] == ["good/m1", "good/m2"]


def test_a_reachable_provider_stands_exactly_once():
    """Silence: the full list names a catalogue provider once per model, and
    the window still shows one house with its picked models."""
    seen = _run(
        _BEFORE
        + """
        await modelle.alleAnbieterLaden()
        const houses = modelle.anbieterAlle()
        const hits = houses.filter((h) => h.id === 'good')
        return { houses: hits.length, modelle: hits[0].modelle.map((m) => m.id) }
        """
    )
    assert seen == {"houses": 1, "modelle": ["good/m1", "good/m2"]}


def test_a_read_that_failed_leaves_the_list_as_it_was():
    seen = _run(
        _BEFORE
        + """
        await modelle.alleAnbieterLaden()
        globalThis.failure = true
        await modelle.alleAnbieterLaden()
        return modelle.anbieterAlle().map((h) => h.id)
        """
    )
    assert seen == ["good", "broken"]


def test_before_the_full_list_has_come_the_reachable_ones_stand_in():
    """Silence: the window opens with what the chat's list holds, not with
    the notice that no provider exists."""
    seen = _run(
        _BEFORE
        + """
        const earlier = modelle.anbieterAlle().map((h) => h.id)
        await modelle.alleAnbieterLaden()
        return { earlier, later: modelle.anbieterAlle().map((h) => h.id) }
        """
    )
    assert seen == {"earlier": ["good"], "later": ["good", "broken"]}


def test_a_removed_provider_leaves_the_list_with_the_next_read():
    seen = _run(
        _BEFORE
        + """
        await modelle.alleAnbieterLaden()
        globalThis.answer = [...good]
        await modelle.alleAnbieterLaden()
        return modelle.anbieterAlle().map((h) => h.id)
        """
    )
    assert seen == ["good"]


def test_the_cloud_window_reads_the_full_list():
    """The component asks the module for the full list and reads it anew
    whenever the chat's list was read anew."""
    source = CLOUD_WINDOW.read_text(encoding="utf-8")
    assert "const haeuser = $derived(anbieterAlle())" in source
    assert "alleAnbieterLaden()" in source
    assert "$derived(anbieter())" not in source
