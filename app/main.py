"""Entry point of the service.

One process, one port: FastAPI answers the API and serves the frontend's
static files at the same time. An nginx in front is possible at any time
without changing anything here.

Started in production via systemd, by hand:

    .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import socket
import sqlite3
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import atomic_file
from app import __version__
from app import input_errors, model_image, sprachwahl
from app import folder_names
from app.i18n import t
from app import agent_report, instanzschloss
from app.api.v1 import router as api_v1_router
from app.api.v1.bilder import empty_scratch_pictures
from app.api.v1.health import _health_ermitteln
from app.modelldownload import Modelldownload
from app import agentenserver, einbettungsserver, sprachserver
from app.bildrunner import Bildrunner
from app.bildturbo import Bildturbo
from app.modellrunner import Modellrunner, begleiter_einsortieren
from app import modellvorlauf
from app import runnerzustand
from app.sddownload import Sddownload
from app.serverdownload import Serverdownload
from app.config import Config, abgelegte_schluessel_melden, get_config
from app.configwanderung import file_tool_added
from app.paketierung import ressourcen
from app.db import datenbank_oeffnen, repositories_erstellen
from app.discovery import Discovery
from app import ereignisstrom
from app.events import Ereignisse, bus
from app.generationen import Generierungsverwaltung
from app import hintergrundwecken
from app.hintergrundmeldung import anmelden as hintergrundmeldung_anmelden
from app.inhaltssicherheit import (
    KOPFZEILE as CSP_KOPFZEILE,
    REGEL as CSP_REGEL,
)
from app.protokoll import ProtokollMiddleware, logging_einrichten, speicher_mb
from app.speicherorte import bildkopien_verzeichnis, ort
from app.tools import WerkzeugRegistry
from app.tools.aufbau import registry_bauen
from app.tools.hintergrund import laeufe
from app.tools.mcp_auth import AuthSpeicher, OAuthVermittler
from app.wecker import Wecker
from app import zwischenstand
from app.no_console import no_window

log = logging.getLogger(__name__)

# The interface ships with the program and is only ever read, so it comes
# from the shipped folder and not from beside the working directory.
STATIC_VERZEICHNIS = ressourcen() / "static"


# --- One data folder, more than one service --------------------------------
#
# ``EXE_AI_PORT`` exists so that a trial run can sit on its own port beside
# the running program (fenster-electron/main.js), and the window's port probe
# keeps a SECOND window from becoming a second service on the SAME port. What
# nothing keeps apart is the data folder: ``data_dir`` does not vary with the
# port, so two services write one database file — in WAL, with a busy
# timeout, so both writes land.
#
# The picture server met this first and answered it: the data folder is
# shared between instances, and the app's own port is the one thing they
# cannot share, so it is what tells them apart (app/bildturbo.py). This is
# the same answer for the service itself.
#
# It is needed because the startup cleanups below ask what state a row is in
# and never who put it there. Measured with two services on 8090 and 8091
# against one database and one answer in flight: starting the second stamped
# the first one's streaming answer 'abgebrochen', moved its running job to
# 'unterbrochen', cleared the status that job would have resumed from, and
# wrote a cron entry to run it a second time.
INSTANZNOTIZ = ".dienst"

# The lock this process holds on its own note for as long as it runs. Held
# here rather than on ``app.state`` because the guard reads and writes it
# from plain functions, and there is one service per process either way.
_schloss: instanzschloss.Schloss | None = None


def _instanznotiz(config: Config) -> Path:
    """This instance's claim on the shared data folder.

    Named by the app port, the same way the picture server names its own
    note — a claim that two instances could overwrite would say nothing.
    """
    return config.datenverzeichnis / f"{INSTANZNOTIZ}-{int(config.app.port)}.json"


def _instanzschloss(config: Config, port: int) -> Path:
    """The file the claim's lock lives on, beside the note it belongs to."""
    return config.datenverzeichnis / f"{INSTANZNOTIZ}-{int(port)}.lock"


def _antwortet(port: int, frist: float = 0.4) -> bool:
    """Is a service listening on that port?

    The window's own test for "one is already answering", down to its 400 ms
    (fenster-electron/main.js) — and the one thing a recycled process id
    cannot fake, because a stranger that inherited the number does not
    inherit the socket. A killed service that has not been reaped yet
    answers ``os.kill(pid, 0)`` as if it were alive and this as what it is.

    Blocking, on the startup loop, the way everything else the lifespan does
    before it serves is blocking. It costs nothing at all where nobody left
    a note, which is every ordinary installation.
    """
    with socket.socket() as dose:
        dose.settimeout(frist)
        try:
            return dose.connect_ex(("127.0.0.1", port)) == 0
        except OSError:
            return False


