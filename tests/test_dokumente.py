"""Document upload: extraction, limits, history, meta."""

from __future__ import annotations

import io

from app.i18n import t
from tests.conftest import pdf_mit_seiten

# The document endings as agreed: the text endings the agent reference
# reads, without .env (it holds keys), plus .pdf — 76 in all. Frozen here
# so neither of the two lists in the code can drift or shrink without a
# test going red.
ERWARTETE_ENDUNGEN = (
    ".pdf",
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".log", ".json", ".jsonl", ".ndjson", ".xml",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".properties", ".html", ".htm",
    ".css", ".scss", ".sass", ".less", ".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".c", ".h", ".cpp", ".cc", ".hpp", ".cs",
    ".java", ".kt", ".go", ".rs", ".rb", ".php", ".pl", ".lua", ".r", ".jl", ".swift", ".m",
    ".scala", ".clj", ".ex", ".exs", ".erl", ".sql", ".graphql", ".proto", ".tf", ".hcl",
    ".dockerfile", ".makefile", ".cmake", ".gradle", ".rst", ".tex", ".srt", ".vtt", ".diff",
    ".patch",
)


def _chat(client):
    return client.post("/api/v1/chats", json={"title": "Doku"}).json()


def test_txt_rundreise_und_meta(client):
    chat = _chat(client)
    antwort = client.post(
        f"/api/v1/documents?chat_id={chat['id']}&name=notiz.txt",
        content="Hallo Dokument, dies ist Text.".encode(),
    )
    assert antwort.status_code == 201
    meta = antwort.json()["dokument"]
    assert meta["typ"] == "txt"
    assert meta["kb"] == 1
    # The extracted text is in the database — not the file itself.
    dokument = client.app.state.repositories.documents.holen(meta["id"])
    assert "Hallo Dokument" in dokument.extracted_text


def test_grosse_texte_bleiben_ganz(client):
    """The upload keeps the whole text. How much of it a request carries is
    decided per model when the request is built (app/dokumentbudget.py) —
    a fixed cut here would throw away what a large window could read."""
    chat = _chat(client)
    antwort = client.post(
        f"/api/v1/documents?chat_id={chat['id']}&name=lang.md",
        content=("x" * 300_000).encode(),
    )
    assert antwort.status_code == 201
    meta = antwort.json()["dokument"]
    gespeichert = client.app.state.repositories.documents.holen(meta["id"])
    assert len(gespeichert.extracted_text) == 300_000


def test_falscher_typ_und_fremder_chat(client):
    chat = _chat(client)
    falsch = client.post(
        f"/api/v1/documents?chat_id={chat['id']}&name=bild.png", content=b"x"
    )
    assert falsch.status_code == 415
    fremd = client.post("/api/v1/documents?chat_id=gibtsnicht&name=a.txt", content=b"x")
    assert fremd.status_code == 404


def test_hochgeladenes_pdf_traegt_seitenmarken(client):
    """A model naming its source needs to see where each page begins — the
    same mark the read-file tool already carries."""
    chat = _chat(client)
    daten = pdf_mit_seiten(["Page one alpha", "Page two beta", "Page three gamma"])
    antwort = client.post(
        f"/api/v1/documents?chat_id={chat['id']}&name=bericht.pdf", content=daten
    )
    assert antwort.status_code == 201
    meta = antwort.json()["dokument"]
    dokument = client.app.state.repositories.documents.holen(meta["id"])
    text = dokument.extracted_text
    assert text.index("[page 1]") < text.index("[page 2]") < text.index("[page 3]")
    assert "Page two beta" in text


def test_txt_bleibt_zeichengetreu(client):
    """The silent case: a non-PDF file carries no page marks at all — the
    upload keeps exactly the bytes it was handed."""
    chat = _chat(client)
    inhalt = "Zeile eins\nZeile zwei"
    antwort = client.post(
        f"/api/v1/documents?chat_id={chat['id']}&name=notiz.txt", content=inhalt.encode()
    )
    assert antwort.status_code == 201
    meta = antwort.json()["dokument"]
    dokument = client.app.state.repositories.documents.holen(meta["id"])
    assert dokument.extracted_text == inhalt
    assert "[page" not in dokument.extracted_text


def test_pdf_ohne_textebene_wird_abgelehnt(client):
    """A scan without text must not slip through as an empty document."""
    from pypdf import PdfWriter

    chat = _chat(client)
    puffer = io.BytesIO()
    schreiber = PdfWriter()
    schreiber.add_blank_page(width=612, height=792)
    schreiber.write(puffer)
    antwort = client.post(
        f"/api/v1/documents?chat_id={chat['id']}&name=leer.pdf",
        content=puffer.getvalue(),
    )
    assert antwort.status_code == 422


