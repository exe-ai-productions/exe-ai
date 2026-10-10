"""The one table of sd.cpp's further switches, and every place they travel.

The picture window has had its own field for each setting it knew so far.
The switches here are the rest of what sd-cli (build 920) takes for a
picture — tileable output, the cache modes, the attention and convolution
options, the finer ADetailer and sampler values, IP-Adapter, PhotoMaker v2,
VAE tiles, the memory options. Each is one row below, and the same row feeds
every layer: the request check, the sd-cli command line, the picture
server's start flags or its request body, and the window (over
``GET /api/v1/bild/switches``). A switch added here is offered everywhere at
once.

Every switch starts unset, and an unset switch sends nothing — so a request
that never mentions one draws exactly as before. No switch carries a range
this program made up: a limit stands only where sd.cpp itself names one
(``--help`` or the check that refuses a value), everything else is left to
sd.cpp's own check, whose words reach the window verbatim.

Values of a ``key=value`` list switch (``--extra-sample-args``,
``--extra-ad-args``) are joined into the one flag sd-cli reads, after the
free-text value the window already had — sd-cli takes only the last copy of
a flag, so two copies would drop the first.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from app import bildwahlen


@dataclass(frozen=True)
class Switch:
    key: str
    # bool | int | float | choice | text | file | picture
    kind: str
    # The block of the picture window the switch sits in.
    group: str
    # sd-cli's switch. Empty for a key that rides in a key=value list.
    flag: str = ""
    # The key=value list flag this key rides in, and its name there.
    list_flag: str = ""
    arg: str = ""
    choices: tuple[str, ...] = ()
    # Where the value goes in the picture server's ``/sdcpp/v1/img_gen``
    # body, as a dotted path. Empty: a start flag of the server.
    body: str = ""
    # A file switch: the folder below the image models its file lies in.
    folder: str = ""
    # What has to be on for the switch to act at all: ``ad_model``,
    # ``photomaker``, ``hires``, ``cache_mode``, ``vae_tiling``,
    # ``ip_adapter``, ``ref_video``. Without it the value is dropped, so a
    # control that would act on nothing sends nothing.
    needs: str = ""
    low: float | None = None
    high: float | None = None
    # A property of the machine the pictures are drawn on rather than of a
    # picture — kept for the session like the other memory fields, never
    # stored with a chat (app/bildfensterwahl.py).
    machine: bool = False
    # True: acts on a video only; False: on a still picture only; None: on
    # both. Dropped where it does not act, like an unmet ``needs``.
    video: bool | None = None


_TRUE_FALSE = ("true", "false")
_SAMPLE = "--extra-sample-args"
_AD = "--extra-ad-args"
TILING = "--extra-tiling-args"
# Where the IP-Adapter models lie. The CLIP vision encoder it needs sits with
# the other encoders.
IP_ADAPTER_FOLDER = "ipadapter"
_ENCODERS = "text_encoders"
_PHOTOMAKER = bildwahlen.PHOTOMAKER_ORDNER

# sd-cli's cache modes, from its --help.
CACHE_MODES = ("easycache", "ucache", "dbcache", "taylorseer", "cache-dit", "spectrum")
# The picture formats whose metadata this program can strip (PNG, JPEG, WebP).
OUTPUT_FORMATS = ("png", "jpg", "webp")
# The containers a video is written in (sd-cli --help, "-o": .avi, .webm and
# animated .webp; the server's vid_gen defaults to webm, api.md).
VIDEO_FORMATS = ("webm", "webp", "avi")
# Where the sound files lie that a video is driven by or refers to (WAV,
# sd-cli --help "--audio", "--ref-audio"), and AnimateDiff's motion modules.
AUDIO_FOLDER = "audio"
MOTION_FOLDER = "animatediff"


def _sample(key: str, kind: str, choices: tuple[str, ...] = ()) -> Switch:
    return Switch(key=f"sample_{key}", kind=kind, group="tuning",
                  list_flag=_SAMPLE, arg=key, choices=choices)


def _ad(key: str, kind: str, choices: tuple[str, ...] = ()) -> Switch:
    return Switch(key=f"ad_{key}", kind=kind, group="face",
                  list_flag=_AD, arg=key, choices=choices, needs="ad_model")


def _high_noise(key: str, kind: str, body: str, choices: tuple[str, ...] = ()) -> Switch:
    """A value of Wan 2.2 A14B's high-noise pass: acts only beside the
    high-noise model."""
    return Switch(key=f"high_noise_{key}", kind=kind, group="tuning",
                  flag=f"--high-noise-{key.replace('_', '-')}", choices=choices,
                  body=f"high_noise_sample_params.{body}", needs="high_noise", video=True)


SWITCHES: tuple[Switch, ...] = (
    # ---- Output ----
    Switch("circular", "bool", "size", flag="--circular"),
    Switch("circularx", "bool", "size", flag="--circularx"),
    Switch("circulary", "bool", "size", flag="--circulary"),
    # Not a flag: sd-cli writes the format the output file's name ends in.
    Switch("output_format", "choice", "size", choices=OUTPUT_FORMATS, body="output_format",
           video=False),
    # "--compression-quality: compression quality of video and JPEG / WebP
    # images"; the server clamps its field to 0..100 (api.md).
    Switch("compression_quality", "int", "size", flag="--compression-quality",
           body="output_compression", low=0, high=100),
    # ---- Model ----
    # sd.cpp refuses a negative count ("qwen_image_layers must be non-negative").
    Switch("qwen_image_layers", "int", "model", flag="--qwen-image-layers",
           body="qwen_image_layers", low=0),
    # ---- Sampling ----
    Switch("timestep_shift", "int", "tuning", flag="--timestep-shift",
           body="sample_params.shifted_timestep"),
    Switch("sampler_rng", "choice", "tuning", flag="--sampler-rng", choices=bildwahlen.RNG_WERTE),
    _sample("guidance_schedule", "text"),
    _sample("apg_eta", "float"),
    _sample("apg_momentum", "float"),
    _sample("apg_norm_threshold", "float"),
    _sample("apg_norm_threshold_smoothing", "float"),
    _sample("slg_uncond", "choice", _TRUE_FALSE),
    _sample("noise_clip_std", "float"),
    _sample("noise_scale_start", "float"),
    _sample("noise_scale_end", "float"),
    _sample("base_shift", "float"),
    _sample("max_shift", "float"),
    _sample("stretch", "float"),
    _sample("terminal", "float"),
    _sample("gamma", "float"),
    _sample("alpha", "float"),
    _sample("beta", "float"),
    _sample("mu", "float"),
    _sample("std", "float"),
    _sample("logsnr_min", "float"),
    _sample("logsnr_max", "float"),
    _sample("resolution_aware", "choice", _TRUE_FALSE),
    _sample("uniform", "choice", _TRUE_FALSE),
    _sample("lms_max_order", "int"),
    _sample("lms_shift", "int"),
    _sample("lms_divisions", "int"),
    _sample("noise_sampler", "choice", ("iid", "brownian_tree")),
    _sample("brownian_tree_rng", "choice", ("cpu", "cuda", "std_default", "sampler_rng")),
    # ---- Speed and caches ----
    Switch("cache_mode", "choice", "memory", flag="--cache-mode", choices=CACHE_MODES,
           body="cache_mode"),
    Switch("cache_option", "text", "memory", flag="--cache-option", body="cache_option",
           needs="cache_mode"),
    Switch("scm_mask", "text", "memory", flag="--scm-mask", body="scm_mask",
           needs="cache_mode"),
    Switch("scm_policy", "choice", "memory", flag="--scm-policy",
           choices=("dynamic", "static"), body="scm_policy_dynamic", needs="cache_mode"),
    Switch("conditioning_cache_size", "int", "memory", flag="--conditioning-cache-size", low=0),
    Switch("fa", "bool", "memory", flag="--fa", machine=True),
    Switch("sage_attn", "bool", "memory", flag="--sage-attn", machine=True),
    Switch("diffusion_conv_direct", "bool", "memory", flag="--diffusion-conv-direct", machine=True),
    Switch("vae_conv_direct", "bool", "memory", flag="--vae-conv-direct", machine=True),
    Switch("linear_scale", "float", "memory", flag="--linear-scale"),
    Switch("attn_scale", "float", "memory", flag="--attn-scale"),
    # ---- Memory ----
    Switch("params_backend", "text", "memory", flag="--params-backend", machine=True),
    Switch("auto_fit", "choice", "memory", flag="--auto-fit", choices=("on", "off"),
           machine=True),
    Switch("eager_load", "bool", "memory", flag="--eager-load", machine=True),
    Switch("mmap", "bool", "memory", flag="--mmap", machine=True),
    Switch("disable_prefetch", "bool", "memory", flag="--disable-prefetch", machine=True),
    Switch("disable_segmented_compute", "bool", "memory", flag="--disable-segmented-compute", machine=True),
    # ---- VAE tiles ----
    Switch("vae_tiling", "bool", "memory", flag="--vae-tiling", body="vae_tiling_params.enabled"),
    Switch("vae_tile_size", "text", "memory", flag="--vae-tile-size",
           body="vae_tiling_params.tile_size", needs="vae_tiling"),
    Switch("vae_tile_overlap", "float", "memory", flag="--vae-tile-overlap",
           body="vae_tiling_params.target_overlap", needs="vae_tiling"),
    Switch("vae_relative_tile_size", "text", "memory", flag="--vae-relative-tile-size",
           body="vae_tiling_params.rel_size", needs="vae_tiling"),
    Switch("force_sdxl_vae_conv_scale", "bool", "memory", flag="--force-sdxl-vae-conv-scale"),
    # ---- Weights ----
    Switch("tensor_type_rules", "text", "memory", flag="--tensor-type-rules"),
    # ---- Highres ----
    Switch("hires_sigmas", "text", "upscale", flag="--hires-sigmas",
           body="hires.custom_sigmas", needs="hires"),
    # sd.cpp refuses anything below 1 ("hires upscale tile size must be positive").
    Switch("hires_upscale_tile_size", "int", "upscale", flag="--hires-upscale-tile-size",
           body="hires.upscale_tile_size", needs="hires", low=1),
    # ---- IP-Adapter ----
    Switch("ip_adapter", "file", "guide", flag="--ip-adapter", folder=IP_ADAPTER_FOLDER),
    # Read by IP-Adapter, and by Wan 2.1's I2V and FLF2V models (docs/wan.md
    # "Download clip_vison_h").
    Switch("clip_vision", "file", "guide", flag="--clip_vision", folder=_ENCODERS,
           needs="ip_adapter|video"),
    Switch("ip_adapter_image", "picture", "guide", flag="--ip-adapter-image",
           body="ip_adapter_image", needs="ip_adapter"),
    Switch("ip_adapter_strength", "float", "guide", flag="--ip-adapter-strength",
           body="ip_adapter_strength", needs="ip_adapter"),
    # ---- Face ----
    Switch("pm_id_embed", "file", "face", flag="--pm-id-embed-path", folder=_PHOTOMAKER,
           needs="photomaker"),
    Switch("pm_style_strength", "float", "face", flag="--pm-style-strength",
           needs="photomaker"),
    _ad("input_size", "int"),
    _ad("nms", "float"),
    _ad("max_detections", "int"),
    _ad("mask_k_largest", "int"),
    _ad("mask_min_ratio", "float"),
    _ad("mask_max_ratio", "float"),
    _ad("dilate_erode", "int"),
    _ad("x_offset", "int"),
    _ad("y_offset", "int"),
    _ad("mask_mode", "choice", ("none", "merge", "merge_invert")),
    _ad("merge_masks", "choice", _TRUE_FALSE),
    _ad("invert_mask", "choice", _TRUE_FALSE),
    _ad("mask_blur", "int"),
    _ad("inpaint_padding", "int"),
    _ad("inpaint_width", "int"),
    _ad("inpaint_height", "int"),
    _ad("denoising_strength", "float"),
    _ad("steps", "int"),
    _ad("cfg_scale", "float"),
    _ad("sample_method", "choice", bildwahlen.SAMPLER),
    _ad("scheduler", "choice", bildwahlen.SCHEDULER),
    _ad("sort_by", "choice", ("none", "left_to_right", "center_to_edge", "area")),
    # ---- Video ----
    # Each in the window block its kind of value sits in, shown only while a
    # video is drawn.
    # Not a flag: sd-cli writes the container its output file's name ends in.
    Switch("video_format", "choice", "size", choices=VIDEO_FORMATS, body="output_format",
           video=True),
    Switch("moe_boundary", "float", "tuning", flag="--moe-boundary", body="moe_boundary",
           video=True),
    Switch("vace_strength", "float", "tuning", flag="--vace-strength", body="vace_strength",
           video=True),
    Switch("temporal_tiling", "bool", "memory", flag="--temporal-tiling",
           body="vae_tiling_params.temporal_tiling", video=True),
    Switch("tiling_temporal_tile_frames", "int", "memory", list_flag=TILING,
           arg="temporal_tile_frames", video=True),
    Switch("tiling_temporal_tile_overlap", "int", "memory", list_flag=TILING,
           arg="temporal_tile_overlap", video=True),
    Switch("motion_module", "file", "model", flag="--motion-module", folder=MOTION_FOLDER,
           video=True),
    Switch("audio", "file", "model", flag="--audio", folder=AUDIO_FOLDER, video=True),
    Switch("ref_audio", "file", "model", flag="--ref-audio", folder=AUDIO_FOLDER, video=True),
    # The sound of a reference video: sd-cli pairs it with ``--ref-video``
    # by position, so it acts only beside one.
    Switch("ref_video_audio", "file", "model", flag="--ref-video-audio", folder=AUDIO_FOLDER,
           needs="ref_video", video=True),
    _high_noise("steps", "int", "sample_steps"),
    _high_noise("cfg_scale", "float", "guidance.txt_cfg"),
    _high_noise("img_cfg_scale", "float", "guidance.img_cfg"),
    _high_noise("guidance", "float", "guidance.distilled_guidance"),
    _high_noise("sampling_method", "choice", "sample_method", bildwahlen.SAMPLER),
    _high_noise("eta", "float", "eta"),
    _high_noise("slg_scale", "float", "guidance.slg.scale"),
    _high_noise("skip_layer_start", "float", "guidance.slg.layer_start"),
    _high_noise("skip_layer_end", "float", "guidance.slg.layer_end"),
    _high_noise("skip_layers", "text", "guidance.slg.layers"),
)

BY_KEY = {switch.key: switch for switch in SWITCHES}

# A text value is one line: sd-cli reads it as one argument, and a line
# break inside it would be a second one on the server's start line.
_TEXT_LIMIT = 500


def get(key: str) -> Switch | None:
    return BY_KEY.get(key)


def check(values: dict) -> dict:
    """The request's switch values, each checked against its row.

    Raises ValueError for an unknown key or a value its row does not take —
    a made-up key is a caller that built the request wrong, not a setting
    to drop quietly. An empty value (None, "", False) is unset and left out.
    File and picture values stay names here; the route resolves them."""
    checked: dict = {}
    for key, value in values.items():
        switch = BY_KEY.get(key)
        if switch is None:
            raise ValueError(f"unknown switch {key}")
        if value is None or value == "" or value is False:
            continue
        checked[key] = _value(switch, value)
    return checked


def _value(switch: Switch, value):
    kind = switch.kind
    if kind == "bool":
        if value is not True:
            raise ValueError(f"{switch.key} takes true or false")
        return True
    if kind in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{switch.key} takes a number")
        if not math.isfinite(value):
            raise ValueError(f"{switch.key} takes a finite number")
        if kind == "int":
            if float(value) != int(value):
                raise ValueError(f"{switch.key} takes a whole number")
            value = int(value)
        else:
            value = float(value)
        if switch.low is not None and value < switch.low:
            raise ValueError(f"{switch.key} is below {switch.low}")
        if switch.high is not None and value > switch.high:
            raise ValueError(f"{switch.key} is above {switch.high}")
        return value
    if not isinstance(value, str):
        raise ValueError(f"{switch.key} takes a text")
    value = value.strip()
    if kind == "choice":
        if value not in switch.choices:
            raise ValueError(f"{switch.key} takes one of {', '.join(switch.choices)}")
        return value
    if len(value) > _TEXT_LIMIT or "\n" in value or "\r" in value:
        raise ValueError(f"{switch.key} takes one line of at most {_TEXT_LIMIT} characters")
    # sd-cli splits its key=value list at every comma, so a comma inside
    # one value would become a key of its own.
    if switch.list_flag and "," in value:
        raise ValueError(f"{switch.key} takes no comma")
    if kind in ("file", "picture") and (value != Path(value).name or value.startswith(".")):
        raise ValueError(f"{switch.key} takes a bare file name")
    return value


def active(values: dict, on: dict[str, bool]) -> dict:
    """The values that act: each switch whose ``needs`` is on (any of the
    names split by ``|``) and that acts on what is drawn, a video or a still
    picture. ``on`` names what is on beside the table — the detector,
    PhotoMaker, the highres pass, the high-noise model, a reference video,
    ``video``; the table's own switches (cache mode, VAE tiles, IP-Adapter)
    are read from ``values`` itself."""
    state = dict(on)
    state["cache_mode"] = bool(values.get("cache_mode"))
    state["vae_tiling"] = bool(values.get("vae_tiling"))
    state["ip_adapter"] = bool(values.get("ip_adapter"))
    video = bool(state.get("video"))

    def acts(switch: Switch) -> bool:
        if switch.video is not None and switch.video != video:
            return False
        return not switch.needs or any(state.get(name) for name in switch.needs.split("|"))

    return {key: value for key, value in values.items() if acts(BY_KEY[key])}


def _text(value) -> str:
    return str(value)


def join_list(*parts: str) -> str:
    """Parts of one ``key=value`` list joined; empty ones left out."""
    return ",".join(part for part in parts if part)


def key_value_list(values: dict, list_flag: str, first: str = "") -> str:
    """The one ``key=value`` list sd-cli reads for ``list_flag``: what came
    before (``first``, the window's own field) followed by the table's keys
    in the table's order."""
    return join_list(first, *(
        f"{switch.arg}={_text(values[switch.key])}"
        for switch in SWITCHES
        if switch.list_flag == list_flag and switch.key in values
    ))


def _flag_parts(switch: Switch, value) -> list[str]:
    if switch.kind == "bool":
        return [switch.flag]
    return [switch.flag, _text(value)]


def cli_parts(values: dict, paths: dict[str, Path]) -> list[str]:
    """The sd-cli switches of the active values, in the table's order.
    ``paths`` holds the resolved file of each file and picture switch.
    The key=value lists and the output format are not here: the caller
    joins the lists with its own field and names the output file."""
    parts: list[str] = []
    for switch in SWITCHES:
        if switch.key not in values or not switch.flag:
            continue
        value = paths[switch.key] if switch.kind in ("file", "picture") else values[switch.key]
        parts += _flag_parts(switch, value)
    return parts


def server_start_parts(values: dict, paths: dict[str, Path]) -> tuple[str, ...]:
    """The switches the picture server can only take at start: every active
    one with no field in its request body."""
    parts: list[str] = []
    for switch in SWITCHES:
        if switch.key not in values or not switch.flag or switch.body:
            continue
        value = paths[switch.key] if switch.kind == "file" else values[switch.key]
        parts += _flag_parts(switch, value)
    return tuple(parts)


def _size(text: str) -> tuple[float, float] | None:
    """``[W]x[H]`` or ``[S]``, as sd-cli reads a tile size."""
    try:
        if "x" in text:
            width, height = text.split("x", 1)
            return float(width), float(height)
        return float(text), float(text)
    except ValueError:
        return None


def _numbers(text: str) -> list[float] | None:
    try:
        return [float(part) for part in text.split(",") if part.strip()]
    except ValueError:
        return None


def _layers(text: str) -> list[int] | None:
    """A layer list as sd-cli takes it — "7,8,9" or "[7,8,9]"."""
    try:
        return [int(part) for part in re.split(r"[\[\],\s]+", text) if part]
    except ValueError:
        return None


def cli_only_reason(values: dict) -> str | None:
    """A value the server's body cannot carry as sd-cli would read it: a
    tile size or a sigma list that is no number. sd-cli then draws it, so
    its own words explain it."""
    for key in ("vae_tile_size", "vae_relative_tile_size"):
        if key in values and _size(values[key]) is None:
            return f"{key} that is no size"
    if "hires_sigmas" in values and _numbers(values["hires_sigmas"]) is None:
        return "hires sigmas that are no list of numbers"
    if "high_noise_skip_layers" in values and _layers(values["high_noise_skip_layers"]) is None:
        return "high-noise skip layers that are no list of numbers"
    # The server reads no sound file: sd-cli alone loads one (sd.cpp
    # examples/cli/main.cpp), and as a start flag of the server either is
    # refused outside video mode (examples/common/common.cpp validate).
    for key in ("audio", "ref_audio", "ref_video_audio"):
        if key in values:
            return f"a sound file ({key})"
    return None


def _put(body: dict, path: str, value) -> None:
    *parents, last = path.split(".")
    node = body
    for name in parents:
        node = node.setdefault(name, {})
    node[last] = value


def body_fields(body: dict, values: dict, picture_b64) -> None:
    """Write the active values with a body field into the server's request
    ``body``. ``picture_b64`` turns a picture switch's key into the base64
    text of its resolved file, the form the server reads."""
    for switch in SWITCHES:
        if switch.key not in values or not switch.body:
            continue
        value = values[switch.key]
        if switch.key == "output_format":
            _put(body, "output_format", "jpeg" if value == "jpg" else value)
        elif switch.key == "scm_policy":
            _put(body, switch.body, value == "dynamic")
        elif switch.key in ("vae_tile_size", "vae_relative_tile_size"):
            width, height = _size(value) or (0.0, 0.0)
            if switch.key == "vae_tile_size":
                _put(body, "vae_tiling_params.tile_size_w", int(width))
                _put(body, "vae_tiling_params.tile_size_h", int(height))
            else:
                _put(body, "vae_tiling_params.rel_size_w", width)
                _put(body, "vae_tiling_params.rel_size_h", height)
        elif switch.key == "hires_sigmas":
            _put(body, switch.body, _numbers(value))
        elif switch.key == "high_noise_skip_layers":
            _put(body, switch.body, _layers(value))
        elif switch.kind == "picture":
            _put(body, switch.body, picture_b64(switch.key))
        else:
            _put(body, switch.body, value)


def output_suffix(values: dict, video: bool = False) -> str:
    """The file ending of the finished picture or video: sd-cli writes the
    format its output file's name ends in. A video is a WebM unless another
    container is chosen, as on the server."""
    if video:
        return f".{values.get('video_format') or VIDEO_FORMATS[0]}"
    chosen = values.get("output_format")
    return f".{chosen}" if chosen in OUTPUT_FORMATS else ".png"


def as_json() -> list[dict]:
    """The table as the picture window reads it."""
    return [
        {
            "key": switch.key,
            "kind": switch.kind,
            "group": switch.group,
            "flag": switch.flag or f"{switch.list_flag} {switch.arg}",
            "choices": list(switch.choices),
            "folder": switch.folder,
            "needs": switch.needs,
            "low": switch.low,
            "high": switch.high,
            "machine": switch.machine,
            "video": switch.video,
        }
        for switch in SWITCHES
    ]


def files(image_folder: Path, folder: str) -> list[str]:
    """The files of one switch folder, by name — hidden ones left out."""
    path = Path(image_folder).expanduser() / folder
    if not path.is_dir():
        return []
    return sorted(
        p.name for p in path.iterdir() if p.is_file() and not p.name.startswith(".")
    )


def file_path(image_folder: Path, folder: str, name: str) -> Path:
    """A switch file's name turned into its path — only a name really in
    its folder."""
    if name not in files(image_folder, folder):
        raise ValueError(f"unknown file {name}")
    return Path(image_folder).expanduser() / folder / name
