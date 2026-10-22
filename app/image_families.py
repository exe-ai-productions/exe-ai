"""The one table of model families: what each one is, which files it reads,
and the values a picture of it starts with.

Every other place that needs to know about a family reads it here — the
picture window (over ``GET /api/v1/bild/familien``), the draw route, the
``draw_image`` tool and the switch builder in ``bildbausatz``. A family added
here is offered everywhere at once; a family missing here is offered nowhere.

Start values come from the place that knows a model best: what its authors
publish (model card, reference code), then the diffusers pipeline, then
sd.cpp's own ``docs/``, then a ComfyUI template — and from sd-cli's own
default where none of them names one (``sd-cli --help``, build 920). The step
count of a family is the one sd.cpp's docs or sd-cli itself start with. A
family whose distilled model is the one people draw with starts at that
model's steps and CFG instead — whoever draws with the slow one sets its
values; elsewhere a variant of the family (``Family.variants``) brings the
distilled model's own. Each value
carries the place it came from, so a reader can check it and a later build
can be compared against it. They are STARTING values: every one of them stays
free in the window, the CFG included.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any

# sd-cli's own defaults, read from ``sd-cli --help`` of build 920.
_CLI = "sd-cli --help (build 920)"


@dataclass(frozen=True)
class StartValues:
    width: int
    height: int
    steps: int
    cfg: float
    # The distilled guidance (``--guidance``) for families whose model has
    # that input; None for families without one.
    guidance: float | None
    sampler: str
    # Empty means "no switch": sd-cli picks its own, model-specific one.
    scheduler: str
    # Where each value above came from, by the field's name.
    sources: dict[str, str] = field(default_factory=dict)
    # ``--flow-shift`` where the docs set one; None leaves sd-cli's own.
    flow_shift: float | None = None
    # A video's frame count and frame rate where the docs set them; None
    # leaves sd-cli's own (one frame, 24 per second).
    frames: int | None = None
    fps: int | None = None
    # ``--vae-format`` and ``--rng`` where the docs start the family with
    # one; empty leaves the program's own (no switch, and ``cuda``).
    vae_format: str = ""
    rng: str = ""
    # Further switches the docs start the family with, by their key in
    # app/image_switches.py. Each has its place in ``sources`` under its key.
    switches: dict[str, Any] = field(default_factory=dict)
    # The noise schedule (``--sigmas``) of a model that is drawn with its own,
    # as the list of numbers both programs take; empty leaves the schedule to
    # the sampler.
    sigmas: str = ""


@dataclass(frozen=True)
class Variant:
    """The models of a family that start elsewhere than the family does — a
    distilled model draws in a few steps without guidance, where the base
    model of the same family needs many."""

    # A regular expression on a lower-case file name: the models it names.
    pattern: str
    # The start values that are these models' own, by the field's name; every
    # other value is the family's.
    own: dict[str, Any]
    # Where each of them came from.
    sources: dict[str, str]

    def start(self, family: StartValues) -> StartValues:
        """The family's start values with the variant's own in their place."""
        return replace(family, **self.own, sources={**family.sources, **self.sources})


@dataclass(frozen=True)
class KitPart:
    """Where one part of a family's kit comes from.

    ``part`` is the field the part fills: a text encoder (``llm``,
    ``t5xxl``, ``clip_l``, ``clip_g``), the ``vae``, or one of the family's
    further parts (``audio_vae``, ``audio_encoder``, ``clip_vision``,
    ``embeddings_connectors``). ``repo`` and ``file``
    are the Hugging Face repository and the file's path inside it, as the
    family's sd.cpp doc names them; ``source`` is the doc's place, so a
    reader can check it. ``when`` is a regular expression on a model's
    lower-case file name for a part only some models of the family take —
    the encoder of one size, the VAE of one version; empty, the part belongs
    to every model of the family.
    """

    part: str
    repo: str
    file: str
    source: str
    when: str = ""
    # True for a part only some models of the family take and that the others
    # do without: a model it does not match keeps its kit (``kit_of_family``)
    # instead of losing it for want of this part.
    optional: bool = False

    @property
    def folder(self) -> str:
        """The sub-folder of the picture folder the part lies in."""
        return "vae" if self.part in ("vae", "audio_vae") else "text_encoders"

    @property
    def name(self) -> str:
        """The file's name in that folder: the last segment of its path."""
        return self.file.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class Family:
    name: str
    # The name people know the family by. A proper name, the same in every
    # language, so it is not a text of the catalogues.
    label: str
    # True when a picture is assembled from several files (a diffusion
    # model plus its text encoders and VAE) instead of one checkpoint.
    kit: bool
    # The text encoder fields a kit of this family reads, in the order
    # sd-cli takes them.
    encoders: tuple[str, ...]
    # The latent channels of the VAE this family decodes with, read from the
    # VAE file's ``decoder.conv_in``. Set, the family needs a VAE beside its
    # diffusion model, and the program picks one by itself where the channels
    # tell it apart (``vae_by_itself``). 16 for the families whose docs
    # decode with Flux's own ``ae.sft`` (measured on ae.safetensors). None
    # where the checkpoint carries its own VAE, or where no file at hand
    # shows the number: then the VAE stays the user's choice — and a family
    # whose kit names a VAE needs one all the same (``needs_vae``).
    vae_channels: int | None
    # What a picture of this family can be asked for, and whether the
    # picture server can draw it (sd-cli draws every one). ``edit`` draws
    # from reference images (``-r``). The video tasks: ``t2v`` from text,
    # ``i2v`` from a first frame (``-i``), ``flf2v`` from a first and a last
    # frame (``--end-img``), ``v2v`` along a control video
    # (``--control-video``).
    tasks: tuple[str, ...]
    on_server: bool
    start: StartValues
    # Further files a kit of this family reads beside its text encoders:
    # ``llm_vision`` (the vision half of a VLM encoder, for editing),
    # ``tokenizer`` (a tokenizer.json), ``uncond_diffusion_model``.
    parts: tuple[str, ...] = ()
    # A further part only some models of the family take, by the regular
    # expression on the model's lower-case file name that a model has to match
    # (the same kind of rule as ``KitPart.when``): (part, expression) pairs.
    # A part named here only is taken by the models it matches; any other is
    # taken by every model of the family (``parts_taken``).
    part_rules: tuple[tuple[str, str], ...] = ()
    # ``--model-args`` the docs start this family with; empty sends none.
    model_args: str = ""
    # True when an edit takes several reference images at once: the
    # families whose reference preset increases or decreases the RoPE index
    # per image (sd.cpp docs/edit.md, "Preset Default Values"), and
    # Qwen-Image 2.1, whose docs say so (docs/qwen_image_2.1.md:40).
    many_references: bool = False
    # True when the family draws an edit only with a LoRA chosen for it: the
    # model alone does not read reference images, the edit comes with a LoRA
    # trained for it (sd.cpp docs/edit.md, "Supported Models": Krea 2 with
    # "Community Edit LoRAs"). A fact for whoever offers the task — the draw
    # itself is not held back by it.
    edit_needs_lora: bool = False
    # The layer count of the family's smallest CLIP text encoder, the most
    # layers ``--clip-skip`` can leave out; None for a family without a CLIP
    # encoder, which has no CLIP skip at all. CLIP-L has 12 (sd.cpp
    # src/conditioning/clip.hpp:274), OpenCLIP-H 24 (:287); SDXL and SD3
    # also read CLIP-L, so its 12 is theirs.
    clip_layers: int | None = None
    # A video model: sd.cpp draws it in video mode only, a single frame
    # included (docs/wan.md:3, "Wan models require -M vid_gen").
    video: bool = False
    # True when the model draws at one frame rate only: sd.cpp sets any other
    # to it with a warning (docs/wan.md, Wan 2.2 S2V draws with 16 frames per
    # second). No window offers the rate then and none is sent.
    fixed_fps: bool = False
    # True when sd.cpp computes a ControlNet for this family: the guide
    # images reach the model only where it is a UNet (SD 1.x, SD 2.x, SDXL
    # and their variants; ``sd_version_is_unet`` in src/stable-diffusion.cpp).
    # For every other family the program ignores the option without a word,
    # so the window does not offer it and a draw does not send it.
    control_net: bool = False
    # The companion kind (app/bildinhalt.py ``companion``) its ``t5xxl``
    # field is filled with by itself: Flux's T5-XXL for most, UMT5-XXL for
    # the Wan models (docs/wan.md "Download umt5_xxl"), none for
    # HunyuanVideo, whose field takes ByT5 (docs/hunyuan_video.md:21) —
    # a header does not tell that one apart, so the field stays the user's.
    t5_kind: str = "t5xxl"
    # Its VAE is a video VAE (3D convolutions), told apart from a picture
    # VAE of the same channel count by the header (app/bildinhalt.py).
    video_vae: bool = False
    # The LLM text encoders this family reads, each as the architecture its
    # GGUF header names and the width of its token embedding. sd.cpp picks
    # the architecture by the family (src/conditioning/conditioner.hpp) and
    # reads the width from the encoder's own weights (src/model/te/llm.hpp),
    # so both have to fit. An LLM is put in by itself only when its header
    # carries one of these pairs; a family without any leaves the field to
    # the user.
    llms: tuple[tuple[str, int], ...] = ()
    # True when sd.cpp cannot load a checkpoint without its text encoder at
    # all, so a start without one is refused. Every other family goes on
    # without an encoder it is not given: sd.cpp warns and fills its values
    # with zeros (SD3 without T5, Flux without CLIP-L), and the picture is drawn.
    needs_text_encoder: bool = False
    # Where each part of this family's kit is fetched from: one entry per
    # text encoder in ``encoders`` and the VAE, and several for a field whose
    # file depends on the model (``KitPart.when``). Empty for a family whose
    # docs name no file that can be fetched as it is.
    kit_parts: tuple[KitPart, ...] = ()
    # Regular expressions on a lower-case file name; one that matches shows
    # the file is a model of this family before it is loaded.
    file_patterns: tuple[str, ...] = ()
    # The models of the family that start elsewhere than the family does.
    # A file name is tried against them in this order, and the first one
    # whose pattern matches is the model's.
    variants: tuple[Variant, ...] = ()
    # The kinds of tiny autoencoder (``bildbausatz.tae_kind`` names a file's)
    # that decode this family's latent space. A file of another kind is not
    # offered with a model of this family and is not taken when it was
    # remembered: it decodes into noise or aborts the draw. Empty where no
    # tiny autoencoder is known to fit.
    tae: tuple[str, ...] = ()


