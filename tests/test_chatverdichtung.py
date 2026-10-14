"""The chat folds its own middle away when it has grown past the threshold.

A job compacts by rewriting the message list it is holding; that list lives
for the whole task. A chat rebuilds its list from the database on every
request, so the fold has to be WRITTEN DOWN or the next thing the user types
undoes it. That is the whole reason this is a separate piece from
`app/verdichtung.py`, and it is why every test here checks the database and
not a list in memory.
"""

from __future__ import annotations

import asyncio

import pytest

from app import (
    antwortgrenze,
    chatverdichtung,
    dokumentbudget,
    faltbitte,
    faltpause,
    fenstergroesse,
    fold_row_weights,
    kontextvoll,
    verdichtung,
    verdichtungswahl,
)
from app import verlaufsbau
from app.providers import MockProvider, mock_endpunkt
# The request builder's own reading of a row. Compaction is handed it now
# instead of reading `messages.content`, so every test here has to hand it
# over too — which is the point: `content` is not what a row says to a
# model, and the tests would go on believing it if the default were kind.
from app.api.v1 import generierung


class _Zustand:
    """An endpoint with a known context size and a provider that answers.
    By default its model cannot be asked about thinking; a test about the
    switch hands its own endpoint.

    The window has to be bigger than the summarizing request's OWN prompt:
    a window smaller than the middle it is asked to summarize leaves no room
    to write the summary in, and the fold folds nothing without asking
    anybody (app/chatverdichtung.py). No real server is
    ever in that state — it is the measuring instrument set wrong, not the
    code. And it has to stay small enough that the verbatim tail
    (``verdichtung.schwanz_budget``, capped at ``LETZTE_ZEICHEN``) does not
    swallow the whole history, or there is no middle left to fold at all.
    The readings the tests hand in are moved with it: what each of them
    checks is a RATIO against this number, never the number itself.
    """

    def __init__(self, provider, context_tokens=100_000, endpunkt=None):
        from app.providers import mock_endpunkt

        self.provider = provider
        self.context_tokens = context_tokens
        self.endpunkt = endpunkt or mock_endpunkt("test")
        self.gemeldeter_name = None
        self.faehigkeiten_erkannt = None
        # Nobody names an output limit for a mock endpoint; the window alone
        # decides what the summarizing request may write.
        self.hersteller_max_tokens = None
        # The models a server with a catalogue offers; a mock endpoint has
        # none, so its refusals are kept under the endpoint alone
        # (app/discovery.py `refusal_key`).
        self.auswaehlbare_modelle = []

    def kann(self, name: str) -> bool:
        """The capability the fold asks about: a model that sees."""
        return name == "vision"


class _Zusammenfasser:
    def __init__(self, text="gerafft"):
        self.text = text
        self.anfragen = []

    async def streamen(self, anfrage):
        from app.providers.base import Stueck

        self.anfragen.append(anfrage)
        yield Stueck("content", text=self.text)


class _Stumm:
    async def streamen(self, anfrage):
        raise AssertionError("must not be asked")
        yield  # pragma: no cover


def _chat(client):
    return client.app.state.repositories.chats.erstellen(
        user_id="standard", title="Lang", endpoint_id="test"
    )


def _schwer(repositories, chat_id, paare: int):
    """A history heavy enough to run past the verbatim tail budget."""
    je = verdichtung.LETZTE_ZEICHEN // 10
    for nr in range(paare):
        repositories.messages.speichern(
            chat_id=chat_id, role="user", content=f"frage {nr} " + "x" * je
        )
        repositories.messages.speichern(
            chat_id=chat_id, role="assistant", content=f"antwort {nr} " + "x" * je,
            zustand="fertig",
        )


def _mit_dokumenten(repositories, chat_id, zuege: int, je: int = 24_000, name="bericht"):
    """Short turns, each carrying a big document — the shape compaction was
    blind to.

    Every row is a handful of characters in `messages.content`; the document
    that dwarfs it is prepended when the request is built, and lives in
    another table entirely.
    """
    for nr in range(zuege):
        dokument = repositories.documents.speichern(
            chat_id=chat_id, filename=f"{name}-{nr}.pdf", extracted_text="D" * je
        )
        repositories.messages.speichern(
            chat_id=chat_id, role="user", content=f"Frage {nr}",
            dokumente=[dokument.id],
        )
        repositories.messages.speichern(
            chat_id=chat_id, role="assistant", content=f"Antwort {nr}",
            zustand="fertig",
        )


def test_der_nachweis_mit_zwei_dokumenten_ist_ein_lesbarer_satz():
    """One sentence per document, joined by a space. Joined by a comma the
    note ran into the next name: "…a stretch of lines., "b.pdf" (200
    characters) The file itself is at…"."""
    from dataclasses import dataclass

    @dataclass
    class _Dok:
        filename: str
        extracted_text: str
        pfad: str | None
        pages: int | None = None

    satz = chatverdichtung._dokumentnachweis(
        [
            _Dok("a.txt", "A" * 100, "/ablage/a.txt"),
            _Dok("b.pdf", "B" * 200, "/ablage/b.pdf", 3),
        ]
    )

    assert ".," not in satz
    assert ") The file" not in satz
    assert '"a.txt" (100 characters).' in satz
    assert '"b.pdf" (200 characters).' in satz
    assert "/ablage/a.txt" in satz
    assert "/ablage/b.pdf" in satz
    assert "lines. \"b.pdf\"" in satz
    assert satz.endswith("had their wording.]")


def test_der_nachweis_ohne_datei_bleibt_ein_satz():
    """A document uploaded before files were kept has no place to read it
    back from: the name and the size stand on their own, still as a
    sentence."""
    from dataclasses import dataclass

    @dataclass
    class _Dok:
        filename: str
        extracted_text: str
        pfad: str | None = None
        pages: int | None = None

    satz = chatverdichtung._dokumentnachweis([_Dok("a.txt", "A" * 100)])

    assert '"a.txt" (100 characters). Their contents accompanied' in satz


async def test_eine_eingestellte_grenze_laesst_den_chat_frueher_falten(client):
    """A ceiling the user set is reserved out of the same window: a reading
    that stays under the threshold of the whole window is over the threshold
    of what is left beside the ceiling."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    # The window of the test state is 100,000; the shipped threshold is a
    # share of it. This reading is under that share and over the share of
    # the 50,000 left beside the ceiling.
    stand = 60_000
    grenze = 50_000

    ohne = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(_Zusammenfasser()),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=stand,
    )
    assert ohne is None

    mit = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(_Zusammenfasser()),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=stand,
        eingestellte_grenze=grenze,
    )

    assert mit is not None


def _gewichte(repositories, zeilen, dokumentplan=None):
    """What each row weighs in the prompt — the reading compaction uses."""
    return fold_row_weights.fold_row_weights(
        zeilen, repositories, document_plan=dokumentplan
    )


def _gebaut(chat, repositories, dokumentplan=None) -> list:
    """The history exactly as it goes to the model, system prompt aside."""
    return generierung._verlauf_bauen(
        chat, repositories, "", config=None, dokumentplan=dokumentplan
    )


def _ganzer_plan(repositories, chat_id):
    """Every document this chat carries travels whole — the plan a window
    comfortably larger than all of them together would produce
    (app/dokumentbudget.py). What these tests weigh and cache is the point,
    not whether a document fits; a plan that includes everything keeps that
    question out of their way."""
    return {
        d.id: dokumentbudget.Anteil(ganz=True)
        for d in repositories.documents.auflisten(chat_id=chat_id)
    }


async def test_ein_unbekanntes_cloud_modell_faltet_mit_dem_ersatzwert(client):
    """An endpoint whose window nobody could read gets the fallback
    (app/fenstergroesse.py, 128,000) from real discovery — not a stand-in
    zustand — and folds on it exactly like a model with a confirmed window,
    where it used to never fold at all."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    zustand = client.app.state.discovery.zustaende["test"]
    assert zustand.context_tokens == fenstergroesse.ERSATZ
    assert zustand.kontext_quelle == fenstergroesse.QUELLE_ERSATZ
    repositories.einstellungen.setzen("global", "verdichtung_schwelle", 1)
    _schwer(repositories, chat.id, 12)

    kennung = await chatverdichtung.vielleicht_verdichten(
        zustand=zustand,
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        # 2 000 of 128 000 is 1.6 % — over the 1 % threshold set above.
        vorheriger_stand=2_000,
    )

    assert kennung is not None
    assert any(z.verdichtet_in == kennung for z in repositories.messages.auflisten(chat_id=chat.id))


async def test_unter_der_schwelle_passiert_nichts(client):
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    vorher = len(repositories.messages.auflisten(chat_id=chat.id))

    ergebnis = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(_Stumm()),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        # 10,000 of 100,000 is 10%, far under the shipped 80.
        vorheriger_stand=10_000,
    )

    assert ergebnis is None
    assert len(repositories.messages.auflisten(chat_id=chat.id)) == vorher


async def test_ueber_der_schwelle_wird_gefaltet_und_nichts_geloescht(client):
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    vorher = repositories.messages.auflisten(chat_id=chat.id)

    kennung = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(_Zusammenfasser()),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )

    assert kennung is not None
    nachher = repositories.messages.auflisten(chat_id=chat.id)
    # Every line still there, plus the summary. Compaction is not deletion.
    assert len(nachher) == len(vorher) + 1
    fuers_modell = repositories.messages.fuer_das_modell(chat_id=chat.id)
    assert len(fuers_modell) < len(nachher)
    assert any(z.id == kennung for z in fuers_modell)


async def test_die_ersten_drei_und_das_ende_bleiben_woertlich(client):
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    vorher = repositories.messages.auflisten(chat_id=chat.id)

    await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(_Zusammenfasser()),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )

    fuers_modell = repositories.messages.fuer_das_modell(chat_id=chat.id)
    assert [z.id for z in fuers_modell[:3]] == [z.id for z in vorher[:3]]
    assert fuers_modell[-1].id == vorher[-1].id


async def test_eine_grosse_neue_nachricht_loest_die_faltung_aus(client):
    """The trigger used to read only `vorheriger_stand`, the reading
    from the LAST answer, and knew nothing about the message just typed.
    Just under the threshold on its own, the message pastes 400,000
    characters straight in — over the threshold once that is counted, and
    today's reading alone would not have folded at all."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    gemeinsam = dict(
        repositories=repositories, chat=chat, endpoint_id="test", modellname="test",
    )
    # 70,000 of 100,000 is 70% — under the shipped 80% by itself.
    ohne_neu = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(_Stumm()), vorheriger_stand=70_000, **gemeinsam
    )
    assert ohne_neu is None, "the old trigger would not have folded here either"

    kennung = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(_Zusammenfasser()),
        vorheriger_stand=70_000,
        # 400,000 characters is 100,000 tokens on top of 70,000 —
        # 170,000 of 100,000 tokens, well past the threshold.
        neu_tokens=100_000,
        **gemeinsam,
    )
    assert kennung is not None


async def test_eine_kleine_neue_nachricht_loest_nichts_aus(client):
    """The silence test: a short chat with a short new message stays
    exactly as it is — a few typed characters must not manufacture a fold
    out of nothing."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    vorher = len(repositories.messages.auflisten(chat_id=chat.id))

    ergebnis = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(_Stumm()),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=10_000,
        neu_tokens=5,
    )

    assert ergebnis is None
    assert len(repositories.messages.auflisten(chat_id=chat.id)) == vorher


async def test_ohne_bekannte_kontextgroesse_wird_nicht_gefaltet(client):
    """A threshold measured against a size nobody confirmed would fold a
    conversation for no reason — the rule the whole context display follows."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)

    ergebnis = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(_Stumm(), context_tokens=None),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )
    assert ergebnis is None


async def test_ohne_messwert_wird_nicht_gefaltet(client):
    """No prior reading and nothing new either (``neu_tokens`` defaults to
    0): ``kontextdruck.prozent`` reads 0%, which cannot clear any threshold —
    even on a chat heavy enough to have a real middle to fold."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)

    ergebnis = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(_Stumm()),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=None,
    )
    assert ergebnis is None


