"""The answer's block of thinking and calls, and the way its text flows.

Three libraries carry the logic and run in node as they are shipped:

* `werkzeugbuendel.js` — which parts of an answer make one block, and which
  colour its single dot wears;
* `textFlow.js` — how much of the last piece of text the window may draw,
  how far it may lag behind the model, and whether its characters fade in;
* `toolResult.js` — how the terminal tool draws a call's result.

The template's own claims (a window of ten lines, the label that names the
word nobody sees, no word at a row's end) are pinned at the source.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "frontend" / "src" / "lib"
COMPONENTS = ROOT / "frontend" / "src" / "teile"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")


def _node(script: str):
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert proc.returncode == 0, f"{proc.stderr}\n{proc.stdout}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


_PARTS_JS = """
import * as b from %r
const text = (t) => ({ art: 'content', text: t })
const thinking = (t = 'hmm') => ({ art: 'reasoning', text: t })
const call = (id, ergebnis = 'ok', extra = {}) => ({
  art: 'werkzeug',
  werkzeug: { aufruf_id: id, name: 'read_file', ergebnis, fehlgeschlagen: false, ...extra },
})
const helper = (id) => ({
  art: 'werkzeug',
  werkzeug: { aufruf_id: id, name: 'start_job', auftrag_id: 'j' + id, ergebnis: 'ok' },
})
const form = (parts) => b.buendeln(parts).map((e) =>
  e.art === 'buendel' ? { bundle: e.eintraege.map((x) => x.i) } : { part: e.i })
""" % ((LIB / "werkzeugbuendel.js").as_uri(),)


def _bundles(js: str):
    return _node(_PARTS_JS + js)


@needs_node
def test_a_single_call_between_two_texts_is_one_block():
    assert _bundles(
        "console.log(JSON.stringify(form([text('a'), call('1'), text('b')])))"
    ) == [{"part": 0}, {"bundle": [1]}, {"part": 2}]


@needs_node
def test_thinking_alone_is_one_block():
    assert _bundles(
        "console.log(JSON.stringify(form([text('a'), thinking(), text('b')])))"
    ) == [{"part": 0}, {"bundle": [1]}, {"part": 2}]


@needs_node
def test_thinking_and_calls_between_two_texts_are_one_single_block():
    assert _bundles(
        "console.log(JSON.stringify(form([thinking(), call('1'), thinking(), call('2'), text('b')])))"
    ) == [{"bundle": [0, 1, 2, 3]}, {"part": 4}]


@needs_node
def test_a_helper_row_ends_the_block():
    assert _bundles(
        "console.log(JSON.stringify(form([call('1'), call('2'), helper('3'), call('4')])))"
    ) == [{"bundle": [0, 1]}, {"part": 2}, {"bundle": [3]}]


@needs_node
def test_visible_text_ends_the_block_empty_text_does_not():
    assert _bundles(
        "console.log(JSON.stringify(form([call('1'), text('   '), call('2'), text('x'), call('3')])))"
    ) == [{"bundle": [0, 2]}, {"part": 3}, {"bundle": [4]}]


@needs_node
def test_a_running_and_a_stored_answer_form_the_same_blocks():
    """The same function reads both; a part that is still without its result
    changes nothing about where the blocks fall."""
    finished = "[text('a'), thinking(), call('1'), call('2'), text('b'), call('3')]"
    running_parts = "[text('a'), thinking(), call('1'), call('2', null), text('b'), call('3', null)]"
    result = _bundles(
        f"console.log(JSON.stringify([form({finished}), form({running_parts})]))"
    )
    assert result[0] == result[1]
    assert result[0] == [{"part": 0}, {"bundle": [1, 2, 3]}, {"part": 4}, {"bundle": [5]}]


@needs_node
def test_the_key_of_a_block_never_meets_the_key_of_a_part():
    key = _bundles(
        "console.log(JSON.stringify(b.buendeln([text('a'), call('1'), text('b')]).map((e) => e.art === 'buendel' ? e.schluessel : e.i)))"
    )
    assert key[0] == 0 and key[2] == 2
    assert key[1] < 0


@needs_node
def test_the_dot_follows_the_last_call_red_in_the_middle_green_at_the_end_is_green():
    result = _bundles("""
const eintraege = [
  { teil: call('1'), i: 0 },
  { teil: call('2'), i: 1 },
  { teil: call('3'), i: 2 },
]
const dot = (w) => ({ farbe: w.aufruf_id === '2' ? 'rot' : 'gruen' })
console.log(JSON.stringify({
  middleRed: b.blockDot(eintraege, false, dot),
  lastRed: b.blockDot(eintraege.slice(0, 2), false, dot),
}))
""")
    assert result["middleRed"] == {"farbe": "gruen", "atmet": False}
    assert result["lastRed"] == {"farbe": "rot", "atmet": False}


@needs_node
def test_a_running_block_is_blue_and_yellow_only_where_the_last_call_waits():
    result = _bundles("""
