"""A cron entry that starts a script instead of an agent.

Two halves, and the first one is the important one. A script started from a
schedule runs with the user's full rights and never passes Tor 3
(app/berechtigungen.py) — nothing sees its name, nothing sees its arguments,
and there is nobody to ask during an unattended run. So the guard sits BEFORE
the start, and every lock of it is tested here:

  * only a chat may create such an entry, and only a chat may change its
    script — an agent's own run can do neither, and cannot even see one;
  * the file has to lie in the scripts folder, resolved, with links followed;
  * it has to exist and be executable.

The second half is that the run itself keeps every book a model run keeps:
one row in ``auftraege``, an outcome, the failure counter, and the
announcement — without a model being started anywhere.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import cronablauf, skriptlauf, speicherorte
from app.tools import cronjob as cronjob_werkzeug
from tests.conftest import script_file

# Tomorrow, so a fresh entry's daily due time always lies after the moment it
# was created — the same baseline tests/test_cronablauf.py works from.
MORGEN = datetime.now(timezone.utc).replace(
    hour=13, minute=0, second=0, microsecond=0
) + timedelta(days=1)


class EinAgent:
    """The little an agent-originated call is judged by: its name."""

    name = "recherche"
    werkzeuge = None


@pytest.fixture
def gemeldet(monkeypatch):
    """Announcements, collected instead of played — no test may put a real
    notification into the machine's notification centre."""
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


def skript_schreiben(ordner: Path, name: str, inhalt: str) -> Path:
    pfad = ordner / name
    pfad.write_text(inhalt, encoding="utf-8")
    pfad.chmod(0o755)
    return pfad


async def werkzeug(argumente, repos, skriptordner, *, herkunft="chat", agent=None):
    return await cronjob_werkzeug.ausfuehren(
        argumente,
        repos.cronjobs,
        (),
        herkunft=herkunft,
        agent=agent,
        skripte_ordner=lambda: skriptordner,
    )


def eintrag_anlegen(repos, **felder):
    felder.setdefault("skript", "arbeit.py")
    return repos.cronjobs.erstellen(
        agent=skriptlauf.SKRIPT_AGENT, task="", zeitplan="08:00",
        herkunft="chat", **felder,
    )


async def feuern(client, jetzt: datetime) -> None:
    """One tick, and then the runs it started, awaited to their end.

    A script run goes into the background exactly like a model run does — the
    thirty-second tick must not wait out an hour-long backup. A test does have
    to wait for it, and this is where it does."""
    await client.app.state.wecker.einmal_pruefen(jetzt=jetzt)
    for lauf in list(client.app.state.generierungen.laufende()):
        if lauf.aufgabe is not None:
            await lauf.aufgabe


def laeufe(client, cronjob_id: str) -> list[dict]:
    antwort = client.get("/api/v1/cronjobs/runs/all")
    assert antwort.status_code == 200
    return [lauf for lauf in antwort.json() if lauf["cronjob_id"] == cronjob_id]


# --- The locks --------------------------------------------------------------


async def test_agentenlauf_darf_keinen_skript_eintrag_anlegen(repos, skriptordner):
    """Riegel 2, and the one the whole step stands on: a page an agent reads
    must not be able to talk it into writing itself a script entry."""
    script_file(skriptordner, "arbeit.py", "")

    with pytest.raises(cronjob_werkzeug.CronjobVerboten) as fehler:
        await werkzeug(
            {"action": "create", "time": "03:00", "script": "arbeit.py"},
            repos, skriptordner, herkunft="agent", agent=EinAgent(),
        )

    assert "only be created from a chat" in str(fehler.value)
    assert repos.cronjobs.auflisten() == []


async def test_agentenlauf_kann_skript_nicht_nachtraeglich_setzen(repos, skriptordner):
    """The same lock on the other door: an entry that already exists must not
    grow a script through an agent's ``update`` either."""
    script_file(skriptordner, "arbeit.py", "")
    eintrag = repos.cronjobs.erstellen(
        agent="recherche", task="Nachsehen", zeitplan="08:00", herkunft="agent"
    )

    with pytest.raises(cronjob_werkzeug.CronjobVerboten) as fehler:
        await werkzeug(
            {"action": "update", "id": eintrag.id, "script": "arbeit.py"},
            repos, skriptordner, herkunft="agent", agent=EinAgent(),
        )

    assert "only be created from a chat" in str(fehler.value)
    assert repos.cronjobs.holen(eintrag.id).skript is None


