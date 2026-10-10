"""What the shipped generator can be told to do.

Two lists and two defaults, copied from ``sd-cli --help`` of the binary that
actually ships — not from memory and not from another project's
documentation. A sampler this build does not know is refused by the program
with a usage message, which reaches the user as "the picture could not be
drawn" and explains nothing.

They live here rather than in the API module because they are a fact about
the generator, not about the route: the window offers them, the route checks
against them, and both read the same list.

Kept as plain tuples so the order is the order the window shows. It follows
the program's own help text, which puts the ones people reach for first.
"""

from __future__ import annotations

# --sampling-method
SAMPLER = (
    "euler_a",
    "euler",
    "heun",
    "dpm2",
    "dpm++2s_a",
    "dpm++2m",
    "dpm++2mv2",
    "dpm++2m_sde",
    "dpm++2m_sde_bt",
    "ipndm",
    "ipndm_v",
    "lcm",
    "ddim_trailing",
    "tcd",
    "res_multistep",
    "res_2s",
    "er_sde",
    "euler_cfg_pp",
    "euler_a_cfg_pp",
    "euler_ge",
    "lms",
)
# What the program itself falls back to for models of the SD-1.5 class.
SAMPLER_VORGABE = "euler_a"

# --scheduler. "normal" is the program's alias for discrete; only the real
# name is offered, so what the window shows is what the command line gets.
SCHEDULER = (
    "karras",
    "discrete",
    "exponential",
    "ays",
    "gits",
    "smoothstep",
    "sgm_uniform",
    "simple",
    "kl_optimal",
    "lcm",
    "bong_tangent",
    "ltx2",
    "logit_normal",
    "flux2",
    "flux",
    "beta",
    "llada_image",
)
SCHEDULER_VORGABE = "karras"

# --lora-apply-mode: sd-cli's own three values, all taken by the draw route.
# The studio offers "at_runtime", which it starts with, and "auto"; a chat
# stored at "immediately" reads as "at_runtime" (app/bildfensterwahl.py).
# "auto" and "immediately" have been seen to abort on the Metal build
# whenever a LoRA or PhotoMaker is in play (see app/bildrunner.py's own
# comment on the flag).
LORA_APPLY_MODE = ("at_runtime", "auto", "immediately")
LORA_APPLY_MODE_VORGABE = "at_runtime"

# --vae-format, for a Bausatz's VAE — unlike sampler/scheduler there is no
# fallback value among these five; the empty string means "not set" and
# leaves the flag off entirely, so an unknown request value is turned into
# that instead of a guessed member of the table.
VAE_FORMATE = ("auto", "flux", "sd3", "flux2", "wan")

# --rng: sd-cli's own three names, from its --help.
RNG_WERTE = ("cuda", "cpu", "std_default")
RNG_VORGABE = "cuda"

# --type (weight type): the types sd.cpp converts weights to, by ggml's own
# names (sd.cpp include/stable-diffusion.h, sd_type_t, and the two float8
# names src/stable-diffusion.cpp:43-47 reads). "Auto" on the window is the
# empty string here and no flag at all: the weight file's own type stays.
WEIGHT_TYPES = (
    "f32", "f16", "bf16", "q8_0", "q5_1", "q5_0", "q4_1", "q4_0",
    "q6_K", "q5_K", "q4_K", "q3_K", "q2_K", "f8_e4m3", "f8_e5m2",
)

# sd-cli's own `--preview` method names, checked against the real --help.
# CLI-only: the persistent server (Image-Turbo) answers one request with
# one finished picture, no channel for a mid-draw frame to travel back on.
LIVE_PREVIEW_WERTE = ("proj", "tae", "vae")

# sd-cli's own `--prediction` override names, checked against the real
# --help. "Auto" on the window is the empty string here and no flag at all
# on the command line — the program then derives the prediction type from
# the model itself, exactly as it does today.
PREDICTION_WERTE = (
    "eps", "v", "edm_v", "sd3_flow", "flux_flow", "sefi_flow",
    "minit2i_flow", "sensenova_u1_flow",
)

# `--hires-upscaler`'s built-in names, copied from the shipped binary's own
# --help. Anything else the field carries has to be a model file inside the
# upscaler folder (pointed at with `--hires-upscalers-dir`); an empty value
# leaves the flag off entirely and sd-cli falls back to its own default
# (Latent).
HIRES_UPSCALER_FESTE = (
    "Lanczos",
    "Nearest",
    "Latent",
    "Latent (nearest)",
    "Latent (nearest-exact)",
    "Latent (antialiased)",
    "Latent (bicubic)",
    "Latent (bicubic antialiased)",
)

