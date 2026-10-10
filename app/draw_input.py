"""The pictures a draw starts from, no larger than the draw needs them.

Any picture may lie in the picture folder, at any size, and the painter
reads a starting picture whole before it makes it fit: one of 8000 pixels a
side is decoded into memory for a draw of 1024. So every picture a draw
reads — a starting, end, reference or control picture, a frame of a
reference video, a picture a switch names — goes to the painter as a
smaller copy when it is larger than the drawing on both sides. A mask goes
at the size its starting picture goes at.

The painter itself crops such a picture to the drawing's shape, around the
middle, and scales the rest onto the drawing size. The copy is therefore
scaled down only until the picture still covers the drawing: one side lands
on the drawing's, the other stays at least as long. What the painter crops
from is all there, and it never has to enlarge what was made smaller here.

The original is never written to. The copy lies among the studio's working
pictures, under a name made from the source's own size and time and the
drawing size, so the next draw from the same picture finds it instead of
making it again; that folder is emptied when the program starts.

Scaling uses the system's own tool (app/model_image.py). Where there is
none, where it fails, or where the file is no picture, the original goes
out: a draw from a large picture is worth more than no draw.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from pathlib import Path

from app import atomic_file
from app import model_image

log = logging.getLogger(__name__)


def covering_size(
    own_width: int, own_height: int, width: int, height: int
) -> tuple[int, int] | None:
    """The size a picture of ``own_width`` by ``own_height`` is scaled down
    to for a drawing of ``width`` by ``height`` — the smallest that still
    covers the drawing, ratio kept — or None where the picture is not larger
    than the drawing on both sides and stays as it is."""
    if own_width <= width or own_height <= height:
        return None
    if width * own_height >= height * own_width:
        # The width is the side that lands on the drawing's.
        return width, max(height, round(own_height * width / own_width))
    return max(width, round(own_width * height / own_height)), height


def fitted(picture: Path, width: int, height: int, folder: Path) -> Path:
    """The file the painter gets for ``picture`` in a drawing of ``width``
    by ``height``: the picture itself where it is small enough, otherwise
    its smaller copy in ``folder``."""
    return _smaller_copy(
        picture, folder, f"{width}x{height}",
        lambda own_width, own_height: covering_size(own_width, own_height, width, height),
    )


def fitted_like(mask: Path, picture: Path, folder: Path) -> Path:
    """The file the painter gets for the mask of a starting picture:
    ``mask`` at exactly the size ``picture`` — that starting picture as the
    painter gets it — has. A mask lies on its picture pixel for pixel, so it
    follows the picture's size and not a reckoning of its own. The mask
    itself where it is not larger than that on both sides, or where the
    picture cannot be measured."""
    if not model_image.verfuegbar():
        return mask
    try:
        width, height = model_image.masse(picture)
    except Exception as error:  # noqa: BLE001 — every one of them means "the original"
        log.warning("Mask %s goes to the painter whole: %s", mask.name, error)
        return mask
    if width is None or height is None:
        return mask
    return _smaller_copy(
        mask, folder, f"as-{width}x{height}",
        lambda own_width, own_height: (
            (width, height) if own_width > width and own_height > height else None
        ),
    )


def _smaller_copy(
    picture: Path, folder: Path, goal: str,
    size_for: Callable[[int, int], tuple[int, int] | None],
) -> Path:
    """``picture`` itself, or its copy in ``folder`` at the size ``size_for``
    names for the picture's own width and height; None from it means the
    picture stays as it is. ``goal`` is what the copy was made for, in its
    name, so a copy for one size is never taken for another."""
    try:
        own = picture.stat()
    except OSError:
        return picture
    copy = folder / f"{picture.stem}-{own.st_size}-{own.st_mtime_ns}-{goal}.png"
    if copy.is_file():
        return copy
    if not model_image.verfuegbar():
        return picture
    # Beside the goal and then renamed: a run that is stopped must not leave
    # a half-written file under the name the next draw would trust.
    part = folder / f"{copy.stem}-{uuid.uuid4().hex}-part.png"
    try:
        own_width, own_height = model_image.masse(picture)
        if own_width is None or own_height is None:
            return picture
        size = size_for(own_width, own_height)
        if size is None:
            return picture
        folder.mkdir(parents=True, exist_ok=True)
        if not model_image.scaled_copy(picture, part, *size) or not part.is_file():
            raise OSError("the copy was not written")
        atomic_file.rename_onto(part, copy)
        log.info(
            "Picture %s goes to the painter at %dx%d instead of %dx%d",
            picture.name, *size, own_width, own_height,
        )
        return copy
    except Exception as error:  # noqa: BLE001 — every one of them means "the original"
        part.unlink(missing_ok=True)
        log.warning("Picture %s goes to the painter whole: %s", picture.name, error)
        return picture