def _cli(**given: str) -> dict[str, str]:
    """Sources: sd-cli's own default for every value the docs leave open,
    the docs' line for each one they name."""
    sources = {
        "width": _CLI, "height": _CLI, "steps": _CLI, "cfg": _CLI,
        "sampler": _CLI + ": euler_a for U-Net models",
        "scheduler": _CLI + ": model-specific",
    }
    sources.update(given)
    return sources


# sd-cli's own sampler when none is named: euler for every DiT model,
# lcm for PiD, euler_a for the U-Net ones.
_DIT_SAMPLER = "sd.cpp src/pipeline/request.cpp:45-55 (euler for DiT models, lcm for PiD)"


def _start(
    source: str, *, width: int = 512, height: int = 512, steps: int = 20,
    cfg: float = 7.0, guidance: float | None = None, sampler: str | None = None,
    flow_shift: float | None = None, named: tuple[str, ...] = (), dit: bool = False,
    frames: int | None = None, fps: int | None = None, scheduler: str = "",
    others: dict[str, str] | None = None,
    vae_format: str = "", rng: str = "", switches: dict[str, Any] | None = None,
) -> StartValues:
    """Start values with ``source`` as the place of every value in
    ``named``. ``others`` names the places of the values that come from
    elsewhere: one value, or several separated by a space, and their place.
    The rest are sd-cli's own — its sampler included, which depends on
    whether the model is a DiT."""
    sources = _cli(**{key: source for key in named})
    if sampler is None:
        sampler = "euler" if dit else "euler_a"
    if dit and "sampler" not in named:
        sources["sampler"] = _DIT_SAMPLER
    sources.update(_places(others))
    return StartValues(
        width=width, height=height, steps=steps, cfg=cfg, guidance=guidance,
        sampler=sampler, scheduler=scheduler, flow_shift=flow_shift, sources=sources,
        frames=frames, fps=fps, vae_format=vae_format, rng=rng, switches=dict(switches or {}),
    )


def _places(others: dict[str, str] | None) -> dict[str, str]:
    """One entry per value from entries that name several, separated by a
    space, for one place."""
    return {name: place for names, place in (others or {}).items() for name in names.split()}


def _variant(word: str, source: str, *, others: dict[str, str] | None = None, **own: Any) -> Variant:
    """The variant of the models whose file name carries ``word`` as a word
    of its own — not inside a longer one — with the start values ``own``.
    ``source`` is the place of each of them, except where ``others`` names
    another one (as in ``_start``)."""
    sources = {**dict.fromkeys(own, source), **_places(others)}
    return Variant(pattern=rf"(?<![a-z]){re.escape(word)}(?![a-z])", own=own, sources=sources)


# A model with the latent consistency weights merged in, of any U-Net family.
_LCM = ("sd.cpp docs/lcm.md (--cfg-scale 1, 2 to 8 steps, --sampling-method lcm); "
        "4 steps as the diffusers docs run it")


# The values of the high-noise pass the docs draw the Wan 2.2 A14B models
# with; they act only beside a high-noise model (app/image_switches.py).
_HIGH_NOISE = {
    "high_noise_cfg_scale": 3.5, "high_noise_sampling_method": "euler", "high_noise_steps": 8,
}
_HIGH_NOISE_NAMES = " ".join(_HIGH_NOISE)
_HIGH_NOISE_WORDS = ("--high-noise-cfg-scale 3.5 --high-noise-sampling-method euler "
                     "--high-noise-steps 8")


def _pid_backbone(pattern: str, vae_format: str) -> Variant:
    """The PiD checkpoints trained on another model than Flux: the VAE and
    its format are the ones of that model, which the file's name carries."""
    return Variant(
        pattern=pattern, own={"vae_format": vae_format},
        sources={"vae_format": "sd.cpp docs/pid.md:18-21 (the VAE of the checkpoint's backbone)"},
    )


# ---- The parts a kit is fetched from, as the sd.cpp docs name them ----

def _part(part: str, repo: str, file: str, doc: str, when: str = "") -> KitPart:
    return KitPart(part=part, repo=repo, file=file, source=f"sd.cpp {doc}", when=when)


_FLUX_T5 = _part("t5xxl", "comfyanonymous/flux_text_encoders", "t5xxl_fp16.safetensors",
                 "docs/flux.md, Download weights")
_FLUX_CLIP_L = _part("clip_l", "comfyanonymous/flux_text_encoders", "clip_l.safetensors",
                     "docs/flux.md, Download weights")
# Flux's VAE. The docs name black-forest-labs/FLUX.1-dev and FLUX.1-schnell
# for it, and neither hands out a file without a login. The same file lies
# open in Comfy-Org/z_image_turbo, the repository docs/z_image.md names for
# Z-Image's own parts (measured: 335,304,388 bytes, the SHA-256 the PiD
# repository's ae.safetensors carries too), so that copy is the one fetched.
_FLUX_VAE_FILE = ("Comfy-Org/z_image_turbo", "split_files/vae/ae.safetensors")


def _flux_vae(doc: str, when: str = "") -> KitPart:
    return _part("vae", *_FLUX_VAE_FILE,
                 f"{doc} (ae.safetensors, fetched from the open copy in Comfy-Org/z_image_turbo)",
                 when)


# Flux.2's VAE. The docs name black-forest-labs/FLUX.2-dev, which hands out
# no file without a login either. docs/ernie_image.md names an open
# repository carrying the same file (measured: 336,213,556 bytes and one
# SHA-256 in Comfy-Org/ERNIE-Image and Comfy-Org/flux2-dev).
_FLUX2_VAE_FILE = ("Comfy-Org/ERNIE-Image", "vae/flux2-vae.safetensors")


def _flux2_vae(doc: str, when: str = "") -> KitPart:
    return _part("vae", *_FLUX2_VAE_FILE,
                 f"{doc} (the Flux.2 VAE, fetched from the open copy in Comfy-Org/ERNIE-Image)",
                 when)


_QWEN_IMAGE_VAE = _part("vae", "Comfy-Org/Qwen-Image_ComfyUI",
                        "split_files/vae/qwen_image_vae.safetensors",
                        "docs/qwen_image.md, Download weights")
_WAN21_VAE_FILE = ("Comfy-Org/Wan_2.1_ComfyUI_repackaged", "split_files/vae/wan_2.1_vae.safetensors")
# UMT5-XXL as docs/wan.md runs it in every example (:70).
_WAN_UMT5 = _part("t5xxl", "city96/umt5-xxl-encoder-gguf", "umt5-xxl-encoder-Q8_0.gguf",
                  "docs/wan.md, Download weights (umt5_xxl, gguf)")
_WAN21_VAE = _part("vae", *_WAN21_VAE_FILE, "docs/wan.md, Download weights (Wan2.1 VAE)")
_WAN_KIT = (_WAN_UMT5, _WAN21_VAE)
# The image encoder of Wan 2.1's I2V and FLF2V models (docs/wan.md, "Download
# clip_vison_h"); every other Wan model draws without one. Wan 2.2 has none.
# The second, high-noise model is Wan 2.2 A14B's alone (docs/wan.md, "Wan2.2
# T2V A14B").
_WAN22_NAME = r"(?<![a-z])wan[-_ ]?2[._]?2"
_WAN21_CLIP_VISION = KitPart(
    part="clip_vision", repo="Comfy-Org/Wan_2.1_ComfyUI_repackaged",
    file="split_files/clip_vision/clip_vision_h.safetensors",
    source="sd.cpp docs/wan.md, Download weights (clip_vision_h)",
    when=r"^(?!.*wan[-_ ]?2[._]?2).*(?<![a-z])(?:i2v|flf2v)", optional=True,
)
# The speech encoder of Wan 2.2 S2V (docs/wan.md, "Download wav2vec2").
_WAN22_S2V_AUDIO_ENCODER = _part(
    "audio_encoder", "Comfy-Org/Wan_2.2_ComfyUI_Repackaged",
    "split_files/audio_encoders/wav2vec2_large_english_fp16.safetensors",
    "docs/wan.md, Download weights (wav2vec2)",
)


# Q8_0 is the quantisation docs/qwen_image.md runs the encoder with (:17); the
# repository names the file with a dot before it.
def _qwen_vl_7b(doc: str) -> KitPart:
    return _part("llm", "mradermacher/Qwen2.5-VL-7B-Instruct-GGUF",
                 "Qwen2.5-VL-7B-Instruct.Q8_0.gguf", f"{doc}, Download weights (gguf)")


# Qwen3-VL 4B at Q4_K_M, as docs/krea2.md (:24) and docs/lingbot_video.md
# (:31) run it; the repository names the file without the dash.
def _qwen3_vl_4b(doc: str) -> KitPart:
    return _part("llm", "Qwen/Qwen3-VL-4B-Instruct-GGUF", "Qwen3VL-4B-Instruct-Q4_K_M.gguf",
                 f"{doc}, Download weights (gguf)")


# Qwen3-VL 8B at Q4_K_M, as docs/boogu_image.md (:20) and docs/ideogram4.md
# (:52) run it, from the repository both name.
def _qwen3_vl_8b(doc: str) -> KitPart:
    return _part("llm", "unsloth/Qwen3-VL-8B-Instruct-GGUF", "Qwen3-VL-8B-Instruct-Q4_K_M.gguf",
                 f"{doc}, Download weights (gguf)")


