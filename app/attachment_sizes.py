"""The size of the pictures a message carries, for the window to hold the
room before they load.

A bubble with a picture grew by the picture's height when the picture
arrived, and a chat opened afresh jumped under the reader's eyes. The window
needs width and height of each attached picture before it fetches it, so the
page of messages names them beside the file names.

Read from the file's header when the page is built, not stored with the
attachment: the attachment is a file name, a picture's size is a fact of that
file, and a size kept beside it would be a second copy to keep true. A file
the library does not read as a picture (a video, a file that is gone) has no
entry, and the window shows it as it always did.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from app import ordnerinhalt

# The EXIF tag for the orientation a camera recorded, and the values that
# turn the picture by a quarter: the browser shows such a picture turned, so
# its box is the other way round.
_ORIENTATION_TAG = 0x0112
_TURNED = frozenset({5, 6, 7, 8})


def of_file(path: Path) -> dict[str, int] | None:
    """Width and height of one picture file, or nothing where it is not one."""
    try:
        with Image.open(path) as picture:
            width, height = picture.size
            if picture.getexif().get(_ORIENTATION_TAG) in _TURNED:
                width, height = height, width
    except Exception:  # noqa: BLE001 — not a picture, whatever the reason
        return None
    if width < 1 or height < 1:
        return None
    return {"width": width, "height": height}


def of_names(folder: Path, names: list[str]) -> dict[str, dict[str, int]]:
    """Width and height by file name, for the names that are pictures."""
    sizes: dict[str, dict[str, int]] = {}
    for name in names:
        path = ordnerinhalt.sicherer_pfad(folder, name)
        size = of_file(path) if path is not None else None
        if size is not None:
            sizes[name] = size
    return sizes
