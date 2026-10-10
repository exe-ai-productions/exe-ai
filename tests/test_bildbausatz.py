"""bildbausatz: which model family needs which files, and nothing else.

No server, no model file, no import of bildrunner or bildturbo — this
module only turns "which family, which paths" into "which switches", so
that is all these tests exercise.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import image_families
from app.bildbausatz import Gespann, familie_pruefen, schalter

FLUX, ZIMAGE, FLUX2 = "flux", "zimage", "flux2"

_KEIN_TEIL = {
    "diffusion_model": None, "t5xxl": None, "clip_l": None,
    "clip_g": None, "llm": None,
}


def test_sd15_und_sdxl_sind_keine_bausaetze():
    assert image_families.is_kit("sd15") is False
    assert image_families.is_kit("sdxl") is False


def test_die_drei_bausatz_familien_sind_bausaetze():
    for familie in (FLUX, ZIMAGE, FLUX2):
        assert image_families.is_kit(familie) is True


def test_familie_pruefen_ist_still_ohne_diffusion_model():
    """No parts at all: nothing can be lost, so nothing is refused. A
    merged single-file Flux names its family and sets no part."""
    familie_pruefen(None, **_KEIN_TEIL)
    familie_pruefen(FLUX, **_KEIN_TEIL)


@pytest.mark.parametrize("feld", ["t5xxl", "clip_l", "clip_g", "llm"])
def test_familie_pruefen_lehnt_textversteher_ohne_diffusion_model_ab(feld):
    """The silent half of the same mistake, and the one that used to pass:
    both callers' plain-model branch builds "-m <file>" and never reads a
    text encoder, so a Bausatz assembled in the window was thrown away
    without a word — and the error that finally arrived named the model
    file, which the reader had every reason to think was right.

    ``clip_g`` belongs in this list for the same reason as the other
    three, and it stayed out of it a commit longer: the window offers the
    field for every Bausatz family, so a merged single-file Flux plus a
    CLIP-G was a request whose CLIP-G no branch ever read."""
    familie = ZIMAGE if feld == "llm" else FLUX
    with pytest.raises(ValueError):
        familie_pruefen(familie, **{**_KEIN_TEIL, feld: Path(f"/{feld}.gguf")})


@pytest.mark.parametrize("familie", [FLUX, ZIMAGE, FLUX2])
def test_familie_pruefen_erlaubt_clip_g_in_jeder_bausatz_familie(familie):
    """The other half of the clip_g rule, and the half that must NOT
    change: no family owns clip_g — ``schalter()`` emits it whatever the
    family is — so with a diffusion model to assemble it with it belongs
    to all three, unlike t5xxl/clip_l (flux) and llm (zimage, flux2)."""
    familie_pruefen(familie, **{
        **_KEIN_TEIL, "diffusion_model": Path("/modell.gguf"),
        "clip_g": Path("/clip_g.safetensors"),
    })


def test_familie_pruefen_ist_still_bei_leerem_diffusion_model():
    """An empty string is unset, the same as None — _begleiter() already
    treats it that way, so a plain model sending "" must not be rejected."""
    familie_pruefen(None, **{**_KEIN_TEIL, "diffusion_model": ""})


def test_familie_pruefen_lehnt_diffusion_model_ohne_familie_ab():
    with pytest.raises(ValueError):
        familie_pruefen(None, **{**_KEIN_TEIL, "diffusion_model": Path("/flux1-dev.gguf")})


def test_familie_pruefen_lehnt_unbekannte_familie_ab():
    for unsinn in ("Flux", "flux ", "sdxl", "quatsch", ""):
        with pytest.raises(ValueError):
            familie_pruefen(unsinn, **{**_KEIN_TEIL, "diffusion_model": Path("/flux1-dev.gguf")})


def test_familie_pruefen_ignoriert_leere_textversteher_felder():
    """A dropdown left empty sends "" in Svelte, not null — that must not
    count as a text encoder from the wrong family."""
    familie_pruefen(ZIMAGE, **{
        **_KEIN_TEIL, "diffusion_model": Path("/zimage.gguf"),
        "llm": Path("/llm.gguf"), "t5xxl": "", "clip_l": "",
    })


def test_familie_pruefen_lehnt_zimage_mit_t5xxl_ab():
    with pytest.raises(ValueError):
        familie_pruefen(ZIMAGE, **{
            **_KEIN_TEIL, "diffusion_model": Path("/flux1-dev.gguf"), "t5xxl": Path("/t5xxl.gguf"),
        })


def test_familie_pruefen_lehnt_flux_mit_llm_ab():
    with pytest.raises(ValueError):
        familie_pruefen(FLUX, **{
            **_KEIN_TEIL, "diffusion_model": Path("/flux1-dev.gguf"), "llm": Path("/llm.gguf"),
        })


def test_familie_pruefen_erlaubt_flux_mit_t5xxl_und_clip_l():
    familie_pruefen(FLUX, **{
        **_KEIN_TEIL, "diffusion_model": Path("/flux1-dev.gguf"),
        "t5xxl": Path("/t5xxl.gguf"), "clip_l": Path("/clip_l.safetensors"),
    })


def _p(path: str) -> str:
    """The path as this system spells it — the switches carry ``str(Path)``,
    and on Windows that is a backslash."""
    return str(Path(path))


def test_flux_schalter_traegt_t5_und_clip_l():
    gespann = Gespann(
        familie=FLUX, diffusion_model=Path("/flux1-dev.gguf"),
        t5xxl=Path("/t5xxl.gguf"), clip_l=Path("/clip_l.safetensors"),
    )
    assert schalter(gespann) == [
        "--diffusion-model", _p("/flux1-dev.gguf"),
        "--t5xxl", _p("/t5xxl.gguf"),
        "--clip_l", _p("/clip_l.safetensors"),
    ]


def test_zimage_schalter_traegt_llm():
    gespann = Gespann(
        familie=ZIMAGE, diffusion_model=Path("/zimage.gguf"), llm=Path("/llm.gguf")
    )
    assert schalter(gespann) == ["--diffusion-model", _p("/zimage.gguf"), "--llm", _p("/llm.gguf")]


def test_flux2_schalter_traegt_llm():
    gespann = Gespann(
        familie=FLUX2, diffusion_model=Path("/flux2.gguf"), llm=Path("/llm.gguf")
    )
    assert schalter(gespann) == ["--diffusion-model", _p("/flux2.gguf"), "--llm", _p("/llm.gguf")]


def test_flux_schalter_laesst_ungesetzten_textversteher_weg():
    gespann = Gespann(familie=FLUX, diffusion_model=Path("/flux1-dev.gguf"))
    assert schalter(gespann) == ["--diffusion-model", _p("/flux1-dev.gguf")]


def test_schalter_lehnt_fehlende_familie_ab():
    """schalter() is the one place every Gespann, from either caller, must
    pass through — the check here is what makes the missing family an
    error rather than a silently incomplete command, whichever caller
    skipped it (familie_pruefen() catches the same case earlier, but only
    for the one caller that runs it)."""
    gespann = Gespann(
        familie=None, diffusion_model=Path("/flux1-dev.gguf"),
        t5xxl=Path("/t5xxl.gguf"), clip_l=Path("/clip_l.safetensors"),
    )
    with pytest.raises(ValueError):
        schalter(gespann)


def test_schalter_lehnt_textversteher_der_falschen_familie_ab():
    gespann = Gespann(
        familie=ZIMAGE, diffusion_model=Path("/flux1-dev.gguf"),
        t5xxl=Path("/t5xxl.gguf"),
    )
    with pytest.raises(ValueError):
        schalter(gespann)


def test_schalter_traegt_vae_und_vae_format_wenn_gesetzt():
    gespann = Gespann(
        familie=FLUX, diffusion_model=Path("/flux1-dev.gguf"),
        vae=Path("/ae.safetensors"), vae_format="flux",
    )
    aus = schalter(gespann)
    assert "--vae" in aus and aus[aus.index("--vae") + 1] == str(Path("/ae.safetensors"))
    assert "--vae-format" in aus and aus[aus.index("--vae-format") + 1] == "flux"


def test_schalter_laesst_vae_weg_wenn_ungesetzt():
    gespann = Gespann(familie=FLUX, diffusion_model=Path("/flux1-dev.gguf"))
    aus = schalter(gespann)
    assert "--vae" not in aus
    assert "--vae-format" not in aus


def test_schalter_traegt_clip_g_unabhaengig_von_der_familie():
    """No family in the table needs clip_g — it is an extra a user can add
    regardless, the same shape as the VAE."""
    gespann = Gespann(
        familie=ZIMAGE, diffusion_model=Path("/zimage.gguf"),
        clip_g=Path("/clip_g.safetensors"),
    )
    aus = schalter(gespann)
    assert aus[aus.index("--clip_g") + 1] == str(Path("/clip_g.safetensors"))


def test_schalter_laesst_clip_g_weg_wenn_ungesetzt():
    gespann = Gespann(familie=FLUX, diffusion_model=Path("/flux1-dev.gguf"))
    assert "--clip_g" not in schalter(gespann)


# --- What a kit still lacks -------------------------------------------------


def test_fehlendes_teil_nennt_das_erste_was_fehlt():
    from app.bildbausatz import fehlendes_teil

    assert fehlendes_teil("zimage", {"llm": "q.gguf"}) == "vae"
    assert fehlendes_teil("zimage", {"vae": "ae.safetensors"}) == "llm"
    assert fehlendes_teil("flux", {"clip_l": "c", "vae": "v"}) == "t5xxl"


def test_ein_ganzer_bausatz_und_ein_checkpoint_fehlen_nichts():
    """The silence probe: a whole kit, a checkpoint family and an unknown
    family are never refused here."""
    from app.bildbausatz import fehlendes_teil

    assert fehlendes_teil("zimage", {"llm": "q.gguf", "vae": "ae.safetensors"}) is None
    assert fehlendes_teil("sdxl", {}) is None
    assert fehlendes_teil("", {}) is None


def test_der_name_des_teils_folgt_der_familie():
    from app.bildbausatz import teil_name

    assert teil_name("zimage", "vae") == "VAE"
    assert teil_name("flux", "t5xxl") == "T5-XXL"
    assert teil_name("wan", "t5xxl") == "UMT5-XXL"
    assert teil_name("hunyuan_video", "t5xxl") == "ByT5"


def test_eine_vae_wird_nur_eingesetzt_wo_der_kopf_sie_kennt():
    """Flux's 16-channel VAE and Wan 2.1's 16-channel video VAE share their
    header with SD3's and Qwen-Image's: never put in by itself. Flux.2's 32
    and Wan 2.2 TI2V's 48 are told apart."""
    from app import image_families

    by_itself = {f.name: image_families.vae_by_itself(f) for f in image_families.FAMILIES}
    assert by_itself["flux"] is False
    assert by_itself["zimage"] is False
    assert by_itself["wan"] is False
    assert by_itself["flux2"] is True
    assert by_itself["flux2_klein"] is True
    assert by_itself["wan22_ti2v"] is True
    assert by_itself["sdxl"] is False


