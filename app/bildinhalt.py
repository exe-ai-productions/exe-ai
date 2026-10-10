"""What a model file actually is, read from its own header — never its
name, its extension, or which folder it happens to sit in.

Unterordner are the ordering the rest of this program relies on (`vae/`,
`text_encoders/`, …), but a file dropped into the main folder by hand only
ever gets a name and an extension right — a text encoder shaped like a
".safetensors" file has been found in the VAE list for exactly that
reason. This module is the net underneath the folder convention: it looks
at the actual bytes and answers ``bildmodell``, ``textversteher`` or
``vae`` only when it is CERTAIN, and ``unbekannt`` otherwise.
``unbekannt`` is handled exactly like today — offered as an image model.
The net must never swallow something it cannot identify with confidence.

Two formats, read only at the front of the file:

* GGUF carries a ``general.architecture`` key in its own metadata section
  — the same key every llama.cpp-family tool writes and trusts. The whole
  header is read, every key and every tensor entry, the way llama.cpp reads
  one before it trusts it, by ``app/ggufmtp.py``, the program's one GGUF
  header reader; a file that ends inside its header answers nothing.
* safetensors starts with an 8-byte little-endian length, then that many
  bytes of JSON mapping each tensor's name to its shape and dtype — the
  tensor NAMES are what differ between a VAE, a text encoder and a
  diffusion model, and they are the only thing read here.
"""

from __future__ import annotations

import functools
import json
import os
import struct
from pathlib import Path

from app import ggufmtp as gguf

BILDMODELL = "bildmodell"
TEXTVERSTEHER = "textversteher"
VAE = "vae"
# Not one of the kinds ``sorte`` answers — such a file is a VAE there — but
# what ``companion`` calls a VAE of video frames.
VIDEO_VAE = "video_vae"
UNBEKANNT = "unbekannt"


def sorte(pfad: Path) -> str:
    """Which of the three kinds this file's header says it is, or
    ``unbekannt``. Never raises — a broken or foreign file proves nothing
    either way, and the caller must still be able to offer it as today."""
    try:
        gelesen = _image_header(pfad)
    except Exception:
        return UNBEKANNT
    if gelesen is None:
        return UNBEKANNT
    is_gguf, architecture, names = gelesen
    if is_gguf:
        return _gguf_sorte(architecture)
    return _sorte_aus_tensornamen(list(names or {}))


# --- safetensors -------------------------------------------------------

# A real header is a few kilobytes to a few megabytes for a model with
# thousands of tensors; this only guards against a corrupt or hostile
# length value asking for a huge read.
_SAFETENSORS_HOECHSTE_KOPF_LAENGE = 100_000_000

# The two text encoders this program's families use. CLIP checkpoints
# follow the diffusers ``CLIPTextModel`` convention (every tensor prefixed
# ``text_model.``); T5 checkpoints carry ``SelfAttention`` in their
# attention layers' names, a word no CLIP or diffusion checkpoint uses.
_TEXTVERSTEHER_MARKER = ("text_model.", "SelfAttention")

# An LLM text encoder in safetensors (Qwen3, Qwen3-VL, Qwen2.5-VL,
# Ministral 3) opens its first decoder layer under this name; a diffusion
# model names its layers without the ``model.`` in front, or nests them
# deeper. The same mark ``companion`` reads an LLM by.
_LLM_MARKER = "model.layers.0.self_attn."

# A VAE's own tensor names in the SD/Flux ecosystem — no text encoder or
# diffusion model carries either the encoder/decoder pair or these two
# exact names.
_VAE_EINZELNAMEN = ("post_quant_conv.weight", "quant_conv.weight")

# A diffusion model's own tensor prefixes: a full SD 1.5/SDXL checkpoint
# nests everything under ``model.diffusion_model.``; a standalone Bausatz
# diffusion model (Flux, SD3-family) names its transformer blocks at the
# top level instead.
_BILDMODELL_PREFIXE = (
    "model.diffusion_model.", "double_blocks.", "single_blocks.", "joint_blocks.",
)