async def test_agent_erreicht_einen_skript_eintrag_ueberhaupt_nicht(repos, skriptordner):
    """Not even to pause it, and worded so that an agent probing ids cannot
    tell a script entry from one that does not exist."""
    eintrag = eintrag_anlegen(repos)

    for aktion in ("pause", "resume", "remove", "update"):
        with pytest.raises(cronjob_werkzeug.CronjobVerboten) as fehler:
            await werkzeug(
                {"action": aktion, "id": eintrag.id},
                repos, skriptordner, herkunft="agent", agent=EinAgent(),
            )
        assert str(fehler.value) == f"Entry '{eintrag.id}' does not exist."

    assert repos.cronjobs.holen(eintrag.id).aktiv is True


async def test_ein_agent_mit_dem_markernamen_kommt_auch_nicht_heran(repos, skriptordner):
    """The name comparison alone is not the lock, and this is why it must not
    be trusted as one: an agent is a file in a folder, and a file CAN be
    called '(skript)'. Only the explicit check on the entry's own script
    column turns that coincidence into a rule."""

    class MarkerAgent:
        name = skriptlauf.SKRIPT_AGENT
        werkzeuge = None

    eintrag = eintrag_anlegen(repos)

    with pytest.raises(cronjob_werkzeug.CronjobVerboten) as fehler:
        await werkzeug(
            {"action": "pause", "id": eintrag.id},
            repos, skriptordner, herkunft="agent", agent=MarkerAgent(),
        )

    assert str(fehler.value) == f"Entry '{eintrag.id}' does not exist."
    assert repos.cronjobs.holen(eintrag.id).aktiv is True


@pytest.mark.parametrize(
    "name", ["../draussen.sh", "/bin/sh", "unterordner/arbeit.sh", "..", "arbeit.sh/.."]
)
async def test_pfad_ausserhalb_des_ordners_wird_abgewiesen(repos, skriptordner, name):
    """Riegel 1, first half: a name that spells out a path was never meant to
    be a file in the folder, whichever way it points."""
    with pytest.raises(cronjob_werkzeug.CronjobVerboten) as fehler:
        await werkzeug(
            {"action": "create", "time": "03:00", "script": name},
            repos, skriptordner,
        )

    assert "plain file name" in str(fehler.value)
    assert repos.cronjobs.auflisten() == []


@pytest.mark.platforms("posix", reason="a symlink needs a privilege on Windows")
async def test_symlink_nach_draussen_wird_abgewiesen(repos, skriptordner, tmp_path):
    """Riegel 1, second half, and the one a plain string check waves through:
    the name IS a plain file name in the folder — the file it names is not."""
    draussen = tmp_path / "draussen.sh"
    draussen.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    draussen.chmod(0o755)
    (skriptordner / "harmlos.sh").symlink_to(draussen)

    with pytest.raises(cronjob_werkzeug.CronjobVerboten) as fehler:
        await werkzeug(
            {"action": "create", "time": "03:00", "script": "harmlos.sh"},
            repos, skriptordner,
        )

    assert "does not resolve to a file within the scripts folder" in str(fehler.value)
    assert repos.cronjobs.auflisten() == []


@pytest.mark.platforms("posix", reason="a symlink needs a privilege on Windows")
async def test_symlink_innerhalb_des_ordners_ist_erlaubt(repos, skriptordner):
    """The counter-test that keeps the rule honest: the guard is about
    leaving the folder, not about links as such."""
    echt = skript_schreiben(skriptordner, "echt.sh", "#!/bin/sh\nexit 0\n")
    (skriptordner / "kurz.sh").symlink_to(echt)

    antwort = await werkzeug(
        {"action": "create", "time": "03:00", "script": "kurz.sh"},
        repos, skriptordner,
    )

    # Stored under the name it really resolves to: the check follows the
    # link, so what is written down is the file that will actually run.
    assert "script echt.sh" in antwort
    assert repos.cronjobs.auflisten()[0].skript == "echt.sh"


async def test_fehlendes_skript_wird_abgewiesen(repos, skriptordner):
    with pytest.raises(cronjob_werkzeug.CronjobVerboten) as fehler:
        await werkzeug(
            {"action": "create", "time": "03:00", "script": "gibtsnicht.sh"},
            repos, skriptordner,
        )

    assert "There is no script 'gibtsnicht.sh'" in str(fehler.value)


@pytest.mark.platforms("posix", reason="the execute bit")
async def test_nicht_ausfuehrbares_skript_wird_abgewiesen(repos, skriptordner):
    pfad = skriptordner / "stumm.sh"
    pfad.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    pfad.chmod(0o644)

    with pytest.raises(cronjob_werkzeug.CronjobVerboten) as fehler:
        await werkzeug(
            {"action": "create", "time": "03:00", "script": "stumm.sh"},
            repos, skriptordner,
        )

    assert "is not executable" in str(fehler.value)


