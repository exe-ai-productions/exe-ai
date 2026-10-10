"""A finished background command carries its chat on by itself.

The report has been landing in the chat for a while
(``tests/test_hintergrundmeldung.py``) — and nothing read it. What is
checked here is the step after: the model is started again in that chat, it
finds the result in its history, and the two brakes hold — one answer at a
time, and a limited number of wakes without the user.

Everything runs against a real app with its startup done, because the
wiring IS the feature: the tool must be able to neither write a message nor
start an answer, and both handles are hung in by the service.
"""

from __future__ import annotations

import asyncio

import pytest

from app import hintergrundwecken, weckrundenwahl
from app.events import Ereignisse, bus
from app.providers import MockProvider
from app.tools.hintergrund import FERTIG, Lauf, laeufe


@pytest.fixture
async def dienst(config):
    """A real app whose lifespan has run."""
    from app.main import app_erstellen

    app = app_erstellen(config)
    async with app.router.lifespan_context(app):
        yield app


def _modell(app, haeppchen=("ok",), **rest) -> MockProvider:
    provider = MockProvider(haeppchen=list(haeppchen), **rest)
    zustand = app.state.discovery.zustaende["test"]
    zustand.provider = provider
    zustand.erreichbar = True
    return provider


def _mitschreiben(app) -> list:
    """Every run this service starts from here on.

    Asked for by the list, not by ``fuer_chat``: the dummy answers in no
    time at all, so by the time a test looks the run is over and no longer
    registered — which says nothing about whether it ever existed.
    """
    gestartet: list = []
    echt = app.state.generierungen.starten

    def starten(**felder):
        lauf = echt(**felder)
        gestartet.append(lauf)
        return lauf

    app.state.generierungen.starten = starten
    return gestartet


def _chat(app):
    return app.state.repositories.chats.erstellen(
        user_id="standard", title="Nachtarbeit", endpoint_id="test"
    )


def _lauf(chat_id: str, nummer: int = 1) -> Lauf:
    lauf = Lauf(nummer=nummer, chat_id=chat_id, befehl="make", hintergrund=True)
    lauf.code = 0
    return lauf


async def _ruhe() -> None:
    """Waits for every scheduled wake — the handle only queues one.

    Deliberately not ``bus.stillstand()`` as well: that set keeps tasks of
    every app ever built in this process, and in a full run it still holds
    ones whose loop is long closed. What is published in these tests is
    awaited where it is published anyway.
    """
    frist = 30
    start = asyncio.get_event_loop().time()
    while hintergrundwecken._aufgaben:
        # Bounded: a wedged task turns into a red test, not a hung suite.
        assert asyncio.get_event_loop().time() - start < frist, "waking hangs"
        await asyncio.wait_for(
            asyncio.gather(*list(hintergrundwecken._aufgaben), return_exceptions=True),
            timeout=frist,
        )


async def _wecken_angelaufen(dienst) -> None:
    """Waits for the fact, not for a number of loop turns: every queued
    wake task has either ENDED (it stood down) or claimed its chat (it
    started an answer and now waits at the gate). A task that has done
    neither is still on its way, and asserting about it would be asserting
    about a coin in the air. Bounded, so a wedged task is a red test."""
    generierungen = dienst.state.generierungen
    # A chat somebody else already holds says nothing about the wake filed
    # for it: `beansprucht` is true whether that wake stood down or never
    # ran at all. Such a task counts as arrived only once it has ENDED.
    fremd = {
        aufgabe.get_name().removeprefix("wecken-")
        for aufgabe in hintergrundwecken._aufgaben
        if generierungen.beansprucht(aufgabe.get_name().removeprefix("wecken-"))
    }
    unterwegs: list = []
    for _ in range(5000):
        await asyncio.sleep(0)
        unterwegs = [
            aufgabe
            for aufgabe in hintergrundwecken._aufgaben
            if not aufgabe.done()
            and (
                (chat := aufgabe.get_name().removeprefix("wecken-")) in fremd
                or not generierungen.beansprucht(chat)
            )
        ]
        if not unterwegs:
            return
    raise AssertionError(
        f"wake tasks neither ended nor claimed their chat: {[a.get_name() for a in unterwegs]}"
    )


async def _antwort_abwarten(gestartet: list) -> None:
    """Lets every run started so far reach its end."""
    for generierung in list(gestartet):
        await asyncio.wait_for(generierung.fertig.wait(), timeout=30)


# --- The wake itself --------------------------------------------------------


async def test_ein_fertiger_lauf_startet_eine_antwort(dienst):
    """The whole point: the model reads the result without being asked to."""
    provider = _modell(dienst, ["Der Build ", "ist durch."])
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)

    laeufe.abschluss(_lauf(chat.id), "BUILD SUCCESSFUL")
    await _ruhe()
    await _antwort_abwarten(gestartet)

    assert [g.chat_id for g in gestartet] == [chat.id]
    assert provider.durchlaeufe == 1
    nachrichten = dienst.state.repositories.messages.auflisten(chat_id=chat.id)
    assert [n.art for n in nachrichten] == ["werkzeugmeldung", "nachricht"]
    assert nachrichten[-1].content == "Der Build ist durch."


