"""The switches a kit ("Bausatz") is assembled with.

A model is either one file (a checkpoint, ``-m``) or a kit: several files
assembled at draw time, each with its own job. Which family is a kit and
which text encoders it reads is the family table's knowledge
(``app/image_families.py``); this module turns "which family, which files"
into "which switches", so ``bildrunner`` (the sd-cli command) and
``bildturbo`` (the persistent server) build the exact same switches from the
exact same rule instead of two hand-written copies drifting apart.

Nothing here imports either of them, and nothing here touches a filesystem
or a running process, which is why it is tested without a server or a model
in sight.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app import image_families

# The sd-cli switch for each text encoder field a family can read.
_ENCODER_SWITCHES = {"t5xxl": "--t5xxl", "clip_l": "--clip_l", "llm": "--llm"}

# The sd-cli switch for each further part a family can read
# (``Family.parts``).
PART_SWITCHES = {
    "llm_vision": "--llm_vision",
    "tokenizer": "--tokenizer",
    "uncond_diffusion_model": "--uncond-diffusion-model",
    # The video kits' further files: Wan 2.2 A14B's second model for the
    # noisy first steps, LTX's and MiniMax-H3's sound decoder, Wan 2.2 S2V's
    # speech encoder and LTX's embeddings connectors.
    "high_noise_diffusion_model": "--high-noise-diffusion-model",
    "audio_vae": "--audio-vae",
    "audio_encoder": "--audio-encoder",
    "embeddings_connectors": "--embeddings-connectors",
}


# The word a model carries in place of a family where none is to decide
# about it: the model's family is not read from its file, because the user
# switched that off for the model. Every part that is set is then sent with
# its own switch; none is refused for the family and none counts as missing,
# and sd.cpp tells for itself what the model is. The model's own file goes
# as ``-m`` (``checkpoint_switches``) unless a diffusion model was chosen
# for it (``schalter``). No family carries this name, and a request cannot
# say it — it is put in by the service alone.
FREE = "free"


def _encoders(familie: str) -> dict[str, str]:
    family = image_families.get(familie)
    encoders = family.encoders if family is not None else ()
    # clip_g has its own rule below: sent whatever the family.
    return {name: _ENCODER_SWITCHES[name] for name in encoders if name in _ENCODER_SWITCHES}


def checkpoint_switches(familie: str | None, **encoders: object | None) -> list[str]:
    """The text encoders passed beside ``-m`` for a checkpoint that brings
    none of its own: each encoder its family reads that is set, in the
    family's order (sd.cpp docs/sd3.md:17, ``-m … --clip_l … --clip_g …
    --t5xxl …``). Empty for a family that reads none, and for no family.

    Where no family decides (``FREE``), every part that is set goes beside
    ``-m`` with its own switch — a text encoder or any further part."""
    if familie == FREE:
        switches = {**_ENCODER_SWITCHES, "clip_g": "--clip_g", **PART_SWITCHES}
        return [
            entry for name, switch in switches.items() if encoders.get(name)
            for entry in (switch, str(encoders[name]))
        ]
    family = image_families.get(familie)
    if family is None:
        return []
    switches = {**_ENCODER_SWITCHES, "clip_g": "--clip_g"}
    parts: list[str] = []
    for name in family.encoders:
        if encoders.get(name):
            parts += [switches[name], str(encoders[name])]
    return parts


def _parts(familie: str) -> dict[str, str]:
    family = image_families.get(familie)
    parts = family.parts if family is not None else ()
    return {name: PART_SWITCHES[name] for name in parts}


@dataclass(frozen=True)
class Gespann:
    """The files one Bausatz picture is assembled from. Only the fields a
    family actually reads are ever looked at by ``schalter`` — carrying the
    others as ``None`` is always safe."""

    familie: str
    diffusion_model: Path
    t5xxl: Path | None = None
    clip_l: Path | None = None
    clip_g: Path | None = None
    llm: Path | None = None
    vae: Path | None = None
    vae_format: str = ""
    llm_vision: Path | None = None
    tokenizer: Path | None = None
    uncond_diffusion_model: Path | None = None
    high_noise_diffusion_model: Path | None = None
    audio_vae: Path | None = None
    audio_encoder: Path | None = None
    embeddings_connectors: Path | None = None


def familie_pruefen(
    familie: str | None,
    *,
    diffusion_model: object | None,
    t5xxl: object | None,
    clip_l: object | None,
    clip_g: object | None,
    llm: object | None,
    llm_vision: object | None = None,
    tokenizer: object | None = None,
    uncond_diffusion_model: object | None = None,
    bare_checkpoint: bool = False,
    **further_parts: object | None,
) -> None:
    """Raise when a diffusion model is set without a known Bausatz family to
    explain it, when a text encoder is set without a diffusion model to
    assemble it with (the same mistake the other way round, and the one
    that used to pass silently), or when a text encoder from a DIFFERENT
    family than the one named is set (``t5xxl``/``clip_l`` belong to flux
    only, ``llm`` to zimage/flux2 only). A named family is the only source
    of truth now —
    nothing here guesses one back from which fields happen to be set, and
    nothing silently drops a field that does not belong. ``clip_g`` takes
    part in the first of those checks and not the second: ``schalter()``
    reads it regardless of family, so no family can make it wrong, but the
    plain-model branch never reads it either, so without a diffusion model
    it is thrown away exactly like the encoders beside it. ``vae_format``
    stays out of both: both callers emit ``--vae-format`` from their
    plain-model branch as well, so it is never lost.

    An empty string counts as unset, the same as ``None`` — a caller like
    ``_begleiter()`` already treats one that way, and disagreeing here
    would reject a plain model that never asked for a Bausatz at all, or
    wave a Bausatz field through a family it does not belong to.

    This runs at the HTTP boundary, before a single path is resolved, so a
    bad request gets a clean 400 instead of a 404 for a file it was never
    going to look for. ``schalter()`` runs the same two checks again right
    before it reads ``familie`` — that copy is the one that actually
    guards the command, since it is the one place every ``Gespann``, from
    either caller, is required to pass through."""
    if not diffusion_model:
        # No parts to assemble: the family is then only a statement about
        # WHAT the model is (its starting values, its CFG lock, whether it
        # has a guidance dial), which every family may make — a merged
        # single-file Flux is still a Flux. Only an unknown word is refused.
        if familie and not image_families.known(familie):
            raise ValueError(f"Unknown model family: {familie!r}")
        # A text encoder with no diffusion model to assemble it with is the
        # other direction of the same mistake, and the quiet one: both
        # callers' plain-model branch builds "-m <file>" and never reads
        # t5xxl, clip_l, clip_g or llm, so a Bausatz put together in the
        # window is dropped without a word — and the error that arrives names
        # the model file, which the reader has every reason to think is
        # right. Refused here instead, where the reason is still known.
        #
        # Deliberately not "a Bausatz family without a diffusion model":
        # that is exactly the merged single-file Flux above, one .gguf that
        # really does carry a whole model, and the family names it. Only
        # PARTS that would be thrown away are refused.
        #
        # One model does read them beside "-m": a checkpoint that brings no
        # text encoder of its own (``bare_checkpoint``, read from its header
        # by the caller) takes the encoders of its family, and only those.
        family = image_families.get(familie) if bare_checkpoint else None
        read = family.encoders if family is not None and family.kit else ()
        for feld, wert in (
            ("t5xxl", t5xxl), ("clip_l", clip_l), ("clip_g", clip_g), ("llm", llm),
            ("llm_vision", llm_vision), ("tokenizer", tokenizer),
            ("uncond_diffusion_model", uncond_diffusion_model), *further_parts.items(),
        ):
            if wert and feld not in read:
                raise ValueError(f"{feld} is set, but no diffusion model is specified for the "
                                 "assembly.")
        return
    if not image_families.is_kit(familie):
        raise ValueError(f"{familie!r} is not a Bausatz family.")
    erlaubt = {**_encoders(familie or ""), **_parts(familie or "")}
    for feld, wert in (
        ("t5xxl", t5xxl), ("clip_l", clip_l), ("llm", llm), ("llm_vision", llm_vision),
        ("tokenizer", tokenizer), ("uncond_diffusion_model", uncond_diffusion_model),
        *further_parts.items(),
    ):
        if wert and feld not in erlaubt:
            raise ValueError(f"{feld} does not belong to model family {familie}.")


# What a part is called where the user reads that it is missing — the name
# the docs give it, the same in every language.
_PART_NAMES = {"t5xxl": "T5-XXL", "clip_l": "CLIP-L", "clip_g": "CLIP-G", "llm": "LLM", "vae": "VAE"}


def fehlendes_teil(familie: str | None, teile: dict[str, object | None]) -> str | None:
    """The first part a kit of this family needs that ``teile`` does not
    carry, or None when nothing is missing. Needed are every text encoder the
    family reads and, where its kit names a VAE or it decodes with one of its
    own (``image_families.needs_vae``), the VAE. Asked before sd.cpp is started, on
    the server's start as on a drawing, so it never starts on half a kit and
    the user learns which part is missing instead of reading a load error."""
    family = image_families.get(familie)
    if family is None or not family.kit:
        return None
    needed = [*family.encoders, *(["vae"] if image_families.needs_vae(family) else [])]
    return next((teil for teil in needed if not teile.get(teil)), None)


def teil_name(familie: str | None, teil: str) -> str:
    """The name of a missing part as the user reads it. The t5xxl field of
    a Wan model holds UMT5, HunyuanVideo's ByT5."""
    family = image_families.get(familie)
    if teil == "t5xxl" and family is not None and family.t5_kind != "t5xxl":
        return {"umt5": "UMT5-XXL", "": "ByT5"}.get(family.t5_kind, _PART_NAMES[teil])
    return _PART_NAMES.get(teil, teil)


