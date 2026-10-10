"""Image-Turbo: the persistent picture server's guards, not its pictures.

The drawing itself is proved by running it; here we test the switch logic and
the state machine that the plus-menu plaque colours itself by.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import bildrunner
from app.bildturbo import PROGRAMM, Bildturbo, BildturboFehler, programm_finden
from app.api.v1.bild import _turbo_auftrag
from app.bildrunner import Auftrag, Bildrunner, LoRA
from app.photomaker import fingerabdruck


def test_ohne_prozess_ist_der_zustand_aus(tmp_path: Path):
    assert Bildturbo(tmp_path).zustand() == "aus"


def test_ohne_server_binary_kein_programm(tmp_path: Path):
    assert programm_finden(tmp_path) is None
    assert Bildturbo(tmp_path).programm is None


def test_das_binary_wird_im_build_ordner_gefunden(tmp_path: Path):
    import os
    build = tmp_path / "stable-diffusion.cpp" / "master-1"
    build.mkdir(parents=True)
    prog = build / PROGRAMM
    prog.write_text("#!/bin/sh\n")
    prog.chmod(0o755)
    gefunden = programm_finden(tmp_path)
    assert gefunden is not None and gefunden.name == PROGRAMM
    assert os.access(gefunden, os.X_OK)


def test_der_turbo_body_traegt_nur_die_basis():
    """Without extras the body stays the bare basics — nothing is invented.
    The fields are those of the server's own route ``img_gen``."""
    auftrag = Auftrag(
        modell=Path("/m.safetensors"), prompt="ein Leuchtturm", negativ="unscharf",
        breite=1024, hoehe=1024, schritte=28, cfg=6.5, seed=42,
        sampler="euler_a", scheduler="karras",
    )
    body = _turbo_auftrag(auftrag)
    assert body == {
        "prompt": "ein Leuchtturm", "negative_prompt": "unscharf",
        "width": 1024, "height": 1024, "seed": 42,
        "sample_params": {
            "sample_method": "euler_a", "sample_steps": 28, "scheduler": "karras",
            "guidance": {"txt_cfg": 6.5},
        },
        "vae_tiling_params": {"enabled": False},
        "embed_image_metadata": True,
        "output_format": "png",
    }


def test_der_turbo_body_laesst_leeren_negativ_und_scheduler_weg():
    auftrag = Auftrag(modell=Path("/m.safetensors"), prompt="x", scheduler="")
    body = _turbo_auftrag(auftrag)
    assert "negative_prompt" not in body
    assert "scheduler" not in body["sample_params"]


def test_der_turbo_body_traegt_die_loras_im_eigenen_feld():
    """A LoRA IS a body field for this server — and it must not be written
    into the prompt.

    Measured against build 820 (master-820-de298c2): the JSON route
    parses no ``<lora:...>`` tag out of a prompt at all — a made-up name drew
    no reaction where sd-cli warns "can not found lora" at once — so the tag
    only reached the text encoder as words. The ``lora`` array is what the
    route reads, and with it the same file reports "834 / 834 LoRA tensors
    have been applied". ``path`` carries the extension, the file name in
    the LoRA folder the server was started with.
    """
    auftrag = Auftrag(
        modell=Path("/m.safetensors"), prompt="a lighthouse",
        loras=(LoRA(name="Hyper-SD15.safetensors", staerke=0.7),
               LoRA(name="detail.safetensors", staerke=0.5)),
    )
    body = _turbo_auftrag(auftrag)
    assert body["prompt"] == "a lighthouse"
    assert body["lora"] == [
        {"path": "Hyper-SD15.safetensors", "multiplier": 0.7},
        {"path": "detail.safetensors", "multiplier": 0.5},
    ]


def test_die_detailer_loras_stehen_im_selben_feld_und_nie_doppelt():
    """The detailer's own stack rides in the same field, for the same reason
    ``bildrunner.prompt_bauen`` writes it into the same prompt: the detail
    pass reuses the main pass's LoRA settings. A name already in the main
    stack is not repeated."""
    auftrag = Auftrag(
        modell=Path("/m.safetensors"), prompt="a face",
        loras=(LoRA(name="Hyper-SD15.safetensors", staerke=0.7),),
        ad_loras=(LoRA(name="Hyper-SD15.safetensors", staerke=0.9),
                  LoRA(name="gesicht.safetensors", staerke=0.4)),
    )
    body = _turbo_auftrag(auftrag)
    assert body["prompt"] == "a face"
    assert body["lora"] == [
        {"path": "Hyper-SD15.safetensors", "multiplier": 0.7},
        {"path": "gesicht.safetensors", "multiplier": 0.4},
    ]


def test_ohne_lora_kein_lora_feld():
    """Nothing invented: a picture without a LoRA sends no ``lora`` key at
    all, so the body stays exactly what it was."""
    auftrag = Auftrag(modell=Path("/m.safetensors"), prompt="a lighthouse")
    assert "lora" not in _turbo_auftrag(auftrag)


def test_gespann_passt_nur_bei_gleichem_modell_vae_und_detektor(tmp_path: Path):
    """passt_zu is the whole switch: a running server draws the picture only
    when model, VAE and detector all match. A stopped server never matches."""
    turbo = Bildturbo(tmp_path)
    # Nothing running — nothing matches, whatever is asked for.
    assert turbo.passt_zu("m.safetensors") is False
    # Pretend a server is up on a specific Gespann.
    turbo._prozess = _LebtImmer()
    turbo._modell = "m.safetensors"
    turbo._vae = "vae.safetensors"
    turbo._ad_modell = "face.pt"
    turbo._ad_prompt = ""
    assert turbo.passt_zu("m.safetensors", "vae.safetensors", "face.pt") is True
    # Any single mismatch falls out.
    assert turbo.passt_zu("anders.safetensors", "vae.safetensors", "face.pt") is False
    assert turbo.passt_zu("m.safetensors", None, "face.pt") is False
    assert turbo.passt_zu("m.safetensors", "vae.safetensors", None) is False
    # The detector's prompt is compared only while a detector is set.
    assert turbo.passt_zu("m.safetensors", "vae.safetensors", "face.pt", "eyes") is False
    turbo._ad_modell = None
    turbo._ad_prompt = ""
    assert turbo.passt_zu("m.safetensors", "vae.safetensors", None, "ignored") is True


def test_gespann_passt_nicht_bei_geaendertem_lora_ordner(tmp_path: Path):
    """The LoRA folder is a start flag (--lora-model-dir) — only the LoRA a
    prompt names travels per request, the folder it resolves against does
    not, so a folder change must force a restart just like the VAE does."""
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._modell = "m.safetensors"
    turbo._lora_ordner = str(tmp_path / "lora")
    assert turbo.passt_zu("m.safetensors", lora_ordner=tmp_path / "lora") is True
    assert turbo.passt_zu("m.safetensors", lora_ordner=tmp_path / "anders") is False
    assert turbo.passt_zu("m.safetensors") is False


def test_gespann_passt_nicht_bei_geaendertem_embd_ordner(tmp_path: Path):
    """Same rule as the LoRA folder, for --embd-dir."""
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._modell = "m.safetensors"
    turbo._embd_ordner = str(tmp_path / "embedding")
    assert turbo.passt_zu("m.safetensors", embd_ordner=tmp_path / "embedding") is True
    assert turbo.passt_zu("m.safetensors", embd_ordner=tmp_path / "anders") is False
    assert turbo.passt_zu("m.safetensors") is False


def test_starten_merkt_sich_lora_und_embd_ordner(tmp_path: Path, monkeypatch):
    """End to end: starten() remembers both folders, so a later passt_zu()
    against the same folders matches."""
    _sd_server_binary_anlegen(tmp_path)
    monkeypatch.setattr("subprocess.Popen", lambda befehl, **kwargs: _LebtImmer())
    turbo = Bildturbo(tmp_path)
    lora = tmp_path / "lora"
    embd = tmp_path / "embedding"

    turbo.starten(Path("/modelle/m.safetensors"), lora_ordner=lora, embd_ordner=embd)

    assert turbo._lora_ordner == str(lora)
    assert turbo._embd_ordner == str(embd)
    assert turbo.passt_zu("m.safetensors", lora_ordner=lora, embd_ordner=embd) is True


def test_starten_setzt_anwendungsmodus_nur_bei_aktivem_lora(tmp_path: Path, monkeypatch):
    """--lora-apply-mode must actually reach the real subprocess argv, and
    only when this wish has a LoRA in play (``lora_aktiv``) — the folder
    itself is always given (see starten()'s own docstring), so the mode
    flag is the one thing that must not claim a choice nobody made."""
    _sd_server_binary_anlegen(tmp_path)
    aufrufe: dict = {}

    def fake_popen(befehl, **kwargs):
        aufrufe["befehl"] = befehl
        return _LebtImmer()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    turbo = Bildturbo(tmp_path)
    lora = tmp_path / "lora"

    turbo.starten(
        Path("/modelle/m.safetensors"), lora_ordner=lora,
        lora_apply_mode="immediately", lora_aktiv=True,
    )
    befehl = aufrufe["befehl"]
    assert befehl[befehl.index("--lora-model-dir") + 1] == str(lora)
    assert befehl[befehl.index("--lora-apply-mode") + 1] == "immediately"

    turbo.starten(
        Path("/modelle/m.safetensors"), lora_ordner=lora,
        lora_apply_mode="immediately", lora_aktiv=False,
    )
    befehl = aufrufe["befehl"]
    assert "--lora-model-dir" in befehl  # the folder is still always given
    assert "--lora-apply-mode" not in befehl


