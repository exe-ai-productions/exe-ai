"""Two endings a run has to survive: the service going down, and a child that
will not let go of the pipe.

Both were measured on the state of ``1454fd0``, which gave the script run its
own process group and hung it on the service's kill switch. That was right and
it opened two holes right behind it:

  * **A clean shutdown was booked as a failed run.** The switch killed the
    script and said nothing to the run around it, so the run read the killing
    as the script's own ending: ``gescheitert``, reason ``skript_fehler``,
    result ``[exit code -9]``. With a failure limit of one that cost the
    schedule its budget, switched the entry off, and sent two "Failed"
    notifications — for nothing more than a restart during the nightly backup.
    A model run does none of that: it is not killed on the way down, its row
    stays on ``laeuft``, and the next start writes ``unterbrochen`` over it.
  * **A killed run could hang for good.** ``await prozess.wait()`` after the
    kill registers a waiter that only ``_call_connection_lost`` wakes, and
    that runs when every pipe is closed. A child that left the group (a
    script calling ``setsid``) holds the pipe, for a service forever. The job
    stayed on ``laeuft``, ``laeuft_fuer_cronjob`` blocked every following due
    time, and the stop button reached nothing. The same line in
    ``run_command`` hung the chat on the tool call.

And one that was never a hole yet, only an unguarded number: ``killpg`` on the
id of a group that has run empty. The number is free then, and after enough
process starts it belongs to somebody else — a terminal's foreground group, or
one of this program's own servers.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import cronablauf, skriptlauf, speicherorte
from app.tools import hintergrund, shell

# Process groups, ``killpg``, ``setsid`` and the signal-0 probe: none of it
# exists on Windows, where a tree is ended with taskkill (app/prozessstopp.py).
pytestmark = pytest.mark.platforms("posix", reason="process groups, killpg and setsid")

MORGEN = datetime.now(timezone.utc).replace(
    hour=13, minute=0, second=0, microsecond=0
) + timedelta(days=1)

# Every wait in here is bounded. The whole point of half these tests is a line
# that used to wait forever, and a test that reproduces that by hanging tells
# nobody anything.
GEDULD = 20.0


# --- Helpers ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _kein_uebertrag():
    """The "cannot start" record is module state on purpose. A test must not
    inherit another test's outage."""
    cronablauf._skript_fehlt.clear()
    yield
    cronablauf._skript_fehlt.clear()


@pytest.fixture
def gemeldet(monkeypatch):
    """Every announcement caught instead of sent. The real one goes to the
    machine's notification centre under the shipped title, from a throwaway
    test service the user cannot tell apart from their own program."""
    aufrufe: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        cronablauf.cronmeldung, "melden",
        lambda text, *, erfolgreich, sprache=None: aufrufe.append((text, erfolgreich)),
    )
    return aufrufe


@pytest.fixture
def skriptordner(config) -> Path:
    ordner = speicherorte.ort(config, "scripts")
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


@pytest.fixture
def aufraeumen():
    """Every process a test deliberately let escape, collected at the end.

    These tests start real processes that really do get away — that is what
    they are about. Not one of them may be left on the machine, and no
    pattern-based sweep is allowed to look for them: other chats run their own
    services on this same machine.
    """
    pids: list[int] = []
    yield pids
    for pid in pids:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGKILL)


def skript_schreiben(ordner: Path, name: str, inhalt: str) -> Path:
    pfad = ordner / name
    pfad.write_text(inhalt, encoding="utf-8")
    pfad.chmod(0o755)
    return pfad


def ausbrecher_befehl(ordner: Path, pidd: Path) -> str:
    """A child that leaves the process group and keeps the output pipe.

    ``setsid`` as a program does not exist on macOS, so the escape is written
    out: a session of its own, then nothing but waiting. It inherits stdout
    and stderr from whatever started it, which is the entire point — those
    pipes stay open after that thing is dead.

    Started through the interpreter by name rather than by a ``#!`` line: the
    path to it carries a space on this machine, and a shebang cannot.
    """
    pfad = ordner / "ausbrecher.py"
    pfad.write_text(
        "import os, sys, time\n"
        "os.setsid()\n"
        "open(sys.argv[1], 'w').write(str(os.getpid()))\n"
        "time.sleep(300)\n",
        encoding="utf-8",
    )
    return f"'{sys.executable}' '{pfad}' '{pidd}'"


