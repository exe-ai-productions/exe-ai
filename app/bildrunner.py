"""Making a picture on this machine, with nothing leaving it.

The sibling of ``app/modellrunner.py``, and deliberately built the other way
round. A language model is a SERVER: it is started once, holds its weights,
and answers for hours. An image is a single call — the program starts,
loads, draws, writes a file and is gone. Keeping a picture server warm
would hold gigabytes for something that runs for half a minute every few
minutes.

That difference is why there is no port here, no health check and no
orphan to find again after a restart: one call, one image, one file.

**One run at a time.** Two of these side by side would ask the machine for
both models at once, and on a shared memory pool that is how a Mac starts
swapping instead of drawing. The lock is not about the program, it is about
the memory.
"""

from __future__ import annotations

import io
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import NamedTuple
from pathlib import Path

from app import bildbausatz, bildinhalt, image_switches, prozessstopp
from app.bildwahlen import EMBEDDING_ORDNER, HIRES_UPSCALER_FESTE
from app.no_console import no_window
from app.pipe_text import live_text

log = logging.getLogger(__name__)

# The program is called `sd-cli` in the official packages. Looked for on
# PATH first, then in the data folder — the same order as the model server,
# so somebody who installed their own build gets theirs.
PROGRAMM = "sd-cli.exe" if sys.platform == "win32" else "sd-cli"
ORDNER = "stable-diffusion.cpp"

# How long a cancelled generator gets to end before it is killed. Short: the
# caller is holding a request open on this answer, and a program told to stop
# drawing has nothing left to finish.
ABBRUCH_FRIST = 5

# One bar of a painting pass: "|=====>    | 12/28 - 3.10it/s". The unit
# says what a bar counts. A painting pass counts iterations ("it/s", or
# "s/it" when a step takes longer than a second); the bars drawn while
# weights are loaded have the same shape and count megabytes ("MB/s") —
# before the first step and again after the last one — and are no steps of
# any picture, so the pattern does not take them. Its other half is the
# painter's own word that a picture's painting begins (third group).
_SCHRITT_MUSTER = re.compile(
    r"\|\s*(\d+)/(\d+)\s*-\s*[\d.]+(?:s/it|it/s)|(generating image:)"
)

# The detector's own word that it found nothing to repaint: no pass of its
# own follows, so the share must not wait for one.
_NOTHING_DETECTED = re.compile(r"ADetailer detected 0 object")

# The painter's own error lines carry a padded level tag, "[ERROR  ]": the
# tag is space-filled to a fixed width, so the bracket closes after any
# number of blanks.
_ERROR_TAG = re.compile(r"\[ERROR\s*\]")

# The most the log part of a failed picture may carry, crash note included.
LOG_LIMIT = 1200


# Marks the one line the app itself adds to the painter's log, so it never
# reads as something the painter printed. English, like the painter's own
# verbatim lines it stands above.
_APP_NOTE = "[Exe AI] "

# On Windows a crash ends the program with an NTSTATUS code. Masked to 32
# bits, the code reads the same whether it arrives signed (-1073741819) or
# unsigned (0xC0000005); every error status starts at 0xC0000000. The common
# crash codes get their meaning spelled out.
_NTSTATUS_ERROR_START = 0xC0000000
_NTSTATUS_CRASHES = {
    0xC0000005: "access violation",
    0xC00000FD: "stack overflow",
    0xC0000409: "stack buffer overrun",
    0xC000001D: "illegal instruction",
    0xC0000094: "divide by zero",
}


class CrashNote(NamedTuple):
    """How the painter crashed: `name` for the server log, `line` for the
    user, marked as the app's own."""

    name: str
    line: str


def _crash_note(returncode: int | None) -> CrashNote | None:
    """How the painter crashed, read once from its exit code: a short name
    for the server log ("SIGSEGV", "signal 200", "NTSTATUS 0xC0000005") and
    the app's marked note for the user. None for an ordinary exit.

    Windows has no signals: CPython hands the exit code over as the
    unsigned DWORD from GetExitCodeProcess; masking to 32 bits reads it the
    same way should it ever arrive signed, and only error statuses get a
    note. Elsewhere the program is started without a shell, so a death by
    signal arrives as the negative signal number. Any other code is the
    program's own exit status and gets no note. The note stays English,
    like the painter's verbatim lines.
    """
    if returncode is None:
        return None
    if sys.platform == "win32":
        status = returncode & 0xFFFFFFFF
        # exit(-1) reads as 0xFFFFFFFF: the program's own word, no crash.
        if status < _NTSTATUS_ERROR_START or status == 0xFFFFFFFF:
            return None
        name = f"NTSTATUS 0x{status:08X}"
        line = f"Command terminated with {name}"
        meaning = _NTSTATUS_CRASHES.get(status)
        if meaning:
            line += f": {meaning}"
        return CrashNote(name, _APP_NOTE + line)
    if returncode >= 0:
        return None
    number = -returncode
    line = f"Command terminated by signal {number}"
    try:
        name = signal.Signals(number).name
    except ValueError:
        return CrashNote(f"signal {number}", _APP_NOTE + line)
    line += f": {name}"
    description = signal.strsignal(number)
    if description:
        # macOS appends the number itself ("Segmentation fault: 11").
        line += f" ({description.removesuffix(f': {number}')})"
    return CrashNote(name, _APP_NOTE + line)


def _pipe_encoding() -> str:
    """The encoding Popen's own text mode would pick for the pipes, read at
    each run."""
    return io.text_encoding(None)


def tail_lines(lines: list[str], limit: int) -> str:
    """The last whole lines that fit in `limit` characters. Blank lines at
    the end are not counted; a last line longer than the whole limit is cut
    from the front, keeping its end."""
    end = len(lines)
    while end and not lines[end - 1].strip():
        end -= 1
    kept: list[str] = []
    size = 0
    for index in range(end - 1, -1, -1):
        line = lines[index]
        grown = size + len(line) + (1 if kept else 0)
        if grown > limit:
            if not kept:
                kept.append(line[-limit:] if limit > 0 else "")
            break
        kept.append(line)
        size = grown
    return "\n".join(reversed(kept))


class BildFehler(Exception):
    """Carries the key of the sentence to show, not the sentence itself.

    `protokoll` optionally carries the painter's REAL last words — its
    telling lines from stdout and stderr ("[ERROR  ]" lines, asserts), or
    the raw tail when there are none. The painter's lines are shown
    verbatim, never paraphrased: a rewritten error catalogue would only
    hide the one line that explains the crash (house rule). At most one
    line of the app's own stands before them, marked as such: the note
    naming the signal or Windows status that ended a crashed program."""

    def __init__(self, grund: str, protokoll: str | None = None) -> None:
        super().__init__(grund)
        self.grund = grund
        self.protokoll = protokoll


@dataclass(frozen=True)
class LoRA:
    """One LoRA and how strongly it applies.

    ONE strength, and that is not a simplification on our side: sd.cpp
    applies a LoRA with a single multiplier. Separate model and clip
    strengths are not a concept sd.cpp has; offering two fields here would
    mean silently dropping one of them.
    """

    name: str
    staerke: float = 0.70