FAMILIES: tuple[Family, ...] = (
    # ---- One file ----
    Family(
        name="sd15", label="SD 1.5", kit=False, encoders=(), vae_channels=None,
        tae=("taesd",),
        control_net=True,
        # A video with AnimateDiff's motion module beside the checkpoint
        # (docs/animatediff.md), from text or from a first frame.
        tasks=("txt2img", "img2img", "t2v", "i2v"), on_server=True,
        start=_start("sd.cpp docs/animatediff.md:57 (--video-frames 8 --fps 8)",
                     cfg=7.5, frames=8, fps=8, named=("frames", "fps"),
                     others={
                         "cfg": (
                             "github.com/CompVis/stable-diffusion scripts/txt2img.py (its authors' defaults); "
                             "diffusers pipelines/stable_diffusion/pipeline_stable_diffusion.py"
                         ),
                     }),
        clip_layers=12,
        variants=(_variant("lcm", _LCM, steps=4, cfg=1.0, sampler="lcm"),),
    ),
    Family(
        name="sd2", label="SD 2.x", kit=False, encoders=(), vae_channels=None,
        tae=("taesd",),
        control_net=True,
        tasks=("txt2img", "img2img"), on_server=True,
        start=_start(_CLI, cfg=7.5, sampler="dpm++2m",
                     others={
                         "cfg": "diffusers pipelines/stable_diffusion/pipeline_stable_diffusion.py",
                         "sampler": (
                             "diffusers docs/source/en/api/pipelines/stable_diffusion/stable_diffusion_2.md"
                         ),
                     }),
        clip_layers=24,
    ),
    Family(
        name="sdxl", label="SDXL", kit=False, encoders=(), vae_channels=None,
        tae=("taesdxl",),
        control_net=True,
        tasks=("txt2img", "img2img"), on_server=True,
        start=_start("sd.cpp docs/sd.md:14 (-W 1024 -H 1024)",
                     width=1024, height=1024, cfg=5.0, sampler="euler",
                     named=("width", "height"),
                     others={
                         "cfg": (
                             "github.com/Stability-AI/generative-models scripts/demo/streamlit_helpers.py; "
                             "diffusers pipelines/stable_diffusion_xl/pipeline_stable_diffusion_xl.py"
                         ),
                         "sampler": (
                             "github.com/Stability-AI/generative-models scripts/demo/streamlit_helpers.py; "
                             "huggingface.co/stabilityai/stable-diffusion-xl-base-1.0 "
                             "scheduler/scheduler_config.json"
                         ),
                     }),
        clip_layers=12,
        variants=(
            _variant("turbo", "diffusers docs sdxl_turbo.md (512 x 512, 1 step and up to 4, "
                     "guidance off, which is CFG 1)",
                     width=512, height=512, steps=1, cfg=1.0),
            _variant("lcm", _LCM, steps=4, cfg=1.0, sampler="lcm"),
        ),
    ),
    Family(
        name="sdxs", label="SDXS", kit=False, encoders=(), vae_channels=None,
        control_net=True,
        tasks=("txt2img",), on_server=True,
        start=_start("sd.cpp docs/distilled_sd.md:107,118 (--cfg-scale 1 --steps 1)",
                     steps=1, cfg=1.0, named=("steps", "cfg")),
        clip_layers=12,
    ),
    Family(
        name="sd15_pix2pix", label="instruct-pix2pix", kit=False, encoders=(),
        tae=("taesd",),
        control_net=True,
        vae_channels=None, tasks=("edit",), on_server=True,
        start=_start(_CLI, cfg=7.5,
                     others={
                         "cfg": (
                             "github.com/timothybrooks/instruct-pix2pix README (by its authors); "
                             "github.com/timothybrooks/instruct-pix2pix edit_cli.py (by its authors)"
                         ),
                     }),
        clip_layers=12,
    ),
    Family(
        name="sdxl_pix2pix", label="CosXL Edit", kit=False, encoders=(),
        tae=("taesdxl",),
        control_net=True,
        vae_channels=None, tasks=("edit",), on_server=True,
        start=_start("sd.cpp docs/sd.md:14 (-W 1024 -H 1024)",
                     width=1024, height=1024, cfg=5.0, sampler="euler",
                     named=("width", "height"),
                     others={
                         "cfg sampler": (
                             "github.com/comfyanonymous/ComfyUI_examples edit_models/sdxl_edit_model.png "
                             "(linked from the model card)"
                         ),
                     }),
        clip_layers=12,
    ),
    Family(
        name="hidream_o1", label="HiDream-O1-Image", kit=False, encoders=(),
        vae_channels=None, tasks=("txt2img",), on_server=True,
        start=_start("sd.cpp docs/hidream_o1_image.md:15-16 (--cfg-scale 1.0)",
                     width=2048, height=2048, cfg=1.0, flow_shift=1.0, named=("cfg",), dit=True,
                     others={
                         "width height": (
                             "huggingface.co/HiDream-ai/HiDream-O1-Image (model card); "
                             "huggingface.co/HiDream-ai/HiDream-O1-Image-Dev (model card)"
                         ),
                         "flow_shift": "huggingface.co/HiDream-ai/HiDream-O1-Image (model card)",
                     }),
    ),
    # ---- A kit of parts ----
    Family(
        name="sd3", label="SD3, SD3.5", kit=True, encoders=("clip_l", "clip_g", "t5xxl"),
        tae=("taesd3",),
        # Its own VAE: 16 channels like Flux's, but not interchangeable.
        vae_channels=None, tasks=("txt2img",), on_server=True,
        start=_start("sd.cpp docs/sd3.md:17 (-H 1024 -W 1024 --cfg-scale 4.5 --sampling-method euler)",
                     width=1024, height=1024, cfg=4.5, sampler="euler", flow_shift=3.0,
                     named=("width", "height", "cfg", "sampler"), dit=True,
                     others={
                         "flow_shift": (
                             "sd.cpp src/pipeline/diffusion_engine.cpp (the flow shift it sets by itself)"
                         ),
                     }),
        clip_layers=12,
        variants=(
            _variant("turbo", "model card of SD3.5 Large Turbo (4 steps, CFG 1); the sd.cpp docs name none",
                     steps=4, cfg=1.0),
        ),
        # A checkpoint named as including its CLIP encoders is one file and
        # no kit.
        file_patterns=(r"(?<![a-z])sd[-_]?3(?:[._]?5)?(?![0-9a-z])(?!.*incl[-_]?clips)",
                       r"stable[-_]diffusion[-_]3(?!.*incl[-_]?clips)"),
        # The docs name no VAE: the checkpoint carries its own.
        kit_parts=tuple(
            _part(part, "Comfy-Org/stable-diffusion-3.5-fp8", f"text_encoders/{file}",
                  "docs/sd3.md, Download weights")
            for part, file in (("clip_l", "clip_l.safetensors"), ("clip_g", "clip_g.safetensors"),
                               ("t5xxl", "t5xxl_fp16.safetensors"))
        ),
    ),
    Family(
        name="flux", label="Flux", kit=True, encoders=("t5xxl", "clip_l"), vae_channels=16,
        tae=("taef1",),
        tasks=("txt2img", "img2img", "edit"), on_server=True,
        start=StartValues(
            width=1024, height=1024, steps=20, cfg=1.0, guidance=3.5,
            sampler="euler", scheduler="",
            sources=_cli(
                **dict.fromkeys(
                    ("width", "height"),
                    "huggingface.co/black-forest-labs/FLUX.1-dev (model card)",
                ),
                cfg="sd.cpp docs/flux.md:25 (--cfg-scale recommended 1)",
                guidance=_CLI + " (--guidance 3.5)",
                sampler="sd.cpp docs/flux.md:31 (--sampling-method euler)",
            ),
        ),
        clip_layers=12,
        file_patterns=(r"(?<![a-z])flux[-_.]?1(?!\d)",),
        # The distilled model takes no guidance.
        variants=(
            _variant("schnell", "sd.cpp docs/flux.md (flux1-schnell: 4 steps, CFG 1, euler)",
                     steps=4, cfg=1.0, guidance=None),
        ),
        kit_parts=(_FLUX_T5, _FLUX_CLIP_L, _flux_vae("docs/flux.md, Download weights")),
    ),
    Family(
        name="chroma", label="Chroma", kit=True, encoders=("t5xxl",), vae_channels=16,
        tae=("taef1",),
        tasks=("txt2img",), on_server=True,
        start=_start("sd.cpp docs/chroma.md:27 (--sampling-method euler)",
                     width=1024, height=1024, cfg=3.0, sampler="euler", named=("sampler",),
                     dit=True,
                     others={
                         "width height": "diffusers pipelines/chroma/pipeline_chroma.py",
                         "cfg": "huggingface.co/lodestones/Chroma1-HD (model card)",
                     }),
        model_args="chroma_use_dit_mask=false",
        file_patterns=(r"(?<![a-z])chroma(?!\d*[-_]?radiance)(?![a-z])",),
        kit_parts=(
            _part("t5xxl", "comfyanonymous/flux_text_encoders", "t5xxl_fp16.safetensors",
                  "docs/chroma.md, Download weights"),
            _flux_vae("docs/chroma.md, Download weights"),
        ),
    ),
    Family(
        name="chroma_radiance", label="Chroma1-Radiance", kit=True, encoders=("t5xxl",),
        vae_channels=None, tasks=("txt2img",), on_server=True,
        start=_start("sd.cpp docs/chroma_radiance.md:15 (--cfg-scale 4.0 --sampling-method euler)",
                     width=1024, height=1024, cfg=4.0, sampler="euler", named=("cfg", "sampler"),
                     dit=True,
                     others={
                         "width height": (
                             "github.com/Comfy-Org/workflow_templates "
                             "templates/image_chroma1_radiance_text_to_image.json"
                         ),
                     }),
        # The docs name no VAE for it: it draws the picture itself.
        file_patterns=(r"(?<![a-z])chroma\d*[-_]?radiance",),
        kit_parts=(_part("t5xxl", "comfyanonymous/flux_text_encoders", "t5xxl_fp16.safetensors",
                         "docs/chroma_radiance.md, Download weights"),),
    ),
    Family(
        # flux2_ae, 32 channels at decoder.conv_in (measured on
        # flux2-vae.safetensors); Mistral-Small-3.2-24B, whose GGUF names the
        # llama architecture at a width of 5120 (docs/flux2.md; measured on
        # Mistral-Small-3.2-24B-Instruct-2506-Q4_K_M.gguf).
        name="flux2", label="Flux.2", kit=True, encoders=("llm",), vae_channels=32,
        tae=("taef2",),
        llms=(("llama", 5120),),
        tasks=("txt2img", "img2img", "edit"), on_server=True,
        start=StartValues(
            width=1024, height=1024, steps=20, cfg=1.0, guidance=4.0,
            sampler="euler", scheduler="",
            sources=_cli(
                **dict.fromkeys(
                    ("width", "height"),
                    "diffusers pipelines/flux2/pipeline_flux2.py",
                ),
                cfg="sd.cpp docs/flux2.md:19 (--cfg-scale 1.0)",
                guidance=(
                    "huggingface.co/black-forest-labs/FLUX.2-dev (model card); "
                    "diffusers pipelines/flux2/pipeline_flux2.py"
                ),
                sampler="sd.cpp docs/flux2.md:19 (--sampling-method euler)",
            ),
        ),
        many_references=True,
        file_patterns=(r"(?<![a-z])flux[-_.]?2(?!\d)(?![-_.]?klein)",),
        kit_parts=(
            _part("llm", "unsloth/Mistral-Small-3.2-24B-Instruct-2506-GGUF",
                  "Mistral-Small-3.2-24B-Instruct-2506-Q4_K_M.gguf",
                  "docs/flux2.md, Flux.2-dev, Download weights"),
            _flux2_vae("docs/flux2.md, Flux.2-dev, Download weights"),
        ),
    ),
    Family(
        # Flux.2's own VAE; Qwen3 4B for klein 4B and Qwen3 8B for klein 9B
        # (docs/flux2.md), 2560 and 4096 wide (measured on the Qwen3 4B and
        # 8B GGUFs).
        name="flux2_klein", label="Flux.2 klein", kit=True, encoders=("llm",), vae_channels=32,
        tae=("taef2",),
        llms=(("qwen3", 2560), ("qwen3", 4096)),
        tasks=("txt2img", "img2img", "edit"), on_server=True,
        start=_start("sd.cpp docs/flux2.md:45 (--cfg-scale 1.0 --steps 4)",
                     width=1024, height=1024, steps=4, cfg=1.0, named=("steps", "cfg"), dit=True,
                     others={
                         "width height": "huggingface.co/black-forest-labs/FLUX.2-klein-4B (model card)",
                     }),
        many_references=True,
        file_patterns=(r"(?<![a-z])flux[-_.]?2[-_.]?klein",),
        # The model that is not distilled.
        variants=(
            _variant("base", "sd.cpp docs/flux2.md (flux-2-klein-base: 20 steps, CFG 4)",
                     steps=20, cfg=4.0),
        ),
        # The encoder goes with the model's size, which the name carries. The
        # docs name the GGUF repository of each without a file; Q4_K_M is the
        # quantisation the same doc runs Flux.2-dev's encoder with (:19).
        kit_parts=(
            _part("llm", "unsloth/Qwen3-4B-GGUF", "Qwen3-4B-Q4_K_M.gguf",
                  "docs/flux2.md, Flux.2 klein 4B, Download weights (gguf)", r"(?<![0-9])4b"),
            _part("llm", "unsloth/Qwen3-8B-GGUF", "Qwen3-8B-Q4_K_M.gguf",
                  "docs/flux2.md, Flux.2 klein 9B, Download weights (gguf)", r"(?<![0-9])9b"),
            _flux2_vae("docs/flux2.md, Flux.2 klein, Download weights"),
        ),
    ),
    Family(
        # Flux.2's own VAE and Qwen3-VL 4B (docs/flux3.md), whose GGUF names
        # the qwen3vl architecture at a width of 2560 (measured on
        # Qwen3-VL-4B-Instruct-Q4_K_M.gguf).
        name="flux3_klein", label="FLUX.3 Klein", kit=True, encoders=("llm",), vae_channels=32,
        tae=("taef2",),
        llms=(("qwen3vl", 2560),),
        tasks=("txt2img", "edit"), on_server=True,
        start=_start("sd.cpp docs/flux3.md:27 (--cfg-scale 1.0 --steps 16 --sampling-method euler)",
                     width=1024, height=1024, steps=16, cfg=1.0, sampler="euler",
                     named=("steps", "cfg", "sampler"), dit=True,
                     others={
                         "width height": (
                             "github.com/Comfy-Org/workflow_templates "
                             "templates/image_flux3_klein_t2i.json"
                         ),
                     }),
        # An edit takes up to ten reference images (docs/flux3.md:38).
        many_references=True,
        file_patterns=(r"(?<![a-z])flux[-_.]?3(?!\d)",),
        # The model that is not distilled.
        variants=(
            _variant("base", "sd.cpp docs/flux3.md:43 (flux-3-image-klein-base: 20 steps, CFG 3.5)",
                     steps=20, cfg=3.5),
        ),
        kit_parts=(
            _qwen3_vl_4b("docs/flux3.md"),
            _flux2_vae("docs/flux3.md, Download weights"),
        ),
    ),
    Family(
        # Flux.2's own VAE and Qwen3.5 9B, whose GGUF names the qwen35
        # architecture at a width of 4096 (measured on
        # Qwen3.5-9B-Q4_K_M.gguf); its vocabulary is not the embedded Qwen
        # one, so the tokenizer file goes with it (docs/moss_image.md:16).
        name="moss_image", label="MOSS-Image", kit=True, encoders=("llm",), vae_channels=32,
        tae=("taef2",),
        llms=(("qwen35", 4096),),
        tasks=("txt2img",), on_server=True,
        start=_start("sd.cpp docs/moss_image.md:23 (--cfg-scale 3.0 -H 1024 -W 1024)",
                     width=1024, height=1024, steps=50, cfg=3.0, sampler="euler",
                     named=("width", "height", "cfg"), dit=True,
                     others={
                         "steps sampler": (
                             "huggingface.co/OpenMOSS-Team/MOSS-Image-Base (model card: "
                             "50 steps, flow-matching Euler)"
                         ),
                     }),
        parts=("tokenizer",),
        file_patterns=(r"(?<![a-z])moss[-_]?image",),
        kit_parts=(
            _part("llm", "unsloth/Qwen3.5-9B-GGUF", "Qwen3.5-9B-Q4_K_M.gguf",
                  "docs/moss_image.md, Download weights (gguf)"),
            _part("tokenizer", "OpenMOSS-Team/MOSS-Image-Base", "tokenizer/tokenizer.json",
                  "docs/moss_image.md, Download weights"),
            _flux2_vae("docs/moss_image.md, Download weights"),
        ),
    ),
    Family(
        # Draws in pixel space: no VAE (docs/iris.md:3). Qwen3-VL 4B reads
        # the text.
        name="iris", label="Iris-3B", kit=True, encoders=("llm",), vae_channels=None,
        llms=(("qwen3vl", 2560),),
        tasks=("txt2img",), on_server=True,
        start=_start("sd.cpp docs/iris.md:16 (--cfg-scale 3 -H 1024 -W 1024)",
                     width=1024, height=1024, steps=100, cfg=3.0, sampler="euler",
                     named=("width", "height", "cfg"), dit=True,
                     others={
                         "steps sampler": (
                             "huggingface.co/speridlabs/iris-3b (model card: "
                             "100 steps, deterministic flow-Euler)"
                         ),
                     }),
        file_patterns=(r"(?<![a-z])iris[-_.]?3b",),
        kit_parts=(_qwen3_vl_4b("docs/iris.md"),),
    ),
    Family(
        # Qwen3 4B (docs/z_image.md), 2560 wide (measured on a Qwen3 4B GGUF).
        name="zimage", label="Z-Image", kit=True, encoders=("llm",), vae_channels=16,
        tae=("taef1",),
        llms=(("qwen3", 2560),),
        tasks=("txt2img", "img2img"), on_server=True,
        start=_start("sd.cpp docs/z_image.md:24 (-H 1024 --steps 8 --cfg-scale 1.0)",
                     width=1024, height=1024, steps=8, cfg=1.0, flow_shift=3.0,
                     named=("height", "steps", "cfg"), dit=True,
                     others={
                         "width": "huggingface.co/Tongyi-MAI/Z-Image-Turbo (model card)",
                         "flow_shift": (
                             "huggingface.co/Tongyi-MAI/Z-Image-Turbo scheduler/scheduler_config.json"
                         ),
                     }),
        file_patterns=(r"(?<![a-z])z[-_]?image",),
        kit_parts=(
            _part("llm", "unsloth/Qwen3-4B-Instruct-2507-GGUF", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
                  "docs/z_image.md, Download weights"),
            _flux_vae("docs/z_image.md, Download weights"),
        ),
    ),
    Family(
        # Qwen2.5-VL 7B (docs/qwen_image.md), whose GGUF names the qwen2vl
        # architecture at a width of 3584 (measured on
        # Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf).
        name="qwen_image", label="Qwen-Image", kit=True, encoders=("llm",), vae_channels=None,
        tae=("taew2_1",),
        llms=(("qwen2vl", 3584),),
        tasks=("txt2img", "edit"), on_server=True,
        start=_start("sd.cpp docs/qwen_image.md:17 (--sampling-method euler --flow-shift 3)",
                     width=1328, height=1328, cfg=4.0, sampler="euler", flow_shift=3.0,
                     named=("sampler", "flow_shift"), dit=True,
                     others={
                         "width height": "github.com/QwenLM/Qwen-Image README.md",
                         "cfg": (
                             "github.com/QwenLM/Qwen-Image README.md; "
                             "diffusers pipelines/qwenimage/pipeline_qwenimage.py"
                         ),
                     }),
        parts=("llm_vision",), many_references=True,
        file_patterns=(r"(?<![a-z])qwen[-_ ]?image(?![-_ ]?(2[._]?1|layered))",),
        variants=(
            _variant("lightning", "diffusers docs qwenimage.md (Qwen-Image-Lightning: 8 steps, "
                     "CFG 1)",
                     steps=8, cfg=1.0),
        ),
        kit_parts=(_qwen_vl_7b("docs/qwen_image.md"), _QWEN_IMAGE_VAE),
    ),
    Family(
        # Qwen3-VL 8B (docs/qwen_image_2.1.md), whose GGUF names the qwen3vl
        # architecture at a width of 4096 (measured on
        # Qwen3VL-8B-Instruct-Q8_0.gguf; the 4B of Krea 2 is 2560 wide).
        name="qwen_image_2_1", label="Qwen-Image 2.1", kit=True, encoders=("llm",),
        tae=("taeqi2_1",),
        llms=(("qwen3vl", 4096),),
        # sd-cli draws from a start picture and through a mask with it
        # (measured: the layout of the start picture stays, and the part
        # outside the mask stays as it was), as it does from text and from
        # references.
        vae_channels=None, tasks=("txt2img", "img2img", "edit"), on_server=True,
        start=_start("sd.cpp docs/qwen_image_2.1.md:26 (--sampling-method euler)",
                     width=2048, height=2048, cfg=1.0, sampler="euler", named=("sampler",),
                     dit=True,
                     others={
                         "width height": "github.com/QwenLM/Qwen-Image-2.1 README.md",
                         "cfg": (
                             "diffusers pipelines/qwenimage21/pipeline_qwenimage21.py; "
                             "github.com/QwenLM/Qwen-Image-2.1 README.md"
                         ),
                     }),
        parts=("llm_vision",), many_references=True,
        file_patterns=(r"(?<![a-z])qwen[-_ ]?image[-_ ]?2[._]?1",),
        kit_parts=(
            # Q4_K_M as the doc runs it (:26); its own VAE, which no earlier
            # Qwen-Image VAE stands in for (:17).
            _part("llm", "Qwen/Qwen3-VL-8B-Instruct-GGUF", "Qwen3VL-8B-Instruct-Q4_K_M.gguf",
                  "docs/qwen_image_2.1.md, Download weights (gguf)"),
            _part("vae", "Comfy-Org/Qwen-Image-2.1", "vae/qwen_image_2.1_vae_bf16.safetensors",
                  "docs/qwen_image_2.1.md, Download weights"),
            # The vision half of the same Qwen3-VL, which --llm_vision takes
            # for editing from references (docs/qwen_image_edit.md).
            _part("llm_vision", "Qwen/Qwen3-VL-8B-Instruct-GGUF",
                  "mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf",
                  "docs/qwen_image_edit.md, --llm_vision takes the mmproj file"),
        ),
        variants=(
            _variant("turbo", "sd.cpp docs/qwen_image_2.1.md, Turbo (--sigmas qwen-image-2.1-turbo "
                     "--steps 8 --cfg-scale 1.0 --sampling-method euler); the preset's nine numbers",
                     steps=8, cfg=1.0, sampler="euler",
                     sigmas="1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0.0"),
        ),
    ),
    Family(
        name="qwen_image_layered", label="Qwen Image Layered", kit=True, encoders=("llm",),
        tae=("taew2_1",),
        vae_channels=None, tasks=("edit",), on_server=True,
        start=_start(_CLI, width=640, height=640, cfg=4.0, dit=True,
                     others={
                         "width height": "github.com/QwenLM/Qwen-Image-Layered README.md",
                         "cfg": (
                             "github.com/QwenLM/Qwen-Image-Layered README.md; "
                             "diffusers pipelines/qwenimage/pipeline_qwenimage_layered.py"
                         ),
                     }),
        parts=("llm_vision",), many_references=True,
    ),
    Family(
        # Qwen3-VL 4B (docs/krea2.md), whose GGUF names the qwen3vl
        # architecture at a width of 2560 (measured on
        # Qwen3-VL-4B-Instruct-Q4_K_M.gguf).
        name="krea2", label="Krea 2", kit=True, encoders=("llm",), vae_channels=None,
        tae=("taew2_1",),
        llms=(("qwen3vl", 2560),),
        # sd-cli draws from a start picture and through a mask with it, as
        # it does from text and from references.
        tasks=("txt2img", "img2img", "edit"), on_server=True, edit_needs_lora=True,
        # The one command the sd.cpp docs give for the distilled model runs
        # it in 8 steps at CFG 1.
        start=_start("sd.cpp docs/int8_convrot.md:105 (--steps 8 --cfg-scale 1)",
                     width=1024, height=1024, steps=8, cfg=1.0, flow_shift=1.15,
                     named=("steps", "cfg"), dit=True,
                     others={
                         "width height": (
                             "github.com/Comfy-Org/workflow_templates templates/image_krea2_turbo_t2i.json"
                         ),
                         "flow_shift": "huggingface.co/krea/Krea-2-Turbo (model card)",
                     }),
        many_references=True,
        file_patterns=(r"(?<![a-z])krea[-_]?2",),
        kit_parts=(
            _qwen3_vl_4b("docs/krea2.md"),
            _part("vae", *_WAN21_VAE_FILE, "docs/krea2.md, Download weights"),
        ),
    ),
    Family(
        name="lens", label="Lens", kit=True, encoders=("llm",), vae_channels=None,
        tae=("taef2",),
        tasks=("txt2img",), on_server=True,
        start=_start("sd.cpp docs/lens.md (lens_turbo: 4 steps, CFG 1)",
                     width=1440, height=1440, steps=4, cfg=1.0, named=("steps", "cfg"), dit=True,
                     others={
                         "width height": (
                             "huggingface.co/microsoft/Lens (model card); "
                             "github.com/Comfy-Org/workflow_templates templates/image_lens_t2i.json"
                         ),
                     }),
        parts=("tokenizer",),
        # Its own files begin with the name; anywhere else "lens" is a word.
        file_patterns=(r"^lens(?![a-z])",),
        kit_parts=(
            _part("llm", "unsloth/gpt-oss-20b-GGUF", "gpt-oss-20b-UD-Q8_K_XL.gguf",
                  "docs/lens.md, Download weights (the file the doc runs, :25)"),
            _flux2_vae("docs/lens.md, Download weights"),
        ),
    ),
    Family(
        name="pid", label="PiD", kit=True, encoders=("llm",), vae_channels=16,
        tasks=("edit",), on_server=True,
        start=_start("sd.cpp docs/pid.md:30 (--cfg-scale 1.0 --steps 4 -H 2048 -W 2048)",
                     width=2048, height=2048, steps=4, cfg=1.0,
                     named=("width", "height", "steps", "cfg"), sampler="lcm", dit=True,
                     vae_format="flux", rng="cpu",
                     others={"vae_format rng": "sd.cpp docs/pid.md:30 (--vae-format flux --rng cpu)"}),
        parts=("tokenizer",),
        file_patterns=(r"(?<![a-z])pid[-_]",),
        # Flux and Z-Image checkpoints decode in Flux's format, the family's
        # own start; the others in the format of their backbone. A name that
        # shows none starts like the docs' example.
        variants=(
            _pid_backbone(r"flux[-_.]?2(?!\d)", "flux2"),
            _pid_backbone(r"sd[-_.]?3(?!\d{2})", "sd3"),
            _pid_backbone(r"(?<![a-z])qwen(?![a-z])", "wan"),
        ),
        # The VAE is the one of the model the checkpoint was trained on, which
        # its name carries (docs/pid.md, "the VAE that matches the PiD
        # checkpoint backbone").
        kit_parts=(
            _part("llm", "Comfy-Org/PixelDiT", "text_encoders/gemma_2_2b_it_elm_bf16.safetensors",
                  "docs/pid.md, Download weights"),
            _flux_vae("docs/pid.md, Download weights: Flux PiD", r"flux[-_.]?1(?!\d)"),
            _flux2_vae("docs/pid.md, Download weights: Flux.2 PiD", r"flux[-_.]?2(?!\d)"),
        ),
    ),
    Family(
        # A kit: the diffusion model, an LLM with its tokenizer, the
        # embeddings connectors and Flux.2's VAE (docs/llada_image.md). It
        # starts where the docs draw the turbo model; no header and no file
        # name known here tells the base model (50 steps, :5) apart. Where
        # its parts are fetched from is not entered: no kit parts.
        name="llada_image", label="LLaDA-Image", kit=True, encoders=("llm",), vae_channels=32,
        tae=("taef2",),
        tasks=("txt2img", "edit"), on_server=True,
        start=_start("sd.cpp docs/llada_image.md:100-103 (1024 x 1024, 4 steps, CFG 1.0)",
                     width=1024, height=1024, steps=4, cfg=1.0,
                     named=("width", "height", "steps", "cfg"), dit=True),
        parts=("tokenizer", "embeddings_connectors"),
        file_patterns=(r"(?<![a-z])llada",),
    ),
    Family(
        # One model in a folder, drawn with the folder as the model
        # (docs/sensenova_u1.md:20): no part beside it, text to image only.
        name="sensenova_u1", label="SenseNova U1.5", kit=False, encoders=(), vae_channels=None,
        tasks=("txt2img",), on_server=True,
        start=_start("sd.cpp docs/sensenova_u1.md:20-31 (--width 2048 --height 2048 --steps 50 "
                     "--cfg-scale 4 --flow-shift 3 --sampling-method euler)",
                     width=2048, height=2048, steps=50, cfg=4.0, sampler="euler", flow_shift=3.0,
                     named=("width", "height", "steps", "cfg", "sampler", "flow_shift"), dit=True),
        file_patterns=(r"(?<![a-z])sensenova",),
    ),
    Family(
        name="longcat", label="LongCat Image", kit=True, encoders=("llm",), vae_channels=16,
        tae=("taef1",),
        # Qwen2.5-VL 7B, the encoder the docs run it with: the pair its GGUF
        # header names, as Qwen-Image's.
        llms=(("qwen2vl", 3584),),
        tasks=("txt2img", "edit"), on_server=True, parts=("llm_vision",),
        start=_start("sd.cpp docs/longcat_image.md:27 (--sampling-method euler --flow-shift 3)",
                     width=1024, height=1024, steps=8, cfg=1.0, sampler="euler", flow_shift=3.0,
                     named=("sampler", "flow_shift"), dit=True,
                     others={
                         "width height": (
                             "diffusers pipelines/longcat_image/pipeline_longcat_image.py; "
                             "github.com/Comfy-Org/workflow_templates "
                             "templates/image_longcat_text_to_image.json"
                         ),
                         "steps cfg": (
                             "model card of LongCat Edit-Turbo (8 steps, CFG 1); the sd.cpp docs name none"
                         ),
                     }),
        file_patterns=(r"(?<![a-z])longcat",),
        kit_parts=(
            _qwen_vl_7b("docs/longcat_image.md"),
            _flux_vae("docs/longcat_image.md, Download weights"),
        ),
    ),
    Family(
        name="minit2i", label="MiniT2I", kit=True, encoders=("t5xxl",), vae_channels=None,
        tasks=("txt2img",), on_server=True,
        start=_start("sd.cpp docs/minit2i.md:17-29 (--steps 100 --cfg-scale 6 --sampling-method euler)",
                     steps=100, cfg=6.0, sampler="euler", named=("steps", "cfg", "sampler"), dit=True),
    ),
    Family(
        name="ovis", label="Ovis-Image", kit=True, encoders=("llm",), vae_channels=16,
        tae=("taef1",),
        tasks=("txt2img",), on_server=True,
        start=_start("sd.cpp docs/ovis_image.md:16 (--cfg-scale 5.0)",
                     width=1024, height=1024, cfg=5.0, named=("cfg",), dit=True,
                     others={
                         "width height": "github.com/AIDC-AI/Ovis-Image README.md",
                     }),
        file_patterns=(r"(?<![a-z])ovis(?![a-z])",),
        kit_parts=(
            _part("llm", "Comfy-Org/Ovis-Image", "split_files/text_encoders/ovis_2.5.safetensors",
                  "docs/ovis_image.md, Download weights"),
            _flux_vae("docs/ovis_image.md, Download weights"),
        ),
    ),
    Family(
        name="ernie", label="ERNIE-Image", kit=True, encoders=("llm",), vae_channels=None,
        tae=("taef2",),
        tasks=("txt2img",), on_server=True,
        start=_start("sd.cpp docs/ernie_image.md (ernie-image-turbo: 8 steps, CFG 1)",
                     width=1024, height=1024, steps=8, cfg=1.0, flow_shift=4.0,
                     named=("steps", "cfg"), dit=True,
                     others={
                         "width height": (
                             "diffusers pipelines/ernie_image/pipeline_ernie_image.py; "
                             "huggingface.co/baidu/ERNIE-Image (model card)"
                         ),
                         "flow_shift": "huggingface.co/baidu/ERNIE-Image scheduler/scheduler_config.json",
                     }),
        file_patterns=(r"(?<![a-z])ernie(?![a-z])",),
        kit_parts=(
            _part("llm", "Comfy-Org/ERNIE-Image", "text_encoders/ministral-3-3b.safetensors",
                  "docs/ernie_image.md, Download weights"),
            _part("vae", "Comfy-Org/ERNIE-Image", "vae/flux2-vae.safetensors",
                  "docs/ernie_image.md, Download weights"),
        ),
    ),
    Family(
        # The standard Flux.2 VAE, passed in every example (sd.cpp
        # docs/sefi_image.md:3,11,35): 32 channels, which the kit cannot
        # start without.
        name="sefi", label="SeFi-Image", kit=True, encoders=("llm",), vae_channels=32,
        tae=("taef2",),
        tasks=("txt2img",), on_server=True,
        start=_start("sd.cpp docs/sefi_image.md:41 (-W 1024 -H 1024)",
                     width=1024, height=1024, steps=4, cfg=1.0, named=("width", "height"), dit=True,
                     others={
                         "steps cfg": "sd.cpp docs/sefi_image.md (sefi_1b_turbo: 4 steps, CFG 1)",
                     }),
    ),
    Family(
        name="anima", label="Anima", kit=True, encoders=("llm",), vae_channels=None,
        tae=("taew2_1",),
        tasks=("txt2img", "edit"), on_server=True,
        start=_start(_CLI, width=1024, height=1024, steps=8, cfg=1.0, sampler="er_sde", dit=True,
                     others={
                         "width height": (
                             "github.com/Comfy-Org/workflow_templates templates/image_anima_base_v1.json; "
                             "huggingface.co/circlestone-labs/Anima (model card)"
                         ),
                         "steps cfg": (
                             "model card of Anima-Turbo (CFG 1, 8 to 12 steps); the sd.cpp docs name none"
                         ),
                         "sampler": "huggingface.co/circlestone-labs/Anima (model card)",
                     }),
        file_patterns=(r"(?<![a-z])anima(?![a-z])",),
        kit_parts=(
            _part("llm", "circlestone-labs/Anima", "split_files/text_encoders/qwen_3_06b_base.safetensors",
                  "docs/anima.md, Download weights"),
            _part("vae", "circlestone-labs/Anima", "split_files/vae/qwen_image_vae.safetensors",
                  "docs/anima.md, Download weights"),
        ),
    ),
    Family(
        name="boogu", label="Boogu Image", kit=True, encoders=("llm",), vae_channels=16,
        # Qwen3-VL 8B, the encoder the docs run it with: the pair its GGUF
        # header names, as Qwen-Image 2.1's.
        llms=(("qwen3vl", 4096),),
        tae=("taef1",),
        tasks=("txt2img", "edit"), on_server=True,
        start=_start(_CLI, width=1024, height=1024, steps=4, cfg=1.0, dit=True,
                     others={
                         "width height": (
                             "github.com/boogu-project/Boogu-Image README.md; "
                             "github.com/boogu-project/Boogu-Image inference.py"
                         ),
                         "steps cfg": (
                             "model card of Boogu Turbo (4 steps, CFG 1); the sd.cpp docs name none"
                         ),
                     }),
        parts=("llm_vision",),
        file_patterns=(r"(?<![a-z])boogu",),
        kit_parts=(
            _qwen3_vl_8b("docs/boogu_image.md"),
            _flux_vae("docs/boogu_image.md, Download weights"),
        ),
    ),
    Family(
        name="mage_flow", label="Mage-Flow", kit=True, encoders=("llm",), vae_channels=None,
        # Qwen3-VL 4B, the encoder the docs run it with: the pair its GGUF
        # header names, as Krea 2's.
        llms=(("qwen3vl", 2560),),
        tasks=("txt2img", "edit"), on_server=True,
        start=_start("sd.cpp docs/mage_flow.md:27,42 (--sampling-method euler)",
                     width=1024, height=1024, steps=4, cfg=1.0, sampler="euler", flow_shift=6.0,
                     named=("sampler",), dit=True,
                     others={
                         "width height flow_shift": "github.com/microsoft/Mage mage_flow/README.md",
                         "steps cfg": "sd.cpp docs/mage_flow.md (Mage-Flow-Turbo: 4 steps, CFG 1)",
                     }),
        parts=("llm_vision",), many_references=True,
        file_patterns=(r"(?<![a-z])mage[-_ ]?flow",),
        kit_parts=(
            _qwen3_vl_4b("docs/mage_flow.md"),
            _part("vae", "Comfy-Org/Mage-Flow", "vae/mage_flow_vae_bf16.safetensors",
                  "docs/mage_flow.md, Download weights"),
        ),
    ),
    Family(
        name="ideogram4", label="Ideogram 4", kit=True, encoders=("llm",), vae_channels=None,
        # Qwen3-VL 8B, the encoder the docs run it with: the pair its GGUF
        # header names, as Qwen-Image 2.1's.
        llms=(("qwen3vl", 4096),),
        tae=("taef2",),
        tasks=("txt2img",), on_server=True,
        start=_start("sd.cpp docs/ideogram4.md:52 (-H 1024 -W 1024)",
                     width=1024, height=1024, named=("width", "height"), dit=True),
        parts=("uncond_diffusion_model",),
        file_patterns=(r"(?<![a-z])ideogram[-_ ]?4",),
        kit_parts=(
            _qwen3_vl_8b("docs/ideogram4.md"),
            _flux2_vae("docs/ideogram4.md, Download weights"),
        ),
    ),
    Family(
        # A 4-channel VAE beside the T5-XXL, SDXL-style for PixArt-Sigma and
        # SD1.x-style for PixArt-Alpha (sd.cpp docs/pixart.md:5-6,15-19,25):
        # the kit cannot start without one, and no header tells which style a
        # 4-channel file is (``_SHARED_VAES``).
        name="pixart", label="PixArt Sigma", kit=True, encoders=("t5xxl",), vae_channels=4,
        tae=("taesd", "taesdxl",),
        tasks=("txt2img",), on_server=True,
        start=_start("sd.cpp docs/pixart.md:25 (--cfg-scale 4.5 -W 1024 -H 1024 --steps 20)",
                     width=1024, height=1024, cfg=4.5, sampler="dpm++2m",
                     named=("width", "height", "cfg", "steps"), dit=True,
                     others={
                         "sampler": (
                             "github.com/PixArt-alpha/PixArt-sigma scripts/inference.py (by its authors); "
                             "huggingface.co/PixArt-alpha/PixArt-Sigma-XL-2-1024-MS "
                             "scheduler/scheduler_config.json"
                         ),
                     }),
    ),
    # ---- Video ----
    # sd.cpp's own versions (src/model_loader.cpp:622-633): one family each.
    # Wan 2.1 T2V, I2V, FLF2V and VACE and Wan 2.2 T2V A14B share one; the
    # A14B models draw with a second, high-noise model beside them.
    Family(
        name="wan", label="Wan 2.1, Wan 2.2 A14B", kit=True, encoders=("t5xxl",),
        tae=("taew2_1",),
        vae_channels=16, tasks=("t2v", "i2v", "flf2v", "v2v"), on_server=True,
        start=_start("sd.cpp docs/wan.md:67 (-W 832 -H 480 --sampling-method euler)",
                     width=832, height=480, cfg=5.0, sampler="euler", flow_shift=5.0, frames=81,
                     fps=16, named=("width", "height", "sampler"), dit=True,
                     switches=_HIGH_NOISE,
                     others={
                         _HIGH_NOISE_NAMES: f"sd.cpp docs/wan.md:93 ({_HIGH_NOISE_WORDS})",
                         "cfg": (
                             "github.com/Wan-Video/Wan2.1 generate.py (by its authors); "
                             "diffusers pipelines/wan/pipeline_wan.py"
                         ),
                         "flow_shift frames": "github.com/Wan-Video/Wan2.1 generate.py (by its authors)",
                         "fps": "github.com/Wan-Video/Wan2.1 wan/configs/shared_config.py",
                     }),
        parts=("high_noise_diffusion_model", "clip_vision"), video=True, t5_kind="umt5",
        video_vae=True,
        # The image encoder is the I2V and FLF2V models' (the name rule of its
        # kit part), the second model Wan 2.2 A14B's.
        part_rules=(
            ("high_noise_diffusion_model", _WAN22_NAME), ("clip_vision", _WAN21_CLIP_VISION.when),
        ),
        # Every Wan 2.1 model, and of Wan 2.2 those the three families below
        # do not take.
        file_patterns=(r"(?<![a-z])wan[-_ ]?2[._]?1",
                       r"(?<![a-z])wan[-_ ]?2[._]?2(?!.*(?:i2v|s2v))"),
        # A model file carrying the word; the LoRA of that name is no model.
        variants=(
            # Its few steps without guidance are the whole draw's: the
            # high-noise pass gets no values of its own, so it follows them.
            _variant("lightx2v", "sd.cpp docs/wan.md (lightx2v: 4 steps, CFG 1)",
                     steps=4, cfg=1.0, switches={}),
        ),
        kit_parts=(*_WAN_KIT, _WAN21_CLIP_VISION),
    ),
    Family(
        name="wan22_i2v", label="Wan 2.2 I2V A14B", kit=True, encoders=("t5xxl",),
        tae=("taew2_1",),
        vae_channels=16, tasks=("i2v", "flf2v"), on_server=True,
        start=_start("sd.cpp docs/wan.md:101 (-W 832 -H 480 --cfg-scale 3.5 --sampling-method euler "
                     "--steps 10)",
                     width=832, height=480, steps=10, cfg=3.5, sampler="euler", flow_shift=5.0,
                     frames=81, fps=16,
                     named=("width", "height", "steps", "cfg", "sampler"), dit=True,
                     switches=_HIGH_NOISE,
                     others={
                         _HIGH_NOISE_NAMES: f"sd.cpp docs/wan.md:101 ({_HIGH_NOISE_WORDS})",
                         "flow_shift": "github.com/Wan-Video/Wan2.2 wan/configs/wan_i2v_A14B.py",
                         "frames fps": "huggingface.co/Wan-AI/Wan2.2-I2V-A14B-Diffusers (model card)",
                     }),
        parts=("high_noise_diffusion_model",), video=True, t5_kind="umt5", video_vae=True,
        file_patterns=(r"(?<![a-z])wan[-_ ]?2[._]?2.*(?<!t)i2v",),
        kit_parts=_WAN_KIT,
    ),
    Family(
        name="wan22_ti2v", label="Wan 2.2 TI2V 5B", kit=True, encoders=("t5xxl",),
        tae=("taew2_2",),
        # Its own VAE, wan2.2_vae (docs/wan.md "for Wan2.2 TI2V 5B only"),
        # with 48 latent channels.
        vae_channels=48, tasks=("t2v", "i2v"), on_server=True,
        start=_start("sd.cpp docs/wan.md:171 (--sampling-method euler)",
                     width=1280, height=704, cfg=5.0, sampler="euler", flow_shift=5.0, frames=121,
                     fps=24, named=("sampler",), dit=True,
                     others={
                         "width height": (
                             "github.com/Wan-Video/Wan2.2 wan/configs/__init__.py (sizes); "
                             "huggingface.co/Wan-AI/Wan2.2-TI2V-5B-Diffusers (model card)"
                         ),
                         "cfg frames": "huggingface.co/Wan-AI/Wan2.2-TI2V-5B-Diffusers (model card)",
                         "flow_shift": "github.com/Wan-Video/Wan2.2 wan/configs/wan_ti2v_5B.py",
                         "fps": (
                             "huggingface.co/Wan-AI/Wan2.2-TI2V-5B-Diffusers (model card); "
                             "github.com/Wan-Video/Wan2.2 README"
                         ),
                     }),
        video=True, t5_kind="umt5", video_vae=True,
        file_patterns=(r"(?<![a-z])wan[-_ ]?2[._]?2.*ti2v",),
        kit_parts=(
            _WAN_UMT5,
            _part("vae", "Comfy-Org/Wan_2.2_ComfyUI_Repackaged",
                  "split_files/vae/wan2.2_vae.safetensors",
                  "docs/wan.md, Download weights (Wan2.2 VAE, for Wan2.2 TI2V 5B only)"),
        ),
    ),
    Family(
        name="wan22_s2v", label="Wan 2.2 S2V 14B", kit=True, encoders=("t5xxl",),
        tae=("taew2_1",),
        # A talking portrait (-i) driven by a sound track (--audio).
        vae_channels=16, tasks=("i2v",), on_server=True,
        start=_start("sd.cpp docs/wan.md:114 (--flow-shift 3.0 --sampling-method euler --steps 20 "
                     "--video-frames 81)",
                     width=1024, height=704, cfg=4.5, sampler="euler", flow_shift=3.0, frames=81,
                     fps=16, named=("sampler", "flow_shift", "frames", "steps"), dit=True,
                     others={
                         "width height": (
                             "github.com/Wan-Video/Wan2.2 README; "
                             "github.com/Wan-Video/Wan2.2 wan/configs/__init__.py (sizes)"
                         ),
                         "cfg": "github.com/Wan-Video/Wan2.2 wan/configs/wan_s2v_14B.py",
                         "fps": (
                             "sd.cpp docs/wan.md; "
                             "github.com/Wan-Video/Wan2.2 wan/configs/shared_config.py"
                         ),
                     }),
        parts=("audio_encoder",), video=True, fixed_fps=True, t5_kind="umt5", video_vae=True,
        file_patterns=(r"(?<![a-z])wan[-_ ]?2[._]?2.*s2v",),
        kit_parts=(*_WAN_KIT, _WAN22_S2V_AUDIO_ENCODER),
    ),
    Family(
        name="ltx", label="LTX-2", kit=True, encoders=("llm",), vae_channels=None,
        # Gemma 3 12B, measured in its GGUF header: architecture ``gemma3``,
        # token embedding 3840 wide.
        llms=(("gemma3", 3840),),
        # Measured: without its Gemma, sd.cpp stops at the first weight of the
        # text encoder it misses.
        needs_text_encoder=True,
        tasks=("t2v", "i2v", "flf2v"), on_server=True,
        start=_start("sd.cpp docs/ltx2.md:58 (-W 1280 -H 720 --sampling-method euler --fps 24)",
                     width=1280, height=720, cfg=3.0, sampler="euler", scheduler="ltx2",
                     frames=121, fps=24, named=("width", "height", "sampler", "fps"), dit=True,
                     others={
                         "cfg frames": (
                             "github.com/Lightricks/LTX-2 "
                             "packages/ltx-pipelines/src/ltx_pipelines/utils/constants.py (by its authors)"
                         ),
                         "scheduler": (
                             "github.com/Lightricks/LTX-2 "
                             "packages/ltx-core/src/ltx_core/components/schedulers.py (LTX2Scheduler); "
                             "sd.cpp src/pipeline/request.cpp (the sampler and scheduler it picks by itself)"
                         ),
                     }),
        parts=("audio_vae", "embeddings_connectors"), video=True,
        file_patterns=(r"(?<![a-z])ltx[-_ ]?2",),
        variants=(
            _variant("distilled", "diffusers docs ltx_video.md (distilled: guidance 1, 4 to 10 "
                     "steps)",
                     steps=8, cfg=1.0),
        ),
        # LTX-2.3's files. LTX-2.5 reads an encoder and a VAE of its own, and
        # the one repository the docs name for them hands out no file without
        # a login, so a 2.5 model comes without a kit.
        kit_parts=(
            # The doc runs gemma-3-12b-it at UD-Q4_K_XL (:58); this is that
            # quantisation in the repository it names.
            _part("llm", "unsloth/gemma-3-12b-it-GGUF", "gemma-3-12b-it-UD-Q4_K_XL.gguf",
                  "docs/ltx2.md, LTX-2.3, Download weights", r"ltx[-_ ]?2[._]3"),
            _part("vae", "unsloth/LTX-2.3-GGUF", "vae/ltx-2.3-22b-dev_video_vae.safetensors",
                  "docs/ltx2.md, LTX-2.3, Download weights", r"ltx[-_ ]?2[._]3"),
            _part("audio_vae", "unsloth/LTX-2.3-GGUF", "vae/ltx-2.3-22b-dev_audio_vae.safetensors",
                  "docs/ltx2.md, LTX-2.3, Download weights", r"ltx[-_ ]?2[._]3"),
            _part("embeddings_connectors", "unsloth/LTX-2.3-GGUF",
                  "text_encoders/ltx-2.3-22b-dev_embeddings_connectors.safetensors",
                  "docs/ltx2.md, LTX-2.3, Download weights", r"ltx[-_ ]?2[._]3"),
        ),
    ),
    Family(
        name="minimax_h3", label="MiniMax-H3", kit=True, encoders=("llm",), vae_channels=None,
        tasks=("t2v", "i2v", "flf2v"), on_server=True,
        start=_start("sd.cpp docs/minimax_h3.md:41 (--cfg-scale 1.0 --fps 24)",
                     width=1344, height=768, cfg=1.0, flow_shift=12.0, frames=124, fps=24,
                     named=("cfg", "fps"), dit=True,
                     others={
                         "width height": (
                             "docs.comfy.org/tutorials/video/minimax/minimax-h3-native; "
                             "github.com/MiniMax-AI/MiniMax-H3 README"
                         ),
                         "flow_shift": (
                             "github.com/MiniMax-AI/MiniMax-H3 scheduler/scheduler_config.json; "
                             "sd.cpp docs/minimax_h3.md"
                         ),
                         "frames": (
                             "sd.cpp docs/minimax_h3.md; "
                             "github.com/MiniMax-AI/MiniMax-H3 README"
                         ),
                     }),
        parts=("llm_vision", "audio_vae"), video=True,
        # Its two models by their own names: the encoder's file carries the
        # family's name too.
        file_patterns=(r"(?<![a-z])minimax[-_ ]?h3[-_ ](?:fl2va|ref2va)",),
        kit_parts=(
            _part("llm", "leejet/MiniMax-H3-GGUF", "qwen3vl_32b_minimax_h3-Q4_K_M.gguf",
                  "docs/minimax_h3.md, Download weights (gguf; the file the doc runs, :41)"),
            _part("vae", "Comfy-Org/MiniMax-H3", "vae/minimax_h3_video_vae_fp16.safetensors",
                  "docs/minimax_h3.md, Download weights"),
            _part("audio_vae", "Comfy-Org/MiniMax-H3", "vae/minimax_h3_audio_vae_fp32.safetensors",
                  "docs/minimax_h3.md, Download weights"),
        ),
    ),
    Family(
        name="hunyuan_video", label="HunyuanVideo 1.5", kit=True, encoders=("llm", "t5xxl"),
        vae_channels=None, tasks=("t2v",), on_server=True,
        # Qwen2.5-VL 7B, the encoder the docs run it with: the pair its GGUF
        # header names, as Qwen-Image's.
        llms=(("qwen2vl", 3584),),
        start=_start("sd.cpp docs/hunyuan_video.md:21 (-W 1280 -H 720 --cfg-scale 6.0 "
                     "--sampling-method euler)",
                     width=1280, height=720, cfg=6.0, sampler="euler", flow_shift=9.0, frames=121,
                     fps=24, named=("width", "height", "cfg", "sampler"), dit=True,
                     others={
                         "flow_shift": (
                             "github.com/Tencent-Hunyuan/HunyuanVideo-1.5 hyvideo/commons/__init__.py; "
                             "huggingface.co/tencent/HunyuanVideo-1.5 (model card)"
                         ),
                         "frames fps": "github.com/Tencent-Hunyuan/HunyuanVideo-1.5 README",
                     }),
        video=True, t5_kind="",
        file_patterns=(r"(?<![a-z])hunyuan[-_ ]?video[-_ ]?1[._]?5",),
        kit_parts=(
            _qwen_vl_7b("docs/hunyuan_video.md"),
            # Its ``t5xxl`` field takes ByT5 (:21).
            _part("t5xxl", "Comfy-Org/HunyuanVideo_1.5_repackaged",
                  "split_files/text_encoders/byt5_small_glyphxl_fp16.safetensors",
                  "docs/hunyuan_video.md, Download weights (byt5 small glyphxl)"),
            _part("vae", "Comfy-Org/HunyuanVideo_1.5_repackaged",
                  "split_files/vae/hunyuanvideo15_vae_fp16.safetensors",
                  "docs/hunyuan_video.md, Download weights"),
        ),
    ),
    Family(
        name="lingbot_video", label="LingBot-Video", kit=True, encoders=("llm",),
        # Qwen3-VL 4B, the encoder the docs run it with: the pair its GGUF
        # header names, as Krea 2's.
        llms=(("qwen3vl", 2560),),
        tae=("taew2_1",),
        # It decodes with Wan 2.1's VAE (docs/lingbot_video.md:3) and takes
        # a first frame with -i (:21).
        vae_channels=16, tasks=("t2v", "i2v"), on_server=True,
        start=_start("sd.cpp docs/lingbot_video.md:31 (--cfg-scale 3)",
                     width=832, height=480, cfg=3.0, flow_shift=3.0, frames=121, fps=24,
                     named=("cfg",), dit=True,
                     others={
                         "width height": (
                             "github.com/robbyant/lingbot-video scripts/single-gpu/run_dense_t2v.sh; "
                             "huggingface.co/robbyant/lingbot-video-dense-1.3b (model card)"
                         ),
                         "flow_shift": (
                             "github.com/robbyant/lingbot-video lingbot_video/runner.py; "
                             "huggingface.co/robbyant/lingbot-video-dense-1.3b (model card)"
                         ),
                         "frames": "github.com/robbyant/lingbot-video README",
                         "fps": (
                             "github.com/robbyant/lingbot-video lingbot_video/runner.py; "
                             "github.com/robbyant/lingbot-video README"
                         ),
                     }),
        video=True, video_vae=True,
        file_patterns=(r"(?<![a-z])lingbot[-_ ]?video",),
        kit_parts=(
            _qwen3_vl_4b("docs/lingbot_video.md"),
            _part("vae", *_WAN21_VAE_FILE, "docs/lingbot_video.md, Download weights"),
        ),
    ),
)

