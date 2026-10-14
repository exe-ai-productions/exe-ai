"""The model runner.

No real model server is started here — that would need a binary and several
gigabytes. What is tested is the part that decides: which file may be loaded,
which command comes out of it, and what happens when there is no program to
run at all.

The dangerous one is the folder boundary. A name that is secretly a path
would let anything on the machine be handed to a program that runs for hours.
"""

from __future__ import annotations

import os
import stat
import sys
import time
from pathlib import Path

import pytest

from tests.conftest import fake_server, llama_server_name, sized_file
from app.modellrunner import (
    Lauf, Modellrunner, RunnerFehler, modelle_auflisten, programm_finden,
)


# A process that stays for a while — the interpreter itself, so it exists
# on every system where `sleep` does not.
_SLEEPER = [sys.executable, "-c", "import time; time.sleep(30)"]


@pytest.fixture
def ordner(tmp_path: Path) -> Path:
    (tmp_path / "klein.gguf").write_bytes(b"x" * 2000)
    (tmp_path / "gross.gguf").write_bytes(b"x" * 9000)
    (tmp_path / "keinmodell.txt").write_text("nein")
    return tmp_path


@pytest.fixture
def falsches_programm(tmp_path: Path) -> Path:
    """Something executable that is not a model server."""
    return fake_server(tmp_path / "llama-server")


# --- What is in the folder ------------------------------------------------


def test_nur_gguf_zaehlt_als_modell(ordner):
    namen = [m.name for m in modelle_auflisten(ordner)]
    assert namen == ["gross.gguf", "klein.gguf"]


def test_das_groesste_steht_oben(ordner):
    assert modelle_auflisten(ordner)[0].name == "gross.gguf"


def test_ein_ordner_der_nicht_existiert_ist_leer(tmp_path):
    assert modelle_auflisten(tmp_path / "gibtsnicht") == []


def _gross(pfad: Path, groesse: int) -> None:
    # Sparse: the size is real to stat, the disk stays empty.
    sized_file(pfad, groesse)


def test_zwei_teile_sind_ein_modell_mit_der_summe(tmp_path):
    _gross(tmp_path / "m-Q2_0-00001-of-00002.gguf", 1_500_000_000)
    _gross(tmp_path / "m-Q2_0-00002-of-00002.gguf", 1_000_000_000)
    (tmp_path / "einzeln.gguf").write_bytes(b"x" * 9000)
    modelle = modelle_auflisten(tmp_path)
    assert [(m.name, m.groesse_gb) for m in modelle] == [
        ("m-Q2_0-00001-of-00002.gguf", 2.5),
        ("einzeln.gguf", 0.0),
    ]


def test_ohne_teil_zwei_kein_modell(tmp_path):
    _gross(tmp_path / "m-00001-of-00002.gguf", 1_500_000_000)
    _gross(tmp_path / "m-00002-of-00003.gguf", 1_000_000_000)
    assert modelle_auflisten(tmp_path) == []


# --- The program ----------------------------------------------------------


@pytest.mark.platforms("posix", reason="the execute bit")
def test_eine_vorgabe_die_nicht_ausfuehrbar_ist_gilt_nicht(tmp_path):
    pfad = tmp_path / "attrappe"
    pfad.write_text("kein Programm")
    assert programm_finden(str(pfad)) is None


def test_eine_ausfuehrbare_vorgabe_gilt(falsches_programm):
    assert programm_finden(str(falsches_programm)) == falsches_programm


def _own_build(tmp_path: Path, name: str | None = None) -> Path:
    from app.serverdownload import BUILD

    ziel = tmp_path / "daten" / "llama.cpp" / BUILD / "build" / "bin"
    ziel.mkdir(parents=True)
    # The name this system looks for (app/serverdownload.py), unless the
    # test plays another system and says which name that one looks for.
    programm = ziel / (name or llama_server_name())
    programm.write_text("#!/bin/sh\n")
    programm.chmod(programm.stat().st_mode | stat.S_IXUSR)
    return programm


def test_the_own_build_wins_over_one_on_path(tmp_path, monkeypatch):
    """A package manager's llama-server on PATH and the program's own build
    both there: the own build is started — its pinned version is the one
    tested here."""
    import app.modellrunner as mr
    import app.paketierung as paketierung

    # The test plays macOS below, so the build carries the name that
    # system looks for — on Windows the helper would lay down the .exe.
    eigener = _own_build(tmp_path, "llama-server")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(paketierung, "daten", lambda: tmp_path / "daten")
    monkeypatch.setattr(mr.shutil, "which", lambda name: "/opt/homebrew/bin/llama-server")
    assert programm_finden() == eigener


@pytest.mark.parametrize(
    ("plattform", "name"), [("linux", "llama-server"), ("win32", "llama-server.exe")],
)
def test_off_the_mac_path_wins_over_the_own_build(tmp_path, monkeypatch, plattform, name):
    """On Windows and Linux the own build is one for the processor alone; a
    llama-server on PATH may be built for the graphics card and is started
    instead."""
    import app.modellrunner as mr
    import app.paketierung as paketierung

    _own_build(tmp_path, name)
    monkeypatch.setattr(sys, "platform", plattform)
    monkeypatch.setattr(paketierung, "daten", lambda: tmp_path / "daten")
    monkeypatch.setattr(mr.shutil, "which", lambda name: "/usr/local/bin/llama-server")
    assert programm_finden() == Path("/usr/local/bin/llama-server")


@pytest.mark.parametrize(
    ("plattform", "name"), [("linux", "llama-server"), ("win32", "llama-server.exe")],
)
def test_off_the_mac_the_own_build_is_found_without_one_on_path(
    tmp_path, monkeypatch, plattform, name,
):
    """Silence probe: nothing on PATH or in the known places — the own build
    is still started."""
    import app.modellrunner as mr
    import app.paketierung as paketierung

    eigener = _own_build(tmp_path, name)
    monkeypatch.setattr(sys, "platform", plattform)
    monkeypatch.setattr(mr, "BEKANNTE_ORTE", ())
    monkeypatch.setattr(paketierung, "daten", lambda: tmp_path / "daten")
    monkeypatch.setattr(mr.shutil, "which", lambda name: None)
    assert programm_finden() == eigener


def test_the_setting_wins_over_the_own_build(tmp_path, monkeypatch, falsches_programm):
    """Silence probe: a program named in the settings is that program."""
    import app.paketierung as paketierung

    _own_build(tmp_path)
    monkeypatch.setattr(paketierung, "daten", lambda: tmp_path / "daten")
    assert programm_finden(str(falsches_programm)) == falsches_programm


def test_without_an_own_build_path_is_asked_as_before(tmp_path, monkeypatch):
    """Silence probe: no own build — PATH, as before."""
    import app.modellrunner as mr
    import app.paketierung as paketierung

    monkeypatch.setattr(paketierung, "daten", lambda: tmp_path / "daten")
    monkeypatch.setattr(mr.shutil, "which", lambda name: "/opt/homebrew/bin/llama-server")
    assert programm_finden() == Path("/opt/homebrew/bin/llama-server")


# --- The command ----------------------------------------------------------


def test_der_befehl_zeigt_alles_was_er_tut(ordner, falsches_programm):
    runner = Modellrunner(ordner, str(falsches_programm))
    befehl = runner.befehl("klein.gguf", 4096, 33, 8081)

    assert befehl[0] == str(falsches_programm)
    # Everything the window shows has to be in there, or the window lies.
    assert "--ctx-size" in befehl and "4096" in befehl
    assert "--n-gpu-layers" in befehl and "33" in befehl
    assert "--port" in befehl and "8081" in befehl
    # Never reachable from the network: a model server has no protection of
    # its own, and whoever reaches it can use the whole machine's memory.
    assert befehl[befehl.index("--host") + 1] == "127.0.0.1"
    # Without raised verbosity the engine's load report never appears, and
    # the flash-attention state would stay unknown forever.
    assert befehl[befehl.index("--log-verbosity") + 1] == "4"


# --- Where it has to refuse -----------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["../draussen.gguf", "unter/tief.gguf", "/etc/passwd", "..%2Fweg.gguf"],
)
def test_ein_name_ist_nie_ein_pfad(ordner, falsches_programm, name):
    runner = Modellrunner(ordner, str(falsches_programm))
    with pytest.raises(RunnerFehler) as fehler:
        runner.starten(name)
    assert fehler.value.grund == "kein_modell"


def test_was_nicht_im_ordner_liegt_startet_nicht(ordner, falsches_programm):
    runner = Modellrunner(ordner, str(falsches_programm))
    with pytest.raises(RunnerFehler) as fehler:
        runner.starten("gibtsnicht.gguf")
    assert fehler.value.grund == "kein_modell"


def test_ohne_programm_geht_nichts(ordner):
    runner = Modellrunner(ordner, "/pfad/den/es/nicht/gibt")
    with pytest.raises(RunnerFehler) as fehler:
        runner.starten("klein.gguf")
    assert fehler.value.grund == "kein_programm"


# --- One at a time --------------------------------------------------------


def test_ein_zweiter_server_wird_abgelehnt(ordner, falsches_programm):
    runner = Modellrunner(ordner, str(falsches_programm))
    # An out-of-the-way port: the default one may be taken by a real server
    # on the developer's machine, and this test is about something else.
    runner.starten("klein.gguf", port=18101)
    try:
        assert runner.laeuft()
        with pytest.raises(RunnerFehler) as fehler:
            runner.starten("gross.gguf", port=18102)
        assert fehler.value.grund == "laeuft_schon"
    finally:
        runner.stoppen()


