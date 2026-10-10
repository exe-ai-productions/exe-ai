"""API endpoints from phase 1."""

from __future__ import annotations

from app import __version__
from app.i18n import STANDARDSPRACHE


def test_health_unversioniert(client):
    """Fixed address for Uptime Kuma and systemd — must never change."""
    antwort = client.get("/health")
    assert antwort.status_code == 200
    daten = antwort.json()
    assert daten["status"] == "ok"
    assert daten["version"] == __version__
    assert daten["datenbank"]["erreichbar"] is True


def test_health_unter_api_v1(client):
    antwort = client.get("/api/v1/health")
    assert antwort.status_code == 200
    assert antwort.json()["status"] == "ok"


def test_alle_api_routen_liegen_unter_v1(client):
    pfade = [
        route.path
        for route in client.app.routes
        if getattr(route, "path", "").startswith("/api")
    ]
    assert pfade, "There must be API routes"
    assert all(pfad.startswith("/api/v1/") for pfad in pfade), pfade


def test_meta_liefert_feature_flags(client):
    daten = client.get("/api/v1/meta").json()
    assert daten["name"] == "Exe AI"
    assert set(daten["features"]) == {
        "mcp",
        "document_upload",
        "shell_tool",
    }
    assert daten["verfuegbare_sprachen"] == ["de", "en"]


def test_meta_folgt_dem_sprachwunsch(client):
    deutsch = client.get("/api/v1/meta", headers={"Accept-Language": "de-DE,de;q=0.9"})
    englisch = client.get("/api/v1/meta", headers={"Accept-Language": "en-US,en;q=0.9"})
    assert deutsch.json()["sprache"] == "de"
    assert englisch.json()["sprache"] == "en"


def test_unbekannte_sprache_faellt_auf_konfiguration_zurueck(client):
    antwort = client.get("/api/v1/meta", headers={"Accept-Language": "fr-FR"})
    assert antwort.json()["sprache"] == "de"


def test_uebersetzungskatalog_wird_ausgeliefert(client):
    daten = client.get("/api/v1/translations/en").json()
    assert daten["sprache"] == "en"
    assert daten["texte"]["chat"]["neu"] == "New chat"


def test_unbekannte_sprache_liefert_standardkatalog(client):
    """Don't check against "de": which language is the default is a
    decision and may change. What matters is the fallback itself."""
    daten = client.get("/api/v1/translations/klingonisch").json()
    assert daten["sprache"] == STANDARDSPRACHE


def test_pwa_manifest_wird_ausgeliefert(client):
    antwort = client.get("/manifest.webmanifest")
    assert antwort.status_code == 200
    assert antwort.json()["short_name"] == "Exe AI"


def test_statische_dateien_werden_ausgeliefert(client):
    antwort = client.get("/")
    assert antwort.status_code == 200
    assert "<title>Exe AI</title>" in antwort.text
    assert ">Exe AI</text>" in antwort.text
    assert "Exe AI Terminal" not in antwort.text


def test_openapi_ist_erreichbar(client):
    assert client.get("/openapi.json").status_code == 200


def test_no_route_writes_text_from_the_page_into_a_working_folder(client):
    """The page once handed the text of an answer to a route of its own to
    have it written into a shared folder. Nothing calls that any more — a
    file reaches a folder through the tools, and a document through its
    upload — so the address is gone: it answers exactly as an address the
    service never had, and it stands neither among the routes nor on the
    page of routes."""
    gone = "/api/v1/outputs"
    body = {"chat_id": "any", "name": "note.txt", "inhalt": "text"}
    never_there = client.post("/api/v1/no-such-address", json=body)
    reply = client.post(gone, json=body)
    # What an unanswered address says is the static pages' business (they
    # are only ever read, so a POST there is refused rather than not found);
    # here it only has to be a refusal, and the same one.
    assert reply.status_code == never_there.status_code
    assert reply.status_code in (404, 405)
    assert client.get(gone).status_code == 404
    assert gone not in {getattr(route, "path", "") for route in client.app.routes}
    assert gone not in client.app.openapi()["paths"]


def test_a_document_is_still_handed_out_as_its_file(client):
    """The silence check beside it: the way a file is read back is the
    documents' own, and it answers as before."""
    chat = client.post("/api/v1/chats", json={"title": "Doku"}).json()
    card = client.post(
        f"/api/v1/documents?chat_id={chat['id']}&name=note.txt", content=b"A line."
    ).json()["dokument"]
    served = client.get(f"/api/v1/documents/{card['id']}/file")
    assert served.status_code == 200
    assert served.content == b"A line."
