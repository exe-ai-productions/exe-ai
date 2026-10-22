"""A sent message with a picture holds the room of the picture before it has
loaded: the box it stands in when the page is opened afresh is the box it has
once the picture is drawn, so the list does not jump.

`Nachricht.svelte` is built as it is shipped and drawn in headless Chrome. Three
pictures (wide, small, tall) are shown three ways: with the size named and the
file not loaded (far below the screen, where the lazy picture is not fetched), with the size named and the file loaded, and with no size
named and the file loaded (an older attachment, as before). The first two have
the same box; the third is the old behaviour and has the same box once drawn.

The room is the tile's of the grid (square, from the column), so a picture
named by size, by nothing or not yet loaded stands in the same box.

Skipped where there is no Chrome or no node, like the other browser tests.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import threading
from pathlib import Path
from uuid import uuid4

import pytest

from app import appfenster
from tests.test_phone_terminal_sheet import PAGE, VITE_CONFIG, _measure

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SRC = FRONTEND / "src"

SHELL = """<script>
  import Nachricht from %(nachricht)r
  import { scene } from './scene.svelte.js'
</script>

<div class="track" style="width: 374px; margin: 0 auto;">
  {#each scene.nachrichten as nachricht (nachricht.id)}
    <div class="row" data-id={nachricht.id}>
      <Nachricht {nachricht} istLetzte={false} istLetzteFrage={false}
                 neuErzeugen={() => {}} neuSenden={() => {}} />
    </div>
  {/each}
</div>
"""

SCENE_JS = """export const scene = $state({ nachrichten: [] })
"""

ENTRY_JS = """import { mount } from 'svelte'
import Shell from './Shell.svelte'
import { scene } from './scene.svelte.js'
import %(global)r

window.scene = scene
mount(Shell, { target: document.getElementById('root') })
"""

CASES = r"""
const { scene } = window
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const sizes = { wide: [800, 400], small: [100, 300], tall: [1000, 2000] }

const blobOf = (width, height) => new Promise((resolve) => {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  canvas.getContext('2d').fillRect(0, 0, width, height)
  canvas.toBlob((blob) => resolve(URL.createObjectURL(blob)))
})

// The room is measured on a picture that is still on its way: its name is
// not a local address, so the window asks the service for it, and the request
// is then pointed at a socket that never answers.
const rows = []
for (const [key, [width, height]] of Object.entries(sizes)) {
  const real = await blobOf(width, height)
  rows.push({ id: `${key}-room`, name: `pending-${key}.png`, sized: [width, height] })
  rows.push({ id: `${key}-loaded`, name: real, sized: [width, height] })
  rows.push({ id: `${key}-plain`, name: real, sized: null })
}
scene.nachrichten = rows.map((row) => ({
  id: row.id, role: 'user', content: 'Describe the picture', anhaenge: [row.name],
  attachment_sizes: row.sized ? { [row.name]: { width: row.sized[0], height: row.sized[1] } } : null,
}))
await wait(600)
for (const img of document.querySelectorAll('img.bildanhang')) {
  if (img.getAttribute('src').includes('/images/pending-')) img.src = '__HANG__'
}
// A picture far below the screen is not fetched (lazy): bring each near.
for (const row of rows) {
  document.querySelector(`[data-id="${row.id}"]`).scrollIntoView()
  await wait(120)
}
await wait(500)

const report = {}
for (const row of rows) {
  const holder = document.querySelector(`[data-id="${row.id}"]`)
  const img = holder.querySelector('img.bildanhang')
  const frame = holder.querySelector('.bildrahmen')
  const r = img.getBoundingClientRect()
  report[row.id] = { width: r.width, height: r.height, frame: frame.getBoundingClientRect().height, loaded: img.complete && img.naturalWidth > 0, style: img.getAttribute('style') }
}
document.getElementById('ergebnis').textContent = JSON.stringify(report)
"""


@pytest.fixture(scope="module")
def report() -> dict:
    if shutil.which("node") is None or not (FRONTEND / "node_modules" / "vite").exists():
        pytest.skip("no node or no frontend dependencies on this machine")
    program = appfenster._programm() or pytest.skip("no Chrome on this machine")
    folder = FRONTEND / "node_modules" / f".harness-attroom-{uuid4().hex}"
    folder.mkdir(parents=True)
    # A socket that takes every request and never answers: the picture it is
    # asked for stays on its way for as long as the page is measured.
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(16)
    taken: list[socket.socket] = []

    def hold() -> None:
        while True:
            try:
                taken.append(holder.accept()[0])
            except OSError:
                return

    threading.Thread(target=hold, daemon=True).start()
    try:
        (folder / "Shell.svelte").write_text(
            SHELL % {"nachricht": "../../src/teile/Nachricht.svelte"}, encoding="utf-8"
        )
        (folder / "scene.svelte.js").write_text(SCENE_JS, encoding="utf-8")
        (folder / "entry.js").write_text(
            ENTRY_JS % {"global": "../../src/stil/global.css"}, encoding="utf-8"
        )
        (folder / "vite.config.js").write_text(VITE_CONFIG, encoding="utf-8")
        built = subprocess.run(
            [shutil.which("vite", path=str(FRONTEND / "node_modules" / ".bin")), "build", "--config", "vite.config.js"],
            cwd=folder, capture_output=True, text=True, timeout=240,
        )
        assert built.returncode == 0, (built.stdout + built.stderr)[-2000:]
        cases = CASES.replace("__HANG__", f"http://127.0.0.1:{holder.getsockname()[1]}/pending.png")
        (folder / "measure.html").write_text(PAGE % {"cases": cases}, encoding="utf-8")
        raw = _measure(program, folder, (folder / "measure.html").as_uri())
        assert raw, "the page wrote no report"
        out = json.loads(raw)
        assert "failure" not in out, out["failure"]
        return out
    finally:
        holder.close()
        for connection in taken:
            connection.close()
        shutil.rmtree(folder, ignore_errors=True)


@pytest.mark.parametrize("key", ["wide", "small", "tall"])
def test_the_room_before_the_picture_loads_is_the_box_it_has_after(report, key):
    room, loaded = report[f"{key}-room"], report[f"{key}-loaded"]
    assert room["loaded"] is False and loaded["loaded"] is True, (room, loaded)
    assert abs(room["width"] - loaded["width"]) <= 1, (room, loaded)
    assert abs(room["height"] - loaded["height"]) <= 1, (room, loaded)
    assert abs(room["frame"] - loaded["frame"]) <= 1, (room, loaded)
    assert room["height"] > 20, room


@pytest.mark.parametrize("key", ["wide", "small", "tall"])
def test_the_named_size_draws_the_picture_where_the_old_rule_did(report, key):
    named, plain = report[f"{key}-loaded"], report[f"{key}-plain"]
    assert abs(named["width"] - plain["width"]) <= 1, (named, plain)
    assert abs(named["height"] - plain["height"]) <= 1, (named, plain)


@pytest.mark.parametrize("key", ["wide", "small", "tall"])
def test_the_tile_is_square_and_the_same_whatever_the_shape_of_the_picture(report, key):
    """The tile holds its room before the picture loads because its size comes
    from the grid and not from the picture: square, and the one size for the
    wide, the small and the tall picture alike (the picture fills it)."""
    for variant in ("room", "loaded", "plain"):
        box = report[f"{key}-{variant}"]
        assert abs(box["width"] - box["height"]) <= 1, box
        assert abs(box["width"] - report["wide-room"]["width"]) <= 1, box
        assert box["style"] is None, box


def test_an_attachment_with_no_size_named_is_drawn_as_it_always_was(report):
    for key in ("wide", "small", "tall"):
        assert report[f"{key}-plain"]["loaded"] is True
