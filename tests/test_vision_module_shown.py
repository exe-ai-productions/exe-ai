"""The vision row names the projector that goes with the start — also one the
name rule finds — and "none" switches it off and stays remembered for that
model file.

The pairing the windows read held only what the folder manifest declared. A
projector the name rule attached at the start was not in it, so the row said
"none" about a server that came up with eyes, and picking "none" on a row
that already said it changed nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import modellzuordnung
from app.modellrunner import Modellrunner

MODELS = "/api/v1/runner"
AGENT = "/api/v1/agentenmodell"


@pytest.fixture
def folder(config) -> Path:
    ordner = Path(config.app.modelle_verzeichnis)
    (ordner / "vision").mkdir(parents=True)
    (ordner / "klein.gguf").write_bytes(b"x" * 10)
    (ordner / "vision" / "klein-mmproj-Q8_0.gguf").write_bytes(b"x" * 5)
    (ordner / "gross.gguf").write_bytes(b"x" * 20)
    return ordner


def test_a_projector_only_the_name_rule_finds_stands_in_the_pairing(client: TestClient, folder):
    for route in (MODELS, AGENT):
        zuordnung = client.get(route).json()["zuordnung"]
        assert zuordnung["klein.gguf"]["mmproj"] == "klein-mmproj-Q8_0.gguf", route


def test_it_is_the_projector_the_start_command_carries(client: TestClient, folder):
    """The row and the process say the same: what the pairing names is what
    ``--mmproj`` gets."""
    runner = Modellrunner(folder, programm="llama-server")
    gezeigt = client.get(MODELS).json()["zuordnung"]["klein.gguf"]["mmproj"]
    befehl = runner.befehl("klein.gguf", 4096, 33, 8081)
    assert befehl[befehl.index("--mmproj") + 1].endswith(gezeigt)


def test_none_chosen_leaves_the_projector_off_the_command(folder):
    runner = Modellrunner(folder, programm="llama-server")
    assert "--mmproj" in runner.befehl("klein.gguf", 4096, 33, 8081)
    assert "--mmproj" not in runner.befehl("klein.gguf", 4096, 33, 8081, vision="")


def test_none_stays_remembered_for_that_file_and_reaches_the_start(client: TestClient, folder):
    from app import runnermodellwahl

    client.patch(
        "/api/v1/settings/global/runnermodell",
        json={"wert": {"module": {"klein.gguf": {"vision": ""}}}},
    )
    repositories = client.app.state.repositories
    assert runnermodellwahl.startwerte(repositories, "klein.gguf")["vision"] == ""
    # Another file nobody said anything about: still "nobody said".
    assert runnermodellwahl.startwerte(repositories, "gross.gguf")["vision"] is None


def test_the_slot_remembers_none_for_the_file_too(client: TestClient, folder):
    from app import agentenmodellwahl

    client.patch(
        "/api/v1/settings/global/agentenmodell",
        json={"wert": {"sorte": "slot", "wert": "klein.gguf",
                       "module": {"klein.gguf": {"vision": ""}}}},
    )
    repositories = client.app.state.repositories
    assert agentenmodellwahl.slot_startwerte(repositories, "klein.gguf")["vision"] == ""


def test_silence_a_model_without_a_matching_projector_has_no_pairing(client: TestClient, folder):
    for route in (MODELS, AGENT):
        zuordnung = client.get(route).json()["zuordnung"]
        assert "gross.gguf" not in zuordnung, route


def test_silence_the_declared_projector_wins_over_the_name_rule(client: TestClient, folder):
    (folder / "vision" / "klein-mmproj-F16.gguf").write_bytes(b"x" * 7)
    modellzuordnung.eintragen(folder, "klein.gguf", "mmproj", "klein-mmproj-F16.gguf")
    zuordnung = client.get(MODELS).json()["zuordnung"]
    assert zuordnung["klein.gguf"]["mmproj"] == "klein-mmproj-F16.gguf"


def test_silence_a_declared_draft_stays_beside_the_found_projector(client: TestClient, folder):
    (folder / "mtp").mkdir()
    (folder / "mtp" / "mtp-klein.gguf").write_bytes(b"x" * 5)
    modellzuordnung.eintragen(folder, "klein.gguf", "mtp", "mtp-klein.gguf")
    eintrag = client.get(MODELS).json()["zuordnung"]["klein.gguf"]
    assert eintrag["mtp"] == "mtp-klein.gguf"
    assert eintrag["mmproj"] == "klein-mmproj-Q8_0.gguf"