def test_ohne_gesendeten_modus_merkt_sich_der_turbo_den_vorgabewert_des_binaries(
    tmp_path: Path, monkeypatch
):
    """When the flag is not sent, the server runs on the BINARY's default,
    and that is "auto" — read out of this build's own --help ("default is
    auto"), not "at_runtime".

    Remembering "at_runtime" made passt_zu() report a match for the first
    LoRA picture, so no restart happened and the LoRA was applied on a
    server running in auto — measured on this build: 0 of 834 tensors, then
    ggml_abort kills the whole server. The honest value is what makes
    passt_zu() pay the one restart it has to.
    """
    _sd_server_binary_anlegen(tmp_path)
    monkeypatch.setattr("subprocess.Popen", lambda befehl, **kwargs: _LebtImmer())
    turbo = Bildturbo(tmp_path)
    lora = tmp_path / "lora"

    turbo.starten(Path("/modelle/m.safetensors"), lora_ordner=lora, lora_aktiv=False)

    assert turbo._lora_apply_mode == "auto"
    # A picture that really has a LoRA must NOT match this server.
    assert turbo.passt_zu(
        "m.safetensors", lora_ordner=lora,
        lora_apply_mode="at_runtime", lora_aktiv=True,
    ) is False
    # A picture without one is untouched by the mode, as before.
    assert turbo.passt_zu("m.safetensors", lora_ordner=lora) is True


def test_a_lora_picture_asks_for_no_lora_list_first(tmp_path: Path, monkeypatch):
    """The server's own route refreshes its LoRA list for every job, so a
    LoRA picture goes straight in — measured on build 920: 834 of 834
    tensors applied on a server never asked for its list. Silence probe:
    nothing but the job route and the job itself is asked."""
    from app import bildturbo as bt

    server = _JobServer()
    server.install(monkeypatch, bt)
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._war_bereit = True

    turbo.zeichnen({"prompt": "x", "lora": [{"path": "a.safetensors", "multiplier": 1.0}]})
    assert [u.split("/sdcpp/v1")[1] for u in server.calls] == ["/img_gen", "/jobs/job_1"]


def test_starten_setzt_speicher_und_geraete_felder(tmp_path: Path, monkeypatch):
    """Memory & devices must reach the real subprocess argv too — RNG
    always, the rest only while actually set."""
    _sd_server_binary_anlegen(tmp_path)
    aufrufe: dict = {}

    def fake_popen(befehl, **kwargs):
        aufrufe["befehl"] = befehl
        return _LebtImmer()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    turbo = Bildturbo(tmp_path)

    turbo.starten(Path("/modelle/m.safetensors"))
    befehl = aufrufe["befehl"]
    assert befehl[befehl.index("--rng") + 1] == "cuda"
    assert "--type" not in befehl
    assert "--threads" not in befehl
    assert "--max-vram" not in befehl
    assert "--offload-to-cpu" not in befehl

    turbo.starten(
        Path("/modelle/m.safetensors"), rng="cpu", weight_type="q8_0",
        threads=8, vram_limit="6", offload_to_cpu=True,
    )
    befehl = aufrufe["befehl"]
    assert befehl[befehl.index("--rng") + 1] == "cpu"
    assert befehl[befehl.index("--type") + 1] == "q8_0"
    assert befehl[befehl.index("--threads") + 1] == "8"
    assert befehl[befehl.index("--max-vram") + 1] == "6"
    assert "--offload-to-cpu" in befehl


def test_gespann_eigenschaften_lesen_den_laufenden_stand_zurueck(tmp_path: Path, monkeypatch):
    """The window's restart pills read the running Gespann back through
    these properties — they must answer the neutral default while nothing
    runs, not the last values a stopped server happened to remember."""
    _sd_server_binary_anlegen(tmp_path)
    monkeypatch.setattr("subprocess.Popen", lambda befehl, **kwargs: _LebtImmer())
    turbo = Bildturbo(tmp_path)

    assert turbo.vae is None
    assert turbo.vae_format == ""
    assert turbo.rng == "cuda"
    assert turbo.weight_type == ""
    assert turbo.threads == -1
    assert turbo.vram_limit == ""
    assert turbo.offload_to_cpu is False
    assert turbo.ad_modell is None
    assert turbo.photomaker is None

    turbo.starten(
        Path("/modelle/m.safetensors"), vae=tmp_path / "v.safetensors",
        ad_modell=tmp_path / "face.pt",
        photomaker=tmp_path / "woman.safetensors", gesichter_ordner=tmp_path,
        rng="cpu", weight_type="q8_0", threads=8, vram_limit="6",
        offload_to_cpu=True,
    )
    assert turbo.vae == "v.safetensors"
    assert turbo.vae_format == ""
    assert turbo.rng == "cpu"
    assert turbo.weight_type == "q8_0"
    assert turbo.threads == 8
    assert turbo.vram_limit == "6"
    assert turbo.offload_to_cpu is True
    assert turbo.ad_modell == "face.pt"
    assert turbo.photomaker == "woman.safetensors"

    # The case a clean stop does NOT exercise: the process dies on its own
    # (crash, killed from outside) without stoppen() ever running, so the
    # private fields are never reset — only the properties' own
    # `if self.laeuft() else …` guard stands between the window and the
    # stale values of a server that no longer exists. Removing that guard
    # leaves this exact assertion green under a clean stop (stoppen()
    # already resets the fields itself) but red here.
    turbo._prozess = _Gestorben()
    assert turbo.laeuft() is False
    assert turbo.vae is None
    assert turbo.vae_format == ""
    assert turbo.rng == "cuda"
    assert turbo.weight_type == ""
    assert turbo.threads == -1
    assert turbo.vram_limit == ""
    assert turbo.offload_to_cpu is False
    assert turbo.ad_modell is None
    assert turbo.photomaker is None

    # And the ordinary clean-stop path still resets the fields directly.
    turbo._prozess = _LebtImmer()
    turbo.stoppen()
    assert turbo.vae is None
    assert turbo.rng == "cuda"
    assert turbo.threads == -1


def test_gespann_passt_nicht_bei_geaenderten_speicher_und_geraete_feldern(tmp_path: Path):
    """A change to any Memory & devices field forces a restart, same rule
    as VAE/detector/PhotoMaker — they are all start flags."""
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._modell = "m.safetensors"
    turbo._rng = "cuda"
    turbo._weight_type = "q8_0"
    turbo._threads = 8
    turbo._vram_limit = "6"
    turbo._offload_to_cpu = True
    assert turbo.passt_zu(
        "m.safetensors", rng="cuda", weight_type="q8_0", threads=8,
        vram_limit="6", offload_to_cpu=True,
    ) is True
    assert turbo.passt_zu("m.safetensors", rng="cpu") is False
    assert turbo.passt_zu(
        "m.safetensors", rng="cuda", weight_type="f16", threads=8,
        vram_limit="6", offload_to_cpu=True,
    ) is False
    assert turbo.passt_zu(
        "m.safetensors", rng="cuda", weight_type="q8_0", threads=4,
        vram_limit="6", offload_to_cpu=True,
    ) is False
    assert turbo.passt_zu(
        "m.safetensors", rng="cuda", weight_type="q8_0", threads=8,
        vram_limit="8", offload_to_cpu=True,
    ) is False
    assert turbo.passt_zu(
        "m.safetensors", rng="cuda", weight_type="q8_0", threads=8,
        vram_limit="6", offload_to_cpu=False,
    ) is False


def test_gespann_passt_nicht_bei_geaendertem_anwendungsmodus(tmp_path: Path):
    """The apply mode is a start flag too (bound to the running server), so a
    request naming a different one of the free three values must force a
    restart — but only while THIS wish actually has a LoRA or a face in
    play (``lora_aktiv``), matching the sd-cli path's own condition for
    sending --lora-apply-mode at all. The folder itself is always set on
    this server (see bildturbo.starten()'s own docstring), so gating on the
    folder's mere presence — as passt_zu() once did — forced a restart for
    every mode change even when no LoRA was ever selected."""
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._modell = "m.safetensors"
    turbo._lora_ordner = str(tmp_path / "lora")
    turbo._lora_apply_mode = "at_runtime"
    assert turbo.passt_zu(
        "m.safetensors", lora_ordner=tmp_path / "lora",
        lora_apply_mode="at_runtime", lora_aktiv=True,
    ) is True
    assert turbo.passt_zu(
        "m.safetensors", lora_ordner=tmp_path / "lora",
        lora_apply_mode="immediately", lora_aktiv=True,
    ) is False
    # The folder is set (as it always is on this server) but THIS wish has
    # no LoRA or face active — the mode cannot matter to it, so a mismatch
    # must not force a restart nothing would use.
    assert turbo.passt_zu(
        "m.safetensors", lora_ordner=tmp_path / "lora",
        lora_apply_mode="immediately", lora_aktiv=False,
    ) is True
    # No LoRA folder at all either — the mode cannot matter regardless.
    turbo._lora_ordner = None
    assert turbo.passt_zu("m.safetensors", lora_apply_mode="immediately") is True


def test_gespann_passt_nicht_bei_geaendertem_diffusion_model(tmp_path: Path):
    """--diffusion-model is a start flag, the same rule as -m: a different
    Bausatz model means a different server."""
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._modell = "m.safetensors"
    turbo._diffusion_model = "flux1-dev.gguf"
    assert turbo.passt_zu("m.safetensors", diffusion_model="flux1-dev.gguf") is True
    assert turbo.passt_zu("m.safetensors", diffusion_model="anders.gguf") is False
    assert turbo.passt_zu("m.safetensors") is False


