"""Two services, one data folder — and the second one keeps its hands off
the first one's running work.

``EXE_AI_PORT`` exists so a trial run can sit on its own port beside the
running program (fenster-electron/main.js), but ``data_dir`` does not vary
with the port: both services write the same database file, in WAL with a
busy timeout, so both writes land. Every cleanup at service start was
written as if this process were the only one — ``WHERE zustand = 'laeuft'``
says what state a row is in and never who put it there.

Measured with two real services on 8090 and 8091 against one database and
one answer in flight: starting the second stamped the first one's streaming
answer 'abgebrochen', moved its running job to 'unterbrochen', cleared the
status that job would have resumed from, and wrote a cron entry to run it a
second time.

The answer is the one the picture server already gave for its own note and
port (tests/test_bildturbo_je_instanz.py): the data folder is shared, the
app's own port is the one thing two instances cannot share, so it is what
tells them apart.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app.db import datenbank_oeffnen, repositories_erstellen
from app import instanzschloss
from app.main import INSTANZNOTIZ, _instanznotiz, app_erstellen


def freier_port() -> int:
    """A port nothing listens on. Bound and released, so the number is real
    and free rather than guessed."""
    with socket.socket() as dose:
        dose.bind(("127.0.0.1", 0))
        return dose.getsockname()[1]


def toter_prozess() -> int:
    """The id of a process that has run and been reaped — the ordinary state
    of the id in a note somebody's crash left behind."""
    prozess = subprocess.Popen([sys.executable, "-c", ""])
    prozess.wait()
    return prozess.pid


def notiz_legen(config, *, pid: int, port: int) -> None:
    """A foreign instance's claim on this data folder, by hand."""
    config.datenverzeichnis.mkdir(parents=True, exist_ok=True)
    (config.datenverzeichnis / f"{INSTANZNOTIZ}-{port}.json").write_text(
        json.dumps({"pid": pid, "port": port}), encoding="utf-8"
    )


def laufende_arbeit_anlegen(config, *, port: int | None = None) -> tuple[str, str]:
    """One streaming answer and one running job with a saved status —
    exactly what a service has open while we start.

    Written through a connection of its own and closed again, so what the
    starting service finds is the file and nothing else.

    ``port`` writes the rows as ANOTHER service's: every running row carries
    the port of the service that wrote it (`dienst_port`, app/db/schema.sql),
    and without a port of its own this helper writes them as the starting
    service's own — which is what the stranded-work tests below want, and
    what the tests about a second service on another port must not have.
    The same-port test is the exception that wants them signed as ours:
    there both services write the very same number, which is the whole
    reason the cleanup has to stay out.
    """
    db = datenbank_oeffnen(config)
    if port is not None:
        db.dienst_port = port
    repos = repositories_erstellen(db)
    chat = repos.chats.erstellen(user_id="lokal", title="Laufender Chat")
    # The row app/api/v1/generierung.py writes the moment a run begins.
    antwort = repos.messages.speichern(
        chat_id=chat.id, role="assistant", content="", zustand="laeuft"
    )
    auftrag = repos.auftraege.erstellen(
        user_id="lokal", agent="test", auftrag="Zähle bis drei"
    )
    repos.auftraege.zwischenstand_setzen(auftrag.id, "bei zwei angekommen")
    db.schliessen()
    return antwort.id, auftrag.id


def nachsehen(config, antwort_id: str, auftrag_id: str):
    db = datenbank_oeffnen(config)
    repos = repositories_erstellen(db)
    antwort = repos.messages.holen(antwort_id)
    auftrag = repos.auftraege.holen(auftrag_id)
    cronjobs = len(repos.cronjobs.auflisten())
    db.schliessen()
    return antwort, auftrag, cronjobs


def test_ein_zweiter_dienst_laesst_die_laufende_arbeit_des_ersten_stehen(config):
    """The whole point. A service answering on its own port has claimed this
    folder, so nothing here is stranded — it is somebody's live work."""
    with socket.socket() as fremder_dienst:
        fremder_dienst.bind(("127.0.0.1", 0))
        fremder_dienst.listen()
        fremder_port = fremder_dienst.getsockname()[1]
        # Written as HIS work, on his port: that signature is what keeps the
        # cleanup off it now that the cleanup runs either way.
        antwort_id, auftrag_id = laufende_arbeit_anlegen(config, port=fremder_port)
        notiz_legen(config, pid=os.getppid(), port=fremder_port)

        with TestClient(app_erstellen(config)):
            pass

    antwort, auftrag, cronjobs = nachsehen(config, antwort_id, auftrag_id)
    assert antwort.zustand == "laeuft"
    assert auftrag.zustand == "laeuft"
    # The status is what a resumption would consume, and a cron entry is what
    # it would be resumed BY: a second service must write neither, or the job
    # runs twice while the first one is still on it.
    assert auftrag.zwischenstand == "bei zwei angekommen"
    assert cronjobs == 0


