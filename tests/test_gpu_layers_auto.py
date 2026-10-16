"""An empty GPU-layer field means Auto: no `--n-gpu-layers` goes out and
llama.cpp places the layers (and, with them, the experts of a MoE model) to
fit the memory it finds.

Before, a fixed number always went out (99 as shipped), and a cleared field
became 0 — no layer on the card at all. A number a hand puts in the field
still goes out as it stands.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import agentenmodellwahl, agentenserver, runnermodellwahl
from app.modellrunner import Modellrunner
from tests.conftest import agentenmodell_setzen
from tests.test_runner_api import StummerRunner

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def runner(tmp_path):
    (tmp_path / "klein.gguf").write_bytes(b"x")
    return Modellrunner(tmp_path, "/opt/homebrew/bin/llama-server")


def test_no_count_means_no_flag(runner):
    command = runner.befehl("klein.gguf", 4096, None, 8081)
    assert "--n-gpu-layers" not in command
    assert "--ctx-size" in command and "--port" in command


def test_a_count_goes_out_as_it_stands(runner):
    command = runner.befehl("klein.gguf", 4096, 33, 8081)
    assert command[command.index("--n-gpu-layers") + 1] == "33"
    # Where it always stood: right behind the context.
    assert command.index("--n-gpu-layers") == command.index("--ctx-size") + 2


def test_zero_is_a_count_not_an_absence(runner):
    """Zero layers on the card is a thing people ask for (processor only)."""
    command = runner.befehl("klein.gguf", 4096, 0, 8081)
    assert command[command.index("--n-gpu-layers") + 1] == "0"


# --- the main model server ---------------------------------------------------


def _model_row(client, wert):
    client.app.state.repositories.einstellungen.setzen(
        "global", runnermodellwahl.SCHLUESSEL, wert
    )


def test_model_server_nothing_stored_starts_without_a_count(client: TestClient):
    runner = StummerRunner()
    client.app.state.modellrunner = runner
    assert client.post("/api/v1/runner/start", json={"modell": "m.gguf"}).status_code == 200
    assert runner.gestartet_mit["schichten"] is None


def test_model_server_a_stored_count_goes_out(client: TestClient):
    runner = StummerRunner()
    client.app.state.modellrunner = runner
    _model_row(client, {"schichten": 33})
    client.post("/api/v1/runner/start", json={"modell": "m.gguf"})
    assert runner.gestartet_mit["schichten"] == 33


def test_model_server_a_stored_null_stays_null(client: TestClient):
    runner = StummerRunner()
    client.app.state.modellrunner = runner
    _model_row(client, {"schichten": 33})
    assert client.patch(
        "/api/v1/settings/global/runnermodell", json={"wert": {"schichten": None}}
    ).status_code == 200
    stored = client.get("/api/v1/settings/resolved/runnermodell").json()["wert"]
    assert stored.get("schichten") is None
    client.post("/api/v1/runner/start", json={"modell": "m.gguf"})
    assert runner.gestartet_mit["schichten"] is None


def test_model_server_the_window_is_told_auto_as_the_works_answer(client: TestClient):
    client.app.state.modellrunner = StummerRunner()
    assert client.get("/api/v1/runner").json()["vorgaben"]["schichten"] is None


def test_the_preload_asks_the_same_question(client: TestClient):
    """The tick that brings the main model up ahead of a cron entry reads the
    one stored answer (`startwerte`), never a number of its own."""
    assert runnermodellwahl.startwerte(client.app.state.repositories, "m.gguf")["schichten"] is None
    source = (ROOT / "app" / "modellvorlauf.py").read_text(encoding="utf-8")
    assert "runnermodellwahl.startwerte(" in source
    assert not re.search(r"schichten\s*=\s*\d", source)


# --- the agent slot ----------------------------------------------------------


def test_agent_slot_nothing_stored_starts_without_a_count(client: TestClient, monkeypatch):
    agentenmodell_setzen(client, "klein.gguf", sorte="slot")
    seen: list[dict] = []
    runner = client.app.state.agentenrunner
    monkeypatch.setattr(runner, "starten", lambda modell, **kw: seen.append(kw))
    monkeypatch.setattr(runner, "lauf", lambda: None)
    client.post("/api/v1/agentenmodell/start", json={"modell": "klein.gguf"})
    assert seen and seen[0]["schichten"] is None


def test_agent_slot_a_stored_count_goes_out(client: TestClient, monkeypatch):
    client.put(
        "/api/v1/settings/global/agentenmodell",
        json={"wert": {"an": True, "sorte": "slot", "wert": "klein.gguf", "schichten": 40}},
    )
    seen: list[dict] = []
    runner = client.app.state.agentenrunner
    monkeypatch.setattr(runner, "starten", lambda modell, **kw: seen.append(kw))
    monkeypatch.setattr(runner, "lauf", lambda: None)
    client.post("/api/v1/agentenmodell/start", json={"modell": "klein.gguf"})
    assert seen[0]["schichten"] == 40


def test_agent_slot_a_stored_null_stays_null(client: TestClient):
    client.put(
        "/api/v1/settings/global/agentenmodell",
        json={"wert": {"sorte": "slot", "wert": "klein.gguf", "schichten": 40}},
    )
    client.patch("/api/v1/settings/global/agentenmodell", json={"wert": {"schichten": None}})
    stand = agentenmodellwahl.slot_startwerte(client.app.state.repositories)
    assert stand["schichten"] is None


async def test_the_autostart_of_the_slot_starts_without_a_count(client: TestClient, monkeypatch):
    client.put(
        "/api/v1/settings/global/agentenmodell",
        json={"wert": {"an": True, "sorte": "slot", "wert": "klein.gguf"}},
    )
    seen: list[dict] = []
    runner = client.app.state.agentenrunner
    monkeypatch.setattr(runner, "laeuft", lambda: False)
    monkeypatch.setattr(runner, "starten", lambda modell, **kw: seen.append(kw))
    monkeypatch.setattr(runner, "lauf", lambda: None)
    assert await agentenserver.slot_starten_wenn_gewollt(client.app) is True
    assert seen[0]["schichten"] is None


def test_the_embedding_server_keeps_its_count(client: TestClient):
    """The silence check: the embedding server has no field and starts as it
    always did — the runner's own default stays a number."""
    import inspect

    default = inspect.signature(Modellrunner.starten).parameters["schichten"].default
    assert default == 99
