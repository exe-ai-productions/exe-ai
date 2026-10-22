"""Drawing a picture on this machine.

Separate from ``bilder.py`` next door on purpose: that one takes pictures IN
(an upload for vision) and hands them back out again. This one makes them,
which is a different act with a different set of things that can go wrong —
no program installed, no room in memory, a run already going.

Everything a request can influence is clamped here rather than at the
generator. A number that arrives out of range is not an error to report but
a value to bring into range: a slider that was dragged is not a mistake.
Two things ARE refused instead of clamped — a model name that is not a
model, and a Bausatz field sent without (or against) the family that
explains it — because those are the two cases where guessing would be
dangerous.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import secrets
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal, NoReturn, Protocol

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from app.api.abhaengigkeiten import hole_config, hole_repositories, hole_sprache
from app import (
    bildbausatz, bildgeraete, bildinhalt, bildmodellwerte, bildstandardmodell, bildstile,
    gesichteraufbereitung, image_families, kit_bond,
    image_switches, photomaker, picture_info, studio_pictures,
)
from app.api.v1.bilder import ERLAUBTE_TYPEN
from app.bildmetadaten import metadaten_entfernen
from app.bildschutz import putzen_an
from app.bildturbo import Bildturbo, BildturboFehler, start_deadline, start_parts
from app.bildrunner import (
    Auftrag, BildFehler, Bildrunner, LoRA, UPSCALE_REPEATS_START, UPSCALE_TILE_START,
    UPSCALER_ORDNER, VAE_ORDNER,
    controlnet_pfad, controlnets, embeddings, is_image_model, loras, lora_pfad, modelle,
    modell_pfad, pulid_embedding_pfad, pulid_embeddings, pulid_pfad, pulids,
    vision_part_path, sehteile, textversteher, textversteher_pfad, tokenizer_pfad, tokenizers,
    imatrix_path, taesd_path, taesd_files, upscaler_path, upscaler_scales, vae_choice_path, vae_choices, vaes,
    vae_pfad, video_parts,
    yolos, yolo_pfad,
)
from app import bildwahlen
from app.bildwahlen import MAX_KANTE, MIN_KANTE, MIN_SCHRITTE, RASTER
from app import bildlauf, bildspeicher, draw_input, image_start_values, paste_back, systemspeicher
from app import attachment_sizes, upscaled_info, upscaler_scale
from pathlib import Path

from app.config import Config
from app.db import Repositories
from app.i18n import t
from app.ordner_oeffnen import OeffnenNichtMoeglich, ordner_oeffnen
from app.speicherorte import ort, scratch_pictures_dir
from app.tools import bild_werkzeug
from app import picture_program_choice, sddownload
from app.sddownload import Sddownload, SddownloadFehler

log = logging.getLogger(__name__)

router = APIRouter(tags=["bild"])

# The limits are sd.cpp's own (app/bildwahlen.py): edges from 64 to 4096 in
# steps of 64, rounded up as sd.cpp rounds them, at least one step. Nothing
# here is narrower than what the generator takes.

class LoRAWunsch(BaseModel):
    name: str
    staerke: float = bildwahlen.LORA_VORGABE


class BildWunsch(BaseModel):
    # An unknown field here is not a caller's optional extra worth ignoring
    # — von/nr/lauf_kennung/frage_erstellen showed how easily a renamed or
    # dropped field goes unnoticed otherwise (see bilder_je_lauf's own
    # orphaned run through this file). 422 says so at the door instead.
    # No upper limit on the numbers below means no infinite one either: a
    # number that is not finite is refused at the door, not drawn with.
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    modell: str
    # Where the picture should land. Without a chat the picture is only
    # made and named — useful for a script, and the one case in which
    # nothing is written to the history.
    chat_id: str | None = None
    # The picture studio's own draw: the finished picture is put on the
    # studio's list of pictures (app/studio_pictures.py), where its row of
    # pictures reads it. A draw without this belongs to no list.
    studio: bool = False
    # Which chat's little history this RUN is written into. Normally the same
    # chat the picture lands in; the picture server's test run sets only this
    # one, because that run is worth showing but the picture is not worth
    # keeping.
    lauf_chat: str | None = None
    # What is drawn from. Only an enlarging may go without one: the upscaler
    # reads no prompt (checked below, with the run's own checks).
    prompt: str
    negativ: str = ""
    # A style the prompt is drawn through (app/bildstile.py): its text, with
    # ``{prompt}`` where the prompt goes, and its negative. The history keeps
    # the prompt as it was typed.
    stil_text: str = ""
    stil_negativ: str = ""
    # The first model is trained on 512; 1024 stays available and costs
    # both time and quality on it.
    breite: int = 512
    hoehe: int = 512
    # sd-cli refuses fewer than one step, and so does this route.
    schritte: int = Field(default=20, ge=MIN_SCHRITTE)
    cfg: float = 7.0
    # -1 means: the generator picks one. Anything else is repeatable.
    seed: int = -1
    # Empty leaves the sampler and the scheduler to sd.cpp, which picks the
    # model's own of each.
    sampler: str = ""
    scheduler: str = ""
    loras: list[LoRAWunsch] = Field(default_factory=list)
    # Free by house rule — see app/bildwahlen.py's own comment on the flag.
    lora_apply_mode: str = bildwahlen.LORA_APPLY_MODE_VORGABE
    # A picture already in this installation to start from, by the name the
    # server gave it — never a path.
    startbild: str | None = None
    staerke: float = bildwahlen.STAERKE_VORGABE
    # The mask, by the name this server gave it — like the starting image.
    maske: str | None = None
    # The starting image is a piece cut out of a larger picture: that
    # picture, by the name this server gave it — never a path — and where
    # the piece lies in it, as x, y, width and height in that picture's
    # pixels. With both, the result is the whole picture with the drawn
    # piece set back in its place (app/paste_back.py).
    crop_of: str | None = None
    crop_box: tuple[int, int, int, int] | None = None
    # The quality companions, all optional. -1 clip-skip means "let the class
    # decide"; an empty VAE/detector name means the pass is simply off. Names,
    # never paths — resolved against their own folders like a LoRA is.
    clip_skip: int = -1
    vae: str | None = None
    ad_modell: str | None = None
    ad_prompt: str = ""
    # The detailer's negative prompt and detection threshold. Both unset by
    # default: an empty negative inherits the MAIN negative prompt (sd-cli's
    # own, useful behaviour — an explicit "" would break it), None
    # confidence leaves sd-cli's own threshold alone.
    # The detailer's own LoRA stack, kept as its own field — but NOT because
    # it stays off the main prompt. It does not stay off it: the engine
    # ignores ``<lora:...>`` inside ``--ad-prompt`` entirely (measured on
    # builds 820 and 920 — a
    # made-up name there drew no reaction, the same name in the main prompt
    # said "can not found lora" at once), and its detail pass reuses the main
    # pass's LoRA settings instead. So these tags are written into the MAIN
    # prompt, which is the only place they reach the face from.
    #
    # The claim that used to stand here — that a face LoRA belongs on the
    # detailer alone so its style does not drag through the picture — is not
    # what the code does and never was. What keeps that drag small is the
    # division of labour spelled out in app/bildrunner.py's prompt_bauen:
    # only the tag rides in the main prompt, while the trigger WORD stays in
    # the detailer prompt, and without its trigger a character LoRA pulls the
    # main picture far more weakly.
    ad_loras: list[LoRAWunsch] = Field(default_factory=list)
    ad_negativ: str = ""
    ad_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    # PhotoMaker: who the photos in the face folder show. Empty means off.
    # Checked against the four words the generator knows — see app/photomaker.py.
    pm_klasse: str = Field(default="", max_length=20)
    # PuLID: a face carried in through a precomputed embedding rather than
    # a class word — both resolved against the PuLID folder like a LoRA:
    # the weights, and a finished ``.pulidembd``. A photo is no embedding
    # and is refused (both required together, checked below).
    pulid_weights: str | None = None
    pulid_id_embedding: str | None = None
    pulid_id_weight: float = Field(default=1.0, ge=0.0)
    # ControlNet: a second image steering the drawing by shape rather than
    # words. The guide image travels the same picked-picture route as
    # startbild; edge detection (canny) only means anything with a guide
    # image set, checked at the request boundary below.
    control_net: str | None = None
    control_image: str | None = None
    control_strength: float = 0.9
    canny: bool = False
    # Highres fix: a second pass at a larger size for finer detail. Off by
    # default; the scale is how much larger. The second pass's own dials
    # below all default to "unset" — 0/empty keeps each switch off the
    # built command entirely, so a request that never touches them draws
    # exactly as it does today (see the Auftrag's own field comments in
    # app/bildrunner.py).
    hires: bool = False
    hires_scale: float = Field(default=2.0, ge=1.0)
    hires_steps: int = Field(default=0, ge=0)
    hires_denoise: float = Field(default=0.0, ge=0.0, le=1.0)
    hires_upscaler: str = Field(default="", max_length=200)
    # A fixed target size beats the scale (sd-cli's own rule), inside the
    # same edge range as the picture itself.
    hires_width: int = Field(default=0, ge=0, le=MAX_KANTE)
    hires_height: int = Field(default=0, ge=0, le=MAX_KANTE)
    # Sampler fine-tuning, all unset by default. eta's unset is None, not
    # 0 — sd-cli's own default is 0 OR 1 depending on the sampler, so an
    # explicit 0 would be a real change for euler_a.
    eta: float | None = None
    flow_shift: float | None = None
    sigmas: str = Field(default="", max_length=500)
    extra_sample_args: str = Field(default="", max_length=500)
    # --prediction override; checked against bildwahlen.PREDICTION_WERTE,
    # unknown values fold to "" (no flag), same as live_preview.
    prediction: str = Field(default="", max_length=20)
    # Skip layer guidance (DiT models, e.g. Flux/SD3): drops the guided
    # pass for a handful of transformer layers between two points in the
    # schedule. 0 leaves it off entirely, same as sd-cli's own default;
    # `skip_layer_start`/`_end` default to sd-cli's own values (0.01/0.2)
    # so a field nobody touched sends exactly what sd-cli would already
    # do once the scale turns SLG on.
    slg_scale: float = Field(default=0.0, ge=0.0)
    skip_layer_start: float = Field(default=0.01, ge=0.0, le=1.0)
    skip_layer_end: float = Field(default=0.2, ge=0.0, le=1.0)
    skip_layers: str = Field(default="", max_length=100)
    # CLI draw only -- checked against bildwahlen.LIVE_PREVIEW_WERTE, the
    # same way split_mode/lora_apply_mode are.
    live_preview: str = Field(default="", max_length=10)
    # The preview's rhythm, its noisy variant and the tiny autoencoder
    # (by name, from its own folder) — each only beside a preview.
    preview_interval: int | None = None
    preview_noisy: bool = False
    taesd: str | None = None
    # Images per run: the window calls this route once PER PICTURE, exactly
    # as it always has for one — these three describe the picture's place
    # in that run so the pictures land as one group instead of four
    # unrelated ones. Checked, not clamped: an out-of-range or made-up
    # value here is not a dragged slider (there is no slider on the wire),
    # it is a caller that built the request wrong, and 422 says so instead
    # of quietly filing the picture under a number nobody asked for.
    von: int = Field(default=1, ge=1)
    nr: int = Field(default=1, ge=1)
    # A short, caller-chosen tag, not a server-issued id — the window
    # mints one per run and sends it on every one of that run's requests;
    # this route has no notion of "before" or "after" a request to hand
    # one out itself. None on a single picture, matching `von`'s default.
    lauf_kennung: str | None = Field(default=None, max_length=64)
    # False only for picture 2+ of a run: one chat text for the whole run,
    # not one repeated per picture. True is every existing caller's shape.
    frage_erstellen: bool = True
    # A Bausatz (flux, zimage, flux2): several files assembled instead of
    # one plain model. Names, never paths — resolved against their own
    # folder like any other companion. Unset by default, so a request that
    # never mentions any of them draws exactly as it does today.
    # Which family the fields above belong to. Unset, the diffusion
    # model's own header (or the model's) names it — never which fields
    # happen to be there.
    familie: str | None = None
    diffusion_model: str | None = None
    t5xxl: str | None = None
    clip_l: str | None = None
    clip_g: str | None = None
    llm: str | None = None
    vae_format: str = ""
    guidance: float | None = None
    # The further parts some kits read (the family table's ``parts``), by
    # name like every other companion, and ``--model-args`` as written.
    llm_vision: str | None = None
    tokenizer: str | None = None
    uncond_diffusion_model: str | None = None
    model_args: str = Field(default="", max_length=500)
    # Editing with reference images: pictures by the name this server gave
    # them, in order — like the starting image, never a path. The image
    # CFG, the reference arguments and the index switch only act beside a
    # reference and are dropped without one.
    ref_bilder: list[str] = Field(default_factory=list)
    img_cfg: float | None = Field(default=None, ge=0.0)
    ref_image_args: str = Field(default="", max_length=500)
    increase_ref_index: bool = False
    # Start flags of the picture, checked against the window's own
    # dropdowns (bildwahlen.rng_pruefen/weight_type_pruefen), not sd-cli's
    # full range. RNG always carries one of its two values, like sampler.
    # The machine's memory and devices are no part of a picture: they come
    # from the picture server's own setting (app/bildgeraete.py).
    rng: str = bildwahlen.RNG_VORGABE
    weight_type: str = ""
    # sd.cpp's further switches by key (``app.image_switches``): checked
    # against the table, unset ones left out. Files and pictures by name.
    # The memory block's switches are the machine's and are taken from the
    # picture server's setting instead.
    switches: dict[str, bool | int | float | str | None] = Field(default_factory=dict)
    # A mode on the finished picture in ``startbild`` instead of drawing:
    # repair it with the detector alone, or enlarge it with the upscaler
    # model ``upscale_model`` (a file of the upscaler folder, by name).
    mode: Literal["", "adetailer", "upscale"] = ""
    upscale_model: str | None = None
    # How often the upscaler runs over the picture and the size of its tiles
    # (sd.cpp's ``--upscale-repeats`` 1 to 4 and ``--upscale-tile-size``).
    upscale_repeats: int = Field(default=UPSCALE_REPEATS_START, ge=1, le=4)
    upscale_tile_size: int = Field(default=UPSCALE_TILE_START, ge=1)
    # A video instead of a still picture: its frame count and rate (None
    # leaves the family's start value to the window, sd-cli's own here),
    # the last frame for a video drawn between two pictures, and the frames
    # of a control video — pictures by the name this server gave them, in
    # order, like the starting image.
    video: bool = False
    video_frames: int | None = Field(default=None, ge=1)
    fps: int | None = Field(default=None, ge=1)
    end_bild: str | None = None
    steuerbilder: list[str] = Field(default_factory=list)
    # The frames of a reference video, by name and in order like the
    # control video's; its sound is the switch ``ref_video_audio``.
    ref_video_frames: list[str] = Field(default_factory=list)
    # The video kits' further parts, by name like every other companion.
    high_noise_diffusion_model: str | None = None
    audio_vae: str | None = None
    audio_encoder: str | None = None
    embeddings_connectors: str | None = None
    clip_vision: str | None = None

    @model_validator(mode="after")
    def _lauf_stimmig(self) -> "BildWunsch":
        if not self.prompt and self.mode != "upscale":
            # The same kind and the same bound as the length check the field
            # had: the answer is built from the catalogue, in the language of
            # the request (app/input_errors.py).
            raise PydanticCustomError(
                "string_too_short", "String should have at least 1 character", {"min_length": 1}
            )
        if self.nr > self.von:
            # The check's own kind IS the catalogue key: the answer to a body
            # that fails its checks is built there (app/input_errors.py), in
            # the language of the request — a sentence written here would
            # reach an English window in German.
            raise PydanticCustomError("bild_lauf_nr_zu_gross", "Image number is outside the "
                                                               "range of this run.")
        return self


class BildAntwort(BaseModel):
    bild: str
    # The seed the picture was drawn with; none for a picture that was only
    # enlarged, which uses no seed.
    seed: int | None = None
    frage_id: str | None = None
    antwort_id: str | None = None


class PictureFromSentence(BaseModel):
    """One sentence and the chat whose picture window gives every value."""

    # Whitespace alone is no sentence: the tool strips the prompt and would
    # refuse it after the request had been taken.
    prompt: str = Field(min_length=1, pattern=r"\S")
    chat_id: str = Field(min_length=1, max_length=200)


class PictureFromSentenceAnswer(BaseModel):
    bild: str
    # Where the finished picture lies, in the pictures folder.
    pfad: str
    seed: int | None = None
    modell: str
    # The prompt it was drawn with, after the prompt preparation.
    prompt: str
    # The values it was drawn with, by the names of the draw request.
    werte: dict[str, Any] = Field(default_factory=dict)


class BildmodellAntwort(BaseModel):
    modelle: list[str]
    # Each model's family, read from its own header (app/bildinhalt.py);
    # empty for a model whose header names none. The window groups its
    # model list by it.
    families: dict[str, str] = Field(default_factory=dict)
    # Each model file's size in bytes, for the list that names it.
    sizes: dict[str, int] = Field(default_factory=dict)
    # For each model that cannot be drawn for want of a kit part, the name of
    # the first part it misses (``missing_kit_part``); a complete model is not
    # in it. The studio's model choice offers complete models only.
    missing_parts: dict[str, str] = Field(default_factory=dict)
    loras: list[str] = Field(default_factory=list)
    vaes: list[str] = Field(default_factory=list)
    yolos: list[str] = Field(default_factory=list)
    pulids: list[str] = Field(default_factory=list)
    controlnets: list[str] = Field(default_factory=list)
    # The tiny autoencoders the "tae" live preview decodes with.
    taesd_files: list[str] = Field(default_factory=list)
    # The kind of each tiny autoencoder file (``bildbausatz.tae_kind``), empty
    # where its name carries none: which families it decodes for.
    tae_kinds: dict[str, str] = Field(default_factory=dict)
    embeddings: list[str] = Field(default_factory=list)
    textversteher: list[str] = Field(default_factory=list)
    # The vision parts (mmproj files) of the text encoder folder: what the
    # kit's vision field takes, never the text encoders above.
    sehteile: list[str] = Field(default_factory=list)
    tokenizers: list[str] = Field(default_factory=list)
    # The finished PuLID face embeddings (``.pulidembd``).
    pulid_embeddings: list[str] = Field(default_factory=list)
    # Model-backed highres upscalers, offered beside sd-cli's built-in
    # names (which travel separately, as `hires_upscaler_feste`).
    upscalers: list[str] = Field(default_factory=list)
    # The factor each of them enlarges by, read from its weights.
    upscaler_scales: dict[str, int] = Field(default_factory=dict)
    hires_upscaler_feste: list[str] = Field(default_factory=list)
    sampler: list[str] = Field(default_factory=list)
    scheduler: list[str] = Field(default_factory=list)
    # The model every chat draws with until it chooses its own
    # (app/bildstandardmodell.py); empty while none is chosen or its file
    # left the folder.
    standardmodell: str = ""
    programm_da: bool
    # The installed generator's build tag, read from the folder on disk
    # (app/sddownload.py) — the window shows it as the version of what it
    # is about to call. None while nothing is installed.
    bau: str | None = None
    # Whether the generator that runs was fetched and is not the tested
    # build — the one case in which there is something to go back from.
    restorable: bool = False
    ordner: str
    # Shown as plain path text next to the folder-open button — not
    # independently relocatable Speicherorte (the name would collide with
    # the unrelated "einbettung" model folder), just where the window's own
    # subfolders happen to sit today.
    lora_ordner: str
    vae_ordner: str
    embedding_ordner: str
    upscaler_ordner: str
    # `bereit` | `kein_modell` | `kein_programm` | `zeichnet`. Deliberately
    # not "running": sd.cpp is not a service that stands, it is a program
    # that is called. A tile claiming a server would be a tile that lies.
    stand: str


def _kante(wert: int) -> int:
    """An edge rounded up onto the grid inside sd.cpp's range."""
    return min(MAX_KANTE, -(-max(MIN_KANTE, int(wert)) // RASTER) * RASTER)


def _zielkante(wert: int) -> int:
    """A hires target edge. 0 means "not set" — the scale applies instead
    and the switch stays off the command entirely. Anything else is snapped
    like a base edge."""
    if int(wert) <= 0:
        return 0
    return _kante(wert)


def _bildordner(config: Config) -> Path:
    return ort(config, "image_models")


def _upscaler_ordner(config: Config) -> Path | None:
    """The model-backed upscaler folder, or nothing while it does not exist
    yet. Both the draw path and the hand switch resolve it through here:
    `passt_zu()` compares this value, so two independent copies of "where
    the upscalers live" would restart a running server for no reason at
    all the first time the two disagreed."""
    ordner = _bildordner(config) / UPSCALER_ORDNER
    return ordner if ordner.is_dir() else None


def _embd_ordner(config: Config) -> Path | None:
    """The embeddings folder, or nothing while it does not exist yet."""
    ordner = _bildordner(config) / bildwahlen.EMBEDDING_ORDNER
    return ordner if ordner.is_dir() else None


def _bilderziel(config: Config) -> Path:
    """Where a finished picture is written and read back from — one named
    location, so the folder is asked for and never spelled out."""
    return ort(config, "images")


def _runner(request: Request) -> Bildrunner:
    """The one runner, built at startup — so the lock is one lock.

    Deliberately NOT created here on first use. Two requests arriving at the
    same moment would both find nothing and both build one, and two runners
    hold two locks: exactly the situation the lock exists to prevent.
    """
    return request.app.state.bildrunner


def _family_of(config: Config, name: str) -> str:
    """A listed model's family. The name comes from the folder's own list,
    so the path is built straight from it — checking it against a fresh
    listing again per model would read the whole folder once per model."""
    return bildinhalt.family(_bildordner(config).expanduser() / name) or ""


def _sizes_of(config: Config, names: list[str]) -> dict[str, int]:
    """The listed models' file sizes. A file that went away between the
    listing and this look is left out rather than failing the list."""
    folder = _bildordner(config).expanduser()
    sizes: dict[str, int] = {}
    for name in names:
        try:
            sizes[name] = (folder / name).stat().st_size
        except OSError:
            continue
    return sizes


@router.get("/bild/modelle", response_model=BildmodellAntwort, summary="Image models")
def bildmodelle(
    request: Request, config: Config = Depends(hole_config),
    repositories: Repositories = Depends(hole_repositories),
) -> BildmodellAntwort:
    runner = _runner(request)
    gefunden = modelle(_bildordner(config))
    programm_da = runner.programm is not None
    picked_variant = picture_program_choice.picked(repositories)
    # Asked once for the whole folder: a model whose family is not to be
    # read is listed without one.
    unread = bildmodellwerte.without_family_detection(repositories)
    tae_files = taesd_files(_bildordner(config))
    scales = upscaler_scales(_bildordner(config))
    return BildmodellAntwort(
        modelle=gefunden,
        families={
            name: "" if name in unread else _family_of(config, name) for name in gefunden
        },
        sizes=_sizes_of(config, gefunden),
        missing_parts=_missing_parts_of(config, repositories, gefunden),
        loras=loras(_bildordner(config)),
        vaes=vaes(_bildordner(config)),
        yolos=yolos(_bildordner(config)),
        pulids=pulids(_bildordner(config)),
        controlnets=controlnets(_bildordner(config)),
        taesd_files=tae_files,
        tae_kinds={name: bildbausatz.tae_kind(name) for name in tae_files},
        embeddings=embeddings(_bildordner(config)),
        textversteher=textversteher(_bildordner(config)),
        sehteile=sehteile(_bildordner(config)),
        tokenizers=tokenizers(_bildordner(config)),
        pulid_embeddings=pulid_embeddings(_bildordner(config)),
        upscalers=list(scales),
        upscaler_scales=scales,
        hires_upscaler_feste=list(bildwahlen.HIRES_UPSCALER_FESTE),
        sampler=list(bildwahlen.SAMPLER),
        scheduler=list(bildwahlen.SCHEDULER),
        standardmodell=bildstandardmodell.lesen(repositories, gefunden),
        programm_da=programm_da,
        bau=sddownload.installierter_bau(config.datenverzeichnis, picked_variant),
        restorable=sddownload.restorable(config.datenverzeichnis, picked_variant),
        ordner=str(_bildordner(config)),
        lora_ordner=str(_bildordner(config) / bildwahlen.LORA_ORDNER),
        vae_ordner=str(_bildordner(config) / VAE_ORDNER),
        embedding_ordner=str(_bildordner(config) / bildwahlen.EMBEDDING_ORDNER),
        upscaler_ordner=str(_bildordner(config) / UPSCALER_ORDNER),
        stand=(
            "zeichnet" if runner.laeuft()
            else "kein_programm" if not programm_da
            else "bereit" if gefunden
            else "kein_modell"
        ),
    )


# --- Image-Turbo: the optional persistent server ---------------------------


def _turbo(request: Request) -> Bildturbo:
    return request.app.state.bildturbo


class TurboAntwort(BaseModel):
    # aus (grey) | bereit (green) | zeichnet (blue) | fehler (red)
    zustand: str
    modell: str | None = None
    programm_da: bool
    # A picture holds the one-picture lock: start and stop by hand wait for
    # it (409), so the tile's button is locked meanwhile.
    picture_running: bool = False
    # The server is down for one sd-cli picture and comes back after it: the
    # catalogue key of the label of the control that picture needs sd-cli
    # for. Empty whenever the server is not paused for a picture.
    paused_for: str | None = None
    # The port the server listens on, running or not — the one a start takes.
    port: int | None = None
    # The default model a start would load (the one chosen for the studio),
    # while its file is in the folder; None where none is chosen. `modell`
    # stays what runs.
    selected_model: str | None = None


def _turbo_stand(
    turbo: Bildturbo, runner: Bildrunner, selected_model: str | None = None
) -> TurboAntwort:
    return TurboAntwort(
        zustand=turbo.zustand(), modell=turbo.modell,
        programm_da=turbo.programm is not None,
        picture_running=runner.laeuft(),
        paused_for=turbo.paused_for(),
        port=turbo.port,
        selected_model=selected_model,
    )


def _selected_picture_model(config: Config, repositories: Repositories) -> str | None:
    """The chosen default picture model while its file is in the folder.

    This answer is polled, so only the one chosen entry is looked at — the
    whole folder is not read for it."""
    name = bildstandardmodell.stored_choice(repositories)
    return name if name and is_image_model(_bildordner(config), name) else None


def _hold_picture_lock(request: Request, sprache: str):
    """The one-picture lock for a start or stop by hand: a server is never
    started or ended under a picture being drawn, nor started beside an
    sd-cli picture it stepped aside for."""
    runner = _runner(request)
    try:
        runner.reservieren()
    except BildFehler as fehler:
        raise HTTPException(status.HTTP_409_CONFLICT, t(fehler.grund, sprache)) from fehler
    return runner


@router.get("/bild/turbo", response_model=TurboAntwort, summary="Image-Turbo — status")
def turbo_stand(
    request: Request, config: Config = Depends(hole_config),
    repositories: Repositories = Depends(hole_repositories),
) -> TurboAntwort:
    return _turbo_stand(
        _turbo(request), _runner(request), _selected_picture_model(config, repositories)
    )


class TurboReasonQuery(BaseModel):
    """The values the studio holds right now that decide which painter draws
    the next picture — nothing else: no prompt, no file is read for it."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    modell: str
    live_preview: str = Field(default="", max_length=10)
    # The preview's rhythm, its noisy variant and whether a tiny
    # autoencoder is chosen for it — each only beside a preview.
    preview_interval: int | None = None
    preview_noisy: bool = False
    preview_taesd: bool = False
    pulid_weights: str | None = None
    pulid_id_embedding: str | None = None
    sigmas: str = Field(default="", max_length=500)
    slg_scale: float = Field(default=0.0, ge=0.0)
    skip_layers: str = Field(default="", max_length=100)
    switches: dict[str, bool | int | float | str | None] = Field(default_factory=dict)
    # The family the window states, as the draw sends it: with it the
    # model's kit is read as the draw reads it, which decides whether the
    # kit brings a second, high-noise diffusion model.
    familie: str | None = Field(default=None, max_length=60)
    # What the picture would carry along: a reference video, a LoRA in the
    # stack (or the detector's), the detector, the highres pass, a video.
    ref_video: bool = False
    lora: bool = False
    ad_modell: bool = False
    hires: bool = False
    video: bool = False
    lora_apply_mode: str = bildwahlen.LORA_APPLY_MODE_VORGABE
    pm_klasse: str = Field(default="", max_length=20)


class TurboReasonAnswer(BaseModel):
    # The catalogue key of the label of the control whose value sends the
    # picture to sd-cli while the server runs, or None.
    control: str | None = None


@dataclass(frozen=True)
class _StudioValues:
    """``_CliValues`` for a picture that is only a set of values so far."""

    live_preview: str
    pulid_weights: str | None
    pulid_id_embedding: str | None
    sigmas: str
    slg_scale: float
    skip_layers: str
    switches: dict
    ref_video_frames: tuple
    lora_apply_mode: str
    preview_interval: int | None = None
    preview_noisy: bool = False
    preview_tae_only: bool = False
    video: bool = False
    mode: str = ""


@router.post(
    "/bild/turbo/reason", response_model=TurboReasonAnswer,
    summary="Image-Turbo — what the studio's values need sd-cli for",
)
def turbo_reason(
    query: TurboReasonQuery,
    request: Request,
    config: Config = Depends(hole_config),
    repositories: Repositories = Depends(hole_repositories),
) -> TurboReasonAnswer:
    """Which control sends the picture, as the studio is set, to sd-cli —
    asked of the same rule the draw route decides by
    (``_cli_only_reason``), so the window keeps no list of its own. Nothing
    while the server is not running: then every picture is drawn by sd-cli
    and there is nothing to say."""
    if not _turbo(request).laeuft():
        return TurboReasonAnswer()
    bildordner = _bildordner(config)
    try:
        model_file: Path | None = modell_pfad(bildordner, query.modell)
    except BildFehler:
        model_file = None
    pm_active = bool(
        photomaker.klasse_pruefen(query.pm_klasse)
        and photomaker.modell(bildordner) is not None
        and photomaker.gesichter(bildordner) is not None
    )
    try:
        given = image_switches.check({
            **bildgeraete.ohne_speicherschalter(query.switches),
            **bildgeraete.lesen(repositories).switches,
        })
        # The kit is read only for a value of the high-noise pass, which
        # counts exactly when the model's kit brings that second model, as
        # in the draw: nothing else depends on it, and the window asks every
        # few seconds.
        second_model = model_file is not None and any(
            "high_noise" in image_switches.BY_KEY[key].needs.split("|") for key in given
        ) and _kit_has_high_noise(
            config, repositories, query.modell, model_file, query.familie
        )
        switches = image_switches.active(
            given,
            {
                "ad_model": query.ad_modell, "photomaker": pm_active,
                "hires": query.hires, "video": query.video,
                "high_noise": second_model, "ref_video": query.ref_video and query.video,
            },
        )
    except ValueError:
        # A value the table refuses fails the draw itself, with its words.
        switches = {}
    live_preview = bildwahlen.live_preview_pruefen(query.live_preview)
    # A tiny autoencoder chosen for the preview paints it alone unless the
    # VAE of the model's kit is one already (as the draw reads it).
    preview_tae_only = bool(
        live_preview == "tae" and query.preview_taesd and model_file is not None
        and not _kit_vae_is_tae(
            config, repositories, query.modell, model_file, query.familie
        )
    )
    values = _StudioValues(
        live_preview=live_preview,
        preview_interval=query.preview_interval if live_preview else None,
        preview_noisy=query.preview_noisy and bool(live_preview),
        preview_tae_only=preview_tae_only,
        video=query.video,
        pulid_weights=query.pulid_weights,
        pulid_id_embedding=query.pulid_id_embedding,
        sigmas=query.sigmas.strip(),
        slg_scale=query.slg_scale,
        skip_layers=query.skip_layers.strip(),
        switches=switches,
        ref_video_frames=("-",) if query.ref_video and query.video else (),
        lora_apply_mode=bildwahlen.lora_apply_mode_pruefen(query.lora_apply_mode),
    )
    reason = _cli_only_reason(values, query.lora or pm_active)
    return TurboReasonAnswer(control=reason.control if reason else None)


class TurboStart(BaseModel):
    modell: str


# Where each part of a model's kit is kept, by the name the draw route takes
# it under: the list of its folder and how a name there becomes a path.
_KIT_PART_FOLDERS = {
    "vae": (vae_choices, vae_choice_path),
    "t5xxl": (textversteher, textversteher_pfad),
    "clip_l": (textversteher, textversteher_pfad),
    "clip_g": (textversteher, textversteher_pfad),
    "llm": (textversteher, textversteher_pfad),
    "llm_vision": (sehteile, vision_part_path),
    "tokenizer": (tokenizers, tokenizer_pfad),
    "uncond_diffusion_model": (modelle, modell_pfad),
    "high_noise_diffusion_model": (modelle, modell_pfad),
    "audio_vae": (vaes, vae_pfad),
    "audio_encoder": (textversteher, textversteher_pfad),
    "embeddings_connectors": (textversteher, textversteher_pfad),
    "clip_vision": (textversteher, textversteher_pfad),
}
# The video kits' parts, which the picture server takes as one bundle.
_VIDEO_PART_FIELDS = (
    "high_noise_diffusion_model", "audio_vae", "audio_encoder", "embeddings_connectors",
    "clip_vision",
)


def kit_fields(
    family: image_families.Family | None, *, free: bool = False, model: str | None = None,
) -> tuple[str, ...]:
    """The parts a model is drawn with besides itself: the VAE of every
    model, and for a kit's own diffusion model the text encoders and the
    further parts its family reads — of those the model itself takes, when
    its file name is given (``image_families.parts_taken``). ``free`` — the
    model's family is not read — is every part there is, since no family
    says which belong."""
    if free:
        return tuple(_KIT_PART_FOLDERS)
    if family is None or not family.kit:
        return ("vae",)
    further = family.parts if model is None else image_families.parts_taken(family, model)
    return ("vae", *family.encoders, *further)


def _model_kit(
    config: Config, repositories: Repositories, model: str, path: Path,
    family: image_families.Family | None,
) -> dict[str, str]:
    """A model's kit by file name, as the picture server holds it for every
    chat: a kit family's own diffusion model brings itself as
    ``diffusion_model`` and the parts the folder offers for its family
    (``kit_bond.matching_parts``); a part given to the model in the picture server
    (app/bildmodellwerte.py) wins over the offered one. A given part whose
    file left its folder counts as none, so a missing part is named rather
    than an unknown file. Any other model has only its VAE here.

    A model whose family is not read (app/bildmodellwerte.py) has exactly
    the parts given to it: the folder offers nothing by itself, because no
    family says what would fit. Its diffusion model is the file chosen for
    it; with none chosen it has none here, and its own file is the model."""
    folder = _bildordner(config)
    own = bildmodellwerte.eigene(repositories, model)
    free = not bildmodellwerte.family_detection(repositories, model)
    if free:
        family = None
    standalone = bool(
        family is not None and family.kit and bildinhalt.standalone_diffusion_model(path)
    )
    # A checkpoint of a kit family that brings no text encoder of its own
    # takes the encoders and the further parts of its family, and not its
    # VAE.
    bare = bool(
        family is not None and family.kit and not standalone
        and bildinhalt.checkpoint_without_text_encoders(path)
    )
    kit: dict[str, str] = {}
    if free:
        chosen = own.get(bildmodellwerte.DIFFUSION_MODEL)
        if chosen and chosen in modelle(folder):
            kit["diffusion_model"] = chosen
    elif standalone and family is not None:
        kit["diffusion_model"] = model
        kit.update(kit_bond.matching_parts(folder, family, model))
    elif bare and family is not None:
        kit.update({
            field: name for field, name in kit_bond.matching_parts(folder, family, model).items()
            if field in (*family.encoders, *image_families.parts_taken(family, model))
        })
    # Each folder is listed once, however many parts it holds.
    listed: dict = {}
    fields = (
        ("vae", *family.encoders, *image_families.parts_taken(family, model))
        if bare and family is not None
        else kit_fields(family if standalone else None, free=free, model=model)
    )
    for field in fields:
        name = own.get(field)
        if not name:
            continue
        # A tiny autoencoder that does not decode this family's latent space
        # stays remembered but is not drawn with: the VAE then counts as unchosen.
        if bildbausatz.is_tae_choice(name) and not bildbausatz.tae_fits(name, family):
            continue
        listing = _KIT_PART_FOLDERS[field][0]
        if listing not in listed:
            listed[listing] = listing(folder)
        if name in listed[listing]:
            kit[field] = name
    return kit


def _kit_has_high_noise(
    config: Config, repositories: Repositories, model: str, path: Path,
    family_word: str | None,
) -> bool:
    """Does the kit of this model, read as a draw reads it, bring a second,
    high-noise diffusion model? The values of that pass act only beside it,
    so every answer about which painter draws a picture counts them in
    exactly when the draw does. The family is the one the window states, or
    else the one the model's header names — as in the draw route — and a
    model whose family is not read has exactly the parts given to it."""
    return "high_noise_diffusion_model" in _kit_as_drawn(
        config, repositories, model, path, family_word
    )


def _kit_vae_is_tae(
    config: Config, repositories: Repositories, model: str, path: Path,
    family_word: str | None,
) -> bool:
    """Is the VAE of this model's kit, read as a draw reads it, a tiny
    autoencoder? Then it paints the "tae" preview itself."""
    kit = _kit_as_drawn(config, repositories, model, path, family_word)
    return bildbausatz.is_tae_choice(kit.get("vae"))


def _kit_as_drawn(
    config: Config, repositories: Repositories, model: str, path: Path,
    family_word: str | None,
) -> dict:
    """The kit of this model as a draw reads it: with the family the window
    states, or else the one the model's header names, and a model whose
    family is not read has exactly the parts given to it."""
    free = not bildmodellwerte.family_detection(repositories, model)
    if family_word:
        family_name = family_word
    elif free:
        family_name = ""
    else:
        family_name = bildinhalt.family(path) or ""
    return _model_kit(config, repositories, model, path, image_families.get(family_name))


def _start_family(repositories: Repositories, path: Path, model: str) -> str:
    """The family a model is started and drawn as: its header's, empty when
    the user switched reading it off for this model."""
    if not bildmodellwerte.family_detection(repositories, model):
        return ""
    return bildinhalt.family(path) or ""


def _kit_for_start(
    config: Config, path: Path, model: str, repositories: Repositories, sprache: str,
) -> dict:
    """What a model is started with by hand beside itself: its kit as a
    drawing takes it (``_model_kit``). A kit family's own diffusion model
    starts with ``--diffusion-model`` and its parts, refused, naming the
    part, when one is missing; any other model starts with ``-m`` and the
    VAE it was given."""
    free = not bildmodellwerte.family_detection(repositories, model)
    family_name = _start_family(repositories, path, model)
    family = image_families.get(family_name)
    names = _model_kit(config, repositories, model, path, family)
    parts = {
        field: _begleiter(_KIT_PART_FOLDERS[field][1], config, name, sprache)
        for field, name in names.items() if field != "diffusion_model"
    }
    # A tiny autoencoder in the VAE's place starts the server with ``--taesd``.
    tae = {"vae_tae": True} if parts.get("vae") and bildbausatz.is_tae_choice(names.get("vae")) else {}
    if free:
        # No family is read: the model with exactly the parts given to it,
        # and the diffusion model chosen for it where one was. None is
        # asked for, none refused.
        bundle = {field: parts.pop(field) for field in _VIDEO_PART_FIELDS if parts.get(field)}
        chosen = _begleiter(modell_pfad, config, names.get("diffusion_model"), sprache)
        return {
            "familie": bildbausatz.FREE,
            **({"diffusion_model": chosen} if chosen is not None else {}),
            **parts, **tae, **({"video_parts": bundle} if bundle else {}),
        }
    # A kit family's own diffusion model, or a checkpoint without text
    # encoders of its own, is refused here, naming the part that is missing.
    missing = _missing_part(family_name, names, path, model)
    if missing is not None:
        _refuse_part(family_name, missing, sprache)
    if "diffusion_model" not in names or family is None:
        # A checkpoint without text encoders of its own starts with the
        # encoders and the further parts of its family beside it; any other
        # with its VAE alone.
        encoders = {
            field: parts[field] for field in (family.encoders if family is not None else ())
            if parts.get(field)
        }
        bare = family is not None and family.kit and bildinhalt.checkpoint_without_text_encoders(path)
        bundle = (
            {field: parts[field] for field in _VIDEO_PART_FIELDS if parts.get(field)}
            if bare else {}
        )
        return {
            **({"familie": family_name, **encoders} if encoders else {}),
            **({"vae": parts["vae"], **tae} if parts.get("vae") else {}),
            **({"video_parts": bundle} if bundle else {}),
        }
    bundle = {field: parts.pop(field) for field in _VIDEO_PART_FIELDS if parts.get(field)}
    return {
        "familie": family_name, "diffusion_model": path, "model_args": family.model_args,
        **parts, **tae, **({"video_parts": bundle} if bundle else {}),
    }


def _missing_part(
    family_name: str, names: dict[str, str], path: Path, model: str,
) -> str | None:
    """The first part a model cannot be started or drawn without, as its kit
    (``_model_kit``) stands: for a kit family's own diffusion model the part
    its docs name (``bildbausatz.fehlendes_teil``), for a checkpoint without
    text encoders of its own the encoder its family cannot do without
    (``bildbausatz.fehlender_textversteher``), nothing for any other model.
    The one rule behind both the start's refusal and the model list's
    ``missing_parts``."""
    family = image_families.get(family_name)
    if family is None or not family.kit:
        return None
    parts: dict[str, object | None] = {
        field: name for field, name in names.items() if field != "diffusion_model"
    }
    if "diffusion_model" in names:
        return bildbausatz.fehlendes_teil(family_name, parts, model)
    if bildinhalt.checkpoint_without_text_encoders(path):
        return bildbausatz.fehlender_textversteher(family_name, parts)
    return None


def missing_kit_part(
    config: Config, repositories: Repositories, model: str, path: Path,
) -> str | None:
    """The name, as the user reads it, of the first kit part a model misses,
    or None when it can be started and drawn as it stands. A model whose
    family is not read has exactly the parts given to it and misses none."""
    if not bildmodellwerte.family_detection(repositories, model):
        return None
    family_name = _start_family(repositories, path, model)
    names = _model_kit(config, repositories, model, path, image_families.get(family_name))
    missing = _missing_part(family_name, names, path, model)
    return None if missing is None else bildbausatz.teil_name(family_name, missing)


def _missing_parts_of(
    config: Config, repositories: Repositories, names: list[str],
) -> dict[str, str]:
    """``missing_kit_part`` for every model of the folder that misses one."""
    out: dict[str, str] = {}
    for name in names:
        try:
            path = modell_pfad(_bildordner(config), name)
        except BildFehler:
            continue
        missing = missing_kit_part(config, repositories, name, path)
        if missing is not None:
            out[name] = missing
    return out


@router.post("/bild/turbo/start", response_model=TurboAntwort, summary="Switch Image-Turbo on")
def turbo_starten(
    daten: TurboStart, request: Request,
    config: Config = Depends(hole_config), sprache: str = Depends(hole_sprache),
    repositories: Repositories = Depends(hole_repositories),
) -> TurboAntwort:
    turbo = _turbo(request)
    try:
        pfad = modell_pfad(_bildordner(config), daten.modell)
    except BildFehler as fehler:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t(fehler.grund, sprache)) from fehler
    kit = _kit_for_start(config, pfad, daten.modell, repositories, sprache)
    runner = _hold_picture_lock(request, sprache)
    try:
        # Switched on by hand on a bare Gespann — the model with its kit and
        # the machine's memory and devices, no detector yet. The LoRA folder
        # is pointed at from the start, so a LoRA picture works straight
        # away without a restart; a request that later wants a detector
        # restarts onto that Gespann on its own.
        #
        # The values of a picture are resolved through the SAME `bildwahlen`
        # validators the draw path uses for an absent field, and the memory
        # and devices come from the one setting every picture reads
        # (app/bildgeraete.py) — not a second copy of what "unset" means.
        geraete = bildgeraete.lesen(repositories)
        # The model's start values — the random source, the weight type, the
        # VAE format, the prediction and the switches its family starts with
        # — are read from the same places a picture of the default model
        # takes them from (app/image_start_values.py), and the machine's
        # switches are laid over the picture's as a draw lays them: so the
        # first picture finds a server that already carries its start values.
        family_name = _start_family(repositories, pfad, daten.modell)
        anfang = image_start_values.lesen(repositories, family_name, daten.modell)
        family = image_families.get(family_name)
        speicherschalter, speicherpfade = _switches(
            config,
            {**bildgeraete.ohne_speicherschalter(anfang.switches), **geraete.switches},
            sprache,
            on={
                "video": bool(family and family.video),
                "high_noise": "high_noise_diffusion_model" in (kit.get("video_parts") or {}),
            },
        )
        turbo.starten(
            pfad,
            lora_ordner=_bildordner(config) / bildwahlen.LORA_ORDNER,
            embd_ordner=_embd_ordner(config),
            rng=anfang.rng,
            weight_type=anfang.weight_type,
            vae_format=anfang.vae_format,
            threads=geraete.threads,
            vram_limit=geraete.vram_limit,
            offload_to_cpu=geraete.offload_to_cpu,
            split_mode=geraete.split_mode,
            backend=geraete.backend,
            extra_start=image_switches.server_start_parts(speicherschalter, speicherpfade),
            # Same rule as the LoRA folder above, and for the same reason:
            # `passt_zu()` compares this, so a hand switch that left it
            # unset would make the very next picture -- even one with no
            # upscaler and no highres at all -- look like a different
            # Gespann and pay a full model reload.
            upscaler_ordner=_upscaler_ordner(config),
            # The detailer's two new start flags and the prediction
            # override, resolved the same way the draw path resolves an
            # absent field rather than leaning on starten()'s own
            # parameter defaults (J4).
            ad_negativ="",
            ad_confidence=None,
            prediction=anfang.prediction,
            **kit,
        )
    except BildturboFehler as fehler:
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED, t(fehler.grund, sprache)
        ) from fehler
    finally:
        runner.freigeben()
    return _turbo_stand(turbo, runner, _selected_picture_model(config, repositories))


@router.post("/bild/turbo/stop", response_model=TurboAntwort, summary="Switch Image-Turbo off")
def turbo_stoppen(
    request: Request, sprache: str = Depends(hole_sprache),
    config: Config = Depends(hole_config),
    repositories: Repositories = Depends(hole_repositories),
) -> TurboAntwort:
    turbo = _turbo(request)
    runner = _hold_picture_lock(request, sprache)
    try:
        turbo.stoppen()
    finally:
        runner.freigeben()
    return _turbo_stand(turbo, runner, _selected_picture_model(config, repositories))


class BildVorgabenAntwort(BaseModel):
    breite: int
    hoehe: int
    schritte: int
    cfg: float
    guidance: float | None = None
    sampler: str = ""
    scheduler: str = ""
    # --flow-shift and --model-args the family starts with; None and ""
    # leave sd-cli's own.
    flow_shift: float | None = None
    model_args: str = ""
    # A video's frame count and rate the family starts with; None leaves
    # sd-cli's own.
    video_frames: int | None = None
    fps: int | None = None
    # --vae-format, --rng and further switches (by their key in
    # app/image_switches.py) the family starts with; empty leaves the
    # program's own. Their places stand in ``sources`` under the same names.
    vae_format: str = ""
    rng: str = ""
    switches: dict[str, bool | int | float | str] = Field(default_factory=dict)
    # The noise schedule the model is drawn with, as a list of numbers;
    # empty leaves it to the sampler.
    sigmas: str = ""
    # What belongs to the model itself (app/bildmodellwerte.py): its VAE,
    # CLIP skip and prediction type — empty or None is "Auto" — its trigger
    # words and a note.
    vae: str = ""
    clip_skip: int | None = None
    prediction: str = ""
    trigger: str = ""
    hinweis: str = ""
    # The names of the values above and of the measures that are the
    # model's own rather than its family's start values.
    eigene: list[str] = Field(default_factory=list)
    # The family read from the model's own header; empty when the header
    # names none of the table's families — then the window asks.
    family: str = ""
    # Whether the model's family is read from its file at all. Off — the
    # user switched it off for this model — ``family`` is empty, every kit
    # part can be given, and exactly the given ones are sent.
    family_detection: bool = True
    # The diffusion model chosen for a model whose family is not read;
    # empty, the model's own file goes to sd.cpp as it is.
    diffusion_model: str = ""
    # The model is a kit's diffusion model on its own (no text encoder or
    # VAE inside), drawn with --diffusion-model rather than -m.
    standalone: bool = False
    # The model is a checkpoint of a kit family that brings no text encoder of
    # its own: it is drawn with ``-m`` and takes the encoders and further
    # parts of its family beside it.
    bare: bool = False
    # The further parts the docs name for this standalone model (``Family.parts``
    # it cannot be started without), by the draw route's field name.
    needed_parts: list[str] = Field(default_factory=list)
    # The further parts of the family (``Family.parts``) this model takes: the
    # page and the studio show a part at the models that take it only.
    parts_taken: list[str] = Field(default_factory=list)
    # The model's kit by the draw route's field name (vae, t5xxl, clip_l,
    # llm, …): the parts given to the model in the picture server over the
    # ones the folder offers for its family — what every picture of the
    # model is drawn with.
    parts: dict[str, str] = Field(default_factory=dict)
    # Where each start value came from (app/image_families.py).
    sources: dict[str, str] = Field(default_factory=dict)


@router.get("/bild/server/log", response_model=list[str], summary="Server messages")
def bildserver_protokoll(request: Request) -> list[str]:
    """The picture server's own words since its last start, for the window's
    server log — the same answer every other server window reads."""
    return request.app.state.bildturbo.protokoll()


@router.get("/bild/familien", summary="Model family table")
def bild_familien() -> list[dict]:
    """The one table of families — the window's family list, the fields a
    kit reads and every start value with its source."""
    return image_families.as_json()


@router.get("/bild/switches", summary="Additional sd.cpp options")
def image_switch_table(config: Config = Depends(hole_config)) -> dict:
    """The further switches the window offers, the files of each folder a
    file switch picks from, and the weight types — one list for every
    field that offers them."""
    table = image_switches.as_json()
    folders = {row["folder"] for row in table if row["folder"]}
    return {
        "switches": table,
        "weight_types": list(bildwahlen.WEIGHT_TYPES),
        "files": {
            folder: image_switches.files(_bildordner(config), folder) for folder in sorted(folders)
        },
    }


def _kit_complete(
    family_name: str, parts: dict[str, object | None], sprache: str, model: str | None = None,
) -> None:
    """Refuse a kit that misses a part its family needs, naming the part.
    Asked before sd.cpp starts — on the server's start by hand as on a
    drawing — so it never starts on half a kit. ``model`` is the standalone
    diffusion model: with it the further parts the docs name for it count."""
    missing = bildbausatz.fehlendes_teil(family_name, parts, model)
    if missing is not None:
        _refuse_part(family_name, missing, sprache)


def _encoders_complete(
    family_name: str, parts: dict[str, object | None], sprache: str,
) -> None:
    """Refuse a checkpoint without text encoders of its own whose family
    cannot do without one (``needs_text_encoder``) and whose encoder is not at
    hand, naming it: sd.cpp would start on it and stop at the first weight it
    misses. Any other family goes on with the encoders it is given."""
    missing = bildbausatz.fehlender_textversteher(family_name, parts)
    if missing is not None:
        _refuse_part(family_name, missing, sprache)


def _refuse_part(family_name: str, part: str, sprache: str) -> NoReturn:
    """The refusal a model that misses a kit part gets, naming the part."""
    raise HTTPException(
        status.HTTP_412_PRECONDITION_FAILED,
        t("bild.teil_fehlt", sprache, teil=bildbausatz.teil_name(family_name, part)),
    )


@router.get("/bild/vorgaben", response_model=BildVorgabenAntwort, summary="Default values for each "
                                                                          "model")
def bild_vorgaben(
    modell: str | None = None,
    chosen_family: str = "",
    config: Config = Depends(hole_config),
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> BildVorgabenAntwort:
    """The values the picture window opens on for a given model: its
    family, read from the model's own header, that family's start values
    from the one table (the model's variant, told by its file name, over
    them), the values the user set for this model in the picture server
    (app/bildmodellwerte.py) laid over those, and the companion files that
    fit it. A model whose family cannot be read starts where sd-cli starts,
    and the window asks for the family.

    ``chosen_family`` is a family the window was told by hand: it decides
    the start values and nothing else — the family field of the answer, the
    kit and its parts stay what the header says. Empty is "automatic"."""
    if chosen_family and not image_families.known(chosen_family):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, t("bild.familie_ungueltig", sprache))
    family_name = ""
    standalone = False
    bare = False
    needed: list[str] = []
    parts: dict[str, str] = {}
    detection = bildmodellwerte.family_detection(repositories, modell) if modell else True
    chosen_diffusion_model = ""
    if modell:
        try:
            path = modell_pfad(_bildordner(config), modell)
        except BildFehler:
            path = None
        if path is not None:
            # The header is not asked for a family where the reading is off.
            family_name = (bildinhalt.family(path) or "") if detection else ""
            family = image_families.get(family_name)
            # Told for every model: a diffusion model whose family the
            # header does not name is still one, and the window fills it
            # in once the family is said by hand.
            standalone = bildinhalt.standalone_diffusion_model(path)
            if family is not None and family.kit:
                bare = not standalone and bildinhalt.checkpoint_without_text_encoders(path)
                if standalone:
                    needed = list(image_families.needed_parts(family, modell))
            kit = _model_kit(config, repositories, modell, path, family)
            parts = {field: name for field, name in kit.items() if field != "diffusion_model"}
            if not detection:
                chosen_diffusion_model = kit.get("diffusion_model", "")
            log.info("Picture model %s: family %s", modell, family_name or "not recognised")
    # The values come from the family said by hand, else from the header's.
    values_family = chosen_family or family_name
    start = image_families.start_values(values_family, modell)
    werte: dict = {
        "breite": start.width, "hoehe": start.height, "schritte": start.steps,
        "cfg": start.cfg, "guidance": start.guidance,
        "sampler": start.sampler, "scheduler": start.scheduler,
        "flow_shift": start.flow_shift, "sigmas": start.sigmas,
    }
    eigene = bildmodellwerte.eigene(repositories, modell) if modell else {}
    start_family = image_families.get(values_family)
    # A model that draws at one frame rate has no rate of its own.
    if start_family is not None and start_family.fixed_fps:
        eigene.pop("fps", None)
    # Frames and rate are answered under their own fields below.
    own_video = {name: eigene[name] for name in ("video_frames", "fps") if name in eigene}
    werte.update({name: wert for name, wert in eigene.items() if name not in own_video})
    # Told only while it is read, and only a file that is still there.
    werte[bildmodellwerte.DIFFUSION_MODEL] = chosen_diffusion_model
    quellen = dict(start.sources)
    for name in eigene:
        quellen[name] = "model"
    return BildVorgabenAntwort(
        **werte,
        video_frames=own_video.get("video_frames", start.frames),
        fps=None if start_family is not None and start_family.fixed_fps
        else own_video.get("fps", start.fps),
        vae_format=start.vae_format, rng=start.rng, switches=dict(start.switches),
        model_args=start_family.model_args if start_family is not None else "",
        family=family_name, standalone=standalone, bare=bare, needed_parts=needed, parts=parts,
        parts_taken=list(image_families.parts_taken(start_family, modell)) if modell else [],
        family_detection=detection,
        sources=quellen, eigene=sorted(eigene),
    )


@router.post("/bild/folder", response_model=bool, summary="Show the image models")
def bildordner_zeigen(
    config: Config = Depends(hole_config), sprache: str = Depends(hole_sprache)
) -> bool:
    """Its OWN folder — every kind of model gets its own button."""
    try:
        ordner_oeffnen(_bildordner(config))
    except OeffnenNichtMoeglich:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, t("fehler.ordner_oeffnen", sprache)
        ) from None
    return True


# --- Fetching the generator itself ----------------------------------------


class GeneratorFortschritt(BaseModel):
    geladen: int
    gesamt: int
    anteil: float
    fertig: bool
    fehler: str | None = None


# One fetch object for the whole service, built on first ask and kept. Two
# requests arriving in the same moment would otherwise each build one, and
# two of them would download the same archive into the same file. The lock
# is what makes "check, then create" a single step.
_bauschloss = threading.Lock()


def hole_sddownload(request: Request, config: Config = Depends(hole_config)) -> Sddownload:
    with _bauschloss:
        vorhanden = getattr(request.app.state, "sddownload", None)
        if vorhanden is None:
            vorhanden = Sddownload(config.datenverzeichnis)
            request.app.state.sddownload = vorhanden
        return vorhanden


def _generatorstand(download: Sddownload) -> GeneratorFortschritt | None:
    stand = download.stand()
    if stand is None:
        return None
    return GeneratorFortschritt(
        geladen=stand.geladen,
        gesamt=stand.gesamt,
        anteil=stand.anteil,
        fertig=stand.fertig,
        fehler=stand.fehler,
    )


class GeneratorVariante(BaseModel):
    variante: str
    groesse: int


class GeneratorVariantenAntwort(BaseModel):
    varianten: list[GeneratorVariante]
    installiert: str | None
    # Builds this machine cannot run, listed so that they are seen (a Mac
    # names the four of Windows); nothing can be fetched from this list.
    unavailable: list[GeneratorVariante] = []


class GeneratorHolenAnfrage(BaseModel):
    variante: str | None = None
    # True fetches whatever release is newest at the moment of the request,
    # not the pinned build — the client's own idea of which build that is
    # (from an earlier /bild/programm/aktualisierung poll) is never trusted
    # for the fetch itself, only for showing the offer.
    aktualisieren: bool = False
    # True fetches the pinned, tested build in place of the one installed.
    restore: bool = False


class GeneratorAktualisierung(BaseModel):
    verfuegbar: bool
    bau: str | None = None
    # True only when the newest release WAS read and is not ahead of the
    # build on disk. Not the same as "nothing available": an unreachable
    # release page or an unreadable tag compares nothing, and the window
    # must not answer that with "up to date".
    aktuell: bool = False
    # True when a build is installed and the newest release could not be
    # read: the window says so, instead of showing nothing.
    unreadable: bool = False


@router.get(
    "/bild/programm",
    response_model=GeneratorFortschritt | None,
    summary="Image generator download progress",
)
def generator_fortschritt(
    download: Sddownload = Depends(hole_sddownload),
) -> GeneratorFortschritt | None:
    return _generatorstand(download)


@router.get(
    "/bild/programm/varianten",
    response_model=GeneratorVariantenAntwort,
    summary="GPU builds available for this PC",
)
def generator_varianten(
    config: Config = Depends(hole_config),
    repositories: Repositories = Depends(hole_repositories),
) -> GeneratorVariantenAntwort:
    return GeneratorVariantenAntwort(
        varianten=[
            GeneratorVariante(variante=variante, groesse=groesse)
            for variante, groesse in sddownload.waehlbare_varianten()
        ],
        installiert=sddownload.installierte_variante(
            config.datenverzeichnis, variante=picture_program_choice.picked(repositories)
        ),
        unavailable=[
            GeneratorVariante(variante=variante, groesse=groesse)
            for variante, groesse in sddownload.unavailable_variants()
        ],
    )


@router.get(
    "/bild/programm/aktualisierung",
    response_model=GeneratorAktualisierung,
    summary="Whether a newer generator version is available",
)
def generator_aktualisierung(
    config: Config = Depends(hole_config),
    repositories: Repositories = Depends(hole_repositories),
) -> GeneratorAktualisierung:
    """Asked when the panel's check is pressed, never on opening and never
    on a timer: reads the project's newest release and compares its build
    number against whichever build is actually on disk (the pinned one, on
    a fresh install). Nothing installed yet has nothing to compare against —
    the plain fetch below already covers that case."""
    installiert = sddownload.installierter_bau(
        config.datenverzeichnis, picture_program_choice.picked(repositories)
    )
    if installiert is None:
        return GeneratorAktualisierung(verfuegbar=False)
    veroeffentlichung = sddownload.neueste_veroeffentlichung()
    if veroeffentlichung is None:
        return GeneratorAktualisierung(verfuegbar=False, unreadable=True)
    if sddownload.ist_voraus(veroeffentlichung, installiert):
        return GeneratorAktualisierung(verfuegbar=True, bau=veroeffentlichung.bau)
    return GeneratorAktualisierung(verfuegbar=False, aktuell=True)


@router.post(
    "/bild/satz",
    response_model=PictureFromSentenceAnswer,
    status_code=status.HTTP_201_CREATED,
    summary="Draw a picture from one sentence with the default model",
)
async def picture_from_sentence(
    wunsch: PictureFromSentence,
    request: Request,
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> PictureFromSentenceAnswer:
    """Draws from the sentence with exactly the values ``draw_image`` takes:
    the default model of the picture server and its start values, in the
    ONE place the tool reads them (``bild_werkzeug.draw_with_window``).

    The picture stays in the pictures folder; the answer says where. It is not
    written into the chat — nobody is writing an answer there. Progress and
    stop are the ones every picture has (``/bild/fortschritt``,
    ``/bild/stop``)."""
    if _chat(request, wunsch.chat_id) is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t("fehler.chat_nicht_gefunden", sprache)
        )
    drawn = await bild_werkzeug.draw_with_window(
        {"prompt": wunsch.prompt}, "http://dienst/api/v1", request.app.state.sitzungsschluessel,
        chat_id=wunsch.chat_id, transport=httpx.ASGITransport(app=request.app),
    )
    if isinstance(drawn, str):
        # The sentence the tool would read: the picture was not drawn, and why.
        raise HTTPException(status.HTTP_409_CONFLICT, drawn)
    name = str(drawn.answer["bild"])
    values = {
        key: value for key, value in drawn.body.items()
        if key not in ("prompt", "negativ", "modell", "chat_id", "lauf_kennung")
    }
    return PictureFromSentenceAnswer(
        bild=name, pfad=str(ort(config, "images") / name), seed=drawn.answer.get("seed"),
        modell=drawn.model, prompt=drawn.prepared.prompt, werte=values,
    )


@router.post(
    "/bild/programm", response_model=GeneratorFortschritt, summary="Download the image "
                                                                   "generator"
)
def generator_holen(
    anfrage: GeneratorHolenAnfrage | None = None,
    download: Sddownload = Depends(hole_sddownload),
    config: Config = Depends(hole_config),
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> GeneratorFortschritt:
    """Fetches sd-cli from a release of the project's own stable-diffusion.cpp
    fork — the pinned build, or, with ``aktualisieren``, whichever one is
    newest at this exact moment, or, with ``restore``, the pinned one in
    place of the build installed.

    The one thing this panel could not do was the one thing a fresh
    installation needs: it said the generator was missing and left it at
    that. Now the same sentence carries a button, and the program lands in
    the data folder where the runner looks by itself.
    """
    variante = anfrage.variante if anfrage else None
    veroeffentlichung = None
    restore = bool(anfrage and anfrage.restore)
    # The variant picked earlier: the one whose build folder runs, and so
    # the one an update or a way back is about.
    picked_variant = picture_program_choice.picked(repositories)
    wechsel = False
    if restore:
        # The way back from an update, and nothing else: with the tested
        # build installed, or a generator unpacked by hand, there is
        # nothing to go back from.
        if not sddownload.restorable(config.datenverzeichnis, picked_variant):
            raise HTTPException(
                status.HTTP_409_CONFLICT, t("fehler.sddownload_schon_da", sprache)
            )
        if variante is None:
            # The variant that is installed, exactly as an update takes it.
            variante = sddownload.installierte_variante(
                config.datenverzeichnis, variante=picked_variant
            )
    elif anfrage and anfrage.aktualisieren:
        # An update is a catch-up on an existing install, not a second way
        # to bootstrap one — a fresh install already has the plain fetch
        # below, at the pinned, tested build. Nothing on disk means nothing
        # to compare a release against, exactly as the GET route reports.
        installiert = sddownload.installierter_bau(config.datenverzeichnis, picked_variant)
        # Re-read just before fetching rather than trust whatever the panel
        # showed a moment ago — an offer that went stale between the poll
        # and the click must not silently re-fetch the build already there.
        veroeffentlichung = sddownload.neuere_fassung(installiert) if installiert else None
        if veroeffentlichung is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, t("fehler.sddownload_keine_neuere_fassung", sprache)
            )
        if variante is None:
            # Update the variant that is actually installed, not whatever
            # the panel's own variant picker happened to have loaded (or
            # not yet loaded) at the moment the button was pressed. `bau`
            # is passed straight in — `installiert` above already walked
            # the folder once to find it.
            variante = sddownload.installierte_variante(
                config.datenverzeichnis, bau=installiert, variante=picked_variant
            )
    elif variante is not None and sddownload.waehlbare_varianten():
        # A switch to another variant of a program that is installed brings
        # that variant's newest number, not the pinned one — a release page
        # unreadable, or a release without that variant, leaves the pinned
        # build to fetch. A fresh install has no program to switch from and
        # takes the pinned, tested build.
        installiert = sddownload.installierter_bau(config.datenverzeichnis, picked_variant)
        if installiert is not None and variante != sddownload.installierte_variante(
            config.datenverzeichnis, bau=installiert, variante=picked_variant
        ):
            wechsel = True
            veroeffentlichung = sddownload.latest_for(variante)
    if variante is not None and not sddownload.gueltige_variante(variante):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, t("fehler.sddownload_unbekannte_variante", sprache)
        )
    try:
        download.starten(variante, veroeffentlichung, replace_newer=restore)
    except SddownloadFehler as fehler:
        if (
            fehler.grund == "schon_da"
            and wechsel
            and variante is not None
            and sddownload.variante_installiert(config.datenverzeichnis, variante)
        ):
            # The variant switched to is on disk already, in the number that
            # would be fetched: nothing to fetch, and the pick is all that
            # is left. Asking for the variant that runs stays "already there".
            picture_program_choice.remember(repositories, variante)
            return GeneratorFortschritt(geladen=0, gesamt=0, anteil=1.0, fertig=True)
        lage = {
            "laeuft_schon": status.HTTP_409_CONFLICT,
            "schon_da": status.HTTP_409_CONFLICT,
        }.get(fehler.grund, status.HTTP_400_BAD_REQUEST)
        raise HTTPException(lage, t(f"fehler.sddownload_{fehler.grund}", sprache)) from None
    if variante is not None and sddownload.waehlbare_varianten():
        picture_program_choice.remember(repositories, variante)
    stand = _generatorstand(download)
    assert stand is not None
    return stand


class FortschrittAntwort(BaseModel):
    """The running picture's honest step counter, for the filling frame.

    `laeuft` False means: nothing to show — the interface keeps its quiet
    wave without a number. The share is overall across the run's passes
    (base, highres, detailer), capped just under one until the file truly
    exists."""

    laeuft: bool
    anteil: float = 0.0
    schritt: int = 0
    gesamt: int = 0
    # The newest live preview's stamp; 0 while there is none.
    preview: int = 0


@router.get("/bild/fortschritt", response_model=FortschrittAntwort, summary="Image generation "
                                                                            "progress")
def bild_fortschritt(request: Request) -> FortschrittAntwort:
    stand = _runner(request).fortschritt() or _turbo(request).fortschritt()
    if not stand:
        return FortschrittAntwort(laeuft=False)
    return FortschrittAntwort(laeuft=True, **stand)


@router.post("/bild/info", summary="Image generation metadata")
async def picture_info_route(
    request: Request, language: str = Depends(hole_sprache),
) -> dict:
    """The prompt, the model and the values a picture carries, read by
    ``sd-cli -M metadata`` from the bytes sent — the picture itself is not
    kept. An empty answer: the picture carries none."""
    kind = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if kind not in ERLAUBTE_TYPEN:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, t("fehler.bild_typ", language))
    data = await request.body()
    if not data:
        # Nothing to read a header from — the same answer the upload gives
        # an empty body (app/api/v1/bilder.py).
        raise HTTPException(status.HTTP_400_BAD_REQUEST, t("fehler.bild_typ", language))
    program = _runner(request).programm
    if program is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, t("bild.kein_programm", language))
    with tempfile.TemporaryDirectory() as folder:
        picture = Path(folder) / f"picture{ERLAUBTE_TYPEN[kind]}"
        picture.write_bytes(data)
        return await asyncio.to_thread(picture_info.read, program, picture)


@router.get("/bild/info", summary="Generation settings for an image created by this "
                                  "installation")
def drawn_with_route(name: str, request: Request) -> dict:
    """The prompt, the model and the values the picture of this name was
    drawn with, as the draw kept them — in the form the reading of a file
    above answers in. Kept by the program, so they are there whether or not
    the file still carries its own. An empty answer: nothing is kept for
    that name — a picture drawn elsewhere, one from before, or none."""
    return _kept_values(request.app.state.repositories, name)


def _kept_values(repositories, name: str) -> dict:
    """What the draw kept for the picture of this name: at its message in a
    chat, else at the studio's list of its own pictures. Empty when neither
    knows the name."""
    return repositories.messages.drawn_with(name) or studio_pictures.drawn_with(repositories, name)


@router.get("/bild/preview", summary="Live preview of the image being generated")
def live_preview_picture(request: Request, language: str = Depends(hole_sprache)) -> Response:
    """The picture as far as it is drawn, while it is drawn with a live
    preview, by sd-cli or by the picture server. Fetched with the session
    key in its header, like any other call. Read at once into memory:
    sd-cli rewrites the file in place and the run deletes it at its end,
    so a file handed on by path could be gone or half written by the time
    it is sent. A draw on the picture server has its newest preview in
    memory (``Bildturbo.preview``); it is asked when sd-cli has none."""
    path = _runner(request).preview()
    data = None
    if path is not None:
        try:
            data = path.read_bytes()
        except OSError:
            data = None
    elif (from_server := _turbo(request).preview()) is not None:
        data = from_server
    # A PNG ends with its IEND chunk; one caught half written has none yet,
    # and the window keeps the preview it has until the next one is whole.
    if not data or not data.rstrip(b"\x00").endswith(b"IEND\xaeB`\x82"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("bild.vorschau_fehlt", language))
    return Response(data, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/bild/stop", response_model=bool, summary="Cancel image generation")
def bild_stoppen(request: Request) -> bool:
    """Ends the running picture. False when there was none.

    No id and no body: one picture runs at a time, so there is exactly one
    thing this can mean. Both paths are reached: the sd-cli runner, and a
    draw on the picture server, whose job is cancelled — or, once it draws,
    the server ended under it (see ``Bildturbo.abbrechen``). A model file
    being converted runs as the runner's process and ends the same way.
    """
    runner = _runner(request)
    gestoppt = runner.stoppen()
    # Neither draws yet, but a picture holds the lock: the picture server
    # still starts for it, or steps aside for it. The stop is kept for that
    # picture, which is then never drawn; the server is left alone.
    return _turbo(request).abbrechen() or gestoppt or runner.ask_stop()


@router.post("/bild/begleiter-folder/{unterordner}", response_model=bool,
             summary="Show a companion folder")
def begleiterordner_zeigen(
    unterordner: Literal[
        "vae", "lora", "adetailer", "embedding", "photomaker", "faces",
        "pulid", "controlnet", "upscaler", "taesd", "ipadapter",
    ],
    config: Config = Depends(hole_config), sprache: str = Depends(hole_sprache),
) -> bool:
    """Open one of the picture server's companion sub-folders so a file can be
    dropped in by hand — a stack nobody can fill is not a stack, so the folder
    is created if it is not there yet. The whitelist on the path is what keeps
    this from opening anything but a companion folder."""
    ordner = _bildordner(config) / unterordner
    ordner.mkdir(parents=True, exist_ok=True)
    try:
        ordner_oeffnen(ordner)
    except OeffnenNichtMoeglich:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, t("fehler.ordner_oeffnen", sprache)
        ) from None
    return True


@router.post(
    "/bild",
    response_model=BildAntwort,
    status_code=status.HTTP_201_CREATED,
    summary="Generate an image (offline)",
)
async def bild_erzeugen(
    wunsch: BildWunsch,
    request: Request,
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
    repositories: Repositories = Depends(hole_repositories),
) -> BildAntwort:
    runner = _runner(request)
    if runner.programm is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, t("bild.kein_programm", sprache)
        )
    try:
        pfad = modell_pfad(_bildordner(config), wunsch.modell)
    except BildFehler as fehler:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t(fehler.grund, sprache)) from fehler
    # A chat that does not exist is said so before anything is drawn. One
    # that is missing when the drawing has ended was deleted meanwhile.
    if wunsch.chat_id and _chat(request, wunsch.chat_id) is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t("fehler.chat_nicht_gefunden", sprache)
        )

    startbild = _startbild(config, wunsch.startbild, sprache)
    # A mask without a starting image has nothing to mask — dropped here
    # rather than passed on, so the command line stays honest.
    maske = _startbild(config, wunsch.maske, sprache) if startbild else None
    crop_whole = _crop_whole(config, wunsch) if startbild else None

    # PhotoMaker needs a class word in the prompt to fire at all. Nobody types
    # it — the window asks who is in the photos, and it is attached here.
    #
    # All three parts are decided TOGETHER, and that is the point: the trigger
    # word must never reach the prompt unless the model and the photos are
    # really there. Deciding it in two places once meant a run with no model
    # still got "a man img" pushed in front of the prompt — and drew something
    # nobody asked for, with nothing on screen to explain why.
    pm_klasse = photomaker.klasse_pruefen(wunsch.pm_klasse)
    pm_modell = photomaker.modell(_bildordner(config)) if pm_klasse else None
    pm_gesichter = photomaker.gesichter(_bildordner(config)) if pm_klasse else None
    if pm_gesichter is not None:
        # Center-cropped and resized to a fixed edge length before either
        # painter ever sees them — sd-cli's own internal scale to 224 can
        # round a photo's dimensions down by one pixel and silently skip
        # the whole batch's face transfer otherwise.
        # The originals in gesichter/ are untouched either way.
        pm_gesichter = gesichteraufbereitung.aufbereiten(
            pm_gesichter, _bildordner(config) / gesichteraufbereitung.ARBEITSORDNER
        )
    if pm_modell is None or pm_gesichter is None:
        # Half of it is nothing at all: no flags, and above all no trigger word.
        pm_klasse = ""

    # PuLID and ControlNet, same "both halves or neither" rule as
    # PhotoMaker just above: a model with nothing to carry, or a guide
    # image nothing steers, is worse than either being simply off.
    pulid_gewichte = _begleiter(pulid_pfad, config, wunsch.pulid_weights, sprache)
    # Looked up only beside weights: an embedding name left over with PuLID
    # off must not stop a picture that does not use it.
    pulid_einbettung = _begleiter(
        pulid_embedding_pfad, config, wunsch.pulid_id_embedding, sprache
    ) if pulid_gewichte is not None else None
    if pulid_gewichte is None or pulid_einbettung is None:
        pulid_gewichte = None
        pulid_einbettung = None
    control_net_modell = _begleiter(controlnet_pfad, config, wunsch.control_net, sprache)
    control_bild = _startbild(config, wunsch.control_image, sprache)
    if control_net_modell is None or control_bild is None:
        control_net_modell = None
        control_bild = None

    # The highres upscaler travels by NAME, never a path: either one of
    # sd-cli's built-in names, or a model file that really lies in the
    # upscaler folder — anything else is refused like any other unknown
    # companion, instead of riding on and silently falling back to the
    # default upscaler. The folder itself rides along whenever it exists
    # (the same "pointed at even when this picture does not use it" rule
    # as the LoRA folder), so Turbo can resolve a model name per request.
    hires_upscaler = wunsch.hires_upscaler.strip()
    upscaler_ordner = _upscaler_ordner(config)
    if hires_upscaler and hires_upscaler not in bildwahlen.HIRES_UPSCALER_FESTE:
        in_folder = upscaler_scales(_bildordner(config))
        if hires_upscaler not in in_folder:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, t("bild.begleiter_unbekannt", sprache)
            )
        # sd.cpp names a model-backed upscaler without its extension and
        # refuses the file name on both paths (sd-cli exits at once,
        # sd-server answers "invalid params"); it looks the file up in the
        # upscaler folder itself. Checked with the extension above, sent
        # without it from here on.
        name = Path(hires_upscaler).stem
        # Without the extension two files (x.pth, x.safetensors) or a file
        # and a built-in name (Lanczos.pth, Lanczos) become one name, and
        # sd.cpp, which checks its built-in names first, would draw with
        # the wrong one. Refused instead of guessed: a built-in name as it is
        # spelled, another file without case, as the file systems it runs on
        # find a file. Only when the second pass runs: the field rides along
        # locked while highres is off.
        key = name.casefold()
        if wunsch.hires and (
            name in bildwahlen.HIRES_UPSCALER_FESTE
            or any(
                Path(other).stem.casefold() == key and other != hires_upscaler
                for other in in_folder
            )
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT, t("bild.upscaler_doppelt", sprache, name=name)
            )
        hires_upscaler = name

    # What the model IS — the family the window states, or the one the
    # model's own header names (app/bildinhalt.py), never a guess from its
    # name. Read before the parts are checked, so a request that sends a
    # kit's parts without naming the family is judged by the header. A
    # model neither names stays without one and draws with sd-cli's own
    # defaults for everything the request leaves out. Read off the thread:
    # a header not read before can be megabytes.
    # A model whose family is not to be read (app/bildmodellwerte.py) is
    # drawn with exactly the parts given to it, and with the diffusion
    # model chosen for it where one was. A family said in the window still
    # sets the values the picture starts at; about the parts it says
    # nothing.
    free = wunsch.mode != "upscale" and not await asyncio.to_thread(
        bildmodellwerte.family_detection, repositories, wunsch.modell
    )
    if wunsch.familie:
        # A word said is checked as said: an unknown one is refused below,
        # never quietly replaced by what the header says.
        family_name = wunsch.familie
    elif free:
        family_name = ""
    else:
        roh_familie: str | None = await asyncio.to_thread(
            bildinhalt.family,
            _begleiter(modell_pfad, config, wunsch.diffusion_model, sprache) or pfad,
        )
        family_name = roh_familie or ""
    # The model's kit as the picture server holds it for every chat
    # (``_model_kit``) — the picture window and the drawing tool name no
    # parts. A request that names parts itself is drawn with exactly those;
    # enlarging a finished picture draws nothing with the model.
    if wunsch.mode != "upscale" and all(
        getattr(wunsch, field) is None for field in ("diffusion_model", *_KIT_PART_FOLDERS)
    ):
        kit = await asyncio.to_thread(
            _model_kit, config, repositories, wunsch.modell, pfad,
            image_families.get(family_name),
        )
        wunsch = wunsch.model_copy(update=kit)
    # A checkpoint of a kit family that brings no text encoder of its own and
    # cannot do without one is refused, naming the encoder, when none is at
    # hand: sd.cpp would start on it and stop at the first weight it misses.
    family_of_wish = image_families.get(family_name)
    if (
        wunsch.mode != "upscale" and not free and wunsch.diffusion_model is None
        and family_of_wish is not None and family_of_wish.kit
    ):
        given = {field: getattr(wunsch, field, None) for field in family_of_wish.encoders}
        if bildbausatz.fehlender_textversteher(family_name, given) is not None and (
            await asyncio.to_thread(bildinhalt.checkpoint_without_text_encoders, pfad)
        ):
            _encoders_complete(family_name, given, sprache)
    try:
        if free:
            # No family decides about the parts; only a family word nobody
            # knows is still refused.
            if wunsch.familie and not image_families.known(wunsch.familie):
                raise ValueError(f"Unknown model family: {wunsch.familie!r}")
        else:
            bildbausatz.familie_pruefen(
                family_name,
                diffusion_model=wunsch.diffusion_model, t5xxl=wunsch.t5xxl,
                clip_l=wunsch.clip_l, clip_g=wunsch.clip_g, llm=wunsch.llm,
                llm_vision=wunsch.llm_vision, tokenizer=wunsch.tokenizer,
                uncond_diffusion_model=wunsch.uncond_diffusion_model,
                bare_checkpoint=(
                    wunsch.diffusion_model is None
                    and any((wunsch.t5xxl, wunsch.clip_l, wunsch.clip_g, wunsch.llm))
                    and bildinhalt.checkpoint_without_text_encoders(pfad)
                ),
                high_noise_diffusion_model=wunsch.high_noise_diffusion_model,
                audio_vae=wunsch.audio_vae, audio_encoder=wunsch.audio_encoder,
                embeddings_connectors=wunsch.embeddings_connectors,
                clip_vision=wunsch.clip_vision,
            )
    except ValueError as fehler:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, t("bild.familie_ungueltig", sprache)
        ) from fehler

    # A Bausatz's files, resolved for the Auftrag.
    bausatz_diffusion_model = _begleiter(modell_pfad, config, wunsch.diffusion_model, sprache)
    bausatz_t5xxl = _begleiter(textversteher_pfad, config, wunsch.t5xxl, sprache)
    bausatz_clip_l = _begleiter(textversteher_pfad, config, wunsch.clip_l, sprache)
    bausatz_clip_g = _begleiter(textversteher_pfad, config, wunsch.clip_g, sprache)
    bausatz_llm = _begleiter(textversteher_pfad, config, wunsch.llm, sprache)
    bausatz_llm_vision = _begleiter(vision_part_path, config, wunsch.llm_vision, sprache)
    bausatz_tokenizer = _begleiter(tokenizer_pfad, config, wunsch.tokenizer, sprache)
    bausatz_uncond = _begleiter(modell_pfad, config, wunsch.uncond_diffusion_model, sprache)
    bausatz_high_noise = _begleiter(
        modell_pfad, config, wunsch.high_noise_diffusion_model, sprache
    )
    bausatz_audio_vae = _begleiter(vae_pfad, config, wunsch.audio_vae, sprache)
    bausatz_audio_encoder = _begleiter(textversteher_pfad, config, wunsch.audio_encoder, sprache)
    bausatz_connectors = _begleiter(
        textversteher_pfad, config, wunsch.embeddings_connectors, sprache
    )
    bausatz_clip_vision = _begleiter(textversteher_pfad, config, wunsch.clip_vision, sprache)
    vae = _begleiter(vae_choice_path, config, wunsch.vae, sprache)
    # A kit missing a part never reaches sd.cpp: the answer names the part.
    # A free kit has no family that could miss one.
    if bausatz_diffusion_model is not None and not free:
        _kit_complete(family_name, {
            "t5xxl": bausatz_t5xxl, "clip_l": bausatz_clip_l, "clip_g": bausatz_clip_g,
            "llm": bausatz_llm, "llm_vision": bausatz_llm_vision, "tokenizer": bausatz_tokenizer,
            "vae": vae, "audio_vae": bausatz_audio_vae,
            "audio_encoder": bausatz_audio_encoder, "embeddings_connectors": bausatz_connectors,
            # Given by the model's part or, as before, by the switch of that name.
            "clip_vision": bausatz_clip_vision or wunsch.switches.get("clip_vision"),
        }, sprache, wunsch.diffusion_model)
    # A video model draws in video mode only, a single frame included
    # (sd.cpp docs/wan.md:3); any other model when the wish asks for one.
    family_entry = image_families.get(family_name)
    # sd.cpp hands the guide image to a UNet model only; for any other family
    # the option would be passed over without a word, so it is not sent.
    if family_entry is not None and not family_entry.control_net:
        control_net_modell = None
        control_bild = None
    video = wunsch.video or bool(family_entry and family_entry.video)
    end_bild = _startbild(config, wunsch.end_bild, sprache) if video else None
    steuerbilder = tuple(
        bild for name in wunsch.steuerbilder
        if (bild := _startbild(config, name, sprache)) is not None
    ) if video else ()
    ref_video_frames = tuple(
        bild for name in wunsch.ref_video_frames
        if (bild := _startbild(config, name, sprache)) is not None
    ) if video else ()
    # The reference pictures of an edit, each resolved like the starting
    # image; the values beside them only travel with at least one.
    ref_bilder = tuple(
        bild for name in wunsch.ref_bilder
        if (bild := _startbild(config, name, sprache)) is not None
    )
    # No picture goes to the painter larger than the drawing needs it. Not
    # for a mode on a finished picture: that picture IS the work, at its
    # own size.
    # The mask as the painter gets it. Setting a drawn piece back into its
    # picture reads the mask itself (further down), at its own size.
    painter_mask = maske
    if not wunsch.mode and (
        startbild or end_bild or control_bild or steuerbilder or ref_bilder
        or ref_video_frames
    ):
        # Off the event loop, in one go: scaling starts the system's tool.
        (
            (startbild, end_bild, control_bild), steuerbilder, ref_bilder,
            ref_video_frames, painter_mask,
        ) = await asyncio.to_thread(
            _fitted, config, wunsch,
            (startbild, end_bild, control_bild), steuerbilder, ref_bilder,
            ref_video_frames, maske,
        )
    bausatz_vae_format = bildwahlen.vae_format_pruefen(wunsch.vae_format)
    bausatz_guidance = (
        max(0.0, float(wunsch.guidance)) if wunsch.guidance is not None else None
    )

    # The memory block's switches are the machine's, stored once for every
    # chat; the picture's own come with the request.
    geraete = bildgeraete.lesen(repositories)
    switch_values = {**bildgeraete.ohne_speicherschalter(wunsch.switches), **geraete.switches}
    # sd.cpp is given one CLIP Vision: the model's own part, where it has one;
    # the switch of the same name serves the models without that part.
    if bausatz_clip_vision is not None:
        switch_values.pop("clip_vision", None)
    switches, switch_paths = _switches(
        config, switch_values, sprache,
        on={
            "ad_model": bool(wunsch.ad_modell),
            "photomaker": bool(pm_klasse),
            "hires": bool(wunsch.hires),
            "video": video,
            "high_noise": bausatz_high_noise is not None,
            "ref_video": bool(ref_video_frames),
        },
    )
    if not wunsch.mode and any(
        image_switches.BY_KEY[key].kind == "picture" for key in switch_paths
    ):
        switch_paths = await asyncio.to_thread(
            _fitted_switch_pictures, config, wunsch, switch_paths
        )

    gestalt_prompt, gestalt_negativ = bildstile.anwenden(
        wunsch.prompt, wunsch.negativ, wunsch.stil_text, wunsch.stil_negativ
    )
    auftrag = Auftrag(
        modell=pfad,
        prompt=photomaker.prompt_mit_klasse(gestalt_prompt, pm_klasse),
        negativ=gestalt_negativ,
        breite=_kante(wunsch.breite),
        hoehe=_kante(wunsch.hoehe),
        schritte=int(wunsch.schritte),
        # Free for every family: the start value of a kit family is low
        # (sd.cpp's docs recommend 1 for Flux), but a value the user sets
        # is the value that is drawn.
        cfg=max(0.0, float(wunsch.cfg)),
        # "Let the generator pick" is turned into a real number HERE, not
        # left to the generator. The answer reports the seed, and a seed of
        # -1 tells nobody how to draw the same picture again — which is the
        # only reason to report one at all.
        #
        # Images per run (nr/von on the wish, one request per picture): a
        # fixed seed walks by the picture's own position — picture 3 of a
        # run is seed+2 — so each is reproducible on its own and the set as
        # a whole is not four copies of the same image. A random seed
        # (-1) is simply rolled again for each request, same as any other
        # single draw; the window never has to compute or send it.
        seed=(
            int(wunsch.seed) + (max(1, int(wunsch.nr)) - 1) if wunsch.seed >= 0
            else secrets.randbelow(2**31)
        ),
        # An unknown name is not an error to report but a value to bring
        # into range: the program would answer a usage message, which
        # reaches the user as "could not be drawn" and explains nothing.
        sampler=bildwahlen.sampler_pruefen(wunsch.sampler),
        scheduler=bildwahlen.scheduler_pruefen(wunsch.scheduler),
        loras=_loras(config, wunsch.loras, sprache),
        lora_apply_mode=bildwahlen.lora_apply_mode_pruefen(wunsch.lora_apply_mode),
        lora_ordner=_bildordner(config) / bildwahlen.LORA_ORDNER,
        embd_ordner=_embd_ordner(config),
        startbild=startbild,
        maske=painter_mask,
        # Without a starting image the strength has nothing to act on.
        staerke=max(0.0, min(1.0, float(wunsch.staerke))) if startbild else 1.0,
        # The quality companions, each resolved against its own folder.
        clip_skip=_clip_skip(family_name, wunsch.clip_skip),
        vae=vae,
        vae_is_tae=bildbausatz.is_tae_choice(wunsch.vae),
        ad_modell=_begleiter(yolo_pfad, config, wunsch.ad_modell, sprache),
        ad_prompt=wunsch.ad_prompt,
        ad_loras=_loras(config, wunsch.ad_loras, sprache),
        ad_negativ=wunsch.ad_negativ,
        ad_confidence=wunsch.ad_confidence,
        # Decided above, together with the trigger word — see there.
        photomaker=pm_modell if pm_klasse else None,
        gesichter_ordner=pm_gesichter if pm_klasse else None,
        pm_klasse=pm_klasse,
        pulid_weights=pulid_gewichte,
        pulid_id_embedding=pulid_einbettung,
        pulid_id_weight=float(wunsch.pulid_id_weight),
        control_net=control_net_modell,
        control_image=control_bild,
        control_strength=float(wunsch.control_strength),
        canny=bool(wunsch.canny) and control_net_modell is not None,
        hires=bool(wunsch.hires),
        hires_scale=float(wunsch.hires_scale),
        hires_steps=int(wunsch.hires_steps),
        hires_denoise=max(0.0, min(1.0, float(wunsch.hires_denoise))),
        hires_upscaler=hires_upscaler,
        hires_upscalers_ordner=upscaler_ordner,
        hires_width=_zielkante(wunsch.hires_width),
        hires_height=_zielkante(wunsch.hires_height),
        # Sampler fine-tuning: unset (None/empty) stays unset — see the
        # field comments on BildWunsch/Auftrag for why there is no default
        # this program could repeat without changing some picture.
        eta=wunsch.eta,
        flow_shift=wunsch.flow_shift,
        sigmas=wunsch.sigmas.strip(),
        extra_sample_args=wunsch.extra_sample_args.strip(),
        prediction=bildwahlen.prediction_pruefen(wunsch.prediction),
        slg_scale=max(0.0, float(wunsch.slg_scale)),
        skip_layer_start=wunsch.skip_layer_start,
        skip_layer_end=wunsch.skip_layer_end,
        skip_layers=wunsch.skip_layers.strip(),
        live_preview=bildwahlen.live_preview_pruefen(wunsch.live_preview),
        preview_interval=(
            int(wunsch.preview_interval) if wunsch.live_preview else None
        ) if wunsch.preview_interval is not None else None,
        preview_noisy=bool(wunsch.preview_noisy) and bool(wunsch.live_preview),
        taesd=(
            _begleiter(taesd_path, config, wunsch.taesd, sprache)
            if wunsch.live_preview == "tae" else None
        ),
        # A Bausatz's files, resolved above, alongside the CFG lock.
        familie=bildbausatz.FREE if free else family_name,
        diffusion_model=bausatz_diffusion_model,
        t5xxl=bausatz_t5xxl, clip_l=bausatz_clip_l, clip_g=bausatz_clip_g,
        llm=bausatz_llm, vae_format=bausatz_vae_format, guidance=bausatz_guidance,
        llm_vision=bausatz_llm_vision, tokenizer=bausatz_tokenizer,
        uncond_diffusion_model=bausatz_uncond,
        high_noise_diffusion_model=bausatz_high_noise,
        audio_vae=bausatz_audio_vae, audio_encoder=bausatz_audio_encoder,
        embeddings_connectors=bausatz_connectors, clip_vision=bausatz_clip_vision,
        video=video,
        video_frames=wunsch.video_frames if video else None,
        fps=None if family_entry is not None and family_entry.fixed_fps
        else wunsch.fps if video else None,
        end_image=end_bild,
        control_frames=steuerbilder,
        ref_video_frames=ref_video_frames,
        model_args=wunsch.model_args.strip(),
        ref_bilder=ref_bilder,
        img_cfg=(
            float(wunsch.img_cfg)
            if ref_bilder and wunsch.img_cfg is not None else None
        ),
        ref_image_args=wunsch.ref_image_args.strip() if ref_bilder else "",
        increase_ref_index=bool(wunsch.increase_ref_index) and bool(ref_bilder),
        # The picture's start flags, then the machine's memory and devices.
        rng=bildwahlen.rng_pruefen(wunsch.rng),
        weight_type=bildwahlen.weight_type_pruefen(wunsch.weight_type),
        threads=geraete.threads,
        vram_limit=geraete.vram_limit,
        offload_to_cpu=geraete.offload_to_cpu,
        split_mode=geraete.split_mode,
        backend=geraete.backend,
        # The machine's time limit; a video has none (it ends on a stop).
        zeitgrenze=None if video else geraete.zeitgrenze,
        switches=switches,
        switch_paths=switch_paths,
        mode=wunsch.mode,
        upscale_model=(
            _begleiter(upscaler_path, config, wunsch.upscale_model, sprache)
            if wunsch.mode == "upscale" else None
        ),
        upscale_repeats=wunsch.upscale_repeats,
        upscale_tile_size=wunsch.upscale_tile_size,
        imatrix=_imatrix(geraete, bausatz_diffusion_model or pfad),
    )
    # A video wish on a model that draws none: a picture family without a
    # video task, or a checkpoint without the motion module that makes it
    # one (sd.cpp docs/animatediff.md) — refused here in words, not left to
    # sd.cpp's "does not support vid_gen".
    if auftrag.video and family_entry is not None and not family_entry.video and (
        not {"t2v", "i2v"} & set(family_entry.tasks) or "motion_module" not in auftrag.switches
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, t("bild.video_unmoeglich", sprache))
    # Repairing or enlarging works on a finished still picture, never on a
    # video being drawn.
    if wunsch.mode and auftrag.video:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, t("bild.modus_unvollstaendig", sprache))
    if wunsch.mode and startbild is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, t("bild.modus_unvollstaendig", sprache))
    if wunsch.mode == "adetailer" and auftrag.ad_modell is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, t("bild.modus_unvollstaendig", sprache))
    if wunsch.mode == "upscale" and auftrag.upscale_model is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, t("bild.modus_unvollstaendig", sprache))
    # Which painter draws this picture. The picture server takes it whenever
    # it runs, unless the picture needs something only sd-cli can do
    # (``_cli_only_reason``). The same condition befehl() uses to decide whether the
    # sd-cli command gets --lora-apply-mode at all — a LoRA in the stack, or
    # a face — is passed to the server so its own copy of the flag only
    # claims a choice this wish actually made.
    turbo = request.app.state.bildturbo
    lora_aktiv = bool(auftrag.loras) or bool(auftrag.ad_loras) or (
        auftrag.photomaker is not None and auftrag.gesichter_ordner is not None
    )
    # Upscaling alone takes its own way: the server's upscale route while
    # the server runs with the upscaler's folder, sd-cli otherwise — and
    # then the running server steps aside, as for any sd-cli picture beside
    # it, since sd-cli loads the upscaler onto the same card. No drawing
    # model is loaded for it, so no model memory is asked for.
    upscale_on_server = (
        auftrag.mode == "upscale" and auftrag.upscale_model is not None
        and turbo.upscaler_folder == str(auftrag.upscale_model.parent)
        and _upscale_fits_the_server(auftrag)
    )
    ueber_turbo = auftrag.mode != "upscale" and _draws_on_server(turbo, auftrag, lora_aktiv)
    fingerprint = (
        photomaker.fingerabdruck(auftrag.gesichter_ordner)
        if ueber_turbo and auftrag.gesichter_ordner else None
    )
    # Asked before the run appears anywhere, so a refusal leaves no trace.
    make_room = (turbo.laeuft() and not upscale_on_server) if auftrag.mode == "upscale" else _speicher_pruefen(
        request, auftrag, sprache, on_server=ueber_turbo,
        # A server that matches but has not drawn yet holds only its graph —
        # the weights come with the first picture — so it counts as loaded
        # only once it has drawn.
        loaded=ueber_turbo and turbo.weights_loaded and _start_values_match(
            turbo, wunsch, auftrag, lora_aktiv, fingerprint
        ),
    )

    name = uuid.uuid4().hex + image_switches.output_suffix(auftrag.switches, auftrag.video)
    ziel = _bilderziel(config) / name

    # The run appears in the little history of the chat — or of the studio —
    # the moment it starts, so a picture that takes half a minute is visible
    # as work rather than as nothing happening.
    lauf = bildlauf.beginnen(
        wunsch.lauf_chat or wunsch.chat_id or (bildlauf.STUDIO if wunsch.studio else None),
        wunsch.prompt, wunsch,
    )

    # The generator runs for half a minute either way; run in a thread so
    # the service keeps answering while it draws.
    try:
        if upscale_on_server:
            await asyncio.to_thread(_upscale_on_server, runner, turbo, auftrag, ziel)
        elif ueber_turbo:
            await asyncio.to_thread(
                _draw_on_server, runner, turbo, wunsch, auftrag, pfad, ziel,
                lora_aktiv, fingerprint,
            )
        elif make_room:
            pause_control: str | None = None
            if auftrag.mode == "upscale":
                # The server could draw it but the result is beyond what
                # it returns: the rows that make it so are named.
                too_large = (
                    auftrag.upscale_model is not None
                    and turbo.upscaler_folder == str(auftrag.upscale_model.parent)
                )
                pause_control = "bild.upscale_repeats" if too_large else "bild.nur_hochskalieren"
            elif (reason := _cli_only_reason(auftrag, lora_aktiv)) is not None:
                pause_control = reason.control
            await asyncio.to_thread(
                _draw_with_server_paused, runner, turbo, auftrag, ziel, pause_control
            )
        else:
            await asyncio.to_thread(runner.erzeugen, auftrag, ziel)
    except BildturboFehler as fehler:
        if fehler.grund == "bild.abgebrochen":
            # A stop pressed during a turbo draw ends the server, which breaks
            # off the draw. Asked for, not gone wrong — the same silent 499 the
            # sd-cli path returns, so the window says nothing and the working
            # message just disappears.
            bildlauf.beenden(lauf, abgebrochen=True)
            code = (status.HTTP_499_CLIENT_CLOSED_REQUEST
                    if hasattr(status, "HTTP_499_CLIENT_CLOSED_REQUEST") else 499)
            raise HTTPException(code, t(fehler.grund, sprache)) from fehler
        satz = t(fehler.grund, sprache)
        if fehler.protokoll:
            # The picture SERVER's real last words, verbatim below the
            # sentence — the same treatment the sd-cli path's stderr gets a
            # few lines down, and for the same reason: the fast path's 400
            # ("invalid lora path: x.safetensors") is the whole explanation,
            # and swallowing it leaves a bare "could not be drawn".
            satz = f"{satz}\n\n{fehler.protokoll}"
        # The run keeps the same words as its output: the window's message
        # is gone after a moment, the red run in the terminal stays.
        bildlauf.beenden(lauf, gescheitert=True, reason=satz)
        # Whoever reads this sentence is the one who asked for it, and this
        # route writes it in the language of the request (``hole_sprache``):
        # the window asks in its own, the drawing tool asks in English,
        # because a model is its reader (app/tools/bild_werkzeug.py).
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, satz) from fehler
    except BildFehler as fehler:
        schluessel = fehler.grund
        code = {
            "bild.laeuft_schon": status.HTTP_409_CONFLICT,
            # Asked for, not gone wrong — the window says nothing and the
            # working message simply disappears.
            "bild.abgebrochen": status.HTTP_499_CLIENT_CLOSED_REQUEST
            if hasattr(status, "HTTP_499_CLIENT_CLOSED_REQUEST")
            else 499,
        }.get(schluessel, status.HTTP_503_SERVICE_UNAVAILABLE)
        satz = t(schluessel, sprache)
        if getattr(fehler, "protokoll", None):
            # The painter's REAL last words, verbatim below the sentence —
            # no rewritten error catalogue, the raw log is the truth.
            satz = f"{satz}\n\n{fehler.protokoll}"
        # A failed run keeps these words as its output, as above; a stopped
        # one is closed without any.
        bildlauf.beenden(
            lauf,
            gescheitert=schluessel != "bild.abgebrochen",
            abgebrochen=schluessel == "bild.abgebrochen",
            reason=satz,
        )
        # See the raise above: the sentence stands in the language of the
        # request, and the drawing tool is the one asking in English.
        raise HTTPException(code, satz) from fehler
    except BaseException:
        bildlauf.beenden(lauf, gescheitert=True)
        raise
    bildlauf.beenden(lauf)

    # Drawn from a piece of a larger picture, the result is that picture
    # with the piece in its place. A video has no place in a picture, and
    # where the piece's place does not fit, the painter's file stays.
    if crop_whole is not None and wunsch.crop_box is not None and not auftrag.video:
        await asyncio.to_thread(paste_back.into_whole, ziel, crop_whole, wunsch.crop_box, maske)

    # The generator writes the prompt, seed and every setting into the file.
    # Whether they stay is the one switch's to say (app/bildschutz.py): with
    # it on they are stripped here, once the finished picture lies on disk,
    # so both painters pass the same gate and nothing but the pixels is
    # stored or handed on. A video's container carries no such settings
    # (sd.cpp writes them into PNG and JPEG only), so there is nothing to
    # strip from it.
    if not auftrag.video and putzen_an(request.app.state.repositories):
        ziel.write_bytes(metadaten_entfernen(ziel.read_bytes()))

    # Images per run: the window calls this SAME route once per picture —
    # nr/von/lauf_kennung describe where this one sits in that run, sent by
    # the caller rather than counted here, so the route stays exactly what
    # it was before this feature: one request, one picture. A single
    # picture (von=1, the default) gets no "lauf" key in stats at all —
    # byte-identical to before this field existed — unless its run is an
    # answer's, which grows picture by picture (see `_ins_gespraech`).
    # Every picture of a run lands in the chat now — there is no cutoff
    # after which a picture still draws and saves but gets no message of
    # its own.
    # Enlarging alone draws nothing: no seed is used, so none is reported —
    # not in the answer, not at the chat's row, not among the values kept
    # for the picture. Repairing faces alone does draw, and keeps its seed.
    seed = None if auftrag.mode == "upscale" else auftrag.seed
    kept = _drawn_with(
        wunsch, auftrag, seed,
        original=(
            _kept_values(request.app.state.repositories, wunsch.startbild)
            if auftrag.mode == "upscale" and wunsch.startbild else None
        ),
        upscaled=(
            await asyncio.to_thread(upscaled_info.of, startbild, ziel)
            if auftrag.mode == "upscale" else None
        ),
    )
    try:
        frage_id, antwort_id = _ins_gespraech(
            request, wunsch, name, sprache, seed,
            drawn_with=kept,
            frage_erstellen=wunsch.frage_erstellen,
            lauf_kennung=wunsch.lauf_kennung,
            nr=wunsch.nr, von=wunsch.von,
        )
    except HTTPException as gone:
        if gone.status_code != status.HTTP_404_NOT_FOUND:
            raise
        # The chat was deleted while its picture was being drawn. A deleted
        # chat's pictures go with it, and so does this one: left lying, it
        # would be a file no row names. The run ends the way a stopped one
        # does — nobody is left to be told that a chat is missing.
        ziel.unlink(missing_ok=True)
        log.info("Picture %s is removed: its chat was deleted while it was drawn", name)
        code = (status.HTTP_499_CLIENT_CLOSED_REQUEST
                if hasattr(status, "HTTP_499_CLIENT_CLOSED_REQUEST") else 499)
        raise HTTPException(code, t("bild.abgebrochen", sprache)) from gone
    if wunsch.studio:
        studio_pictures.add(request.app.state.repositories, name)
        studio_pictures.keep_drawn_with(request.app.state.repositories, name, kept)
    return BildAntwort(
        bild=name, seed=seed, frage_id=frage_id, antwort_id=antwort_id,
    )


def _turbo_loras(auftrag: Auftrag) -> list[dict]:
    """This picture's LoRA stack, in the field the picture SERVER reads.

    Not in the prompt. The server parses no ``<lora:name:strength>`` tag out
    of a prompt at all (measured on builds 820 and 920: a made-up name drew
    no reaction, a real one no LoRA line in the log — the tag reached the
    text encoder as plain WORDS), and its own route leaves tag parsing off
    on purpose. It reads a ``lora`` array; with it the same file reports
    "834 / 834 LoRA tensors have been applied", measured on build 920 over
    ``img_gen`` on a server that was never asked for its LoRA list — the
    route refreshes that list itself for every job.

    ``path`` is the file NAME with its extension — the same string
    ``LoRA.name`` already holds — looked up in the LoRA folder the server
    was started with. ``multiplier`` is the strength, the ``:0.7`` of the
    sd-cli tag.

    The detailer's own stack is merged in here for exactly the reason
    ``bildrunner.prompt_bauen`` merges it into the main prompt: the detail
    pass reuses the main pass's LoRA settings, so this is the only place a
    face LoRA can be named. Deduplicated by stem, the same rule and the same
    order as that function, so both painters carry the same stack.
    """
    stapel: list[dict] = []
    schon_da: set[str] = set()
    for lora in auftrag.loras:
        schon_da.add(Path(lora.name).stem)
        stapel.append({"path": lora.name, "multiplier": lora.staerke})
    for lora in auftrag.ad_loras:
        stamm = Path(lora.name).stem
        if stamm not in schon_da:
            schon_da.add(stamm)
            stapel.append({"path": lora.name, "multiplier": lora.staerke})
    return stapel


def _number_list(text: str, kind: type) -> list | None:
    """A list the way sd-cli takes it on its command line — "14.6,7.8,0" or
    "[7,8,9]" — as numbers for the server's JSON, or None when it is not
    one. Brackets, commas and spaces separate, as they do for sd-cli."""
    try:
        return [kind(part) for part in re.split(r"[\[\],\s]+", text) if part]
    except ValueError:
        return None


class _CliReason(str):
    """Why a picture goes to sd-cli: the sentence the log carries, and in
    ``control`` the catalogue key of the label of the control whose value
    sends it there — the window names that control, so no list of reasons
    lives anywhere else."""

    control: str

    def __new__(cls, text: str, control: str) -> _CliReason:
        reason = super().__new__(cls, text)
        reason.control = control
        return reason


class _CliValues(Protocol):
    """What ``_cli_only_reason`` reads of a picture: the resolved job, or
    the values the window holds before there is one."""

    @property
    def live_preview(self) -> str: ...
    @property
    def preview_interval(self) -> int | None: ...
    @property
    def preview_noisy(self) -> bool: ...
    @property
    def preview_tae_only(self) -> bool: ...
    @property
    def video(self) -> bool: ...
    @property
    def pulid_weights(self) -> object | None: ...
    @property
    def pulid_id_embedding(self) -> object | None: ...
    @property
    def sigmas(self) -> str: ...
    @property
    def slg_scale(self) -> float: ...
    @property
    def skip_layers(self) -> str: ...
    @property
    def switches(self) -> dict: ...
    @property
    def ref_video_frames(self) -> tuple: ...
    @property
    def mode(self) -> str: ...
    @property
    def lora_apply_mode(self) -> str: ...


def _cli_only_reason(auftrag: _CliValues, lora_aktiv: bool) -> _CliReason | None:
    """What in this picture only sd-cli can draw, or None.

    The server's own interface carries every per-picture value this window
    sends except a few. Its live preview has the kind and the rhythm of a
    picture, but not the noisy variant, not a rhythm below 1 (sd-cli reads
    it as "after step N", the server as 1), not a tiny autoencoder for the
    preview alone (only sd-cli adds one beside the VAE) and not a video (the
    preview fields belong to the picture route). PuLID has no field in its
    body (its weights are a start value of sd-cli's alone), and neither has
    a reference video, whose frames this program hands over as a folder
    (``--ref-video``). A list sd-cli would
    read but that is no list of numbers goes to sd-cli too, so its own
    usage message explains it instead of a value dropped here.

    An apply mode other than at_runtime, with a LoRA or a face in play,
    does not fail the picture — it aborts the generator (ggml_abort after
    applying 0 of N tensors, measured on build 820 with LCM-SD15, LCM-SDXL
    and Hyper-SD15, and on build 920 with Hyper-SD15). On sd-cli that ends
    one short-lived process; on the server it ends the SERVER. The chosen
    mode still travels, unchanged, to the painter that draws it."""
    if auftrag.live_preview:
        if auftrag.video:
            return _CliReason("a live preview of a video", "bild.live_preview")
        if auftrag.preview_noisy:
            return _CliReason("noisy live preview", "bild.preview_noisy")
        if auftrag.preview_interval is not None and auftrag.preview_interval < 1:
            return _CliReason("live preview rhythm below 1", "bild.preview_interval")
        if auftrag.preview_tae_only:
            return _CliReason("a tiny autoencoder for the preview alone", "bild.taesd")
    if auftrag.pulid_weights is not None and auftrag.pulid_id_embedding is not None:
        return _CliReason("PuLID", "bild.pulid")
    if auftrag.sigmas and _number_list(auftrag.sigmas, float) is None:
        return _CliReason("sigmas not provided as a list of numbers", "bild.sigmas")
    if auftrag.slg_scale > 0 and auftrag.skip_layers and _number_list(auftrag.skip_layers, int) is None:
        return _CliReason("skip layers not provided as a list of numbers", "bild.skip_layers")
    switch = image_switches.cli_only(auftrag.switches)
    if switch:
        return _CliReason(switch.text, f"bild.sw_{switch.key}")
    if auftrag.ref_video_frames:
        return _CliReason("a reference video", "bild.referenzvideo")
    if auftrag.mode == "adetailer":
        return _CliReason("ADetailer applied to a finished image", "bild.nur_adetailer")
    if lora_aktiv and auftrag.lora_apply_mode != "at_runtime":
        return _CliReason(
            f"LoRA apply mode {auftrag.lora_apply_mode} would cause the server to abort",
            "bild.lora_modus",
        )
    return None


def _draws_on_server(turbo: Bildturbo, auftrag: Auftrag, lora_aktiv: bool) -> bool:
    """Does the running picture server draw this picture? Nothing is
    greyed out and nothing is said: a picture the server cannot draw goes
    to sd-cli, and only the log names the reason. A server its idle time
    ended counts as the server: the picture starts it again."""
    if not turbo.laeuft() and not turbo.im_leerlauf_beendet():
        return False
    reason = _cli_only_reason(auftrag, lora_aktiv)
    if reason:
        log.info("Picture over sd-cli while the image server runs: %s", reason)
        return False
    return True


def _start_values_match(
    turbo: Bildturbo, wunsch: BildWunsch, auftrag: Auftrag, lora_aktiv: bool,
    fingerprint: str | None,
) -> bool:
    """Does the running server already carry this picture's start values?

    ``fingerprint`` is the face photos' fingerprint, read once per
    request — the folder's own name never changes, only its photos do, and
    that is what has to trigger a restart."""
    return turbo.passt_zu(
        wunsch.modell, wunsch.vae or None,
        wunsch.ad_modell or None, auftrag.ad_prompt,
        ad_negativ=auftrag.ad_negativ,
        ad_confidence=auftrag.ad_confidence,
        prediction=auftrag.prediction,
        control_net=auftrag.control_net.name if auftrag.control_net else None,
        upscaler_ordner=auftrag.hires_upscalers_ordner,
        photomaker=auftrag.photomaker.name if auftrag.photomaker else None,
        gesichter_fingerabdruck=fingerprint,
        lora_ordner=auftrag.lora_ordner,
        lora_apply_mode=auftrag.lora_apply_mode,
        lora_aktiv=lora_aktiv,
        embd_ordner=auftrag.embd_ordner,
        diffusion_model=wunsch.diffusion_model or None,
        t5xxl=wunsch.t5xxl or None,
        clip_l=wunsch.clip_l or None,
        clip_g=wunsch.clip_g or None,
        llm=wunsch.llm or None,
        vae_format=auftrag.vae_format,
        llm_vision=wunsch.llm_vision or None,
        tokenizer=wunsch.tokenizer or None,
        uncond_diffusion_model=wunsch.uncond_diffusion_model or None,
        # The comparison keeps file names, so the paths the kit hands out
        # travel as the plain names the fingerprint is built from.
        video_parts={k: str(v) for k, v in video_parts(auftrag).items()},
        model_args=auftrag.model_args,
        rng=auftrag.rng,
        weight_type=auftrag.weight_type,
        threads=auftrag.threads,
        vram_limit=auftrag.vram_limit,
        offload_to_cpu=auftrag.offload_to_cpu,
        split_mode=auftrag.split_mode,
        backend=auftrag.backend,
        extra_start=_server_start_switches(auftrag),
        ad_extra=image_switches.key_value_list(auftrag.switches, "--extra-ad-args"),
    )


def _server_start_switches(auftrag: Auftrag) -> tuple[str, ...]:
    """The further switches the picture server takes only at start."""
    return image_switches.server_start_parts(auftrag.switches, auftrag.switch_paths)


def _turbo_auftrag(auftrag: Auftrag) -> dict:
    """The body of the picture server's own route ``/sdcpp/v1/img_gen``.

    Every per-picture value sd-cli is given on its command line has its
    field here, so nothing the window sends is dropped on this path. What
    binds the server at start — model, VAE, encoders, detector, PhotoMaker,
    ControlNet model, memory — is not in it (``Bildturbo.starten``).

    The LoRA stack travels in the ``lora`` field, never as a tag in the
    prompt: the server parses no ``<lora:…>`` tag (see ``_turbo_loras``).
    The mask keeps the polarity sd-cli reads — white means "draw this
    again" — because this route hands it on unchanged, as sd-cli does. The
    generator writes its settings into the file here as it does on sd-cli;
    the same strip afterwards removes them where asked.
    """
    guide: dict = {"txt_cfg": auftrag.cfg}
    # The distilled guidance belongs to the model, as on sd-cli: sent
    # whenever it is set, left to the server's default otherwise.
    if auftrag.guidance is not None:
        guide["distilled_guidance"] = auftrag.guidance
    if auftrag.slg_scale > 0:
        slg: dict = {
            "scale": auftrag.slg_scale,
            "layer_start": auftrag.skip_layer_start,
            "layer_end": auftrag.skip_layer_end,
        }
        if auftrag.skip_layers:
            slg["layers"] = _number_list(auftrag.skip_layers, int)
        guide["slg"] = slg
    sampler: dict = {
        "sample_steps": auftrag.schritte,
        "guidance": guide,
    }
    # Unset leaves the server to pick the model's own, as sd-cli does.
    if auftrag.sampler:
        sampler["sample_method"] = auftrag.sampler
    if auftrag.scheduler:
        sampler["scheduler"] = auftrag.scheduler
    # Unset stays unset, as on sd-cli: the per-sampler defaults are values
    # this program could not repeat without changing some picture.
    if auftrag.eta is not None:
        sampler["eta"] = auftrag.eta
    if auftrag.flow_shift is not None:
        sampler["flow_shift"] = auftrag.flow_shift
    if auftrag.sigmas:
        sampler["custom_sigmas"] = _number_list(auftrag.sigmas, float)
    sample_args = image_switches.key_value_list(
        auftrag.switches, "--extra-sample-args", auftrag.extra_sample_args
    )
    if sample_args:
        sampler["extra_sample_args"] = sample_args
    body: dict = {
        "prompt": auftrag.prompt,
        "width": auftrag.breite,
        "height": auftrag.hoehe,
        "seed": auftrag.seed,
        "sample_params": sampler,
        "vae_tiling_params": {"enabled": False},
        "embed_image_metadata": True,
        "output_format": "png",
    }
    if auftrag.negativ:
        body["negative_prompt"] = auftrag.negativ
    # The live preview: its kind and, when one was chosen, its rhythm. Left
    # out, the server draws none (and reads the rhythm as 1 when it is not
    # named, which is the rhythm sd-cli takes too).
    if auftrag.live_preview:
        body["preview"] = auftrag.live_preview
        if auftrag.preview_interval is not None:
            body["preview_interval"] = auftrag.preview_interval
    if auftrag.clip_skip >= 1:
        body["clip_skip"] = auftrag.clip_skip
    stapel = _turbo_loras(auftrag)
    if stapel:
        body["lora"] = stapel
    if auftrag.startbild is not None:
        body["init_image"] = _alsb64(auftrag.startbild)
        body["strength"] = auftrag.staerke
        # Only ever alongside a starting image — the caller already dropped a
        # mask that arrived without one.
        if auftrag.maske is not None:
            body["mask_image"] = _alsb64(auftrag.maske)
    if auftrag.ref_bilder:
        # The same order sd-cli's -r list keeps.
        body["ref_images"] = [_alsb64(bild) for bild in auftrag.ref_bilder]
        if auftrag.img_cfg is not None:
            guide["img_cfg"] = auftrag.img_cfg
        if auftrag.ref_image_args:
            body["ref_image_args"] = auftrag.ref_image_args
        if auftrag.increase_ref_index:
            body["increase_ref_index"] = True
    if auftrag.control_net is not None and auftrag.control_image is not None:
        body["control_image"] = _alsb64(auftrag.control_image)
        body["control_strength"] = auftrag.control_strength
        if auftrag.canny:
            body["image_preprocess"] = "target=control,canny=true"
    if auftrag.hires:
        hires: dict = {"enabled": True, "scale": auftrag.hires_scale}
        if auftrag.hires_steps > 0:
            hires["steps"] = auftrag.hires_steps
        if auftrag.hires_denoise > 0:
            hires["denoising_strength"] = auftrag.hires_denoise
        if auftrag.hires_upscaler:
            hires["upscaler"] = auftrag.hires_upscaler
        # Either one beats the scale (sd-cli's own rule); 0 means "not set".
        if auftrag.hires_width > 0:
            hires["target_width"] = auftrag.hires_width
        if auftrag.hires_height > 0:
            hires["target_height"] = auftrag.hires_height
        body["hires"] = hires
    # The further switches with a field of their own; the tiles, the cache,
    # the format and the IP-Adapter picture among them.
    image_switches.body_fields(
        body, auftrag.switches,
        lambda key: _alsb64(auftrag.switch_paths[key]),
    )
    return body


# The fields of the picture route's body that the video route does not take
# (sd.cpp examples/server/api.md, "vid_gen" request body).
_NOT_IN_VIDEO_BODY = (
    "ref_images", "mask_image", "control_image", "control_strength", "ip_adapter_image",
    "ip_adapter_strength", "embed_image_metadata", "ref_image_args", "increase_ref_index",
    "image_preprocess",
)


def _turbo_video_body(auftrag: Auftrag) -> dict:
    """The body of the server's ``/sdcpp/v1/vid_gen``: the picture's body
    without what a video does not take, with the frames, the last frame and
    the control video added."""
    body = _turbo_auftrag(auftrag)
    for field in _NOT_IN_VIDEO_BODY:
        body.pop(field, None)
    # The picture route's PNG default is no container; the video route's
    # own default is WebM, which the chosen video format replaces.
    if "video_format" not in auftrag.switches:
        body["output_format"] = image_switches.VIDEO_FORMATS[0]
    if auftrag.video_frames is not None:
        body["video_frames"] = auftrag.video_frames
    if auftrag.fps is not None:
        body["fps"] = auftrag.fps
    if auftrag.end_image is not None:
        body["end_image"] = _alsb64(auftrag.end_image)
    if auftrag.control_frames:
        body["control_frames"] = [_alsb64(frame) for frame in auftrag.control_frames]
    tiling_args = image_switches.key_value_list(auftrag.switches, image_switches.TILING)
    if tiling_args:
        body.setdefault("vae_tiling_params", {})["extra_tiling_args"] = tiling_args
    return body


def _erwartete_paesse(auftrag: Auftrag) -> int:
    """How many painting passes a TURBO run is sure to take: the base one,
    plus highres.

    The detailer's repaint is not planned, although a detector may be set:
    the picture server of the pinned build ignores the detector — two draws
    with the same seed, with and without ``--ad-model``, came back
    byte-identical. A pass that is planned and never painted leaves the bar
    standing at half when the picture is done. A server that does repaint
    stays inside the last pass's share, as every pass beyond the plan does.
    """
    return 1 + (1 if auftrag.hires else 0)


def _alsb64(pfad: Path) -> str:
    """A picture on disk as the base64 the server takes. The bytes go from
    the file into the request and nowhere else — nothing about the picture
    is read, logged or kept."""
    return base64.b64encode(pfad.read_bytes()).decode()


def _chat(request: Request, chat_id: str):
    """The chat a picture is drawn for, or None where there is none."""
    from app.api.abhaengigkeiten import STANDARD_BENUTZER

    benutzer = getattr(request.app.state, "standard_benutzer", STANDARD_BENUTZER)
    return request.app.state.repositories.chats.holen(chat_id, user_id=benutzer)


def _drawn_with(
    wunsch: BildWunsch, auftrag: Auftrag, seed: int | None, original: dict | None = None,
    upscaled: dict | None = None,
) -> dict:
    """What a picture is kept with: the prompt and its negative as they were
    asked for, the model, and the values the painter drew with — under the
    names the reading of a picture's file answers with (app/picture_info.py).
    What the run did not set is left out, as there.

    An enlarging draws nothing and reads no value of its request: the new
    picture is kept with what its original was kept with (``original``, as
    the program kept it for the original), and with the prompt the request
    carries where the original has none. An original with no kept values
    leaves the new picture with that prompt alone — never with the values
    the route would have drawn with. The enlarging itself is kept beside them
    (``upscaled``: the factor and the new size, app/upscaled_info.py), and what
    an earlier enlarging of the original said is not carried on."""
    if auftrag.mode == "upscale":
        kept = dict(original or {})
        kept.pop("upscaled", None)
        if not kept.get("prompt") and wunsch.prompt:
            kept["prompt"] = wunsch.prompt
        if upscaled:
            kept["upscaled"] = upscaled
        return kept
    values: dict = {
        "prompt": wunsch.prompt, "negativ": wunsch.negativ, "modell": wunsch.modell,
        "breite": auftrag.breite, "hoehe": auftrag.hoehe, "schritte": auftrag.schritte,
        "cfg": auftrag.cfg, "guidance": auftrag.guidance, "seed": seed,
        "sampler": auftrag.sampler, "scheduler": auftrag.scheduler,
    }
    return {name: value for name, value in values.items() if value not in ("", None)}


def _ins_gespraech(
    request: Request, wunsch: BildWunsch, name: str, sprache: str, seed: int | None,
    *, frage_erstellen: bool = True,
    lauf_kennung: str | None = None, nr: int = 1, von: int = 1,
    drawn_with: dict | None = None,
) -> tuple[str | None, str | None]:
    """A single picture's message pair — or, for a run of several
    (``lauf_kennung`` set), the run's own ONE question and ONE answer:
    every picture of the run is written into that same answer row
    (``lauf_bild_speichern``), never a row of its own. A single picture
    (the default, ``lauf_kennung=None``) is entirely unaffected by any of
    this: it gets its own row, and its stats carry its seed and what it was
    drawn with (``drawn_with``) and nothing of a run.

    ``frage_erstellen`` — either value — names a PLAN, not a fact: the
    window sets ``True`` only for the run's first request and ``False``
    for the rest, on the assumption they arrive in that order and nothing
    in between ever removes what one of them wrote. Neither half of that
    holds up: the first one's own draw can fail before this function is
    ever called for it (a stopped server, a bad model, anything upstream
    of this route), and a request can land, then be regenerated away, then
    a later one of the same run still believes the plan instead of
    checking. Trusting either value would carry that loss — or its
    opposite, a second question typed into the same run — forward.
    Checked here instead, on every request that names a run: a lauf's
    question is created the moment SOME request of it reaches this point
    with none written yet, whichever position that turns out to be, and
    left alone the moment one already exists, no matter what the request
    itself expected.

    A run named after an ANSWER of this chat is the pictures a model draws
    while it writes that answer (app/tools/bild_werkzeug.py). It is a run
    from its first picture on, whatever ``von`` says. Its question is the
    one the answer answers and already stands in the chat, so none is
    written here. And nobody knew beforehand how many pictures it would
    hold: each one takes the next place at the end and the run grows with
    it (``lauf_bild_speichern`` with ``nr=None``), so ``nr`` and ``von``
    of the request are not read for it."""
    if not wunsch.chat_id:
        return None, None
    repositories = request.app.state.repositories
    chat = _chat(request, wunsch.chat_id)
    if chat is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t("fehler.chat_nicht_gefunden", sprache)
        )
    of_answer = False
    if lauf_kennung is not None:
        answer_row = repositories.messages.holen(lauf_kennung)
        of_answer = (
            answer_row is not None
            and answer_row.chat_id == chat.id
            and answer_row.role == "assistant"
            and answer_row.art == "nachricht"
        )
        if of_answer:
            frage_erstellen = False
        elif von <= 1:
            # A single picture of the window stays the single picture it
            # always was, run key or not.
            lauf_kennung = None
        else:
            frage_erstellen = not repositories.messages.lauf_hat_nachricht(
                chat_id=chat.id, lauf_kennung=lauf_kennung
            )
    frage = None
    if frage_erstellen:
        frage = repositories.messages.speichern(
            chat_id=chat.id, role="user", content=wunsch.prompt,
            lauf_id=lauf_kennung,
        )
    if lauf_kennung is not None:
        antwort = repositories.messages.lauf_bild_speichern(
            chat_id=chat.id, lauf_kennung=lauf_kennung,
            nr=None if of_answer else nr, von=von,
            bild=name, seed=seed, drawn_with=drawn_with,
        )
        if antwort is not None:
            log.info(
                "Picture %s is in the chat now: run %s of chat %s holds %d",
                name, lauf_kennung, chat.id, len(antwort.bild_dateien()),
            )
    else:
        # The seed rides along in the message's stats, so a single saved
        # picture carries the number it was drawn with — shown under the
        # picture and copyable, exactly like the chat's own values.
        #
        # `art="bild"` is what keeps this row out of the running answer's
        # way. Empty content on an assistant row used to be the exact
        # profile a reader looked for when asking "which row is the answer
        # being written right now?", and the picture window is not blocked
        # while a chat answers — so this row could land behind a live
        # answer and be mistaken for it.
        stats: dict = {}
        if seed is not None:
            stats["seed"] = seed
        if drawn_with is not None:
            stats["drawn_with"] = drawn_with
        antwort = repositories.messages.speichern(
            chat_id=chat.id, role="assistant", content="", bild=name, stats=stats, art="bild",
        )
    repositories.chats.zeitstempel_auffrischen(chat.id)
    return (frage.id if frage is not None else None), antwort.id


def _loras(
    config: Config, eintraege: list[LoRAWunsch], sprache: str
) -> tuple[LoRA, ...]:
    """One stack, every name checked against the folder it must lie in.

    Takes the LIST, not the whole wish: there are two stacks now — the
    picture's own and the detailer's — and both are checked the same way.
    """
    gewaehlt = []
    for eintrag in eintraege:
        try:
            lora_pfad(_bildordner(config), eintrag.name)
        except BildFehler as fehler:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, t(fehler.grund, sprache)
            ) from fehler
        gewaehlt.append(LoRA(
            name=eintrag.name,
            staerke=max(bildwahlen.LORA_MIN, min(bildwahlen.LORA_MAX, eintrag.staerke)),
        ))
    return tuple(gewaehlt)


def _begleiter(aufloeser, config: Config, name: str | None, sprache: str) -> Path | None:
    """A VAE or detector NAME turned into a path, or None when unset — every
    name checked against the folder it must lie in, like a LoRA."""
    if not name:
        return None
    try:
        return aufloeser(_bildordner(config), name)
    except BildFehler as fehler:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t(fehler.grund, sprache)
        ) from fehler


def _imatrix(geraete: bildgeraete.Geraete, model: Path) -> Path | None:
    """Where this picture adds to an importance matrix: beside the model
    file it draws with, while the machine's switch for it is on."""
    return imatrix_path(model) if geraete.imatrix else None


def _clip_skip(family_name: str, value: int) -> int:
    """CLIP skip within the family's own CLIP layers. A family without a
    CLIP encoder has nothing to skip; a model whose family is not known
    gets the smallest count any family has, so no encoder is asked for
    more layers than it holds."""
    family = image_families.get(family_name)
    if family is None:
        layers = image_families.FALLBACK_CLIP_LAYERS
    elif family.clip_layers is None:
        return -1
    else:
        layers = family.clip_layers
    return max(-1, min(layers, int(value)))


def _switches(
    config: Config, values: dict, language: str, on: dict[str, bool],
) -> tuple[dict, dict[str, Path]]:
    """The request's further switches, checked against their table, only
    the ones that act, with each file and picture resolved: a file against
    its own folder, a picture like the starting image."""
    try:
        checked = image_switches.active(image_switches.check(values), on)
    except ValueError as error:
        # The sentence comes from the catalogue; the reason the check gives
        # rides along as its value, the way `{field}` does next door.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, t("bild.schalter_ungueltig", language, grund=error)
        ) from error
    paths: dict[str, Path] = {}
    for key, value in checked.items():
        # check() has refused every key without a row.
        switch = image_switches.BY_KEY[key]
        if switch.kind == "picture":
            picture = _startbild(config, value, language)
            if picture is not None:
                paths[key] = picture
        elif switch.kind == "file":
            try:
                paths[key] = image_switches.file_path(_bildordner(config), switch.folder, value)
            except ValueError as error:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND, t("bild.begleiter_unbekannt", language)
                ) from error
    return checked, paths


def _startbild(config: Config, name: str | None, sprache: str) -> Path | None:
    """A picture to start from — by the name this server gave it.

    The same rule as a model name: only a bare name, and only one that is
    really lying in the picture folder — or among the studio's working
    pictures, where the frames of a video and what the drawing surface put
    together lie. A path from a request never becomes a path on disk.
    """
    if not name:
        return None
    if "/" in name or "\\" in name or name != Path(name).name:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("bild.startbild_fehlt", sprache))
    for folder in (_bilderziel(config), scratch_pictures_dir(config)):
        pfad = folder / name
        if pfad.is_file():
            return pfad
    raise HTTPException(status.HTTP_404_NOT_FOUND, t("bild.startbild_fehlt", sprache))