def _sorte_aus_tensornamen(namen: list[str]) -> str:
    # A diffusion prefix wins first: a full single-file checkpoint often
    # embeds its own text encoder (and sometimes its own VAE) under the
    # same roof, so checking the companion markers first would call the
    # whole checkpoint a text encoder. The file itself is still a model a
    # user picks as one, embedded companions or not.
    if any(n.startswith(_BILDMODELL_PREFIXE) for n in namen):
        return BILDMODELL
    # Checked before the broad encoder+decoder VAE rule below: T5 is
    # itself an encoder-decoder model, so a complete T5 (not just the
    # encoder-only distribution the Flux ecosystem ships) carries both
    # prefixes too and would otherwise be called a VAE.
    if any(marker in n for n in namen for marker in _TEXTVERSTEHER_MARKER):
        return TEXTVERSTEHER
    if any(n.startswith(_LLM_MARKER) for n in namen):
        return TEXTVERSTEHER
    if any(n in _VAE_EINZELNAMEN for n in namen) or (
        any(n.startswith("encoder.") for n in namen)
        and any(n.startswith("decoder.") for n in namen)
    ):
        return VAE
    return UNBEKANNT


# --- GGUF ----------------------------------------------------------------

# This program's own five families, by the general.architecture value the
# shipped conversion tools write for each.
_GGUF_BILDMODELL_ARCHITEKTUREN = {"sd1", "sdxl", "sd3", "flux", "flux2"}
_GGUF_TEXTVERSTEHER_ARCHITEKTUREN = {
    "t5", "t5encoder", "clip",
    # LLM checkpoints (zimage's and flux2's text understanding) — the
    # architecture names llama.cpp itself writes for the families this
    # program is likeliest to see used as a Bausatz's LLM.
    "llama", "qwen2", "qwen3", "gemma", "gemma2", "phi3",
    # The vision-language and Mistral encoders of Krea 2 (Qwen3-VL),
    # Qwen-Image (Qwen2.5-VL) and ERNIE-Image (Ministral 3), as their GGUF
    # headers name them.
    "qwen3vl", "qwen2vl", "mistral3",
}


def _gguf_sorte(architecture: str | None) -> str:
    if architecture in _GGUF_BILDMODELL_ARCHITEKTUREN:
        return BILDMODELL
    if architecture in _GGUF_TEXTVERSTEHER_ARCHITEKTUREN:
        return TEXTVERSTEHER
    return UNBEKANNT


def _gguf_architecture(header: gguf.Header | None) -> str | None:
    """The architecture the header names as text, or None."""
    if header is None:
        return None
    architecture = header[0].get(gguf.ARCHITEKTUR_SCHLUESSEL)
    return architecture if isinstance(architecture, str) else None


# --- Family and companion kind -------------------------------------------
#
# Read the way sd.cpp itself tells families apart (``get_sd_version`` in its
# src/model_loader.cpp): by the NAMES of the weights and, where two families
# share names, by one weight's SHAPE. Only the families of this program's
# own table (app/image_families.py) are answered; anything else is None —
# never a guess.


def tensors(path: Path) -> tuple[dict[str, list[int]], str | None] | None:
    """Every weight's name and shape in the file's header, and GGUF's
    ``general.architecture`` if it has one. Shapes are outermost first, the
    safetensors order; GGUF stores them the other way round and is turned
    here, so both formats answer alike. None when the header cannot be
    read."""
    try:
        gelesen = _image_header(path)
    except OSError:
        return None
    if gelesen is None or gelesen[2] is None:
        return None
    return gelesen[2], gelesen[1]


# A header read: whether it is GGUF, GGUF's architecture, and every weight's
# name with its shape — None for the names when a GGUF name is not valid
# UTF-8, so the architecture still answers.
_ImageHeader = tuple[bool, str | None, dict[str, list[int]] | None]


