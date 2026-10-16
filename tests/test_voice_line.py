"""The voice button and the line that shows what is heard.

While the voice is in use the left of the input bar's row gives way to a line
with an amplitude: the microphone's loudness at a dictation and while a
conversation listens, the answer voice's loudness while it speaks. The seconds
counter beside the button is gone; the button itself wears no rings and no
spinner.

Two modules are run in Node against stand-in audio objects
(``aufnahme.svelte.js``: the level the line reads; ``playbackLevel.js``: the
route from the answer clip to the output through an analyser). The rest is
read from the sources: where the line stands, what the button draws, and that
the row the bar measures is left as it was.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SRC = FRONTEND / "src"
RECORDING = SRC / "lib/aufnahme.svelte.js"
PLAYBACK = SRC / "lib/playbackLevel.js"
BAR = (SRC / "teile/Eingabeleiste.svelte").read_text(encoding="utf-8")
BUTTON = (SRC / "teile/Mikrofonknopf.svelte").read_text(encoding="utf-8")
LINE = (SRC / "teile/VoiceLine.svelte").read_text(encoding="utf-8")
PLAYBACK_SRC = PLAYBACK.read_text(encoding="utf-8")

needs_node = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)

RECORDING_DRIVER = """
import { compileModule } from 'svelte/compiler'
import { readFileSync, writeFileSync } from 'fs'
const code = compileModule(readFileSync(%(module)r, 'utf-8'), {
  filename: 'aufnahme.svelte.js', generate: 'client',
}).js.code
writeFileSync('%(built)s', code)

const nodes = []
class FakeContext {
  constructor(options) {
    this.sampleRate = options?.sampleRate ?? 48000
    this.audioWorklet = { addModule: async () => {} }
    this.destination = {}
  }
  async resume() {}
  createMediaStreamSource() { return { connect() {}, disconnect() {} } }
  createGain() { return { gain: {}, connect() {}, disconnect() {} } }
  close() {}
}
class FakeNode {
  constructor() {
    this.port = { close() {}, onmessage: null }
    nodes.push(this)
  }
  connect() {}
  disconnect() {}
}
globalThis.AudioContext = FakeContext
globalThis.AudioWorkletNode = FakeNode
Object.defineProperty(globalThis, 'navigator', {
  configurable: true,
  value: {
    mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) },
  },
})
globalThis.setInterval = () => 1
globalThis.clearInterval = () => {}
// A clock the scenario can push forward.
const realNow = performance.now.bind(performance)
let skew = 0
performance.now = () => realNow() + skew
const later = (ms) => { skew += ms }