async def test_ein_kurzer_chat_hat_keine_mitte(client):
    """Past the threshold, but everything fits in the pinned opening and
    the verbatim tail — there is nothing in between to summarize."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 1)

    ergebnis = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(_Stumm()),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )
    assert ergebnis is None


def _zeilen(repositories, chat_id) -> list[tuple]:
    """Every row of the chat as the fold could change it: its id, its text,
    its kind, and what summary it is folded into."""
    return [
        (z.id, z.content, z.art, z.verdichtet_in)
        for z in repositories.messages.auflisten(chat_id=chat_id)
    ]


def _buchungen(chat_id) -> int:
    """How many failed folds in a row the fold pause holds for this chat."""
    stand = faltpause._staende.get(chat_id)
    return stand.notfaelle if stand else 0


async def test_eine_leere_antwort_faltet_nicht(client):
    """A summary the model failed to write folds nothing: no seam, not one
    row changed, one request, one failure booked with the short pause."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    vorher = _zeilen(repositories, chat.id)
    fasser = _Zusammenfasser(text="   ")

    ergebnis = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(fasser),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )

    assert ergebnis is None
    assert _zeilen(repositories, chat.id) == vorher
    assert len(fasser.anfragen) == 1
    assert _buchungen(chat.id) == 1
    assert faltpause.pausiert(chat.id)
    faltpause.freigeben(chat.id)


class _Denker:
    """Answers the fold's request only with thinking and a natural ending —
    the summary that was never written out."""

    def __init__(self):
        self.anfragen = []

    async def streamen(self, anfrage):
        from app.providers.base import Stueck

        self.anfragen.append(anfrage)
        yield Stueck("reasoning", text="Gedachte Mitte")
        yield Stueck("stats", daten={"ende_grund": "stop"})


async def test_eine_gedachte_zusammenfassung_faltet_den_chat(client):
    """A summary the model thought instead of writing is a summary: the
    middle is folded, the seam carries the thought, nothing is booked as a
    failure — the same swap chat and job make
    (app/reasoning.denktext_als_antwort)."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    fasser = _Denker()

    kennung = await _falten(client, chat, fasser)

    assert kennung is not None
    assert len(fasser.anfragen) == 1
    zusammenfassung = repositories.messages.holen(kennung)
    assert "Gedachte Mitte" in zusammenfassung.content
    assert zusammenfassung.stats.get("notfall") is None
    assert _buchungen(chat.id) == 0
    assert faltpause.pausiert(chat.id) is False


async def test_eine_zusammenfassung_ohne_ersparnis_wird_nicht_angewendet(client):
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    vorher = len(repositories.messages.auflisten(chat_id=chat.id))

    ergebnis = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(_Zusammenfasser(text="x" * verdichtung.LETZTE_ZEICHEN * 4)),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )

    assert ergebnis is None
    assert len(repositories.messages.auflisten(chat_id=chat.id)) == vorher


async def test_die_eingestellte_schwelle_gilt(client):
    """The whole point of the setting: a chat that says 5% folds where the
    shipped 80 would not have."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    repositories.einstellungen.setzen(
        bereich=f"chat:{chat.id}", schluessel=verdichtungswahl.SCHLUESSEL, wert=5
    )

    kennung = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(_Zusammenfasser()),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        # 100 of 1000 is 10% — under the shipped 80, over this chat's 5.
        vorheriger_stand=10_000,
    )
    assert kennung is not None


async def test_ein_kleines_modell_kann_verdichten(client):
    """A 16k-context model at the shipped threshold: the history that gets it
    there is some 50,000 characters, under the fixed 80,000-character tail —
    so before the budget followed the model, the middle was empty on every
    turn and the chat could never fold. Now it can."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    # Twelve pairs of ~2,100 characters: ~50,000 in all, well under the
    # ceiling and well over half of what 16k tokens at 80% weigh.
    je = 2_100
    for nr in range(12):
        repositories.messages.speichern(
            chat_id=chat.id, role="user", content=f"frage {nr} " + "x" * je
        )
        repositories.messages.speichern(
            chat_id=chat.id, role="assistant", content=f"antwort {nr} " + "x" * je,
            zustand="fertig",
        )
    zeilen = repositories.messages.fuer_das_modell(chat_id=chat.id)
    assert sum(len(z.content) for z in zeilen) < verdichtung.LETZTE_ZEICHEN
    assert chatverdichtung._mitte_suchen(zeilen, [len(z.content) for z in zeilen]) == []

    kennung = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(_Zusammenfasser(), context_tokens=16_000),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        # 13,000 of 16,000 is 81% — over the shipped 80.
        vorheriger_stand=13_000,
    )
    assert kennung is not None
    assert any(z.verdichtet_in == kennung for z in repositories.messages.auflisten(chat_id=chat.id))


async def test_ein_dokument_wird_je_antwort_nur_einmal_gelesen(client):
    """Weighing the rows, building the compaction request and building the
    prompt each turned the same rows into words, and each reading fetched
    every document's full text from the database again — at least twice
    per turn for every document, every turn, once the chat sat above the
    threshold. Inside one answer a document is read once."""
    from app import dokumentcache

    repositories = client.app.state.repositories
    chat = _chat(client)
    _mit_dokumenten(repositories, chat.id, 12)
    dokumente = len(repositories.documents.auflisten(chat_id=chat.id))
    assert dokumente == 12
    plan = _ganzer_plan(repositories, chat.id)

    gelesen = []
    echt = repositories.documents.holen
    repositories.documents.holen = lambda kennung: (gelesen.append(kennung), echt(kennung))[1]

    with dokumentcache.aktiv():
        kennung = await chatverdichtung.vielleicht_verdichten(
            zustand=_Zustand(_Zusammenfasser()),
            repositories=repositories,
            chat=chat,
            endpoint_id="test",
            modellname="test",
            vorheriger_stand=90_000,
            dokumentplan=plan,
        )
        assert kennung is not None
        _gebaut(chat, repositories, dokumentplan=plan)

    assert len(gelesen) == dokumente, f"{len(gelesen)} reads for {dokumente} documents"

    # Outside a cache, reads go straight through — a document edited between
    # two answers is read fresh by the second.
    gelesen.clear()
    _gebaut(chat, repositories, dokumentplan=plan)
    assert len(gelesen) > 0


def test_die_bremse_geht_mit_dem_chat(client):
    """A chat deleted while braked kept its entry for the life of the
    process — nothing here listened to the deletion. The wake brake hangs on
    the run registry's forget hook for exactly this; this does now too."""
    from app.tools.hintergrund import laeufe

    chatverdichtung._ohne_ersparnis["weg"] = ("test", 3, 300)
    chatverdichtung._ohne_ersparnis["bleibt"] = ("test", 3, 300)
    laeufe.vergessen("weg")
    assert "weg" not in chatverdichtung._ohne_ersparnis
    assert "bleibt" in chatverdichtung._ohne_ersparnis
    chatverdichtung._ohne_ersparnis.pop("bleibt", None)


async def test_eine_faltung_sagt_vorher_bescheid(client):
    """Before the summarizing request goes out, the bus hears that this chat
    is being compacted — once per fold, and never when there is nothing to
    fold: the placeholder in the window wears the word for exactly as long
    as the second model call takes."""
    from app.events import Ereignisse, bus

    gehoert = []

    async def hoeren(**daten):
        gehoert.append(daten.get("chat_id"))

    bus.abonnieren(Ereignisse.VERDICHTUNG_LAEUFT, hoeren)
    try:
        repositories = client.app.state.repositories
        chat = _chat(client)
        _schwer(repositories, chat.id, 12)
        gemeinsam = dict(
            repositories=repositories, chat=chat, endpoint_id="test",
            modellname="test",
        )
        # Under the threshold: nothing is said.
        assert await chatverdichtung.vielleicht_verdichten(
            zustand=_Zustand(_Stumm()), vorheriger_stand=10_000, **gemeinsam
        ) is None
        assert gehoert == []
        # Over it: said once, before the request.
        kennung = await chatverdichtung.vielleicht_verdichten(
            zustand=_Zustand(_Zusammenfasser()), vorheriger_stand=90_000, **gemeinsam
        )
        assert kennung is not None
        assert gehoert == [chat.id]
    finally:
        bus.abbestellen(Ereignisse.VERDICHTUNG_LAEUFT, hoeren)


async def test_die_anfrage_traegt_nur_die_mitte(client):
    """The summarizing request is built for itself: the pinned opening and
    the verbatim tail are not in it, and the live conversation is untouched
    until there is an answer to record."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    fasser = _Zusammenfasser()

    await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(fasser),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )

    assert len(fasser.anfragen) == 1
    # The model has to be NAMED. A request built from scratch carries none,
    # and an OpenAI-compatible server answers that with a 422 — which this
    # function catches and turns into "did nothing", so the chat would
    # simply never fold and nothing would say why. Found in a live run
    # against a real server; no mock notices, because a mock does not care
    # what it is called.
    assert fasser.anfragen[0].modell == "test"
    # No ceiling of its own on the OpenAI wire: the server decides how long
    # a summary may be, the same as for an answer (app/antwortgrenze.py).
    assert fasser.anfragen[0].max_tokens is None
    gefragt = fasser.anfragen[0].nachrichten
    assert gefragt[-1].content == verdichtung.ANFRAGE_TEXT
    alle = repositories.messages.auflisten(chat_id=chat.id)
    assert len(gefragt) - 1 < len(alle)


async def test_die_faltung_schaltet_das_denken_aus(client):
    """A summary is a mechanical request whose reasoning nobody reads: where
    the model can be switched, the fold asks with thinking off, in the
    server's own words."""
    from app.config import Capabilities, EndpointConfig

    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    fasser = _Zusammenfasser()
    mlx = EndpointConfig(
        id="o",
        base_url="http://127.0.0.1:8000/v1",
        parameter_dialect="mlx",
        capabilities=Capabilities(thinking=True),
    )

    await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(fasser, endpunkt=mlx),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )

    assert len(fasser.anfragen) == 1
    assert fasser.anfragen[0].zusatz == {"chat_template_kwargs": {"enable_thinking": False}}


async def test_die_faltung_des_chats_schickt_nur_den_schalter(client):
    """The chat's fold is built from scratch and carries none of the
    answer's parameters: on a llama.cpp model that can be switched, the body
    that goes out holds the switch and no thinking length beside it."""
    from app.config import Capabilities, EndpointConfig
    from app.providers.openai_kompatibel import OpenAIKompatiblerProvider

    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    fasser = _Zusammenfasser()
    llama = EndpointConfig(
        id="l",
        base_url="http://127.0.0.1:9/v1",
        parameter_dialect="llama_cpp",
        capabilities=Capabilities(thinking=True),
    )

    await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(fasser, endpunkt=llama),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )

    assert len(fasser.anfragen) == 1
    koerper = OpenAIKompatiblerProvider(llama)._koerper_bauen(fasser.anfragen[0])
    assert koerper["reasoning_effort"] == "none"
    assert "reasoning_budget_tokens" not in koerper


class _Abschneider:
    """Answers, then says the ceiling cut the answer short."""

    def __init__(self):
        self.anfragen = []

    async def streamen(self, anfrage):
        from app.providers.base import Stueck

        self.anfragen.append(anfrage)
        yield Stueck("content", text="## Done\n- half of")
        yield Stueck("stats", daten={"abgeschnitten": True, "ende_grund": "length"})


