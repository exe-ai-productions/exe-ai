"""A picture `read_file` read, on its way to the model — chat and job.

The chat can see a picture because the user attached it; an agent could not
see one at all. ``read_file`` on an image closes that: the picture travels the
way an attachment travels, as a user turn with an image part, placed after the
results of the round that read it. A model without eyes gets a plain sentence
instead, and never a picture it cannot look at.

Both runs are driven here, because both build their own message list
(app/api/v1/generierung.py, app/api/v1/auftraege.py) and only the module in
between is shared.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import verlaufsbau, werkzeugbild
from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Werkzeugaufruf
from app.tools.registry import WerkzeugRegistry
from tests.conftest import pdf_mit_seiten, png_bytes, provider_setzen


# --- The message itself ----------------------------------------------------


def test_ohne_bild_kein_zug():
    assert werkzeugbild.nachricht([], []) is None


def test_mit_bild_ein_benutzerzug():
    nachricht = werkzeugbild.nachricht(["foto.png"], ["data:image/png;base64,AA"])
    assert nachricht is not None
    # A user turn: an image part is valid on no other role.
    assert nachricht.role == "user"
    assert nachricht.bild_urls == ["data:image/png;base64,AA"]
    assert "foto.png" in nachricht.content


# --- Recognising such a result again --------------------------------------


class _Zeile:
    """A stored answer with a tool log, as the history readers ask for one."""

    role = "assistant"
    art = "nachricht"
    id = "0123456789abcdef"

    def __init__(self, eintraege) -> None:
        self.stats = {"werkzeuge": eintraege}


def _bildeintrag():
    return {
        "name": "read_file",
        "argumente": {"path": "bilder/foto.png"},
        "ergebnis": werkzeugbild.bildsatz("/geteilt/bilder/foto.png", 4711),
    }


def test_nur_die_eigene_form_gilt_als_bildanhang():
    """Told apart by its whole shape, not by the sentence alone.

    A result that merely QUOTES the sentence is somebody's real output — a
    `shell` grep over this source tree, a read of an exported transcript —
    and replacing it would throw the answer away and claim an image the
    call never read.
    """
    echt = werkzeugbild.bildsatz("/geteilt/foto.png", 1234)
    assert werkzeugbild.gelesener_bildpfad("read_file", echt) == "/geteilt/foto.png"
    # Someone else's output that contains the sentence.
    assert (
        werkzeugbild.gelesener_bildpfad(
            "shell", f"app/werkzeugbild.py:30: {werkzeugbild.ANHANG_SATZ}"
        )
        is None
    )
    assert (
        werkzeugbild.gelesener_bildpfad(
            "read_file", f"grep hit: {werkzeugbild.ANHANG_SATZ}"
        )
        is None
    )
    # And the reading tool's other answers about a picture.
    assert (
        werkzeugbild.gelesener_bildpfad(
            "read_file",
            "'/geteilt/foto.png' is an image, and this model cannot be shown images.",
        )
        is None
    )
    assert werkzeugbild.gelesener_bildpfad("read_file", None) is None


def test_der_hinweis_nennt_die_datei_aus_dem_ergebnis():
    """The path comes out of the RESULT, not out of the call's arguments.

    The argument may be relative and resolves against the chat's first
    shared folder — reorder those and the same name is a different file. The
    result carries the file as it was actually resolved, and a call whose
    arguments were never stored still gets a path.
    """
    eintrag = {
        "name": "read_file",
        # What the model typed, and what that resolved to — told apart on
        # purpose: the argument alone would send a later turn somewhere else.
        "argumente": {"path": "kurz.png"},
        "ergebnis": werkzeugbild.bildsatz("/geteilt/bilder/aufgeloest.png", 4711),
    }
    ohne_argumente = {"name": "read_file", "ergebnis": eintrag["ergebnis"]}
    for eintraege in ([eintrag], [ohne_argumente]):
        text = verlaufsbau.werkzeuge_fuer_die_faltung(_Zeile(eintraege), "Gesehen.")
        assert werkzeugbild.NICHT_MEHR_DABEI in text
        hinweis = text[text.index(werkzeugbild.NICHT_MEHR_DABEI) :]
        assert "/geteilt/bilder/aufgeloest.png" in hinweis
        assert "kurz.png" not in hinweis


def test_auch_ohne_werkzeuge_und_in_der_faltbitte_steht_der_hinweis():
    """The three readers of the STORED tool log say the same thing.

    The turns are only one of them: a request that offers no tools writes
    the log as a text block, and a compaction request built from the rows
    writes its own. Both used to carry "is attached below" — the second one
    into a summary that outlives the rows it replaced. (A fold inside a
    running answer reads the request's own messages instead, not these rows;
    that reader is somewhere else.)
    """
    zeile = _Zeile([_bildeintrag()])

    ohne_werkzeuge = verlaufsbau._werkzeuge_als_text(zeile, "Gesehen.")
    faltbitte_text = verlaufsbau.werkzeuge_fuer_die_faltung(zeile, "Gesehen.")

    for text in (ohne_werkzeuge, faltbitte_text):
        assert werkzeugbild.ANHANG_SATZ not in text
        assert werkzeugbild.NICHT_MEHR_DABEI in text
        assert "bilder/foto.png" in text


def test_das_gewicht_zaehlt_was_wirklich_gesendet_wird():
    """The fold is decided on this number, so it counts the note, not the
    stored sentence it replaces."""
    zeile = _Zeile([_bildeintrag()])
    gesendet = verlaufsbau._werkzeugzuege(zeile, "Gesehen.")
    ergebnis = next(n for n in gesendet if n.role == "tool")

    assert verlaufsbau.werkzeuggewicht(zeile) >= len(ergebnis.content)


# --- Through the chat ------------------------------------------------------


def _werkzeuge_mit_datenordner(client) -> WerkzeugRegistry:
    """The stub registry for these tests — WITH the run's own data folder
    attached: the read tool keeps the model's picture copies under it,
    and without one it falls back to the installed folder, so
    the tests would write into the project's own data directory."""
    from app.tools import create_folder

    return WerkzeugRegistry(
        [],
        shell_an=True,
        folder_share=create_folder.ChatFolderShare(
            client.app.state.repositories, client.app.state.config.datenverzeichnis
        ),
    )


