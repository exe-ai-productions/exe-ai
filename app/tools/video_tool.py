"""The video tool: the model asks for a short video — from words alone, or
from a picture it names.

It goes the way the drawing tool goes (app/tools/bild_werkzeug.py): it calls
this very service's picture route, which decides who paints, holds the
one-picture lock and puts the finished file into the pictures folder — and,
in a chat, into the answer being written. The route is asked for a video;
everything else about the request is the video model's own start, with the
values of the chat's picture window laid over where that window stands at
this model.

A video has no time limit. It ends when it is finished or when the run that
asked for it is stopped.

The tool exists only while a video model lies in the model folder
(``video_model_installed``): a tool that is sure to fail is one the model
should never be shown.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx

from app import bildfensterwahl, bildinhalt, bildrunner, image_families
from app.tools import bild_werkzeug
from app.tools.mcp_client import MCPWerkzeug

log = logging.getLogger(__name__)

SERVER_NAME = bild_werkzeug.SERVER_NAME
WERKZEUG_NAME = "draw_video"
# The tools that paint: what they make joins the run of the answer being
# written, and a stop of that run has to end the painter.
DRAWING_TOOLS = frozenset({bild_werkzeug.WERKZEUG_NAME, WERKZEUG_NAME})

IN_CHAT = (
    "The finished video appears automatically in your response, and the result includes its "
    "filename and path. Do not describe its contents afterward; you have not seen it."
)
IN_JOB = (
    "The finished video is saved in the pictures folder, visible to the user under Images. "
    "The response includes its filename. Do not describe its contents afterward; you have not "
    "seen it."
)

UNUSABLE_ANSWER = (
    "The video could not be generated: the image service returned an unusable response."
)
# What this tool makes, for the calls it shares with the drawing tool.
VIDEO = bild_werkzeug.Made(
    "The video could not be generated", "The video was not generated", UNUSABLE_ANSWER,
)
NO_VIDEO_MODEL = (
    "No video model is installed. The user can add one under Images or from "
    "the catalogue."
)
# Nothing chooses among several video models by itself.
MODEL_NOT_CHOSEN = (
    "The video was not generated: several video models are installed, but none is selected "
    "for this chat. Ask the user to select one under Images › Video."
)

# The start values of a video model the request carries, by their name in
# the route's answer and in its request (app/api/v1/bild.py).
_START_FIELDS = (
    "breite", "hoehe", "schritte", "cfg", "guidance", "sampler", "scheduler", "flow_shift",
    "video_frames", "fps", "vae_format", "rng", "switches", "model_args",
)


# The last answer per model folder, with the folder's change time it was
# read at. The registry asks at every listing and every call; a file that
# arrives, leaves or is renamed changes that time, and only then is the
# folder read again.
_installed: dict[str, tuple[int, bool]] = {}


def video_model_installed(model_folder: Path) -> bool:
    """Whether a video model lies in the model folder — a file whose header
    names a family that makes video."""
    folder = Path(model_folder).expanduser()
    try:
        changed = folder.stat().st_mtime_ns
    except OSError:
        return False
    known = _installed.get(str(folder))
    if known is not None and known[0] == changed:
        return known[1]
    found = any(
        (family := image_families.get(bildinhalt.family(folder / name))) is not None
        and family.video
        for name in bildrunner.modelle(folder)
    )
    _installed[str(folder)] = (changed, found)
    return found


def werkzeug_beschreibung(in_chat: bool = True) -> MCPWerkzeug:
    """The tool as a run is offered it. ``in_chat`` is False for a job's
    list: its video stays in the pictures folder instead of appearing in an
    answer."""
    return MCPWerkzeug(
        name=WERKZEUG_NAME,
        beschreibung=(
            "Makes a short video with the video model installed on this "
            "machine — from words alone, or from a picture when you pass its "
            "path as image. Write the prompt in ENGLISH: what is seen and "
            "how it moves. A video takes minutes and has no time limit; it "
            "ends when it is finished or when the user stops the run. "
            + (IN_CHAT if in_chat else IN_JOB)
        ),
        schema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Describe the video's content and motion in English.",
                },
                "negative_prompt": {
                    "type": "string",
                    "description": "Optional. Elements to exclude from the video.",
                },
                "image": {
                    "type": "string",
                    "description": (
                        "Optional: path to a readable image in a shared folder or the "
                        "pictures folder to use as the video's starting point."
                    ),
                },
            },
            "required": ["prompt"],
        },
        server=SERVER_NAME,
    )


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
    """Makes the video and reports what happened. The arguments are the
    drawing tool's own (``bild_werkzeug.ausfuehren``): the service's API
    root and session key, the chat and its answer or the job, the tool this
    run hands files on with, the run's stop signal, and the picture to
    start from, already checked against the folders this run may read."""
    prompt = str(argumente.get("prompt") or "").strip()
    if not prompt:
        raise bild_werkzeug.BildWerkzeugFehler("draw_video needs a prompt.")
    negative = str(argumente.get("negative_prompt") or "").strip()
    # English from the route, as for a picture: the model reads its refusals.
    headers = {"X-Sitzungsschluessel": schluessel, "X-Ui-Language": "en"}
    in_chat = bool(chat_id and antwort_id)
    try:
        # No time limit: a video ends by itself or with the run's stop.
        async with httpx.AsyncClient(timeout=None, headers=headers) as client:
            made = await _make(
                client, basis, prompt, negative, chat_id, job_id,
                antwort_id if in_chat else None, abbruch, input_picture,
            )
    except (httpx.HTTPError, httpx.InvalidURL) as error:
        return f"The video could not be generated: {str(error) or type(error).__name__}"
    if isinstance(made, str):
        return made
    model, body, name = made
    path = bilderordner / name
    used = [f"model {model}"]
    if body.get("breite") and body.get("hoehe"):
        used.append(f"{body['breite']}×{body['hoehe']} pixels")
    if body.get("video_frames"):
        used.append(f"{body['video_frames']} frames")
    if input_picture is not None:
        used.append(f"based on {input_picture.name}")
    if not in_chat:
        sentence = (
            f"The video was generated ({', '.join(used)}) and saved as {path} in the pictures "
            "folder, visible to the user under Images. It is not attached to your report."
        )
        if deliver_with:
            sentence += (
                " If this video is a deliverable for the user, deliver it using "
                f"{deliver_with} with this path."
            )
        return sentence
    return (
        f"The video was generated ({', '.join(used)}), attached to this response, and saved as "
        f"{path}."
    )


def _whole_number(value: Any) -> int | None:
    """A count the window stored — it keeps what was typed, so a number may
    stand there as text. None for anything that is no count of at least one."""
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if number >= 1 else None


def _refused(answer: httpx.Response, body: dict[str, Any] | None) -> str:
    """What the model reads when a call on the way to the video failed: the
    route's own sentence, as it wrote it."""
    return bild_werkzeug._nicht_gezeichnet(answer, body, VIDEO)


