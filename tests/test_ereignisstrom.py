"""The live line that belongs to no chat (app/ereignisstrom.py).

What matters here is not that a queue works but that the line says the
right things to every window at once, keeps saying something while nothing
happens, and does not grow without end behind a listener that stopped
reading.
"""

from __future__ import annotations

import asyncio
import contextlib
import json

import pytest

from app import ereignisstrom
from app.api.v1.ereignisse import _sse_strom
from app.ereignisstrom import Ereignisstrom
from app.events import Ereignisse, bus


async def _naechstes(lauscher, *, grenze=1.0):
    """The next thing off a watcher, with a ceiling so a broken test fails
    instead of hanging the suite."""
    return await asyncio.wait_for(lauscher.__anext__(), timeout=grenze)


async def _lauschend(strom, anzahl=1, *, grenze=1.0):
    """Waits until that many watchers have actually registered.

    An async generator runs no line of its own body until the first
    ``__anext__()``, so the queue only exists once the task driving it has
    got that far. A bare ``sleep(0)`` is one turn of the loop and lands
    there only by luck — this waits for the fact instead of for a moment.
    """
    schluss = asyncio.get_running_loop().time() + grenze
    while strom.zuschauer < anzahl:
        assert asyncio.get_running_loop().time() < schluss, "watcher never arrived"
        await asyncio.sleep(0.005)


# --- The hub ---------------------------------------------------------------


async def test_jedes_fenster_hoert_dasselbe():
    strom = Ereignisstrom()
    eins = strom.zuschauen()
    zwei = strom.zuschauen()
    # A generator registers its queue on the first step, so both have to be
    # started before anything is announced.
    erste = asyncio.ensure_future(_naechstes(eins))
    zweite = asyncio.ensure_future(_naechstes(zwei))
    await _lauschend(strom, 2)
    strom.melden("auftrag_beendet", auftrag_id="a")

    assert await erste == {"typ": "auftrag_beendet", "auftrag_id": "a"}
    assert await zweite == {"typ": "auftrag_beendet", "auftrag_id": "a"}
    await eins.aclose()
    await zwei.aclose()


async def test_ohne_zuschauer_faellt_nichts_um():
    strom = Ereignisstrom()
    strom.melden("auftrag_beendet", auftrag_id="a")
    assert strom.zuschauer == 0


async def test_ein_zuschauer_geht_wieder_weg():
    """A closed window leaves nothing behind — otherwise every reconnect
    would add a queue nobody ever reads again."""
    strom = Ereignisstrom()
    lauscher = strom.zuschauen()
    aufgabe = asyncio.ensure_future(_naechstes(lauscher))
    await _lauschend(strom)
    # Awaited, not merely cancelled: the cancellation has to be DELIVERED
    # before the generator's `finally` can have run.
    aufgabe.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await aufgabe
    await lauscher.aclose()
    assert strom.zuschauer == 0


async def test_der_herzschlag_kommt_wenn_nichts_passiert():
    """A line that says nothing for minutes is a line something in between
    may decide is dead."""
    strom = Ereignisstrom()
    lauscher = strom.zuschauen(herzschlag_sekunden=0.01)
    assert await _naechstes(lauscher) is None
    await lauscher.aclose()


async def test_wer_nicht_mehr_liest_laesst_die_schlange_nicht_wachsen():
    """A tab the machine suspended must not cost memory without end. Past
    the ceiling its line is ENDED rather than quietly thinned."""
    strom = Ereignisstrom()
    # The queue is registered by hand here rather than through a watcher
    # nobody drives: a generator whose task is cancelled unregisters itself,
    # which is the opposite of the case under test.
    schlange: asyncio.Queue = asyncio.Queue()
    strom._zuschauer.add(schlange)

    for nummer in range(ereignisstrom.SCHLANGENGRENZE + 50):
        strom.melden("auftrag_beendet", auftrag_id=str(nummer))

    # Only the mark is left. The waiting messages went with the line: they
    # are worth nothing to a watcher whose line has ended, and behind two
    # hundred of them the mark would have been the last thing read instead
    # of the next one.
    assert schlange.qsize() == 1
    assert schlange.get_nowait() is ereignisstrom._UEBERLAUF
    # And it is offered nothing further: a queue nobody drains is dropped.
    assert strom.zuschauer == 0