@dataclass(frozen=True)
class Auftrag:
    """One picture, fully described. Checked before it gets here."""

    modell: Path
    prompt: str
    negativ: str = ""
    breite: int = 512
    hoehe: int = 512
    schritte: int = 20
    cfg: float = 7.0
    seed: int = -1
    # Empty leaves the sampler and the scheduler to sd-cli, which picks the
    # model's own of each.
    sampler: str = ""
    scheduler: str = ""
    # Stackable, in the order they were added — that order is what the
    # prompt syntax carries, so it is what the picture gets.
    loras: tuple[LoRA, ...] = ()
    lora_ordner: Path | None = None
    # sd-cli's own three values (auto, immediately, at_runtime) — free by
    # house rule ("we do not hide what can be shown"), not locked to the one
    # proven safe on this Metal build. The window warns instead of blocking.
    lora_apply_mode: str = "at_runtime"
    # Textual-inversion embeddings: the folder is pointed at, and a file in
    # it is called by its name inside the prompt. Only passed when the
    # folder exists, so the flag never names a place that is not there.
    embd_ordner: Path | None = None
    # PhotoMaker: one person's face, carried into a picture that was never
    # taken. The model does the carrying, the folder holds the photos it
    # learns the face from, and the class word is what makes it fire at all —
    # without it in the prompt the model loads and changes nothing.
    #
    # All three belong together: a model without photos has no face to carry,
    # photos without a model are just files. SDXL only — on an SD-1.5 model
    # the generator ignores the whole thing.
    photomaker: Path | None = None
    gesichter_ordner: Path | None = None
    pm_klasse: str = ""
    # PuLID: face identity carried into a picture through a precomputed
    # embedding file, not a class word in the prompt (that is PhotoMaker's
    # own way, above). Both the weights and the embedding are required
    # together -- weights alone have no face to carry, an embedding alone
    # has nothing to carry it with.
    pulid_weights: Path | None = None
    pulid_id_embedding: Path | None = None
    pulid_id_weight: float = 1.0
    # ControlNet: a second image whose edges/pose/depth steer the drawing,
    # by a preprocessed guide image rather than by words. Since build 920
    # edge detection is one rule of `--image-preprocess` (target=control,
    # canny=true); the old `--canny` switch is gone from sd-cli's own
    # --help. The picture server takes the same rule in its
    # `image_preprocess` field.
    control_net: Path | None = None
    control_image: Path | None = None
    control_strength: float = 0.9
    canny: bool = False
    # An image to start from, and how much of it to paint over. 1.0 means
    # nothing of it survives, which is what a picture made from nothing is —
    # so without a starting image the value never leaves 1.0.
    startbild: Path | None = None
    staerke: float = 1.0
    # Black and white, the starting image's size: white is what gets drawn
    # again. Only means anything beside a starting image — a mask without
    # one has nothing to mask.
    maske: Path | None = None
    # How many of CLIP's last layers to ignore. -1 means "unspecified", which
    # the generator turns into the right value per model class. A few models
    # (notably some SD-1.5 anime checkpoints) were trained expecting one layer
    # skipped and look wrong without it.
    clip_skip: int = -1
    # A standalone VAE — the part that turns the model's internal number-image
    # into real pixels. A model's built-in VAE is often the weak link; the
    # right external one is where washed-out colour and mushy detail come back.
    vae: Path | None = None
    # ADetailer: a small detector that finds faces and redraws each one at
    # full resolution, so a face that came out as a smear in a wide shot is
    # painted again sharp. The model file is the detector (a YOLO net); an
    # empty file means the pass is off.
    ad_modell: Path | None = None
    ad_prompt: str = ""
    # The detailer's own negative prompt. Empty inherits the MAIN negative
    # prompt (sd-cli's own, useful behaviour) — which is exactly why empty
    # must keep the flag off the command line: an explicit "" would break
    # that inheritance.
    ad_negativ: str = ""
    # The detailer's OWN LoRA stack. Deliberately separate from `loras`: a
    # face LoRA in the MAIN prompt drags its style through the whole picture
    # and fights the composition, which is why the practice is to hang it on
    # the detailer alone. These names are written into the ad prompt and
    # nowhere else.
    ad_loras: tuple[LoRA, ...] = ()
    # Detection threshold, sent as `--extra-ad-args confidence=<wert>` —
    # deliberately only this one key of that key=value list. None keeps the
    # flag off and sd-cli's own default applies.
    ad_confidence: float | None = None
    # Flash attention in the diffusion model — faster where the machine can do
    # it, no effect on the picture. ON by default: measured on build 820, the
    # second, high-resolution pass of the highres fix drops from ~30 s per
    # step to ~3.5 s — nine times faster, the difference between a usable
    # highres fix and one that runs past the time limit and gets killed. On
    # build 920 a whole SD-1.5 highres run takes 26 s with it and 207 s
    # without. The persistent server (Image-Turbo) already runs with it. The risk
    # it was held back for — an older sd-cli a user swapped in that predates the
    # flag and refuses the unknown argument — is against the binary we ship, so
    # the default follows our build, not a hypothetical replacement.
    diffusion_fa: bool = True
    # Highres fix: draw at the base size, then upscale and paint over the
    # result at the larger size, so fine detail the first pass could not fit
    # arrives on the second. `hires_scale` is how much larger (2.0 = double);
    # `hires_steps` 0 reuses the main step count. Off by default — it roughly
    # doubles the time, and most drafts do not need it.
    hires: bool = False
    hires_scale: float = 2.0
    hires_steps: int = 0
    # The second pass's own denoise. 0 means "unset" — sd-cli's own default
    # (0.7) then applies WITHOUT the flag on the command line; sd-cli itself
    # refuses an explicit 0, so the sentinel never collides with a real wish.
    hires_denoise: float = 0.0
    # The second pass's upscaler, by NAME: one of sd-cli's built-in names
    # (``bildwahlen.HIRES_UPSCALER_FESTE``), or a model file in the
    # upscaler folder, named without its extension as sd.cpp wants it
    # (the route strips it) — only that second case sends the folder along as
    # `--hires-upscalers-dir`; ``befehl()`` tells the cases apart against
    # the built-in list. Empty stays off the command line, sd-cli's own
    # default (Latent) then applies.
    hires_upscaler: str = ""
    hires_upscalers_ordner: Path | None = None
    # A fixed target size for the second pass. Either one set beats
    # `hires_scale` (sd-cli's own rule: "0 to use --hires-scale"); 0 keeps
    # the flag off entirely.
    hires_width: int = 0
    hires_height: int = 0
    # Sampler fine-tuning, every one of them "unset by default": None/empty
    # keeps the flag off the command line entirely, so sd-cli's own
    # per-sampler defaults keep applying exactly as they do today. An
    # explicit `--eta 0` would be a REAL change for euler_a (its own
    # default is 1), which is why eta's unset is None, not 0.
    eta: float | None = None
    flow_shift: float | None = None
    sigmas: str = ""
    extra_sample_args: str = ""
    # `--prediction` override — empty means "let the program derive it from
    # the model", sd-cli's own behaviour without the flag.
    prediction: str = ""
    # Skip layer guidance (DiT models only): drop the guided pass for a
    # handful of transformer layers between two points in the schedule.
    # `slg_scale` 0 means disabled, sd-cli's own default -- the whole
    # group stays off the command line while it is. `start`/`end` carry
    # sd-cli's own defaults here too, so a field nobody touched sends
    # exactly what sd-cli would already do without it; `skip_layers`
    # empty leaves sd-cli's own default layer set alone.
    slg_scale: float = 0.0
    skip_layer_start: float = 0.01
    skip_layer_end: float = 0.2
    skip_layers: str = ""
    # sd-cli only -- the persistent server answers one request with one
    # finished picture, no channel for a mid-draw preview frame to
    # travel back on. Empty stays off the command line, same as every
    # other unset start-of-scale field here.
    live_preview: str = ""
    # How often the preview is written: positive N every Nth step, -N only
    # after step N, 0 once after the first pass (sd-cli's own reading).
    # None leaves sd-cli's own 1.
    preview_interval: int | None = None
    # The noisy input of the model instead of the denoised picture.
    preview_noisy: bool = False
    # A tiny autoencoder for the "tae" preview — the preview only: the
    # finished picture is still decoded by the real VAE.
    taesd: Path | None = None
    # sd.cpp's further switches (``app.image_switches``), by key: only the
    # ones that act, checked at the request boundary. File and picture
    # switches carry their resolved path in ``switch_paths``. Empty sends
    # nothing, so a request that never names one draws as before.
    switches: dict = field(default_factory=dict)
    switch_paths: dict = field(default_factory=dict)
    # A mode other than drawing, on the finished picture in ``startbild``:
    # "adetailer" repairs what the detector finds (sd-cli -M adetailer),
    # "upscale" enlarges it with ``upscale_model`` (sd-cli -M upscale).
    # Empty draws a picture.
    mode: str = ""
    upscale_model: Path | None = None
    # Collect an importance matrix for quantizing while this picture is
    # drawn (--imat-out), continuing the one already there (--imat-in).
    imatrix: Path | None = None
    # A Bausatz (flux, zimage, flux2): several files assembled instead of one
    # plain model. Set only when ``image_families.is_kit()`` says so — every
    # field here defaults to "unset", so a request that never mentions any of
    # them builds exactly today's Auftrag. ``app.bildbausatz`` knows which of
    # these a given family actually reads; this dataclass just carries them.
    # ``familie`` names which one — checked at the request boundary, never
    # guessed back from which of the fields below happen to be set.
    familie: str | None = None
    diffusion_model: Path | None = None
    t5xxl: Path | None = None
    clip_l: Path | None = None
    clip_g: Path | None = None
    llm: Path | None = None
    vae_format: str = ""
    guidance: float | None = None
    # The further parts some kits read (``Family.parts``): a VLM encoder's
    # vision half, a tokenizer.json, Ideogram 4's unconditional model.
    llm_vision: Path | None = None
    tokenizer: Path | None = None
    uncond_diffusion_model: Path | None = None
    # The video kits' further parts (``bildbausatz.PART_SWITCHES``).
    high_noise_diffusion_model: Path | None = None
    audio_vae: Path | None = None
    audio_encoder: Path | None = None
    embeddings_connectors: Path | None = None
    # A video instead of a still picture (``-M vid_gen``): its frame count
    # and rate (None leaves sd-cli's own), the last frame of a video drawn
    # between two, and the frames of a control video and of a reference
    # video, each in order.
    video: bool = False
    video_frames: int | None = None
    fps: int | None = None
    end_image: Path | None = None
    control_frames: tuple[Path, ...] = ()
    ref_video_frames: tuple[Path, ...] = ()
    # ``--model-args``, as written; empty sends none.
    model_args: str = ""
    # Editing with reference images (``-r``, once per picture, in order).
    # The image CFG, the reference arguments and the index switch only
    # mean anything beside a reference, and stay off without one.
    ref_bilder: tuple[Path, ...] = ()
    img_cfg: float | None = None
    ref_image_args: str = ""
    increase_ref_index: bool = False
    # Memory & devices: start flags, bound to the running server exactly like
    # the Bausatz fields above — a change here means a Turbo restart, and the
    # sd-cli path just gets them fresh on the next call. Every one of them
    # empty/unset means "leave sd-cli's own default alone", so a request that
    # never touches this block builds exactly today's command.
    #
    # RNG is the one exception: the window always sends one of its two
    # values, the same way it always sends a sampler — there is no "let
    # sd-cli decide" option on the field, so there is none here either.
    rng: str = "cuda"
    # sd-cli's own weight-type names (f16, q8_0, q4_K, …) — empty keeps the
    # weight file's own type, which is what "Auto" means on the window.
    weight_type: str = ""
    # -1 is sd-cli's own "use every physical core" default.
    threads: int = -1
    # --max-vram as sd-cli reads it: GiB, or a budget per device
    # ("cuda0=6"); empty lets sd-cli manage it (the switch is omitted).
    vram_limit: str = ""
    offload_to_cpu: bool = False
    # L1: empty means "leave sd-cli's own default alone" for both, same
    # shape as everything else in this block.
    split_mode: str = ""
    backend: str = ""
    # Seconds a picture may take before it is ended (app/bildgeraete.py);
    # None draws without a limit and is stopped by hand. A video has none.
    zeitgrenze: int | None = None


