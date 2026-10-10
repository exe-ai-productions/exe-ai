"""A chat run outlives its owning connection, the
chat list's ring learns about a run from the service, not only from this
window's own memory of it, and an open ask_user question
survives the chat being left and reopened."""

from __future__ import annotations

import asyncio

import pytest

from app.generationen import Generierung


class GetrennteVerbindung:
    """Just enough of a request for the watchdog: the browser is gone."""

    async def is_disconnected(self) -> bool:
        return True


def test_ein_via_completions_gestarteter_lauf_ist_nicht_an_die_verbindung_gebunden(
    client, chat_id
):
    """The real route a person's own send hits — not a hand-built run — ends
    up with ``an_verbindung_gebunden=False``, the same as a background wake
    already had. Without the fix at app/api/v1/generierung.py's
    ``completions`` route this reads ``True``, the dataclass default."""
    from app.providers import MockProvider

    from tests.conftest import provider_setzen

    provider_setzen(client, MockProvider(haeppchen=["Hallo"]))
    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Hi"},
    )
    assert antwort.status_code == 200
    zeile = next(z for z in antwort.text.splitlines() if z.startswith("data:"))
    generation_id = __import__("json").loads(zeile[5:])["generation_id"]

    lauf = client.app.state.generierungen.holen(generation_id)
    assert lauf is not None
    assert lauf.an_verbindung_gebunden is False


async def test_eine_getrennte_verbindung_bricht_einen_ungebundenen_lauf_nicht_ab():
    """The regression itself: a chat run started the way ``completions`` now
    starts it keeps going once its window is gone. Fails
    without the fix — the same watchdog, with ``an_verbindung_gebunden=True``
    (the old default), sets the signal instead (schweigeprobe below)."""
    from app.api.v1.generierung import _zusehen

    lauf = Generierung(
        id="g-ungebunden", chat_id="c-1", endpoint_id="test",
        an_verbindung_gebunden=False,
    )
    lauf.melden("erste Zeile")

    strom = _zusehen(lauf, GetrennteVerbindung())
    assert await strom.__anext__() == "erste Zeile"
    # A watchdog that were armed regardless of the flag would have had two
    # full ticks by now to see the "disconnected" answer and act on it.
    await asyncio.sleep(0.05)
    assert not lauf.soll_abbrechen, "a disconnect stopped a run that should not be bound to it"

    lauf.beenden()
    with pytest.raises(StopAsyncIteration):
        await strom.__anext__()


async def test_schweigeprobe_eine_gebundene_verbindung_bricht_weiter_ab():
    """Without this, the test above would pass for the wrong reason — a
    watchdog that never runs at all, say. A bound run (an agent watching its
    OWN request, or a chat before this fix) must still end when it goes."""
    from app.api.v1.generierung import _zusehen

    lauf = Generierung(
        id="g-gebunden", chat_id="c-1", endpoint_id="test",
        an_verbindung_gebunden=True,
    )
    lauf.melden("erste Zeile")

    strom = _zusehen(lauf, GetrennteVerbindung())
    assert await strom.__anext__() == "erste Zeile"
    for _ in range(40):
        if lauf.soll_abbrechen:
            break
        await asyncio.sleep(0.05)
    assert lauf.soll_abbrechen, "the bound run's own watchdog never fired"

    lauf.beenden()
    with pytest.raises(StopAsyncIteration):
        await strom.__anext__()


# --- The chat list learns about a run from the service --------------------


def test_chats_auflisten_meldet_laeuft_fuer_einen_registrierten_lauf(client, chat_id):
    """The list a SECOND window's sidebar reads must say a chat is running
    even though that window never started or watched the run itself."""
    verwaltung = client.app.state.generierungen
    lauf = verwaltung.anmelden(chat_id=chat_id, endpoint_id="test")
    try:
        chats = client.get("/api/v1/chats").json()
        eigener = next(c for c in chats if c["id"] == chat_id)
        assert eigener["laeuft"] is True
    finally:
        verwaltung.abmelden(lauf.id)

    chats = client.get("/api/v1/chats").json()
    eigener = next(c for c in chats if c["id"] == chat_id)
    assert eigener["laeuft"] is False


def test_ein_ruhender_chat_meldet_laeuft_falsch(client, chat_id):
    """Schweigeprobe: a chat with nothing going on does not light up."""
    chats = client.get("/api/v1/chats").json()
    eigener = next(c for c in chats if c["id"] == chat_id)
    assert eigener["laeuft"] is False


def test_chat_aendern_meldet_laeuft_auch_fuer_einen_gerade_laufenden_chat(client, chat_id):
    """A rename or a pin replaces this chat's OWN entry in the sidebar list
    directly (frontend/src/lib/zustand.svelte.js) — if that response always
    said ``laeuft: false``, renaming a running chat would dim its ring."""
    verwaltung = client.app.state.generierungen
    lauf = verwaltung.anmelden(chat_id=chat_id, endpoint_id="test")
    try:
        antwort = client.patch(f"/api/v1/chats/{chat_id}", json={"title": "Neu"})
        assert antwort.status_code == 200
        assert antwort.json()["laeuft"] is True
    finally:
        verwaltung.abmelden(lauf.id)