async def test_die_meldung_steht_im_verlauf_des_geweckten_laufs(dienst):
    """The wake is worth nothing if the answer is built before the report is
    saved — the model would then be started on a history in which nothing
    happened."""
    provider = _modell(dienst)
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)

    laeufe.abschluss(_lauf(chat.id), "BUILD SUCCESSFUL")
    await _ruhe()
    await _antwort_abwarten(gestartet)

    text = " ".join(n.content or "" for n in provider.letzte_anfrage.nachrichten)
    assert "BUILD SUCCESSFUL" in text
    assert "[background run #1 finished: make]" in text


async def test_der_geweckte_lauf_haengt_an_keiner_verbindung(dienst):
    """Nobody asked for this answer, so no connection may end it. Bound to
    one, a window that happens to stand open on the chat would take the
    answer down with it when it closes."""
    _modell(dienst, ["…"])
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)

    laeufe.abschluss(_lauf(chat.id), "fertig")
    await _ruhe()

    assert len(gestartet) == 1
    assert gestartet[0].an_verbindung_gebunden is False
    await _antwort_abwarten(gestartet)


async def test_ein_vergessener_lauf_weckt_nichts(dienst):
    """The chat is gone. The report is not written, so there is nothing to
    read and nothing to start."""
    provider = _modell(dienst)
    chat = _chat(dienst)
    lauf = _lauf(chat.id)
    lauf.vergessen = True

    laeufe.abschluss(lauf, "zu spät")
    await _ruhe()

    assert provider.durchlaeufe == 0
    assert dienst.state.repositories.messages.auflisten(chat_id=chat.id) == []


async def test_ohne_chat_wird_nicht_geweckt(dienst):
    """Deleted between the report and the task that reads it."""
    provider = _modell(dienst)

    laeufe.abschluss(_lauf("gibt-es-nicht"), "egal")
    await _ruhe()

    assert provider.durchlaeufe == 0


# --- One answer at a time ---------------------------------------------------


async def test_ein_laufender_chat_bekommt_keine_zweite_antwort(dienst):
    """A chat holds exactly one run. The wake does not open a second."""
    provider = _modell(dienst)
    chat = _chat(dienst)
    besetzt = dienst.state.generierungen.anmelden(
        chat_id=chat.id, endpoint_id="test"
    )

    laeufe.abschluss(_lauf(chat.id), "fertig")
    await _ruhe()

    assert provider.durchlaeufe == 0
    assert chat.id in hintergrundwecken._nachzuholen
    dienst.state.generierungen.abmelden(besetzt.id)


async def test_das_nachholen_kommt_wenn_die_antwort_endet(dienst):
    """And it is not dropped either: the running answer's message list was
    built before the report existed, so it cannot see the result. Held back
    and pulled again when the chat is free."""
    provider = _modell(dienst)
    chat = _chat(dienst)
    besetzt = dienst.state.generierungen.anmelden(
        chat_id=chat.id, endpoint_id="test"
    )
    gestartet = _mitschreiben(dienst)
    laeufe.abschluss(_lauf(chat.id), "fertig")
    await _ruhe()
    assert provider.durchlaeufe == 0

    dienst.state.generierungen.abmelden(besetzt.id)
    await bus.veroeffentlichen(
        Ereignisse.ANTWORT_FERTIG, chat_id=chat.id, message_id="x",
        endpoint_id="test", stats={},
    )
    await _ruhe()
    await _antwort_abwarten(gestartet)

    assert provider.durchlaeufe == 1
    assert chat.id not in hintergrundwecken._nachzuholen


async def test_zwei_gleichzeitig_fertige_befehle_wecken_einmal(dienst):
    """Two commands ending in the same loop turn are one thing to read.

    The completion handler writes its report and wakes with no await in
    between (``app/hintergrundmeldung.py``), so when two land together BOTH
    reports stand in the chat before either wake task runs. The first wake
    takes the chat and its prompt carries both of them; the second finds the
    chat busy and stands down.

    Fired anyway — which is what a note remembering only the chat id did —
    the second request is the first one plus its own reply, under an
    ``ANSTOSS`` telling the model its report is the last entry in the
    conversation when the last entry is the model's own answer. And it costs
    a second wake out of the budget to say it.
    """
    provider = _modell(dienst, ["ok"])
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)

    laeufe.abschluss(_lauf(chat.id, 1), "BUILD SUCCESSFUL")
    laeufe.abschluss(_lauf(chat.id, 2), "42 passed")
    await _ruhe()
    await _antwort_abwarten(gestartet)
    # A second wake would be queued by the end of the first answer, so the
    # drain gets its turn before anything is counted.
    await _ruhe()
    await _antwort_abwarten(gestartet)

    assert provider.durchlaeufe == 1, (
        "the second report started an answer of its own"
    )
    # Both reports reached the model, in the one request that went out.
    text = " ".join(n.content or "" for n in provider.letzte_anfrage.nachrichten)
    assert "BUILD SUCCESSFUL" in text
    assert "42 passed" in text
    # And the brake was charged once, for the one answer that happened.
    assert hintergrundwecken._weckungen.get(chat.id) == 1, (
        "the discarded wake still took from the budget"
    )
    assert [
        n.art for n in dienst.state.repositories.messages.auflisten(chat_id=chat.id)
    ] == ["werkzeugmeldung", "werkzeugmeldung", "nachricht"]