def schalter(gespann: Gespann) -> list[str]:
    """The complete switch list for one Bausatz: the model, its text
    encoder(s), the VAE and its format if set — the one truth both the
    sd-cli command and the turbo start line read from.

    Every ``Gespann`` passes through here, whichever caller built it — so
    this is where an unnamed or unknown family, or a text encoder from a
    different one, is caught. ``familie_pruefen()`` catches the same two
    things earlier, at the HTTP boundary, for a clean 400 before any file
    is even resolved — this check is what makes that one more than a
    suggestion: skip it (a caller that builds an ``Auftrag`` directly, a
    test, a future caller) and the command built here still refuses to
    guess."""
    if gespann.familie == FREE:
        # No family decides: every field has its switch and none is refused.
        erlaubt = dict(_ENCODER_SWITCHES)
        teile_erlaubt = dict(PART_SWITCHES)
    elif not image_families.is_kit(gespann.familie):
        raise ValueError(f"{gespann.familie!r} is not a Bausatz family.")
    else:
        erlaubt = _encoders(gespann.familie)
        teile_erlaubt = _parts(gespann.familie)
    for feld in ("t5xxl", "clip_l", "llm", *PART_SWITCHES):
        wert = getattr(gespann, feld)
        if wert and feld not in erlaubt and feld not in teile_erlaubt:
            raise ValueError(f"{feld} does not belong to model family {gespann.familie}.")

    teile = ["--diffusion-model", str(gespann.diffusion_model)]
    for feld, schalter_name in {**erlaubt, **teile_erlaubt}.items():
        wert = getattr(gespann, feld)
        if wert is not None:
            teile += [schalter_name, str(wert)]
    # A second CLIP, same shape as the VAE below: no family in the table
    # needs it, but a user can add one regardless of family.
    if gespann.clip_g is not None:
        teile += ["--clip_g", str(gespann.clip_g)]
    if gespann.vae is not None:
        teile += ["--vae", str(gespann.vae)]
    if gespann.vae_format:
        teile += ["--vae-format", gespann.vae_format]
    return teile
