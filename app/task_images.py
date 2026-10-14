"""Pictures a chat hands to the agent it sends off with ``start_job``.

The agent never saw the conversation, and a picture is the one part of it a
task text cannot carry: "the layout in the screenshot" means nothing to a run
that was never shown the screenshot. So the call may name up to eight
pictures, and they travel in the run's first message.

Three ways to name a picture, each with its own path:

* **A local path** — read here, in the same one place ``read_file`` reads a
  picture with (metadata off, a smaller copy where it is large), and sent as
  a picture. Only a file inside the folders the agent's run gets, so the
  path the agent is told is one it can read itself, and only where the
  permission check lets ``read_file`` read it without asking
  (``may_read``): a "no" rule, a "never" rule or a mode that asks stops the
  picture as it would stop the read. Only a real picture is read, decided
  the way ``read_file`` decides it — its extension, then the signature in
  its first bytes — before the file itself is opened. A path that is
  outside, refused, missing or no picture is skipped; the rest still travel.
* **A ``data:image/…`` URL** — the picture itself, sent as it is.
* **An ``http(s)`` URL** — named, never fetched: every provider of this
  house is handed pictures as data URLs, and fetching a page the model named
  would be a request out of the house nobody asked for. The agent reads the
  line and can fetch it with its own tools.

A model that cannot see gets a line per picture instead, so it knows there
is one and where: ``[Image attached at: <path>]`` for a file,
``[Image attached: <url>]`` for an address. A data URL has no place to name
and is left out for it. A picture whose payload is still above the vision
payload ceiling after the smaller copy is made is not attached for any
model; a sentence says which one and why. Whatever goes wrong on the way
leaves the task as plain text: a broken picture must not keep the agent
from starting.
"""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

# The largest picture payload handed on, as the data URL that travels — no
# major provider takes a larger one. A picture still above it after the
# smaller copy is made is not attached; the model is told so instead
# (:func:`for_model`).
MAX_PAYLOAD_BYTES = 20 * 1024 * 1024

# The most pictures one call may hand over.
MAX_IMAGES = 8

_DATA_PREFIXES = ("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,")


class TaskImagesInvalid(ValueError):
    """The ``images`` field cannot be read; the reason says why."""


@dataclasses.dataclass(frozen=True)
class TaskImage:
    """One picture as named, and — where it can be sent — its data URL."""

    source: str
    kind: str  # "path", "url" or "data"
    data_url: str | None = None
    # Still above MAX_PAYLOAD_BYTES after the smaller copy: not sent, named.
    too_large: bool = False
    # Its place in ``images`` as the call gave them, counted from 1 — what
    # a sentence about it names, whatever was skipped before it.
    position: int = 0


def _capped(image: TaskImage) -> TaskImage:
    """``image`` as it may travel: one whose payload is above the ceiling
    loses its data URL and is marked, so the model hears why it is missing."""
    if image.data_url is not None and len(image.data_url) > MAX_PAYLOAD_BYTES:
        log.info("A picture for a job is not attached: its payload is above the ceiling")
        return dataclasses.replace(image, data_url=None, too_large=True)
    return image


def _too_large_sentence(image: TaskImage, number: int) -> str:
    """What the model reads for a picture that was not attached for its
    size: which one, that it is missing, and what to do about it."""
    ceiling = MAX_PAYLOAD_BYTES // (1024 * 1024)
    if image.kind == "data":
        # A data URL travels as it was given; nothing made it smaller.
        return (
            f"[Inline image number {number} was not attached because it exceeds the model's "
            f"limit of {ceiling} MB. Work without it, or ask for a smaller copy if the task "
            "requires it.]"
        )
    return (
        f"[The image at {image.source} was not attached because it still exceeds the model's "
        f"limit of {ceiling} MB after resizing. Work without it, or ask for a smaller copy if "
        "the task requires it.]"
    )