const eintraege = [{ teil: call('1'), i: 0 }, { teil: call('2', null), i: 1 }]
const blau = (w) => ({ farbe: 'blau' })
const gelb = (w) => ({ farbe: w.aufruf_id === '2' ? 'gelb' : 'gruen', atmet: false })
console.log(JSON.stringify({
  running: b.blockDot(eintraege, true, blau, true),
  pending: b.blockDot(eintraege, true, gelb, true),
  thinkingOnly: b.blockDot([{ teil: thinking(), i: 0 }], false, blau),
  thinkingOnlyRunning: b.blockDot([{ teil: thinking(), i: 0 }], true, blau, true),
}))
""")
    assert result["running"] == {"farbe": "blau", "atmet": True}
    assert result["pending"] == {"farbe": "gelb", "atmet": False}
    assert result["thinkingOnly"] == {"farbe": "blau", "atmet": False}
    assert result["thinkingOnlyRunning"] == {"farbe": "blau", "atmet": True}


@needs_node
def test_the_number_of_calls_does_not_count_the_thinking():
    assert _bundles("""
const eintraege = [{ teil: thinking(), i: 0 }, { teil: call('1'), i: 1 }, { teil: thinking(), i: 2 }]
console.log(JSON.stringify(b.aufrufZahl(eintraege)))
""") == 1


# --- How the text of a running answer comes up ------------------------------

_FLOW_JS = """
import { makeTextFlow } from %r
const log = []
let clock = 0
let pending = null
let reducedMotion = false
const flow = makeTextFlow({
  set: (length, flowing) => log.push([length, flowing]),
  raf: (fn) => { pending = fn; return 1 },
  caf: () => { pending = null },
  reducedMotion: () => reducedMotion,
})
const ticks = (n) => { for (let k = 0; k < n && pending; k += 1) { const fn = pending; pending = null; clock += 16; fn(clock) } }
const last = () => log[log.length - 1]
""" % ((LIB / "textFlow.js").as_uri(),)


def _flow(js: str):
    return _node(_FLOW_JS + js)


@needs_node
def test_a_stored_answer_stands_whole_at_once():
    assert _flow("""
flow.follow(2, 120, false)
console.log(JSON.stringify({ last: last(), pending: pending !== null }))
""") == {"last": [120, False], "pending": False}


@needs_node
def test_less_motion_leaves_the_text_whole_even_while_it_grows():
    assert _flow("""
reducedMotion = true
flow.follow(0, 10, true)
flow.follow(0, 90, true)
console.log(JSON.stringify({ last: last(), pending: pending !== null }))
""") == {"last": [90, False], "pending": False}


@needs_node
def test_what_was_there_at_first_sight_stands_whole_and_new_text_flows():
    result = _flow("""
flow.follow(0, 40, true)
const atFirst = last()
flow.follow(0, 400, true)
const atOnce = last()
ticks(5)
const later = last()
ticks(2000)
console.log(JSON.stringify({ atFirst, atOnce, later, end: last() }))
""")
    assert result["atFirst"] == [40, True]
    # What is waiting is let out evenly, not at once.
    assert result["atOnce"][0] == 40 and result["atOnce"][1] is True
    assert 40 < result["later"][0] < 400
    assert result["end"] == [400, True]


@needs_node
def test_a_new_piece_of_text_during_the_run_begins_at_its_first_character():
    result = _flow("""
flow.follow(0, 30, true)
flow.follow(2, 200, true)
console.log(JSON.stringify(last()))
""")
    assert result == [0, True]


@needs_node
def test_after_the_end_the_rest_runs_out_instead_of_jumping():
    result = _flow("""
flow.follow(0, 20, true)
flow.follow(0, 600, true)
flow.follow(0, 600, false)
const straightAway = last()
ticks(4000)
console.log(JSON.stringify({ straightAway, end: last(), pending: pending !== null }))
""")
    assert result["straightAway"][0] < 600
    assert result["straightAway"][1] is True
    assert result["end"] == [600, False]
    assert result["pending"] is False


_STEP_JS = """
import { makeFlow } from %r
// How long, in steps of 16 ms, a queue of `n` characters waits.
const drain = (n) => {
  const f = makeFlow()
  let now = 0
  let queued = n
  while (queued > 0 && now < 20000) { now += 16; queued -= f.step(now, queued) }
  return now
}
""" % ((LIB / "textFlow.js").as_uri(),)


@needs_node
def test_a_queue_of_any_length_is_empty_a_quarter_of_a_second_after_it_came():
    """The text is never more than 250 ms behind what has arrived, however
    much has arrived at once (before: up to 3 s behind a fast model)."""
    result = _node(_STEP_JS + "console.log(JSON.stringify([50, 500, 5000].map(drain)))")
    # 250 ms plus the one frame the first step needs.
    assert all(ms <= 250 + 16 for ms in result), result


@needs_node
def test_the_speed_does_not_grow_while_a_queue_runs_out():
    """Characters let out per frame never rise within one queue: the pace
    that the piece set holds until it is empty (before: the speed ramped up
    over seconds and the text got visibly faster)."""
    result = _node(_STEP_JS + """
