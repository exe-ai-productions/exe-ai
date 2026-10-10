"""One answer per chat — including while the next one is still being set up.

``antwort_anstossen`` asks whether the chat is free and then takes its time:
it loads an embedding model for a chat with a cut-up document, and it sends a
whole model request when the history has grown past the compaction threshold.
Both are awaits, and an await is where the next caller runs.

For a while nothing checked again after them. Two callers were both told the
chat was free, both started, and the chat carried two answers — of which
``fuer_chat`` hands out only the first, so the second wrote into a row no
window was looking at.

So what is checked here is not "does the guard exist" but "does it survive
the waiting": every test parks one caller on the compaction await and lets a
second one in behind it. The claim (``Generierungsverwaltung.reservieren``)
is what has to hold, and it has to be handed back on every way out — a run
that never started must not lock the chat for the life of the service.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app import chatverdichtung, hintergrundwecken
from app.api.v1.generierung import antwort_anstossen
from app.api.v1.schemas import GenerierungAnfrage
from app.providers import MockProvider


@pytest.fixture
async def dienst(config):
    """A real app whose lifespan has run — the wake is wired in at startup,
    and one of these tests goes through it."""
    from app.main import app_erstellen

    app = app_erstellen(config)
    async with app.router.lifespan_context(app):
        yield app


def _modell(app, haeppchen=("ok",), verzoegerung: float = 0.0) -> MockProvider:
    provider = MockProvider(haeppchen=list(haeppchen), verzoegerung=verzoegerung)
    zustand = app.state.discovery.zustaende["test"]
    zustand.provider = provider
    zustand.erreichbar = True
    return provider


def _chat(app, endpoint_id: str | None = "test"):
    return app.state.repositories.chats.erstellen(
        user_id="standard", title="Nachtarbeit", endpoint_id=endpoint_id
    )


def _anstossen(app, chat_id: str, **felder):
    """One call to the function under test, with the fixtures it wants.

    Handed back as a coroutine rather than awaited, because most of these
    tests need it as a task they can park and look at.
    """
    return antwort_anstossen(
        app=app,
        daten=GenerierungAnfrage(chat_id=chat_id, **felder),
        repositories=app.state.repositories,
        discovery=app.state.discovery,
        generierungen=app.state.generierungen,
        user_id="standard",
        sprache="de",
    )


def _mitschreiben(app) -> list:
    """Every run this service registers from here on.

    Asked for by this list rather than by ``fuer_chat``: a run that started
    and ended again is gone from there, and "it is not there now" says
    nothing about whether it ever existed. What this defect is about is
    exactly a run that should never have been registered.
    """
    gestartet: list = []
    echt = app.state.generierungen.starten

    def starten(**felder):
        lauf = echt(**felder)
        gestartet.append(lauf)
        return lauf

    app.state.generierungen.starten = starten
    return gestartet


def _laufende_zeilen(app, chat_id: str) -> list:
    """The rows marked as being written right now. There must never be two:
    that is the shape the defect takes in the database, and the one a cold
    window reads."""
    return [
        n
        for n in app.state.repositories.messages.auflisten(chat_id=chat_id)
        if n.zustand == "laeuft"
    ]


def _verdichtung_anhalten(monkeypatch):
    """Parks the FIRST caller on the compaction await and lets the rest
    through.

    The real await, not a stand-in sleep: this is the one that grew the
    window from milliseconds to seconds, and patching it here keeps the test
    about the place the defect lives. What it returns is what a chat below
    the threshold gets anyway.
    """
    drin = asyncio.Event()
    weiter = asyncio.Event()
    erster = {"offen": True}

    async def angehalten(**_felder):
        if erster["offen"]:
            erster["offen"] = False
            drin.set()
            await weiter.wait()
        return None

    monkeypatch.setattr(chatverdichtung, "vielleicht_verdichten", angehalten)
    return drin, weiter


async def _aufraeumen(gestartet: list) -> None:
    """Ends every run a test started, so nothing writes into a database that
    is being torn down."""
    for lauf in gestartet:
        if lauf.aufgabe is not None:
            lauf.aufgabe.cancel()
    await asyncio.gather(
        *[lauf.aufgabe for lauf in gestartet if lauf.aufgabe is not None],
        return_exceptions=True,
    )


# --- The window itself ------------------------------------------------------


async def test_ein_zweiter_anstoss_im_wartefenster_bekommt_409(dienst, monkeypatch):
    """Two people, one chat. The second must be turned away even though the
    first has not registered its run yet."""
    _modell(dienst, verzoegerung=5.0)
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)
    drin, weiter = _verdichtung_anhalten(monkeypatch)

    erster = asyncio.create_task(_anstossen(dienst, chat.id, content="Hallo"))
    await drin.wait()

    with pytest.raises(HTTPException) as gefangen:
        await _anstossen(dienst, chat.id, content="Und noch mal")
    assert gefangen.value.status_code == 409

    weiter.set()
    await erster
    assert len(gestartet) == 1
    assert len(_laufende_zeilen(dienst, chat.id)) == 1

    await _aufraeumen(gestartet)


async def test_eine_weckung_im_wartefenster_startet_keinen_zweiten_lauf(
    dienst, monkeypatch
):
    """The case from the field: the chat is over the compaction threshold,
    the user presses send, and a background command finishes while that
    request hangs on the summary.

    The claim closes the window for one wake against another as well — a
    wake takes it through ``antwort_anstossen`` before the first await —
    and a user request goes through the same door, so the claim is what
    has to catch this one.
    """
    _modell(dienst, verzoegerung=5.0)
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)
    drin, weiter = _verdichtung_anhalten(monkeypatch)

    benutzer = asyncio.create_task(_anstossen(dienst, chat.id, content="Hallo"))
    await drin.wait()

    # Straight into the wake, not through a finished command: what is on
    # trial is the window, and the queueing in between would only make the
    # moment harder to hit exactly.
    await hintergrundwecken._wecken(dienst, chat.id)

    weiter.set()
    lauf = await benutzer

    assert [g.id for g in gestartet] == [lauf.id]
    assert len(_laufende_zeilen(dienst, chat.id)) == 1
    assert dienst.state.generierungen.fuer_chat(chat.id) is lauf

    await _aufraeumen(gestartet)


async def test_ein_anderer_chat_bleibt_frei(dienst, monkeypatch):
    """The claim is per chat, not a lock on the service. A second chat must
    still be able to answer while the first one is being set up."""
    _modell(dienst, verzoegerung=5.0)
    einer = _chat(dienst)
    anderer = _chat(dienst)
    gestartet = _mitschreiben(dienst)
    drin, weiter = _verdichtung_anhalten(monkeypatch)

    erster = asyncio.create_task(_anstossen(dienst, einer.id, content="Hallo"))
    await drin.wait()

    zweiter = await _anstossen(dienst, anderer.id, content="Hallo")
    assert zweiter.chat_id == anderer.id

    weiter.set()
    await erster
    assert len(gestartet) == 2

    await _aufraeumen(gestartet)


# --- Handing the claim back -------------------------------------------------


async def test_ein_frueher_fehler_gibt_den_chat_wieder_frei(dienst):
    """A request turned away before any waiting — here: no model set — still
    took the claim, and owes it back. Kept, it would lock the chat out of
    answering for as long as the service runs, and there would be no run
    left over to see that from."""
    _modell(dienst)
    chat = _chat(dienst, endpoint_id=None)

    with pytest.raises(HTTPException) as gefangen:
        await _anstossen(dienst, chat.id, content="Hallo")
    assert gefangen.value.status_code == 400

    gestartet = _mitschreiben(dienst)
    lauf = await _anstossen(dienst, chat.id, endpoint_id="test", content="Hallo")
    await lauf.fertig.wait()
    assert len(gestartet) == 1


async def test_ein_fehler_hinter_dem_warten_gibt_den_chat_wieder_frei(
    dienst, monkeypatch
):
    """The same, for everything that can go wrong AFTER the claim was taken
    and the waiting has begun — a provider that throws while folding the
    history is the one that reaches furthest."""
    _modell(dienst)
    chat = _chat(dienst)

    async def scheitert(**_felder):
        raise RuntimeError("Verdichtung gescheitert")

    monkeypatch.setattr(chatverdichtung, "vielleicht_verdichten", scheitert)
    with pytest.raises(RuntimeError):
        await _anstossen(dienst, chat.id, content="Hallo")

    monkeypatch.undo()
    gestartet = _mitschreiben(dienst)
    lauf = await _anstossen(dienst, chat.id, content="Noch mal")
    await lauf.fertig.wait()
    assert len(gestartet) == 1


async def test_ein_abgebrochener_anstoss_gibt_den_chat_wieder_frei(dienst, monkeypatch):
    """A browser that closes while the request waits cancels the task in the
    middle of the claim. Cancellation is not an error and passes no
    ``except`` — only a ``finally`` sees it."""
    _modell(dienst)
    chat = _chat(dienst)
    drin, _weiter = _verdichtung_anhalten(monkeypatch)

    abgebrochen = asyncio.create_task(_anstossen(dienst, chat.id, content="Hallo"))
    await drin.wait()
    abgebrochen.cancel()
    with pytest.raises(asyncio.CancelledError):
        await abgebrochen

    gestartet = _mitschreiben(dienst)
    lauf = await _anstossen(dienst, chat.id, content="Noch mal")
    await lauf.fertig.wait()
    assert len(gestartet) == 1


# --- What the service says about a chat it holds ---------------------------


def _seite(app, chat_id: str):
    """The chat route's own answer, the way a window fetches it — the same
    call `GET /{chat}/messages` makes, without the HTTP around it."""
    from fastapi import Response

    from app.api.v1.chats import nachrichten_auflisten

    # limit/offset/neueste are handed over as plain values: called directly,
    # the route's own defaults are still `Query` markers, which the database
    # layer cannot bind.
    return nachrichten_auflisten(
        chat_id=chat_id,
        antwort=Response(),
        limit=500,
        offset=0,
        neueste=False,
        repositories=app.state.repositories,
        user_id="standard",
        sprache="de",
        generierungen=app.state.generierungen,
    )


def _stopp(app, **felder):
    """The stop route's own function, called the way the route calls it."""
    from app.api.v1.generierung import stoppen
    from app.api.v1.schemas import AbbruchAnfrage

    return stoppen(
        daten=AbbruchAnfrage(**felder),
        generierungen=app.state.generierungen,
        sprache="de",
    )


