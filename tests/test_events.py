"""Event system: delivery, decoupling, fault tolerance."""

from __future__ import annotations

import asyncio
import logging

import pytest

from app.events import Ereignisse, EventBus


@pytest.mark.asyncio
async def test_handler_wird_aufgerufen():
    bus = EventBus()
    empfangen = []

    async def handler(**daten):
        empfangen.append(daten)

    bus.abonnieren(Ereignisse.CHAT_ERSTELLT, handler)
    await bus.veroeffentlichen(Ereignisse.CHAT_ERSTELLT, chat_id="abc")

    assert empfangen == [{"chat_id": "abc"}]


@pytest.mark.asyncio
async def test_synchroner_handler_funktioniert_auch():
    bus = EventBus()
    empfangen = []

    def handler(**daten):
        empfangen.append(daten)

    bus.abonnieren("test", handler)
    await bus.veroeffentlichen("test", wert=1)

    assert empfangen == [{"wert": 1}]


@pytest.mark.asyncio
async def test_mehrere_abonnenten_bekommen_alle_das_ereignis():
    bus = EventBus()
    zaehler = []

    for nummer in range(3):
        bus.abonnieren("test", lambda nummer=nummer, **_: zaehler.append(nummer))

    await bus.veroeffentlichen("test")
    assert sorted(zaehler) == [0, 1, 2]


@pytest.mark.asyncio
async def test_defekter_handler_blockiert_die_anderen_nicht():
    bus = EventBus()
    erfolgreich = []

    def kaputt(**_):
        raise RuntimeError("absichtlich")

    bus.abonnieren("test", kaputt)
    bus.abonnieren("test", lambda **_: erfolgreich.append(True))

    await bus.veroeffentlichen("test")  # must not raise
    assert erfolgreich == [True]


@pytest.mark.asyncio
async def test_abbestellen_wirkt():
    bus = EventBus()
    empfangen = []

    def handler(**_):
        empfangen.append(True)

    bus.abonnieren("test", handler)
    bus.abbestellen("test", handler)
    await bus.veroeffentlichen("test")

    assert empfangen == []


@pytest.mark.asyncio
async def test_ereignis_ohne_abonnenten_ist_harmlos():
    bus = EventBus()
    await bus.veroeffentlichen("niemand_hoert_zu", wert=1)


# --- Fire and forget, but not forget the task ------------------------------


@pytest.mark.asyncio
async def test_alle_ereignisse_kommen_an_auch_viele_auf_einmal():
    """The task a `create_task` hands back is the only strong reference
    there is — the loop keeps a weak one, so an announcement nobody holds
    may be collected before it runs. Rarely, which is the worst kind of
    fault there is, and the bus now carries every notice to the user."""
    bus = EventBus()
    angekommen = []
    bus.abonnieren("test", lambda nummer, **_: angekommen.append(nummer))

    wieviele = 300
    for nummer in range(wieviele):
        bus.veroeffentlichen_ohne_warten("test", nummer=nummer)
    # Held, all of them, until they have run.
    assert bus.offene_aufgaben == wieviele
    await bus.stillstand()

    assert sorted(angekommen) == list(range(wieviele))
    assert bus.offene_aufgaben == 0


@pytest.mark.asyncio
async def test_ein_werfender_handler_steht_im_protokoll(caplog):
    """And the others run anyway: a fire-and-forget announcement has no
    caller left to raise at, so the log is the only place a broken
    subscriber can surface at all."""
    bus = EventBus()
    andere = []

    def kaputt(**_):
        raise RuntimeError("Kabelbrand")

    bus.abonnieren("test", kaputt)
    bus.abonnieren("test", lambda **_: andere.append(True))

    with caplog.at_level(logging.ERROR, logger="app.events"):
        bus.veroeffentlichen_ohne_warten("test")
        await bus.stillstand()

    assert andere == [True]
    assert any("Kabelbrand" in eintrag.message or "Kabelbrand" in str(eintrag.exc_info)
               for eintrag in caplog.records)


@pytest.mark.asyncio
async def test_ohne_laufende_schleife_ist_es_gleich_erledigt():
    """A script or a synchronous test fires without a loop — that path is
    unchanged, and it is done before the call returns."""
    bus = EventBus()
    angekommen = []
    bus.abonnieren("test", lambda **_: angekommen.append(True))

    await asyncio.to_thread(bus.veroeffentlichen_ohne_warten, "test")

    assert angekommen == [True]
    assert bus.offene_aufgaben == 0