# --- Startable, by system ---------------------------------------------------
#
# Windows has no execute bit (os.access(X_OK) is true for every file there),
# so the extension decides: .exe .bat .cmd .ps1 .py — a .sh never. The Mac
# keeps the bit. The platform is a parameter, so nothing here rewrites
# sys.platform.


@pytest.mark.parametrize("name, erwartet", [
    ("a.bat", True), ("b.ps1", True), ("c.py", True), ("d.exe", True), ("e.cmd", True),
    ("f.sh", False), ("g.txt", False), ("H.BAT", True),
])
def test_on_windows_the_extension_says_what_is_startable(skriptordner, monkeypatch, name, erwartet):
    monkeypatch.setattr(skriptlauf.shutil, "which", lambda programm: "C:/Python/python.exe")
    pfad = skript_schreiben(skriptordner, name, "echo hi\n")
    pfad.chmod(0o755)  # the bit is set on purpose: on Windows it must not count
    assert skriptlauf.startable(pfad, "win32") is erwartet


def test_on_windows_a_py_without_a_python_is_not_startable(skriptordner, monkeypatch):
    monkeypatch.setattr(skriptlauf.shutil, "which", lambda programm: None)
    pfad = skript_schreiben(skriptordner, "c.py", "print(1)\n")
    assert skriptlauf.startable(pfad, "win32") is False


def test_on_windows_the_launcher_counts_when_python_is_not_on_the_path(skriptordner, monkeypatch):
    monkeypatch.setattr(
        skriptlauf.shutil, "which", lambda programm: "C:/Windows/py.exe" if programm == "py" else None
    )
    pfad = skript_schreiben(skriptordner, "c.py", "print(1)\n")
    assert skriptlauf.startable(pfad, "win32") is True
    assert skriptlauf.command_line(pfad, "win32") == ["C:/Windows/py.exe", str(pfad)]


# The Store's stand-in: with no Python installed Windows still puts a
# ``python.exe`` into the WindowsApps folder, and starting it opens the Store.
STORE_STUB = r"C:\Users\u\AppData\Local\Microsoft\WindowsApps\python.exe"


def _which_gibt(**gefunden):
    """A ``shutil.which`` that knows only what the test hands it."""
    return lambda programm: gefunden.get(programm)


def test_on_windows_the_store_placeholder_is_not_a_python(skriptordner, monkeypatch):
    monkeypatch.setattr(skriptlauf.shutil, "which", _which_gibt(python=STORE_STUB))
    pfad = skript_schreiben(skriptordner, "c.py", "print(1)\n")

    assert skriptlauf.startable(pfad, "win32") is False


def test_on_windows_the_launcher_is_asked_after_the_placeholder(skriptordner, monkeypatch):
    monkeypatch.setattr(
        skriptlauf.shutil, "which", _which_gibt(python=STORE_STUB, py=r"C:\Windows\py.exe")
    )
    pfad = skript_schreiben(skriptordner, "c.py", "print(1)\n")

    assert skriptlauf.startable(pfad, "win32") is True
    assert skriptlauf.command_line(pfad, "win32") == [r"C:\Windows\py.exe", str(pfad)]


@pytest.mark.parametrize("stub", [
    r"C:\Users\u\AppData\Local\Microsoft\windowsapps\python.exe",
    r"C:\Users\u\AppData\Local\Microsoft\WINDOWSAPPS\python.exe",
    "C:/Users/u/AppData/Local/Microsoft/WindowsApps/python.exe",
])
def test_on_windows_the_placeholder_is_told_in_every_spelling(skriptordner, monkeypatch, stub):
    monkeypatch.setattr(skriptlauf.shutil, "which", _which_gibt(python=stub))
    pfad = skript_schreiben(skriptordner, "c.py", "print(1)\n")

    assert skriptlauf.startable(pfad, "win32") is False


def test_silence_on_windows_a_real_python_on_the_path_runs_as_before(skriptordner, monkeypatch):
    """A Python outside WindowsApps wins, also with a launcher present."""
    monkeypatch.setattr(
        skriptlauf.shutil, "which",
        _which_gibt(python=r"C:\Python313\python.exe", py=r"C:\Windows\py.exe"),
    )
    pfad = skript_schreiben(skriptordner, "c.py", "print(1)\n")

    assert skriptlauf.startable(pfad, "win32") is True
    assert skriptlauf.command_line(pfad, "win32") == [r"C:\Python313\python.exe", str(pfad)]


