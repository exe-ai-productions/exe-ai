"""Several attachments on one message: lists in, lists through, ✕ out.

The pipeline used to carry exactly one image and one document per message.
These tests hold the list path together end to end: the request takes lists,
the stored row keeps them (scalar twins filled for older readers), the
provider receives one image part per attachment and one text block per
document, and the ✕ route removes a single attachment without touching the
rest of the message.
"""

from __future__ import annotations

import itertools

from app.providers import ChatNachricht, MockProvider
from app.providers.openai_kompatibel import OpenAIKompatiblerProvider
from tests.conftest import provider_setzen

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"testbild"
_UPLOADS = itertools.count()


def _chat(client):
    return client.post("/api/v1/chats", json={"title": "Anhaenge"}).json()


def _bild_hochladen(client) -> str:
    # Every call is a picture of its own: the same bytes would be one file.
    inhalt = PNG_BYTES + str(next(_UPLOADS)).encode()
    return client.post(
        "/api/v1/images", content=inhalt, headers={"Content-Type": "image/png"}
    ).json()["bild"]


def _dokument_hochladen(client, chat_id: str, name: str, text: str) -> str:
    antwort = client.post(
        f"/api/v1/documents?chat_id={chat_id}&name={name}", content=text.encode()
    )
    assert antwort.status_code == 201
    return antwort.json()["dokument"]["id"]


def _vision_an(client) -> None:
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.vision = True


def test_mehrere_bilder_reisen_als_liste(client):
    chat = _chat(client)
    _vision_an(client)
    provider = provider_setzen(client, MockProvider(haeppchen=["ok"]))
    eins, zwei = _bild_hochladen(client), _bild_hochladen(client)

    antwort = client.post(
        "/api/v1/chat/completions",
        json={
            "chat_id": chat["id"],
            "endpoint_id": "test",
            "content": "Was ist auf den Bildern?",
            "bilder": [eins, zwei],
        },
    )
    assert antwort.status_code == 200

    nachricht = client.get(f"/api/v1/chats/{chat['id']}/messages").json()["nachrichten"][0]
    assert nachricht["anhaenge"] == [eins, zwei]
    # The scalar twin carries the first entry for older readers.
    assert nachricht["bild"] == eins

    benutzer = [n for n in provider.letzte_anfrage.nachrichten if n.role == "user"][-1]
    assert len(benutzer.alle_bild_urls()) == 2


def test_mehrere_bilder_ohne_vision_geben_400(client):
    chat = _chat(client)
    bild = _bild_hochladen(client)
    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat["id"], "endpoint_id": "test", "bilder": [bild]},
    )
    assert antwort.status_code == 400


def test_mehrere_dokumente_reisen_in_den_verlauf(client):
    chat = _chat(client)
    provider = provider_setzen(client, MockProvider(haeppchen=["ok"]))
    erste = _dokument_hochladen(client, chat["id"], "eins.txt", "Erster Inhalt AAA.")
    zweite = _dokument_hochladen(client, chat["id"], "zwei.txt", "Zweiter Inhalt BBB.")

    antwort = client.post(
        "/api/v1/chat/completions",
        json={
            "chat_id": chat["id"],
            "endpoint_id": "test",
            "content": "Fasse beide zusammen.",
            "dokumente": [erste, zweite],
        },
    )
    assert antwort.status_code == 200

    benutzer = [n for n in provider.letzte_anfrage.nachrichten if n.role == "user"][-1]
    assert "Erster Inhalt AAA." in benutzer.content
    assert "Zweiter Inhalt BBB." in benutzer.content
    # The first attachment stands first in the prepended blocks.
    assert benutzer.content.index("AAA") < benutzer.content.index("BBB")

    nachricht = client.get(f"/api/v1/chats/{chat['id']}/messages").json()["nachrichten"][0]
    karten = nachricht["dokumente"]
    assert [karte["name"] for karte in karten] == ["eins.txt", "zwei.txt"]


def test_einzelbild_bleibt_wie_bisher(client):
    """The scalar fields keep working — older callers, queued sends."""
    chat = _chat(client)
    _vision_an(client)
    provider = provider_setzen(client, MockProvider(haeppchen=["ok"]))
    bild = _bild_hochladen(client)
    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat["id"], "endpoint_id": "test", "content": "?", "bild": bild},
    )
    assert antwort.status_code == 200
    benutzer = [n for n in provider.letzte_anfrage.nachrichten if n.role == "user"][-1]
    assert len(benutzer.alle_bild_urls()) == 1