def test_gespann_passt_nicht_bei_geaendertem_t5xxl(tmp_path: Path):
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._modell = "m.safetensors"
    turbo._t5xxl = "t5xxl.gguf"
    assert turbo.passt_zu("m.safetensors", t5xxl="t5xxl.gguf") is True
    assert turbo.passt_zu("m.safetensors", t5xxl="anders.gguf") is False
    assert turbo.passt_zu("m.safetensors") is False


def test_gespann_passt_nicht_bei_geaendertem_clip_l(tmp_path: Path):
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._modell = "m.safetensors"
    turbo._clip_l = "clip_l.safetensors"
    assert turbo.passt_zu("m.safetensors", clip_l="clip_l.safetensors") is True
    assert turbo.passt_zu("m.safetensors", clip_l="anders.safetensors") is False
    assert turbo.passt_zu("m.safetensors") is False


def test_gespann_passt_nicht_bei_geaendertem_clip_g(tmp_path: Path):
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._modell = "m.safetensors"
    turbo._clip_g = "clip_g.safetensors"
    assert turbo.passt_zu("m.safetensors", clip_g="clip_g.safetensors") is True
    assert turbo.passt_zu("m.safetensors", clip_g="anders.safetensors") is False
    assert turbo.passt_zu("m.safetensors") is False


def test_gespann_passt_nicht_bei_geaendertem_llm(tmp_path: Path):
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._modell = "m.safetensors"
    turbo._llm = "llm.gguf"
    assert turbo.passt_zu("m.safetensors", llm="llm.gguf") is True
    assert turbo.passt_zu("m.safetensors", llm="anders.gguf") is False
    assert turbo.passt_zu("m.safetensors") is False


def test_gespann_passt_nicht_bei_geaendertem_vae_format(tmp_path: Path):
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._modell = "m.safetensors"
    turbo._vae_format = "flux"
    assert turbo.passt_zu("m.safetensors", vae_format="flux") is True
    assert turbo.passt_zu("m.safetensors", vae_format="sd3") is False
    assert turbo.passt_zu("m.safetensors") is False


def test_starten_merkt_sich_die_bausatz_felder(tmp_path: Path, monkeypatch):
    """End to end: starten() remembers every field it was started with, so
    a later passt_zu() against the same values matches — checked once per
    family shape, since t5xxl/clip_l (flux) and llm (zimage/flux2) never
    belong to the same Gespann."""
    _sd_server_binary_anlegen(tmp_path)
    monkeypatch.setattr("subprocess.Popen", lambda befehl, **kwargs: _LebtImmer())
    turbo = Bildturbo(tmp_path)

    turbo.starten(
        Path("/modelle/m.safetensors"),
        familie="flux",
        diffusion_model=Path("/modelle/flux1-dev.gguf"),
        t5xxl=Path("/textversteher/t5xxl.gguf"),
        clip_l=Path("/textversteher/clip_l.safetensors"),
        clip_g=Path("/textversteher/clip_g.safetensors"),
        vae_format="flux",
    )

    assert turbo._diffusion_model == "flux1-dev.gguf"
    assert turbo._t5xxl == "t5xxl.gguf"
    assert turbo._clip_l == "clip_l.safetensors"
    assert turbo._clip_g == "clip_g.safetensors"
    assert turbo._vae_format == "flux"
    assert turbo.passt_zu(
        "m.safetensors", diffusion_model="flux1-dev.gguf", t5xxl="t5xxl.gguf",
        clip_l="clip_l.safetensors", clip_g="clip_g.safetensors", vae_format="flux",
    ) is True

    turbo.starten(
        Path("/modelle/m.safetensors"),
        familie="zimage",
        diffusion_model=Path("/modelle/zimage.gguf"),
        llm=Path("/textversteher/llm.gguf"),
    )

    assert turbo._llm == "llm.gguf"
    assert turbo.passt_zu(
        "m.safetensors", diffusion_model="zimage.gguf", llm="llm.gguf",
    ) is True


def test_starten_ohne_familie_wird_nicht_still_gebaut(tmp_path: Path, monkeypatch):
    """starten() is not only reached through the API's own familie_pruefen()
    check — a caller that skips familie must not silently lose its text
    encoders, and the server must never come up half-started."""
    _sd_server_binary_anlegen(tmp_path)
    monkeypatch.setattr("subprocess.Popen", lambda befehl, **kwargs: _LebtImmer())
    turbo = Bildturbo(tmp_path)

    with pytest.raises(BildturboFehler):
        turbo.starten(
            Path("/modelle/m.safetensors"),
            diffusion_model=Path("/modelle/flux1-dev.gguf"),
            t5xxl=Path("/textversteher/t5xxl.gguf"),
            clip_l=Path("/textversteher/clip_l.safetensors"),
        )


def test_starten_baut_bausatz_befehl_ueber_das_modul(tmp_path: Path, monkeypatch):
    _sd_server_binary_anlegen(tmp_path)
    aufrufe: dict = {}

    def fake_popen(befehl, **kwargs):
        aufrufe["befehl"] = befehl
        return _LebtImmer()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    turbo = Bildturbo(tmp_path)

    turbo.starten(
        Path("/modelle/m.safetensors"),
        familie="flux",
        diffusion_model=Path("/modelle/flux1-dev.gguf"),
        t5xxl=Path("/textversteher/t5xxl.gguf"),
        clip_l=Path("/textversteher/clip_l.safetensors"),
    )

    befehl = aufrufe["befehl"]
    assert "-m" not in befehl
    assert befehl[befehl.index("--diffusion-model") + 1] == str(Path("/modelle/flux1-dev.gguf"))
    assert befehl[befehl.index("--t5xxl") + 1] == str(Path("/textversteher/t5xxl.gguf"))
    assert befehl[befehl.index("--clip_l") + 1] == str(Path("/textversteher/clip_l.safetensors"))


def test_starten_ohne_bausatz_baut_weiter_m(tmp_path: Path, monkeypatch):
    """No diffusion_model set — byte-identical to before this step."""
    _sd_server_binary_anlegen(tmp_path)
    aufrufe: dict = {}
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda befehl, **kwargs: (aufrufe.__setitem__("befehl", befehl), _LebtImmer())[1],
    )
    turbo = Bildturbo(tmp_path)

    turbo.starten(Path("/modelle/m.safetensors"))

    assert aufrufe["befehl"][1:3] == ["-m", str(Path("/modelle/m.safetensors"))]
    assert "--diffusion-model" not in aufrufe["befehl"]


def test_vae_format_erreicht_die_argv_auch_ohne_bausatz(tmp_path: Path, monkeypatch):
    """J2: `vae_format` only ever became a flag through
    `bildbausatz.schalter()`, which a simple model (no `diffusion_model`)
    never calls — the wish was remembered (`self._vae_format`) and
    reported back by `/bild/turbo` as set, while sd-cli itself never saw
    it and the restart bought nothing."""
    _sd_server_binary_anlegen(tmp_path)
    aufrufe: dict = {}
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda befehl, **kwargs: (aufrufe.__setitem__("befehl", befehl), _LebtImmer())[1],
    )
    turbo = Bildturbo(tmp_path)

    turbo.starten(Path("/modelle/m.safetensors"), vae_format="gguf")

    befehl = aufrufe["befehl"]
    assert befehl[befehl.index("--vae-format") + 1] == "gguf"


def test_split_mode_und_backend_erreichen_die_argv(tmp_path: Path, monkeypatch):
    """L1: left empty, neither flag goes out at all — sd-cli's own
    default stays untouched, same shape as threads/vram_limit."""
    _sd_server_binary_anlegen(tmp_path)
    aufrufe: dict = {}
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda befehl, **kwargs: (aufrufe.__setitem__("befehl", befehl), _LebtImmer())[1],
    )
    turbo = Bildturbo(tmp_path)

    turbo.starten(
        Path("/modelle/m.safetensors"),
        split_mode="row", backend="clip=cpu,vae=cuda0,diffusion=vulkan0",
    )

    befehl = aufrufe["befehl"]
    assert befehl[befehl.index("--split-mode") + 1] == "row"
    assert befehl[befehl.index("--backend") + 1] == "clip=cpu,vae=cuda0,diffusion=vulkan0"


def test_the_controlnet_is_a_start_value(tmp_path: Path, monkeypatch):
    """The ControlNet model binds the server at start like the VAE; only its
    guide picture travels per job. A different one means a fresh server."""
    _sd_server_binary_anlegen(tmp_path)
    calls_seen: dict = {}
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda command, **kwargs: (calls_seen.__setitem__("command", command), _LebtImmer())[1],
    )
    turbo = Bildturbo(tmp_path)
    turbo.starten(Path("/modelle/m.safetensors"), control_net=Path("/c/canny.safetensors"))

    command = calls_seen["command"]
    assert command[command.index("--control-net") + 1] == str(Path("/c/canny.safetensors"))
    assert turbo.passt_zu("m.safetensors", control_net="canny.safetensors")
    assert not turbo.passt_zu("m.safetensors", control_net="depth.safetensors")
    assert not turbo.passt_zu("m.safetensors")


def test_split_mode_und_backend_leer_lassen_schickt_keine_flagge(tmp_path: Path, monkeypatch):
    _sd_server_binary_anlegen(tmp_path)
    aufrufe: dict = {}
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda befehl, **kwargs: (aufrufe.__setitem__("befehl", befehl), _LebtImmer())[1],
    )
    turbo = Bildturbo(tmp_path)

    turbo.starten(Path("/modelle/m.safetensors"))

    befehl = aufrufe["befehl"]
    assert "--split-mode" not in befehl
    assert "--backend" not in befehl