def _image_header(path: Path) -> _ImageHeader | None:
    """The header of an image model file, built once per file state: a
    header of a few megabytes is read once per file, not once per question.
    A file that cannot be read right now raises ``OSError`` and is not
    remembered, so the next look reads it."""
    state = os.stat(path)
    return _image_header_cached(str(path), state.st_size, state.st_mtime_ns)


@functools.lru_cache(maxsize=256)
def _image_header_cached(path: str, size: int, mtime_ns: int) -> _ImageHeader | None:
    try:
        with open(path, "rb") as file:
            start = file.read(8)
            if start[:4] == b"GGUF":
                header = gguf.read_header(Path(path))
                if header is None:
                    return None
                return True, _gguf_architecture(header), _gguf_names(header)
            if len(start) == 8:
                header_length = struct.unpack("<Q", start)[0]
                if 0 < header_length < _SAFETENSORS_HOECHSTE_KOPF_LAENGE:
                    raw = file.read(header_length)
                    loaded = json.loads(raw)
                    if isinstance(loaded, dict):
                        return False, None, {
                            name: list(value.get("shape") or [])
                            for name, value in loaded.items()
                            if name != "__metadata__" and isinstance(value, dict)
                        }
    except OSError:
        # Not readable right now: raised past the cache, so it is not kept.
        raise
    except Exception:  # noqa: BLE001 - a broken or foreign file answers nothing
        return None
    return None


def _gguf_names(header: gguf.Header) -> dict[str, list[int]] | None:
    # The names are what ``tensors`` answers with, so they are read as text;
    # a name that is not valid UTF-8 leaves them unanswered, as before.
    try:
        return {name.decode("utf-8"): list(reversed(shape)) for name, shape in header[1]}
    except UnicodeDecodeError:
        return None


# A standalone diffusion model names its blocks at the top level; inside a
# checkpoint the same names sit under this prefix, and sd.cpp adds it to a
# standalone file itself. Added here where it is missing, so one rule reads
# both.
_DIFFUSION_PREFIX = "model.diffusion_model."

# The text encoder's token embedding in an SD checkpoint, by the names
# sd.cpp looks for; its width is 768 for SD 1.x.
_TOKEN_EMBEDDING = (
    "cond_stage_model.transformer.text_model.embeddings.token_embedding.weight",
    "cond_stage_model.model.token_embedding.weight",
    "text_model.embeddings.token_embedding.weight",
    "te.text_model.embeddings.token_embedding.weight",
    "conditioner.embedders.0.model.token_embedding.weight",
    "conditioner.embedders.0.transformer.text_model.embeddings.token_embedding.weight",
)

# GGUF files written by the common conversion tools name their family here.
_GGUF_FAMILIES = {"flux": "flux", "sd1": "sd15", "sdxl": "sdxl"}


# A model that is a folder: the index of a safetensors model split into
# shards names every weight and the shard that holds it. sd.cpp is handed
# the folder itself (docs/sensenova_u1.md: "The directory must contain
# model.safetensors.index.json, every referenced Safetensors shard, and the
# tokenizer files").
FOLDER_INDEX = "model.safetensors.index.json"
# The weight that tells SenseNova U1.5 apart.
_SENSENOVA_WEIGHT = "language_model.model.layers.0.self_attn.q_proj_mot_gen.weight"


def folder_model(path: Path) -> bool:
    """A folder that is a model: one holding the index of its shards."""
    return path.is_dir() and (path / FOLDER_INDEX).is_file()


