"""Who writes the picture prompts, and with which instruction per family.

The picture server's "Prompt preparation" block holds two things:

  * ``verbesserer`` — the server that writes the prompt: the agent server,
    the model server, the clean-up server, or a cloud model by its id
  * ``anweisungen`` — the instruction per picture family, where the user
    rewrote one; a family without an entry writes with the works text from
    app/bildprompt.py, and "reset" stores None to get that text back. A
    model without a family has an entry of its own among them
    (``NO_FAMILY``)

Stored as one setting in the global scope, the way the speech server keeps
its clean-up (app/diktatsprachewahl.py): read on every request, so a change
takes effect at once. Read by the prompt route (app/api/v1/bildprompt.py),
which both the picture window's button and ``draw_image`` call.
"""

from __future__ import annotations

from typing import Any

from app.bildprompt import ANWEISUNGEN, MAX_EINGABE

SCHLUESSEL = "bildaufbereitung"

# The three servers this program holds that can write a prompt. A cloud
# model is stored by its id behind ``KENNUNG``, so one field holds both
# kinds without a bare model name passing for a server.
SERVER: tuple[str, ...] = ("agent", "modell", "putzmodell")
KENNUNG = "kennung:"
# The longest id a cloud model is stored under.
KENNUNG_MAX = 300

# The agent server writes by default: it is what everything unattended runs
# on, so a picture drawn by a schedule is prepared where its run is.
VORGABE: dict[str, Any] = {"verbesserer": "agent", "anweisungen": {}}


def _verbesserer(roh: Any) -> str | None:
    if not isinstance(roh, str):
        return None
    wert = roh.strip()
    if wert in SERVER:
        return wert
    if wert.startswith(KENNUNG) and len(wert) > len(KENNUNG) and len(wert) <= KENNUNG_MAX:
        return wert
    return None


def wahl_pruefen(wert: Any) -> dict[str, Any]:
    """The settings check: the server as one of the known kinds, and an
    instruction only for a family that has one, or for the entry of the
    models without a family; None takes either back to the works text."""
    if not isinstance(wert, dict):
        return {}
    sauber: dict[str, Any] = {}
    if "verbesserer" in wert:
        verbesserer = _verbesserer(wert["verbesserer"])
        if verbesserer is not None:
            sauber["verbesserer"] = verbesserer
    roh = wert.get("anweisungen")
    if isinstance(roh, dict):
        anweisungen: dict[str, str | None] = {}
        for family, text in roh.items():
            if family not in ANWEISUNGEN:
                continue
            if text is None:
                anweisungen[family] = None
            elif isinstance(text, str):
                anweisungen[family] = text.strip()[:MAX_EINGABE] or None
        sauber["anweisungen"] = anweisungen
    return sauber


def wahl(repositories) -> dict[str, Any]:
    """What the block says right now, with the works answers behind it."""
    stand = repositories.einstellungen.zusammengefuehrt(SCHLUESSEL, vorgabe={})
    return {**VORGABE, **wahl_pruefen(stand if isinstance(stand, dict) else {})}


def verbesserer(repositories) -> str:
    return wahl(repositories)["verbesserer"]


def anweisung(repositories, family: str) -> str | None:
    """The instruction for a family, or for ``NO_FAMILY``: the user's own
    where there is one, the works text otherwise — None for a family that
    does not draw from text."""
    eigene = wahl(repositories)["anweisungen"].get(family)
    return eigene or ANWEISUNGEN.get(family)


def eigene_anweisungen(repositories) -> dict[str, str]:
    """The families whose instruction the user rewrote, with their text."""
    return {name: text for name, text in wahl(repositories)["anweisungen"].items() if text}


__all__ = [
    "KENNUNG",
    "SCHLUESSEL",
    "SERVER",
    "VORGABE",
    "anweisung",
    "eigene_anweisungen",
    "verbesserer",
    "wahl",
    "wahl_pruefen",
]