async def test_eine_spaeter_gelandete_meldung_weckt_noch_einmal(dienst):
    """The other half of the same rule: a report that really did arrive
    after the prompt was built is in nobody's prompt, and its wake goes
    ahead.

    Both cases look identical from the check — the chat was busy — so what
    tells them apart is the mark the note carries, not the fact that a wake
    stood down.
    """
    tor = asyncio.Event()
    provider = _modell(dienst, ["a"] * 8, tor=tor)
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)

    laeufe.abschluss(_lauf(chat.id, 1), "erster")
    await _wecken_angelaufen(dienst)
    assert gestartet and not gestartet[0].fertig.is_set(), (
        "the first answer was already over"
    )

    # Now, with that answer's history long since read and the model writing.
    laeufe.abschluss(_lauf(chat.id, 2), "zweiter")
    await _wecken_angelaufen(dienst)
    # "Claimed" fires the moment the run is registered, before its task has
    # had a single turn to reach the provider — waited for here as its own
    # fact, not assumed to already be true the instant the chat is claimed.
    for _ in range(5000):
        if provider.durchlaeufe >= 1:
            break
        await asyncio.sleep(0)
    assert provider.durchlaeufe == 1, "the wake ran right into the answer"

    tor.set()
    await _antwort_abwarten(gestartet)
    await _ruhe()
    await _antwort_abwarten(gestartet)

    assert provider.durchlaeufe == 2, "the later report stayed unread"
    text = " ".join(n.content or "" for n in provider.letzte_anfrage.nachrichten)
    assert "zweiter" in text


async def test_eine_meldung_waehrend_der_verdichtung_wird_noch_gelesen(dienst, monkeypatch):
    """The blind spot a mark could not see, and the chat can.

    The user's answer is being set up and waits on the compaction request.
    A background command reports during that wait, its wake finds the chat
    claimed and stands down. The prompt is read AFTER the wait, so the
    report is in it — and the answer's row is saved right behind that read,
    so the report stands before the row: read. Had the prompt been read
    before the wait, the report would be in nobody's prompt and still stand
    before the answer's row, and the chat could not have said so.

    Both halves in one: the report lands during the wait and is read by
    that very answer, and no second answer is started for it.
    """
    from app import chatverdichtung
    from app.api.v1 import generierung as generierungsmodul
    from app.api.v1.schemas import GenerierungAnfrage

    provider = _modell(dienst)
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)
    drin, weiter = asyncio.Event(), asyncio.Event()

    async def angehalten(**_felder):
        drin.set()
        await weiter.wait()
        return None

    monkeypatch.setattr(chatverdichtung, "vielleicht_verdichten", angehalten)
    benutzer = asyncio.ensure_future(generierungsmodul.antwort_anstossen(
        app=dienst,
        daten=GenerierungAnfrage(chat_id=chat.id, content="Hallo"),
        repositories=dienst.state.repositories,
        discovery=dienst.state.discovery,
        generierungen=dienst.state.generierungen,
        user_id="standard",
        sprache="de",
    ))
    await drin.wait()

    laeufe.abschluss(_lauf(chat.id), "waehrend der Faltung")
    await _ruhe()
    assert chat.id in hintergrundwecken._nachzuholen, "the wake was not postponed"

    weiter.set()
    await benutzer
    await _antwort_abwarten(gestartet)
    await _ruhe()
    await _antwort_abwarten(gestartet)

    assert provider.durchlaeufe == 1, "a second answer was started for a report the first had read"
    text = " ".join(n.content or "" for n in provider.letzte_anfrage.nachrichten)
    assert "waehrend der Faltung" in text, "the report landed in nobody's prompt"
    assert chat.id not in hintergrundwecken._nachzuholen


