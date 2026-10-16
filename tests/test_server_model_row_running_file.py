"""A running server's model row names the file it holds, also when the
command line or another window started it.

The agent server's start route did not remember the file it started, so the
stored choice — all the window read — went on naming the one before; and a
model window that was open kept the file it had opened with.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

URL = "/api/v1/settings/global/agentenmodell"
REPO = Path(__file__).resolve().parent.parent


def _stored(client: TestClient) -> dict:
    return client.get(URL).json().get("wert", {})


def test_starting_another_file_makes_it_the_stored_choice(client: TestClient, config, monkeypatch):
    ordner = Path(config.app.modelle_verzeichnis)
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "a.gguf").write_bytes(b"x" * 10)
    (ordner / "b.gguf").write_bytes(b"x" * 10)
    client.put(URL, json={"wert": {"sorte": "slot", "wert": "a.gguf", "kontext": 4096}})

    runner = client.app.state.agentenrunner
    monkeypatch.setattr(runner, "starten", lambda modell, **kw: None)
    monkeypatch.setattr(runner, "lauf", lambda: None)
    client.post("/api/v1/agentenmodell/start", json={"modell": "b.gguf"})

    stored = _stored(client)
    assert (stored["sorte"], stored["wert"]) == ("slot", "b.gguf")
    # The rest of the row is not touched by it.
    assert stored["kontext"] == 4096


def test_silence_a_chosen_cloud_or_main_model_is_not_replaced_by_a_start(
    client: TestClient, monkeypatch
):
    """Starting the slot from outside is no decision about which model the
    unattended runs use."""
    runner = client.app.state.agentenrunner
    monkeypatch.setattr(runner, "starten", lambda modell, **kw: None)
    monkeypatch.setattr(runner, "lauf", lambda: None)

    client.put(URL, json={"wert": {"sorte": "kennung", "wert": "endpunkt:modell"}})
    client.post("/api/v1/agentenmodell/start", json={"modell": "b.gguf"})
    stored = _stored(client)
    assert (stored["sorte"], stored["wert"]) == ("kennung", "endpunkt:modell")

    client.put(URL, json={"wert": {"sorte": "", "wert": ""}})
    client.post("/api/v1/agentenmodell/start", json={"modell": "b.gguf"})
    assert _stored(client)["wert"] == ""


def test_silence_a_refused_start_leaves_the_choice_alone(client: TestClient, monkeypatch):
    from app.modellrunner import RunnerFehler

    client.put(URL, json={"wert": {"sorte": "slot", "wert": "a.gguf"}})

    def refuse(modell, **kw):
        raise RunnerFehler("kein_modell")

    monkeypatch.setattr(client.app.state.agentenrunner, "starten", refuse)
    antwort = client.post("/api/v1/agentenmodell/start", json={"modell": "gibtsnicht.gguf"})
    assert antwort.status_code == 404
    assert _stored(client)["wert"] == "a.gguf"


def test_silence_starting_the_chosen_file_writes_nothing_new(client: TestClient, monkeypatch):
    from app import agentenmodellwahl

    client.put(URL, json={"wert": {"sorte": "slot", "wert": "a.gguf"}})
    runner = client.app.state.agentenrunner
    monkeypatch.setattr(runner, "starten", lambda modell, **kw: None)
    monkeypatch.setattr(runner, "lauf", lambda: None)
    writes: list = []
    repositories = client.app.state.repositories
    original = repositories.einstellungen.zusammenlegen

    def recording(*args, **kwargs):
        writes.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(repositories.einstellungen, "zusammenlegen", recording)
    client.post("/api/v1/agentenmodell/start", json={"modell": "a.gguf"})
    assert [w for w in writes if w[1] == agentenmodellwahl.SCHLUESSEL] == []


def test_the_windows_name_the_running_file():
    modell = (REPO / "frontend" / "src" / "teile" / "Modellserver.svelte").read_text(
        encoding="utf-8"
    )
    assert "if (auskunft.modell && auskunft.modell !== modell) modell = auskunft.modell" in modell
    agent = (REPO / "frontend" / "src" / "teile" / "Agentserver.svelte").read_text(
        encoding="utf-8"
    )
    assert "auskunft.modell !== readFor" in agent
