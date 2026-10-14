"""Finding the agent somebody meant, and saying which ones there are.

Written after a chat that could not get a schedule created at all. The model
tried ``reminder``, was refused, tried ``Recherche``, was refused again, and
then said what the real problem was: it did not know which agents exist. Both
attempts were reasonable — the shipped agent is described in the tool's own
text as "the shipped reminder agent", and ``Recherche`` is how the word is
spelled in German. The names come from file names and are all lower case, and
the comparison was exact, so both fell through.

Which spellings count as the same name is NOT decided here — that belongs to
``Agentenverzeichnis`` in app/agenten.py, where every one of the five places
a name is looked up already comes through. What is left here is the wording:

  * a refusal says which names there ARE. That single line is what was
    missing; without it the caller can only keep guessing.
  * and an agent that can only answer says so before it is picked, not at run
    time in a sentence that reads like a model failure.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def namen_satz(vorhandene: Iterable[str]) -> str:
    """The available names, for a refusal to name them."""
    namen = sorted(vorhandene, key=str.casefold)
    return ", ".join(namen) if namen else "none"


def unbekannt_text(name: str | None, vorhandene: Iterable[str]) -> str:
    """What a caller is told when the name is not one of these.

    The available names belong in the sentence itself. A refusal that only
    repeats the rejected word leaves the caller exactly where it was.
    """
    return (
        f"Unknown agent {str(name or '').strip()!r}. Available agents: "
        f"{namen_satz(vorhandene)}."
    )


def ohne_werkzeuge(agenten: Mapping[str, Any]) -> list[str]:
    """Which of these agents can only answer, having no tools at all.

    An empty ``tools:`` list is a deliberate no (the shipped reminder agent
    has one). Left out entirely means every approved tool, which is the
    opposite — so only the explicit empty list counts here.
    """
    return sorted(
        (name for name, agent in agenten.items() if getattr(agent, "werkzeuge", None) == []),
        key=str.casefold,
    )


def auswahl_satz(agenten: Mapping[str, Any]) -> str:
    """The names, each saying whether it can do anything but answer, and
    what it is for where its file says so.

    The reminder agent's empty tool list is deliberate, and the user found
    out about it at run time, in an answer that read like a model failure:
    "I have no tool for the system time". Whoever picks the agent should be
    able to see that beforehand.
    """
    stumme = set(ohne_werkzeuge(agenten))
    teile = []
    described = False
    for name in sorted(agenten, key=str.casefold):
        part = f"{name} (answers only, no tools)" if name in stumme else name
        # What the agent is for, where its file says: without it the model
        # picks from the names alone. Kept to one line, however the file
        # wrapped it, so each agent stays one entry.
        description = " ".join(str(getattr(agenten[name], "description", None) or "").split())
        if description:
            described = True
            part = f"{part}: {description}"
        teile.append(part)
    if not teile:
        return "none"
    # One line per agent once any carries a description — a description
    # may hold commas of its own, and a line is a boundary it cannot blur.
    if described:
        return "\n" + "\n".join(f"- {part}" for part in teile)
    return ", ".join(teile)