def _echte_werkzeuge(client, ordner, *, bildsicht: bool):
    client.app.state.werkzeuge = _werkzeuge_mit_datenordner(client)
    client.app.state.config.features.mcp = True
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.endpunkt.capabilities.tool_calls = True
    zustand.endpunkt.capabilities.vision = bildsicht
    return ordner


def _chat_mit_ordner(client, ordner):
    chat = client.post("/api/v1/chats", json={"title": "Lesen"}).json()
    client.patch(f"/api/v1/chats/{chat['id']}", json={"working_dirs": [str(ordner)]})
    return chat["id"]


def _lauf(client, chat_id, werkzeug_argumente):
    provider = provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["Gesehen."],
            werkzeugaufrufe=[
                Werkzeugaufruf(id="a1", name="read_file", argumente=werkzeug_argumente)
            ],
        ),
    )
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Sieh nach."},
    )
    return provider


def test_chat_bekommt_das_bild_als_bild(client, tmp_path):
    _echte_werkzeuge(client, tmp_path, bildsicht=True)
    (tmp_path / "foto.png").write_bytes(png_bytes())
    chat_id = _chat_mit_ordner(client, tmp_path)

    provider = _lauf(client, chat_id, {"path": "foto.png"})

    # The second request is the one that carries the round's results.
    zweite = provider.alle_anfragen[1].nachrichten
    mit_bild = [n for n in zweite if n.alle_bild_urls()]
    assert len(mit_bild) == 1
    assert mit_bild[0].role == "user"
    assert mit_bild[0].alle_bild_urls()[0].startswith("data:image/png;base64,")
    # And it stands AFTER the tool result, not between call and result.
    assert zweite.index(mit_bild[0]) > max(
        i for i, n in enumerate(zweite) if n.role == "tool"
    )


def _zweite_frage(client, chat_id):
    """A turn after the one that read the picture — the history is rebuilt
    from the stored rows here, which is where the round's picture is gone."""
    provider = provider_setzen(
        client, MockProvider(mock_endpunkt("test"), haeppchen=["Gut."])
    )
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Und nun?"},
    )
    return provider