def test_passt_zu_sieht_einen_geaenderten_split_mode_oder_backend(
    tmp_path: Path, monkeypatch
):
    _sd_server_binary_anlegen(tmp_path)
    monkeypatch.setattr("subprocess.Popen", lambda befehl, **kwargs: _LebtImmer())
    turbo = Bildturbo(tmp_path)
    turbo.starten(Path("/modelle/m.safetensors"), split_mode="row", backend="cpu")

    assert turbo.passt_zu("m.safetensors", split_mode="row", backend="cpu")
    assert not turbo.passt_zu("m.safetensors", split_mode="layer", backend="cpu")
    assert not turbo.passt_zu("m.safetensors", split_mode="row", backend="cuda0")


def test_turbo_vae_bleibt_ein_einzelner_schalter_auch_bei_einem_bausatz(
    tmp_path: Path, monkeypatch
):
    """bildbausatz.schalter() can add --vae itself, but this integration
    must not duplicate the flag the command already carries for every
    model — the existing unconditional --vae line stays untouched."""
    _sd_server_binary_anlegen(tmp_path)
    aufrufe: dict = {}
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda befehl, **kwargs: (aufrufe.__setitem__("befehl", befehl), _LebtImmer())[1],
    )
    turbo = Bildturbo(tmp_path)

    turbo.starten(
        Path("/modelle/m.safetensors"), vae=Path("/vae/ae.safetensors"),
        familie="flux", diffusion_model=Path("/modelle/flux1-dev.gguf"),
    )

    assert aufrufe["befehl"].count("--vae") == 1


def test_beide_wege_bauen_dieselben_schalter_fuer_dieselbe_familie(
    tmp_path: Path, monkeypatch
):
    """Both paths now read the family from the same explicit value instead
    of guessing it back from which fields are set — this checks they still
    agree on the switches for a given family. Two shapes: a flux Gespann
    (t5xxl+clip_l) and a zimage-shaped one (llm only)."""
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/irgendwo/sd-cli")
    _sd_server_binary_anlegen(tmp_path)

    for familie, t5xxl, clip_l, llm in (
        ("flux", tmp_path / "t5xxl.gguf", tmp_path / "clip_l.safetensors", None),
        ("zimage", None, None, tmp_path / "llm.gguf"),
    ):
        befehl_sd_cli = Bildrunner(tmp_path).befehl(
            Auftrag(
                modell=tmp_path / "klein.gguf", prompt="x", familie=familie,
                diffusion_model=tmp_path / "flux1-dev.gguf",
                t5xxl=t5xxl, clip_l=clip_l, llm=llm,
            ),
            tmp_path / "a.png",
        )

        aufrufe: dict = {}
        monkeypatch.setattr(
            "subprocess.Popen",
            lambda befehl, **kwargs: (aufrufe.__setitem__("befehl", befehl), _LebtImmer())[1],
        )
        Bildturbo(tmp_path).starten(
            Path("/modelle/klein.gguf"), familie=familie,
            diffusion_model=Path("/modelle/flux1-dev.gguf"),
            t5xxl=t5xxl, clip_l=clip_l, llm=llm,
        )
        befehl_turbo = aufrufe["befehl"]

        for schalter in ("--t5xxl", "--clip_l", "--llm"):
            assert (schalter in befehl_sd_cli) == (schalter in befehl_turbo), (
                familie, schalter
            )


def test_gespann_passt_nicht_bei_geaendertem_gesicht(tmp_path: Path):
    """PhotoMaker is a start flag too — a changed model
    or fingerprint means a different server, the same way a VAE change
    does."""
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._modell = "m.safetensors"
    turbo._photomaker = "photomaker-v1.safetensors"
    turbo._gesichter_fingerabdruck = "abc123"
    assert turbo.passt_zu(
        "m.safetensors", photomaker="photomaker-v1.safetensors",
        gesichter_fingerabdruck="abc123",
    ) is True
    # Turning it off, turning it on for the first time, or swapping either
    # half of the pair all count as a mismatch.
    assert turbo.passt_zu("m.safetensors") is False
    assert turbo.passt_zu(
        "m.safetensors", photomaker="anders.safetensors",
        gesichter_fingerabdruck="abc123",
    ) is False
    assert turbo.passt_zu(
        "m.safetensors", photomaker="photomaker-v1.safetensors",
        gesichter_fingerabdruck="anders",
    ) is False


def test_ausgetauschte_fotos_im_selben_ordner_gelten_als_anderes_gesicht(tmp_path: Path):
    """A photo swap must count as another face: the folder is always named
    "gesichter" (app.bildwahlen.GESICHTER_ORDNER) — comparing it by name
    can never notice a photo swap. Real files, the real fingerabdruck()."""
    ordner = tmp_path / "gesichter"
    ordner.mkdir()
    (ordner / "eins.jpg").write_bytes(b"first one")
    vorher = fingerabdruck(ordner)

    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._modell = "m.safetensors"
    turbo._photomaker = "pm.safetensors"
    turbo._gesichter_fingerabdruck = vorher
    assert turbo.passt_zu(
        "m.safetensors", photomaker="pm.safetensors", gesichter_fingerabdruck=vorher
    ) is True

    # Same folder, same name — the photos inside are somebody else's now.
    (ordner / "eins.jpg").unlink()
    (ordner / "zwei.jpg").write_bytes(b"jemand anderes")
    nachher = fingerabdruck(ordner)

    assert nachher != vorher
    assert turbo.passt_zu(
        "m.safetensors", photomaker="pm.safetensors", gesichter_fingerabdruck=nachher
    ) is False


def test_starten_haengt_photomaker_und_gesichterordner_an(tmp_path: Path, monkeypatch):
    """photomaker and gesichter_ordner reach the start command — the
    actual sd-server flags, --photo-maker and --pm-id-images-dir (verified
    against the running build, not per-request body fields — see
    app/api/v1/bild.py's _turbo_auftrag)."""
    _sd_server_binary_anlegen(tmp_path)
    gesichter = tmp_path / "gesichter"
    gesichter.mkdir()
    (gesichter / "eins.jpg").write_bytes(b"first one")
    aufrufe: dict = {}

    def fake_popen(befehl, **kwargs):
        aufrufe["befehl"] = befehl
        return _LebtImmer(pid=4321)

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    turbo = Bildturbo(tmp_path)

    turbo.starten(
        Path("/modelle/m.safetensors"),
        photomaker=Path("/photomaker/pm.safetensors"),
        gesichter_ordner=gesichter,
    )

    befehl = aufrufe["befehl"]
    assert "--photo-maker" in befehl
    assert befehl[befehl.index("--photo-maker") + 1] == str(Path("/photomaker/pm.safetensors"))
    assert "--pm-id-images-dir" in befehl
    assert befehl[befehl.index("--pm-id-images-dir") + 1] == str(gesichter)
    assert turbo._photomaker == "pm.safetensors"
    assert turbo._gesichter_fingerabdruck == fingerabdruck(gesichter)


def test_starten_ohne_gesicht_setzt_keine_photomaker_flags(tmp_path: Path, monkeypatch):
    """Half of the pair is nothing at all — same rule as app/bildrunner.py's
    sd-cli path (``if auftrag.photomaker is not None and auftrag.gesichter_ordner
    is not None``)."""
    _sd_server_binary_anlegen(tmp_path)
    aufrufe: dict = {}
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda befehl, **kwargs: (aufrufe.__setitem__("befehl", befehl), _LebtImmer())[1],
    )
    turbo = Bildturbo(tmp_path)

    turbo.starten(Path("/modelle/m.safetensors"), photomaker=Path("/photomaker/pm.safetensors"))

    assert "--photo-maker" not in aufrufe["befehl"]
    assert "--pm-id-images-dir" not in aufrufe["befehl"]
    assert turbo._photomaker is None


def _sd_server_binary_anlegen(datenordner: Path) -> None:
    build = datenordner / "stable-diffusion.cpp" / "master-1"
    build.mkdir(parents=True)
    prog = build / PROGRAMM
    prog.write_text("#!/bin/sh\n")
    prog.chmod(0o755)


class _LebtImmer:
    """A stand-in process that always reports as running. ``pid`` and
    ``stdout`` only matter for a test that goes through ``starten()`` —
    it spawns a real reader thread against them; an empty read is an
    immediate, clean EOF for that thread."""

    def __init__(self, pid: int = 1234):
        self.pid = pid
        self.stdout = _LeererStdout()
        self.args: list[str] = []

    def poll(self):
        return None

    # The Windows path of the stop runs ``taskkill`` through subprocess.run,
    # which builds its process with the patched ``Popen`` — so this stand-in
    # is also what ``run`` gets back there, and it answers as a finished
    # process does: its command, an empty output, a kill that does nothing
    # (measured: "'_LebtImmer' object has no attribute 'kill'").
    def communicate(self, *_args, **_kwargs):
        return (b"", b"")

    def kill(self):
        pass

    def terminate(self):
        pass

    # The Windows path of the stop uses the process as a context manager
    # (measured: "does not support the context manager protocol").
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _Gestorben:
    """A stand-in process that has already exited on its own — a crash, or
    something outside the program killing it — as opposed to stoppen()
    ever having run. The one case where the Gespann properties' own
    ``if self.laeuft() else …`` guard is the only thing standing between a
    caller and the stale fields of a server that no longer exists."""

    def poll(self):
        return 1


