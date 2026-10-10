"""Script entries: the run itself, not the guard in front of it.

The locks that decide whether a script may run at all are tested next door
(tests/test_skript_cronjob.py). These tests are about what happens once one
IS running, and every one of these is a hole that was measured before it was
closed:

  * **Stopping.** Cancelling is cooperative everywhere in this program — the
    signal is set and the run is expected to notice. A script run never
    looked: the stop button said "cancelling", the script ran to its end, and
    the ending was then booked against the schedule's failure budget. Deleting
    the job was worse — the process kept running headless, which is the exact
    opposite of what the route promises.
  * **The time limit, again.** It was fixed once and still had a way out: a
    script that puts its work in the background and exits 0 itself is reaped,
    ``os.getpgid`` on a reaped process raises, and the fallback went to the
    same dead process. The work ran forever.
  * **The same hole in ``run_command``**, where it hits every foreground
    command a person runs, every day.
  * **Unsubscribing.** Every firing left its run object in the manager for
    good, and left the finished job pointing at a "live" run.
  * **What is announced.** The last line of the output is the announcement,
    and on a failed run the last line was ``[exit code 1]``.
  * **A script that cannot be started at all** — the one state a script entry
    had no way of showing.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import cronablauf, skriptlauf, speicherorte
from app.api.abhaengigkeiten import STANDARD_BENUTZER
from app.api.v1.auftraege import auftrag_abbrechen, auftrag_loeschen
from app.tools import hintergrund, shell
from tests.conftest import script_file

MORGEN = datetime.now(timezone.utc).replace(
    hour=13, minute=0, second=0, microsecond=0
) + timedelta(days=1)


# --- Helpers ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _kein_uebertrag():
    """The "cannot start" record is module state, on purpose (it is a fact
    about right now). A test must not inherit another test's outage."""
    cronablauf._skript_fehlt.clear()
    yield
    cronablauf._skript_fehlt.clear()


@pytest.fixture
def gemeldet(monkeypatch):
    aufrufe: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        cronablauf.cronmeldung, "melden",
        lambda text, *, erfolgreich: aufrufe.append((text, erfolgreich)),
    )
    return aufrufe


@pytest.fixture
def skriptordner(config) -> Path:
    ordner = speicherorte.ort(config, "scripts")
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


def skript_schreiben(ordner: Path, name: str, inhalt: str) -> Path:
    pfad = ordner / name
    pfad.write_text(inhalt, encoding="utf-8")
    pfad.chmod(0o755)
    return pfad


def eintrag_anlegen(repos, **felder):
    felder.setdefault("skript", "arbeit.py")
    felder.setdefault("zeitplan", "08:00")
    return repos.cronjobs.erstellen(
        agent=skriptlauf.SKRIPT_AGENT, task="", herkunft="chat", **felder
    )


async def feuern(client, jetzt: datetime) -> None:
    """One tick, and the runs it started awaited to their end."""
    await client.app.state.wecker.einmal_pruefen(jetzt=jetzt)
    for lauf in list(client.app.state.generierungen.laufende()):
        if lauf.aufgabe is not None:
            await lauf.aufgabe


async def anfeuern(client, jetzt: datetime):
    """One tick, and the run it started handed back still running."""
    await client.app.state.wecker.einmal_pruefen(jetzt=jetzt)
    laufende = list(client.app.state.generierungen.laufende())
    assert len(laufende) == 1
    return laufende[0]


def lebt(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


async def warten_bis_tot(pid: int, grenze: float = 5.0) -> bool:
    """Whether ``pid`` is gone within ``grenze`` seconds. A signal is not
    instantaneous, and polling once right after the kill is a coin toss."""
    ende = asyncio.get_running_loop().time() + grenze
    while asyncio.get_running_loop().time() < ende:
        if not lebt(pid):
            return True
        await asyncio.sleep(0.05)
    return not lebt(pid)


async def pid_lesen(datei: Path, grenze: float = 5.0) -> int:
    ende = asyncio.get_running_loop().time() + grenze
    while asyncio.get_running_loop().time() < ende:
        if datei.exists() and datei.read_text().strip():
            return int(datei.read_text().strip())
        await asyncio.sleep(0.05)
    raise AssertionError(f"{datei} carries no pid")


# --- The time limit is still escapable ------------------------------


@pytest.mark.platforms("posix", reason="process groups and the signal-0 probe")
async def test_zeitgrenze_toetet_das_hintergrundkind(client, skriptordner, tmp_path):
    """A script that backgrounds its work and exits 0 itself.

    The parent ends at once and is reaped, the child keeps the output pipe
    open, so the wait runs into the limit — and the old kill asked
    ``os.getpgid`` for a process that no longer exists. That raises, the
    fallback went to the very same dead process and raised nothing at all, and
    the child ran on forever. Killing the group by the process id works
    because the group outlives its leader.
    """
    kind = tmp_path / "kind.pid"
    skript_schreiben(
        skriptordner, "loslassen.sh",
        f"#!/bin/sh\nsleep 300 &\necho $! > '{kind}'\nexit 0\n",
    )
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos, skript="loslassen.sh", zeitgrenze=1)

    await feuern(client, MORGEN.replace(hour=8, minute=1))

    pid = int(kind.read_text().strip())
    assert await warten_bis_tot(pid), f"the child {pid} is still alive"
    auftrag = repos.auftraege.laeufe_fuer_cronjob(eintrag.id)[0]
    assert auftrag.ende_grund == "zeitgrenze"


