"""The offline image generator: its guards, not its pictures.

What is worth testing here is everything AROUND the drawing — a model name
that is really a path, two runs asking for the machine at once, a request
whose numbers would tie the machine up for an hour. The picture itself is
the generator's business and is proved by running it, not by asserting
about pixels.
"""

from __future__ import annotations

import io
import json
import logging
import os
import struct
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import bildrunner, bildspeicher, bildwahlen, model_convert
from app.api.v1.bild import MAX_KANTE, MIN_KANTE, RASTER, _erwartete_paesse, _kante
from app.bildrunner import Auftrag, BildFehler, Bildrunner, LoRA
from app.bildturbo import Bildturbo
from app.config import Config


@pytest.fixture
def daten(tmp_path: Path) -> Path:
    """The image model folder itself — the folder IS the kind now."""
    (tmp_path / "klein.gguf").write_bytes(b"x")
    (tmp_path / "notiz.txt").write_text("kein Modell")
    return tmp_path


def test_nur_dateien_aus_dem_bildmodell_ordner_zaehlen(daten: Path):
    assert bildrunner.modelle(daten) == ["klein.gguf"]


def test_ein_modellname_ist_nie_ein_pfad(daten: Path):
    """The one place where guessing would be dangerous, so it refuses."""
    for versuch in ("../../etc/passwd", "unterordner/klein.gguf", "", "gibtsnicht.gguf"):
        with pytest.raises(BildFehler) as fehler:
            bildrunner.modell_pfad(daten, versuch)
        assert fehler.value.grund == "bild.modell_unbekannt"


def test_ein_bekannter_name_wird_zum_pfad(daten: Path):
    pfad = bildrunner.modell_pfad(daten, "klein.gguf")
    assert pfad == daten / "klein.gguf"


def test_ohne_programm_gibt_es_keinen_befehl(daten: Path, monkeypatch):
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: None)
    runner = Bildrunner(daten)
    assert runner.programm is None
    with pytest.raises(BildFehler) as fehler:
        runner.befehl(Auftrag(modell=daten / "klein.gguf", prompt="x"), daten / "aus.png")
    assert fehler.value.grund == "bild.kein_programm"


def test_der_befehl_traegt_alles_was_gesetzt_wurde(daten: Path, monkeypatch):
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    runner = Bildrunner(daten)
    befehl = runner.befehl(
        Auftrag(
            modell=daten / "klein.gguf", prompt="ein Leuchtturm", negativ="unscharf",
            breite=512, hoehe=768, schritte=14, cfg=6.5, seed=42,
        ),
        daten / "aus.png",
    )
    assert befehl[0] == str(Path("/irgendwo/sd-cli"))
    for marke in ("-p", "ein Leuchtturm", "--negative-prompt", "unscharf",
                  "-W", "512", "-H", "768", "--steps", "14", "--seed", "42"):
        assert marke in befehl


def test_ohne_negativ_faellt_die_option_weg(daten: Path, monkeypatch):
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="x"), daten / "aus.png"
    )
    assert "--negative-prompt" not in befehl


def test_zwei_laeufe_gleichzeitig_gibt_es_nicht(daten: Path, monkeypatch):
    """The lock is not about the program — it is about the memory pool."""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    runner = Bildrunner(daten)
    drin = threading.Event()
    weiter = threading.Event()

    class Prozess:
        """A generator that takes its time and can be asked to stop. Its
        pipes are exhausted — the runner's readers stop at once."""

        returncode = 0
        pid = 4242

        def __init__(self):
            self.stdout = io.BytesIO()
            self.stderr = io.BytesIO()

        def wait(self, timeout=None):
            drin.set()
            weiter.wait(5)
            return 0

        def communicate(self, timeout=None):
            drin.set()
            weiter.wait(5)
            return ("", "")

        def poll(self):
            return None

    monkeypatch.setattr(bildrunner.subprocess, "Popen", lambda *a, **k: Prozess())
    ziel = daten / "aus.png"
    ziel.write_bytes(b"png")
    auftrag = Auftrag(modell=daten / "klein.gguf", prompt="x")

    faden = threading.Thread(target=lambda: runner.erzeugen(auftrag, ziel))
    faden.start()
    assert drin.wait(5)
    with pytest.raises(BildFehler) as fehler:
        runner.erzeugen(auftrag, ziel)
    assert fehler.value.grund == "bild.laeuft_schon"
    weiter.set()
    faden.join(5)
    # And free again afterwards, or one failed picture would block the rest
    # of the evening.
    assert runner.laeuft() is False


def test_sampler_und_scheduler_stehen_im_befehl(daten: Path, monkeypatch):
    """Both come from the shipped binary's own list.

    A name this build does not know is answered with a usage message, which
    reaches the user as "the picture could not be drawn" and explains
    nothing — so anything unknown is brought back to the default instead.
    """
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(
            modell=daten / "klein.gguf", prompt="x",
            sampler="dpm++2m", scheduler="exponential",
        ),
        daten / "aus.png",
    )
    assert "--sampling-method" in befehl and "dpm++2m" in befehl
    assert "--scheduler" in befehl and "exponential" in befehl
    assert bildwahlen.sampler_pruefen("gibtsnicht") == bildwahlen.SAMPLER_VORGABE
    assert bildwahlen.scheduler_pruefen(None) == bildwahlen.SCHEDULER_VORGABE
    assert bildwahlen.sampler_pruefen("heun") == "heun"


def test_vae_format_pruefen_kennt_die_fuenf_werte():
    for wert in bildwahlen.VAE_FORMATE:
        assert bildwahlen.vae_format_pruefen(wert) == wert
    assert bildwahlen.vae_format_pruefen("gibtsnicht") == ""
    assert bildwahlen.vae_format_pruefen(None) == ""


def test_rng_pruefen_kennt_die_zwei_werte():
    for wert in bildwahlen.RNG_WERTE:
        assert bildwahlen.rng_pruefen(wert) == wert
    assert bildwahlen.rng_pruefen("gibtsnicht") == bildwahlen.RNG_VORGABE
    assert bildwahlen.rng_pruefen(None) == bildwahlen.RNG_VORGABE


def test_weight_type_pruefen_kennt_die_drei_werte():
    for wert in bildwahlen.WEIGHT_TYPES:
        assert bildwahlen.weight_type_pruefen(wert) == wert
    assert bildwahlen.weight_type_pruefen("gibtsnicht") == ""
    assert bildwahlen.weight_type_pruefen(None) == ""


def test_speicher_und_geraete_felder_im_befehl(daten: Path, monkeypatch):
    """Memory & devices: RNG always rides along, the rest stay off the
    command line while unset."""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="ein Leuchtturm"),
        daten / "aus.png",
    )
    assert befehl[befehl.index("--rng") + 1] == "cuda"
    assert "--type" not in befehl
    assert "--threads" not in befehl
    assert "--max-vram" not in befehl
    assert "--offload-to-cpu" not in befehl
    assert "--split-mode" not in befehl
    assert "--backend" not in befehl

    voll = Bildrunner(daten).befehl(
        Auftrag(
            modell=daten / "klein.gguf", prompt="ein Leuchtturm",
            rng="cpu", weight_type="q8_0", threads=8, vram_limit="6",
            offload_to_cpu=True, split_mode="row", backend="cpu",
        ),
        daten / "aus.png",
    )
    assert voll[voll.index("--rng") + 1] == "cpu"
    assert voll[voll.index("--type") + 1] == "q8_0"
    assert voll[voll.index("--threads") + 1] == "8"
    assert voll[voll.index("--max-vram") + 1] == "6"
    assert "--offload-to-cpu" in voll
    assert voll[voll.index("--split-mode") + 1] == "row"
    assert voll[voll.index("--backend") + 1] == "cpu"


def test_der_lora_stapel_wandert_in_den_prompt(daten: Path, monkeypatch):
    """sd.cpp has no LoRA option — it reads them out of the prompt."""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(
            modell=daten / "klein.gguf",
            prompt="ein Leuchtturm",
            loras=(
                bildrunner.LoRA(name="stil.safetensors", staerke=0.7),
                bildrunner.LoRA(name="licht.safetensors", staerke=0.4),
            ),
            lora_ordner=daten / "lora",
        ),
        daten / "aus.png",
    )
    prompt = befehl[befehl.index("-p") + 1]
    # In the order they were stacked — that order is what applies.
    assert prompt == "ein Leuchtturm <lora:stil:0.7> <lora:licht:0.4>"
    assert "--lora-model-dir" in befehl


def test_eine_lora_ist_nie_ein_pfad(daten: Path):
    (daten / "lora").mkdir()
    (daten / "lora" / "stil.safetensors").write_bytes(b"x")
    assert bildrunner.loras(daten) == ["stil.safetensors"]
    assert bildrunner.lora_pfad(daten, "stil.safetensors").name == "stil.safetensors"
    for versuch in ("../klein.gguf", "unter/stil.safetensors", "", "gibtsnicht.safetensors"):
        with pytest.raises(BildFehler) as fehler:
            bildrunner.lora_pfad(daten, versuch)
        assert fehler.value.grund == "bild.lora_unbekannt"


def test_die_staerke_reist_nur_neben_einem_startbild(daten: Path, monkeypatch):
    """A control that does nothing is worse than no control."""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    runner = Bildrunner(daten)
    ohne = runner.befehl(Auftrag(modell=daten / "klein.gguf", prompt="x"), daten / "a.png")
    assert "--strength" not in ohne and "-i" not in ohne
    mit = runner.befehl(
        Auftrag(
            modell=daten / "klein.gguf", prompt="x",
            startbild=daten / "start.png", staerke=0.6,
        ),
        daten / "a.png",
    )
    assert "-i" in mit and "--strength" in mit and "0.6" in mit


def test_die_maske_reist_nur_neben_einem_startbild(daten: Path, monkeypatch):
    """A mask without a picture to mask has nothing to say.

    Passed anyway it would be an argument the program either ignores or
    stumbles over, and the command line would stop describing what actually
    happens.
    """
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    runner = Bildrunner(daten)
    ohne = runner.befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="x", maske=daten / "m.png"),
        daten / "a.png",
    )
    assert "--mask" not in ohne
    mit = runner.befehl(
        Auftrag(
            modell=daten / "klein.gguf", prompt="x",
            startbild=daten / "start.png", staerke=0.7, maske=daten / "m.png",
        ),
        daten / "a.png",
    )
    assert "--mask" in mit and str(daten / "m.png") in mit


def test_die_vorgabe_ist_das_mass_des_erstmodells():
    """512 is what the first model was trained on."""
    auftrag = Auftrag(modell=Path("/m.gguf"), prompt="x")
    assert (auftrag.breite, auftrag.hoehe) == (512, 512)