def eintrag_anlegen(repos, **felder):
    felder.setdefault("skript", "arbeit.sh")
    felder.setdefault("zeitplan", "08:00")
    return repos.cronjobs.erstellen(
        agent=skriptlauf.SKRIPT_AGENT, task="", herkunft="chat", **felder
    )


async def anfeuern(client, jetzt: datetime):
    """One tick, and the run it started handed back still running."""
    await client.app.state.wecker.einmal_pruefen(jetzt=jetzt)
    laufende = list(client.app.state.generierungen.laufende())
    assert len(laufende) == 1
    return laufende[0]


def lebt(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def warten_bis_tot(pid: int, grenze: float = 5.0) -> bool:
    ende = asyncio.get_running_loop().time() + grenze
    while asyncio.get_running_loop().time() < ende:
        if not lebt(pid):
            return True
        await asyncio.sleep(0.05)
    return not lebt(pid)


async def pid_lesen(datei: Path, grenze: float = 10.0) -> int:
    ende = asyncio.get_running_loop().time() + grenze
    while asyncio.get_running_loop().time() < ende:
        if datei.exists() and datei.read_text().strip():
            return int(datei.read_text().strip())
        await asyncio.sleep(0.05)
    raise AssertionError(f"{datei} carries no pid")


# --- A clean shutdown is not a failed run ---------------------------


async def test_dienstende_bucht_keinen_fehlversuch(
    client, skriptordner, tmp_path, gemeldet
):
    """The restart during the nightly backup, with the numbers it cost.

    Measured on ``1454fd0`` with exactly this entry — limit of one failed run,
    announcements on — and exactly this shutdown::

        zustand=gescheitert  ende_grund=skript_fehler  ergebnis='[exit code -9]'
        Eintrag: fehlversuche=1  aktiv=False
        Mitteilungen: ('lang.sh - stopped after 1 failed runs', False)
                      ('lang.sh - [exit code -9]', False)

    Every one of those five lines is asserted away below.
    """
    kind = tmp_path / "skript.pid"
    skript_schreiben(
        skriptordner, "lang.sh", f"#!/bin/sh\necho $$ > '{kind}'\nsleep 300\n"
    )
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(
        repos, skript="lang.sh", zeitgrenze=600, fehlergrenze=1, deliver="announce"
    )

    lauf = await anfeuern(client, MORGEN.replace(hour=8, minute=1))
    auftrag_id = lauf.chat_id
    pid = await pid_lesen(kind)

    # The line the service pulls on the way down (app/main.py).
    assert hintergrund.laeufe.alle_toeten() >= 1
    assert await warten_bis_tot(pid), f"the script {pid} outlives the end of the service"

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(lauf.aufgabe, timeout=GEDULD)

    # Nothing was written: no ending, no reason, no result.
    auftrag = repos.auftraege.holen(auftrag_id)
    assert auftrag.zustand == "laeuft"
    assert auftrag.ende_grund is None
    assert auftrag.ergebnis is None
    # The entry keeps its budget and stays switched on.
    frisch = repos.cronjobs.holen(eintrag.id)
    assert frisch.fehlversuche == 0
    assert frisch.aktiv is True
    # And the user hears nothing about a run they stopped themselves.
    assert gemeldet == []


async def test_der_zustand_nach_dem_neustart_ist_unterbrochen(
    client, skriptordner, tmp_path
):
    """The other half of the same answer: not booking must not mean the row
    lies about running forever.

    ``beim_start_aufraeumen`` is what the next start runs (app/main.py), and it
    is the same function that gives a model run its honest ending. Nothing
    special is needed here — the row simply has to be found the way a model
    run leaves it.
    """
    kind = tmp_path / "skript.pid"
    skript_schreiben(
        skriptordner, "lang.sh", f"#!/bin/sh\necho $$ > '{kind}'\nsleep 300\n"
    )
    repos = client.app.state.repositories
    eintrag_anlegen(repos, skript="lang.sh", zeitgrenze=600)

    lauf = await anfeuern(client, MORGEN.replace(hour=8, minute=1))
    auftrag_id = lauf.chat_id
    pid = await pid_lesen(kind)

    hintergrund.laeufe.alle_toeten()
    assert await warten_bis_tot(pid)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(lauf.aufgabe, timeout=GEDULD)

    assert repos.auftraege.beim_start_aufraeumen() >= 1
    assert repos.auftraege.holen(auftrag_id).zustand == "unterbrochen"


# --- A killed run has to end ----------------------------------------


async def test_zeitgrenze_endet_auch_wenn_ein_kind_die_pipe_haelt(
    client, skriptordner, tmp_path, aufraeumen
):
    """Form 2: the script is still alive at the limit, its escaped child is
    not in the group and holds the output pipe.

    ``killpg`` ends the script, and then ``await prozess.wait()`` waited for
    a pipe that a ``sleep 300`` — for a service, anything — keeps open. The
    exit status was there the whole time: measured ``-9`` while ``wait()``
    never returned. Without the fix this test does not fail, it hangs, so
    every wait in it is bounded.
    """
    kind = tmp_path / "kind.pid"
    skript_schreiben(
        skriptordner, "haelt.sh",
        f"#!/bin/sh\n{ausbrecher_befehl(skriptordner, kind)} &\nsleep 300\n",
    )
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos, skript="haelt.sh", zeitgrenze=1)

    lauf = await anfeuern(client, MORGEN.replace(hour=8, minute=1))
    aufraeumen.append(await pid_lesen(kind))

    await asyncio.wait_for(lauf.aufgabe, timeout=GEDULD)

    # The run ended, and it ended as what it was.
    auftrag = repos.auftraege.holen(lauf.chat_id)
    assert auftrag.zustand == "gescheitert"
    assert auftrag.ende_grund == "zeitgrenze"
    # And the next due time is not blocked any more — the consequence that
    # made this worse than a lost run: one hung script and the schedule was
    # over for good.
    assert repos.auftraege.laeuft_fuer_cronjob(eintrag.id) is False


