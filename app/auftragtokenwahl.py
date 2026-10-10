"""How many tokens a job's answer may use — resolved like a chat's, plus the
agent head on top.

A job used to take one shipped number with no way around it, while a chat has
long resolved the same value through the settings cascade
(``global -> modell:<id> -> chat:<id>``, see
``app/db/repositories/einstellungen.py``). A thinking model splits that
budget between its reasoning and its actual answer; a report cut off mid-word
is what a limit too small for that looks like.

Jobs travel the same cascade a chat does — global, then the model's own
setting — but have no scope of their own (a job is one run, not a
conversation to keep tuning). The agent head is what stands in for that: the
most specific layer a job has, and the only thing allowed to override the
cascade's answer.

Nothing set anywhere answers ``None``, which is not a missing value but a
stated one: "Auto". What that resolves to is worked out per request against
the model's window (``app/antwortgrenze.py``), not here.

The value is checked, not trusted, the same way ``app/werkzeugrundenwahl.py``
checks a round count: a whole number of at least one. Anything else counts as
unset and the layer below it applies instead.
"""

from __future__ import annotations

from typing import Any

from app import einstellungswahl

SCHLUESSEL = "max_tokens"

# Same ceiling the chat request schema enforces on a request body
# (app/api/v1/schemas.py, max_tokens: ... le=1_000_000). The cascade branch
# below travels app/parameter.py's own clamp first (256 to 1,000,000, applied
# in `pruefen()`) on whatever gets saved to a settings row, and an empty field
# means "Auto" rather than a number — this ceiling is what actually stands
# between the agent head, which reaches here unfiltered by that clamp, and an
# unbounded number.
OBERGRENZE = 1_000_000


def wahl_pruefen(wert: Any) -> int | None:
    """``max_tokens``: a whole number between one and :data:`OBERGRENZE`, or
    nothing.

    A ``bool`` is refused explicitly: in Python it would pass
    ``isinstance(_, int)`` and silently mean 1 or 0, which nobody typed.
    """
    zahl = einstellungswahl.ganze_zahl_ab_eins(wert)
    if zahl is None or zahl > OBERGRENZE:
        return None
    return zahl


def aufgeloest(
    repositories,
    *,
    modell: str | None,
    agent_wert: int | None,
) -> int | None:
    """The token budget for one job run, or ``None`` for "Auto".

    Resolution order: the agent head, if it names a usable number, wins
    outright — it is the most specific layer a job has. Otherwise the same
    cascade a chat reads (``global`` -> the model's own setting) applies.
    ``None`` where neither has anything to say: nothing is set, so the
    request works out the largest ceiling that fits
    (``app/antwortgrenze.py``).

    Deliberately checking the extracted value itself, not the merged
    settings object's truthiness: ``zusammengefuehrt()`` returns an empty
    dict when nothing is set anywhere, and a dict that merely lacks this one
    key is just as ordinary — neither case may be mistaken for "unset" by
    testing the whole object instead of the key.
    """
    aus_agent = wahl_pruefen(agent_wert)
    if aus_agent is not None:
        return aus_agent
    # Scope by scope, most specific first, like every other reader of the
    # cascade: a model value the check refuses steps aside for the global
    # one, instead of hiding it behind the merged result. The number lives
    # inside each scope's `parameter` set, so the check reads it out of the
    # set the scope holds.
    def aus_dem_satz(satz: Any) -> int | None:
        return wahl_pruefen(satz.get(SCHLUESSEL)) if isinstance(satz, dict) else None

    return einstellungswahl.aufgeloest(
        repositories, "parameter", aus_dem_satz, None, modell=modell
    )