async def test_eine_abgeschnittene_zusammenfassung_faltet_nicht(client):
    """Cut at the ceiling, the summary is no summary — so nothing is folded.
    The saving brake is NOT set by that: it keeps a middle that was answered
    and did not shrink from being asked again, and this one was not
    answered. What keeps the next turn from asking again is the pause."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    vorher = _zeilen(repositories, chat.id)
    fasser = _Abschneider()
    kennung = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(fasser),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )
    assert kennung is None
    assert chat.id not in chatverdichtung._ohne_ersparnis
    assert _zeilen(repositories, chat.id) == vorher
    assert _buchungen(chat.id) == 1
    # And no second request while the pause runs.
    await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(fasser),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )
    assert len(fasser.anfragen) == 1
    faltpause.freigeben(chat.id)


async def test_die_anfrage_erbt_die_antwortlaenge_des_nutzers_nicht(client):
    """The answer's ceiling is the user's choice for ANSWERS, and the
    settings let it go down to a few hundred tokens. A summary cut off by
    such a ceiling would be stored whole and fold away rows it never got to
    speak for — so the fold never carries it. On the OpenAI wire it carries
    no number at all."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    fasser = _Zusammenfasser()

    # A chat whose answer length is set as low as the settings allow.
    antwort = client.put(
        "/api/v1/settings/global/parameter", json={"wert": {"max_tokens": 500}}
    )
    assert antwort.status_code == 200

    await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(fasser),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )

    assert len(fasser.anfragen) == 1
    gesendet = fasser.anfragen[0]
    # Neither the user's number nor the fixed floor the fold used to carry —
    # on the OpenAI wire no number at all.
    assert gesendet.max_tokens is None


async def test_die_faltung_auf_dem_anthropic_draht_rechnet_wie_eine_antwort(client):
    """On the wire that needs a number the fold works its own out against
    its own input, instead of inheriting the answer's."""
    from app import antwortgrenze, kontextvoll
    from app.providers import mock_endpunkt

    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    fasser = _Zusammenfasser()

    antwort = client.put(
        "/api/v1/settings/global/parameter", json={"wert": {"max_tokens": 500}}
    )
    assert antwort.status_code == 200

    await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(fasser, endpunkt=mock_endpunkt("test", provider="anthropic")),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )

    assert len(fasser.anfragen) == 1
    gesendet = fasser.anfragen[0]
    assert gesendet.max_tokens != 500
    assert gesendet.max_tokens != 4096
    eingabe = antwortgrenze.eingabe_schaetzen(gesendet.nachrichten)
    assert gesendet.max_tokens == max(
        antwortgrenze.MINDESTWERT, 100_000 - eingabe - kontextvoll.SICHERHEITSABSTAND
    )


async def test_die_faltung_rechnet_nicht_mit_einer_fremden_ablehnung(client):
    """A number a refusal named belongs to the request it happened to.
    The fold is its own request and must not inherit a
    ceiling left over from whatever the chat turn asked before it — the
    silent case (no prior refusal) is already measured by the test of the
    fold on the Anthropic wire above, which this test's refused request
    beside it is the only difference from. The fold does not take the
    number away from that request either."""
    from app import antwortgrenze, kontextvoll
    from app.providers import mock_endpunkt

    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    fasser = _Zusammenfasser()

    zustand = _Zustand(fasser, endpunkt=mock_endpunkt("test", provider="anthropic"))
    abgelehnt = antwortgrenze.Zug(max_tokens=50)

    await chatverdichtung.vielleicht_verdichten(
        zustand=zustand,
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )

    assert len(fasser.anfragen) == 1
    gesendet = fasser.anfragen[0]
    eingabe = antwortgrenze.eingabe_schaetzen(gesendet.nachrichten)
    assert gesendet.max_tokens == max(
        antwortgrenze.MINDESTWERT, 100_000 - eingabe - kontextvoll.SICHERHEITSABSTAND
    )
    assert antwortgrenze.geltender_deckel(zustand, None, abgelehnt) == 50


async def test_eine_mitte_aus_lauter_zusammenfassung_wird_nicht_gefragt(client):
    """The summary eats itself while the real hog is untouchable.

    The tail keeps the newest row however big it is, so one 200 KB message
    pins itself and the boundary lands directly behind the last summary:
    the middle is that summary and nothing else. Every turn would summarize
    the summary again — thinner and vaguer each time, and passing the saving
    check each time BECAUSE it got thinner — while the message that is
    actually filling the context can never be reached. Reproduced exactly
    this way before the floor existed.
    """
    repositories = client.app.state.repositories
    chat = _chat(client)
    for nr in range(3):
        repositories.messages.speichern(
            chat_id=chat.id,
            role="user" if nr % 2 == 0 else "assistant",
            content=f"eroeffnung {nr}",
        )
    gefaltet = [
        repositories.messages.speichern(
            chat_id=chat.id, role="user", content=f"alt {nr} " + "x" * 2000
        )
        for nr in range(4)
    ]
    repositories.messages.verdichten(
        chat_id=chat.id,
        text=f"{verdichtung.VORSPANN}\n\n" + "z" * 3950,
        ersetzte_ids=[z.id for z in gefaltet],
    )
    # The one that really fills the context, and that the tail pins.
    repositories.messages.speichern(
        chat_id=chat.id, role="user", content="r" * 200_000
    )

    fuers_modell = repositories.messages.fuer_das_modell(chat_id=chat.id)
    assert [z.art for z in fuers_modell] == [
        "nachricht", "nachricht", "nachricht", "verdichtung", "nachricht"
    ]
    assert chatverdichtung._mitte_suchen(
        fuers_modell, _gewichte(repositories, fuers_modell)
    ) == []

    fasser = _Zusammenfasser()
    ergebnis = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(fasser),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )

    assert ergebnis is None
    assert fasser.anfragen == [], "the summary was summarized again"
    assert all(
        z.art != "verdichtung" or z.verdichtet_in is None
        for z in repositories.messages.auflisten(chat_id=chat.id)
    )


async def test_eine_verdichtung_ohne_ersparnis_wird_nicht_wiederholt(client):
    """The brake the job path has and this one did not.

    ``verdichtung.Ergebnis.ohne_ersparnis`` exists so a run stops paying for
    folds that gain nothing; the job's caller keeps it in a local for the
    rest of the run. A chat has no run: it is rebuilt from the database on
    every request, so without a memory the identical attempt goes out again
    on the very next turn, and the user waits behind it every time.
    """
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    vorher = len(repositories.messages.auflisten(chat_id=chat.id))
    fasser = _Zusammenfasser(text="x" * verdichtung.LETZTE_ZEICHEN * 4)

    for _ in range(3):
        ergebnis = await chatverdichtung.vielleicht_verdichten(
            zustand=_Zustand(fasser),
            repositories=repositories,
            chat=chat,
            endpoint_id="test",
            modellname="test",
            vorheriger_stand=90_000,
        )
        assert ergebnis is None

    assert len(fasser.anfragen) == 1, (
        "the same middle part was summarized again"
    )
    # And nothing was lost by stopping: the chat is exactly as it was.
    assert len(repositories.messages.auflisten(chat_id=chat.id)) == vorher
    assert all(
        z.verdichtet_in is None
        for z in repositories.messages.auflisten(chat_id=chat.id)
    )


async def test_die_bremse_loest_sich_wenn_die_mitte_eine_andere_ist(client):
    """The other half: a brake that cannot let go is a switch.

    What is remembered is WHICH attempt gained nothing, not that compaction
    is off. The chat keeps growing, rows leave the verbatim tail and join
    the middle, and a middle that is a different middle deserves its own
    try — the summary that was too long for eleven rows may well be shorter
    than thirteen.
    """
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    fasser = _Zusammenfasser(text="x" * verdichtung.LETZTE_ZEICHEN * 4)
    gemeinsam = dict(
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )

    await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(fasser), **gemeinsam
    )
    assert len(fasser.anfragen) == 1
    # The conversation carries on, and the middle grows by what the tail
    # budget pushes out of itself.
    _schwer(repositories, chat.id, 2)

    await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(fasser), **gemeinsam
    )

    assert len(fasser.anfragen) == 2, "the brake holds on to a middle that no longer exists"


async def test_die_budgetgrenze_wird_genau_einmal_gelaufen(client, monkeypatch):
    """The unread block was nine lines that could not do anything.

    It found the last real answer and walked the boundary a SECOND
    time over the rows behind it, folding the result in with a ``min``. Both
    walks add the same texts from the same end against the same budget, so
    the same row busts it and the slice only renames it with a smaller
    index; its own guard ruled out the one shape where that could differ.
    Measured over 45,110 histories before it went: the guard was entered
    10,798 times and not one boundary changed.

    The history below is the shape that DID enter the guard — one early
    answer, then a stack of unread reports. One walk now, the same boundary
    as before, and the unread reports still outside the middle.
    """
    from app.hintergrundmeldung import MAX_ZEICHEN

    class _Zeile:
        def __init__(self, inhalt, rolle="assistant", art="nachricht"):
            self.content = inhalt
            self.id = inhalt[:14]
            self.role = rolle
            self.art = art

    zeilen = [_Zeile("Die letzte echte Antwort")]
    zeilen += [
        _Zeile(f"BERICHT {i:03d} " + "y" * MAX_ZEICHEN, art="werkzeugmeldung")
        for i in range(60)
    ]
    echt = verdichtung.tail_start_from_weights
    grenze = echt([len(z.content) for z in zeilen], verdichtung.LETZTE_ZEICHEN)
    # The guard the removed block sat behind: unread from row 1 on, boundary
    # far behind that. Without this the block would not even have run.
    assert 1 < grenze, "the history does not hit the case at all"

    laeufe = []

    def zaehlend(gewichte, *rest):
        laeufe.append(list(gewichte))
        return echt(gewichte, *rest)

    monkeypatch.setattr(verdichtung, "tail_start_from_weights", zaehlend)
    # These rows carry nothing but text, so their weight IS their content —
    # which is what the caller hands in.
    mitte = chatverdichtung._mitte_suchen(zeilen, [len(z.content) for z in zeilen])

    assert len(laeufe) == 1, "the budget boundary is still walked twice"
    assert laeufe[0] == [len(z.content) for z in zeilen]
    # Behaviour unchanged — the global boundary was always the answer.
    erwartet = zeilen[verdichtung.ERSTE_FEST : grenze]
    assert [z.id for z in mitte] == [z.id for z in erwartet]
    # And what the block promised still holds: the newest reports, the ones
    # a wake is actually about, are outside the middle.
    kennungen = [z.id for z in mitte]
    assert zeilen[-1].id not in kennungen
    assert zeilen[-2].id not in kennungen


async def test_ein_chat_aus_dokumenten_wird_ueberhaupt_verdichtet(client):
    """The chat that needed compaction most was the one chat that
    could never have it.

    Forty short turns, each with a 24,000-character document. The document
    text is not in `messages.content`: the row only points at it, and the
    text is prepended when the request is built. Measured on exactly this
    history: `content` added up to 700 characters against a tail budget of
    80,000, so the boundary came back 0, the middle was empty every single
    turn, and the request that went out was 962,970 characters.
    """
    repositories = client.app.state.repositories
    chat = _chat(client)
    _mit_dokumenten(repositories, chat.id, 40)
    zeilen = repositories.messages.fuer_das_modell(chat_id=chat.id)
    plan = _ganzer_plan(repositories, chat.id)

    # The old measurement, kept as the proof that this history is the case:
    # by `content` alone there is nothing here to compact.
    roh = [z.content or "" for z in zeilen]
    assert sum(len(t) for t in roh) < verdichtung.LETZTE_ZEICHEN
    assert verdichtung.tail_start_from_weights([len(t) for t in roh]) == 0
    assert chatverdichtung._mitte_suchen(zeilen, [len(t) for t in roh]) == []
    # And what actually goes to the model.
    vorher = sum(len(n.content or "") for n in _gebaut(chat, repositories, dokumentplan=plan))
    assert vorher > 900_000

    kennung = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(_Zusammenfasser()),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
        dokumentplan=plan,
    )

    assert kennung is not None
    nachher = sum(len(n.content or "") for n in _gebaut(chat, repositories, dokumentplan=plan))
    assert nachher < vorher / 4, "the fold did not make the prompt smaller"
    # And nothing was lost doing it: every line still readable, summary on top.
    assert len(repositories.messages.auflisten(chat_id=chat.id)) == len(zeilen) + 1