# --- A checkpoint without text encoders of its own ---------------------------

_SD3_ENCODERS = {
    "clip_l": Path("/enc/clip_l.safetensors"), "clip_g": Path("/enc/clip_g.safetensors"),
    "t5xxl": Path("/enc/t5xxl.safetensors"),
}


def test_a_checkpoint_without_encoders_takes_its_family_s_beside_m(tmp_path, monkeypatch):
    """SD3.5 as one checkpoint with separate text encoders: sd-cli is called
    with ``-m`` and the three encoders its family reads, in the family's
    order; the check lets exactly these through for such a checkpoint."""
    from app import bildbausatz, bildrunner

    assert bildbausatz.checkpoint_switches("sd3", **_SD3_ENCODERS, llm=None) == [
        "--clip_l", str(_SD3_ENCODERS["clip_l"]), "--clip_g", str(_SD3_ENCODERS["clip_g"]),
        "--t5xxl", str(_SD3_ENCODERS["t5xxl"]),
    ]
    familie_pruefen("sd3", **{**_KEIN_TEIL, **_SD3_ENCODERS}, bare_checkpoint=True)

    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/somewhere/sd-cli")
    model = tmp_path / "sd3.5_large.safetensors"
    command = bildrunner.Bildrunner(tmp_path).befehl(
        bildrunner.Auftrag(modell=model, prompt="x", familie="sd3", **_SD3_ENCODERS),
        tmp_path / "out.png",
    )
    start = command.index("-m")
    assert command[start:start + 8] == [
        "-m", str(model), "--clip_l", str(_SD3_ENCODERS["clip_l"]),
        "--clip_g", str(_SD3_ENCODERS["clip_g"]), "--t5xxl", str(_SD3_ENCODERS["t5xxl"]),
    ]
    assert "--diffusion-model" not in command


