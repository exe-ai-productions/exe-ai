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
    # The round's wait and the number of rounds are the user's too: no
    # number of the round stands fixed in the bar any more.
    assert "GESPRAECH_RUNDE_STILLE_MS" not in bar and "GESPRAECH_RUNDEN_ENDE" not in bar
    assert "roundMs(diktat.conversation_wait_seconds)" in bar
    assert "silentRounds(diktat.conversation_silent_rounds)" in bar


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


# --- the round's wait and the rounds without speech ----------------------------


def _calc(expression: str):
    return _run(f"console.log(JSON.stringify({expression}))")


@needs_node
def test_the_users_wait_and_rounds_come_back_as_they_are():
    assert _calc("roundMs(20)") == 20000
    assert _calc("roundMs(0.5)") == 500
    assert _calc("silentRounds(5)") == 5
    assert _calc("silentRounds(1)") == 1


@needs_node
def test_what_is_no_wait_or_no_round_count_is_the_works_answer():
    for bad in ("0", "-3", "NaN", "Infinity", "true", "null", "undefined", '"20"'):
        assert _calc(f"roundMs({bad})") == 15000, bad
    for bad in ("0", "-1", "2.5", "NaN", "true", "null", "undefined", '"5"'):
        assert _calc(f"silentRounds({bad})") == 3, bad


@needs_node
def test_the_works_numbers_of_the_page_are_the_services_own():
    assert _calc("WAIT_DEFAULT_SECONDS") == diktatsprachewahl.VORGABE["conversation_wait_seconds"]
    assert _calc("ROUNDS_DEFAULT") == diktatsprachewahl.VORGABE["conversation_silent_rounds"]
    assert (diktatsprachewahl.VORGABE["conversation_wait_seconds"], diktatsprachewahl.VORGABE["conversation_silent_rounds"]) == (15.0, 3)


def test_the_service_keeps_the_wait_and_the_rounds_it_is_given():
    assert diktatsprachewahl.wahl_pruefen(
        {"conversation_wait_seconds": 20, "conversation_silent_rounds": 5}
    ) == {"conversation_wait_seconds": 20.0, "conversation_silent_rounds": 5}
    assert diktatsprachewahl.wahl_pruefen({"conversation_wait_seconds": 0.5}) == {
        "conversation_wait_seconds": 0.5
    }


def test_a_wait_or_round_count_that_is_no_choice_is_not_stored():
    for bad in (0, -1, True, "abc", None, float("inf"), float("nan")):
        assert diktatsprachewahl.wahl_pruefen({"conversation_wait_seconds": bad}) == {}, bad
    for bad in (0, -1, True, "abc", None, 2.5, 3.0, float("nan")):
        assert diktatsprachewahl.wahl_pruefen({"conversation_silent_rounds": bad}) == {}, bad


def test_the_works_wait_and_rounds_are_read_back_and_a_stored_one_is_taken_away(client: TestClient):
    shown = client.get("/api/v1/sprachserver").json()["diktat_vorgaben"]
    assert shown["conversation_wait_seconds"] == 15.0
    assert shown["conversation_silent_rounds"] == 3
    client.put(SETTING, json={"wert": {"conversation_wait_seconds": 4, "conversation_silent_rounds": 2}})
    stored = client.get("/api/v1/settings/resolved/diktat").json()["wert"]
    assert stored["conversation_wait_seconds"] == 4.0
    assert stored["conversation_silent_rounds"] == 2
    # The pause is untouched by either.
    assert "conversation_pause_seconds" not in stored
    client.put(SETTING, json={"wert": {"conversation_wait_seconds": None, "conversation_silent_rounds": None}})
    stored = client.get("/api/v1/settings/resolved/diktat").json()["wert"]
    assert "conversation_wait_seconds" not in stored
    assert "conversation_silent_rounds" not in stored


def test_the_two_fields_sit_directly_under_the_pause_in_both_windows():
    panel = (ROOT / "frontend/src/teile/Sprachserver.svelte").read_text(encoding="utf-8")
    pause = panel.index("t('sprachserver.pause_before_sending')")
    wait = panel.index("t('sprachserver.wait_for_speech')")
    rounds = panel.index("t('sprachserver.rounds_without_speech')")
    assert pause < wait < rounds < panel.index("t('sprachserver.feld_stimmprobe')")
    assert "conversation_wait_seconds: value" in panel and "conversation_silent_rounds: value" in panel
    phone = (ROOT / "frontend/src/phone/servers/SpeechSettings.svelte").read_text(encoding="utf-8")
    pause = phone.index("t('sprachserver.pause_before_sending')")
    wait = phone.index("t('sprachserver.wait_for_speech')")
    rounds = phone.index("t('sprachserver.rounds_without_speech')")
    assert pause < wait < rounds < phone.index("t('sprachserver.feld_stimmprobe')")


def test_the_new_texts_stand_in_both_catalogues_and_the_old_one_is_gone():
    expected = {
        "de": ("Auf Spracheingabe warten", "Spracheingabe-Runden", "Keine Antwort; das Gespräch wird beendet."),
        "en": ("Wait for speech input", "Speech input rounds", "No response; the conversation is ending."),
    }
    for language, (wait, rounds, ending) in expected.items():
        catalogue = json.loads((ROOT / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))
        assert catalogue["sprachserver"]["wait_for_speech"] == wait
        assert catalogue["sprachserver"]["rounds_without_speech"] == rounds
        assert catalogue["sprache"]["conversation_no_response"] == ending
        assert "gespraech_drei_runden" not in catalogue["sprache"]