# How much of the init image is painted over. 1.0 means: ignore it entirely,
# which is what a picture made from nothing does — so it is also the value
# that applies when no init image was chosen at all.
STAERKE_VORGABE = 1.0

# What a LoRA is applied with when no strength was set.
LORA_VORGABE = 0.70
# A LoRA's strength as a number: negative turns its effect around. The slider
# covers the usual range, the field takes this one.
LORA_MIN, LORA_MAX = -10.0, 10.0

# The folder the LoRA files live in, below the image models.
LORA_ORDNER = "lora"

# The folder the textual-inversion embeddings live in, below the image
# models. An embedding is called by its file name inside the prompt.
EMBEDDING_ORDNER = "embedding"

# PhotoMaker: the model that carries a face into a new picture, and the
# folder holding the photos of that face. Two folders because they hold two
# different kinds of thing — one is a downloaded model, the other is the
# user's own pictures, and mixing them would make "which of these is the
# model" a question the program has to guess.
PHOTOMAKER_ORDNER = "photomaker"
GESICHTER_ORDNER = "faces"

# PhotoMaker only fires when the prompt names a class word with `img` stuck
# to it — "a man img, sitting in a café". These are the words it was trained
# on; anything else silently does nothing, which is why the window offers a
# choice instead of a text field.
PM_KLASSEN = ("man", "woman", "girl", "boy")

# How large a picture may be asked for, and in what step. sd.cpp aligns an
# edge UP to its model's grid and draws it (sd-cli warns "align generation
# request up 200x260 to 256x320 (multiple=64)"); its server answers edges of
# 64 to 4096 (``/sdcpp/v1/capabilities``, ``limits``). The program draws and
# keeps edges in steps of 64, rounded up the way sd.cpp rounds them.
#
# They live beside the sampler lists for the same reason those do: the window
# offers them, the route checks against them, and the stored defaults are
# checked against them too — one fact, read from one place.
MIN_KANTE = 64
MAX_KANTE = 4096
RASTER = 64
# sd-cli refuses fewer: "the sample_steps must be greater than 0". It has no
# upper limit, and neither has the CFG.
MIN_SCHRITTE = 1


def kante_pruefen(wert: object) -> int | None:
    """One edge of the picture, rounded up onto the grid inside sd.cpp's
    own range, or None if it is not a number."""
    try:
        zahl = int(wert)
    except (TypeError, ValueError):
        return None
    oben = -(-max(MIN_KANTE, zahl) // RASTER) * RASTER
    return min(MAX_KANTE, oben)


def schritte_pruefen(wert: object) -> int | None:
    """How many steps are kept: at least one, as sd-cli asks, and no upper
    limit, as it sets none; None if it is not a number."""
    try:
        zahl = int(wert)
    except (TypeError, ValueError):
        return None
    return max(MIN_SCHRITTE, zahl)


def sampler_pruefen(wert: str | None) -> str:
    """A known sampler, or the empty string for "no switch": sd.cpp then
    picks its own for the model (``sd_get_default_sample_method``: euler for
    a DiT model, lcm for PiD, euler_a otherwise), on sd-cli as on the
    server. An unknown name keeps the program's own."""
    if not wert:
        return ""
    return wert if wert in SAMPLER else SAMPLER_VORGABE


def scheduler_pruefen(wert: str | None) -> str:
    """A known scheduler, or the empty string for "no switch": sd-cli then
    picks its own, model-specific one (``sd-cli --help``: "default:
    model-specific") — the start value of every family in the table
    (``app/image_families.py``). Unset (None) keeps the program's own."""
    if wert == "":
        return ""
    return wert if wert in SCHEDULER else SCHEDULER_VORGABE


def vae_format_pruefen(wert: str | None) -> str:
    return wert if wert in VAE_FORMATE else ""


def rng_pruefen(wert: str | None) -> str:
    return wert if wert in RNG_WERTE else RNG_VORGABE


def weight_type_pruefen(wert: str | None) -> str:
    return wert if wert in WEIGHT_TYPES else ""


def live_preview_pruefen(wert: str | None) -> str:
    return wert if wert in LIVE_PREVIEW_WERTE else ""


def prediction_pruefen(wert: str | None) -> str:
    return wert if wert in PREDICTION_WERTE else ""


def lora_apply_mode_pruefen(wert: str | None) -> str:
    return wert if wert in LORA_APPLY_MODE else LORA_APPLY_MODE_VORGABE
