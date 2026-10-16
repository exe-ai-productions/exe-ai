"""The chat list's status dots cost one pass per change, not one per row.

Every row of the chat list asks ``ringFarbe`` for its own chat. That used to
search the chat list, two id lists and the whole job list for each row, so a
list of two thousand chats read reactive arrays millions of times whenever a
chat was added or a run started — the page stood still for seconds before the
first request of a new chat could leave.

The two modules run for real in node, compiled with Svelte's own compiler
(they use runes); only the state container and the few modules around the job
list are stand-ins. The colours are the shipped rule's, so the first tests
pin what a row says; the last one pins what it costs.
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

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)

STAND_INS = {
    "zustand.mjs": """
import { proxy } from 'svelte/internal/client'
export const zustand = proxy({
  chats: [], laeuft: {}, fertigeChats: [], auftraege: [],
  werkzeugfrage: {}, benutzerfrage: {}, jobfrage: {},
})
export const melde = () => {}
export const auftraegeStillLaden = async () => {}
""",
    "api.mjs": "export const api = {}\n",
    "arbeitsleiste.mjs": (
        "export const anbieten = () => {}\n"
        "export const leiste = { offen: false, modul: '' }\n"
        "export const moduleShow = async () => {}\n"
    ),
    "texte.mjs": "export const t = (key) => key\n",
}


@contextmanager
def _harness_folder():
    """A folder of this call's own under ``frontend/node_modules``: node
    resolves the compiler and the runtime by walking up from the importing
    file, and an ignored folder cannot leave a stray file in the tree."""
    folder = FRONTEND / "node_modules" / f".harness-chatrings-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _run(scenario: str) -> dict:
    """Compile both modules, run `scenario` (a function body with `ring`,
    `agent`, `zustand`, `fehlerChats` in scope), return what it returns."""
    with _harness_folder() as folder:
        for name, source in STAND_INS.items():
            (folder / name).write_text(source, encoding="utf-8")
        (folder / "harness.mjs").write_text(
            textwrap.dedent(
                """
                import { compileModule } from 'svelte/compiler'
                import { readFileSync, writeFileSync } from 'fs'
                const build = (source, name, target) => {
                  const built = compileModule(readFileSync(source, 'utf-8'),
                    { filename: name, generate: 'client' })
                  writeFileSync(target, built.js.code
                    .replaceAll('./zustand.svelte.js', './zustand.mjs')
                    .replaceAll('./api.js', './api.mjs')
                    .replaceAll('./arbeitsleiste.svelte.js', './arbeitsleiste.mjs')
                    .replaceAll('./texte.svelte.js', './texte.mjs')
                    .replaceAll('./agentchat.svelte.js', './agent.mjs')
                    .replaceAll('./ringfarbe.js', %r))
                }
                build(%r, 'agentchat.svelte.js', 'agent.mjs')
                build(%r, 'chatringe.svelte.js', 'ring.mjs')
                const ring = await import('./ring.mjs')
                const agent = await import('./agent.mjs')
                const { zustand } = await import('./zustand.mjs')
                const { fehlerChats } = ring
                const scenario = async () => { %s }
                console.log('---BERICHT---' + JSON.stringify(await scenario()))
                """
            )
            % (
                (LIB / "ringfarbe.js").as_uri(),
                str(LIB / "agentchat.svelte.js"),
                str(LIB / "chatringe.svelte.js"),
                scenario,
            ),
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


def test_every_state_of_a_row_keeps_its_colour():
    colours = _run(
        """
        zustand.chats = [
          { id: 'a', laeuft: false }, { id: 'b', laeuft: true },
          { id: 'c', laeuft: false }, { id: 'd', laeuft: false },
          { id: 'e', laeuft: false }, { id: 'f', laeuft: false },
        ]
        zustand.fertigeChats = ['d']
        fehlerChats.liste = ['c']
        zustand.benutzerfrage = { e: { frage: 'q' } }
        zustand.auftraege = [
          { id: 'j1', chat_id: 'f', state: 'wartet', question: { frage: 'q?', aufruf_id: 'x' } },
          { id: 'j2', chat_id: 'a', state: 'laeuft' },
        ]
        const ids = ['a', 'b', 'c', 'd', 'e', 'f', 'g']
        return Object.fromEntries(ids.map((id) => [id, ring.ringFarbe(id)]))
        """
    )
    assert colours == {
        "a": "leer",  # a job that runs but asks nothing lights nothing
        "b": "blau",  # the list says a run is going here
        "c": "rot",  # a run failed and nobody looked
        "d": "gruen",  # an answer finished and nobody looked
        "e": "gelb",  # the chat's own question
        "f": "gelb",  # an agent of this chat waits on the user
        "g": "leer",  # a chat the list does not know
    }


def test_a_row_follows_the_lists_when_they_change():
    """Silence probe for the sets: they are rebuilt, not frozen."""
    history = _run(
        """
        zustand.chats = [{ id: 'a', laeuft: false }, { id: 'b', laeuft: false }]
        const before = [ring.ringFarbe('a'), ring.ringFarbe('b')]
        zustand.chats = [{ id: 'a', laeuft: true }, { id: 'b', laeuft: false }]
        zustand.fertigeChats = ['b']
        fehlerChats.liste = []
        const after = [ring.ringFarbe('a'), ring.ringFarbe('b')]
        zustand.auftraege = [{ id: 'j', chat_id: 'b', state: 'wartet', question: { frage: 'q?', aufruf_id: 'x' } }]
        const withQuestion = [ring.ringFarbe('a'), ring.ringFarbe('b')]
        zustand.auftraege = []
        return { before, after, withQuestion, without: ring.ringFarbe('b') }
        """
    )
    assert history == {
        "before": ["leer", "leer"],
        "after": ["blau", "gruen"],
        "withQuestion": ["blau", "gelb"],
        "without": "gruen",
    }


def test_an_answered_question_of_an_agent_stops_lighting_its_chat():
    colours = _run(
        """
        zustand.chats = [{ id: 'a', laeuft: false }]
        zustand.auftraege = [{ id: 'j', chat_id: 'a', state: 'wartet', question: { frage: 'q?', aufruf_id: 'x' } }]
        const offen = ring.ringFarbe('a')
        zustand.auftraege = [{ id: 'j', chat_id: 'a', state: 'laeuft', question: { frage: 'q?', aufruf_id: 'x' } }]
        return { offen, answered: ring.ringFarbe('a'), agentAsks: agent.agentAsks('a') }
        """
    )
    assert colours == {"offen": "gelb", "answered": "leer", "agentAsks": False}


def test_two_thousand_rows_cost_one_pass_of_each_list_per_change():
    """The failure it pins: with 2000 chats and 2000 jobs every row searched
    the chat list and the job list itself, and a change of the list ran all
    of that again for every row. Each change must now cost a pass of each
    list, whatever the number of rows."""
    report = _run(
        """
        const n = 2000
        const ids = Array.from({ length: n }, (_, i) => 'chat' + i)
        zustand.chats = ids.map((id, i) => ({ id, laeuft: i % 50 === 0 }))
        zustand.fertigeChats = ids.filter((_, i) => i % 7 === 0)
        fehlerChats.liste = ids.filter((_, i) => i % 11 === 0)
        zustand.auftraege = ids.map((id, i) => ({
          id: 'job' + i, chat_id: id, state: i % 13 === 0 ? 'wartet' : 'beendet',
          question: i % 13 === 0 ? { frage: 'q?', aufruf_id: 'c' + i } : null,
          created_at: '2026-10-15T00:00:' + String(i % 60).padStart(2, '0'),
        }))
        const all = () => ids.map((id) => ring.ringFarbe(id))
        all()
        // a chat is added: the whole list is a new value and every row asks again
        const t0 = performance.now()
        for (let round = 0; round < 3; round++) {
          zustand.chats = [...zustand.chats, { id: 'new' + round, laeuft: false }]
          all()
        }
        const ms = Math.round((performance.now() - t0) / 3)
        const tally = all().reduce((m, f) => ((m[f] = (m[f] || 0) + 1), m), {})
        return { ms, tally }
        """
    )
    assert sum(report["tally"].values()) == 2000
    # What the rows say stays what the rule says: 154 asked (every 13th, the
    # question beats everything), 40 running, the rest by fault and finish.
    assert report["tally"]["gelb"] == 154
    # Per change: about 150 ms for one pass of each list and the 2000 reads;
    # the old form needed about a second here and seconds more in the page,
    # where the rows read reactive proxies on top.
    assert report["ms"] < 600, report
