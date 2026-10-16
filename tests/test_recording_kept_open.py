"""A conversation's microphone opens once and stays open through every round.

Before, every round started the device again (``getUserMedia``, a new audio
context) and freed it again at the end. On a small Mac the restart failed
halfway through a conversation and the round heard nothing. Now ``oeffnen``
opens the microphone when the conversation begins, a round only starts and
stops collecting (``starten`` / ``stoppen`` / ``abbrechen``), and
``schliessen`` frees the device when the conversation ends. A dictation, which
never calls ``oeffnen``, opens and frees as before. The module is compiled
with the Svelte compiler and run in Node against a stand-in audio context; the
page's side (opening before the voice is announced, the round's own clock) is
pinned in the source.
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
MODULE = FRONTEND / "src/lib/aufnahme.svelte.js"
BAR = FRONTEND / "src/teile/Eingabeleiste.svelte"

node_needed = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)

DRIVER = """
import { compileModule } from 'svelte/compiler'
import { readFileSync, writeFileSync } from 'fs'
const code = compileModule(readFileSync(%(module)r, 'utf-8'), {
  filename: 'aufnahme.svelte.js', generate: 'client',
}).js.code
writeFileSync('%(built)s', code)

const count = { media: 0, context: 0, trackStops: 0, contextCloses: 0 }
const tracks = []
let micError = null
const nodes = []
class FakeContext {
  constructor(options) {
    count.context += 1
    this.sampleRate = options?.sampleRate ?? 48000
    this.audioWorklet = { addModule: async () => {} }
    this.destination = {}
  }
  async resume() {}
  createMediaStreamSource() { return { connect() {}, disconnect() {} } }
  createGain() { return { gain: {}, connect() {}, disconnect() {} } }
  close() { count.contextCloses += 1 }
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
    mediaDevices: {
      getUserMedia: async () => {
        if (micError) throw Object.assign(new Error('mic'), { name: micError })
        count.media += 1
        const track = { stop() { count.trackStops += 1 } }
        tracks.push(track)
        return { getTracks: () => [track] }
      },
    },
  },
})
globalThis.setInterval = () => 1
globalThis.clearInterval = () => {}

const m = await import('./%(built)s')
// One block of the microphone, as the worklet posts it.
const block = (n) => nodes[nodes.length - 1].port.onmessage({
  data: new Float32Array(n).fill(0.25),
})
const size = async (blob) => (blob ? (await blob.arrayBuffer()).byteLength : null)
const report = await (async () => {
%(scenario)s
})()
console.log('---REPORT---' + JSON.stringify(report))
process.exit(0)
"""


def _run(scenario: str) -> dict:
    tag = str(os.getpid())
    built = f"rec-{tag}.built.mjs"
    check = f"rec-{tag}.check.mjs"
    (FRONTEND / check).write_text(
        DRIVER % {"module": str(MODULE), "built": built, "scenario": scenario}, encoding="utf-8"
    )
    try:
        result = subprocess.run(
            ["node", check], cwd=FRONTEND, capture_output=True, text=True, timeout=120
        )
    finally:
        (FRONTEND / check).unlink(missing_ok=True)
        (FRONTEND / built).unlink(missing_ok=True)
    assert result.returncode == 0, (result.stdout + result.stderr)[-3000:]
    marker = "---REPORT---"
    assert marker in result.stdout, result.stdout[-3000:]
    return json.loads(result.stdout.split(marker, 1)[1].strip())


@node_needed
def test_two_rounds_open_the_device_and_the_context_once():
    report = _run("""
    await m.oeffnen()
    await m.starten()
    block(128)
    const first = await size(m.stoppen())
    await m.starten()
    block(64)
    const second = await size(m.stoppen())
    return { count, first, second }
""")

    assert report["count"] == {"media": 1, "context": 1, "trackStops": 0, "contextCloses": 0}
    assert (report["first"], report["second"]) == (44 + 256, 44 + 128)


@node_needed
def test_what_the_microphone_hears_between_two_rounds_lands_in_no_recording():
    report = _run("""
    await m.oeffnen()
    block(1000)
    await m.starten()
    block(64)
    const first = await size(m.stoppen())
    block(1000)
    await m.starten()
    block(32)
    const second = await size(m.stoppen())
    return { first, second }
""")

    assert report == {"first": 44 + 128, "second": 44 + 64}


@node_needed
def test_the_level_is_reported_only_while_a_round_listens():
    report = _run("""
    const levels = []
    await m.oeffnen()
    block(128)
    await m.starten(null, (level) => levels.push(level))
    block(128)
    m.stoppen()
    block(128)
    return { levels: levels.length }
""")

    assert report == {"levels": 1}


@node_needed
def test_an_escape_drops_the_round_and_keeps_the_microphone():
    report = _run("""
    await m.oeffnen()
    await m.starten()
    block(128)
    m.abbrechen()
    const running = m.aufnahme.laeuft
    await m.starten()
    block(64)
    const blob = await size(m.stoppen())
    return { count, running, blob }