def test_allein_wird_weiter_aufgeraeumt(config):
    """The guard must not swallow the reason the cleanup exists. With no
    other service on the folder, a genuinely stranded row is still ended."""
    antwort_id, auftrag_id = laufende_arbeit_anlegen(config)

    with TestClient(app_erstellen(config)):
        pass

    antwort, auftrag, cronjobs = nachsehen(config, antwort_id, auftrag_id)
    assert antwort.zustand == "abgebrochen"
    assert auftrag.zustand == "unterbrochen"
    assert cronjobs == 1


def test_eine_notiz_ohne_prozess_dahinter_haelt_nichts_auf(config):
    """The ordinary leftover: the service that wrote this note was killed, so
    its id names nothing. The note goes and the cleanup runs."""
    antwort_id, auftrag_id = laufende_arbeit_anlegen(config)
    port = freier_port()
    notiz_legen(config, pid=toter_prozess(), port=port)

    with TestClient(app_erstellen(config)):
        pass

    antwort, _auftrag, _cronjobs = nachsehen(config, antwort_id, auftrag_id)
    assert antwort.zustand == "abgebrochen"
    assert not (config.datenverzeichnis / f"{INSTANZNOTIZ}-{port}.json").exists()


def test_eine_notiz_ohne_dienst_dahinter_haelt_nichts_auf(config):
    """The harder leftover: the id in the note is alive, but it belongs to
    somebody else — the recycling app/tools/shell.py refuses to signal
    through. Nothing answers on the port, so it names no service of ours.

    Without this, a recycled id would hold the cleanup off for as long as
    that stranger lived, and a stranded row that is never cleaned is exactly
    what the cleanup is for.
    """
    antwort_id, auftrag_id = laufende_arbeit_anlegen(config)
    port = freier_port()
    notiz_legen(config, pid=os.getppid(), port=port)

    with TestClient(app_erstellen(config)):
        pass

    antwort, _auftrag, _cronjobs = nachsehen(config, antwort_id, auftrag_id)
    assert antwort.zustand == "abgebrochen"
    assert not (config.datenverzeichnis / f"{INSTANZNOTIZ}-{port}.json").exists()


def test_ein_zweiter_start_auf_demselben_port_nimmt_die_fremde_notiz_nicht_mit(config):
    """The name of a note is made from the port alone, so two services told
    to use the same port want the same file.

    The window's probe keeps that off the ordinary path; started by hand it
    happens, and the second start runs its whole lifespan before the socket
    it cannot have is even asked for. If it claimed the note on the way in
    and withdrew it on the way out, the service still running would be left
    without a claim — and the next start would call its live answer
    stranded.
    """
    with socket.socket() as fremder_dienst:
        # Bound to the port THIS config names, so the collision is real.
        fremder_dienst.bind(("127.0.0.1", 0))
        fremder_dienst.listen()
        config.app.port = fremder_dienst.getsockname()[1]
        # Written only now, and unsigned by any foreign port: the rows carry
        # the port the starting service is about to claim as its own. That is
        # the case the owner column cannot decide — a signature it would read
        # as its own belongs to the service still running on it — and the
        # only reason the running work below survives is that the cleanup
        # stays out of a same-port start entirely.
        antwort_id, auftrag_id = laufende_arbeit_anlegen(config)
        notiz_legen(config, pid=os.getppid(), port=config.app.port)

        with TestClient(app_erstellen(config)):
            pass

        notiert = json.loads(_instanznotiz(config).read_text(encoding="utf-8"))

    # Untouched, id and all — and the running work it stands for with it.
    assert notiert == {"pid": os.getppid(), "port": config.app.port}
    antwort, auftrag, cronjobs = nachsehen(config, antwort_id, auftrag_id)
    assert antwort.zustand == "laeuft"
    assert auftrag.zustand == "laeuft"
    # The third write of the startup, too: no resumption is scheduled for a
    # job the service on this port may be working on right now.
    assert auftrag.zwischenstand == "bei zwei angekommen"
    assert cronjobs == 0


