"""Holding a task the loop would otherwise only remember weakly.

``create_task`` hands back the only strong reference there is; the loop
itself keeps a weak one, so a task nobody holds may be collected mid-flight
and whatever it was doing simply never happens. Rarely — which is the worst
kind of fault there is. Four places in the program had written the same
three lines against it, each with a done-callback of its own, and six
older ``create_task`` calls had written none.

One function, then: it creates the task, holds it in a set until it is
over, and lets the caller add what it wants to do at the end. Callers with
a shutdown story of their own — wakes that are cancelled when the service
goes down, companions whose exceptions are read with the run in hand —
hand in their own set and keep that story; everybody else uses the one
here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

# What is held by default: every fire-and-forget task with no owner of its
# own. Discarded the moment a task is done.
_gehalten: set[asyncio.Task] = set()


def halten(
    coro: Coroutine[Any, Any, Any],
    *,
    name: str,
    menge: set[asyncio.Task] | None = None,
    bei_ende: Callable[[asyncio.Task], Any] | None = None,
) -> asyncio.Task:
    """Starts ``coro`` on the running loop and holds the task until it ends.

    ``menge`` is the set that holds it — the caller's own where the caller
    has one, the module's otherwise. ``bei_ende`` runs when the task is
    done, after the task has been let go of, with the task in hand.
    """
    ziel = _gehalten if menge is None else menge
    aufgabe = asyncio.get_running_loop().create_task(coro, name=name)
    ziel.add(aufgabe)

    def loslassen(fertig: asyncio.Task) -> None:
        ziel.discard(fertig)
        if bei_ende is not None:
            bei_ende(fertig)

    aufgabe.add_done_callback(loslassen)
    return aufgabe


def offene() -> set[asyncio.Task]:
    """The tasks held here that are still running."""
    return {aufgabe for aufgabe in _gehalten if not aufgabe.done()}