""")

    assert report["count"]["media"] == 1 and report["count"]["trackStops"] == 0
    assert report["running"] is False
    assert report["blob"] == 44 + 128


@node_needed
def test_the_end_of_the_conversation_frees_the_device_and_drops_a_listening_round():
    report = _run("""
    await m.oeffnen()
    await m.starten()
    block(128)
    m.schliessen()
    const afterClose = { running: m.aufnahme.laeuft, count: { ...count } }
    await m.starten()
    block(16)
    const again = await size(m.stoppen())
    return { afterClose, again, count }
""")

    assert report["afterClose"]["running"] is False
    assert report["afterClose"]["count"]["trackStops"] == 1
    assert report["afterClose"]["count"]["contextCloses"] == 1
    # After the end a dictation opens its own device again, and frees it.
    assert report["count"]["media"] == 2 and report["count"]["trackStops"] == 2
    assert report["again"] == 44 + 32


@node_needed
def test_opening_twice_is_one_open():
    report = _run("""
    await m.oeffnen()
    await m.oeffnen()
    return count
""")

    assert report["media"] == 1 and report["context"] == 1


@node_needed
def test_a_device_that_went_away_is_opened_again_for_the_next_round():
    report = _run("""
    await m.oeffnen()
    await m.starten()
    block(128)
    m.stoppen()
    tracks[0].readyState = 'ended'
    await m.oeffnen()
    await m.starten()
    block(64)
    const blob = await size(m.stoppen())
    return { count, blob }
""")

    assert report["count"]["media"] == 2 and report["count"]["context"] == 2
    assert report["blob"] == 44 + 128


@node_needed
def test_a_refused_microphone_holds_nothing_and_the_next_try_asks_again():
    report = _run("""
    micError = 'NotAllowedError'
    let name = null
    try { await m.oeffnen() } catch (error) { name = error.name }
    micError = null
    await m.oeffnen()
    return { name, count }
""")

    assert report["name"] == "NotAllowedError"
    assert report["count"]["media"] == 1 and report["count"]["context"] == 1


@node_needed
def test_silence_a_dictation_opens_and_frees_the_device_each_time():
    report = _run("""
    await m.starten()
    block(128)
    const first = await size(m.stoppen())
    const afterFirst = { ...count }
    await m.starten()
    block(128)
    m.abbrechen()
    return { first, afterFirst, count }
""")

    assert report["first"] == 44 + 256
    assert report["afterFirst"] == {"media": 1, "context": 1, "trackStops": 1, "contextCloses": 1}
    assert report["count"] == {"media": 2, "context": 2, "trackStops": 2, "contextCloses": 2}


def _bar() -> str:
    return BAR.read_text(encoding="utf-8")


def test_the_conversation_opens_its_microphone_before_the_voice_is_announced():
    bar = _bar()
    start = bar.index("gespraechAn = true\n      vadFehlrunden = 0")
    opening = bar.index("await gespraechMikroOeffnen()", start)
    announcing = bar.index("voiceKeepStart()", start)
    assert opening < announcing


def test_every_round_opens_through_the_same_door_and_the_end_frees_the_device():
    bar = _bar()
    rounds = re.search(r"async function gespraechZuhoeren\(\) \{(.*?)\n  \}", bar, re.S)
    assert rounds is not None and "gespraechMikroOeffnen()" in rounds.group(1)
    ending = re.search(r"function gespraechBeenden\([^)]*\) \{(.*?)\n  \}", bar, re.S)
    assert ending is not None
    assert "aufnahmeSchliessen()" in ending.group(1) and "vadRundenUhrStoppen()" in ending.group(1)
    assert "if (gespraechAn) aufnahmeSchliessen()" in bar


def test_the_rounds_fifteen_seconds_run_on_a_clock_and_not_on_the_blocks():
    bar = _bar()
    assert "setTimeout(gespraechRundeAblaufen, GESPRAECH_RUNDE_STILLE_MS)" in bar
    level = re.search(r"function gespraechPegel\(pegel\) \{(.*?)\n  \}", bar, re.S)
    assert level is not None and "GESPRAECH_RUNDE_STILLE_MS" not in level.group(1)
    expiring = re.search(r"function gespraechRundeAblaufen\(\) \{(.*?)\n  \}", bar, re.S)
    assert expiring is not None
    assert "GESPRAECH_MIN_SPRACH_MS" in expiring.group(1)
    assert "gespraechRundeOhneSatz()" in expiring.group(1)
    sentence = re.search(r"async function gespraechSatzFertig\(blob\) \{(.*?)\n    if", bar, re.S)
    assert sentence is not None and "vadRundenUhrStoppen()" in sentence.group(1)