async def test_ein_chat_auf_der_verdichtung_gilt_als_gehalten(dienst, monkeypatch):
    """A window whose send broke before the stream's `start` asks the service
    about the chat. While the setup still folds, there is no run to name —
    and the answer it started is nevertheless on its way. Told nothing, the
    window wrote the send off as failed and drew a red dot under it."""
    _modell(dienst, verzoegerung=5.0)
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)
    drin, weiter = _verdichtung_anhalten(monkeypatch)

    anstoss = asyncio.create_task(_anstossen(dienst, chat.id, content="Hallo"))
    await drin.wait()

    seite = _seite(dienst, chat.id)
    assert seite.laufend is None, "no run is registered here yet"
    assert seite.gehalten is True, "the service holds the chat and does not say so"

    weiter.set()
    lauf = await anstoss
    danach = _seite(dienst, chat.id)
    assert danach.gehalten is False, "held, although the run is running"
    assert danach.laufend is not None
    assert danach.laufend.generation_id == lauf.id
    assert danach.laufend.message_id == lauf.message_id

    await lauf.fertig.wait()
    await _aufraeumen(gestartet)


async def test_ein_ruhender_chat_gilt_nicht_als_gehalten(dienst):
    """Silence probe: a chat nobody is working on answers exactly as it did
    before — no run, and not held either."""
    _modell(dienst)
    chat = _chat(dienst)

    seite = _seite(dienst, chat.id)
    assert seite.laufend is None
    assert seite.gehalten is False