def test_gestartet_und_wieder_angehalten(ordner, falsches_programm):
    runner = Modellrunner(ordner, str(falsches_programm))
    lauf = runner.starten("klein.gguf", kontext=2048, schichten=10, port=8099)

    assert lauf.modell == "klein.gguf"
    assert lauf.kontext == 2048
    assert runner.lauf() is not None

    assert runner.stoppen() is True
    assert not runner.laeuft()
    assert runner.lauf() is None


def test_anhalten_ohne_lauf_ist_kein_fehler(ordner, falsches_programm):
    runner = Modellrunner(ordner, str(falsches_programm))
    assert runner.stoppen() is False


# --- Several runners side by side -----------------------------------------
#
# Three of these exist now: the chat model, the embedding server and the
# guardian. They share the class and differ in the name of the variable their
# key lives under. Anything that reads the module constant instead of the
# instance field reaches into a sibling's environment.


def test_jeder_runner_raeumt_nur_seinen_eigenen_schluessel_weg(ordner, falsches_programm):
    chat = Modellrunner(ordner, str(falsches_programm))
    waechter = Modellrunner(
        ordner, str(falsches_programm), schluessel_variable="EXE_TEST_ZWEITER_SCHLUESSEL"
    )

    chat.starten("klein.gguf", port=18111)
    waechter.starten("gross.gguf", port=18112)
    try:
        assert os.environ.get("EXE_RUNNER_API_KEY")
        assert os.environ.get("EXE_TEST_ZWEITER_SCHLUESSEL")

        # Stopping the guardian must leave the chat model able to sign its
        # requests; otherwise every answer comes back unauthorised and the
        # endpoint looks dead for a reason nobody can see.
        waechter.stoppen()

        assert os.environ.get("EXE_RUNNER_API_KEY")
        assert "EXE_TEST_ZWEITER_SCHLUESSEL" not in os.environ
    finally:
        chat.stoppen()
        waechter.stoppen()
        os.environ.pop("EXE_TEST_ZWEITER_SCHLUESSEL", None)


def test_der_letzte_runner_raeumt_seinen_schluessel_wirklich_weg(ordner, falsches_programm):
    runner = Modellrunner(ordner, str(falsches_programm))
    runner.starten("klein.gguf", port=18113)
    assert os.environ.get("EXE_RUNNER_API_KEY")
    runner.stoppen()
    assert "EXE_RUNNER_API_KEY" not in os.environ


# --- Vision companions ----------------------------------------------------


def test_ein_projektor_ist_kein_modell(tmp_path):
    ordner = tmp_path / "modelle"
    ordner.mkdir()
    (ordner / "klein.gguf").write_bytes(b"x" * 10)
    (ordner / "vision").mkdir()
    (ordner / "vision" / "klein-mmproj-Q8_0.gguf").write_bytes(b"x" * 5)
    from app.modellrunner import mmproj_auflisten

    assert [m.name for m in modelle_auflisten(ordner)] == ["klein.gguf"]
    assert mmproj_auflisten(ordner) == ["klein-mmproj-Q8_0.gguf"]


def test_der_befehl_haengt_die_passenden_augen_an(ordner, falsches_programm):
    (ordner / "vision").mkdir()
    (ordner / "vision" / "klein-mmproj-Q8_0.gguf").write_bytes(b"x" * 5)
    runner = Modellrunner(ordner, programm=str(falsches_programm))
    befehl = runner.befehl("klein.gguf", 4096, 33, 8081)
    assert "--mmproj" in befehl
    assert befehl[befehl.index("--mmproj") + 1].endswith("klein-mmproj-Q8_0.gguf")


def test_ohne_augen_kein_mmproj(ordner, falsches_programm):
    runner = Modellrunner(ordner, programm=str(falsches_programm))
    assert "--mmproj" not in runner.befehl("klein.gguf", 4096, 33, 8081)


def test_gewaehlte_augen_schlagen_die_heuristik(ordner, falsches_programm):
    # A projector whose name does not follow the convention — mmproj at the
    # front instead of behind the model prefix — is never auto-paired. Chosen
    # by hand, it is attached all the same.
    (ordner / "vision").mkdir()
    (ordner / "vision" / "mmproj-fremd-f16.gguf").write_bytes(b"x" * 5)
    runner = Modellrunner(ordner, programm=str(falsches_programm))
    assert "--mmproj" not in runner.befehl("klein.gguf", 4096, 33, 8081)
    befehl = runner.befehl("klein.gguf", 4096, 33, 8081, vision="mmproj-fremd-f16.gguf")
    assert befehl[befehl.index("--mmproj") + 1].endswith("mmproj-fremd-f16.gguf")


def test_gewaehlte_augen_ausserhalb_des_ordners_greifen_nicht(ordner, falsches_programm):
    # The chosen name obeys the same folder boundary as every other file a
    # start may reach: a traversal name attaches nothing.
    (ordner / "vision").mkdir()
    runner = Modellrunner(ordner, programm=str(falsches_programm))
    assert "--mmproj" not in runner.befehl(
        "klein.gguf", 4096, 33, 8081, vision="../../etc/passwd"
    )


def test_fremde_augen_bleiben_liegen(ordner, falsches_programm):
    # The shared prefix ends before the word mmproj — those are somebody
    # else's eyes, and attaching them would be worse than none.
    (ordner / "vision").mkdir()
    (ordner / "vision" / "anderes-modell-mmproj-BF16.gguf").write_bytes(b"x" * 5)
    (ordner / "vision" / "mmproj-BF16.gguf").write_bytes(b"x" * 5)
    runner = Modellrunner(ordner, programm=str(falsches_programm))
    assert "--mmproj" not in runner.befehl("klein.gguf", 4096, 33, 8081)


def test_von_zwei_paaren_gewinnt_das_laengere(ordner, falsches_programm):
    (ordner / "Qwen3.6-27B-Q4_K_M.gguf").write_bytes(b"x" * 10)
    (ordner / "vision").mkdir()
    (ordner / "vision" / "Qwen3.6-27B-mmproj-BF16.gguf").write_bytes(b"x" * 5)
    (ordner / "vision" / "Qwen3.6-35B-A3B-mmproj-BF16.gguf").write_bytes(b"x" * 5)
    runner = Modellrunner(ordner, programm=str(falsches_programm))
    befehl = runner.befehl("Qwen3.6-27B-Q4_K_M.gguf", 4096, 33, 8081)
    assert befehl[befehl.index("--mmproj") + 1].endswith("Qwen3.6-27B-mmproj-BF16.gguf")


# --- Loose companions get sorted into their own sub-folders ----------------


def test_begleiter_einsortieren_raeumt_flache_dateien_ein(ordner):
    from app.modellrunner import begleiter_einsortieren, mmproj_auflisten, mtp_auflisten

    (ordner / "gross.gguf").write_bytes(b"x" * 10)
    (ordner / "gross-mmproj-F16.gguf").write_bytes(b"x" * 5)
    (ordner / "gross-mtp-Q4.gguf").write_bytes(BEIFAHRER_KOPF)
    begleiter_einsortieren(ordner)

    # The model stays flat; the companions move into their own folders.
    assert (ordner / "gross.gguf").is_file()
    assert not (ordner / "gross-mmproj-F16.gguf").exists()
    assert (ordner / "vision" / "gross-mmproj-F16.gguf").is_file()
    assert (ordner / "mtp" / "gross-mtp-Q4.gguf").is_file()
    modelle = [m.name for m in modelle_auflisten(ordner)]
    assert "gross.gguf" in modelle
    assert "gross-mmproj-F16.gguf" not in modelle and "gross-mtp-Q4.gguf" not in modelle
    assert mmproj_auflisten(ordner) == ["gross-mmproj-F16.gguf"]
    assert [m.name for m in mtp_auflisten(ordner)] == ["gross-mtp-Q4.gguf"]


def test_begleiter_einsortieren_ueberschreibt_kein_belegtes_ziel(ordner):
    from app.modellrunner import begleiter_einsortieren

    (ordner / "vision").mkdir()
    (ordner / "vision" / "x-mmproj.gguf").write_bytes(b"neu")
    (ordner / "x-mmproj.gguf").write_bytes(b"alt")
    begleiter_einsortieren(ordner)

    # Target name taken → the loose file stays put, nothing is overwritten.
    assert (ordner / "x-mmproj.gguf").read_bytes() == b"alt"
    assert (ordner / "vision" / "x-mmproj.gguf").read_bytes() == b"neu"


# --- A drafter is told by its header, never by its name --------------------


def _gguf_kopf(architektur: str) -> bytes:
    """A GGUF header dummy: magic, version, no tensors, and one key — the
    architecture, the only thing the drafter check reads."""
    import struct

    schluessel = b"general.architecture"
    wert = architektur.encode()
    return (b"GGUF" + struct.pack("<IQQ", 3, 0, 1)
            + struct.pack("<Q", len(schluessel)) + schluessel
            + struct.pack("<I", 8) + struct.pack("<Q", len(wert)) + wert)


BEIFAHRER_KOPF = _gguf_kopf("gemma4-assistant")
MODELL_KOPF = _gguf_kopf("qwen35")


