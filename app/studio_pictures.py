"""The pictures the picture studio drew, newest first.

The studio belongs to no chat: what it draws is made and named and lies
once in the pictures folder, and no message names it. This list is the one
place that says which of the pictures in that folder the studio drew — the
studio's row of pictures shows exactly these (``GET /bilder?studio=true``).

It is kept under one key in the global scope, as names only, and written by
the draw route alone when a request that says it is the studio's has
finished (app/api/v1/bild.py). A name that is no longer in the pictures
folder drops out of what is shown, not out of the list: the file may come
back, and nothing here deletes anything.
"""

from __future__ import annotations

from typing import Any

from app.bildfensterwahl import BILDNAME
from app.db.repositories.einstellungen import GLOBAL

KEY = "studio_pictures"


def names(repositories) -> list[str]:
    """The names, newest first. A stored value that is no list of picture
    names holds nothing."""
    stored: Any = repositories.einstellungen.holen(GLOBAL, KEY)
    if not isinstance(stored, list):
        return []
    return [name for name in stored if isinstance(name, str) and BILDNAME.fullmatch(name)]


def add(repositories, name: str) -> None:
    """A finished picture of the studio goes to the front. The same picture
    drawn again is the same file: it moves to the front, it is not listed
    twice."""
    if not BILDNAME.fullmatch(name):
        return
    kept = [other for other in names(repositories) if other != name]
    repositories.einstellungen.setzen(GLOBAL, KEY, [name, *kept])