def test_die_kanten_werden_wie_von_sdcpp_aufs_raster_gelegt():
    """sd.cpp's own range (64 to 4096) and its own rounding: up to the next
    step of 64 ("align generation request up 200x260 to 256x320")."""
    assert (MIN_KANTE, MAX_KANTE, RASTER) == (64, 4096, 64)
    assert _kante(99999) == MAX_KANTE
    assert _kante(1) == MIN_KANTE
    assert (_kante(200), _kante(260)) == (256, 320)
    assert _kante(768) == 768
    assert _kante(769) == 832
    assert _kante(2048) == 2048


def test_der_speicher_wird_vor_dem_lauf_gefragt():
    # 64 GB machine, 8 GB held by the language model, a 2 GB image model:
    # room enough.
    assert bildspeicher.passt(64, 8, 2) is True
    # 16 GB machine, 12 GB held, a 2 GB image model: it would swap.
    assert bildspeicher.passt(16, 12, 2) is False
    assert bildspeicher.fehlend_gb(16, 12, 2) > 0
    # A machine whose memory cannot be read must not block the feature.
    assert bildspeicher.passt(None, 99, 99) is True
    assert bildspeicher.fehlend_gb(None, 99, 99) == 0.0


class Runner:
    """Something that holds a model and can say how much."""

    def __init__(self, gb):
        self._gb = gb

    def belegt_gb(self):
        return self._gb


class Zustand:
    """Stands in for the application state, which is a bag of attributes."""

    def __init__(self, **dinge):
        self.__dict__.update(dinge)


def test_alle_laufenden_server_zaehlen_mit():
    """Asking one of several is worse than not asking at all.

    Three servers may hold a model at once. Counting only the first turns a
    machine that is already full into a machine that says yes.
    """
    zustand = Zustand(
        modellrunner=Runner(4.0),
        einbettungsrunner=Runner(6.0),
        agentenrunner=Runner(2.5),
    )
    assert bildspeicher.gehaltene_gb(zustand) == 12.5
    # 16 GB machine, a 2 GB image model. Asking only the chat model finds
    # 4 + 2 + 2.5 = 8.5 and waves it through; the truth is 12.5 + 2 + 2.5,
    # which is a gigabyte more than the machine has.
    assert bildspeicher.passt(16, 4.0, 2.0) is True
    assert bildspeicher.passt(16, bildspeicher.gehaltene_gb(zustand), 2.0) is False


def test_wer_nichts_haelt_zaehlt_nichts():
    """An idle server answers nothing, and nothing is not a number."""
    zustand = Zustand(modellrunner=Runner(None), einbettungsrunner=Runner(0.0))
    assert bildspeicher.gehaltene_gb(zustand) == 0.0


def test_was_kein_server_ist_wird_uebergangen():
    """The sum is collected by asking, so the bag may hold anything.

    That is what keeps a fifth server from being forgotten: nothing has to
    be added to a list when one appears.
    """
    zustand = Zustand(
        modellrunner=Runner(4.0),
        bildrunner=object(),
        werkzeuge=[1, 2, 3],
        config="irgendwas",
    )
    assert bildspeicher.gehaltene_gb(zustand) == 4.0


def test_ein_neuer_server_wird_von_selbst_mitgezaehlt():
    zustand = Zustand(modellrunner=Runner(4.0))
    assert bildspeicher.gehaltene_gb(zustand) == 4.0
    zustand.nochwas_runner = Runner(3.0)
    assert bildspeicher.gehaltene_gb(zustand) == 7.0


def test_der_zustand_einer_anwendung_wird_gelesen():
    """Starlette keeps its state in an inner dictionary, not in `__dict__`."""
    from starlette.datastructures import State

    zustand = State()
    zustand.modellrunner = Runner(4.0)
    zustand.agentenrunner = Runner(2.0)
    assert bildspeicher.gehaltene_gb(zustand) == 6.0


# --- The quality companions (block D) -------------------------------------


def test_flash_attention_ist_an_seit_gemessen(daten: Path, monkeypatch):
    """On by default now that it is measured on the shipped build: the highres
    fix's second pass drops from ~30 s to ~3.5 s per step with it. It can still
    be switched off explicitly for a swapped-in binary that does not know the
    flag."""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    an = Bildrunner(daten).befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="x"), daten / "a.png"
    )
    assert "--diffusion-fa" in an
    aus = Bildrunner(daten).befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="x", diffusion_fa=False), daten / "a.png"
    )
    assert "--diffusion-fa" not in aus


def test_die_begleiter_fallen_weg_wenn_ungesetzt(daten: Path, monkeypatch):
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="x"), daten / "a.png"
    )
    for weg in ("--clip-skip", "--vae", "--ad-model", "--ad-prompt"):
        assert weg not in befehl


def test_clip_skip_reist_nur_wenn_gesetzt(daten: Path, monkeypatch):
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    runner = Bildrunner(daten)
    aus = runner.befehl(Auftrag(modell=daten / "klein.gguf", prompt="x", clip_skip=-1), daten / "a.png")
    assert "--clip-skip" not in aus
    an = runner.befehl(Auftrag(modell=daten / "klein.gguf", prompt="x", clip_skip=2), daten / "a.png")
    assert "--clip-skip" in an and "2" in an


def test_clip_skip_1_reist_mit(daten: Path, monkeypatch):
    """1 is a value sd-cli names in its own --help ("1 ignores none, 2
    ignores one layer"), so the window offers it and it has to arrive.

    It was withheld for a while because one checkpoint drew a blank picture
    with it -- but that is a property of that checkpoint, not of the
    switch, and a value the program refuses to pass on is a value the user
    cannot try. Only "auto" (-1) keeps the switch off the command line, so
    sd-cli picks per model class as it always has."""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    runner = Bildrunner(daten)
    befehl = runner.befehl(Auftrag(modell=daten / "klein.gguf", prompt="x", clip_skip=1), daten / "a.png")
    assert "--clip-skip" in befehl
    assert befehl[befehl.index("--clip-skip") + 1] == "1"
    # The silence half: auto still sends nothing at all.
    aus = runner.befehl(Auftrag(modell=daten / "klein.gguf", prompt="x", clip_skip=-1), daten / "a.png")
    assert "--clip-skip" not in aus


def test_vae_und_detektor_stehen_im_befehl(daten: Path, monkeypatch):
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(
            modell=daten / "klein.gguf", prompt="x",
            vae=daten / "vae" / "besser.safetensors",
            ad_modell=daten / "adetailer" / "face.pt", ad_prompt="detailed face",
        ),
        daten / "a.png",
    )
    assert "--vae" in befehl and str(daten / "vae" / "besser.safetensors") in befehl
    assert "--ad-model" in befehl and str(daten / "adetailer" / "face.pt") in befehl
    assert "--ad-prompt" in befehl and "detailed face" in befehl


def test_pulid_braucht_beide_haelften(daten: Path, monkeypatch):
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    nur_gewicht = Bildrunner(daten).befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="x",
                pulid_weights=daten / "pulid" / "flux-pulid.safetensors"),
        daten / "a.png",
    )
    assert "--pulid-weights" not in nur_gewicht

    nur_einbettung = Bildrunner(daten).befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="x",
                pulid_id_embedding=daten / "gesichter" / "gesicht.bin"),
        daten / "a.png",
    )
    assert "--pulid-id-embedding" not in nur_einbettung


def test_pulid_lauf_traegt_gewichte_und_einbettung(daten: Path, monkeypatch):
    """'Ein PuLID-Lauf traegt --pulid-weights + Embedding im Befehl.'"""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(
            modell=daten / "klein.gguf", prompt="x",
            pulid_weights=daten / "pulid" / "flux-pulid.safetensors",
            pulid_id_embedding=daten / "gesichter" / "gesicht.bin",
            pulid_id_weight=0.8,
        ),
        daten / "a.png",
    )
    assert "--pulid-weights" in befehl and str(daten / "pulid" / "flux-pulid.safetensors") in befehl
    assert "--pulid-id-embedding" in befehl and str(daten / "gesichter" / "gesicht.bin") in befehl
    assert befehl[befehl.index("--pulid-id-weight") + 1] == "0.8"


def test_controlnet_braucht_beide_haelften(daten: Path, monkeypatch):
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    nur_modell = Bildrunner(daten).befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="x",
                control_net=daten / "controlnet" / "canny.safetensors", canny=True),
        daten / "a.png",
    )
    assert "--control-net" not in nur_modell
    assert "--image-preprocess" not in nur_modell, "Edge detection without a ControlNet run is meaningless"
    assert "--canny" not in nur_modell


def test_controlnet_lauf_traegt_modell_und_guide_image(daten: Path, monkeypatch):
    """'ControlNet-Lauf traegt --control-net/--control-image im Befehl.'"""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(
            modell=daten / "klein.gguf", prompt="x",
            control_net=daten / "controlnet" / "canny.safetensors",
            control_image=daten / "guide.png", control_strength=0.7, canny=True,
        ),
        daten / "a.png",
    )
    assert "--control-net" in befehl and str(daten / "controlnet" / "canny.safetensors") in befehl
    assert "--control-image" in befehl and str(daten / "guide.png") in befehl
    assert befehl[befehl.index("--control-strength") + 1] == "0.7"
    # Build 920 has no --canny; edge detection is a preprocessing rule.
    assert befehl[befehl.index("--image-preprocess") + 1] == "target=control,canny=true"
    assert "--canny" not in befehl


def test_without_edge_detection_no_preprocessing_is_asked_for(daten: Path, monkeypatch):
    """Silence probe: a ControlNet run without edge detection, and a picture
    with no guide at all, carry neither switch."""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    for auftrag in (
        Auftrag(modell=daten / "klein.gguf", prompt="x",
                control_net=daten / "controlnet" / "canny.safetensors",
                control_image=daten / "guide.png"),
        Auftrag(modell=daten / "klein.gguf", prompt="x"),
    ):
        befehl = Bildrunner(daten).befehl(auftrag, daten / "a.png")
        assert "--image-preprocess" not in befehl and "--canny" not in befehl


def test_ad_prompt_faellt_ohne_detektor_weg(daten: Path, monkeypatch):
    """A face prompt without a detector has nothing to steer."""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="x", ad_prompt="face"),
        daten / "a.png",
    )
    assert "--ad-prompt" not in befehl


def test_vae_und_yolo_liegen_in_eigenen_ordnern(daten: Path):
    (daten / "vae").mkdir()
    (daten / "vae" / "besser.safetensors").write_bytes(b"x")
    (daten / "adetailer").mkdir()
    (daten / "adetailer" / "face.pt").write_bytes(b"x")
    assert bildrunner.vaes(daten) == ["besser.safetensors"]
    assert bildrunner.yolos(daten) == ["face.pt"]
    assert bildrunner.vae_pfad(daten, "besser.safetensors").name == "besser.safetensors"
    assert bildrunner.yolo_pfad(daten, "face.pt").name == "face.pt"