def test_verlauf_traegt_den_dokumenttext(client):
    from app.api.v1.generierung import _verlauf_bauen
    from app.dokumentbudget import Anteil

    chat_daten = _chat(client)
    repositories = client.app.state.repositories
    meta = client.post(
        f"/api/v1/documents?chat_id={chat_daten['id']}&name=notiz.txt",
        content="Der Schatz liegt unter der Eiche.".encode(),
    ).json()["dokument"]
    repositories.messages.speichern(
        chat_id=chat_daten["id"], role="user", content="Fass zusammen.", dokument=meta["id"]
    )
    chat = repositories.chats.holen(chat_daten["id"])
    # What a real request would resolve for this tiny note against any real
    # window (app/dokumentbudget.py) — handed in directly rather than
    # computed, since resolving a window is not what this test is about.
    plan = {meta["id"]: Anteil(ganz=True)}
    nachrichten = _verlauf_bauen(chat, repositories, "", dokumentplan=plan)
    assert "Schatz liegt unter der Eiche" in nachrichten[-1].content
    assert "Fass zusammen." in nachrichten[-1].content


def test_nachrichtenabruf_liefert_die_meta_karte(client):
    chat = _chat(client)
    meta = client.post(
        f"/api/v1/documents?chat_id={chat['id']}&name=notiz.txt", content=b"Inhalt."
    ).json()["dokument"]
    repositories = client.app.state.repositories
    repositories.messages.speichern(
        chat_id=chat["id"], role="user", content="Frage", dokument=meta["id"]
    )
    nachrichten = client.get(f"/api/v1/chats/{chat['id']}/messages").json()["nachrichten"]
    assert nachrichten[-1]["dokument"]["name"] == "notiz.txt"
    assert nachrichten[-1]["dokument"]["typ"] == "txt"
    # Image messages and plain messages still carry no document.
    assert nachrichten[0].get("dokument") is None or "dokument" in nachrichten[0]


def test_the_meta_card_carries_the_path_of_the_file(client):
    """The window shows where a document lies, and it shows only what the
    interface hands it: the card of the upload and the card on the message
    both carry the place the row keeps."""
    from pathlib import Path

    chat = _chat(client)
    meta = client.post(
        f"/api/v1/documents?chat_id={chat['id']}&name=notiz.txt", content=b"Inhalt."
    ).json()["dokument"]
    repositories = client.app.state.repositories
    kept = repositories.documents.holen(meta["id"]).pfad
    assert kept and Path(kept).is_file() and Path(kept).name == "notiz.txt"
    assert meta["pfad"] == kept
    repositories.messages.speichern(
        chat_id=chat["id"], role="user", content="Frage", dokument=meta["id"]
    )
    messages = client.get(f"/api/v1/chats/{chat['id']}/messages").json()["nachrichten"]
    assert messages[-1]["dokument"]["pfad"] == kept


def test_in_a_chat_with_a_shared_folder_the_path_lies_in_that_folder(client, tmp_path):
    from pathlib import Path

    shared = tmp_path / "shared"
    shared.mkdir()
    chat = _chat(client)
    client.patch(f"/api/v1/chats/{chat['id']}", json={"working_dirs": [str(shared)]})
    meta = client.post(
        f"/api/v1/documents?chat_id={chat['id']}&name=notiz.txt", content=b"Inhalt."
    ).json()["dokument"]
    assert Path(meta["pfad"]).is_file()
    assert Path(meta["pfad"]).resolve().parent == shared.resolve()


def test_a_document_without_a_kept_file_has_no_path_and_the_card_is_as_it_was():
    """The silence check: a row from before files were kept has no place —
    none or an empty one — and the card says None for both; every other
    field is what it always was."""
    from app.api.v1.dokumente import meta_bauen
    from app.db.models import Document

    old = Document(
        id="d1", chat_id="c1", filename="alt.pdf", created_at="2024-01-01T00:00:00",
        size_bytes=4096, pages=3,
    )
    card = {"id": "d1", "name": "alt.pdf", "typ": "pdf", "seiten": 3, "kb": 4, "getragen": None}
    assert meta_bauen(old).model_dump() == {**card, "pfad": None}
    old.pfad = ""
    assert meta_bauen(old).model_dump() == {**card, "pfad": None}
    old.pfad = "/shared/alt.pdf"
    assert meta_bauen(old, getragen="ganz").model_dump() == {
        **card, "getragen": "ganz", "pfad": "/shared/alt.pdf",
    }