const m = await import('./%(built)s')
const block = (value, count = 128) => nodes[nodes.length - 1].port.onmessage({
  data: new Float32Array(count).fill(value),
})
const report = await (async () => {
%(scenario)s
})()
console.log('---REPORT---' + JSON.stringify(report))
process.exit(0)
"""

PLAYBACK_DRIVER = """
const made = { sources: [], analysers: [], connections: [] }
let state = %(state)r
class FakeAnalyser {
  constructor() { this.fftSize = 0; made.analysers.push(this) }
  connect(target) { made.connections.push(['analyser', target === ctxDestination ? 'destination' : 'other']) }
  getFloatTimeDomainData(samples) { samples.fill(%(sample)s) }
}
const ctxDestination = { name: 'destination' }
class FakeContext {
  constructor() { this.destination = ctxDestination; this.state = state }
  resume() {
    // A context that cannot wake up never settles its promise.
    if (%(stuck)s) return new Promise(() => {})
    this.state = 'running'
    return Promise.resolve()
  }
  createAnalyser() { return new FakeAnalyser() }
  createMediaElementSource(element) {
    if (%(throws)s) throw new Error('already connected')
    const source = {
      element,
      connect(target) { made.connections.push(['source', target instanceof FakeAnalyser ? 'analyser' : 'other']) },
      disconnect() { made.connections.push(['source', 'gone']) },
    }
    made.sources.push(source)
    return source
  }
}
%(context)s
const m = await import('./%(module)s')
const report = await (async () => {
%(scenario)s
})()
console.log('---REPORT---' + JSON.stringify({ ...report, connections: made.connections, sources: made.sources.length }))
process.exit(0)
"""


def _node(driver: str, label: str) -> dict:
    tag = f"{label}-{os.getpid()}"
    check = FRONTEND / f"{tag}.check.mjs"
    check.write_text(driver, encoding="utf-8")
    try:
        result = subprocess.run(
            ["node", check.name], cwd=FRONTEND, capture_output=True, text=True, timeout=120
        )
    finally:
        check.unlink(missing_ok=True)
    assert result.returncode == 0, (result.stdout + result.stderr)[-3000:]
    marker = "---REPORT---"
    assert marker in result.stdout, result.stdout[-3000:]
    return json.loads(result.stdout.split(marker, 1)[1].strip())


def _recording(scenario: str) -> dict:
    tag = f"line-rec-{os.getpid()}"
    built = f"{tag}.built.mjs"
    try:
        return _node(
            RECORDING_DRIVER % {"module": str(RECORDING), "built": built, "scenario": scenario},
            "line-rec",
        )
    finally:
        (FRONTEND / built).unlink(missing_ok=True)


def _playback(scenario: str, *, state="running", stuck="false", throws="false", sample="0.5",
              with_context=True) -> dict:
    copy = FRONTEND / f"line-play-{os.getpid()}.mjs"
    copy.write_text(PLAYBACK.read_text(encoding="utf-8"), encoding="utf-8")
    context = "globalThis.AudioContext = FakeContext" if with_context else ""
    try:
        return _node(
            PLAYBACK_DRIVER % {
                "state": state, "stuck": stuck, "throws": throws, "sample": sample,
                "context": context, "module": copy.name, "scenario": scenario,
            },
            "line-play",
        )
    finally:
        copy.unlink(missing_ok=True)


# --- The level the line reads --------------------------------------------------


@needs_node
def test_a_dictation_gives_the_microphones_level_without_any_callback():
    report = _recording("""
    await m.starten()
    block(0.25)
    return { level: m.currentLevel() }
""")

    assert report["level"] == pytest.approx(0.25)


@needs_node
def test_the_conversation_callback_still_gets_its_blocks_and_the_level_is_there_too():
    report = _recording("""
    const heard = []
    await m.starten(null, (level) => heard.push(level))
    block(0.25)
    return { heard, level: m.currentLevel() }
""")

    assert report["heard"] == [pytest.approx(0.25 * 0x8000)]
    assert report["level"] == pytest.approx(0.25)


@needs_node
def test_the_level_is_zero_before_a_recording_after_it_and_when_the_blocks_stop_coming():
    report = _recording("""
    const before = m.currentLevel()
    await m.starten()
    block(0.25)
    const during = m.currentLevel()
    later(1000)
    const stale = m.currentLevel()
    block(0.25)
    m.stoppen()
    return { before, during, stale, after: m.currentLevel() }
""")

    assert report["before"] == 0
    assert report["during"] > 0
    assert report["stale"] == 0
    assert report["after"] == 0


@needs_node
def test_silence_is_a_level_of_zero_not_a_stale_one():
    report = _recording("""
    await m.starten()
    block(0.25)
    block(0)
    return { level: m.currentLevel() }
""")

    assert report["level"] == 0


@needs_node
def test_a_block_between_the_rounds_of_a_conversation_gives_no_level():
    report = _recording("""
    await m.oeffnen()
    block(0.25)
    const between = m.currentLevel()
    await m.starten()
    block(0.25)
    const listening = m.currentLevel()
    m.abbrechen()
    return { between, listening, after: m.currentLevel() }