def programm_finden(datenordner: Path) -> Path | None:
    """The sd-cli binary, or nothing if this machine has none.

    PATH first, so somebody who installed their own build gets theirs. Then
    the data folder, which is where the fetch next door puts it — bare for a
    build unpacked by hand, one level down in a build-named folder for a
    fetched one. That second case is what makes the fetch worth having: a
    program nobody can find is a program nobody got.
    """
    gefunden = shutil.which(PROGRAMM)
    if gefunden:
        return Path(gefunden)
    from app.sddownload import gefundenes_programm

    return gefundenes_programm(datenordner)


def modelle(bildordner: Path) -> list[str]:
    """The image models lying in their own folder, by file name.

    A file the content-sniffing catch net (``app.bildinhalt``) is CERTAIN
    is a text encoder or a VAE is excluded here — it belongs in one of the
    companion lists instead (``textversteher()``/``vaes()`` below). A file
    it cannot identify is offered here exactly as before: ``unbekannt``
    means "treat it like an image model", never "hide it".
    """
    ordner = Path(bildordner).expanduser()
    if not ordner.is_dir():
        return []
    ausgeschlossen = {bildinhalt.TEXTVERSTEHER, bildinhalt.VAE}
    # A model can also be a folder: one that holds the index of its shards
    # (``bildinhalt.folder_model``) is offered by the folder's name and
    # handed to sd-cli as it is. Any other folder is none.
    return sorted(
        p.name for p in ordner.iterdir()
        if (p.is_file() and p.suffix in {".gguf", ".safetensors"}
            and bildinhalt.sorte(p) not in ausgeschlossen)
        or bildinhalt.folder_model(p)
    )


def prompt_bauen(
    prompt: str, loras: tuple[LoRA, ...], ad_loras: tuple[LoRA, ...]
) -> str:
    """The main prompt with every LoRA of this picture written into it.

    A LoRA is not a command-line option in this program — it is written into
    the prompt, and the folder is pointed at separately.

    The detailer's LoRAs belong in here too, which reads backwards and is
    not. The engine does NOT read ``<lora:...>`` from ``--ad-prompt``:
    measured against builds 820 and 920, a made-up LoRA name in
    the detailer prompt drew no reaction at all, while the same name in the
    main prompt produced "can not found lora" at once. Written there, the
    stack was passed and never applied.

    What the engine does instead is documented in its own adetailer notes:
    the detail pass REUSES the main pass's LoRA settings. Counted on a real
    run: three loads without the detailer, six with it, the second three
    sitting between "ADetailer detected" and "ADetailer applied". So the
    main prompt is the only place a face LoRA can be written, and from
    there it reaches the face.

    The price is that the weights hang in the main pass as well. The
    division of labour is what keeps that small: only the tag goes here,
    while the trigger WORD stays in the detailer prompt. Without its
    trigger, a character LoRA pulls the main picture far more weakly.

    A LoRA already in the main stack is not added twice — the same name
    written twice only adds up its strength.

    One function because both painters need the same answer: the sd-cli
    command and the persistent server's request body.
    """
    schon_da = set()
    for lora in loras:
        stamm = Path(lora.name).stem
        prompt += f" <lora:{stamm}:{lora.staerke}>"
        schon_da.add(stamm)
    for lora in ad_loras:
        stamm = Path(lora.name).stem
        if stamm not in schon_da:
            prompt += f" <lora:{stamm}:{lora.staerke}>"
            schon_da.add(stamm)
    return prompt


def loras(bildordner: Path) -> list[str]:
    """The LoRA files in their own folder below the image models."""
    ordner = Path(bildordner).expanduser() / "lora"
    if not ordner.is_dir():
        return []
    return sorted(
        p.name for p in ordner.iterdir()
        if p.is_file() and p.suffix in {".gguf", ".safetensors", ".ckpt", ".pt"}
        and not bildinhalt.is_sqlite(p)
    )


def lora_pfad(bildordner: Path, name: str) -> Path:
    """A LoRA NAME turned into a path, under the same rule as a model."""
    if not name or "/" in name or "\\" in name or name != Path(name).name:
        raise BildFehler("bild.lora_unbekannt")
    if name not in loras(bildordner):
        raise BildFehler("bild.lora_unbekannt")
    return Path(bildordner).expanduser() / "lora" / name


# The companion kinds, each in its own subfolder below the image models —
# the same shape as `lora/`, so nothing collides with a model in the picker.
VAE_ORDNER = "vae"
YOLO_ORDNER = "adetailer"
PULID_ORDNER = "pulid"
# What sd.cpp's own PuLID tool writes a face embedding as.
PULID_ENDUNG = ".pulidembd"
CONTROLNET_ORDNER = "controlnet"
# The tiny autoencoders (TAESD, TAE) the live preview can decode with.
TAESD_FOLDER = "taesd"
# Model-backed highres upscalers (ESRGAN-style files). sd-cli takes the
# NAME of a file in here via --hires-upscaler and the folder itself via
# --hires-upscalers-dir — a name, never a path. Upscaling a finished
# picture on its own (sd-cli -M upscale) takes the file itself, which is
# what `upscaler_path()` below resolves.
UPSCALER_ORDNER = "upscaler"
# A Bausatz family's prompt understanding (T5, CLIP, an LLM checkpoint) —
# the one folder the Flux build actually adds; `vae/` already existed.
TEXTVERSTEHER_ORDNER = "text_encoders"