def test_textversteher_liegen_in_ihrem_eigenen_ordner(daten: Path):
    (daten / "text_encoders").mkdir()
    (daten / "text_encoders" / "t5xxl.gguf").write_bytes(b"x")
    assert bildrunner.textversteher(daten) == ["t5xxl.gguf"]


def test_ein_fehlender_textversteher_ordner_ist_eine_leere_liste(daten: Path):
    assert bildrunner.textversteher(daten) == []


def _safetensors_bytes(namen: list[str]) -> bytes:
    import json
    import struct
    kopf = {n: {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]} for n in namen}
    rohkopf = json.dumps(kopf).encode("utf-8")
    return struct.pack("<Q", len(rohkopf)) + rohkopf


def test_ein_textversteher_im_hauptordner_wird_gefangen(daten: Path):
    """The catch net's own acceptance case: a T5 file mistakenly dropped in
    the main folder no longer shows up as an image model — it shows up as
    a text encoder instead, and its own name resolves against the main
    folder where it actually is."""
    t5_datei = daten / "t5xxl-versehentlich-hier.safetensors"
    t5_datei.write_bytes(_safetensors_bytes([
        "shared.weight", "encoder.block.0.layer.0.SelfAttention.k.weight",
    ]))
    assert t5_datei.name not in bildrunner.modelle(daten)
    assert t5_datei.name in bildrunner.textversteher(daten)
    assert bildrunner.textversteher_pfad(daten, t5_datei.name) == t5_datei


def test_eine_vae_im_hauptordner_wird_gefangen(daten: Path):
    vae_datei = daten / "vae-versehentlich-hier.safetensors"
    vae_datei.write_bytes(_safetensors_bytes([
        "encoder.down.0.block.0.norm1.weight",
        "decoder.up.0.block.0.norm1.weight",
        "post_quant_conv.weight",
    ]))
    assert vae_datei.name not in bildrunner.modelle(daten)
    assert vae_datei.name in bildrunner.vaes(daten)
    assert bildrunner.vae_pfad(daten, vae_datei.name) == vae_datei


def test_eine_unbekannte_datei_verhaelt_sich_wie_heute(daten: Path):
    """Everything this reader cannot identify with confidence stays an
    image model, exactly as before the catch net — including the plain
    ``b"x"`` placeholder every other test in this file already writes."""
    assert "klein.gguf" in bildrunner.modelle(daten)
    assert "klein.gguf" not in bildrunner.vaes(daten)
    assert "klein.gguf" not in bildrunner.textversteher(daten)


def test_textversteher_pfad_loest_gegen_den_eigenen_ordner_auf(daten: Path):
    (daten / "text_encoders").mkdir()
    (daten / "text_encoders" / "t5xxl.gguf").write_bytes(b"x")
    pfad = bildrunner.textversteher_pfad(daten, "t5xxl.gguf")
    assert pfad == daten / "text_encoders" / "t5xxl.gguf"
    with pytest.raises(BildFehler) as fehler:
        bildrunner.textversteher_pfad(daten, "gibtsnicht.gguf")
    assert fehler.value.grund == "bild.begleiter_unbekannt"


def test_embeddings_kommen_ohne_endung_wie_im_prompt(daten: Path):
    """No suffix filter, unlike a model or LoRA — the folder holds nothing
    but embeddings, and sd.cpp itself decides what it does with each one."""
    (daten / "embedding").mkdir()
    (daten / "embedding" / "EasyNegative.pt").write_bytes(b"x")
    (daten / "embedding" / "bad-hands.safetensors").write_bytes(b"x")
    assert bildrunner.embeddings(daten) == ["EasyNegative", "bad-hands"]


def test_ein_fehlender_embedding_ordner_ist_eine_leere_liste(daten: Path):
    assert bildrunner.embeddings(daten) == []


def test_versteckte_dateien_sind_keine_embeddings(daten: Path):
    """A Finder litter file such as ``.DS_Store`` shows
    up the moment the folder is opened by hand — exactly what this list
    exists to make unnecessary."""
    (daten / "embedding").mkdir()
    (daten / "embedding" / "EasyNegative.pt").write_bytes(b"x")
    (daten / "embedding" / ".DS_Store").write_bytes(b"x")
    (daten / "embedding" / "._EasyNegative").write_bytes(b"x")
    assert bildrunner.embeddings(daten) == ["EasyNegative"]


def test_bild_modelle_route_liefert_die_embeddings(
    config: Config, client: TestClient, tmp_path: Path
):
    """Nothing between ``bildrunner.embeddings()`` and
    the response held this together — the field could vanish from
    ``BildmodellAntwort`` without a single test noticing."""
    config.app.bildmodelle_verzeichnis = str(tmp_path / "bildmodelle")
    ordner = tmp_path / "bildmodelle" / "embedding"
    ordner.mkdir(parents=True)
    (ordner / "EasyNegative.pt").write_bytes(b"x")

    antwort = client.get("/api/v1/bild/modelle")
    assert antwort.json()["embeddings"] == ["EasyNegative"]


def test_bild_modelle_route_liefert_die_textversteher(
    config: Config, client: TestClient, tmp_path: Path
):
    config.app.bildmodelle_verzeichnis = str(tmp_path / "bildmodelle")
    ordner = tmp_path / "bildmodelle" / "text_encoders"
    ordner.mkdir(parents=True)
    (ordner / "t5xxl.gguf").write_bytes(b"x")

    antwort = client.get("/api/v1/bild/modelle")
    daten = antwort.json()
    assert daten["textversteher"] == ["t5xxl.gguf"]
    # Every other field the response already carried stays exactly where
    # it was — this step only adds a field, it does not move one.
    assert daten["embeddings"] == []
    assert daten["vaes"] == []


def test_bild_modelle_route_liefert_den_vae_ordner(
    config: Config, client: TestClient, tmp_path: Path
):
    """The VAE path row needs its own folder, the same way
    lora_ordner/embedding_ordner already carry theirs."""
    config.app.bildmodelle_verzeichnis = str(tmp_path / "bildmodelle")
    antwort = client.get("/api/v1/bild/modelle")
    assert antwort.json()["vae_ordner"] == str(tmp_path / "bildmodelle" / "vae")


def test_ein_begleiter_ist_nie_ein_pfad(daten: Path):
    (daten / "vae").mkdir()
    (daten / "vae" / "besser.safetensors").write_bytes(b"x")
    for versuch in ("../klein.gguf", "unter/besser.safetensors", "", "gibtsnicht.safetensors"):
        with pytest.raises(BildFehler) as fehler:
            bildrunner.vae_pfad(daten, versuch)
        assert fehler.value.grund == "bild.begleiter_unbekannt"


def test_hires_fix_faellt_ohne_schalter_weg(daten: Path, monkeypatch):
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="x"), daten / "a.png"
    )
    assert "--hires" not in befehl and "--hires-scale" not in befehl


def test_hires_fix_traegt_massstab_und_schritte(daten: Path, monkeypatch):
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="x", hires=True, hires_scale=2.0, hires_steps=10),
        daten / "a.png",
    )
    assert "--hires" in befehl
    assert "--hires-scale" in befehl and "2.0" in befehl
    assert "--hires-steps" in befehl and "10" in befehl


def test_hires_kachel_1_5_x_traegt_die_richtige_basisgroesse(daten: Path, monkeypatch):
    """The window offers 1.25x/1.5x/1.6x tiles instead of
    2x/3x/4x. sd-cli computes the actual target size itself from
    --hires-scale and the base --width/--height (0 in --hires-width/
    -height means "use the scale") -- so what the window must hand over
    correctly is the base size and the scale, not a precomputed target.
    832x1216 at 1.5x is 1248x1824 (the size a Windows SDXL run at this
    resolution would ask for)."""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(
            modell=daten / "klein.gguf", prompt="x", breite=832, hoehe=1216,
            hires=True, hires_scale=1.5,
        ),
        daten / "a.png",
    )
    assert befehl[befehl.index("-W") + 1] == "832"
    assert befehl[befehl.index("-H") + 1] == "1216"
    assert befehl[befehl.index("--hires-scale") + 1] == "1.5"
    assert 832 * 1.5 == 1248 and 1216 * 1.5 == 1824.0


def test_slg_faellt_ohne_massstab_weg(daten: Path, monkeypatch):
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(
            modell=daten / "klein.gguf", prompt="x",
            skip_layer_start=0.05, skip_layer_end=0.3, skip_layers="1,2,3",
        ),
        daten / "a.png",
    )
    assert "--slg-scale" not in befehl
    assert "--skip-layer-start" not in befehl
    assert "--skip-layer-end" not in befehl
    assert "--skip-layers" not in befehl


def test_slg_traegt_alle_vier_felder(daten: Path, monkeypatch):
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(
            modell=daten / "klein.gguf", prompt="x", slg_scale=2.5,
            skip_layer_start=0.05, skip_layer_end=0.3, skip_layers="7,8,9",
        ),
        daten / "a.png",
    )
    assert befehl[befehl.index("--slg-scale") + 1] == "2.5"
    assert befehl[befehl.index("--skip-layer-start") + 1] == "0.05"
    assert befehl[befehl.index("--skip-layer-end") + 1] == "0.3"
    assert befehl[befehl.index("--skip-layers") + 1] == "7,8,9"


def test_live_preview_faellt_ohne_wahl_weg(daten: Path, monkeypatch):
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="x"), daten / "a.png"
    )
    assert "--preview" not in befehl


def test_live_preview_traegt_die_gewaehlte_methode(daten: Path, monkeypatch):
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="x", live_preview="tae"),
        daten / "a.png",
    )
    assert befehl[befehl.index("--preview") + 1] == "tae"


def test_slg_ohne_layers_laesst_sd_clis_eigene_schicht_auswahl_greifen(daten: Path, monkeypatch):
    """`From`/`To` always travel once SLG is on -- their own field
    defaults already match sd-cli's (0.01/0.2), so sending them changes
    nothing a silent default would not. `skip_layers` is the one that
    stays off the command line while empty, since there is no field
    default that could stand in for sd-cli's own layer list."""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="x", slg_scale=2.5),
        daten / "a.png",
    )
    assert befehl[befehl.index("--slg-scale") + 1] == "2.5"
    assert befehl[befehl.index("--skip-layer-start") + 1] == "0.01"
    assert befehl[befehl.index("--skip-layer-end") + 1] == "0.2"
    assert "--skip-layers" not in befehl


def test_vae_tiling_ist_stilles_plumbing(daten: Path, monkeypatch):
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    aus = Bildrunner(daten).befehl(Auftrag(modell=daten / "klein.gguf", prompt="x"), daten / "a.png")
    assert "--vae-tiling" not in aus
    an = Bildrunner(daten).befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="x", switches={"vae_tiling": True}), daten / "a.png"
    )
    assert "--vae-tiling" in an


