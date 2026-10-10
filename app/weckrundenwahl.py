"""How often a chat may carry itself on without the user — from the cascade.

A finished background command now starts a new answer in its chat
(``app/hintergrundwecken.py``). That is what lets a piece of work run
through the night; it is also a loop waiting to happen. The model starts a
run, is woken, starts the next, is woken — and by morning the context is
full and nobody was awake to see it happen.

So the wakes are counted, and the count is a setting like any other. It
travels the same cascade the tool rounds do (``app/werkzeugrundenwahl.py``)
— a global number by default, overridable per model or per chat. What it
counts is wakes WITHOUT the user: their next message sets it back to zero.

The value is checked, not trusted: a whole number of at least one, exactly
like the round limit next door.

Zero — "never wake me on my own" — is deliberately NOT a value, however
much it sounds like one. The settings route reads every checked value that
is falsy as "nothing was set" (``app/api/v1/einstellungen.py``: ``if not
wert: wert = None``), so a stored zero would come straight back as the
default and the switch would lie about being off. One is the floor that can
be said honestly: one wake per turn, and then the chat waits for its user.
"""

from __future__ import annotations

from typing import Any

from app import einstellungswahl

SCHLUESSEL = "weck_runden"

# What ships before anyone changes it. Enough for a night of work: one cycle
# is a command plus the answer that reads its result, so at five minutes a
# cycle fifty of them are four hours, at ten minutes eight. Below about
# twenty the chat would stop in the middle of the night for no reason other
# than the number.
#
# It is also what a runaway costs before it is caught: fifty answers is a
# surprise in the morning, not a bill. A ceiling that lets the thing loop
# for ever would make the counter decorative.
VORGABE = 50


def wahl_pruefen(wert: Any) -> int | None:
    """``weck_runden``: a whole number of at least one, or nothing.

    Anything that is not a usable count — a string, a fraction, zero, a
    negative — counts as unset and steps aside for the scope above. A
    ``bool`` is refused explicitly: in Python it would pass
    ``isinstance(_, int)`` and silently mean 1 or 0, which nobody typed.
    """
    return einstellungswahl.ganze_zahl_ab_eins(wert)


def runden(repositories, *, modell: str | None = None,
           chat: str | None = None) -> int:
    """How many wakes this chat still gets — the most specific scope that set it.

    Falls back to :data:`VORGABE` when no scope has a value, so a fresh
    install carries a chat through the night without anyone opening the
    settings.
    """
    return einstellungswahl.aufgeloest(
        repositories, SCHLUESSEL, wahl_pruefen, VORGABE, modell=modell, chat=chat
    )
