"""Fetching the picture generator itself.

What matters here is the path from a fresh installation to a working
generator: is there a package for this machine, does it land where the
runner looks, does it come out able to run, and does a machine without a
network get an honest sentence instead of a half-unpacked folder.
"""

from __future__ import annotations

import io
import os
import sys
import time
import zipfile

import pytest

from app import bildrunner, sddownload
from app.sddownload import (
    BAU,
    ORDNER,
    Sddownload,
    SddownloadFehler,
    Veroeffentlichung,
    gefundenes_programm,
    paketname,
)


def _play_windows(monkeypatch) -> None:
    """GPU variants exist on Windows only; a test that fetches one plays it."""
    monkeypatch.setattr(sddownload.sys, "platform", "win32")
    monkeypatch.setattr(sddownload.platform, "machine", lambda: "amd64")


# --- The package table ----------------------------------------------------


def test_macos_und_windows_haben_pakete():
    """macOS has one universal package; Windows has one per GPU variant.
    Neither table names a Linux build — there is no Linux package."""
    assert sddownload._PAKET_DARWIN.endswith(".zip")
    for name, groesse in sddownload._PAKETE_WIN32.values():
        assert name.endswith(".zip")
        assert groesse > 0


def test_cuda_variante_bringt_ihre_laufzeit_mit():
    assert sddownload._CUDART[0].endswith(".zip")
    assert sddownload._CUDART[1] > 0


def test_ein_intel_und_ein_arm_mac_bekommen_dasselbe_paket(monkeypatch):
    """The macOS package is universal — one file serves both kinds of Mac."""
    monkeypatch.setattr(sddownload.sys, "platform", "darwin")
    monkeypatch.setattr(sddownload.platform, "machine", lambda: "arm64")
    arm = paketname()
    monkeypatch.setattr(sddownload.platform, "machine", lambda: "x86_64")
    intel = paketname()
    assert arm == intel == sddownload._PAKET_DARWIN


def test_die_maschine_wird_erkannt(monkeypatch):
    monkeypatch.setattr(sddownload.sys, "platform", "darwin")
    monkeypatch.setattr(sddownload.platform, "machine", lambda: "arm64")
    assert paketname() == sddownload._PAKET_DARWIN

    # Windows reports its architecture in several spellings; all of them
    # mean the same machine and must not fall through to "no package". No
    # variant is asked for, so this is the default — today's package.
    monkeypatch.setattr(sddownload.sys, "platform", "win32")
    for geschrieben in ("AMD64", "x86_64", "x64"):
        monkeypatch.setattr(sddownload.platform, "machine", lambda g=geschrieben: g)
        assert paketname() == sddownload._PAKETE_WIN32[sddownload.VORGABE_VARIANTE][0]


def test_jede_windows_variante_hat_ihr_eigenes_paket(monkeypatch):
    monkeypatch.setattr(sddownload.sys, "platform", "win32")
    monkeypatch.setattr(sddownload.platform, "machine", lambda: "amd64")
    for variante, (name, _) in sddownload._PAKETE_WIN32.items():
        assert paketname(variante) == name


def test_eine_unbekannte_variante_liefert_kein_paket(monkeypatch):
    monkeypatch.setattr(sddownload.sys, "platform", "win32")
    monkeypatch.setattr(sddownload.platform, "machine", lambda: "amd64")
    assert paketname("quanten") is None


def test_es_gibt_kein_linux_paket(monkeypatch):
    """No Linux build ships with this program, so there is nothing to fetch
    a generator for there — paketname() says so cleanly, it does not fail."""
    monkeypatch.setattr(sddownload.sys, "platform", "linux")
    monkeypatch.setattr(sddownload.platform, "machine", lambda: "x86_64")
    assert paketname() is None


def test_eine_maschine_ohne_paket_wird_zugegeben(monkeypatch):
    """A refusal is better than downloading something that cannot run."""
    monkeypatch.setattr(sddownload.sys, "platform", "win32")
    monkeypatch.setattr(sddownload.platform, "machine", lambda: "riscv64")
    assert paketname() is None


def test_bauordner_heisst_nach_variante():
    assert sddownload._bauordner_name_von(BAU, sddownload.VORGABE_VARIANTE) == BAU
    assert sddownload._bauordner_name_von(BAU, "cuda12") == f"{BAU}-cuda12"


def test_gueltige_variante_kennt_nur_die_tabelle():
    for variante in sddownload._PAKETE_WIN32:
        assert sddownload.gueltige_variante(variante)
    assert not sddownload.gueltige_variante("quanten")


def test_waehlbare_varianten_nur_auf_win32(monkeypatch):
    monkeypatch.setattr(sddownload.sys, "platform", "darwin")
    assert sddownload.waehlbare_varianten() == []

    monkeypatch.setattr(sddownload.sys, "platform", "win32")
    varianten = sddownload.waehlbare_varianten()
    assert {v for v, _ in varianten} == set(sddownload._PAKETE_WIN32)
    for variante, groesse in varianten:
        assert groesse == sddownload._PAKETE_WIN32[variante][1]


# --- Which one is installed -------------------------------------------------


def test_installierte_variante_ohne_bau_ist_nichts(tmp_path):
    assert sddownload.installierte_variante(tmp_path) is None


def test_installierte_variante_liest_den_standardordner(tmp_path, monkeypatch):
    """The plain build folder is the CPU build under Windows; every other
    system has one universal package whose folder name carries no backend,
    so the same folder answers a name on win32 and nothing beyond it."""
    ordner = tmp_path / ORDNER / BAU
    ordner.mkdir(parents=True)

    monkeypatch.setattr(sddownload.sys, "platform", "win32")
    (ordner / sddownload.program_name()).write_bytes(b"x")
    assert sddownload.installierte_variante(tmp_path) == sddownload.VORGABE_VARIANTE

    monkeypatch.setattr(sddownload.sys, "platform", "darwin")
    (ordner / sddownload.program_name()).write_bytes(b"x")
    assert sddownload.installierte_variante(tmp_path) is None


