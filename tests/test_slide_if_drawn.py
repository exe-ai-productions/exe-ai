"""A row that comes or goes inside a sheet nobody sees must not be animated
(`frontend/src/lib/slideIfDrawn.js`, used by the chat list in
`frontend/src/teile/Seitenleiste.svelte`).

`slide` reads the height of the node it moves. In a sheet that is not drawn
the height is not a number, and the console fills with "Invalid keyframe
value for property height: NaNpx". The module is run in Node against stand-in
nodes; the sidebar is read as source."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
BAR = FRONTEND / "src" / "teile" / "Seitenleiste.svelte"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)


def _run(js: str) -> dict:
    driver = FRONTEND / f"slide-if-drawn-{uuid4().hex}.mjs"
    driver.write_text(
        textwrap.dedent(
            """
            import { slideIfDrawn } from './src/lib/slideIfDrawn.js'
            // What `slide` reads off a drawn node: every measure a number.
            globalThis.getComputedStyle = () => new Proxy({}, {
              get: (_, name) => (name === 'display' ? 'block' : name === 'opacity' ? '1' : '24px'),
            })
            const drawn = { getClientRects: () => [{ width: 10, height: 24 }] }
            const hidden = { getClientRects: () => [] }
            const report = (() => {
            %s
            })()
            console.log('---REPORT---' + JSON.stringify(report))
            """
        )
        % textwrap.indent(js, "  "),
        encoding="utf-8",
    )
    try:
        run = subprocess.run(
            ["node", driver.name], cwd=FRONTEND, capture_output=True, text=True, timeout=120
        )
    finally:
        driver.unlink(missing_ok=True)
    assert run.returncode == 0, (run.stdout + run.stderr)[-2000:]
    assert "---REPORT---" in run.stdout, run.stdout[-2000:]
    return json.loads(run.stdout.split("---REPORT---", 1)[1].strip())


@needs_node
def test_a_row_in_a_sheet_that_is_not_drawn_has_no_animation():
    report = _run(
        """
        const config = slideIfDrawn(hidden, { duration: 160 })
        return { duration: config.duration, css: typeof config.css }
        """
    )
    assert report == {"duration": 0, "css": "undefined"}


@needs_node
def test_a_drawn_row_slides_as_it_did():
    """Silence probe: the same call for a node with a box is `slide` itself —
    its own duration, and keyframes made of numbers only."""
    report = _run(
        """
        const config = slideIfDrawn(drawn, { duration: 160 })
        const frame = config.css(0.5, 0.5)
        return { duration: config.duration, hasCss: typeof config.css, nan: frame.includes('NaN') }
        """
    )
    assert report == {"duration": 160, "hasCss": "function", "nan": False}


def test_the_chat_list_moves_its_rows_with_it_and_with_nothing_else():
    bar = BAR.read_text(encoding="utf-8")
    assert "import { slideIfDrawn } from '../lib/slideIfDrawn.js'" in bar
    assert "transition:slide=" not in bar
    assert "transition:slideIfDrawn=" in bar