def _lebende_instanz(config: Config) -> int | None:
    """The port of ANOTHER service using this data folder, or None.

    Read before this instance writes its own note, so every note found here
    is somebody else's claim.

    Three facts, and each covers a blind spot of the others. The process
    id says the writer is gone the moment it is — the ordinary case after a
    crash, for one syscall. The lock (``app/instanzschloss.py``) says the
    writer is alive: nobody but a live process can hold it, and the kernel
    drops it when that process dies, so a number the system handed on to a
    stranger holds nothing. The port says the same for a service that
    left no lock behind — an older build, or a folder where the lock could
    not be taken.

    The lock is what covers the window between the note and the socket.
    The note is written inside the lifespan, and the socket is bound only
    after the whole lifespan has run — seconds of model probes and server
    starts. A second service starting in that window found a live id on a
    silent port, took the note for stale and threw it away, and the first
    service then ran for the rest of its life with no claim at all: the
    next start on the folder stamped its live answer 'abgebrochen'.

    A note whose holder is gone and whose port answers nothing names no
    service, so it goes. Leaving it would hold the cleanup off for as long
    as it lay there — and a stranded row that is never cleaned is the very
    thing the cleanup exists for. A note carrying OUR id is left alone and
    never counted: one process is one service, so that is this run's own
    claim (or a predecessor whose number we inherited, which is gone either
    way).
    """
    for notiz in sorted(config.datenverzeichnis.glob(f"{INSTANZNOTIZ}-*.json")):
        try:
            daten = json.loads(notiz.read_text(encoding="utf-8"))
            pid, port = int(daten["pid"]), int(daten["port"])
        except (OSError, ValueError, KeyError, TypeError):
            # Unreadable is not the same as stale: a scanner landing in the
            # moment another service writes its note read half a file, took
            # the LIVE claim for garbage and deleted it. Notes are written
            # atomically now, so this is a leftover — but only age proves
            # that, not one bad read.
            try:
                # Either way round: a stamp from the future (a clock that
                # jumped, a folder copied from another machine) is as far
                # from "being written right now" as an old one.
                alter = abs(time.time() - notiz.stat().st_mtime)
            except OSError:
                continue
            if alter > 60:
                notiz.unlink(missing_ok=True)
            continue
        if pid == os.getpid():
            continue
        schloss = _instanzschloss(config, port)
        # Asked once: what the process id says is handed on, not asked again.
        gone = _prozess_gestorben(pid)
        if gone:
            notiz.unlink(missing_ok=True)
            # The lock file is a signal of its own (the scan below reads
            # it): a service starting on that port right now holds it
            # before it has written its note, and deleting the file from
            # under it would blind that scan. Held means somebody is there.
            if _service_alive(schloss, lambda: False):
                return port
            _lock_file_removed(schloss)
            continue
        if _service_alive(schloss, lambda: True) or _antwortet(port):
            return port
        notiz.unlink(missing_ok=True)
        _lock_file_removed(schloss)
    # The lock is taken BEFORE the note is written (see _instanz_eintragen),
    # so a start caught between the two shows a held lock and no note. Two
    # services starting at once used to both see an empty folder and both
    # run the cleanup; whoever locks first is visible here now.
    return _foreign_lock(config)


def _foreign_lock(config: Config) -> int | None:
    """The port of ANOTHER service holding a lock on this data folder RIGHT
    NOW, or None.

    The lock is the one fact about a service that is still true when it is
    read: a note says somebody claimed the folder, and its writer can be
    gone a moment later, but a held lock dies with its holder. Asked where
    the answer has to be current rather than where it was true once — the
    startup cleanup's question whether a second service's rows are somebody's
    live work. The liveness look at the top of the lifespan answers a wider
    question (notes and ports, not only locks) and is asked once per start.

    Our own port is NOT skipped here: asked before this process takes its
    own lock, a held lock on our port can only be somebody else's — a
    service starting on the very port we are about to bind, whose running
    work the cleanup would otherwise declare stranded. Once this process
    holds its own, that one is skipped and it is its own (`_schloss`).
    """
    eigenes = _instanzschloss(config, int(config.app.port)) if _schloss is not None else None
    for schlossdatei in sorted(config.datenverzeichnis.glob(f"{INSTANZNOTIZ}-*.lock")):
        try:
            port = int(schlossdatei.stem.rsplit("-", 1)[1])
        except (ValueError, IndexError):
            continue
        if eigenes is not None and schlossdatei == eigenes:
            continue
        if _service_alive(schlossdatei, lambda: _pid_alive(_noted_pid(config, port))):
            return port
    return None


def _lock_file_removed(lock_file: Path) -> None:
    """Removes the lock file of a service that is gone. One that cannot be
    removed — a folder in its place, a file the system will not let go —
    stays: it costs the next scan a look, never the start."""
    try:
        lock_file.unlink(missing_ok=True)
    except OSError as error:
        log.debug("Lock file %s not removed: %s", lock_file, error)


def _fremder_auf_unserem_port(config: Config) -> bool:
    """Whether a LIVING service already holds the very port we are about to
    bind.

    Asked separately from `_lebende_instanz`, which answers a different
    question: it returns the FIRST living instance it finds, so with one
    service alive on a lower port it never gets as far as ours. Comparing
    its answer to our own port therefore misses exactly the case that must
    not be missed — two services on ONE port write the same owner stamp,
    so every row of the one still running looks like ours, and a cleanup
    narrowed to "our own rows" would end its live run and hand its note to
    us to delete on the way out.

    Asked before this process takes its own lock, so a held lock on our
    port is somebody else's. Nothing is deleted here: the scan in
    `_lebende_instanz` does the tidying, and this look must not race it.
    """
    port = int(config.app.port)
    # A free lock and one that answers nothing both leave it to the note.
    return instanzschloss.gehalten(_instanzschloss(config, port)) is True or _pid_alive(
        _noted_pid(config, port)
    )