class _LeererStdout:
    def read1(self, groesse: int) -> bytes:
        return b""


def test_abbrechen_nur_beim_zeichnen(tmp_path: Path, monkeypatch):
    """A stop with nothing drawing tears down nothing; while drawing it ends
    the server and marks the draw as a silent abort, not a failure."""
    from app import bildturbo as bt
    from app.bildturbo import Bildturbo

    # Never touch a real process in the test — record that the end was asked
    # for instead of sending a signal.
    beendet = []
    monkeypatch.setattr(bt.prozessstopp, "beenden", lambda p, frist=5.0: beendet.append(p))

    turbo = Bildturbo(tmp_path)
    # Idle: nothing to break off.
    assert turbo.abbrechen() is False
    assert turbo._abgebrochen is False

    # Pretend a draw is being handed in on a running server: no job id yet.
    turbo._prozess = _LebtImmer()
    turbo._zeichnet = True
    assert turbo.abbrechen() is True
    # The draw will report an abort, not a failure, and cancels its job the
    # moment the id comes back — the server is not ended for it.
    assert turbo._abgebrochen is True
    assert beendet == []


def test_a_stop_while_handing_in_cancels_the_job_once_it_exists(
    tmp_path: Path, monkeypatch
):
    """A stop pressed while img_gen is still answering: the draw sees the
    stop when the job id arrives and cancels that job; the server stays."""
    from app import bildturbo as bt

    ended = []
    monkeypatch.setattr(bt.prozessstopp, "beenden", lambda p, frist=5.0: ended.append(p))
    turbo = Bildturbo(tmp_path)
    server = _JobServer(status="cancelled", on_submit=lambda: turbo.abbrechen())
    server.install(monkeypatch, bt)
    turbo._prozess = _LebtImmer()
    turbo._war_bereit = True

    with pytest.raises(BildturboFehler) as error:
        turbo.zeichnen({"prompt": "x"})
    assert error.value.grund == "bild.abgebrochen"
    assert any(u.endswith("/jobs/job_1/cancel") for u in server.calls)
    assert ended == []


def test_the_wait_for_the_server_ends_at_once_for_a_stopped_picture(tmp_path: Path, monkeypatch):
    """The server still starts and the picture it starts for is stopped: the
    wait gives up without waiting out its deadline, and the server is not
    ended for it."""
    from app import bildturbo as bt

    ended = []
    monkeypatch.setattr(bt.prozessstopp, "beenden", lambda p, frist=5.0: ended.append(p))
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    monkeypatch.setattr(turbo, "_bereit", lambda: False)
    began = bt.time.monotonic()
    assert turbo.bereit_abwarten(600.0, stopped=lambda: True) is False
    assert bt.time.monotonic() - began < 5
    assert ended == [] and turbo.laeuft()
    # Silence probe: a wait nobody stopped answers as before.
    monkeypatch.setattr(turbo, "_bereit", lambda: True)
    assert turbo.bereit_abwarten(600.0, stopped=lambda: False) is True


def test_a_picture_stopped_while_the_server_starts_is_never_handed_in(tmp_path: Path, monkeypatch):
    """The draw's own wait for a server that has not answered yet: stopped
    there, the picture is a silent stop and nothing is posted."""
    from app import bildturbo as bt

    server = _JobServer()
    server.install(monkeypatch, bt)
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    monkeypatch.setattr(turbo, "_bereit", lambda: False)
    with pytest.raises(BildturboFehler) as error:
        turbo.zeichnen({"prompt": "x"}, stopped=lambda: True)
    assert error.value.grund == "bild.abgebrochen"
    assert server.calls == []
    assert turbo._zeichnet is False


def test_a_stop_asked_as_the_draw_takes_over_is_never_handed_in(tmp_path: Path, monkeypatch):
    """The server answers already and the stop was asked in the moment
    before the draw began: nothing is posted and nothing has to be
    cancelled."""
    from app import bildturbo as bt

    turbo = Bildturbo(tmp_path)
    server = _JobServer()
    server.install(monkeypatch, bt)
    turbo._prozess = _LebtImmer()
    turbo._war_bereit = True
    with pytest.raises(BildturboFehler) as error:
        turbo.zeichnen({"prompt": "x"}, stopped=lambda: True)
    assert error.value.grund == "bild.abgebrochen"
    assert server.calls == []
    assert turbo._zeichnet is False


def test_a_stop_that_falls_into_the_takeover_is_taken_up_by_the_draw(tmp_path: Path, monkeypatch):
    """Asked after the draw's last look and before its own flag stood: the
    draw finds it at its next look for the job's state and cancels the job
    like any stop of a running draw — the server stays."""
    from app import bildturbo as bt

    ended = []
    monkeypatch.setattr(bt.prozessstopp, "beenden", lambda p, frist=5.0: ended.append(p))
    monkeypatch.setattr(bt.time, "sleep", lambda s: None)
    turbo = Bildturbo(tmp_path)
    server = _JobServer(before=["generating"], status="cancelled")
    server.install(monkeypatch, bt)
    turbo._prozess = _LebtImmer()
    turbo._war_bereit = True
    # Not stopped while the draw takes over, stopped from then on.
    looks = iter([False])
    with pytest.raises(BildturboFehler) as error:
        turbo.zeichnen({"prompt": "x"}, stopped=lambda: next(looks, True))
    assert error.value.grund == "bild.abgebrochen"
    assert any(u.endswith("/jobs/job_1/cancel") for u in server.calls)
    assert ended == []


def test_the_job_is_ended_after_the_deadline(tmp_path: Path, monkeypatch):
    """The same fifteen minutes the sd-cli path allows; after them the job
    is ended, so nothing keeps drawing for nobody."""
    from app import bildturbo as bt

    server = _JobServer(before=["generating"] * 3)
    server.install(monkeypatch, bt)
    monkeypatch.setattr(bt.time, "sleep", lambda s: None)
    monkeypatch.setattr(bt, "ZEICHENFRIST", -1.0)
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._war_bereit = True

    with pytest.raises(BildturboFehler) as error:
        turbo.zeichnen({"prompt": "x"})
    assert error.value.grund == "bild.gescheitert"
    assert any(u.endswith("/jobs/job_1/cancel") for u in server.calls)


def test_an_unknown_end_status_does_not_wait_out_the_deadline(tmp_path: Path, monkeypatch):
    from app import bildturbo as bt

    server = _JobServer(status="canceled")
    server.install(monkeypatch, bt)
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._war_bereit = True

    with pytest.raises(BildturboFehler) as error:
        turbo.zeichnen({"prompt": "x"})
    assert error.value.protokoll == "canceled"
    assert len([u for u in server.calls if "/jobs/" in u]) == 1


# --- The extras that used to force the slow path -----------------------------


def test_startbild_und_maske_reisen_als_base64(tmp_path: Path):
    """A starting picture and its mask travel in the body, base64, with the
    strength beside them, in the fields of the server's own route."""
    import base64

    start = tmp_path / "start.png"
    start.write_bytes(b"START-BYTES")
    maske = tmp_path / "maske.png"
    maske.write_bytes(b"MASKE-BYTES")

    auftrag = Auftrag(
        modell=Path("/m.safetensors"), prompt="x",
        startbild=start, maske=maske, staerke=0.42,
    )
    body = _turbo_auftrag(auftrag)
    assert body["init_image"] == base64.b64encode(b"START-BYTES").decode()
    assert body["mask_image"] == base64.b64encode(b"MASKE-BYTES").decode()
    assert body["strength"] == 0.42


def test_ohne_startbild_keine_staerke_und_keine_maske(tmp_path: Path):
    """No starting picture, no strength — a denoising figure without a picture
    to act on would be a number about nothing."""
    auftrag = Auftrag(modell=Path("/m.safetensors"), prompt="x", staerke=0.5)
    body = _turbo_auftrag(auftrag)
    assert "init_image" not in body
    assert "strength" not in body
    assert "mask_image" not in body


def test_hires_und_clipskip_reisen_mit():
    auftrag = Auftrag(
        modell=Path("/m.safetensors"), prompt="x",
        hires=True, hires_scale=2.0, clip_skip=2,
    )
    body = _turbo_auftrag(auftrag)
    assert body["hires"] == {"enabled": True, "scale": 2.0}
    assert body["clip_skip"] == 2


def test_ohne_hires_und_ohne_clipskip_steht_nichts_im_body():
    auftrag = Auftrag(modell=Path("/m.safetensors"), prompt="x", clip_skip=-1)
    body = _turbo_auftrag(auftrag)
    assert "hires" not in body
    assert "clip_skip" not in body


def test_clip_skip_1_reist_in_den_body():
    """Same rule as the sd-cli path: 1 is a value the window offers, so it
    has to arrive. Only auto (-1) leaves the key out entirely."""
    auftrag = Auftrag(modell=Path("/m.safetensors"), prompt="x", clip_skip=1)
    body = _turbo_auftrag(auftrag)
    assert body["clip_skip"] == 1


def test_hires_kachel_1_5_x_traegt_die_richtige_basisgroesse_im_turbo_body():
    """The hires tiles' other draw path: Image-Turbo takes the same base
    size and scale as the cold sd-cli run, not a precomputed target --
    832x1216 at 1.5x is 1248x1824, computed by whatever reads the scale
    and width/height together, same as the cold path."""
    auftrag = Auftrag(
        modell=Path("/m.safetensors"), prompt="x", breite=832, hoehe=1216,
        hires=True, hires_scale=1.5,
    )
    body = _turbo_auftrag(auftrag)
    assert body["width"] == 832
    assert body["height"] == 1216
    assert body["hires"]["scale"] == 1.5
    assert 832 * 1.5 == 1248 and 1216 * 1.5 == 1824.0