_BY_NAME = {family.name: family for family in FAMILIES}

# The VAEs a header cannot tell apart, by (video VAE, latent channels): Flux's
# VAE and SD3's carry the same names, shapes and types at 16 channels, and so
# do the video VAEs of Wan 2.1 and Qwen-Image (measured on both pairs). A
# 4-channel VAE comes in an SDXL style and an SD1.x style, and one family
# reads either (sd.cpp docs/pixart.md:5-6). Which of them belongs to a model
# is not in any file, so a family decoding with one of them takes its VAE from
# the model's own setting.
_SHARED_VAES = {(False, 16), (True, 16), (False, 4)}


def needs_vae(family: Family) -> bool:
    """Whether a kit of this family cannot start without a VAE: the family
    decodes with one of its own (``vae_channels`` set), or its kit names a
    VAE among its parts. The one place this is decided — the start, the
    drawing and the window all read it."""
    return family.vae_channels is not None or any(part.part == "vae" for part in family.kit_parts)


def vae_by_itself(family: Family) -> bool:
    """Whether the program may put this family's VAE in by itself: only
    where the header of a VAE file tells it apart from every other VAE."""
    return (
        family.vae_channels is not None
        and (family.video_vae, family.vae_channels) not in _SHARED_VAES
    )

# The CLIP layers a model whose family is not known may skip: the smallest
# count any family has, so no encoder is asked for more than it holds.
FALLBACK_CLIP_LAYERS = min(f.clip_layers for f in FAMILIES if f.clip_layers is not None)

