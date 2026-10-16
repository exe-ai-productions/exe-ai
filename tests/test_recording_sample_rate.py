"""The dictation recording starts even when the browser refuses 16 kHz.

``lib/aufnahme.svelte.js`` asks the audio context for 16 kHz. A browser may
refuse (the constructor throws ``NotSupportedError``); the recording then
starts at the rate the device runs at, the WAV header carries that rate and
the longest recording follows it. The module is compiled with the Svelte
compiler (it uses runes) and run in Node against a stand-in audio context.
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

const constructed = []
let refuseRate = false
let failWith = null
class FakeContext {
  constructor(options) {
    constructed.push(options ?? null)
    if (failWith) throw Object.assign(new Error('failed'), { name: failWith })
    if (options && options.sampleRate && refuseRate) {
      throw Object.assign(new Error('rate'), { name: 'NotSupportedError' })
    }
    this.sampleRate = options?.sampleRate ?? 48000
    this.audioWorklet = { addModule: async () => {} }
    this.destination = {}
  }
  async resume() {}
  createMediaStreamSource() { return { connect() {}, disconnect() {} } }
  createGain() { return { gain: {}, connect() {}, disconnect() {} } }
  close() {}
}
const nodes = []
class FakeNode {
  constructor() { this.port = { close() {}, onmessage: null }; nodes.push(this) }
  connect() {}
  disconnect() {}
}
globalThis.AudioContext = FakeContext
globalThis.AudioWorkletNode = FakeNode
let micError = null
Object.defineProperty(globalThis, 'navigator', {
  configurable: true,
  value: {
    mediaDevices: {
      getUserMedia: async () => {
        if (micError) throw Object.assign(new Error('mic'), { name: micError })
        return { getTracks: () => [{ stop() {} }] }
      },
    },
  },
})
let tick = null
let now = 0
globalThis.setInterval = (fn) => { tick = fn; return 1 }
globalThis.clearInterval = () => {}
performance.now = () => now

const m = await import('./%(built)s')
const rateOf = async (blob) => new DataView(await blob.arrayBuffer()).getUint32(24, true)
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


def test_a_refused_rate_starts_at_the_rate_of_the_device():
    report = _run("""
    refuseRate = true
    await m.starten()
    const running = m.aufnahme.laeuft
    now = 86000
    tick()
    const stillRunning = m.aufnahme.laeuft
    now = 88000
    tick()
    const stopped = !m.aufnahme.laeuft
    return { constructed, running, stillRunning, stopped }
""")

    assert report["constructed"] == [{"sampleRate": 16000}, None]
    assert report["running"] is True
    # The ceiling follows the rate the context came up at: 87 s at 48 kHz.
    assert report["stillRunning"] is True
    assert report["stopped"] is True


def test_the_header_of_that_recording_carries_the_device_rate():
    report = _run("""
    refuseRate = true
    await m.starten()
    // A recording that heard nothing gives no file; one block is enough.
    nodes[nodes.length - 1].port.onmessage({ data: new Float32Array(128).fill(0.25) })
    return { rate: await rateOf(m.stoppen()) }
""")

    assert report["rate"] == 48000


def test_silence_an_accepted_rate_builds_the_context_once_and_runs_at_16_khz():
    report = _run("""
    await m.starten()
    now = 239000
    tick()
    const stillRunning = m.aufnahme.laeuft
    now = 241000
    tick()
    return { constructed, stillRunning, stopped: !m.aufnahme.laeuft }
""")

    assert report["constructed"] == [{"sampleRate": 16000}]
    assert report["stillRunning"] is True
    assert report["stopped"] is True


def test_silence_a_refused_microphone_ends_the_start_as_before():
    report = _run("""
    micError = 'NotAllowedError'
    let name = null
    try { await m.starten() } catch (error) { name = error.name }
    return { name, constructed, running: m.aufnahme.laeuft }
""")

    assert report == {"name": "NotAllowedError", "constructed": [], "running": False}


def test_silence_another_failure_of_the_context_is_not_retried():
    report = _run("""
    failWith = 'InvalidStateError'
    let name = null
    try { await m.starten() } catch (error) { name = error.name }
    return { name, constructed, running: m.aufnahme.laeuft }
""")

    assert report["name"] == "InvalidStateError"
    assert report["constructed"] == [{"sampleRate": 16000}]
    assert report["running"] is False