async def test_das_gewicht_einer_zeile_ist_was_die_anfrage_traegt(client):
    """One reading, not two.

    The measurement goes through the request builder itself, so a rule
    added to the builder cannot leave compaction behind — which is how
    documents came to be invisible in the first place.
    """
    repositories = client.app.state.repositories
    chat = _chat(client)
    _mit_dokumenten(repositories, chat.id, 6)
    zeilen = repositories.messages.fuer_das_modell(chat_id=chat.id)
    plan = _ganzer_plan(repositories, chat.id)

    gewichte = _gewichte(repositories, zeilen, dokumentplan=plan)
    gebaut = _gebaut(chat, repositories, dokumentplan=plan)

    assert gewichte == [len(n.content or "") for n in gebaut]
    assert sum(gewichte) > 6 * 24_000


async def test_die_anfrage_nennt_das_dokument_und_traegt_es_nicht(client):
    """Weighed with the documents, asked without them — two questions, one
    builder, two honest answers.

    Weighing a row without its document is what made this chat invisible.
    SENDING the documents into the summarizing request is the other ditch:
    the middle below weighs over 800,000 characters, and a request that
    size goes to a model whose context is already past the compaction
    threshold. It fails, the failure is caught as "did nothing", and the
    chat silently never folds again — the same defect from the other side.
    """
    repositories = client.app.state.repositories
    chat = _chat(client)
    _mit_dokumenten(repositories, chat.id, 40)
    fasser = _Zusammenfasser()

    await chatverdichtung.vielleicht_verdichten(
        # A window of its own: the rows here are short, so the verbatim tail
        # has to stay short too or it swallows the whole history and there is
        # no middle left. Big enough all the same to write the summary of
        # that middle in.
        zustand=_Zustand(fasser, context_tokens=4_000),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=3_600,
    )

    gefragt = fasser.anfragen[0].nachrichten
    assert any('bericht-5.pdf' in (n.content or "") for n in gefragt), (
        "the document is not even named to the summary"
    )
    assert not any("D" * 1_000 in (n.content or "") for n in gefragt), (
        "the document text travels into the compaction request"
    )
    assert sum(len(n.content or "") for n in gefragt) < 50_000
    # And the rule that says what to do with a document it cannot read.
    assert chatverdichtung.DOKUMENTREGEL.strip() in gefragt[-1].content


async def test_keine_leere_nachricht_in_der_verdichtungsanfrage(client):
    """A picture row in the middle went out with nothing in it.

    Image parts are only valid in user messages on OpenAI-style servers,
    and a turn with no content at all ends the request with an error. The
    request builder has had that guard for a long time; the compaction
    request had none, so an `art='bild'` row and an image-only message
    each became a message with an empty string in it.
    """
    repositories = client.app.state.repositories
    chat = _chat(client)
    je = verdichtung.LETZTE_ZEICHEN // 10
    for nr in range(12):
        if nr == 2:
            repositories.messages.speichern(
                chat_id=chat.id, role="user", content="", anhaenge=["foto.png"]
            )
        else:
            repositories.messages.speichern(
                chat_id=chat.id, role="user", content=f"frage {nr} " + "x" * je
            )
        if nr == 3:
            repositories.messages.speichern(
                chat_id=chat.id, role="assistant", content="",
                bild="katze.png", art="bild",
            )
        else:
            repositories.messages.speichern(
                chat_id=chat.id, role="assistant",
                content=f"antwort {nr} " + "x" * je, zustand="fertig",
            )
    fasser = _Zusammenfasser()

    await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(fasser),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )

    gefragt = fasser.anfragen[0].nachrichten
    assert all((n.content or "").strip() for n in gefragt), (
        "an empty message in the compaction request"
    )
    inhalte = [n.content for n in gefragt]
    assert "[An image was attached here.]" in inhalte
    assert "[A generated image was shown here.]" in inhalte


async def test_die_naht_sagt_welche_dokumente_gegangen_sind(client):
    """A summary speaks FOR the rows it folded — and it cannot speak for a
    document, whose text was never in a row and was never shown to it.

    So the fold says out loud what stopped travelling, with names and
    sizes, written by us rather than left to the model. Without it the
    model answers about a contract it can no longer read and nothing on
    either side says so.
    """
    repositories = client.app.state.repositories
    chat = _chat(client)
    _mit_dokumenten(repositories, chat.id, 40)

    kennung = await chatverdichtung.vielleicht_verdichten(
        # A window of its own: the rows here are short, so the verbatim tail
        # has to stay short too or it swallows the whole history and there is
        # no middle left. Big enough all the same to write the summary of
        # that middle in.
        zustand=_Zustand(_Zusammenfasser(), context_tokens=4_000),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=3_600,
    )

    naht = repositories.messages.holen(kennung)
    assert 'bericht-5.pdf' in naht.content
    assert "24000 characters" in naht.content
    # Named, not carried — the seam is a sentence about the document, not
    # the document.
    assert "D" * 1_000 not in naht.content
    assert len(naht.content) < 10_000


async def test_die_ersparnispruefung_sieht_den_dokumenttext(client):
    """The check compared `content` lengths too.

    The middle below is 611 characters of `content` and over 800,000
    characters of prompt. A summary of 100,000 characters is longer than
    the first number and a fraction of the second: measured the old way the
    fold was refused as "no shorter" and the brake wrote it down, while in
    truth it frees three quarters of a megabyte.
    """
    repositories = client.app.state.repositories
    chat = _chat(client)
    _mit_dokumenten(repositories, chat.id, 40)
    zeilen = repositories.messages.fuer_das_modell(chat_id=chat.id)
    plan = _ganzer_plan(repositories, chat.id)
    vorher = sum(len(n.content or "") for n in _gebaut(chat, repositories, dokumentplan=plan))
    fasser = _Zusammenfasser(text="z" * 100_000)

    kennung = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(fasser),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
        dokumentplan=plan,
    )

    assert sum(len(z.content or "") for z in zeilen) < 100_000, (
        "the history does not hit the case at all"
    )
    assert kennung is not None, "a fold that saves 800 KB was refused"
    assert chat.id not in chatverdichtung._ohne_ersparnis
    nachher = sum(len(n.content or "") for n in _gebaut(chat, repositories, dokumentplan=plan))
    assert nachher < vorher - 700_000


# How the sentence a fold writes about displaced documents begins — written
# out here rather than taken from the module, because summaries already
# stored carry exactly these words.
DOCUMENT_SENTENCE = "[Documents attached in the stretch summarized above:"


def _summaries(repositories, chat_id) -> list:
    return [
        z for z in repositories.messages.fuer_das_modell(chat_id=chat_id)
        if z.art == "verdichtung"
    ]


async def _fold(repositories, chat, plan=None, summary="gerafft"):
    return await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(_Zusammenfasser(summary)),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
        dokumentplan=plan,
    )


async def test_a_second_fold_passes_the_first_document_sentence_on(client):
    """The first fold's summary names the documents it displaced. A second
    fold that takes that summary into its middle passes the sentence on
    word for word — and no summary row ever carries ``dokumente``, which
    would bring the folded text back into the request."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    sentence = await _first_sentence(repositories, chat)
    assert "bericht-2.pdf" in sentence
    [first] = _summaries(repositories, chat.id)

    _schwer(repositories, chat.id, 12)
    assert await _fold(repositories, chat, _ganzer_plan(repositories, chat.id)) is not None

    [second] = _summaries(repositories, chat.id)
    assert second.id != first.id
    assert sentence in second.content
    assert second.content.count(sentence) == 1
    assert not any(
        z.dokument_ids() for z in repositories.messages.auflisten(chat_id=chat.id)
        if z.art == "verdichtung"
    )


async def _first_sentence(repositories, chat) -> str:
    _mit_dokumenten(repositories, chat.id, 40)
    assert await _fold(repositories, chat, _ganzer_plan(repositories, chat.id)) is not None
    [first] = _summaries(repositories, chat.id)
    return first.content[first.content.index(DOCUMENT_SENTENCE):]


async def test_a_second_fold_names_old_and_new_documents_in_order(client):
    """A second middle holding the first summary AND rows with documents of
    its own: the earlier sentence comes first, word for word, then the one
    about this fold's documents."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    sentence = await _first_sentence(repositories, chat)
    _mit_dokumenten(repositories, chat.id, 40, name="neu")
    assert await _fold(repositories, chat, _ganzer_plan(repositories, chat.id)) is not None

    [second] = _summaries(repositories, chat.id)
    assert second.content.count(DOCUMENT_SENTENCE) == 2
    carried = second.content.index(sentence)
    new = second.content.index(DOCUMENT_SENTENCE, carried + len(sentence))
    assert "neu-" in second.content[new:]
    assert "neu-" not in sentence


async def test_a_sentence_the_model_already_copied_is_not_added_twice(client):
    repositories = client.app.state.repositories
    chat = _chat(client)
    sentence = await _first_sentence(repositories, chat)
    _schwer(repositories, chat.id, 12)
    assert await _fold(repositories, chat, summary=f"gerafft\n\n{sentence}") is not None

    [second] = _summaries(repositories, chat.id)
    assert second.content.count(sentence) == 1


async def test_an_unfinished_sentence_of_the_model_is_not_passed_on(client):
    """A model that opens the sentence in its own words and never closes it:
    only the sentence the fold wrote travels on, not the model's prose."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _mit_dokumenten(repositories, chat.id, 40)
    prose = f"{DOCUMENT_SENTENCE} some notes of the model's own"
    assert await _fold(
        repositories, chat, _ganzer_plan(repositories, chat.id), summary=prose
    ) is not None
    [first] = _summaries(repositories, chat.id)
    ours = first.content[first.content.rindex(DOCUMENT_SENTENCE):]
    _schwer(repositories, chat.id, 12)
    assert await _fold(repositories, chat) is not None

    [second] = _summaries(repositories, chat.id)
    assert ours in second.content
    assert "some notes of the model's own" not in second.content


async def test_a_fold_without_documents_writes_no_sentence(client):
    """The silence probe: plain rows folded twice carry no document
    sentence at all."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    assert await _fold(repositories, chat) is not None
    _schwer(repositories, chat.id, 12)
    assert await _fold(repositories, chat) is not None

    [summary] = _summaries(repositories, chat.id)
    assert DOCUMENT_SENTENCE not in summary.content


async def test_ein_gefaltetes_dokument_reist_nicht_mehr_mit(client):
    """A document the fold carried away is not IN the next request at all —
    named once, in the summary that replaced it, and never again.

    Compaction runs BEFORE the request is built and without the question,
    so what it weighs is never the cut the real answer would make (a
    document too big for the fold's own view may still fit the real plan,
    whole) — the two ask different questions and must not share an answer.
    A document that stays in the tail keeps following the real plan.
    """
    repositories = client.app.state.repositories
    chat = _chat(client)

    def grosses_dokument(name: str, buchstabe: str) -> str:
        dokument = repositories.documents.speichern(
            chat_id=chat.id, filename=name, extracted_text=buchstabe * 50_000,
        )
        repositories.messages.speichern(
            chat_id=chat.id, role="user", content=f"zu {name}",
            dokumente=[dokument.id],
        )
        return dokument.id

    _schwer(repositories, chat.id, 12)
    grosses_dokument("mitte.pdf", "M")
    _schwer(repositories, chat.id, 12)
    grosses_dokument("schwanz.pdf", "S")
    plan = _ganzer_plan(repositories, chat.id)

    kennung = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(_Zusammenfasser()),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
        dokumentplan=plan,
    )

    assert kennung is not None
    assert "mitte.pdf" in repositories.messages.holen(kennung).content
    assert "schwanz.pdf" not in repositories.messages.holen(kennung).content

    gebaut = _gebaut(chat, repositories, dokumentplan=plan)
    text = "\n".join(n.content or "" for n in gebaut)
    # The document's own body, not the filename: the summary that replaced
    # the fold is allowed — meant — to name what it removed.
    assert "M" * 50_000 not in text, "the folded document's body travels again"
    assert "S" * 50_000 in text