def test_ein_dritter_dienst_sieht_den_gleichen_port_auch_hinter_einem_anderen(config):
    """The same-port case has to be asked about OUR port, not read off
    whichever port the folder scan names first.

    `_lebende_instanz` returns the FIRST living instance it finds, and the
    notes are read in sorted order — so with an ordinary service alive on a
    lower port it never gets as far as ours. Comparing its answer to our own
    port therefore said "different port" while a service was streaming on
    exactly our port, and the cleanup, narrowed to "our own rows", would
    have ended that live run: both write the same owner stamp.
    """
    with socket.socket() as fremder_dienst:
        fremder_dienst.bind(("127.0.0.1", 0))
        fremder_dienst.listen()
        config.app.port = fremder_dienst.getsockname()[1]
        # Signed with the port this start is about to claim — the work of
        # the service already on it.
        antwort_id, auftrag_id = laufende_arbeit_anlegen(config)
        notiz_legen(config, pid=os.getppid(), port=config.app.port)
        # And an ordinary service on a lower port, whose note is read
        # first. Its lock is what makes it count as living on a port
        # nothing answers on — the same signal a service holds between
        # writing its note and binding its socket.
        notiz_legen(config, pid=os.getppid(), port=1000)
        niedriges_schloss = instanzschloss.halten(schloss_von(config, 1000))
        assert niedriges_schloss is not None
        try:
            with TestClient(app_erstellen(config)):
                pass
        finally:
            instanzschloss.loslassen(niedriges_schloss)

        notiert = json.loads(_instanznotiz(config).read_text(encoding="utf-8"))

    antwort, auftrag, cronjobs = nachsehen(config, antwort_id, auftrag_id)
    assert antwort.zustand == "laeuft"
    assert auftrag.zustand == "laeuft"
    assert cronjobs == 0
    # And its claim stays its own: taken over here, the shutdown would have
    # deleted it and left the running service with nothing.
    assert notiert == {"pid": os.getppid(), "port": config.app.port}


def test_die_eigene_notiz_liegt_nur_solange_der_dienst_laeuft(config):
    """The claim is what the NEXT service reads. It has to be there while
    this one runs and gone the moment it has stopped — a note that outlived
    its service would hold every later cleanup off for good."""
    with TestClient(app_erstellen(config)):
        assert _instanznotiz(config).exists()
        notiert = json.loads(_instanznotiz(config).read_text(encoding="utf-8"))
        assert notiert == {"pid": os.getpid(), "port": config.app.port}
    assert not _instanznotiz(config).exists()


def test_unter_windows_wird_kein_signal_geschickt(config, monkeypatch):
    """On Windows ``os.kill`` is ``TerminateProcess`` wearing a probe's name,
    and a missing id raises a plain ``OSError`` there, not
    ``ProcessLookupError``. So the liveness test must not touch ``os.kill``
    at all on that platform and leave the decision to the port."""
    from app import main as dienst

    def niemals(*_args, **_kwargs):
        raise AssertionError("os.kill must not be called on Windows")

    # Played on the Mac, the Windows half has no `tasklist` to ask and says
    # "not known"; on Windows itself the process list answers, and a reaped
    # id is a clear "gone" there — without `os.kill` either way.
    on_windows = sys.platform == "win32"
    monkeypatch.setattr(dienst.os, "name", "nt")
    monkeypatch.setattr(dienst.os, "kill", niemals)

    assert dienst._prozess_gestorben(os.getppid()) is False
    assert dienst._prozess_gestorben(toter_prozess()) is on_windows


def test_auf_posix_gilt_ein_gestorbener_prozess_als_gestorben():
    """The ordinary case the note guard relies on: a reaped id names nothing."""
    from app import main as dienst

    if os.name == "nt":
        return
    assert dienst._prozess_gestorben(toter_prozess()) is True
    assert dienst._prozess_gestorben(os.getppid()) is False


def schloss_von(config, port: int):
    return config.datenverzeichnis / f"{INSTANZNOTIZ}-{port}.lock"


def test_ein_dienst_vor_seinem_socket_gilt_schon_als_lebendig(config):
    """The note is written inside the lifespan and the socket is bound only
    after the whole lifespan has run — seconds of model probes and server
    starts. A second service starting in that window found a live id on a
    silent port, took the note for stale and threw it away, and the first
    one ran on with no claim at all. The lock the first service holds on
    its note is what says it is alive before it listens."""
    port = freier_port()
    antwort_id, auftrag_id = laufende_arbeit_anlegen(config, port=port)
    notiz_legen(config, pid=os.getppid(), port=port)
    # What the first service holds from the moment it writes its note.
    schloss = instanzschloss.halten(schloss_von(config, port))
    assert schloss is not None
    try:
        with TestClient(app_erstellen(config)):
            pass
    finally:
        instanzschloss.loslassen(schloss)

    assert (config.datenverzeichnis / f"{INSTANZNOTIZ}-{port}.json").exists()
    antwort, auftrag, cronjobs = nachsehen(config, antwort_id, auftrag_id)
    assert antwort.zustand == "laeuft"
    assert auftrag.zustand == "laeuft"
    assert cronjobs == 0


def test_das_eigene_schloss_wird_mit_der_notiz_losgelassen(config):
    """Held while the service runs, gone when it has stopped — a lock that
    outlived its holder would call every later start a second instance."""
    with TestClient(app_erstellen(config)):
        assert instanzschloss.gehalten(schloss_von(config, config.app.port))
    assert not schloss_von(config, config.app.port).exists()
    assert not instanzschloss.gehalten(schloss_von(config, config.app.port))