""")

    assert report["between"] == 0
    assert report["listening"] == pytest.approx(0.25)
    assert report["after"] == 0


# --- The answer voice goes through an analyser to the output ------------------------


@needs_node
def test_a_clip_is_routed_from_its_element_through_the_analyser_to_the_output():
    report = _playback("""
    const element = { name: 'clip' }
    const release = await m.attachPlayback(element)
    return { routed: typeof release === 'function', level: m.playbackLevel() }
""")

    assert report["routed"] is True
    assert report["connections"] == [["analyser", "destination"], ["source", "analyser"]]
    assert report["level"] == pytest.approx(0.5)


@needs_node
def test_taking_the_route_down_disconnects_the_clip_and_the_level_falls_to_zero():
    report = _playback("""
    const release = await m.attachPlayback({})
    const during = m.playbackLevel()
    release()
    return { during, after: m.playbackLevel() }
""")

    assert report["during"] > 0
    assert report["after"] == 0
    assert report["connections"][-1] == ["source", "gone"]


@needs_node
def test_with_no_clip_routed_the_level_is_zero():
    report = _playback("return { level: m.playbackLevel() }")

    assert report["level"] == 0
    assert report["sources"] == 0


@needs_node
def test_a_route_that_cannot_be_built_leaves_the_clip_alone_and_the_line_calm():
    report = _playback("""
    const release = await m.attachPlayback({})
    return { release, level: m.playbackLevel() }
""", throws="true")

    assert report["release"] is None
    assert report["level"] == 0


@needs_node
def test_a_context_that_stays_suspended_gets_no_route_so_the_answer_is_not_silenced():
    report = _playback("""
    const release = await m.attachPlayback({})
    return { release }
""", state="suspended", stuck="true")

    assert report["release"] is None
    assert report["sources"] == 0


@needs_node
def test_a_context_that_did_not_wake_is_not_waited_for_again_with_every_clip():
    report = _playback("""
    const started = Date.now()
    await m.attachPlayback({})
    const first = Date.now() - started
    const again = Date.now()
    await m.attachPlayback({})
    return { first, second: Date.now() - again }
""", state="suspended", stuck="true")

    assert report["first"] >= 300
    assert report["second"] < 100


@needs_node
def test_a_suspended_context_that_wakes_up_gets_its_route():
    report = _playback("""
    const release = await m.attachPlayback({})
    return { routed: typeof release === 'function' }
""", state="suspended")

    assert report["routed"] is True
    assert report["sources"] == 1


@needs_node
def test_without_any_audio_context_the_clip_plays_on_its_own():
    report = _playback("""
    const release = await m.attachPlayback({})
    return { release, level: m.playbackLevel() }