def _im_unterordner(bildordner: Path, unter: str) -> list[str]:
    ordner = Path(bildordner).expanduser() / unter
    if not ordner.is_dir():
        return []
    return sorted(
        p.name for p in ordner.iterdir()
        if p.is_file() and p.suffix in {".gguf", ".safetensors", ".ckpt", ".pt", ".pth", ".onnx"}
        and not bildinhalt.is_sqlite(p)
    )


def _hauptordner_fang(bildordner: Path, ziel: str) -> list[str]:
    """Files sitting loose in the main folder that ``bildinhalt.sorte()``
    is CERTAIN belong to the given companion kind instead — the catch net
    for companion files. A name only ever lands here because the content
    itself said so, never because of its extension or its name."""
    ordner = Path(bildordner).expanduser()
    if not ordner.is_dir():
        return []
    return [
        p.name for p in ordner.iterdir()
        if p.is_file() and p.suffix in {".gguf", ".safetensors"} and bildinhalt.sorte(p) == ziel
    ]


def vaes(bildordner: Path) -> list[str]:
    """The standalone VAE files in their own folder below the image
    models, plus any VAE the content-sniffing catch net finds loose in
    the main folder."""
    return sorted(set(_im_unterordner(bildordner, VAE_ORDNER))
                  | set(_hauptordner_fang(bildordner, bildinhalt.VAE)))


def tokenizers(bildordner: Path) -> list[str]:
    """The tokenizer.json files some kits read (``--tokenizer``), kept
    beside the text encoders."""
    ordner = Path(bildordner).expanduser() / TEXTVERSTEHER_ORDNER
    if not ordner.is_dir():
        return []
    return sorted(p.name for p in ordner.iterdir() if p.is_file() and p.suffix == ".json")


def pulid_embeddings(bildordner: Path) -> list[str]:
    """The finished PuLID face embeddings (``.pulidembd``) in the PuLID
    folder — the one thing ``--pulid-id-embedding`` takes. A photo is no
    embedding: sd.cpp only warns and draws as if PuLID were off."""
    ordner = Path(bildordner).expanduser() / PULID_ORDNER
    if not ordner.is_dir():
        return []
    return sorted(p.name for p in ordner.iterdir() if p.is_file() and p.suffix == PULID_ENDUNG)


def yolos(bildordner: Path) -> list[str]:
    """The ADetailer detector models in their own folder."""
    return _im_unterordner(bildordner, YOLO_ORDNER)


def pulids(bildordner: Path) -> list[str]:
    """The PuLID weight files in their own folder."""
    return _im_unterordner(bildordner, PULID_ORDNER)


def taesd_files(image_folder: Path) -> list[str]:
    """The tiny autoencoders in their own folder."""
    return _im_unterordner(image_folder, TAESD_FOLDER)


def taesd_path(image_folder: Path, name: str) -> Path:
    return _begleiter_pfad(image_folder, name, TAESD_FOLDER, taesd_files(image_folder))


def controlnets(bildordner: Path) -> list[str]:
    """The ControlNet models in their own folder."""
    return _im_unterordner(bildordner, CONTROLNET_ORDNER)


def upscalers(bildordner: Path) -> list[str]:
    """The model-backed highres upscalers in their own folder, by file
    name — what `--hires-upscaler` is allowed to carry beside sd-cli's
    built-in names (``bildwahlen.HIRES_UPSCALER_FESTE``)."""
    return _im_unterordner(bildordner, UPSCALER_ORDNER)


def textversteher(bildordner: Path) -> list[str]:
    """The text encoder files (T5, CLIP, an LLM checkpoint) a Bausatz family
    assembles a picture from, in their own folder below the image models,
    plus any the content-sniffing catch net finds loose in the main
    folder."""
    return sorted(set(_im_unterordner(bildordner, TEXTVERSTEHER_ORDNER))
                  | set(_hauptordner_fang(bildordner, bildinhalt.TEXTVERSTEHER)))


def embeddings(bildordner: Path) -> list[str]:
    """The names an embedding is called by inside a prompt — its file name
    without extension, from the shared textual-inversion folder. Unlike a
    model or LoRA, no suffix filter: whatever sd.cpp itself is handed
    through ``--embd-dir`` matches by name, and this list has no reason to
    disagree with it. A hidden file is skipped regardless — a Finder litter
    file such as ``.DS_Store``, never something placed there on purpose;
    opening the folder by hand to drop a file in is exactly what this list
    exists to make unnecessary."""
    ordner = Path(bildordner).expanduser() / EMBEDDING_ORDNER
    if not ordner.is_dir():
        return []
    return sorted(
        p.stem for p in ordner.iterdir() if p.is_file() and not p.name.startswith(".")
    )


def _begleiter_pfad(bildordner: Path, name: str, unter: str, vorhanden: list[str]) -> Path:
    """A companion NAME turned into a path — hostile name treated as hostile,
    exactly like a model or a LoRA: bare file name, really in its folder.

    ``vorhanden`` can also carry a name the content-sniffing catch net
    caught loose in the main folder — that membership check
    is the only gate this function needs, so a name not actually sitting
    in ``unter`` falls back to the main folder instead of failing."""
    if not name or "/" in name or "\\" in name or name != Path(name).name:
        raise BildFehler("bild.begleiter_unbekannt")
    if name not in vorhanden:
        raise BildFehler("bild.begleiter_unbekannt")
    im_unterordner = Path(bildordner).expanduser() / unter / name
    if im_unterordner.is_file():
        return im_unterordner
    return Path(bildordner).expanduser() / name


def vae_pfad(bildordner: Path, name: str) -> Path:
    return _begleiter_pfad(bildordner, name, VAE_ORDNER, vaes(bildordner))


def yolo_pfad(bildordner: Path, name: str) -> Path:
    return _begleiter_pfad(bildordner, name, YOLO_ORDNER, yolos(bildordner))


def pulid_pfad(bildordner: Path, name: str) -> Path:
    return _begleiter_pfad(bildordner, name, PULID_ORDNER, pulids(bildordner))


def pulid_embedding_pfad(bildordner: Path, name: str) -> Path:
    return _begleiter_pfad(bildordner, name, PULID_ORDNER, pulid_embeddings(bildordner))


def tokenizer_pfad(bildordner: Path, name: str) -> Path:
    return _begleiter_pfad(bildordner, name, TEXTVERSTEHER_ORDNER, tokenizers(bildordner))


def controlnet_pfad(bildordner: Path, name: str) -> Path:
    return _begleiter_pfad(bildordner, name, CONTROLNET_ORDNER, controlnets(bildordner))


def upscaler_path(image_folder: Path, name: str) -> Path:
    return _begleiter_pfad(image_folder, name, UPSCALER_ORDNER, upscalers(image_folder))


def textversteher_pfad(bildordner: Path, name: str) -> Path:
    return _begleiter_pfad(bildordner, name, TEXTVERSTEHER_ORDNER, textversteher(bildordner))


def imatrix_path(model: Path) -> Path:
    """Where a model file's importance matrix is collected: beside it."""
    return model.with_name(model.name + ".imatrix.dat")


def modell_pfad(bildordner: Path, name: str) -> Path:
    """A model NAME turned into a path — never the other way round.

    The name comes from a request, so it is treated as hostile: only a bare
    file name is accepted, and only one that is really lying in the image
    model folder. Anything with a separator in it, or anything the folder
    does not contain, is refused before it can become a path at all.
    """
    if not name or "/" in name or "\\" in name or name != Path(name).name:
        raise BildFehler("bild.modell_unbekannt")
    if name not in modelle(bildordner):
        raise BildFehler("bild.modell_unbekannt")
    return Path(bildordner).expanduser() / name