def test_ein_schloss_ohne_halter_haelt_nichts_auf(config):
    """A lock file left behind by a kill is a file and nothing more: the
    kernel let the lock go with the process. The note beside it goes."""
    antwort_id, auftrag_id = laufende_arbeit_anlegen(config)
    port = freier_port()
    notiz_legen(config, pid=os.getppid(), port=port)
    schloss_von(config, port).touch()

    with TestClient(app_erstellen(config)):
        pass

    antwort, _auftrag, _cronjobs = nachsehen(config, antwort_id, auftrag_id)
    assert antwort.zustand == "abgebrochen"
    assert not schloss_von(config, port).exists()


def test_ein_startfehler_nimmt_zettel_und_schloss_wieder_mit():
    """The note and the lock are written before the runners start; a
    startup failure below them used to leave both standing, and — flock
    refusing a second holder in the same process — the next lifespan ran
    with no lock at all. Source-text guard: the stretch after the entry is
    wrapped, and the wrapper withdraws."""
    quelle = (Path(__file__).resolve().parent.parent / "app/main.py").read_text()
    stelle = quelle.find("_instanz_eintragen, config, gleicher_port=gleicher_port)")
    assert stelle > 0
    danach = quelle[stelle:]
    assert danach.find("    try:") < danach.find("registry_bauen"), (
        "the start path after the entry is no longer wrapped"
    )
    assert "except BaseException:\n        _instanz_austragen(config)\n        raise" in danach, (
        "the wrapper's exit no longer carries out"
    )


def test_the_folder_move_runs_under_the_service_s_own_lock(config, monkeypatch):
    """Renaming reaches into the data folder, so it may not start before this
    service holds the lock on it. Between the liveness question and the claim
    sat the database, the wake-up services and the report paths — seconds in
    which a second service found an unclaimed folder and renamed every folder
    a second time. Silence probe in passing: the move still happens, once."""
    from app import folder_names

    seen: list[bool] = []

    def move(running_config, lock_path=None):
        seen.append(
            instanzschloss.gehalten(schloss_von(running_config, running_config.app.port))
        )
        return True

    monkeypatch.setattr(folder_names, "carry_over", move)
    with TestClient(app_erstellen(config)):
        pass
    assert seen == [True], "the move ran without this service holding the lock"


def test_each_liveness_question_is_asked_once_per_start(config, monkeypatch):
    """The claim and the folder move decide on ONE look at the folder, not on
    two: asked a second time after the database had been opened, the second
    look could find a folder a service had entered in the meantime, and the
    two answers could then disagree about the same folder."""
    from app import main as hauptmodul

    asked = {"liveness": 0, "own_port": 0}
    real_liveness = hauptmodul._lebende_instanz
    real_own_port = hauptmodul._fremder_auf_unserem_port

    def counted_liveness(running_config):
        asked["liveness"] += 1
        return real_liveness(running_config)

    def counted_own_port(running_config):
        asked["own_port"] += 1
        return real_own_port(running_config)

    monkeypatch.setattr(hauptmodul, "_lebende_instanz", counted_liveness)
    monkeypatch.setattr(hauptmodul, "_fremder_auf_unserem_port", counted_own_port)

    with TestClient(app_erstellen(config)):
        pass

    assert asked == {"liveness": 1, "own_port": 1}


def test_a_second_start_in_the_window_moves_nothing(config, monkeypatch):
    """The case the job names: a first service is starting, so it holds the
    lock on the data folder and has not touched it yet, and a second start
    comes up right beside it. It must not rename a thing — two services
    renaming one folder leave it in two places."""
    from app import folder_names

    first_port = freier_port()
    notiz_legen(config, pid=os.getppid(), port=first_port)
    lock = instanzschloss.halten(schloss_von(config, first_port))
    assert lock is not None
    moves: list[int] = []
    monkeypatch.setattr(folder_names, "carry_over", lambda _config: moves.append(1))
    try:
        with TestClient(app_erstellen(config)):
            pass
    finally:
        instanzschloss.loslassen(lock)
    assert moves == [], "a second start renamed folders the first one is working on"