# --- The same hole in run_command -----------------------------------


@pytest.mark.platforms("posix", reason="process groups and the signal-0 probe")
async def test_run_command_zeitgrenze_toetet_den_befehl_nicht_nur_die_shell(tmp_path):
    """The one that hits a person every day: a build, an rsync, a sleep.

    Because of the folder marker the shell can never exec away, so the command
    is ALWAYS its child — and killing the shell alone left it running with the
    user's full rights, writing into the shared folder, while the chat said
    "Stopped after 1 seconds".
    """
    kind = tmp_path / "befehl.pid"
    antwort = await shell.ausfuehren(
        {"command": f"sleep 300 & echo $! > '{kind}'; wait"},
        [str(tmp_path)],
        zeitgrenze=1,
    )

    assert "Stopped after 1 seconds" in antwort
    pid = int(kind.read_text().strip())
    assert await warten_bis_tot(pid), f"the command {pid} keeps running"


@pytest.mark.platforms("posix", reason="process groups and the signal-0 probe")
async def test_dienstende_toetet_den_befehl_mit(tmp_path):
    """The kill switch at the other end of a run's life: what the service
    kills on the way down has to be the command, not the shell around it."""
    kind = tmp_path / "befehl.pid"
    aufgabe = asyncio.ensure_future(
        shell.ausfuehren(
            {"command": f"sleep 300 & echo $! > '{kind}'; wait"},
            [str(tmp_path)],
            chat_id="chat-dienstende",
            zeitgrenze=60,
        )
    )
    try:
        pid = await pid_lesen(kind)
        assert hintergrund.laeufe.alle_toeten() >= 1
        assert await warten_bis_tot(pid), f"the command {pid} outlives the end of the service"
    finally:
        aufgabe.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await aufgabe
        hintergrund.laeufe.vergessen("chat-dienstende")


# --- A script must not outlive the service --------------------------


@pytest.mark.platforms("posix", reason="process groups and the signal-0 probe")
async def test_skriptlauf_haengt_am_todesschalter_des_dienstes(
    client, skriptordner, tmp_path
):
    """A script gets its own session so the limit can take its children with
    it — and that same session is what let it outlive the service. The next
    start set the row to "interrupted", the next due time saw nothing running
    in the database, and a second backup started next to the first."""
    kind = tmp_path / "skript.pid"
    skript_schreiben(
        skriptordner, "lang.sh",
        f"#!/bin/sh\necho $$ > '{kind}'\nsleep 300\n",
    )
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos, skript="lang.sh", zeitgrenze=600)

    lauf = await anfeuern(client, MORGEN.replace(hour=8, minute=1))
    # The job's own id — the run management carries it as the chat id, and
    # laeufe_fuer_cronjob lists only runs that already ended.
    auftrag_id = lauf.chat_id
    pid = await pid_lesen(kind)

    assert hintergrund.laeufe.laeufe(auftrag_id), "the run is not in the switch"
    assert hintergrund.laeufe.alle_toeten() >= 1
    assert await warten_bis_tot(pid), f"the script {pid} outlives the end of the service"

    # The run ends WITH the process, and it ends as cancelled: the switch
    # says so through the kill itself, and a run that is being shut down books
    # nothing (tests/test_dienstende_und_haenger.py). Killing the script alone
    # left the run booking its own killing as a failure.
    with pytest.raises(asyncio.CancelledError):
        await lauf.aufgabe
    # And nothing left behind: a schedule at minute intervals would otherwise
    # file 1440 records a day into the same list.
    assert hintergrund.laeufe.laeufe(auftrag_id) == []