""", with_context=False)

    assert report["release"] is None
    assert report["level"] == 0


def test_the_answer_clip_is_routed_before_it_plays_and_the_route_is_taken_down_after():
    body = BAR[BAR.index("async function stueckAbspielen"):]
    body = body[: body.index("function vorlesungStoppen")]

    assert body.index("attachPlayback(audioEl)") < body.index("audioEl.play()")
    assert "route?.()" in body[body.index("finally"):]


def test_the_analyser_leads_to_the_output_and_the_element_leads_to_the_analyser():
    assert "analyser.connect(context.destination)" in PLAYBACK_SRC
    assert "createMediaElementSource(audio)" in PLAYBACK_SRC
    assert "node.connect(analyser)" in PLAYBACK_SRC
    assert "ctx.state !== 'running'" in PLAYBACK_SRC


# --- Where the line stands -----------------------------------------------------------


def test_the_seconds_counter_is_gone():
    assert "zaehler" not in BAR
    assert "zaehler" not in BUTTON


def test_the_line_stands_in_the_row_beside_the_left_group_and_before_the_right_one():
    row = BAR[BAR.index('<div class="bar-row"'):]
    place = row.index('<div class="links-platz"')
    group = row.index('<div class="linkegruppe"')
    line = row.index("<VoiceLine")
    right = row.index('<div class="rechts">')

    assert place < group < line < right


def test_the_row_line_the_bar_measures_by_is_as_it_was():
    assert '<div class="bar-row" class:narrow class:tight bind:this={row}>' in BAR


def test_the_bar_measures_the_group_not_the_place_that_stretches_around_it():
    assert "groupOf(child).getBoundingClientRect().width" in BAR
    assert "observer.observe(groupOf(child))" in BAR


def test_the_left_group_fades_out_first_and_the_line_comes_in_after_it():
    assert ".links-platz > .linkegruppe { transition: opacity 0.22s ease-out 0.16s; }" in BAR
    assert re.search(
        r"\.links-platz\.stimme > \.linkegruppe \{[^}]*opacity: 0;[^}]*"
        r"transition: opacity 0\.16s ease-in;",
        BAR,
    )
    assert "transition: opacity 0.22s ease-out 0.16s, transform 0.32s cubic-bezier(0.2, 0.9, 0.3, 1) 0.16s;" in LINE
    assert "transform: scaleX(0.6)" in LINE
    assert "transform-origin: left center" in LINE


def test_the_group_does_not_leave_the_layout_so_the_height_stays():
    rule = BAR[BAR.index(".links-platz.stimme > .linkegruppe"):]
    rule = rule[: rule.index("}")]

    assert "display" not in rule
    assert "height" not in rule
    assert "inert={Boolean(lineState)}" in BAR


def test_without_the_voice_the_group_shows_and_the_line_is_off():
    assert "gespraechAn ? gespraechZustand : holtText ? 'holt' : aufnahme.laeuft ? 'diktat' : null" in BAR
    assert 'class:stimme={Boolean(lineState)}' in BAR
    assert "class:an={Boolean(zustand)}" in LINE


def test_the_microphone_and_the_arrow_never_sit_under_a_condition():
    right = BAR[BAR.index('<div class="rechts">'):]
    for part in ("<Mikrofonknopf", '<button\n          class="aktion"'):
        before = right[: right.index(part)]
        assert before.count("{#if") == before.count("{/if}")


# --- What the line draws ---------------------------------------------------------------


def test_the_line_reads_the_microphone_for_dictation_and_listening_and_the_voice_for_speaking():
    assert "currentLevel" in LINE and "playbackLevel" in LINE
    assert re.search(r"state === 'diktat' \|\| state === 'hoert'\) \{\s*source = Math.min\(1, currentLevel\(\)", LINE)
    assert re.search(r"state === 'spricht'\) \{\s*source = Math.min\(1, playbackLevel\(\)", LINE)


def test_the_microphone_is_drawn_in_the_text_colour_and_the_answer_voice_in_blue():
    assert "let target = text" in LINE
    assert re.search(r"state === 'spricht'\) \{[^}]*target = blue", LINE)
    assert re.search(r"state === 'denkt'\) \{[^}]*target = blue", LINE)


def test_a_small_wave_runs_while_text_is_fetched_and_while_the_model_thinks():
    assert re.search(r"state === 'holt'\) \{\s*mode = 'denkt'", LINE)
    assert re.search(r"state === 'denkt'\) \{\s*mode = 'denkt'", LINE)


def test_the_curve_is_the_one_of_the_preview():
    assert "[[0, 0], [0.2, 0.2], [0.5, 0.9], [0.8, 0.2], [1, 0]]" in LINE
    assert "const points = 120" in LINE
    assert "const f1 = 6" in LINE and "const f2 = 10" in LINE
    assert "g.lineWidth = 1.6 * dpr" in LINE
    assert "source > level ? 0.35 : 0.08" in LINE
    assert "(mode === 'denkt' ? 0.05 : 0.12)" in LINE
    assert "((t * 0.42) % 1.3) - 0.15" in LINE


def test_less_motion_follows_the_loudness_only_with_the_small_wave_standing_still():
    assert "prefers-reduced-motion: reduce" in LINE
    assert "if (!quiet) phase +=" in LINE
    assert "quiet ? 0.5 :" in LINE
    # The fades stay: the reduced branch takes the growing away, and says the
    # fades' length with `!important`, because the page-wide rule for less
    # motion cuts every transition to nothing with it.
    reduced = LINE[LINE.index("@media (prefers-reduced-motion: reduce)"):]
    assert "transform: none" in reduced
    assert ".zeilenlinie { transition-duration: 0.16s !important; }" in reduced
    assert ".zeilenlinie.an { transition-duration: 0.22s !important; }" in reduced
    bar = BAR[BAR.index("@media (prefers-reduced-motion: reduce)", BAR.index(".links-platz")):]
    assert ".links-platz > .linkegruppe { transition-duration: 0.22s !important; }" in bar
    assert ".links-platz.stimme > .linkegruppe { transition-duration: 0.16s !important; }" in bar


def test_the_loop_runs_only_while_the_line_is_shown():
    assert "if (!canvas || !on) return" in LINE
    assert "cancelAnimationFrame" in LINE
    assert "OUT_MS" in LINE


# --- What the button draws -------------------------------------------------------------


def test_the_button_has_no_rings_no_spinner_no_blue_circle():
    for gone in ('class="atem', "atmen", 'class="blau"', "dreht", "schwingt", "conic-gradient"):
        assert gone not in BUTTON


def test_in_rest_the_button_has_no_fill_and_the_sign_is_quiet():
    rest = BUTTON[BUTTON.index("  .mikro {"):]
    rest = rest[: rest.index("}")]

    assert "background: none" in rest
    assert "color: var(--text-leise)" in rest
    assert "width: 30px" in rest and "height: 30px" in rest


def test_dictation_turns_the_sign_into_a_stop_square_without_a_fill():
    assert "class:diktat={nimmt && !gespraech}" in BUTTON
    assert '<span class="stopp"' in BUTTON
    assert ".mikro.diktat .zeichen { opacity: 0; transform: scale(0.6); }" in BUTTON
    assert ".mikro.diktat .stopp { opacity: 1; transform: none; }" in BUTTON
    assert ".mikro.diktat { color: var(--text); }" in BUTTON


def test_while_the_text_is_fetched_the_sign_is_dimmed():
    assert ".mikro.holt .zeichen { opacity: 0.45; }" in BUTTON


def test_the_conversation_has_a_quiet_blue_fill_and_a_ring_that_breathes_while_it_thinks():
    assert "background: color-mix(in srgb, var(--blau) 16%, transparent)" in BUTTON
    assert "box-shadow: inset 0 0 0 1.5px var(--blau)" in BUTTON
    assert "@property --tiefe" in BUTTON and "@property --atem" in BUTTON
    assert "animation: ringatem 1.2s ease-in-out infinite" in BUTTON
    assert ".mikro.gespraech.denkt { --tiefe: 1; }" in BUTTON
    assert "--tiefe 0.3s ease" in BUTTON


def test_the_hold_arc_is_the_outline_of_the_button_and_runs_back_when_let_go_early():
    assert (
        '<rect x="0.75" y="0.75" width="28.5" height="28.5" rx="14.25" pathLength="100" />'
        in BUTTON
    )
    assert "stroke-dashoffset 0.2s ease-out" in BUTTON
    assert "transition: stroke-dashoffset 1s linear" in BUTTON


def test_the_hold_and_the_click_logic_and_the_texts_are_untouched():
    assert "}, 1000)" in BUTTON
    assert "pointerBehandelt" in BUTTON and "tasteHaelt" in BUTTON
    for key in ("sprache.diktat", "sprache.aufnehmen", "sprache.aufnahme_stoppen"):
        assert f"t('{key}')" in BUTTON


def test_less_motion_leaves_the_ring_standing_and_keeps_the_fades():
    reduced = BUTTON[BUTTON.index("@media (prefers-reduced-motion: reduce)"):]

    assert ".ring::after { animation: none; }" in reduced
    assert ".ring { transition-duration: 0.24s !important; }" in reduced
    assert ".mikro .zeichen { transition-duration: 0.18s !important; }" in reduced