def test_ein_modell_mit_mtp_im_namen_bleibt_in_der_modellwahl(ordner):
    from app.modellrunner import begleiter_einsortieren, mtp_auflisten

    (ordner / "Qwen3.8-27B-IQ3_S-mtp.gguf").write_bytes(MODELL_KOPF)
    begleiter_einsortieren(ordner)

    assert (ordner / "Qwen3.8-27B-IQ3_S-mtp.gguf").is_file()
    assert "Qwen3.8-27B-IQ3_S-mtp.gguf" in [m.name for m in modelle_auflisten(ordner)]
    assert mtp_auflisten(ordner) == []


def test_ein_beifahrer_kopf_wandert_nach_mtp_und_faehrt_mit(ordner):
    from app.modellrunner import begleiter_einsortieren, mtp_auflisten

    (ordner / "mtp-gemma-4-12B-it.gguf").write_bytes(BEIFAHRER_KOPF)
    begleiter_einsortieren(ordner)

    assert (ordner / "mtp" / "mtp-gemma-4-12B-it.gguf").is_file()
    assert [m.name for m in mtp_auflisten(ordner)] == ["mtp-gemma-4-12B-it.gguf"]
    assert "mtp-gemma-4-12B-it.gguf" not in [m.name for m in modelle_auflisten(ordner)]
    befehl = Modellrunner(ordner).befehl("gross.gguf", 4096, 33, 8081, drafter="mtp-gemma-4-12B-it.gguf")
    assert befehl[befehl.index("--spec-type") + 1] == "draft-mtp"


def test_ein_beifahrer_ohne_mtp_im_namen_wird_erkannt(ordner):
    from app.modellrunner import begleiter_einsortieren

    (ordner / "gemma-helfer.gguf").write_bytes(BEIFAHRER_KOPF)
    begleiter_einsortieren(ordner)

    assert (ordner / "mtp" / "gemma-helfer.gguf").is_file()


def test_ein_ganzes_modell_in_mtp_wandert_zurueck(ordner):
    from app.modellrunner import begleiter_einsortieren, mtp_auflisten

    (ordner / "mtp").mkdir()
    (ordner / "mtp" / "Qwen3.8-27B-IQ3_S-mtp.gguf").write_bytes(MODELL_KOPF)
    begleiter_einsortieren(ordner)

    assert not (ordner / "mtp" / "Qwen3.8-27B-IQ3_S-mtp.gguf").exists()
    assert (ordner / "Qwen3.8-27B-IQ3_S-mtp.gguf").read_bytes() == MODELL_KOPF
    assert "Qwen3.8-27B-IQ3_S-mtp.gguf" in [m.name for m in modelle_auflisten(ordner)]
    assert mtp_auflisten(ordner) == []


def test_ein_kaputter_kopf_bleibt_liegen(ordner):
    from app.modellrunner import begleiter_einsortieren, mtp_auflisten

    (ordner / "halb-mtp.gguf").write_bytes(BEIFAHRER_KOPF[:20])
    (ordner / "mtp").mkdir()
    (ordner / "mtp" / "kaputt-mtp.gguf").write_bytes(b"nicht gguf")
    begleiter_einsortieren(ordner)

    assert (ordner / "halb-mtp.gguf").is_file()
    assert (ordner / "mtp" / "kaputt-mtp.gguf").is_file()
    assert mtp_auflisten(ordner) == []


def test_ein_belegtes_ziel_bleibt_unberuehrt_in_beide_richtungen(ordner):
    from app.modellrunner import begleiter_einsortieren

    (ordner / "mtp").mkdir()
    # Model folder → mtp/: the name is taken there.
    (ordner / "helfer.gguf").write_bytes(BEIFAHRER_KOPF + b"alt")
    (ordner / "mtp" / "helfer.gguf").write_bytes(BEIFAHRER_KOPF + b"neu")
    # mtp/ → model folder: the name is taken there.
    (ordner / "mtp" / "modell.gguf").write_bytes(MODELL_KOPF + b"alt")
    (ordner / "modell.gguf").write_bytes(MODELL_KOPF + b"neu")
    begleiter_einsortieren(ordner)

    assert (ordner / "helfer.gguf").read_bytes() == BEIFAHRER_KOPF + b"alt"
    assert (ordner / "mtp" / "helfer.gguf").read_bytes() == BEIFAHRER_KOPF + b"neu"
    assert (ordner / "mtp" / "modell.gguf").read_bytes() == MODELL_KOPF + b"alt"
    assert (ordner / "modell.gguf").read_bytes() == MODELL_KOPF + b"neu"


# --- Sorted with every reading of the folder, not only at the start --------


@pytest.fixture
def nothing_said():
    """The sorting remembers which files it has spoken of; each test starts
    with none."""
    from app import modellrunner

    modellrunner._left_lying.clear()
    yield
    modellrunner._left_lying.clear()