def _folder_weights(path: Path) -> list[str]:
    """The names of a folder model's weights, from its index; none when the
    index cannot be read."""
    try:
        index = json.loads((path / FOLDER_INDEX).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    weights = index.get("weight_map") if isinstance(index, dict) else None
    return [str(name) for name in weights] if isinstance(weights, dict) else []


def family(path: Path) -> str | None:
    """The family of a diffusion model or checkpoint, from its header — of
    a model that is a folder, from its index — or None when it is none of
    this program's families or cannot be read."""
    if path.is_dir():
        if any(_SENSENOVA_WEIGHT in name for name in _folder_weights(path)):
            return "sensenova_u1"
        return None
    read = tensors(path)
    if read is None:
        return None
    names, architecture = read
    # A GGUF file names a family in its own key; a safetensors one never has
    # one, so the architecture key tells the two apart without reading
    # the file again.
    is_gguf = architecture is not None or _is_gguf(path)
    return _family_from_names(names, sort=not is_gguf) or _GGUF_FAMILIES.get(architecture or "")


def _is_gguf(path: Path) -> bool:
    try:
        state = path.stat()
    except OSError:
        return False
    return _is_gguf_cached(str(path), state.st_size, state.st_mtime_ns)


@functools.lru_cache(maxsize=256)
def _is_gguf_cached(path: str, size: int, mtime_ns: int) -> bool:
    try:
        with open(path, "rb") as file:
            return file.read(4) == b"GGUF"
    except OSError:
        return False


# sd.cpp tells the Wan 2.2 variants apart by the patch embedding's input
# times output channels (its ``ne[3]`` after folding the 5D kernel into 4
# dimensions, src/model_loader.cpp:626-631): 36 x 5120 for I2V A14B, 48 x
# 3072 for TI2V 5B.
_WAN22_I2V_PATCH = 184320
_WAN22_TI2V_PATCH = 147456


def _patch_channels(shape: list[int]) -> int:
    """The patch embedding's folded channel count: output times input of a
    5D kernel as safetensors lists it, or the first number of the 4D shape a
    GGUF file stores it in."""
    if len(shape) == 5:
        return shape[0] * shape[1]
    return shape[0] if shape else 0


def _family_from_names(raw: dict[str, list[int]], *, sort: bool = True) -> str | None:
    """sd.cpp's own ``get_sd_version`` (src/model_loader.cpp:438-699 of
    build 920), rule for rule and in its order, answered with this
    program's family names. Walked in sd.cpp's own order: a safetensors
    header by name (sd.cpp reads it through a JSON object, which sorts its
    keys), a GGUF file in the order the file lists them (``sort``).

    sd.cpp reads a standalone diffusion model with ``model.diffusion_model.``
    in front of every name that lacks it (src/model_loader.cpp:275), a
    checkpoint as it is. Which of the two a file will be is not known here,
    so both spellings are looked at; a rule written for one finds its name
    either way. Shapes are outermost first, so sd.cpp's ``ne[0]`` is the
    last number of a shape and ``ne[2]`` of a convolution the second."""
    names: dict[str, list[int]] = dict(raw)
    walk: list[str] = []
    # sd.cpp orders the names as the file has them (sorted for safetensors)
    # and adds the prefix after; each name is looked at in both spellings
    # at its own place.
    for name in (sorted(raw) if sort else raw):
        walk.append(name)
        if not name.startswith(_DIFFUSION_PREFIX):
            names.setdefault(_DIFFUSION_PREFIX + name, raw[name])
            walk.append(_DIFFUSION_PREFIX + name)

    def has(name: str) -> bool:
        return name in names

    def last(name: str) -> int | None:
        shape = names.get(name)
        return shape[-1] if shape else None

    flags = {
        "flux": False, "flux2": False, "single_47": False, "unet": False,
        "xl": False, "multiple_encoders": False, "middle_1": False,
        "output_311": False, "output_71": False, "attn_1024": False,
        "wan": False, "s2v": False, "img_emb": False,
    }
    patch_channels = 0
    token_width = input_channels = context_width = None
    for name in walk:
        if ("model.diffusion_model.double_blocks." in name
                or "model.diffusion_model.single_transformer_blocks." in name):
            flags["flux"] = True
        if "model.diffusion_model.net.lq_proj.latent_proj.0.weight" in name:
            return "pid"
        if "embed_image_indicator.weight" in name:
            return "ideogram4"
        if ("model.diffusion_model.txtfusion.projector.weight" in name
                or "model.diffusion_model.text_fusion.projector.weight" in name):
            return "krea2"
        if "model.diffusion_model.nerf_final_layer_conv." in name:
            return "chroma_radiance"
        if "model.diffusion_model.joint_blocks." in name:
            return "sd3"
        if ("model.x_embedder.proj1.weight" in name
                and has("model.language_model.layers.0.self_attn.q_proj.weight")):
            return "hidream_o1"
        if ("model.diffusion_model.transformer_blocks.0.attn.norm_added_q.weight" in name
                and has("model.diffusion_model.transformer_blocks.0.img_mlp.w1.weight")):
            return "lens"
        if "net.img_embedder.proj1.weight" in name:
            return "minit2i"
        if _SENSENOVA_WEIGHT in name:
            # SenseNova U1.5 — one shard of a model that is loaded as a
            # folder (``folder_model``); a single file of it is no model.
            return None
        if name == "model.diffusion_model.txt_in.text_norm.weight":
            return "qwen_image_2_1"
        if "model.diffusion_model.transformer_blocks.0.img_mod.1.weight" in name:
            if last("model.diffusion_model.img_in.weight") == 128:
                return "mage_flow"
            if has("model.diffusion_model.time_text_embed.addition_t_embedding.weight"):
                return "qwen_image_layered"
            return "qwen_image"
        if ("model.diffusion_model.txt_in.individual_token_refiner.blocks.0."
                "adaLN_modulation.1.weight") in name:
            return "hunyuan_video"
        if "llm_adapter.blocks.0.cross_attn.q_proj.weight" in name:
            return "anima"
        if "model.diffusion_model.double_stream_modulation_img.lin.weight" in name:
            flags["flux2"] = True
        if "dual_time_embed.semantic_embedder.linear_1.weight" in name:
            return "sefi"
        if "single_blocks.47.linear1.weight" in name:
            flags["single_47"] = True
        if "model.diffusion_model.double_blocks.0.img_mlp.gate_proj.weight" in name:
            return "ovis"
        if "model.diffusion_model.sigvq_embedder.1.weight" in name:
            return "llada_image"
        if "model.diffusion_model.cap_embedder.0.weight" in name:
            return "zimage"
        if "double_stream_layers.0.img_instruct_attn.processor.img_to_q.weight" in name:
            return "boogu"
        if "model.diffusion_model.layers.0.adaLN_sa_ln.weight" in name:
            return "ernie"
        if ("model.diffusion_model.t_block.1.weight" in name
                and has("model.diffusion_model.x_embedder.proj.weight")
                and not has("model.diffusion_model.audio_patchify_proj.weight")):
            return "pixart"
        if "model.diffusion_model.adaln_single.emb.timestep_embedder.linear_1.bias" in name:
            if (has("model.diffusion_model.pos_embed.proj.weight")
                    and has("model.diffusion_model.adaln_single.linear.weight")
                    and not has("model.diffusion_model.audio_patchify_proj.weight")):
                return "pixart"
            return "ltx"
        if ("model.diffusion_model.video_patch_proj.weight" in name
                and has("model.diffusion_model.audio_patch_proj.weight")):
            return "minimax_h3"
        if "model.diffusion_model.blocks.0.cross_attn.norm_k.weight" in name:
            flags["wan"] = True
        if "casual_audio_encoder.weights" in name or "audio_injector.injector.0.q.weight" in name:
            # S2V and T2V-14B share patch_embedding shapes.
            flags["s2v"] = True
        if "model.diffusion_model.patch_embedder.weight" in name:
            return "lingbot_video"
        if "model.diffusion_model.patch_embedding.weight" in name:
            patch_channels = _patch_channels(names[name])
        if "model.diffusion_model.img_emb" in name:
            flags["img_emb"] = True
        if "model.diffusion_model.input_blocks." in name or "unet.down_blocks." in name:
            flags["unet"] = True
            if flags["multiple_encoders"]:
                flags["xl"] = True
        if ("conditioner.embedders.1" in name or "cond_stage_model.1" in name
                or "te.1" in name):
            flags["multiple_encoders"] = True
            if flags["unet"]:
                flags["xl"] = True
        if "model.diffusion_model.input_blocks.8.0.time_mixer.mix_factor" in name:
            return None  # Stable Video Diffusion
        if ("model.diffusion_model.middle_block.1." in name
                or "unet.mid_block.resnets.1." in name):
            flags["middle_1"] = True
        if ("model.diffusion_model.output_blocks.3.1.transformer_blocks.1" in name
                or "unet.up_blocks.1.attentions.0.transformer_blocks.1" in name):
            flags["output_311"] = True
        if ("model.diffusion_model.output_blocks.7.1" in name
                or "unet.up_blocks.2.attentions.1" in name):
            flags["output_71"] = True
            if name == "model.diffusion_model.output_blocks.7.1.transformer_blocks.0.attn1.to_k.weight":
                if last(name) == 1024:
                    flags["attn_1024"] = True
        if name in _TOKEN_EMBEDDING:
            token_width = last(name)
        if name in ("model.diffusion_model.input_blocks.0.0.weight",
                    "model.diffusion_model.img_in.weight", "unet.conv_in.weight"):
            shape = names[name]
            input_channels = shape[1] if len(shape) == 4 else None
        if name in ("model.diffusion_model.txt_in.weight",
                    "model.diffusion_model.context_embedder.weight"):
            context_width = last(name)
    if flags["wan"]:
        if flags["s2v"]:
            return "wan22_s2v"
        if patch_channels == _WAN22_I2V_PATCH and not flags["img_emb"]:
            return "wan22_i2v"
        if patch_channels == _WAN22_TI2V_PATCH and not flags["img_emb"]:
            return "wan22_ti2v"
        return "wan"
    inpaint_or_plain = input_channels != 8
    if flags["xl"]:
        if not inpaint_or_plain:
            return "sdxl_pix2pix"
        return "sdxl"
    if flags["flux"] and not flags["flux2"]:
        if context_width == 3584:
            return "longcat"
        # Chroma shares Flux's blocks and tells itself apart by this layer
        # (src/model/diffusion/flux.hpp:140).
        if any(n.startswith(_DIFFUSION_PREFIX + "distilled_guidance_layer.") for n in names):
            return "chroma"
        return "flux"
    if flags["flux2"]:
        return "flux2" if flags["single_47"] else "flux2_klein"
    # sd.cpp answers by the text encoder's width alone here; a file that is
    # nothing but a CLIP text encoder would pass as SD. Only a file with a
    # U-Net is a Stable Diffusion model.
    if not flags["unet"]:
        return None
    if token_width == 768:
        if not inpaint_or_plain:
            return "sd15_pix2pix"
        if not flags["middle_1"] and not flags["output_71"]:
            return "sdxs"
        return "sd15"
    if token_width == 1024:
        if not flags["middle_1"] and flags["attn_1024"]:
            return "sdxs"
        return "sd2"
    return None


def standalone_diffusion_model(path: Path) -> bool:
    """A diffusion model without its text encoders and VAE — a kit part,
    drawn with ``--diffusion-model`` rather than ``-m``. Its weights either
    all carry the prefix or none does: sd.cpp adds the prefix only where it
    is missing (src/model_loader.cpp:275), so both load alike. A checkpoint
    holds its diffusion model under the prefix BESIDE other weights (the
    VAE's, the text encoder's)."""
    read = tensors(path)
    if read is None or not read[0]:
        return False
    prefixed = [n.startswith(_DIFFUSION_PREFIX) for n in read[0]]
    return all(prefixed) or not any(prefixed)


# Where a checkpoint holds its text encoders: SD 1.x and 2.x, SDXL, and the
# single-file form of SD3 and Flux.
_TEXT_ENCODER_PREFIXES = ("cond_stage_model.", "conditioner.embedders.", "text_encoders.")


def checkpoint_without_text_encoders(path: Path) -> bool:
    """A checkpoint — a diffusion model beside other weights, drawn with
    ``-m`` — that brings no text encoder of its own, so its family's
    encoders are passed beside it (sd.cpp docs/sd3.md:17). False for a
    standalone diffusion model, which is a kit part, and for a file whose
    header cannot be read."""
    read = tensors(path)
    if read is None or not read[0]:
        return False
    names = read[0]
    prefixed = [n.startswith(_DIFFUSION_PREFIX) for n in names]
    if all(prefixed) or not any(prefixed):
        return False
    return not any(n.startswith(_TEXT_ENCODER_PREFIXES) for n in names)


# The T5 vocabulary Flux's encoder was trained with — UMT5 (Wan's encoder)
# shares the architecture but not the vocabulary, and is the wrong encoder
# for Flux. Measured: t5xxl.safetensors shared.weight [32128, 4096];
# umt5-xxl-encoder-Q8_0.gguf token_embd.weight 256384 wide.
_T5_VOCABULARY = 32128
_UMT5_VOCABULARY = 256384
_T5_XXL_WIDTH = 4096

# CLIP widths: 768 for CLIP-L, 1280 for CLIP-G.
_CLIP_WIDTHS = {768: "clip_l", 1280: "clip_g"}


def companion(path: Path) -> tuple[str, int | None]:
    """What a companion file is for a kit: ``t5xxl``, ``umt5``,
    ``clip_l``, ``clip_g``, ``llm``, ``vae`` or ``video_vae`` (both with
    their latent channels), or ``""`` when the header does not say so for
    certain."""
    read = tensors(path)
    if read is None:
        return "", None
    names, architecture = read
    conv_in = names.get("decoder.conv_in.weight")
    if conv_in and len(conv_in) == 4:
        return VAE, conv_in[1]
    # Wan's VAE opens its decoder with a 3D convolution over the latent
    # channels: [384, 16, 3, 3, 3] in wan_2.1_vae.safetensors.
    conv1 = names.get("decoder.conv1.weight")
    if conv1 and len(conv1) == 5:
        return VIDEO_VAE, conv1[1]
    if architecture in ("t5", "t5encoder") or any("SelfAttention" in n for n in names):
        shapes = [
            shape for name in ("shared.weight", "encoder.embed_tokens.weight", "token_embd.weight")
            if (shape := names.get(name))
        ]
        # T5-XXL by its vocabulary AND its width: flan-t5-large (MiniT2I's
        # encoder) shares the vocabulary at a width of 1024.
        xxl = shapes and (len(shapes[0]) < 2 or shapes[0][-1] == _T5_XXL_WIDTH)
        if xxl and shapes[0][0] == _T5_VOCABULARY:
            return "t5xxl", None
        if xxl and shapes[0][0] == _UMT5_VOCABULARY:
            return "umt5", None
        return "", None
    shape = names.get("text_model.embeddings.token_embedding.weight")
    if shape:
        return _CLIP_WIDTHS.get(shape[-1], ""), None
    if architecture in _GGUF_TEXTVERSTEHER_ARCHITEKTUREN - {"t5", "t5encoder", "clip"} or any(
        n.startswith(_LLM_MARKER) for n in names
    ):
        return "llm", None
    return "", None


# Where an LLM keeps its token embedding: GGUF's name, and the one the
# safetensors encoders above use.
_TOKEN_EMBEDDINGS = ("token_embd.weight", "model.embed_tokens.weight")


def llm(path: Path) -> tuple[str, int] | None:
    """An LLM text encoder's architecture, as its GGUF header names it, and
    the width of its token embedding — the two things a family's LLM has to
    match (app/image_families.py, ``llms``). None when the header does not
    carry both: a safetensors encoder names no architecture."""
    read = tensors(path)
    if read is None:
        return None
    names, architecture = read
    if not architecture:
        return None
    for name in _TOKEN_EMBEDDINGS:
        shape = names.get(name)
        if shape:
            return architecture, shape[-1]
    return None