def referenz_schalter(auftrag: Auftrag) -> list[str]:
    """The switches of an edit: each reference image with ``-r`` in the
    order given, then the image CFG, the reference arguments and the index
    switch — only with a reference image, since without one they act on
    nothing."""
    if not auftrag.ref_bilder:
        return []
    teile: list[str] = []
    for bild in auftrag.ref_bilder:
        teile += ["-r", str(bild)]
    if auftrag.img_cfg is not None:
        teile += ["--img-cfg-scale", str(auftrag.img_cfg)]
    if auftrag.ref_image_args:
        teile += ["--ref-image-args", auftrag.ref_image_args]
    if auftrag.increase_ref_index:
        teile += ["--increase-ref-index"]
    return teile


def video_parts(auftrag: Auftrag) -> dict[str, Path]:
    """The video kit parts that are set, by their field name."""
    return {
        field: path for field in (
            "high_noise_diffusion_model", "audio_vae", "audio_encoder", "embeddings_connectors",
        )
        if (path := getattr(auftrag, field)) is not None
    }


def video_schalter(auftrag: Auftrag, frames_folder: Path, ref_frames_folder: Path) -> list[str]:
    """A video's own switches: frame count and rate, the last frame, the
    control video and the reference video. sd-cli reads either video as a
    folder of pictures in name order (``--control-video``, ``--ref-video``),
    which ``frames_folder`` and ``ref_frames_folder`` are — filled by the
    runner before sd-cli starts."""
    teile: list[str] = []
    if auftrag.video_frames is not None:
        teile += ["--video-frames", str(auftrag.video_frames)]
    if auftrag.fps is not None:
        teile += ["--fps", str(auftrag.fps)]
    if auftrag.end_image is not None:
        teile += ["--end-img", str(auftrag.end_image)]
    if auftrag.control_frames:
        teile += ["--control-video", str(frames_folder)]
    if auftrag.ref_video_frames:
        teile += ["--ref-video", str(ref_frames_folder)]
    return teile


def ad_args_text(auftrag: Auftrag) -> str:
    """The detailer's one ``key=value`` list: the threshold first, then the
    table's further values — sd-cli reads only the last ``--extra-ad-args``,
    so they have to travel together."""
    first = f"confidence={auftrag.ad_confidence}" if auftrag.ad_confidence is not None else ""
    return image_switches.key_value_list(auftrag.switches, "--extra-ad-args", first)