def test_hires_steps_reist_im_turbo_body_mit():
    auftrag = Auftrag(
        modell=Path("/m.safetensors"), prompt="x",
        hires=True, hires_scale=2.0, hires_steps=8,
    )
    body = _turbo_auftrag(auftrag)
    assert body["hires"]["steps"] == 8


def test_hires_ohne_hires_steps_traegt_keinen_schluessel():
    auftrag = Auftrag(modell=Path("/m.safetensors"), prompt="x", hires=True, hires_scale=2.0)
    body = _turbo_auftrag(auftrag)
    assert "steps" not in body["hires"]


def test_the_passes_count_what_the_turbo_really_paints():
    """The bar plans the passes this server really draws — the base one and
    highres. A detector set adds none: the pinned build's server ignores
    it."""
    from app.api.v1.bild import _erwartete_paesse

    schlicht = Auftrag(modell=Path("/m.safetensors"), prompt="x")
    assert _erwartete_paesse(schlicht) == 1

    mit_hires = Auftrag(modell=Path("/m.safetensors"), prompt="x", hires=True)
    assert _erwartete_paesse(mit_hires) == 2

    nur_detektor = Auftrag(
        modell=Path("/m.safetensors"), prompt="x",
        ad_modell=Path("/face.safetensors"),
    )
    assert _erwartete_paesse(nur_detektor) == 1

    mit_beidem = Auftrag(
        modell=Path("/m.safetensors"), prompt="x",
        hires=True, ad_modell=Path("/face.safetensors"),
    )
    assert _erwartete_paesse(mit_beidem) == 2


def test_ohne_zahl_vom_aufrufer_plant_der_turbo_einen_pass(tmp_path: Path, monkeypatch):
    """The module's own fallback counts the detector just as little as the
    caller does. A running server with a detector loaded and a caller that
    names no number still plans exactly one pass."""
    import app.bildturbo as bt

    turbo = Bildturbo(tmp_path)
    server = _JobServer(on_submit=lambda: gesehen.update(turbo._zaehl or {}))
    gesehen: dict = {}
    server.install(monkeypatch, bt)
    turbo._prozess = _LebtImmer()
    turbo._war_bereit = True
    turbo._ad_modell = "face.safetensors"

    turbo.zeichnen({"prompt": "x", "sample_params": {"sample_steps": 8}})
    assert gesehen["paesse"] == 1


def test_every_picture_goes_over_img_gen_and_never_to_sdapi(tmp_path: Path, monkeypatch):
    """One entrance for every picture, a starting picture included: the
    server's own route. Silence probe: nothing is ever sent to the A1111
    routes, and the module's source names none of them."""
    import app.bildturbo as bt

    server = _JobServer()
    server.install(monkeypatch, bt)
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._war_bereit = True

    assert turbo.zeichnen({"prompt": "x", "init_image": "QUJD", "strength": 0.5}) == b"PNG"
    assert turbo.zeichnen({"prompt": "x"}) == b"PNG"

    handed_in = [u for u in server.calls if u.endswith("/img_gen")]
    assert len(handed_in) == 2
    assert all("/sdcpp/v1/" in u for u in server.calls)
    assert "/sdapi/" not in Path(bt.__file__).read_text(encoding="utf-8")


def test_die_paesse_kommen_vom_aufrufer(tmp_path: Path, monkeypatch):
    """The caller knows about highres; the module only takes the number."""
    import app.bildturbo as bt

    turbo = Bildturbo(tmp_path)
    gesehen: dict = {}
    # The counting stands while the job is handed in.
    server = _JobServer(on_submit=lambda: gesehen.update(turbo._zaehl or {}))
    server.install(monkeypatch, bt)
    turbo._prozess = _LebtImmer()
    turbo._war_bereit = True

    turbo.zeichnen({"prompt": "x", "sample_params": {"sample_steps": 8}}, paesse=3)
    assert gesehen["paesse"] == 3


def test_maske_ohne_startbild_erreicht_den_body_nicht(tmp_path: Path):
    """The old rule stands: a mask without a picture to mask has nothing to
    act on, and the endpoint drops it before the body is built."""
    maske = tmp_path / "m.png"
    maske.write_bytes(b"MASKE")
    auftrag = Auftrag(modell=Path("/m.safetensors"), prompt="x", maske=maske)
    body = _turbo_auftrag(auftrag)
    assert "mask_image" not in body


# --- Auftrag B: the restart-bound refinement fields on the turbo path -------


def test_starten_setzt_ad_negativ_schwelle_und_prediction(tmp_path: Path, monkeypatch):
    """--ad-negative-prompt, --extra-ad-args confidence= and --prediction
    must reach the real subprocess argv — they are start flags, exactly
    like the detailer's own prompt."""
    _sd_server_binary_anlegen(tmp_path)
    aufrufe: dict = {}

    def fake_popen(befehl, **kwargs):
        aufrufe["befehl"] = befehl
        return _LebtImmer()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    turbo = Bildturbo(tmp_path)

    turbo.starten(
        Path("/modelle/m.safetensors"), ad_modell=Path("/y/face.pt"),
        ad_negativ="blurry", ad_confidence=0.4, prediction="flux_flow",
    )
    befehl = aufrufe["befehl"]
    assert befehl[befehl.index("--ad-negative-prompt") + 1] == "blurry"
    assert befehl[befehl.index("--extra-ad-args") + 1] == "confidence=0.4"
    assert befehl[befehl.index("--prediction") + 1] == "flux_flow"
    assert turbo._ad_negativ == "blurry"
    assert turbo._ad_confidence == 0.4
    assert turbo._prediction == "flux_flow"


def test_starten_unbesetzt_schickt_keinen_der_drei(tmp_path: Path, monkeypatch):
    """The silence check: with a detector but neither dial set, and no
    prediction, none of the three flags appears — an explicit
    --ad-negative-prompt "" would break sd-cli's own inheritance of the
    main negative prompt."""
    _sd_server_binary_anlegen(tmp_path)
    aufrufe: dict = {}

    def fake_popen(befehl, **kwargs):
        aufrufe["befehl"] = befehl
        return _LebtImmer()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    turbo = Bildturbo(tmp_path)

    turbo.starten(Path("/modelle/m.safetensors"), ad_modell=Path("/y/face.pt"))
    befehl = aufrufe["befehl"]
    assert "--ad-negative-prompt" not in befehl
    assert "--extra-ad-args" not in befehl
    assert "--prediction" not in befehl


def test_ad_negativ_und_schwelle_haengen_am_detektor_auch_beim_start(
    tmp_path: Path, monkeypatch
):
    """Without a detector the two dials are not sent AND not remembered —
    a stored half-pair would tell passt_zu the server carries something
    its command never asked for."""
    _sd_server_binary_anlegen(tmp_path)
    aufrufe: dict = {}

    def fake_popen(befehl, **kwargs):
        aufrufe["befehl"] = befehl
        return _LebtImmer()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    turbo = Bildturbo(tmp_path)

    turbo.starten(
        Path("/modelle/m.safetensors"), ad_negativ="blurry", ad_confidence=0.4,
    )
    befehl = aufrufe["befehl"]
    assert "--ad-negative-prompt" not in befehl
    assert "--extra-ad-args" not in befehl
    assert turbo._ad_negativ == ""
    assert turbo._ad_confidence is None


def test_gespann_passt_nicht_bei_geaendertem_ad_negativ_oder_schwelle(tmp_path: Path):
    """Both are compared only while a detector is set — the same rule as
    the detailer's own prompt, including the silence half: without a
    detector an orphaned value must NOT force a restart."""
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._modell = "m.safetensors"
    turbo._ad_modell = "face.pt"
    turbo._ad_negativ = "blurry"
    turbo._ad_confidence = 0.4
    passt = dict(ad_modell="face.pt", ad_negativ="blurry", ad_confidence=0.4)
    assert turbo.passt_zu("m.safetensors", **passt) is True
    assert turbo.passt_zu(
        "m.safetensors", ad_modell="face.pt", ad_negativ="anders", ad_confidence=0.4
    ) is False
    assert turbo.passt_zu(
        "m.safetensors", ad_modell="face.pt", ad_negativ="blurry", ad_confidence=0.7
    ) is False
    # No detector: the running server's own values are also folded to
    # unset, so the orphaned wish values change nothing.
    turbo._ad_modell = None
    turbo._ad_negativ = ""
    turbo._ad_confidence = None
    assert turbo.passt_zu(
        "m.safetensors", ad_negativ="ignored", ad_confidence=0.9
    ) is True


def test_gespann_passt_nicht_bei_geaenderter_prediction(tmp_path: Path):
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._modell = "m.safetensors"
    turbo._prediction = "flux_flow"
    assert turbo.passt_zu("m.safetensors", prediction="flux_flow") is True
    assert turbo.passt_zu("m.safetensors", prediction="eps") is False
    assert turbo.passt_zu("m.safetensors") is False


