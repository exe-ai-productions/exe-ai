"""What every setting resolved from the cascade does the same way.

A setting travels the cascade — a global number by default, overridable
per model or per chat — and comes back as whatever was stored: a number
somebody typed, a string a form sent, nothing at all. Five modules read
one such value each (tool rounds, wake rounds, command seconds, job
tokens, the compaction threshold), and every one of them had written the
same two steps by hand: check the value, fall back to the shipped default
where the check fails. Five copies of one routine is how the copy nobody
remembers keeps refusing what the others have learned to accept.

The two steps live here once. Each module keeps its own key, its own
default and its own idea of what a usable value is; what it no longer
keeps is the routine around them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


def ganze_zahl_ab_eins(wert: Any) -> int | None:
    """A whole number of at least one, or nothing.

    Anything that is not a usable count — a string, a fraction, zero, a
    negative — counts as unset and steps aside for the scope above. A
    ``bool`` is refused explicitly: in Python it would pass
    ``isinstance(_, int)`` and silently mean 1 or 0, which nobody typed.
    """
    if isinstance(wert, bool) or not isinstance(wert, int):
        return None
    if wert < 1:
        return None
    return wert


def aufgeloest(
    repositories,
    schluessel: str,
    pruefer: Callable[[Any], T | None],
    vorgabe: T,
    *,
    modell: str | None = None,
    chat: str | None = None,
) -> T:
    """The value that applies here — the most specific scope that set it,
    checked by ``pruefer``, and ``vorgabe`` where no scope has a usable one.

    So a fresh install behaves sensibly without anyone opening the
    settings, and a stored value the checker refuses is the same as no
    value: it steps aside — to the NEXT scope, not past it. Resolving the
    whole cascade first and checking the winner skipped every level in
    between: a chat value from an older build's wider band fell through
    to the shipped default while a perfectly good global value stood in
    the table. Each scope is asked in turn now, most specific first.
    """
    for bereich in reversed(
        list(repositories.einstellungen.kette(schluessel, modell=modell, chat=chat))
    ):
        geprueft = pruefer(repositories.einstellungen.holen(bereich, schluessel))
        if geprueft is not None:
            return geprueft
    return vorgabe