def test_on_windows_the_command_line_follows_the_extension(skriptordner, monkeypatch):
    monkeypatch.setattr(skriptlauf.shutil, "which", lambda programm: "C:/Python/python.exe")
    bat = skript_schreiben(skriptordner, "a.bat", "echo hi\n")
    ps1 = skript_schreiben(skriptordner, "b.ps1", "Write-Host hi\n")
    py = skript_schreiben(skriptordner, "c.py", "print(1)\n")
    exe = skript_schreiben(skriptordner, "d.exe", "")
    assert skriptlauf.command_line(bat, "win32") == [str(bat)]
    assert skriptlauf.command_line(exe, "win32") == [str(exe)]
    assert skriptlauf.command_line(ps1, "win32") == [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1),
    ]
    assert skriptlauf.command_line(py, "win32") == ["C:/Python/python.exe", str(py)]


@pytest.mark.platforms("posix", reason="the execute bit")
def test_on_the_mac_the_execute_bit_decides_and_the_file_starts_alone(skriptordner):
    """The silence side: nothing changes here — the bit, and the file as
    the whole command line, as before."""
    mit = skript_schreiben(skriptordner, "mit.sh", "#!/bin/sh\nexit 0\n")
    mit.chmod(0o755)
    ohne = skript_schreiben(skriptordner, "ohne.sh", "#!/bin/sh\nexit 0\n")
    ohne.chmod(0o644)
    bat = skript_schreiben(skriptordner, "a.bat", "echo hi\n")
    bat.chmod(0o644)
    assert skriptlauf.startable(mit, "darwin") is True
    assert skriptlauf.startable(ohne, "darwin") is False
    assert skriptlauf.startable(bat, "darwin") is False
    assert skriptlauf.command_line(mit, "darwin") == [str(mit)]
    assert skriptlauf.command_line(bat, "darwin") == [str(bat)]


async def test_on_windows_a_shell_script_is_refused_at_creation(repos, skriptordner, monkeypatch):
    """The check at creation and at every firing asks the same function —
    so on Windows a .sh with the bit set is refused with the sentence the
    Mac uses for a file without the bit."""
    import functools

    monkeypatch.setattr(skriptlauf, "startable", functools.partial(skriptlauf.startable, platform="win32"))
    pfad = skript_schreiben(skriptordner, "nacht.sh", "#!/bin/sh\nexit 0\n")
    pfad.chmod(0o755)

    with pytest.raises(cronjob_werkzeug.CronjobVerboten) as fehler:
        await werkzeug(
            {"action": "create", "time": "03:00", "script": "nacht.sh"},
            repos, skriptordner,
        )

    assert "is not executable" in str(fehler.value)


