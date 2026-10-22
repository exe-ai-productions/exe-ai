"""The page Configuration shows and saves the file the service read.

A service started with ``EXE_AI_CONFIG`` reads its configuration from that
file. The page used to take the ``config.yaml`` in the data folder instead:
empty when there is none, a stranger's file when there is one, and a save
went to a place the service never looks at. One rule now (``config_file``),
asked by the page and by the provider routes alike. The credentials are not
part of it: the ``.env`` stays in the data folder.
"""

from __future__ import annotations

import pytest

from app import paketierung
from app.config import config_file

ELSEWHERE_TEXT = "app:\n  port: 8095\nendpoints: []\n"


@pytest.fixture
def data_folder(tmp_path, monkeypatch):
    """The user's data folder redirected, so no test touches the project's
    own files; the variable starts unset."""
    folder = tmp_path / "userdata"
    folder.mkdir()
    monkeypatch.setattr(paketierung, "daten", lambda: folder)
    monkeypatch.delenv("EXE_AI_CONFIG", raising=False)
    return folder


@pytest.fixture
def elsewhere(tmp_path, monkeypatch, data_folder):
    """A configuration of its own, far from the data folder."""
    file = tmp_path / "elsewhere" / "config.yaml"
    file.parent.mkdir()
    file.write_text(ELSEWHERE_TEXT, encoding="utf-8")
    monkeypatch.setenv("EXE_AI_CONFIG", str(file))
    return file


def test_the_page_shows_the_file_the_service_read(client, elsewhere, data_folder):
    answer = client.get("/api/v1/dateien/konfiguration")

    assert answer.status_code == 200, answer.text
    assert answer.json()["inhalt"] == ELSEWHERE_TEXT
    assert not (data_folder / "config.yaml").exists()


def test_saving_writes_the_file_the_service_read(client, elsewhere, data_folder):
    answer = client.put("/api/v1/dateien/konfiguration", json={"inhalt": "app:\n  port: 8096\n"})

    assert answer.status_code == 200, answer.text
    assert elsewhere.read_text(encoding="utf-8") == "app:\n  port: 8096\n"
    assert (elsewhere.parent / "config.yaml.vorher").read_text(encoding="utf-8") == ELSEWHERE_TEXT
    assert not (data_folder / "config.yaml").exists()
    assert not (data_folder / "config.yaml.vorher").exists()


def test_silence_without_an_own_file_the_data_folder_stays(client, data_folder):
    own = data_folder / "config.yaml"
    own.write_text("endpoints: []\n", encoding="utf-8")

    assert client.get("/api/v1/dateien/konfiguration").json()["inhalt"] == "endpoints: []\n"
    client.put("/api/v1/dateien/konfiguration", json={"inhalt": "endpoints: []\napp: {}\n"})

    assert own.read_text(encoding="utf-8") == "endpoints: []\napp: {}\n"
    assert (data_folder / "config.yaml.vorher").read_text(encoding="utf-8") == "endpoints: []\n"
    assert config_file(client.app.state.config) == own.resolve()


def test_a_provider_is_written_into_the_file_the_service_read(client, elsewhere, data_folder):
    answer = client.post(
        "/api/v1/providers",
        json={
            "art": "eigen",
            "kennung": "eigene",
            "url": "http://127.0.0.1:9/v1",
            "schluessel": "sk-test-1234",
        },
    )

    assert answer.status_code in (200, 201), answer.text
    assert "eigene" in elsewhere.read_text(encoding="utf-8")
    assert not (data_folder / "config.yaml").exists()


@pytest.mark.parametrize("own_file", [False, True])
def test_the_credentials_stay_in_the_data_folder_with_or_without_an_own_file(
    client, data_folder, tmp_path, monkeypatch, own_file
):
    if own_file:
        other = tmp_path / "elsewhere.yaml"
        other.write_text(ELSEWHERE_TEXT, encoding="utf-8")
        monkeypatch.setenv("EXE_AI_CONFIG", str(other))
    (data_folder / ".env").write_text("A_KEY=1\n", encoding="utf-8")

    read = client.get("/api/v1/dateien/zugangsdaten")
    client.put("/api/v1/dateien/zugangsdaten", json={"inhalt": "A_KEY=2\n"})

    assert read.json()["inhalt"] == "A_KEY=1\n"
    assert (data_folder / ".env").read_text(encoding="utf-8") == "A_KEY=2\n"


def test_an_unknown_name_is_a_404(client, elsewhere):
    assert client.get("/api/v1/dateien/gibtsnicht").status_code == 404
