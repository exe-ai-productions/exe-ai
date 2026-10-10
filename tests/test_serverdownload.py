"""Fetching the model server itself."""

from __future__ import annotations

import io
import tarfile
import zipfile

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
    monkeypatch.setattr(serverdownload, "paketname", lambda: None)
    with pytest.raises(ServerdownloadFehler) as fehler:
        Serverdownload(tmp_path).starten()
    assert fehler.value.grund == "kein_paket"


class FalscherStrom:
    """Stands in for httpx.stream and delivers a tiny tar archive."""

    def __init__(self, daten: bytes):
        self._daten = daten
        self.headers = {"content-length": str(len(daten))}

    def __call__(self, *a, **k):
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


def test_holen_entpackt_und_findet_den_server(tmp_path, monkeypatch):
    import time

    monkeypatch.setattr(serverdownload.httpx, "stream", FalscherStrom(_archiv_mit_server()))
    download = Serverdownload(tmp_path)
    download.starten()
    ende = time.time() + 5
    while time.time() < ende and download.laeuft():
        time.sleep(0.02)
    stand = download.stand()
    assert stand is not None and stand.fertig and stand.fehler is None
    assert gefundener_server(tmp_path) is not None


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
    assert set(serverdownload._PAKETE.values()) == _RELEASE_B11429


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

