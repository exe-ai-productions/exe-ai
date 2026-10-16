"""Pictures the user took out of a run are not pictures that "were not
generated" (a cross on a waiting one, the stop on the one drawing).

Runs saved before the studio stood apart from the chats carry the count on
their row (``stats["abgenommen"]``); the shortfall line under the pictures
reads the row and leaves them out. A picture that really failed still counts.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "frontend" / "src" / "App.svelte"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


# --- The line under the pictures reads it ---------------------------------------


def _function(name: str) -> str:
    """The source of one function of App.svelte, cut by its own braces."""
    source = APP.read_text(encoding="utf-8")
    start = source.index(f"function {name}(")
    depth = 0
    for index in range(source.index("{", start), len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"no end of {name}")


def _shortfall(rows: list[dict], row: int = -1) -> dict | None:
    """What `teilausfall` answers for ``rows[row]`` once the run is over."""
    script = (
        _function("teilausfall")
        + """
const laufKennung = (n) => n.lauf_id ?? null
const bildDateien = (n) => (n.bilder || []).filter(Boolean)
const rows = JSON.parse(process.argv[1])
const r = teilausfall(rows[Number(process.argv[2]) < 0 ? rows.length - 1 : Number(process.argv[2])], null, rows)
console.log(JSON.stringify(r))
"""
    )
    done = subprocess.run(
        ["node", "-e", script, json.dumps(rows), str(row)],
        capture_output=True, text=True, timeout=60, check=True,
    )
    return json.loads(done.stdout)


def _run_row(bilder: list, **stats) -> dict:
    return {"lauf_id": "lauf-a", "bilder": bilder, "stats": {"von": 4, **stats}}


@needs_node
def test_two_pictures_taken_out_are_not_two_that_were_not_generated():
    row = _run_row(["a.png", "b.png", None, None], abgenommen=2)

    assert _shortfall([row]) is None


@needs_node
def test_a_stop_and_a_cross_together_leave_no_shortfall():
    row = _run_row(["a.png", None, "c.png", None], abgenommen=2)

    assert _shortfall([row]) is None


@needs_node
def test_silence_a_picture_that_really_failed_still_counts():
    # Four asked for, two drawn, one taken out: one failed.
    row = _run_row(["a.png", "b.png", None, None], abgenommen=1)

    assert _shortfall([row]) == {"gescheitert": 1, "von": 4}
    # Without any taking out, the line is what it always was.
    assert _shortfall([_run_row(["a.png", "b.png", None, None])]) == {"gescheitert": 2, "von": 4}


@needs_node
def test_silence_a_run_without_an_intervention_shows_nothing():
    assert _shortfall([_run_row(["a.png", "b.png", "c.png", "d.png"])]) is None
