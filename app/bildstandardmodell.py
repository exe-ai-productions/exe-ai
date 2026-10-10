"""The picture model every chat draws with until it chooses its own.

Chosen once in the picture server and kept for every chat: a chat whose
picture window names no model, the drawing tool outside a chat and the
server's start by hand all draw with it. Nothing picks it by itself — the
first file of the folder is no choice anybody made — so without it, or
when its file left the folder, nothing is drawn, and the answer says where
it is chosen.
"""

from __future__ import annotations

from typing import Any

SCHLUESSEL = "bild_standardmodell"

# A file name in the picture folder, never a path.
NAME_MAX = 255


def pruefen(wert: Any) -> str:
    """A file name, or empty: none chosen."""
    if not isinstance(wert, str) or len(wert) > NAME_MAX:
        return ""
    if "/" in wert or "\\" in wert or wert in (".", ".."):
        return ""
    return wert


def lesen(repositories, modelle: list[str]) -> str:
    """The chosen model while it is in the folder, or empty."""
    name = pruefen(repositories.einstellungen.zusammengefuehrt(SCHLUESSEL, vorgabe=""))
    return name if name in modelle else ""