def test_a_service_that_dies_during_our_start_leaves_nothing_running(config, monkeypatch):
    """A service alive when our start looks, gone by the time our cleanup
    runs: its work is stranded and has to be cleaned. Read off the look from
    before — it was narrowed to "somebody else is here" — its rows would stay
    'laeuft' for the rest of this run, drawn as running and never resumed,
    and no later step asks twice."""
    from app import hintergrundwecken
    from app import main as hauptmodul

    port = freier_port()
    antwort_id, auftrag_id = laufende_arbeit_anlegen(config, port=port)
    notiz_legen(config, pid=os.getppid(), port=port)
    lock = instanzschloss.halten(schloss_von(config, port))
    assert lock is not None
    # The other service dies while this one is still starting — after the
    # look, before the cleanup.
    real_subscribe = hintergrundwecken.anmelden

    def dies_on_subscribe(app):
        instanzschloss.loslassen(lock)
        return real_subscribe(app)

    monkeypatch.setattr(hintergrundwecken, "anmelden", dies_on_subscribe)
    with TestClient(app_erstellen(config)):
        pass

    assert hauptmodul._foreign_lock(config) is None
    antwort, auftrag, cronjobs = nachsehen(config, antwort_id, auftrag_id)
    assert antwort.zustand == "abgebrochen"
    assert auftrag.zustand == "unterbrochen"
    assert cronjobs == 1


def test_the_note_survives_a_start_that_only_found_the_folder_claimed(config):
    """The note of the folder move is what makes the move survivable: it
    names the pairs whose stored paths still have to follow, and it goes once
    they have. A service that only found the folder claimed must not read it
    — nothing would have been moved yet, and deleting the note afterwards
    takes the pairs from the mover, which has no way to write them again."""
    from app import folder_names

    data = config.datenverzeichnis
    data.mkdir(parents=True, exist_ok=True)
    note = data / folder_names.PENDING
    note.write_text(json.dumps([[str(data / "chatdateien"), str(data / "chat_files")]]))

    # A second service, alive on this folder: its note, and the lock it holds.
    fremder_port = freier_port()
    notiz_legen(config, pid=os.getppid(), port=fremder_port)
    foreign = instanzschloss.halten(schloss_von(config, fremder_port))
    assert foreign is not None
    try:
        with TestClient(app_erstellen(config)):
            pass
    finally:
        instanzschloss.loslassen(foreign)

    assert note.exists(), "the note of the move was read and deleted by a starter"


def test_eine_frische_unlesbare_notiz_bleibt_liegen(tmp_path):
    """A scanner that lands in another service's write moment reads half a
    file; deleting on that one bad read deleted a LIVE claim. Only age
    retires an unreadable note."""
    from app import main as hauptmodul
    from app.config import Config

    config = Config.model_validate(
        {"app": {"data_dir": str(tmp_path), "port": 8090}}
    )
    kaputt = tmp_path / f"{hauptmodul.INSTANZNOTIZ}-9999.json"
    kaputt.write_text("{halb", encoding="utf-8")
    assert hauptmodul._lebende_instanz(config) is None
    assert kaputt.exists(), "a fresh unreadable note was deleted"
    os.utime(kaputt, (1, 1))
    assert hauptmodul._lebende_instanz(config) is None
    assert not kaputt.exists(), "an old unreadable note stayed behind"


def test_ein_gehaltenes_schloss_zaehlt_als_lebende_instanz(tmp_path):
    """The lock is taken before the note is written; a start caught
    between the two must be visible to a second starter, or both clean."""
    from app import instanzschloss
    from app import main as hauptmodul
    from app.config import Config

    config = Config.model_validate(
        {"app": {"data_dir": str(tmp_path), "port": 8090}}
    )
    fremd = tmp_path / f"{hauptmodul.INSTANZNOTIZ}-9999.lock"
    gehalten = instanzschloss.halten(fremd)
    assert gehalten is not None
    try:
        assert hauptmodul._lebende_instanz(config) == 9999
    finally:
        instanzschloss.loslassen(gehalten)
    assert hauptmodul._lebende_instanz(config) is None


def _config(tmp_path, port: int = 8090):
    from app.config import Config

    return Config.model_validate({"app": {"data_dir": str(tmp_path), "port": port}})


@pytest.fixture(autouse=True)
def eigenes_schloss_zurueckgesetzt():
    """The held lock is a module global. A test that fails between taking
    and releasing it would leave it held, and every later test in this
    process would then measure that leftover instead of its own case."""
    from app import main as hauptmodul

    yield
    instanzschloss.loslassen(hauptmodul._schloss)
    hauptmodul._schloss = None


def test_das_schloss_wird_auch_ohne_eigene_notiz_losgelassen(tmp_path):
    """The lock is ours whatever the note says. Withdrawn only behind a note
    of our own, a note that could not be written (or that a stranger
    overwrote) kept the lock held — and flock refusing a second holder in
    the same process, the next lifecycle ran with none."""
    from app import main as hauptmodul

    config = _config(tmp_path)
    hauptmodul._instanz_eintragen(config, gleicher_port=False)
    assert hauptmodul._schloss is not None
    _instanznotiz(config).unlink()  # the note is gone, the lock is not
    hauptmodul._instanz_austragen(config)
    assert hauptmodul._schloss is None
    assert not instanzschloss.gehalten(schloss_von(config, config.app.port))
    # And the same process can claim again.
    hauptmodul._instanz_eintragen(config, gleicher_port=False)
    assert hauptmodul._schloss is not None
    hauptmodul._instanz_austragen(config)
    assert hauptmodul._schloss is None
    assert not schloss_von(config, config.app.port).exists()


