"""Manage running answers — and, since 6.1, own them too.

An answer used to run *inside* the request: the loop sat in the generator of
the ``StreamingResponse``, and when the browser closed, it was over. That was
once thought right for a chat — nobody should heat up the GPU while no one is
watching — but a closed tab, a reload or a laptop going to sleep is not the
same thing as someone stopping the answer on purpose, and it was ending chats
the same way a crash would. For an agent it was always exactly
wrong.

So now **the run** owns the loop, not the request. It runs as its own
background task, writes its events into a memory and passes them on to
everyone currently watching. A request is merely one of those watchers.

``an_verbindung_gebunden`` still exists for the one caller that has no
request to speak for it at all: a background wake owns nothing to bind to
in the first place. Every route that starts a run for a person now passes
``False`` too, on purpose — the field is not "chat vs. job" any more, only
"is there an owning connection able to cancel this." Ended only by the stop
button, deleting the chat, or the run finishing on its own.

**On the name:** This is still called ``Generierung`` because so far there is
only one kind. As soon as agents exist (6.3), the word no longer fits and the
rename to ``Lauf`` comes along with them — doing it now would just be noise.

The confirmation prompt before a tool (1.6) also runs via the same id: the
stream only goes one way, so the user's answer comes in via
``/api/v1/chat/confirm`` and is delivered here to the waiting answer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, AsyncIterator, Awaitable, Callable

if TYPE_CHECKING:
    from app.providers.base import Stueck

log = logging.getLogger(__name__)

# The three questions a run can stand at, and the two events that end one: a
# question is always sent BEFORE its call and its result, so a question with
# either of those behind it in the same history is already settled.
_FRAGE_TYPEN = ("tool_confirm", "user_ask", "job_confirm")
_ERLEDIGT_TYPEN = ("tool_call", "tool_result")


def _ereignis(zeile: str, typen: tuple[str, ...]) -> dict | None:
    """The event behind a line when it is one of ``typen``, else ``None``.

    Lines are mostly not worth parsing (text, reasoning), so a cheap look at
    the text comes first. Anything that is not an event line — the tests feed
    plain strings through a run — is simply not one of ours.
    """
    if not any(f'"typ": "{typ}"' in zeile for typ in typen):
        return None
    if not zeile.startswith("data: "):
        return None
    try:
        ereignis = json.loads(zeile[len("data: ") :])
    except ValueError:
        return None
    return ereignis if isinstance(ereignis, dict) and ereignis.get("typ") in typen else None


def nachgeholt(zeilen: list[str]) -> list[str]:
    """The history as a reattaching watcher gets it: every question that is
    already settled carries ``"settled": true``.

    The window used to put each replayed question up again — sound, box and
    yellow entry — until the call or the result of the same ``aufruf_id``
    came by and took it down. Only the service knows the whole history, so it
    says which questions are over; the window only draws their line. What is
    still open is passed on unchanged, and so is everything live.

    Order matters: a question is settled by a call or result that comes AFTER
    it. A server may reuse a call id from round to round, and a new question
    must not be taken for answered because an older one with the same id was.
    """
    ergebnis = list(zeilen)
    offen: dict[str, int] = {}  # aufruf_id -> position of its pending question
    for stelle, zeile in enumerate(zeilen):
        frage = _ereignis(zeile, _FRAGE_TYPEN)
        if frage:
            offen[frage.get("aufruf_id")] = stelle
            continue
        erledigt = _ereignis(zeile, _ERLEDIGT_TYPEN)
        if not erledigt:
            continue
        position = offen.pop(erledigt.get("aufruf_id"), None)
        if position is None:
            continue
        ereignis = _ereignis(zeilen[position], _FRAGE_TYPEN)
        ereignis["settled"] = True
        ergebnis[position] = f"data: {json.dumps(ereignis, ensure_ascii=False)}\n\n"
    return ergebnis


async def discard(future: "asyncio.Future") -> "BaseException | None":
    """Ends a future still in flight and waits for that to actually settle —
    a bare ``.cancel()`` only requests it, and the caller relies on the
    future being truly done the moment this returns. Anything other than the
    expected ``CancelledError`` is only logged, never left to propagate: this
    is best-effort cleanup, and it must never be able to override the outcome
    the caller already settled on.

    Answers what a future that had ALREADY settled carried, read here so the
    event loop never has to report it later. Written for the caller that had
    a sibling: the two requests of the image prompt request fail and take
    each other along, and the failure of the one that was finished first is
    the reason the other is being cleaned up — the caller logs it as what it
    is. ``naechstes_stueck`` reads its own request here, whose error its
    caller already reported, and passes the answer by; that is why this
    function does not log it itself. The same place for every caller, the
    chat and job runs and the image prompt request alike: one way to end a
    sibling, not two.
    """
    if future.done():
        if future.cancelled():
            return None
        return future.exception()
    future.cancel()
    try:
        await future
    except asyncio.CancelledError:
        pass
    except Exception:
        log.exception("Cleaning up a cancelled future raised")
    return None


# How many finished runs stay in memory. This lets someone who only looks
# shortly after the end still see the transcript. Keep it small: what lasts
# lives in the database, this here is only the display window.
VERGANGENE_LAEUFE = 50

# How long a deleted chat waits for its runs to deregister, and how often it
# looks. A stopped run reads the signal at its next piece and lets a tool that
# is mid-run finish, so it ends in a moment — but not at once, and the wait has
# to be long enough for that tool and the run's closing write.
RUN_END_TIMEOUT_SECONDS = 45.0
RUN_END_POLL_SECONDS = 0.1


@dataclass
class Generierung:
    id: str
    chat_id: str
    endpoint_id: str
    # The answer row this run is writing. Known from the moment the run
    # starts — the row is created before the run is registered — but until
    # now it never left this process, so a window opening the chat cold had
    # to work out which row was live from its POSITION in the list. That
    # guess is what let a background report or a picture be mistaken for the
    # answer, blanked, and rewritten with the replayed stream.
    message_id: str | None = None
    # Whether an owning connection can cancel this run — see module header.
    an_verbindung_gebunden: bool = True
    signal: asyncio.Event = field(default_factory=asyncio.Event)
    # Why the run was told to stop, when whoever stopped it said so — a job
    # stopped with the run above it or with its chat records that reason
    # instead of the stop button's. None for the stop button.
    stop_reason: str | None = None
    # Open confirmation prompts: tool-call id -> decision.
    bestaetigungen: dict[str, "asyncio.Future[bool]"] = field(default_factory=dict)
    # The tool name each open prompt was actually asked about
    # — so a "always allow" that names a different tool than the one
    # waiting, or one nothing is waiting for any more, can be told apart
    # from a genuine match before a permanent rule is written from it.
    bestaetigung_namen: dict[str, str] = field(default_factory=dict)

    # --- Memory and watchers (6.1) --------------------------------------
    # Every reported line, in order of occurrence. Whoever joins later
    # catches up here on what they missed.
    ereignisse: list[str] = field(default_factory=list)
    _zuschauer: set[asyncio.Queue] = field(default_factory=set)
    fertig: asyncio.Event = field(default_factory=asyncio.Event)
    aufgabe: asyncio.Task | None = None
    # The one step of this run that waits for the stop signal: made with the
    # first piece the run reads, ended with the run (`beenden`). A step per
    # piece was a new task, and a new one thrown away, for every piece of
    # an answer — thousands for a long one.
    _stop_watcher: "asyncio.Future[bool] | None" = field(default=None, repr=False)

    @property
    def soll_abbrechen(self) -> bool:
        return self.signal.is_set()

    async def naechstes_stueck(
        self, quelle: AsyncIterator["Stueck"]
    ) -> tuple["Stueck | None", bool]:
        """The next piece of a provider's stream, and whether a stop is why
        the wait for it ended: ``(None, True)`` once a stop won the race,
        ``(None, False)`` once the stream reached its own end on its own —
        the two are never confused, even when both happen to land in the
        very same tick, because a stop that merely coincides with an answer
        that was finishing anyway must not turn a complete answer into an
        aborted one.

        A plain ``async for`` only ever checks ``signal`` between two
        pieces the provider actually sent — and a server can go on sending
        nothing but bare keepalives (no real ``Stueck``,
        ``app/providers/openai_kompatibel.py``) for as long as the
        connection to it stays open, so that check never runs again and the
        stop never lands. Racing the wait for the next piece against
        ``signal`` itself is what lets a stop win even then: cancelling the
        wait for the next piece is what actually closes the connection to
        the server, the same way ``asyncio.wait_for``'s own timeout would.

        The cancellation is awaited out here, not merely requested: the
        generator behind ``quelle`` counts as still running until it has
        actually unwound, and closing it (the caller's job, right after
        this returns) while it is fails with "asynchronous generator is
        already running" — measured against the existing abort test the
        moment this method first tried to skip that wait.

        A piece that happens to have arrived in the very same tick a stop
        landed still loses the tie: a burst of already-buffered pieces
        (batched network reads, a fast local provider) resolves the wait
        for the next one without ever really suspending, and always
        preferring that piece over a signal that was already set the same
        way would starve a stop for as long as the burst lasted — where a
        plain ``async for`` re-checks ``signal`` on every single piece and
        so never can. A stream that ends on its own is read differently
        from that same tie, on purpose: nothing of it was ever discarded,
        so a stop landing at that exact moment changes nothing about it.
        """
        if self._stop_watcher is None:
            self._stop_watcher = asyncio.ensure_future(self.signal.wait())
        abbruch = self._stop_watcher
        naechstes = asyncio.ensure_future(anext(quelle, None))
        try:
            await asyncio.wait({naechstes, abbruch}, return_when=asyncio.FIRST_COMPLETED)
            if naechstes.done():
                fehler = naechstes.exception()
                if fehler is not None:
                    raise fehler
                ergebnis = naechstes.result()
                if ergebnis is None:
                    return None, False
                if abbruch.done():
                    return None, True
                return ergebnis, False
            return None, True
        finally:
            # Cancelling the wait itself (the caller torn down from the
            # outside, not this method's own race) leaves the wait for the
            # piece exactly where the race left it, win or not — so it is
            # cleaned up here unconditionally, not only on the branch above
            # that returns normally. The wait for the stop is the run's
            # own and stays until the run ends.
            await discard(naechstes)

    # --- Confirmation prompts --------------------------------------------

    def bestaetigung_erwarten(self, aufruf_id: str, name: str) -> "asyncio.Future[bool]":
        zukunft: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self.bestaetigungen[aufruf_id] = zukunft
        self.bestaetigung_namen[aufruf_id] = name
        return zukunft

    def bestaetigung_ablegen(self, aufruf_id: str) -> None:
        self.bestaetigungen.pop(aufruf_id, None)
        self.bestaetigung_namen.pop(aufruf_id, None)

    # --- Events ----------------------------------------------------------

    def melden(self, zeile: str) -> None:
        """One line into memory and to everyone currently watching."""
        self.ereignisse.append(zeile)
        for schlange in self._zuschauer:
            schlange.put_nowait(zeile)

    def beenden(self) -> None:
        """The run is done. Watchers get the end marker."""
        if self.fertig.is_set():
            return
        self.fertig.set()
        if self._stop_watcher is not None:
            if not self._stop_watcher.done():
                self._stop_watcher.cancel()
            self._stop_watcher = None
        for schlange in self._zuschauer:
            schlange.put_nowait(None)

    async def zuschauen(self, ab: int = 0) -> AsyncIterator[str]:
        """First catch up on what happened, then continue live.

        ``ab`` is the counter position to read from — this lets a watcher
        whose connection was torn down reattach exactly where they left off.

        **Between catch-up and live, nothing may fall through and nothing may
        arrive twice.** That is why the queue is registered *first* and the
        counter taken *afterwards*: everything up to ``stand`` is already in
        memory, everything from ``stand`` on lands in the queue. There is no
        waiting in between, and without an ``await`` nothing in asyncio can
        butt in.
        """
        schlange: asyncio.Queue = asyncio.Queue()
        self._zuschauer.add(schlange)
        stand = len(self.ereignisse)
        war_fertig = self.fertig.is_set()
        try:
            # The history is judged whole, the way it stands at ``stand``: a
            # question the watcher has not read yet may be answered by a call
            # that lies further on, and one it read before the cut is not
            # replayed anyway.
            geschichte = nachgeholt(self.ereignisse[:stand])
            for zeile in geschichte[ab:stand]:
                yield zeile
            # The run was already over when we arrived — then there is no live part.
            if war_fertig:
                return
            while True:
                zeile = await schlange.get()
                if zeile is None:
                    return
                yield zeile
        finally:
            self._zuschauer.discard(schlange)


class Generierungsverwaltung:
    def __init__(self) -> None:
        self._laufende: dict[str, Generierung] = {}
        # Finished ones, so a late watcher can still find the transcript.
        self._vergangene: deque[Generierung] = deque(maxlen=VERGANGENE_LAEUFE)
        # Chats claimed by a run that is on its way but not registered yet.
        # See `reservieren`.
        #
        # Here and not module-level, because a claim belongs to ONE service:
        # tests build several apps in the same process, and a set living at
        # module level would carry one app's half-started chats into the
        # next. `hintergrundwecken` pays exactly that price for its own
        # module-level marks and has to clear them at every startup.
        # A claim is a chat, not a run: it carries the one thing the stop
        # button needs to reach it BEFORE a run exists — a signal the setup
        # watches, so a stop that arrives during the fold ends there instead
        # of starting an answer nobody waits for any more. A claim with no
        # signal would be a stop that reaches nothing, which is exactly how
        # the button used to behave in that window.
        self._reserviert: dict[str, asyncio.Event] = {}

    # --- Creating and starting -------------------------------------------

    def reservieren(self, chat_id: str) -> bool:
        """Claims the chat for a run that is about to start. True if it was
        free — and from then on it is the caller's, until `freigeben`.

        `fuer_chat` answers "is a run going here", and for a while asking it
        was enough: whoever asked started the run in the same breath, so
        nothing could get in between. That stopped being true. The chat path
        now WAITS between the two — on an embedding model for a chat with a
        cut-up document, and on a whole model request when the history has
        grown past the compaction threshold — and an await is precisely
        where the next caller runs.

        Both then found the chat free, both started, and one chat carried
        two answers. Only the first is handed out by `fuer_chat`, so the
        second wrote into a row no window was looking at.

        So the question and the claim are one call. Nothing in here awaits,
        and without an await nothing in asyncio can butt in — the same
        reasoning `zuschauen` uses for its own handover. It is also the one
        claim a wake asks about (``app/hintergrundwecken.py``): the wake
        takes it through `antwort_anstossen` before that function's first
        await, so one wake against another is settled here as well.

        A claim is not a run: it has no id and writes no row, which is why
        it is kept apart from `_laufende` rather than parked in it as a
        half-built `Generierung`. A window opening the chat cold asks
        `fuer_chat` which ROW is being written, and a claim cannot answer
        that — it would name none, and the window would push a second
        placeholder beside the stored answer.
        """
        if chat_id in self._reserviert or self.fuer_chat(chat_id) is not None:
            return False
        self._reserviert[chat_id] = asyncio.Event()
        return True

    def anspruch(self, chat_id: str) -> asyncio.Event | None:
        """The claim's own stop signal, or ``None`` where nothing claims the
        chat. What the setup holds while it folds: set, the caller stopped
        before the answer began, and no run is started for it."""
        return self._reserviert.get(chat_id)

    def beansprucht(self, chat_id: str) -> bool:
        """Whether anything holds this chat — a registered run or a claim.

        The question `reservieren` asks, without taking anything. Whoever is
        going to start the answer wants the claim; whoever only has to decide
        whether to step aside wants this. The background wake
        (app/hintergrundwecken.py) is the second kind: it asked `fuer_chat`
        alone, saw only REGISTERED runs, and walked into the 409 of a chat
        that was claimed but not yet running.

        It closes no race on its own — a claim can be taken the moment after
        this answers, and only `reservieren` inside the start itself can rule
        that out. What it does is make the ordinary case quiet: stepping
        aside where stepping aside was always the answer, rather than paying
        for a whole setup to be turned away at the end of it.
        """
        return chat_id in self._reserviert or self.fuer_chat(chat_id) is not None

    def freigeben(self, chat_id: str) -> None:
        """Hands the claim back.

        Owed on every way out of the stretch it covers — the registered run,
        and every early exit and error in between. A claim nobody hands back
        locks the chat out of answering for as long as the service runs, and
        unlike a run there is nothing left over to see that from.

        Idempotent, and safe for a chat that never held one: the release sits
        in a `finally` that also runs for callers who were turned away.
        """
        self._reserviert.pop(chat_id, None)

    def anmelden(
        self,
        *,
        chat_id: str,
        endpoint_id: str,
        an_verbindung_gebunden: bool = True,
        message_id: str | None = None,
    ) -> Generierung:
        generierung = Generierung(
            id=uuid.uuid4().hex,
            chat_id=chat_id,
            endpoint_id=endpoint_id,
            an_verbindung_gebunden=an_verbindung_gebunden,
            message_id=message_id,
        )
        self._laufende[generierung.id] = generierung
        return generierung

    def starten(
        self,
        *,
        chat_id: str,
        endpoint_id: str,
        arbeit: Callable[[Generierung], Awaitable[None]],
        an_verbindung_gebunden: bool = True,
        message_id: str | None = None,
    ) -> Generierung:
        """Creates the run and sends the work into the background.

        From here on the work depends on nothing coming from outside. Whoever
        wants to watch calls ``zuschauen()``; whoever wants to cancel,
        ``abbrechen()``.
        """
        generierung = self.anmelden(
            chat_id=chat_id,
            endpoint_id=endpoint_id,
            an_verbindung_gebunden=an_verbindung_gebunden,
            message_id=message_id,
        )

        async def huelle() -> None:
            try:
                await arbeit(generierung)
            except asyncio.CancelledError:
                # Cancellation from outside is not a malfunction, it is the stop button.
                raise
            except Exception:  # noqa: BLE001 - a run must not drag the service down with it
                log.exception("Run %s failed unexpectedly", generierung.id)
            finally:
                generierung.beenden()

        generierung.aufgabe = asyncio.create_task(huelle(), name=f"lauf-{generierung.id}")
        return generierung

    # --- Lookup -----------------------------------------------------------

    def holen(self, generierung_id: str) -> Generierung | None:
        """A run, whether it is still running or just finished."""
        treffer = self._laufende.get(generierung_id)
        if treffer is not None:
            return treffer
        for vergangen in self._vergangene:
            if vergangen.id == generierung_id:
                return vergangen
        return None

    def laufende(self) -> list[Generierung]:
        return list(self._laufende.values())

    def active_endpoints(self) -> set[str]:
        """The endpoints an answer is being written on right now — what
        makes a server `active` (app/server_state.py)."""
        return {generierung.endpoint_id for generierung in self.laufende()}

    def _im_chat(self, chat_id: str) -> list[Generierung]:
        """Every run going for this chat — walked over the SNAPSHOT that
        ``laufende()`` hands out, never over the live dict.

        ``GET /{chat}/messages`` is a plain ``def`` route, so FastAPI runs it
        in a worker thread while ``anmelden``/``abmelden`` change this same
        dict from the event-loop thread. Iterating the dict itself would then
        risk "dictionary changed size during iteration" — a 500 on a route
        that is hit every single time a chat is opened.

        Everyone who searches the dict goes through here, so there is one
        place to change if this ever needs a real lock as well.
        """
        return [g for g in self.laufende() if g.chat_id == chat_id]

    def fuer_chat(self, chat_id: str) -> Generierung | None:
        """The run currently going for this chat, if any — what a window
        that opens the chat cold (a reload, a fresh tab) needs in order to
        find out there is anything to reattach to at all. Only ever one at a
        time in practice: the chat holds the model's turn until this ends.
        """
        treffer = self._im_chat(chat_id)
        return treffer[0] if treffer else None

    # --- Finishing --------------------------------------------------------

    def abmelden(self, generierung_id: str) -> None:
        generierung = self._laufende.pop(generierung_id, None)
        if generierung is None:
            return
        # Whoever is still waiting for an answer is no longer waiting on anyone.
        for zukunft in generierung.bestaetigungen.values():
            if not zukunft.done():
                zukunft.cancel()
        generierung.bestaetigungen.clear()
        generierung.bestaetigung_namen.clear()
        self._vergangene.append(generierung)

    def abbrechen(self, generierung_id: str, *, reason: str | None = None) -> bool:
        """True if this answer existed and is now being cancelled.

        ``reason`` is the ending a job run records for it (``stop_reason``);
        the first one given stays."""
        generierung = self._laufende.get(generierung_id)
        if generierung is None:
            return False
        if reason and generierung.stop_reason is None:
            generierung.stop_reason = reason
        generierung.signal.set()
        return True

    def alle_im_chat_abbrechen(self, chat_id: str) -> int:
        """Stops what this chat holds: its registered runs, and the claim of
        a setup that is still on its way.

        The claim is the one the stop button could not reach before. The
        window presses stop while the service folds, the fold costs a whole
        model request, and a stop that only ever looked at registered runs
        found nothing and counted zero — so the answer began anyway, and the
        window hung it onto the screen of a run the person had just stopped.
        """
        anzahl = 0
        for generierung in self._im_chat(chat_id):
            generierung.signal.set()
            anzahl += 1
        anspruch = self._reserviert.get(chat_id)
        if anspruch is not None:
            anspruch.set()
            anzahl += 1
        return anzahl

    async def wait_for_chat_runs(self, chat_id: str) -> bool:
        """Waits until no run of this chat is registered any more — True when
        that happened, False when one was still there after
        ``RUN_END_TIMEOUT_SECONDS``.

        Sending the stop signal is not the end of a run: it reads the signal
        at its next piece, then writes its closing rows into the chat and
        deregisters. Whoever deletes the chat must let that happen first,
        or the closing write meets a chat that is gone and the run never
        deregisters.

        A run whose task has already finished without deregistering will
        never do it any more, so it is dropped here rather than waited for:
        it would otherwise keep the chat from ever being deleted. A run that
        started after the stop signal went out (a woken answer, a send from
        another window) gets the signal here, so it does not have to be
        outwaited to its natural end.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + RUN_END_TIMEOUT_SECONDS
        while True:
            still_running = []
            for run in self._im_chat(chat_id):
                if run.aufgabe is not None and run.aufgabe.done():
                    self.abmelden(run.id)
                else:
                    run.signal.set()
                    still_running.append(run)
            if not still_running:
                return True
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(RUN_END_POLL_SECONDS)

    def bestaetigen(
        self, generierung_id: str, aufruf_id: str, erlaubt: bool,
        antwort: str | None = None,
    ) -> bool:
        """Deliver the user's decision, or their answer.

        False here does not mean "denied" but "nobody is waiting for this
        answer" — the answer is over, or the click already happened.

        ``antwort`` belongs to ``ask_user``: there the waiting call wants a
        text, not a yes. Both travel the same future, and the waiting side
        knows which of the two it asked for.
        """
        generierung = self._laufende.get(generierung_id)
        if generierung is None:
            return False
        zukunft = generierung.bestaetigungen.get(aufruf_id)
        if zukunft is None or zukunft.done():
            return False
        zukunft.set_result(antwort if antwort is not None else erlaubt)
        return True

    def wartender_name(self, generierung_id: str, aufruf_id: str) -> str | None:
        """The tool name the open prompt for ``aufruf_id`` was actually
        asked about — ``None`` if nothing is waiting for it any more.
        Lets the confirm route tell a genuine match from a
        stray or mistargeted answer before writing a permanent rule from it.
        """
        generierung = self._laufende.get(generierung_id)
        if generierung is None:
            return None
        zukunft = generierung.bestaetigungen.get(aufruf_id)
        if zukunft is None or zukunft.done():
            return None
        return generierung.bestaetigung_namen.get(aufruf_id)
