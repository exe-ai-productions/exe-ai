"""Stop closes a fold request on the spot.

A summary is a whole model request, up to ten minutes under its clocks. The
stop button used to be read only between two fold attempts, so the model
server stayed busy and the summary was written and booked after the person
had stopped. Now the request is closed when stop is pressed: nothing is
folded, nothing is booked (no pause, no failed attempt, no notice), and the
run ends the way it ends after any stop.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from app import faltpause, faltversuche, fenstergroesse, verdichtung
from app.api.v1.generierung import antwort_anstossen, stoppen
from app.api.v1.schemas import AbbruchAnfrage, GenerierungAnfrage
from app.providers import MockProvider, mock_endpunkt
from app.providers.base import ChatNachricht, Generierungsanfrage, Stueck
from tests.test_kontextvoll import (
    ZuLangDannGut,
    ZuLangImAuftrag,
    _antwort,
    _auftrag,
    _chat_mit,
    _ist_faltung,
    _langer_chat,
    _senden,
)

# How long after the fold request has gone out stop is pressed.
NACH_SEKUNDEN = 0.2
# A fold request that never ends on its own — it ends when it is closed.
NIE = 60.0


async def _haengende_bitte(provider) -> None:
    """The body both test providers share: count the request, press stop in
    ``NACH_SEKUNDEN`` where there is a button, and hang until closed."""
    provider.faltungen += 1
    if provider.stoppen is not None:
        asyncio.get_running_loop().call_later(NACH_SEKUNDEN, provider.stoppen)
    try:
        await asyncio.sleep(NIE)
    finally:
        provider.faltung_geschlossen = True


class HaengendeFaltung(ZuLangDannGut):
    """The summary request hangs until it is closed. Stop is pressed
    ``NACH_SEKUNDEN`` after it went out, by whatever ``stoppen`` does."""

    def __init__(self, *args, stoppen=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.stoppen = stoppen
        self.faltung_geschlossen = False

    async def streamen(self, anfrage):
        if _ist_faltung(anfrage):
            await _haengende_bitte(self)
            yield Stueck("content", text="summary")
            return
        async for stueck in super().streamen(anfrage):
            yield stueck


class HaengendeFaltungImAuftrag(ZuLangImAuftrag):
    def __init__(self, *args, stoppen=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.stoppen = stoppen
        self.faltung_geschlossen = False

    async def streamen(self, anfrage):
        if _ist_faltung(anfrage):
            await _haengende_bitte(self)
            yield Stueck("content", text="summary")
            return
        async for stueck in super().streamen(anfrage):
            yield stueck


@pytest.fixture
async def dienst(config):
    """A real app whose lifespan has run."""
    from app.main import app_erstellen

    app = app_erstellen(config)
    async with app.router.lifespan_context(app):
        yield app


def _anfrage() -> Generierungsanfrage:
    """A request that ends on the fold's own ask, as the test providers
    recognise one."""
    return Generierungsanfrage(
        modell="test",
        nachrichten=[ChatNachricht(role="user", content=verdichtung.ANFRAGE_TEXT)],
    )


async def test_a_stop_closes_the_fold_request_at_once():
    provider = HaengendeFaltung(mock_endpunkt("test"), zu_lang=0)
    stopp = asyncio.Event()
    asyncio.get_running_loop().call_later(NACH_SEKUNDEN, stopp.set)
    begonnen = time.monotonic()

    with pytest.raises(faltversuche.Gestoppt):
        await faltversuche.anfordern(SimpleNamespace(provider=provider), _anfrage(), stopp)

    assert provider.faltung_geschlossen
    assert time.monotonic() - begonnen < NIE / 10


async def test_a_stop_set_before_the_request_goes_out_still_closes_it():
    provider = HaengendeFaltung(mock_endpunkt("test"), zu_lang=0)
    stopp = asyncio.Event()
    stopp.set()

    with pytest.raises(faltversuche.Gestoppt):
        await faltversuche.anfordern(SimpleNamespace(provider=provider), _anfrage(), stopp)

    # Either never asked, or asked and closed again in the same breath.
    assert provider.faltungen == 0 or provider.faltung_geschlossen


async def test_silence_without_a_stop_the_summary_is_read_as_before():
    provider = MockProvider(mock_endpunkt("test"), haeppchen=["the summary"])

    text = await faltversuche.anfordern(
        SimpleNamespace(provider=provider), _anfrage(), asyncio.Event()
    )

    assert text == "the summary"


def test_silence_chat_a_stop_during_a_fold_in_the_answer_closes_the_request(client, chat_id):
    generierungen = client.app.state.generierungen
    provider = _chat_mit(
        client,
        HaengendeFaltung(
            mock_endpunkt("test"),
            zu_lang=4,
            stoppen=lambda: generierungen.alle_im_chat_abbrechen(chat_id),
        ),
    )
    _langer_chat(client, chat_id)
    begonnen = time.monotonic()

    ereignisse = _senden(client, chat_id)

    assert time.monotonic() - begonnen < NIE / 4
    # The request was closed, not waited out; the answer never began.
    assert provider.faltung_geschlossen
    assert provider.faltungen == 1
    assert len(provider.groessen) == 1
    assert ereignisse[-1]["abgebrochen"] is True
    assert _antwort(client, chat_id)["zustand"] == "abgebrochen"
    # Nothing folded: no summary row in the chat.
    zeilen = client.app.state.repositories.messages.fuer_das_modell(chat_id=chat_id)
    assert not [z for z in zeilen if (z.content or "").startswith(verdichtung.VORSPANN)]
    # Nothing booked: no pause, nothing held back for the next turn.
    assert not faltpause.pausiert(chat_id)
    assert not faltpause.automatik_gesperrt(chat_id)
    assert not [
        e for e in ereignisse
        if "fehlgeschlagen" in str(e.get("text", "")) or e.get("typ") == "error"
    ]


def test_chat_a_stopped_fold_books_no_pause(client, chat_id):
    """What a failed fold leaves behind — a pause, a run of emergencies —
    is not left by a stopped one."""
    generierungen = client.app.state.generierungen
    _chat_mit(
        client,
        HaengendeFaltung(
            mock_endpunkt("test"),
            zu_lang=4,
            stoppen=lambda: generierungen.alle_im_chat_abbrechen(chat_id),
        ),
    )
    _langer_chat(client, chat_id)

    _senden(client, chat_id)

    assert not faltpause.pausiert(chat_id)
    assert not faltpause.automatik_gesperrt(chat_id)
    assert not faltpause._staende.get(chat_id)


def test_job_a_stop_during_the_fold_closes_the_request(config, client):
    generierungen = client.app.state.generierungen

    def stoppen():
        for lauf in generierungen.laufende():
            generierungen.abbrechen(lauf.id)

    provider = HaengendeFaltungImAuftrag(mock_endpunkt("test"), zu_lang=4, stoppen=stoppen)
    begonnen = time.monotonic()

    daten = _auftrag(client, config, provider)

    assert time.monotonic() - begonnen < NIE / 4
    assert provider.faltung_geschlossen
    assert daten["state"] == "abgebrochen"
    assert provider.faltungen == 1
    assert len(provider.groessen) == 1
    # No notice that the fold failed: it did not fail, it was stopped.
    status = [
        zeile for zeile in str(daten.get("log", "")).splitlines()
        if "Komprimierung fehlgeschlagen" in zeile
    ]
    assert not status
    assert not faltpause.pausiert(daten.get("id", ""))


def test_silence_a_stop_in_another_chat_lets_the_fold_run(client, chat_id):
    """Stop of a different chat does not reach this chat's fold: it goes to
    its end and the answer comes after it."""
    generierungen = client.app.state.generierungen
    provider = _chat_mit(
        client,
        ZuLangDannGut(
            mock_endpunkt("test"),
            zu_lang=1,
            beim_falten=lambda: generierungen.alle_im_chat_abbrechen("some-other-chat"),
        ),
    )
    _langer_chat(client, chat_id)

    ereignisse = _senden(client, chat_id)

    assert provider.faltungen == 1
    assert len(provider.groessen) == 2
    assert "".join(e.get("text", "") for e in ereignisse if e["typ"] == "content") == "Hello World"


async def test_a_stop_during_the_fold_before_the_answer_closes_the_request(dienst):
    """The fold the service makes BEFORE an answer: only the claim of the
    chat carries the stop there, and it used to be read after the summary
    had been written."""
    provider = HaengendeFaltung(mock_endpunkt("test"), zu_lang=0)
    zustand = dienst.state.discovery.zustaende["test"]
    zustand.provider = provider
    zustand.erreichbar = True
    # A small window the new message pushes the history over.
    zustand.context_tokens = 3_000
    zustand.kontext_quelle = fenstergroesse.QUELLE_EINGETRAGEN
    repositories = dienst.state.repositories
    chat = repositories.chats.erstellen(
        user_id="standard", title="Stopp", endpoint_id="test"
    )
    for nr in range(12):
        repositories.messages.speichern(
            chat_id=chat.id, role="user", content=f"question {nr} " + "x" * 2_000
        )
        repositories.messages.speichern(
            chat_id=chat.id, role="assistant", content=f"answer {nr} " + "x" * 2_000,
            zustand="fertig",
        )
    gestartet = []
    echt = dienst.state.generierungen.starten

    def starten(**felder):
        lauf = echt(**felder)
        gestartet.append(lauf)
        return lauf

    dienst.state.generierungen.starten = starten

    anstoss = asyncio.create_task(antwort_anstossen(
        app=dienst,
        daten=GenerierungAnfrage(chat_id=chat.id, content="new question " + "y" * 16_000),
        repositories=repositories,
        discovery=dienst.state.discovery,
        generierungen=dienst.state.generierungen,
        user_id="standard",
        sprache="de",
    ))
    for _ in range(100):
        if provider.faltungen:
            break
        await asyncio.sleep(0.05)
    assert provider.faltungen == 1, "the fold request never went out"

    begonnen = time.monotonic()
    antwort = stoppen(
        daten=AbbruchAnfrage(chat_id=chat.id),
        generierungen=dienst.state.generierungen,
        sprache="de",
    )
    assert antwort.abgebrochen == 1
    await asyncio.wait_for(anstoss, timeout=NIE / 4)

    assert time.monotonic() - begonnen < NIE / 4
    assert provider.faltung_geschlossen, "the fold request ran on after the stop"
    assert gestartet == [], "an answer began despite the stop"
    zeilen = repositories.messages.auflisten(chat_id=chat.id)
    assert not [z for z in zeilen if (z.content or "").startswith(verdichtung.VORSPANN)]
    assert not faltpause.pausiert(chat.id)
    assert not faltpause.automatik_gesperrt(chat.id)