const f = makeFlow()
let now = 0
let queued = 2000
const counts = []
while (queued > 0 && now < 5000) { now += 16; const c = f.step(now, queued); queued -= c; counts.push(c) }
console.log(JSON.stringify(counts))
""")
    # Never faster than the first frame's pace, apart from a rounding of one.
    assert max(result) <= result[0] + 1, result[:10]


@needs_node
def test_a_single_character_stands_in_the_next_frame_and_a_slow_model_is_told_one_by_one():
    result = _node(_STEP_JS + """
const one = drain(1)
// 70 characters a second for five seconds, a frame every 16 ms.
const f = makeFlow()
let arrived = 0
let shown = 0
let widest = 0
for (let t = 16; t <= 5000; t += 16) {
  arrived = Math.floor(t * 0.07)
  shown += f.step(t, arrived - shown)
  widest = Math.max(widest, arrived - shown)
}
console.log(JSON.stringify({ one, widest }))
""")
    assert result["one"] == 16
    # Whatever came in a frame is out in that frame.
    assert result["widest"] == 0


@needs_node
def test_with_less_motion_the_whole_queue_stands_at_once():
    result = _flow("""
reducedMotion = true
flow.follow(0, 20, true)
flow.follow(0, 5000, true)
console.log(JSON.stringify(last()))
""")
    assert result == [5000, False]


# --- What the terminal tool does with a result ------------------------------


@needs_node
def test_a_change_block_is_split_from_the_result_text_and_coloured_line_by_line():
    result = _node(
        f"""