def _crop_whole(config: Config, wunsch: BildWunsch) -> Path | None:
    """The picture this run's starting image was cut from, or None where the
    request does not name both it and the piece's place — or names a picture
    that is not there. No reason to refuse the draw: without it the result
    is the piece the painter drew."""
    if not wunsch.crop_of or wunsch.crop_box is None:
        return None
    try:
        return _startbild(config, wunsch.crop_of, "en")
    except HTTPException:
        return None


def _fitted(
    config: Config, wunsch: BildWunsch,
    single: tuple[Path | None, Path | None, Path | None],
    control_frames: tuple[Path, ...], references: tuple[Path, ...],
    video_frames: tuple[Path, ...], mask: Path | None,
) -> tuple[
    tuple[Path | None, Path | None, Path | None], tuple[Path, ...], tuple[Path, ...],
    tuple[Path, ...], Path | None,
]:
    """The input pictures of a drawing as the painter gets them — the
    starting, end and control picture, the control frames, the reference
    pictures, the frames of a reference video and the mask: each itself, or
    its smaller copy among the studio's working pictures when it is larger
    than the drawing needs it (app/draw_input.py). The mask follows its
    starting picture: it goes at exactly the size that picture goes at."""
    width, height = _kante(wunsch.breite), _kante(wunsch.hoehe)
    folder = scratch_pictures_dir(config)

    def fit(picture: Path) -> Path:
        return draw_input.fitted(picture, width, height, folder)

    def fit_frames(frames: tuple[Path, ...]) -> tuple[Path, ...]:
        # The frames of one video share one size: where the first goes
        # itself, the others are not measured one by one to learn the same.
        if not frames or fit(frames[0]) == frames[0]:
            return frames
        return tuple(fit(frame) for frame in frames)

    start, end, control = (None if picture is None else fit(picture) for picture in single)
    if mask is not None and start is not None:
        mask = draw_input.fitted_like(mask, start, folder)
    return (
        (start, end, control),
        fit_frames(control_frames),
        tuple(fit(picture) for picture in references),
        fit_frames(video_frames),
        mask,
    )