def _knapper_plan(repositories, chat_id):
    """A plan that sends only four of the chat's forty documents whole and
    names the rest — real weight around 96 000 characters where the body of
    all forty together is 960 000, and nowhere near the zero a document
    named outright would suggest."""
    from app.dokumentbudget import Anteil

    plan = {}
    for i, dokument in enumerate(repositories.documents.auflisten(chat_id=chat_id)):
        plan[dokument.id] = Anteil(ganz=i < 4)
    return plan


async def test_ein_verdichtetes_dokument_zaehlt_mit_dem_was_der_plan_sendet(client):
    """A document the plan names does not send its 24k body — judged at
    that, a summary "saved" a factor of ten and the chat folded again on
    every turn. It sends only what the plan really carries
    (app/dokumentbudget.py), and that is what it weighs: a summary longer
    than the rows' text plus that much per document shrinks nothing and is
    refused, and the brake writes the middle down. Forty documents: by the
    body they weigh 960 000 characters, by what this plan really sends
    about 100 000 — a 300 000-character summary is a saving under the first
    reading and none under the second."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _mit_dokumenten(repositories, chat.id, 40)
    plan = _knapper_plan(repositories, chat.id)
    fasser = _Zusammenfasser(text="z" * 300_000)
    # A low threshold keeps the tail as short as a far smaller window would.
    repositories.einstellungen.setzen(
        bereich=f"chat:{chat.id}", schluessel=verdichtungswahl.SCHLUESSEL, wert=40
    )
    kennung = await chatverdichtung.vielleicht_verdichten(
        # A window of its own, with the threshold set above: the verbatim
        # tail grows with both, and every row the tail takes is a row the
        # middle loses. What this test weighs is the middle against the
        # summary offered for it, so the middle has to stay heavier than
        # the 50,000 characters below and lighter than the 300,000 above —
        # while the window still leaves the summarizing request room for the
        # history once the summary's reserve is set aside
        # (``faltbitte.reserve``).
        zustand=_Zustand(fasser, context_tokens=3_200),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=2_880,
        dokumentplan=plan,
    )
    assert kennung is None, "a fold without a real saving was written"
    assert chat.id in chatverdichtung._ohne_ersparnis


async def test_ein_verdichtetes_dokument_zaehlt_nicht_als_nichts(client):
    """The other edge of the same reading. Counted as nothing, a middle of
    short rows and four whole documents weighed only a few thousand
    characters, a summary of fifty thousand "saved nothing", and the chat
    could never fold again — while every turn kept paying for the
    documents the plan actually sends whole. Against what the plan really
    sends (about 100 000 characters), that summary is a saving and the
    fold happens."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _mit_dokumenten(repositories, chat.id, 40)
    plan = _knapper_plan(repositories, chat.id)
    fasser = _Zusammenfasser(text="z" * 50_000)
    # A low threshold keeps the tail as short as a far smaller window would.
    repositories.einstellungen.setzen(
        bereich=f"chat:{chat.id}", schluessel=verdichtungswahl.SCHLUESSEL, wert=40
    )
    kennung = await chatverdichtung.vielleicht_verdichten(
        # A window of its own, with the threshold set above: the verbatim
        # tail grows with both, and every row the tail takes is a row the
        # middle loses. What this test weighs is the middle against the
        # summary offered for it, so the middle has to stay heavier than
        # the 50,000 characters below and lighter than the 300,000 above —
        # while the window still leaves the summarizing request room for the
        # history once the summary's reserve is set aside
        # (``faltbitte.reserve``).
        zustand=_Zustand(fasser, context_tokens=3_200),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=2_880,
        dokumentplan=plan,
    )
    assert kennung is not None, "a fold with a real saving was discarded"
    assert chat.id not in chatverdichtung._ohne_ersparnis


async def test_die_werkzeugrunden_einer_antwort_zaehlen_zur_mitte(client):
    """An answer's tool calls travel back as calls and capped results, on
    top of its text (app/verlaufsbau.py). Weighed by prose alone, a middle
    of many calls looked thousands of characters lighter than it is, and a
    summary that saved plenty was thrown away as "no saving"."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    je = verdichtung.LETZTE_ZEICHEN // 10
    for nr in range(12):
        repositories.messages.speichern(
            chat_id=chat.id, role="user", content=f"frage {nr} " + "x" * (je // 4)
        )
        repositories.messages.speichern(
            chat_id=chat.id, role="assistant", content=f"antwort {nr}", zustand="fertig",
            stats={"werkzeuge": [
                {"name": "read_file", "argumente": {"path": f"{nr}/{i}.py"}, "ergebnis": "y" * 800}
                for i in range(20)
            ]},
        )
    zeilen = repositories.messages.auflisten(chat_id=chat.id)
    # What the calls weigh, by the same reading the fold uses.
    werkzeuge = sum(verlaufsbau.werkzeuggewicht(z) for z in zeilen)
    assert werkzeuge > 100_000
    # Longer than every row's text put together, shorter than text plus
    # calls: a fold that only saves because the calls count.
    text = sum(len(verlaufsbau.zeilentext(z, repositories)) for z in zeilen)
    fasser = _Zusammenfasser(text="z" * (text + 20_000))
    # The rows here are short, so the verbatim tail has to stay short too or
    # it swallows the whole history and there is no middle left — the tail
    # is sized from the threshold, so the threshold is set low. The window
    # has to hold the summarizing request, which carries every call of the
    # middle: a window under it leaves no room to write a summary in, no
    # model is asked, and nothing is folded (app/chatverdichtung.py).
    repositories.einstellungen.setzen("global", "verdichtung_schwelle", 1)
    fenster = 60_000
    kennung = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(fasser, context_tokens=fenster),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=fenster // 2,
    )
    assert len(fasser.anfragen) == 1, "no summary was asked for"
    assert kennung is not None, "the tool rounds of the middle part did not count"


# --- the fold that fails ----------------------------------------------------


class _Ausfall:
    """Refuses every request the way a dead model server does."""

    def __init__(self):
        self.anfragen = []

    async def streamen(self, anfrage):
        self.anfragen.append(anfrage)
        raise RuntimeError("provider is down")
        yield  # pragma: no cover


class _Uhr:
    """A clock the test moves itself, so a pause can be waited out."""

    def __init__(self):
        self.jetzt = 0.0

    def __call__(self) -> float:
        return self.jetzt

    def weiter(self, sekunden: float) -> None:
        self.jetzt += sekunden


@pytest.fixture
def uhr(monkeypatch):
    gestellt = _Uhr()
    monkeypatch.setattr(faltpause, "uhr", gestellt)
    return gestellt


async def _falten(client, chat, provider, stand=90_000):
    return await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(provider),
        repositories=client.app.state.repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=stand,
    )


class _ErstAusfall:
    """Refuses the first request, then answers with a summary."""

    def __init__(self) -> None:
        self.anfragen: list = []

    async def streamen(self, anfrage):
        from app.providers.base import Stueck

        self.anfragen.append(anfrage)
        if len(self.anfragen) == 1:
            raise RuntimeError("provider hiccup")
        yield Stueck("content", text="## Done\n- the real summary")


async def test_eine_ausnahme_faltet_nicht_und_wird_nicht_wiederholt(client, uhr):
    """The model server is gone: one request, no second one inside the same
    turn, not one row changed, the long pause booked once."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    vorher = _zeilen(repositories, chat.id)
    fasser = _ErstAusfall()

    kennung = await _falten(client, chat, fasser)

    assert kennung is None
    assert len(fasser.anfragen) == 1
    assert _zeilen(repositories, chat.id) == vorher
    assert _buchungen(chat.id) == 1
    assert faltpause.pausiert(chat.id, jetzt=faltpause.PAUSE_LANG - 1)
    assert not faltpause.pausiert(chat.id, jetzt=faltpause.PAUSE_LANG)


async def test_ist_das_modell_wieder_da_faltet_der_naechste_zug_wie_vorher(client, uhr):
    """Silence test: the pause is the retry. Once it has run out, the next
    turn asks again, the real summary is written with its seam and without
    an emergency mark, and nothing about the failure is left standing."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    fasser = _ErstAusfall()
    assert await _falten(client, chat, fasser) is None

    uhr.weiter(faltpause.PAUSE_LANG)
    kennung = await _falten(client, chat, fasser)

    assert kennung is not None
    assert len(fasser.anfragen) == 2
    zusammenfassung = repositories.messages.holen(kennung)
    assert zusammenfassung.content.startswith(verdichtung.VORSPANN)
    assert "the real summary" in zusammenfassung.content
    assert zusammenfassung.stats.get("notfall") is None
    assert any(
        z.verdichtet_in == kennung
        for z in repositories.messages.auflisten(chat_id=chat.id)
    )
    assert faltpause.pausiert(chat.id) is False
    assert _buchungen(chat.id) == 0


async def test_waehrend_der_pause_geht_keine_anfrage_raus_danach_wieder(client, uhr):
    """Inside the pause the automatic path does nothing at all — not one
    request leaves the house. Once it lapses, it asks again."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    ausfall = _Ausfall()

    await _falten(client, chat, ausfall)
    assert len(ausfall.anfragen) == 1

    _schwer(repositories, chat.id, 12)
    await _falten(client, chat, ausfall)
    assert len(ausfall.anfragen) == 1, "a request went out inside the pause"

    uhr.weiter(faltpause.PAUSE_LANG)
    await _falten(client, chat, ausfall)
    assert len(ausfall.anfragen) == 2


async def test_der_erzwungene_weg_fragt_in_der_pause_nicht_und_bucht_nichts(client, uhr):
    """Forced means "no answer comes out otherwise", not "the user asked for
    it" — and the model has just failed to summarize. So no request, nothing
    folded, and nothing booked: nothing was learned about the model."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    ausfall = _Ausfall()
    await _falten(client, chat, ausfall)
    assert faltpause.pausiert(chat.id)

    _schwer(repositories, chat.id, 12)
    vorher = _zeilen(repositories, chat.id)
    zeilen = repositories.messages.fuer_das_modell(chat_id=chat.id)
    kennung, ergebnis = await chatverdichtung.erzwungen_verdichten(
        zustand=_Zustand(ausfall),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        zeilen=zeilen,
        budget=verdichtung.LETZTE_ZEICHEN,
    )

    assert kennung is None
    # Nothing failed here, and a smaller step would sit in the same pause:
    # the same answer the job's fold gives (test_verdichtung.py).
    assert ergebnis == verdichtung.Ergebnis(angewendet=False)
    assert len(ausfall.anfragen) == 1, "a fold request went out inside the pause"
    assert _zeilen(repositories, chat.id) == vorher
    assert _buchungen(chat.id) == 1


async def test_ohne_platz_fuer_eine_zusammenfassung_wird_nicht_gebucht(client, uhr):
    """A window the summarizing request does not fit into: no request goes
    out, nothing is folded, and nothing is booked."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    vorher = _zeilen(repositories, chat.id)

    kennung, ergebnis = await chatverdichtung.erzwungen_verdichten(
        zustand=_Zustand(_Stumm(), context_tokens=1_000),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        zeilen=repositories.messages.fuer_das_modell(chat_id=chat.id),
        budget=verdichtung.LETZTE_ZEICHEN,
    )

    assert kennung is None
    assert ergebnis == verdichtung.Ergebnis(angewendet=False)
    assert _zeilen(repositories, chat.id) == vorher
    assert _buchungen(chat.id) == 0
    assert faltpause.pausiert(chat.id) is False