# A model whose family the header does not name starts where sd-cli starts
# without being told anything.
CLI_START = _start(_CLI)

# The start values of each family's variants, made once: a model of a variant
# is handed the same values every time it is asked for.
_VARIANT_STARTS = {
    family.name: tuple((variant.pattern, variant.start(family.start)) for variant in family.variants)
    for family in FAMILIES
}


def start_values(name: str | None, file_name: str | None = None) -> StartValues:
    """The values a picture of this family starts with — sd-cli's own for
    a model whose family is not known. Given the model's file name, a model
    the family lists as a variant (``Family.variants``) starts at its own
    values instead."""
    family = get(name)
    if family is None:
        return CLI_START
    if file_name:
        base = file_name.rsplit("/", 1)[-1].lower()
        for pattern, values in _VARIANT_STARTS[family.name]:
            if re.search(pattern, base):
                return values
    return family.start


def get(name: str | None) -> Family | None:
    """The family of this name, or None for an unknown or empty one."""
    return _BY_NAME.get(name or "")


def family_of_file(file_name: str) -> Family | None:
    """The family a model file's name shows, or None for a name that shows
    none. Where several families' patterns match, the one matching first in
    the name wins — a model trained on another carries that one's name
    behind its own — and of two matching at the same place the earlier in
    the table. A name that matches nothing is a file this program does not
    assemble a kit for."""
    base = file_name.rsplit("/", 1)[-1].lower()
    first: tuple[int, Family] | None = None
    for family in FAMILIES:
        for pattern in family.file_patterns:
            found = re.search(pattern, base)
            if found is not None and (first is None or found.start() < first[0]):
                first = (found.start(), family)
    return first[1] if first is not None else None


