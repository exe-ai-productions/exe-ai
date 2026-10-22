"""An installed picture generator older than the pinned build is replaced at
the start of the service.

The pinned build knows the switches this program sends; an older one refuses
them ("unknown argument"). So a service that starts with an older build
installed fetches the pinned one by itself — the variant that runs, the
progress like a fetch by hand, the removal of the old build included — while a
newer build, a program unpacked by hand, the pinned build itself and an
installation with nothing in it are left alone. When the fetch does not come
off, a picture says that the generator needs an update instead of quoting the
generator's refusal.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import bildrunner, bildturbo, sddownload
from app.bildrunner import Auftrag, Bildrunner, BildFehler
from app.main import app_erstellen
from app.serverdownload import Fortschritt


def _build(daten: Path, tag: str, *, loose: bool = False) -> None:
    """A runnable generator below the data folder: in a build folder named
    after its tag, or loose in the bare folder (unpacked by hand)."""
    folder = daten / sddownload.ORDNER
    if not loose:
        folder = folder / tag
    folder.mkdir(parents=True)
    program = folder / sddownload.program_name()
    program.write_bytes(b"x")
    program.chmod(0o755)


class _Download:
    """What the service's fetch object is asked to do, written down."""

    def __init__(self, error: Exception | None = None):
        self.calls: list[tuple] = []
        self._error = error

    def starten(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self._error:
            raise self._error
        return Fortschritt(geladen=0, gesamt=0)


# --- The rule -------------------------------------------------------------


@pytest.mark.parametrize(("installed", "expected"), [
    ("master-948-228c707", True),
    ("master-974-aaaaaaa", True),
    (sddownload.BAU, False),
    ("master-980-bbbbbbb", False),
])
def test_only_an_older_installed_build_needs_the_update(tmp_path, installed, expected):
    _build(tmp_path, installed)
    assert sddownload.update_needed(tmp_path) is expected


def test_nothing_installed_and_a_hand_installation_need_no_update(tmp_path):
    assert sddownload.update_needed(tmp_path) is False
    _build(tmp_path, "master-948-228c707")
    program = tmp_path / sddownload.ORDNER / sddownload.program_name()
    program.write_bytes(b"x")
    program.chmod(0o755)
    assert sddownload.update_needed(tmp_path) is False


def test_the_update_fetches_the_pinned_build_once_in_the_variant_that_runs(tmp_path):
    _build(tmp_path, "master-948-228c707")
    download = _Download()
    assert sddownload.update_at_start(download, tmp_path) == sddownload.BAU
    assert len(download.calls) == 1
    # The variant is the one the installed build folder names (none on a system
    # with one universal package), never a default of the caller's.
    installed = sddownload.installierter_bau(tmp_path)
    assert download.calls[0][0] == (sddownload.installierte_variante(tmp_path, bau=installed),)


def test_silence_nothing_is_fetched_for_the_pinned_build_a_newer_one_or_a_hand_installation(tmp_path):
    for tag in (sddownload.BAU, "master-980-bbbbbbb"):
        folder = tmp_path / tag
        _build(folder, tag)
        download = _Download()
        assert sddownload.update_at_start(download, folder) is None
        assert download.calls == []
    hand = tmp_path / "hand"
    _build(hand, "master-948-228c707")
    program = hand / sddownload.ORDNER / sddownload.program_name()
    program.write_bytes(b"x")
    program.chmod(0o755)
    download = _Download()
    assert sddownload.update_at_start(download, hand) is None and download.calls == []


def test_a_fetch_that_cannot_start_does_not_hold_the_start_up(tmp_path):
    _build(tmp_path, "master-948-228c707")
    download = _Download(sddownload.SddownloadFehler("laeuft_schon"))
    assert sddownload.update_at_start(download, tmp_path) is None
    assert len(download.calls) == 1


# --- The service ----------------------------------------------------------


def _start(config, monkeypatch, installed: str | None, *, hand: bool = False) -> list:
    calls: list = []

    def recorder(self, *args, **kwargs):
        calls.append((args, kwargs))
        return Fortschritt(geladen=0, gesamt=0)

    monkeypatch.setattr(sddownload.Sddownload, "starten", recorder)
    daten = Path(config.datenverzeichnis)
    if installed:
        _build(daten, installed)
    if hand:
        program = daten / sddownload.ORDNER / sddownload.program_name()
        program.write_bytes(b"x")
        program.chmod(0o755)
    with TestClient(app_erstellen(config)):
        pass
    return calls


def test_a_service_that_starts_with_build_948_fetches_the_pinned_build_exactly_once(config, monkeypatch):
    assert len(_start(config, monkeypatch, "master-948-228c707")) == 1


@pytest.mark.parametrize("installed", [sddownload.BAU, "master-980-bbbbbbb", None])
def test_a_service_that_starts_with_the_pinned_build_a_newer_one_or_none_fetches_nothing(
    config, monkeypatch, installed
):
    assert _start(config, monkeypatch, installed) == []


def test_a_service_that_starts_with_a_hand_installation_fetches_nothing(config, monkeypatch):
    assert _start(config, monkeypatch, "master-948-228c707", hand=True) == []


# --- The sentence when the generator stays old ----------------------------


def test_a_picture_of_a_generator_that_refuses_a_switch_says_it_needs_an_update(tmp_path, monkeypatch):
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/somewhere/sd-cli")

    class Process:
        pid = 4243

        def __init__(self):
            import io
            self.returncode = None
            self.stdout = io.BytesIO(b"")
            self.stderr = io.BytesIO(b"error: unknown argument: --flash-attn\n")

        def wait(self, timeout=None):
            self.returncode = 1
            return 1

        def poll(self):
            return self.returncode

    monkeypatch.setattr(bildrunner.subprocess, "Popen", lambda *a, **k: Process())
    with pytest.raises(BildFehler) as raised:
        Bildrunner(tmp_path).erzeugen(
            Auftrag(modell=tmp_path / "small.gguf", prompt="x"), tmp_path / "out.png"
        )
    assert raised.value.grund == "bild.sdcpp_veraltet"
    assert raised.value.protokoll is None


def test_a_picture_server_that_refuses_a_switch_says_it_needs_an_update(tmp_path):
    turbo = bildturbo.Bildturbo(tmp_path, 18998, lambda: None)
    assert turbo.ladefehler_grund() == "bild.turbo_ladefehler"
    turbo._protokoll.append("error: unknown argument: --flash-attn")
    assert turbo.ladefehler_grund() == "bild.sdcpp_veraltet"


def test_the_sentence_is_in_both_catalogues():
    import json

    base = Path(__file__).resolve().parent.parent / "app" / "locales"
    assert json.loads((base / "en.json").read_text("utf-8"))["bild"]["sdcpp_veraltet"] == "sd.cpp needs an update"
    assert json.loads((base / "de.json").read_text("utf-8"))["bild"]["sdcpp_veraltet"] == "sd.cpp muss aktualisiert werden"
