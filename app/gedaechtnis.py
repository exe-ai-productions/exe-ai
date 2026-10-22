"""The persistent memory — what the program keeps knowing about its user.

A second prompt file next to ``prompts/system.md``, read fresh on every
request and prepended to the history. Deliberately a file and not a table:
the thing that permanently shapes how the model behaves should be openable in
any editor and readable at a glance. Whoever cannot see what a memory knows
cannot correct it.

Two kinds live in it, under two headings:

    ## Rules
    - Comments and commit messages are English.

    ## Facts
    - Works on a desktop machine, sometimes from a laptop.

The distinction is the only one that does something. A **rule** changes
behaviour and therefore always applies — it must never depend on some
similarity measure deciding it is relevant. A **fact** is knowledge and
applies when it fits; that half is the one that can later be fetched on
demand, once the file outgrows what is worth sending every time.

Whether it travels is TWO switches, ``{"lokal": bool, "cloud": bool}``, and
that is the whole granularity: on the machine, and off it. Per-provider or
per-chat would be finer than anyone wants to operate.

The default is on, locally and in the cloud: a model that does not know what
the user told it before cannot work the way they asked, and one that cannot
keep what it learns makes them say it again. A memory in a system prompt is
sent with EVERY request, so to a provider it means a personal profile on a
foreign server; the two switches are there for whoever does not want that.

Not stored as bare booleans on purpose: the settings route treats a falsy
value as "nothing set" and lets the scope above take over, so a plain
``False`` could never switch anything OFF. A two-key object is truthy either
way.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

SCHLUESSEL = "gedaechtnis"

# On here and out there — until somebody switches a side off.
VORGABE: dict[str, bool] = {"lokal": True, "cloud": True}

# The headings the file is split by. English like everything in a prompt —
# the entries themselves are written in whatever language the user speaks.
UEBERSCHRIFT_REGELN = "## Rules"
UEBERSCHRIFT_FAKTEN = "## Facts"

# What the model is told before the memory. Without a sentence like this the
# entries read as part of the conversation instead of as standing knowledge.
EINLEITUNG = (
    "Information about this user from previous sessions. The rules always apply; use the "
    "facts when relevant. Do not repeat this information to the user unless asked. "
    "Your memory describes the user, not the machine you are running on; check the live system "
    "before you rely on it."
)


def schalter_pruefen(wert: Any) -> dict[str, bool]:
    """``gedaechtnis``: the two switches, checked before they are stored.

    Only the two known keys survive, and both as real booleans. Whatever else
    somebody sends is dropped rather than stored — a settings column holds
    JSON and cannot check anything by itself.
    """
    if not isinstance(wert, dict):
        return {}
    sauber = {name: bool(wert[name]) for name in VORGABE if name in wert}
    return sauber


# How often the user saved the memory in the window since this process
# started. Their change is in their next message: it is part of what tells
# the request route to build a chat's system message anew
# (app/api/v1/generierung.py, `_system_messages`). What the model saves with
# memory_save does not count it and waits for the next fold or the next chat.
_user_edits = 0


def note_user_edit() -> None:
    """Called by the memory route after the user saved the memory."""
    global _user_edits
    _user_edits += 1


def user_edit_count() -> int:
    return _user_edits


def mitschicken(repositories, zustand) -> bool:
    """Whether the memory travels with a request to THIS endpoint."""
    stand = repositories.einstellungen.zusammengefuehrt(
        SCHLUESSEL, vorgabe=dict(VORGABE)
    )
    if not isinstance(stand, dict):
        stand = dict(VORGABE)
    endpunkt = getattr(zustand, "endpunkt", None)
    seite = "lokal" if getattr(endpunkt, "group", None) == "local" else "cloud"
    return bool(stand.get(seite, VORGABE[seite]))


def anhaengen(system_prompt: str, gedaechtnis: str) -> str:
    """Puts prompt and memory into ONE system message.

    One and not two: Anthropic takes a single system field, and providers
    disagree about what a second system message means. Assembling here keeps
    that difference out of everything downstream.

    The file is used as it stands, including its headings — they are what
    tells the model which half always applies.
    """
    gedaechtnis = (gedaechtnis or "").strip()
    if not gedaechtnis:
        return system_prompt
    block = f"{EINLEITUNG}\n\n{gedaechtnis}"
    system_prompt = (system_prompt or "").strip()
    return f"{system_prompt}\n\n{block}" if system_prompt else block