def kit_of_file(file_name: str) -> tuple[KitPart, ...]:
    """The parts a model file of this name is drawn with: one per field its
    family names a source for. Empty for a name that shows no family, and for
    one whose family names a field's files only for other models
    (``KitPart.when``) — half a kit is none."""
    return kit_of_family(family_of_file(file_name), file_name)


def kit_of_family(family: Family | None, file_name: str) -> tuple[KitPart, ...]:
    """The parts a model file of this family is drawn with — the family
    given, not read from the name: one told by the file's own header. The
    name still picks among the parts only some models of the family take."""
    if family is None:
        return ()
    base = file_name.rsplit("/", 1)[-1].lower()
    chosen: dict[str, KitPart] = {}
    for part in family.kit_parts:
        if part.part not in chosen and (not part.when or re.search(part.when, base)):
            chosen[part.part] = part
    if not {part.part for part in family.kit_parts if not part.optional} <= chosen.keys():
        return ()
    return tuple(chosen.values())


def parts_taken(family: Family | None, file_name: str) -> tuple[str, ...]:
    """The further parts of the family (``Family.parts``) that a model of this
    file name takes: every one, except those the family restricts by the name
    (``Family.part_rules``). One
    rule for the picture-server page, the studio and the start: a part a model
    does not take is neither shown at it nor sent with it."""
    if family is None:
        return ()
    base = file_name.rsplit("/", 1)[-1].lower()
    rules = dict(family.part_rules)
    return tuple(
        part for part in family.parts if not rules.get(part) or re.search(rules[part], base)
    )