def test_ein_sdxl_auftrag_baut_exakt_den_heutigen_befehl(daten: Path, monkeypatch):
    """No diffusion_model set — the plain-model branch, byte-identical to
    before this step (Schutzregel 3 of the planning)."""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="x"), daten / "a.png"
    )
    assert befehl[1:3] == ["-m", str(daten / "klein.gguf")]
    assert "--diffusion-model" not in befehl


def test_flux_auftrag_baut_diffusion_model_t5xxl_clip_l_und_guidance(daten: Path, monkeypatch):
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(
            modell=daten / "klein.gguf", prompt="x", familie="flux",
            diffusion_model=daten / "flux1-dev.gguf",
            t5xxl=daten / "t5xxl.gguf", clip_l=daten / "clip_l.safetensors",
            guidance=2.5,
        ),
        daten / "a.png",
    )
    assert "-m" not in befehl
    assert befehl[befehl.index("--diffusion-model") + 1] == str(daten / "flux1-dev.gguf")
    assert befehl[befehl.index("--t5xxl") + 1] == str(daten / "t5xxl.gguf")
    assert befehl[befehl.index("--clip_l") + 1] == str(daten / "clip_l.safetensors")
    assert befehl[befehl.index("--guidance") + 1] == "2.5"


def test_diffusion_model_ohne_familie_wird_nicht_still_gebaut(daten: Path, monkeypatch):
    """befehl() is not only reached through the API's own familie_pruefen()
    check — an Auftrag built directly (a test, a future caller) must not
    silently lose its text encoders just because familie was left at its
    default of None."""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    with pytest.raises(BildFehler):
        Bildrunner(daten).befehl(
            Auftrag(
                modell=daten / "klein.gguf", prompt="x",
                diffusion_model=daten / "flux1-dev.gguf",
                t5xxl=daten / "t5xxl.gguf", clip_l=daten / "clip_l.safetensors",
            ),
            daten / "a.png",
        )


def test_zimage_auftrag_baut_llm(daten: Path, monkeypatch):
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(
            modell=daten / "klein.gguf", prompt="x", familie="zimage",
            diffusion_model=daten / "zimage.gguf", llm=daten / "llm.gguf",
        ),
        daten / "a.png",
    )
    assert "-m" not in befehl
    assert befehl[befehl.index("--llm") + 1] == str(daten / "llm.gguf")
    assert "--t5xxl" not in befehl and "--clip_l" not in befehl


def test_vae_format_reist_nur_mit_wenn_es_gesetzt_ist(daten: Path, monkeypatch):
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    ohne = Bildrunner(daten).befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="x"), daten / "a.png"
    )
    assert "--vae-format" not in ohne
    mit = Bildrunner(daten).befehl(
        Auftrag(
            modell=daten / "klein.gguf", prompt="x", familie="flux",
            diffusion_model=daten / "flux1-dev.gguf", vae_format="flux",
        ),
        daten / "a.png",
    )
    assert mit[mit.index("--vae-format") + 1] == "flux"


def test_vae_format_reist_auch_bei_einem_einzeldateimodell_mit(daten: Path, monkeypatch):
    """--vae-format is a plain sd-cli flag, not part of the Bausatz switch
    list, and a merged single-file model can need one just as much. The
    turbo path (app/bildturbo.py) already sent it from its "-m" branch
    while this one dropped it — the same wish, answered differently
    depending on whether the turbo happened to be on."""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="x", vae_format="flux"),
        daten / "a.png",
    )
    assert "-m" in befehl
    assert befehl[befehl.index("--vae-format") + 1] == "flux"


def test_clip_g_reist_nur_wenn_gesetzt(daten: Path, monkeypatch):
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    mit = Bildrunner(daten).befehl(
        Auftrag(
            modell=daten / "klein.gguf", prompt="x", familie="flux",
            diffusion_model=daten / "flux1-dev.gguf", clip_g=daten / "clip_g.safetensors",
        ),
        daten / "a.png",
    )
    assert mit[mit.index("--clip_g") + 1] == str(daten / "clip_g.safetensors")

    ohne = Bildrunner(daten).befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="x"), daten / "a.png"
    )
    assert "--clip_g" not in ohne
    # An Auftrag without clip_g still builds byte-for-byte today's command —
    # adding the field must not shift anything that came before it.
    assert ohne[1:3] == ["-m", str(daten / "klein.gguf")]


def test_vae_bleibt_ein_einzelner_schalter_auch_bei_einem_bausatz(daten: Path, monkeypatch):
    """bildbausatz.schalter() can add --vae itself, but this integration
    must not duplicate the flag the command already carries for every
    model — the existing unconditional --vae line stays untouched."""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(
            modell=daten / "klein.gguf", prompt="x", familie="flux",
            diffusion_model=daten / "flux1-dev.gguf", vae=daten / "ae.safetensors",
        ),
        daten / "a.png",
    )
    assert befehl.count("--vae") == 1


# --- Auftrag B: the twelve refinement fields, measured on the built command ---
#
# Every switch is asserted on the produced sd-cli command list, never
# inferred from the code that builds it — and for every field the unset
# case proves the switch stays off ENTIRELY: an explicit `--eta 0` or
# `--ad-negative-prompt ""` would change the picture against today.


def _befehl(daten: Path, monkeypatch, **felder) -> list[str]:
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    return Bildrunner(daten).befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="x", **felder), daten / "a.png"
    )


def test_hires_zusatzfelder_fallen_unbesetzt_weg(daten: Path, monkeypatch):
    """hires on, every second-pass dial untouched: exactly today's command."""
    befehl = _befehl(daten, monkeypatch, hires=True)
    for schalter in (
        "--hires-steps", "--hires-denoising-strength", "--hires-upscaler",
        "--hires-upscalers-dir", "--hires-width", "--hires-height",
    ):
        assert schalter not in befehl


def test_hires_denoise_traegt_den_wert(daten: Path, monkeypatch):
    befehl = _befehl(daten, monkeypatch, hires=True, hires_denoise=0.55)
    assert befehl[befehl.index("--hires-denoising-strength") + 1] == "0.55"


def test_hires_upscaler_fester_name_kommt_ohne_ordner(daten: Path, monkeypatch):
    """A built-in name travels alone — the folder is only for model files."""
    befehl = _befehl(
        daten, monkeypatch, hires=True,
        hires_upscaler="Lanczos", hires_upscalers_ordner=daten / "upscaler",
    )
    assert befehl[befehl.index("--hires-upscaler") + 1] == "Lanczos"
    assert "--hires-upscalers-dir" not in befehl


def test_hires_upscaler_modellname_bringt_den_ordner_mit(daten: Path, monkeypatch):
    befehl = _befehl(
        daten, monkeypatch, hires=True,
        hires_upscaler="esrgan-x4", hires_upscalers_ordner=daten / "upscaler",
    )
    assert befehl[befehl.index("--hires-upscaler") + 1] == "esrgan-x4"
    assert befehl[befehl.index("--hires-upscalers-dir") + 1] == str(daten / "upscaler")


def test_hires_zielgroesse_traegt_beide_kanten(daten: Path, monkeypatch):
    befehl = _befehl(
        daten, monkeypatch, hires=True, hires_width=1664, hires_height=2432,
    )
    assert befehl[befehl.index("--hires-width") + 1] == "1664"
    assert befehl[befehl.index("--hires-height") + 1] == "2432"


def test_feintuning_faellt_unbesetzt_weg(daten: Path, monkeypatch):
    """None/empty means NO switch — sd-cli's own per-sampler defaults
    (eta 0 OR 1 depending on the sampler, flow-shift "auto") must keep
    applying, which no explicit value could repeat."""
    befehl = _befehl(daten, monkeypatch)
    for schalter in ("--eta", "--flow-shift", "--sigmas", "--extra-sample-args", "--prediction"):
        assert schalter not in befehl


def test_eta_null_ist_ein_echter_wert(daten: Path, monkeypatch):
    """0 is a REAL eta (a change for euler_a) — only None means unset."""
    befehl = _befehl(daten, monkeypatch, eta=0.0)
    assert befehl[befehl.index("--eta") + 1] == "0.0"


def test_feintuning_traegt_alle_vier_schalter(daten: Path, monkeypatch):
    befehl = _befehl(
        daten, monkeypatch, eta=0.5, flow_shift=3.0,
        sigmas="14.61,7.8,3.5,0.0", extra_sample_args="base_shift=0.5",
    )
    assert befehl[befehl.index("--eta") + 1] == "0.5"
    assert befehl[befehl.index("--flow-shift") + 1] == "3.0"
    assert befehl[befehl.index("--sigmas") + 1] == "14.61,7.8,3.5,0.0"
    assert befehl[befehl.index("--extra-sample-args") + 1] == "base_shift=0.5"


def test_prediction_traegt_den_wert(daten: Path, monkeypatch):
    befehl = _befehl(daten, monkeypatch, prediction="flux_flow")
    assert befehl[befehl.index("--prediction") + 1] == "flux_flow"


def test_ad_negativ_und_schwelle_fallen_unbesetzt_weg(daten: Path, monkeypatch):
    """A detector without the two new dials: exactly today's command — an
    explicit --ad-negative-prompt "" would break sd-cli's own inheritance
    of the main negative prompt."""
    (daten / "adetailer").mkdir()
    (daten / "adetailer" / "face.pt").write_bytes(b"x")
    befehl = _befehl(daten, monkeypatch, ad_modell=daten / "adetailer" / "face.pt")
    assert "--ad-negative-prompt" not in befehl
    assert "--extra-ad-args" not in befehl


def test_ad_negativ_und_schwelle_haengen_am_detektor(daten: Path, monkeypatch):
    """Without a detector there is nothing they could act on — set anyway,
    they stay off the command instead of riding along as a claim."""
    befehl = _befehl(daten, monkeypatch, ad_negativ="blurry", ad_confidence=0.4)
    assert "--ad-negative-prompt" not in befehl
    assert "--extra-ad-args" not in befehl


def test_ad_negativ_und_schwelle_tragen_ihre_werte(daten: Path, monkeypatch):
    (daten / "adetailer").mkdir()
    (daten / "adetailer" / "face.pt").write_bytes(b"x")
    befehl = _befehl(
        daten, monkeypatch, ad_modell=daten / "adetailer" / "face.pt",
        ad_negativ="blurry", ad_confidence=0.4,
    )
    assert befehl[befehl.index("--ad-negative-prompt") + 1] == "blurry"
    assert befehl[befehl.index("--extra-ad-args") + 1] == "confidence=0.4"