def test_die_frage_an_den_chat_unterscheidet_bericht_antwort_und_bremse(dienst):
    """What `_nachholen` asks: is the newest row the model sees a report
    nobody answered? An answer's row behind it says read; the brake's own
    note is a werkzeugmeldung too and must not count as a report."""
    repositories = dienst.state.repositories
    chat = _chat(dienst)
    assert hintergrundwecken._ungelesener_bericht(repositories, chat.id) is False

    laeufe.abschluss(_lauf(chat.id), "BUILD SUCCESSFUL")
    assert hintergrundwecken._ungelesener_bericht(repositories, chat.id) is True

    repositories.messages.speichern(
        chat_id=chat.id, role="assistant", content="gelesen", zustand="fertig"
    )
    assert hintergrundwecken._ungelesener_bericht(repositories, chat.id) is False

    hintergrundwecken._notiz_schreiben(repositories, chat.id, 3, 3)
    assert hintergrundwecken._ungelesener_bericht(repositories, chat.id) is False


async def test_eine_gescheiterte_weckung_gibt_die_zurueckgestellte_frei(
    dienst, monkeypatch
):
    """A wake that stood down behind an answer that never began.

    The note is worth what the run it stood down for is worth. If that run
    sets a prompt up, the report is read and the note is spent; if the model
    server has gone in the meantime, nothing was read — and then the note is
    the only thing left that can get the report in front of the model.

    Discarding it stood in the failure path, which is a lost report: the
    result waits until somebody types, which is exactly the state this
    module was built to end.
    """
    from fastapi import HTTPException

    from app.api.v1 import generierung as generierungsmodul

    provider = _modell(dienst)
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)

    echt = generierungsmodul.antwort_anstossen
    versuche: list = []

    async def erst_scheitern(**felder):
        versuche.append(felder["daten"].chat_id)
        if len(versuche) == 1:
            # Long enough for the second report's wake to run and note
            # itself behind this one — and then nothing goes out after all.
            await asyncio.sleep(0)
            raise HTTPException(503, "Modell nicht erreichbar")
        return await echt(**felder)

    monkeypatch.setattr(generierungsmodul, "antwort_anstossen", erst_scheitern)

    laeufe.abschluss(_lauf(chat.id, 1), "erster")
    laeufe.abschluss(_lauf(chat.id, 2), "zweiter")
    await _ruhe()
    await _antwort_abwarten(gestartet)

    assert len(versuche) == 2, "nothing more was tried after the failure"
    assert provider.durchlaeufe == 1, "the reports stayed unread"
    text = " ".join(n.content or "" for n in provider.letzte_anfrage.nachrichten)
    assert "erster" in text
    assert "zweiter" in text
    assert chat.id not in hintergrundwecken._nachzuholen


async def test_eine_nachricht_des_nutzers_nimmt_das_nachholen_mit(dienst):
    """A postponed wake must not outlive the reason it was postponed.

    The wake was held back because the running answer could not see the
    report — its message list was built before the report was written. A
    message from the user rebuilds that list from the database, report
    included, so the model has read it by the time that answer ends. Firing
    the held wake anyway starts a second, unasked-for answer straight after
    the user's own: they type, get their reply, and the chat then produces
    another one for no reason anybody can see.

    The count is already cleared on the user's message; this is the other
    half of the same fact.
    """
    provider = _modell(dienst)
    chat = _chat(dienst)
    besetzt = dienst.state.generierungen.anmelden(
        chat_id=chat.id, endpoint_id="test"
    )
    gestartet = _mitschreiben(dienst)
    # A report lands while an answer is being written: held back.
    laeufe.abschluss(_lauf(chat.id), "fertig")
    await _ruhe()
    assert chat.id in hintergrundwecken._nachzuholen

    # The user writes. This is what the chat route does first.
    hintergrundwecken.zuruecksetzen(chat.id)

    dienst.state.generierungen.abmelden(besetzt.id)
    await bus.veroeffentlichen(
        Ereignisse.ANTWORT_FERTIG, chat_id=chat.id, message_id="x",
        endpoint_id="test", stats={},
    )
    await _ruhe()
    await _antwort_abwarten(gestartet)

    assert provider.durchlaeufe == 0, (
        "the chat was woken anyway after a message from the user"
    )
    assert chat.id not in hintergrundwecken._nachzuholen


async def test_eine_fremde_fertige_antwort_weckt_nichts(dienst):
    """The subscriber hangs on every answer in every chat. One with nothing
    waiting must stay a lookup and nothing more."""
    provider = _modell(dienst)
    chat = _chat(dienst)

    await bus.veroeffentlichen(
        Ereignisse.ANTWORT_FERTIG, chat_id=chat.id, message_id="x",
        endpoint_id="test", stats={},
    )
    await _ruhe()

    assert provider.durchlaeufe == 0