async def test_run_command_endet_auch_wenn_ein_kind_die_pipe_haelt(
    tmp_path, aufraeumen
):
    """The same line in ``run_command``, where it hangs the chat on the tool
    call instead of a schedule."""
    kind = tmp_path / "kind.pid"
    befehl = ausbrecher_befehl(tmp_path, kind)

    antwort = await asyncio.wait_for(
        shell.ausfuehren(
            {"command": f"{befehl} & sleep 300"},
            [str(tmp_path)],
            zeitgrenze=1,
        ),
        timeout=GEDULD,
    )

    assert "Stopped after 1 seconds" in antwort
    aufraeumen.append(await pid_lesen(kind))


async def test_ernten_nimmt_den_rueckgabewert_ohne_die_pipe(tmp_path, aufraeumen):
    """The mechanism itself, in the open.

    The order is the whole finding. A waiter registered BEFORE the status
    arrives — which is where ``await prozess.wait()`` stood, one line after
    the kill — is woken by ``_call_connection_lost`` and by nothing else, and
    that runs when the last pipe closes. The escaped child holds it. Asked
    afterwards the same call answers at once, because the status is simply
    read out. So the status was never missing; the waiting for it was wrong.
    """
    kind = tmp_path / "kind.pid"
    skript = skript_schreiben(
        tmp_path, "haelt.sh",
        f"#!/bin/sh\n{ausbrecher_befehl(tmp_path, kind)} &\nsleep 300\n",
    )
    prozess = await asyncio.create_subprocess_exec(
        str(skript),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    kommunikation = asyncio.ensure_future(prozess.communicate())
    alt = None
    try:
        aufraeumen.append(await pid_lesen(kind))
        assert prozess.returncode is None, "the script must still be alive"

        # The old line, put where it stood: waiting before the status is in.
        alt = asyncio.ensure_future(prozess.wait())
        await asyncio.sleep(0)

        shell.gruppe_toeten(prozess)
        kommunikation.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await kommunikation

        # The status arrives...
        schleife = asyncio.get_running_loop()
        ende = schleife.time() + 5
        while prozess.returncode is None and schleife.time() < ende:
            await asyncio.sleep(0.02)
        assert prozess.returncode == -signal.SIGKILL
        # ...and the waiter is not woken by it.
        await asyncio.sleep(0.3)
        assert not alt.done(), "wait() came back — the hang is gone"

        assert await shell.ernten(prozess) == -signal.SIGKILL
        # And with the pipes let go of, the abandoned waiter is released too —
        # nothing is left behind holding descriptors open.
        await asyncio.wait_for(alt, timeout=2)
    finally:
        for aufgabe in (kommunikation, alt):
            if aufgabe is not None and not aufgabe.done():
                aufgabe.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await aufgabe


# --- Killpg on a number that is no longer ours ----------------------


async def test_killpg_trifft_keinen_fremden_gruppenfuehrer(tmp_path, aufraeumen):
    """The guard, with a real stranger standing in the line of fire.

    The setup is the situation after a group has run empty: our leader was
    reaped, so its id is free, and some other process is holding it by the
    time the kill arrives — hours later at a backup's limit, or at the
    shutdown. Recreating the recycling itself would take some hundred thousand
    process starts, so the stranger is put where the number points instead:
    a process of its own group that has nothing to do with us. It has to
    survive, and it does not survive without the guard.
    """
    fremder = await asyncio.create_subprocess_exec(
        "/bin/sh", "-c", "sleep 30", start_new_session=True
    )
    aufraeumen.append(fremder.pid)

    class Gereapt:
        """What is left of a run whose leader has been collected: the id, and
        an exit status that says the process behind it is gone."""

        pid = fremder.pid
        returncode = 0
        getroffen = False

        def kill(self):
            type(self).getroffen = True

    assert shell.gruppe_ist_noch_unsere(Gereapt()) is False
    shell.gruppe_toeten(Gereapt())

    await asyncio.sleep(0.3)
    assert lebt(fremder.pid), "the foreign group leader was killed"
    assert fremder.returncode is None
    # The fallback is what ran instead, and on a reaped process it is a
    # no-op that cannot reach anybody (Popen refuses once the status is in).
    assert Gereapt.getroffen is True

    fremder.kill()
    await fremder.wait()


def test_die_eigene_und_die_erste_gruppe_sind_tabu():
    """``killpg(0)`` is "my own group" — the service, and every command it is
    running right now. ``killpg(1)`` is init's. Neither can ever be a child of
    ours; the reviewer says the ids cannot occur, and until now nothing said
    so in the code."""

    class Kennung:
        def __init__(self, pid):
            self.pid = pid
            self.returncode = None

    assert shell.gruppe_ist_noch_unsere(Kennung(0)) is False
    assert shell.gruppe_ist_noch_unsere(Kennung(1)) is False
    assert shell.gruppe_ist_noch_unsere(Kennung(-1)) is False
    assert shell.gruppe_ist_noch_unsere(Kennung(None)) is False


async def test_der_waechter_laesst_die_gereapte_gruppe_durch(tmp_path, aufraeumen):
    """The guard must not take back the fix it guards.

    The case the time limit was repaired for: the script exited 0 and was
    reaped, its child lives on in the group. The leader's id belongs to no
    live process — which is exactly why the group cannot have been handed on —
    and the kill has to go through.
    """
    kind = tmp_path / "kind.pid"
    skript = skript_schreiben(
        tmp_path, "loslassen.sh",
        f"#!/bin/sh\nsleep 300 &\necho $! > '{kind}'\nexit 0\n",
    )
    prozess = await asyncio.create_subprocess_exec(
        str(skript),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    kommunikation = asyncio.ensure_future(prozess.communicate())
    try:
        enkel = await pid_lesen(kind)
        aufraeumen.append(enkel)
        # Wait for the leader to be collected — that is the state under test.
        ende = asyncio.get_running_loop().time() + 5
        while prozess.returncode is None and asyncio.get_running_loop().time() < ende:
            await asyncio.sleep(0.05)
        assert prozess.returncode == 0, "the parent must have been reaped"

        assert shell.gruppe_ist_noch_unsere(prozess) is True
        shell.gruppe_toeten(prozess)
        assert await warten_bis_tot(enkel), f"the child {enkel} lives on"
    finally:
        kommunikation.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await kommunikation
