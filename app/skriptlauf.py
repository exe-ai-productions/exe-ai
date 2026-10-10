"""Starting a cron entry's script — a scheduled run without a model.

For a nightly backup, loading a language model in order to say "run the
backup" is nonsense. The script IS the work, so a cron entry may name one
and the program starts it directly.

**This is the one execution path in the program that does not pass Tor 3.**
Every tool call does (app/berechtigungen.py): it sees the tool's name AND its
arguments, and for an unattended run "ask" becomes "no", because there is
nobody there to answer. A script started from here runs with the user's full
rights and is asked about by nobody.

So the whole of its security sits BEFORE the start, and this module is where
it sits:

  * **Where it may live.** Only a file inside the scripts location
    (app/speicherorte.py). The name is resolved — links followed — at
    creation AND at every single firing, and has to come out inside that
    folder. A name that carries a path at all is refused before any of that.
  * **What is started.** The file itself and nothing else: no shell string,
    no arguments, nothing interpolated by a model. The working folder is the
    scripts folder.
  * **How long.** A limit, always. Whatever runs past it is killed and the
    run counts as failed.

The remaining lock is not here but in the tool (app/tools/cronjob.py): only a
chat may create such an entry. Without that one, the road is open — a page an
agent reads talks it into writing itself a script entry, and code runs
unattended past a gate that never saw it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from app import i18n, speicherorte
from app.no_console import no_window
from app.tools import shell

log = logging.getLogger(__name__)

# The named storage location these scripts live in (app/speicherorte.py). One
# name, so the folder can be moved from the interface like every other one and
# the check below always asks where it is NOW.
ORT = "scripts"

# What stands in the NOT NULL ``agent`` column of a script entry, and in the
# ``agent`` of the runs it fires. A marker rather than a nullable column: the
# column carries a foreign key's worth of meaning everywhere else in the
# program, and an empty one would have to be read as "unknown agent" in every
# place that shows one. Brackets can appear in no agent name — an agent is a
# file name and the interface's own pattern allows none — so this collides
# with nothing.
SKRIPT_AGENT = "(skript)"

# The reason an ended run carries when the script came back non-zero. Its
# sibling ``zeitgrenze`` is the shipped one for a run that was stopped.
GRUND_FEHLGESCHLAGEN = "skript_fehler"

# How long a script may run when the entry says nothing. The command tool's
# own default, so a script and a command a person watches start from the same
# number — and the entry may raise it, which is the whole reason it is a
# column (a backup must not die on a limit meant for a chat).
ZEITGRENZE_VORGABE = shell.ZEITGRENZE_SEKUNDEN


class SkriptVerboten(Exception):
    """The script was refused — nothing was stored, and nothing was run.

    Carries the KEY of the sentence and its values, not only the sentence.
    The refusal has two very different readers: a model, which is told in
    English prose like every other tool answer, and a person looking at the
    schedules panel, who was shown "Kann nicht starten — There is no script
    'x' in /Users/..." because the German wrapper was filled with an English
    middle.

    ``str()`` still yields the English sentence, so the tool, the log line
    and every existing caller read unchanged. Whoever wants it in the
    reader's language renders ``schluessel`` and ``werte`` through
    ``app/i18n.py`` — the same trick the catalogue key travelling instead of
    a note takes elsewhere in the program.
    """

    def __init__(self, schluessel: str, **werte: object) -> None:
        self.schluessel = schluessel
        self.werte = werte
        super().__init__(i18n.t(schluessel, i18n.STANDARDSPRACHE, **werte))


def ordner(config) -> Path:
    """Where the scripts live right now. Asked fresh every time on purpose:
    the folder can be moved from the interface while entries exist, and the
    next firing has to look in the new place."""
    return speicherorte.ort(config, ORT)


def _kein_pfad(name: str) -> str:
    """The name as a plain file name, or a refusal.

    First of the two halves of the folder guard, and the one that answers in
    the caller's own words: a name that spells out a path was never meant to
    be a file in the folder. ``..``, a leading slash and a backslash all get
    the same sentence, because they are all the same wish.
    """
    name = str(name or "").strip()
    if not name:
        raise SkriptVerboten("fehler.skript_leer")
    if name != Path(name).name or name in (".", ".."):
        raise SkriptVerboten("fehler.skript_mit_pfad")
    return name


# What Windows starts, told by the extension: it has no execute bit, and
# ``os.access(X_OK)`` is true there for every file that exists — so a .txt
# counted as startable and a .sh started into "not a valid Win32 application".
# These five and nothing else, a shell script never (the owner's decision).
WINDOWS_STARTABLE = (".exe", ".bat", ".cmd", ".ps1", ".py")


def _python_on_windows() -> str | None:
    """The Python that runs a .py script on Windows: the one on the path,
    else the launcher. Neither — then a .py cannot be started here."""
    return shutil.which("python") or shutil.which("py")


def startable(path: Path, platform: str | None = None) -> bool:
    """Whether this file can be started here — the one answer for the
    listing and for the start.

    On the Mac and Linux the execute bit decides, as before. On Windows the
    extension does (``WINDOWS_STARTABLE``); a .py also needs a Python to be
    found. ``platform`` is a parameter so a test can ask for the other
    system without rewriting ``sys.platform``.
    """
    if (platform or sys.platform) != "win32":
        return os.access(path, os.X_OK)
    extension = path.suffix.lower()
    if extension == ".py":
        return _python_on_windows() is not None
    return extension in WINDOWS_STARTABLE


def command_line(path: Path, platform: str | None = None) -> list[str]:
    """The command line that starts the script: the file alone, except on
    Windows, where the extension names the program that runs it — Windows
    reads no ``#!`` line. A .ps1 goes to PowerShell without profile and
    without the execution policy in the way; a .py to the Python found by
    ``startable``. .exe, .bat and .cmd start by themselves.
    """
    if (platform or sys.platform) != "win32":
        return [str(path)]
    extension = path.suffix.lower()
    if extension == ".ps1":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path)]
    if extension == ".py":
        return [_python_on_windows() or "python", str(path)]
    return [str(path)]


def geprueft(wurzel: Path, name: str) -> Path:
    """The absolute path of a script that may be started, or a refusal.

    ``wurzel`` is the scripts folder as it stands right now, handed in rather
    than looked up: the two callers reach it differently — the firing loop has
    the configuration, the tool has a registry that was built without one —
    and the check must not depend on which of them is asking.

    Called at creation and again at every firing. Both, not one: the folder
    can be moved, the file can be swapped for a link, and permissions can
    change — a check that only ever ran when the entry was written would be
    a statement about a file that no longer exists.

    ``resolve()`` is what makes the second half work. It follows links, so a
    link INSIDE the folder pointing at something outside comes out with its
    real path and fails the containment test — which is exactly the trick a
    plain string comparison on the given name would wave through.
    """
    name = _kein_pfad(name)
    wurzel = Path(wurzel).resolve()
    ziel = (wurzel / name).resolve()
    if ziel == wurzel or not ziel.is_relative_to(wurzel):
        raise SkriptVerboten("fehler.skript_fuehrt_hinaus", name=name, ordner=wurzel)
    if not ziel.is_file():
        raise SkriptVerboten("fehler.skript_fehlt", name=name, ordner=wurzel)
    if not startable(ziel):
        raise SkriptVerboten(
            "fehler.skript_nicht_ausfuehrbar", name=name, ordner=wurzel
        )
    return ziel


ABBRUCH_TEXT = "Cancelled — the script was stopped."

# The reason carried by the cancellation a shutdown raises. Nothing reads it —
# it is what stands in a log line or a traceback when someone asks why a run
# ended without an ending.
DIENSTENDE_TEXT = "Service shutting down — the script was stopped."


@dataclass(frozen=True)
class Ergebnis:
    """One finished script run: what it wrote, how it ended, and whether the
    time limit or the stop button is what ended it."""

    ausgabe: str
    code: int | None
    abgelaufen: bool
    # Stopped by hand — the cancel button, or the deletion of the job. Its own
    # field rather than a reading of ``code``, because a run the user stopped
    # is not a failed run and must not reach the failure counter.
    abgebrochen: bool = False
    # What the script really wrote, before ``_antwort_bauen`` dressed it for
    # display. Kept beside the finished text on purpose — see letzte_zeile.
    zeilen: tuple[str, ...] = ()

    @property
    def erfolgreich(self) -> bool:
        """Exit code 0 and nothing else — the one definition a script run has
        without a model to interpret anything for it."""
        return self.code == 0

    @property
    def letzte_zeile(self) -> str:
        """The last line the script wrote, for the announcement (F3). A
        script entry has no task text to announce, and its whole output is
        not a notification — the last line is what a script that reports
        anything reports.

        Read from the RAW lines, not from the finished text. ``_antwort_bauen``
        appends ``[exit code 1]`` as the last line of anything that ended
        badly, and cuts the middle out of anything long and leaves a marker
        there — so on exactly the two runs a person wants to be told about, a
        failure and a talkative one, the "last line" was the machinery's own
        note and never the script's error. Announced was
        ``Failed — kaputt.sh — [exit code 1]``, which says nothing at all.

        With no raw lines to read — the time limit, an abort, a file that
        could not be started — the sentence written for that case is the
        whole output and is what goes out.
        """
        quelle = self.zeilen or tuple(self.ausgabe.splitlines())
        zeilen = [z.strip() for z in quelle if z.strip()]
        return zeilen[-1] if zeilen else ""


async def starten(
    pfad: Path,
    wurzel: Path,
    grenze: int,
    *,
    abbruch: asyncio.Event | None = None,
    lauf=None,
) -> Ergebnis:
    """Runs the script and waits for it, up to ``grenze`` seconds.

    ``create_subprocess_exec`` with the file and nothing after it (on
    Windows with the program its extension names in front, ``command_line``):
    no shell, no argument list, nothing a model wrote anywhere near the
    command line.
    The working folder is the scripts folder, so a script may use relative
    paths of its own without knowing where it was started from.

    A file with no ``#!`` line cannot be executed at all, and the operating
    system says so as an ``OSError`` rather than as an exit code. Caught here
    and turned into a failed run with that sentence in its output — silently
    reading it as success is the one ending this must never have.

    ``abbruch`` is the run's cancel signal (app/generationen.py). Cancelling
    is cooperative everywhere in this program — the signal is set, and the run
    is expected to notice — and a script run had nothing that ever looked at
    it: the stop button said "cancelling", the script ran to its end, and the
    ending was then booked as a failure against the entry's failure budget.
    Waited on here BESIDE the process, so noticing costs no polling and the
    process dies with the signal rather than after it.

    ``lauf`` is the run record the service's kill switch walks when it shuts
    down (app/tools/hintergrund.py). A script gets its own session so the time
    limit can take its children with it — and that same session is what lets
    it outlive the service, which is how a nightly backup ended up running
    twice: the orphan kept going, the database row was set to "interrupted" on
    the next start, and the next due time found nothing running and started a
    second copy. Filed here, it goes down with the service like every command
    does.

    **And the run has to hear that switch, not just feel it.** Killing the
    script alone was half a fix: the process died and the run went on through
    its own loop and booked what it saw — ``gescheitert``, reason
    ``skript_fehler``, result ``[exit code -9]``. Measured with a limit of one
    failed run: the entry lost its failure budget, switched itself off, and
    sent two "Failed" notifications — because the user restarted the program
    while the nightly backup was running. A model run has none of this: it is
    not killed on the way down at all, its row stays on ``laeuft``, and the
    next start turns it into ``unterbrochen`` (app/main.py, ``beim_start_-
    aufraeumen``). That is the honest ending, and it is the one taken here:
    the switch cancels the run, so nothing at all is booked and the row is
    found on ``laeuft`` at the next start, exactly like the model's.
    """
    try:
        prozess = await asyncio.create_subprocess_exec(
            *command_line(pfad),
            cwd=str(wurzel),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # Its own process group, so the time limit below can take the
            # whole tree down. Measured, not assumed: a script whose last
            # line is `sleep 30`, stopped after one second, went on for the
            # full thirty. Killing the shell alone leaves its children
            # running, they keep the output pipe open, and the wait for the
            # end of the run waits for THAT — a limit that stops nothing and
            # reports a stop is worse than no limit at all.
            start_new_session=True,
            **no_window(),
        )
    except OSError as fehler:
        return Ergebnis(
            ausgabe=f"{pfad.name} could not be started: {fehler.strerror or fehler}. "
            "A script needs a '#!' line and the execute bit.",
            code=None,
            abgelaufen=False,
        )

    # Set by the service's kill switch, from inside the kill itself — the
    # switch has no other way of announcing itself, and without it this run
    # only ever saw a process that suddenly died.
    dienstende = asyncio.Event()
    if lauf is not None:
        # As a group, not as a bare process: the switch that keeps a run from
        # outliving the service calls kill() on what it finds here, and a
        # script's children must not be what is left behind.
        lauf.prozess = shell.Prozessgruppe(prozess, beim_toeten=dienstende.set)

    # Four ways this can end, and all four are waited for at once: the script
    # finishes, the user cancels, the limit runs out, or the service goes
    # down. asyncio.wait rather than wait_for, because the signals are things
    # to wait on beside the process and wait_for knows only one.
    kommunikation = asyncio.ensure_future(prozess.communicate())
    warten = [kommunikation]
    signalwarter = asyncio.ensure_future(abbruch.wait()) if abbruch is not None else None
    if signalwarter is not None:
        warten.append(signalwarter)
    dienstwarter = asyncio.ensure_future(dienstende.wait())
    warten.append(dienstwarter)
    try:
        fertig, _offen = await asyncio.wait(
            warten, timeout=grenze, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        for warter in (signalwarter, dienstwarter):
            if warter is not None and not warter.done():
                warter.cancel()

    if kommunikation not in fertig or dienstwarter in fertig:
        # Killed, not abandoned: a script left running keeps writing into the
        # user's folders long after the run that started it was booked — and
        # the whole group with it, children included (see the start above).
        # The service ending is asked about FIRST: it has already killed the
        # group, so the finished read it leaves behind would otherwise read as
        # an ordinary failed run.
        beendet_sich = dienstwarter in fertig
        abgebrochen = signalwarter is not None and signalwarter in fertig
        if not beendet_sich:
            shell.gruppe_toeten(prozess)
        # The read has to be let go of by hand. It is waiting on a pipe, and a
        # child that escaped the group (a script calling setsid itself) holds
        # that pipe open for good — an abandoned task there would keep this
        # run's output buffers alive for the rest of the program's life.
        kommunikation.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await kommunikation
        # Not ``prozess.wait()``: with that same escaped child holding the
        # pipe, a waiter registered after the kill is never woken and this
        # line blocks for the life of the program — the job stays on "laeuft",
        # the schedule's "one at a time" rule blocks every following due time,
        # and the stop button reaches nothing. See shell.ernten.
        await shell.ernten(prozess)
        if beendet_sich:
            # Nothing is booked and nothing is announced: the run is cancelled
            # where it stands, its finally unsubscribes it, and the row stays
            # on ``laeuft`` until the next start writes ``unterbrochen`` over
            # it. That is what a model run leaves behind on a shutdown, and it
            # is the truth about a run nobody finished.
            raise asyncio.CancelledError(DIENSTENDE_TEXT)
        if abgebrochen:
            return Ergebnis(
                ausgabe=ABBRUCH_TEXT, code=None, abgelaufen=False, abgebrochen=True
            )
        return Ergebnis(
            ausgabe=f"Stopped after {int(grenze)} seconds — the script was still running.",
            code=None,
            abgelaufen=True,
        )

    roh_aus, roh_fehler = kommunikation.result()
    zeilen = (*_zeilen(roh_aus), *_zeilen(roh_fehler))
    # The same shape the command tool gives a finished process, from the same
    # function: output, then stderr under its own heading, then the exit code
    # when it is not zero. One truth for how a process reads, so a script run
    # in the history looks like every other command in the program.
    ausgabe = shell._antwort_bauen(
        _zeilen(roh_aus), _zeilen(roh_fehler), prozess.returncode
    )
    return Ergebnis(
        ausgabe=ausgabe,
        code=prozess.returncode,
        abgelaufen=False,
        zeilen=zeilen,
    )


def _zeilen(roh: bytes | None) -> list[str]:
    """Decoded output as lines. Undecodable bytes are replaced rather than
    raised over: a script's stray byte must not turn a finished run into a
    crash in the bookkeeping behind it."""
    if not roh:
        return []
    return roh.decode("utf-8", errors="replace").splitlines()
