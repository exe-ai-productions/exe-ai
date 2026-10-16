"""The picture styles: named templates a prompt is drawn through.

A style has a name, a text and a negative. The text carries ``{prompt}``
where the prompt goes; a text without it is added after the prompt. The
negative is added after the picture's own negative. The styles are one global
setting; which one the picture studio draws with is its own choice
(``stil`` in app/bildfensterwahl.py).

A style also has an id that never changes. The studio keeps its choice by
that id, so a style given a new name is still the style it draws through.
A choice made before styles had ids keeps the name instead, and finds its
style for as long as the style is called that.

Its own module for the same reason every stored setting has one: the
settings route only writes what somebody vouches for.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

SCHLUESSEL = "bildstile"

PLATZHALTER = "{prompt}"


_ID = re.compile(r"[0-9a-f]{32}")
# The ids of styles that were stored without one grow from their names.
_ID_SPACE = uuid.UUID("6f0b6f5e-5d0c-4d0e-9a57-3c2b1d9e7a41")


def _own_id(given: Any, taken: set[str]) -> str | None:
    """The id a style brings, while it has the right shape and no style
    before it carries it."""
    if isinstance(given, str) and _ID.fullmatch(given) and given not in taken:
        return given
    return None


def _new_id(name: str, taken: set[str]) -> str:
    """The id for a style that came without one — it was stored before
    styles had ids: grown from its name, so two windows that both write the
    old list give the same style the same id. A grown id that a style of the
    list carries already gives way to a fresh one."""
    grown = uuid.uuid5(_ID_SPACE, name).hex
    return grown if grown not in taken else uuid.uuid4().hex


def wahl_pruefen(wert: Any) -> list[dict[str, str]] | None:
    """Keeps every style with a name, once per name; ``None`` deletes the
    entry. Text and negative are kept as written, and every style leaves
    with an id of its own."""
    if not isinstance(wert, list):
        return None
    sauber: list[dict[str, str]] = []
    namen: set[str] = set()
    ids: set[str] = set()
    for eintrag in wert:
        if not isinstance(eintrag, dict):
            continue
        name = eintrag.get("name")
        if not isinstance(name, str) or not name.strip() or name.strip() in namen:
            continue
        namen.add(name.strip())
        own = _own_id(eintrag.get("id"), ids)
        if own:
            ids.add(own)
        sauber.append({
            "id": own or "",
            "name": name.strip(),
            "text": eintrag["text"] if isinstance(eintrag.get("text"), str) else "",
            "negativ": eintrag["negativ"] if isinstance(eintrag.get("negativ"), str) else "",
        })
    # The ids the styles brought are all known by now: a style without one
    # cannot be given the id another style of the list carries, wherever in
    # the list the two stand.
    for style in sauber:
        if not style["id"]:
            style["id"] = _new_id(style["name"], ids)
            ids.add(style["id"])
    return sauber


def name_of(styles: Any, chosen: Any) -> str:
    """The name of the style a chat's choice stands for, "" when there is
    none: the style with that id, else — for a choice made before styles had
    ids — the style called that."""
    if not isinstance(chosen, str) or not chosen or not isinstance(styles, list):
        return ""
    entries = [entry for entry in styles if isinstance(entry, dict)]
    for key in ("id", "name"):
        for entry in entries:
            if entry.get(key) == chosen and isinstance(entry.get("name"), str):
                return entry["name"]
    return ""


def _zusammen(vorne: str, hinten: str) -> str:
    vorne, hinten = vorne.strip(), hinten.strip()
    if not vorne or not hinten:
        return vorne or hinten
    return f"{vorne}, {hinten}"


def anwenden(prompt: str, negativ: str, text: str, stil_negativ: str) -> tuple[str, str]:
    """The prompt and negative a style turns these into.

    ``{prompt}`` in the style's text stands for the prompt, every time it
    occurs; a text without it follows the prompt. The style's negative
    follows the picture's own. An empty style changes nothing.
    """
    if PLATZHALTER in text:
        prompt = text.replace(PLATZHALTER, prompt.strip()).strip()
    else:
        prompt = _zusammen(prompt, text)
    return prompt, _zusammen(negativ, stil_negativ)