def _fitted_switch_pictures(
    config: Config, wunsch: BildWunsch, paths: dict[str, Path],
) -> dict[str, Path]:
    """The switches' resolved paths with every picture among them as the
    painter gets it — no larger than the drawing needs it, like the starting
    picture. A file a switch names is no picture and stays as it is."""
    width, height = _kante(wunsch.breite), _kante(wunsch.hoehe)
    folder = scratch_pictures_dir(config)
    return {
        key: draw_input.fitted(path, width, height, folder)
        if image_switches.BY_KEY[key].kind == "picture" else path
        for key, path in paths.items()
    }


def _draw_on_server(
    runner: Bildrunner, turbo: Bildturbo, wunsch: BildWunsch, auftrag: Auftrag,
    pfad: Path, ziel: Path, lora_aktiv: bool, fingerprint: str | None,
) -> None:
    """Draw one picture on the picture server — restart it first when the
    picture needs another model or other start values — under ONE hold of
    the one-picture lock and in ONE thread: a second request cannot restart
    the server under a running draw, a server picture and an sd-cli picture
    never run at once, and a request cancelled meanwhile cannot release the
    lock under a draw that is still running.

    A stop asked while the server still starts for this picture ends the
    picture and nothing else: it is not drawn, and the server goes on
    starting on the model it was just given."""
    runner.reservieren(stoppable=True)
    try:
        if not _start_values_match(turbo, wunsch, auftrag, lora_aktiv, fingerprint):
            # Another model or other start values: the server starts again
            # on them, without a word, the moment a request names another
            # checkpoint.
            log.info("Image server restarts on another model or other start values")
            turbo.starten(
                pfad,
                vae=auftrag.vae, vae_tae=auftrag.vae_is_tae, ad_modell=auftrag.ad_modell,
                ad_prompt=auftrag.ad_prompt,
                ad_negativ=auftrag.ad_negativ,
                ad_confidence=auftrag.ad_confidence,
                prediction=auftrag.prediction,
                control_net=auftrag.control_net,
                upscaler_ordner=auftrag.hires_upscalers_ordner,
                lora_ordner=auftrag.lora_ordner,
                lora_apply_mode=auftrag.lora_apply_mode,
                lora_aktiv=lora_aktiv,
                embd_ordner=auftrag.embd_ordner,
                photomaker=auftrag.photomaker,
                gesichter_ordner=auftrag.gesichter_ordner,
                familie=auftrag.familie,
                diffusion_model=auftrag.diffusion_model,
                t5xxl=auftrag.t5xxl, clip_l=auftrag.clip_l,
                clip_g=auftrag.clip_g, llm=auftrag.llm,
                vae_format=auftrag.vae_format,
                llm_vision=auftrag.llm_vision, tokenizer=auftrag.tokenizer,
                uncond_diffusion_model=auftrag.uncond_diffusion_model,
                video_parts=video_parts(auftrag),
                model_args=auftrag.model_args,
                rng=auftrag.rng,
                weight_type=auftrag.weight_type,
                threads=auftrag.threads,
                vram_limit=auftrag.vram_limit,
                offload_to_cpu=auftrag.offload_to_cpu,
                split_mode=auftrag.split_mode,
                backend=auftrag.backend,
                extra_start=_server_start_switches(auftrag),
                ad_extra=image_switches.key_value_list(auftrag.switches, "--extra-ad-args"),
            )
            # A load with files beside the model is much heavier than a
            # plain model's — the long deadline gives it room without
            # falsely reporting a still-loading server as failed.
            deadline = start_deadline(*start_parts(auftrag, video_parts(auftrag)))
            if not turbo.bereit_abwarten(deadline, stopped=runner.stop_asked):
                runner.end_if_stopped()
                raise BildturboFehler(turbo.ladefehler_grund())
        runner.end_if_stopped()
        daten = turbo.zeichnen(
            _turbo_video_body(auftrag) if auftrag.video else _turbo_auftrag(auftrag),
            paesse=_erwartete_paesse(auftrag), video=auftrag.video,
            stopped=runner.stop_asked, zeitgrenze=auftrag.zeitgrenze,
        )
        # The last look: a stop asked in the moment the draw took over was
        # heard by neither side, and its picture is not handed back.
        runner.end_if_stopped(last=True)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(daten)
    finally:
        runner.freigeben()