def test_gesichts_lora_reist_im_hauptprompt(daten: Path, monkeypatch):
    """The engine does not read `<lora:...>` from `--ad-prompt` — measured
    against the build this program drives, a name written there drew no
    reaction at all. What it does instead is reuse the main pass's LoRA
    settings for the detail pass, so the main prompt is the only place a
    face LoRA can be written and still reach the face."""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(
            modell=daten / "klein.gguf", prompt="frau im wald",
            loras=(LoRA(name="stil.safetensors", staerke=0.6),),
            ad_modell=daten / "face.pt",
            ad_prompt="ein ruhiges gesicht",
            ad_loras=(LoRA(name="gesicht.safetensors", staerke=0.9),),
            lora_ordner=daten,
        ),
        daten / "a.png",
    )
    haupt = befehl[befehl.index("-p") + 1]
    gesicht = befehl[befehl.index("--ad-prompt") + 1]
    assert "<lora:stil:0.6>" in haupt
    assert "<lora:gesicht:0.9>" in haupt, "otherwise it is never loaded"
    assert "<lora:" not in gesicht, "the engine does not read it there"
    assert gesicht == "ein ruhiges gesicht"


def test_ein_lora_in_beiden_staepeln_wird_nur_einmal_geschrieben(daten: Path, monkeypatch):
    """Twice the same name only adds up its strength."""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(
            modell=daten / "klein.gguf", prompt="frau im wald",
            loras=(LoRA(name="gesicht.safetensors", staerke=0.6),),
            ad_modell=daten / "face.pt",
            ad_loras=(LoRA(name="gesicht.safetensors", staerke=0.9),),
            lora_ordner=daten,
        ),
        daten / "a.png",
    )
    haupt = befehl[befehl.index("-p") + 1]
    assert haupt.count("<lora:gesicht:") == 1
    assert "<lora:gesicht:0.6>" in haupt, "the main stack wins"


def test_ohne_eigenen_text_bleibt_der_ad_prompt_ganz_weg(daten: Path, monkeypatch):
    """An empty detailer prompt inherits the main one — useful behaviour of
    the engine's own, and the reason the flag stays off the command line
    when there is nothing to say. The face LoRA no longer forces text into
    it, so there is nothing left to write."""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    befehl = Bildrunner(daten).befehl(
        Auftrag(
            modell=daten / "klein.gguf", prompt="frau im wald",
            ad_modell=daten / "face.pt",
            ad_loras=(LoRA(name="gesicht.safetensors", staerke=0.9),),
            lora_ordner=daten,
        ),
        daten / "a.png",
    )
    assert "--ad-prompt" not in befehl
    assert "<lora:gesicht:0.9>" in befehl[befehl.index("-p") + 1]
    # The folder has to travel even when the ONLY stack is the detailer's,
    # or the name in the prompt resolves against nothing.
    assert "--lora-model-dir" in befehl


def test_ohne_gesichts_lora_bleibt_alles_wie_vorher(daten: Path, monkeypatch):
    """The silence half. No face stack must mean no change at all: an empty
    ad prompt stays OFF the command line (it inherits by itself), and a
    written one travels untouched — no stray `[PROMPT]` where nobody asked
    for one."""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    runner = Bildrunner(daten)
    ohne = runner.befehl(
        Auftrag(modell=daten / "klein.gguf", prompt="x", ad_modell=daten / "face.pt"),
        daten / "a.png",
    )
    assert "--ad-prompt" not in ohne
    mit_text = runner.befehl(
        Auftrag(
            modell=daten / "klein.gguf", prompt="x", ad_modell=daten / "face.pt",
            ad_prompt="scharfe augen",
        ),
        daten / "a.png",
    )
    assert mit_text[mit_text.index("--ad-prompt") + 1] == "scharfe augen"


# What sd-cli printed in the measured Metal crash: the backend's start-up
# chatter, then the painter's own error lines with their padded level tag.
_METAL_STARTUP = (
    "ggml_metal_device_init: tensor API disabled for pre-M5 and pre-A19 devices\n"
    "ggml_metal_library_init: using embedded metal library\n"
    "ts_init: creating a residency set collection\n"
    "ggml_metal_init: picking default device: Apple M4 Max\n"
    "ggml_metal_init: use bfloat         = true\n"
)
_METAL_ERRORS = (
    "[ERROR  ] ggml_metal_library_compile_pipeline: failed to compile pipeline: "
    "base = 'kernel_mul_mm_f8_e4m3_f32'\n"
    "[ERROR  ] ggml_metal_library_compile_pipeline: Error Domain=MTLLibraryErrorDomain "
    'Code=5 "Function kernel_mul_mm_f8_e4m3_f32 was not found in the library"\n'
)
_SEGFAULT_NOTE = "[Exe AI] Command terminated by signal 11: SIGSEGV"


def _log_part(error: BildFehler) -> str:
    """The log part of a failed picture, which these runs always carry."""
    assert error.protokoll is not None
    return error.protokoll


def _failed_run(
    daten: Path, monkeypatch, stdout: str | bytes, returncode: int,
    platform: str = "darwin", stderr: str | bytes = b"",
) -> BildFehler:
    """One run of a painter that printed `stdout` and `stderr` and ended
    with `returncode` without writing a picture. The bytes go through the
    runner's own reader; the exit code is read as on `platform`."""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/somewhere/sd-cli")
    monkeypatch.setattr(bildrunner.sys, "platform", platform)

    class Process:
        pid = 4243

        def __init__(self):
            self.returncode = None
            self.stdout = io.BytesIO(stdout.encode() if isinstance(stdout, str) else stdout)
            self.stderr = io.BytesIO(stderr.encode() if isinstance(stderr, str) else stderr)

        def wait(self, timeout=None):
            self.returncode = returncode
            return returncode

        def poll(self):
            return self.returncode

    monkeypatch.setattr(bildrunner.subprocess, "Popen", lambda *a, **k: Process())
    target = daten / "out.png"
    with pytest.raises(BildFehler) as raised:
        Bildrunner(daten).erzeugen(Auftrag(modell=daten / "small.gguf", prompt="x"), target)
    assert raised.value.grund == "bild.gescheitert"
    return raised.value


def test_a_crash_names_its_signal_and_the_padded_error_lines(daten: Path, monkeypatch):
    """A segfault after Metal errors: the log part opens with the signal and
    carries the painter's error lines, not the start-up chatter."""
    error = _failed_run(daten, monkeypatch, _METAL_STARTUP + _METAL_ERRORS, -11)
    lines = _log_part(error).splitlines()
    assert lines[0].startswith(_SEGFAULT_NOTE)
    assert "failed to compile pipeline: base = 'kernel_mul_mm_f8_e4m3_f32'" in _log_part(error)
    assert "Function kernel_mul_mm_f8_e4m3_f32 was not found in the library" in _log_part(error)
    for start in _METAL_STARTUP.splitlines():
        assert start not in _log_part(error)


def test_an_ordinary_failure_carries_no_signal_line(daten: Path, monkeypatch):
    """Exit status 1 is the program's own word, not a signal."""
    error = _failed_run(daten, monkeypatch, _METAL_STARTUP + _METAL_ERRORS, 1)
    assert "signal" not in _log_part(error)
    assert "[Exe AI]" not in _log_part(error)
    assert _log_part(error).startswith("[ERROR  ] ggml_metal_library_compile_pipeline")


def test_without_error_lines_the_raw_tail_still_stands(daten: Path, monkeypatch):
    """No line worth picking: the raw tail is the log part, exactly the last
    whole lines that fit the limit."""
    raw = [f"raw line {i:03d} ......." for i in range(200)]
    assert len("\n".join(raw)) > bildrunner.LOG_LIMIT
    error = _failed_run(daten, monkeypatch, "\n".join(raw) + "\n", 1)
    fitting = (bildrunner.LOG_LIMIT + 1) // (len(raw[0]) + 1)  # line plus newline
    assert _log_part(error) == "\n".join(raw[-fitting:])


def test_an_overlong_last_raw_line_is_cut_from_the_front(daten: Path, monkeypatch):
    """The raw tail ends in one line longer than the limit: its end is kept,
    the log part is never left empty."""
    error = _failed_run(daten, monkeypatch, "short\n" + "y" * 1500 + "\n", 1)
    assert _log_part(error) == "y" * bildrunner.LOG_LIMIT


def test_an_overlong_last_raw_line_after_a_crash_note(daten: Path, monkeypatch):
    error = _failed_run(daten, monkeypatch, "short\n" + "y" * 1500 + "\n", -11)
    note, rest = _log_part(error).split("\n")
    assert note.startswith(_SEGFAULT_NOTE)
    assert rest and set(rest) == {"y"}
    assert len(_log_part(error)) == bildrunner.LOG_LIMIT


_REDRAWN_BAR = "|#  | 1/4 - 1it/s\r|## | 2/4 - 1it/s\r|###| 3/4 - 1it/s"


def test_a_progress_bar_redrawn_in_place_keeps_what_stood_last(daten: Path, monkeypatch):
    """Carriage returns redraw the bar on the same line: the line keeps the
    last drawing, and a "\r\n" ending is no redraw."""
    error = _failed_run(
        daten, monkeypatch, "loading\r\n" + _REDRAWN_BAR + "\n", 1,
    )
    assert _log_part(error).split("\n") == ["loading", "|###| 3/4 - 1it/s"]


def test_a_real_painter_redrawing_its_bar_is_read_as_one_line(daten: Path, monkeypatch):
    """Through a real child process and its real pipes: the bytes are read
    without newline translation."""
    script = (
        "import sys\n"
        f"sys.stdout.write({('loading' + chr(10) + _REDRAWN_BAR + chr(10))!r})\n"
        "sys.exit(1)\n"
    )
    monkeypatch.setattr(
        Bildrunner, "befehl", lambda self, job, target: [sys.executable, "-c", script],
    )
    with pytest.raises(BildFehler) as raised:
        Bildrunner(daten).erzeugen(
            Auftrag(modell=daten / "small.gguf", prompt="x"), daten / "out.png",
        )
    assert _log_part(raised.value).split("\n") == ["loading", "|###| 3/4 - 1it/s"]


def test_an_unknown_signal_number_is_still_named_by_number(daten: Path, monkeypatch):
    """A number the platform has no name for still says it was a signal."""
    error = _failed_run(daten, monkeypatch, _METAL_ERRORS, -200)
    assert _log_part(error).splitlines()[0] == "[Exe AI] Command terminated by signal 200"


def test_a_signal_without_a_description_keeps_its_name(daten: Path, monkeypatch):
    monkeypatch.setattr(bildrunner.signal, "strsignal", lambda n: None)
    error = _failed_run(daten, monkeypatch, _METAL_ERRORS, -11)
    assert _log_part(error).splitlines()[0] == _SEGFAULT_NOTE


