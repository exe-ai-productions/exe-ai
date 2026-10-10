"""A job run asking the user something, and standing still until answered.

The chat has done this since ``ask_user`` was built: the model asks, the call
is held open, the buttons appear above the input field, the answer becomes the
tool's result. A job was refused the tool for one reason — it had no PLACE to
put a question. Nobody is sitting in front of a run that fires from a schedule
at three in the morning.

The place is this: the run goes to ``wartet``, the question is written onto the
run itself, and it stands in the waiting group until somebody walks past. The
holding open is not rebuilt here — it is the very same future the chat uses
(``app/generationen.py``), reached through the very same route
(``POST /api/v1/chat/confirm``), because a job run IS a run in the same manager.

FIVE RULES, each with a case behind it.

1. **Waiting has no deadline.** The chat gives up after a few minutes and
   carries on; a job must not. A deadline would throw away everything the run
   has done so far because nobody happened to be at the machine — which is the
   normal state of a run that fires at night.

2. **A waiting run holds no slot at the model server.** It is not computing:
   it sits between two rounds with a tool call unanswered. That is what makes
   rule 1 affordable — an unanswered question over a whole night would
   otherwise block one of the few slots, and the slots share the one context
   window between them.

3. **Cancelling has to work.** ``soll_abbrechen`` is read on every tick, so
   the stop button reaches a waiting run as fast as it reaches a running one.
   Without that a run nobody answers would stand in the list for ever.

4. **The waiting time is given back to the run.** ``max_minutes`` is a budget
   for WORK, not for how long a person took to answer, so the caller pushes
   its deadline out by exactly the time spent here.

5. **The question outlives a restart, and so does the work.** The question is
   written to the row, not held in memory. The run behind it does not survive
   — the in-memory future goes with the process — so the answer given
   afterwards cannot wake it. It is not thrown away either: the run is carried
   on from its own status with the question and the answer folded into the
   assignment (``app/api/v1/auftraege.py``, ``zwischenstand.fortsetzung_planen``).
   That is why this module writes a status BEFORE it waits: standing still on
   a question is exactly the moment a run has to be resumable from, and a
   round that only made a tool call has written nothing yet.
"""

from __future__ import annotations

import asyncio
import json
import logging

from app.events import Ereignisse, bus
from app.tools import frage_werkzeug

log = logging.getLogger(__name__)

# How often the wait looks up to see whether the run was cancelled. Short
# enough that a stop button feels immediate, long enough to cost nothing over
# a night of waiting.
PRUEFTAKT = 0.5


def stand_beim_fragen(repositories, auftrag_id: str, frage: str) -> None:
    """Records where the run got to, before it stops.

    A run writes its status after every round that produced prose
    (``app/api/v1/auftraege.py``). A round that did nothing but call this
    tool produced none — so a run that asks in its first round has nothing on
    its row, and a restart would have nothing to carry it on from. Standing
    still on a question is precisely the moment that has to be resumable.

    Appended, never replacing: whatever the run already said about itself is
    the more useful half.
    """
    auftrag = repositories.auftraege.holen(auftrag_id)
    bisher = (auftrag.zwischenstand or "").strip() if auftrag else ""
    satz = f"Asked the user: {frage}"
    repositories.auftraege.zwischenstand_setzen(
        auftrag_id, f"{bisher}\n\n{satz}" if bisher else satz
    )


def frage_schreiben(
    repositories, auftrag_id: str, aufruf_id: str, frage: str, optionen: list[dict]
) -> None:
    """The question onto the run, so three displays can read it without
    walking a transcript: the waiting group, the banner, the buttons."""
    repositories.auftraege.frage_setzen(
        auftrag_id,
        json.dumps(
            {"aufruf_id": aufruf_id, "frage": frage, "optionen": optionen},
            ensure_ascii=False,
        ),
    )


async def stellen(
    *,
    generierung,
    repositories,
    auftrag_id: str,
    agent: str,
    aufruf_id: str,
    frage: str,
    optionen: list[dict],
) -> str | None:
    """Asks, waits, and hands back the answer.

    ``None`` means the run was cancelled while waiting — the caller ends it
    rather than carrying on with a decision nobody made.

    The state and the question are written together and cleared together, so
    a row never says "waiting" with nothing to answer, or the other way round.
    """
    zukunft = generierung.bestaetigung_erwarten(aufruf_id, frage_werkzeug.WERKZEUG_NAME)
    frage_schreiben(repositories, auftrag_id, aufruf_id, frage, optionen)
    stand_beim_fragen(repositories, auftrag_id, frage)
    repositories.auftraege.zustand_setzen(auftrag_id, "wartet")
    bus.veroeffentlichen_ohne_warten(
        Ereignisse.AUFTRAG_FRAGT, auftrag_id=auftrag_id, agent=agent, wartet=True
    )
    try:
        while True:
            try:
                # shield: a tick running out ends the waiting, never the
                # answer — the same construction the chat's own wait uses.
                antwort = await asyncio.wait_for(
                    asyncio.shield(zukunft), timeout=PRUEFTAKT
                )
            except asyncio.TimeoutError:
                if generierung.soll_abbrechen:
                    return None
                continue
            except asyncio.CancelledError:
                if zukunft.cancelled():
                    return None
                raise
            # The confirm route carries either a decision or a text. Only a
            # text is an answer here; a bare yes came from somewhere else.
            return antwort if isinstance(antwort, str) else None
    finally:
        generierung.bestaetigung_ablegen(aufruf_id)
        repositories.auftraege.frage_setzen(auftrag_id, None)
        # Back to running — but never over an ending. A cancel while waiting
        # has already written 'abgebrochen' through the cancel route, and
        # overwriting it here would put a finished run back into the list.
        auftrag = repositories.auftraege.holen(auftrag_id)
        if auftrag is not None and auftrag.zustand == "wartet":
            repositories.auftraege.zustand_setzen(auftrag_id, "laeuft")
        bus.veroeffentlichen_ohne_warten(
            Ereignisse.AUFTRAG_FRAGT, auftrag_id=auftrag_id, agent=agent, wartet=False
        )
