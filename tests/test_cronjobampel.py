"""The cronjobs dot on the rail, executed rather than read: blue while an
entry of the cron list is firing a run.

It matches the running runs on the entry that fired each of them
(``cronjob_id``), not on the piece of work they belong to (``work_id``).
The two came apart once a run somebody started by hand became the
origin of its own restart chain, so its continuation's work is a run id —
while the row that fired the continuation is a chain entry standing in the
cron list. Matched on the work, the dot would stay dark next to it.

The module is compiled with Svelte's own compiler and run in node, the way
tests/test_agentenampel.py runs the agents dot. Only the two modules it
imports are stubbed — the service call and the state container.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

# Borrowed rather than copied: the folder under node_modules is where node
# resolves the Svelte runtime the compiled module pulls in.
from tests.test_agentenampel import _pruefordner

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"
MODUL = FRONTEND / "src" / "lib" / "cronjobampel.svelte.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)


def _farbe(jobs: list[dict], termine: list[dict]) -> str:
    """Compile the dot module, hand it `jobs` and the cron list `termine`,
    and return the colour it decides on. The watermark is set to now, so no
    entry's last outcome counts as news and only "firing" can colour it."""
    with _pruefordner() as ordner:
        treiber = ordner / "pruefung.mjs"
        gebaut = ordner / "gebaut.mjs"
        (ordner / "zustand.mjs").write_text(
            "export const zustand = { auftraege: [] }\n", encoding="utf-8"
        )
        (ordner / "api.mjs").write_text("export const api = {}\n", encoding="utf-8")
        treiber.write_text(
            textwrap.dedent(
                """
                import { compileModule } from 'svelte/compiler'
                import { readFileSync, writeFileSync } from 'fs'
                const quelle = readFileSync(%r, 'utf-8')
                const gebaut = compileModule(quelle, {
                  filename: 'cronjobampel.svelte.js', generate: 'client',
                })
                writeFileSync(%r, gebaut.js.code
                  .replace('./zustand.svelte.js', './zustand.mjs')
                  .replace('./api.js', './api.mjs'))
                const a = await import('./gebaut.mjs')
                const { zustand } = await import('./zustand.mjs')
                zustand.auftraege = %s
                a.cronampel.liste = %s
                a.cronampel.gesehen = Date.now()
                console.log('---BERICHT---' + JSON.stringify(a.punktfarbe()))
                """
            )
            % (str(MODUL), str(gebaut), json.dumps(jobs), json.dumps(termine)),
            encoding="utf-8",
        )
        ergebnis = subprocess.run(
            ["node", treiber.name],
            cwd=ordner,
            capture_output=True,
            text=True,
            timeout=120,
        )
    assert ergebnis.returncode == 0, (ergebnis.stdout + ergebnis.stderr)[-2000:]
    marke = "---BERICHT---"
    assert marke in ergebnis.stdout, ergebnis.stdout[-2000:]
    return json.loads(ergebnis.stdout.split(marke, 1)[1].strip())


def _termin(kennung: str) -> dict:
    return {"id": kennung, "letzter_ausgang": None, "zuletzt_ausgeloest": None}


def test_die_fortsetzung_eines_handstarts_leuchtet_blau():
    """The case that moved: the continuation's work is the run a person
    started, its entry is the chain row in the list."""
    jobs = [{"id": "lauf-2", "state": "laeuft", "work_id": "lauf-1", "cronjob_id": "kette-1"}]
    assert _farbe(jobs, [_termin("kette-1")]) == "blau"


def test_ein_lauf_eines_termins_leuchtet_blau():
    """Unchanged for an entry a person made: it fires the run itself."""
    jobs = [{"id": "lauf-3", "state": "laeuft", "work_id": "termin-1", "cronjob_id": "termin-1"}]
    assert _farbe(jobs, [_termin("termin-1")]) == "blau"


def test_ein_handstart_leuchtet_nicht():
    """The silence probe: a run started by hand names no entry, and the
    list's entries fire nothing."""
    jobs = [{"id": "lauf-4", "state": "laeuft", "work_id": "lauf-4", "cronjob_id": None}]
    assert _farbe(jobs, [_termin("termin-1")]) == "still"


def test_ein_beendeter_lauf_eines_termins_leuchtet_nicht():
    """Only a run still going is firing."""
    jobs = [{"id": "lauf-5", "state": "fertig", "work_id": "termin-1", "cronjob_id": "termin-1"}]
    assert _farbe(jobs, [_termin("termin-1")]) == "still"