async def test_eine_gescheiterte_verdichtung_laesst_den_chat_frei(dienst, monkeypatch):
    """Partial failure: a fold that throws leaves the chat neither running
    nor held — the window waiting on it has to learn that it may stop."""
    _modell(dienst)
    chat = _chat(dienst)

    async def scheitert(**_felder):
        raise RuntimeError("Verdichtung gescheitert")

    monkeypatch.setattr(chatverdichtung, "vielleicht_verdichten", scheitert)
    with pytest.raises(RuntimeError):
        await _anstossen(dienst, chat.id, content="Hallo")

    seite = _seite(dienst, chat.id)
    assert seite.laufend is None
    assert seite.gehalten is False


# --- The stop button before the start --------------------------------------


async def test_ein_stopp_ueber_die_chat_kennung_beendet_den_anspruch(
    dienst, monkeypatch
):
    """The stop button pressed while the service folds. The window has no run
    id yet — the chat id is all it can send, and it has to be enough: the
    press used to count zero, and the answer began anyway."""
    _modell(dienst, verzoegerung=5.0)
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)
    drin, weiter = _verdichtung_anhalten(monkeypatch)

    anstoss = asyncio.create_task(_anstossen(dienst, chat.id, content="Hallo"))
    await drin.wait()

    antwort = _stopp(dienst, chat_id=chat.id)
    assert antwort.abgebrochen == 1, "the stop did not reach the claim"

    weiter.set()
    await anstoss

    assert gestartet == [], "a run was registered despite the stop"
    assert _laufende_zeilen(dienst, chat.id) == []
    # The question stands without an answer, like after a fold that failed —
    # nothing else was written.
    zeilen = dienst.state.repositories.messages.auflisten(chat_id=chat.id)
    assert [z.role for z in zeilen] == ["user"], [(z.role, z.zustand) for z in zeilen]

    # And the chat is free: the next send goes through.
    lauf = await _anstossen(dienst, chat.id, content="Noch mal")
    await lauf.fertig.wait()
    assert len(gestartet) == 1