async def test_on_windows_the_start_hands_the_interpreter_to_the_process(skriptordner, monkeypatch):
    """The wiring, not the list: `starten` really gives `command_line` to
    the process. A recording fake stands in for the process and refuses,
    the way Windows refuses a bare .ps1 — so the run ends as a failed start
    and the recorded argv is what would have been started."""
    import functools

    monkeypatch.setattr(skriptlauf, "command_line", functools.partial(skriptlauf.command_line, platform="win32"))
    gesehen: list[list[str]] = []

    async def fake_exec(*argv, **kwargs):
        gesehen.append(list(argv))
        raise OSError(193, "not a valid Win32 application")

    monkeypatch.setattr(skriptlauf.asyncio, "create_subprocess_exec", fake_exec)
    pfad = skript_schreiben(skriptordner, "nacht.ps1", "Write-Host hi\n")

    ergebnis = await skriptlauf.starten(pfad, skriptordner, 10)

    assert gesehen == [["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(pfad)]]
    assert ergebnis.code is None
    assert "could not be started" in ergebnis.ausgabe


# --- The two kinds stay apart ----------------------------------------------


async def test_skript_und_aufgabe_zusammen_werden_abgewiesen(repos, skriptordner):
    script_file(skriptordner, "arbeit.py", "")

    with pytest.raises(cronjob_werkzeug.CronjobVerboten):
        await werkzeug(
            {"action": "create", "time": "03:00", "script": "arbeit.py",
             "task": "Auch noch nachsehen"},
            repos, skriptordner,
        )


async def test_skript_eintrag_bekommt_kein_ziel(repos, skriptordner):
    """Riegel 6: there is no model in such a run to report a goal."""
    script_file(skriptordner, "arbeit.py", "")

    with pytest.raises(cronjob_werkzeug.CronjobVerboten) as fehler:
        await werkzeug(
            {"action": "create", "time": "03:00", "script": "arbeit.py",
             "goal": "Sicherung liegt auf der Platte"},
            repos, skriptordner,
        )

    assert "cannot have a 'goal'" in str(fehler.value)


async def test_ziel_kann_einem_skript_eintrag_nicht_nachgereicht_werden(repos, skriptordner):
    eintrag = eintrag_anlegen(repos)

    with pytest.raises(cronjob_werkzeug.CronjobVerboten):
        await werkzeug(
            {"action": "update", "id": eintrag.id, "goal": "irgendwas"},
            repos, skriptordner,
        )


async def test_agentenplan_wird_nicht_zum_skriptplan(repos, skriptordner):
    script_file(skriptordner, "arbeit.py", "")
    eintrag = repos.cronjobs.erstellen(
        agent="recherche", task="Nachsehen", zeitplan="08:00", herkunft="chat"
    )

    with pytest.raises(cronjob_werkzeug.CronjobVerboten) as fehler:
        await werkzeug(
            {"action": "update", "id": eintrag.id, "script": "arbeit.py"},
            repos, skriptordner,
        )

    assert "an existing script entry" in str(fehler.value)


async def test_max_seconds_nur_am_skript_eintrag(repos, skriptordner):
    eintrag = repos.cronjobs.erstellen(
        agent="recherche", task="Nachsehen", zeitplan="08:00", herkunft="chat"
    )

    with pytest.raises(cronjob_werkzeug.CronjobVerboten):
        await werkzeug(
            {"action": "update", "id": eintrag.id, "max_seconds": 600},
            repos, skriptordner,
        )


# --- Creating one from a chat ----------------------------------------------


async def test_anlegen_aus_dem_chat_speichert_marker_und_grenze(repos, skriptordner):
    script_file(skriptordner, "sicherung.py", "")

    antwort = await werkzeug(
        {"action": "create", "time": "03:00", "script": "sicherung.py",
         "max_seconds": 3600},
        repos, skriptordner,
    )

    eintrag = repos.cronjobs.auflisten()[0]
    assert eintrag.skript == "sicherung.py"
    assert eintrag.zeitgrenze == 3600
    # The NOT NULL agent column carries the marker, and no task text is
    # invented for an entry nobody wrote one for.
    assert eintrag.agent == skriptlauf.SKRIPT_AGENT
    assert eintrag.task == ""
    assert "script sicherung.py" in antwort
    assert "3600s" in antwort


async def test_liste_nennt_das_skript_statt_einer_aufgabe(repos, skriptordner):
    eintrag_anlegen(repos, skript="sicherung.py")

    antwort = await werkzeug({"action": "list"}, repos, skriptordner)

    assert "script sicherung.py" in antwort
    assert "task:" not in antwort


# --- The run ---------------------------------------------------------------


async def test_skript_laeuft_ohne_dass_ein_modell_startet(config, client, skriptordner):
    """The whole point of the step. No provider is set up in this test, so
    NOTHING is reachable — an agent entry would sit in 'waiting for a model'
    and never run. The script runs anyway, and the run carries no endpoint."""
    beweis = Path(config.app.data_dir) / "beweis.txt"
    script_file(
        skriptordner, "arbeit.py",
        f"print('sicherung fertig')\nopen({str(beweis)!r}, 'w').write('x')\n",
    )
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos)

    await feuern(client, MORGEN.replace(hour=8, minute=1))

    assert beweis.exists()
    lauf = laeufe(client, eintrag.id)[0]
    assert lauf["status"] == "gut"
    assert lauf["task"] == "arbeit.py"
    zeilen = client.get("/api/v1/jobs").json()
    assert [z["agent"] for z in zeilen] == [skriptlauf.SKRIPT_AGENT]
    voll = client.get(f"/api/v1/jobs/{zeilen[0]['id']}").json()
    assert voll["state"] == "fertig"
    assert "sicherung fertig" in voll["result"]
    assert voll["endpoint_id"] in (None, "")


async def test_exit_eins_scheitert_und_zaehlt_bis_zur_grenze(client, skriptordner, gemeldet):
    """The failure counter applies to a script entry unchanged — and it is the
    exit code, nothing else, that decides."""
    script_file(skriptordner, "kaputt.py", "print('ging schief')\nraise SystemExit(1)\n")
    repos = client.app.state.repositories
    # On 'announce': the limit's sentence is a notification like any other,
    # and an entry on 'log' gets it in the log alone. The counting, the
    # switch-off and the run's own row are what this is about, and none of
    # them depends on the setting.
    eintrag = eintrag_anlegen(
        repos, skript="kaputt.py", fehlergrenze=2, deliver="announce"
    )

    await feuern(client, MORGEN.replace(hour=8, minute=1))
    assert repos.cronjobs.holen(eintrag.id).fehlversuche == 1
    assert repos.cronjobs.holen(eintrag.id).aktiv is True

    await feuern(client, MORGEN.replace(hour=8, minute=1) + timedelta(days=1))
    frisch = repos.cronjobs.holen(eintrag.id)
    assert frisch.fehlversuche == 2
    assert frisch.aktiv is False
    # Two runs, two sentences, and never two about ONE ending: the first
    # run's own result, then the limit's — which is the one that survives on
    # the run that reaches it (``schon_gemeldet``), and which says why that
    # run failed as the first one did.
    assert gemeldet == [
        ("kaputt.py — ging schief — Skript mit Fehler beendet", False),
        ("kaputt.py — nach 2 fehlgeschlagenen Durchläufen gestoppt — Skript mit Fehler beendet", False),
    ]

    lauf = laeufe(client, eintrag.id)[0]
    assert lauf["status"] == "gescheitert"
    assert lauf["grund"] == skriptlauf.GRUND_FEHLGESCHLAGEN


async def test_zeitgrenze_beendet_den_lauf_mit_passendem_grund(client, skriptordner):
    script_file(skriptordner, "haengt.py", "import time\ntime.sleep(30)\n")
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos, skript="haengt.py", zeitgrenze=1)

    await feuern(client, MORGEN.replace(hour=8, minute=1))

    lauf = laeufe(client, eintrag.id)[0]
    assert lauf["status"] == "gescheitert"
    assert lauf["grund"] == "zeitgrenze"
    auftrag = client.get("/api/v1/jobs").json()[0]
    voll = client.get(f"/api/v1/jobs/{auftrag['id']}").json()
    assert "Nach 1 Sekunden gestoppt" in voll["result"]


