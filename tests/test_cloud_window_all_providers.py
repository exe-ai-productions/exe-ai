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
export const aktuellesModell = () => globalThis.current ?? null
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
  // What the module stores: [scope, key, value], read back by a scenario.
  einstellungSetzen: async (...call) => { (globalThis.saved ??= []).push(call) },
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


# --- One state for a cloud model ---------------------------------------------------
#
# A cloud model out of a catalogue is on when it is ticked in its catalogue and
# off when it is not; the quick picker's "off" list says nothing about it. A
# provider's single model has no catalogue to tick in, and keeps the "off"
# list; so does a local model.

_CLOUD = """
const catalogued = (name) => ({
  id: 'cloud/' + name, name, anbieter: 'cloud', anbieter_name: 'Cloud',
  group: 'cloud', erreichbar: true, modell: name,
  capabilities: {}, context_tokens: null, timeout_enabled: true,
})
const single = {
  id: 'homelab', name: 'homelab-model', anbieter: 'homelab', anbieter_name: 'Homelab',
  group: 'cloud', erreichbar: true, capabilities: {}, context_tokens: null,
  timeout_enabled: true,
}
const local = {
  id: 'local-a', name: 'local-a', anbieter: 'omlx', group: 'local',
  erreichbar: true, capabilities: {}, context_tokens: null,
}
zustand.modelle = [catalogued('m1'), catalogued('m2'), single, local]
globalThis.answer = zustand.modelle
// m1 is ticked; the old "off" list still names it, and names a local model.
modelle.modellwahl.gewaehlt = { cloud: ['m1'] }
modelle.modellwahl.aus = ['cloud/m1', 'local-a']
"""


def test_a_ticked_cloud_model_is_on_whatever_the_old_off_list_says():
    seen = _run(
        _CLOUD
        + """
        globalThis.current = true
        const modelWord = (id) => { zustand.modellId = id; return modelle.chosenModelOff() }
        return {
          ticked: modelle.istAn('cloud/m1'),
          unticked: modelle.istAn('cloud/m2'),
          chatOffTicked: modelWord('cloud/m1'),
          chatOffUnticked: modelWord('cloud/m2'),
          visible: modelle.sichtbare().map((m) => m.id),
        }
        """
    )
    assert seen == {
        "ticked": True,
        "unticked": False,
        "chatOffTicked": False,
        "chatOffUnticked": True,
        "visible": ["cloud/m1", "homelab"],
    }


def test_unticking_in_the_catalogue_is_switching_the_model_off():
    seen = _run(
        _CLOUD
        + """
        const m1 = zustand.modelle[0]
        await modelle.katalogSchalten(m1, false)
        return { on: modelle.istAn('cloud/m1'), off: [...modelle.modellwahl.aus] }
        """
    )
    assert seen["on"] is False
    # The picker's "off" list is not touched by a cloud model's tick.
    assert seen["off"] == ["cloud/m1", "local-a"]


def test_the_switch_of_a_cloud_model_is_its_tick_and_writes_the_pick_only():
    seen = _run(
        _CLOUD
        + """
        await modelle.schalten('cloud/m2', true)
        const after = { m2: modelle.istAn('cloud/m2'), picked: modelle.modellwahl.gewaehlt.cloud }
        await modelle.schalten('cloud/m1', false)
        return {
          ...after,
          m1: modelle.istAn('cloud/m1'),
          off: [...modelle.modellwahl.aus],
          keys: globalThis.saved.map((call) => call[1]),
        }
        """
    )
    assert seen["m2"] is True
    assert seen["picked"] == ["m1", "m2"]
    assert seen["m1"] is False
    assert seen["off"] == ["cloud/m1", "local-a"]
    assert seen["keys"] == ["katalog_wahl", "katalog_wahl"]


def test_silence_a_local_model_keeps_the_off_list():
    seen = _run(
        _CLOUD
        + """
        const before = modelle.istAn('local-a')
        await modelle.schalten('local-a', true)
        return {
          before, after: modelle.istAn('local-a'),
          off: [...modelle.modellwahl.aus],
          keys: globalThis.saved.map((call) => call[1]),
        }
        """
    )
    assert seen == {"before": False, "after": True, "off": ["cloud/m1"], "keys": ["modelle_aus"]}


def test_a_providers_single_model_unticked_leaves_the_provider_standing():
    seen = _run(
        _CLOUD
        + """
        await modelle.alleAnbieterLaden()
        await modelle.schalten('homelab', false)
        const house = modelle.anbieterAlle().find((h) => h.id === 'homelab')
        const off = {
          on: modelle.istAn('homelab'),
          kept: house?.modelle.map((m) => m.id),
          visible: modelle.sichtbare().map((m) => m.id),
          off: [...modelle.modellwahl.aus],
        }
        await modelle.schalten('homelab', true)
        return { ...off, back: modelle.istAn('homelab') }
        """
    )
    assert seen["on"] is False
    # The provider and its model stand; only the model choice lost it.
    assert seen["kept"] == ["homelab"]
    assert "homelab" not in seen["visible"]
    assert "homelab" in seen["off"]
    assert seen["back"] is True
