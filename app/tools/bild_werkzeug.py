"""The drawing tool — `draw_image`.

The bridge the image-generator skill was missing: the skill told the model
to make a picture, but no tool existed that could — the model guessed at
shell commands and failed. This one talks to the picture pipeline of this
very service over its own HTTP API, so it walks exactly the road the
picture window walks: the same queue lock, the same memory check, the same
metadata scrub.

The model does not pick the model file or any other value. Every value is
the one the picture window of the chat stands at (stored per chat,
``app/bildfensterwahl.py``) — read on every call, so a change in the window
holds for the very next picture — except the pictures the window was
given (start picture, mask, face photo, guide picture). A job reads the
window of the chat it was started from. A run with no chat, a chat without a
model of its own, or one whose model is gone from the folder takes the first
model in the folder with its family's start values
(``app/image_families.py``), and the log says so. What the model brings is
the one thing only it has: the prompt.

In a chat the picture goes the picture window's way all the way into the
chat: the request names the chat and the answer being written, and the
route writes every finished picture into that answer's own run itself —
the moment it is finished, one file and one row, the same tiles the picture
window's pictures stand in. The answer is named by the caller, not by an
argument: anything the model can pass, the model can forge.

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
    bildfensterwahl, bildinhalt, bildmodellwerte, bildrunner, bildstandardmodell, bildstile,
    bildwahlen, image_families,
)
from app.i18n import t
from app.image_families import Family
from app.speicherorte import ort
from app.tools.mcp_client import MCPWerkzeug

log = logging.getLogger(__name__)

SERVER_NAME = "image"
WERKZEUG_NAME = "draw_image"

# An SDXL picture with a detailer pass takes minutes, not seconds. This bound
# only keeps a hung server from holding the tool call open forever.
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
    "The finished picture appears in your answer by itself, and the result "
    "names its file and path; do not describe its contents afterwards — "
    "you have not seen it."
)
# What the model reads about the optional input picture, in every list.
INPUT_PICTURE = {
    "type": "string",
    "description": (
        "Optional: the path of a picture to draw from — a file you may read, "
        "in a shared folder or in the pictures folder. With it, the picture "
        "is drawn from that one instead of from scratch."
    ),
}
# The kinds of picture the service takes in, by the file's ending.
_PICTURE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
}
IN_JOB = (
    "The finished picture is saved in the pictures folder, which the user "
    "sees under Images, and the answer names its file; do not describe its "
    "contents afterwards — you have not seen it."
)

# What the model reads when the picture service answered without an error
# but with nothing this tool can use. Short and without field names: the
# model cannot repair the service, it can only tell the user that the
# picture did not come.
UNUSABLE_ANSWER = (
    "The picture could not be drawn: the picture service sent an answer "
    "that could not be used."
)
NO_PICTURE = "The picture could not be drawn: the picture service sent no picture."


@dataclass(frozen=True)
class Made:
    """What a tool that paints is on the way to, in the words its refusals
    open with. The calls before the painting are shared by every such tool
    (the chat of a job, the chat's picture window, a picture handed in);
    each tells them what it makes, so the model reads of the thing it asked
    for."""

    # A call on the way failed.
    failed: str
    # The request itself was not usable.
    refused: str
    # The service answered with something that could not be read.
    unusable: str


PICTURE = Made("The picture could not be drawn", "The picture was not drawn", UNUSABLE_ANSWER)
# Nothing chooses the default model by itself, so without one the model
# learns where the user chooses it.
NO_DEFAULT_MODEL = (
    "The picture was not drawn: no default image model is chosen, and this "
    "chat names no model of its own. Ask the user to choose the default "
    "model on the picture server page (Local, picture server, the row "
    "Default model) and try again."
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
        "Write it as short, dense keyword phrases, most important first; "
        "weights like (word:1.2) are read. Long prompts are read in pieces "
        "of 77 tokens, so what stands first weighs most."
    ),
    "t5": (
        "Write whole, flowing sentences. Long prompts are read in pieces of "
        "256 tokens, so the opening sentence carries the most weight."
    ),
    "llm": (
        "Write a full description in plain prose; a short piece of text "
        "inside the picture works too."
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
        "The picture's width in pixels. Defaults to this chat's current "
        "setting. Omit unless the user asks for a width.",
        "size",
    ),
    (
        "height", "hoehe",
        "The picture's height in pixels. Defaults to this chat's current "
        "setting. Omit unless the user asks for a height.",
        "size",
    ),
    (
        "steps", "schritte",
        "The number of sampling steps. Defaults to this chat's current "
        "setting. Omit unless the user asks for a step count.",
        "steps",
    ),
    (
        "cfg", "cfg",
        "The CFG scale. Defaults to this chat's current setting. Omit unless "
        "the user asks for one.",
        "CFG",
    ),
    (
        "sampler", "sampler",
        "The sampler, e.g. euler_a. Defaults to this chat's current setting. "
        "Omit unless the user asks for a sampler.",
        "sampler",
    ),
    (
        "scheduler", "scheduler",
        "The scheduler, e.g. discrete. Defaults to this chat's current "
        "setting. Omit unless the user asks for a scheduler.",
        "scheduler",
    ),
    (
        "seed", "seed",
        "The seed. Random by default. Omit unless the user names a seed.",
        "seed",
    ),
    (
        "guidance", "guidance",
        "The distilled guidance (Flux only). Defaults to this chat's current "
        "setting. Omit unless the user asks for one.",
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
    """The tool as this chat's picture window makes it.

    ``familie`` is the image model the picture window stands at, ``values``
    the values the next picture of this chat is drawn with, the CFG among
    them. Together they decide what the model has to know BEFORE writing:
    which text encoder reads the prompt and how, whether a negative prompt
    does anything at all, which values exist, and what each one is when the
    model sends none. The caller reads both with ``fensterbild`` — the same
    reading the drawing itself makes — so the description and the call
    cannot name two different models or two different values.

    ``None`` is the honest answer for a caller that knows no window: the
    sentence that fits every case, without a value the tool could not send.

    ``in_chat`` is False for a job's list: its picture stays in the pictures
    folder instead of appearing in an answer (``IN_JOB``).
    """
    where = IN_CHAT if in_chat else IN_JOB
    if familie is None:
        return MCPWerkzeug(
            name=WERKZEUG_NAME,
            beschreibung=(
                "Draws a picture with the image model installed on this "
                "machine. Turn the wish into ONE dense visual sentence: "
                f"subject, setting, light, mood, look — vague adjectives do nothing. {where}"
            ),
            schema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "What the picture shows. Write it in English.",
                    },
                    "negative_prompt": {
                        "type": "string",
                        "description": "What must stay out of the picture. Optional.",
                    },
                    "image": INPUT_PICTURE,
                },
                "required": ["prompt"],
            },
            server=SERVER_NAME,
        )
    # No branch for a family that cannot draw from text (editing, video): a
    # run whose window stands at one is not offered this tool at all
    # (app/tools/registry.py), so there is nothing here to describe — and a
    # description that has to say "this does nothing" is a promise the tool
    # cannot keep, sent in every request of that run.
    start = familie.start
    # What the picture will really run at: the CFG among the values in
    # force — the chat's own, else the one set for the model itself, else
    # the family's start — and the family's start for a caller that read
    # none.
    wirksame_cfg = (values or {}).get("cfg")
    if wirksame_cfg is None:
        wirksame_cfg = start.cfg
    saetze = [
        # English FIRST: measured twice against a German wish, the model
        # wrote German keywords when this sentence stood behind the one
        # naming the model (picture window on SDXL).
        "Write the prompt in ENGLISH, whatever language the user writes in — "
        "the picture model was trained on English and reads nothing else "
        "reliably.",
        f"Draws a picture with {familie.label}, the image model this chat "
        "is set to.",
        "Turn the wish into a picture: subject, setting, light, mood, look — "
        "vague adjectives do nothing.",
        _prompt_stil(familie),
    ]
    if wirksame_cfg == 1:
        saetze.append(
            "At CFG 1 the negative prompt has no effect — leave it out."
        )
    saetze.append(
        "Size, steps, CFG, sampler and seed default to this chat's current "
        "settings. Send one only when the user asks for it; it applies to "
        "this picture only and does not change the settings."
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
                        f"What the picture shows, written in English for "
                        f"{familie.label}."
                    ),
                },
                "negative_prompt": {
                    "type": "string",
                    "description": "What must stay out of the picture. Optional.",
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
    """What this chat's picture window will draw with.

    ``familie`` is the image model as a family, ``values`` the values the
    next picture is drawn with, by the names of the tool's fields — both
    exactly as the drawing will read them.
    """

    familie: Family | None
    values: dict[str, Any] = field(default_factory=dict)


def fensterbild(repositories, chat_id: str | None, config) -> FensterBild:
    """The image model this chat's picture window will draw with.

    The SAME resolution the drawing makes (``ausfuehren``): the model the
    window names, but only while it is still in the folder — a model that is
    gone changes nothing, the default model of the picture server draws
    instead (app/bildstandardmodell.py). Where there is no chat, no window
    or no model, the default model is what draws, and that is what this
    answers too; without one nothing draws. The window's own family wins
    over the file's header, again like the drawing.

    ``values`` are the values in force: what the chat set, and for
    everything it never set the values the user set for this model in the
    picture server, laid over its family's start values (``_request_of``,
    the drawing's own reading).
    """
    ordner = ort(config, "image_models")
    modelle = bildrunner.modelle(ordner)
    werte = repositories.einstellungen.zusammengefuehrt(
        bildfensterwahl.SCHLUESSEL, chat=chat_id
    )
    window: dict[str, Any] = {}
    modell = werte.get("modell") if isinstance(werte, dict) else None
    if isinstance(modell, str) and modell in modelle:
        window = werte
    else:
        # No window, or one whose model is gone: the default model draws,
        # and the chat's other values belonged to its own model.
        modell = bildstandardmodell.lesen(repositories, modelle)
        if not modell:
            return FensterBild(None)
    # A model whose family is not to be read has none here either, exactly
    # as the picture route takes it: its own values hold, and its kit is
    # the one given to it.
    header = (
        bildinhalt.family(ordner / modell) or ""
        if bildmodellwerte.family_detection(repositories, modell) else ""
    )
    familie = image_families.get(window.get("familie")) or image_families.get(header)
    start = image_families.start_values(familie.name if familie is not None else None, modell)
    own = (
        bildmodellwerte.eigene(repositories, modell)
        if _own_values_apply(familie, header) else {}
    )
    return FensterBild(familie, _values_in_force(_request_of(window, start, own)))


def _own_values_apply(family: Family | None, header_family: Any) -> bool:
    """Whether the values the user set for the model itself apply. A family
    said by hand in the chat is another family than the one the file's
    header names, and starts at its own start values."""
    return family is None or family.name == header_family


def _request_of(window: dict[str, Any], start, own: dict[str, Any]) -> dict[str, Any]:
    """The draw request this chat makes with its model, before anything the
    model asks for: what the chat set, and every value it never set starting
    where the model starts — the values the user set for this model in the
    picture server (``own``, empty where they do not apply) laid over its
    family's start values (``start``).

    ONE reading for the drawing and for the tool's description, so the
    values the model is told are the ones the picture is drawn with.
    """
    request = bildfensterwahl.draw_request(window)
    starts_at = {
        "breite": start.width, "hoehe": start.height, "schritte": start.steps,
        "sampler": start.sampler, "scheduler": start.scheduler, "cfg": start.cfg,
        "guidance": start.guidance, "flow_shift": start.flow_shift,
    }
    for field_name in starts_at:
        if field_name in own:
            starts_at[field_name] = own[field_name]
    for field_name in ("breite", "hoehe", "schritte", "sampler", "scheduler", "cfg"):
        request.setdefault(field_name, starts_at[field_name])
    if "guidance" not in request and starts_at["guidance"] is not None:
        request["guidance"] = starts_at["guidance"]
    if "flow_shift" not in request and starts_at["flow_shift"] is not None:
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


async def ausfuehren(
    argumente: dict[str, Any],
    basis: str,
    bilderordner: Path,
    schluessel: str,
    antwort_id: str | None = None,
    chat_id: str | None = None,
    job_id: str | None = None,
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
            "The picture was not drawn: these values were not usable: "
            + ", ".join(unbrauchbar)
            + ". Send numbers (and a known sampler or scheduler), or omit "
            "them to use this chat's current settings."
        )

    # Every sentence this tool reads back comes from the picture route, and
    # the picture route writes them in the language the interface is set to
    # (``hole_sprache``). This tool is the model's door, so it asks that
    # route for English: one header, and every refusal along the whole route
    # — the missing space before drawing, the raw log of a failed run, all
    # of them — arrives in the language the model reads. The window keeps
    # its own sentences: it asks the same route without this header.
    kopfzeilen = {"X-Sitzungsschluessel": schluessel, "X-Ui-Language": "en"}
    # A call that never got an answer — the service gone, the connection
    # cut, the time up — is a failure like any refused one, and so is an
    # answer httpx could not read: the model reads why, in the same
    # sentence, instead of a raw exception.
    # The chat's own answer, named by the caller: only with both does the
    # picture go into the chat.
    in_chat = bool(chat_id and antwort_id)
    try:
        async with httpx.AsyncClient(timeout=ZEITFENSTER_S, headers=kopfzeilen) as client:
            drawn = await _draw(
                client, basis, prompt, negativ, werte, chat_id, job_id,
                antwort_id if in_chat else None, abbruch, input_picture,
            )
    except (httpx.HTTPError, httpx.InvalidURL) as error:
        return f"The picture could not be drawn: {str(error) or type(error).__name__}"
    if isinstance(drawn, str):
        return drawn
    modell, koerper, daten = drawn.model, drawn.body, drawn.answer
    # The prompt it was drawn with, so the model sees what was drawn; and
    # when nobody prepared it, that it was drawn as the model wrote it.
    if drawn.prepared.not_prepared:
        prompt_satz = (
            f" The prompt was not prepared ({drawn.prepared.not_prepared}); the "
            f'picture was drawn with your prompt as written: "{drawn.prepared.prompt}".'
        )
    else:
        prompt_satz = f' The prompt it was drawn with: "{drawn.prepared.prompt}".'

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
        benutzt.append(f"drawn from {input_picture.name}")
    if not in_chat:
        sentence = (
            f"The picture was drawn ({', '.join(benutzt)}) and saved as {pfad}, "
            "in the pictures folder the user sees under Images; it is not "
            "attached to your report." + prompt_satz
        )
        if deliver_with:
            sentence += (
                " When it is meant for the user as a result of this job, "
                f"deliver it with {deliver_with}, passing this path."
            )
        return sentence
    return (
        f"The picture was drawn ({', '.join(benutzt)}), is attached to this "
        f"answer and saved as {pfad}." + prompt_satz
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
    style: Any,
) -> _Prepared:
    """The request, written over by the prompt preparation — or as it came,
    with the reason, when the preparation did not answer. ``style`` is the
    window's choice of a style; the preparation is told that style's name."""
    stil = await _style_name(client, basis, style)
    try:
        antwort = await client.post(
            f"{basis}/bild/prompt",
            json={
                "prompt": prompt, "negativ": negativ, "modell": modell,
                "familie": familie, "stil": stil,
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
        return _Prepared(prompt, negativ, "the answer carried no prompt")
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
    if abbruch is None:
        return await client.post(f"{basis}/bild", json=koerper)
    anfrage = asyncio.ensure_future(client.post(f"{basis}/bild", json=koerper))
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
    return f"The picture could not be drawn: {t('bild.abgebrochen', 'en')}"


async def _draw(
    client: httpx.AsyncClient,
    basis: str,
    prompt: str,
    negativ: str,
    werte: dict[str, Any],
    chat_id: str | None,
    job_id: str | None,
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
            "No image generator is installed. The user can fetch it under "
            "Images (plus menu)."
        )
    modelle = lage.get("modelle") or []
    familien = lage.get("families") or {}
    if not modelle:
        return (
            "No image model is installed. The user can add one under "
            "Images or from the catalogue."
        )
    if chat_id is None and job_id:
        chat_id, refusal = await _chat_of_job(client, basis, job_id)
        if refusal is not None:
            return refusal
    window, refusal = await _window_of_chat(client, basis, chat_id)
    if refusal is not None:
        return refusal
    gewaehlt = window.get("modell")
    modell: str = gewaehlt if isinstance(gewaehlt, str) else ""
    if modell not in modelle:
        standard = lage.get("standardmodell")
        if not isinstance(standard, str) or standard not in modelle:
            return NO_DEFAULT_MODEL
        log.info(
            "draw_image: %s — drawing with the default model %s",
            f"the chat's model {modell} is not in the folder" if modell
            else "no model is set in this chat's picture window" if chat_id
            else "a run outside a chat has no picture window",
            standard,
        )
        modell = standard
        # The chat's other values belonged to its own model.
        window = {}
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
    family = image_families.get(window.get("familie")) or image_families.get(
        defaults.get("family")
    )
    wache = family or image_families.get(familien.get(modell))
    # The same rule the OFFER keeps, asked once more where the drawing
    # happens: a window standing at a family that cannot draw from text
    # (editing, video) is not offered this tool (app/tools/registry.py).
    # A run outlives the offer it started with, though — the user can
    # turn the window around while an answer is still going, and a call
    # made against the old offer would have a video drawn and handed
    # back as a picture. Read again here, and answered in words rather
    # than drawn: the model can tell the user what to change.
    # The offer's own predicate, asked again here
    # (``image_families.draws_from_text``) — one rule, two ends of one
    # tool, so neither can drift away from the other.
    if wache is not None and not image_families.draws_from_text(wache):
        # Says "the model in use" and not "this chat's picture window":
        # the family can also come from the default model —
        # a run without a chat has no window at all, and a window whose
        # model has left the folder is read the same way (see the two
        # branches above). What is true in all of them is that the model
        # this call would draw with cannot draw from text.
        return (
            "The picture was not drawn: the image model in use — "
            f"{wache.label} — cannot draw from text; it edits an "
            "existing picture or makes video. Ask the user to pick a "
            "text-to-image model and try again — under Images for this "
            "chat, or as the default model on the picture server page "
            "when the run has no chat of its own."
        )
    # What the chat never set starts where the model starts: the values the
    # user set for this model in the picture server, laid over its family's
    # start values — the answer above carries both. A family said by hand in
    # the window is another family than the header's, and starts at its own
    # start values.
    start = image_families.start_values(family.name if family is not None else None, modell)
    eigene_gelten = _own_values_apply(family, defaults.get("family"))
    koerper = _request_of(
        window, start,
        {name: defaults.get(name) for name in (defaults.get("eigene") or [])}
        if eigene_gelten else {},
    )
    # The VAE format, the RNG and the further switches the family starts
    # with, each where the chat set none of its own.
    if start.vae_format and "vae_format" not in koerper:
        koerper["vae_format"] = start.vae_format
    if start.rng and "rng" not in koerper:
        koerper["rng"] = start.rng
    if start.switches:
        koerper["switches"] = {**start.switches, **(koerper.get("switches") or {})}
    # What belongs to the model itself goes along where the chat set none;
    # its kit the draw route adds itself.
    if eigene_gelten:
        if defaults.get("clip_skip") and "clip_skip" not in koerper:
            koerper["clip_skip"] = defaults["clip_skip"]
        if defaults.get("prediction") and "prediction" not in koerper:
            koerper["prediction"] = defaults["prediction"]
    if "model_args" not in window and family is not None and family.model_args:
        koerper["model_args"] = family.model_args
    if family is not None and "familie" not in koerper:
        koerper["familie"] = family.name
    koerper["modell"] = modell
    # A number the user named travels along for THIS picture and is not
    # written into the picture window: the window is the user's, and a
    # wish spoken once in a chat is not a setting. Whatever the caller
    # did not send keeps the value it already has above.
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
                "The picture was not drawn: the image model in use — "
                f"{family.label} — cannot draw from a picture. Call again "
                "without an image."
            )
        name, refusal = await _hand_in(client, basis, input_picture)
        if name is None:
            return refusal
        koerper[field] = [name] if field == "ref_bilder" else name
    # Every request goes through the prompt preparation, the same one the
    # picture window's button asks: a language model writes the prompt for
    # this family. When it does not answer, the picture is drawn with the
    # request as it came, and the answer says so.
    vorbereitet = await _bis_abbruch(
        _aufbereiten(
            client, basis, prompt, negativ, modell,
            familie=str(koerper.get("familie") or ""), cfg=koerper.get("cfg"),
            style=window.get("stil"),
        ),
        abbruch,
    )
    if vorbereitet is None:
        return _gestoppt()
    prompt, negativ = vorbereitet.prompt, vorbereitet.negativ
    koerper["prompt"] = prompt
    if negativ:
        koerper["negativ"] = negativ
    if chat_id:
        log.info("draw_image: drawing with the picture window of chat %s", chat_id)
    if antwort_id:
        # The picture window's own way into the chat: the route writes the
        # finished picture into the run of the answer being written, at
        # once, and the window draws it in that run's tiles.
        koerper["chat_id"] = chat_id
        koerper["lauf_kennung"] = antwort_id

    # A stop that came after the preparation answered: nothing has been
    # started yet, so nothing is.
    if abbruch is not None and abbruch.is_set():
        return _gestoppt()
    try:
        antwort = await _bild_anfordern(client, basis, koerper, abbruch)
    except httpx.ReadTimeout:
        # The request went out and the route may still be drawing: a
        # second call would draw the same picture twice.
        return (
            "The picture took too long: no answer came within "
            f"{ZEITFENSTER_S / 60:g} minutes. It may still be drawn, so "
            "do not draw it again."
        )
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
        return None, f"{made.refused}: {picture.name} is not a PNG, JPEG or WebP picture."
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


async def _chat_of_job(
    client: httpx.AsyncClient, basis: str, job_id: str, made: Made = PICTURE,
) -> tuple[str | None, str | None]:
    """The chat a job was started from, and the sentence that stops the
    drawing when the job could not be read.

    No chat is a real answer: a job a schedule or the start window started
    has none, and neither has a job the service does not know (the job
    route answers 404 for that, app/api/v1/auftraege.py), and a readable
    answer without a chat counts as no chat. Any other failed
    answer stops the drawing: guessing "no chat" there would draw with the
    default model instead of the chat's own. A call that got no
    answer at all raises and is left to the caller.
    """
    antwort = await client.get(f"{basis}/jobs/{job_id}")
    if antwort.status_code == 404:
        return None, None
    body = _json_object(antwort)
    if antwort.status_code >= 400:
        return None, _nicht_gezeichnet(antwort, body, made)
    chat = (body or {}).get("chat_id")
    return (chat if isinstance(chat, str) and chat else None), None


async def _style_name(client: httpx.AsyncClient, basis: str, chosen: Any) -> str:
    """The name of the style the window draws through, as the prompt
    preparation is told it — the name the style has now. A style that is
    gone names none, like the button in the picture studio; a list that
    could not be read names none either, and the picture is drawn all the
    same: the name is one fact more for the prompt writer, not a setting of
    the drawing."""
    if not isinstance(chosen, str) or not chosen:
        return ""
    try:
        antwort = await client.get(f"{basis}/settings/resolved/{bildstile.SCHLUESSEL}")
    except httpx.HTTPError:
        return ""
    body = _json_object(antwort)
    if antwort.status_code >= 400:
        return ""
    return bildstile.name_of((body or {}).get("wert"), chosen)


async def _window_of_chat(
    client: httpx.AsyncClient, basis: str, chat_id: str | None, made: Made = PICTURE,
) -> tuple[dict[str, Any], str | None]:
    """What this chat's picture window stands at ({} when there is no chat
    or the window holds nothing), and the sentence that stops the drawing
    when the window could not be read.

    The settings route answers a chat without a window with an empty value,
    never with an error (app/api/v1/einstellungen.py) — so a failed answer
    is a real failure and stops the drawing, rather than drawing with the
    default model instead of the chat's own. An answer that
    comes without a window value counts as no window. A call that got no
    answer at all raises and is left to the caller.
    """
    if not chat_id:
        return {}, None
    antwort = await client.get(
        f"{basis}/settings/resolved/bildfenster", params={"chat": chat_id}
    )
    body = _json_object(antwort)
    if antwort.status_code >= 400:
        return {}, _nicht_gezeichnet(antwort, body, made)
    value = (body or {}).get("wert")
    if not isinstance(value, dict):
        return {}, None
    # The family the window names decides how the picture is drawn; one of
    # the wrong kind is an answer this tool cannot read, not an empty one.
    if _wrong_kind(value, {"familie": str}):
        return {}, made.unusable
    return value, None
