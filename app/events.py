"""Internal event system (publish/subscribe).

Purpose: decouple modules. The streaming proxy does not need to know who
reacts to a finished answer — it announces ``model_response_finished``, and
whoever is interested (save chat, count tokens, update statistics) has
subscribed beforehand.

Handlers may be synchronous or asynchronous. An error in one handler does not
stop the others — it is logged and the flow continues.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from app import aufgaben
from collections import defaultdict
from functools import partial
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

Handler = Callable[..., Any | Awaitable[Any]]


class Ereignisse:
    """Names of the known events — no loose strings in the code."""

    CHAT_ERSTELLT = "chat_created"
    CHAT_GELOESCHT = "chat_deleted"
    NACHRICHT_GESPEICHERT = "message_saved"
    # An answer has started in a chat — by a request from a window, or on
    # the service's own initiative when a finished background command woke
    # the model. Carries chat_id, generation_id and message_id, so a window
    # idle on that chat can attach to a run it did not start.
    ANTWORT_BEGONNEN = "model_response_started"
    ANTWORT_FERTIG = "model_response_finished"
    ANTWORT_ABGEBROCHEN = "model_response_cancelled"
    ENDPUNKT_STATUS_GEAENDERT = "endpoint_status_changed"
    # A shared folder's exe.md has grown past the warning threshold
    # (app/ordnerwissen.py). Fired once per chat and folder; what turns it
    # into the yellow line in the window is a separate piece of work.
    EXEMD_ZU_GROSS = "exemd_too_large"
    # A job run reached an end state and nothing is going to follow it
    # (app/auftragsende.py). Fired once per run, never for a run whose work
    # was handed on to a continuation — a chain of ten links is one piece of
    # work ending once, not ten.
    AUFTRAG_BEENDET = "job_finished"
    # A job run was just created and is on its way. Fired where the row is
    # written — the start route and the schedule that fires one.
    AUFTRAG_BEGONNEN = "job_started"
    # A job run called `ask_user` and is standing on the answer — or has
    # just been given one and is going again (app/api/v1/auftraege.py). The
    # one moment a run changes state without ending, so nothing else on this
    # bus reports it, and three displays wait on it: the waiting group, the
    # banner, and the notice.
    AUFTRAG_FRAGT = "job_asks"
    # A job run wrote a new context reading (a ``kontext`` step,
    # app/api/v1/auftraege.py). The tile of that run draws the reading as
    # its context line off the job list, and this is what makes the window
    # fetch that list again — nothing else reloads it while a run goes on.
    AUFTRAG_KONTEXT = "job_context"
    # A schedule reached its due time and started a run for it
    # (app/cronablauf.py). The entry's own row changed with it, which is
    # what the schedules panel wants to know.
    TERMIN_GEFEUERT = "cron_fired"
    # The model server came up, went away, or the truth about how it is
    # running became known (app/modellrunner.py). Only the chat runner
    # announces it: the embedding, speech and vision servers have no readout
    # waiting on them. Carries the three facts themselves rather than "go
    # and look" — there is no list behind them, and a window that had to
    # fetch them would be back to asking.
    MODELLSERVER_ZUSTAND = "model_server_state"
    # A chat is being compacted right now (app/chatverdichtung.py): the
    # summarizing request is out, and the answer the user is waiting for
    # cannot start until it is back. Fired before the request goes out,
    # once per fold, so the window can say what the wait is for — until
    # this the placeholder sat there wearing the ordinary waiting mark for
    # as long as a second model call took.
    VERDICHTUNG_LAEUFT = "compaction_running"


class EventBus:
    def __init__(self) -> None:
        self._handler: dict[str, list[Handler]] = defaultdict(list)
        # Every announcement fired from synchronous code, held until it has
        # run. See ``veroeffentlichen_ohne_warten`` for why that matters.
        self._laufende: set[asyncio.Task] = set()
        # The service's own loop, once it is running. See
        # ``veroeffentlichen_ohne_warten`` for what it is for.
        self._schleife: asyncio.AbstractEventLoop | None = None

    def schleife_merken(self, schleife: asyncio.AbstractEventLoop | None) -> None:
        """Tells the bus which loop the service runs on.

        Called once at startup. Without it an announcement fired from a
        worker thread has no way home — see ``veroeffentlichen_ohne_warten``.
        """
        self._schleife = schleife

    def abonnieren(self, ereignis: str, handler: Handler) -> None:
        self._handler[ereignis].append(handler)

    def abbestellen(self, ereignis: str, handler: Handler) -> None:
        if handler in self._handler.get(ereignis, []):
            self._handler[ereignis].remove(handler)

    def abonnenten(self, ereignis: str) -> list[Handler]:
        return list(self._handler.get(ereignis, []))

    def alles_loeschen(self) -> None:
        """Tests only."""
        self._handler.clear()

    @property
    def offene_aufgaben(self) -> int:
        """Announcements fired and not yet run. For tests."""
        return len(self._laufende)

    async def veroeffentlichen(self, ereignis: str, **daten: Any) -> None:
        """Calls all handlers of the event. Errors are logged, not raised."""
        handler_liste = self._handler.get(ereignis, [])
        if not handler_liste:
            return

        for handler in list(handler_liste):
            try:
                ergebnis = handler(**daten)
                if inspect.isawaitable(ergebnis):
                    await ergebnis
            except Exception:  # noqa: BLE001 - a broken subscriber must not block anything
                log.exception(
                    "Handler for event '%s' failed: %r", ereignis, handler
                )

    def veroeffentlichen_ohne_warten(self, ereignis: str, **daten: Any) -> None:
        """Fires an event from synchronous code without waiting for it.

        The task is HELD until it has run, and that is the whole point of
        the set above. ``create_task`` hands back the only strong reference
        there is; the loop itself keeps a weak one, so a task nobody holds
        may be collected mid-flight and its event simply never arrives.
        Rarely — which is the worst kind of fault there is, and it was
        tolerable only while the bus carried events nobody was waiting for.
        It carries every notice to the user now (app/ereignisstrom.py): an
        announcement that occasionally vanishes is an agent run that never
        reports, with nothing anywhere to say why.

        FIRING FROM A WORKER THREAD goes back to the service's loop, and
        that is the reason ``schleife_merken`` exists. There is no loop
        running on such a thread, and the obvious answer — start one here
        and drive the handlers on it — is silently wrong: the handlers feed
        queues that belong to the service's loop (app/ereignisstrom.py), and
        an ``asyncio.Queue`` touched from a second thread is a fault that
        surfaces rarely and nowhere near where it was made. Every reader
        thread and downloader in this program publishes this way.

        Firing while the service has no loop at all — a script, a
        synchronous test — keeps its old answer: run it here and now, and be
        done before this returns.
        """
        try:
            schleife = asyncio.get_running_loop()
        except RuntimeError:
            dienstschleife = self._schleife
            # Not running is as useless as closed, and quieter about it: the
            # handoff is accepted, the callback is queued behind a loop that
            # will never turn again, and the announcement is simply gone. A
            # loop that was remembered and then stopped is the ordinary shape
            # of a test that built an app and let it go.
            if (
                dienstschleife is None
                or dienstschleife.is_closed()
                or not dienstschleife.is_running()
            ):
                asyncio.run(self.veroeffentlichen(ereignis, **daten))
                return
            try:
                dienstschleife.call_soon_threadsafe(
                    partial(self.veroeffentlichen_ohne_warten, ereignis, **daten)
                )
            except RuntimeError:
                # The loop closed between the check and the handoff: the
                # service is going down and nobody is listening any more.
                log.debug("Event '%s' discarded: the loop is closed", ereignis)
            return
        del schleife  # only asked to know there is one; `halten` uses it
        aufgaben.halten(
            self.veroeffentlichen(ereignis, **daten),
            name=f"ereignis-{ereignis}",
            menge=self._laufende,
        )

    async def stillstand(self) -> None:
        """Waits for everything fired and not yet run. For tests and for a
        shutdown that would otherwise leave announcements in mid-air."""
        while self._laufende:
            await asyncio.gather(*list(self._laufende), return_exceptions=True)


# Process-wide bus. Tests create their own when needed.
bus = EventBus()
