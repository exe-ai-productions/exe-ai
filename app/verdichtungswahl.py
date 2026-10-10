"""At what share of the context a chat compacts itself — from the settings
cascade.

Compaction folds the settled middle of a conversation into one summary so
the rest keeps fitting (``app/verdichtung.py``). WHEN that should happen is
not a property of the program, it is a property of the work: a chat of short
questions can run most of the way full before folding anything is worth the
request it costs, while one that reads large files wants the room long
before that. A number baked into the code has to be wrong for one of them.

So it travels the same cascade as the rest — a global default, overridable
per model or per chat — exactly like ``app/werkzeugrundenwahl.py`` does for
the tool-round limit, and for the same reason: that one was a hard ten in
the source until a task across fifty files ran into it with no way past
short of editing the file.

The emergency handoff at 90% (``app/zwischenstand.py``) is deliberately NOT
part of this. That one is not a preference, it is the last moment at which a
run can still ask for a status report and have it fit; a setting that could
be pushed above it would be a setting that can break the thing it configures.
"""

from __future__ import annotations

from typing import Any

from app import einstellungswahl

SCHLUESSEL = "verdichtung_schwelle"

# Where it stands before anyone changes it.
#
# Fifty came from the job path, and in a chat it fires far too early — every
# firing is a summarizing request of its own, paid for a saving nobody
# needed yet. Anthropic's own server-side compaction, for comparison,
# defaults to 150,000 input tokens.
#
# Eighty is late enough that a chat runs a long way before paying anything,
# and early enough that the summarizing request and the round that triggered
# the check both still fit under the 90% at which the emergency handoff
# takes over.
VORGABE = 80.0

# One, not five.
#
# Five was a judgement about what is sensible, and it made the field lie:
# the number box below cannot say "zero OR five to eighty-five" — zero is
# how it says "default" — so a typed 3 was shown, sent, refused with a
# plain 200 and silently forgotten, and the threshold stayed at 80. A
# setting that shows one number and obeys another is worse than a setting
# that lets somebody pick a silly one.
#
# The ceiling is a different matter and stays: at or above the handoff's own
# threshold the setting would be reaching past the safety net it sits under.
KLEINSTE = 1.0
GROESSTE = 85.0


def wahl_pruefen(wert: Any) -> float | None:
    """A usable share, or nothing.

    Anything outside the band counts as unset and steps aside for the scope
    above rather than being clamped: a number somebody typed and a number
    this module invented from it are different things, and only the first
    should decide anything. A ``bool`` is refused explicitly — in Python it
    passes ``isinstance(_, int)`` and would silently mean 1 or 0.
    """
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return None
    anteil = float(wert)
    if not KLEINSTE <= anteil <= GROESSTE:
        return None
    return anteil


def schwelle(repositories, *, modell: str | None = None,
             chat: str | None = None) -> float:
    """The threshold that applies here — the most specific scope that set it.

    Falls back to :data:`VORGABE` when no scope has a value, so an install
    that never opens the settings behaves exactly as it did before this
    module existed.
    """
    return einstellungswahl.aufgeloest(
        repositories, SCHLUESSEL, wahl_pruefen, VORGABE, modell=modell, chat=chat
    )