def test_ein_gehaltenes_schloss_auf_dem_eigenen_port_ist_ein_fremdes(tmp_path):
    """The lock scan runs before this process takes its own lock, so a
    held lock on OUR port can only be somebody else's: a service starting
    on the very port we are about to bind. Skipped, its running work was
    declared stranded and its note overwritten with our id."""
    from app import main as hauptmodul

    config = _config(tmp_path)
    fremd = instanzschloss.halten(schloss_von(config, config.app.port))
    assert fremd is not None
    try:
        assert hauptmodul._lebende_instanz(config) == config.app.port
    finally:
        instanzschloss.loslassen(fremd)
    assert hauptmodul._lebende_instanz(config) is None


def test_eine_tote_notiz_loescht_kein_schloss_das_gerade_gehalten_wird(tmp_path):
    """A note with a dead id beside a lock somebody holds right now: a new
    service on that port has taken its lock and not yet written its note.
    Deleting the lock file from under it would blind the scan that reads
    the file — held means somebody is there, and the scan says so."""
    from app import main as hauptmodul

    config = _config(tmp_path)
    port = freier_port()
    notiz_legen(config, pid=toter_prozess(), port=port)
    neu = instanzschloss.halten(schloss_von(config, port))
    assert neu is not None
    try:
        assert hauptmodul._lebende_instanz(config) == port
        assert schloss_von(config, port).exists()
    finally:
        instanzschloss.loslassen(neu)
    # The dead note itself is gone, and with nobody holding the lock the
    # scan reports nobody. The file may stay: the scan never deletes a lock
    # file it did not find beside a note, because a starter between opening
    # the file and locking it would lose its claim to that deletion.
    assert not (config.datenverzeichnis / f"{INSTANZNOTIZ}-{port}.json").exists()
    assert hauptmodul._lebende_instanz(config) is None
    assert not instanzschloss.gehalten(schloss_von(config, port))


def test_ein_gescheiterter_tausch_laesst_keine_halbe_notiz_liegen(tmp_path, monkeypatch):
    """The note is written to a side file and renamed into place; a rename
    that fails must not leave the side file in the folder for good."""
    from app import main as hauptmodul

    config = _config(tmp_path)

    def kaputt(_quelle, _ziel):
        raise OSError("no rename here")

    monkeypatch.setattr(hauptmodul.os, "replace", kaputt)
    hauptmodul._instanz_eintragen(config, gleicher_port=False)
    try:
        assert not list(tmp_path.glob(".*.tmp"))
        assert not _instanznotiz(config).exists()
    finally:
        hauptmodul._instanz_austragen(config)


def test_die_windows_probe_liest_die_prozessliste_als_csv():
    """The half of the Windows probe that a Mac can measure: what tasklist
    prints is CSV, and the id is one field of it. A dead id whose digits
    appear in the memory column is dead; a live process whose image name
    carries a comma is alive; the "no tasks" notice names nobody."""
    from app.main import _tasklist_nennt

    lebt = '"Exe AI, Terminal.exe","4321","Console","1","14.321 K"\r\n'
    assert _tasklist_nennt(lebt, 4321) is True
    # The digits of 4321 stand in the memory column of ANOTHER process.
    anderer = '"python.exe","9001","Console","1","14.321 K"\r\n'
    assert _tasklist_nennt(anderer, 4321) is False
    keiner = "INFO: No tasks are running which match the specified criteria.\r\n"
    assert _tasklist_nennt(keiner, 4321) is False
    assert _tasklist_nennt("", 4321) is False


def test_eine_unlesbare_notiz_aus_der_zukunft_wird_zurueckgezogen(tmp_path):
    """A stamp from the future — a clock that jumped, a folder copied from
    another machine — is as far from "being written right now" as an old
    one, and an unreadable note wearing it must not sit there for good."""
    import time

    from app import main as hauptmodul

    config = _config(tmp_path)
    kaputt = tmp_path / f"{hauptmodul.INSTANZNOTIZ}-9999.json"
    kaputt.write_text("{halb", encoding="utf-8")
    kuenftig = time.time() + 3600
    os.utime(kaputt, (kuenftig, kuenftig))
    assert hauptmodul._lebende_instanz(config) is None
    assert not kaputt.exists(), "an unreadable note from the future stayed behind"