async def test_ein_ueberlaufener_zuschauer_bekommt_seine_leitung_beendet():
    """Thinning was safe only while every event said "go and look". An event
    that CARRIES the state has no next one to make good a dropped message —
    so the line ends, the browser reconnects, and the reconnect asks."""
    strom = Ereignisstrom()
    lauscher = strom.zuschauen(herzschlag_sekunden=0.01)
    erste = asyncio.ensure_future(_naechstes(lauscher))
    await _lauschend(strom)
    assert await erste is None  # the heartbeat, so the generator is running

    schlange = next(iter(strom._zuschauer))
    for nummer in range(ereignisstrom.SCHLANGENGRENZE + 5):
        strom.melden("auftrag_beendet", auftrag_id=str(nummer))

    # The end of the line, and nothing before it: the mark is the NEXT thing
    # read, not the two-hundred-and-first. A watcher that never reads again
    # would never have reached it.
    gesehen = 0
    with pytest.raises(StopAsyncIteration):
        while True:
            await _naechstes(lauscher)
            gesehen += 1
    assert gesehen == 0
    assert schlange is not None


async def test_unter_der_grenze_geht_keine_meldung_verloren():
    """The silence probe for the emptying above: a watcher that is merely
    slow, not gone, keeps every message. Emptying the queue is what happens
    to a line that has ENDED, never to one that is still being read."""
    strom = Ereignisstrom()
    schlange: asyncio.Queue = asyncio.Queue()
    strom._zuschauer.add(schlange)

    for nummer in range(ereignisstrom.SCHLANGENGRENZE - 1):
        strom.melden("auftrag_beendet", auftrag_id=str(nummer))

    assert schlange.qsize() == ereignisstrom.SCHLANGENGRENZE - 1
    assert strom.zuschauer == 1
    assert schlange.get_nowait()["auftrag_id"] == "0"


# --- What comes off the bus ------------------------------------------------


@pytest.fixture
def angemeldet():
    ereignisstrom.anmelden()
    yield
    for ereignis, handler in ereignisstrom._WEITERLEITUNG:
        bus.abbestellen(ereignis, handler)


async def test_ein_beendeter_auftrag_geht_ueber_die_leitung(angemeldet):
    lauscher = ereignisstrom.strom.zuschauen()
    aufgabe = asyncio.ensure_future(_naechstes(lauscher))
    await _lauschend(ereignisstrom.strom)

    await bus.veroeffentlichen(
        Ereignisse.AUFTRAG_BEENDET,
        auftrag_id="a1", work_id="w1", agent="Rechercheur",
        ausgang="fertig", grund="fertig", ergebnis="ein sehr langer Bericht",
    )

    nachricht = await aufgabe
    assert nachricht["typ"] == "auftrag_beendet"
    assert nachricht["auftrag_id"] == "a1"
    assert nachricht["agent"] == "Rechercheur"
    assert nachricht["ausgang"] == "fertig"
    # The report itself stays off the line — it can be pages long, and the
    # window reads it from the job it fetches anyway.
    assert "ergebnis" not in nachricht
    await lauscher.aclose()


async def test_eine_laufende_verdichtung_geht_ueber_die_leitung(angemeldet):
    """The answer's own stream has not opened while its chat is compacted,
    so the program's line is what tells the window what the wait is for."""
    lauscher = ereignisstrom.strom.zuschauen()
    aufgabe = asyncio.ensure_future(_naechstes(lauscher))
    await _lauschend(ereignisstrom.strom)

    await bus.veroeffentlichen(Ereignisse.VERDICHTUNG_LAEUFT, chat_id="c1")

    assert await aufgabe == {"typ": "verdichtung_laeuft", "chat_id": "c1"}
    await lauscher.aclose()


async def test_ein_gefeuerter_termin_geht_ueber_die_leitung(angemeldet):
    lauscher = ereignisstrom.strom.zuschauen()
    aufgabe = asyncio.ensure_future(_naechstes(lauscher))
    await _lauschend(ereignisstrom.strom)

    await bus.veroeffentlichen(Ereignisse.TERMIN_GEFEUERT, cronjob_id="t1")

    assert await aufgabe == {"typ": "termin_gefeuert", "cronjob_id": "t1"}
    await lauscher.aclose()


async def test_der_modellserver_geht_ueber_die_leitung(angemeldet):
    """The flags travel WITH the announcement, unlike everything else on
    this line, and the server they speak for travels with them
    (app/events.py says why)."""
    lauscher = ereignisstrom.strom.zuschauen()
    aufgabe = asyncio.ensure_future(_naechstes(lauscher))
    await _lauschend(ereignisstrom.strom)

    await bus.veroeffentlichen(
        Ereignisse.MODELLSERVER_ZUSTAND,
        runner="chat", laeuft=True, flash_aktiv=True, mtp_aktiv="aktiv",
    )

    assert await aufgabe == {
        "typ": "modellserver_zustand", "runner": "chat",
        "laeuft": True, "flash_aktiv": True, "mtp_aktiv": "aktiv",
    }
    await lauscher.aclose()


