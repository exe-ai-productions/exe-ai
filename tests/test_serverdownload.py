"""Fetching the model server itself."""

from __future__ import annotations

import io
import tarfile
import time
import zipfile
from pathlib import Path

import httpx
import pytest

from app import serverdownload
from tests.conftest import llama_server_name
from app.serverdownload import (
    BUILD,
    Serverdownload,
    ServerdownloadFehler,
    gefundener_server,
    paketname,
)


def test_fuer_diese_maschine_gibt_es_ein_paket():
    # The build machine itself must be coverable, whatever it is.
    assert paketname() is not None


def test_ohne_entpackten_server_wird_nichts_gefunden(tmp_path):
    assert gefundener_server(tmp_path) is None


def test_ein_entpackter_server_wird_gefunden(tmp_path):
    ziel = tmp_path / "llama.cpp" / BUILD / "build" / "bin"
    ziel.mkdir(parents=True)
    (ziel / llama_server_name()).write_bytes(b"x")
    gefunden = gefundener_server(tmp_path)
    assert gefunden is not None and gefunden.name == llama_server_name()


def test_was_schon_da_ist_wird_nicht_nochmal_geholt(tmp_path):
    ziel = tmp_path / "llama.cpp" / BUILD
    ziel.mkdir(parents=True)
    (ziel / llama_server_name()).write_bytes(b"x")
    download = Serverdownload(tmp_path)
    with pytest.raises(ServerdownloadFehler) as fehler:
        download.starten()
    assert fehler.value.grund == "schon_da"


def test_ohne_paket_fuer_die_maschine_ein_ehrlicher_fehler(tmp_path, monkeypatch):
    monkeypatch.setattr(serverdownload, "paketname", lambda build=BUILD: None)
    with pytest.raises(ServerdownloadFehler) as fehler:
        Serverdownload(tmp_path).starten()
    assert fehler.value.grund == "kein_paket"


class FalscherStrom:
    """Stands in for httpx.stream and delivers a tiny tar archive."""

    def __init__(self, daten: bytes):
        self._daten = daten
        self.headers = {"content-length": str(len(daten))}
        # Every address that was asked for, so a test can read which build
        # and which package a fetch went for.
        self.asked: list[str] = []

    def __call__(self, methode, url, **k):
        self.asked.append(url)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_bytes(self, groesse):
        yield self._daten


def _archiv_mit_server() -> bytes:
    """The archive the program expects on THIS system (``paketname``): a zip
    on Windows, a gzipped tar elsewhere — with the server under the name the
    finder looks for there."""
    name = f"build/bin/{llama_server_name()}"
    inhalt = b"#!/bin/sh\n"
    speicher = io.BytesIO()
    if (serverdownload.paketname() or "").endswith(".zip"):
        with zipfile.ZipFile(speicher, "w") as zf:
            zf.writestr(name, inhalt)
    else:
        with tarfile.open(fileobj=speicher, mode="w:gz") as tf:
            info = tarfile.TarInfo(name)
            info.size = len(inhalt)
            tf.addfile(info, io.BytesIO(inhalt))
    return speicher.getvalue()


def _wait(download: Serverdownload) -> None:
    ende = time.time() + 5
    while time.time() < ende and download.laeuft():
        time.sleep(0.02)


def test_holen_entpackt_und_findet_den_server(tmp_path, monkeypatch):
    strom = FalscherStrom(_archiv_mit_server())
    monkeypatch.setattr(serverdownload.httpx, "stream", strom)
    download = Serverdownload(tmp_path)
    download.starten()
    _wait(download)
    stand = download.stand()
    assert stand is not None and stand.fertig and stand.fehler is None
    assert gefundener_server(tmp_path) is not None
    # Silence probe: a machine without a server still gets the pinned build.
    assert strom.asked == [
        f"https://github.com/ggml-org/llama.cpp/releases/download/{BUILD}/{paketname()}"
    ]
    assert serverdownload.installed_build(tmp_path) == BUILD


# The packages of the pinned build as the release lists them
# (gh api repos/ggml-org/llama.cpp/releases/tags/b11429, the six this
# program uses out of its asset list).
_RELEASE_B11429 = {
    "llama-b11429-bin-macos-arm64.tar.gz",
    "llama-b11429-bin-macos-x64.tar.gz",
    "llama-b11429-bin-win-cpu-x64.zip",
    "llama-b11429-bin-win-cpu-arm64.zip",
    "llama-b11429-bin-ubuntu-x64.tar.gz",
    "llama-b11429-bin-ubuntu-arm64.tar.gz",
}


def test_the_package_names_are_the_release_files_of_the_pinned_build():
    assert BUILD == "b11429"
    assert {
        form.format(build=BUILD) for form in serverdownload._PAKETE.values()
    } == _RELEASE_B11429


def test_a_system_without_a_package_stays_without(monkeypatch):
    """Silence probe: a machine llama.cpp has no package for gets none."""
    monkeypatch.setattr(serverdownload.platform, "machine", lambda: "riscv64")
    assert paketname() is None