def test_a_lock_that_cannot_be_taken_at_all_answers_nothing(tmp_path, caplog):
    """A lock file that cannot even be opened says nothing about its
    holder: neither held nor free. Read as held, every scan stepped aside
    for a service that is not there; read as free, a living one was cleaned
    up. The log says that the lock answers nothing."""
    import logging

    unusable = tmp_path / "x.lock"
    unusable.mkdir()
    with caplog.at_level(logging.WARNING, logger="app.instanzschloss"):
        assert instanzschloss.gehalten(unusable) is None
    lines = [r for r in caplog.records if "is not known" in r.getMessage()]
    assert [r.levelno for r in lines] == [logging.WARNING]


def _no_locks(monkeypatch):
    """A file system that gives no lock at all: every try answers ENOLCK."""
    import errno

    real_flock = instanzschloss.fcntl.flock

    def flock(fd, operation):
        if operation & instanzschloss.fcntl.LOCK_EX:
            raise OSError(errno.ENOLCK, os.strerror(errno.ENOLCK))
        return real_flock(fd, operation)

    monkeypatch.setattr(instanzschloss.fcntl, "flock", flock)


@pytest.mark.skipif(sys.platform == "win32", reason="stands in for the POSIX lock call")
def test_a_file_system_without_locks_answers_nothing(tmp_path, monkeypatch, caplog):
    """The same for a file that opens on a file system that gives no lock."""
    import logging

    path = tmp_path / "x.lock"
    path.touch()
    _no_locks(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="app.instanzschloss"):
        assert instanzschloss.gehalten(path) is None
    assert any("is not known" in r.getMessage() for r in caplog.records)


def test_a_held_and_a_free_lock_read_as_before_and_say_nothing(tmp_path, caplog):
    """Silence probe: a lock somebody holds is held, a free one is not, a
    missing file is not — and none of them writes a line."""
    import logging

    path = tmp_path / "x.lock"
    with caplog.at_level(logging.WARNING, logger="app.instanzschloss"):
        assert instanzschloss.gehalten(path) is False
        holder = instanzschloss.halten(path)
        assert holder is not None
        try:
            assert instanzschloss.gehalten(path) is True
        finally:
            instanzschloss.loslassen(holder)
        assert instanzschloss.gehalten(path) is False
    assert not [r for r in caplog.records if r.name == "app.instanzschloss"]


def test_an_unusable_lock_file_without_a_note_names_no_foreign_service(config):
    """An unusable lock file with no note beside it names no process: the
    data folder is not taken for claimed by a service that is not there."""
    from app import main as main_module

    config.datenverzeichnis.mkdir(parents=True, exist_ok=True)
    (config.datenverzeichnis / f"{INSTANZNOTIZ}-1234.lock").mkdir()
    assert main_module._foreign_lock(config) is None


@pytest.mark.skipif(sys.platform == "win32", reason="stands in for the POSIX lock call")
def test_without_locks_a_living_process_keeps_its_claim_and_its_work(config, monkeypatch):
    """On a disk that gives no lock at all, the lock says nothing, and the
    note's process id decides: it is alive, so the service is running. Its
    note stays and its running work is not ended — read as a free lock, its
    note went and its work was taken for stranded."""
    port = freier_port()
    antwort_id, auftrag_id = laufende_arbeit_anlegen(config, port=port)
    notiz_legen(config, pid=os.getppid(), port=port)
    # What the running service's own try at its lock left behind.
    schloss_von(config, port).touch()
    _no_locks(monkeypatch)
    with TestClient(app_erstellen(config)):
        pass
    assert (config.datenverzeichnis / f"{INSTANZNOTIZ}-{port}.json").exists()
    assert schloss_von(config, port).exists()
    antwort, auftrag, cronjobs = nachsehen(config, antwort_id, auftrag_id)
    assert antwort.zustand == "laeuft"
    assert auftrag.zustand == "laeuft"
    assert auftrag.zwischenstand == "bei zwei angekommen"
    assert cronjobs == 0


@pytest.mark.skipif(sys.platform == "win32", reason="stands in for the POSIX lock call")
def test_without_locks_a_dead_process_is_cleaned_up(config, monkeypatch):
    """Silence probe: on the same disk, a note whose process is gone names
    no service. Note and lock file go, and its work is cleaned up."""
    port = freier_port()
    antwort_id, auftrag_id = laufende_arbeit_anlegen(config, port=port)
    notiz_legen(config, pid=toter_prozess(), port=port)
    schloss_von(config, port).touch()
    _no_locks(monkeypatch)
    with TestClient(app_erstellen(config)):
        pass
    assert not (config.datenverzeichnis / f"{INSTANZNOTIZ}-{port}.json").exists()
    assert not schloss_von(config, port).exists()
    antwort, _auftrag, _cronjobs = nachsehen(config, antwort_id, auftrag_id)
    assert antwort.zustand == "abgebrochen"


