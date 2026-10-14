"""The version a file had before it is written over, set beside it.

A save replaces the whole file, and a file the program could not show — one
whose bytes are no text, or that the page opened empty — would be replaced by
what the page then sends. The previous version is copied beside it as
``<name>.vorher``, byte for byte, before anything is written; every save
replaces the one copy that is there. The configuration files and the agent
files take this one way, so the name and the manner are the same for both.

The copy is made under a side name and takes its name in one step
(``app/atomic_file.py``): a copy that breaks off halfway leaves the older copy
whole, and a copy that was made read-only — as the file it was taken from may
have been — is still replaced by the next one.

A copy that cannot be made is an ``OSError`` for the caller to answer: nothing
is written without it.
"""

from __future__ import annotations

import shutil
from contextlib import suppress
from pathlib import Path

from app import atomic_file

SUFFIX = ".vorher"


def set_beside(path: Path) -> None:
    """Copies ``path`` to ``<path>.vorher`` where ``path`` is there; nothing
    otherwise — a first save has no previous version."""
    if not path.exists():
        return
    target = path.with_suffix(path.suffix + SUFFIX)
    side = target.with_name(atomic_file.side_file_name(target.name))
    try:
        shutil.copy2(path, side)
        atomic_file.rename_onto(side, target)
    except BaseException:
        with suppress(OSError):
            side.unlink()
        raise
