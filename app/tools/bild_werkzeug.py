"""The drawing tool — `draw_image`.

The bridge the image-generator skill was missing: the skill told the model
to make a picture, but no tool existed that could — the model guessed at
shell commands and failed. This one talks to the picture pipeline of this
very service over its own HTTP API, so it walks exactly the road the
picture window walks: the same queue lock, the same memory check, the same
metadata scrub.

The model does not pick the model file or any other value. A picture is
drawn with the default model of the picture server
(``app/bildstandardmodell.py``) and its start values — the values the user
set for that model in the picture server laid over its family's start
values (``app/image_families.py``). The picture studio's own model and
values are not read here: the studio and the chats share nothing. What the
model brings is the one thing only it has: the prompt.

In a chat the picture goes into the chat the way the studio's pictures
never do: the request names the chat and the answer being written, and the
route writes every finished picture into that answer's own run itself —
the moment it is finished, one file and one row. The answer is named by
the caller, not by an argument: anything the model can pass, the model can
forge.

A job has no answer for a picture to stand under and names none: there the
picture stays in the pictures folder, and the model is told its path, so it
can hand the file on with the delivery tool where the run has one.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app import (
    bildinhalt, bildmodellwerte, bildrunner, bildstandardmodell, bildwahlen, image_families,
)
from app.i18n import t
from app.image_families import Family
from app.speicherorte import ort
from app.tools.mcp_client import MCPWerkzeug

log = logging.getLogger(__name__)

SERVER_NAME = "image"
WERKZEUG_NAME = "draw_image"

# How long a call to the picture route may take to connect, to send and to be
# answered — every call but the picture request itself. That request has no
# read bound of its own (``_bild_anfordern``): the route ends a picture at the
# time limit of the image-server page, and with none set a picture ends with
# the image or with the run's stop.
ZEITFENSTER_S = 900.0

# How often a stop is sent again while the picture route still has not
# answered. One send can arrive before the route has started the painter, and
# a stop that finds nothing running ends nothing; the next one finds it.
STOPP_TAKT_S = 1.0


# How the model learns where the finished picture is. In a chat it hangs on
# the answer; in a job it stays in the pictures folder — shown in the Images
# panel (app/api/v1/bilder.py lists that folder) — and the tool's answer
# names the file.
IN_CHAT = (
    "The finished image appears automatically in your response, and the result includes its "
    "filename and path. Do not describe its contents afterward; you have not seen it."
)
# What the model reads about the optional input picture, in every list.
INPUT_PICTURE = {
    "type": "string",
    "description": (
        "Optional: path to a readable image in a shared folder or the pictures folder. If "
        "provided, this image is used as the starting point instead of generating one from "
        "scratch."
    ),
}
# The kinds of picture the service takes in, by the file's ending.
_PICTURE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
}
IN_JOB = (
    "The finished image is saved in the pictures folder, visible to the user under Images. "
    "The response includes its filename. Do not describe its contents afterward; you have not "
    "seen it."
)

# What the model reads when the picture service answered without an error
# but with nothing this tool can use. Short and without field names: the
# model cannot repair the service, it can only tell the user that the
# picture did not come.
UNUSABLE_ANSWER = (
    "The image could not be generated: the image service returned an unusable response."
)
NO_PICTURE = "The image could not be generated: the image service returned no image."


@dataclass(frozen=True)
class Made:
    """What a tool that paints is on the way to, in the words its refusals
    open with. The calls before the painting are shared by every such tool
    (the default model, a picture handed in);
    each tells them what it makes, so the model reads of the thing it asked
    for."""

    # A call on the way failed.
    failed: str
    # The request itself was not usable.
    refused: str
    # The service answered with something that could not be read.
    unusable: str


PICTURE = Made("The image could not be generated", "The image was not generated", UNUSABLE_ANSWER)
# Nothing chooses the default model by itself, so without one the model
# learns where the user chooses it.
NO_DEFAULT_MODEL = (
    "The image was not generated: no default image model is selected. Ask the user to select "
    "a default model on the picture server page (Local, picture server, Default model), then "
    "try again."
)


class BildWerkzeugFehler(Exception):
    """The picture could not be made; the message says why."""


# What the text encoder of a family does with a long prompt, in the words a
# model needs to write a fitting one. CLIP reads fixed chunks, T5 reads
# sentences in bigger chunks, a language model reads prose — and a prompt
# written for one of them is written wrong for the others. The chunk sizes
# are sd.cpp's own (docs/tokenizers.md, CLIP 77 and T5 256 tokens).
_PROMPT_STIL = {
    "clip": (
        "Use concise, information-rich keyword phrases, placing the most important elements "
        "first. Weights such as (word:1.2) are supported. Long prompts are processed in "
        "chunks of 77 tokens, so earlier elements carry more weight."
    ),
    "t5": (
        "Write complete, fluent sentences. Long prompts are processed in chunks of 256 "
        "tokens, so the opening sentence carries the most weight."
    ),
    "llm": (
        "Write a complete description in plain prose. The image can also include a short "
        "passage of text."
    ),
}

# The optional values this tool may send: the field each one has in the
# draw request (app/api/v1/bild.py), what the model reads about it — what it
# is, what it defaults to, when to leave it out — and its word in the reply.
# ONE table: the schema, the request and the reply all read it, so a value
# cannot travel under two names.
_WERTEFELDER: tuple[tuple[str, str, str, str], ...] = (
    (
        "width", "breite",
        "Image width in pixels. Uses the image model's start value by default. Omit unless the "
        "user requests a specific width.",
        "size",
    ),
    (
        "height", "hoehe",
        "Image height in pixels. Uses the image model's start value by default. Omit unless the "
        "user requests a specific height.",
        "size",
    ),
    (
        "steps", "schritte",
        "Number of sampling steps. Uses the image model's start value by default. Omit unless "
        "the user requests a step count.",
        "steps",
    ),
    (
        "cfg", "cfg",
        "CFG scale. Uses the image model's start value by default. Omit unless the user "
        "requests a specific value.",
        "CFG",
    ),
    (
        "sampler", "sampler",
        "Sampler, e.g. euler_a. Uses the image model's start value by default. Omit unless the "
        "user requests a sampler.",
        "sampler",
    ),
    (
        "scheduler", "scheduler",
        "Scheduler, e.g. discrete. Uses the image model's start value by default. Omit unless "
        "the user requests a scheduler.",
        "scheduler",
    ),
    (
        "seed", "seed",
        "Seed. Random by default. Omit unless the user specifies a seed.",
        "seed",
    ),
    (
        "guidance", "guidance",
        "Distilled guidance (Flux only). Uses the image model's start value by default. Omit "
        "unless the user requests a specific value.",
        "guidance",
    ),
)

_WERTETYPEN = {
    "width": "integer", "height": "integer", "steps": "integer", "seed": "integer",
    "cfg": "number", "guidance": "number", "sampler": "string", "scheduler": "string",
}


def _prompt_stil(familie: Family) -> str:
    """Which way of writing the prompt this family's text encoder wants.

    Decided by what actually reads the prompt: a language model, T5, or CLIP.
    ``encoders`` names what a KIT reads and stays empty for a checkpoint —
    there the family's own CLIP (``clip_layers``) is the reader. A family
    with neither gets prose: the one answer that is never wrong about a text
    encoder nobody wrote down.
    """
    if "llm" in familie.encoders:
        return _PROMPT_STIL["llm"]
    if "t5xxl" in familie.encoders:
        return _PROMPT_STIL["t5"]
    if familie.encoders or familie.clip_layers is not None:
        return _PROMPT_STIL["clip"]
    return _PROMPT_STIL["llm"]


def _werte_schema(start, values: dict[str, Any] | None = None) -> dict[str, Any]:
    """The optional values. Each carries, as its ``default``, the value the
    next picture of this chat is drawn with — where the caller read one
    (``values``, by the fields' own names). A value that is not set (no
    sampler chosen) has no default, and neither has the seed: it is random
    unless the user names one.

    ``guidance`` appears only where the family has one: a field the model may
    fill and the family then ignores is a promise this tool cannot keep.
    """
    felder: dict[str, Any] = {}
    for name, _feld, text, _wort in _WERTEFELDER:
        if name == "guidance" and start.guidance is None:
            continue
        entry: dict[str, Any] = {"type": _WERTETYPEN[name], "description": text}
        if values and name != "seed" and values.get(name) not in (None, ""):
            entry["default"] = values[name]
        felder[name] = entry
    return felder


def werkzeug_beschreibung(
    familie: Family | None = None, *, in_chat: bool = True,
    values: dict[str, Any] | None = None,
) -> MCPWerkzeug:
    """The tool as the default image model makes it.

    ``familie`` is the default image model, ``values`` the values the next
    picture is drawn with, the CFG among them. Together they decide what
    the model has to know BEFORE writing: which text encoder reads the prompt and how, whether a negative prompt
    does anything at all, which values exist, and what each one is when the
    model sends none. The caller reads both with ``fensterbild`` — the same
    reading the drawing itself makes — so the description and the call
    cannot name two different models or two different values.

    ``None`` is the honest answer for a caller that knows no model: the
    sentence that fits every case, without a value the tool could not send.

    ``in_chat`` is False for a job's list: its picture stays in the pictures
    folder instead of appearing in an answer (``IN_JOB``).
    """
    where = IN_CHAT if in_chat else IN_JOB
    if familie is None:
        return MCPWerkzeug(
            name=WERKZEUG_NAME,
            beschreibung=(
                "Generates an image using the image model installed on this machine. Express "
                "the request in ONE precise visual sentence covering the subject, setting, "
                f"lighting, mood, and appearance. Avoid vague adjectives. {where}"
            ),
            schema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Describe what the image should show, in English.",
                    },
                    "negative_prompt": {
                        "type": "string",
                        "description": "Optional. Elements to exclude from the image.",
                    },
                    "image": INPUT_PICTURE,
                },
                "required": ["prompt"],
            },
            server=SERVER_NAME,
        )
    # No branch for a family that cannot draw from text (editing, video): a
    # run whose default model is one is not offered this tool at all
    # (app/tools/registry.py), so there is nothing here to describe — and a
    # description that has to say "this does nothing" is a promise the tool
    # cannot keep, sent in every request of that run.
    start = familie.start
    # What the picture will really run at: the CFG among the values in
    # force — the one set for the model itself, else the family's start —
    # and the family's start for a caller that read none.
    wirksame_cfg = (values or {}).get("cfg")
    if wirksame_cfg is None:
        wirksame_cfg = start.cfg
    saetze = [
        # English FIRST: measured twice against a German wish, the model
        # wrote German keywords when this sentence stood behind the one
        # naming the model (SDXL).
        "Write the prompt in ENGLISH regardless of the user's language. The image model was "
        "trained on English and does not reliably interpret other languages.",
        f"Generates an image using {familie.label}, the default image model.",
        "Describe the requested image through its subject, setting, lighting, mood, and "
        "appearance. Avoid vague adjectives.",
        _prompt_stil(familie),
    ]
    if wirksame_cfg == 1:
        saetze.append(
            "At CFG 1, the negative prompt has no effect. Omit it."
        )
    saetze.append(
        "Size, steps, CFG, sampler, and seed use the image model's start values by default. "
        "Specify a value only when the user requests it. It applies to this image only and "
        "does not change the settings."
    )
    saetze.append(where)
    return MCPWerkzeug(
        name=WERKZEUG_NAME,
        beschreibung=" ".join(saetze),
        schema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        f"Describe what the image should show, in English for {familie.label}."
                    ),
                },
                "negative_prompt": {
                    "type": "string",
                    "description": "Optional. Elements to exclude from the image.",
                },
                "image": INPUT_PICTURE,
                **_werte_schema(start, values),
            },
            "required": ["prompt"],
        },
        server=SERVER_NAME,
    )


@dataclass(frozen=True)
class FensterBild:
    """What the default image model will draw with.

    ``familie`` is the image model as a family, ``values`` the values the
    next picture is drawn with, by the names of the tool's fields — both
    exactly as the drawing will read them.
    """

    familie: Family | None
    values: dict[str, Any] = field(default_factory=dict)


def fensterbild(repositories, config) -> FensterBild:
    """The image model the next picture is drawn with: the default model
    of the picture server (app/bildstandardmodell.py), as a family, and the
    values it starts at.

    The SAME resolution the drawing makes (``_draw``): the picture studio's
    model and values are not read — the studio and the chats share nothing.
    Without a default model nothing draws, and this answers that too.

    ``values`` are the values in force: the values the user set for this
    model in the picture server, laid over its family's start values
    (``_request_of``, the drawing's own reading).
    """
    ordner = ort(config, "image_models")
    modell = bildstandardmodell.lesen(repositories, bildrunner.modelle(ordner))
    if not modell:
        return FensterBild(None)
    # A model whose family is not to be read has none here either, exactly
    # as the picture route takes it: its own values hold, and its kit is
    # the one given to it.
    header = (
        bildinhalt.family(ordner / modell) or ""
        if bildmodellwerte.family_detection(repositories, modell) else ""
    )
    familie = image_families.get(header)
    start = image_families.start_values(familie.name if familie is not None else None, modell)
    own = bildmodellwerte.eigene(repositories, modell)
    return FensterBild(familie, _values_in_force(_request_of(start, own)))


def _request_of(start, own: dict[str, Any]) -> dict[str, Any]:
    """The draw request the default model is drawn with, before anything
    the model asks for: every value starting where the model starts — the
    values the user set for this model in the picture server (``own``,
    empty where they do not apply) laid over its family's start values
    (``start``).

    ONE reading for the drawing and for the tool's description, so the
    values the model is told are the ones the picture is drawn with.
    """
    request: dict[str, Any] = {}
    starts_at = {
        "breite": start.width, "hoehe": start.height, "schritte": start.steps,
        "sampler": start.sampler, "scheduler": start.scheduler, "cfg": start.cfg,
        "guidance": start.guidance, "flow_shift": start.flow_shift,
    }
    for field_name in starts_at:
        if field_name in own:
            starts_at[field_name] = own[field_name]
    for field_name in ("breite", "hoehe", "schritte", "sampler", "scheduler", "cfg"):
        request[field_name] = starts_at[field_name]
    if starts_at["guidance"] is not None:
        request["guidance"] = starts_at["guidance"]
    if starts_at["flow_shift"] is not None:
        request["flow_shift"] = starts_at["flow_shift"]
    return request


def _values_in_force(request: dict[str, Any]) -> dict[str, Any]:
    """The values a draw request stands at, under the names the tool's
    fields have, and checked the way a value the model names is — so each
    stands in the schema as its field's own type, on the raster and inside
    the range the picture route keeps. A value that is not set (no sampler
    chosen) or not usable is left out, and the seed is never among them."""
    named = {
        outer: request.get(inner)
        for outer, inner, _text, _word in _WERTEFELDER if outer != "seed"
    }
    checked, _unusable = _geprueft(named)
    return {
        outer: checked[inner]
        for outer, inner, _text, _word in _WERTEFELDER if inner in checked
    }



def _geprueft(argumente: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The named values, checked the way the picture route checks them.

    Returns the values that can travel (under their request field names) and
    the names that cannot — a word where a number belongs, or a sampler no
    route knows. Nothing here invents a value: what comes out is what the
    picture will be drawn with, so the reply can name it honestly.
    """
    werte: dict[str, Any] = {}
    unbrauchbar: list[str] = []
    for aussen, innen, _was, _wort in _WERTEFELDER:
        roh = argumente.get(aussen)
        if roh in (None, ""):
            continue
        geprueft: Any = None
        if aussen in ("width", "height"):
            geprueft = bildwahlen.kante_pruefen(roh)
        elif aussen == "steps":
            geprueft = bildwahlen.schritte_pruefen(roh)
        elif aussen == "sampler":
            geprueft = bildwahlen.sampler_pruefen(str(roh)) or None
        elif aussen == "scheduler":
            geprueft = bildwahlen.scheduler_pruefen(str(roh)) or None
        elif aussen == "seed":
            try:
                geprueft = int(roh)
            except (TypeError, ValueError):
                geprueft = None
        else:  # cfg, guidance — never negative, no upper limit, as in sd.cpp
            try:
                geprueft = max(0.0, float(roh))
            except (TypeError, ValueError):
                geprueft = None
        if geprueft is None:
            unbrauchbar.append(aussen)
        else:
            werte[innen] = geprueft
    return werte, unbrauchbar


async def draw_with_window(
    argumente: dict[str, Any],
    basis: str,
    schluessel: str,
    *,
    chat_id: str | None = None,
    antwort_id: str | None = None,
    abbruch: asyncio.Event | None = None,
    input_picture: Path | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> "_Drawn | str":
    """Draws the picture a prompt asks for with the default model of the
    picture server and its start values, and hands back what was drawn —
    or the sentence the model reads when no picture came.

    The ONE place the values of a picture come together: ``draw_image`` and
    the service's own way from one sentence to a picture (``POST
    /bild/satz``, app/api/v1/bild.py) both go through it, so a picture
    drawn from a sentence takes exactly the values the model's call would.

    ``argumente`` carries the prompt (``prompt``) and, for the model's call,
    the values it named. ``transport`` is for a caller inside this service:
    the calls then go to the app in-process, session key included.
    """
    prompt = str(argumente.get("prompt") or "").strip()
    if not prompt:
        raise BildWerkzeugFehler("draw_image needs a prompt.")
    negativ = str(argumente.get("negative_prompt") or "").strip()
    # Every value the model named goes through the SAME checkers the picture
    # route uses, here and not there: the route's answer carries the picture
    # and the seed, nothing else, so a value it clamped would be reported
    # back to the model as it was ASKED for. Checked once on the way in,
    # both readers see the same number (the checkers are idempotent, so the
    # route clamping the same value again changes nothing).
    werte, unbrauchbar = _geprueft(argumente)
    if unbrauchbar:
        return (
            "The image was not generated because these values were invalid: "
            + ", ".join(unbrauchbar)
            + ". Provide numbers and a supported sampler or scheduler, or omit them to use "
              "the image model's start values."
        )

    # Every sentence this tool reads back comes from the picture route, and
    # the picture route writes them in the language the interface is set to
    # (``hole_sprache``). This tool is the model's door, so it asks that
    # route for English: one header, and every refusal along the whole route
    # — the missing space before drawing, the raw log of a failed run, all
    # of them — arrives in the language the model reads. The studio keeps
    # its own sentences: it asks the same route without this header.
    kopfzeilen = {"X-Sitzungsschluessel": schluessel, "X-Ui-Language": "en"}
    # A call that never got an answer — the service gone, the connection
    # cut, the time up — is a failure like any refused one, and so is an
    # answer httpx could not read: the model reads why, in the same
    # sentence, instead of a raw exception.
    # The chat's own answer, named by the caller: only with both does the
    # picture go into the chat.
    in_chat = bool(chat_id and antwort_id)
    optionen: dict[str, Any] = {} if transport is None else {"transport": transport}
    try:
        async with httpx.AsyncClient(
            timeout=ZEITFENSTER_S, headers=kopfzeilen, **optionen
        ) as client:
            return await _draw(
                client, basis, prompt, negativ, werte, chat_id,
                antwort_id if in_chat else None, abbruch, input_picture,
            )
    except (httpx.HTTPError, httpx.InvalidURL) as error:
        return f"The image could not be generated: {str(error) or type(error).__name__}"


async def ausfuehren(
    argumente: dict[str, Any],
    basis: str,
    bilderordner: Path,
    schluessel: str,
    antwort_id: str | None = None,
    chat_id: str | None = None,
    deliver_with: str | None = None,
    abbruch: asyncio.Event | None = None,
    input_picture: Path | None = None,
) -> str:
    """Draws the picture and reports what happened.

    ``input_picture`` is a picture the model named to draw from, already
    checked by the caller against the folders this run may read. Its
    content goes to the picture route; it is not copied into the pictures
    folder.

    ``basis`` is this service's own API root. Calling ourselves over HTTP is
    deliberate: the picture endpoint holds the one-picture lock, checks the
    memory and scrubs the metadata — re-implementing that here would be a
    second, drifting copy of the rules.

    ``schluessel`` is this run's own session key — without it
    every one of these calls is rejected the same way a foreign process's
    would be; being the service's own tool is not an exemption.

    ``antwort_id`` is the answer a chat is writing while it draws: with it
    and the chat, the route puts the picture into that answer's run in the
    chat (app/api/v1/bild.py, ``_ins_gespraech``). Without them — a job —
    the picture stays where the route put it, and the answer names that
    file. ``deliver_with`` is the tool this run hands files on with, where
    it has one: the answer then says to hand the picture on with it when it
    is meant for the user. ``abbruch`` is the stop signal of the run that
    called: set while the picture is being drawn, it ends the picture — a
    stop of the chat reaches the painter, not only the answer's text.
    """
    in_chat = bool(chat_id and antwort_id)
    drawn = await draw_with_window(
        argumente, basis, schluessel, chat_id=chat_id, antwort_id=antwort_id,
        abbruch=abbruch, input_picture=input_picture,
    )
    if isinstance(drawn, str):
        return drawn
    modell, koerper, daten = drawn.model, drawn.body, drawn.answer
    # The prompt it was drawn with, so the model sees what was drawn; and
    # when nobody prepared it, that it was drawn as the model wrote it.
    if drawn.prepared.not_prepared:
        prompt_satz = (
            f' The prompt was not prepared ({drawn.prepared.not_prepared}). The image was '
            f'generated using your original prompt: "{drawn.prepared.prompt}".'
        )
    else:
        prompt_satz = f' Prompt used to generate the image: "{drawn.prepared.prompt}".'

    pfad = bilderordner / daten.get("bild", "")

    # What was actually used, not what was asked for: the route clamps a
    # size to its raster and fills every value it was not given, and a
    # report naming the request would name numbers the picture never had.
    benutzt = [f"model {modell}"]
    breite, hoehe = koerper.get("breite"), koerper.get("hoehe")
    if breite and hoehe:
        benutzt.append(f"{breite}×{hoehe} pixels")
    # One table for all three readers — schema, request and this line — so a
    # value that travels can never be missing from the report.
    for _aussen, innen, _was, wort in _WERTEFELDER:
        if innen in ("breite", "hoehe", "seed"):
            continue
        wert = koerper.get(innen)
        if wert in (None, ""):
            continue
        benutzt.append(
            f"{wort} {wert:g}" if isinstance(wert, (int, float)) else f"{wort} {wert}"
        )
    # The seed comes from the ROUTE: it turns -1 into a real number so a
    # picture can be drawn again, and only the answer knows which one it is.
    seed = daten.get("seed", koerper.get("seed"))
    if seed is not None:
        benutzt.append(f"seed {seed}")
    if input_picture is not None:
        benutzt.append(f"generated from {input_picture.name}")
    if not in_chat:
        sentence = (
            f"The image was generated ({', '.join(benutzt)}) and saved as {pfad} in the "
            "pictures folder, visible to the user under Images. It is not attached to your "
            "report." + prompt_satz
        )
        if deliver_with:
            sentence += (
                " If this image is a deliverable for the user, deliver it using "
                f"{deliver_with} with this path."
            )
        return sentence
    # The picture hangs on the answer already. Told its path, a model writes
    # a link or an image tag onto it that points nowhere, under the picture
    # that is really there.
    return (
        f"The image was generated ({', '.join(benutzt)}), attached to this response, and saved "
        f"as {pfad}. It is already attached to your response, so write no link and no image "
        "markdown for it." + prompt_satz
    )


@dataclass(frozen=True)
class _Prepared:
    """The prompt a picture is drawn with, and why it was not prepared when
    the preparation did not answer (empty when it did)."""

    prompt: str
    negativ: str
    not_prepared: str = ""


@dataclass(frozen=True)
class _Drawn:
    """A picture the route drew: the model, the request body and the answer."""

    model: str
    body: dict[str, Any]
    answer: dict[str, Any]
    prepared: _Prepared


async def _aufbereiten(
    client: httpx.AsyncClient,
    basis: str,
    prompt: str,
    negativ: str,
    modell: str,
    *,
    familie: str,
    cfg: Any,
) -> _Prepared:
    """The request, written over by the prompt preparation — or as it came,
    with the reason, when the preparation did not answer."""
    try:
        antwort = await client.post(
            f"{basis}/bild/prompt",
            json={
                "prompt": prompt, "negativ": negativ, "modell": modell,
                "familie": familie,
                "cfg": cfg if isinstance(cfg, (int, float)) and not isinstance(cfg, bool) else None,
            },
        )
    except httpx.HTTPError as error:
        return _Prepared(prompt, negativ, str(error) or type(error).__name__)
    daten = _json_object(antwort)
    if antwort.status_code >= 400:
        return _Prepared(prompt, negativ, _reason(antwort, daten))
    neu = daten.get("prompt") if daten is not None else None
    if not isinstance(neu, str) or not neu.strip():
        return _Prepared(prompt, negativ, "The response contained no prompt.")
    neu_negativ = daten.get("negativ") if daten is not None else ""
    return _Prepared(neu.strip(), neu_negativ.strip() if isinstance(neu_negativ, str) else "")


async def _bild_anfordern(
    client: httpx.AsyncClient, basis: str, koerper: dict[str, Any],
    abbruch: asyncio.Event | None,
) -> httpx.Response:
    """The picture request, ended with the run it belongs to.

    The route draws in a thread of its own, so closing this request would
    leave the painter running for nobody — and holding the one-picture lock
    until its time limit, while every later picture is refused. A stop on
    the run's signal therefore asks the route to end the picture and goes on
    waiting for the route's own answer, which then carries the stop. Asked
    again every ``STOPP_TAKT_S`` until that answer is here: a stop that came
    before the painter had started found nothing to end.
    """
    # The route answers with the finished picture and has no frame of its
    # own; a bound on the read would end the wait while the painter still
    # draws, and the picture would never reach the chat.
    ohne_lesefrist = httpx.Timeout(ZEITFENSTER_S, read=None)
    if abbruch is None:
        return await client.post(f"{basis}/bild", json=koerper, timeout=ohne_lesefrist)
    anfrage = asyncio.ensure_future(
        client.post(f"{basis}/bild", json=koerper, timeout=ohne_lesefrist)
    )
    stopp = asyncio.ensure_future(abbruch.wait())
    gemeldet = False
    try:
        await asyncio.wait({anfrage, stopp}, return_when=asyncio.FIRST_COMPLETED)
        while not anfrage.done():
            try:
                await client.post(f"{basis}/bild/stop")
            except httpx.HTTPError:
                # Said once: the stop is sent again every second, and a route
                # that cannot be reached would fill the log with the same line.
                if not gemeldet:
                    log.warning("draw_image: the stop did not reach the picture route", exc_info=True)
                    gemeldet = True
            await asyncio.wait({anfrage}, timeout=STOPP_TAKT_S)
        return anfrage.result()
    finally:
        for aufgabe in (anfrage, stopp):
            if not aufgabe.done():
                aufgabe.cancel()


async def _bis_abbruch(arbeit: Any, abbruch: asyncio.Event | None) -> Any:
    """What the coroutine returns, or None when the stop signal came first —
    the coroutine is cancelled then, so a slow request ahead of the drawing
    does not hold a stopped run."""
    if abbruch is None:
        return await arbeit
    aufgabe = asyncio.ensure_future(arbeit)
    stopp = asyncio.ensure_future(abbruch.wait())
    try:
        await asyncio.wait({aufgabe, stopp}, return_when=asyncio.FIRST_COMPLETED)
        return aufgabe.result() if aufgabe.done() else None
    finally:
        for offen in (aufgabe, stopp):
            if not offen.done():
                offen.cancel()


def _gestoppt() -> str:
    """The sentence of a picture that was stopped: the route's own, the one a
    stop during the drawing hands back as well."""
    return f"The image could not be generated: {t('bild.abgebrochen', 'en')}"


async def _draw(
    client: httpx.AsyncClient,
    basis: str,
    prompt: str,
    negativ: str,
    werte: dict[str, Any],
    chat_id: str | None,
    antwort_id: str | None = None,
    abbruch: asyncio.Event | None = None,
    input_picture: Path | None = None,
) -> _Drawn | str:
    """Every call on the way to the picture, and the drawing itself.

    Returns what was drawn, or the sentence the model reads when no picture
    came. A call that got no answer at all raises and is answered by the
    caller, once for all of them. ``antwort_id`` is set only in a chat,
    together with ``chat_id``: the answer whose run the picture joins.
    ``abbruch`` is the run's stop signal: set, the picture ends and the
    answer says it was stopped.
    """
    list_answer = await client.get(f"{basis}/bild/modelle")
    # A failed or unreadable answer carries no ``programm_da`` — read as
    # a body it would report a missing generator that is in fact
    # installed (a rejected session key answers this way). The reason
    # goes to the model instead, the same sentence the draw call below
    # hands over.
    lage = _json_object(list_answer)
    if list_answer.status_code >= 400:
        return _nicht_gezeichnet(list_answer, lage)
    if (
        lage is None
        or _wrong_kind(lage, {"programm_da": bool, "modelle": list, "families": dict})
        or not _all_text(lage.get("modelle") or [])
        or not _all_text((lage.get("families") or {}).values())
    ):
        return UNUSABLE_ANSWER
    if not lage.get("programm_da"):
        return (
            "No image generator is installed. The user can download it from the plus menu "
            "under Images."
        )
    modelle = lage.get("modelle") or []
    familien = lage.get("families") or {}
    if not modelle:
        return (
            "No image model is installed. The user can add one under "
            "Images or from the catalogue."
        )
    # The default model of the picture server draws, whichever chat or job
    # asks: the picture studio's own model is the studio's.
    modell = lage.get("standardmodell")
    if not isinstance(modell, str) or modell not in modelle:
        return NO_DEFAULT_MODEL
    answer = await client.get(f"{basis}/bild/vorgaben", params={"modell": modell})
    # A failed answer is not an empty one: drawing on with the family's
    # start values would hand back a picture the window never asked for,
    # and the model would not know why. The reason goes to the model —
    # for an answer that cannot be read as well, which is no empty one
    # either.
    defaults = _json_object(answer)
    if answer.status_code >= 400:
        return _nicht_gezeichnet(answer, defaults)
    if defaults is None or _wrong_kind(
        defaults, {"family": str, "standalone": bool, "parts": dict}
    ):
        return UNUSABLE_ANSWER
    # The family the window states wins over the one the header names,
    # the same order the draw route keeps; the start values are that
    # family's own from the one table.
    # ONLY the guard reads further than these two voices: a run without a
    # chat has no window, and the route can answer without a family. Then the
    # header of the model file is the only voice left — and that IS where
    # the draw route reads the family (`bildinhalt.family`), reported with
    # the model list (`families`, app/api/v1/bild.py:321, filled at :422).
    # Without it a video would have been drawn and handed back as a
    # picture whenever the window and the route both happened to say
    # nothing. What it must NOT do is choose the drawing itself: a family
    # read here would bring its own kit along (`t5xxl`, `clip_l`, …) and
    # the route would refuse the body — the header is read for the ONE
    # question "can this model draw from text at all", nothing else.
    family = image_families.get(defaults.get("family"))
    wache = family or image_families.get(familien.get(modell))
    # The same rule the OFFER keeps, asked once more where the drawing
    # happens: a default model whose family cannot draw from text
    # (editing, video) is not offered this tool (app/tools/registry.py).
    # A run outlives the offer it started with, though — the user can
    # change the default model while an answer is still going, and a call
    # made against the old offer would have a video drawn and handed
    # back as a picture. Read again here, and answered in words rather
    # than drawn: the model can tell the user what to change.
    # The offer's own predicate, asked again here
    # (``image_families.draws_from_text``) — one rule, two ends of one
    # tool, so neither can drift away from the other.
    if wache is not None and not image_families.draws_from_text(wache):
        # What is true is that the model this call would draw with, the
        # default one, cannot draw from text.
        return (
            f"The image was not generated: the selected model, {wache.label}, cannot generate "
            "images from text. It edits existing images or creates videos. Ask the user to "
            "select a text-to-image model as the default on the picture server page and try "
            "again."
        )
    # Every value starts where the model starts: the values the user set for
    # this model in the picture server, laid over its family's start values
    # — the answer above carries both.
    start = image_families.start_values(family.name if family is not None else None, modell)
    koerper = _request_of(
        start, {name: defaults.get(name) for name in (defaults.get("eigene") or [])},
    )
    # The VAE format, the RNG and the further switches the family starts
    # with.
    if start.vae_format:
        koerper["vae_format"] = start.vae_format
    if start.rng:
        koerper["rng"] = start.rng
    if start.switches:
        koerper["switches"] = dict(start.switches)
    # What belongs to the model itself goes along; its kit the draw route
    # adds itself.
    if defaults.get("clip_skip"):
        koerper["clip_skip"] = defaults["clip_skip"]
    if defaults.get("prediction"):
        koerper["prediction"] = defaults["prediction"]
    if family is not None and family.model_args:
        koerper["model_args"] = family.model_args
    if family is not None and "familie" not in koerper:
        koerper["familie"] = family.name
    koerper["modell"] = modell
    # A number the user named travels along for THIS picture and is not
    # written anywhere: a wish spoken once in a chat is not a setting.
    # Whatever the caller did not send keeps the value it already has
    # above.
    koerper.update(werte)
    if input_picture is not None:
        # The picture the model named: handed to the service as its content
        # and drawn from under the name the service gives it. A family that
        # edits reads it as a reference — unless its editing needs a LoRA
        # of its own, which nothing here brings — and one that draws
        # picture to picture as the picture to start from. An unknown
        # family counts as one that does, like everywhere else.
        field = _input_field(family)
        if field is None:
            assert family is not None  # an unknown family has a field
            return (
                f"The image was not generated: the selected model, {family.label}, cannot use "
                "an image as input. Call again without an image."
            )
        name, refusal = await _hand_in(client, basis, input_picture)
        if name is None:
            return refusal
        koerper[field] = [name] if field == "ref_bilder" else name
    # Every request goes through the prompt preparation, the same one the
    # studio's button asks: a language model writes the prompt for
    # this family. When it does not answer, the picture is drawn with the
    # request as it came, and the answer says so.
    vorbereitet = await _bis_abbruch(
        _aufbereiten(
            client, basis, prompt, negativ, modell,
            familie=str(koerper.get("familie") or ""), cfg=koerper.get("cfg"),
        ),
        abbruch,
    )
    if vorbereitet is None:
        return _gestoppt()
    prompt, negativ = vorbereitet.prompt, vorbereitet.negativ
    koerper["prompt"] = prompt
    if negativ:
        koerper["negativ"] = negativ
    if antwort_id:
        # The route writes the finished picture into the run of the answer
        # being written, at once, and the chat draws it in that run's tiles.
        koerper["chat_id"] = chat_id
        koerper["lauf_kennung"] = antwort_id

    # A stop that came after the preparation answered: nothing has been
    # started yet, so nothing is.
    if abbruch is not None and abbruch.is_set():
        return _gestoppt()
    antwort = await _bild_anfordern(client, basis, koerper, abbruch)
    daten = _json_object(antwort)
    if antwort.status_code >= 400:
        return _nicht_gezeichnet(antwort, daten)
    # An answer that is not an object, or whose picture name is not a name,
    # carries no picture; read as one it would end in a crash instead of a
    # reason.
    if daten is None:
        return UNUSABLE_ANSWER
    # The name is read and then deleted inside the picture folder, so only a
    # bare file name counts; "../x" or an absolute path would reach outside.
    name = daten.get("bild")
    if not isinstance(name, str) or not name or Path(name).name != name:
        return NO_PICTURE
    return _Drawn(model=str(modell), body=koerper, answer=daten, prepared=vorbereitet)


def _input_field(family: image_families.Family | None) -> str | None:
    """The request field a named input picture goes into for this family,
    or None when the family draws from no picture at all."""
    if family is None:
        return "startbild"
    if "edit" in family.tasks and not family.edit_needs_lora:
        return "ref_bilder"
    if "img2img" in family.tasks:
        return "startbild"
    return None


async def _hand_in(
    client: httpx.AsyncClient, basis: str, picture: Path, made: Made = PICTURE,
) -> tuple[str | None, str]:
    """Hands the input picture to the service among its working pictures —
    made for one draw, on no wall — and answers with the name the service
    gave it, or with no name and the sentence the model reads instead."""
    kind = _PICTURE_TYPES.get(picture.suffix.lower())
    if kind is None:
        return None, f"{made.refused}: {picture.name} is not a PNG, JPEG, or WebP image."
    try:
        data = await asyncio.to_thread(picture.read_bytes)
    except OSError as error:
        return None, f"{made.refused}: {picture.name} could not be read ({error})."
    answer = await client.post(
        f"{basis}/images", params={"scratch": "true"}, content=data,
        headers={"Content-Type": kind},
    )
    body = _json_object(answer)
    if answer.status_code >= 400:
        return None, _nicht_gezeichnet(answer, body, made)
    name = (body or {}).get("bild")
    if not isinstance(name, str) or not name or Path(name).name != name:
        return None, made.unusable
    return name, ""


def _nicht_gezeichnet(
    antwort: httpx.Response, body: dict[str, Any] | None, made: Made = PICTURE,
) -> str:
    """What the model reads when a call on the way to the picture failed.

    The route answered in English, because this tool asks for it
    (``X-Ui-Language``). What it hands over is its own failure sentence, the
    raw log of a run included: that log is the evidence, and nothing may
    shorten or translate it.
    """
    return f"{made.failed}: {_reason(antwort, body)}"


def _json_object(response: httpx.Response) -> dict[str, Any] | None:
    """The answer's JSON object, or None when the body is not one."""
    try:
        body = response.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _all_text(values: Any) -> bool:
    """Whether every entry is text — model names and families are."""
    return all(isinstance(value, str) for value in values)


def _wrong_kind(body: dict[str, Any], kinds: dict[str, type]) -> bool:
    """Whether a field the drawing reads has the wrong kind of value.

    A field that is missing or null reads as empty, as before; one that is
    there with another kind (a list where a mapping belongs) is an answer
    this tool cannot read, and is treated like one.
    """
    return any(
        body.get(name) is not None and not isinstance(body[name], kind)
        for name, kind in kinds.items()
    )


def _reason(response: httpx.Response, body: dict[str, Any] | None) -> str:
    """Why a call failed, as readable as the answer allows.

    The route's own ``detail`` first — a sentence, or the list a rejected
    request carries (app/input_errors.py), whose ``msg`` parts are joined.
    An object without a usable ``detail`` says nothing beyond its status,
    so the status line stands in; any other body is handed over as text,
    its last lines only, and an empty one leaves the status line again. ``body`` is the answer
    as ``_json_object`` already read it.
    """
    if body is not None:
        detail = body.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail
        if isinstance(detail, list):
            parts = [
                entry["msg"] for entry in detail
                if isinstance(entry, dict)
                and isinstance(entry.get("msg"), str)
                and entry["msg"].strip()
            ]
            if parts:
                return "; ".join(parts)
        if detail not in (None, "", [], {}) and not isinstance(detail, str):
            # Any other detail — an object, a list without a usable ``msg``,
            # a number, a flag — says more as compact JSON than as nothing.
            return json.dumps(detail, ensure_ascii=False, separators=(",", ":"))
    else:
        # A body that is no object is not the route's own sentence — a
        # proxy's HTML page can run to many kilobytes. It is kept to the
        # same size, and from the same end, as the painter's log in a failed
        # picture; the route's own ``detail`` above stays whole.
        text = bildrunner.tail_lines(
            (response.text or "").strip().splitlines(), bildrunner.LOG_LIMIT
        )
        if text:
            return text
    return f"HTTP {response.status_code} {response.reason_phrase}".strip()
