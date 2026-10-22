"""The speech server names the projector a start would take: the one the folder
manifest pairs first, the one the name rule finds second.

`GET /api/v1/sprachserver` carries `projektoren` per model. The card's
"no projector" hint and the Wired Memory row read it, so it has to agree with
the start, which asks the manifest before the name rule.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import modellzuordnung


def _folder(client: TestClient) -> Path:
    folder = Path(client.get("/api/v1/sprachserver").json()["ordner"])
    (folder / "vision").mkdir(parents=True, exist_ok=True)
    return folder


def _model(folder: Path, name: str) -> None:
    (folder / name).write_bytes(b"x" * 10)


def _projector(folder: Path, name: str) -> None:
    (folder / "vision" / name).write_bytes(b"x" * 10)


def test_a_projector_the_manifest_pairs_is_named_whatever_its_file_is_called(
    client: TestClient,
):
    folder = _folder(client)
    _model(folder, "listener.gguf")
    _projector(folder, "other-mmproj-F16.gguf")
    modellzuordnung.eintragen(folder, "listener.gguf", "mmproj", "other-mmproj-F16.gguf")
    answer = client.get("/api/v1/sprachserver").json()
    assert answer["projektoren"] == {"listener.gguf": "other-mmproj-F16.gguf"}
    # The row of Wired Memory reads the size of exactly this file.
    assert "other-mmproj-F16.gguf" in answer["projector_size_gb"]


def test_the_manifest_wins_over_the_name_rule(client: TestClient):
    folder = _folder(client)
    _model(folder, "listener.gguf")
    _projector(folder, "listener-mmproj-F16.gguf")
    _projector(folder, "other-mmproj-F16.gguf")
    modellzuordnung.eintragen(folder, "listener.gguf", "mmproj", "other-mmproj-F16.gguf")
    answer = client.get("/api/v1/sprachserver").json()
    assert answer["projektoren"]["listener.gguf"] == "other-mmproj-F16.gguf"


def test_silence_without_a_manifest_the_name_rule_finds_the_projector(
    client: TestClient,
):
    folder = _folder(client)
    _model(folder, "listener.gguf")
    _projector(folder, "listener-mmproj-F16.gguf")
    answer = client.get("/api/v1/sprachserver").json()
    assert answer["projektoren"] == {"listener.gguf": "listener-mmproj-F16.gguf"}


def test_silence_a_model_with_no_projector_at_all_has_none(client: TestClient):
    folder = _folder(client)
    _model(folder, "listener.gguf")
    _projector(folder, "other-mmproj-F16.gguf")
    answer = client.get("/api/v1/sprachserver").json()
    assert answer["projektoren"] == {"listener.gguf": None}


def test_the_start_takes_the_same_projector_the_answer_names(client: TestClient):
    folder = _folder(client)
    _model(folder, "listener.gguf")
    _projector(folder, "other-mmproj-F16.gguf")
    modellzuordnung.eintragen(folder, "listener.gguf", "mmproj", "other-mmproj-F16.gguf")
    runner = client.app.state.sprachrunner
    named = client.get("/api/v1/sprachserver").json()["projektoren"]["listener.gguf"]
    assert runner.projektor_fuer("listener.gguf") == folder / "vision" / named


def test_a_manifest_projector_that_was_deleted_falls_back_to_the_name_rule(
    client: TestClient,
):
    folder = _folder(client)
    _model(folder, "listener.gguf")
    _projector(folder, "listener-mmproj-F16.gguf")
    modellzuordnung.eintragen(folder, "listener.gguf", "mmproj", "gone.gguf")
    answer = client.get("/api/v1/sprachserver").json()
    assert answer["projektoren"] == {"listener.gguf": "listener-mmproj-F16.gguf"}