def test_with_working_locks_a_free_lock_still_outweighs_a_living_id(config):
    """Silence probe: where the lock answers, it decides. A free lock and a
    living id — a recycled one — still name no service."""
    from app import main as main_module

    config.datenverzeichnis.mkdir(parents=True, exist_ok=True)
    schloss_von(config, 4321).touch()
    notiz_legen(config, pid=os.getppid(), port=4321)
    assert main_module._service_alive(schloss_von(config, 4321), lambda: True) is False
    assert main_module._foreign_lock(config) is None


@pytest.mark.skipif(sys.platform == "win32", reason="stands in for the POSIX lock call")
def test_without_locks_and_without_another_service_the_folders_move(config, monkeypatch):
    """On a disk that gives no lock at all, nobody can hold one: with no
    other service alive by its note, this one claims the folder and carries
    the folders over without the lock. Unclaimed, they kept their former
    names on such a disk for good."""
    data = config.datenverzeichnis
    (data / "bilder").mkdir(parents=True)
    _no_locks(monkeypatch)
    with TestClient(app_erstellen(config)):
        pass
    assert (data / "images").is_dir()
    assert not (data / "bilder").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="stands in for the POSIX lock call")
def test_without_locks_a_living_service_keeps_the_folders_as_they_are(config, monkeypatch):
    """Silence probe: on the same disk, another service alive by its note
    keeps this one from moving anything."""
    data = config.datenverzeichnis
    (data / "bilder").mkdir(parents=True)
    port = freier_port()
    notiz_legen(config, pid=os.getppid(), port=port)
    schloss_von(config, port).touch()
    _no_locks(monkeypatch)
    with TestClient(app_erstellen(config)):
        pass
    assert (data / "bilder").is_dir()
    assert not (data / "images").exists()


def test_a_lock_file_that_cannot_be_removed_does_not_stop_the_start(config):
    """A dead service's lock file goes with its note — but a lock file that
    cannot be removed (a folder in its place) stays, and the start goes on.
    Raised, it ended the whole start."""
    port = freier_port()
    notiz_legen(config, pid=toter_prozess(), port=port)
    schloss_von(config, port).mkdir()
    with TestClient(app_erstellen(config)):
        pass
    assert not (config.datenverzeichnis / f"{INSTANZNOTIZ}-{port}.json").exists()
    assert schloss_von(config, port).is_dir()


def test_a_dead_service_s_lock_file_is_still_removed(config):
    """Silence probe: an ordinary lock file of a dead service goes."""
    port = freier_port()
    notiz_legen(config, pid=toter_prozess(), port=port)
    schloss_von(config, port).touch()
    with TestClient(app_erstellen(config)):
        pass
    assert not schloss_von(config, port).exists()


@pytest.mark.skipif(sys.platform == "win32", reason="stands in for the POSIX lock call")
def test_the_scan_asks_about_a_process_once(config, monkeypatch):
    """Where the lock answers nothing, what the process id already said is
    handed on — the scan does not ask the system about the same id twice."""
    from app import main as main_module

    port = freier_port()
    notiz_legen(config, pid=os.getppid(), port=port)
    schloss_von(config, port).touch()
    _no_locks(monkeypatch)
    asked: list[int] = []
    real = main_module._prozess_gestorben

    def counted(pid):
        asked.append(pid)
        return real(pid)

    monkeypatch.setattr(main_module, "_prozess_gestorben", counted)
    assert main_module._lebende_instanz(config) == port
    assert asked == [os.getppid()]


def test_a_held_lock_is_answer_enough_without_the_note(config, monkeypatch):
    """The scan of lock files reads a note only where the lock answers
    nothing: a held lock needs no process id."""
    from app import main as main_module

    port = freier_port()
    config.datenverzeichnis.mkdir(parents=True, exist_ok=True)
    notiz_legen(config, pid=os.getppid(), port=port)
    read: list[int] = []
    monkeypatch.setattr(main_module, "_noted_pid", lambda own, p: read.append(p) or None)
    holder = instanzschloss.halten(schloss_von(config, port))
    assert holder is not None
    try:
        assert main_module._foreign_lock(config) == port
    finally:
        instanzschloss.loslassen(holder)
    assert read == []


def test_an_unknown_lock_is_warned_about_once_per_process(tmp_path, caplog):
    """The same lock file asked about again and again says its warning once;
    after that it is a debug line, word for word the same."""
    import logging

    unusable = tmp_path / "once.lock"
    unusable.mkdir()
    with caplog.at_level(logging.DEBUG, logger="app.instanzschloss"):
        for _ in range(3):
            assert instanzschloss.gehalten(unusable) is None
    lines = [r for r in caplog.records if "is not known" in r.getMessage()]
    assert [r.levelno for r in lines] == [logging.WARNING, logging.DEBUG, logging.DEBUG]
    assert len({r.getMessage() for r in lines}) == 1
