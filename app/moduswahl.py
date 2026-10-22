"""Light, dark, and the five that are neither.

Its own module for the same reason the sound switch has one: the settings
route only writes what somebody vouches for, and a JSON column cannot vouch
for anything by itself.

Stored as an object rather than a bare string, like every other setting
here: the route reads a falsy value as "nothing set", and while no mode is
an empty string today, a one-key object keeps that from ever becoming the
difference between "auto" and "unset".

The list mirrors MODI in teile/SystemPrompt.svelte and teile/Erststart.svelte
— `auto` follows the system, the other six are chosen outright; `eigen`,
the own gradient, is never what `auto` resolves to.
"""

from __future__ import annotations

from typing import Any

SCHLUESSEL = "modus"

MODI = ("auto", "hell", "dunkel", "darkmatter", "heaven", "moune", "snow", "eigen")

# A fresh installation follows the device: Snow where the system is light, Exe
# where it is dark. The first picture of the interface (the stylesheet shows
# Auto where nothing is stored) and this answer agree, so the look does not
# change on the way up.
VORGABE: dict[str, Any] = {"modus": "auto"}


def wahl_pruefen(wert: Any) -> dict[str, Any] | None:
    """Keeps what is usable, drops the rest. ``None`` deletes the entry."""
    if not isinstance(wert, dict):
        return None
    if wert.get("modus") not in MODI:
        return None
    return {"modus": wert["modus"]}


def aufgeloest(wert: Any) -> dict[str, Any]:
    """The stored value with the default behind it."""
    return {**VORGABE, **(wahl_pruefen(wert) or {})}