def test_starten_zeigt_immer_auf_den_upscaler_ordner(tmp_path: Path, monkeypatch):
    """--hires-upscalers-dir is pointed at whenever it is given, like the
    LoRA folder: hr_upscaler travels per request, the folder it resolves
    against does not."""
    _sd_server_binary_anlegen(tmp_path)
    aufrufe: dict = {}

    def fake_popen(befehl, **kwargs):
        aufrufe["befehl"] = befehl
        return _LebtImmer()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    turbo = Bildturbo(tmp_path)
    ordner = tmp_path / "upscaler"

    turbo.starten(Path("/modelle/m.safetensors"), upscaler_ordner=ordner)
    befehl = aufrufe["befehl"]
    assert befehl[befehl.index("--hires-upscalers-dir") + 1] == str(ordner)
    assert turbo.passt_zu("m.safetensors", upscaler_ordner=ordner) is True
    assert turbo.passt_zu("m.safetensors") is False

    turbo.starten(Path("/modelle/m.safetensors"))
    assert "--hires-upscalers-dir" not in aufrufe["befehl"]


def test_der_turbo_body_traegt_die_hires_zusatzfelder(tmp_path: Path):
    """Every highres value travels in the ``hires`` object of the server's
    own route, the same values sd-cli is given."""
    auftrag = Auftrag(
        modell=Path("/m.safetensors"), prompt="x", hires=True, hires_scale=1.5,
        hires_steps=12, hires_denoise=0.55, hires_upscaler="Lanczos",
        hires_width=1664, hires_height=2432,
    )
    body = _turbo_auftrag(auftrag)
    assert body["hires"] == {
        "enabled": True, "scale": 1.5, "steps": 12, "denoising_strength": 0.55,
        "upscaler": "Lanczos", "target_width": 1664, "target_height": 2432,
    }


def test_der_turbo_body_laesst_unbesetzte_hires_zusatzfelder_weg(tmp_path: Path):
    auftrag = Auftrag(modell=Path("/m.safetensors"), prompt="x", hires=True)
    body = _turbo_auftrag(auftrag)
    for feld in ("steps", "denoising_strength", "upscaler", "target_width", "target_height"):
        assert feld not in body["hires"]


def test_hires_denoise_ueberschreibt_nie_die_startbild_staerke(tmp_path: Path):
    """The starting picture's strength and the highres denoise are two
    fields of their own on this route — neither overwrites the other."""
    bild = tmp_path / "start.png"
    bild.write_bytes(b"PNG")
    auftrag = Auftrag(
        modell=Path("/m.safetensors"), prompt="x", startbild=bild, staerke=0.6,
        hires=True, hires_denoise=0.55,
    )
    body = _turbo_auftrag(auftrag)
    assert body["strength"] == 0.6
    assert body["hires"]["denoising_strength"] == 0.55


def test_gezeichnet_wird_erst_wenn_der_server_wirklich_antwortet(
    tmp_path: Path, monkeypatch
):
    """Popen returns long before the server binds its port, and a draw sent
    into that gap dies on a plain connection refusal (measured: HTTP 503
    after 0.04 s on build 820, a refused connection after 0.05 s on build
    920). The draw waits for the capabilities route to answer first."""
    from app import bildturbo as bt

    server = _JobServer(refused=2)
    server.install(monkeypatch, bt)
    monkeypatch.setattr(bt.time, "sleep", lambda s: None)

    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()

    # No exception: the draw waits the port out instead of being thrown at it.
    assert turbo.zeichnen({"prompt": "x"}) == b"PNG"
    assert len([u for u in server.calls if u.endswith("/capabilities")]) == 3


def test_ein_warmer_server_wird_kein_zweites_mal_gefragt(tmp_path: Path, monkeypatch):
    """A server that is already up must not be delayed. Once one has
    answered, the guard is a flag lookup — no HTTP, on this or any later
    picture."""
    from app import bildturbo as bt

    server = _JobServer()
    server.install(monkeypatch, bt)

    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()

    for _ in range(5):
        turbo.zeichnen({"prompt": "x"})

    gefragt = [u for u in server.calls if u.endswith("/capabilities")]
    assert gefragt == [f"http://127.0.0.1:{bt.PORT}/sdcpp/v1/capabilities"]


def test_ein_server_der_nicht_hochkommt_meldet_klar_statt_zu_zeichnen(
    tmp_path: Path, monkeypatch
):
    """No draw is thrown at a server that never came up — the
    caller gets the same sentence a failed start already shows.

    Measured with a real subprocess that exits at once (which is what
    sd-server does on a missing or corrupt checkpoint: "new_sd_ctx_t
    failed", process gone): BildturboFehler('bild.turbo_ladefehler') after
    0.554 s.
    """
    from app import bildturbo as bt

    monkeypatch.setattr(bt.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        bt.httpx, "get", lambda url, **kw: (_ for _ in ()).throw(
            bt.httpx.ConnectError("connection refused")
        )
    )

    class Gestorben:
        """Alive at the door, gone by the time the guard looks again — the
        real race a server that dies while loading produces."""

        pid = 1234

        def __init__(self):
            self._reste = 1

        def poll(self):
            if self._reste > 0:
                self._reste -= 1
                return None
            return 1

    turbo = Bildturbo(tmp_path)
    turbo._prozess = Gestorben()

    with pytest.raises(BildturboFehler) as fehler:
        turbo.zeichnen({"prompt": "x"})
    assert fehler.value.grund == "bild.turbo_ladefehler"


def test_ein_frischer_server_wird_wieder_gefragt(tmp_path: Path, monkeypatch):
    """The "already answered" flag belongs to ONE server. A restart or a
    stop drops it, so the next server is waited for again rather than
    inheriting its predecessor's clean bill of health."""
    _sd_server_binary_anlegen(tmp_path)
    monkeypatch.setattr("subprocess.Popen", lambda befehl, **kwargs: _LebtImmer())

    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._war_bereit = True

    turbo.starten(Path("/modelle/m.safetensors"))
    assert turbo._war_bereit is False

    turbo._war_bereit = True
    turbo.stoppen()
    assert turbo._war_bereit is False


def test_ein_gescheiterter_zug_traegt_die_worte_des_servers(tmp_path: Path, monkeypatch):
    """A refused draw carries the server's own answer, not just the key.

    The 400 of the picture server names the file and the mistake ("invalid
    lora path: x.safetensors"); the bare key says only that something
    failed. The request path shows it below the sentence, exactly as it
    shows the sd-cli painter's stderr.
    """
    import httpx

    from app import bildturbo as bt

    class FakeAntwort:
        status_code = 400
        text = '{"error":"invalid lora path: x.safetensors"}'

        def raise_for_status(self):
            raise httpx.HTTPStatusError("400", request=None, response=self)

    monkeypatch.setattr(bt.httpx, "get", lambda url, **kw: FakeAntwort())
    monkeypatch.setattr(bt.httpx, "post", lambda url, **kw: FakeAntwort())

    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._war_bereit = True

    with pytest.raises(BildturboFehler) as fehler:
        turbo.zeichnen({"prompt": "x"})
    assert fehler.value.grund == "bild.gescheitert"
    assert "invalid lora path: x.safetensors" in fehler.value.protokoll
    assert fehler.value.protokoll.startswith("HTTP 400")


def test_ein_langer_serversatz_wird_gekappt(tmp_path: Path, monkeypatch):
    """A server answering with a page instead of a line cannot push a wall
    of text into the window."""
    import httpx

    from app import bildturbo as bt

    class FakeAntwort:
        status_code = 500
        text = "x" * 5000

        def raise_for_status(self):
            raise httpx.HTTPStatusError("500", request=None, response=self)

    monkeypatch.setattr(bt.httpx, "get", lambda url, **kw: FakeAntwort())
    monkeypatch.setattr(bt.httpx, "post", lambda url, **kw: FakeAntwort())

    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._war_bereit = True

    with pytest.raises(BildturboFehler) as fehler:
        turbo.zeichnen({"prompt": "x"})
    assert len(fehler.value.protokoll) < bt.ANTWORTTEXT_GRENZE + 20


def test_ein_verbindungsfehler_hat_keine_serverworte(tmp_path: Path, monkeypatch):
    """Nothing to quote when the server never answered — the sentence stands
    alone rather than gaining an invented explanation."""
    import httpx

    from app import bildturbo as bt

    def _post(url, **kw):
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(bt.httpx, "post", _post)

    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._war_bereit = True

    with pytest.raises(BildturboFehler) as fehler:
        turbo.zeichnen({"prompt": "x"})
    assert fehler.value.protokoll is None


def test_a_failed_job_carries_the_server_words(tmp_path: Path, monkeypatch):
    """A job that fails on the server carries the server's own message
    below the sentence, as a refused request does."""
    from app import bildturbo as bt

    server = _JobServer(status="failed", error_text="generate_image returned no results")
    server.install(monkeypatch, bt)
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._war_bereit = True

    with pytest.raises(BildturboFehler) as error:
        turbo.zeichnen({"prompt": "x"})
    assert error.value.grund == "bild.gescheitert"
    assert error.value.protokoll == "generate_image returned no results"


def test_a_cancelled_job_is_a_silent_stop(tmp_path: Path, monkeypatch):
    from app import bildturbo as bt

    server = _JobServer(status="cancelled")
    server.install(monkeypatch, bt)
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._war_bereit = True

    with pytest.raises(BildturboFehler) as error:
        turbo.zeichnen({"prompt": "x"})
    assert error.value.grund == "bild.abgebrochen"


def test_the_job_is_polled_until_it_ends(tmp_path: Path, monkeypatch):
    """A job answers queued, then generating, then completed; the picture
    comes from the last answer."""
    from app import bildturbo as bt

    server = _JobServer(before=["queued", "generating"])
    server.install(monkeypatch, bt)
    monkeypatch.setattr(bt.time, "sleep", lambda s: None)
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._war_bereit = True

    assert turbo.zeichnen({"prompt": "x"}) == b"PNG"
    assert len([u for u in server.calls if "/jobs/" in u]) == 3


