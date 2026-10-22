"""Every answer's start is said on the bus, and the window can act on it.

A finished background command woke the model
while the window sat idle on the chat; the woken answer ran for half a
minute without the window knowing, the user typed into it, the service
answered 409, and the answer appeared only on the next open.
"""

from __future__ import annotations

from pathlib import Path

from app.events import Ereignisse, bus
from app.providers import MockProvider, mock_endpunkt
from tests.conftest import provider_setzen
from tests.fensterquelle import BAR_SOURCE, WINDOW_SOURCE

WURZEL = Path(__file__).resolve().parents[1]


def test_der_start_einer_antwort_liegt_auf_dem_bus(client, chat_id, monkeypatch):
    gesehen = []

    async def aufzeichnen(typ, **daten):
        gesehen.append((typ, daten))

    monkeypatch.setattr(bus, "veroeffentlichen", aufzeichnen)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Hallo."]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Hi"},
    )
    starts = [d for typ, d in gesehen if typ == Ereignisse.ANTWORT_BEGONNEN]
    assert len(starts) == 1
    assert starts[0]["chat_id"] == chat_id
    assert starts[0]["generation_id"] and starts[0]["message_id"]
    zeile = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"][1]
    assert starts[0]["message_id"] == zeile["id"]


def test_das_fenster_haengt_sich_an_und_nimmt_ein_409_zurueck():
    """Pinned at the source: the line's event becomes an owed reattachment
    unless the window holds the run itself, and a refused send takes its
    bubble down and hands the words back instead of standing twice."""
    leitung = (WURZEL / "frontend/src/lib/ereignisstrom.svelte.js").read_text(encoding="utf-8")
    assert "antwort_begonnen: (ereignis) => {" in leitung
    # Neither a run this window holds nor a send of its own still uploading
    # its document — that start is its own too.
    assert "zustand.laeuft[chatId] || zustand.sendet[chatId]) return" in leitung
    assert "zustand.wiederanhaengen[chatId] = {" in leitung
    app = WINDOW_SOURCE.read_text(encoding="utf-8")
    assert "fehler.status === 409" in app
    # The list is only touched while the refused chat is the one on screen;
    # the words AND the attachments go back to THAT chat's field or draft
    # either way — and with no word sent, too: such a send was refused just
    # the same, and used to get nothing back at all. A regenerate is not one
    # of those: `inhalt === null` never went through the bar, so the bar has
    # nothing of its own to hand back.
    assert "if (zielChat === zustand.aktiverChat) {" in app
    # What came out of the queue goes back in line (the other tests of the
    # queue pin that); what was typed goes back to the field.
    assert "eingabe?.zurueckgeben(inhalt, zielChat, nachrichtId)" in app
    assert "if (ausReihe) {" in app
    assert "gleichWiederAbgewiesen" not in app
    assert "void chatOeffnen(zielChat)" in app
    # The end-of-run reconcile attaches synchronously — it has just fetched
    # the list itself and must claim the chat before the queue wakes.
    assert "}, { nachholen: false })" in app
    assert "async function antwortWiederAnhaengen(wiederanhang, { nachholen = true } = {})" in app
    # A fetch overtaken by a later one for another run must not attach its
    # own, older run; and two runs naming each other must not fetch forever.
    assert "const nachgeholtFuer = new Set()" in app
    assert "if (nachgeholtZuletzt !== wiederanhang.generationId) return" in app
    # The ✕ on a bubble takes the message back into the field; nothing sends
    # a waiting message by a click any more.
    assert "eingabe?.takeBack(eintrag)" in app
    assert "warteschlangeLosschicken" not in app
    leiste = BAR_SOURCE.read_text(encoding="utf-8")
    assert "function zurueckgeben(inhalt, chat = entwurfChat, messageId = null)" in leiste
