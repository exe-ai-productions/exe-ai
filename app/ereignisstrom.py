"""What the program as a whole has to say, on one line to the window.

There was already a live line, and the chat uses it: a command's output
arrives word by word over ``text/event-stream``
(``zusehen``, app/api/v1/befehle.py). But that line belongs to ONE chat.
Anything that concerns the program itself — a job ends, a schedule fires, a
model server comes up or goes away — had no way forward at all, so every
window asked instead: fourteen timers, the slowest of them fifteen seconds.
An agent finished and the person who started it found out a quarter of a
minute later.

This is the second line, and it belongs to no chat. It carries what the
event bus already announces; it invents nothing of its own.

WHAT IT DOES NOT CARRY. A chat's word-by-word answer. That is one chat's
business, it has its own stream, and putting it here would mean every open
window reading every chat's tokens.

WHAT IT SENDS IS A FACT, NOT A LIST. "This job ended", not the job. The
window fetches the list it already knows how to fetch, once, when it hears
that the list changed — so there stays one shape of a job in the program
and not a second one that has to be kept in step. What this saves is the
ASKING, not the answer.

ONE LINE PER WINDOW, not one per panel. Eight panels with eight connections
would be the same fault in a better disguise.

WHY NOT A WEBSOCKET. ``EventSource`` reconnects by itself when the line
drops, and this only ever goes one way. A websocket would be a second
protocol to keep alive for nothing.

WHAT THE FREE RECONNECT DOES NOT COVER, measured: a restart of the SERVICE.
The session key is minted fresh on every start and never touches disk
(app/sitzungsschluessel.py), so the retry carries the key of a process that
is gone, is answered 401, and an ``EventSource`` stops for good on a
non-2xx answer. That is not this line's problem to solve, and it is not
this line's alone: every request an already-loaded page can still make is
refused for the same reason. What recovers from a service restart is a
reload of the page, exactly as before.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

from app import shutdown
from app.events import Ereignisse, bus

log = logging.getLogger(__name__)

# Long enough that the line is nearly silent while nothing happens, short
# enough that a proxy or a sleeping machine cannot mistake it for dead.
HERZSCHLAG_SEKUNDEN = 20.0

# A watcher that stopped reading — a tab the machine suspended — must not
# grow a queue without end. Past this its line is ENDED rather than quietly
# thinned: the browser reconnects on its own, and the reconnect asks for the
# current state, which is the whole reason nothing here has to be replayed.
#
# Thinning was the older answer and was safe only while every event said "go
# and look": a dropped nudge was made good by the next one. An event that
# CARRIES the state has no next one — the runner speaks on change, and a
# change that was dropped is simply gone. Ending the line is the answer that
# recovers.
SCHLANGENGRENZE = 200

# What a watcher gets instead of the message it could not be handed. Not a
# message: the generator stops on it, the response ends, and the browser
# does the rest.
_UEBERLAUF = object()

# Put to every watcher when the service begins to end (see ``close_watchers``).
_ENDE = object()


class Ereignisstrom:
    """One fan-out point: whatever is announced reaches every open window."""

    def __init__(self) -> None:
        self._zuschauer: set[asyncio.Queue] = set()

    def melden(self, typ: str, **daten: Any) -> None:
        nachricht = {"typ": typ, **daten}
        for schlange in list(self._zuschauer):
            if schlange.qsize() >= SCHLANGENGRENZE:
                # Ended, not thinned — see SCHLANGENGRENZE. Dropped from the
                # watcher set here as well, so a queue nobody will drain is
                # not offered another message on the next announcement.
                #
                # The waiting messages go first, so the mark is the NEXT
                # thing read and not the two-hundred-and-first. They are
                # worth nothing to this watcher anyway: the line ends on the
                # mark, and the browser's reconnect asks for the current
                # state — which is why nothing here is replayed.
                while not schlange.empty():
                    schlange.get_nowait()
                schlange.put_nowait(_UEBERLAUF)
                self._zuschauer.discard(schlange)
                continue
            schlange.put_nowait(nachricht)

    async def zuschauen(
        self, *, herzschlag_sekunden: float = HERZSCHLAG_SEKUNDEN
    ) -> AsyncIterator[dict[str, Any] | None]:
        """Everything announced from now on. ``None`` is the heartbeat.

        Nothing is replayed and nothing is numbered, unlike the command
        stream next door. That one carries a run's output, where a missed
        line is a hole in a text nobody can recover; this one carries "go
        and look", and a watcher that reconnects goes and looks anyway.

        The wait happens inside this generator's own frame on purpose — the
        same reason ``Laufverwaltung.zuschauen`` gives at length: timing out
        ``__anext__()`` from the outside cancels the task the generator is
        suspended in, and an async generator that lets a ``CancelledError``
        escape is finished for good.
        """
        if shutdown.begun():
            return
        schlange: asyncio.Queue = asyncio.Queue()
        self._zuschauer.add(schlange)
        try:
            while True:
                try:
                    ereignis = await asyncio.wait_for(
                        schlange.get(), timeout=herzschlag_sekunden
                    )
                except asyncio.TimeoutError:
                    yield None
                    continue
                if ereignis is _ENDE:
                    return
                if ereignis is _UEBERLAUF:
                    # This watcher fell too far behind to be told everything.
                    # Ending here is what gets it back in step: the browser
                    # reconnects and asks for the state it missed.
                    return
                yield ereignis
        finally:
            self._zuschauer.discard(schlange)

    def close_watchers(self) -> None:
        """The service begins to end: every line ends now, and one that is
        opened from here on ends at once (see ``zuschauen``).

        A line that never ends keeps the server from shutting down, and a
        window holds one open all the time. Its reconnect finds nobody and
        tries again, as it does for any restart."""
        for schlange in list(self._zuschauer):
            schlange.put_nowait(_ENDE)

    @property
    def zuschauer(self) -> int:
        """How many windows are listening. For tests and for the log."""
        return len(self._zuschauer)


strom = Ereignisstrom()


# --- What comes off the bus, and what goes out as ------------------------

async def _auftrag_beendet(
    auftrag_id: str = "", work_id: str = "", agent: str = "",
    ausgang: str = "", grund: str | None = None, **_rest,
) -> None:
    # Deliberately without the run's result: it can be pages long, and the
    # window reads it from the job it fetches anyway.
    strom.melden(
        "auftrag_beendet",
        auftrag_id=auftrag_id,
        work_id=work_id,
        agent=agent,
        ausgang=ausgang,
        grund=grund,
    )


async def _auftrag_begonnen(
    auftrag_id: str = "", agent: str = "", cronjob_id: str | None = None, **_rest,
) -> None:
    strom.melden(
        "auftrag_begonnen", auftrag_id=auftrag_id, agent=agent, cronjob_id=cronjob_id
    )


async def _auftrag_fragt(
    auftrag_id: str = "", agent: str = "", wartet: bool = False, **_rest,
) -> None:
    # Deliberately without the question itself: it belongs to the run, the
    # window fetches the run anyway, and a question on the wire would be one
    # more copy of it to keep in step.
    strom.melden(
        "auftrag_fragt", auftrag_id=auftrag_id, agent=agent, wartet=wartet
    )


async def _auftrag_kontext(auftrag_id: str = "", **_rest) -> None:
    # Only which run: the reading itself is in the run's steps, and the
    # window fetches it from there.
    strom.melden("auftrag_kontext", auftrag_id=auftrag_id)


async def _termin_gefeuert(cronjob_id: str = "", **_rest) -> None:
    strom.melden("termin_gefeuert", cronjob_id=cronjob_id)


async def _cron_changed(cronjob_id: str = "", **_rest) -> None:
    strom.melden("cron_changed", cronjob_id=cronjob_id)


async def _model_switches_changed(schluessel: str = "", **_rest) -> None:
    strom.melden("model_switches_changed", schluessel=schluessel)


async def _endpunkt_status(
    endpoint_id: str = "", erreichbar: bool = False, **_rest
) -> None:
    strom.melden("endpunkt_status", endpoint_id=endpoint_id, erreichbar=erreichbar)


async def _exemd_zu_gross(
    chat_id: str = "", ordner: str = "", zeichen: int = 0, meldung: str = "", **_rest
) -> None:
    strom.melden(
        "exemd_zu_gross",
        chat_id=chat_id,
        ordner=ordner,
        zeichen=zeichen,
        meldung=meldung,
    )


async def _modellserver_zustand(
    runner: str = "",
    laeuft: bool = False,
    flash_aktiv: bool | None = None,
    mtp_aktiv: str | None = None,
    unknown_architecture: str | None = None,
    **_rest,
) -> None:
    # The one announcement that carries its answer instead of pointing at a
    # list. Why that is the right call, and what it costs, is written once
    # where the event is defined (app/events.py).
    # The architecture rides along only when there is one: a start that
    # failed on it is the one state that has a name to give, and every other
    # announcement keeps the three facts it always had.
    zusatz = {"unknown_architecture": unknown_architecture} if unknown_architecture else {}
    strom.melden(
        "modellserver_zustand",
        runner=runner,
        laeuft=laeuft,
        flash_aktiv=flash_aktiv,
        mtp_aktiv=mtp_aktiv,
        **zusatz,
    )


async def _server_state(endpoint_id: str = "", server_state: str = "", **_rest) -> None:
    # Carries its answer, like the model server's announcement above: one
    # word for one endpoint, nothing to go and look at (app/server_state.py).
    strom.melden("server_state", endpoint_id=endpoint_id, server_state=server_state)


async def _verdichtung_laeuft(chat_id: str = "", **_rest) -> None:
    strom.melden("verdichtung_laeuft", chat_id=chat_id)


async def _antwort_begonnen(
    chat_id: str = "", generation_id: str = "", message_id: str | None = None, **_rest
) -> None:
    strom.melden(
        "antwort_begonnen",
        chat_id=chat_id,
        generation_id=generation_id,
        message_id=message_id,
    )


_WEITERLEITUNG = (
    (Ereignisse.VERDICHTUNG_LAEUFT, _verdichtung_laeuft),
    (Ereignisse.ANTWORT_BEGONNEN, _antwort_begonnen),
    (Ereignisse.AUFTRAG_BEENDET, _auftrag_beendet),
    (Ereignisse.AUFTRAG_BEGONNEN, _auftrag_begonnen),
    (Ereignisse.AUFTRAG_FRAGT, _auftrag_fragt),
    (Ereignisse.AUFTRAG_KONTEXT, _auftrag_kontext),
    (Ereignisse.TERMIN_GEFEUERT, _termin_gefeuert),
    (Ereignisse.CRON_CHANGED, _cron_changed),
    (Ereignisse.MODEL_SWITCHES_CHANGED, _model_switches_changed),
    (Ereignisse.ENDPUNKT_STATUS_GEAENDERT, _endpunkt_status),
    (Ereignisse.EXEMD_ZU_GROSS, _exemd_zu_gross),
    (Ereignisse.MODELLSERVER_ZUSTAND, _modellserver_zustand),
    (Ereignisse.SERVER_STATE, _server_state),
)


def anmelden() -> None:
    """Hooks the hub onto the bus. Safe to call more than once — the bus is
    process-wide and a test suite builds many apps against it, and a handler
    registered twice would send every event twice."""
    for ereignis, handler in _WEITERLEITUNG:
        bus.abbestellen(ereignis, handler)
        bus.abonnieren(ereignis, handler)
