"""The kinds of tool the row above a task is drawn from, run rather than read.

``lib/werkzeugarten.js`` is plain JavaScript: it groups the tools an agent may
use into a handful of kinds, so the row draws each kind once with a count
instead of one mark per tool.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")

WERKZEUGE = (
    [{"name": "read_file", "server": ""}, {"name": "write_file", "server": ""}]
    + [{"name": "web_search", "server": "websuche"}, {"name": "run_command", "server": "shell"}]
    + [{"name": "create_issue", "server": "github"}, {"name": "send_message", "server": "gmail"}]
    # Unknown to the catalogue: one with a server nobody entered, one with none.
    + [{"name": "page_create", "server": "notion"}, {"name": "mystery", "server": ""}]
    + [{"name": f"zusatz_{i}", "server": "unbekannt"} for i in range(26)]
)


def _arten(werkzeuge: list[dict]) -> list[dict]:
    treiber = FRONTEND / f"arten-{os.getpid()}.pruefung.mjs"
    treiber.write_text(
        f"""
import {{ werkzeugarten }} from './src/lib/werkzeugarten.js'
console.log('---BERICHT---' + JSON.stringify(werkzeugarten({json.dumps(werkzeuge)})
  .map((a) => ({{ art: a.art, anzahl: a.anzahl }}))))
""",
        encoding="utf-8",
    )
    try:
        lauf = subprocess.run(["node", treiber.name], cwd=FRONTEND, capture_output=True, text=True, timeout=60)
    finally:
        treiber.unlink(missing_ok=True)
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-3000:]
    return json.loads(lauf.stdout.split("---BERICHT---", 1)[1].strip())


def test_vierunddreissig_werkzeuge_sind_sechs_marken_in_fester_reihenfolge():
    assert len(WERKZEUGE) == 34
    assert _arten(WERKZEUGE) == [
        {"art": "web", "anzahl": 1},
        {"art": "dateien", "anzahl": 2},
        {"art": "terminal", "anzahl": 1},
        {"art": "github", "anzahl": 1},
        {"art": "gmail", "anzahl": 1},
        # everything the catalogue does not know, in one kind of its own
        {"art": "weitere", "anzahl": 28},
    ]


def test_eine_art_ohne_werkzeug_hat_keine_marke():
    # Silence probe: no tools, no marks; and a kind nobody has is left out.
    assert _arten([]) == []
    assert [a["art"] for a in _arten([{"name": "read_file", "server": ""}])] == ["dateien"]


def test_jede_art_hat_ihren_text_in_beiden_katalogen():
    treiber = FRONTEND / f"arten-namen-{os.getpid()}.pruefung.mjs"
    treiber.write_text(
        "import { ARTEN } from './src/lib/werkzeugarten.js'\n"
        "console.log('---BERICHT---' + JSON.stringify(ARTEN.map((a) => a.art)))\n",
        encoding="utf-8",
    )
    try:
        lauf = subprocess.run(["node", treiber.name], cwd=FRONTEND, capture_output=True, text=True, timeout=60)
    finally:
        treiber.unlink(missing_ok=True)
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-3000:]
    arten = json.loads(lauf.stdout.split("---BERICHT---", 1)[1].strip())
    assert arten, "no kinds at all"
    for sprache in ("de", "en"):
        katalog = json.loads((FRONTEND.parent / f"app/locales/{sprache}.json").read_text(encoding="utf-8"))
        fehlend = [art for art in arten if f"art_{art}" not in katalog["werkzeug"]]
        assert not fehlend, f"{sprache}: no text for the kinds {fehlend}"