def test_x_entfernt_ein_bild_und_laesst_den_rest(client):
    chat = _chat(client)
    _vision_an(client)
    provider_setzen(client, MockProvider(haeppchen=["ok"]))
    eins, zwei = _bild_hochladen(client), _bild_hochladen(client)
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat["id"], "endpoint_id": "test", "content": "?", "bilder": [eins, zwei]},
    )
    nachricht = client.get(f"/api/v1/chats/{chat['id']}/messages").json()["nachrichten"][0]

    antwort = client.delete(
        f"/api/v1/chats/{chat['id']}/messages/{nachricht['id']}/anhang?bild={eins}"
    )
    assert antwort.status_code == 200
    danach = client.get(f"/api/v1/chats/{chat['id']}/messages").json()["nachrichten"][0]
    assert danach["bild"] == zwei
    assert danach["anhaenge"] is None

    # A second run rebuilds the history — the removed image is gone there too.
    provider = provider_setzen(client, MockProvider(haeppchen=["ok"]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat["id"], "endpoint_id": "test", "content": "Nochmal"},
    )
    benutzer = [n for n in provider.letzte_anfrage.nachrichten if n.role == "user"]
    assert len(benutzer[0].alle_bild_urls()) == 1


def test_x_entfernt_ein_dokument_mitsamt_zeile(client):
    chat = _chat(client)
    provider_setzen(client, MockProvider(haeppchen=["ok"]))
    erste = _dokument_hochladen(client, chat["id"], "eins.txt", "Inhalt EINS.")
    zweite = _dokument_hochladen(client, chat["id"], "zwei.txt", "Inhalt ZWEI.")
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat["id"], "endpoint_id": "test", "content": "?", "dokumente": [erste, zweite]},
    )
    nachricht = client.get(f"/api/v1/chats/{chat['id']}/messages").json()["nachrichten"][0]

    antwort = client.delete(
        f"/api/v1/chats/{chat['id']}/messages/{nachricht['id']}/anhang?dokument={erste}"
    )
    assert antwort.status_code == 200
    # The row is gone with the reference — its text existed for this message.
    assert client.get(f"/api/v1/documents/{erste}").status_code == 404
    provider = provider_setzen(client, MockProvider(haeppchen=["ok"]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat["id"], "endpoint_id": "test", "content": "Weiter"},
    )
    benutzer = [n for n in provider.letzte_anfrage.nachrichten if n.role == "user"]
    assert "Inhalt ZWEI." in benutzer[0].content
    assert "Inhalt EINS." not in benutzer[0].content


def test_x_auf_fremden_anhang_gibt_404(client):
    chat = _chat(client)
    _vision_an(client)
    provider_setzen(client, MockProvider(haeppchen=["ok"]))
    bild = _bild_hochladen(client)
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat["id"], "endpoint_id": "test", "content": "?", "bild": bild},
    )
    nachricht = client.get(f"/api/v1/chats/{chat['id']}/messages").json()["nachrichten"][0]
    basis = f"/api/v1/chats/{chat['id']}/messages/{nachricht['id']}/anhang"
    assert client.delete(f"{basis}?bild=falsch.png").status_code == 404
    assert client.delete(basis).status_code == 400


def test_dokument_lesen_gibt_den_text(client):
    chat = _chat(client)
    kennung = _dokument_hochladen(client, chat["id"], "lesen.md", "Der ganze Text.")
    antwort = client.get(f"/api/v1/documents/{kennung}")
    assert antwort.status_code == 200
    daten = antwort.json()
    assert daten["dokument"]["name"] == "lesen.md"
    assert daten["text"] == "Der ganze Text."
    assert client.get("/api/v1/documents/gibtsnicht").status_code == 404


def test_provider_baut_mehrere_bildteile():
    nachricht = ChatNachricht(
        role="user",
        content="Vergleich?",
        bild_urls=["data:image/png;base64,QUJD", "data:image/png;base64,REVG"],
    )
    eintrag = OpenAIKompatiblerProvider._nachricht_bauen(nachricht)
    assert eintrag["content"] == [
        {"type": "text", "text": "Vergleich?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,REVG"}},
    ]