async def test_ein_beanspruchter_chat_stellt_die_weckung_zurueck(dienst):
    """A chat can be taken by a run that is on its way but not yet
    registered (``Generierungsverwaltung.reservieren``). Asking only for the
    REGISTERED run walked straight past that claim and into the 409 behind
    it — and that 409 threw the wake away."""
    provider = _modell(dienst)
    chat = _chat(dienst)
    assert dienst.state.generierungen.reservieren(chat.id) is True

    laeufe.abschluss(_lauf(chat.id), "fertig")
    await _ruhe()

    assert provider.durchlaeufe == 0
    assert chat.id in hintergrundwecken._nachzuholen, (
        "the wake was discarded instead of postponed"
    )
    dienst.state.generierungen.freigeben(chat.id)


async def test_ein_anspruch_im_rennen_stellt_die_weckung_zurueck(dienst):
    """And the check above closes no race — only the claim inside the start
    itself can.

    So the 409 is the backstop, and it must postpone rather than drop. Most
    of the time dropping reads fine: whoever claimed the chat is typing, and
    their answer builds its history from the database with the report in it.
    But if their request then fails — a model server that went away answers
    503 — the report lies unread until somebody types again, which is the
    one thing this module exists to prevent.
    """
    provider = _modell(dienst)
    chat = _chat(dienst)
    verwaltung = dienst.state.generierungen
    echt = verwaltung.fuer_chat
    gesehen: list = []

    def erst_frei_dann_belegt(chat_id: str):
        # The claim falls the instant the wake has looked and seen nothing —
        # exactly the window no check of its own can close, and the reason
        # the answer is claimed inside the start rather than asked for
        # twice.
        if not gesehen:
            gesehen.append(chat_id)
            verwaltung.reservieren(chat_id)
            return None
        return echt(chat_id)

    verwaltung.fuer_chat = erst_frei_dann_belegt
    laeufe.abschluss(_lauf(chat.id), "fertig")
    await _ruhe()

    assert provider.durchlaeufe == 0
    assert chat.id in hintergrundwecken._nachzuholen, (
        "the wake was discarded on the 409 instead of postponed"
    )
    # And the count was given back: nothing was woken.
    assert hintergrundwecken._weckungen.get(chat.id, 0) == 0
    verwaltung.fuer_chat = echt
    verwaltung.freigeben(chat.id)


async def test_ein_geloeschter_chat_beendet_seinen_geweckten_lauf(dienst):
    """A woken run hangs on no connection — that is what carries it through
    a window closing at night, and it is also why nothing ended it when the
    chat itself went. It wrote on, ran tools on, and the button that could
    have stopped it left the sidebar with the chat."""
    from app.api.v1.chats import chat_loeschen
    from app.api.v1.generierung import antwort_anstossen
    from app.api.v1.schemas import GenerierungAnfrage

    # The slow stream stays: deletion has to abort a model that is truly
    # MID-write, and 40 chunks of 50 ms are two seconds of writing against
    # a five-second bound — the flake sat in the sleep before the assert,
    # not in the stream.
    _modell(dienst, ["…"] * 40, verzoegerung=0.05)
    chat = _chat(dienst)

    lauf = await antwort_anstossen(
        app=dienst,
        daten=GenerierungAnfrage(chat_id=chat.id),
        repositories=dienst.state.repositories,
        discovery=dienst.state.discovery,
        generierungen=dienst.state.generierungen,
        user_id="standard",
        sprache="de",
        an_verbindung_gebunden=False,
        systemhinweis=hintergrundwecken.ANSTOSS,
    )
    await _wecken_angelaufen(dienst)
    assert not lauf.fertig.is_set(), "the run was already over"

    await chat_loeschen(
        chat_id=chat.id,
        repositories=dienst.state.repositories,
        generierungen=dienst.state.generierungen,
        user_id="standard",
        sprache="de",
        # Called past FastAPI, so the dependency has to be handed in: the
        # delete takes the chat's own document folder with it and needs to
        # know where the data folder is.
        config=dienst.state.config,
    )

    await asyncio.wait_for(lauf.fertig.wait(), timeout=5)


# --- The brake --------------------------------------------------------------


def _grenze(app, wert: int) -> None:
    app.state.repositories.einstellungen.setzen(
        "global", weckrundenwahl.SCHLUESSEL, wert
    )


async def test_nach_der_grenze_ist_schluss_und_es_steht_im_chat(dienst):
    """Model starts a run, is woken, starts the next — nobody sees that at
    three in the morning. After the set number it stops, and it says so
    where both sides read it."""
    provider = _modell(dienst)
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)
    _grenze(dienst, 1)

    laeufe.abschluss(_lauf(chat.id, 1), "erster")
    await _ruhe()
    await _antwort_abwarten(gestartet)
    assert provider.durchlaeufe == 1

    laeufe.abschluss(_lauf(chat.id, 2), "zweiter")
    await _ruhe()

    assert provider.durchlaeufe == 1, "the brake did not hold"
    letzte = dienst.state.repositories.messages.auflisten(chat_id=chat.id)[-1]
    assert letzte.art == "werkzeugmeldung"
    # It has no run of its own, so it claims no state — the same rule the
    # background report follows.
    assert letzte.zustand is None
    assert "Stopping here" in letzte.content