# --- Cancelling and deleting ---------------------------------------


@pytest.mark.platforms("posix", reason="process groups and the signal-0 probe")
async def test_abbrechen_stoppt_das_skript_und_zaehlt_nicht(
    client, skriptordner, tmp_path, gemeldet
):
    """The cancel route, called the way the button calls it.

    Three things at once, and all three were wrong: the process has to die,
    the ending has to be ``abgebrochen``, and it must not touch the failure
    count — a hand stop is the user's own doing a second ago, never a fault of
    the schedule. The model path has said so from the beginning.
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
    auftrag = repos.auftraege.holen(lauf.chat_id)
    pid = await pid_lesen(kind)

    auftrag_abbrechen(
        auftrag.id,
        repositories=repos,
        generierungen=client.app.state.generierungen,
        user_id=STANDARD_BENUTZER,
        sprache="de",
    )
    await lauf.aufgabe

    assert await warten_bis_tot(pid), f"the script {pid} keeps running after the abort"
    frisch = repos.auftraege.holen(auftrag.id)
    assert frisch.zustand == "abgebrochen"
    assert frisch.ende_grund == "benutzer_abbruch"
    assert repos.cronjobs.holen(eintrag.id).fehlversuche == 0
    assert repos.cronjobs.holen(eintrag.id).aktiv is True
    assert gemeldet == []


@pytest.mark.platforms("posix", reason="process groups and the signal-0 probe")
async def test_loeschen_nimmt_den_prozess_mit(client, skriptordner, tmp_path):
    """"gone means gone, not keeps running headless" — what the route's own
    comment promises. It stopped being true the moment the run stopped
    listening: the process went on, and the closing booking ran into a foreign
    key violation that was only logged away."""
    kind = tmp_path / "skript.pid"
    skript_schreiben(
        skriptordner, "lang.sh", f"#!/bin/sh\necho $$ > '{kind}'\nsleep 300\n"
    )
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos, skript="lang.sh", zeitgrenze=600)

    lauf = await anfeuern(client, MORGEN.replace(hour=8, minute=1))
    auftrag = repos.auftraege.holen(lauf.chat_id)
    pid = await pid_lesen(kind)

    auftrag_loeschen(
        auftrag.id,
        repositories=repos,
        generierungen=client.app.state.generierungen,
        user_id=STANDARD_BENUTZER,
        sprache="de",
    )
    await lauf.aufgabe

    assert await warten_bis_tot(pid), f"the script {pid} keeps running after the deletion"
    assert repos.auftraege.holen(auftrag.id) is None
    assert repos.auftraege.laeufe_fuer_cronjob(eintrag.id) == []


# --- Unsubscribing --------------------------------------------------


async def test_zehn_feuerungen_lassen_keinen_lauf_zurueck(client, skriptordner):
    """1440 a day at minute intervals, for as long as the program runs."""
    script_file(skriptordner, "kurz.py", "")
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos, skript="kurz.py", zeitplan="*/1 * * * *")
    generierungen = client.app.state.generierungen
    vorher = len(generierungen.laufende())

    jetzt = MORGEN.replace(hour=8, minute=0, second=30)
    for schritt in range(10):
        await feuern(client, jetzt + timedelta(minutes=schritt))

    assert len(repos.auftraege.laeufe_fuer_cronjob(eintrag.id)) == 10
    assert len(generierungen.laufende()) == vorher


async def test_abbrechen_auf_einen_fertigen_lauf_luegt_nicht(client, skriptordner):
    """The second half of the same fault: the finished job kept pointing at a
    "live" run, so cancelling it found one, answered "cancelling", and changed
    nothing at all."""
    script_file(skriptordner, "kurz.py", "")
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos, skript="kurz.py")

    await feuern(client, MORGEN.replace(hour=8, minute=1))
    auftrag = repos.auftraege.laeufe_fuer_cronjob(eintrag.id)[0]

    assert auftrag.generation_id is None
    assert repos.auftraege.holen(auftrag.id).zustand == "fertig"
    antwort = auftrag_abbrechen(
        auftrag.id,
        repositories=repos,
        generierungen=client.app.state.generierungen,
        user_id=STANDARD_BENUTZER,
        sprache="de",
    )
    assert antwort.state == "fertig"


# --- What is announced ---------------------------------------------


async def test_meldung_zeigt_die_fehlerzeile_statt_des_exitcodes(
    client, skriptordner, gemeldet
):
    """``_antwort_bauen`` appends ``[exit code 1]`` as the LAST line of
    anything that ended badly — so on exactly the run a person wants to hear
    about, the announcement said nothing at all."""
    script_file(
        skriptordner, "kaputt.py",
        "import sys\nprint('starte')\nprint('rsync: connection refused', file=sys.stderr)\n"
        "raise SystemExit(1)\n",
    )
    repos = client.app.state.repositories
    eintrag_anlegen(repos, skript="kaputt.py", deliver="announce", fehlergrenze=99)

    await feuern(client, MORGEN.replace(hour=8, minute=1))

    # The ending's reason rides behind it, the same as in the row in the
    # reports list.
    assert gemeldet == [
        ("kaputt.py — rsync: connection refused — script ended with an error", False)
    ]


async def test_lange_ausgabe_meldet_nicht_die_kuerzungsmarke(
    client, skriptordner, gemeldet
):
    """The same fault from the other side: a talkative script's last line was
    the truncation marker the display put in the middle of its own output."""
    script_file(
        skriptordner, "viel.py",
        "for i in range(4000):\n    print(f'Zeile {i} mit ordentlich Text daran')\n"
        "print('fertig: 12 Dateien')\n",
    )
    repos = client.app.state.repositories
    eintrag_anlegen(repos, skript="viel.py", deliver="announce")

    await feuern(client, MORGEN.replace(hour=8, minute=1))

    assert gemeldet == [("viel.py — fertig: 12 Dateien", True)]


# --- A script that cannot be started at all -------------------------


async def test_nicht_startbares_skript_ist_sichtbar_und_meldet_sich(
    client, skriptordner, gemeldet, monkeypatch
):
    """Moving the scripts folder writes the new location and moves nothing, so
    every script entry goes quiet at once. The due time rightly stays open —
    nothing is broken about the entry — but the only trace was one log line
    every thirty seconds, and the schedule simply stopped happening."""
    script_file(skriptordner, "sicherung.py", "")
    repos = client.app.state.repositories
    # On 'announce': the outage notice follows the setting, while the
    # visible state (``skript_nicht_startbar``, the log line, the
    # untouched failure budget) is written whatever it says.
    eintrag = eintrag_anlegen(
        repos, skript="sicherung.py", zeitplan="*/1 * * * *", deliver="announce"
    )

    await feuern(client, MORGEN.replace(hour=8, minute=0, second=30))
    assert cronablauf.skript_nicht_startbar(eintrag.id) is None
    # That first run worked, and on 'announce' it says so — this test is
    # about the OUTAGE that follows, so its own notification is set aside.
    assert gemeldet == [("sicherung.py — (done, no output)", True)]
    gemeldet.clear()

    (skriptordner / "sicherung.py").unlink()
    monkeypatch.setattr(cronablauf, "WARTEMELDUNG_SEKUNDEN", 60)

    await feuern(client, MORGEN.replace(hour=8, minute=1, second=30))
    grund = cronablauf.skript_nicht_startbar(eintrag.id)
    assert grund is not None and "sicherung.py" in grund
    # Not counted as a failure, and the due time stays open: a folder someone
    # moved must not cost the entry its failure budget.
    assert repos.cronjobs.holen(eintrag.id).fehlversuche == 0
    assert repos.cronjobs.holen(eintrag.id).aktiv is True
    # One tick is a hiccup, not an outage — nothing is announced yet.
    assert gemeldet == []

    await feuern(client, MORGEN.replace(hour=8, minute=3, second=30))
    assert len(gemeldet) == 1
    text, erfolgreich = gemeldet[0]
    # In the configured interface language, frame and reason alike.
    from app.i18n import t

    sprache = client.app.state.config.app.language
    assert text.startswith(
        t("cronjobs.script_cannot_start", sprache, script="sicherung.py", minutes=1, reason="")
    )
    assert text.endswith(cronablauf.skript_nicht_startbar(eintrag.id, sprache))
    assert erfolgreich is False

    # And once per outage, not once per tick.
    await feuern(client, MORGEN.replace(hour=8, minute=4, second=30))
    assert len(gemeldet) == 1

    script_file(skriptordner, "sicherung.py", "")
    await feuern(client, MORGEN.replace(hour=8, minute=5, second=30))
    assert cronablauf.skript_nicht_startbar(eintrag.id) is None