def test_installierte_variante_liest_den_variantenordner(tmp_path):
    ordner = tmp_path / ORDNER / f"{BAU}-cuda12"
    ordner.mkdir(parents=True)
    (ordner / sddownload.program_name()).write_bytes(b"x")
    assert sddownload.installierte_variante(tmp_path) == "cuda12"


def _runnable_build(tmp_path, name: str):
    folder = tmp_path / ORDNER / name
    folder.mkdir(parents=True)
    program = folder / sddownload.program_name()
    program.write_bytes(b"x")
    program.chmod(0o755)
    return program


def test_der_benannte_ordner_gewinnt_neben_dem_schlichten(tmp_path, monkeypatch):
    """Windows, the plain CPU folder and a ``-cuda12`` folder of the same
    build side by side, the plain one sorted first: the panel names the
    variant that is started, and the one started is that folder."""
    _play_windows(monkeypatch)
    _runnable_build(tmp_path, BAU)
    cuda = _runnable_build(tmp_path, f"{BAU}-cuda12")

    assert sddownload.installierte_variante(tmp_path) == "cuda12"
    assert gefundenes_programm(tmp_path) == cuda


def test_shown_and_started_build_are_the_same_on_every_system(tmp_path, monkeypatch):
    """One rule for the panel and for the start: the highest build number,
    at the same number the folder named for a variant."""
    monkeypatch.setattr(sddownload.sys, "platform", "darwin")
    _runnable_build(tmp_path, "master-1-a1b2c3d-vulkan")
    newer = _runnable_build(tmp_path, "master-989-c678dfe")

    assert sddownload.installierter_bau(tmp_path) == "master-989-c678dfe"
    assert sddownload.installierte_variante(tmp_path) is None
    assert gefundenes_programm(tmp_path) == newer

    named = _runnable_build(tmp_path, "master-989-c678dfe-vulkan")
    assert sddownload.installierte_variante(tmp_path) == "vulkan"
    assert gefundenes_programm(tmp_path) == named


def test_one_build_folder_is_both_shown_and_started(tmp_path, monkeypatch):
    """Silence probe: with one folder there is nothing to choose."""
    _play_windows(monkeypatch)
    only = _runnable_build(tmp_path, BAU)
    assert sddownload.installierte_variante(tmp_path) == sddownload.VORGABE_VARIANTE
    assert gefundenes_programm(tmp_path) == only


def test_a_folder_vanishing_while_read_is_skipped(tmp_path, monkeypatch):
    """A fetch removes other build folders from its own thread. A folder
    that disappears while it is being searched counts as not there; the
    others are still found."""
    gone = tmp_path / ORDNER / "master-989-c678dfe"
    kept = _runnable_build(tmp_path, BAU)
    gone.mkdir(parents=True)
    (gone / sddownload.program_name()).write_bytes(b"x")
    real_rglob = sddownload.Path.rglob

    def rglob(self, pattern):
        if self.name == gone.name:
            raise FileNotFoundError(2, "No such file or directory", str(self))
        return real_rglob(self, pattern)

    monkeypatch.setattr(sddownload.Path, "rglob", rglob)
    assert sddownload.installierter_bau(tmp_path) == BAU
    assert gefundenes_programm(tmp_path) == kept


def test_a_program_unpacked_by_hand_into_its_own_folder_is_still_found(tmp_path):
    """Silence probe for the chosen folder: a program unpacked into a folder
    that is not named after a build (as an archive tool names it) is still
    found when no build folder has one."""
    program = _runnable_build(tmp_path, "sd-master-de298c2-bin-Darwin-macOS-26.5.2-arm64")
    assert sddownload.installierte_variante(tmp_path) is None
    assert gefundenes_programm(tmp_path) == program


def test_nothing_vanishing_reads_the_same(tmp_path):
    """Silence probe: without a removal the newer folder wins as always."""
    _runnable_build(tmp_path, BAU)
    _runnable_build(tmp_path, "master-989-c678dfe")
    assert sddownload.installierter_bau(tmp_path) == "master-989-c678dfe"


def test_installierte_variante_reads_the_root_once(tmp_path, monkeypatch):
    _runnable_build(tmp_path, f"{BAU}-cuda12")
    root = tmp_path / ORDNER
    calls: list[str] = []
    real_iterdir = sddownload.Path.iterdir

    def iterdir(self):
        if self == root:
            calls.append(str(self))
        return real_iterdir(self)

    monkeypatch.setattr(sddownload.Path, "iterdir", iterdir)
    assert sddownload.installierte_variante(tmp_path) == "cuda12"
    assert len(calls) == 1


def test_installierte_variante_ist_nichts_fuer_eine_handinstallation(tmp_path):
    """A hand install sits loose in the root, not in a build folder — there
    is no variant name on it to read."""
    ordner = tmp_path / ORDNER
    ordner.mkdir()
    (ordner / sddownload.program_name()).write_bytes(b"x")
    assert sddownload.installierte_variante(tmp_path) is None


def test_installierte_variante_erkennt_auch_einen_fremden_pin(tmp_path, monkeypatch):
    """A build folder from an older pin than today's ``BAU`` also starts
    with "master-" — and is recognised as a real,
    working install rather than being skipped: the whole point of that
    order is that "installed" no longer means "matches the app's own
    pin", it means "runnable build on disk". A win32 folder with no
    suffix is that pin's CPU build, same as for the pinned BAU."""
    ordner = tmp_path / ORDNER / "master-1-a1b2c3d"
    ordner.mkdir(parents=True)
    monkeypatch.setattr(sddownload.sys, "platform", "win32")
    (ordner / sddownload.program_name()).write_bytes(b"x")

    assert sddownload.installierte_variante(tmp_path) == sddownload.VORGABE_VARIANTE
    assert sddownload.installierter_bau(tmp_path) == "master-1-a1b2c3d"


