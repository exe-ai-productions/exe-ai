"""The download route puts a file in the folder in force at the moment of the
request, for every kind of model and for a companion in its sub-folder: a
location moved while the service runs is the one the next download sees."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modelldownload import Fortschritt

SPEICHERORTE = "/api/v1/speicherorte"
DOWNLOAD = "/api/v1/runner/download"

KINDS = [
    ("chat", "models", "model.gguf"),
    ("einbettung", "embedding_models", "embed.gguf"),
    ("sprache", "speech_models", "voice.gguf"),
    ("bild", "image_models", "picture.safetensors"),
]


class Recorder:
    """Stands in for the download: records where it was told to put the file."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def starten(self, repo, datei, ziel=None, gehoert_zu=None, rolle=None, **kwargs):
        self.calls.append({"datei": datei, "ordner": kwargs.get("ordner"), "manifest": kwargs.get("manifest_ordner")})
        return Fortschritt(datei=datei, geladen=0, gesamt=0)

    def stand(self):
        return Fortschritt(datei="x", geladen=0, gesamt=0)


@pytest.fixture
def recorder(client) -> Recorder:
    client.app.state.modelldownload = Recorder()
    return client.app.state.modelldownload


def _fetch(client, art: str, name: str, unterordner: str | None = None) -> None:
    antwort = client.post(
        DOWNLOAD, json={"repo": "owner/repo", "datei": name, "art": art, "unterordner": unterordner}
    )
    assert antwort.status_code == 200, antwort.text


@pytest.mark.parametrize(("art", "ort", "name"), KINDS)
def test_a_download_goes_to_the_folder_in_force_and_follows_a_move_without_a_restart(
    client, recorder, tmp_path, art, ort, name
):
    first, second = tmp_path / "first", tmp_path / "second"
    client.put(f"{SPEICHERORTE}/{ort}", json={"pfad": str(first)})
    _fetch(client, art, name)
    client.put(f"{SPEICHERORTE}/{ort}", json={"pfad": str(second)})
    _fetch(client, art, name)

    assert [Path(call["ordner"]) for call in recorder.calls] == [first.resolve(), second.resolve()]
    assert [Path(call["manifest"]) for call in recorder.calls] == [first.resolve(), second.resolve()]


def test_a_companion_lands_in_its_sub_folder_of_the_moved_folder(client, recorder, tmp_path):
    moved = tmp_path / "pictures"
    client.put(f"{SPEICHERORTE}/image_models", json={"pfad": str(moved)})
    _fetch(client, "bild", "face.safetensors", "adetailer")
    call = recorder.calls[0]
    assert Path(call["ordner"]) == moved.resolve() / "adetailer"
    # The manifest stays with the model folder, not with the companion's.
    assert Path(call["manifest"]) == moved.resolve()


def test_silence_without_a_move_the_download_goes_to_the_installed_folder(client, recorder):
    _fetch(client, "bild", "picture.safetensors")
    shown = {row["name"]: row for row in client.get(SPEICHERORTE).json()}["image_models"]
    assert Path(recorder.calls[0]["ordner"]) == Path(shown["standard"]).resolve()
    assert shown["ist_standard"] is True


def test_a_reset_sends_the_next_download_back_to_the_installed_folder(client, recorder, tmp_path):
    client.put(f"{SPEICHERORTE}/models", json={"pfad": str(tmp_path / "away")})
    client.delete(f"{SPEICHERORTE}/models")
    _fetch(client, "chat", "model.gguf")
    shown = {row["name"]: row for row in client.get(SPEICHERORTE).json()}["models"]
    assert Path(recorder.calls[0]["ordner"]) == Path(shown["standard"]).resolve()
