"""The speech server's start values are stored, and the next start uses them.

Its file, context, GPU layers, CPU threads and port used to live in the page
only: with the server off, closing the window or restarting the program put
back 4096 / 99 / Auto / 8084 and the first file of the folder, and the next
start ran on those. They are stored in the dictation row the way the clean-up
server's are (`speech_model`, `speech_context`, `speech_gpu_layers`,
`speech_threads`, `speech_port`).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import diktatsprachewahl

ROW = "/api/v1/settings/global/diktat"
RESOLVED = "/api/v1/settings/resolved/diktat"

VALUES = {
    "speech_model": "voice-model.gguf",
    "speech_context": 8192,
    "speech_gpu_layers": 12,
    "speech_threads": 6,
    "speech_port": 8190,
}


def _fresh_client(config) -> TestClient:
    from app.main import app_erstellen

    app = app_erstellen(config)
    client = TestClient(app)
    client.__enter__()
    client.headers["X-Sitzungsschluessel"] = app.state.sitzungsschluessel
    return client


def test_the_five_values_are_stored_and_read_back(client: TestClient):
    assert client.patch(ROW, json={"wert": VALUES}).status_code == 200
    stored = client.get(RESOLVED).json()["wert"]
    for name, value in VALUES.items():
        assert stored[name] == value, name


def test_they_survive_a_restart_of_the_program(client: TestClient, config):
    client.patch(ROW, json={"wert": VALUES})
    again = _fresh_client(config)
    try:
        stored = again.get(RESOLVED).json()["wert"]
        for name, value in VALUES.items():
            assert stored[name] == value, name
    finally:
        again.__exit__(None, None, None)


def test_the_start_without_numbers_carries_the_stored_ones(client: TestClient, monkeypatch):
    client.patch(ROW, json={"wert": VALUES})
    seen: dict = {}

    def fake(modell, **kwargs):
        seen["modell"] = modell
        seen.update(kwargs)

    monkeypatch.setattr(client.app.state.sprachrunner, "starten", fake)
    answer = client.post("/api/v1/sprachserver/start", json={"modell": "voice-model.gguf"})
    assert answer.status_code == 200, answer.text
    assert seen["modell"] == "voice-model.gguf"
    assert seen["kontext"] == 8192
    assert seen["schichten"] == 12
    assert seen["port"] == 8190
    assert seen["fein"].faeden == 6


def test_what_the_request_names_beats_the_stored_value(client: TestClient, monkeypatch):
    client.patch(ROW, json={"wert": VALUES})
    seen: dict = {}
    monkeypatch.setattr(
        client.app.state.sprachrunner, "starten", lambda modell, **kw: seen.update(kw)
    )
    client.post(
        "/api/v1/sprachserver/start",
        json={"modell": "m.gguf", "kontext": 2048, "schichten": 0, "port": 8200, "threads": 2},
    )
    assert seen["kontext"] == 2048
    assert seen["schichten"] == 0
    assert seen["port"] == 8200
    assert seen["fein"].faeden == 2


def test_with_nothing_stored_the_start_goes_by_the_works_answers(client: TestClient, monkeypatch):
    """The silence check: a program that never stored a value starts exactly
    as it always did."""
    seen: dict = {}
    monkeypatch.setattr(
        client.app.state.sprachrunner, "starten", lambda modell, **kw: seen.update(kw)
    )
    client.post("/api/v1/sprachserver/start", json={"modell": "m.gguf"})
    assert seen["kontext"] == 4096
    assert seen["schichten"] is None
    assert seen["port"] is None
    assert seen["fein"].faeden is None


@pytest.mark.parametrize("bad", [100, 70000, "x", True])
def test_a_port_outside_the_range_is_not_stored(client: TestClient, bad):
    client.patch(ROW, json={"wert": {"speech_port": bad}})
    assert "speech_port" not in (client.get(RESOLVED).json()["wert"] or {})


def test_the_works_answers_are_the_ones_the_window_is_told(client: TestClient):
    shown = client.get("/api/v1/sprachserver").json()["diktat_vorgaben"]
    assert shown["speech_context"] == 4096
    assert shown["speech_gpu_layers"] is None
    assert shown["speech_threads"] == 0
    assert shown["speech_port"] is None
    assert shown["speech_model"] == ""
    assert diktatsprachewahl.vorgaben()["speech_context"] == 4096