def test_an_older_build_left_behind_is_not_the_server(tmp_path):
    """Only the pinned build's folder counts — an older one left by an
    earlier version is neither used nor in the way of fetching the new one."""
    alt = tmp_path / "llama.cpp" / "b10331"
    alt.mkdir(parents=True)
    (alt / llama_server_name()).write_bytes(b"x")
    assert gefundener_server(tmp_path) is None



# --- A newer build, and the way back --------------------------------------

NEWER = "b11541"


def _lay_build(folder: Path, build: str) -> Path:
    """A fetched build as it lies on disk: its folder, the server inside."""
    target = folder / "llama.cpp" / build / "build" / "bin"
    target.mkdir(parents=True)
    server = target / llama_server_name()
    server.write_bytes(b"x")
    return server


class _Answer:
    """Stands in for the answer of httpx.get."""

    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _release(tag: str, *assets: str) -> dict:
    return {"tag_name": tag, "prerelease": True, "assets": [{"name": name} for name in assets]}


def test_the_top_build_with_this_machines_package_is_the_newest(monkeypatch):
    """The list as the project publishes it: its version release on top,
    which carries no packages; a build whose packages are not all there
    yet; then the builds that can be fetched."""
    asked: list[str] = []

    def get(url, **_):
        asked.append(url)
        return _Answer([
            _release("v0.6.0", "nightly-tag.txt"),
            _release("b11550", "llama-b11550-bin-some-other-system.zip"),
            _release(NEWER, paketname(NEWER), "llama-b11541-bin-some-other-system.zip"),
            _release("b11500", paketname("b11500")),
        ])

    monkeypatch.setattr(serverdownload.httpx, "get", get)
    assert serverdownload.newest_build() == NEWER
    assert asked == ["https://api.github.com/repos/ggml-org/llama.cpp/releases"]


@pytest.mark.parametrize("data", [{"message": "rate limit"}, [], [{"tag_name": "v0.6.0"}]])
def test_a_list_without_a_fetchable_build_names_none(monkeypatch, data):
    """Silence probe: nothing is made up where the list holds no build."""
    monkeypatch.setattr(serverdownload.httpx, "get", lambda url, **_: _Answer(data))
    assert serverdownload.newest_build() is None


def test_an_unreachable_list_names_no_build(monkeypatch):
    def get(url, **_):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(serverdownload.httpx, "get", get)
    assert serverdownload.newest_build() is None


def test_the_package_name_carries_the_build_tag():
    pinned, newer = paketname(), paketname(NEWER)
    assert pinned is not None and newer is not None
    assert NEWER in newer and BUILD not in newer
    assert newer == pinned.replace(BUILD, NEWER)


@pytest.mark.parametrize(
    ("build", "running", "ahead"),
    [
        (NEWER, BUILD, True),
        (BUILD, BUILD, False),
        (BUILD, NEWER, False),
        # A program that does not say which build it is cannot be shown to
        # be current.
        (NEWER, None, True),
        # And a name that is no build tag is never ahead of anything.
        ("v0.6.0", BUILD, False),
    ],
)
def test_only_a_higher_build_number_is_ahead(build, running, ahead):
    assert serverdownload.is_ahead(build, running) is ahead


def test_of_two_builds_the_higher_one_is_the_server(tmp_path):
    _lay_build(tmp_path, BUILD)
    newer = _lay_build(tmp_path, NEWER)
    assert gefundener_server(tmp_path) == newer
    assert serverdownload.installed_build(tmp_path) == NEWER


def test_a_fetched_newer_build_is_found_and_the_older_one_is_gone(tmp_path, monkeypatch):
    _lay_build(tmp_path, BUILD)
    strom = FalscherStrom(_archiv_mit_server())
    monkeypatch.setattr(serverdownload.httpx, "stream", strom)
    download = Serverdownload(tmp_path)
    download.starten(NEWER)
    _wait(download)

    stand = download.stand()
    assert stand is not None and stand.fertig and stand.fehler is None
    assert strom.asked == [
        f"https://github.com/ggml-org/llama.cpp/releases/download/{NEWER}/{paketname(NEWER)}"
    ]
    server = gefundener_server(tmp_path)
    assert server is not None
    assert tmp_path / "llama.cpp" / NEWER in server.parents
    assert not (tmp_path / "llama.cpp" / BUILD).exists()


def test_restoring_fetches_the_pinned_build_in_place_of_the_newer_one(tmp_path, monkeypatch):
    _lay_build(tmp_path, NEWER)
    strom = FalscherStrom(_archiv_mit_server())
    monkeypatch.setattr(serverdownload.httpx, "stream", strom)
    download = Serverdownload(tmp_path)
    download.starten(BUILD)
    _wait(download)

    stand = download.stand()
    assert stand is not None and stand.fertig and stand.fehler is None
    assert strom.asked == [
        f"https://github.com/ggml-org/llama.cpp/releases/download/{BUILD}/{paketname()}"
    ]
    assert serverdownload.installed_build(tmp_path) == BUILD
    assert not (tmp_path / "llama.cpp" / NEWER).exists()


