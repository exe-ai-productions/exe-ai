"""The agent server's models are on the model list for the runs and the
agent mask, but the chat does not offer them and does not take one of its
own accord.

Window side, run in node: the chat's choice (`sichtbare`), the model taken
when none is chosen or the chosen server is gone (`modelleLaden`), and the
quick picker's groups (source). The same file of weights under the model
server and under the agent server shows once.
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

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
LIB = FRONTEND / "src" / "lib"
TEILE = FRONTEND / "src" / "teile"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)

LOCAL = {"group": "local", "name": "klein.gguf"}


@contextmanager
def _workdir():
    folder = FRONTEND / "node_modules" / f".pruefstand-chatwahl-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _node(folder: Path, script: str):
    driver = folder / "driver.mjs"
    driver.write_text(script, encoding="utf-8")
    result = subprocess.run(
        ["node", driver.name], cwd=folder, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def _picker(models: list[dict]):
    """`sichtbare()` of the real module over a list of models."""
    with _workdir() as folder:
        (folder / "api.mjs").write_text("export const api = {}\n", encoding="utf-8")
        (folder / "zustand.mjs").write_text(
            f"export const zustand = {{ modelle: {json.dumps(models)}, modellId: '' }}\n"
            "export const aktuellesModell = () => null\n",
            encoding="utf-8",
        )
        script = textwrap.dedent(
            """
            import { compileModule } from 'svelte/compiler'
            import { readFileSync, writeFileSync } from 'fs'
            const built = compileModule(readFileSync(%r, 'utf-8'), {
              filename: 'modelle.svelte.js', generate: 'client',
            })
            writeFileSync('./built.mjs', built.js.code
              .replace("'./api.js'", "'./api.mjs'")
              .replace("'./zustand.svelte.js'", "'./zustand.mjs'"))
            const m = await import('./built.mjs')
            console.log(JSON.stringify(m.sichtbare().map((x) => x.id)))
            """
        ) % str(LIB / "modelle.svelte.js")
        return _node(folder, script)


@needs_node
def test_the_same_file_under_both_servers_is_offered_once():
    models = [
        {"id": "agentenmodell", "anbieter": "agentenmodell", **LOCAL},
        {"id": "runner", "anbieter": "runner", **LOCAL},
    ]
    assert _picker(models) == ["runner"]


@needs_node
def test_models_of_the_model_server_and_the_cloud_stay_in_the_choice():
    """Silence probe: nothing else leaves the list."""
    models = [
        {"id": "runner", "anbieter": "runner", **LOCAL},
        {"id": "provider-a", "anbieter": "provider-a", "group": "cloud", "name": "Provider Model 35B"},
    ]
    assert _picker(models) == ["runner", "provider-a"]


def _loader(chosen: str, listed: list[dict], everything: list[dict] | None = None):
    """`modelleLaden` of the real source, with the window's neighbours
    stubbed: returns the models the chat was made to choose, in order."""
    state = (LIB / "zustand.svelte.js").read_text(encoding="utf-8")

    def piece(pattern: str, name: str) -> str:
        found = re.search(pattern, state, re.S)
        assert found, f"{name} not found"
        return found.group(0).strip() + "\n"

    parts = "\n".join([
        piece(r"\nconst AGENT_SERVER_ID = '[^']+'\n", "AGENT_SERVER_ID"),
        piece(r"\nfunction firstChatModel\(list\) \{\n.*?\n\}\n", "firstChatModel"),
        piece(r"\nfunction providerOf\(modelId\) \{\n.*?\n\}\n", "providerOf"),
        piece(r"\nlet modelLoadRun = 0\n", "modelLoadRun"),
        piece(r"\nexport async function modelleLaden\(frisch = false\) \{\n.*?\n\}\n", "modelleLaden"),
    ]).replace("export async function", "async function")
    with _workdir() as folder:
        script = f"""
const picked = []
const zustand = {{ modellId: {json.dumps(chosen)}, modelle: [], unlistedModel: null }}
const api = {{
  modelle: async () => {json.dumps(listed)},
  modelleAlle: async () => {json.dumps(everything if everything is not None else [])},
}}
const aktuellesModell = () => null
const modellWaehlen = (id) => {{ picked.push(id); zustand.modellId = id }}
const keptModelName = () => ''
const storedModelId = async () => zustand.modellId
const modellSpeichern = () => {{}}
{parts}
await modelleLaden()
console.log(JSON.stringify(picked))
"""
        return _node(folder, script)


AGENT = {"id": "agentenmodell", "anbieter": "agentenmodell", **LOCAL}
RUNNER = {"id": "runner", "anbieter": "runner", **LOCAL}


@needs_node
def test_with_no_choice_the_first_model_is_not_one_of_the_agent_server():
    assert _loader("", [AGENT, RUNNER]) == ["runner"]


@needs_node
def test_with_no_choice_and_only_the_agent_server_nothing_is_taken():
    assert _loader("", [AGENT]) == []


@needs_node
def test_a_chosen_server_that_is_gone_gives_the_first_model_of_the_choice():
    assert _loader("weg", [AGENT, RUNNER], everything=[]) == ["runner"]


@needs_node
def test_a_model_that_is_chosen_and_listed_stays_chosen():
    """Silence probe: nothing is taken of the window's own accord."""
    assert _loader("runner", [AGENT, RUNNER]) == []


def test_a_chat_that_carries_a_model_of_the_agent_server_takes_the_first_of_the_choice():
    state = (LIB / "zustand.svelte.js").read_text(encoding="utf-8")
    assert "if (carried && carried.anbieter !== AGENT_SERVER_ID) {" in state
    assert "const first = firstChatModel(zustand.modelle)" in state


def test_the_quick_picker_has_no_group_for_the_agent_server():
    source = (TEILE / "ModelleLokal.svelte").read_text(encoding="utf-8")
    assert "lokale().filter((m) => m.anbieter !== SLOT_ENDPUNKT)" in source
    assert "[SLOT_ENDPUNKT]: 'agentserver.titel'" not in source
    assert "[SLOT_ENDPUNKT]: 1" not in source
    # The server list still names the agent server: it is a server to set up.
    # (the list the page and the settings share).
    assert "SERVER as SERVER_PAGES" in source
    assert "titel: 'agentserver.titel'" in (LIB / "einstellungsliste.js").read_text(encoding="utf-8")


def test_the_word_for_the_agent_server_is_one_word_in_three_files():
    slot = re.search(
        r"export const SLOT_ENDPUNKT = '([^']+)'",
        (LIB / "agentenserver.svelte.js").read_text(encoding="utf-8"),
    )
    assert slot
    for name in ("modelle.svelte.js", "zustand.svelte.js"):
        local = re.search(
            r"const AGENT_SERVER_ID = '([^']+)'", (LIB / name).read_text(encoding="utf-8")
        )
        assert local and local.group(1) == slot.group(1), name