def test_a_signal_without_telling_lines_leads_the_raw_tail(daten: Path, monkeypatch):
    error = _failed_run(daten, monkeypatch, _METAL_STARTUP, -11)
    lines = _log_part(error).splitlines()
    assert lines[0].startswith(_SEGFAULT_NOTE)
    assert lines[1:] == _METAL_STARTUP.strip().splitlines()


def test_the_limit_holds_with_the_signal_line_and_keeps_lines_whole(daten: Path, monkeypatch):
    """Eight long error lines overflow the limit: the whole log part, signal
    line included, stays inside it, and every kept line is a whole one."""
    long_lines = [f"[ERROR  ] line {i:02d} " + "x" * 200 for i in range(8)]
    error = _failed_run(daten, monkeypatch, "\n".join(long_lines) + "\n", -11)
    assert len(_log_part(error)) <= bildrunner.LOG_LIMIT
    lines = _log_part(error).splitlines()
    assert lines[0].startswith(_SEGFAULT_NOTE)
    assert len(lines) > 1
    assert lines[1:] == long_lines[-len(lines[1:]):]


@pytest.mark.parametrize(("code", "logged"), [
    (-11, "Picture failed (-11, SIGSEGV)"),
    (-200, "Picture failed (-200, signal 200)"),
])
def test_the_warning_names_the_crash(daten: Path, monkeypatch, caplog, code, logged):
    with caplog.at_level("WARNING", logger="app.bildrunner"):
        _failed_run(daten, monkeypatch, _METAL_ERRORS, code)
    assert logged in caplog.text


_WINDOWS_CRASHES = [
    (0xC0000005, "NTSTATUS 0xC0000005", "access violation"),
    (0xC00000FD, "NTSTATUS 0xC00000FD", "stack overflow"),
    (0xC0000409, "NTSTATUS 0xC0000409", "stack buffer overrun"),
    (0xC000001D, "NTSTATUS 0xC000001D", "illegal instruction"),
    (0xC0000094, "NTSTATUS 0xC0000094", "divide by zero"),
]


@pytest.mark.parametrize("signed", [False, True])
@pytest.mark.parametrize(("status", "name", "meaning"), _WINDOWS_CRASHES)
def test_a_windows_crash_status_is_named(monkeypatch, status, name, meaning, signed):
    """Python on Windows hands the exit code over unsigned (0xC0000005); the
    signed spelling (-1073741819) names the same status."""
    code = status - 0x100000000 if signed else status
    monkeypatch.setattr(bildrunner.sys, "platform", "win32")
    assert bildrunner._crash_note(code) == bildrunner.CrashNote(
        name, f"[Exe AI] Command terminated with {name}: {meaning}",
    )


@pytest.mark.parametrize("code", [0xC0000135, 0xC0000135 - 0x100000000])
def test_an_unknown_windows_error_status_is_named_by_its_hex_value(monkeypatch, code):
    monkeypatch.setattr(bildrunner.sys, "platform", "win32")
    assert bildrunner._crash_note(code) == (
        "NTSTATUS 0xC0000135", "[Exe AI] Command terminated with NTSTATUS 0xC0000135",
    )


@pytest.mark.parametrize("code", [0, 1, 255, -1, 0xFFFFFFFF, 0xBFFFFFFF])
def test_an_ordinary_windows_exit_gets_no_note(monkeypatch, code):
    """No signals on Windows: exit(-1) and every code below the error range
    are the program's own word."""
    monkeypatch.setattr(bildrunner.sys, "platform", "win32")
    assert bildrunner._crash_note(code) is None


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_signals_are_read_on_mac_and_linux(monkeypatch, platform):
    monkeypatch.setattr(bildrunner.sys, "platform", platform)
    note = bildrunner._crash_note(-11)
    assert note.name == "SIGSEGV"
    assert note.line.startswith(_SEGFAULT_NOTE)


@pytest.mark.parametrize("platform", ["darwin", "linux"])
@pytest.mark.parametrize("code", [1, 2, 255, 0xBFFFFFFF, 0xC0000005])
def test_no_ntstatus_reading_off_windows(monkeypatch, platform, code):
    """A positive code is an exit status off Windows, even in the NTSTATUS
    range."""
    monkeypatch.setattr(bildrunner.sys, "platform", platform)
    assert bildrunner._crash_note(code) is None


def test_a_positive_code_in_the_ntstatus_range_gets_no_note_off_windows(
    daten: Path, monkeypatch,
):
    """Through the whole run, read as on a Mac."""
    error = _failed_run(daten, monkeypatch, _METAL_ERRORS, 0xC0000005)
    assert "[Exe AI]" not in _log_part(error)


@pytest.mark.parametrize("code", [3221225477, -1073741819])
def test_a_windows_crash_leads_the_log_through_the_whole_run(daten: Path, monkeypatch, code):
    """CPython hands over the unsigned DWORD (3221225477); the signed
    spelling reads the same."""
    error = _failed_run(daten, monkeypatch, _METAL_ERRORS, code, platform="win32")
    lines = _log_part(error).splitlines()
    assert lines[0] == "[Exe AI] Command terminated with NTSTATUS 0xC0000005: access violation"
    assert lines[1].startswith("[ERROR  ] ggml_metal_library_compile_pipeline")


def test_exit_minus_one_on_windows_gets_no_note_through_the_whole_run(
    daten: Path, monkeypatch,
):
    error = _failed_run(daten, monkeypatch, _METAL_ERRORS, -1, platform="win32")
    assert "[Exe AI]" not in _log_part(error)


def test_a_stray_byte_does_not_silence_the_reader(daten: Path, monkeypatch, caplog):
    """A byte the encoding cannot read is replaced; the lines after it still
    arrive, in the log part and in the server log."""
    monkeypatch.setattr(bildrunner, "_pipe_encoding", lambda: "utf-8")
    with caplog.at_level("WARNING", logger="app.bildrunner"):
        error = _failed_run(
            daten, monkeypatch,
            b"loading \xff\xfe done\n" + _METAL_ERRORS.encode(), 1, stderr=b"\xc3\n",
        )
    assert "Function kernel_mul_mm_f8_e4m3_f32 was not found in the library" in _log_part(error)
    assert "loading \ufffd\ufffd done" in caplog.text


def test_the_server_log_shows_the_redrawn_bar_as_it_stood_last(daten: Path, monkeypatch, caplog):
    with caplog.at_level("WARNING", logger="app.bildrunner"):
        _failed_run(daten, monkeypatch, "loading\n" + _REDRAWN_BAR + "\n", 1)
    assert "\r" not in caplog.text
    assert "loading\n|###| 3/4 - 1it/s" in caplog.text



def test_textleser_stehen_nie_in_der_bildmodell_liste(tmp_path: Path):
    """Krea 2's, Qwen-Image's and ERNIE's encoders, in GGUF and
    safetensors, lie in the folder: they are text encoders, not models to
    draw with. A Flux model beside them stays one."""
    import struct as _struct

    def gguf(name: str, architektur: str) -> None:
        roh = architektur.encode()
        schluessel = b"general.architecture"
        kopf = (b"GGUF" + _struct.pack("<I", 3) + _struct.pack("<Q", 0) + _struct.pack("<Q", 1)
                + _struct.pack("<Q", len(schluessel)) + schluessel + _struct.pack("<I", 8)
                + _struct.pack("<Q", len(roh)) + roh)
        (tmp_path / name).write_bytes(kopf)

    gguf("qwen3-vl-4b.gguf", "qwen3vl")
    gguf("qwen2.5-vl-7b.gguf", "qwen2vl")
    gguf("ministral-3-3b.gguf", "mistral3")
    gguf("flux1-dev.gguf", "flux")
    (tmp_path / "qwen_2.5_vl_7b.safetensors").write_bytes(
        _safetensors_bytes(["model.layers.0.self_attn.q_proj.weight", "model.embed_tokens.weight"])
    )
    assert bildrunner.modelle(tmp_path) == ["flux1-dev.gguf"]
    assert bildrunner.textversteher(tmp_path) == [
        "ministral-3-3b.gguf", "qwen2.5-vl-7b.gguf", "qwen3-vl-4b.gguf", "qwen_2.5_vl_7b.safetensors",
    ]


def test_ohne_sampler_waehlt_sd_cli_selbst(daten: Path, monkeypatch):
    """No sampler named: no --sampling-method at all, so sd-cli picks the
    model's own (euler for a DiT like Flux, not euler_a)."""
    assert "--sampling-method" not in _befehl(daten, monkeypatch)


def test_ein_genannter_sampler_geht_hinaus(daten: Path, monkeypatch):
    """The silence probe: a sampler that is named stands in the command."""
    befehl = _befehl(daten, monkeypatch, sampler="dpm++2m")
    assert befehl[befehl.index("--sampling-method") + 1] == "dpm++2m"


# --- The step counter hears the painter as it speaks -------------------------


class _PipedPainter:
    """A painter the test speaks for. What the test writes travels through a
    real pipe, the way a child process's output does, and the run lasts
    until the test ends it."""

    pid = 4244

    def __init__(self) -> None:
        read_end, write_end = os.pipe()
        self.stdout = os.fdopen(read_end, "rb")
        self.stderr = io.BytesIO()
        self._mouth = os.fdopen(write_end, "wb", buffering=0)
        self._ended = threading.Event()
        self.returncode: int | None = None

    def say(self, text: str) -> None:
        self._mouth.write(text.encode())

    def end(self) -> None:
        if not self._ended.is_set():
            self._mouth.close()
            self.returncode = 0
            self._ended.set()

    def wait(self, timeout=None):
        self._ended.wait(10)
        return self.returncode

    def poll(self):
        return self.returncode


