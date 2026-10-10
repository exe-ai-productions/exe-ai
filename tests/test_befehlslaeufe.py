"""What a command leaves behind: a folder, live lines, a background result.

Three promises are checked here, and each of them broke something real when
it was missing:

* a `cd` reaches the next call — but only inside the shared folders, because
  otherwise a chat could walk itself out of its permission,
* every line is announced while the command runs, not at the end,
* a background call returns at once and its result finds its way back.
"""

from __future__ import annotations

import asyncio

import pytest

from app.api.v1 import befehle
from app.tools import hintergrund, ordnergedaechtnis, shell
from tests.conftest import cwd_command, process_alive, python_command

# A command that stays, on every system.
SLEEP_30 = python_command("import time; time.sleep(30)")


@pytest.fixture(autouse=True)
def sauber():
    ordnergedaechtnis.vergessen()
    hintergrund.laeufe._laeufe.clear()
    hintergrund.laeufe._ereignisse.clear()
    hintergrund.laeufe.abschluss = None
    yield
    ordnergedaechtnis.vergessen()
    hintergrund.laeufe._laeufe.clear()
    hintergrund.laeufe._ereignisse.clear()
    hintergrund.laeufe.abschluss = None


@pytest.fixture()
def ordner(tmp_path):
    (tmp_path / "unterordner").mkdir()
    return [str(tmp_path)]


# --- The remembered folder -------------------------------------------------


@pytest.mark.asyncio
async def test_ein_cd_wirkt_im_naechsten_aufruf(ordner, tmp_path):
    await shell.ausfuehren({"command": "cd unterordner"}, ordner, "chat-1")
    antwort = await shell.ausfuehren({"command": cwd_command()}, ordner, "chat-1")
    assert str((tmp_path / "unterordner").resolve()) in antwort


@pytest.mark.asyncio
async def test_ein_cd_gehoert_nur_seinem_chat(ordner, tmp_path):
    await shell.ausfuehren({"command": "cd unterordner"}, ordner, "chat-1")
    antwort = await shell.ausfuehren({"command": cwd_command()}, ordner, "chat-2")
    assert antwort.strip().endswith(str(tmp_path.resolve()))


@pytest.mark.asyncio
async def test_ein_cd_nach_draussen_wird_nicht_gemerkt(ordner, tmp_path):
    await shell.ausfuehren({"command": f"cd {tmp_path.parent}"}, ordner, "chat-1")
    antwort = await shell.ausfuehren({"command": cwd_command()}, ordner, "chat-1")
    assert antwort.strip().endswith(str(tmp_path.resolve()))


@pytest.mark.asyncio
async def test_die_ordnermarke_steht_nicht_in_der_ausgabe(ordner):
    antwort = await shell.ausfuehren({"command": "echo hallo"}, ordner, "chat-1")
    assert antwort == "hallo"
    assert shell.MARKE not in antwort


# --- Live output -----------------------------------------------------------


@pytest.mark.asyncio
async def test_jede_zeile_wird_gemeldet(ordner):
    gesehen = []

    async def zuschauen():
        async for ereignis in hintergrund.laeufe.zuschauen("chat-1"):
            gesehen.append(ereignis)

    zuschauer = asyncio.ensure_future(zuschauen())
    await asyncio.sleep(0)
    await shell.ausfuehren(
        {"command": python_command("print('eins'); print('zwei')")}, ordner, "chat-1"
    )
    await asyncio.sleep(0.05)
    zuschauer.cancel()

    arten = [e["typ"] for e in gesehen]
    assert arten[0] == "lauf_start"
    assert arten[-1] == "lauf_ende"
    assert [e["text"] for e in gesehen if e["typ"] == "lauf_zeile"] == ["eins", "zwei"]


@pytest.mark.asyncio
async def test_der_lauf_kennt_seinen_ausgang(ordner):
    await shell.ausfuehren({"command": "exit 3"}, ordner, "chat-1")
    lauf = hintergrund.laeufe.holen("chat-1", 1)
    assert lauf.zustand == hintergrund.FEHLER
    assert lauf.code == 3


# --- Background ------------------------------------------------------------


def _laeuft_noch(pid: int) -> bool:
    """Whether that process is still there — asked the way the system
    allows (tests/conftest.py: on Windows a signal would end it instead)."""
    return process_alive(pid)


@pytest.mark.asyncio
async def test_hintergrund_kehrt_sofort_zurueck_und_meldet_sich_spaeter(ordner, tmp_path):
    fertig: list[tuple] = []
    hintergrund.laeufe.abschluss = lambda lauf, antwort: fertig.append((lauf, antwort))

    antwort = await shell.ausfuehren(
        {"command": python_command("import time; time.sleep(0.2); print('spaet')"), "background": True},
        ordner, "chat-1",
    )
    assert "run #1" in antwort
    assert "spaet" not in antwort

    for _ in range(60):
        if fertig:
            break
        await asyncio.sleep(0.05)
    assert fertig, "the background run never reported"
    lauf, ergebnis = fertig[0]
    assert lauf.hintergrund is True
    assert "spaet" in ergebnis