def needed_parts(family: Family | None, file_name: str) -> tuple[str, ...]:
    """The further parts of the family (``Family.parts``) that the docs name
    for a standalone diffusion model of this name: the ones its kit fetches
    (``kit_of_family``). A model the docs name no kit for, and a part that
    cannot be fetched as it is (the second, high-noise model), needs none."""
    if family is None:
        return ()
    return tuple(
        part.part for part in kit_of_family(family, file_name) if part.part in family.parts
    )


def known(name: str | None) -> bool:
    return get(name) is not None


def is_kit(name: str | None) -> bool:
    family = get(name)
    return family is not None and family.kit


def draws_from_text(family: Family | None) -> bool:
    """Whether this family turns words into a picture at all.

    Asked at both ends of the drawing tool — where it is offered
    (app/tools/registry.py) and where it is called
    (app/tools/bild_werkzeug.py) — and asked for the same reason at both: a
    window standing at a family that only edits or only makes video must not
    be promised a picture. One predicate, because two spellings of it drift:
    the run outlives its offer, and a family that reads as "draws" on one
    side and as "does not" on the other is a video handed back in a
    picture's place.

    An unknown family (``None``) counts as one that draws: the values then
    come from the file's own header, and a "no" for a name nobody knows
    would turn a working call into a refusal.
    """
    return family is None or "txt2img" in family.tasks


