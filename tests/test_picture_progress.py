"""The running picture's step counter is asked one question at a time, and a
beat that comes while a question is on its way waits for its answer.

Run rather than read: the counter's module is compiled with the Svelte
compiler (it uses runes) and run in node; the service and the timer are
stand-ins, so a scenario says which question answers and when the beat
comes.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
LIB = FRONTEND / "src/lib"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)

# Every question the module asks lands in `asks`; the scenario answers it or
# leaves it hanging. With `mode.late` a question given up (the watch ended)
# still answers when the scenario says so, as a slow connection would.
STUBS = """
export const asks = []
export const mode = { late: false }
export const api = {
  bildFortschritt: (signal) => new Promise((resolve, reject) => {
    const ask = { signal, settled: false }
    ask.resolve = (value) => { ask.settled = true; resolve(value) }
    asks.push(ask)
    signal.addEventListener('abort', () => {
      if (mode.late) return
      ask.settled = true
      reject(new DOMException('aborted', 'AbortError'))
    })
  }),
}
"""

DRIVER = """
import { compileModule } from 'svelte/compiler'
import { readFileSync, writeFileSync } from 'fs'
const source = readFileSync(%(lib)r + '/pictureProgress.svelte.js', 'utf-8')
const compiled = compileModule(source, { filename: 'pictureProgress.svelte.js', generate: 'client' })
const swapped = compiled.js.code.replaceAll("from './api.js'", "from './picture-progress.stubs.mjs'")
if (swapped === compiled.js.code) throw new Error('the service import was not swapped for the stand-in')
writeFileSync('picture-progress.module.mjs', swapped)

let beat = null
const timer = { cleared: 0, interval: 0 }
globalThis.setInterval = (fn, ms) => { beat = fn; timer.interval = ms; return 7 }
globalThis.clearInterval = () => { timer.cleared += 1; beat = null }

const stubs = await import('./picture-progress.stubs.mjs')
const { pictureProgress, watchPictureProgress } = await import('./picture-progress.module.mjs')
const { asks, mode } = stubs
const flush = async () => { for (let i = 0; i < 10; i += 1) await new Promise((r) => setTimeout(r, 0)) }
const running = (step) => ({ laeuft: true, anteil: step / 10, schritt: step, gesamt: 10 })
const outstanding = () => asks.filter((a) => !a.settled && !a.signal.aborted).length
const counter = () => ({ running: pictureProgress.running, step: pictureProgress.step, total: pictureProgress.total })
const report = await (async () => {
%(scenario)s
})()
console.log('---REPORT---' + JSON.stringify(report))
process.exit(0)
"""


def _run(scenario: str) -> dict:
    files = {
        FRONTEND / "picture-progress.stubs.mjs": STUBS,
        FRONTEND / "picture-progress.driver.mjs": DRIVER % {"lib": str(LIB), "scenario": scenario},
    }
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
    try:
        done = subprocess.run(
            ["node", "picture-progress.driver.mjs"], cwd=FRONTEND, capture_output=True, text=True, timeout=120,
        )
    finally:
        for path in [*files, FRONTEND / "picture-progress.module.mjs"]:
            path.unlink(missing_ok=True)
    assert done.returncode == 0, (done.stdout + done.stderr)[-3000:]
    mark = "---REPORT---"
    assert mark in done.stdout, done.stdout[-3000:]
    return json.loads(done.stdout.split(mark, 1)[1].strip())


@needs_node
def test_a_beat_while_a_question_is_on_its_way_asks_nothing_and_gives_nothing_up():
    """The first question is still on its way at the next beat: it is not
    given up (its signal stays), no second one is asked, and its answer
    moves the counter when it arrives."""
    report = _run("""
    const stop = watchPictureProgress()
    await flush()
    beat()
    await flush()
    const waiting = { asked: asks.length, aborted: asks[0].signal.aborted, outstanding: outstanding() }
    asks[0].resolve(running(3))
    await flush()
    const shown = counter()
    stop()
    return { waiting, shown, interval: timer.interval }
    """)
    assert report["waiting"] == {"asked": 1, "aborted": False, "outstanding": 1}
    assert report["shown"] == {"running": True, "step": 3, "total": 10}
    assert report["interval"] == 700


@needs_node
def test_an_answer_that_comes_after_two_beats_moves_the_counter_and_the_next_beat_asks_again():
    """A line that needs more than one beat to answer: two beats pass
    without a second question; the answer moves the counter, and the beat
    after it asks the next question."""
    report = _run("""
    const stop = watchPictureProgress()
    await flush()
    beat()
    await flush()
    beat()
    await flush()
    const during = { asked: asks.length, aborted: asks[0].signal.aborted }
    asks[0].resolve(running(5))
    await flush()
    const answered = { shown: counter(), asked: asks.length }
    beat()
    await flush()
    const after = { asked: asks.length, outstanding: outstanding() }
    asks[1].resolve(running(6))
    await flush()
    const last = counter()
    stop()
    return { during, answered, after, last }
    """)
    assert report["during"] == {"asked": 1, "aborted": False}
    assert report["answered"] == {"shown": {"running": True, "step": 5, "total": 10}, "asked": 1}
    assert report["after"] == {"asked": 2, "outstanding": 1}
    assert report["last"] == {"running": True, "step": 6, "total": 10}


@needs_node
def test_a_question_that_answers_before_the_next_beat_is_not_given_up():
    """Silence probe: every question answers before the beat, so none is
    aborted and each beat asks exactly one new question. With a service that
    never answers, no more than one question is ever on its way, and no
    second one is asked."""
    report = _run("""
    const stop = watchPictureProgress()
    await flush()
    for (let step = 1; step <= 3; step += 1) {
      asks[asks.length - 1].resolve(running(step))
      await flush()
      beat()
      await flush()
    }
    const answered = { asked: asks.length, anyAborted: asks.some((a) => a.signal.aborted), step: pictureProgress.step }
    stop()

    const hanging = []
    const before = asks.length
    const again = watchPictureProgress()
    await flush()
    hanging.push(outstanding())
    for (let i = 0; i < 5; i += 1) {
      beat()
      await flush()
      hanging.push(outstanding())
    }
    const asked_while_hanging = asks.length - before
    again()
    return { answered, hanging, asked_while_hanging }
    """)
    assert report["answered"] == {"asked": 4, "anyAborted": False, "step": 3}
    assert report["hanging"] == [1, 1, 1, 1, 1, 1]
    assert report["asked_while_hanging"] == 1


@needs_node
def test_ending_the_watch_gives_up_the_question_and_asks_nothing_more():
    """When the last surface stops watching, the question on its way is
    given up, the timer is cleared, the counter is cleared, and an answer
    that still arrives afterwards shows nothing."""
    report = _run("""
    mode.late = true
    const stop = watchPictureProgress()
    await flush()
    asks[0].resolve(running(4))
    await flush()
    beat()
    await flush()
    const before = counter()
    stop()
    await flush()
    asks[1].resolve(running(9))
    await flush()
    return { before, after: counter(), secondAborted: asks[1].signal.aborted, cleared: timer.cleared, asked: asks.length }
    """)
    assert report["before"] == {"running": True, "step": 4, "total": 10}
    assert report["after"] == {"running": False, "step": 0, "total": 0}
    assert report["secondAborted"] is True
    assert report["cleared"] == 1
    assert report["asked"] == 2