@pytest.mark.asyncio
async def test_der_begleiter_wird_gehalten_bis_er_fertig_ist(ordner):
    """The companion task has a reference for exactly as long as it runs.

    This is the honest half of the story and it is worth saying plainly: a
    task that gets collected mid-flight cannot be provoked on demand, so
    what is checked here is not the collection but the thing that prevents
    it — that the reference exists while the run is going, and is gone once
    it has finished rather than piling up for the life of the process.

    Both halves matter. Dropped at the call, the task is the one the loop
    holds only weakly (app/events.py); never dropped, the set is a leak of
    every background command a session ever ran.
    """
    vorher = set(shell._begleiter)
    await shell.ausfuehren(
        {"command": python_command("import time; time.sleep(0.2); print('spaet')"), "background": True},
        ordner, "chat-1",
    )
    neu = shell._begleiter - vorher
    assert len(neu) == 1, "the companion task is not held"

    for _ in range(60):
        if not (neu & shell._begleiter):
            break
        await asyncio.sleep(0.05)
    assert not (neu & shell._begleiter), "the companion task was never let go of"
    assert hintergrund.laeufe.holen("chat-1", 1).zustand == hintergrund.FERTIG


@pytest.mark.asyncio
async def test_ein_gescheiterter_begleiter_laesst_den_lauf_nicht_haengen(
    ordner, monkeypatch
):
    """A companion that dies still leaves a run somebody can see.

    Before the companion was held and read out, the run stood at LAEUFT for
    the life of the process, the chat never heard from it, and the only
    trace anywhere was asyncio's "Task exception was never retrieved" at
    some later collection.

    The failure is injected rather than provoked. It used to be provoked by
    one output line longer than the stream's own limit, which was a real
    case then; `_mitlesen` carries that one itself now, and the
    test below proves it. What is left for this net is every OTHER way the
    companion can die, and there is no command that arranges one — so the
    reader is made to raise, and the net is what is under test.

    The command keeps going after the failure, because that is the case
    worth checking: nobody is reading its output any more, so it must not be
    left running in the shared folder either.
    """

    async def _faellt_um(*_a, **_k):
        raise RuntimeError("der Leser ist gescheitert")

    monkeypatch.setattr(shell, "_mitlesen", _faellt_um)
    await shell.ausfuehren(
        {"command": SLEEP_30, "background": True},
        ordner,
        "chat-1",
    )
    lauf = hintergrund.laeufe.holen("chat-1", 1)
    pid = lauf.prozess.pid
    for _ in range(60):
        if lauf.zustand != hintergrund.LAEUFT:
            break
        await asyncio.sleep(0.05)
    assert lauf.zustand == hintergrund.FEHLER
    assert not shell._begleiter

    for _ in range(60):
        if not _laeuft_noch(pid):
            break
        await asyncio.sleep(0.05)
    assert not _laeuft_noch(pid), "the detached command keeps running"


@pytest.mark.asyncio
async def test_eine_zu_lange_zeile_beendet_einen_hintergrundlauf_normal(ordner):
    """The cause the net above used to be demonstrated with, now cured.

    One line past the reader's limit — a single `cat` of a minified file
    clears the shipped 64 KiB — used to take the companion down with it and
    leave the run at LAEUFT for the life of the process. It is named in the
    output now and the run ends the way any other ends.
    """
    await shell.ausfuehren(
        {
            "command": python_command("print('x' * 70000); print('DANACH')"),
            "background": True,
        },
        ordner,
        "chat-1",
    )
    lauf = hintergrund.laeufe.holen("chat-1", 1)
    for _ in range(100):
        if lauf.zustand != hintergrund.LAEUFT:
            break
        await asyncio.sleep(0.05)
    assert lauf.zustand == hintergrund.FERTIG
    zeilen = "\n".join(str(z) for z in lauf.zeilen)
    assert shell.HINWEIS_ZEILE_ZU_LANG in zeilen
    assert "DANACH" in zeilen


@pytest.mark.asyncio
async def test_alles_wird_beim_herunterfahren_getoetet(ordner):
    await shell.ausfuehren({"command": SLEEP_30, "background": True}, ordner, "chat-1")
    assert hintergrund.laeufe.alle_toeten() == 1
    assert hintergrund.laeufe.holen("chat-1", 1).zustand == hintergrund.FEHLER
    # Let the killed run finish tidying up before the loop goes away.
    await asyncio.sleep(0.1)


# --- The window's route ----------------------------------------------------