def test_die_naechste_antwort_sagt_wo_das_bild_liegt(client, tmp_path):
    """The sentence the result carried was true for one round only.

    The picture rides on a message of its own round and a rebuilt history
    carries the stored text alone — so from the second answer on, "is
    attached below" pointed the model at nothing. It now reads the note the
    house gives for every picture that is no longer in the request: where the
    file is and which tool reads it back.
    """
    _echte_werkzeuge(client, tmp_path, bildsicht=True)
    (tmp_path / "foto.png").write_bytes(png_bytes())
    chat_id = _chat_mit_ordner(client, tmp_path)

    erster = _lauf(client, chat_id, {"path": "foto.png"})
    # The round that read it says it is attached — that half must stay true,
    # and it is what the next request recognises the result by.
    ergebnis_damals = next(
        n for n in erster.alle_anfragen[1].nachrichten if n.role == "tool"
    )
    assert werkzeugbild.ANHANG_SATZ in ergebnis_damals.content

    zweiter = _zweite_frage(client, chat_id)
    verlauf = zweiter.alle_anfragen[0].nachrichten
    ergebnis = next(n for n in verlauf if n.role == "tool")
    assert werkzeugbild.ANHANG_SATZ not in ergebnis.content
    assert werkzeugbild.NICHT_MEHR_DABEI in ergebnis.content
    # The path the model passed itself, and the tool that reads it again.
    assert "foto.png" in ergebnis.content
    assert "read_file" in ergebnis.content
    # And nothing smuggles the picture back in: it is not in this request.
    assert not any(n.alle_bild_urls() for n in verlauf)


def test_ein_abgelehntes_bild_behaelt_seinen_satz(client, tmp_path):
    """The silent half: a read that carried no picture keeps its own words.

    A model without eyes is told so, and that sentence is the honest answer
    in every later round too — replaced by a note about a picture that never
    travelled, the model would be sent to read a file it cannot look at.
    """
    _echte_werkzeuge(client, tmp_path, bildsicht=False)
    (tmp_path / "foto.png").write_bytes(png_bytes())
    chat_id = _chat_mit_ordner(client, tmp_path)

    _lauf(client, chat_id, {"path": "foto.png"})
    zweiter = _zweite_frage(client, chat_id)

    ergebnis = next(
        n for n in zweiter.alle_anfragen[0].nachrichten if n.role == "tool"
    )
    assert "cannot be shown images" in ergebnis.content
    assert werkzeugbild.NICHT_MEHR_DABEI not in ergebnis.content


def test_chat_ohne_bildsicht_bekommt_einen_satz(client, tmp_path):
    _echte_werkzeuge(client, tmp_path, bildsicht=False)
    (tmp_path / "foto.png").write_bytes(png_bytes())
    chat_id = _chat_mit_ordner(client, tmp_path)

    provider = _lauf(client, chat_id, {"path": "foto.png"})

    zweite = provider.alle_anfragen[1].nachrichten
    assert not any(n.alle_bild_urls() for n in zweite)
    ergebnis = next(n for n in zweite if n.role == "tool")
    assert "cannot be shown images" in ergebnis.content


def test_gelesenes_bild_zaehlt_beim_fuellstand_mit(client, tmp_path, monkeypatch):
    """A picture weighs what every other picture weighs. Counted by its
    sentence alone, a round that read three screenshots would look like a
    hundred characters of growth and the fold would never fire."""
    from app import kontextdruck

    _echte_werkzeuge(client, tmp_path, bildsicht=True)
    (tmp_path / "foto.png").write_bytes(png_bytes())
    chat_id = _chat_mit_ordner(client, tmp_path)

    gesehen: list[int] = []
    echt = kontextdruck.ueber_der_schwelle

    def mitschreiben(letzter_stand, neu_tokens, fenster, *rest):
        gesehen.append(neu_tokens)
        return echt(letzter_stand, neu_tokens, fenster, *rest)

    # The round-end trigger asks this one question (app/kontextdruck.py);
    # what it is handed as "new since the last reading" is what this test is
    # about.
    monkeypatch.setattr(kontextdruck, "ueber_der_schwelle", mitschreiben)
    _lauf(client, chat_id, {"path": "foto.png"})

    assert gesehen, "the round-end reading never ran"
    assert max(gesehen) >= kontextdruck.bild_tokens(1)


def test_chat_liest_eine_seite_aus_dem_pdf(client, tmp_path):
    """The other half of the same tool: a document too large to travel is
    read a page at a time — that is what keeping the file is for."""
    _echte_werkzeuge(client, tmp_path, bildsicht=False)
    (tmp_path / "bericht.pdf").write_bytes(
        pdf_mit_seiten(["Page one alpha", "Page two beta", "Page three gamma"])
    )
    chat_id = _chat_mit_ordner(client, tmp_path)

    provider = _lauf(client, chat_id, {"path": "bericht.pdf", "page": 2})

    ergebnis = next(n for n in provider.alle_anfragen[1].nachrichten if n.role == "tool")
    assert "page 2 of 3" in ergebnis.content
    assert "Page two beta" in ergebnis.content
    assert "Page one alpha" not in ergebnis.content


