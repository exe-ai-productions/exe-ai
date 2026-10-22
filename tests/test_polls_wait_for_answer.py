"""The pages that ask the service on a beat start a round only when the one
before it has answered.

A plain timer asked again even when the last question was still on its way;
slow answers then piled up and took the connections the browser has per
machine, so every other request waited behind them. The beat is one module
(`frontend/src/lib/pollWithoutOverlap.js`), run here in node, and every page
that asks on a beat asks through it.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from tests.conftest import node_script

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend/src"
BEAT = FRONTEND / "lib/pollWithoutOverlap.js"

ohne_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")

# The places that ask the service on a beat, by file.
BEATS = [
    "teile/Speicherpille.svelte",
    "lib/serverstand.svelte.js",
    "teile/ModelleLokal.svelte",
    "teile/Modellserver.svelte",
    "teile/Agentserver.svelte",
    "teile/Bereinigungsserver.svelte",
    "teile/Sprachserver.svelte",
    "teile/Bildserver.svelte",
    "teile/LlamaCppSection.svelte",
    "teile/Katalog.svelte",
    "teile/Eingabeleiste.svelte",
    "teile/DocFolder.svelte",
    "teile/ModulAgenten.svelte",
    "teile/Serverpunkt.svelte",
    "teile/SettingsWebApp.svelte",
]
# Timers that ask nothing of the service: the reading of a stream the page
# holds open (its own lock), and the announcement that keeps a voice held.
OTHER_TIMERS = {"teile/Eingabeleiste.svelte": ("NACHLESEN_MS", "VOICE_HOLD_MS")}


def _beat() -> str:
    """The beat as a plain script: the export becomes a declaration."""
    return re.sub(r"^export (?=function)", "", BEAT.read_text(encoding="utf-8"), flags=re.M)


def _node(script: str) -> dict:
    run = node_script(script)
    assert run.returncode == 0, f"{run.stderr}\n{run.stdout}"
    return json.loads(run.stdout.strip().splitlines()[-1])


@ohne_node
def test_a_round_of_five_ticks_never_runs_twice_at_once():
    result = _node(f"""
{_beat()}
let live = 0, most = 0, starts = 0
const stop = pollWithoutOverlap(async () => {{
  starts++; live++; most = Math.max(most, live)
  await new Promise((done) => setTimeout(done, 300))
  live--
}}, 50)
setTimeout(() => {{ stop(); console.log(JSON.stringify({{ most, starts }})) }}, 1000)
""")
    # A tick every 50 ms and a round of 300 ms: three or four rounds in a
    # second, never two at a time (a plain timer started twenty).
    assert result["most"] == 1
    assert 2 <= result["starts"] <= 4


@ohne_node
def test_silence_a_quick_round_keeps_the_beat():
    result = _node(f"""
{_beat()}
let starts = 0
const stop = pollWithoutOverlap(() => {{ starts++ }}, 50)
setTimeout(() => {{ stop(); console.log(JSON.stringify({{ starts }})) }}, 520)
""")
    assert 8 <= result["starts"] <= 11


@ohne_node
def test_a_round_that_fails_does_not_stop_the_beat():
    result = _node(f"""
{_beat()}
let starts = 0
const stop = pollWithoutOverlap(async () => {{ starts++; throw new Error('refused') }}, 50)
setTimeout(() => {{ stop(); console.log(JSON.stringify({{ starts }})) }}, 420)
""")
    assert result["starts"] >= 6


@ohne_node
def test_stopping_ends_the_beat_while_a_round_is_running():
    result = _node(f"""
{_beat()}
let starts = 0
const stop = pollWithoutOverlap(async () => {{
  starts++
  await new Promise((done) => setTimeout(done, 400))
}}, 50)
setTimeout(stop, 120)
setTimeout(() => console.log(JSON.stringify({{ starts }})), 900)
""")
    assert result["starts"] == 1


@pytest.mark.parametrize("name", BEATS)
def test_every_place_that_asks_on_a_beat_asks_through_the_shared_one(name):
    source = (FRONTEND / name).read_text(encoding="utf-8")
    assert "pollWithoutOverlap(" in source, name
    others = OTHER_TIMERS.get(name, ())
    timers = [line for line in source.splitlines() if "setInterval(" in line]
    # What is left of a plain timer asks nothing of the service.
    assert len(timers) == len(others), (name, timers)
    for line, marker in zip(timers, others, strict=True):
        assert marker in line, (name, line)
