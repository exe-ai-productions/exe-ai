"""The line of a running answer does not get shorter while the answer runs.

A second tool call folds the thinking and the calls before it into the one row
of a bundle (`lib/werkzeugbuendel.js`), and the next thinking opens again
below it: the answer fell by the height of the folded rows and grew back. The
line keeps the greatest height it has had for as long as the answer runs
(`lib/lineFloor.js`, bound to `.antwortlinie` in `teile/Nachricht.svelte`).
The pure function runs in Node; the binding is read off the source.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
MODULE = FRONTEND / "src/lib/lineFloor.js"
MESSAGE = (FRONTEND / "src/teile/Nachricht.svelte").read_text(encoding="utf-8")

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


def _floors(steps: list[tuple[bool, float]]) -> list[float]:
    """The floor after each step (does the answer run, how high is the line);
    the floor of one step is the next one's input, as the component keeps it."""
    script = f"""
import {{ lineFloor }} from {json.dumps(MODULE.as_uri())}
let floor = 0
const out = []
for (const [running, height] of {json.dumps(steps)}) {{
  floor = lineFloor(running, height, floor)
  out.push(floor)
}}
console.log(JSON.stringify(out))
"""
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    return json.loads(run.stdout.strip().splitlines()[-1])


@needs_node
def test_a_line_that_folds_into_a_bundle_keeps_the_height_it_had_while_the_answer_runs():
    """The heights measured at the second tool call: 162 px, then 82.5 px when
    the bundle folds, 132 px with the next thinking, and the text after it."""
    heights = [53, 103, 112.5, 162, 82.5, 132, 150, 178.1, 206.1]
    floors = _floors([(True, h) for h in heights])
    assert floors == [53, 103, 112.5, 162, 162, 162, 162, 178.1, 206.1]


@needs_node
def test_the_floor_goes_with_the_end_of_the_run():
    floors = _floors([(True, 120), (True, 90), (False, 90), (False, 60)])
    assert floors == [120, 120, 0, 0]


@needs_node
def test_a_new_run_starts_without_the_floor_of_the_one_before():
    """Silence probe: nothing is carried over a run that ended; a line that
    never ran keeps no floor at all."""
    floors = _floors([(True, 200), (False, 150), (True, 40), (True, 30)])
    assert floors == [200, 0, 40, 40]
    assert _floors([(False, 300), (False, 100)]) == [0, 0]


def test_the_line_of_the_answer_carries_the_floor():
    """The binding in the component: the height of `.antwortlinie` is read, the
    floor is its `min-height`, and it comes from the pure function with the
    answer's own `laeuft` — so a finished answer, which never has one, is
    drawn as before."""
    assert "import { lineFloor } from '../lib/lineFloor.js'" in MESSAGE
    assert 'class="antwortlinie" bind:offsetHeight={lineHeight}' in MESSAGE
    assert "style:min-height={floorHeight ? `${floorHeight}px` : null}" in MESSAGE
    assert "lineFloor(laeuft, lineHeight," in MESSAGE