# --- Through a job ---------------------------------------------------------


@pytest.fixture()
def auftrags_client(config):
    from fastapi.testclient import TestClient

    from app.main import app_erstellen

    config.features.mcp = True
    config.mcp.servers_file = str(Path(config.app.data_dir) / "keine_server.json")
    with TestClient(app_erstellen(config)) as testclient:
        testclient.headers["X-Sitzungsschluessel"] = testclient.app.state.sitzungsschluessel
        testclient.app.state.werkzeuge = _werkzeuge_mit_datenordner(testclient)
        zustand = testclient.app.state.discovery.zustaende["test"]
        zustand.endpunkt.capabilities.tool_calls = True
        yield testclient


def _agent_schreiben(config, ordner, werkzeug="read_file"):
    verzeichnis = Path(config.agentenverzeichnisse[0])
    verzeichnis.mkdir(parents=True, exist_ok=True)
    (verzeichnis / "leser.md").write_text(
        f"---\nmodel: test\ntools:\n  - {werkzeug}\nfolders:\n  - {ordner}\n---\nLies nach.\n",
        encoding="utf-8",
    )


def _auftrag_laufen_lassen(client, argumente):
    provider = provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["Gesehen."],
            werkzeugaufrufe=[
                Werkzeugaufruf(id="a1", name="read_file", argumente=argumente)
            ],
        ),
    )
    kennung = client.post(
        "/api/v1/jobs", json={"agent": "leser", "task": "Lies", "endpoint_id": "test"}
    ).json()["id"]
    for _ in range(400):
        daten = client.get(f"/api/v1/jobs/{kennung}").json()
        if daten["state"] in ("fertig", "abgebrochen", "gescheitert"):
            break
        import time

        time.sleep(0.02)
    return provider, daten


def test_auftrag_bekommt_das_bild_als_bild(auftrags_client, config, tmp_path):
    geteilt = tmp_path / "geteilt"
    geteilt.mkdir()
    (geteilt / "foto.png").write_bytes(png_bytes())
    _agent_schreiben(config, geteilt)
    auftrags_client.app.state.discovery.zustaende["test"].endpunkt.capabilities.vision = True

    provider, _ = _auftrag_laufen_lassen(auftrags_client, {"path": "foto.png"})

    zweite = provider.alle_anfragen[1].nachrichten
    mit_bild = [n for n in zweite if n.alle_bild_urls()]
    assert len(mit_bild) == 1
    assert mit_bild[0].role == "user"
    assert zweite.index(mit_bild[0]) > max(
        i for i, n in enumerate(zweite) if n.role == "tool"
    )


def test_auftrag_ohne_bildsicht_bekommt_einen_satz(auftrags_client, config, tmp_path):
    geteilt = tmp_path / "geteilt"
    geteilt.mkdir()
    (geteilt / "foto.png").write_bytes(png_bytes())
    _agent_schreiben(config, geteilt)
    auftrags_client.app.state.discovery.zustaende["test"].endpunkt.capabilities.vision = False

    provider, _ = _auftrag_laufen_lassen(auftrags_client, {"path": "foto.png"})

    zweite = provider.alle_anfragen[1].nachrichten
    assert not any(n.alle_bild_urls() for n in zweite)
    ergebnis = next(n for n in zweite if n.role == "tool")
    assert "cannot be shown images" in ergebnis.content


def test_auftrag_liest_eine_seite_aus_dem_pdf(auftrags_client, config, tmp_path):
    geteilt = tmp_path / "geteilt"
    geteilt.mkdir()
    (geteilt / "bericht.pdf").write_bytes(
        pdf_mit_seiten(["Page one alpha", "Page two beta", "Page three gamma"])
    )
    _agent_schreiben(config, geteilt)

    provider, _ = _auftrag_laufen_lassen(
        auftrags_client, {"path": "bericht.pdf", "page": 3}
    )

    ergebnis = next(n for n in provider.alle_anfragen[1].nachrichten if n.role == "tool")
    assert "page 3 of 3" in ergebnis.content
    assert "Page three gamma" in ergebnis.content