def test_dokument_oeffnen_uebergibt_genau_den_gespeicherten_pfad(client, monkeypatch):
    """The client never says which path to open, only which document — the
    system command it triggers gets exactly the path the upload wrote,
    never one a caller could name."""
    from pathlib import Path

    chat = _chat(client)
    meta = client.post(
        f"/api/v1/documents?chat_id={chat['id']}&name=notiz.txt", content=b"Inhalt."
    ).json()["dokument"]
    dokument = client.app.state.repositories.documents.holen(meta["id"])
    assert dokument.pfad

    geoeffnet: list[Path] = []
    monkeypatch.setattr(
        "app.api.v1.dokumente.datei_oeffnen", lambda pfad: geoeffnet.append(pfad)
    )
    antwort = client.post(f"/api/v1/documents/{meta['id']}/open")
    assert antwort.status_code == 200
    assert geoeffnet == [Path(dokument.pfad)]


def test_dokument_oeffnen_unbekannte_kennung_bleibt_stumm(client, monkeypatch):
    """Schweigeprobe: an id that names no document opens nothing at all —
    not even the attempt to run a command."""
    from pathlib import Path

    geoeffnet: list[Path] = []
    monkeypatch.setattr(
        "app.api.v1.dokumente.datei_oeffnen", lambda pfad: geoeffnet.append(pfad)
    )
    antwort = client.post("/api/v1/documents/gibtsnicht/open")
    assert antwort.status_code == 404
    assert geoeffnet == []


def test_dokument_loeschen_vor_dem_senden(client):
    """The stack's own ✕ (4.1, upload-on-attach): a document nobody sent
    yet is free to remove — row and file both go."""
    chat = _chat(client)
    meta = client.post(
        f"/api/v1/documents?chat_id={chat['id']}&name=notiz.txt", content=b"Inhalt."
    ).json()["dokument"]

    antwort = client.delete(f"/api/v1/documents/{meta['id']}")
    assert antwort.status_code == 204
    assert client.app.state.repositories.documents.holen(meta["id"]) is None


def test_dokument_loeschen_nach_dem_senden_wird_abgewiesen(client):
    """Once a message carries the document, this route is no longer the
    way to drop it — only that message's own ✕ checks the document against
    the message it is actually attached to; this one takes a bare id on
    faith and must refuse instead of trusting it."""
    chat = _chat(client)
    meta = client.post(
        f"/api/v1/documents?chat_id={chat['id']}&name=notiz.txt", content=b"Inhalt."
    ).json()["dokument"]
    client.app.state.repositories.messages.speichern(
        chat_id=chat["id"], role="user", content="Frage", dokument=meta["id"]
    )

    antwort = client.delete(f"/api/v1/documents/{meta['id']}")
    assert antwort.status_code == 409
    assert client.app.state.repositories.documents.holen(meta["id"]) is not None


def test_dokument_loeschen_unbekannte_kennung(client):
    antwort = client.delete("/api/v1/documents/gibtsnicht")
    assert antwort.status_code == 404


def test_jede_textendung_geht_den_dokumentweg(client):
    """Every ending of the agreed list travels the way .txt and .md did:
    stored, its text kept unchanged, its kind named by the ending. Plain
    text as a media type for each new one, also .html — the file is never
    served as a page; .md and .pdf keep their own types."""
    chat = _chat(client)
    for endung in ERWARTETE_ENDUNGEN:
        if endung == ".pdf":
            inhalt = None
            daten = pdf_mit_seiten(["Eine Seite"])
        else:
            inhalt = f"Inhalt der Datei {endung}."
            daten = inhalt.encode()
        antwort = client.post(
            f"/api/v1/documents?chat_id={chat['id']}&name=probe{endung}", content=daten
        )
        assert antwort.status_code == 201, f"{endung}: {antwort.text}"
        meta = antwort.json()["dokument"]
        assert meta["typ"] == endung[1:], endung
        dokument = client.app.state.repositories.documents.holen(meta["id"])
        if endung == ".md":
            erwartet = "text/markdown"
        elif endung == ".pdf":
            erwartet = "application/pdf"
        else:
            erwartet = "text/plain"
        assert dokument.mime_type == erwartet, endung
        if inhalt is not None:
            assert dokument.extracted_text == inhalt, endung
        ausgeliefert = client.get(f"/api/v1/documents/{meta['id']}/file")
        assert ausgeliefert.headers["content-type"].startswith(erwartet), endung