async def test_die_notiz_steht_genau_einmal(dienst):
    """Ten commands finishing after the brake would otherwise leave ten
    identical lines in the chat."""
    _modell(dienst)
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)
    _grenze(dienst, 1)

    for nummer in range(1, 5):
        laeufe.abschluss(_lauf(chat.id, nummer), "fertig")
        await _ruhe()
        await _antwort_abwarten(gestartet)

    notizen = [
        n
        for n in dienst.state.repositories.messages.auflisten(chat_id=chat.id)
        if "Stopping here" in (n.content or "")
    ]
    assert len(notizen) == 1


async def test_eine_nachricht_des_nutzers_loest_die_bremse(dienst):
    """What the count counts is answers nobody asked for. Whoever is at the
    keyboard starts it over."""
    provider = _modell(dienst)
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)
    _grenze(dienst, 1)

    laeufe.abschluss(_lauf(chat.id, 1), "erster")
    await _ruhe()
    await _antwort_abwarten(gestartet)
    laeufe.abschluss(_lauf(chat.id, 2), "zweiter")
    await _ruhe()
    assert provider.durchlaeufe == 1

    hintergrundwecken.zuruecksetzen(chat.id)
    laeufe.abschluss(_lauf(chat.id, 3), "dritter")
    await _ruhe()
    await _antwort_abwarten(gestartet)

    assert provider.durchlaeufe == 2


async def test_ein_muellwert_faellt_auf_die_vorgabe_und_nicht_auf_null(dienst):
    """A stored number that is not a usable count must not silence the chat
    — the shipped default applies, exactly as if nobody had set anything."""
    provider = _modell(dienst)
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)
    dienst.state.repositories.einstellungen.setzen(
        "global", weckrundenwahl.SCHLUESSEL, 0
    )

    laeufe.abschluss(_lauf(chat.id), "fertig")
    await _ruhe()
    await _antwort_abwarten(gestartet)

    assert provider.durchlaeufe == 1


async def test_eine_gesenkte_grenze_sagt_es_im_chat(dienst):
    """The note used to hang on ``stand == grenze`` — true for one single
    value of the counter, while ``grenze`` is re-read from the cascade on
    every wake. Lowering the number stepped clean over the equality: the
    brake held and the chat said nothing about why."""
    provider = _modell(dienst)
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)
    _grenze(dienst, 3)

    for nummer in (1, 2, 3):
        laeufe.abschluss(_lauf(chat.id, nummer), "fertig")
        await _ruhe()
        await _antwort_abwarten(gestartet)
    assert provider.durchlaeufe == 3

    _grenze(dienst, 1)
    laeufe.abschluss(_lauf(chat.id, 4), "vierter")
    await _ruhe()

    assert provider.durchlaeufe == 3, "the brake did not hold"
    letzte = dienst.state.repositories.messages.auflisten(chat_id=chat.id)[-1]
    assert "Stopping here" in (letzte.content or ""), (
        "the brake held without saying so in the chat"
    )
    # And it names what really happened, not the new number: the chat was
    # carried on three times, and the limit is now one.
    assert "on 3 times" in letzte.content
    assert "limit is 1" in letzte.content


async def test_der_zaehler_klettert_hinter_der_bremse_nicht_weiter(dienst):
    """What it counts is wakes that happened. Counting refusals as well let
    it run away from a limit that could then never catch up with it."""
    provider = _modell(dienst)
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)
    _grenze(dienst, 2)

    for nummer in range(1, 7):
        laeufe.abschluss(_lauf(chat.id, nummer), "fertig")
        await _ruhe()
        await _antwort_abwarten(gestartet)

    assert provider.durchlaeufe == 2
    assert hintergrundwecken._weckungen.get(chat.id) == 2, (
        "the counter kept counting behind the brake"
    )


async def test_eine_angehobene_grenze_weckt_wieder(dienst):
    """A hundred reports overnight against a limit of fifty left the count
    at a hundred and more, so setting the number to a hundred in the morning
    changed nothing at all — and wrote no note about it either."""
    provider = _modell(dienst)
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)
    _grenze(dienst, 2)

    # Six reports against a limit of two: two wake, four run into the brake.
    for nummer in range(1, 7):
        laeufe.abschluss(_lauf(chat.id, nummer), "fertig")
        await _ruhe()
        await _antwort_abwarten(gestartet)
    assert provider.durchlaeufe == 2

    # In the morning the number is raised past what the night used up.
    _grenze(dienst, 3)
    laeufe.abschluss(_lauf(chat.id, 7), "am Morgen")
    await _ruhe()
    await _antwort_abwarten(gestartet)

    assert provider.durchlaeufe == 3, "raising the limit changed nothing"