def test_the_build_that_is_installed_is_not_fetched_again(tmp_path, monkeypatch):
    """Silence probe: asked for the build already there, and asked plainly
    with a newer one there, nothing is fetched."""
    _lay_build(tmp_path, NEWER)
    strom = FalscherStrom(_archiv_mit_server())
    monkeypatch.setattr(serverdownload.httpx, "stream", strom)
    download = Serverdownload(tmp_path)
    for build in (NEWER, None):
        with pytest.raises(ServerdownloadFehler) as fehler:
            download.starten(build)
        assert fehler.value.grund == "schon_da"
    assert strom.asked == []


def test_a_failed_update_leaves_the_installed_build_as_it_was(tmp_path, monkeypatch):
    old = _lay_build(tmp_path, BUILD)

    def no_network(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr(serverdownload.httpx, "stream", no_network)
    download = Serverdownload(tmp_path)
    download.starten(NEWER)
    _wait(download)

    stand = download.stand()
    assert stand is not None and stand.fehler == "fehlgeschlagen"
    assert gefundener_server(tmp_path) == old
    assert not (tmp_path / "llama.cpp" / NEWER).exists()


def test_a_build_still_being_unpacked_is_not_the_server(tmp_path, monkeypatch):
    """A server starting while the archive is written out must get the
    build that was there before, not half of the new one."""
    old = _lay_build(tmp_path, BUILD)
    newer = _lay_build(tmp_path, NEWER)
    folder = (tmp_path / "llama.cpp" / NEWER).resolve()
    monkeypatch.setattr(serverdownload, "_unpacking", {folder})
    assert gefundener_server(tmp_path) == old
    monkeypatch.setattr(serverdownload, "_unpacking", set())
    assert gefundener_server(tmp_path) == newer


def test_a_newer_build_that_cannot_be_removed_is_not_in_the_way(tmp_path, monkeypatch):
    """A server still running from the newer build keeps its files open,
    and where those cannot be deleted the folder stays. The build just
    fetched is the one that starts all the same."""
    _lay_build(tmp_path, NEWER)
    monkeypatch.setattr(serverdownload.httpx, "stream", FalscherStrom(_archiv_mit_server()))
    monkeypatch.setattr(serverdownload.shutil, "rmtree", lambda *a, **k: None)
    download = Serverdownload(tmp_path)
    download.starten(BUILD)
    _wait(download)

    stand = download.stand()
    assert stand is not None and stand.fertig
    assert (tmp_path / "llama.cpp" / NEWER).is_dir()
    assert serverdownload.installed_build(tmp_path) == BUILD


# --- Which build a program is ---------------------------------------------


@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("version: 10310 (cb26014d9)\nbuilt with AppleClang for Darwin arm64\n", 10310),
        ("version: 0.6.0 (build 11429, commit d81235049)\nbuilt with AppleClang\n", 11429),
        ("llama-server: unknown option --version\n", None),
        ("", None),
    ],
)
def test_the_build_number_is_read_from_both_forms_of_the_version_line(text, number):
    assert serverdownload.stated_build_number(text) == number


def test_a_fetched_build_is_named_by_its_folder(tmp_path):
    server = _lay_build(tmp_path, NEWER)
    assert serverdownload.fetched_build(server, tmp_path) == NEWER


class _Said:
    def __init__(self, stdout: str = "", stderr: str = ""):
        self.stdout = stdout
        self.stderr = stderr


def test_an_installed_program_is_asked_once_and_again_after_it_changed(tmp_path, monkeypatch):
    program = tmp_path / "elsewhere" / llama_server_name()
    program.parent.mkdir()
    program.write_bytes(b"x")
    calls: list[list[str]] = []
    says = ["version: 10310 (cb26014d9)\n"]

    def run(command, **_):
        calls.append(command)
        return _Said(stderr=says[0])

    monkeypatch.setattr(serverdownload, "_stated", {})
    monkeypatch.setattr(serverdownload.subprocess, "run", run)
    data = tmp_path / "data"
    assert serverdownload.fetched_build(program, data) is None
    assert serverdownload.stated_build(program) == "b10310"
    assert serverdownload.stated_build(program) == "b10310"
    assert calls == [[str(program), "--version"]]

    # A package manager replaced the file: it is asked again.
    says[0] = "version: 0.6.0 (build 11429, commit d81235049)\n"
    program.write_bytes(b"xx")
    assert serverdownload.stated_build(program) == "b11429"
    assert len(calls) == 2


def test_a_program_that_does_not_say_its_build_has_none(tmp_path, monkeypatch):
    program = tmp_path / llama_server_name()
    program.write_bytes(b"x")

    def run(command, **_):
        raise OSError("cannot be started")

    monkeypatch.setattr(serverdownload, "_stated", {})
    monkeypatch.setattr(serverdownload.subprocess, "run", run)
    assert serverdownload.stated_build(program) is None
