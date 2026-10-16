"""The speech, clean-up and conversation-voice models take no layer count
unless one is typed: an empty GPU-layer field means Auto.

Before, 99 always went out — to `llama-server` for the speech and clean-up
servers, to `llama-tts` for a spoken sentence, and to the kept voice. Now
nothing named means no `--n-gpu-layers`; the kept voice's C interface has no
"auto", so it loads with all layers (-1) instead.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import diktatsprachewahl, stimme
from app.voice_worker import ALL_LAYERS
from tests.test_voice_routes import HOLD, SETTING, SPEAK, _voice_files, plain, voice  # noqa: F401

RESOLVED = "/api/v1/settings/resolved/diktat"


def _capture(client: TestClient, monkeypatch, runner_name: str) -> dict:
    seen: dict = {}
    monkeypatch.setattr(
        getattr(client.app.state, runner_name), "starten", lambda modell, **kw: seen.update(kw)
    )
    return seen


def test_the_works_answers_say_auto_for_all_three(client: TestClient):
    shown = diktatsprachewahl.vorgaben()
    assert shown["speech_gpu_layers"] is None
    assert shown["putzschichten"] is None
    assert shown["stimmschichten"] is None


# --- the speech server -------------------------------------------------------


def test_the_speech_server_starts_without_a_count(client: TestClient, monkeypatch):
    seen = _capture(client, monkeypatch, "sprachrunner")
    client.post("/api/v1/sprachserver/start", json={"modell": "m.gguf"})
    assert seen["schichten"] is None


def test_a_stored_count_goes_out_and_a_cleared_one_does_not(client: TestClient, monkeypatch):
    seen = _capture(client, monkeypatch, "sprachrunner")
    client.patch(SETTING, json={"wert": {"speech_gpu_layers": 20}})
    client.post("/api/v1/sprachserver/start", json={"modell": "m.gguf"})
    assert seen["schichten"] == 20
    # The emptied field: null takes the value out (the works answer, Auto, stands).
    assert client.patch(SETTING, json={"wert": {"speech_gpu_layers": None}}).status_code == 200
    assert "speech_gpu_layers" not in client.get(RESOLVED).json()["wert"]
    client.post("/api/v1/sprachserver/start", json={"modell": "m.gguf"})
    assert seen["schichten"] is None


def test_zero_layers_stays_a_count(client: TestClient, monkeypatch):
    seen = _capture(client, monkeypatch, "sprachrunner")
    client.patch(SETTING, json={"wert": {"speech_gpu_layers": 0}})
    client.post("/api/v1/sprachserver/start", json={"modell": "m.gguf"})
    assert seen["schichten"] == 0


# --- the clean-up server -----------------------------------------------------


def test_the_cleanup_server_starts_without_a_count(client: TestClient, monkeypatch):
    seen = _capture(client, monkeypatch, "sprachputzrunner")
    client.post("/api/v1/bereinigungsserver/start", json={"modell": "m.gguf"})
    assert seen["schichten"] is None


def test_the_cleanup_servers_stored_count_goes_out_until_it_is_cleared(
    client: TestClient, monkeypatch,
):
    seen = _capture(client, monkeypatch, "sprachputzrunner")
    client.patch(SETTING, json={"wert": {"putzschichten": 12}})
    client.post("/api/v1/bereinigungsserver/start", json={"modell": "m.gguf"})
    assert seen["schichten"] == 12
    client.patch(SETTING, json={"wert": {"putzschichten": None}})
    client.post("/api/v1/bereinigungsserver/start", json={"modell": "m.gguf"})
    assert seen["schichten"] is None


# --- the voice of the conversation -------------------------------------------


def test_llama_tts_gets_no_flag_without_a_count(client: TestClient, monkeypatch):
    folder = _voice_files(client)
    seen: dict = {}
    monkeypatch.setattr(
        stimme, "programm_finden", lambda llama_server: folder / "llama-tts"
    )
    monkeypatch.setattr(
        stimme, "sprechen", lambda *a, **kw: seen.update(kw) or b"RIFF"
    )
    answer = client.post(SPEAK, json={"text": "Hallo."})
    assert answer.status_code == 200
    assert seen["schichten"] is None


def test_llama_tts_gets_the_stored_count(client: TestClient, monkeypatch):
    folder = _voice_files(client, stimmschichten=30)
    seen: dict = {}
    monkeypatch.setattr(stimme, "programm_finden", lambda llama_server: folder / "llama-tts")
    monkeypatch.setattr(stimme, "sprechen", lambda *a, **kw: seen.update(kw) or b"RIFF")
    client.post(SPEAK, json={"text": "Hallo."})
    assert seen["schichten"] == 30


def test_the_kept_voice_loads_all_layers_where_none_is_named(client: TestClient, voice):  # noqa: F811
    _voice_files(client)
    assert client.post(HOLD).json() == {"kept": True}
    assert voice.held[0].gpu_layers == ALL_LAYERS == -1


def test_the_kept_voice_loads_a_named_count_as_named(client: TestClient, voice):  # noqa: F811
    _voice_files(client, stimmschichten=40)
    client.post(HOLD)
    assert voice.held[0].gpu_layers == 40


def test_an_emptied_voice_field_goes_back_to_auto(client: TestClient):
    client.patch(SETTING, json={"wert": {"stimmschichten": 40}})
    client.patch(SETTING, json={"wert": {"stimmschichten": None}})
    assert "stimmschichten" not in client.get(RESOLVED).json()["wert"]
    assert diktatsprachewahl.stimmspeicher(client.app.state.repositories)[0] is None