def as_json() -> list[dict]:
    """The table as the picture window and the draw tool read it."""
    return [
        {
            "name": family.name,
            "label": family.label,
            "kit": family.kit,
            "encoders": list(family.encoders),
            "vae_channels": family.vae_channels,
            "needs_vae": needs_vae(family),
            "tasks": list(family.tasks),
            "on_server": family.on_server,
            "parts": list(family.parts),
            "model_args": family.model_args,
            "many_references": family.many_references,
            "edit_needs_lora": family.edit_needs_lora,
            "clip_layers": family.clip_layers,
            "video": family.video,
            "fixed_fps": family.fixed_fps,
            "control_net": family.control_net,
            "tae": list(family.tae),
            "start": {
                "width": family.start.width,
                "height": family.start.height,
                "steps": family.start.steps,
                "cfg": family.start.cfg,
                "guidance": family.start.guidance,
                "sampler": family.start.sampler,
                "scheduler": family.start.scheduler,
                "flow_shift": family.start.flow_shift,
                "frames": family.start.frames,
                "fps": family.start.fps,
                "vae_format": family.start.vae_format,
                "rng": family.start.rng,
                "switches": dict(family.start.switches),
                "sigmas": family.start.sigmas,
                "sources": dict(family.start.sources),
            },
        }
        for family in FAMILIES
    ]