async def test_nach_dem_anheben_wird_erneut_gebremst_und_erneut_gesagt(dienst):
    """One note per braking, not one for the life of the chat: a chat let
    loose again and stopped again has something new to say."""
    _modell(dienst)
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)
    _grenze(dienst, 1)

    for nummer in (1, 2, 3):
        laeufe.abschluss(_lauf(chat.id, nummer), "fertig")
        await _ruhe()
        await _antwort_abwarten(gestartet)

    _grenze(dienst, 2)
    for nummer in (4, 5):
        laeufe.abschluss(_lauf(chat.id, nummer), "fertig")
        await _ruhe()
        await _antwort_abwarten(gestartet)

    notizen = [
        n
        for n in dienst.state.repositories.messages.auflisten(chat_id=chat.id)
        if "Stopping here" in (n.content or "")
    ]
    assert len(notizen) == 2, "the second braking stayed silent"


async def test_ein_geloeschter_chat_nimmt_sein_zaehlwerk_mit(dienst):
    """Otherwise two dictionaries grow over chats that no longer exist for
    as long as the program runs."""
    chat = _chat(dienst)
    hintergrundwecken._weckungen[chat.id] = 3
    hintergrundwecken._nachzuholen.add(chat.id)

    laeufe.vergessen(chat.id)

    assert chat.id not in hintergrundwecken._weckungen
    assert chat.id not in hintergrundwecken._nachzuholen


# --- Shutdown ---------------------------------------------------------------


async def test_beim_beenden_startet_keine_wartende_weckung_mehr(config):
    """A wake is filed the moment a command reports and runs a moment later
    — and the shutdown has three ``await``s between those two moments.

    ``laeufe.alle_toeten`` does not cover it: that marks runs still GOING,
    which is what keeps a killed run's late report quiet. A command that
    finished normally a second earlier stands at FERTIG with its report
    already written. Measured before this: a whole answer started after
    "Exe AI Terminal beendet", against model servers stopped a few lines
    above it, and it wrote its row into a database that had just been
    closed — ``Database.schliessen`` drops the connection, and the next
    caller is handed a fresh one straight back.
    """
    from app.main import app_erstellen

    app = app_erstellen(config)
    async with app.router.lifespan_context(app):
        _modell(app, ["a", "b", "c"], verzoegerung=0.02)
        chat = _chat(app)
        gestartet = _mitschreiben(app)
        # A background command that finished NORMALLY a moment ago: its
        # report is written and its wake is on the loop.
        lauf = _lauf(chat.id)
        lauf.zustand = FERTIG
        laeufe.abschluss(lauf, "BUILD SUCCESSFUL")
        assert hintergrundwecken._aufgaben, "no wake was queued at all"

    await _ruhe()
    assert gestartet == [], "an answer still started after the shutdown"
    # The report is there — it was written before any of this. What must not
    # be there is an answer written against a service that is gone.
    assert [
        n.art
        for n in app.state.repositories.messages.auflisten(chat_id=chat.id)
    ] == ["werkzeugmeldung"]


# --- The wiring -------------------------------------------------------------


def test_ohne_dienst_weckt_der_lauf_niemanden(repos):
    """The tool may write no message and start no run. Registered without a
    handle — which is what every test that only wants the report does — a
    finished run reports and nothing else."""
    from app.hintergrundmeldung import anmelden

    chat = repos.chats.erstellen(user_id="standard", title="t")
    anmelden(repos)

    laeufe.abschluss(_lauf(chat.id), "fertig")

    assert [n.art for n in repos.messages.auflisten(chat_id=chat.id)] == [
        "werkzeugmeldung"
    ]


def test_die_route_setzt_das_zaehlwerk_zurueck(client, chat_id):
    """The reset hangs on the ROUTE, not on the function behind it: what
    comes through the route is the user being there, and the wake goes to
    the function directly. Hung one level lower, a wake would clear the very
    brake that is counting it."""
    from tests.conftest import provider_setzen

    provider_setzen(client, MockProvider())
    hintergrundwecken._weckungen[chat_id] = 7

    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "weiter"},
    )

    assert chat_id not in hintergrundwecken._weckungen


def test_die_zahl_laesst_sich_ueber_die_einstellungen_setzen(client):
    """A number nobody can reach is a constant with extra steps."""
    antwort = client.put(
        f"/api/v1/settings/global/{weckrundenwahl.SCHLUESSEL}", json={"wert": 8}
    )
    assert antwort.status_code == 200
    stand = client.get(
        f"/api/v1/settings/resolved/{weckrundenwahl.SCHLUESSEL}"
    ).json()
    assert stand["wert"] == 8