def _painting_bar(step: int, total: int) -> str:
    """One bar of a painting pass as the painter redraws it: it counts
    iterations."""
    filled = "=" * (50 * step // total)
    return f"\r  |{filled:<50}| {step}/{total} - 9.57s/it\x1b[K" + ("\n" if step == total else "")


def _loading_bar(done: int, total: int) -> str:
    """One bar of weights being loaded: it counts megabytes."""
    filled = "#" * (50 * done // total)
    return f"\r  |{filled:<50}| {done}/{total} - 111.66MB/s\x1b[K"


def _reached(condition, seconds: float = 2.0) -> bool:
    """True as soon as ``condition()`` holds, False when it still does not
    after ``seconds``."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return bool(condition())


@pytest.fixture
def runs():
    """The runs a test starts, each ended and its pipe closed afterwards."""
    started: list[tuple[_PipedPainter, threading.Thread]] = []
    yield started
    for painter, thread in started:
        painter.end()
        thread.join(5)
        painter.stdout.close()


def _on_sd_cli(runs, daten: Path, monkeypatch, steps: int, **job):
    """Start one sd-cli run of ``steps`` requested steps on a painter the
    test speaks for; hands back the painter and a function that reads the
    progress the way the progress route does."""
    painter = _PipedPainter()
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/somewhere/sd-cli")
    monkeypatch.setattr(bildrunner.subprocess, "Popen", lambda *a, **k: painter)
    runner = Bildrunner(daten)
    target = daten / "out.png"
    target.write_bytes(b"png")
    order = Auftrag(modell=daten / "klein.gguf", prompt="x", schritte=steps, **job)
    thread = threading.Thread(target=lambda: runner.erzeugen(order, target))
    thread.start()
    runs.append((painter, thread))
    return painter, lambda: runner.fortschritt() or {}


def _on_the_picture_server(runs, daten: Path, steps: int, passes: int = 1):
    """The same for a picture drawn over the picture server, planned as
    ``passes`` painting passes: its reader at work on the test's painter."""
    painter = _PipedPainter()
    turbo = Bildturbo(daten)
    turbo._prozess = painter  # type: ignore[assignment]
    turbo._zeichnet = True
    turbo._arm_counter(steps, passes)
    thread = threading.Thread(target=turbo._zaehler_lesen, args=(painter,))
    thread.start()
    runs.append((painter, thread))
    return painter, lambda: turbo.fortschritt() or {}


@pytest.fixture(params=["sd-cli", "picture server"])
def counter(request, runs, daten: Path, monkeypatch):
    """Each of the two readers of a painter's output in turn.
    ``counter(steps)`` starts a run and hands back the painter and the
    progress function; ``passes`` plans the picture server's run, the
    job's own fields plan sd-cli's."""

    def start(steps: int, passes: int = 1, **job):
        if request.param == "sd-cli":
            return _on_sd_cli(runs, daten, monkeypatch, steps, **job)
        return _on_the_picture_server(runs, daten, steps, passes)

    return start


def test_every_step_is_reported_before_the_painter_writes_the_next(counter):
    """The counter takes each bar the moment the painter has written it,
    not once a block of several bars has filled up."""
    painter, progress = counter(12)
    for step in range(1, 13):
        painter.say(_painting_bar(step, 12))
        assert _reached(lambda: progress().get("schritt") == step), (
            f"step {step} of 12 was not reported before the next bar"
        )
        assert progress()["gesamt"] == 12
        assert progress()["anteil"] == pytest.approx(min(step / 12, 0.99))


def test_a_bar_that_arrives_in_two_pieces_is_put_together(counter):
    """Silence probe: a bar cut in the middle of its step number is still
    read as the one bar it is, not as the tail's smaller number."""
    painter, progress = counter(12)
    for step in range(1, 11):
        painter.say(_painting_bar(step, 12))
    assert _reached(lambda: progress().get("schritt") == 10)
    whole = _painting_bar(11, 12)
    cut = whole.index("11/12") + 1
    painter.say(whole[:cut])
    painter.say(whole[cut:])
    assert _reached(lambda: progress().get("schritt") == 11)
    assert progress()["anteil"] == pytest.approx(11 / 12)


def test_the_error_channel_is_still_read_to_its_end(daten: Path, monkeypatch):
    """Silence probe: stderr is taken whole, far beyond one read, and its
    last line reaches the log part as before."""
    filler = "".join(f"ggml note {i:03d} {'.' * 40}\n" for i in range(40))
    error = _failed_run(
        daten, monkeypatch, "loading\n", 1,
        stderr="GGML_ASSERT: first\n" + filler + "GGML_ASSERT: last\n",
    )
    assert len(filler) > 2000
    assert _log_part(error).split("\n") == ["GGML_ASSERT: first", "GGML_ASSERT: last"]


def test_from_a_starting_picture_the_painters_own_step_count_is_counted(counter):
    """Asked for 8 steps from a starting picture, the painter makes 5: its
    bars read 1/5 to 5/5, and each one counts. Silence probe: the bars of
    the weights loaded before count nothing — not even one whose total is
    the requested step count."""
    painter, progress = counter(8)
    painter.say(_loading_bar(82, 82) + "\n")
    painter.say(_loading_bar(8, 8))
    painter.say(_loading_bar(94, 386))
    for step in range(1, 6):
        painter.say(_painting_bar(step, 5))
        assert _reached(lambda: progress().get("schritt") == step), (
            f"step {step} of 5 was not reported"
        )
        assert progress()["gesamt"] == 5
        assert progress()["anteil"] == pytest.approx(min(step / 5, 0.99))


def test_a_later_bar_with_another_total_is_never_reported_as_the_step(counter):
    """Sixteen painting steps, then bars that count something else: weights
    loaded for decoding, and a pass with 140 steps of its own. The share
    follows the later pass; the step stays within 16 of 16."""
    painter, progress = counter(16)
    for step in range(1, 17):
        painter.say(_painting_bar(step, 16))
    assert _reached(lambda: progress().get("schritt") == 16)
    painter.say(_loading_bar(140, 140))
    painter.say(_painting_bar(70, 140))
    assert _reached(lambda: progress().get("anteil") == pytest.approx(0.5))
    assert (progress()["schritt"], progress()["gesamt"]) == (16, 16)


def test_weights_loaded_between_two_passes_are_no_pass_of_their_own(counter, daten: Path):
    """Three planned passes: base, highres, detector. The megabyte bars
    after the base pass use up none of them — the next pass's first bar
    stands in the second third of the share, not in the last."""
    painter, progress = counter(
        12, passes=3, hires=True, ad_modell=daten / "face.safetensors",
    )
    for step in range(1, 13):
        painter.say(_painting_bar(step, 12))
    assert _reached(lambda: progress().get("schritt") == 12)
    assert progress()["anteil"] == pytest.approx(1 / 3)
    painter.say(_loading_bar(87, 104))
    painter.say(_loading_bar(104, 104) + "\n")
    painter.say(_loading_bar(1, 300))
    painter.say(_painting_bar(1, 12))
    assert _reached(lambda: progress().get("schritt") == 1)
    assert progress()["anteil"] == pytest.approx((1 + 1 / 12) / 3)


def _detector_says(found: int) -> str:
    return f"[INFO ] detailer.cpp:725  - ADetailer detected {found} object(s)\n"


def test_a_detector_that_finds_nothing_takes_its_pass_out_of_the_share(runs, daten: Path, monkeypatch):
    """sd-cli with a detector plans two passes. The detector says it found
    nothing: no second pass comes, and the share stands at the end instead
    of waiting at the half until the picture is there."""
    painter, progress = _on_sd_cli(runs, daten, monkeypatch, 12, ad_modell=daten / "face.safetensors")
    for step in range(1, 13):
        painter.say(_painting_bar(step, 12))
    assert _reached(lambda: progress().get("anteil") == pytest.approx(0.5))
    painter.say(_detector_says(0))
    assert _reached(lambda: progress().get("anteil") == pytest.approx(0.99))
    assert (progress()["schritt"], progress()["gesamt"]) == (12, 12)


def test_with_highres_the_share_without_the_detector_s_pass_is_the_end_too(
    runs, daten: Path, monkeypatch,
):
    """Three planned passes — base, highres, detector — and the detector's
    word arriving in two pieces: the share stood at two thirds and goes to
    the end."""
    painter, progress = _on_sd_cli(
        runs, daten, monkeypatch, 12, hires=True, ad_modell=daten / "face.safetensors",
    )
    for _pass in range(2):
        for step in range(1, 13):
            painter.say(_painting_bar(step, 12))
    assert _reached(lambda: progress().get("anteil") == pytest.approx(2 / 3))
    line = _detector_says(0)
    painter.say(line[:40])
    painter.say(line[40:])
    assert _reached(lambda: progress().get("anteil") == pytest.approx(0.99))


@pytest.mark.parametrize("found", [1, 10])
def test_a_detector_that_finds_a_face_keeps_its_pass(runs, daten: Path, monkeypatch, found):
    """Silence probe: with a face found the share stays at the half, and the
    bars of the repair lead to the end — ten faces are not none."""
    painter, progress = _on_sd_cli(runs, daten, monkeypatch, 12, ad_modell=daten / "face.safetensors")
    for step in range(1, 13):
        painter.say(_painting_bar(step, 12))
    assert _reached(lambda: progress().get("anteil") == pytest.approx(0.5))
    painter.say(_detector_says(found))
    painter.say(_painting_bar(3, 12))
    assert _reached(lambda: progress().get("anteil") == pytest.approx((1 + 3 / 12) / 2))
    painter.say(_painting_bar(12, 12))
    assert _reached(lambda: progress().get("anteil") == pytest.approx(0.99))


def test_without_a_detector_its_word_changes_nothing(runs, daten: Path, monkeypatch):
    """Silence probe: a picture that plans no detector pass has none to
    take out — base and highres stay two passes."""
    painter, progress = _on_sd_cli(runs, daten, monkeypatch, 12, hires=True)
    for step in range(1, 13):
        painter.say(_painting_bar(step, 12))
    assert _reached(lambda: progress().get("anteil") == pytest.approx(0.5))
    painter.say(_detector_says(0))
    painter.say(_painting_bar(6, 12))
    assert _reached(lambda: progress().get("anteil") == pytest.approx((1 + 6 / 12) / 2))


# --- A stop asked before the picture draws ------------------------------------


def test_a_stop_is_kept_only_for_a_hold_that_can_let_go(tmp_path: Path):
    """No picture: nothing to stop. A hold that cannot let go (a model being
    converted): nothing either. A picture that waits to draw: the stop is
    kept for it — and a new hold starts without it."""
    runner = Bildrunner(tmp_path)
    assert runner.ask_stop() is False
    runner.reservieren()
    try:
        assert runner.ask_stop() is False
        runner.end_if_stopped()
    finally:
        runner.freigeben()
    runner.reservieren(stoppable=True)
    try:
        assert runner.stop_asked() is False
        assert runner.ask_stop() is True
        with pytest.raises(BildFehler) as error:
            runner.end_if_stopped()
        assert error.value.grund == "bild.abgebrochen"
    finally:
        runner.freigeben()
    assert runner.ask_stop() is False
    runner.reservieren(stoppable=True)
    try:
        assert runner.stop_asked() is False
        # After the picture's last look a stop no longer reaches it.
        runner.end_if_stopped(last=True)
        assert runner.ask_stop() is False
    finally:
        runner.freigeben()


def test_a_picture_stopped_before_its_draw_never_starts_the_painter(tmp_path: Path, monkeypatch):
    """The picture server stepped aside for an sd-cli picture and the stop
    came meanwhile: sd-cli is not started, and the lock stays the caller's."""
    started: list = []
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/somewhere/sd-cli")
    monkeypatch.setattr(bildrunner.subprocess, "Popen", lambda *a, **k: started.append(a))
    runner = Bildrunner(tmp_path)
    job = Auftrag(modell=tmp_path / "m.gguf", prompt="x")
    runner.reservieren(stoppable=True)
    try:
        assert runner.ask_stop() is True
        with pytest.raises(BildFehler) as error:
            runner.erzeugen(job, tmp_path / "a.png", reserved=True)
        assert error.value.grund == "bild.abgebrochen"
        assert started == [] and runner.laeuft()
    finally:
        runner.freigeben()


def test_a_stop_in_the_moment_the_painter_starts_ends_it(runs, daten: Path, monkeypatch):
    """Asked after the look before the start, when there was no process to
    end yet: the painter that was just started is ended, and the picture is
    a stopped one, not a drawn one."""
    painter = _PipedPainter()
    runner = Bildrunner(daten)

    def start(*a, **k):
        assert runner.ask_stop() is True
        return painter

    ended: list = []
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/somewhere/sd-cli")
    monkeypatch.setattr(bildrunner.subprocess, "Popen", start)
    monkeypatch.setattr(
        bildrunner.prozessstopp, "beenden", lambda p, frist=5.0: (ended.append(p), p.end()),
    )
    target = daten / "out.png"
    target.write_bytes(b"png")
    with pytest.raises(BildFehler) as error:
        runner.erzeugen(Auftrag(modell=daten / "klein.gguf", prompt="x"), target)
    painter.stdout.close()
    assert error.value.grund == "bild.abgebrochen"
    assert ended == [painter]
    assert not target.exists() and not runner.laeuft()


def test_a_bar_that_counts_megabytes_is_no_step_for_either_reader():
    """Bars as the painter really prints them: the ones that count
    iterations are steps, slow or fast; the one drawn while weights load is
    not, whatever its numbers."""
    from app import bildturbo

    slow = "\r  |==========>                                       | 1/5 - 44.45s/it\x1b[K"
    fast = "|=====>    | 12/28 - 3.10it/s"
    loading = "\r  |##########################################        | 87/104 - 111.66MB/s\x1b[K"
    for module in (bildrunner, bildturbo):
        assert module._SCHRITT_MUSTER.search(slow).group(1, 2) == ("1", "5")
        assert module._SCHRITT_MUSTER.search(fast).group(1, 2) == ("12", "28")
        assert module._SCHRITT_MUSTER.search(loading) is None


def test_the_picture_server_with_a_detector_ends_at_the_full_bar(runs, daten: Path):
    """The picture server's bar plans the passes that path really paints,
    and a detector set there adds none: one painting pass ends the bar full
    — just under one until the file exists — not at half. Silence probe:
    highres is a pass that path does paint, and stays planned."""
    with_detector = Auftrag(
        modell=daten / "klein.gguf", prompt="x", schritte=8,
        ad_modell=daten / "face.safetensors",
    )
    painter, progress = _on_the_picture_server(
        runs, daten, 8, _erwartete_paesse(with_detector),
    )
    for step in range(1, 9):
        painter.say(_painting_bar(step, 8))
    assert _reached(lambda: progress().get("schritt") == 8)
    assert progress()["anteil"] == 0.99

    with_highres = Auftrag(
        modell=daten / "klein.gguf", prompt="x", schritte=8, hires=True,
        ad_modell=daten / "face.safetensors",
    )
    painter, progress = _on_the_picture_server(
        runs, daten, 8, _erwartete_paesse(with_highres),
    )
    for step in range(1, 9):
        painter.say(_painting_bar(step, 8))
    assert _reached(lambda: progress().get("schritt") == 8)
    assert progress()["anteil"] == pytest.approx(0.5)


def test_a_bar_counting_beyond_the_requested_steps_does_not_start_the_count(counter):
    """A loader that counts tensors draws its bar in the painter's own shape
    and unit. Before painting has begun, a bar that counts further than the
    steps asked for is no painting pass: the first step still reads 1 of 12."""
    painter, progress = counter(12)
    painter.say(_painting_bar(300, 1500))
    painter.say(_painting_bar(1500, 1500))
    painter.say(_painting_bar(1, 12))
    assert _reached(lambda: progress().get("schritt") == 1)
    assert progress()["gesamt"] == 12
    assert progress()["anteil"] == pytest.approx(1 / 12)


_PAINTING_BEGINS = "[INFO ] stable-diffusion.cpp:5670 - generating image: 1/1 - seed 730\n"


def test_tiles_encoded_before_painting_are_no_part_of_the_share(counter):
    """A starting picture encoded tile by tile draws a bar that counts
    iterations, before the painter says that it starts to paint. At that
    word the count begins anew: the first step of five reads 1 of 5, at a
    fifth. Silence probe: the same word said again resets nothing."""
    painter, progress = counter(8)
    painter.say(_painting_bar(1, 1))
    assert _reached(lambda: progress().get("anteil") == 0.99)
    painter.say(_PAINTING_BEGINS)
    assert _reached(lambda: progress().get("anteil") == 0.0)
    assert (progress()["schritt"], progress()["gesamt"]) == (0, 8)
    for step in range(1, 4):
        painter.say(_painting_bar(step, 5))
    assert _reached(lambda: progress().get("schritt") == 3)
    assert progress()["gesamt"] == 5
    assert progress()["anteil"] == pytest.approx(0.6)
    painter.say(_PAINTING_BEGINS)
    painter.say(_painting_bar(4, 5))
    assert _reached(lambda: progress().get("schritt") == 4)
    assert progress()["anteil"] == pytest.approx(0.8)


# --- Converting a model file is the runner's process -------------------------

# Stands in for sd-cli converting: half the copy, a wait, the whole copy.
_CONVERTER = (
    "import pathlib, sys, time\n"
    "out = pathlib.Path(sys.argv[1])\n"
    "out.write_bytes(b'half')\n"
    "print('converting', flush=True)\n"
    "time.sleep(float(sys.argv[2]))\n"
    "if sys.argv[3] != '0':\n"
    "    sys.exit(int(sys.argv[3]))\n"
    "out.write_bytes(b'whole')\n"
)


@pytest.fixture
def converting(config: Config, client: TestClient, tmp_path: Path, monkeypatch):
    """A model file a smaller copy can be made of, and a way to ask the
    route for that copy from a thread of its own: the converter writes half
    the copy, waits ``seconds``, then ends with ``code``."""
    folder = tmp_path / "bildmodelle"
    config.app.bildmodelle_verzeichnis = str(folder)
    folder.mkdir()
    header = json.dumps({"w": {"dtype": "F16", "shape": [64, 64]}}).encode()
    (folder / "m.safetensors").write_bytes(struct.pack("<Q", len(header)) + header)
    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path(sys.executable)))

    def start(seconds: float, code: int = 0):
        monkeypatch.setattr(
            model_convert, "command",
            lambda program, source, kind: [
                str(program), "-c", _CONVERTER,
                str(model_convert.target(source, kind)), str(seconds), str(code),
            ],
        )
        answers: list = []
        thread = threading.Thread(
            target=lambda: answers.append(client.post(
                "/api/v1/bild/convert", json={"model": "m.safetensors", "weight_type": "q8_0"},
            )),
            daemon=True,
        )
        thread.start()
        return thread, answers

    return folder / "m.q8_0.gguf", start