def test_installierter_bau_gewinnt_die_hoechste_nummer(tmp_path):
    """Two build folders side by side (mid-update, before the older one is
    cleaned away) — the higher build number is reported as installed, the
    same one ``_andere_bauten_entfernen`` would keep."""
    for name in ("master-1-a1b2c3d", "master-989-c678dfe"):
        ordner = tmp_path / ORDNER / name
        ordner.mkdir(parents=True)
        (ordner / sddownload.program_name()).write_bytes(b"x")
    assert sddownload.installierter_bau(tmp_path) == "master-989-c678dfe"


def test_installierter_bau_ohne_ordner_ist_nichts(tmp_path):
    assert sddownload.installierter_bau(tmp_path) is None


def test_bau_nummer_liest_die_zahl_aus_dem_tag():
    assert sddownload._bau_nummer("master-989-c678dfe") == 989
    assert sddownload._bau_nummer(sddownload.BAU) == 948


def test_the_pinned_build_is_948_in_tag_address_folder_and_packages():
    """What a fresh installation fetches: the build's tag, the address its
    packages come from, the folder it lands in, and every package under the
    name the release itself lists it by."""
    tag = "master-948-228c707"
    assert BAU == tag
    assert sddownload._BASIS == (
        f"https://github.com/leejet/stable-diffusion.cpp/releases/download/{tag}"
    )
    assert sddownload._bauordner_name_von(BAU, sddownload.VORGABE_VARIANTE) == tag
    assert sddownload._bauordner_name_von(BAU, "cuda12") == f"{tag}-cuda12"
    assert sddownload._PAKET_DARWIN == "sd-master-228c707-bin-Darwin-macOS-26.6.2-arm64.zip"
    assert {variant: name for variant, (name, _) in sddownload._PAKETE_WIN32.items()} == {
        "cpu": "sd-master-228c707-bin-win-cpu-x64.zip",
        "cuda12": "sd-master-228c707-bin-win-cuda12-x64.zip",
        "vulkan": "sd-master-228c707-bin-win-vulkan-x64.zip",
        "rocm": "sd-master-228c707-bin-win-rocm-7.14.0-x64.zip",
    }
    assert sddownload._CUDART[0] == "cudart-sd-bin-win-cu12-x64.zip"
    # The sizes are the release's own byte counts: the cuda12 bar is laid
    # out from them, and a rounded total would be passed before the end.
    assert {variant: size for variant, (_, size) in sddownload._PAKETE_WIN32.items()} == {
        "cpu": 17_517_910, "cuda12": 337_979_057, "vulkan": 30_098_372, "rocm": 251_568_217,
    }
    assert sddownload._CUDART[1] == 563_452_046
    pinned = sddownload.pinned_build()
    assert (pinned.bau, pinned.nummer) == (tag, 948)


def test_the_pinned_build_installed_is_up_to_date_when_it_is_the_newest(monkeypatch):
    """Silence probe: the update question is what it was. With the pinned
    build as the project's newest release there is nothing newer for an
    installation that has it — and an older installation is still told."""
    newest = _veroeffentlichung_daten("master-948-228c707", "228c707")
    monkeypatch.setattr(sddownload.httpx, "get", lambda *a, **k: _FalscheAntwort(newest))
    release = sddownload.neueste_veroeffentlichung()
    assert release is not None and (release.bau, release.nummer) == (BAU, 948)
    assert not sddownload.ist_voraus(release, BAU)
    assert sddownload.neuere_fassung(BAU) is None
    assert sddownload.ist_voraus(release, "master-820-de298c2")
    older = sddownload.neuere_fassung("master-820-de298c2")
    assert older is not None and older.bau == BAU


def test_bau_nummer_verweigert_ein_fremdes_tag():
    assert sddownload._bau_nummer("v1.2.3") is None
    assert sddownload._bau_nummer("nicht-mal-aehnlich") is None


# --- Where it lands -------------------------------------------------------


def test_ohne_entpacktes_programm_wird_nichts_gefunden(tmp_path):
    assert gefundenes_programm(tmp_path) is None


def test_ein_von_hand_abgelegtes_programm_wird_gefunden(tmp_path):
    ordner = tmp_path / ORDNER
    ordner.mkdir()
    pfad = ordner / sddownload.program_name()
    pfad.write_bytes(b"x")
    pfad.chmod(0o755)
    assert gefundenes_programm(tmp_path) == pfad


def test_ein_geholtes_programm_wird_unter_dem_bau_gefunden(tmp_path):
    ordner = tmp_path / ORDNER / BAU
    ordner.mkdir(parents=True)
    pfad = ordner / sddownload.program_name()
    pfad.write_bytes(b"x")
    pfad.chmod(0o755)
    gefunden = gefundenes_programm(tmp_path)
    assert gefunden is not None and gefunden.name == sddownload.program_name()


def test_der_bildrunner_findet_was_geholt_wurde(tmp_path, monkeypatch):
    """The whole point: the fetch and the search must meet somewhere."""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: None)
    assert bildrunner.programm_finden(tmp_path) is None
    ordner = tmp_path / ORDNER / BAU
    ordner.mkdir(parents=True)
    pfad = ordner / sddownload.program_name()
    pfad.write_bytes(b"x")
    pfad.chmod(0o755)
    assert bildrunner.programm_finden(tmp_path) == pfad


# --- The guards before a fetch starts -------------------------------------


def test_was_schon_da_ist_wird_nicht_nochmal_geholt(tmp_path):
    ordner = tmp_path / ORDNER / BAU
    ordner.mkdir(parents=True)
    pfad = ordner / sddownload.program_name()
    pfad.write_bytes(b"x")
    pfad.chmod(0o755)
    with pytest.raises(SddownloadFehler) as fehler:
        Sddownload(tmp_path).starten()
    assert fehler.value.grund == "schon_da"


def test_ohne_paket_fuer_die_maschine_ein_ehrlicher_fehler(tmp_path, monkeypatch):
    monkeypatch.setattr(sddownload.sys, "platform", "linux")
    with pytest.raises(SddownloadFehler) as fehler:
        Sddownload(tmp_path).starten()
    assert fehler.value.grund == "kein_paket"


