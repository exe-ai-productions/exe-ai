"""The line with the newest thought under a running thinking head.

It shows the newest thought that is finished — a sentence closed by . ! or ?
with white space after it, or a paragraph closed by a line break — never the
one still being written, and each thought stays at least a second
(`frontend/src/lib/thoughtLine.js`, drawn by `teile/ThoughtLine.svelte`).
The pure module runs in Node; the drawing is read off the source.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

# Borrowed rather than copied: a folder under node_modules, which no run that
# is killed halfway can leave a stray file out of in the working tree.
from tests.test_agentenampel import _pruefordner

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
NACHRICHT = (FRONTEND / "src/teile/Nachricht.svelte").read_text(encoding="utf-8")
LINE = (FRONTEND / "src/teile/ThoughtLine.svelte").read_text(encoding="utf-8")
MODULE = FRONTEND / "src/lib/thoughtLine.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


def _run(body: str) -> dict:
    """Run `body` (it fills `out`) with the module imported, in Node."""
    with _pruefordner() as folder:
        driver = folder / "thought-line.mjs"
        driver.write_text(
            textwrap.dedent(
                """
                import { finishedThought, minimumDisplay } from %s
                const out = {}
                %s
                console.log('---REPORT---' + JSON.stringify(out))
                """
            )
            % (json.dumps(MODULE.as_uri()), body),
            encoding="utf-8",
        )
        run = subprocess.run(
            ["node", driver.name], cwd=folder, capture_output=True, text=True, timeout=60
        )
    assert run.returncode == 0, (run.stdout + run.stderr)[-2000:]
    return json.loads(run.stdout.split("---REPORT---", 1)[1].strip())


@needs_node
def test_the_line_shows_only_a_finished_thought():
    out = _run(
        """
        out.none = finishedThought('')
        // Not finished: no mark yet, or the mark is the last character.
        out.unfinished = finishedThought('I check the file')
        out.markLast = finishedThought('I check the file.')
        // Finished: the mark has white space behind it.
        out.finished = finishedThought('I check the file. Then the')
        out.second = finishedThought('First. Second! Third? Fou')
        // A paragraph closed by a line break is finished without a mark.
        out.paragraph = finishedThought('A thought without a mark\\nand the next')
        out.manyBreaks = finishedThought('One.\\n\\nTwo\\n\\nThr')
        // A number does not end a thought.
        out.number = finishedThought('Version 3.5 is out and I')
        """
    )
    assert out["none"] == ""
    assert out["unfinished"] == ""
    assert out["markLast"] == ""
    assert out["finished"] == "I check the file."
    assert out["second"] == "Third?"
    assert out["paragraph"] == "A thought without a mark"
    assert out["manyBreaks"] == "Two"
    assert out["number"] == ""


@needs_node
def test_the_backward_reading_agrees_with_a_plain_split_on_any_text():
    """The reading from the end must say what the plain way of splitting the
    whole text says: the last non-empty piece in front of the last place a
    thought ends."""
    out = _run(
        """
        const reference = (text) => {
          const s = String(text || '')
          const ends = [...s.matchAll(/[.!?](?=\\s)|(?=\\n)/g)]
          for (let i = ends.length - 1; i >= 0; i--) {
            const end = s[ends[i].index] === '\\n' ? ends[i].index : ends[i].index + 1
            const pieces = s.slice(0, end).split(/(?<=[.!?])\\s+|\\n+/)
            for (let k = pieces.length - 1; k >= 0; k--) if (pieces[k].trim()) return pieces[k].trim()
          }
          return ''
        }
        const alphabet = ['a', 'b', ' ', ' ', '.', '!', '?', '\\n', '\\n', '3']
        let seed = 12345
        const next = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648
        const bad = []
        for (let n = 0; n < 4000; n++) {
          const length = Math.floor(next() * 40)
          let text = ''
          for (let i = 0; i < length; i++) text += alphabet[Math.floor(next() * alphabet.length)]
          if (finishedThought(text) !== reference(text)) bad.push(text)
        }
        out.bad = bad.slice(0, 5)
        """
    )
    assert out["bad"] == []


@needs_node
def test_a_thought_stays_at_least_a_second_and_only_the_newest_follows():
    out = _run(
        """
        let now = 0
        const timers = []
        const clock = {
          now: () => now,
          set: (fn, ms) => { timers.push({ at: now + ms, fn }); return timers.length - 1 },
          clear: (id) => { if (timers[id]) timers[id].fn = null },
        }
        const advance = (to) => {
          now = to
          for (const t of timers) if (t.fn && t.at <= now) { const f = t.fn; t.fn = null; f() }
        }
        const shownAt = []
        const hold = minimumDisplay(1000, (v) => shownAt.push([now, v]), clock)
        hold.offer('')                      // nothing yet
        hold.offer('A.')                    // first: at once, at 0
        advance(300); hold.offer('B.')      // too early: waits
        advance(500); hold.offer('C.')      // replaces B, still waiting
        advance(999)                        // not yet
        out.before = shownAt.length
        advance(1000)                       // A has stood a second: C comes
        advance(1500); hold.offer('D.')     // C stands since 1000: waits to 2000
        advance(2000)
        advance(3500); hold.offer('E.')     // long enough: at once
        hold.offer('E.')                    // same again: nothing
        out.shown = shownAt
        const late = []
        const h2 = minimumDisplay(1000, (v) => late.push(v), clock)
        h2.offer('X.'); now += 10; h2.offer('Y.'); h2.dispose(); now += 5000; advance(now)
        out.afterDispose = late
        """
    )
    assert out["before"] == 1
    assert out["shown"] == [[0, "A."], [1000, "C."], [2000, "D."], [3500, "E."]]
    assert out["afterDispose"] == ["X."]


def test_the_chat_draws_the_line_from_the_module_and_keeps_its_old_rule_nowhere():
    assert "import ThoughtLine from './ThoughtLine.svelte'" in NACHRICHT
    assert "<ThoughtLine text={teil.text} />" in NACHRICHT
    # The old rule showed the sentence still being written.
    assert "function letzterGedanke" not in NACHRICHT
    assert ".mitlesen" not in NACHRICHT
    assert "import { finishedThought, minimumDisplay } from '../lib/thoughtLine.js'" in LINE
    assert "const MIN_MS = 1000" in LINE
    # It has its height before the first thought stands in it.
    assert "min-height: 20px;" in LINE
    # The pending timer goes with the line.
    assert "hold.dispose()" in LINE