def _tree(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*"))


@pytest.mark.parametrize("first_reading", ["modelle", "mmproj", "pairing"])
def test_a_projector_laid_down_after_the_start_is_found_without_a_restart(ordner, first_reading):
    """A model laid into the folder by hand while the service runs brings
    its projector along loose. Whichever reading of the folder comes first
    sorts it into ``vision/``, and the model is offered its eyes."""
    from app.modellrunner import begleiter_einsortieren, passende_mmproj

    runner = Modellrunner(ordner)
    begleiter_einsortieren(ordner)  # the start of the service: nothing lies loose yet
    assert not (ordner / "vision").exists()
    (ordner / "gross-mmproj-F16.gguf").write_bytes(b"x" * 5)

    if first_reading == "modelle":
        assert [m.name for m in runner.modelle()] == ["gross.gguf", "klein.gguf"]
    elif first_reading == "mmproj":
        assert runner.mmproj() == ["gross-mmproj-F16.gguf"]
    else:
        assert passende_mmproj(ordner, "gross.gguf") == ordner / "vision" / "gross-mmproj-F16.gguf"

    assert not (ordner / "gross-mmproj-F16.gguf").exists()
    assert (ordner / "vision" / "gross-mmproj-F16.gguf").read_bytes() == b"x" * 5
    assert runner.mmproj() == ["gross-mmproj-F16.gguf"]
    assert passende_mmproj(ordner, "gross.gguf") == ordner / "vision" / "gross-mmproj-F16.gguf"
    befehl = runner.befehl("gross.gguf", 4096, 33, 8081)
    assert befehl[befehl.index("--mmproj") + 1].endswith("gross-mmproj-F16.gguf")


def test_a_drafter_laid_down_after_the_start_is_offered_without_a_restart(ordner):
    from app.modellrunner import begleiter_einsortieren

    runner = Modellrunner(ordner)
    begleiter_einsortieren(ordner)
    (ordner / "gemma-helfer.gguf").write_bytes(BEIFAHRER_KOPF)

    assert [m.name for m in runner.mtp()] == ["gemma-helfer.gguf"]
    assert (ordner / "mtp" / "gemma-helfer.gguf").is_file()
    assert "gemma-helfer.gguf" not in [m.name for m in runner.modelle()]


def test_a_file_that_cannot_be_renamed_leaves_the_reading_whole(ordner, monkeypatch, caplog, nothing_said):
    """A projector somebody is still copying is locked on some systems: the
    rename is refused. The reading goes through all the same, the file stays
    where it lies — offered neither as a model nor as a projector — and the
    next reading tries again. The log says it once, not once per reading."""
    from app.modellrunner import begleiter_einsortieren, mmproj_auflisten, mtp_auflisten

    begleiter_einsortieren(ordner)
    loose = ordner / "gross-mmproj-F16.gguf"
    loose.write_bytes(b"x" * 5)
    real_rename = Path.rename
    refused = []

    def locked(self, target):
        if self == loose:
            refused.append(target)
            raise PermissionError(13, "the file is used by another process")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", locked)
    with caplog.at_level("WARNING", logger="app.modellrunner"):
        for _ in range(2):
            assert [m.name for m in modelle_auflisten(ordner)] == ["gross.gguf", "klein.gguf"]
            assert mmproj_auflisten(ordner) == []
            assert mtp_auflisten(ordner) == []
    assert loose.read_bytes() == b"x" * 5
    assert len(refused) == 6, "every reading tries the move again"
    said = [r.getMessage() for r in caplog.records if "stays in place" in r.getMessage()]
    assert len(said) == 1 and "cannot be moved right now" in said[0], said

    monkeypatch.setattr(Path, "rename", real_rename)
    assert mmproj_auflisten(ordner) == ["gross-mmproj-F16.gguf"]
    assert not loose.exists()


def test_a_folder_that_cannot_be_looked_through_leaves_the_reading_to_the_listing(ordner, monkeypatch):
    """The sorting never raises into the reading it is part of."""
    from app import modellrunner

    def unreadable(name):
        raise PermissionError(13, "not allowed")

    # The first look at a file's name fails as an unreadable folder would.
    monkeypatch.setattr(modellrunner, "ist_mmproj", unreadable)
    modellrunner.begleiter_einsortieren(ordner)
    modellrunner._loose_companions_sorted(ordner)


def test_a_whole_model_in_the_drafter_folder_waits_for_the_start(ordner):
    """Silence probe: a reading sorts what lies loose and nothing else. A
    whole model lying in ``mtp/`` drafts from there and moves back with the
    next start, as it always did."""
    from app.modellrunner import begleiter_einsortieren, mtp_auflisten

    begleiter_einsortieren(ordner)
    (ordner / "mtp").mkdir()
    (ordner / "mtp" / "Bonsai-1.7B-Q1_0.gguf").write_bytes(MODELL_KOPF)
    runner = Modellrunner(ordner)

    assert [m.name for m in runner.modelle()] == ["gross.gguf", "klein.gguf"]
    assert runner.mmproj() == [] and mtp_auflisten(ordner) == []
    assert (ordner / "mtp" / "Bonsai-1.7B-Q1_0.gguf").is_file()
    befehl = runner.befehl("gross.gguf", 4096, 33, 8081, drafter="Bonsai-1.7B-Q1_0.gguf")
    assert "--model-draft" in befehl

    begleiter_einsortieren(ordner)
    assert (ordner / "Bonsai-1.7B-Q1_0.gguf").is_file()
    assert not (ordner / "mtp" / "Bonsai-1.7B-Q1_0.gguf").exists()


def test_a_folder_without_loose_companions_is_left_as_it_is(ordner):
    """Silence probe: reading sorts nothing where nothing lies loose, and
    makes no folder for companions that are not there."""
    from app.modellrunner import begleiter_einsortieren, mmproj_auflisten, mtp_auflisten

    (ordner / "vision").mkdir()
    (ordner / "vision" / "klein-mmproj-F16.gguf").write_bytes(b"augen")
    begleiter_einsortieren(ordner)
    before = _tree(ordner)
    stamps = {name: (ordner / name).stat().st_mtime_ns for name in before}

    assert [m.name for m in modelle_auflisten(ordner)] == ["gross.gguf", "klein.gguf"]
    assert mmproj_auflisten(ordner) == ["klein-mmproj-F16.gguf"]
    assert mtp_auflisten(ordner) == []

    assert _tree(ordner) == before
    assert not (ordner / "mtp").exists()
    assert {name: (ordner / name).stat().st_mtime_ns for name in before} == stamps


def test_a_reading_overwrites_no_taken_target_and_says_so_once(ordner, caplog, nothing_said):
    """Silence probe: the reading moves by the same rule as the start — a
    name taken in ``vision/`` keeps its file, the loose one stays loose."""
    from app.modellrunner import begleiter_einsortieren, mmproj_auflisten

    begleiter_einsortieren(ordner)
    (ordner / "vision").mkdir()
    (ordner / "vision" / "x-mmproj.gguf").write_bytes(b"neu")
    (ordner / "x-mmproj.gguf").write_bytes(b"alt")
    with caplog.at_level("WARNING", logger="app.modellrunner"):
        for _ in range(3):
            assert mmproj_auflisten(ordner) == ["x-mmproj.gguf"]
            assert [m.name for m in modelle_auflisten(ordner)] == ["gross.gguf", "klein.gguf"]

    assert (ordner / "x-mmproj.gguf").read_bytes() == b"alt"
    assert (ordner / "vision" / "x-mmproj.gguf").read_bytes() == b"neu"
    said = [r.getMessage() for r in caplog.records if "stays in place" in r.getMessage()]
    assert len(said) == 1 and "target taken" in said[0], said


def test_a_folder_the_start_never_sorted_is_left_as_it_is(ordner):
    """Silence probe: a reading sorts the folders the start sorted and no
    other. A folder for another kind of model is listed and not touched —
    what looks like a companion there is still not offered as a model."""
    from app.modellrunner import mmproj_auflisten, mtp_auflisten

    (ordner / "gross-mmproj-F16.gguf").write_bytes(b"x" * 5)
    (ordner / "gemma-helfer.gguf").write_bytes(BEIFAHRER_KOPF)
    before = _tree(ordner)

    assert [m.name for m in modelle_auflisten(ordner)] == ["gross.gguf", "klein.gguf"]
    assert mmproj_auflisten(ordner) == []
    assert mtp_auflisten(ordner) == []
    assert _tree(ordner) == before


def test_readings_at_the_same_time_move_a_file_once(ordner, monkeypatch, caplog, nothing_said):
    """The window asks for its lists from several threads at once. One of
    them moves the loose projector, the others wait and find it sorted —
    none of them finds its source gone halfway."""
    import threading
    import time

    from app.modellrunner import begleiter_einsortieren, mmproj_auflisten

    begleiter_einsortieren(ordner)
    loose = ordner / "gross-mmproj-F16.gguf"
    loose.write_bytes(b"x" * 5)
    real_rename = Path.rename
    moves = []

    def slow(self, target):
        moves.append(self)
        # Long enough for every other thread to have looked at the folder.
        time.sleep(0.2)
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", slow)
    together = threading.Barrier(6)
    answers = []

    def read():
        together.wait()
        answers.append(mmproj_auflisten(ordner))

    with caplog.at_level("WARNING", logger="app.modellrunner"):
        threads = [threading.Thread(target=read) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert answers == [["gross-mmproj-F16.gguf"]] * 6
    assert moves == [loose]
    assert not [r.getMessage() for r in caplog.records if "stays in place" in r.getMessage()]


# --- The folder manifest wins over the name heuristic ----------------------


def test_der_befehl_bevorzugt_das_manifest_gegenueber_der_heuristik(ordner, falsches_programm):
    from app import modellzuordnung

    # The heuristic would tie klein.gguf to its prefix twin; the manifest
    # names a different projector, and the manifest is the one to trust.
    (ordner / "vision").mkdir()
    (ordner / "vision" / "klein-mmproj-Q8_0.gguf").write_bytes(b"x" * 5)
    (ordner / "vision" / "spezial-mmproj.gguf").write_bytes(b"x" * 5)
    modellzuordnung.eintragen(ordner, "klein.gguf", "mmproj", "spezial-mmproj.gguf")

    runner = Modellrunner(ordner, programm=str(falsches_programm))
    befehl = runner.befehl("klein.gguf", 4096, 33, 8081)
    assert befehl[befehl.index("--mmproj") + 1].endswith("spezial-mmproj.gguf")


def test_starten_nimmt_den_mtp_aus_dem_manifest(ordner, falsches_programm, monkeypatch):
    from app import modellzuordnung
    import app.modellrunner as mr

    # A draft declared in the manifest is picked up when the caller passes
    # none, so the bond survives a restart and the command carries it.
    (ordner / "mtp").mkdir()
    (ordner / "mtp" / "klein-mtp-Q8.gguf").write_bytes(BEIFAHRER_KOPF)
    modellzuordnung.eintragen(ordner, "klein.gguf", "mtp", "klein-mtp-Q8.gguf")

    aufgezeichnet = {}
    echtes_popen = mr.subprocess.Popen

    def merken(befehl, *args, **kwargs):
        aufgezeichnet["befehl"] = befehl
        return echtes_popen(befehl, *args, **kwargs)

    monkeypatch.setattr(mr.subprocess, "Popen", merken)

    runner = Modellrunner(ordner, programm=str(falsches_programm))
    try:
        lauf = runner.starten("klein.gguf", port=18097)
        assert lauf.drafter == "klein-mtp-Q8.gguf"
        befehl = aufgezeichnet["befehl"]
        assert befehl[befehl.index("--model-draft") + 1].endswith("klein-mtp-Q8.gguf")
        assert befehl[befehl.index("--spec-type") + 1] == "draft-mtp"
    finally:
        runner.stoppen()


def test_start_takes_a_sibling_draft_from_the_manifest(
    ordner, falsches_programm, monkeypatch
):
    """A sibling model noted as the draft lies in the model folder (the start
    puts a whole model that was fetched into mtp/ back there): without a
    chosen draft the start finds it through the note and names the plain
    draft path."""
    from app import modellzuordnung
    import app.modellrunner as mr

    (ordner / "geschwister.gguf").write_bytes(b"x" * 5)
    modellzuordnung.eintragen(ordner, "klein.gguf", "mtp", "geschwister.gguf")

    aufgezeichnet = {}
    echtes_popen = mr.subprocess.Popen

    def merken(befehl, *args, **kwargs):
        aufgezeichnet["befehl"] = befehl
        return echtes_popen(befehl, *args, **kwargs)

    monkeypatch.setattr(mr.subprocess, "Popen", merken)

    runner = Modellrunner(ordner, programm=str(falsches_programm))
    try:
        lauf = runner.starten("klein.gguf", port=18098)
        assert lauf.drafter == "geschwister.gguf"
        befehl = aufgezeichnet["befehl"]
        assert befehl[befehl.index("--model-draft") + 1] == str(ordner / "geschwister.gguf")
        assert befehl[befehl.index("--spec-type") + 1] == "draft-simple"
    finally:
        runner.stoppen()


def test_without_a_draft_and_without_built_in_layers_there_is_no_spec_type(
    ordner, falsches_programm
):
    runner = Modellrunner(ordner, programm=str(falsches_programm))
    befehl = runner.befehl("klein.gguf", 4096, 33, 8081)
    assert "--spec-type" not in befehl
    assert "--model-draft" not in befehl


def _start_and_capture(folder, program, monkeypatch, **options):
    import app.modellrunner as mr

    captured = {}
    real_popen = mr.subprocess.Popen

    def capture(command, *args, **kwargs):
        # The first process only: the stop afterwards runs ``taskkill``
        # through subprocess.run on Windows, and that builds its process
        # with this very ``Popen`` (measured: the captured line was the
        # taskkill call, not the server's).
        captured.setdefault("command", command)
        return real_popen(command, *args, **kwargs)

    monkeypatch.setattr(mr.subprocess, "Popen", capture)
    runner = Modellrunner(folder, programm=str(program))
    try:
        runner.starten("gross.gguf", port=18098, **options)
    finally:
        runner.stoppen()
    assert "command" in captured, "the server was never started"
    return captured["command"]


def test_a_sibling_model_from_the_model_folder_drafts(ordner, falsches_programm, monkeypatch):
    """The model window offers small siblings from the model folder itself as
    a draft; the start used to look only in mtp/ and refused them."""
    command = _start_and_capture(ordner, falsches_programm, monkeypatch, drafter="klein.gguf")
    assert command[command.index("--model-draft") + 1] == str(ordner / "klein.gguf")
    # A whole model drafts by the plain path, and the engine has to be told
    # so: its default is no speculative backend at all.
    assert command[command.index("--spec-type") + 1] == "draft-simple"


def test_a_drafter_from_mtp_drafts_as_before(ordner, falsches_programm, monkeypatch):
    (ordner / "mtp").mkdir()
    (ordner / "mtp" / "gross-mtp-Q8.gguf").write_bytes(BEIFAHRER_KOPF)
    command = _start_and_capture(ordner, falsches_programm, monkeypatch, drafter="gross-mtp-Q8.gguf")
    assert command[command.index("--model-draft") + 1] == str(ordner / "mtp" / "gross-mtp-Q8.gguf")
    assert command[command.index("--spec-type") + 1] == "draft-mtp"


@pytest.mark.parametrize(
    "name",
    # Outside both folders, missing, the main model itself in any spelling,
    # and files beside the models that are no model (the manifest, a
    # download in progress, a projector).
    [
        "../outside.gguf", "missing.gguf", "gross.gguf", "GROSS.gguf", "alias.gguf", "hard.gguf",
        "keinmodell.txt", "zuordnung.json", "x.gguf.teil", "x-mmproj-F16.gguf",
        "nope/../klein.gguf", "/etc/hosts",
    ],
)
def test_a_draft_that_is_no_other_model_is_refused(ordner, falsches_programm, name):
    (ordner.parent / "outside.gguf").write_bytes(b"x" * 100)
    (ordner / "zuordnung.json").write_text("{}")
    (ordner / "x.gguf.teil").write_bytes(b"x" * 100)
    (ordner / "x-mmproj-F16.gguf").write_bytes(b"x" * 100)
    (ordner / "alias.gguf").symlink_to(ordner / "gross.gguf")
    os.link(ordner / "gross.gguf", ordner / "hard.gguf")
    runner = Modellrunner(ordner, programm=str(falsches_programm))
    with pytest.raises(RunnerFehler) as error:
        runner.starten("gross.gguf", port=18099, drafter=name)
    assert str(error.value) == "kein_modell"
    assert not runner.laeuft()


# --- The drafter riding inside the model's own file -------------------------
# The same key llama.cpp itself writes on an architecture that carries its
# own prediction layers — never a name or a repository, only the header.


def _mtp_gguf_bytes() -> bytes:
    schluessel = b"qwen35moe.nextn_predict_layers"
    kopf = bytearray(b"GGUF")
    kopf += (3).to_bytes(4, "little")  # version
    kopf += (0).to_bytes(8, "little")  # tensor count
    kopf += (1).to_bytes(8, "little")  # one metadata pair
    kopf += len(schluessel).to_bytes(8, "little") + schluessel
    kopf += (4).to_bytes(4, "little")  # value type: u32
    kopf += (1).to_bytes(4, "little")  # one embedded prediction layer
    return bytes(kopf)


def _echtes_aber_gewoehnliches_gguf_bytes() -> bytes:
    schluessel = b"general.architecture"
    wert = b"qwen35moe"
    kopf = bytearray(b"GGUF")
    kopf += (3).to_bytes(4, "little")
    kopf += (0).to_bytes(8, "little")
    kopf += (1).to_bytes(8, "little")
    kopf += len(schluessel).to_bytes(8, "little") + schluessel
    kopf += (8).to_bytes(4, "little")  # value type: string
    kopf += len(wert).to_bytes(8, "little") + wert
    return bytes(kopf)


def test_der_befehl_setzt_spec_type_fuer_eingebettetes_mtp_ohne_drafter(ordner, falsches_programm):
    (ordner / "mtp-modell.gguf").write_bytes(_mtp_gguf_bytes())
    runner = Modellrunner(ordner, str(falsches_programm))
    befehl = runner.befehl("mtp-modell.gguf", 4096, 33, 8081)
    assert befehl[befehl.index("--spec-type") + 1] == "draft-mtp"
    assert "--model-draft" not in befehl


def test_der_befehl_laesst_ein_modell_ohne_das_merkmal_unangetastet(ordner, falsches_programm):
    (ordner / "normal.gguf").write_bytes(_echtes_aber_gewoehnliches_gguf_bytes())
    runner = Modellrunner(ordner, str(falsches_programm))
    befehl = runner.befehl("normal.gguf", 4096, 33, 8081)
    assert "--spec-type" not in befehl


def test_ein_gewaehlter_drafter_gewinnt_gegen_das_eingebettete_merkmal(ordner, falsches_programm):
    # The main model's own header carries the marker too — the caller's
    # explicit choice must still be the only one that is obeyed, and the
    # flag must appear exactly once.
    (ordner / "mtp-modell.gguf").write_bytes(_mtp_gguf_bytes())
    (ordner / "mtp").mkdir()
    (ordner / "mtp" / "klein-mtp-Q8.gguf").write_bytes(BEIFAHRER_KOPF)
    runner = Modellrunner(ordner, str(falsches_programm))
    befehl = runner.befehl("mtp-modell.gguf", 4096, 33, 8081, drafter="klein-mtp-Q8.gguf")
    assert befehl[befehl.index("--model-draft") + 1].endswith("klein-mtp-Q8.gguf")
    assert befehl.count("--spec-type") == 1
    assert befehl[befehl.index("--spec-type") + 1] == "draft-mtp"


def test_starten_erkennt_eingebettetes_mtp_fuer_den_blitz(ordner, falsches_programm):
    (ordner / "mtp-modell.gguf").write_bytes(_mtp_gguf_bytes())
    runner = Modellrunner(ordner, programm=str(falsches_programm))
    try:
        lauf = runner.starten("mtp-modell.gguf", port=18098)
        # No companion file exists — the bolt's proof comes from the log,
        # not from a drafter name that was never there to begin with.
        assert lauf.drafter is None
        assert runner._drafter_gewuenscht is True
    finally:
        runner.stoppen()


def test_starten_ohne_das_merkmal_erwartet_keinen_drafter(ordner, falsches_programm):
    (ordner / "normal.gguf").write_bytes(_echtes_aber_gewoehnliches_gguf_bytes())
    runner = Modellrunner(ordner, programm=str(falsches_programm))
    try:
        runner.starten("normal.gguf", port=18100)
        assert runner._drafter_gewuenscht is False
    finally:
        runner.stoppen()


# --- The orphan after a service restart ------------------------------------


def test_der_start_merkt_sich_die_pid(ordner, falsches_programm):
    from app.modellrunner import PID_DATEI
    import json

    runner = Modellrunner(ordner, programm=str(falsches_programm))
    lauf = runner.starten("klein.gguf", port=18099)
    assert lauf is not None
    notiz = json.loads((ordner / PID_DATEI).read_text())
    assert notiz["pid"] == runner._prozess.pid
    runner.stoppen()
    assert not (ordner / PID_DATEI).exists()


def test_aufraeumen_beendet_nur_echte_server(ordner):
    from app.modellrunner import PID_DATEI
    import json, subprocess

    schlaefer = subprocess.Popen(_SLEEPER, start_new_session=True)
    (ordner / PID_DATEI).write_text(json.dumps({"pid": schlaefer.pid}))
    runner = Modellrunner(ordner)

    # Somebody else's process id: the note goes, the process stays.
    assert runner.aufraeumen(ist_unserer=lambda pid: False) is False
    assert not (ordner / PID_DATEI).exists()
    assert schlaefer.poll() is None

    # Our own kind: it gets ended.
    (ordner / PID_DATEI).write_text(json.dumps({"pid": schlaefer.pid}))
    assert runner.aufraeumen(ist_unserer=lambda pid: True) is True
    schlaefer.wait(timeout=5)


def test_aufraeumen_ohne_notiz_ist_still(ordner):
    assert Modellrunner(ordner).aufraeumen() is False


def test_ein_belegter_port_faellt_sofort_auf(ordner, falsches_programm):
    import socket

    with socket.socket() as belegt:
        belegt.bind(("127.0.0.1", 0))
        belegt.listen(1)
        port = belegt.getsockname()[1]
        runner = Modellrunner(ordner, programm=str(falsches_programm))
        try:
            runner.starten("klein.gguf", port=port)
            raise AssertionError("no error")
        except RunnerFehler as fehler:
            assert fehler.grund == "port_belegt"


# --- Reading flash attention's true state off the log ----------------------


class _LaufenderProzess:
    """A stand-in for a live server process: the log-reading tests never spawn
    a real one, but the state methods now gate on ``laeuft()`` — the log flags
    survive a stopped process, the reported state must not — so a runner under
    test must count as running for its log lines to be read at all."""

    pid = 0

    def poll(self):
        return None


def test_flash_attn_zustand_ohne_protokoll_ist_unbekannt(ordner):
    assert Modellrunner(ordner).flash_attn_zustand() is None


def test_flash_attn_zustand_liest_die_eigene_zeile_des_servers(ordner):
    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    runner._zeile_aufnehmen("llama_context: n_ctx     = 32768")
    runner._zeile_aufnehmen("llama_context: flash_attn    = enabled")
    assert runner.flash_attn_zustand() is True


def test_flash_attn_zustand_nimmt_die_letzte_zeile(ordner):
    """A second load in the same process — reload, restart — must not answer
    with the first one's word once a newer line disagrees with it."""
    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    runner._zeile_aufnehmen("llama_context: flash_attn    = enabled")
    runner._zeile_aufnehmen("llama_context: flash_attn    = disabled")
    assert runner.flash_attn_zustand() is False


def test_flash_attn_zustand_ignoriert_fremde_zeilen(ordner):
    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    runner._zeile_aufnehmen("srv  params_from_: some other line entirely")
    assert runner.flash_attn_zustand() is None


def test_flash_attn_zustand_ueberlebt_den_vollen_ringpuffer(ordner):
    """The load-time line is written once; a busy server then pushes it out
    of the 400-line ring buffer. The answer must survive that."""
    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    runner._zeile_aufnehmen("llama_context: flash_attn    = enabled")
    for n in range(500):
        runner._zeile_aufnehmen(f"srv  log: request {n}")
    assert runner.flash_attn_zustand() is True


def test_flash_attn_zustand_liest_die_entscheidungszeile(ordner):
    """Newer engine builds put the result into a line of their own — the
    exact line as measured on the engine, timestamp prefix and all."""
    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    runner._zeile_aufnehmen("0.00.445.451 I resolve_fused_ops: Flash Attention enabled")
    assert runner.flash_attn_zustand() is True


def test_flash_attn_zustand_entscheidungszeile_disabled(ordner):
    """The guard on the second wording: no model at hand produced it, so the
    line is covered here — a reported "disabled" must come through as off."""
    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    runner._zeile_aufnehmen("0.00.445.451 I resolve_fused_ops: Flash Attention disabled")
    assert runner.flash_attn_zustand() is False


def test_flash_attn_zustand_wunschzeile_auto_bleibt_unbekannt(ordner):
    """Newer builds' configuration line only repeats the wish ("auto") —
    it must not count as an answer, in neither direction."""
    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    runner._zeile_aufnehmen("0.00.427.233 I llama_context: flash_attn    = auto")
    assert runner.flash_attn_zustand() is None


def test_flash_attn_zustand_entscheidung_folgt_auf_den_wunsch(ordner):
    """The measured order of a real start: the wish line first ("auto"),
    the decision a few lines later. The decision must land."""
    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    runner._zeile_aufnehmen("0.00.427.233 I llama_context: flash_attn    = auto")
    runner._zeile_aufnehmen("0.00.445.451 I resolve_fused_ops: Flash Attention enabled")
    assert runner.flash_attn_zustand() is True


def test_flash_attn_zustand_schweigt_ohne_die_zeile(ordner):
    """The silence check: a server that reaches "model loaded" without ever
    saying a word about flash attention keeps answering "unknown" — never
    a made-up off."""
    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    runner._zeile_aufnehmen("0.00.509.115 I srv  llama_server: model loaded")
    assert runner.flash_attn_zustand() is None


def test_flash_attn_zustand_ist_none_wenn_server_aus(ordner):
    """The load-time line stays in the buffer after the process dies; the
    reported state must not. A server that is no longer running answers
    "unknown", not the word it printed while it was up."""
    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    runner._zeile_aufnehmen("llama_context: flash_attn    = enabled")
    assert runner.flash_attn_zustand() is True
    runner._prozess = None
    assert runner.flash_attn_zustand() is None


# --- The drafter's honest state (MTP), read off the same log --------------
# The two lines below are the real ones a llama-server (build 10310) prints:
# the speculative-init line comes BEFORE "model loaded", so a "model loaded"
# without it means the drafter was set but never engaged.
_MTP_ZEILE = "0.00.886 I common_speculative_init_result: loading draft model 'm.gguf'"
_BEREIT_ZEILE = "0.01.084 I srv  llama_server: model loaded"


def test_mtp_ohne_drafter_ist_nichts(ordner):
    """No drafter asked for → nothing to show, whatever the log says."""
    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    runner._zeile_aufnehmen(_BEREIT_ZEILE)
    assert runner.mtp_zustand() is None


def test_mtp_aktiv_wenn_die_speculative_zeile_kam(ordner):
    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    runner._drafter_gewuenscht = True
    runner._zeile_aufnehmen(_MTP_ZEILE)
    runner._zeile_aufnehmen(_BEREIT_ZEILE)
    assert runner.mtp_zustand() == "aktiv"


def test_mtp_fehler_wenn_server_hochkam_ohne_die_zeile(ordner):
    """Drafter configured, server reached "model loaded", but the speculative
    line never appeared — the pairing did not take."""
    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    runner._drafter_gewuenscht = True
    runner._zeile_aufnehmen(_BEREIT_ZEILE)
    assert runner.mtp_zustand() == "fehler"


_NO_BACKEND_LINE = (
    "0.00.887 W common_speculative_init: no implementations specified for speculative decoding"
)


def test_mtp_error_when_the_server_says_no_backend_was_chosen(ordner):
    """The draft file was loaded (the init line passed) and the server then
    says no way of drafting was chosen: nothing drafts, so the bolt is red,
    not blue — and at once, without waiting for "model loaded"."""
    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    runner._drafter_gewuenscht = True
    runner._zeile_aufnehmen(_MTP_ZEILE)
    runner._zeile_aufnehmen(_NO_BACKEND_LINE)
    assert runner.mtp_zustand() == "fehler"
    runner._zeile_aufnehmen(_BEREIT_ZEILE)
    assert runner.mtp_zustand() == "fehler"


def test_mtp_stays_active_without_the_no_backend_line(ordner):
    """Silence probe: the init line alone, as with a chosen mode, stays blue."""
    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    runner._drafter_gewuenscht = True
    runner._zeile_aufnehmen(_MTP_ZEILE)
    runner._zeile_aufnehmen("0.00.887 I common_speculative_init: using draft-simple")
    runner._zeile_aufnehmen(_BEREIT_ZEILE)
    assert runner.mtp_zustand() == "aktiv"


def test_mtp_laedt_noch_ist_nichts(ordner):
    """Drafter configured but the server has not reached ready yet: grey, not
    a premature red."""
    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    runner._drafter_gewuenscht = True
    assert runner.mtp_zustand() is None


def test_mtp_zustand_ueberlebt_den_vollen_ringpuffer(ordner):
    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    runner._drafter_gewuenscht = True
    runner._zeile_aufnehmen(_MTP_ZEILE)
    runner._zeile_aufnehmen(_BEREIT_ZEILE)
    for n in range(500):
        runner._zeile_aufnehmen(f"srv  log: request {n}")
    assert runner.mtp_zustand() == "aktiv"


def test_mtp_zustand_ist_none_wenn_server_aus(ordner):
    """The same liveness rule for the drafter: once the process is gone the
    bolt goes grey, even though the speculative line is still in the buffer."""
    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    runner._drafter_gewuenscht = True
    runner._zeile_aufnehmen(_MTP_ZEILE)
    runner._zeile_aufnehmen(_BEREIT_ZEILE)
    assert runner.mtp_zustand() == "aktiv"
    runner._prozess = None
    assert runner.mtp_zustand() is None


# --- Measuring how long a load took ----------------------------


def test_bereit_callback_bekommt_modell_und_dauer(ordner):
    """The callback fires once the ready line passes, with the model this
    run started and a real elapsed duration — never before, and never
    without one asked for."""
    aufrufe = []
    runner = Modellrunner(ordner, bereit_callback=lambda m, s: aufrufe.append((m, s)))
    runner._lauf = Lauf(modell="klein.gguf", kontext=8192, schichten=99, port=8080)
    runner._start_zeit = time.monotonic() - 0.05
    runner._zeile_aufnehmen(_BEREIT_ZEILE)
    assert len(aufrufe) == 1
    modell, dauer = aufrufe[0]
    assert modell == "klein.gguf"
    # Two readings of the clock, subtracted: on Windows the difference
    # comes out a hair under the 0.05 that was taken off (measured:
    # 0.049999999999954525), so a hair is allowed.
    assert dauer >= 0.05 - 1e-6


def test_ohne_bereit_callback_passiert_nichts(ordner):
    runner = Modellrunner(ordner)  # no callback given
    runner._lauf = Lauf(modell="klein.gguf", kontext=8192, schichten=99, port=8080)
    runner._start_zeit = time.monotonic()
    runner._zeile_aufnehmen(_BEREIT_ZEILE)  # must not raise


def test_bereit_callback_feuert_nur_einmal(ordner):
    """A busy log ring buffer can push the ready line back through in
    theory — the callback must not fire a second time for the same start."""
    aufrufe = []
    runner = Modellrunner(ordner, bereit_callback=lambda m, s: aufrufe.append((m, s)))
    runner._lauf = Lauf(modell="klein.gguf", kontext=8192, schichten=99, port=8080)
    runner._start_zeit = time.monotonic()
    runner._zeile_aufnehmen(_BEREIT_ZEILE)
    runner._zeile_aufnehmen(_BEREIT_ZEILE)
    assert len(aufrufe) == 1


def test_bereit_callback_ohne_fehler_bringt_den_leser_nicht_um(ordner, caplog):
    """A broken store (a full disk, say) must cost the measurement, never
    the reader thread that is still keeping the rest of the log."""
    def _wirft(modell, sekunden):
        raise RuntimeError("kaputt")

    runner = Modellrunner(ordner, bereit_callback=_wirft)
    runner._lauf = Lauf(modell="klein.gguf", kontext=8192, schichten=99, port=8080)
    runner._start_zeit = time.monotonic()
    with caplog.at_level("ERROR"):
        runner._zeile_aufnehmen(_BEREIT_ZEILE)  # must not raise
    assert "klein.gguf" in caplog.text


def test_ein_echter_start_ueber_die_app_landet_als_messung(config, client):
    """End to end, through app/main.py's own wiring —
    not a callback hand-rolled in the test. Two mutations used to survive
    the whole test run unnoticed: dropping ``self._start_zeit =
    time.monotonic()`` from ``starten()``, and dropping the
    ``bereit_callback=`` argument from the runner's construction in
    main.py. Neither breaks a single existing test, because every other
    test injects ``_lauf``/``_start_zeit`` by hand or checks the callback
    contract in isolation — none of them ever go through a real start."""
    from app import modellvorlauf

    # The runner's own folder was fixed at app startup, before this test's
    # tmp_path existed — pointed here the same way ``ordner`` in every
    # other test of this file stands in for it, private attribute and all.
    modellordner = config.datenverzeichnis / "modelle"
    modellordner.mkdir(parents=True, exist_ok=True)
    (modellordner / "klein.gguf").write_bytes(b"x")
    programm = fake_server(
        config.datenverzeichnis / "llama-server", says=["llama_server: model loaded"]
    )

    runner = client.app.state.modellrunner
    runner._ordner = modellordner
    runner._programm_vorgabe = str(programm)
    runner.starten("klein.gguf", port=18106)
    try:
        repositories = client.app.state.repositories
        # Ten seconds, not two. What is waited for is a real process being
        # spawned and a reader thread getting to its first line, and two
        # seconds is generous when this test runs alone and not generous at
        # all when three thousand others are running with it — measured, it
        # is the only way this test has ever failed. A passing run still
        # returns on the first tick; the ceiling only decides how long a
        # loaded machine may take before the test calls it a failure.
        for _ in range(500):
            if modellvorlauf.messung_holen(repositories, "klein.gguf") is not None:
                break
            time.sleep(0.02)
        gemessen = modellvorlauf.messung_holen(repositories, "klein.gguf")
        assert gemessen is not None
        assert gemessen >= 0
    finally:
        runner.stoppen()


# --- "chosen: none" reaches the command line ------


def test_gewaehlt_keine_augen_schlaegt_die_heuristik(ordner, falsches_programm):
    """`""` is "chosen: no projector" and stops the pairing.

    `None` means nobody said, and then the manifest or the name heuristic
    speaks. Folding the two together is how a model whose eyes were switched
    off by hand got them back on the next start.
    """
    (ordner / "vision").mkdir()
    (ordner / "vision" / "klein-mmproj-Q8_0.gguf").write_bytes(b"x" * 5)
    runner = Modellrunner(ordner, programm=str(falsches_programm))
    assert "--mmproj" in runner.befehl("klein.gguf", 4096, 33, 8081)
    assert "--mmproj" not in runner.befehl("klein.gguf", 4096, 33, 8081, vision="")


def test_gewaehlt_keine_augen_schlaegt_auch_das_manifest(ordner, falsches_programm):
    from app import modellzuordnung

    (ordner / "vision").mkdir()
    (ordner / "vision" / "spezial-mmproj.gguf").write_bytes(b"x" * 5)
    modellzuordnung.eintragen(ordner, "klein.gguf", "mmproj", "spezial-mmproj.gguf")
    runner = Modellrunner(ordner, programm=str(falsches_programm))
    assert "--mmproj" in runner.befehl("klein.gguf", 4096, 33, 8081)
    assert "--mmproj" not in runner.befehl("klein.gguf", 4096, 33, 8081, vision="")


def test_gewaehlt_kein_drafter_holt_nichts_aus_dem_manifest(ordner, falsches_programm):
    from app import modellzuordnung

    (ordner / "mtp").mkdir()
    (ordner / "mtp" / "klein-mtp-Q8.gguf").write_bytes(BEIFAHRER_KOPF)
    modellzuordnung.eintragen(ordner, "klein.gguf", "mtp", "klein-mtp-Q8.gguf")
    runner = Modellrunner(ordner, programm=str(falsches_programm))
    try:
        lauf = runner.starten("klein.gguf", port=18122, drafter="")
        assert lauf.drafter == ""
    finally:
        runner.stoppen()
    runner2 = Modellrunner(ordner, programm=str(falsches_programm))
    try:
        # Nobody said: the manifest still speaks, exactly as before.
        lauf = runner2.starten("klein.gguf", port=18123)
        assert lauf.drafter == "klein-mtp-Q8.gguf"
    finally:
        runner2.stoppen()


# --- Announcing the state instead of being asked for it --------------------
#
# Three readouts in the window used to fetch this on beats of their own, and
# the answer changes about twice a day. The runner says it now. The fourth
# fire point is the one worth guarding: neither flash attention nor the
# drafter is settled at start, so a start announcement alone would say
# "unknown" about both.


def _melder():
    """Collects what the runner announces, in order — the first three facts;
    the fourth, the unknown architecture, has its own collector below."""
    gehoert: list[tuple[bool, bool | None, str | None]] = []
    return gehoert, lambda laeuft, flash, mtp, arch=None: gehoert.append((laeuft, flash, mtp))


def _melder_vier():
    """Collects all four facts, in order."""
    gehoert: list[tuple[bool, bool | None, str | None, str | None]] = []
    return gehoert, lambda *tatsachen: gehoert.append(tatsachen)


def test_der_start_meldet_dass_der_server_da_ist(ordner, falsches_programm):
    gehoert, melden = _melder()
    runner = Modellrunner(
        ordner, str(falsches_programm), zustand_callback=melden
    )
    try:
        runner.starten("klein.gguf", port=18130)
    finally:
        runner.stoppen()
    # Up with nothing known about flash yet, then down again.
    assert gehoert == [(True, None, None), (False, None, None)]


def test_ein_start_der_scheitert_meldet_nichts(ordner, falsches_programm):
    gehoert, melden = _melder()
    runner = Modellrunner(
        ordner, str(falsches_programm), zustand_callback=melden
    )
    with pytest.raises(RunnerFehler):
        runner.starten("gibtsnicht.gguf", port=18131)
    assert gehoert == []


def test_anhalten_ohne_lauf_meldet_nichts(ordner, falsches_programm):
    gehoert, melden = _melder()
    runner = Modellrunner(
        ordner, str(falsches_programm), zustand_callback=melden
    )
    assert runner.stoppen() is False
    assert gehoert == []


def test_die_flash_zeile_meldet_sich_von_selbst(ordner):
    """The fire point that is easy to miss. Without it the dot stays grey
    under a server that has long been up."""
    gehoert, melden = _melder()
    runner = Modellrunner(ordner, zustand_callback=melden)
    runner._prozess = _LaufenderProzess()
    runner._zeile_aufnehmen("llama_context: n_ctx     = 32768")
    assert gehoert == []
    runner._zeile_aufnehmen("llama_context: flash_attn    = enabled")
    assert gehoert == [(True, True, None)]


def test_dieselbe_flash_zeile_meldet_sich_nur_einmal(ordner):
    """Every line of the server's output passes through here, and the
    configuration line can repeat what the decision line already said."""
    gehoert, melden = _melder()
    runner = Modellrunner(ordner, zustand_callback=melden)
    runner._prozess = _LaufenderProzess()
    runner._zeile_aufnehmen("llama_context: flash_attn    = enabled")
    runner._zeile_aufnehmen("llama_context: flash_attn    = enabled")
    assert gehoert == [(True, True, None)]
    # A server that contradicts itself is worth a second word.
    runner._zeile_aufnehmen("llama_context: flash_attn    = disabled")
    assert gehoert == [(True, True, None), (True, False, None)]


def test_ein_eingesammelter_waise_wird_gemeldet(ordner):
    from app.modellrunner import PID_DATEI
    import json, subprocess

    gehoert, melden = _melder()
    schlaefer = subprocess.Popen(_SLEEPER, start_new_session=True)
    (ordner / PID_DATEI).write_text(json.dumps({"pid": schlaefer.pid}))
    runner = Modellrunner(ordner, zustand_callback=melden)

    # Somebody else's process: nothing was collected, so nothing is said.
    assert runner.aufraeumen(ist_unserer=lambda pid: False) is False
    assert gehoert == []

    (ordner / PID_DATEI).write_text(json.dumps({"pid": schlaefer.pid}))
    assert runner.aufraeumen(ist_unserer=lambda pid: True) is True
    schlaefer.wait(timeout=5)
    assert gehoert == [(False, None, None)]


def test_ein_runner_ohne_rueckruf_laeuft_wie_zuvor(ordner, falsches_programm):
    """The embedding, speech and vision runners get none — and must not
    notice that there is one to get."""
    runner = Modellrunner(ordner, str(falsches_programm))
    try:
        assert runner.starten("klein.gguf", port=18132) is not None
    finally:
        runner.stoppen()


def test_ein_kaputter_zuhoerer_haelt_den_lesefaden_nicht_auf(ordner):
    """This runs on the thread that drains the server's output. A thread
    that dies there stops the pipe, and the server blocks mid-load."""
    def melden(laeuft, flash, mtp):
        raise RuntimeError("kaputt")

    runner = Modellrunner(ordner, zustand_callback=melden)
    runner._prozess = _LaufenderProzess()
    runner._zeile_aufnehmen("llama_context: flash_attn    = enabled")
    assert runner.flash_attn_zustand() is True


def test_der_drafter_meldet_sich_wenn_er_wirklich_greift(ordner):
    """The lamp in the input bar had its own six-second beat for this. The
    answer is settled the same way flash attention is: off a line the server
    prints on its own."""
    gehoert, melden = _melder()
    runner = Modellrunner(ordner, zustand_callback=melden)
    runner._prozess = _LaufenderProzess()
    runner._drafter_gewuenscht = True
    runner._zeile_aufnehmen(_MTP_ZEILE)
    assert gehoert == [(True, None, "aktiv")]


def test_ein_drafter_der_nie_ansprang_meldet_den_fehler(ordner):
    """Configured is not running: the server reached "model loaded" without
    the draft's own line, and that is the red case worth seeing."""
    gehoert, melden = _melder()
    runner = Modellrunner(ordner, zustand_callback=melden)
    runner._prozess = _LaufenderProzess()
    runner._drafter_gewuenscht = True
    runner._zeile_aufnehmen(_BEREIT_ZEILE)
    assert gehoert == [(True, None, "fehler")]


def test_ohne_drafter_meldet_die_bereitzeile_gar_nichts(ordner):
    """Nothing was asked for, so the ready line moves no answer — and an
    announcement that repeats what was already said is not sent."""
    gehoert, melden = _melder()
    runner = Modellrunner(ordner, zustand_callback=melden)
    runner._prozess = _LaufenderProzess()
    runner._zeile_aufnehmen(_BEREIT_ZEILE)
    assert gehoert == []


def test_dasselbe_zweimal_wird_nur_einmal_gesagt(ordner):
    """Every fire point may announce whenever it likes. What the window is
    spared is the repetition, and that is decided in one place."""
    gehoert, melden = _melder()
    runner = Modellrunner(ordner, zustand_callback=melden)
    runner._prozess = _LaufenderProzess()
    runner._zustand_melden()
    runner._zustand_melden()
    assert gehoert == [(True, None, None)]


class _ToterProzess:
    """A process whose pipe has closed, modelled the way the kernel really
    behaves: the fds go first, and only a ``wait`` makes it reapable. Until
    then ``poll`` still answers None, which is what ``laeuft()`` reads.

    Driven by hand rather than really killed: a real one leaves the timing of
    its children between the test and the answer.
    """

    pid = 0

    def __init__(self, zeilen=()):
        self.stdout = iter(zeilen)
        self._geerntet = False

    def poll(self):
        return 1 if self._geerntet else None

    def wait(self, timeout=None):
        self._geerntet = True
        return 1


def test_ein_server_der_von_selbst_stirbt_wird_gemeldet(ordner):
    """The state change nobody ordered — an OOM kill, a crash, a `kill` from
    a terminal. None of the deliberate fire points sees it, and with nothing
    polling any more an unsaid death leaves a green dot over a server that
    is gone."""
    gehoert, melden = _melder()
    runner = Modellrunner(ordner, zustand_callback=melden)
    runner._prozess = _LaufenderProzess()
    runner._zustand_melden()
    assert gehoert == [(True, None, None)]

    # The pipe closes exactly when the process ends; the reader thread runs
    # out of lines. The handle is not reapable yet — so an announcement built
    # without reaping it first would say "still running", word for word what
    # was already said, and be swallowed as a repeat.
    tot = _ToterProzess()
    runner._prozess = tot
    assert tot.poll() is None
    runner._mitlesen()
    assert gehoert == [(True, None, None), (False, None, None)]
    # And nobody else was going to let go of it.
    assert runner._prozess is None
    assert runner.lauf() is None


def test_ein_leser_dessen_server_ersetzt_wurde_schweigt(ordner):
    """Stopping does not wait for the reader thread, so a stop pressed
    mid-load leaves the old server's words still to come. Written into the
    flags after a new server started, they would be published as the new
    one's state — an old "flash disabled" turning the new server's dot red.
    """
    gehoert, melden = _melder()
    runner = Modellrunner(ordner, zustand_callback=melden)

    def zeilen():
        # The replacement happens between two lines of the old output, which
        # is exactly where the real race sits.
        yield "llama_context: n_ctx     = 4096\n"
        runner._prozess = _LaufenderProzess()
        yield "llama_context: flash_attn    = disabled\n"

    veraltet = _ToterProzess(zeilen())
    runner._prozess = veraltet
    runner._mitlesen()

    # The second line was never read, so the new server's flash state is
    # still its own, and nothing was announced in its name.
    assert runner._flash_attn is None
    assert gehoert == []


def test_eine_meldung_die_nicht_ankam_gilt_nicht_als_gesagt(ordner):
    """The dedup remembers what went out, not what was attempted. Recording
    it first would latch a state as said that was never said, and swallow
    every later attempt to say it."""
    fehler = {"jetzt": True}
    gehoert = []

    def melden(laeuft, flash, mtp, arch=None):
        if fehler["jetzt"]:
            raise RuntimeError("die Leitung war weg")
        gehoert.append((laeuft, flash, mtp))

    runner = Modellrunner(ordner, zustand_callback=melden)
    runner._prozess = _LaufenderProzess()
    runner._zustand_melden()
    assert gehoert == []

    fehler["jetzt"] = False
    runner._zustand_melden()
    assert gehoert == [(True, None, None)]


# --- A start that fails on an architecture llama-server does not know --------


class _BeendeterProzess:
    """A server that has exited — what is left after a failed load."""

    pid = 0

    def poll(self):
        return 1


_UNKNOWN_ARCH_LOG = (
    "0.00.067.528 I srv    load_model: loading model '/models/diffusiongemma-26B-A4B-it-Q5_K_M.gguf'",
    "0.00.298.139 E llama_model_load: error loading model: unknown model architecture: 'diffusion-gemma'",
    "0.00.526.014 E srv    load_model: failed to load model, '/models/diffusiongemma-26B-A4B-it-Q5_K_M.gguf'",
    "0.00.526.480 E srv  llama_server: exiting due to model loading error",
)


def test_a_start_failed_on_an_unknown_architecture_names_it(ordner):
    """The server's own line (build 10310, diffusiongemma-26B): the state
    names the architecture once the server has exited."""
    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    for zeile in _UNKNOWN_ARCH_LOG:
        runner._zeile_aufnehmen(zeile)
    runner._prozess = _BeendeterProzess()
    assert runner.unknown_architecture() == "diffusion-gemma"


def test_another_load_error_names_no_architecture(ordner):
    """Silence probe: a load that fails for another reason stays as before."""
    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    runner._zeile_aufnehmen("E llama_model_load: error loading model: tensor 'blk.0.ffn_up' data is not within the file bounds")
    runner._zeile_aufnehmen("E srv  llama_server: exiting due to model loading error")
    runner._prozess = _BeendeterProzess()
    assert runner.unknown_architecture() is None


def test_a_running_server_reports_no_unknown_architecture(ordner):
    """Silence probe: while a server runs there is no failed start to name."""
    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    runner._zeile_aufnehmen(_UNKNOWN_ARCH_LOG[1])
    assert runner.unknown_architecture() is None


def test_the_server_info_carries_the_unknown_architecture(ordner):
    """The route the window polls hands it on."""
    from app.api.v1.runner import auskunft

    runner = Modellrunner(ordner)
    runner._prozess = _LaufenderProzess()
    runner._zeile_aufnehmen(_UNKNOWN_ARCH_LOG[1])
    runner._prozess = _BeendeterProzess()
    assert auskunft(runner).unknown_architecture == "diffusion-gemma"


def test_a_refused_start_clears_the_earlier_unknown_architecture(ordner):
    """A start refused before anything runs (no such file) is not the
    earlier start's failure: the old architecture does not stay standing."""
    runner = Modellrunner(ordner)
    runner._unknown_arch = "diffusion-gemma"
    with pytest.raises(RunnerFehler):
        runner.starten("gibtsnicht.gguf")
    assert runner.unknown_architecture() is None


# --- the fourth fact: the architecture the build does not know ---------------


def test_the_unknown_architecture_is_announced_with_the_server_that_ended(ordner):
    """The reader reads the line, the process ends: the announcement carries
    the name together with `laeuft=False` — a state that was never said
    before, so it goes out."""
    gehoert, melden = _melder_vier()
    runner = Modellrunner(ordner, zustand_callback=melden)
    runner._prozess = _ToterProzess(
        iter(["llama_model_load: error loading model architecture: unknown model architecture: 'diffusion-gemma'\n"])
    )
    runner._mitlesen()
    assert gehoert and gehoert[-1] == (False, None, None, "diffusion-gemma")


def test_a_start_that_failed_for_another_reason_announces_no_architecture(ordner):
    gehoert, melden = _melder_vier()
    runner = Modellrunner(ordner, zustand_callback=melden)
    runner._prozess = _ToterProzess(iter(["something else went wrong\n"]))
    runner._mitlesen()
    assert all(tatsachen[3] is None for tatsachen in gehoert)


def test_a_running_server_and_an_unchanged_state_announce_no_architecture_twice(ordner):
    gehoert, melden = _melder_vier()
    runner = Modellrunner(ordner, zustand_callback=melden)
    runner._unknown_arch = "diffusion-gemma"
    runner._prozess = _LaufenderProzess()
    runner._zustand_melden()
    # Running: no failed start to name, whatever the earlier one was.
    assert gehoert == [(True, None, None, None)]
    runner._zustand_melden()
    assert len(gehoert) == 1
