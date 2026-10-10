"""How long a job's model may think first — resolved like its answer budget.

The twin of ``app/auftragtokenwahl.py``, and deliberately a second file
rather than a second branch inside that one: they answer two different
questions (how long may it think, how long may the answer be) and the day one
of them grows a rule of its own, a shared function would have to be told
which of the two it is resolving.

Same order, same reasons: the agent head wins outright when it names a usable
number, otherwise the settings cascade a chat reads (``global`` -> the
model's own setting) applies. There is no app-wide default: an unset thinking
length means nothing is sent at all and the server keeps its own habit, which
is exactly what every model did before this knob existed.

Zero is a real value here, not "unset" — llama.cpp reads a budget of zero as
"stop thinking immediately", and somebody who typed it meant it. Minus one is
Auto, as in a chat (``app/parameter.py``): no artificial cap, ``unrestricted``
on llama.cpp. Both are sent, never dropped.
"""

from __future__ import annotations

from typing import Any

from app.parameter import NACH_NAME, NAME_DENKLAENGE

SCHLUESSEL = NAME_DENKLAENGE

# The floor and ceiling of the thinking-length knob, read from the knob itself
# (app/parameter.py), so the two numbers are written down once. The agent head
# reaches this module without passing that file's clamp.
_KNOPF = NACH_NAME[SCHLUESSEL]
AUTO = int(_KNOPF.minimum)
OBERGRENZE = int(_KNOPF.maximum)


def wahl_pruefen(wert: Any) -> int | None:
    """A whole number between :data:`AUTO` and :data:`OBERGRENZE`, or nothing.

    A ``bool`` is refused explicitly: in Python it would pass
    ``isinstance(_, int)`` and silently mean 1 or 0, which nobody typed.
    """
    if isinstance(wert, bool) or not isinstance(wert, int):
        return None
    if not (AUTO <= wert <= OBERGRENZE):
        return None
    return wert


def aufgeloest(repositories, *, modell: str | None, agent_wert: int | None) -> int | None:
    """The thinking budget for one job run, or nothing at all.

    ``None`` means: send no field. That is not the same as zero, which is a
    stated wish for no thinking — the difference is the whole point of the
    knob being allowed to stay untouched.
    """
    aus_agent = wahl_pruefen(agent_wert)
    if aus_agent is not None:
        return aus_agent
    eingestellt = repositories.einstellungen.zusammengefuehrt("parameter", modell=modell)
    return wahl_pruefen(eingestellt.get(SCHLUESSEL))