def test_ein_unbrauchbarer_wert_landet_nicht_in_der_kaskade(client):
    """The column checks nothing by itself, so the route's own checker has
    to. What it discards is stored as "nothing set", which is what makes the
    shipped number apply instead of a "viele" nobody could read."""
    client.put(
        f"/api/v1/settings/global/{weckrundenwahl.SCHLUESSEL}", json={"wert": "viele"}
    )
    stand = client.get(
        f"/api/v1/settings/resolved/{weckrundenwahl.SCHLUESSEL}"
    ).json()
    # Unset comes back as None or {} — 0 must NOT pass here: it is exactly
    # the value the sibling test proves must not silence the chat.
    assert stand["wert"] in (None, {}), "a junk value was stored instead of discarded"
    assert weckrundenwahl.runden(client.app.state.repositories) == weckrundenwahl.VORGABE


async def test_the_nudge_stands_behind_the_report(dienst):
    """A run nobody asked for has to say so. It says so behind the report
    that woke it, in that report's turn — a turn marked as the service's —
    and the system message stays the same bytes, so the wake does not make
    the server read the whole chat again."""
    provider = _modell(dienst)
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)

    laeufe.abschluss(_lauf(chat.id), "alle Tests gruen")
    await _ruhe()
    await _antwort_abwarten(gestartet)

    assert provider.alle_anfragen, "nothing was woken at all"
    nachrichten = provider.alle_anfragen[-1].nachrichten
    system = [n for n in nachrichten if n.role == "system"]
    assert system, "no system message in the request"
    assert hintergrundwecken.ANSTOSS not in system[0].content, (
        "the nudge still moves the system message"
    )
    report = nachrichten[-1]
    assert report.role == "user" and report.service_report, (
        "the newest turn is not the report the service wrote"
    )
    assert report.content.endswith(hintergrundwecken.ANSTOSS), (
        "the nudge is missing behind the report"
    )


async def test_der_anstoss_wird_nicht_als_nachricht_des_nutzers_abgelegt(dienst):
    """It rides behind the report and is never a row of its own: a message
    the user never wrote must never be stored as theirs, nor shown to them as
    theirs."""
    _modell(dienst)
    chat = _chat(dienst)
    gestartet = _mitschreiben(dienst)

    laeufe.abschluss(_lauf(chat.id), "alle Tests gruen")
    await _ruhe()
    await _antwort_abwarten(gestartet)

    zeilen = dienst.state.repositories.messages.auflisten(chat_id=chat.id)
    for zeile in zeilen:
        assert hintergrundwecken.ANSTOSS not in (zeile.content or ""), (
            "the nudge stands in the chat as a message"
        )
    # And no user turn appeared at all — nobody typed.
    assert not [z for z in zeilen if z.role == "user"], (
        "a user message appeared out of nowhere"
    )


async def test_eine_gewoehnliche_antwort_bekommt_keinen_anstoss(dienst, client):
    """The notice belongs to the wake and to nothing else. On a turn the
    user actually started it would be a lie."""
    from app.api.v1.generierung import antwort_anstossen
    from app.api.v1.schemas import GenerierungAnfrage

    provider = _modell(dienst)
    chat = _chat(dienst)

    lauf = await antwort_anstossen(
        app=dienst,
        daten=GenerierungAnfrage(chat_id=chat.id, content="Hallo"),
        repositories=dienst.state.repositories,
        discovery=dienst.state.discovery,
        generierungen=dienst.state.generierungen,
        user_id="standard",
        sprache="de",
    )
    await lauf.fertig.wait()

    system = [n for n in provider.alle_anfragen[-1].nachrichten if n.role == "system"]
    assert system
    assert hintergrundwecken.ANSTOSS not in system[0].content


async def _language_of_a_wake(app, monkeypatch, choice: str) -> str:
    """What the answer a finished background run wakes is started with,
    under a stored interface choice and `de` in the configuration."""
    from app import sprachwahl
    from app.api.v1 import generierung as generierungsmodul

    app.state.config.app.language = "de"
    app.state.repositories.einstellungen.setzen(
        "global", sprachwahl.SCHLUESSEL, {"sprache": choice}
    )
    _modell(app)
    chat = _chat(app)
    started = _mitschreiben(app)
    real = generierungsmodul.antwort_anstossen
    languages: list[str] = []

    async def capture(**fields):
        languages.append(fields["sprache"])
        return await real(**fields)

    monkeypatch.setattr(generierungsmodul, "antwort_anstossen", capture)
    laeufe.abschluss(_lauf(chat.id), "BUILD SUCCESSFUL")
    await _ruhe()
    await _antwort_abwarten(started)
    assert len(languages) == 1, "no answer was woken"
    return languages[0]


async def test_the_wake_speaks_the_language_chosen_for_the_interface(dienst, monkeypatch):
    """The interface is set to English, the configuration says German: the
    woken answer's texts come in English, like a scheduled run's."""
    assert await _language_of_a_wake(dienst, monkeypatch, "en") == "en"


async def test_the_wake_on_auto_keeps_the_configured_language(dienst, monkeypatch):
    """Silence probe: on `auto` the configured language stands as before."""
    assert await _language_of_a_wake(dienst, monkeypatch, "auto") == "de"