def test_handinstallation_blockiert_jede_variante(tmp_path):
    """A hand install sits loose in the root, ahead of any build folder this
    program would ever make — it blocks a fetch no matter which variant is
    asked for, and it is never the one removed."""
    ordner = tmp_path / ORDNER
    ordner.mkdir()
    pfad = ordner / sddownload.program_name()
    pfad.write_bytes(b"x")
    pfad.chmod(0o755)
    for variante in (None, "cuda12"):
        with pytest.raises(SddownloadFehler) as fehler:
            Sddownload(tmp_path).starten(variante)
        assert fehler.value.grund == "schon_da"


def test_andere_variante_ist_nicht_schon_da(tmp_path, monkeypatch):
    """schon_da is per variant: the default build sitting there must not
    block a fetch of a different one."""
    _play_windows(monkeypatch)
    ordner = tmp_path / ORDNER / BAU
    ordner.mkdir(parents=True)
    pfad = ordner / sddownload.program_name()
    pfad.write_bytes(b"x")
    pfad.chmod(0o755)
    with pytest.raises(SddownloadFehler) as fehler:
        Sddownload(tmp_path).starten()
    assert fehler.value.grund == "schon_da"

    monkeypatch.setattr(sddownload.httpx, "stream", KaputterStrom())
    download = Sddownload(tmp_path)
    download.starten("cuda12")  # must not raise schon_da
    _warten(download)
    assert download.stand().fehler == "fehlgeschlagen"  # a network failure, not schon_da
    assert ordner.is_dir()  # the existing cpu build is untouched


# --- The fetch itself -----------------------------------------------------


class FalscherStrom:
    """Stands in for httpx.stream and delivers a tiny zip archive."""

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


class KaputterStrom:
    """A machine without a network, as the library reports it."""

    def __call__(self, *a, **k):
        raise OSError("kein Netz")


def _archiv_mit_programm() -> bytes:
    """Flat, like the real packages: the binary and its library side by side."""
    speicher = io.BytesIO()
    with zipfile.ZipFile(speicher, "w") as zf:
        zf.writestr(sddownload.program_name(), "#!/bin/sh\n")
        zf.writestr("libstable-diffusion.dylib", "x")
    return speicher.getvalue()


def _warten(download: Sddownload) -> None:
    ende = time.time() + 5
    while time.time() < ende and download.laeuft():
        time.sleep(0.02)


def test_holen_entpackt_und_macht_ausfuehrbar(tmp_path, monkeypatch):
    monkeypatch.setattr(sddownload.httpx, "stream", FalscherStrom(_archiv_mit_programm()))
    download = Sddownload(tmp_path)
    download.starten()
    _warten(download)

    stand = download.stand()
    assert stand is not None and stand.fertig and stand.fehler is None

    programm = gefundenes_programm(tmp_path)
    assert programm is not None
    # A zip file carries no permission bits, so an unpacked binary arrives
    # unable to run — which would look exactly like never having fetched it.
    if sys.platform != "win32":
        assert os.access(programm, os.X_OK)
    # And the shared library lies beside it, where the binary looks for it.
    assert (programm.parent / "libstable-diffusion.dylib").is_file()


def test_der_bildrunner_nimmt_das_geholte_programm(tmp_path, monkeypatch):
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: None)
    monkeypatch.setattr(sddownload.httpx, "stream", FalscherStrom(_archiv_mit_programm()))
    download = Sddownload(tmp_path)
    download.starten()
    _warten(download)
    assert bildrunner.Bildrunner(tmp_path).programm is not None


def test_ohne_netz_bleibt_kein_halbes_ergebnis_liegen(tmp_path, monkeypatch):
    monkeypatch.setattr(sddownload.httpx, "stream", KaputterStrom())
    download = Sddownload(tmp_path)
    download.starten()
    _warten(download)

    stand = download.stand()
    assert stand is not None and stand.fehler == "fehlgeschlagen" and not stand.fertig
    # Nothing half-unpacked stays behind, or the next attempt would find
    # something that looks like a generator and is not one.
    assert gefundenes_programm(tmp_path) is None
    assert not list((tmp_path / ORDNER).glob("*" + sddownload.UNFERTIG))


def test_ein_ordner_der_nicht_entstehen_kann_ist_ein_fehler(tmp_path, monkeypatch):
    """A dangling link where the folder belongs: making the folder fails.
    The fetch has to end with an error, not stand at nought for good."""
    monkeypatch.setattr(sddownload.httpx, "stream", FalscherStrom(_archiv_mit_programm()))
    (tmp_path / ORDNER).symlink_to(tmp_path / "gibt-es-nicht")
    download = Sddownload(tmp_path)
    download.starten()
    _warten(download)

    stand = download.stand()
    assert stand is not None and stand.fehler == "fehlgeschlagen" and not stand.fertig
    assert not download.laeuft()


def test_ein_kaputtes_archiv_ist_ein_fehler_und_kein_programm(tmp_path, monkeypatch):
    monkeypatch.setattr(sddownload.httpx, "stream", FalscherStrom(b"das ist kein zip"))
    download = Sddownload(tmp_path)
    download.starten()
    _warten(download)

    stand = download.stand()
    assert stand is not None and stand.fehler == "fehlgeschlagen"
    assert gefundenes_programm(tmp_path) is None


# --- GPU variants -----------------------------------------------------------


class _MehrfacherStrom:
    """Answers httpx.stream with a different payload per URL, so the main
    package and the cudart runtime archive can be told apart."""

    def __init__(self, daten_je_url: dict[str, bytes]):
        self._daten_je_url = daten_je_url
        self.aufrufe: list[str] = []

    def __call__(self, methode, url, **kwargs):
        self.aufrufe.append(url)
        return _EinzelnerStrom(self._daten_je_url[url])


