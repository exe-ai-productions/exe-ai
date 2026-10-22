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

Beside the list the studio keeps what each picture was drawn with, the
values the draw keeps for a picture in a chat (``_drawn_with`` of
app/api/v1/bild.py): one row of its own per picture, under its name, so a
new picture writes one row and no other. They are what the picture's infos
show (``GET /bild/info``) while the file carries none of its own.
"""

from __future__ import annotations

from typing import Any

from app.bildfensterwahl import BILDNAME
from app.db.repositories.einstellungen import GLOBAL

KEY = "studio_pictures"

# The scope of the per-picture rows. A fact about a picture, not a setting:
# outside the cascade, like the other scopes of that kind.
VALUES_SCOPE = "studio_picture_values"


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


def keep_drawn_with(repositories, name: str, values: dict) -> None:
    """The values a finished picture of the studio was drawn with, in a row
    of their own under its name. The same picture drawn again is the same
    file: its row is replaced. Nothing is written for an empty set."""
    if not BILDNAME.fullmatch(name) or not values:
        return
    repositories.einstellungen.setzen(VALUES_SCOPE, name, values)


def drawn_with(repositories, name: str) -> dict:
    """What the studio kept for this picture, or an empty answer for a name
    it never drew and for a row that holds no set of values."""
    if not BILDNAME.fullmatch(name):
        return {}
    stored: Any = repositories.einstellungen.holen(VALUES_SCOPE, name)
    return stored if isinstance(stored, dict) else {}