def test_only_such_a_checkpoint_and_only_its_family_s_encoders_pass():
    """Silence: without the word that the checkpoint brings no encoders the
    check refuses as before; with it, an encoder the family does not read,
    a further kit part and a family that is no kit are still refused."""
    with pytest.raises(ValueError):
        familie_pruefen("sd3", **{**_KEIN_TEIL, **_SD3_ENCODERS})
    with pytest.raises(ValueError):
        familie_pruefen("sd3", **{**_KEIN_TEIL, "llm": Path("/llm.gguf")}, bare_checkpoint=True)
    with pytest.raises(ValueError):
        familie_pruefen(
            "sd3", **{**_KEIN_TEIL, **_SD3_ENCODERS}, tokenizer=Path("/t.json"),
            bare_checkpoint=True,
        )
    with pytest.raises(ValueError):
        familie_pruefen(
            "sd15", **{**_KEIN_TEIL, "clip_l": Path("/clip_l.safetensors")}, bare_checkpoint=True,
        )


def test_a_plain_checkpoint_draws_without_encoder_switches(tmp_path, monkeypatch):
    """Silence: an SD 1.5 checkpoint is one flag as before, and a family
    that reads no encoder gives none even when one is handed in."""
    from app import bildbausatz, bildrunner

    assert bildbausatz.checkpoint_switches("sd15", clip_l=Path("/clip_l.safetensors")) == []
    assert bildbausatz.checkpoint_switches(None, clip_l=Path("/clip_l.safetensors")) == []
    assert bildbausatz.checkpoint_switches("sd3", clip_l=None, clip_g=None, t5xxl=None) == []
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/somewhere/sd-cli")
    command = bildrunner.Bildrunner(tmp_path).befehl(
        bildrunner.Auftrag(modell=tmp_path / "v1-5.safetensors", prompt="x", familie="sd15"),
        tmp_path / "out.png",
    )
    assert command[command.index("-m") + 2] == "-p"
    for switch in ("--clip_l", "--clip_g", "--t5xxl", "--llm"):
        assert switch not in command