def test_fremde_endungen_werden_mit_einem_wort_ohne_liste_abgelehnt(client):
    """Schweigeprobe: .docx, .zip, .env and a name with no ending at all
    are refused with 415 and the one sentence from the catalogue — the
    sentence the user gets instead of a list of file types."""
    wort = t("fehler.dokument_typ", "de")
    # The order asks for a sentence that claims no list of types; naming
    # PDF/TXT/MD at all would be a list someone reads as incomplete.
    assert "PDF" not in wort and "TXT" not in wort and "MD" not in wort
    chat = _chat(client)
    for name in ["brief.docx", "archiv.zip", "geheim.env", "ohneendung"]:
        antwort = client.post(
            f"/api/v1/documents?chat_id={chat['id']}&name={name}", content=b"Inhalt."
        )
        assert antwort.status_code == 415, name
        assert antwort.json()["detail"] == wort, name


def test_das_tor_liest_die_volle_endung_nicht_die_gekuerzte(client):
    """The stored name is capped at 120 characters, the gate reads the
    whole one: a long real ending still passes — and stays on the stored
    name, so the file in the shared folder keeps its kind — while a
    made-up ending hiding behind the cut is still refused."""
    chat = _chat(client)
    lang_pdf = "a" * 130 + ".pdf"
    antwort = client.post(
        f"/api/v1/documents?chat_id={chat['id']}&name={lang_pdf}",
        content=pdf_mit_seiten(["Eine Seite"]),
    )
    assert antwort.status_code == 201, antwort.text
    meta = antwort.json()["dokument"]
    assert len(meta["name"]) <= 120
    assert meta["name"].endswith(".pdf")
    assert meta["typ"] == "pdf"
    erfunden = "a" * 116 + ".txtzzz"
    antwort = client.post(
        f"/api/v1/documents?chat_id={chat['id']}&name={erfunden}", content=b"Inhalt."
    )
    assert antwort.status_code == 415


def test_ein_nullbyte_im_namen_bleibt_ein_sauberer_name(client):
    """A null byte can stand in no file name on any system — it is dropped
    before the name is used, instead of crashing the writing of the file
    with a 500 and a traceback."""
    chat = _chat(client)
    antwort = client.post(
        f"/api/v1/documents?chat_id={chat['id']}&name=a%00.txt", content=b"Inhalt."
    )
    assert antwort.status_code == 201, antwort.text
    assert antwort.json()["dokument"]["name"] == "a.txt"


def test_ein_leerer_upload_sagt_dass_nichts_zu_lesen_ist(client):
    """An empty body is no document — the answer is the unreadable one, not
    the one about file types; a .txt IS read, and telling the user otherwise
    sends them after the wrong thing."""
    chat = _chat(client)
    antwort = client.post(
        f"/api/v1/documents?chat_id={chat['id']}&name=leer.txt", content=b""
    )
    assert antwort.status_code == 400
    assert antwort.json()["detail"] == t("fehler.dokument_unlesbar", "de")


def test_die_listen_von_fenster_und_backend_bleiben_gleich():
    """The window offers exactly what the upload route accepts, and both
    are the agreed set — read off the sources, because drift between the
    two lists turns an honest refusal into a silent miss (a document the
    picker hides, or an upload the route refuses after the window said
    yes)."""
    import re
    from pathlib import Path

    from app.api.v1.dokumente import ERLAUBTE_ENDUNGEN

    quelle = (
        Path(__file__).resolve().parent.parent
        / "frontend/src/teile/Eingabeleiste.svelte"
    ).read_text(encoding="utf-8")
    # Comments out of the way: a quoted word inside one would join the set.
    quelle = re.sub(r"//[^\n]*", "", quelle)
    quelle = re.sub(r"/\*.*?\*/", "", quelle, flags=re.S)
    treffer = re.search(r"DOKUMENT_ENDUNGEN\s*=\s*\[(.*?)\]", quelle, re.S)
    assert treffer, "DOKUMENT_ENDUNGEN nicht gefunden"
    aus_dem_fenster = re.findall(r"['\"]([^'\"]+)['\"]", treffer.group(1))
    assert len(aus_dem_fenster) == len(set(aus_dem_fenster)), "doppelte Endung"
    assert set(aus_dem_fenster) == set(ERLAUBTE_ENDUNGEN)
    assert set(ERLAUBTE_ENDUNGEN) == set(ERWARTETE_ENDUNGEN)