class Bildrunner:
    """One picture at a time, on this machine."""

    def __init__(self, datenordner: Path) -> None:
        self._datenordner = Path(datenordner).expanduser()
        self._schloss = threading.Lock()
        # The running program, so a stop can actually reach it. Without this
        # the only way out of a picture was to wait five minutes for the
        # time limit — and the panel had no way of saying so.
        self._prozess: subprocess.Popen | None = None
        self._abgebrochen = False
        # A stop asked for while a picture holds the lock and nothing draws
        # yet — the picture server still starts for it, or steps aside for
        # an sd-cli picture. It belongs to that one hold of the lock: taken
        # down when the lock is taken, read before, during and after the
        # draw, so the picture it was meant for is never handed back.
        self._stop_asked = False
        self._stoppable = False
        # Asking and the picture's last look are one step each: a stop that
        # is answered "yes" is never one the picture has already passed.
        self._stop_guard = threading.Lock()
        # The live step counter of the running picture, or None while no
        # picture runs — what the filling frame in the interface drinks from.
        self._fortschritt: dict | None = None
        # Where sd-cli writes the live preview of the running picture. One
        # per process: two instances may share the data folder.
        self.preview_path = self._datenordner / f"picture-preview-{os.getpid()}.png"
        # The folder a control video's frames are laid into for sd-cli, one
        # per process for the same reason.
        self.frames_folder = self._datenordner / f"control-frames-{os.getpid()}"
        # And the folder a reference video's frames are laid into, beside it.
        self.ref_frames_folder = self._datenordner / f"reference-frames-{os.getpid()}"
        # The model files whose importance matrix is being collected, by
        # name: every sd-cli picture drawn with one of them adds to it. For
        # this session only — collecting is something one does for a while.
        self.imatrix_models: set[str] = set()

    def fortschritt(self) -> dict | None:
        """The running picture's honest progress, or nothing while idle —
        with the stamp of its newest preview (0 while there is none), so
        the window knows when to fetch it again."""
        if not self.laeuft() or self._fortschritt is None:
            return None
        # Microseconds: a nanosecond stamp is beyond what a JavaScript
        # number holds exactly, and two stamps must not read as one.
        try:
            stamp = self.preview_path.stat().st_mtime_ns // 1000
        except OSError:
            stamp = 0
        return {**self._fortschritt, "preview": stamp}

    def preview(self) -> Path | None:
        """The running picture's live preview, while there is one."""
        return self.preview_path if self.laeuft() and self.preview_path.is_file() else None

    def reservieren(self, *, stoppable: bool = False) -> None:
        """Take the one-picture-at-a-time lock without drawing — the turbo
        path borrows it so a turbo picture and an sd-cli picture can never
        run at once, and a second request cannot restart the server under a
        running draw. Pairs with ``freigeben``.

        ``stoppable`` says this hold is a picture that honours a stop asked
        before it draws (``ask_stop``): the holder reads ``stop_asked`` or
        calls ``end_if_stopped`` wherever it can still let go."""
        if not self._schloss.acquire(blocking=False):
            raise BildFehler("bild.laeuft_schon")
        self._stop_asked = False
        self._stoppable = stoppable

    def freigeben(self) -> None:
        self._stoppable = False
        self._schloss.release()

    def ask_stop(self) -> bool:
        """Stop the picture that holds the lock although nothing draws yet.
        True when there is such a picture: it will not be handed back. A
        hold that cannot let go — a model being converted, a picture being
        enlarged on the server — is not one, and neither is no hold at
        all."""
        with self._stop_guard:
            if not self._schloss.locked() or not self._stoppable:
                return False
            self._stop_asked = True
            return True

    def stop_asked(self) -> bool:
        return self._stop_asked

    def end_if_stopped(self, *, last: bool = False) -> None:
        """Raises the stopped picture's own error when a stop was asked for
        during this hold of the lock. ``last`` is the look after which the
        picture is handed back: from then on a stop no longer reaches it,
        and ``ask_stop`` says so."""
        with self._stop_guard:
            if self._stop_asked:
                raise BildFehler("bild.abgebrochen")
            if last:
                self._stoppable = False

    @property
    def programm(self) -> Path | None:
        return programm_finden(self._datenordner)

    def laeuft(self) -> bool:
        return self._schloss.locked()

    def stoppen(self) -> bool:
        """End the running picture. True when there was one to end.

        The whole tree goes, not just the parent — a generator that kept
        working after the stop would hold the lock and the memory for a
        picture nobody is waiting for anymore.

        How a tree is reached differs per system, which is why it lives in
        ``app/prozessstopp.py``. Reaching for the POSIX call directly is what
        made this button do nothing on Windows: ``os.killpg`` does not exist
        there and raises AttributeError, which is not an OSError and so fell
        straight through the guard below it.

        Waited on rather than fired and forgotten: the caller releases the
        lock on the strength of this answer, and a second generator started
        while the first is still drawing is the one thing a machine at its
        memory limit cannot take.
        """
        prozess = self._prozess
        if prozess is None or prozess.poll() is not None:
            return False
        self._abgebrochen = True
        prozessstopp.beenden(prozess, frist=ABBRUCH_FRIST)
        return True

    def run_tool(self, command: list[str], *, timeout: float) -> tuple[int, str]:
        """Run one of the painter's tools that draws no picture — converting
        a model file — as this runner's process, so a stop reaches it the
        way it reaches a picture. The caller holds the one-picture lock
        (``reservieren``) and releases it itself.

        Returns the exit code and everything the tool printed. A stopped
        tool raises ``BildFehler("bild.abgebrochen")``; one still running
        after ``timeout`` seconds is ended and raises
        ``subprocess.TimeoutExpired``."""
        self._abgebrochen = False
        # Its own process group, as for a picture: ending it takes the
        # whole tree. Read as text, a stray byte replaced: one byte the
        # tool prints must not cost the answer.
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding=_pipe_encoding(), errors="replace", start_new_session=True,
            **no_window(),
        )
        self._prozess = process
        try:
            try:
                printed, complained = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                prozessstopp.beenden(process, frist=ABBRUCH_FRIST)
                # Collect the child so no zombie is left behind.
                process.communicate()
                raise
            if self._abgebrochen:
                raise BildFehler("bild.abgebrochen")
            return process.returncode, (printed or "") + "\n" + (complained or "")
        finally:
            self._prozess = None

    def befehl(self, auftrag: Auftrag, ziel: Path) -> list[str]:
        """The command line, built in one place so it can be read in one."""
        programm = self.programm
        if programm is None:
            raise BildFehler("bild.kein_programm")
        if auftrag.mode == "upscale":
            # Only the upscaler reads the picture: no model, no prompt.
            if auftrag.upscale_model is None or auftrag.startbild is None:
                raise BildFehler("bild.modus_unvollstaendig")
            return [
                str(programm), "-M", "upscale",
                "--upscale-model", str(auftrag.upscale_model),
                "-i", str(auftrag.startbild), "-o", str(ziel),
            ]
        if auftrag.mode == "adetailer" and (auftrag.ad_modell is None or auftrag.startbild is None):
            raise BildFehler("bild.modus_unvollstaendig")
        # A LoRA is not a command-line option in this program — it is
        # written into the prompt, and the folder is pointed at separately.
        # So the stack is appended to the prompt here rather than passed as
        # flags, which is also why the order of the list survives.
        prompt = prompt_bauen(auftrag.prompt, auftrag.loras, auftrag.ad_loras)
        # A plain model is one flag; a Bausatz assembles several files and
        # asks bildbausatz for the exact switches instead — that module is
        # the one place that knows which family reads which of them. This
        # branch is new; the plain-model line below it is untouched.
        if auftrag.diffusion_model is not None:
            gespann = bildbausatz.Gespann(
                familie=auftrag.familie,
                diffusion_model=auftrag.diffusion_model,
                t5xxl=auftrag.t5xxl, clip_l=auftrag.clip_l, clip_g=auftrag.clip_g,
                llm=auftrag.llm, vae_format=auftrag.vae_format,
                llm_vision=auftrag.llm_vision, tokenizer=auftrag.tokenizer,
                uncond_diffusion_model=auftrag.uncond_diffusion_model,
                **video_parts(auftrag),
            )
            try:
                modell_teile = bildbausatz.schalter(gespann)
            except ValueError as fehler:
                raise BildFehler("bild.familie_ungueltig") from fehler
        else:
            modell_teile = ["-m", str(auftrag.modell)]
            # A checkpoint without text encoders of its own is handed the
            # ones of its family; any other plain model carries none here.
            modell_teile += bildbausatz.checkpoint_switches(
                auftrag.familie, t5xxl=auftrag.t5xxl, clip_l=auftrag.clip_l,
                clip_g=auftrag.clip_g, llm=auftrag.llm,
                # Read only where no family decides about the model: then
                # every part that is set goes beside the model.
                llm_vision=auftrag.llm_vision, tokenizer=auftrag.tokenizer,
                uncond_diffusion_model=auftrag.uncond_diffusion_model,
                **video_parts(auftrag),
            )
            # A plain model has no Gespann, so bildbausatz.schalter() never
            # runs for it — the one place vae_format otherwise becomes a
            # flag. Without this line a merged single-file model was told
            # to use a latent format and sd-cli never heard of it, while
            # the turbo path (app/bildturbo.py) already sent it. Same flag,
            # same branch, same rule on both paths now.
            if auftrag.vae_format:
                modell_teile += ["--vae-format", auftrag.vae_format]
        # The distilled guidance belongs to the MODEL, not to the way its
        # files arrived: a merged single-file Flux has the same guidance
        # input a Flux assembled from parts has. Sent whenever it is set;
        # unset keeps the flag off entirely, as everywhere else.
        if auftrag.guidance is not None:
            modell_teile += ["--guidance", str(auftrag.guidance)]
        if auftrag.model_args:
            modell_teile += ["--model-args", auftrag.model_args]
        teile = [
            str(programm),
            *modell_teile,
            "-p", prompt,
            "-W", str(auftrag.breite),
            "-H", str(auftrag.hoehe),
            "--steps", str(auftrag.schritte),
            "--cfg-scale", str(auftrag.cfg),
            "--seed", str(auftrag.seed),
            "-o", str(ziel),
        ]
        # Empty means "no switch": sd-cli picks the model's own sampler.
        if auftrag.sampler:
            teile += ["--sampling-method", auftrag.sampler]
        # Empty means "no switch": sd-cli picks its own, model-specific
        # scheduler — the start value of every family in the table.
        if auftrag.scheduler:
            teile += ["--scheduler", auftrag.scheduler]
        if auftrag.negativ:
            teile += ["--negative-prompt", auftrag.negativ]
        if (auftrag.loras or auftrag.ad_loras) and auftrag.lora_ordner is not None:
            teile += ["--lora-model-dir", str(auftrag.lora_ordner)]
            # Free choice, by house rule: nothing that can be shown is
            # hidden — this field can matter to someone tinkering.
            # The warning stays in the window, not in a server-side lock:
            # "auto" and "immediately" are proven to abort on this Metal
            # build (ggml-backend.cpp:930, applies 0 of N tensors and dies
            # in sampling — live with LCM-SD15, LCM-SDXL, Hyper-SD15).
            # at_runtime, the field's own default, is the one proven to
            # render.
            teile += ["--lora-apply-mode", auftrag.lora_apply_mode]
        # The quality companions. Each is left off entirely when unset, so the
        # command line carries only what was actually chosen.
        if auftrag.embd_ordner is not None:
            teile += ["--embd-dir", str(auftrag.embd_ordner)]
        if auftrag.clip_skip >= 1:
            teile += ["--clip-skip", str(auftrag.clip_skip)]
        if auftrag.vae is not None:
            teile += ["--vae", str(auftrag.vae)]
        # PhotoMaker needs both halves or neither: the model has no face to
        # carry without the photos, and the photos do nothing without it.
        # Passing one alone would load a model that changes nothing, and the
        # picture would come back looking like a plain run for no visible
        # reason.
        if auftrag.photomaker is not None and auftrag.gesichter_ordner is not None:
            teile += [
                "--photo-maker", str(auftrag.photomaker),
                "--pm-id-images-dir", str(auftrag.gesichter_ordner),
            ]
            # The same Metal trap the LoRA stack falls into, and the same way
            # out. PhotoMaker adds weights to the model exactly as a LoRA does,
            # so without this the run dies in ggml-backend.cpp:930 —
            # "pre-allocated tensor … in a buffer (MTL0) that cannot run the
            # operation (ADD)" — before a single step is sampled. Measured on
            # builds 820 and 920: with the flag the picture renders, without it
            # every run aborts.
            #
            # Set here as well as above because a face can be carried without
            # any LoRA in the stack, and then the line above never runs. Passing
            # it twice does no harm; passing it never does.
            if not (auftrag.loras and auftrag.lora_ordner is not None):
                teile += ["--lora-apply-mode", auftrag.lora_apply_mode]
        # PuLID needs both halves too, same reasoning as PhotoMaker just
        # above: weights alone have no face to carry, an embedding alone
        # has nothing to carry it with.
        if auftrag.pulid_weights is not None and auftrag.pulid_id_embedding is not None:
            teile += [
                "--pulid-weights", str(auftrag.pulid_weights),
                "--pulid-id-embedding", str(auftrag.pulid_id_embedding),
                "--pulid-id-weight", str(auftrag.pulid_id_weight),
            ]
        if auftrag.control_net is not None and auftrag.control_image is not None:
            teile += [
                "--control-net", str(auftrag.control_net),
                "--control-image", str(auftrag.control_image),
                "--control-strength", str(auftrag.control_strength),
            ]
            if auftrag.canny:
                teile += ["--image-preprocess", "target=control,canny=true"]
        if auftrag.diffusion_fa:
            teile += ["--diffusion-fa"]
        # Memory & devices. RNG is always sent (see the field's own
        # comment); the rest stay off the command line entirely while
        # unset, matching whatever sd-cli would already do on its own.
        teile += ["--rng", auftrag.rng]
        if auftrag.weight_type:
            teile += ["--type", auftrag.weight_type]
        if auftrag.threads > 0:
            teile += ["--threads", str(auftrag.threads)]
        if auftrag.vram_limit:
            teile += ["--max-vram", auftrag.vram_limit]
        if auftrag.offload_to_cpu:
            teile += ["--offload-to-cpu"]
        if auftrag.split_mode:
            teile += ["--split-mode", auftrag.split_mode]
        if auftrag.backend:
            teile += ["--backend", auftrag.backend]
        if auftrag.hires:
            teile += ["--hires", "--hires-scale", str(auftrag.hires_scale)]
            if auftrag.hires_steps > 0:
                teile += ["--hires-steps", str(auftrag.hires_steps)]
            if auftrag.hires_denoise > 0:
                teile += ["--hires-denoising-strength", str(auftrag.hires_denoise)]
            if auftrag.hires_upscaler:
                teile += ["--hires-upscaler", auftrag.hires_upscaler]
                # The folder only for a model-backed upscaler — the
                # built-in names need none, and a flag nothing reads is a
                # flag too many.
                if (auftrag.hires_upscaler not in HIRES_UPSCALER_FESTE
                        and auftrag.hires_upscalers_ordner is not None):
                    teile += ["--hires-upscalers-dir", str(auftrag.hires_upscalers_ordner)]
            # Either one beats --hires-scale (sd-cli's own rule); 0 means
            # "not set" and stays off the command line.
            if auftrag.hires_width > 0:
                teile += ["--hires-width", str(auftrag.hires_width)]
            if auftrag.hires_height > 0:
                teile += ["--hires-height", str(auftrag.hires_height)]
        # Sampler fine-tuning. Every unset field stays off the command line
        # entirely — sd-cli's own per-sampler defaults (eta 0 OR 1 depending
        # on the sampler, flow-shift "auto") are values this program could
        # not repeat without changing some picture somewhere.
        if auftrag.eta is not None:
            teile += ["--eta", str(auftrag.eta)]
        if auftrag.flow_shift is not None:
            teile += ["--flow-shift", str(auftrag.flow_shift)]
        if auftrag.sigmas:
            teile += ["--sigmas", auftrag.sigmas]
        sample_args = image_switches.key_value_list(
            auftrag.switches, "--extra-sample-args", auftrag.extra_sample_args
        )
        if sample_args:
            teile += ["--extra-sample-args", sample_args]
        tiling_args = image_switches.key_value_list(auftrag.switches, image_switches.TILING)
        if tiling_args:
            teile += [image_switches.TILING, tiling_args]
        if auftrag.prediction:
            teile += ["--prediction", auftrag.prediction]
        if auftrag.slg_scale > 0:
            teile += [
                "--slg-scale", str(auftrag.slg_scale),
                "--skip-layer-start", str(auftrag.skip_layer_start),
                "--skip-layer-end", str(auftrag.skip_layer_end),
            ]
            if auftrag.skip_layers:
                teile += ["--skip-layers", auftrag.skip_layers]
        if auftrag.live_preview:
            # The preview is written where the window reads it from; without
            # a path sd-cli writes ./preview.png, where nobody looks.
            teile += ["--preview", auftrag.live_preview,
                      "--preview-path", str(self.preview_path)]
            if auftrag.preview_interval is not None:
                teile += ["--preview-interval", str(auftrag.preview_interval)]
            if auftrag.preview_noisy:
                teile += ["--preview-noisy"]
            if auftrag.live_preview == "tae" and auftrag.taesd is not None:
                teile += ["--taesd", str(auftrag.taesd), "--taesd-preview-only"]
        if auftrag.ad_modell is not None:
            teile += ["--ad-model", str(auftrag.ad_modell)]
            # Only the text. The LoRA tags ride in the MAIN prompt, because
            # that is the only place the engine reads them from.
            ad_prompt = auftrag.ad_prompt
            if ad_prompt:
                teile += ["--ad-prompt", ad_prompt]
            # Empty inherits the main negative prompt — sd-cli's own,
            # useful behaviour, so empty means NO flag, never an explicit
            # empty string that would break the inheritance.
            if auftrag.ad_negativ:
                teile += ["--ad-negative-prompt", auftrag.ad_negativ]
            ad_args = ad_args_text(auftrag)
            if ad_args:
                teile += ["--extra-ad-args", ad_args]
        # The strength only means anything beside a starting image. Sent
        # without one it would be a number the program quietly ignores, and
        # a control that does nothing is worse than no control.
        if auftrag.startbild is not None:
            teile += ["-i", str(auftrag.startbild), "--strength", str(auftrag.staerke)]
            if auftrag.maske is not None:
                teile += ["--mask", str(auftrag.maske)]
        teile += referenz_schalter(auftrag)
        if auftrag.video:
            teile += video_schalter(auftrag, self.frames_folder, self.ref_frames_folder)
        teile += image_switches.cli_parts(auftrag.switches, auftrag.switch_paths)
        if auftrag.imatrix is not None:
            teile += ["--imat-out", str(auftrag.imatrix)]
            if auftrag.imatrix.is_file():
                teile += ["--imat-in", str(auftrag.imatrix)]
        if auftrag.mode == "adetailer":
            # The same options: -M adetailer repairs the start picture with
            # the detail pass alone (sd.cpp docs/adetailer.md).
            teile[1:1] = ["-M", "adetailer"]
        elif auftrag.video:
            teile[1:1] = ["-M", "vid_gen"]
        return teile

    def erzeugen(self, auftrag: Auftrag, ziel: Path, *, reserved: bool = False) -> Path:
        """Draw one picture into `ziel`. Blocks for as long as it takes.

        ``reserved`` means the caller already holds the one-picture lock
        (``reservieren``) and releases it itself — so something done before
        the draw, like the picture server stepping aside, happens under the
        same lock as the draw."""
        if not reserved:
            # This picture's own hold of the lock, stoppable from here on.
            self.reservieren(stoppable=True)
        try:
            befehl = self.befehl(auftrag, ziel)
            ziel.parent.mkdir(parents=True, exist_ok=True)
            # The prompt is left out of the log on purpose: what somebody
            # asks a picture generator for is their business, and a log file
            # is read by whoever gets the machine next.
            log.info(
                "Picture: %s, %dx%d, %d steps, seed %s",
                auftrag.modell.name, auftrag.breite, auftrag.hoehe,
                auftrag.schritte, auftrag.seed,
            )
            self._abgebrochen = False
            # Stopped before the painter was even started — while the
            # picture server stepped aside for this picture, say.
            self.end_if_stopped()
            # A preview left over from the picture before is not this one's.
            self.preview_path.unlink(missing_ok=True)
            self._lay_out_frames(self.frames_folder, auftrag.control_frames)
            self._lay_out_frames(self.ref_frames_folder, auftrag.ref_video_frames)
            try:
                # Popen and not run(): a stop has to be able to reach the
                # program, and run() hands back only the finished result.
                # Its own process group, so ending it takes the whole thing.
                # BOTH streams are read live, each by its own reader: the
                # painter prints its log and the step counter on stdout,
                # ggml its asserts on stderr — the counter feeds the filling
                # frame, and both texts together feed the honest error.
                self._prozess = subprocess.Popen(
                    befehl,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                    **no_window(),
                )
            except OSError as fehler:
                raise BildFehler("bild.kein_programm") from fehler
            if self._stop_asked:
                # Asked in the moment between the check above and the
                # painter's start, when there was no process to end yet.
                self.stoppen()

            # Honest percent: only bars that count iterations are painting
            # passes (the loader prints bars too, counting megabytes). A run
            # has a known number of passes — base, plus highres, plus one
            # detailer pass — and the overall share is passes done plus the
            # current pass's fraction.
            erwartete_paesse = (
                1 if auftrag.mode
                else 1 + (1 if auftrag.hires else 0) + (1 if auftrag.ad_modell else 0)
            )
            ausgabeteile: list[str] = []
            fehlerteile: list[str] = []
            self._fortschritt = {"anteil": 0.0, "schritt": 0, "gesamt": auftrag.schritte}
            fertige_paesse = 0
            letzter_schritt = 0

            # The stream handles are caught in locals BEFORE the threads
            # start: a reader that outlives the wait (a grandchild holding
            # the pipe open) must never reach for self._prozess after the
            # finally block has nulled it.
            # Read as text with the encoding Popen's own text mode would
            # pick, a stray byte replaced instead of killing the reader, and
            # without newline translation: Popen's text mode turns every "\r"
            # into "\n", which splits one redrawn progress bar into many
            # lines. The step counter's pattern matches either way.
            # stdout is taken piece by piece as the painter writes it, so
            # every step's bar is counted when it is printed; stderr is only
            # needed whole, once the painter has ended.
            stdout_pipe, stderr_pipe = self._prozess.stdout, self._prozess.stderr
            assert stdout_pipe is not None and stderr_pipe is not None  # both PIPE
            ausgang = live_text(stdout_pipe, _pipe_encoding())
            fehlerkanal = io.TextIOWrapper(
                stderr_pipe, encoding=_pipe_encoding(), errors="replace", newline="",
            )

            def _zaehler_lesen() -> None:
                nonlocal fertige_paesse, letzter_schritt, erwartete_paesse
                rest = ""
                # The share of the pass the last bar named, kept so the
                # overall share can be worked out again when a planned pass
                # turns out not to come.
                pass_share = 0.0
                detector_counted = bool(auftrag.ad_modell) and not auftrag.mode
                # The step count of the painting pass, read off its first
                # bar, and the last step a bar of that pass named. Not the
                # requested count: from a starting picture the painter makes
                # fewer steps than were asked for, and says so only here.
                paint_total = 0
                painted = 0
                announced = False  # the painter has said that it starts to paint
                for stueck in ausgang:
                    ausgabeteile.append(stueck)
                    text = rest + stueck
                    for treffer in _SCHRITT_MUSTER.finditer(text):
                        if treffer.end() <= len(rest):
                            continue  # already seen in the previous round
                        if treffer.group(3):
                            # The bars before this line were the preparation
                            # — a starting picture encoded tile by tile counts
                            # iterations too — and are no part of the picture's
                            # share. Only the first time: a later pass that
                            # says the same goes on counting.
                            if not announced:
                                announced = True
                                paint_total = painted = 0
                                fertige_paesse = letzter_schritt = 0
                                self._fortschritt = {
                                    "anteil": 0.0, "schritt": 0, "gesamt": auftrag.schritte,
                                }
                            continue
                        schritt, gesamt = int(treffer.group(1)), int(treffer.group(2))
                        if not paint_total:
                            # A painting pass never has more steps than were
                            # asked for: a bar that counts further before
                            # painting has begun counts something else — a
                            # loader that counts tensors draws the same bar.
                            if gesamt > auftrag.schritte:
                                continue
                            paint_total = gesamt
                        if schritt < letzter_schritt:
                            # A new pass began. More faces than expected stay
                            # inside the last pass's share instead of pushing
                            # the figure past the end.
                            fertige_paesse = min(fertige_paesse + 1, erwartete_paesse - 1)
                        letzter_schritt = schritt
                        # EVERY painting bar is real remaining work and moves
                        # the share — the detector repaints each found face,
                        # often with its own step count. The step and its
                        # total are only those of the painting pass itself: a
                        # bar counting something else would read as a step
                        # far beyond the picture's last one.
                        pass_share = schritt / gesamt
                        anteil = (fertige_paesse + pass_share) / erwartete_paesse
                        if gesamt == paint_total:
                            painted = schritt
                        self._fortschritt = {
                            "anteil": min(anteil, 0.99),
                            "schritt": painted,
                            "gesamt": paint_total,
                        }
                    if detector_counted and any(
                        found.end() > len(rest) for found in _NOTHING_DETECTED.finditer(text)
                    ):
                        # The detector found nothing: its pass was planned
                        # and does not come. The share stands where it
                        # stands without that pass, instead of waiting at
                        # the half for bars that are never printed.
                        detector_counted = False
                        erwartete_paesse = max(1, erwartete_paesse - 1)
                        fertige_paesse = min(fertige_paesse, erwartete_paesse - 1)
                        anteil = (fertige_paesse + pass_share) / erwartete_paesse
                        self._fortschritt = {
                            "anteil": min(anteil, 0.99),
                            "schritt": painted,
                            "gesamt": paint_total,
                        }
                    rest = text[-64:]

            def _fehler_lesen() -> None:
                while True:
                    stueck = fehlerkanal.read(256)
                    if not stueck:
                        break
                    fehlerteile.append(stueck)

            leser = [
                threading.Thread(target=_zaehler_lesen, daemon=True),
                threading.Thread(target=_fehler_lesen, daemon=True),
            ]
            for l in leser:
                l.start()
            try:
                self._prozess.wait(
                    timeout=None if auftrag.video else auftrag.zeitgrenze
                )
            except subprocess.TimeoutExpired as fehler:
                self.stoppen()
                # Collect the child so no zombie is left behind.
                self._prozess.wait()
                for l in leser:
                    l.join(timeout=5)
                raise BildFehler("bild.zeit_abgelaufen") from fehler
            for l in leser:
                l.join(timeout=5)
            # Both voices together: the painter's log (stdout) carries the
            # "[ERROR  ]" lines (level tag padded with blanks), ggml's aborts
            # land on stderr.
            fehlertext = "".join(ausgabeteile) + "\n" + "".join(fehlerteile)
            with self._stop_guard:
                stopped = self._abgebrochen or self._stop_asked
                # The last look: what follows hands the picture back.
                self._stoppable = False
            if stopped:
                # A stopped picture is not a failed one. The difference
                # matters at the other end: one is reported, the other is
                # what the user just asked for.
                ziel.unlink(missing_ok=True)
                raise BildFehler("bild.abgebrochen")
            if self._prozess.returncode != 0 or not ziel.is_file():
                crash = _crash_note(self._prozess.returncode)
                # Split on newlines only, and of a line redrawn with "\r"
                # keep what stood last on screen (a "\r\n" ending is no
                # redraw).
                lines = [
                    line.rstrip("\r").rsplit("\r", 1)[-1]
                    for line in fehlertext.split("\n")
                ]
                log.warning(
                    "Picture failed (%s%s): %s",
                    self._prozess.returncode, f", {crash.name}" if crash else "",
                    tail_lines(lines, 500),
                )
                # The user sees the painter's REAL lines, verbatim. The
                # telling ones (asserts, "[ERROR  ]" lines) usually stand
                # BEFORE the backtrace, so they are picked first; the raw
                # tail only fills in when no such line exists. The
                # painter's lines are selected, never reworded; the app's
                # one marked crash note, when there is one, leads and counts
                # toward the same limit. Lines are dropped whole.
                telling = [
                    line for line in lines
                    if "GGML_ASSERT" in line or "GGML_ABORT" in line
                    or _ERROR_TAG.search(line) or "error:" in line.lower()
                    # ggml aborts print "file.cpp:930: <reason>" without any
                    # ERROR marker — that reason line IS the crash message.
                    or (re.search(r"\.\w+:\d+: ", line) and not line.lstrip().startswith(("[INFO", "[WARN", "[DEBUG")))
                ]
                # A crash leaves no message of its own; the signal or status
                # that ended the program is the reason, so it leads the log.
                note = crash.line if crash else None
                room = LOG_LIMIT - (len(note) + 1 if note else 0)
                excerpt = tail_lines(telling[-8:] if telling else lines, room)
                if note:
                    excerpt = f"{note}\n{excerpt}" if excerpt else note
                raise BildFehler("bild.gescheitert", protokoll=excerpt)
            return ziel
        finally:
            self._prozess = None
            self._fortschritt = None
            self.preview_path.unlink(missing_ok=True)
            shutil.rmtree(self.frames_folder, ignore_errors=True)
            shutil.rmtree(self.ref_frames_folder, ignore_errors=True)
            if not reserved:
                self.freigeben()

    @staticmethod
    def _lay_out_frames(folder: Path, frames: tuple[Path, ...]) -> None:
        """A video's frames as sd-cli reads them: pictures in one folder
        whose names sort in the frames' order. Without frames no folder."""
        shutil.rmtree(folder, ignore_errors=True)
        if not frames:
            return
        folder.mkdir(parents=True)
        for number, frame in enumerate(frames):
            shutil.copyfile(frame, folder / f"{number:05d}{frame.suffix.lower()}")
