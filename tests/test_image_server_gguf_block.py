"""The picture server's importance matrix switch and the state of each model
file: one switch for every file, on until it is turned off and kept over a
restart of the service; the model file list says whether pictures add to the
matrix and which type a converted file is (app/bildgeraete.py,
app/api/v1/image_tools.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import bildgeraete
from app.api.v1.image_tools import ImatrixWish
from app.bildrunner import Bildrunner, imatrix_path
from app.config import Config
from app.main import app_erstellen

MODEL = "base.safetensors"


def _folder(config: Config, tmp_path: Path, *names: str) -> Path:
    folder = tmp_path / "bildmodelle"
    config.app.bildmodelle_verzeichnis = str(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"x")
    return folder


def _draw_commands(client: TestClient, monkeypatch) -> list[list[str]]:
    """The sd-cli command every picture is drawn with, one per request."""
    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    commands: list[list[str]] = []

    def _draw(self, job, target):
        commands.append(self.befehl(job, target))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"PNG")
        return target

    monkeypatch.setattr(Bildrunner, "erzeugen", _draw)
    return commands


def _picture(client: TestClient) -> None:
    assert client.post("/api/v1/bild", json={"prompt": "x", "modell": MODEL}).status_code == 201


def _switch(client: TestClient, on: bool):
    return client.post("/api/v1/bild/imatrix", json={"on": on})


def test_the_matrix_is_collected_without_any_stored_value(config, client, tmp_path, monkeypatch):
    folder = _folder(config, tmp_path, MODEL)
    commands = _draw_commands(client, monkeypatch)
    assert bildgeraete.Geraete().imatrix is True
    _picture(client)
    command = commands[-1]
    at = command.index("--imat-out")
    assert command[at + 1] == str(imatrix_path(folder / MODEL))
    assert command[at + 1].endswith(f"{MODEL}.imatrix.dat")
    # The list says a matrix is being collected where one lies beside the file.
    assert client.get("/api/v1/bild/model-files").json()[0]["collecting_imatrix"] is False
    imatrix_path(folder / MODEL).write_bytes(b"M")
    entry = client.get("/api/v1/bild/model-files").json()[0]
    assert (entry["collecting_imatrix"], entry["has_imatrix"]) == (True, True)


def test_the_switch_off_stops_collecting_and_stays_off_after_a_new_start(config, client, tmp_path, monkeypatch):
    folder = _folder(config, tmp_path, MODEL)
    imatrix_path(folder / MODEL).write_bytes(b"M")
    commands = _draw_commands(client, monkeypatch)
    assert client.get("/api/v1/bild/model-files").json()[0]["collecting_imatrix"] is True
    assert _switch(client, False).json() is False
    _picture(client)
    assert "--imat-out" not in commands[-1]
    # Off: nothing is collected, though the matrix of earlier pictures still lies there.
    entry = client.get("/api/v1/bild/model-files").json()[0]
    assert (entry["collecting_imatrix"], entry["has_imatrix"]) == (False, True)
    # A new start of the service: a second application over the same data.
    with TestClient(app_erstellen(config)) as again:
        again.headers["X-Sitzungsschluessel"] = again.app.state.sitzungsschluessel
        assert again.get("/api/v1/bild/model-files").json()[0]["collecting_imatrix"] is False
        _picture(again)
        assert "--imat-out" not in commands[-1]
        # And on again: the next picture collects, and so does the list.
        assert _switch(again, True).json() is True
        _picture(again)
        assert "--imat-out" in commands[-1]
        assert again.get("/api/v1/bild/model-files").json()[0]["collecting_imatrix"] is True


def test_the_switch_takes_no_file_name_and_is_stored_with_the_machine_s_settings(client):
    assert set(ImatrixWish.model_fields) == {"on"}
    _switch(client, False)
    stored = client.get("/api/v1/settings/global/bildgeraete").json()
    assert stored["wert"]["imatrix"] is False
    # The other fields of the row stay as they were.
    client.put("/api/v1/settings/global/bildgeraete", json={"wert": {"threads": 3, "imatrix": False}})
    _switch(client, True)
    assert client.get("/api/v1/settings/global/bildgeraete").json()["wert"] == {"threads": 3, "imatrix": True}


def test_a_stored_value_that_is_no_off_is_the_default():
    assert bildgeraete.pruefen({"imatrix": "no"}) == {"imatrix": True}
    assert bildgeraete.pruefen({"imatrix": None}) == {"imatrix": True}
    assert bildgeraete.pruefen({"imatrix": False}) == {"imatrix": False}


def test_the_list_names_the_type_of_a_converted_file_by_its_name(config, client, tmp_path):
    _folder(config, tmp_path, MODEL, "base.q8_0.gguf", "base.q4_K.gguf", "other.safetensors", "plain.gguf")
    files = {entry["name"]: entry for entry in client.get("/api/v1/bild/model-files").json()}
    # Only the copy carries a type; the source does not list its copies.
    assert files["base.q8_0.gguf"]["gguf_type"] == "q8_0"
    assert files["base.q4_K.gguf"]["gguf_type"] == "q4_K"
    assert files[MODEL]["gguf_type"] is None
    assert files["other.safetensors"]["gguf_type"] is None
    assert files["plain.gguf"]["gguf_type"] is None


def test_a_picture_the_running_server_draws_is_not_pushed_to_sd_cli_by_the_matrix(client):
    """The matrix is on from the start; it must not make every picture an
    sd-cli picture, or the server would never draw one."""
    answer = client.post("/api/v1/bild/turbo/reason", json={"modell": MODEL})
    assert answer.status_code == 200
    assert answer.json()["control"] is None


def test_the_old_words_are_gone_from_both_languages():
    root = Path(__file__).resolve().parent.parent / "app" / "locales"
    for language in ("de", "en"):
        text = (root / f"{language}.json").read_text(encoding="utf-8").lower()
        assert "wichtigkeitsmatrix" not in text and "importance matrix" not in text, language


@pytest.mark.parametrize("name", ["imatrix_models", "toggleImatrix"])
def test_no_trace_of_the_per_file_switch_is_left(name):
    root = Path(__file__).resolve().parent.parent
    for path in (root / "app").rglob("*.py"):
        assert name not in path.read_text(encoding="utf-8"), path
    for path in (root / "frontend" / "src").rglob("*.svelte"):
        assert name not in path.read_text(encoding="utf-8"), path