def test_a_stop_ends_a_running_conversion_and_frees_the_lock(converting, client, caplog):
    """The stop that ends a picture ends a conversion: its answer says
    stopped, the log names it, the half-written copy is gone, and the
    one-picture lock is free at once."""
    out, start = converting
    runner = client.app.state.bildrunner
    with caplog.at_level(logging.INFO, logger="app.model_convert"):
        thread, answers = start(30)
        assert _reached(out.is_file, 10)
        assert runner.laeuft()
        assert client.post("/api/v1/bild/stop").json() is True
        thread.join(timeout=20)
    assert not thread.is_alive()
    assert answers[0].status_code == 499
    assert answers[0].json()["detail"] in ("Zeichnen abgebrochen", "Drawing stopped")
    assert not out.exists()
    assert "Converting m.safetensors to q8_0 was stopped" in caplog.text
    assert not runner.laeuft()
    # Free for the next picture, and nothing left to stop.
    runner.reservieren()
    runner.freigeben()
    assert client.post("/api/v1/bild/stop").json() is False


def test_a_conversion_nobody_stops_ends_with_the_new_file(converting, client):
    """Silence: without a stop the copy is made and the lock handed back."""
    out, start = converting
    thread, answers = start(0)
    thread.join(timeout=20)
    assert answers[0].status_code == 200, answers[0].text
    assert answers[0].json() == {"file": "m.q8_0.gguf"}
    assert out.read_bytes() == b"whole"
    assert not client.app.state.bildrunner.laeuft()


def test_a_failed_conversion_answers_as_before(converting, client):
    """Silence: a converter that ends with an error is no stop — its own
    words come back, the half-written copy goes, the lock is free."""
    out, start = converting
    thread, answers = start(0, code=3)
    thread.join(timeout=20)
    assert answers[0].status_code == 503
    assert answers[0].json()["detail"].endswith("converting")
    assert not out.exists()
    assert not client.app.state.bildrunner.laeuft()


def test_a_stray_byte_the_converter_prints_does_not_cost_the_answer(daten: Path):
    """What a tool prints is read with a byte that is no text replaced:
    the exit code and the words around the byte still come back."""
    script = "import sys\nsys.stdout.buffer.write(b'before \\xff after')\nsys.exit(3)\n"
    runner = Bildrunner(daten)
    code, text = runner.run_tool([sys.executable, "-c", script], timeout=20)
    assert code == 3
    assert text.startswith("before ") and text.rstrip().endswith(" after")
    assert runner._prozess is None


def test_a_conversion_past_its_time_is_ended(converting, client, monkeypatch):
    """Silence: the ceiling still catches a hang, and ends the converter."""
    monkeypatch.setattr(model_convert, "CONVERT_TIMEOUT", 0.5)
    out, start = converting
    began = time.monotonic()
    thread, answers = start(30)
    thread.join(timeout=20)
    assert time.monotonic() - began < 15
    assert answers[0].status_code == 503
    assert not out.exists()
    assert not client.app.state.bildrunner.laeuft()


def test_a_picture_still_stops_as_before(daten: Path, monkeypatch):
    """Silence: a running picture ends on a stop and reports it as stopped."""
    monkeypatch.setattr(
        Bildrunner, "befehl",
        lambda self, job, target: [sys.executable, "-c", "import time\ntime.sleep(30)\n"],
    )
    runner = Bildrunner(daten)
    raised: list[str] = []

    def draw() -> None:
        try:
            runner.erzeugen(Auftrag(modell=daten / "klein.gguf", prompt="x"), daten / "out.png")
        except BildFehler as error:
            raised.append(error.grund)

    thread = threading.Thread(target=draw, daemon=True)
    thread.start()
    assert _reached(lambda: runner._prozess is not None, 10)
    assert runner.stoppen() is True
    thread.join(timeout=20)
    assert raised == ["bild.abgebrochen"]
    assert not runner.laeuft()
