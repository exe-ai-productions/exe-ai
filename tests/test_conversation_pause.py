"""The silence that ends a spoken sentence of a conversation is the user's
number of seconds (frontend/src/lib/conversationPause.js), kept by the
service (app/diktatsprachewahl.py) and set in the speech server window.

The module runs in node, like tests/test_sprechtext.py: what is asserted is
what the real file returns."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import diktatsprachewahl

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "frontend/src/lib/conversationPause.js"
SETTING = "/api/v1/settings/global/diktat"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")


def _run(script: str):
    source = re.sub(r"^export ", "", MODULE.read_text(encoding="utf-8"), flags=re.M)
    run = subprocess.run(["node", "-e", f"{source}\n{script}"], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _ended_after(seconds, step_ms: int = 100, limit_ms: int = 20000) -> int:
    """A clock that runs in blocks of `step_ms` of silence: after how many
    milliseconds does the pause end the sentence?"""
    script = f"""
let silence = 0;
const seconds = {json.dumps(seconds)};
while (!pauseElapsed(silence, seconds) && silence < {limit_ms}) silence += {step_ms};
console.log(JSON.stringify(silence));
"""
    return _run(script)


@needs_node
def test_the_pause_from_the_setting_decides_the_silence():
    assert _ended_after(1.5) == 1500
    assert _ended_after(5) == 5000
    assert _ended_after(0.4) == 400


@needs_node
def test_an_empty_field_is_the_works_three_seconds():
    assert _ended_after(None) == 3000


@needs_node
def test_a_number_that_is_not_a_pause_is_the_works_answer():
    for bad in (0, -1, "2", None):
        assert _ended_after(bad) == 3000


@needs_node
def test_the_works_number_of_the_page_is_the_services_own():
    assert _run("console.log(JSON.stringify(PAUSE_DEFAULT_SECONDS))") == diktatsprachewahl.VORGABE[
        "conversation_pause_seconds"
    ]


def test_the_service_keeps_any_number_above_zero():
    assert diktatsprachewahl.wahl_pruefen({"conversation_pause_seconds": 1.5}) == {
        "conversation_pause_seconds": 1.5
    }
    assert diktatsprachewahl.wahl_pruefen({"conversation_pause_seconds": 12}) == {
        "conversation_pause_seconds": 12.0
    }


def test_zero_negative_and_no_number_are_not_stored():
    for bad in (0, -0.5, -3, "3", True, None, float("inf"), float("nan")):
        assert diktatsprachewahl.wahl_pruefen({"conversation_pause_seconds": bad}) == {}, bad


def test_the_works_pause_is_three_seconds_and_a_stored_one_is_read_back(client: TestClient):
    shown = client.get("/api/v1/sprachserver").json()["diktat_vorgaben"]
    assert shown["conversation_pause_seconds"] == 3.0
    client.put(SETTING, json={"wert": {"conversation_pause_seconds": 1.5}})
    stored = client.get("/api/v1/settings/resolved/diktat").json()["wert"]
    assert stored["conversation_pause_seconds"] == 1.5
    # Written empty, the stored number is taken away and the works one stands.
    client.put(SETTING, json={"wert": {"conversation_pause_seconds": None}})
    stored = client.get("/api/v1/settings/resolved/diktat").json()["wert"]
    assert "conversation_pause_seconds" not in stored


def test_the_conversation_uses_the_setting_and_not_a_fixed_silence():
    bar = (ROOT / "frontend/src/teile/Eingabeleiste.svelte").read_text(encoding="utf-8")
    assert "pauseElapsed(vadStilleMs, diktat.conversation_pause_seconds)" in bar
    assert "GESPRAECH_STILLE_MS" not in bar
    # What stays: the speech floor and the round.
    assert "const GESPRAECH_MIN_SPRACH_MS = 300" in bar
    assert "const GESPRAECH_RUNDE_STILLE_MS = 15000" in bar


def test_the_field_sits_directly_under_the_model_switch():
    panel = (ROOT / "frontend/src/teile/Sprachserver.svelte").read_text(encoding="utf-8")
    switch = panel.index("t('sprachserver.keep_model_loaded')")
    field = panel.index("t('sprachserver.pause_before_sending')")
    assert switch < field
    assert panel.index("t('sprachserver.feld_stimmprobe')") > field
    assert "conversation_pause_seconds: wert" in panel


def test_the_texts_stand_in_both_catalogues():
    expected = {"de": "Pause vor dem Senden", "en": "Pause before sending"}
    for language, text in expected.items():
        catalogue = json.loads((ROOT / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))
        assert catalogue["sprachserver"]["pause_before_sending"] == text
