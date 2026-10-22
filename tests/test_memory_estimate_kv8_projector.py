"""The memory estimate of a server counts the 8-bit cache and the vision
projector.

The switch "KV cache · 8-bit" left the estimated number where it was, and a
projector was not in the sum. The share of the 8-bit cache is the one the
engine itself reported at its start line for one model and one window: 896 MiB
with the f16 cache, 476 MiB with 8-bit.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

LIB = Path(__file__).resolve().parent.parent / "frontend" / "src" / "lib"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")

SCRIPT = """
import { pathToFileURL } from 'node:url'
const lib = await import(process.argv[1])
const { serverAnteil, speicherSchaetzung, kvShare } = lib
const cases = JSON.parse(process.argv[2])
const out = cases.map((c) => {
  if (c.fn === 'anteil') return serverAnteil(c.dateien, c.module, c.opt)
  if (c.fn === 'schaetzung') return speicherSchaetzung(...c.args)
  if (c.fn === 'kvShare') return kvShare(c.wert)
})
console.log(JSON.stringify(out))
"""


def _run(*cases: dict) -> list:
    run = subprocess.run(
        ["node", "--input-type=module", "-e", SCRIPT, (LIB / "speicherschaetzung.js").as_uri(),
         json.dumps(list(cases))],
        capture_output=True, text=True, timeout=60,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


DATEIEN = [{"name": "m.gguf", "groesse_gb": 4.0}]


@needs_node
def test_the_8_bit_cache_takes_the_measured_share_of_the_cache():
    voll, acht = _run(
        {"fn": "schaetzung", "args": [4.0, 8192, 0]},
        {"fn": "schaetzung", "args": [4.0, 8192, 0, {"kvShare": 34 / 64}]},
    )
    assert voll["kv"] == pytest.approx(8192 * 8 * 4.0 / 1e6)
    assert acht["kv"] == pytest.approx(voll["kv"] * 476 / 896)
    # The model itself does not shrink.
    assert acht["modell"] == voll["modell"] == 4.0
    assert acht["gesamt"] == pytest.approx(4.0 + acht["kv"])


@needs_node
def test_a_projector_adds_its_file_size():
    ohne, mit = _run(
        {"fn": "anteil", "dateien": DATEIEN, "module": [], "opt": {"modell": "m.gguf", "kontext": 8192}},
        {"fn": "anteil", "dateien": DATEIEN, "module": [],
         "opt": {"modell": "m.gguf", "kontext": 8192, "vision": "mm.gguf",
                 "projectors": {"mm.gguf": 0.6}}},
    )
    assert mit["projector"] == 0.6
    assert mit["gesamt"] == pytest.approx(ohne["gesamt"] + 0.6)


@needs_node
def test_silence_no_projector_chosen_or_an_unknown_one_adds_nothing():
    leer, unbekannt, ohne = _run(
        {"fn": "anteil", "dateien": DATEIEN, "module": [],
         "opt": {"modell": "m.gguf", "kontext": 8192, "vision": "", "projectors": {"mm.gguf": 0.6}}},
        {"fn": "anteil", "dateien": DATEIEN, "module": [],
         "opt": {"modell": "m.gguf", "kontext": 8192, "vision": "fremd.gguf",
                 "projectors": {"mm.gguf": 0.6}}},
        {"fn": "anteil", "dateien": DATEIEN, "module": [], "opt": {"modell": "m.gguf", "kontext": 8192}},
    )
    assert leer == unbekannt == ohne


@needs_node
def test_silence_without_the_switch_the_number_is_the_old_one():
    alt = 4.0 + (8192 * 8 * 4.0) / 1e6
    (neu,) = _run({"fn": "anteil", "dateien": DATEIEN, "module": [],
                   "opt": {"modell": "m.gguf", "kontext": 8192}})
    assert neu["gesamt"] == pytest.approx(alt)


@needs_node
def test_each_cache_step_takes_its_share_of_the_16_bit_cache():
    """ggml keeps 32 values in 64 bytes (f16), 34 (8 bit), 22 (5 bit) and 18
    (4 bit); an unknown type counts as the 16-bit cache."""
    antworten = _run(
        {"fn": "kvShare", "wert": "f16"},
        {"fn": "kvShare", "wert": "q8_0"},
        {"fn": "kvShare", "wert": "q5_0"},
        {"fn": "kvShare", "wert": "q4_0"},
        {"fn": "kvShare", "wert": None},
    )
    assert antworten == pytest.approx([1, 34 / 64, 22 / 64, 18 / 64, 1])
    # The 8-bit share is the one the engine reported: 476 MiB against 896.
    assert antworten[1] == pytest.approx(476 / 896)


def test_both_server_answers_carry_the_projector_sizes(client: TestClient, config):
    ordner = Path(config.app.modelle_verzeichnis)
    (ordner / "vision").mkdir(parents=True)
    (ordner / "klein.gguf").write_bytes(b"x" * 10)
    (ordner / "vision" / "klein-mmproj-Q8_0.gguf").write_bytes(b"x" * 600_000_000)
    for route in ("/api/v1/runner", "/api/v1/agentenmodell"):
        groessen = client.get(route).json()["projector_size_gb"]
        assert groessen == {"klein-mmproj-Q8_0.gguf": 0.6}, route


def test_silence_without_projectors_the_sizes_are_empty(client: TestClient):
    for route in ("/api/v1/runner", "/api/v1/agentenmodell"):
        assert client.get(route).json()["projector_size_gb"] == {}, route


def test_the_windows_hand_both_to_the_estimate():
    teile = LIB.parent / "teile"
    for datei in ("Modellserver.svelte", "Agentserver.svelte"):
        quelle = (teile / datei).read_text(encoding="utf-8")
        assert "kvShare: kvShare(" in quelle, datei
        assert "projectors:" in quelle, datei