def test_stopping_a_queued_job_keeps_the_server(tmp_path: Path, monkeypatch):
    """A job still in the queue is cancelled over the server's own route —
    the model stays loaded, nothing is ended."""
    from app import bildturbo as bt

    ended = []
    monkeypatch.setattr(bt.prozessstopp, "beenden", lambda p, frist=5.0: ended.append(p))
    server = _JobServer(cancel_status=200)
    server.install(monkeypatch, bt)

    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._zeichnet = True
    turbo._job = "job_1"
    assert turbo.abbrechen() is True
    assert server.calls[-1].endswith("/sdcpp/v1/jobs/job_1/cancel")
    assert ended == []
    assert turbo.laeuft()


def test_stopping_a_drawing_job_ends_the_server(tmp_path: Path, monkeypatch):
    """Once the job draws, the server refuses the cancel — measured on build
    920: 409 "job is currently generating and cannot be interrupted yet".
    Then the server is ended under the draw, as before."""
    from app import bildturbo as bt

    ended = []
    monkeypatch.setattr(bt.prozessstopp, "beenden", lambda p, frist=5.0: ended.append(p))
    server = _JobServer(cancel_status=409)
    server.install(monkeypatch, bt)

    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._zeichnet = True
    turbo._job = "job_1"
    assert turbo.abbrechen() is True
    assert turbo._abgebrochen is True
    assert len(ended) == 1


def test_a_job_that_fails_after_a_stop_is_a_silent_stop(tmp_path: Path, monkeypatch):
    """Whatever end a job reports after a stop was pressed, it ended because
    of the stop — the window says nothing."""
    from app import bildturbo as bt

    server = _JobServer(status="failed", error_text="job cancelled by client")
    server.install(monkeypatch, bt)
    turbo = Bildturbo(tmp_path)
    server._on_submit = lambda: setattr(turbo, "_abgebrochen", True)
    turbo._prozess = _LebtImmer()
    turbo._war_bereit = True
    monkeypatch.setattr(turbo, "_end_job", lambda job: None)

    with pytest.raises(BildturboFehler) as error:
        turbo.zeichnen({"prompt": "x"})
    assert error.value.grund == "bild.abgebrochen"


def test_only_a_server_that_has_drawn_holds_its_weights(tmp_path: Path, monkeypatch):
    from app import bildturbo as bt

    server = _JobServer()
    server.install(monkeypatch, bt)
    turbo = Bildturbo(tmp_path)
    turbo._prozess = _LebtImmer()
    turbo._war_bereit = True
    assert turbo.weights_loaded is False
    turbo.zeichnen({"prompt": "x"})
    assert turbo.weights_loaded is True
    turbo._prozess = None
    assert turbo.weights_loaded is False


def test_a_status_answer_is_kept_only_for_the_process_it_asked(tmp_path: Path, monkeypatch):
    """A poll whose server was replaced by a start meanwhile must not mark
    the new server as ready."""
    turbo = Bildturbo(tmp_path)
    old, new = _LebtImmer(pid=1), _LebtImmer(pid=2)
    turbo._prozess = old

    def _answer_while_replaced():
        turbo._prozess = new
        return True

    monkeypatch.setattr(turbo, "_bereit", _answer_while_replaced)
    assert turbo.zustand() == "bereit"
    assert turbo._war_bereit is False
    monkeypatch.setattr(turbo, "_bereit", lambda: True)
    assert turbo.zustand() == "bereit"
    assert turbo._war_bereit is True


def test_the_server_reports_what_it_holds(tmp_path: Path, monkeypatch):
    """The memory check asks every server what it holds; this one answers
    with its resident memory while it runs and nothing while it is off."""
    from app import bildturbo as bt

    monkeypatch.setattr(bt, "rss_gb", lambda pid: 3.5 if pid == 1234 else None)
    turbo = Bildturbo(tmp_path)
    assert turbo.belegt_gb() is None
    turbo._prozess = _LebtImmer()
    assert turbo.belegt_gb() == 3.5


def test_pause_and_resume_start_the_same_server_again(tmp_path: Path, monkeypatch):
    """The server steps aside for one picture and comes back with exactly
    the start values it ran with."""
    _sd_server_binary_anlegen(tmp_path)
    commands: list[list[str]] = []
    ended = []
    from app import bildturbo as bt

    monkeypatch.setattr(bt.prozessstopp, "beenden", lambda p, frist=5.0: ended.append(p))
    monkeypatch.setattr(
        "subprocess.Popen", lambda command, **kwargs: (commands.append(command), _LebtImmer())[1]
    )
    turbo = Bildturbo(tmp_path)
    turbo.starten(Path("/modelle/m.safetensors"), vae=Path("/v/vae.safetensors"), threads=4)

    assert turbo.pause() is True
    assert len(ended) == 1
    turbo._prozess = None
    turbo.resume()
    assert commands[1] == commands[0]
    assert turbo.passt_zu("m.safetensors", "vae.safetensors", threads=4)


def test_a_server_stopped_since_its_pause_does_not_come_back(tmp_path: Path, monkeypatch):
    """The program ends while an sd-cli picture is drawn: its stop runs
    after ``resume`` has read the start values and before it starts — and
    nothing is started behind the program's back."""
    _sd_server_binary_anlegen(tmp_path)
    commands: list[list[str]] = []
    from app import bildturbo as bt

    monkeypatch.setattr(bt.prozessstopp, "beenden", lambda p, frist=5.0: None)
    monkeypatch.setattr(
        "subprocess.Popen", lambda command, **kwargs: (commands.append(command), _LebtImmer())[1]
    )
    turbo = Bildturbo(tmp_path)
    turbo.starten(Path("/modelle/m.safetensors"), threads=4)
    assert turbo.pause() is True
    turbo._prozess = None

    # ``resume`` asks whether the server runs right after it read the start
    # values: the stop of the ending program lands exactly there.
    def stop_in_between() -> bool:
        monkeypatch.setattr(turbo, "laeuft", lambda: False)
        turbo.stoppen()
        return False

    monkeypatch.setattr(turbo, "laeuft", stop_in_between)
    assert turbo.resume() is False
    assert len(commands) == 1
    assert turbo._prozess is None
    # And once stopped, a later resume has nothing to bring back either.
    assert turbo.resume() is False
    assert len(commands) == 1


def test_a_server_started_anew_since_its_pause_is_left_alone(tmp_path: Path, monkeypatch):
    """Silence probe for the same look: a server started on another model
    after the pause keeps running; the paused one is not started over it."""
    _sd_server_binary_anlegen(tmp_path)
    commands: list[list[str]] = []
    from app import bildturbo as bt

    monkeypatch.setattr(bt.prozessstopp, "beenden", lambda p, frist=5.0: None)
    monkeypatch.setattr(
        "subprocess.Popen", lambda command, **kwargs: (commands.append(command), _LebtImmer())[1]
    )
    turbo = Bildturbo(tmp_path)
    turbo.starten(Path("/modelle/m.safetensors"))
    assert turbo.pause() is True
    paused_with = turbo._start_values
    turbo._prozess = None
    turbo.starten(Path("/modelle/other.safetensors"))
    args, kwargs = paused_with
    assert turbo.starten(*args, **kwargs, _paused_with=paused_with) is False
    assert len(commands) == 2
    assert turbo.passt_zu("other.safetensors", None)


def test_pause_without_a_running_server_does_nothing(tmp_path: Path):
    turbo = Bildturbo(tmp_path)
    assert turbo.pause() is False
    turbo.resume()
    assert turbo._prozess is None




class _Answer:
    def __init__(self, status_code: int, data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._data = data or {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError(str(self.status_code), request=None, response=self)

    def json(self):
        return self._data


class _JobServer:
    """A stand-in for the picture server's own interface: ``img_gen`` hands
    out a job, the job answers with its state, ``cancel`` with the given
    status. Every URL asked is recorded."""

    def __init__(self, *, status: str = "completed", before: list[str] | None = None,
                 error_text: str = "", cancel_status: int = 200, refused: int = 0,
                 on_submit=None):
        import base64

        self.calls: list[str] = []
        self.bodies: list[dict] = []
        self._status = status
        self._before = list(before or [])
        self._error_text = error_text
        self._cancel_status = cancel_status
        self._refused = refused
        self._on_submit = on_submit
        self._image = base64.b64encode(b"PNG").decode()

    def install(self, monkeypatch, module) -> None:
        monkeypatch.setattr(module.httpx, "post", self.post)
        monkeypatch.setattr(module.httpx, "get", self.get)

    def post(self, url, json=None, timeout=None, **kw):
        self.calls.append(url)
        if url.endswith("/img_gen"):
            self.bodies.append(json)
            if self._on_submit:
                self._on_submit()
            return _Answer(202, {"id": "job_1", "status": "queued"})
        return _Answer(self._cancel_status, {}, "job is currently generating")

    def get(self, url, timeout=None, **kw):
        import httpx

        self.calls.append(url)
        if url.endswith("/capabilities"):
            if self._refused > 0:
                self._refused -= 1
                raise httpx.ConnectError("connection refused")
            return _Answer(200, {})
        if self._before:
            return _Answer(200, {"id": "job_1", "status": self._before.pop(0)})
        job = {"id": "job_1", "status": self._status}
        if self._status == "completed":
            job["result"] = {"images": [{"index": 0, "b64_json": self._image}]}
        else:
            job["error"] = {"code": self._status, "message": self._error_text}
        return _Answer(200, job)