def test_die_laeufe_eines_chats_stehen_im_netz(client):
    """The window asks once for what already ran; the stream carries only
    what happens from then on."""
    lauf = hintergrund.laeufe.anlegen("chat-9", "echo hallo")
    hintergrund.laeufe.zeile(lauf, "hallo")
    hintergrund.laeufe.beenden(lauf, 0)

    antwort = client.get("/api/v1/laeufe/chat-9")
    assert antwort.status_code == 200
    antwort_daten = antwort.json()
    # Three events happened (lauf_start, lauf_zeile, lauf_ende) — `ab` says
    # so, letting the window's stream resume right after them.
    assert antwort_daten["ab"] == 3
    eintraege = antwort_daten["laeufe"]
    assert len(eintraege) == 1
    # The duration is measured, so it is checked for being there rather than
    # for being a particular number.
    dauer = eintraege[0].pop("dauer_sekunden")
    assert dauer is not None and dauer >= 0
    assert eintraege == [
        {
            "lauf": 1,
            "befehl": "echo hallo",
            "hintergrund": False,
            "zustand": "fertig",
            "code": 0,
            "ausgabe": "hallo",
            "art": "befehl",
            # A command run has no dials of its own — only a picture does
            # (bildlauf.regler_von, read by _als_daten for art == 'bild').
            "regler": None,
            # Whether an answer has read the run's report yet — false for
            # a foreground run, which never writes one (Lauf.gelesen).
            "gelesen": False,
            # The folder it ran in; a run made by hand here names none.
            "folder": None,
        }
    ]


# --- The SSE stream's own end ----------------------------------------------


@pytest.mark.asyncio
async def test_ausgelaufene_quelle_beendet_den_strom_ohne_ausnahme():
    """PEP 479: a StopAsyncIteration escaping the source's own __anext__()
    used to leave the enclosing generator as an unhandled RuntimeError
    instead of ending the SSE stream cleanly."""

    async def quelle():
        yield {"eins": 1}
        yield {"zwei": 2}
        # ends here, on its own — the source running dry, not an error.

    zeilen = [zeile async for zeile in befehle._sse_strom(quelle())]

    assert zeilen == [
        'data: {"eins": 1}\n\n',
        'data: {"zwei": 2}\n\n',
    ]


@pytest.mark.asyncio
async def test_leere_quelle_beendet_den_strom_sofort():
    async def quelle():
        return
        yield  # pragma: no cover - never reached, keeps this a generator

    zeilen = [zeile async for zeile in befehle._sse_strom(quelle())]
    assert zeilen == []


# --- The heartbeat lives inside zuschauen() now -------


@pytest.mark.asyncio
async def test_ein_herzschlag_wird_zur_kommentarzeile_und_der_strom_geht_weiter():
    """A ``None`` from the source is a heartbeat, not an event — an
    EventSource client would try to parse a data line, so it becomes an SSE
    comment instead. And the stream does not stop there: a real event right
    after it still arrives on the SAME iteration."""

    async def quelle():
        yield None
        yield {"eins": 1}

    zeilen = [zeile async for zeile in befehle._sse_strom(quelle())]

    assert zeilen == [": still here\n\n", 'data: {"eins": 1}\n\n']


async def _bis_zum_ersten_ereignis(chat_id: str) -> list:
    ergebnisse: list = []
    async for ereignis in hintergrund.laeufe.zuschauen(chat_id, herzschlag_sekunden=0.01):
        ergebnisse.append(ereignis)
        if ereignis is not None:
            return ergebnisse
    return ergebnisse  # pragma: no cover - only reached if the source ends


@pytest.mark.asyncio
async def test_zuschauen_ueberlebt_mehrere_herzschlaege_und_liefert_das_naechste_ereignis(
    ordner,
):
    """The actual bug: wrapping __anext__() in asyncio.wait_for from the
    OUTSIDE used to cancel the generator's own suspended await on its very
    first timeout — an async generator that lets a CancelledError escape is
    closed for good, silently, no matter what was still queued behind it.
    Waiting inside zuschauen() itself must survive any number of heartbeats
    and still deliver the next real event on the same connection."""
    aufgabe = asyncio.ensure_future(_bis_zum_ersten_ereignis("chat-1"))
    # Long enough for several heartbeats at this rate, short enough to keep
    # the test fast: the connection stays open for longer than two heartbeats.
    await asyncio.sleep(0.05)
    hintergrund.laeufe.melden(
        "chat-1", typ="lauf_start", lauf=1, befehl="x", hintergrund=False, art="befehl"
    )
    ergebnisse = await asyncio.wait_for(aufgabe, timeout=2)

    assert len(ergebnisse) >= 3, "too few heartbeats to really test the case"
    assert ergebnisse[:-1] == [None] * (len(ergebnisse) - 1)
    assert ergebnisse[-1]["typ"] == "lauf_start"


# --- The buffer ------------------------------------------------------------


def test_der_puffer_behaelt_beide_enden():
    lauf = hintergrund.Lauf(nummer=1, chat_id="chat-1", befehl="x")
    zeile = "y" * 1000
    for nummer in range(400):
        lauf.anhaengen(f"{nummer:04} {zeile}")
    text = lauf.ausgabe
    assert len(text) <= hintergrund.MAX_PUFFER_ZEICHEN + 200
    assert text.startswith("0000 ")
    assert text.rstrip().endswith(f"0399 {zeile}")
    assert "cut out of the middle" in text