async def test_ein_kleines_fenster_fragt_das_modell_mit_gesenktem_deckel(client, uhr):
    """A window far smaller than the history: the request's ceiling comes
    down to the window, the model IS asked and the middle folds, and the
    summary keeps its reserve free — where the fixed ceiling left no room
    and asked nobody. On the Anthropic wire, where a number still travels."""
    from app.providers import mock_endpunkt

    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 40)
    fenster = 32_768
    fasser = _Zusammenfasser()

    kennung, ergebnis = await chatverdichtung.erzwungen_verdichten(
        zustand=_Zustand(
            fasser,
            context_tokens=fenster,
            endpunkt=mock_endpunkt("test", provider="anthropic"),
        ),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        zeilen=repositories.messages.fuer_das_modell(chat_id=chat.id),
        budget=verdichtung.LETZTE_ZEICHEN,
    )

    assert kennung is not None
    assert ergebnis.angewendet is True
    assert ergebnis.ersetzt > 0
    assert len(fasser.anfragen) == 1
    gefragt = fasser.anfragen[0]
    assert len(gefragt.nachrichten[0].content) < faltbitte.BITTE_MAX
    reserve = faltbitte.reserve(fenster)
    eingabe = antwortgrenze.eingabe_schaetzen(gefragt.nachrichten)
    assert eingabe <= fenster - reserve - kontextvoll.SICHERHEITSABSTAND
    assert gefragt.max_tokens >= reserve


async def test_passt_kein_zeichen_verlauf_fragt_nicht_auch_wenn_platz_waere(
    client, uhr, monkeypatch
):
    """A window that leaves the history not one character: no request, nothing
    folded, nothing booked — decided by the ceiling itself, not by the "no
    room" arithmetic, which is told here that there is room."""
    monkeypatch.setattr(antwortgrenze, "reicht_nicht", lambda *_, **__: False)
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    vorher = _zeilen(repositories, chat.id)

    kennung, ergebnis = await chatverdichtung.erzwungen_verdichten(
        zustand=_Zustand(_Stumm(), context_tokens=2_048),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        zeilen=repositories.messages.fuer_das_modell(chat_id=chat.id),
        budget=verdichtung.LETZTE_ZEICHEN,
    )

    assert kennung is None
    assert ergebnis == verdichtung.Ergebnis(angewendet=False)
    assert _zeilen(repositories, chat.id) == vorher
    assert _buchungen(chat.id) == 0
    assert faltpause.pausiert(chat.id) is False


async def test_zwei_notfaelle_schalten_die_automatik_ab(client, uhr):
    """Two in a row, and the answer they happen in carries the notice once."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    ausfall = _Ausfall()

    await _falten(client, chat, ausfall)
    assert faltpause.hinweis_faellig(chat.id) is False

    uhr.weiter(faltpause.PAUSE_LANG)
    _schwer(repositories, chat.id, 12)
    await _falten(client, chat, ausfall)
    assert faltpause.hinweis_faellig(chat.id) is True
    assert faltpause.hinweis_faellig(chat.id) is False

    uhr.weiter(faltpause.PAUSE_LANG)
    _schwer(repositories, chat.id, 12)
    await _falten(client, chat, ausfall)
    assert len(ausfall.anfragen) == 2, "automatic folding asked despite the block"

    # After the recovery window exactly one attempt — one request — goes through again.
    uhr.weiter(faltpause.WIEDERAUFNAHME_SEKUNDEN)
    await _falten(client, chat, ausfall)
    assert len(ausfall.anfragen) == 3


async def test_ein_erfolg_dazwischen_setzt_die_reihe_zurueck(client, uhr):
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    ausfall = _Ausfall()

    await _falten(client, chat, ausfall)
    uhr.weiter(faltpause.PAUSE_LANG)
    _schwer(repositories, chat.id, 12)
    await _falten(client, chat, _Zusammenfasser())
    _schwer(repositories, chat.id, 12)
    await _falten(client, chat, ausfall)

    assert faltpause.hinweis_faellig(chat.id) is False
    assert faltpause.automatik_gesperrt(chat.id, jetzt=uhr.jetzt + faltpause.PAUSE_LANG) is False


async def test_ein_totes_modell_laesst_die_zeilen_stehen_und_sperrt_beim_zweiten_mal(client, uhr):
    """A dead model: no seam, not one row changed, the pause — and the second
    failure after the pause switches automatic folding off, with its notice
    due once."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    vorher = _zeilen(repositories, chat.id)
    ausfall = _Ausfall()

    kennung = await _falten(client, chat, ausfall)

    assert kennung is None
    assert _zeilen(repositories, chat.id) == vorher
    assert not [z for z in vorher if z[2] == "verdichtung"]
    assert faltpause.pausiert(chat.id) is True
    assert faltpause.hinweis_faellig(chat.id) is False

    uhr.weiter(faltpause.PAUSE_LANG)
    await _falten(client, chat, ausfall)

    assert len(ausfall.anfragen) == 2
    assert faltpause.automatik_gesperrt(chat.id) is True
    assert faltpause.hinweis_faellig(chat.id) is True
    assert faltpause.hinweis_faellig(chat.id) is False


async def test_eine_pruefung_ohne_anfrage_verbraucht_den_einen_versuch_nicht(client, uhr):
    """After the block and its recovery window one attempt stands ready. A
    turn that gets past the check and then asks no model — here because the
    window leaves no room to write a summary in — leaves that attempt
    standing, and the next turn that asks spends it with one request."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    ausfall = _Ausfall()

    await _falten(client, chat, ausfall)
    uhr.weiter(faltpause.PAUSE_LANG)
    await _falten(client, chat, ausfall)
    assert len(ausfall.anfragen) == 2
    assert faltpause.automatik_gesperrt(chat.id) is True

    uhr.weiter(faltpause.PAUSE_LANG)
    await _falten(client, chat, ausfall)
    uhr.weiter(faltpause.WIEDERAUFNAHME_SEKUNDEN)

    # A turn that gets past the check and asks nothing: the same reading, but
    # a window that leaves the summarizing request no room for any of the
    # history once the summary's reserve is set aside.
    enges_fenster = 2_048
    assert await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(ausfall, context_tokens=enges_fenster),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=enges_fenster,
    ) is None

    assert len(ausfall.anfragen) == 2, "a request went out without room for a summary"

    # The attempt is still standing, and the next turn spends it — with
    # exactly one request.
    await _falten(client, chat, ausfall)

    assert len(ausfall.anfragen) == 3, "the one attempt was already spent"
    # And it was spent by that one request: the block is back at once.
    uhr.weiter(faltpause.PAUSE_LANG)
    await _falten(client, chat, ausfall)

    assert len(ausfall.anfragen) == 3, "the block let a second one through"


async def test_nach_der_freigabe_wird_sofort_wieder_ein_modell_gefragt(client, uhr):
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    ausfall = _Ausfall()
    await _falten(client, chat, ausfall)
    await _falten(client, chat, ausfall)
    assert len(ausfall.anfragen) == 1

    faltpause.freigeben(chat.id)

    _schwer(repositories, chat.id, 12)
    await _falten(client, chat, ausfall)
    assert len(ausfall.anfragen) == 2


async def test_eine_gelungene_faltung_traegt_keine_notfallmarke(client, uhr):
    """The silence test: nothing about a fold that worked says emergency."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)

    kennung = await _falten(client, chat, _Zusammenfasser())

    assert kennung is not None
    assert repositories.messages.holen(kennung).stats.get("notfall") is None
    assert faltpause.hinweis_faellig(chat.id) is False
    assert faltpause.pausiert(chat.id) is False


async def test_ein_gescheiterter_versuch_laesst_die_dokumente_im_verlauf(client, uhr):
    """No summary, no fold: the rows carrying documents stay unfolded, so
    every document keeps travelling with the conversation and nothing leaves
    the prompt without a word."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    _mit_dokumenten(repositories, chat.id, 12)
    plan = _ganzer_plan(repositories, chat.id)
    repositories.einstellungen.setzen("global", "verdichtung_schwelle", 1)
    vorher = _zeilen(repositories, chat.id)
    ausfall = _Ausfall()

    kennung = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(ausfall),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=120_000,
        dokumentplan=plan,
    )

    assert kennung is None
    assert len(ausfall.anfragen) == 1
    assert _zeilen(repositories, chat.id) == vorher
    text = "\n".join(n.content or "" for n in _gebaut(chat, repositories, plan))
    assert text.count("D" * 24_000) == 12


# --- what the tools found reaches the summarizer too ---


async def test_die_bitte_traegt_die_werkzeuge_der_mitte(client):
    """A tool call in the folded stretch travels into the summarizing
    request, with what it returned — capped, and saying that it was capped.

    Without it the summary could not carry what the tool FOUND, and after
    the fold that was out of every later prompt unless an answer had
    repeated it by hand. The calls were weighed into the saving check all
    along (`werkzeuggewicht`), which is what made the gap hard to see.
    """
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 3)
    repositories.messages.speichern(
        chat_id=chat.id, role="user", content="Sieh im Log nach.",
    )
    repositories.messages.speichern(
        chat_id=chat.id, role="assistant", content="Erledigt.", zustand="fertig",
        stats={"werkzeuge": [
            {
                "name": "run_command",
                "argumente": {"command": "cat log"},
                "ergebnis": "ANFANG" + "Q" * 20_000 + "ENDE",
                "fehlgeschlagen": False,
            },
        ]},
    )
    _schwer(repositories, chat.id, 9)
    fasser = _Zusammenfasser()

    await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(fasser),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )

    gefragt = fasser.anfragen[0].nachrichten
    # The compaction request offers no tools, so the calls travel as text —
    # messages carrying calls without an offer are refused outright.
    assert all(not n.werkzeugaufrufe for n in gefragt)
    text = "\n".join(n.content for n in gefragt)
    # The call stands in front of what it answered, in one line.
    assert faltbitte.KOPFZEILE in text
    assert '- run_command {"command": "cat log"} → ANFANG' in text
    # As much of the result as this chat's own prompts have ever carried,
    # and no more: since the call ran, the model has not seen the rest, so
    # a summary cannot be asked to write it down. Cut where the prompt cuts,
    # with the prompt's own note (app/verlaufsbau.py).
    assert text.count("Q") == verlaufsbau.VERLAUF_ERGEBNIS_ZEICHEN - len("ANFANG")
    assert "ENDE" not in text
    assert "…[truncated]" in text
    assert faltbitte.ERGEBNIS_VERMERK not in text


async def test_eine_berichtszeile_geht_als_nutzerseite_in_die_faltung(client):
    """A report is the SERVICE talking, and the fold hands it over the way
    the conversation does — as the user's side of it.

    The row is stored as an assistant row so the window files it with the
    answer, but the model never said it. Read from that stored field it would
    go to the summarising model as the model's own words, and the summary
    would carry a report of the model's own making — the shape the ONE rule
    (`app/verlaufsbau._als_modellnachricht`) exists to prevent.
    """
    repositories = client.app.state.repositories
    chat = _chat(client)
    # The row has to land where the fold KEEPS the middle: a middle wider
    # than the ceiling is cut in its own middle, so a report placed in the
    # centre of the history would be gone from the request either way.
    _schwer(repositories, chat.id, 2)
    repositories.messages.speichern(
        chat_id=chat.id,
        role="assistant",
        content="ein bericht des dienstes",
        art="werkzeugmeldung",
        zustand="fertig",
    )
    _schwer(repositories, chat.id, 58)
    fasser = _Zusammenfasser()

    kennung = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(fasser),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )

    assert kennung is not None
    gefragt = "\n".join(n.content for n in fasser.anfragen[0].nachrichten)
    assert "[USER]: ein bericht des dienstes" in gefragt
    assert "[ASSISTANT]: ein bericht des dienstes" not in gefragt
    assert "[ASSISTANT]: ein bericht des dienstes" not in gefragt


async def test_eine_riesige_mitte_wird_gedeckelt_mit_vermerk(client):
    """A middle wider than the ceiling is cut from its middle, and the
    request says so.

    Without the ceiling the fold asks a model to read more than it can:
    there is no room left to write a summary in, so nothing is folded and
    no model is ever asked — on every turn, for the rest of the
    conversation.
    """
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 30)
    fasser = _Zusammenfasser()

    kennung = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(fasser),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )

    assert kennung is not None
    gefragt = fasser.anfragen[0].nachrichten
    assert len(gefragt) == 2
    assert len(gefragt[0].content) <= faltbitte.BITTE_MAX
    # Front, end and a note in between: the front of the folded stretch —
    # the request carries the middle, the pinned opening stays out of it —
    # the end of it, and a visible seam between them.
    assert gefragt[0].content.startswith("[ASSISTANT]: antwort 1 ")
    assert "Summary input truncated" in gefragt[0].content
    # The ask itself is never cut: it is what the request is for.
    assert gefragt[1].content == verdichtung.ANFRAGE_TEXT


def _denkender_llama():
    from app.config import Capabilities, EndpointConfig

    return EndpointConfig(
        id="test",
        base_url="http://127.0.0.1:9/v1",
        parameter_dialect="llama_cpp",
        capabilities=Capabilities(thinking=True),
    )


async def _chatfaltung(client, fasser):
    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 40)
    return await chatverdichtung.erzwungen_verdichten(
        zustand=_Zustand(fasser, endpunkt=_denkender_llama()),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        zeilen=repositories.messages.fuer_das_modell(chat_id=chat.id),
        budget=verdichtung.LETZTE_ZEICHEN,
    )


async def test_die_chatfaltung_liest_die_gemerkte_ablehnung(client, uhr):
    """The chat's own fold reads the list its turns read: a switch this
    server has refused before does not go out with the summary request."""
    from app import denkablehnung

    denkablehnung.merken(client.app.state.repositories.einstellungen, "test", "off")
    fasser = _Zusammenfasser()

    await _chatfaltung(client, fasser)

    assert fasser.anfragen[0].zusatz == {}


async def test_ohne_ablehnung_schaltet_die_chatfaltung_das_denken_aus(client, uhr):
    """The silence probe: nothing refused, the switch goes out as before."""
    fasser = _Zusammenfasser()

    await _chatfaltung(client, fasser)

    assert fasser.anfragen[0].zusatz


async def test_die_chatfaltung_merkt_sich_eine_abgelehnte_stufe(client, uhr):
    """A server that refuses the chat fold's "off" has it written down under
    its id, where the chat's turns and the jobs on that server read it."""
    from app import denkablehnung
    from app.providers import ProviderFehler

    class Ablehnend(_Zusammenfasser):
        async def streamen(self, anfrage):
            self.anfragen.append(anfrage)
            raise ProviderFehler(
                "abgelehnt", status=400,
                rohtext="thinking: this parameter is not supported by this model",
            )
            yield  # pragma: no cover

    fasser = Ablehnend()
    await _chatfaltung(client, fasser)

    assert fasser.anfragen[0].zusatz, "no switch went out, nothing to refuse"
    assert denkablehnung.gemerkt(client.app.state.repositories.einstellungen, "test") == ["off"]


