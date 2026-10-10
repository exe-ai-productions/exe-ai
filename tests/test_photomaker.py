"""PhotoMaker: the class word, the two folders, and the flags at the command."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import bildrunner, photomaker
from app.bildrunner import Auftrag, Bildrunner


def test_nur_die_vier_klassen_zaehlen():
    for wort in ("man", "woman", "girl", "boy"):
        assert photomaker.klasse_pruefen(wort) == wort
    # Anything else would pass through and quietly do nothing.
    for wort in ("person", "mann", "", "  ", "cat", None):
        assert photomaker.klasse_pruefen(wort) == ""


def test_klasse_wird_geputzt():
    assert photomaker.klasse_pruefen("  MAN  ") == "man"


def test_triggerwort_kommt_vor_den_prompt():
    assert (
        photomaker.prompt_mit_klasse("sitting in a café", "man")
        == "a man img, sitting in a café"
    )


def test_ohne_klasse_bleibt_der_prompt_unberuehrt():
    assert photomaker.prompt_mit_klasse("sitting in a café", "") == "sitting in a café"


def test_vorhandenes_triggerwort_wird_nicht_verdoppelt():
    # Somebody may have written it themselves — then it stays at one.
    schon_da = "a man img, walking"
    assert photomaker.prompt_mit_klasse(schon_da, "man") == schon_da
    assert photomaker.prompt_mit_klasse("A MAN IMG, walking", "man") == "A MAN IMG, walking"


def test_leerer_prompt_bekommt_nur_das_triggerwort():
    assert photomaker.prompt_mit_klasse("", "woman") == "a woman img"


def test_modell_wird_gefunden(tmp_path):
    assert photomaker.modell(tmp_path) is None
    ordner = tmp_path / "photomaker"
    ordner.mkdir()
    assert photomaker.modell(tmp_path) is None
    datei = ordner / "photomaker-v1.safetensors"
    datei.write_bytes(b"x")
    assert photomaker.modell(tmp_path) == datei


def test_leerer_gesichterordner_zaehlt_wie_keiner(tmp_path):
    ordner = tmp_path / "faces"
    ordner.mkdir()
    # An empty folder would load the model and give it no face to learn.
    assert photomaker.gesichter(tmp_path) is None
    (ordner / "notiz.txt").write_text("kein Foto")
    assert photomaker.gesichter(tmp_path) is None
    (ordner / "ich.jpg").write_bytes(b"x")
    assert photomaker.gesichter(tmp_path) == ordner


def test_fingerabdruck_bleibt_gleich_ohne_aenderung(tmp_path):
    ordner = tmp_path / "faces"
    ordner.mkdir()
    (ordner / "ich.jpg").write_bytes(b"x")
    assert photomaker.fingerabdruck(ordner) == photomaker.fingerabdruck(ordner)


def test_fingerabdruck_aendert_sich_mit_den_fotos(tmp_path):
    """The point of the function: the folder itself
    never changes name — Image-Turbo needs to notice when the photos in it
    do."""
    ordner = tmp_path / "faces"
    ordner.mkdir()
    (ordner / "eins.jpg").write_bytes(b"first one")
    vorher = photomaker.fingerabdruck(ordner)

    (ordner / "eins.jpg").unlink()
    (ordner / "zwei.jpg").write_bytes(b"jemand anderes")

    assert photomaker.fingerabdruck(ordner) != vorher


def test_fingerabdruck_ignoriert_nicht_bild_dateien(tmp_path):
    """A stray note in the folder is not a photo — same filter as
    ``gesichter()`` itself."""
    ordner = tmp_path / "faces"
    ordner.mkdir()
    (ordner / "ich.jpg").write_bytes(b"x")
    vorher = photomaker.fingerabdruck(ordner)

    (ordner / "notiz.txt").write_text("kein Foto")

    assert photomaker.fingerabdruck(ordner) == vorher


@pytest.fixture
def runner(tmp_path: Path, monkeypatch) -> Bildrunner:
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    (tmp_path / "klein.gguf").write_bytes(b"x")
    return Bildrunner(tmp_path)


def _befehl(runner: Bildrunner, ordner: Path, **felder) -> list[str]:
    auftrag = Auftrag(modell=ordner / "klein.gguf", prompt="p", **felder)
    return runner.befehl(auftrag, ordner / "aus.png")


def test_schalter_nur_wenn_modell_und_ordner_da_sind(runner, tmp_path):
    ohne = _befehl(runner, tmp_path)
    assert "--photo-maker" not in ohne
    assert "--pm-id-images-dir" not in ohne

    # Half of it set must stay off: a model without photos has no face to
    # carry, and would change nothing while looking switched on.
    nur_modell = _befehl(runner, tmp_path, photomaker=tmp_path / "pm.safetensors")
    assert "--photo-maker" not in nur_modell

    nur_ordner = _befehl(runner, tmp_path, gesichter_ordner=tmp_path)
    assert "--pm-id-images-dir" not in nur_ordner


def test_beide_schalter_zusammen(runner, tmp_path):
    modell = tmp_path / "pm.safetensors"
    zeile = _befehl(
        runner, tmp_path,
        photomaker=modell, gesichter_ordner=tmp_path, pm_klasse="man",
    )
    assert zeile[zeile.index("--photo-maker") + 1] == str(modell)
    assert zeile[zeile.index("--pm-id-images-dir") + 1] == str(tmp_path)


def test_photomaker_bringt_den_lora_anwendungsmodus_mit(runner, tmp_path):
    """Without it the Metal build aborts in ggml-backend.cpp:930 — measured."""
    zeile = _befehl(
        runner, tmp_path,
        photomaker=tmp_path / "pm.safetensors", gesichter_ordner=tmp_path,
        pm_klasse="man",
    )
    assert zeile[zeile.index("--lora-apply-mode") + 1] == "at_runtime"


def test_der_anwendungsmodus_steht_nur_einmal(runner, tmp_path):
    """A face beside a LoRA must not put the same flag on the line twice."""
    from app.bildrunner import LoRA

    zeile = _befehl(
        runner, tmp_path,
        photomaker=tmp_path / "pm.safetensors", gesichter_ordner=tmp_path,
        pm_klasse="man",
        loras=(LoRA(name="stil", staerke=0.7),), lora_ordner=tmp_path,
    )
    assert zeile.count("--lora-apply-mode") == 1


def test_der_anwendungsmodus_ist_frei_waehlbar(runner, tmp_path):
    """Free by house rule, not locked to at_runtime: a request naming one of
    the other two known values (proven to abort on this build) must still
    reach the command line unchanged — the window warns, the server does
    not overrule."""
    from app.bildrunner import LoRA

    zeile = _befehl(
        runner, tmp_path,
        loras=(LoRA(name="stil", staerke=0.7),), lora_ordner=tmp_path,
        lora_apply_mode="immediately",
    )
    assert zeile[zeile.index("--lora-apply-mode") + 1] == "immediately"
