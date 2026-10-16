"""A recording that heard nothing is no recording.

``lib/aufnahme.svelte.js`` writes a WAV from the blocks the microphone
delivered. A microphone that has not delivered one — the click came before
the first block, or the stream is silent at the source — used to leave a
44-byte header with no samples behind it, and the speech engine refuses that
file with a 400. Now ``stoppen()`` and ``zwischenstand()`` give back nothing
when there is nothing, and the callers (conversation, dictation, the reading
while somebody still speaks) already treat nothing as "no sentence". The
module is compiled with the Svelte compiler and run in Node against a
stand-in audio context.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
MODULE = FRONTEND / "src/lib/aufnahme.svelte.js"

pytestmark = pytest.mark.skipif(
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

const m = await import('./%(built)s')
// One block of the microphone, as the worklet posts it.
const block = (count) => nodes[nodes.length - 1].port.onmessage({
  data: new Float32Array(count).fill(0.25),
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


def test_a_stop_before_the_first_block_gives_nothing_and_still_ends_the_recording():
    report = _run("""
    await m.starten()
    const blob = m.stoppen()
    return { blob: blob === null, running: m.aufnahme.laeuft }
""")

    assert report == {"blob": True, "running": False}


def test_a_stop_after_one_block_gives_a_header_and_the_samples():
    report = _run("""
    await m.starten()
    block(128)
    const blob = m.stoppen()
    return { size: await size(blob), type: blob.type }
""")

    assert report == {"size": 44 + 256, "type": "audio/wav"}


def test_a_reading_with_no_new_sound_since_the_last_one_gives_nothing():
    report = _run("""
    await m.starten()
    const beforeAny = m.zwischenstand(0)
    block(128)
    const first = m.zwischenstand(0)
    const behind = m.zwischenstand(first.bis)
    block(64)
    const second = m.zwischenstand(first.bis)
    return {
      beforeAny,
      first: await size(first.blob), until: first.bis,
      behind,
      second: await size(second.blob), secondUntil: second.bis,
    }
""")

    assert report == {
        "beforeAny": None,
        "first": 44 + 256, "until": 128,
        "behind": None,
        "second": 44 + 128, "secondUntil": 192,
    }


def test_silence_a_reading_without_a_recording_is_still_nothing():
    report = _run("""
    return { reading: m.zwischenstand(0), blob: m.stoppen() }
""")

    assert report == {"reading": None, "blob": None}