import * as w from {(LIB / "toolResult.js").as_uri()!r}
const text = 'Edited a.py\\n\\n@@ -1,2 +1,2 @@\\n ctx\\n-old\\n+new'
console.log(JSON.stringify({{
  split: w.aenderungAufteilen(text),
  none: w.aenderungAufteilen('plain output'),
  html: w.aenderungHtml('@@ -1 +1 @@\\n-old\\n+new'),
}}))
"""
    )
    assert result["split"]["kurz"] == "Edited a.py"
    assert result["split"]["diff"].startswith("@@ ")
    assert result["none"] is None
    assert "diff-entfernt" in result["html"] and "diff-hinzu" in result["html"]


# --- The template's claims, read at the source ------------------------------


def _message_source() -> str:
    return (COMPONENTS / "Nachricht.svelte").read_text(encoding="utf-8")


def _rule(css: str, selector: str) -> str:
    found = re.search(rf"\n  {re.escape(selector)} \{{([^}}]*)\}}", css)
    assert found, selector
    return found.group(1)


def test_the_window_of_a_block_shows_ten_rows_at_most_and_scrolls_without_a_bar():
    css = _message_source().split("<style>", 1)[1]
    block_window = _rule(css, ".block-window")
    assert "max-height: calc(10 * 20px)" in block_window
    assert "overflow-y: auto" in block_window
    assert "overscroll-behavior: contain" in block_window


def test_a_call_is_a_button_that_opens_the_terminal_and_carries_its_word_in_the_label():
    row = _message_source().split("{#snippet callRow(teil, i)}", 1)[1].split("{/snippet}", 1)[0]
    assert "aria-label={callLabel(werkzeug, stand)}" in row
    assert "openCall(callKey(werkzeug), event.currentTarget)" in row
    # The dot is small and quiet: six pixels, no standing glow.
    assert "groesse={6}" in row and " quiet" in row


def test_a_call_row_asks_for_the_mark_of_its_server():
    row = _message_source().split("{#snippet callRow(teil, i)}", 1)[1].split("{/snippet}", 1)[0]
    assert "serverMark(werkzeug.server)" in row
    assert "wz-marke" not in _message_source()


def test_the_built_in_sources_wear_no_server_logo():
    """Every source name a built-in tool of the service sends is on the list
    the call row screens out: a server of one's own called the same never
    lends its logo to those calls."""
    logo = (Path(__file__).resolve().parent.parent / "frontend/src/lib/serverlogo.svelte.js").read_text(encoding="utf-8")
    listed = set(re.findall(r"'([a-z]+)'", logo.split("new Set([", 1)[1].split("])", 1)[0]))
    found = set()
    for path in (Path(__file__).resolve().parent.parent / "app").rglob("*.py"):
        found |= set(re.findall(r'^SERVER_NAME\s*=\s*"([a-z]+)"', path.read_text(encoding="utf-8"), re.M))
    assert found and found <= listed, found - listed


def test_the_dot_on_the_line_and_the_ring_are_both_seven_pixels():
    message = _message_source()
    dot = message.split("{#snippet punkt(farbe, atmet = false)}", 1)[1].split("{/snippet}", 1)[0]
    assert "groesse={7}" in dot and "quiet" in dot
    css = message.split("<style>", 1)[1]
    ring = _rule(css, ".ring")
    assert "width: 7px" in ring and "height: 7px" in ring


def test_a_click_on_a_helper_opens_the_agents_and_remembers_the_row():
    message = _message_source()
    assert "function openHelper(jobId, row) {\n    rememberTrigger(row)\n    openTranscript(jobId)" in message
    assert "openHelper(job?.id ?? teil.werkzeug.auftrag_id, event.currentTarget)" in message


def test_the_terminal_reads_the_chosen_call_and_unfolds_it():
    terminal = (COMPONENTS / "ModulTerminal.svelte").read_text(encoding="utf-8")
    assert "from '../lib/callSelection.svelte.js'" in terminal
    assert "callSelection.counter" in terminal and "callSelection.key" in terminal
    assert "data-key={eintrag.schluessel}" in terminal
    assert "data-key={`l${eintrag.lauf.lauf}`}" in terminal
    assert "class:selected={selected === eintrag.schluessel}" in terminal


def test_esc_and_the_cross_close_and_the_focus_returns():
    bar_source = (COMPONENTS / "Arbeitsleiste.svelte").read_text(encoding="utf-8")
    assert "<svelte:window onkeydown={onKey} />" in bar_source
    assert "if (event.key !== 'Escape' || event.defaultPrevented) return" in bar_source
    assert "await schliessen()\n    restoreFocus()" in bar_source
    assert "onclick={closeWithFocus}" in bar_source


def test_a_closed_block_is_only_its_head_and_the_line_of_the_newest_step_is_gone():
    message = _message_source()
    assert "ThoughtLine" not in message
    assert not (COMPONENTS / "ThoughtLine.svelte").exists()
    assert not (LIB / "thoughtLine.js").exists()
    block = message.split("{#snippet block(eintrag)}", 1)[1].split("{/snippet}", 1)[0]
    # Nothing but the head stands outside the open window.
    assert block.count("{#if offen}") == 1 and "{:else if going}" not in block


def test_head_thinking_calls_and_run_number_stand_in_one_brightness_the_answer_stays_bright():
    css = _message_source().split("<style>", 1)[1]
    for selector in (".block-head", ".step-thought", ".aufruf"):
        assert "color: var(--text-neben)" in _rule(css, selector), selector
    # The shimmer of a running head runs in the same colour.
    shimmer = _rule(css, ".leucht")
    assert "var(--text-neben)" in shimmer and "--text-still" not in shimmer
    # No brightness of their own: neither the count nor the run number is dimmed again.
    assert "opacity" not in _rule(css, ".aufruf .wz-nummer")
    assert ".head-count { opacity" not in css
    # The names in the block carry no extra colour and no weight.
    message = _message_source()
    block = message.split("{#snippet block(eintrag)}", 1)[1].split("{/snippet}", 1)[0]
    row = message.split("{#snippet callRow(teil, i)}", 1)[1].split("{/snippet}", 1)[0]
    written = message.split("{#snippet beingWritten(werkzeug)}", 1)[1].split("{/snippet}", 1)[0]
    for part in (block, row, written):
        assert "werkzeugname" not in part
    assert ".head-name { font-family: var(--schrift-fest); }" in css
    # The answer is the text colour of the program.
    assert "color: var(--text);" in _rule(css, ".antwort") or "var(--text)" in css


def test_the_terminal_tab_keeps_the_text_colour_and_the_weight_of_a_tool_name():
    glass = (ROOT / "frontend" / "src" / "stil" / "global.css").read_text(encoding="utf-8")
    rule = re.search(r"\.werkzeugname \{([^}]*)\}", glass)
    assert rule, ".werkzeugname"
    assert "color: var(--text)" in rule.group(1) and "font-weight: 600" in rule.group(1)
    terminal = (COMPONENTS / "ModulTerminal.svelte").read_text(encoding="utf-8")
    assert "werkzeugname" in terminal