@pytest.mark.platforms("posix", reason="the shebang line")
async def test_skript_ohne_shebang_scheitert_sauber(client, skriptordner):
    """Not a silent success: a file the system cannot execute at all comes
    back as an error from the operating system, not as an exit code."""
    pfad = skriptordner / "ohne.sh"
    pfad.write_text("echo hallo\n", encoding="utf-8")
    pfad.chmod(0o755)
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos, skript="ohne.sh")

    await feuern(client, MORGEN.replace(hour=8, minute=1))

    assert laeufe(client, eintrag.id)[0]["status"] == "gescheitert"
    assert repos.cronjobs.holen(eintrag.id).fehlversuche == 1


async def test_announce_nennt_skript_und_letzte_zeile(client, skriptordner, gemeldet):
    """A script entry has no task text to announce, so it announces what
    a script that reports anything reports — its last line."""
    script_file(
        skriptordner, "sicherung.py", "print('starte')\nprint('42 Dateien gesichert')\n"
    )
    repos = client.app.state.repositories
    eintrag_anlegen(repos, skript="sicherung.py", deliver="announce")

    await feuern(client, MORGEN.replace(hour=8, minute=1))

    assert gemeldet == [("sicherung.py — 42 Dateien gesichert", True)]


async def test_stiller_eintrag_meldet_nicht(client, skriptordner, gemeldet):
    script_file(skriptordner, "still.py", "print('da')\n")
    repos = client.app.state.repositories
    eintrag_anlegen(repos, skript="still.py", deliver="log")

    await feuern(client, MORGEN.replace(hour=8, minute=1))

    assert gemeldet == []


async def test_verlegter_ordner_feuert_am_neuen_ort(config, client, skriptordner, tmp_path):
    """The pencil in the storage row moves the folder, and the next due time
    runs the script THERE — the path is resolved at every firing, never once
    at startup."""
    alt = script_file(
        skriptordner, "arbeit.py", f"open({str(tmp_path / 'wer.txt')!r}, 'w').write('alt')\n"
    )
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos)

    await feuern(client, MORGEN.replace(hour=8, minute=1))
    assert (tmp_path / "wer.txt").read_text() == "alt"

    neuer_ordner = tmp_path / "woanders"
    antwort = client.put("/api/v1/speicherorte/scripts", json={"pfad": str(neuer_ordner)})
    assert antwort.status_code == 200
    script_file(
        neuer_ordner, "arbeit.py", f"open({str(tmp_path / 'wer.txt')!r}, 'w').write('neu')\n"
    )
    assert alt.exists()

    await feuern(client, MORGEN.replace(hour=8, minute=1) + timedelta(days=1))

    assert (tmp_path / "wer.txt").read_text() == "neu"