def _noted_pid(config: Config, port: int) -> int | None:
    """The process id the note for ``port`` names, or None where there is
    no readable note."""
    try:
        daten = json.loads(
            (config.datenverzeichnis / f"{INSTANZNOTIZ}-{port}.json").read_text(
                encoding="utf-8"
            )
        )
        return int(daten["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _pid_alive(pid: int | None) -> bool:
    """Whether ``pid`` names another process that is not certainly gone
    (``_prozess_gestorben``). This process itself is no other service."""
    return pid is not None and pid != os.getpid() and not _prozess_gestorben(pid)


def _service_alive(lock_file: Path, process_alive: Callable[[], bool]) -> bool:
    """Is the service behind ``lock_file`` alive? The one place this is
    decided. The lock answers where it can: held means alive, free means
    gone. Where it cannot be taken at all — a file that cannot be opened, a
    disk without locks — it answers nothing, and the note's process id
    decides instead (``process_alive``, asked only then): alive unless
    certainly gone. Only a service whose process is really gone is cleaned
    up then."""
    held = instanzschloss.gehalten(lock_file)
    if held is None:
        return process_alive()
    return held


def _tasklist_nennt(ausgabe: str, pid: int) -> bool:
    """Whether ``tasklist /FO CSV`` output lists the process ``pid``.

    Compared field by field, not as a substring of the whole line: the
    memory column ("14.321 K") can contain the digits of a dead id, and
    "4321" in that line called the dead service alive — which is exactly
    the failure the probe exists to end. Read as the CSV it is, not split
    on commas: an image name with a comma in it would shift the fields and
    call a LIVE process gone. tasklist's "no tasks" notice is one field
    wide and drops out. Kept apart from the call so it can be measured on
    a machine without a tasklist.
    """
    import csv

    zeilen = [z for z in csv.reader(ausgabe.splitlines()) if len(z) > 1]
    return any(z[1].strip() == str(int(pid)) for z in zeilen)


def _prozess_gestorben(pid: int) -> bool:
    """Is the process behind that id certainly gone?

    Only a POSIX signal 0 can say so without touching the process. On
    Windows ``os.kill`` is not a probe: any signal but the two console
    events is ``TerminateProcess``, and a missing id raises a plain
    ``OSError`` rather than ``ProcessLookupError`` — so the "probe" would
    kill the service it was asked about and call every dead id alive. There
    the answer is "not known", and the port decides alone.

    Anything that is not a clear "gone" counts as alive: an id we may not
    signal exists, and an id we cannot ask about must not lose its claim on
    a guess.
    """
    if os.name == "nt":  # pragma: no cover - the Windows half
        # `os.kill` is no probe here (see above), but the process list is:
        # a missing id in tasklist's answer is a clear "gone". Without this
        # a dead service whose port some OTHER program later took was
        # counted alive forever, and the cleanup never ran again on that
        # folder — every crash from then on stranded its rows for good.
        import subprocess

        try:
            lauf = subprocess.run(
                ["tasklist", "/FI", f"PID eq {int(pid)}", "/NH", "/FO", "CSV"],
                capture_output=True, text=True, timeout=5, check=False,
                # The system's own code page ("locale" is Python's name for
                # it) — only the id is read —, and a byte it cannot decode
                # must not raise past the OSError catch below and stop the
                # service from starting.
                encoding="locale",
                errors="replace",
                # No console window flashing up for every old note in the
                # packaged app — the same flag the other subprocess calls use.
                **no_window(),
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        if lauf.returncode != 0 or not lauf.stdout:
            return False
        return not _tasklist_nennt(lauf.stdout, pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


def _instanz_eintragen(config: Config, *, gleicher_port: bool) -> bool:
    """Says out loud that this process is using this data folder, so the next
    service to start does not take its running work for stranded work.

    Answers whether this service may reach into the folder: the lock on it
    is held from here on — taken here and given back in
    ``_instanz_austragen`` — or it cannot be taken at all, on a disk that
    gives no lock. The carrying over of folders runs only then, and its
    second half — the stored paths following the note — does too (the
    lifespan): renaming reaches into the folder, and a folder two services
    rename at once ends up in two places. Every error a try at the lock
    meets counts as "cannot be taken at all", a lock file that is broken —
    a folder in its place, a file that cannot be opened — included: nobody
    can hold that one either. Without any lock, whether another
    service is alive is told by its note's process id (``_service_alive``,
    read into the lifespan's ``fremder_port``), and the lifespan moves only
    where that names nobody — the one guard left on such a disk.

    Not written when a living service sits on OUR port
    (`_fremder_auf_unserem_port`, which asks about that one port rather than
    reading whichever port the folder scan happened to name first): its note
    IS this note, and overwriting it would put our id on a claim that is not
    ours. A start on a taken port does not get far — the socket comes after
    the lifespan and the bind fails — and the shutdown that follows would
    then take that note with it, leaving the one still running with no claim
    at all. The window's own probe keeps this off the ordinary path
    (fenster-electron/main.js); a second service started by hand does not go
    through it.
    """
    global _schloss
    if gleicher_port:
        return False
    # The lock FIRST, then the note. The other way round left a window in
    # which the claim existed with nothing defending it — a scanner found a
    # note whose lock was free and whose socket was silent, and cleaned a
    # service that was seconds from binding. A held lock is what the scan
    # now reads as "somebody is starting here".
    _schloss, lock_error = instanzschloss.try_lock(
        _instanzschloss(config, int(config.app.port))
    )
    if lock_error is not None:
        log.debug("Instance lock cannot be taken at all: %s", lock_error)
    elif _schloss is None:
        log.debug("Instance lock cannot be held")
    try:
        # Atomically: a scanner must see the old note, the new note, or no
        # note — never half a file (that half was once read as garbage and
        # the live claim went with it).
        ziel = _instanznotiz(config)
        atomic_file.write(
            ziel, json.dumps({"pid": os.getpid(), "port": int(config.app.port)})
        )
    except OSError:
        # A folder we cannot write is a problem the database will report far
        # more loudly a moment later; losing the note only costs the guard.
        log.debug("Instance note cannot be written", exc_info=True)
    # About the lock, not the note: a note that could not be written still
    # leaves the folder claimed — the lock is what the next start reads.
    # Where no lock can be had at all, the note's process id is what the
    # next start reads instead (``_service_alive``).
    return _schloss is not None or lock_error is not None


def _instanz_austragen(config: Config) -> None:
    """Withdraws the claim on a clean stop. A kill skips this, which is
    exactly what the liveness test in ``_lebende_instanz`` is there for.

    Only a note carrying our own id is ours to take back. The name is made
    from the port alone, so a note under it can belong to somebody else, and
    withdrawing a claim we never made would hand that service's running work
    to the next start as stranded work.
    """
    global _schloss
    notiz = _instanznotiz(config)
    unsere = False
    try:
        daten = json.loads(notiz.read_text(encoding="utf-8"))
        unsere = int(daten["pid"]) == os.getpid()
        if unsere:
            notiz.unlink(missing_ok=True)
    except (OSError, ValueError, KeyError, TypeError):
        log.debug("Instance note cannot be removed", exc_info=True)
    # The lock is ours whatever the note says — a note that could not be
    # written, or one a stranger overwrote, must not keep it held: the
    # next lifecycle in this process could not take it again. Released
    # first, so the file can go on every platform. The FILE goes only with
    # our own note: under a stranger's note it is the stranger's lock.
    instanzschloss.loslassen(_schloss)
    _schloss = None
    if unsere:
        _instanzschloss(config, int(config.app.port)).unlink(missing_ok=True)


def _startbereinigung(
    app: FastAPI, config: Config, *, nur_eigene: bool = False
) -> None:
    """What was still running at the last stop is now, honestly, over.

    Runs beside a second service on the same data folder too, which is new.
    The premise its three writes share — that the last stop was OURS — is
    no longer something the caller has to establish for them: every row put
    on 'laeuft' carries the port of the service that wrote it
    (`dienst_port`, app/db/schema.sql), so each of them can ask who owns a
    row instead of only what state it is in. That is what used to cost this
    cleanup its whole run: it stayed out entirely while a second service
    was up, and every row the other one stranded stayed 'laeuft' for good.

    ``nur_eigene`` narrows all three writes to rows carrying our own port —
    set when a second, LIVING service holds a lock on another port. Left
    false, they clean every 'laeuft' row whoever wrote it, which is right
    exactly when nobody else is on the folder: rows of a service that died
    on another port, and rows naming no owner at all, have nobody left to
    come back for them.

    The caller leaves this out entirely for a second service on the SAME
    port — there the stamp cannot tell the two apart (see the lifespan).
    """
    # Clean up jobs (6.2): whatever was still running at the last stop is now,
    # honestly, interrupted. Pending confirmation prompts remain answerable.
    unterbrochen = app.state.repositories.auftraege.beim_start_aufraeumen(
        nur_eigene=nur_eigene
    )
    if unterbrochen:
        log.info(
            "%d job(s) stood at 'laeuft' and are now 'unterbrochen'",
            unterbrochen,
            extra={"ereignis": "auftraege_aufgeraeumt", "anzahl": unterbrochen},
        )
    # The same for answers. A chat run has no `auftraege` row to be tidied
    # up in the block above; its state lives on the message itself, and it
    # only ever leaves 'laeuft' through the run's own closing write. Killed
    # mid-stream, that row keeps claiming to be live for good — the window
    # draws it as a running answer forever, and the context bar reads its
    # token count as the current one.
    abgebrochen = app.state.repositories.messages.beim_start_aufraeumen(
        nur_eigene=nur_eigene
    )
    if abgebrochen:
        log.info(
            "%d answer(s) stood at 'laeuft' and are now 'abgebrochen'",
            abgebrochen,
            extra={"ereignis": "antworten_aufgeraeumt", "anzahl": abgebrochen},
        )
    # Every one of them that has a status from the periodic
    # write during its run gets a resumption scheduled — not only the ones
    # that already belonged to a restart chain.
    fortgesetzt = zwischenstand.nach_neustart_fortsetzen(
        config, app.state.repositories, nur_eigene=nur_eigene
    )
    if fortgesetzt:
        log.info(
            "%d interrupted job(s) continue from their saved state",
            fortgesetzt,
            extra={"ereignis": "auftraege_fortgesetzt", "anzahl": fortgesetzt},
        )
    # The smaller copies for the model are a cache, not an archive: what its
    # picture no longer exists for goes now. The pictures sit
    # under their named location, the copies under theirs — no port or owner
    # question in this one, the cache belongs to this installation alone.
    entfernt = model_image.aufraeumen(
        ort(config, "images"),
        bildkopien_verzeichnis(config),
    )
    if entfernt:
        log.info(
            "%d picture copy(ies) without their picture removed",
            entfernt,
            extra={"ereignis": "bildkopien_aufgeraeumt", "anzahl": entfernt},
        )
    # The picture studio's working pictures were made for draws of the
    # window that was open before this start; none of them is asked for
    # again. Beside a second, living service they stay: a draw of its
    # window may still read them.
    if not nur_eigene:
        emptied = empty_scratch_pictures(config)
        if emptied:
            log.info(
                "%d working picture(s) of the picture studio removed",
                emptied,
                extra={"ereignis": "scratch_pictures_emptied", "anzahl": emptied},
            )


def _standard_abonnenten_anmelden() -> None:
    """Logging hangs off the event system — not scattered through the modules' code."""

    async def chat_erstellt(chat_id: str, **_rest) -> None:
        log.info("Chat created: %s", chat_id, extra={"ereignis": "chat_erstellt"})

    async def endpunkt_status(endpoint_id: str, erreichbar: bool, **_rest) -> None:
        log.info(
            "Endpoint %s is now %s",
            endpoint_id,
            "reachable" if erreichbar else "not reachable",
            extra={
                "ereignis": "endpunkt_status",
                "endpunkt": endpoint_id,
                "erreichbar": erreichbar,
            },
        )

    async def antwort_fertig(
        endpoint_id: str = "", model: str | None = None, stats: dict | None = None, **_rest
    ) -> None:
        messwerte = stats or {}
        # The model beside the endpoint, where one was named: a proof asked
        # for one particular model has to show which ran, and "omlx" names
        # the server. A server that names no model and a request that asked
        # for none leaves the line as it always was (app/providers/openai_kompatibel.py).
        log.info(
            "Answer from %s%s: %s tok/s, %s s%s",
            endpoint_id,
            f" ({model})" if model else "",
            messwerte.get("tokens_pro_sekunde", "?"),
            messwerte.get("dauer_sekunden", "?"),
            " (aborted)" if messwerte.get("abgebrochen") else "",
            extra={
                "ereignis": "antwort_fertig",
                "endpunkt": endpoint_id,
                "modell": model,
                "tokens_pro_sekunde": messwerte.get("tokens_pro_sekunde"),
                "dauer_sekunden": messwerte.get("dauer_sekunden"),
                "erstes_token_nach_sekunden": messwerte.get("erstes_token_nach_sekunden"),
                "abgebrochen": bool(messwerte.get("abgebrochen")),
                "werkzeuge": len(messwerte.get("werkzeuge") or []),
                "speicher_mb": speicher_mb(),
            },
        )

    async def auftrag_beendet(
        auftrag_id: str = "", agent: str = "", ausgang: str = "",
        grund: str | None = None, **_rest,
    ) -> None:
        log.info(
            "Job %s is %s (%s)",
            auftrag_id,
            ausgang,
            grund or "-",
            extra={
                "ereignis": "auftrag_beendet",
                "auftrag": auftrag_id,
                "agent": agent,
                "ausgang": ausgang,
                "grund": grund,
            },
        )

    bus.abonnieren(Ereignisse.CHAT_ERSTELLT, chat_erstellt)
    bus.abonnieren(Ereignisse.ENDPUNKT_STATUS_GEAENDERT, endpunkt_status)
    bus.abonnieren(Ereignisse.ANTWORT_FERTIG, antwort_fertig)
    bus.abonnieren(Ereignisse.ANTWORT_ABGEBROCHEN, antwort_fertig)
    bus.abonnieren(Ereignisse.AUFTRAG_BEENDET, auftrag_beendet)


@asynccontextmanager
async def lebenszyklus(app: FastAPI):
    config: Config = app.state.config
    config.datenverzeichnis.mkdir(parents=True, exist_ok=True)
    # Am I the only service on this data folder? Asked once, here at the top,
    # and the answer travels down: the claim written just below decides on it,
    # and so does the carrying over of folders below that. Asked a second time
    # after the database had been opened, the two looks could find two
    # different folders.
    fremder_port = _lebende_instanz(config)
    # Two questions, not one: whether ANY other service is on the folder,
    # and whether one is on the very port we want. The second is not the
    # first compared to our port — see `_fremder_auf_unserem_port`. Both are
    # asked before the note is written, so what they find is somebody
    # else's claim and not our own.
    gleicher_port = _fremder_auf_unserem_port(config)
    # The claim on this folder comes BEFORE the folders are carried over:
    # renaming reaches into the data folder, and only a service holding the
    # lock on it may reach into it. With the move ahead of the claim, a
    # second service starting while this one was still busy with the
    # database, the wake-up services and the report paths found an unclaimed
    # folder and renamed every folder a second time.
    # In a thread, for the one rule and not for a gain here: the note is
    # written whole or not at all (app/atomic_file.py), which waits on Windows
    # while the file is held, and no coroutine of the program waits on that —
    # even this one, which serves nothing yet while it runs.
    claimed = await asyncio.to_thread(_instanz_eintragen, config, gleicher_port=gleicher_port)
    # From here to the end of the shutdown the claim is OURS to take
    # back. The note and the lock are written above; without this guard a
    # startup failure anywhere below (tool registry, discovery, runners,
    # wake-up) left both standing, and — flock refusing a second holder in
    # the same process — the next lifespan in this process ran with no
    # lock at all. The shutdown finally withdraws on the clean path; a
    # second withdrawal is a no-op (the note is gone, the reader returns).
    try:
        # Folders made under their former German names get their English ones
        # before anything asks for a location (app/folder_names.py). Only
        # under the claim taken above, and only while no other service works
        # on this data folder: one still running an older build holds the
        # former names and would go on writing into them.
        # Worked out once and handed to both halves of the move.
        move_lock = folder_names.lock_path(config)
        # Whether the stored paths are this start's to follow: not when the
        # lock on the move stayed with another service through the wait —
        # that one moves them, and a second wait would only hold this start
        # up twice. A move that failed is tried again at the next start;
        # what it did manage, the paths follow now.
        paths_follow = False
        if claimed and fremder_port is None:
            paths_follow = True
            try:
                paths_follow = folder_names.carry_over(config, move_lock)
            except (OSError, RuntimeError, ValueError) as error:
                # Never a reason not to start: what was not carried over is
                # tried again at the next start.
                log.warning("Folders not carried over to their new names: %s", error)
        else:
            # Another service uses the folder and moves nothing here — but it
            # may have moved the folders and written their new names after
            # this one read its configuration. Only read, never written.
            folder_names.names_read_again(config)
        # The scripts folder is the one location nothing ever writes into: a
        # cron entry only READS it, and the settings screen only shows it. So
        # it was the only one that could still be missing while the window
        # named its path and listed nothing under it — a folder the user is
        # told to fill and cannot find. It is made here, beside the data
        # folder, for the same reason that one is: the program owns the place
        # and should not ask anybody to create it by hand.
        #
        # Best effort. A location pinned to a path that cannot be made is the
        # settings screen's business to report; it is not a reason to refuse
        # to start, because everything else in this program works without it.
        try:
            ort(config, "scripts").mkdir(parents=True, exist_ok=True)
        except OSError as fehler:
            log.warning("Scripts folder cannot be created: %s", fehler)
        # The folder of the two prompt files is the user's and ships empty —
        # so empty that a fresh copy of the program does not carry it. Made
        # here for the reason the scripts folder is: the settings name the
        # place, and it should be there before anything is read from it or
        # dropped into it by hand. Best effort as above; reading a prompt
        # file that is not there gives the empty text either way.
        prompt_files = (config.app.system_prompt_file, config.app.memory_file)
        for folder in {config.pfad(prompt_file).parent for prompt_file in prompt_files}:
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                log.warning("Prompts folder cannot be created: %s", error)

        db = datenbank_oeffnen(config)
        app.state.db = db
        app.state.repositories = repositories_erstellen(db)
        # The second half of the same move, and under the same claim: the
        # note this reads is the one the move above wrote, and it goes once
        # the paths have followed. Read and deleted by a service that only
        # found the folder claimed, the note would be gone before the mover
        # ever got to it — and a note nobody reads is a move whose stored
        # paths never follow, with nothing left to try again.
        if paths_follow:
            try:
                folder_names.paths_carried_over(config, app.state.repositories, move_lock)
            except (OSError, ValueError, TypeError, sqlite3.Error) as error:
                log.warning("Stored paths not carried over to renamed folders: %s", error)
        app.state.generierungen = Generierungsverwaltung()
        _standard_abonnenten_anmelden()
        # The live line to the window (app/ereignisstrom.py). Hooked onto the
        # bus here rather than at import time, so a test that builds an app
        # without ever opening the stream gets it too — and so this sits beside
        # the other subscribers instead of somewhere a reader has to go looking.
        ereignisstrom.anmelden()
        # Where announcements fired from a worker thread have to be handed back
        # to. Every reader thread and downloader in the program publishes that
        # way; see app/events.py.
        bus.schleife_merken(asyncio.get_running_loop())
        # A background command reports its result into the chat when it is done —
        # and wakes the model with it, so a chat carries on through the night
        # without anyone typing (app/hintergrundwecken.py). Both handles are hung
        # in here for the same reason: the tool must be able to neither write a
        # message nor start an answer.
        wecken = hintergrundwecken.anmelden(app)
        hintergrundmeldung_anmelden(app.state.repositories, wecken=wecken)
        # And the same for an agent a chat started: its report goes back into
        # that chat and wakes the model to sum it up (app/agent_report.py).
        agent_report.anmelden(app.state.repositories, wecken=wecken)

        # Cleaned beside a second service now: the rows say who owns them,
        # so another service on this folder no longer costs the cleanup its
        # run — it only narrows what the cleanup may touch.
        #
        # Except on the very same port: there the stamp is no help at all,
        # because both services write the same number, so "ours" and
        # "theirs" are the same rows. The cleanup stays out completely, as
        # it did for every second service before this column existed — the
        # price is a row the other service may have stranded staying
        # 'laeuft', and that is the smaller damage.
        if gleicher_port:
            # A warning, not a note: a startup that skips its cleanup leaves
            # rows behind, and the line has to be findable afterwards.
            log.warning(
                "A second service is starting on the same port %s — the "
                "start cleanup stays off, because both write the same "
                "identity",
                int(config.app.port),
                extra={
                    "ereignis": "startbereinigung_ausgelassen",
                    "fremder_port": int(config.app.port),
                },
            )
        else:
            # Whether the cleanup has to keep its hands off somebody else's
            # rows is asked HERE, not read off the look from the top of the
            # lifespan: since that look the service it found may have died,
            # and its rows would then never be cleaned — a killed service's
            # answer would read as a running one for good, and there is
            # nothing below that would ask a second time.
            #
            # Two facts, both true when they are read: a lock held in the
            # folder right now, and the port that look named answering right
            # now. The second covers the service that left no lock behind —
            # an older build, or one whose lock could not be taken.
            foreign_now = _foreign_lock(config)
            if foreign_now is None and fremder_port is not None and _antwortet(fremder_port):
                foreign_now = fremder_port
            _startbereinigung(app, config, nur_eigene=foreign_now is not None)
            if foreign_now is not None:
                log.info(
                    "A second service uses this data folder (port %s) — the "
                    "start cleanup ran and only tidied its own rows",
                    foreign_now,
                    extra={
                        "ereignis": "startbereinigung_nur_eigene",
                        "fremder_port": foreign_now,
                    },
                )

        # The browser sign-in for hosted MCP servers. Independent of the mcp
        # switch, so "connect" also works before the first server is running.
        # Redirect fixed to the loopback address — sign-in is local ONLY.
        oauth = OAuthVermittler(
            AuthSpeicher(config.pfad(config.mcp.auth_file)),
            rueckleitung=(
                f"http://127.0.0.1:{config.app.port}/api/v1/tools/oauth/callback"
            ),
        )
        app.state.mcp_oauth = oauth

        # A permission file written before `create_folder` existed names the
        # file tools without it and would judge it by `standard` instead of
        # by the path rule of its siblings. Added once per start where it is
        # missing (app/configwanderung.py); an operator who wants the tool
        # judged otherwise gives it a rule of its own under `regeln`, which
        # wins over the path rule.
        file_tool_added(config.pfad(config.app.berechtigungen_datei), "create_folder")

        # Only build the tools when the feature is switched on.
        # Built by app/tools/aufbau.py — the same builder the restart after
        # saving the settings uses, so the two can no longer drift apart.
        registry: WerkzeugRegistry | None = None
        if config.features.mcp:
            registry = registry_bauen(app, config)
            await registry.starten()
        app.state.werkzeuge = registry

        discovery = Discovery(config, bus, app.state.repositories)
        app.state.discovery = discovery

        # The model runner. Built here and not per request: it holds a running
        # process, and a second instance would not know about the first.
        modellordner = ort(config, "models")
        # Companions used to lie loose among the models; move them into their own
        # sub-folders once at startup, so the model folder shows only models and
        # each companion folder only its own kind. A plain rename, names kept;
        # a drafter is told by its file header, and a whole model found in the
        # drafter folder moves back.
        begleiter_einsortieren(modellordner)
        app.state.modellrunner = Modellrunner(
            modellordner,
            config.app.runner_programm,
            # Only this runner ever serves a cron entry ahead of
            # time, so only this one gets to record how long a load took — the
            # embedding and vision-encoder runners below have nothing to
            # preload for. Fires on the reader thread; the store itself must
            # not care which thread calls it.
            bereit_callback=lambda modell, sekunden: modellvorlauf.messung_setzen(
                app.state.repositories, modell, sekunden
            ),
            # And only this runner announces its state today: the header has a
            # readout for the chat server and for none of the others below. The
            # announcement carries the server's name, so giving one of them a
            # readout later needs a listener and nothing else.
            zustand_callback=runnerzustand.melder(runnerzustand.CHAT),
        )
        # The picture runner is built HERE and not on first use. Its whole job is
        # to hold one lock so two pictures cannot be drawn at once — and a lazy
        # "check, then create" in a request handler can be run twice at the same
        # moment by two requests, which would leave two runners holding two
        # locks and let exactly the thing happen that the lock exists to stop.
        app.state.bildrunner = Bildrunner(config.datenverzeichnis)
        # Image-Turbo: the optional persistent picture server. Built here, never
        # started here — off by default, switched on by hand from the plus menu.
        # sd-cli stays the default; this only holds the model in memory so every
        # picture after the first skips the load.
        # The app's own port travels with it: the data folder is shared between
        # instances, so it is the one thing that tells them apart — and without
        # it a second instance read the first one's note and killed a picture
        # server that was drawing for somebody else.
        app.state.bildturbo = Bildturbo(config.datenverzeichnis, config.app.port)
        # A leftover server from a previous run holds the port; end it now.
        app.state.bildturbo._raeum_waise()
        # The embedding server: its own folder, its own port, its own note and
        # key. Not started here — it is a speed-up somebody switches on, and the
        # one-shot path works without it.
        app.state.einbettungsrunner = einbettungsserver.runner_bauen(
            config.pfad(config.app.einbettungsmodelle_verzeichnis),
            config.app.runner_programm,
            config.app.einbettung_port,
        )
        if app.state.einbettungsrunner.aufraeumen():
            log.info("Orphaned embedding server stopped")
        # The speech server, and beside it the small text model that tidies a
        # dictation. One folder for both, one port each. Neither is started here:
        # a microphone button is pressed by a hand, and until one is there is
        # nothing to listen to.
        sprachordner = ort(config, "speech_models")
        # Projectors dropped in loose belong in the vision sub-folder, the same
        # rule the model folder follows — a speech model without its projector
        # cannot hear at all, and the pairing reads that sub-folder.
        begleiter_einsortieren(sprachordner)
        app.state.sprachrunner = sprachserver.runner_bauen(
            sprachordner, config.app.runner_programm, config.app.sprache_port
        )
        app.state.sprachputzrunner = sprachserver.putzrunner_bauen(
            sprachordner, config.app.runner_programm, config.app.sprachputz_port
        )
        if app.state.sprachrunner.aufraeumen():
            log.info("Orphaned speech server stopped")
        if app.state.sprachputzrunner.aufraeumen():
            log.info("Orphaned clean-up model stopped")
        # The agent model slot — the fourth process this program may hold. Built
        # here; whether it also STARTS here is the one field's answer, and that is
        # asked further down, once the discovery it registers with exists.
        app.state.agentenrunner = agentenserver.runner_bauen(
            modellordner, config.app.runner_programm
        )
        if app.state.agentenrunner.aufraeumen():
            log.info("Orphaned agent model server stopped")
        # A previous service run may have left its model server behind — it
        # lives in its own process group and holds the port until somebody who
        # knows about it ends it. That somebody is us, right now.
        if app.state.modellrunner.aufraeumen():
            log.info("Orphaned model server from the previous run stopped")
        app.state.modelldownload = Modelldownload(modellordner)
        # One folder per kind of model, keyed by the catalogue's tab names. The
        # download routes by this map, because each server reads only its own
        # folder — a file in the wrong one is invisible where it belongs and a
        # broken entry where it lands.
        app.state.modellordner_je_art = {
            "chat": modellordner,
            "einbettung": config.pfad(config.app.einbettungsmodelle_verzeichnis),
            "sprache": sprachordner,
            "bild": ort(config, "image_models"),
        }
        # The model server itself, fetchable in one click on machines that do
        # not have it — into the user's data folder, next to their models.
        app.state.serverdownload = Serverdownload(config.pfad("."))
        # The picture generator the same way. Built here rather than on first
        # use, so there is one of it: two requests arriving together would
        # otherwise each build their own and write into the same file.
        app.state.sddownload = Sddownload(config.datenverzeichnis)
        await discovery.starten()

        # The slot, if the one field asks for one. After discovery,
        # because starting it means registering it there — and before the alarm
        # clock, so its very first catch-up pass already has a model to run on.
        #
        # This is a deliberate break with the rule the slot was written under
        # ("nothing here starts by itself"): the switched-on field IS the given
        # consent, and without this every restart would be a silent outage until
        # somebody opened the model window. Switching the field off takes the
        # consent back, and entries then wait visibly.
        await agentenserver.slot_starten_wenn_gewollt(app)

        # The alarm clock (6.7) comes after discovery: its first pass catches up
        # on missed appointments and needs the reachability state for that.
        wecker = Wecker(app)
        app.state.wecker = wecker
        await wecker.starten()

        log.info(
            "Exe AI Terminal %s started — port %s, language %s, database %s, "
            "%d/%d endpoints reachable, %d tool(s)",
            __version__,
            config.app.port,
            config.app.language,
            db.pfad,
            len(discovery.erreichbare()),
            len(discovery.alle()),
            registry.anzahl if registry else 0,
            extra={
                "ereignis": "start",
                "version": __version__,
                "port": config.app.port,
                "endpunkte_erreichbar": len(discovery.erreichbare()),
                "endpunkte_gesamt": len(discovery.alle()),
                "werkzeuge": registry.anzahl if registry else 0,
                "speicher_mb": speicher_mb(),
            },
        )
        try:
            yield
        finally:
            # No server outlives the program. The model, embedding, slot and
            # image-turbo servers each run in their OWN session (so a crash of the
            # service does not take them with it), which means they also do NOT die
            # on a clean shutdown unless ended by hand. Left running, the next
            # launch mints a fresh session key and the old server rejects it with
            # "Invalid API-Key" — the bug that made the program look broken after a
            # restart. So every server the service holds goes down here first.
            for name in (
                "modellrunner", "einbettungsrunner", "agentenrunner",
                "sprachrunner", "sprachputzrunner", "bildturbo",
            ):
                server = getattr(app.state, name, None)
                if server is None:
                    continue
                try:
                    server.stoppen()
                except Exception:
                    log.warning("%s could not be stopped on shutdown", name, exc_info=True)
            # No process outlives its chat unseen: whatever a background run
            # still has running goes down with the service.
            getoetet = laeufe.alle_toeten()
            if getoetet:
                log.info("%d running command(s) stopped on shutdown", getoetet)
            # And no ANSWER either. A command that finished normally a moment
            # ago has its report written and its wake already filed on the loop
            # (app/hintergrundwecken.py); the line above marks only runs that
            # were still going, so that one is not covered by it — and the three
            # awaits below are exactly where a filed task gets to run. Measured:
            # a whole answer started after this block, against the model servers
            # stopped a few lines up, and its message row reopened the database
            # file that `db.schliessen()` closes at the end of it.
            #
            # Here rather than lower down: nothing has yielded to the loop since
            # the shutdown began, so this sees every wake there is, and it has
            # cancelled them all before its own await lets any of them move.
            verworfen = await hintergrundwecken.alle_abbrechen()
            if verworfen:
                log.info("%d waiting wake-up(s) discarded on shutdown", verworfen)
            await wecker.stoppen()
            if registry is not None:
                await registry.stoppen()
            await discovery.stoppen()
            db.schliessen()
            # The claim on the data folder goes last, once nothing of ours can
            # write into it any more: while the note lies there, a service
            # starting on this folder holds its cleanup back, and holding it back
            # for a run that is already over would strand exactly the rows the
            # cleanup is for.
            _instanz_austragen(config)
            log.info("Exe AI Terminal stopped")
    except BaseException:
        _instanz_austragen(config)
        raise


def app_erstellen(config: Config | None = None) -> FastAPI:
    config = config or get_config()
    logging_einrichten(config)
    # Said now and not while the file was read: the configuration is loaded
    # before there is a log to write into (app/config.py).
    abgelegte_schluessel_melden()

    app = FastAPI(
        title="Exe AI Terminal",
        version=__version__,
        description="Its own interface to local and remote language models.",
        lifespan=lebenszyklus,
        docs_url=None,
        redoc_url=None,
    )
    app.state.config = config
    # A fresh key per start — never written to disk, so it
    # cannot outlive this process. See app/sitzungsschluessel.py.
    from app.sitzungsschluessel import neuer_schluessel
    app.state.sitzungsschluessel = neuer_schluessel()

    # Outermost, so every request gets an id — including those that abort
    # with an error along the way.
    app.add_middleware(ProtokollMiddleware)

    # A browser on this machine can aim any web page at loopback; writes
    # from foreign origins are turned away — see app/herkunftswaechter.py.
    from app.herkunftswaechter import Herkunftswaechter
    app.add_middleware(Herkunftswaechter)

    # Every /api/v1 call — reading included — needs this run's own key.
    # See app/sitzungsschluessel.py for why reading is checked too.
    from app.sitzungsschluessel import Sitzungswaechter
    app.add_middleware(Sitzungswaechter)

    # HTML ALWAYS checks back with the server: index.html carries the reference to the current
    # bundle — if the browser blindly pulls it from cache, the app keeps
    # running on the old version after an update. The bundles themselves may
    # cache forever, their file name changes with every build.
    # no-cache means: use it, yes, but only after checking back (a 304 is cheap).
    @app.middleware("http")
    async def html_nie_stumpf_cachen(request, call_next):
        antwort = await call_next(request)
        if antwort.headers.get("content-type", "").startswith("text/html"):
            antwort.headers["Cache-Control"] = "no-cache"
        return antwort

    # EVERY page carries the content rule, not only the interface. A page on
    # this origin that has none is a way around it, because a script in the
    # interface can open one and act from inside it. Same shape as the cache
    # header above, and for the same reason it goes by content type: the
    # static mount serves pages this file never names.
    # See app/inhaltssicherheit.py.
    @app.middleware("http")
    async def inhaltsregel_setzen(request, call_next):
        antwort = await call_next(request)
        if not antwort.headers.get("content-type", "").startswith("text/html"):
            return antwort
        antwort.headers[CSP_KOPFZEILE] = CSP_REGEL
        return antwort

    app.include_router(api_v1_router)

    # A body that fails its checks is answered by FastAPI itself, in English
    # — the window shows that sentence verbatim. The handler builds every one
    # of them from the catalogue instead (app/input_errors.py).
    app.add_exception_handler(
        RequestValidationError, input_errors.answer_for_input_error
    )

    # Unversioned health check — fixed address for monitoring/systemd.
    @app.get("/health", tags=["health"], summary="State of the service")
    def health():
        return _health_ermitteln(config, app.state.repositories)

    # PWA: the manifest must live at a fixed address.
    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest(request: Request):
        datei = STATIC_VERZEICHNIS / "manifest.webmanifest"
        if not datei.exists():
            # A fixed address with an answer nobody looks at: the browser's
            # manifest loader drops the body on failure. It stands in the
            # language of the interface all the same — one rule for this
            # route's answers, and the page names the address.
            sprache = sprachwahl.page_language(request.app.state.repositories, request)
            return JSONResponse(
                {"detail": t("fehler.manifest_fehlt", sprache)}, status_code=404
            )
        return FileResponse(datei, media_type="application/manifest+json")

    # The interface's own page: served here, ahead of the plain
    # static mount below, so this run's key can be stitched in — the one
    # exception to "everything needs the key", since without it the page
    # could never load far enough to send it. Nothing in the shell itself
    # is sensitive; only the API calls it goes on to make are. Everything
    # else under /app/ (the built JS/CSS bundles) carries no per-run data
    # and stays on the plain static mount.
    @app.get("/app/", include_in_schema=False)
    @app.get("/app/index.html", include_in_schema=False)
    def oberflaeche(request: Request):
        datei = STATIC_VERZEICHNIS / "app" / "index.html"
        # The language this page is about to speak, which only the service
        # knows — the stored choice, or on "auto" the language of this very
        # request (app/sprachwahl.page_language). It answers the missing
        # page as well as the page itself.
        sprache = sprachwahl.page_language(request.app.state.repositories, request)
        if not datei.exists():
            return JSONResponse(
                {"detail": t("fehler.oberflaeche_fehlt", sprache)}, status_code=404
            )
        # The sentences the page has to be able to show before the
        # catalogue is there: the message of a start that failed, the name
        # of a refusal that came without a reason, and what a stream that
        # ends without its `done` says. They travel in the
        # language this page is about to speak. Both keep their
        # placeholder: the number and the reason are filled in by the page
        # (frontend/src/lib/api.js, frontend/src/main.js).
        texte = {
            "dienst_antwortet_nicht": t("fehler.dienst_antwortet_nicht", sprache),
            "status": t("fehler.status", sprache),
            "strom_abriss": t("fehler.strom_abriss", sprache),
        }
        # ``<`` never travels as itself into the script block: JSON does not
        # escape it, and a catalogue text carrying "</script>" would end the
        # element early — the page would come without key, diagnosis flag and
        # texts. The escape reads back as the same character in the page.
        texte_json = json.dumps(texte, ensure_ascii=False).replace("<", "\\u003c")
        eingebettet = (
            datei.read_text(encoding="utf-8")
            # The document says which language it is written in before a
            # line of the program runs — a reading tool or a translator
            # trusts that attribute, and the catalogue only arrives after
            # the first request (frontend/src/lib/texte.svelte.js). The
            # built page carries German as its own default; the service
            # hands it out in the language it answers in.
            .replace('<html lang="de">', f'<html lang="{sprache}">', 1)
            .replace(
                "</head>",
                f"<script>window.__SITZUNGSSCHLUESSEL__="
                f"{json.dumps(app.state.sitzungsschluessel)};"
                f"window.__DIAGNOSE__={json.dumps(bool(config.app.diagnose))};"
                f"window.__TEXTE__={texte_json}"
                f"</script></head>",
                1,
            )
        )
        return HTMLResponse(eingebettet)

    # Mount static files last so the API routes take precedence.
    # The Vite-built Svelte folder will land here later.
    if STATIC_VERZEICHNIS.exists():
        app.mount(
            "/", StaticFiles(directory=STATIC_VERZEICHNIS, html=True), name="static"
        )
    else:
        log.warning("No static folder under %s", STATIC_VERZEICHNIS)

    return app


app = app_erstellen()


if __name__ == "__main__":
    import uvicorn

    konfiguration = get_config()
    uvicorn.run(
        "app.main:app",
        host=konfiguration.app.host,
        port=konfiguration.app.port,
        reload=False,
    )
