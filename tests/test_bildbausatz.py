"""bildbausatz: which model family needs which files, and nothing else.

No server, no model file, no import of bildrunner or bildturbo — this
module only turns "which family, which paths" into "which switches", so
that is all these tests exercise.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import image_families
from app.bildbausatz import (
    FREE, PART_SWITCHES, Gespann, checkpoint_switches, familie_pruefen, fehlendes_teil, schalter,
)

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


def test_bei_den_familien_ohne_kanalzahl_zaehlt_die_vae_mit_wenn_der_bausatz_sie_nennt():
    """Krea 2 names a VAE in its kit and no channel count: without a VAE the
    kit is incomplete, with it whole."""
    from app.bildbausatz import fehlendes_teil

    assert fehlendes_teil("krea2", {"llm": "q.gguf"}) == "vae"
    assert fehlendes_teil("krea2", {"llm": "q.gguf", "vae": "wan_2.1_vae.safetensors"}) is None
    assert fehlendes_teil("krea2", {"vae": "wan_2.1_vae.safetensors"}) == "llm"


def test_eine_familie_ohne_vae_im_bausatz_braucht_keine():
    """The silence probe: a kit family that names no VAE is not refused for
    the lack of one."""
    from app.bildbausatz import fehlendes_teil

    assert fehlendes_teil("sd3", {"t5xxl": "t", "clip_l": "c", "clip_g": "g"}) is None
    assert fehlendes_teil("chroma_radiance", {"t5xxl": "t"}) is None


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


# --- A model no family decides about -----------------------------------------


def test_beside_the_plain_model_every_given_part_has_its_switch():
    """The model's family is not read and no diffusion model was chosen: the
    model's own file goes as ``-m``, and beside it every part that is set —
    the tokenizer among them — and nothing that is not set."""
    assert checkpoint_switches(
        FREE, t5xxl=None, clip_l=None, clip_g=None, llm=Path("/llm.gguf"),
        llm_vision=None, tokenizer=Path("/tokenizer.json"), uncond_diffusion_model=None,
    ) == ["--llm", _p("/llm.gguf"), "--tokenizer", _p("/tokenizer.json")]
    assert checkpoint_switches(FREE, t5xxl=None, llm=None, tokenizer=None) == []


@pytest.mark.parametrize(
    "field,switch",
    [("t5xxl", "--t5xxl"), ("clip_l", "--clip_l"), ("clip_g", "--clip_g"), ("llm", "--llm"),
     *PART_SWITCHES.items()],
)
def test_beside_the_plain_model_no_field_is_refused(field, switch):
    assert checkpoint_switches(FREE, **{field: Path("/part.gguf")}) == [switch, _p("/part.gguf")]


def test_the_command_of_a_model_without_a_read_family(tmp_path, monkeypatch):
    """sd-cli's own command line: ``-m`` with the given parts where no
    diffusion model was chosen, ``--diffusion-model`` with them where one
    was — and, the silence probe, a part beside a model whose family is
    read and does not take it stays out as before."""
    from app import bildrunner

    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/somewhere/sd-cli")
    model, chosen = tmp_path / "model.safetensors", tmp_path / "chosen.safetensors"
    parts = {"llm": tmp_path / "llm.gguf", "tokenizer": tmp_path / "tokenizer.json"}
    runner = bildrunner.Bildrunner(tmp_path)

    command = runner.befehl(
        bildrunner.Auftrag(modell=model, prompt="x", familie=FREE, **parts), tmp_path / "out.png",
    )
    start = command.index("-m")
    assert command[start:start + 6] == [
        "-m", str(model), "--llm", str(parts["llm"]), "--tokenizer", str(parts["tokenizer"]),
    ]
    assert "--diffusion-model" not in command

    command = runner.befehl(
        bildrunner.Auftrag(modell=model, prompt="x", familie=FREE, diffusion_model=chosen, **parts),
        tmp_path / "out.png",
    )
    start = command.index("--diffusion-model")
    assert command[start:start + 6] == [
        "--diffusion-model", str(chosen), "--llm", str(parts["llm"]),
        "--tokenizer", str(parts["tokenizer"]),
    ]
    assert "-m" not in command

    command = runner.befehl(
        bildrunner.Auftrag(modell=model, prompt="x", familie="sdxl", **parts), tmp_path / "out.png",
    )
    assert "--tokenizer" not in command and "--llm" not in command


def test_a_free_kit_carries_exactly_the_parts_it_was_given():
    """A diffusion model was chosen for the model whose family is not read:
    every part that is set travels with its own switch — the tokenizer
    beside a plain LLM among them, which a family reading an LLM alone
    refuses — and nothing that is not set."""
    gespann = Gespann(
        familie=FREE, diffusion_model=Path("/model.safetensors"),
        llm=Path("/llm.gguf"), tokenizer=Path("/tokenizer.json"),
        vae=Path("/ae.safetensors"),
    )
    assert schalter(gespann) == [
        "--diffusion-model", _p("/model.safetensors"),
        "--llm", _p("/llm.gguf"),
        "--tokenizer", _p("/tokenizer.json"),
        "--vae", _p("/ae.safetensors"),
    ]


@pytest.mark.parametrize(
    "field,switch",
    [("t5xxl", "--t5xxl"), ("clip_l", "--clip_l"), ("llm", "--llm"), *PART_SWITCHES.items()],
)
def test_a_free_kit_refuses_no_field(field, switch):
    gespann = Gespann(
        familie=FREE, diffusion_model=Path("/model.gguf"), **{field: Path("/part.gguf")}
    )
    assert schalter(gespann) == ["--diffusion-model", _p("/model.gguf"), switch, _p("/part.gguf")]


def test_a_free_kit_without_parts_is_the_model_alone():
    """Every field may stay empty: then nothing but the model is sent."""
    gespann = Gespann(familie=FREE, diffusion_model=Path("/model.gguf"))
    assert schalter(gespann) == ["--diffusion-model", _p("/model.gguf")]


def test_a_free_kit_lacks_no_part():
    assert fehlendes_teil(FREE, {}) is None


def test_free_is_no_family_and_no_request_can_say_it():
    """The silence probe: the word stands for "no family decides" and is put
    in by the service alone. It is no family of the table, and a request that
    says it is refused like any other unknown word."""
    assert image_families.get(FREE) is None
    assert image_families.is_kit(FREE) is False
    with pytest.raises(ValueError):
        familie_pruefen(FREE, **{**_KEIN_TEIL, "diffusion_model": Path("/model.gguf")})


def test_a_known_family_still_refuses_a_part_it_does_not_read():
    """The silence probe: with the family read, a tokenizer beside a Z-Image
    model is refused exactly as before."""
    gespann = Gespann(
        familie=ZIMAGE, diffusion_model=Path("/zimage.gguf"),
        llm=Path("/llm.gguf"), tokenizer=Path("/tokenizer.json"),
    )
    with pytest.raises(ValueError):
        schalter(gespann)