async def test_verschwundenes_skript_haelt_den_termin_offen(client, skriptordner):
    """Same answer a missing agent file gets: nothing runs, nothing is
    counted, and putting the file back picks the schedule right up. A folder
    moved by mistake must not cost the entry its failure budget."""
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos, skript="weg.sh")

    await feuern(client, MORGEN.replace(hour=8, minute=1))

    assert client.get("/api/v1/jobs").json() == []
    frisch = repos.cronjobs.holen(eintrag.id)
    assert frisch.fehlversuche == 0
    assert frisch.aktiv is True


async def test_laufendes_skript_laesst_den_naechsten_termin_warten(client, skriptordner):
    """Per entry, not per agent name: every script entry carries the same
    marker in ``agent``, so the name-based check would make one long backup
    hold up every other script in the table."""
    script_file(skriptordner, "arbeit.py", "")
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos)
    zweiter = eintrag_anlegen(repos, skript="arbeit.py")
    # A run of the first entry that never ended.
    repos.auftraege.erstellen(
        user_id="u", agent=skriptlauf.SKRIPT_AGENT, auftrag="arbeit.py",
        cronjob_id=eintrag.id,
    )

    await feuern(client, MORGEN.replace(hour=8, minute=1))

    # The second entry ran; the first one, whose own run is still open, was
    # skipped -- and its due time is stamped so it does not stack up.
    assert repos.auftraege.laeufe_fuer_cronjob(zweiter.id)
    assert repos.auftraege.laeufe_fuer_cronjob(eintrag.id) == []
    assert repos.cronjobs.holen(eintrag.id).zuletzt_ausgeloest


# --- The unit underneath ---------------------------------------------------


@pytest.mark.platforms("posix", reason="a symlink needs a privilege on Windows")
def test_geprueft_folgt_dem_link_und_faellt_nicht_auf_den_namen_herein(skriptordner, tmp_path):
    draussen = tmp_path / "x.sh"
    draussen.write_text("#!/bin/sh\n", encoding="utf-8")
    draussen.chmod(0o755)
    (skriptordner / "harmlos.sh").symlink_to(draussen)

    with pytest.raises(skriptlauf.SkriptVerboten):
        skriptlauf.geprueft(skriptordner, "harmlos.sh")


async def test_starten_gibt_keine_argumente_weiter(skriptordner):
    """Riegel 3: the file itself is started, nothing after it — no shell
    string, nothing a model could have written into a command line."""
    pfad = script_file(
        skriptordner, "argumente.py", "import sys\nprint('[' + ' '.join(sys.argv[1:]) + ']')\n"
    )

    ergebnis = await skriptlauf.starten(pfad, skriptordner, 10)

    assert ergebnis.erfolgreich
    assert "[]" in ergebnis.ausgabe


async def test_arbeitsverzeichnis_ist_der_skriptordner(skriptordner):
    pfad = script_file(skriptordner, "wo.py", "import os\nprint(os.getcwd())\n")

    ergebnis = await skriptlauf.starten(pfad, skriptordner, 10)

    assert os.path.realpath(ergebnis.letzte_zeile) == os.path.realpath(skriptordner)


async def test_zeitgrenze_nimmt_auch_die_kinder_mit(skriptordner):
    """Measured, not assumed: killing only the shell leaves its children
    running, and a child holding the output pipe open makes the wait for the
    end of the run last as long as the child does. A one-second limit on a
    thirty-second sleep took the full thirty before the whole group was taken
    down instead."""
    pfad = script_file(
        skriptordner, "kinder.py",
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "time.sleep(30)\n",
    )

    begonnen = time.monotonic()
    ergebnis = await skriptlauf.starten(pfad, skriptordner, 1)

    assert ergebnis.abgelaufen
    assert time.monotonic() - begonnen < 10


# --- Started by hand --------------------------------------------------------
#
# The same start the tick makes, asked for by a person instead of by a due
# time (app/api/v1/cronjobs.py). One body, two callers — the difference is
# what a missing file means: the tick notes it and leaves the due time open,
# a person is told which file is wrong and why.


def skript_eintrag(repos, skript: str):
    return repos.cronjobs.erstellen(
        agent=skriptlauf.SKRIPT_AGENT, task="", zeitplan="08:00",
        herkunft="chat", skript=skript,
    )


def auf_lauf_warten(client, cronjob_id: str, timeout: float = 8.0) -> list[dict]:
    """The entry's history, once the run it just started has ended.

    Polled over the API rather than awaited: the run lives on the service's
    own loop, which is not the one a test runs on."""
    frist = time.time() + timeout
    while time.time() < frist:
        fertig = laeufe(client, cronjob_id)
        if fertig:
            return fertig
        time.sleep(0.05)
    raise AssertionError("the start by hand left no finished run")


