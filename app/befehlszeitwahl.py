"""How long one shell command may run — resolved from the settings cascade.

The limit used to be a constant baked into the code
(``app/tools/shell.py``): 120 seconds for every command, every chat, every
job, with no way around it short of editing the source. A model download
dies against that wall, and the background escape hatch is not always
available. A restraint nobody can loosen is not a guide value, it is a lock.

So the limit is a setting like any other. It travels the same cascade the
tool rounds already do (``app/werkzeugrundenwahl.py``) — a global number by
default, overridable per model or per chat — and a job's agent head may
override it outright with ``max_command_seconds``, the same way the token
budget already works (``app/auftragtokenwahl.py``): the head is the most
specific layer a job has.

The value is checked, not trusted: a whole number of at least one second.
There is no upper bound on purpose — whoever sets an hour means an hour,
and the place to stop a runaway command is the stop button, not a ceiling
nobody can reach past.
"""

from __future__ import annotations

from typing import Any

from app import einstellungswahl
from app.tools.shell import ZEITGRENZE_SEKUNDEN

SCHLUESSEL = "befehl_zeitgrenze"

# What ships before anyone changes it: the same 120 seconds the code always
# had. Imported, not repeated — whoever does not touch the setting must get
# exactly the old behaviour, and one number in two places drifts apart.
VORGABE = ZEITGRENZE_SEKUNDEN


def wahl_pruefen(wert: Any) -> int | None:
    """``befehl_zeitgrenze``: a whole number of at least one, or nothing.

    Anything that is not a usable second count — a string, a fraction, zero,
    a negative — counts as unset and steps aside for the scope above. A
    ``bool`` is refused explicitly: in Python it would pass
    ``isinstance(_, int)`` and silently mean 1 or 0, which nobody typed.
    """
    return einstellungswahl.ganze_zahl_ab_eins(wert)


def sekunden(
    repositories,
    *,
    modell: str | None = None,
    chat: str | None = None,
    agent_wert: int | None = None,
) -> int:
    """The time limit that applies here, in seconds.

    ``agent_wert`` is what the agent head says (``max_command_seconds``); if
    it names a usable number it wins outright. Otherwise the most specific
    scope that set the value applies, and :data:`VORGABE` is what is left
    when no scope has anything to say — so a fresh install behaves exactly
    as before this setting existed.
    """
    aus_agent = wahl_pruefen(agent_wert)
    if aus_agent is not None:
        return aus_agent
    return einstellungswahl.aufgeloest(
        repositories, SCHLUESSEL, wahl_pruefen, VORGABE, modell=modell, chat=chat
    )