class _EinzelnerStrom:
    def __init__(self, daten: bytes):
        self._daten = daten
        self.headers = {"content-length": str(len(daten))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_bytes(self, groesse):
        yield self._daten


def _archiv_mit_dll() -> bytes:
    """A stand-in for the cudart runtime archive — flat DLLs, no binary."""
    speicher = io.BytesIO()
    with zipfile.ZipFile(speicher, "w") as zf:
        zf.writestr("runtime.dll", "x")
    return speicher.getvalue()


def test_variante_landet_in_ihrem_eigenen_ordner(tmp_path, monkeypatch):
    _play_windows(monkeypatch)
    monkeypatch.setattr(sddownload.httpx, "stream", FalscherStrom(_archiv_mit_programm()))
    download = Sddownload(tmp_path)
    download.starten("vulkan")
    _warten(download)

    stand = download.stand()
    assert stand is not None and stand.fertig and stand.fehler is None
    assert (tmp_path / ORDNER / f"{BAU}-vulkan" / sddownload.program_name()).is_file()
    # The default folder is untouched — nothing was ever fetched into it.
    assert not (tmp_path / ORDNER / BAU).exists()


def test_variantenwechsel_raeumt_den_alten_bau_weg(tmp_path, monkeypatch):
    """Only one build stays on disk. Fetching a second variant must remove
    the first — a leftover build nobody points at any more otherwise sits
    there forever."""
    _play_windows(monkeypatch)
    monkeypatch.setattr(sddownload.httpx, "stream", FalscherStrom(_archiv_mit_programm()))
    erster = Sddownload(tmp_path)
    erster.starten()
    _warten(erster)
    alter_bauordner = tmp_path / ORDNER / BAU
    assert alter_bauordner.is_dir()

    zweiter = Sddownload(tmp_path)
    zweiter.starten("vulkan")
    _warten(zweiter)

    assert not alter_bauordner.exists()
    assert (tmp_path / ORDNER / f"{BAU}-vulkan" / sddownload.program_name()).is_file()


def test_ein_neuerer_bau_ueberlebt_einen_pinned_variantenwechsel(tmp_path, monkeypatch):
    """A newer release, once fetched, must not be thrown away by a later
    plain (pinned-BAU) variant fetch's own cleanup — the variant picker
    still only ever fetches the pinned build, and running it after an
    update is not a request to roll that update back."""
    _play_windows(monkeypatch)
    neuerer_ordner = tmp_path / ORDNER / "master-989-c678dfe"
    neuerer_ordner.mkdir(parents=True)
    (neuerer_ordner / sddownload.program_name()).write_bytes(b"x")

    monkeypatch.setattr(sddownload.httpx, "stream", FalscherStrom(_archiv_mit_programm()))
    download = Sddownload(tmp_path)
    download.starten("vulkan")
    _warten(download)

    stand = download.stand()
    assert stand is not None and stand.fertig and stand.fehler is None
    assert (tmp_path / ORDNER / f"{BAU}-vulkan" / sddownload.program_name()).is_file()
    assert neuerer_ordner.is_dir()


def test_cuda12_laedt_beide_archive_in_einen_balken(tmp_path, monkeypatch):
    """The acceptance criterion: choosing cuda12 fetches both the package
    and the cudart runtime into one variant folder, with one progress bar
    that only ever grows and never resets between the two files. ``gesamt``
    is fixed from the table before the first byte arrives (not measured),
    exactly so it cannot jump once the second file starts."""
    monkeypatch.setattr(sddownload.sys, "platform", "win32")
    monkeypatch.setattr(sddownload.platform, "machine", lambda: "amd64")
    haupt_name = sddownload._PAKETE_WIN32["cuda12"][0]
    cudart_name = sddownload._CUDART[0]
    haupt_daten = _archiv_mit_programm()
    cudart_daten = _archiv_mit_dll()
    strom = _MehrfacherStrom({
        f"{sddownload._BASIS}/{haupt_name}": haupt_daten,
        f"{sddownload._BASIS}/{cudart_name}": cudart_daten,
    })
    monkeypatch.setattr(sddownload.httpx, "stream", strom)

    download = Sddownload(tmp_path)
    download.starten("cuda12")
    _warten(download)

    stand = download.stand()
    assert stand is not None and stand.fertig and stand.fehler is None
    assert stand.gesamt == sddownload._PAKETE_WIN32["cuda12"][1] + sddownload._CUDART[1]
    assert stand.geladen == len(haupt_daten) + len(cudart_daten)
    # The main package first, the runtime second — never the other way.
    assert strom.aufrufe == [
        f"{sddownload._BASIS}/{haupt_name}", f"{sddownload._BASIS}/{cudart_name}",
    ]

    bauordner = tmp_path / ORDNER / f"{BAU}-cuda12"
    assert (bauordner / sddownload.program_name()).is_file()
    assert (bauordner / "runtime.dll").is_file()


def test_cuda12_balken_faellt_nie_zurueck(tmp_path, monkeypatch):
    """Sampled WHILE the download runs, not just at the end — a total that
    jumps once the second file starts (the bug the fix above closes) shows
    up here as ``anteil`` dropping between two samples, which the
    end-of-run assertions above cannot see.

    The table sizes are scaled down to the test archives' real byte counts.
    At the real ~857 MB total, every ``anteil`` a
    few hundred test bytes could ever produce rounds to 0.0 — the
    monotonicity check would stay green even if the bar never moved a
    single step, which is why ``any(a > 0 …)`` is asserted too."""
    monkeypatch.setattr(sddownload.sys, "platform", "win32")
    monkeypatch.setattr(sddownload.platform, "machine", lambda: "amd64")
    haupt_name = sddownload._PAKETE_WIN32["cuda12"][0]
    cudart_name = sddownload._CUDART[0]
    haupt_daten = _archiv_mit_programm()
    cudart_daten = _archiv_mit_dll()
    monkeypatch.setitem(
        sddownload._PAKETE_WIN32, "cuda12", (haupt_name, len(haupt_daten))
    )
    monkeypatch.setattr(sddownload, "_CUDART", (cudart_name, len(cudart_daten)))
    strom = _MehrfacherStrom({
        f"{sddownload._BASIS}/{haupt_name}": haupt_daten,
        f"{sddownload._BASIS}/{cudart_name}": cudart_daten,
    })
    monkeypatch.setattr(sddownload.httpx, "stream", strom)

    download = Sddownload(tmp_path)
    download.starten("cuda12")

    anteile = []
    ende = time.time() + 5
    while time.time() < ende and download.laeuft():
        stand = download.stand()
        if stand is not None and stand.gesamt:
            anteile.append(stand.anteil)

    stand = download.stand()
    assert stand is not None and stand.fertig and stand.fehler is None
    assert any(a > 0 for a in anteile), anteile
    assert all(b >= a for a, b in zip(anteile, anteile[1:], strict=False)), anteile


# --- Reading the newest release ---------------------------------------------


class _FalscheAntwort:
    """Stands in for httpx.get's return value."""

    def __init__(self, daten):
        self._daten = daten

    def raise_for_status(self):
        pass

    def json(self):
        return self._daten


def _veroeffentlichung_daten(tag: str, hash_: str, ohne=()) -> dict:
    """The shape GitHub answers with — trimmed to the fields this program
    reads, with the same file names a real release carries, measured
    against the project's own /releases/latest. ``ohne`` drops named
    assets, to build an incomplete or ambiguous release on purpose."""
    namen = {
        "cudart": ("cudart-sd-bin-win-cu12-x64.zip", 563452046),
        "darwin": (f"sd-master-{hash_}-bin-Darwin-macOS-26.6.2-arm64.zip", 34310861),
        "cpu": (f"sd-master-{hash_}-bin-win-cpu-x64.zip", 17185424),
        "cuda12": (f"sd-master-{hash_}-bin-win-cuda12-x64.zip", 332970080),
        "vulkan": (f"sd-master-{hash_}-bin-win-vulkan-x64.zip", 31935490),
        "rocm": (f"sd-master-{hash_}-bin-win-rocm-7.14.0-x64.zip", 192106873),
    }
    return {
        "tag_name": tag,
        "assets": [
            {"name": name, "size": groesse}
            for schluessel, (name, groesse) in namen.items()
            if schluessel not in ohne
        ],
    }


def test_neueste_veroeffentlichung_liest_tag_und_pakete(monkeypatch):
    monkeypatch.setattr(
        sddownload.httpx, "get",
        lambda *a, **k: _FalscheAntwort(_veroeffentlichung_daten("master-989-c678dfe", "c678dfe")),
    )
    v = sddownload.neueste_veroeffentlichung()
    assert v is not None
    assert v.bau == "master-989-c678dfe"
    assert v.nummer == 989
    assert v.darwin == ("sd-master-c678dfe-bin-Darwin-macOS-26.6.2-arm64.zip", 34310861)
    assert set(v.varianten) == {"cpu", "cuda12", "vulkan", "rocm"}
    assert v.varianten["cuda12"] == ("sd-master-c678dfe-bin-win-cuda12-x64.zip", 332970080)
    assert v.cudart == 563452046


def test_neueste_veroeffentlichung_ohne_netz_ist_nichts(monkeypatch):
    def kaputt(*a, **k):
        raise sddownload.httpx.ConnectError("kein Netz")

    monkeypatch.setattr(sddownload.httpx, "get", kaputt)
    assert sddownload.neueste_veroeffentlichung() is None


def test_neueste_veroeffentlichung_mit_fremdem_tag_ist_nichts(monkeypatch):
    """A release this program would not recognise as its own project (a
    foreign tag shape) is not a release to offer — not a guess to make."""
    monkeypatch.setattr(
        sddownload.httpx, "get", lambda *a, **k: _FalscheAntwort({"tag_name": "v1.2.3", "assets": []})
    )
    assert sddownload.neueste_veroeffentlichung() is None


def test_ein_mehrdeutiges_paket_wird_nicht_angeboten(monkeypatch):
    """Two assets matching the same pattern (or the pattern's one asset
    simply missing) are the same case: not one name this program can be
    certain of, so nothing is offered for it rather than a guess among
    several — or an invented one out of none."""
    daten = _veroeffentlichung_daten("master-989-c678dfe", "c678dfe")
    daten["assets"].append(
        {"name": "sd-master-deadbee-bin-Darwin-macOS-26.6.2-arm64.zip", "size": 1}
    )
    monkeypatch.setattr(sddownload.httpx, "get", lambda *a, **k: _FalscheAntwort(daten))
    v = sddownload.neueste_veroeffentlichung()
    assert v is not None and v.darwin is None

    monkeypatch.setattr(
        sddownload.httpx, "get",
        lambda *a, **k: _FalscheAntwort(
            _veroeffentlichung_daten("master-989-c678dfe", "c678dfe", ohne={"cudart"})
        ),
    )
    v = sddownload.neueste_veroeffentlichung()
    assert v is not None and v.cudart is None


def test_neuere_fassung_nur_wenn_wirklich_neuer(monkeypatch):
    monkeypatch.setattr(
        sddownload.httpx, "get",
        lambda *a, **k: _FalscheAntwort(_veroeffentlichung_daten("master-989-c678dfe", "c678dfe")),
    )
    assert sddownload.neuere_fassung(BAU) is not None
    assert sddownload.neuere_fassung("master-989-c678dfe") is None
    assert sddownload.neuere_fassung("master-990-abc1234") is None


def test_veroeffentlichung_paket_folgt_der_plattform(monkeypatch):
    v = Veroeffentlichung(
        bau="master-989-c678dfe", nummer=989,
        darwin=("sd-master-c678dfe-bin-Darwin-macOS-26.6.2-arm64.zip", 1),
        varianten={"cpu": ("sd-master-c678dfe-bin-win-cpu-x64.zip", 2)},
        cudart=3,
    )
    monkeypatch.setattr(sddownload.sys, "platform", "darwin")
    monkeypatch.setattr(sddownload.platform, "machine", lambda: "arm64")
    assert sddownload.veroeffentlichung_paket(v) == v.darwin

    monkeypatch.setattr(sddownload.sys, "platform", "win32")
    monkeypatch.setattr(sddownload.platform, "machine", lambda: "amd64")
    assert sddownload.veroeffentlichung_paket(v) == v.varianten["cpu"]
    assert sddownload.veroeffentlichung_paket(v, "vulkan") is None

    monkeypatch.setattr(sddownload.sys, "platform", "linux")
    assert sddownload.veroeffentlichung_paket(v) is None


# --- Fetching an update ------------------------------------------------------


def test_starten_mit_veroeffentlichung_holt_den_neuen_bau(tmp_path, monkeypatch):
    """The acceptance criterion: a newer release lands under
    its OWN tag, not the pinned BAU, and the older build the panel already
    had is removed only once the new one has come out and works."""
    monkeypatch.setattr(sddownload.sys, "platform", "darwin")
    alter_ordner = tmp_path / ORDNER / BAU
    alter_ordner.mkdir(parents=True)
    (alter_ordner / sddownload.program_name()).write_bytes(b"x")
    (alter_ordner / sddownload.program_name()).chmod(0o755)

    monkeypatch.setattr(sddownload.platform, "machine", lambda: "arm64")
    v = Veroeffentlichung(
        bau="master-989-c678dfe", nummer=989,
        darwin=("sd-master-c678dfe-bin-Darwin-macOS-26.6.2-arm64.zip", 34310861),
        varianten={}, cudart=None,
    )
    monkeypatch.setattr(sddownload.httpx, "stream", FalscherStrom(_archiv_mit_programm()))

    download = Sddownload(tmp_path)
    download.starten(veroeffentlichung=v)
    _warten(download)

    stand = download.stand()
    assert stand is not None and stand.fertig and stand.fehler is None
    assert (tmp_path / ORDNER / "master-989-c678dfe" / sddownload.program_name()).is_file()
    assert not alter_ordner.exists()


def test_starten_mit_veroeffentlichung_ohne_darwin_paket_ist_kein_paket(tmp_path, monkeypatch):
    monkeypatch.setattr(sddownload.sys, "platform", "darwin")
    monkeypatch.setattr(sddownload.platform, "machine", lambda: "arm64")
    v = Veroeffentlichung(bau="master-989-c678dfe", nummer=989, darwin=None, varianten={}, cudart=None)
    with pytest.raises(SddownloadFehler) as fehler:
        Sddownload(tmp_path).starten(veroeffentlichung=v)
    assert fehler.value.grund == "kein_paket"


def test_starten_cuda12_aktualisierung_ohne_cudart_wird_verweigert(tmp_path, monkeypatch):
    """cuda12 cannot run without its runtime archive — a release that does
    not carry it (uniquely) is refused for that variant rather than fetched
    half-working."""
    monkeypatch.setattr(sddownload.sys, "platform", "win32")
    monkeypatch.setattr(sddownload.platform, "machine", lambda: "amd64")
    v = Veroeffentlichung(
        bau="master-989-c678dfe", nummer=989, darwin=None,
        varianten={"cuda12": ("sd-master-c678dfe-bin-win-cuda12-x64.zip", 1)},
        cudart=None,
    )
    with pytest.raises(SddownloadFehler) as fehler:
        Sddownload(tmp_path).starten("cuda12", veroeffentlichung=v)
    assert fehler.value.grund == "kein_paket"


# --- Where the packages come from ----------------------------------------------


def test_packages_and_updates_come_from_upstream(monkeypatch):
    """Both the package address and the update question name upstream
    stable-diffusion.cpp, whose releases carry the prebuilt packages — a
    repository without published releases would leave a fresh installation
    with nothing to fetch."""
    assert sddownload._basis("master-820-de298c2") == (
        "https://github.com/leejet/stable-diffusion.cpp/releases/download/master-820-de298c2"
    )
    gefragt: list[str] = []

    def merken(url, *a, **k):
        gefragt.append(url)
        return _FalscheAntwort(_veroeffentlichung_daten("master-989-c678dfe", "c678dfe"))

    monkeypatch.setattr(sddownload.httpx, "get", merken)
    sddownload.neueste_veroeffentlichung()
    assert gefragt == ["https://api.github.com/repos/leejet/stable-diffusion.cpp/releases/latest"]
    assert "exe-ai-productions" not in sddownload._BASIS


def test_a_fork_tag_is_read_as_a_build(monkeypatch):
    """A tag "exe<N>" publishes "<tag>-<commit count>-<short hash>"; the
    count orders it against the upstream builds installed before."""
    assert sddownload._bau_nummer("exe1-951-1a2b3c4") == 951
    assert sddownload._ordner_aufschluesseln("exe12-930-abcdef0-cuda12") == ("exe12-930-abcdef0", "cuda12")
    daten = _veroeffentlichung_daten("exe1-951-1a2b3c4", "1a2b3c4")
    for eintrag in daten["assets"]:
        eintrag["name"] = eintrag["name"].replace("sd-master-", "sd-exe1-")
    monkeypatch.setattr(sddownload.httpx, "get", lambda *a, **k: _FalscheAntwort(daten))
    v = sddownload.neueste_veroeffentlichung()
    assert v is not None and (v.bau, v.nummer) == ("exe1-951-1a2b3c4", 951)
    assert v.darwin == ("sd-exe1-1a2b3c4-bin-Darwin-macOS-26.6.2-arm64.zip", 34310861)
    assert set(v.varianten) == {"cpu", "cuda12", "vulkan", "rocm"}
    # Newer than the upstream build this program pinned before.
    assert v.nummer > sddownload._bau_nummer(sddownload.BAU)


def test_a_hand_placed_program_still_comes_first(tmp_path):
    """Silence probe: a build unpacked by hand beside a fetched fork build
    is still the one that runs."""
    for ordner in (tmp_path / ORDNER, tmp_path / ORDNER / "exe1-951-1a2b3c4"):
        ordner.mkdir(parents=True, exist_ok=True)
        (ordner / sddownload.program_name()).write_text("#!/bin/sh\n")
        (ordner / sddownload.program_name()).chmod(0o755)
    assert sddownload.gefundenes_programm(tmp_path) == tmp_path / ORDNER / sddownload.program_name()


# --- Variants off Windows ---------------------------------------------------


def test_a_mac_refuses_a_gpu_variant(tmp_path, monkeypatch):
    """There is one Mac package and no Vulkan build for it: asking for one
    is refused, not fetched into a folder named after it."""
    monkeypatch.setattr(sddownload.sys, "platform", "darwin")
    monkeypatch.setattr(sddownload.platform, "machine", lambda: "arm64")
    with pytest.raises(SddownloadFehler) as fehler:
        Sddownload(tmp_path).starten("vulkan")
    assert fehler.value.grund == "kein_paket"
    assert not (tmp_path / ORDNER / f"{BAU}-vulkan").exists()
    assert paketname("vulkan") is None


def test_a_mac_keeps_its_default_and_windows_its_variants(monkeypatch):
    """Silence probe: the default package on a Mac as before, and Vulkan
    still on offer under Windows."""
    monkeypatch.setattr(sddownload.sys, "platform", "darwin")
    monkeypatch.setattr(sddownload.platform, "machine", lambda: "arm64")
    assert paketname() == sddownload._PAKET_DARWIN
    assert paketname(sddownload.VORGABE_VARIANTE) == sddownload._PAKET_DARWIN
    _play_windows(monkeypatch)
    assert paketname("vulkan") == sddownload._PAKETE_WIN32["vulkan"][0]


# --- One description of a build ----------------------------------------------


def test_the_pinned_build_and_a_read_release_take_one_path(tmp_path, monkeypatch):
    """The plain fetch and a release read off GitHub go the same way: each
    is fetched from its own tag's address and lands under its own tag."""
    _play_windows(monkeypatch)
    requested: list[str] = []

    class Recording(FalscherStrom):
        def __call__(self, method, url, *a, **k):
            requested.append(url)
            return self

    monkeypatch.setattr(sddownload.httpx, "stream", Recording(_archiv_mit_programm()))
    release = Veroeffentlichung(
        bau="exe1-951-1a2b3c4", nummer=951, darwin=None,
        varianten={"vulkan": ("sd-exe1-1a2b3c4-bin-win-vulkan-x64.zip", 1)}, cudart=None,
    )
    pinned_package = sddownload._PAKETE_WIN32["vulkan"][0]
    for data_folder, extra, tag, package in (
        (tmp_path / "a", {}, BAU, pinned_package),
        (tmp_path / "b", {"veroeffentlichung": release}, release.bau, release.varianten["vulkan"][0]),
    ):
        download = Sddownload(data_folder)
        download.starten("vulkan", **extra)
        _warten(download)
        assert download.stand().fertig
        assert requested[-1] == f"{sddownload._basis(tag)}/{package}"
        assert (data_folder / ORDNER / f"{tag}-vulkan" / sddownload.program_name()).is_file()


def test_an_unknown_suffix_does_not_outrank_the_plain_folder(tmp_path, monkeypatch):
    """Only a variant this program fetches is preferred: a folder renamed by
    hand (a backup, say) ranks as plain, and the plain one sorts first."""
    _play_windows(monkeypatch)
    plain = _runnable_build(tmp_path, BAU)
    _runnable_build(tmp_path, f"{BAU}-alt")
    assert sddownload.installierte_variante(tmp_path) == sddownload.VORGABE_VARIANTE
    assert gefundenes_programm(tmp_path) == plain


def test_a_vanishing_folder_keeps_what_the_root_search_found(tmp_path, monkeypatch):
    """The root-wide search keeps the programs it found before a folder
    vanished under it."""
    real_rglob = sddownload.Path.rglob
    found_first = tmp_path / ORDNER / "a" / sddownload.program_name()
    found_first.parent.mkdir(parents=True)
    found_first.write_bytes(b"x")
    found_first.chmod(0o755)

    def rglob(self, pattern):
        yield from real_rglob(self, pattern)
        raise FileNotFoundError(2, "No such file or directory", str(self / "b"))

    monkeypatch.setattr(sddownload.Path, "rglob", rglob)
    assert gefundenes_programm(tmp_path) == found_first


# --- Playing another system ----------------------------------------------


def test_playing_windows_searches_for_the_windows_name(tmp_path, monkeypatch):
    """A test that plays Windows must be able to tell ``sd-cli`` from
    ``sd-cli.exe``: the plain name is not a Windows program, the ``.exe``
    one is. Both files are runnable, so the name alone decides."""
    monkeypatch.setattr(sddownload.sys, "platform", "win32")
    folder = tmp_path / ORDNER / BAU
    folder.mkdir(parents=True)
    plain = folder / "sd-cli"
    plain.write_bytes(b"x")
    plain.chmod(0o755)
    assert gefundenes_programm(tmp_path) is None

    windows = folder / "sd-cli.exe"
    windows.write_bytes(b"x")
    windows.chmod(0o755)
    found = gefundenes_programm(tmp_path)
    assert found is not None and found.name == "sd-cli.exe"


def test_playing_macos_searches_for_the_plain_name(tmp_path, monkeypatch):
    """The silence probe: every other system keeps the plain name."""
    monkeypatch.setattr(sddownload.sys, "platform", "darwin")
    folder = tmp_path / ORDNER / BAU
    folder.mkdir(parents=True)
    windows = folder / "sd-cli.exe"
    windows.write_bytes(b"x")
    windows.chmod(0o755)
    assert gefundenes_programm(tmp_path) is None

    plain = folder / "sd-cli"
    plain.write_bytes(b"x")
    plain.chmod(0o755)
    found = gefundenes_programm(tmp_path)
    assert found is not None and found.name == "sd-cli"


def test_playing_windows_an_existing_exe_build_is_already_there(tmp_path, monkeypatch):
    """The fetch guard reads the same name: with Windows played, a runnable
    ``sd-cli.exe`` in the build folder blocks a second fetch."""
    monkeypatch.setattr(sddownload.sys, "platform", "win32")
    folder = tmp_path / ORDNER / BAU
    folder.mkdir(parents=True)
    program = folder / "sd-cli.exe"
    program.write_bytes(b"x")
    program.chmod(0o755)
    with pytest.raises(SddownloadFehler) as error:
        Sddownload(tmp_path).starten()
    assert error.value.grund == "schon_da"