def test_handstart_startet_das_skript(client, skriptordner):
    script_file(skriptordner, "arbeit.py", "")
    eintrag = skript_eintrag(client.app.state.repositories, "arbeit.py")

    assert client.post(f"/api/v1/cronjobs/{eintrag.id}/run").status_code == 200

    (gelaufen,) = auf_lauf_warten(client, eintrag.id)
    assert gelaufen["task"] == "arbeit.py"
    assert gelaufen["status"] == "gut"
    # And the entry's clock moved, which is what keeps the next tick from
    # firing the same past due time on top of it.
    (zeile,) = client.get("/api/v1/cronjobs").json()
    assert zeile["zuletzt_ausgeloest"] is not None


def test_handstart_ohne_datei_sagt_warum(client, skriptordner):
    """The tick leaves this open and tries again every thirty seconds. A
    person who pressed a button gets the checker's own sentence instead."""
    eintrag = skript_eintrag(client.app.state.repositories, "weg.sh")

    antwort = client.post(
        f"/api/v1/cronjobs/{eintrag.id}/run", headers={"Accept-Language": "de"}
    )
    assert antwort.status_code == 400
    # In the reader's language, not the checker's: the sentence goes to a
    # person who pressed a button, not to a model.
    assert "weg.sh" in antwort.json()["detail"]
    assert "gibt es kein Skript" in antwort.json()["detail"]
    # And nothing moved: no run, no stamp, no failure counted.
    assert laeufe(client, eintrag.id) == []
    (zeile,) = client.get("/api/v1/cronjobs").json()
    assert zeile["zuletzt_ausgeloest"] is None
    assert zeile["fehlversuche"] == 0


async def test_handstart_schluckt_den_faelligen_termin(client, skriptordner):
    """The silence test: a due time that has passed and not been served is
    exactly what the tick fires. After a hand start it must not — the entry
    has just run, and running it twice over one due time is what the stamp
    prevents."""
    script_file(skriptordner, "arbeit.py", "")
    repos = client.app.state.repositories
    eintrag = skript_eintrag(repos, "arbeit.py")
    # Backdated, so today's due time counts as one this entry has never
    # served — without that, a fresh entry's own creation is the baseline
    # and there would be nothing to fire in the first place.
    repos.cronjobs.verbindung.execute(
        "UPDATE cronjobs SET created_at = ? WHERE id = ?",
        ("2020-01-01T00:00:00", eintrag.id),
    )

    client.post(f"/api/v1/cronjobs/{eintrag.id}/run")
    (gelaufen,) = auf_lauf_warten(client, eintrag.id)

    # A tick at the moment the hand start stamped: the most recent due time
    # lies at or before it, so it has been served and nothing fires.
    (zeile,) = client.get("/api/v1/cronjobs").json()
    gestempelt = datetime.fromisoformat(zeile["zuletzt_ausgeloest"])
    await feuern(client, gestempelt)
    assert [lauf["id"] for lauf in laeufe(client, eintrag.id)] == [gelaufen["id"]]


def test_anlegen_mit_fehlender_datei_sagt_warum_auf_deutsch(client, skriptordner):
    """The same refusal on the other door. The create route hands the mask
    the tool's sentence, and for the script check that sentence used to be
    the English one — the very mix this fixed for the hand start, left
    standing on the route above it."""
    antwort = client.post(
        "/api/v1/cronjobs",
        json={"zeitplan": "08:00", "skript": "weg.sh"},
        headers={"Accept-Language": "de"},
    )
    assert antwort.status_code == 400
    assert "gibt es kein Skript" in antwort.json()["detail"]
    assert "weg.sh" in antwort.json()["detail"]

    englisch = client.post(
        "/api/v1/cronjobs",
        json={"zeitplan": "08:00", "skript": "weg.sh"},
        headers={"Accept-Language": "en"},
    )
    assert "There is no script" in englisch.json()["detail"]


def test_anlegen_reicht_eine_refusal_ohne_schluessel_durch(client, skriptordner):
    """The silence test: a refusal reaches the mask as a sentence in the
    reader's language, never as the name of a key."""
    antwort = client.post(
        "/api/v1/cronjobs",
        json={"zeitplan": "08:00", "task": "Los", "datum": "2020-01-01"},
        headers={"Accept-Language": "de"},
    )
    assert antwort.status_code == 400
    detail = antwort.json()["detail"]
    assert "fehler." not in detail, detail
    assert "cronjob_refusal." not in detail, detail
    assert detail == "Ein Datum kann nur für einen einmaligen Eintrag angegeben werden."
