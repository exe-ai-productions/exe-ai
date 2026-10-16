"""The kept voice loads from an own, fixed copy of llama.cpp b11429 — never
from the libraries beside whatever server build is active.

A newer build changes the layout of the library's parameter blocks, and the
voice refuses a layout it was not written for. So the copy lies in a folder
of its own, the server builds' choice and clean-up do not touch it, and a
missing copy is fetched once, by itself, while ``llama-tts`` speaks.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import serverdownload, voice_library
from app.voice_library import VoiceLibrary, libraries_in
from app.voice_worker import LAYOUT_BUILD, library_names
from tests.test_voice_routes import HOLD, RELEASE, SPEAK, FakeVoice, _voice_files, plain, voice  # noqa: F401


def _libraries(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in library_names():
        (folder / name).write_bytes(b"x")


class FakeFetch:
    """The downloader, as the library sees it: calls counted, nothing fetched."""

    def __init__(self) -> None:
        self.started: list[tuple[str | None, str | None]] = []
        self.running = False
        self.refuse: str | None = None

    def laeuft(self) -> bool:
        return self.running

    def starten(self, build=None, previous=None, variante=None):
        if self.refuse:
            raise serverdownload.ServerdownloadFehler(self.refuse)
        self.started.append((build, variante))
        self.running = True


def _copy_folder(data: Path, variant: str | None = None) -> Path:
    return data / voice_library.FOLDER / serverdownload.ORDNER / serverdownload.bauordner_name(
        LAYOUT_BUILD, variant
    )


def test_the_fixed_build_is_the_one_the_worker_was_written_for():
    assert LAYOUT_BUILD == "b11429"


def test_the_libraries_are_found_below_the_folder_and_only_when_both_are_there(tmp_path):
    core, audio = library_names()
    assert libraries_in(tmp_path / "missing") is None
    deep = tmp_path / "llama-b11429" / "bin"
    deep.mkdir(parents=True)
    (deep / core).write_bytes(b"x")
    assert libraries_in(tmp_path) is None
    (deep / audio).write_bytes(b"x")
    assert libraries_in(tmp_path) == deep


def test_the_copy_lies_beside_the_server_builds_and_not_in_their_folder(tmp_path):
    folder = _copy_folder(tmp_path)
    assert folder.parent.parent.parent == tmp_path
    assert folder.parent.parent.name == voice_library.FOLDER != serverdownload.ORDNER


def test_a_present_copy_is_the_answer_and_nothing_is_fetched(tmp_path):
    _libraries(_copy_folder(tmp_path))
    fetch = FakeFetch()
    library = VoiceLibrary(tmp_path, fetch=fetch)
    assert library.directory() == _copy_folder(tmp_path)
    assert fetch.started == []


def test_a_missing_copy_starts_exactly_one_fetch_in_the_installed_variant(tmp_path):
    fetch = FakeFetch()
    library = VoiceLibrary(tmp_path, variant=lambda: "vulkan", fetch=fetch)
    for _ in range(4):
        assert library.directory() is None
    assert fetch.started == [(LAYOUT_BUILD, "vulkan")]


def test_a_copy_that_is_still_being_unpacked_is_not_handed_out(tmp_path):
    _libraries(_copy_folder(tmp_path))
    fetch = FakeFetch()
    fetch.running = True
    assert VoiceLibrary(tmp_path, fetch=fetch).directory() is None
    assert fetch.started == []


def test_a_fetch_that_brought_nothing_is_tried_again_in_the_next_conversation(tmp_path):
    fetch = FakeFetch()
    library = VoiceLibrary(tmp_path, fetch=fetch)
    library.directory()
    fetch.running = False
    assert library.directory() is None
    assert len(fetch.started) == 1
    library.conversation_over()
    library.directory()
    assert len(fetch.started) == 2


def test_a_machine_without_a_package_is_asked_once_and_the_voice_goes_the_plain_way(
    tmp_path, caplog
):
    fetch = FakeFetch()
    fetch.refuse = "kein_paket"
    library = VoiceLibrary(tmp_path, fetch=fetch)
    with caplog.at_level(logging.INFO):
        assert library.directory() is None
        assert library.directory() is None
    assert fetch.started == []
    assert sum("not fetched" in line for line in caplog.messages) == 1


def test_a_newer_server_build_does_not_change_the_copy(tmp_path):
    newer = tmp_path / serverdownload.ORDNER / "b11556"
    _libraries(newer)
    _libraries(_copy_folder(tmp_path))
    assert VoiceLibrary(tmp_path, fetch=FakeFetch()).directory() == _copy_folder(tmp_path)


def test_the_clean_up_of_the_server_builds_leaves_the_copy(tmp_path):
    """A fetch of a server build removes every other build folder — but only
    in the root it was made for."""
    server_root = tmp_path / serverdownload.ORDNER
    (server_root / "b11429").mkdir(parents=True)
    _libraries(_copy_folder(tmp_path))
    fetcher = serverdownload.Serverdownload(tmp_path)
    (server_root / "b11556").mkdir()
    fetcher._remove_other_builds("b11556")
    assert not (server_root / "b11429").exists()
    assert libraries_in(_copy_folder(tmp_path)) is not None


def test_the_service_gets_the_copys_folder_even_when_a_newer_build_is_active(
    client: TestClient, voice: FakeVoice, tmp_path
):
    _voice_files(client)
    _libraries(tmp_path / serverdownload.ORDNER / "b11556")
    _libraries(_copy_folder(tmp_path))
    client.app.state.voice_library = VoiceLibrary(tmp_path, fetch=FakeFetch())
    assert client.post(HOLD).json() == {"kept": True}
    assert voice.held[0].library_dir == str(_copy_folder(tmp_path))


def test_without_the_copy_one_fetch_starts_and_llama_tts_speaks(
    client: TestClient, voice: FakeVoice, plain: list, tmp_path
):
    _voice_files(client)
    fetch = FakeFetch()
    client.app.state.voice_library = VoiceLibrary(tmp_path, fetch=fetch)
    assert client.post(HOLD).json() == {"kept": False}
    assert client.post(HOLD).json() == {"kept": False}
    voice.running = True
    answer = client.post(SPEAK, json={"text": "Erst einmal so."})
    assert answer.content == b"RIFF-plain"
    assert plain == ["Erst einmal so."]
    assert voice.spoken == [] and fetch.started == [(LAYOUT_BUILD, None)]


def test_once_the_copy_is_there_the_next_announcement_keeps_the_voice(
    client: TestClient, voice: FakeVoice, tmp_path
):
    _voice_files(client)
    fetch = FakeFetch()
    client.app.state.voice_library = VoiceLibrary(tmp_path, fetch=fetch)
    assert client.post(HOLD).json() == {"kept": False}
    _libraries(_copy_folder(tmp_path))
    fetch.running = False
    assert client.post(HOLD).json() == {"kept": True}
    assert voice.held[0].library_dir == str(_copy_folder(tmp_path))
    assert len(fetch.started) == 1


def test_the_end_of_a_conversation_reaches_the_library(client: TestClient, tmp_path):
    fetch = FakeFetch()
    client.app.state.voice_library = VoiceLibrary(tmp_path, fetch=fetch)
    client.app.state.voice_library.directory()
    fetch.running = False
    client.app.state.voice_library.directory()
    assert len(fetch.started) == 1
    assert client.post(RELEASE).status_code == 204
    client.app.state.voice_library.directory()
    assert len(fetch.started) == 2