# The most the picture server's upscale route returns, in pixels on a side.
UPSCALE_SERVER_MAX_SIDE = 8192


def _upscale_fits_the_server(job: Auftrag) -> bool:
    """Is the enlarged picture no wider and no higher than the picture
    server returns? The size is the start picture's side times the model's
    factor to the power of the repeats; a size or a factor that is not known
    leaves the server to try, as before. A larger result goes to sd-cli,
    and the log names the reason like any picture that does."""
    if job.upscale_model is None or job.startbild is None:
        return True
    factor = upscaler_scale.scale(job.upscale_model)
    size = attachment_sizes.of_file(job.startbild)
    if factor is None or size is None:
        return True
    side = max(size["width"], size["height"]) * factor ** job.upscale_repeats
    if side <= UPSCALE_SERVER_MAX_SIDE:
        return True
    log.info(
        "Enlarging over sd-cli while the image server runs: %d pixels on a side "
        "are beyond the %d the server returns", side, UPSCALE_SERVER_MAX_SIDE,
    )
    return False


def _upscale_on_server(runner: Bildrunner, turbo: Bildturbo, job: Auftrag, target: Path) -> None:
    """Enlarge the start picture over the server's upscale route, under the
    one-picture lock like every other picture, in the format the target's
    name ends in."""
    if job.startbild is None or job.upscale_model is None:
        raise BildFehler("bild.modus_unvollstaendig")
    runner.reservieren()
    try:
        data = turbo.upscale(
            _alsb64(job.startbild), job.upscale_model.stem,
            {".jpg": "jpeg", ".webp": "webp"}.get(target.suffix, "png"),
            zeitgrenze=job.zeitgrenze,
            repeats=job.upscale_repeats if job.upscale_repeats != UPSCALE_REPEATS_START else None,
            tile_size=job.upscale_tile_size if job.upscale_tile_size != UPSCALE_TILE_START else None,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    finally:
        runner.freigeben()


def _draw_with_server_paused(
    runner: Bildrunner, turbo: Bildturbo, auftrag: Auftrag, ziel: Path,
    control: str | None = None,
) -> None:
    """Pause the picture server, draw with sd-cli, start the server again —
    under ONE hold of the one-picture lock and in ONE thread. Nothing can
    start the server again or draw on it while the sd-cli picture needs its
    memory, and a request that is cancelled meanwhile cannot release the
    lock or bring the server back under a draw that is still running.
    ``control`` names what needs sd-cli, for the window's footer while the
    server is down.

    A stop asked while the server steps aside ends the picture before
    sd-cli is started; the server comes back as after every such picture."""
    runner.reservieren(stoppable=True)
    try:
        started = time.monotonic()
        paused = turbo.pause(control)
        if paused:
            log.info(
                "Image server steps aside for an sd-cli picture (%.1f s to stop)",
                time.monotonic() - started,
            )
        try:
            runner.erzeugen(auftrag, ziel, reserved=True)
        finally:
            if paused:
                try:
                    restarted = time.monotonic()
                    if turbo.resume():
                        log.info(
                            "Image server started again on the same model (%.1f s)",
                            time.monotonic() - restarted,
                        )
                except Exception:  # noqa: BLE001 - the picture is drawn; a server that stays down is only slower
                    log.warning("Image server could not start again", exc_info=True)
    finally:
        runner.freigeben()


def _kit_files_gb(auftrag: Auftrag) -> float | None:
    """What every file this picture loads weighs together, or None when the
    model itself cannot be read — then there is nothing honest to add up.

    All of them, not the model alone: a Bausatz is a diffusion model plus
    its text encoders and VAE, and a Flux one weighs as much in its encoder
    as in its model."""
    main_file = auftrag.diffusion_model or auftrag.modell
    try:
        total = main_file.stat().st_size
    except OSError:
        return None
    files = [
        auftrag.t5xxl, auftrag.clip_l, auftrag.clip_g, auftrag.llm, auftrag.vae,
        auftrag.control_net, auftrag.photomaker, auftrag.ad_modell,
        auftrag.pulid_weights, auftrag.llm_vision, auftrag.uncond_diffusion_model,
        *video_parts(auftrag).values(),
    ]
    if auftrag.lora_ordner is not None:
        # The detailer's stack merges into the main one by file stem, as
        # the painters load it (``_turbo_loras``): one file counts once.
        stems = {Path(lora.name).stem: lora.name for lora in [*auftrag.ad_loras, *auftrag.loras]}
        files += [auftrag.lora_ordner / name for name in stems.values()]
    for path in files:
        if path is None:
            continue
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total / (1024**3)


def _speicher_pruefen(
    request: Request, auftrag: Auftrag, sprache: str, *, on_server: bool, loaded: bool
) -> bool:
    """An honest sentence instead of a machine brought to its knees.

    Returns True when the picture server has to step aside for this sd-cli
    picture. It does so for every sd-cli picture while it runs — the same
    model never lies in memory twice, whatever the figures say, and a model
    file that cannot be read changes nothing about that. The server then
    stops for the picture and starts again on the same model afterwards.
    What is asked is only whether the picture fits without the server; when
    it does not, the answer is the refusal below.

    ``loaded`` means the running server already holds every file of this
    picture — then nothing new is loaded and there is nothing to check.
    A picture that restarts the server frees what the server holds now."""
    if loaded:
        return False
    steps_aside = not on_server and request.app.state.bildturbo.laeuft()
    files_gb = _kit_files_gb(auftrag)
    if files_gb is None:
        return steps_aside
    # What the running servers are holding RIGHT NOW, not what their files
    # weigh — the picture server included. All of them, not just the chat
    # model — see `bildspeicher` for why asking one of several is worse
    # than not asking at all.
    belegt = bildspeicher.gehaltene_gb(request.app.state)
    server_gb = request.app.state.bildturbo.belegt_gb() or 0.0
    # Two readings of a growing server can differ a little; what is held
    # without it is never below nothing.
    gesamt = systemspeicher.gesamt_gb()
    without_server = max(0.0, belegt - server_gb)
    if bildspeicher.passt(gesamt, without_server, files_gb):
        return steps_aside
    raise HTTPException(
        status.HTTP_507_INSUFFICIENT_STORAGE,
        t("bild.kein_platz", sprache,
          gb=bildspeicher.fehlend_gb(gesamt, without_server, files_gb)),
    )