def checked(raw: Any) -> list[str]:
    """The ``images`` field as a list of names, or a refusal the model can
    act on. Missing or empty is no pictures."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise TaskImagesInvalid("images must be a list of file paths or image URLs.")
    names = [item.strip() for item in raw if item.strip()]
    if len(names) > MAX_IMAGES:
        raise TaskImagesInvalid(
            f"A job accepts at most {MAX_IMAGES} images; {len(names)} were provided."
        )
    return names


def _kind(name: str) -> str:
    lowered = name.lower()
    if lowered.startswith("data:"):
        return "data"
    if lowered.startswith(("http://", "https://")):
        return "url"
    return "path"


def _local(
    name: str, folders: list[str], data_dir, may_read: Callable[[str], bool]
) -> TaskImage | None:
    """The picture behind a local path, or None where it is not to be read."""
    from app.api.v1.bilder import ANZEIGBARE_ENDUNGEN
    from app.tools import grenzen
    from app.tools.datei_lesen import _bild_bereiten, medientyp_aus_pfad

    if not folders:
        return None
    roots = grenzen.wurzeln(folders)
    path = grenzen.aufgeloest(name, roots[0])
    if not any(grenzen.inside(path, root) for root in roots) or not path.is_file():
        log.info("A picture for a job is skipped: not a file in the run's folders")
        return None
    if not may_read(str(path)):
        log.info("A picture for a job is skipped: the permission check refuses reading it")
        return None
    # A picture by extension and by signature, as read_file decides it —
    # checked on the few bytes a signature needs, before the whole file is.
    if (
        path.suffix.lower() not in ANZEIGBARE_ENDUNGEN
        or medientyp_aus_pfad(str(path)) is None
    ):
        log.info("A picture for a job is skipped: not a png, jpeg or webp file")
        return None
    data_url, _size = _bild_bereiten(Path(path), data_dir)
    return _capped(TaskImage(source=str(path), kind="path", data_url=data_url))


def prepare(
    names: list[str], folders: list[str], data_dir, may_read: Callable[[str], bool]
) -> list[TaskImage]:
    """Reads what is to be read. Blocking — reads files and may make a
    smaller copy — so a caller on the event loop runs it in a thread.

    ``folders`` are the folders the agent's run gets; ``may_read`` answers
    whether the permission check lets ``read_file`` read a path there.

    A picture that cannot be read is skipped on its own, and anything
    unexpected leaves no pictures at all rather than no job."""
    from app.tools import grenzen

    try:
        images: list[TaskImage] = []
        for position, name in enumerate(names, start=1):
            kind = _kind(name)
            if kind == "data":
                if name.startswith(_DATA_PREFIXES):
                    images.append(_capped(
                        TaskImage(source=name, kind="data", data_url=name, position=position)
                    ))
                else:
                    log.info("A picture for a job is skipped: not a png, jpeg or webp data URL")
                continue
            if kind == "url":
                images.append(TaskImage(source=name, kind="url", position=position))
                continue
            try:
                image = _local(name, folders, data_dir, may_read)
            except (OSError, RuntimeError, ValueError, MemoryError, grenzen.GrenzeVerletzt):
                log.info("A picture for a job is skipped: it could not be read")
                image = None
            if image is not None:
                images.append(dataclasses.replace(image, position=position))
        return images
    except Exception:  # noqa: BLE001 - a picture must never keep the job from starting
        log.warning("The pictures for a job could not be prepared", exc_info=True)
        return []


def for_model(images: list[TaskImage], vision: bool) -> tuple[list[str], list[str]]:
    """What the run's first message carries: the pictures it sends, and the
    lines it adds to the task."""
    urls: list[str] = []
    lines: list[str] = []
    for image in images:
        if image.too_large:
            lines.append(_too_large_sentence(image, image.position))
        elif image.kind == "url":
            lines.append(f"[Image attached: {image.source}]")
        elif vision and image.data_url:
            urls.append(image.data_url)
        elif image.kind == "path":
            lines.append(f"[Image attached at: {image.source}]")
    return urls, lines