# --- An open ask_user question survives leaving the chat ------------------


def test_eine_offene_werkzeugfrage_steht_waehrend_des_wartens_in_der_datenbank(
    client, chat_id
):
    """The moment the model asks, the question is not only an in-memory
    Future any more — it is readable straight from the chat row, the same
    way a job's own `frage` column already works."""
    from tests.test_frage_werkzeug import FrageRegistry
    from app.providers import MockProvider, mock_endpunkt
    from app.providers.base import Werkzeugaufruf
    from tests.conftest import provider_setzen
    import json as json_

    repositories = client.app.state.repositories
    verwaltung = client.app.state.generierungen
    gesehen = {}

    def warten_und_lesen():
        # `bestaetigungen` is only populated once `_auf_entscheidung_warten`
        # has actually started waiting — the same moment the question's JSON
        # is on the chat row, since that write happens right before it. Only
        # then is it read, and only then does the answer go in — the same
        # moment a second window's cold reattach would read the row.
        for generierung in verwaltung.laufende():
            for aufruf_id in list(generierung.bestaetigungen):
                gesehen["frage_waehrend_des_wartens"] = repositories.chats.holen(chat_id).frage
                verwaltung.bestaetigen(generierung.id, aufruf_id, True, "Links")
                return
        asyncio.get_running_loop().call_later(0.01, warten_und_lesen)

    class WartendeRegistry(FrageRegistry):
        def braucht_bestaetigung(self, name, argumente=None, ordner=None):
            asyncio.get_running_loop().call_later(0.01, warten_und_lesen)
            return False

    registry = WartendeRegistry(client)
    client.app.state.werkzeuge = registry
    client.app.state.config.features.mcp = True
    provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["Gut."],
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id="a1",
                    name="ask_user",
                    argumente={
                        "question": "Welcher Weg?",
                        "options": [{"label": "Links"}, {"label": "Rechts"}],
                    },
                )
            ],
        ),
    )

    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "entscheide"},
    )
    assert antwort.status_code == 200

    roh = gesehen.get("frage_waehrend_des_wartens")
    assert roh is not None, "the question was never written to the chat row"
    gespeichert = json_.loads(roh)
    assert gespeichert["frage"] == "Welcher Weg?"
    assert gespeichert["aufruf_id"] == "a1"
    assert [o["label"] for o in gespeichert["optionen"]] == ["Links", "Rechts"]

    # Cleared once the run has answered it and moved on.
    chat_danach = repositories.chats.holen(chat_id)
    assert chat_danach.frage is None


def test_messages_liefert_die_offene_frage_beim_oeffnen_mit(client, chat_id):
    """What a cold-opened window actually reads: `NachrichtenSeite.frage`,
    the shape `zustand.svelte.js` adopts into `zustand.benutzerfrage`.

    Options are objects, `{"label": ..., "description": ...}` — the shape
    `frage_werkzeug.gepruefte_frage` actually produces and the live
    `user_ask` SSE event already carries — not bare strings. A live proof
    caught `OffeneFrage.optionen` declared as `list[str]`: it
    parsed an empty list fine and then failed this exact route with a 500
    the moment a real question had any options at all."""
    import json as json_

    repositories = client.app.state.repositories
    verwaltung = client.app.state.generierungen
    lauf = verwaltung.anmelden(chat_id=chat_id, endpoint_id="test")
    optionen = [
        {"label": "Links", "description": "über den Marktplatz"},
        {"label": "Rechts", "description": ""},
    ]
    repositories.chats.frage_setzen(
        chat_id,
        json_.dumps({"aufruf_id": "a1", "frage": "Welcher Weg?", "optionen": optionen}),
    )
    try:
        antwort = client.get(f"/api/v1/chats/{chat_id}/messages")
        assert antwort.status_code == 200
        frage = antwort.json()["frage"]
        assert frage == {"aufruf_id": "a1", "frage": "Welcher Weg?", "optionen": optionen}
    finally:
        verwaltung.abmelden(lauf.id)
        repositories.chats.frage_setzen(chat_id, None)


def test_messages_liefert_keine_frage_wenn_keine_offen_ist(client, chat_id):
    """Schweigeprobe: a chat with nothing open reports no question."""
    antwort = client.get(f"/api/v1/chats/{chat_id}/messages")
    assert antwort.json()["frage"] is None


def test_frage_setzen_ruehrt_updated_at_nicht_an(client, chat_id):
    """Asking or answering a question is not the user reordering their own
    list — `anheften` makes the same promise for pinning."""
    repositories = client.app.state.repositories
    vorher = repositories.chats.holen(chat_id).updated_at
    repositories.chats.frage_setzen(chat_id, '{"aufruf_id": "a1", "frage": "x", "optionen": []}')
    repositories.chats.frage_setzen(chat_id, None)
    assert repositories.chats.holen(chat_id).updated_at == vorher