async def _make(
    client: httpx.AsyncClient,
    basis: str,
    prompt: str,
    negative: str,
    chat_id: str | None,
    job_id: str | None,
    antwort_id: str | None,
    abbruch: asyncio.Event | None,
    input_picture: Path | None,
) -> tuple[str, dict[str, Any], str] | str:
    """Every call on the way to the video. Returns the model, the request
    and the file's name — or the sentence the model reads when no video
    came."""
    listed = await client.get(f"{basis}/bild/modelle")
    state = bild_werkzeug._json_object(listed)
    if listed.status_code >= 400:
        return _refused(listed, state)
    if (
        state is None
        or bild_werkzeug._wrong_kind(
            state, {"programm_da": bool, "modelle": list, "families": dict}
        )
        or not bild_werkzeug._all_text(state.get("modelle") or [])
        or not bild_werkzeug._all_text((state.get("families") or {}).values())
    ):
        return UNUSABLE_ANSWER
    if not state.get("programm_da"):
        return (
            "No image generator is installed. The user can download it from the plus menu "
            "under Images."
        )
    families = state.get("families") or {}
    video_models = [
        name for name in state.get("modelle") or []
        if (entry := image_families.get(families.get(name))) is not None and entry.video
    ]
    if not video_models:
        return NO_VIDEO_MODEL
    if chat_id is None and job_id:
        chat_id, refusal = await bild_werkzeug._chat_of_job(client, basis, job_id, VIDEO)
        if refusal is not None:
            return refusal
    window, refusal = await bild_werkzeug._window_of_chat(client, basis, chat_id, VIDEO)
    if refusal is not None:
        return refusal
    # The model: the one the chat's picture window stands at when that is a
    # video model; else the one video model there is. Among several, nothing
    # chooses by itself.
    standing = window.get("modell")
    if isinstance(standing, str) and standing in video_models:
        model = standing
    elif len(video_models) == 1:
        model = video_models[0]
    else:
        return MODEL_NOT_CHOSEN
    family = image_families.get(families.get(model))
    assert family is not None  # a video model has a family
    # What the family can start from: words, or a first frame.
    if input_picture is None and "t2v" not in family.tasks:
        return (
            f"The video was not generated: the selected model, {family.label}, requires an "
            "input image. Pass its path as image."
        )
    if input_picture is not None and "i2v" not in family.tasks:
        return (
            f"The video was not generated: the selected model, {family.label}, accepts text "
            "input only. Call again without an image."
        )
    answer = await client.get(f"{basis}/bild/vorgaben", params={"modell": model})
    start = bild_werkzeug._json_object(answer)
    if answer.status_code >= 400:
        return _refused(answer, start)
    if start is None:
        return UNUSABLE_ANSWER
    body: dict[str, Any] = {
        name: start[name] for name in _START_FIELDS if start.get(name) not in (None, "", {})
    }
    if model == standing:
        # The window stands at this very model: its own values are the
        # person's, and win over the model's start — the video's length and
        # rate among them. A video model the window does not stand at runs
        # on its family's start alone, never on the size, steps or guidance
        # of the picture model the window holds.
        body.update(bildfensterwahl.draw_request(window))
        for name in ("video_frames", "fps"):
            count = _whole_number(window.get(name))
            if count is not None:
                body[name] = count
    body.update({"modell": model, "familie": family.name, "video": True, "prompt": prompt})
    if negative:
        body["negativ"] = negative
    if input_picture is not None:
        handed_in, refusal = await bild_werkzeug._hand_in(client, basis, input_picture, VIDEO)
        if handed_in is None:
            return refusal
        body["startbild"] = handed_in
    if antwort_id:
        # Into the run of the answer being written, like a drawn picture.
        body["chat_id"] = chat_id
        body["lauf_kennung"] = antwort_id
    if abbruch is not None and abbruch.is_set():
        return "The video was not generated because the run was stopped."
    log.info("draw_video: making a video with %s", model)
    made = await bild_werkzeug._bild_anfordern(client, basis, body, abbruch)
    data = bild_werkzeug._json_object(made)
    if made.status_code >= 400:
        return _refused(made, data)
    name = (data or {}).get("bild")
    if not isinstance(name, str) or not name or Path(name).name != name:
        return UNUSABLE_ANSWER
    return model, body, name