async def test_ein_unbekannter_zustand_bleibt_unbekannt(angemeldet):
    """None is its own answer — "running, and nobody knows yet" — and must
    not arrive as False, which the dot would show as a fault."""
    lauscher = ereignisstrom.strom.zuschauen()
    aufgabe = asyncio.ensure_future(_naechstes(lauscher))
    await _lauschend(ereignisstrom.strom)

    await bus.veroeffentlichen(
        Ereignisse.MODELLSERVER_ZUSTAND,
        runner="chat", laeuft=True, flash_aktiv=None, mtp_aktiv=None,
    )

    assert await aufgabe == {
        "typ": "modellserver_zustand", "runner": "chat",
        "laeuft": True, "flash_aktiv": None, "mtp_aktiv": None,
    }
    await lauscher.aclose()


async def test_der_melder_traegt_aus_einem_fremden_faden_ein(angemeldet):
    """The runner reports from the thread that drains the server's log, and
    every queue on this line belongs to the service's loop. The hop home is
    the bus's business now (app/events.py), so this proves the whole road."""
    from app import runnerzustand

    lauscher = ereignisstrom.strom.zuschauen()
    aufgabe = asyncio.ensure_future(_naechstes(lauscher, grenze=2.0))
    await _lauschend(ereignisstrom.strom)

    from app.events import bus as echter_bus

    echter_bus.schleife_merken(asyncio.get_running_loop())
    melden = runnerzustand.melder(runnerzustand.CHAT)
    try:
        await asyncio.to_thread(melden, True, False, "fehler")

        assert await aufgabe == {
            "typ": "modellserver_zustand", "runner": "chat",
            "laeuft": True, "flash_aktiv": False, "mtp_aktiv": "fehler",
        }
    finally:
        echter_bus.schleife_merken(None)
    await lauscher.aclose()


async def test_zweimal_anmelden_meldet_nicht_zweimal(angemeldet):
    """The bus is process-wide and a test suite builds many apps against it.
    A handler registered twice would say everything twice."""
    ereignisstrom.anmelden()
    ereignisstrom.anmelden()
    assert len(bus.abonnenten(Ereignisse.AUFTRAG_BEENDET)) == 1


async def test_die_chatantwort_geht_nicht_ueber_diese_leitung(angemeldet):
    """One chat's word-by-word answer has its own stream and keeps it —
    every open window would otherwise read every chat's tokens."""
    lauscher = ereignisstrom.strom.zuschauen(herzschlag_sekunden=0.01)
    aufgabe = asyncio.ensure_future(_naechstes(lauscher))
    await _lauschend(ereignisstrom.strom)

    await bus.veroeffentlichen(Ereignisse.ANTWORT_FERTIG, endpoint_id="e1", stats={})

    # Nothing but the heartbeat.
    assert await aufgabe is None
    await lauscher.aclose()


# --- The SSE shape ---------------------------------------------------------


async def test_der_herzschlag_wird_ein_kommentar_keine_meldung():
    """An EventSource would hand a bare `data:` line to the client as an
    event with nothing in it."""

    async def quelle():
        yield None
        yield {"typ": "auftrag_beendet", "auftrag_id": "a"}

    zeilen = [zeile async for zeile in _sse_strom(quelle())]
    assert zeilen[0].startswith(":")
    assert zeilen[1].startswith("data: ")
    assert json.loads(zeilen[1][len("data: "):]) == {
        "typ": "auftrag_beendet", "auftrag_id": "a"
    }


def test_die_route_haengt_am_bus(client):
    """The door exists and the hub is hooked on at startup, not at import."""
    assert any(
        getattr(weg, "path", "") == "/api/v1/events/stream" for weg in client.app.routes
    )
    assert bus.abonnenten(Ereignisse.AUFTRAG_BEENDET)


async def test_eine_begonnene_antwort_geht_ueber_die_leitung(angemeldet):
    """An answer the service starts by itself — a finished background command
    woke the model — was invisible to a window idle on that chat. The line
    names it, chat, run and row, so the window can attach."""
    lauscher = ereignisstrom.strom.zuschauen()
    aufgabe = asyncio.ensure_future(_naechstes(lauscher))
    await _lauschend(ereignisstrom.strom)

    await bus.veroeffentlichen(
        Ereignisse.ANTWORT_BEGONNEN, chat_id="c1", generation_id="g1", message_id="m1"
    )

    assert await aufgabe == {
        "typ": "antwort_begonnen", "chat_id": "c1", "generation_id": "g1", "message_id": "m1",
    }
    await lauscher.aclose()