async def test_ein_stopp_mit_laufkennung_bricht_weiterhin_ab(dienst):
    """Silence probe: the stop by run id does exactly what it always did."""
    _modell(dienst, verzoegerung=5.0)
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)

    lauf = await _anstossen(dienst, chat.id, content="Hallo")
    antwort = _stopp(dienst, generation_id=lauf.id)
    assert antwort.abgebrochen == 1

    await lauf.fertig.wait()
    assert len(gestartet) == 1
    assert _laufende_zeilen(dienst, chat.id) == []


async def test_ein_stopp_fuer_einen_anderen_chat_laesst_den_anspruch_in_ruhe(
    dienst, monkeypatch
):
    """Silence probe: the stop is per chat. A press in another chat must not
    end a setup that belongs to this one."""
    _modell(dienst, verzoegerung=5.0)
    gemeint = _chat(dienst)
    anderer = _chat(dienst)
    gestartet = _mitschreiben(dienst)
    drin, weiter = _verdichtung_anhalten(monkeypatch)

    anstoss = asyncio.create_task(_anstossen(dienst, gemeint.id, content="Hallo"))
    await drin.wait()

    assert _stopp(dienst, chat_id=anderer.id).abgebrochen == 0

    weiter.set()
    lauf = await anstoss
    assert len(gestartet) == 1
    assert dienst.state.generierungen.fuer_chat(gemeint.id) is lauf

    await lauf.fertig.wait()
    await _aufraeumen(gestartet)


async def test_ein_stopp_ohne_anspruch_hinterlaesst_nichts(dienst):
    """Partial failure: a stop for a chat that nothing holds counts zero,
    leaves no mark, and the next send runs through as always."""
    _modell(dienst, verzoegerung=5.0)
    chat = _chat(dienst)

    assert _stopp(dienst, chat_id=chat.id).abgebrochen == 0

    gestartet = _mitschreiben(dienst)
    lauf = await _anstossen(dienst, chat.id, content="Hallo")
    await lauf.fertig.wait()
    assert len(gestartet) == 1


async def test_ein_stopp_ohne_jede_kennung_bleibt_ein_fehler(dienst):
    """The route still refuses a stop that names nothing at all."""
    _modell(dienst)
    with pytest.raises(HTTPException) as gefangen:
        _stopp(dienst)
    assert gefangen.value.status_code == 400
