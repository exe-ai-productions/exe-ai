"""How many tool rounds one answer may run — resolved from the settings cascade.

A tool round is one pass of "the model asks for a tool, we run it, the result
goes back". A task that reads fifty files needs fifty of them; a hard ceiling
baked into the code turned every such task into a dead end after ten, with no
way to lift it short of editing the source.

So the limit is a setting like any other. It travels the same cascade as the
rest — a global number by default, overridable per model or per chat — and the
agents keep their own ``max_rounds`` in the agent head, untouched by this.

The value is checked, not trusted: a whole number of at least one. There is no
upper bound on purpose. Someone who means a very long run means it, and the
place to stop a runaway is the model's own behaviour, not a number nobody can
reach past.
"""

from __future__ import annotations

from typing import Any

from app import einstellungswahl

SCHLUESSEL = "werkzeug_runden"

# What ships before anyone changes it. Far above the old hard ten, so a run
# across many files completes instead of being cut off, while still bounding a
# model that would otherwise circle forever.
VORGABE = 50


def wahl_pruefen(wert: Any) -> int | None:
    """``werkzeug_runden``: a whole number of at least one, or nothing.

    Anything that is not a usable count — a string, a fraction, zero, a
    negative — counts as unset and steps aside for the scope above. A ``bool``
    is refused explicitly: in Python it would pass ``isinstance(_, int)`` and
    silently mean 1 or 0, which nobody typed.
    """
    return einstellungswahl.ganze_zahl_ab_eins(wert)


def runden(repositories, *, modell: str | None = None,
           chat: str | None = None) -> int:
    """The round limit that applies here — the most specific scope that set it.

    Falls back to :data:`VORGABE` when no scope has a value, so a fresh install
    behaves sensibly without anyone opening the settings.
    """
    return einstellungswahl.aufgeloest(
        repositories, SCHLUESSEL, wahl_pruefen, VORGABE, modell=modell, chat=chat
    )