async def test_the_fold_keeps_a_refusal_where_the_model_list_reads_it(client, uhr):
    """A chat that names the model beside a server without a catalogue
    (`test:test`) still has the fold's refusal written under the id the
    model list reads (`refusal_key`: the endpoint alone), and the next fold
    reads it from there; another endpoint's list stays empty."""
    from app import denkablehnung
    from app.providers import ProviderFehler

    class Ablehnend(_Zusammenfasser):
        async def streamen(self, anfrage):
            self.anfragen.append(anfrage)
            raise ProviderFehler(
                "abgelehnt", status=400,
                rohtext="thinking: this parameter is not supported by this model",
            )
            yield  # pragma: no cover

    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 40)
    await chatverdichtung.erzwungen_verdichten(
        zustand=_Zustand(Ablehnend(), endpunkt=_denkender_llama()),
        repositories=repositories,
        chat=chat,
        endpoint_id="test:test",
        modellname="test",
        zeilen=repositories.messages.fuer_das_modell(chat_id=chat.id),
        budget=verdichtung.LETZTE_ZEICHEN,
    )
    einstellungen = repositories.einstellungen
    assert denkablehnung.gemerkt(einstellungen, "test") == ["off"]
    assert denkablehnung.gemerkt(einstellungen, "test:test") == []
    assert denkablehnung.gemerkt(einstellungen, "anders") == []


class _RefusesOnce(_Zusammenfasser):
    """Refuses the switch on the first request, summarises on the next."""

    def __init__(self, rohtext="thinking: this parameter is not supported by this model"):
        super().__init__()
        self.rohtext = rohtext

    async def streamen(self, anfrage):
        from app.providers import ProviderFehler
        from app.providers.base import Stueck

        self.anfragen.append(anfrage)
        if len(self.anfragen) == 1:
            raise ProviderFehler("refused", status=400, rohtext=self.rohtext)
        yield Stueck("content", text=self.text)


async def test_the_chat_fold_asks_once_more_without_a_refused_switch(client, uhr):
    """Written down, then the same fold once more at once without the
    switch — and its summary is used."""
    server = _RefusesOnce()
    _zusammenfassung, ergebnis = await _chatfaltung(client, server)

    assert len(server.anfragen) == 2
    assert server.anfragen[0].zusatz
    assert server.anfragen[1].zusatz == {}
    assert ergebnis.angewendet is True


async def test_another_400_of_the_chat_fold_gets_no_second_request(client, uhr):
    """Silence probe: any other failure stays one request."""
    server = _RefusesOnce(rohtext="invalid_api_key: the key is wrong")
    _zusammenfassung, ergebnis = await _chatfaltung(client, server)

    assert len(server.anfragen) == 1
    assert ergebnis.angewendet is False


# --- compacting by hand: POST /chats/{id}/compact ---


def _hand(client, provider, context_tokens=100_000):
    """The test endpoint answering with ``provider``, a window it fits in."""
    from tests.conftest import provider_setzen

    provider_setzen(client, provider)
    client.app.state.discovery.zustaende["test"].context_tokens = context_tokens
    return provider


def _compact(client, chat_id, **body):
    return client.post(f"/api/v1/chats/{chat_id}/compact", json=body)


def _unfolded(repositories, chat_id) -> int:
    return len(repositories.messages.fuer_das_modell(chat_id=chat_id))


def test_a_hand_made_fold_folds_a_chat_below_its_threshold_and_says_how_many(client):
    """No reading, no threshold: the chat has never been measured and folds."""
    from app.providers import MockProvider

    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    before = _unfolded(repositories, chat.id)
    fasser = _hand(client, MockProvider(haeppchen=["## Done\n- compacted"]))

    antwort = _compact(client, chat.id)

    assert antwort.status_code == 200
    body = antwort.json()
    assert body["result"] == "folded"
    assert body["replaced"] > 0
    # The count is what the seam under the middle will say.
    summary = next(
        m for m in repositories.messages.auflisten(chat_id=chat.id) if m.art == "verdichtung"
    )
    assert body["replaced"] == summary.verdichtete_anzahl
    assert _unfolded(repositories, chat.id) == before - body["replaced"] + 1
    assert len(fasser.alle_anfragen) == 1, "exactly one summary request"


def test_a_second_hand_made_fold_finds_nothing_left_to_fold(client):
    from app.providers import MockProvider

    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    fasser = _hand(client, MockProvider(haeppchen=["## Done\n- compacted"]))
    assert _compact(client, chat.id).json()["result"] == "folded"

    antwort = _compact(client, chat.id)

    assert antwort.json() == {"result": "too_short", "replaced": 0}
    assert len(fasser.alle_anfragen) == 1, "the second one asked no model"


def test_a_chat_without_a_middle_is_too_short_and_asks_no_model(client):
    from app.providers import MockProvider

    repositories = client.app.state.repositories
    chat = _chat(client)
    repositories.messages.speichern(chat_id=chat.id, role="user", content="Hi")
    repositories.messages.speichern(
        chat_id=chat.id, role="assistant", content="Hello", zustand="fertig"
    )
    fasser = _hand(client, MockProvider())

    antwort = _compact(client, chat.id)

    assert antwort.json() == {"result": "too_short", "replaced": 0}
    assert fasser.alle_anfragen == []
    assert not [
        m for m in repositories.messages.auflisten(chat_id=chat.id) if m.art == "verdichtung"
    ]


def test_a_summary_that_is_not_shorter_folds_nothing_and_says_so(client):
    from app.providers import MockProvider

    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    before = _unfolded(repositories, chat.id)
    _hand(client, MockProvider(haeppchen=["z" * 600_000]))

    antwort = _compact(client, chat.id)

    assert antwort.json() == {"result": "no_saving", "replaced": 0}
    assert _unfolded(repositories, chat.id) == before


def test_a_failed_summary_folds_nothing_and_frees_the_chat(client):
    from app.providers import MockProvider

    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    before = _unfolded(repositories, chat.id)
    _hand(client, MockProvider(fehler="the server is down"))

    antwort = _compact(client, chat.id)

    assert antwort.json() == {"result": "failed", "replaced": 0}
    assert _unfolded(repositories, chat.id) == before
    generierungen = client.app.state.generierungen
    assert generierungen.beansprucht(chat.id) is False
    faltpause.freigeben(chat.id)


def test_the_hand_lifts_the_pause_and_the_block_and_the_automatic_fold_works_again(client):
    from app.providers import MockProvider

    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    faltpause.notfall(chat.id, faltpause.LANG)
    assert faltpause.notfall(chat.id, faltpause.LANG) is True
    assert faltpause.automatik_gesperrt(chat.id) is True
    fasser = _hand(client, MockProvider(haeppchen=["## Done\n- compacted"]))

    antwort = _compact(client, chat.id)

    assert antwort.json()["result"] == "folded"
    assert len(fasser.alle_anfragen) == 1
    assert faltpause.pausiert(chat.id) is False
    assert faltpause.automatik_gesperrt(chat.id) is False


def test_a_hand_made_fold_goes_past_the_brake_of_an_earlier_empty_try(client):
    """An automatic fold that saved nothing for this middle brakes the next
    automatic one; the user asking is not that next one."""
    from app.providers import MockProvider

    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    chatverdichtung._ohne_ersparnis[chat.id] = ("test", 1, 1)
    try:
        fasser = _hand(client, MockProvider(haeppchen=["## Done\n- compacted"]))
        assert _compact(client, chat.id).json()["result"] == "folded"
        assert len(fasser.alle_anfragen) == 1
    finally:
        chatverdichtung._ohne_ersparnis.pop(chat.id, None)


def test_a_topic_is_the_last_sentence_of_the_request_and_no_topic_changes_nothing(client):
    from app.providers import MockProvider

    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    fasser = _hand(client, MockProvider(haeppchen=["## Done\n- compacted"]))

    assert _compact(client, chat.id).json()["result"] == "folded"
    plain = fasser.alle_anfragen[-1].nachrichten[-1].content
    assert plain == verdichtung.ANFRAGE_TEXT

    _schwer(repositories, chat.id, 12)
    assert _compact(client, chat.id, topic="  only the open tasks  ").json()["result"] == "folded"
    focused = fasser.alle_anfragen[-1].nachrichten[-1].content
    sentence = verdichtung.FOCUS_TEXT.format(topic="only the open tasks")
    assert focused.startswith(verdichtung.ANFRAGE_TEXT)
    assert focused.rstrip("\n").endswith(sentence)
    assert focused.count(sentence) == 1


