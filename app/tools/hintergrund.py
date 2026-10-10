"""Command runs: what is running, what it wrote, and who is watching.

Every ``run_command`` becomes a run here, foreground and background alike.
Three jobs in one place, because they are the same data seen from three
sides:

* **Live output.** A build that takes two minutes used to be two minutes of
  nothing. Each line is announced the moment it arrives, and the terminal
  window shows it.
* **Background runs.** A call may return at once and keep working. When it
  finishes, the result goes into the chat by itself — the alternative, a
  second tool for looking it up, was rejected: small models never look.
* **The kill switch.** Nothing outlives the program. Whatever is still
  running when the service stops is killed, so no process keeps writing into
  a folder while the chat that started it is gone.

The buffer is capped and keeps both ends: the start says what was being done,
the end says how it went, and the middle is the part nobody reads.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from itertools import islice
from typing import Any, AsyncIterator, Callable, Iterable

from app import prozessstopp

log = logging.getLogger(__name__)

# How much of one run's output is kept. Enough for a long build log, far from
# enough to eat the memory of a machine that also runs a model.
MAX_PUFFER_ZEICHEN = 200_000

# How many of a chat's reported events stay reachable for a watcher that
# reattaches. The run's own output is capped above; this is the SECOND copy
# of every line, the one `melden()` files per chat so a dropped connection
# can resume — and it had no cap at all.
#
# Measured (a 109-character build line, tracemalloc): 220 bytes an event, so
# 100,000 lines are 21 MB and five million are just over a gigabyte. A
# nightly run writing 100 lines a second makes 180,000 in half an hour, and
# fifty such runs a night is the shape this was built for. Nothing released
# any of it before the chat was deleted.
#
# 5,000 is the same order as one run's own buffer (200,000 characters) and
# covers roughly fifty seconds at that measured rate — far longer than the
# few seconds an `EventSource` takes to reconnect by itself, which is the
# one case that reads back past the live edge.
#
# WHAT IT COSTS: a watcher that was away for longer than the cap holds gets
# the events that are still here and not the ones in between, so that run's
# output has a hole in the terminal window until the run list is fetched
# again — and that fetch (`GET /laeufe/{chat}`) carries every run's full
# `ausgabe` from the buffer above, so the hole closes on the next chat
# switch. Nothing else reads the list: the record of what a command wrote is
# `Lauf.zeilen`, not this.
MAX_EREIGNISSE = 5_000

# A heartbeat often enough that a proxy or a sleeping laptop does not quietly
# drop the connection. Read inside zuschauen() itself —
# see the docstring there for why it cannot live in the caller instead.
HERZSCHLAG_SEKUNDEN = 20.0

# How long a background run may take before it is stopped. The foreground has
# two minutes; a background run is meant for the long things, but not for
# forever.
HINTERGRUND_GRENZE_SEKUNDEN = 30 * 60

LAEUFT = "laeuft"
FERTIG = "fertig"
FEHLER = "fehler"
# Asked for, not gone wrong. Its own state because the colour rules treat a
# failure and a change of mind differently, and a stopped run should not
# leave a red mark in the history.
ABGEBROCHEN = "abgebrochen"

# What kind of work a run is. The list carries both because they are the same
# thing seen by the same eye: something started in this chat, and it ended.
ART_BEFEHL = "befehl"
ART_BILD = "bild"

# What a background command's report says when the service went down
# before the command finished. English, like every other line a tool
# writes into the model's history.
ABSCHLUSS_BEIM_BEENDEN = "Stopped: the service shut down before the command finished."


@dataclass
class Lauf:
    """One command, from its first line to its exit code."""

    nummer: int
    chat_id: str
    befehl: str
    hintergrund: bool = False
    zustand: str = LAEUFT
    # Set by Laufverwaltung.vergessen(): the chat is gone, and everything
    # still holding this object (a companion task awaiting the process, a
    # drawing job) must let its late news die with it. Without the flag the
    # first such report re-created the purged chat's event record — see
    # zeile()/beenden() below.
    vergessen: bool = False
    code: int | None = None
    zeilen: list[str] = field(default_factory=list)
    prozess: Any = None
    # What was run. A command writes lines and has an exit code; a picture
    # writes nothing and has a duration — one list, two shapes of entry.
    art: str = ART_BEFEHL
    # Monotonic, so a clock the user drags around cannot make a run last
    # minus two seconds.
    _begonnen: float = field(default_factory=time.monotonic)
    dauer_sekunden: float | None = None
    # Whether the model has had this run's report in front of it. Set the
    # moment an answer starts in the chat after the run ended — that
    # answer's history carries the report row — and announced on the
    # chat's stream, so the card of the call that started the run can
    # stop pulsing (app/api/v1/generierung.py, Nachricht.svelte).
    gelesen: bool = False
    # The stored answer whose tool call started this run — stamped by the
    # answer once the call has returned, read by the report handler when a
    # background run ends after that answer is over, so the ending lands
    # on the right row without searching the chat for the number.
    antwort_id: str | None = None
    # The folder the command runs in, shown under it in the terminal.
    folder: str | None = None
    # Somebody pressed stop: the ending that follows is "stopped", not the
    # failure its exit code alone would read as.
    stop_requested: bool = False
    _zeichen: int = 0

    @property
    def ausgabe(self) -> str:
        return "\n".join(self.zeilen)

    def anhaengen(self, text: str) -> None:
        self.zeilen.append(text)
        self._zeichen += len(text) + 1
        if self._zeichen <= MAX_PUFFER_ZEICHEN:
            return
        # Keep both ends: the first lines say what was started, the last ones
        # say how it ended. What goes is the middle, and it says so.
        haelfte = MAX_PUFFER_ZEICHEN // 2
        kopf: list[str] = []
        laenge = 0
        for zeile in self.zeilen:
            if laenge + len(zeile) + 1 > haelfte:
                break
            kopf.append(zeile)
            laenge += len(zeile) + 1
        fuss: list[str] = []
        laenge = 0
        for zeile in reversed(self.zeilen):
            if laenge + len(zeile) + 1 > haelfte:
                break
            fuss.append(zeile)
            laenge += len(zeile) + 1
        fuss.reverse()
        weg = len(self.zeilen) - len(kopf) - len(fuss)
        if weg <= 0:
            return
        self.zeilen = [*kopf, f"… [{weg} lines cut out of the middle]", *fuss]
        self._zeichen = sum(len(z) + 1 for z in self.zeilen)


class Laufverwaltung:
    """All runs of all chats, and everyone watching them.

    In memory on purpose: a run belongs to a program that is running. What is
    worth keeping lands in the chat as a message.
    """

    def __init__(self) -> None:
        self._laeufe: dict[str, list[Lauf]] = {}
        # The last MAX_EREIGNISSE events reported, in order — mirrors what
        # Generierung.ereignisse does for a text answer. A watcher who lost
        # the connection (a chat switch that outran its own fetch, a dropped
        # network) counts what it already has and reattaches exactly there.
        self._ereignisse: dict[str, deque[dict[str, Any]]] = {}
        # How many events this chat has EVER reported. Its own number
        # because the deque above forgets: once a long run has pushed the
        # start out, the length of the buffer is no longer the position of
        # the next event, and `n` is what tells a reconnecting watcher
        # "already seen" from "new". Counting by length would hand out the
        # same `n` twice and the window would drop the second one.
        self._ereignisstand: dict[str, int] = {}
        self._zuschauer: dict[str, set[asyncio.Queue]] = {}
        # What to do with a finished background run. The tool cannot write to
        # the database; the service hangs its own handler in here at startup.
        self.abschluss: Callable[[Lauf, str], Any] | None = None
        # Where a chat's numbering continues from. Runs live in memory, but
        # their numbers are written into the chat's rows (the tool log of
        # the answer that started a run carries it), and a window pairs
        # call and run by that number. Counting from one after every
        # restart handed a new run the number of a stored call, and the
        # old card took the new run's output. The service hangs in a reader
        # of the highest number the chat's rows carry; without one the
        # count starts at one, as it always did.
        self.nummernstart: Callable[[str], int] | None = None
        self._startnummer: dict[str, int] = {}
        # Everything that keeps its own record beside a run and has to drop
        # it when the chat's runs go. See beim_vergessen() below.
        self._hoerer: list[Callable[[str], Any]] = []

    # --- The runs --------------------------------------------------------

    def _naechste_nummer(self, chat_id: str) -> int:
        """The next free number of this chat — after its stored ones.

        Only a reading that succeeded is remembered: a database locked for
        a moment must not put the chat back on a numbering that collides
        with its stored calls for the rest of the process. The run that
        hit the failure counts from the in-memory list alone, and the next
        one asks again.
        """
        if chat_id not in self._startnummer:
            if self.nummernstart is None:
                self._startnummer[chat_id] = 0
            else:
                try:
                    self._startnummer[chat_id] = max(0, int(self.nummernstart(chat_id) or 0))
                except Exception:  # noqa: BLE001 - a number we cannot read is not worth the run
                    log.exception("Highest run number of chat %s cannot be read", chat_id)
                    return len(self._laeufe.get(chat_id, ())) + 1
        return self._startnummer[chat_id] + len(self._laeufe.get(chat_id, ())) + 1

    def anlegen(
        self,
        chat_id: str,
        befehl: str,
        hintergrund: bool = False,
        art: str = ART_BEFEHL,
        folder: str | None = None,
    ) -> Lauf:
        nummer = self._naechste_nummer(chat_id)
        liste = self._laeufe.setdefault(chat_id, [])
        lauf = Lauf(
            nummer=nummer,
            chat_id=chat_id,
            befehl=befehl,
            hintergrund=hintergrund,
            art=art,
            folder=folder,
        )
        liste.append(lauf)
        self.melden(
            chat_id,
            typ="lauf_start",
            lauf=lauf.nummer,
            befehl=befehl,
            hintergrund=hintergrund,
            art=art,
            folder=folder,
        )
        return lauf

    def zeile(self, lauf: Lauf, text: str, strom: str = "stdout") -> None:
        # A forgotten run's chat no longer exists; reporting for it would
        # setdefault() its event record back into `_ereignisse` — for good,
        # because vergessen() is only reachable while the chat still is.
        if lauf.vergessen:
            return
        lauf.anhaengen(text)
        self.melden(
            lauf.chat_id, typ="lauf_zeile", lauf=lauf.nummer, text=text, strom=strom
        )

    def beenden(self, lauf: Lauf, code: int | None, zustand: str | None = None) -> None:
        """Closes a run. `zustand` overrides the exit-code reading.

        A picture has no exit code, and a stopped one is not a failure — both
        say for themselves how they ended.
        """
        # Same as zeile(): the companion task of a killed run still wakes on
        # the stream's end and reports in. Late news for a dead chat is
        # dropped, not filed.
        if lauf.vergessen:
            return
        # Stopped, where the stop cut it short; a command that finished
        # cleanly as the button was pressed simply finished. A stopped run
        # carries no code, as one stopped at the time limit does not: the
        # number is the signal's, not the command's answer, and drawn it
        # reads as a failure.
        if zustand is None and lauf.stop_requested and code != 0:
            zustand = ABGEBROCHEN
            code = None
        lauf.code = code
        lauf.zustand = zustand or (FERTIG if code == 0 else FEHLER)
        lauf.prozess = None
        lauf.dauer_sekunden = round(time.monotonic() - lauf._begonnen, 3)
        self.melden(
            lauf.chat_id,
            typ="lauf_ende",
            lauf=lauf.nummer,
            code=code,
            zustand=lauf.zustand,
            hintergrund=lauf.hintergrund,
            dauer_sekunden=lauf.dauer_sekunden,
        )

    def laeufe(self, chat_id: str) -> list[Lauf]:
        return list(self._laeufe.get(chat_id, []))

    async def stop(self, chat_id: str, nummer: int) -> Lauf | None:
        """Stops one running command with everything it started: asked
        first, then insisted on (app/prozessstopp.py). Returns the run, or
        None when this chat has no run of that number.

        A run that is already over is returned as it is — stopping what has
        stopped is not a fault. The ending itself stays its companion's to
        write, as for every run; the flag makes it read "stopped".
        """
        lauf = self.holen(chat_id, nummer)
        if lauf is None or lauf.zustand != LAEUFT or lauf.prozess is None:
            return lauf
        lauf.stop_requested = True
        prozess = lauf.prozess
        log.info("Run #%s in chat %s stopped by the user: %s", nummer, chat_id, lauf.befehl)
        await prozessstopp.stop_watched(
            ended=lambda: lauf.zustand != LAEUFT,
            term=prozess.terminate,
            kill=prozess.kill,
        )
        return lauf

    def holen(self, chat_id: str, nummer: int) -> Lauf | None:
        for lauf in self._laeufe.get(chat_id, []):
            if lauf.nummer == nummer:
                return lauf
        return None

    def juengster(
        self, chat_id: str, befehl: str, seit: float | None = None
    ) -> Lauf | None:
        """The newest run of this chat that runs ``befehl``.

        The shell tool answers with text, and the answer's tool log needs
        the number of the run behind it — for a background start so the
        ending can be written onto the call later, for a foreground command
        so the terminal panel pairs call and run by number instead of by
        position. Looked up newest first, so two identical commands started
        one after the other each find their own run.

        ``seit`` is a ``time.monotonic()`` reading: only a run that began at
        or after it counts. The caller took it before the call went out, so
        a call that never started a run gets none — not the last run of the
        same command, started by an earlier call.
        """
        for lauf in reversed(self._laeufe.get(chat_id, [])):
            if lauf.befehl == befehl and (seit is None or lauf._begonnen >= seit):
                return lauf
        return None

    def abgeschlossene(self, chat_id: str) -> list[int]:
        """The numbers of the chat's finished background runs nobody has
        read yet — what ``als_gelesen_melden`` may mark once the request
        built right after this reading has gone out."""
        return [
            lauf.nummer
            for lauf in self._laeufe.get(chat_id, [])
            if lauf.hintergrund
            and lauf.zustand != LAEUFT
            and not lauf.gelesen
            and not lauf.vergessen
        ]

    def als_gelesen_melden(
        self, chat_id: str, nummern: Iterable[int] | None = None
    ) -> list[int]:
        """Marks finished background runs of the chat as read.

        Called when an answer starts in the chat: its history was built
        from the chat's rows, and every finished run's report is one of
        them. ``nummern`` says which runs those are — the reading the
        caller took before it read the rows (``abgeschlossene``). A run
        that ends after that reading is NOT covered — its report was not
        in the request — and waits for the next start; without ``nummern``
        every finished run counts. Each newly read run is announced on the
        chat's stream so the window can stop the card's pulse. Returns the
        numbers.
        """
        erlaubt = None if nummern is None else set(nummern)
        markiert: list[int] = []
        for lauf in self._laeufe.get(chat_id, []):
            if (
                not lauf.hintergrund
                or lauf.zustand == LAEUFT
                or lauf.gelesen
                or lauf.vergessen
                or (erlaubt is not None and lauf.nummer not in erlaubt)
            ):
                continue
            lauf.gelesen = True
            markiert.append(lauf.nummer)
            self.melden(chat_id, typ="lauf_gelesen", lauf=lauf.nummer)
        return markiert

    # --- Watchers --------------------------------------------------------

    def melden(self, chat_id: str, **daten: Any) -> None:
        # Its own position in the chat's history, carried on the event itself
        # — `EventSource` reconnects on its own after a dropped connection,
        # using the very same URL it was built with, `ab` included. Without
        # a way to tell "already applied" from "new" on the far side, that
        # replay would draw every line between the old `ab` and the drop a
        # second time. `n` is that way: a watcher remembers the highest one
        # it has seen and skips anything at or below it, however often the
        # same stretch is resent.
        verlauf = self._ereignisse.setdefault(
            chat_id, deque(maxlen=MAX_EREIGNISSE)
        )
        nummer = self._ereignisstand.get(chat_id, 0)
        daten = {"n": nummer, **daten}
        self._ereignisstand[chat_id] = nummer + 1
        # The deque drops its own oldest entry when it is full — O(1), and
        # it happens on EVERY line of a long build, which is why this is not
        # a list that gets sliced.
        verlauf.append(daten)
        for schlange in self._zuschauer.get(chat_id, set()):
            schlange.put_nowait(daten)

    def ereignisstand(self, chat_id: str) -> int:
        """How many events this chat has reported so far — what a fresh
        ``zuschauen(chat_id, ab=...)`` right after would need to skip.

        The count, not the length of what is kept: the buffer forgets its
        oldest entries (MAX_EREIGNISSE), and a caller handed that length
        would ask to resume from a position that passed long ago and get
        the whole buffer replayed on top of what it just fetched.
        """
        return self._ereignisstand.get(chat_id, 0)

    async def zuschauen(
        self, chat_id: str, *, ab: int = 0, herzschlag_sekunden: float = HERZSCHLAG_SEKUNDEN
    ) -> AsyncIterator[dict[str, Any] | None]:
        """Live events of this chat, resuming after ``ab`` already-seen ones.

        ``ab`` mirrors ``Generierung.zuschauen``: the count of events a
        watcher already has, so reattaching after a dropped connection does
        not repeat them and does not miss what arrived in between. Whoever
        specifies nothing gets the chat's events from the beginning.

        The queue is registered *before* the backlog is read, same as there:
        everything up to that point is already in ``_ereignisse``, everything
        after lands in the queue, and nothing in between can be lost.

        ``ab`` is an absolute position, and the buffer no longer starts at
        zero (MAX_EREIGNISSE) — so it is translated rather than used as an
        index. A watcher that was away for longer than the buffer holds asks
        for events nobody kept: it gets what is left, not an exception and
        not the whole history a second time.

        ``None`` is a heartbeat, yielded when nothing arrived within
        ``herzschlag_sekunden`` — waited for from inside this generator's own
        frame, on purpose. The caller used to wrap ``__anext__()`` itself in
        ``asyncio.wait_for`` from the outside instead: a timeout there
        cancels the task running that call, and that cancellation lands
        exactly where this generator is suspended (``await schlange.get()``).
        An async generator that lets a ``CancelledError`` escape is done for
        good — the very first heartbeat silently closed it, and every
        `__anext__()` after that just raised ``StopAsyncIteration``
        immediately, no matter what was still queued behind it. Timing out
        `schlange.get()` in here instead is an ordinary, local
        try/except around one ``await`` — nothing above it is ever touched,
        and the loop simply continues.
        """
        schlange: asyncio.Queue = asyncio.Queue()
        self._zuschauer.setdefault(chat_id, set()).add(schlange)
        verlauf = self._ereignisse.get(chat_id, ())
        # Where the buffer begins, in the same counting `ab` uses.
        erstes = self._ereignisstand.get(chat_id, 0) - len(verlauf)
        # Copied out BEFORE the first yield, exactly as the old slice did:
        # from here on this generator suspends between events, and what it
        # replays must not shift under it as new lines push old ones out.
        rueckblick = list(islice(verlauf, max(0, ab - erstes), None))
        try:
            for ereignis in rueckblick:
                yield ereignis
            while True:
                try:
                    yield await asyncio.wait_for(
                        schlange.get(), timeout=herzschlag_sekunden
                    )
                except asyncio.TimeoutError:
                    yield None
        finally:
            self._zuschauer.get(chat_id, set()).discard(schlange)

    # --- The kill switch --------------------------------------------------

    def _toeten(self, laeufe: Any) -> int:
        """Stops every run in `laeufe` that still holds a live process."""
        getoetet = 0
        for lauf in laeufe:
            if lauf.zustand != LAEUFT or lauf.prozess is None:
                continue
            try:
                lauf.prozess.kill()
                getoetet += 1
            except (ProcessLookupError, OSError):
                pass
            lauf.zustand = FEHLER
            lauf.prozess = None
        return getoetet

    def alle_toeten(self) -> int:
        """Stops everything still running. Called when the service goes down.

        And marks them forgotten, which is what stops their late news from
        arriving after the lights are out. A killed run's companion wakes at
        the closed pipe and reports exactly as a finished one does — the
        report lands in the chat, and the report WAKES THE MODEL
        (``app/hintergrundwecken.py``). Measured during shutdown: both
        writes landed after ``db.schliessen()``, and a whole answer was
        started against model servers that had already been stopped a few
        lines earlier.

        `vergessen()` is not used here: that one is for a chat that is gone
        and drops its counters with it. These runs' chats still exist — only
        the service does not.

        Marking alone dropped the report with the wake. A run lives in
        memory only, so after the next launch the chat held the "started
        run #3" tool result and nothing else: the reader saw no trace that
        the build was cut off, and the model, asked next, still took the
        run for pending. The closing line every finished run gets is
        written here instead — now, in this thread, while the database is
        still open — and only THEN is the run marked, so the companion that
        wakes at the closed pipe a moment later stays silent as before. The
        wake the report files is cancelled by the shutdown a few lines
        after this call (``app/main.py``), as it always was.
        """
        getoetet = 0
        for liste in self._laeufe.values():
            for lauf in liste:
                if lauf.zustand != LAEUFT:
                    continue
                getoetet += self._toeten([lauf])
                if lauf.art == ART_BEFEHL:
                    self.beenden(lauf, None, zustand=FEHLER)
                    if lauf.hintergrund and self.abschluss is not None:
                        self.abschluss(lauf, ABSCHLUSS_BEIM_BEENDEN)
                lauf.vergessen = True
        return getoetet

    def beim_vergessen(self, hoerer: Any) -> None:
        """Registers something that keeps its own record beside a run.

        This class deliberately knows nothing about what any particular kind
        of run carries — a caller that files extra data elsewhere says so
        here rather than making this one learn its vocabulary. Without it
        such a record outlives the run it belongs to, and the next run of the
        same number in the same chat reads the old one's data.
        """
        self._hoerer.append(hoerer)

    def vergessen(self, chat_id: str) -> None:
        """Drops everything this chat's runs left behind.

        Stops them first, and that is not a courtesy: `_laeufe` is the ONLY
        place a live subprocess is reachable from, so `alle_toeten()` — the
        switch that keeps a background command from outliving the service —
        would never see a run dropped here while it was still running. What
        is forgotten without being stopped is an orphan nobody can kill.

        A run that has already finished carries no process and is skipped,
        so the ordinary case (a chat deleted long after its commands ran) is
        exactly as it was.

        Killing is not enough on its own: a background command's companion
        task and a drawing job both hold their Lauf directly and report in
        AFTER the kill — a report that would setdefault() the purged event
        record straight back and file a message into the deleted chat. The
        `vergessen` mark on each run is what makes those late reports die
        quietly (zeile/beenden above, and the abschluss handler).
        """
        getroffene = self._laeufe.get(chat_id, ())
        self._toeten(getroffene)
        for lauf in getroffene:
            lauf.vergessen = True
        self._laeufe.pop(chat_id, None)
        self._startnummer.pop(chat_id, None)
        self._ereignisse.pop(chat_id, None)
        self._ereignisstand.pop(chat_id, None)
        for hoerer in self._hoerer:
            # A broken listener must not break the deletion for the rest —
            # same courtesy the event bus extends to its subscribers.
            try:
                hoerer(chat_id)
            except Exception:  # noqa: BLE001
                log.exception("A beim_vergessen listener failed")


# Process-wide, like the event bus: one program, one set of runs.
laeufe = Laufverwaltung()