def test_a_blank_topic_is_no_topic(client):
    from app.providers import MockProvider

    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    fasser = _hand(client, MockProvider(haeppchen=["## Done\n- compacted"]))

    _compact(client, chat.id, topic="   ")

    assert fasser.alle_anfragen[-1].nachrichten[-1].content == verdichtung.ANFRAGE_TEXT


def test_a_busy_chat_answers_409_and_is_not_touched(client):
    from app.providers import MockProvider

    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    before = _unfolded(repositories, chat.id)
    fasser = _hand(client, MockProvider())
    generierungen = client.app.state.generierungen
    assert generierungen.reservieren(chat.id)
    try:
        antwort = _compact(client, chat.id)
    finally:
        generierungen.freigeben(chat.id)

    assert antwort.status_code == 409
    assert fasser.alle_anfragen == []
    assert _unfolded(repositories, chat.id) == before
    # And the claim of the one that held it is not taken away by the loser.
    assert generierungen.beansprucht(chat.id) is False


def test_a_chat_without_a_model_or_with_an_unknown_one_is_refused(client):
    repositories = client.app.state.repositories
    chat = repositories.chats.erstellen(user_id="standard", title="Ohne Modell")

    assert _compact(client, chat.id).status_code == 400
    assert _compact(client, chat.id, endpoint_id="nowhere").status_code == 404
    assert client.post(
        "/api/v1/chats/nope/compact", json={}
    ).status_code == 404


def test_a_message_that_only_says_compact_is_a_message(client):
    """The slash line is the window's; the service folds only on its own way."""
    from app.providers import MockProvider
    from tests.conftest import senden

    chat_id = client.post("/api/v1/chats", json={"title": "T"}).json()["id"]
    provider = _hand(client, MockProvider(haeppchen=["ok"]))

    senden(client, chat_id, content="/compact")

    rows = client.app.state.repositories.messages.auflisten(chat_id=chat_id)
    assert rows[0].content == "/compact" and rows[0].role == "user"
    # It went to the model as what it is, a message; the request builder
    # puts its own block in front of the newest turn.
    assert provider.alle_anfragen[-1].nachrichten[-1].content.endswith("/compact")
    assert not [m for m in rows if m.art == "verdichtung"]


def test_a_hand_made_fold_of_a_chat_with_documents_names_them_and_counts_exactly(client):
    """The document plan is read from the rows, so a chat of short turns that
    each carry a big document folds, and the request asks the summary to
    record what each document was — the same rule the automatic fold gives."""
    from app.providers import MockProvider

    repositories = client.app.state.repositories
    chat = _chat(client)
    _mit_dokumenten(repositories, chat.id, 12)
    fasser = _hand(client, MockProvider(haeppchen=["## Done\n- compacted"]))

    antwort = _compact(client, chat.id).json()

    assert antwort["result"] == "folded"
    summary = next(
        m for m in repositories.messages.auflisten(chat_id=chat.id) if m.art == "verdichtung"
    )
    assert antwort["replaced"] == summary.verdichtete_anzahl > 0
    request = fasser.alle_anfragen[-1].nachrichten
    assert chatverdichtung.DOKUMENTREGEL in request[-1].content
    # The documents go in named and measured, never with their bodies.
    history = "\n".join(m.content for m in request[:-1])
    assert "is not included here" in history
    assert "D" * 1_000 not in history


def _middle_of(client, zeilen_daten):
    repositories = client.app.state.repositories
    chat = _chat(client)
    for daten in zeilen_daten:
        repositories.messages.speichern(chat_id=chat.id, **daten)
    return repositories, repositories.messages.auflisten(chat_id=chat.id)


def test_the_middle_weighs_its_tools_in_the_shape_of_the_offer(client):
    """The middle is weighed as the request that is asked about carries it:
    the calls as turns where tools are offered, as the text block over the
    answer where they are not."""
    repositories, zeilen = _middle_of(client, [
        {"role": "user", "content": "Zeig mir den Ordner."},
        {"role": "assistant", "content": "Hier.", "zustand": "fertig",
         "stats": {"werkzeuge": [
             {"name": "run_command", "argumente": {"command": "ls"}, "ergebnis": "file.txt\n"},
         ]}},
    ])

    mit = chatverdichtung._mitte_wirklich(zeilen, [], repositories, None, offers_tools=True)
    ohne = chatverdichtung._mitte_wirklich(zeilen, [], repositories, None, offers_tools=False)

    assert ohne - mit == verlaufsbau.werkzeuggewicht(zeilen[1], offers_tools=False) - (
        verlaufsbau.werkzeuggewicht(zeilen[1], offers_tools=True)
    )
    assert ohne > mit


def test_the_middle_weighs_a_picture_at_its_price_where_the_model_sees(client):
    from app import kontextdruck

    repositories, zeilen = _middle_of(client, [
        {"role": "user", "content": "", "anhaenge": ["foto.png"]},
    ])

    sieht = chatverdichtung._mitte_wirklich(zeilen, [], repositories, None, vision=True)
    blind = chatverdichtung._mitte_wirklich(zeilen, [], repositories, None, vision=False)

    assert sieht == kontextdruck.bild_zeichen(1)
    assert blind == len("[An image was attached here that this model cannot see.]")


def test_silence_a_middle_of_text_weighs_its_text(client):
    repositories, zeilen = _middle_of(client, [
        {"role": "user", "content": "Hallo"},
        {"role": "assistant", "content": "Welt", "zustand": "fertig"},
    ])

    assert chatverdichtung._mitte_wirklich(zeilen, [], repositories, None) == len("Hallo") + len("Welt")


# --- the boundary of the verbatim tail weighs what the request carries -----


def test_a_row_weighs_its_words_its_pictures_and_its_tool_log(client):
    from app import kontextdruck

    repositories, zeilen = _middle_of(client, [
        {"role": "user", "content": "", "anhaenge": ["foto.png"]},
        {"role": "user", "content": "Hallo", "anhaenge": ["foto.png", "zwei.png"]},
        {"role": "assistant", "content": "Hier.", "zustand": "fertig",
         "stats": {"werkzeuge": [
             {"name": "run_command", "argumente": {"command": "ls"}, "ergebnis": "y" * 300},
         ]}},
    ])

    gewichte = fold_row_weights.fold_row_weights(zeilen, repositories, document_plan=None)

    # A picture alone says nothing in words: it weighs its price, and not the
    # sentence that stands in for an empty row as well.
    assert gewichte[0] == kontextdruck.bild_zeichen(1)
    assert gewichte[1] == len("Hallo") + kontextdruck.bild_zeichen(2)
    assert verlaufsbau.werkzeuggewicht(zeilen[2]) > 300
    assert gewichte[2] == len("Hier.") + verlaufsbau.werkzeuggewicht(zeilen[2])
    # A caller that stays inside what a fold of messages counts leaves the
    # tool log out.
    ohne_log = fold_row_weights.fold_row_weights(
        zeilen, repositories, document_plan=None, tool_log=False
    )
    assert ohne_log[2] == len("Hier.")
    # A model that cannot see weighs the sentence that goes instead.
    blind = fold_row_weights.fold_row_weights(
        zeilen, repositories, document_plan=None, vision=False
    )
    assert blind[0] == len("[An image was attached here that this model cannot see.]")


async def test_a_chat_of_pictures_and_little_text_folds(client):
    """Twenty pictures and a few words each: by its text the history is a few
    hundred characters and never passes the tail budget, by what the request
    carries it is twenty times the price of a picture."""
    from app import kontextdruck

    repositories = client.app.state.repositories
    chat = _chat(client)
    for nr in range(20):
        repositories.messages.speichern(
            chat_id=chat.id, role="user", content=f"Look at {nr}.", anhaenge=["foto.png"]
        )
        repositories.messages.speichern(
            chat_id=chat.id, role="assistant", content=f"Seen {nr}.", zustand="fertig"
        )
    zeilen = repositories.messages.fuer_das_modell(chat_id=chat.id)
    assert sum(len(z.content) for z in zeilen) < 1_000
    assert 20 * kontextdruck.bild_zeichen(1) > verdichtung.LETZTE_ZEICHEN

    fasser = _Zusammenfasser()
    kennung = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(fasser),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )

    assert len(fasser.anfragen) == 1, "no summary was asked for"
    assert kennung is not None
    # The newest rows stay verbatim: the tail is not folded away.
    sichtbar = repositories.messages.fuer_das_modell(chat_id=chat.id)
    assert sichtbar[-1].content == "Seen 19."


async def test_silence_a_chat_of_text_alone_of_the_same_size_does_not_fold(client):
    repositories = client.app.state.repositories
    chat = _chat(client)
    for nr in range(20):
        repositories.messages.speichern(chat_id=chat.id, role="user", content=f"Look at {nr}.")
        repositories.messages.speichern(
            chat_id=chat.id, role="assistant", content=f"Seen {nr}.", zustand="fertig"
        )

    fasser = _Zusammenfasser()
    kennung = await chatverdichtung.vielleicht_verdichten(
        zustand=_Zustand(fasser),
        repositories=repositories,
        chat=chat,
        endpoint_id="test",
        modellname="test",
        vorheriger_stand=90_000,
    )

    assert fasser.anfragen == []
    assert kennung is None


# --- compacting by hand: the stop button ---


class _HaengendeBitte(MockProvider):
    """A provider whose summary request hangs until it is closed. Stop is
    pressed shortly after the request went out."""

    def __init__(self, stoppen=None):
        super().__init__(mock_endpunkt("test"), haeppchen=["## Done\n- compacted"])
        self.stoppen = stoppen
        self.bitten = 0
        self.geschlossen = False

    async def streamen(self, anfrage):
        self.bitten += 1
        if self.stoppen is not None:
            asyncio.get_running_loop().call_later(0.2, self.stoppen)
        try:
            await asyncio.sleep(60)
        finally:
            self.geschlossen = True
        async for stueck in super().streamen(anfrage):
            yield stueck


def test_a_stop_during_a_hand_made_fold_closes_the_request_and_folds_nothing(client):
    import time

    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    before = _unfolded(repositories, chat.id)
    generierungen = client.app.state.generierungen
    fasser = _hand(
        client, _HaengendeBitte(stoppen=lambda: generierungen.alle_im_chat_abbrechen(chat.id))
    )
    begonnen = time.monotonic()

    antwort = _compact(client, chat.id)

    assert time.monotonic() - begonnen < 15
    assert antwort.status_code == 200
    assert antwort.json() == {"result": "stopped", "replaced": 0}
    assert fasser.bitten == 1
    assert fasser.geschlossen, "the summary request ran on after the stop"
    # Nothing folded, nothing booked, the claim given back.
    assert _unfolded(repositories, chat.id) == before
    assert not [
        m for m in repositories.messages.auflisten(chat_id=chat.id) if m.art == "verdichtung"
    ]
    assert not faltpause.pausiert(chat.id)
    assert not faltpause.automatik_gesperrt(chat.id)
    assert not generierungen.beansprucht(chat.id)


def test_silence_a_stop_in_another_chat_lets_a_hand_made_fold_run(client):
    from app.providers import MockProvider

    repositories = client.app.state.repositories
    chat = _chat(client)
    _schwer(repositories, chat.id, 12)
    generierungen = client.app.state.generierungen
    _hand(client, MockProvider(haeppchen=["## Done\n- compacted"]))

    assert generierungen.alle_im_chat_abbrechen("some-other-chat") == 0
    antwort = _compact(client, chat.id)

    assert antwort.json()["result"] == "folded"
