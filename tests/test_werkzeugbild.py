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

from app import verlaufsbau, werkzeugbild, werkzeugkuerzung
from app.providers import MockProvider, ProviderFehler, mock_endpunkt
from app.providers.base import Stueck, Werkzeugaufruf
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


def test_the_next_answer_carries_the_picture_again(client, tmp_path):
    """A picture a tool read does not vanish with its round.

    The history is rebuilt from the stored rows for the next answer; the
    newest few tool pictures go out again there, in the shape their own round
    had: the result with the sentence it returned, and the picture on a user
    turn behind the round's results.
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
    assert werkzeugbild.ANHANG_SATZ in ergebnis.content
    assert werkzeugbild.NICHT_MEHR_DABEI not in ergebnis.content
    mit_bild = [n for n in verlauf if n.alle_bild_urls()]
    assert len(mit_bild) == 1
    assert mit_bild[0].role == "user"
    assert mit_bild[0].alle_bild_urls()[0].startswith("data:image/png;base64,")
    assert "foto.png" in mit_bild[0].content
    # Behind the results, never between call and result.
    assert verlauf.index(mit_bild[0]) > verlauf.index(ergebnis)
    # The same bytes the round itself sent.
    damals = next(n for n in erster.alle_anfragen[1].nachrichten if n.alle_bild_urls())
    assert mit_bild[0].alle_bild_urls() == damals.alle_bild_urls()


def _five_pictures_read(client, tmp_path):
    _echte_werkzeuge(client, tmp_path, bildsicht=True)
    chat_id = _chat_mit_ordner(client, tmp_path)
    for nummer in range(5):
        (tmp_path / f"foto{nummer}.png").write_bytes(png_bytes())
        _lauf(client, chat_id, {"path": f"foto{nummer}.png"})
    return chat_id


@pytest.fixture
def small_limits(monkeypatch):
    """The way a retired picture is told and rebuilt, shown with five
    pictures: three stay and the older ones go one at a time. The real
    numbers have their own tests (tests/test_werkzeugkuerzung.py)."""
    monkeypatch.setattr(werkzeugkuerzung, "OUTBOUND_IMAGE_LIMIT", 3)
    monkeypatch.setattr(werkzeugkuerzung, "IMAGE_EVICTION_BATCH", 1)


@pytest.mark.usefixtures("small_limits")
def test_only_the_three_newest_pictures_of_the_chat_ride_again(client, tmp_path):
    """Five answers each read one picture: the next request carries the
    newest three and says where the two older ones lie."""
    chat_id = _five_pictures_read(client, tmp_path)

    zweiter = _zweite_frage(client, chat_id)
    verlauf = zweiter.alle_anfragen[0].nachrichten

    mit_bild = [n for n in verlauf if n.alle_bild_urls()]
    assert len(mit_bild) == 3
    assert [Path(n.werkzeugbilder[0]).name for n in mit_bild] == [
        "foto2.png",
        "foto3.png",
        "foto4.png",
    ]
    ergebnisse = [n.content for n in verlauf if n.role == "tool"]
    assert [werkzeugbild.NICHT_MEHR_DABEI in text for text in ergebnisse] == [
        True, True, False, False, False,
    ]
    assert [werkzeugbild.ANHANG_SATZ in text for text in ergebnisse] == [
        False, False, True, True, True,
    ]
    # The shape the run gave a retired picture: the bare sentence on the
    # result, and the note with the path on a turn of its own behind it.
    assert ergebnisse[:2] == [werkzeugbild.NICHT_MEHR_DABEI] * 2
    notes = [
        n
        for n in verlauf
        if n.role == "user" and werkzeugkuerzung.BILD_ENTFERNT in n.content
    ]
    assert len(notes) == 2
    assert not any(n.alle_bild_urls() for n in notes)
    for nummer in (0, 1):
        assert f"foto{nummer}.png" in notes[nummer].content
    # What the rows remember: the files, oldest first.
    messages = client.app.state.repositories.messages
    all_values = messages.tool_entry_values(
        chat_id=chat_id, key=werkzeugbild.READ_IMAGE_PATH, newest=10
    )
    assert [Path(pfad).name for pfad in all_values] == [f"foto{n}.png" for n in range(5)]
    newest_values = messages.tool_entry_values(
        chat_id=chat_id, key=werkzeugbild.READ_IMAGE_PATH, newest=3
    )
    assert [Path(pfad).name for pfad in newest_values] == ["foto2.png", "foto3.png", "foto4.png"]


def test_the_next_message_takes_the_same_pictures_out_as_the_run_did(client, tmp_path):
    """The real numbers: twenty-one answers each read one picture. The run
    of the last one sends the newest thirteen and takes the oldest eight out
    at once; the next message, rebuilt from the stored rows, carries the same
    thirteen and the same eight notes — so it starts with the bytes the run's
    request ended with, and the server reads it from its cache."""
    _echte_werkzeuge(client, tmp_path, bildsicht=True)
    chat_id = _chat_mit_ordner(client, tmp_path)
    reads = werkzeugkuerzung.OUTBOUND_IMAGE_LIMIT + 1
    last = None
    for nummer in range(reads):
        (tmp_path / f"foto{nummer}.png").write_bytes(png_bytes())
        last = _lauf(client, chat_id, {"path": f"foto{nummer}.png"})
    run_request = last.alle_anfragen[1].nachrichten

    history = _zweite_frage(client, chat_id).alle_anfragen[0].nachrichten

    def _told(verlauf):
        pictures = [n for n in verlauf if n.alle_bild_urls()]
        notes = [
            n for n in verlauf
            if n.role == "user" and werkzeugkuerzung.BILD_ENTFERNT in n.content
        ]
        return len(pictures), len(notes)

    leaving = werkzeugkuerzung.IMAGE_EVICTION_BATCH
    assert _told(run_request) == (reads - leaving, leaving)
    assert _told(history) == _told(run_request)


def test_silence_up_to_the_limit_no_picture_leaves_the_next_message(client, tmp_path):
    """Twenty answers each read one picture: all twenty ride again."""
    _echte_werkzeuge(client, tmp_path, bildsicht=True)
    chat_id = _chat_mit_ordner(client, tmp_path)
    reads = werkzeugkuerzung.OUTBOUND_IMAGE_LIMIT
    for nummer in range(reads):
        (tmp_path / f"foto{nummer}.png").write_bytes(png_bytes())
        _lauf(client, chat_id, {"path": f"foto{nummer}.png"})

    history = _zweite_frage(client, chat_id).alle_anfragen[0].nachrichten

    assert len([n for n in history if n.alle_bild_urls()]) == reads
    assert not any(werkzeugkuerzung.BILD_ENTFERNT in n.content for n in history)


def _wie_gesendet(nachricht):
    """What the model is told by one message: role, words, pictures, and the
    calls with their ids — the parts a server reads its cache by."""
    return (
        nachricht.role,
        nachricht.content,
        tuple(nachricht.alle_bild_urls()),
        nachricht.werkzeugaufruf_id,
        tuple((a.id, a.name, str(a.argumente)) for a in nachricht.werkzeugaufrufe or ()),
    )


def _lauf_mit_bildern(client, chat_id, namen):
    """One answer whose first round reads every file in ``namen`` at once."""
    return provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["Gesehen."],
            werkzeugaufrufe=[
                Werkzeugaufruf(id=f"a{n}", name="read_file", argumente={"path": name})
                for n, name in enumerate(namen)
            ],
        ),
    )


def _frage_stellen(client, chat_id, provider):
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Sieh nach."},
    )
    return provider


@pytest.mark.usefixtures("small_limits")
def test_the_history_after_a_retired_picture_begins_with_what_the_run_sent(client, tmp_path):
    """Four answers each read one picture; the fourth retires the first from
    its own request. The next message rebuilds the history from the rows, and
    its first messages are those the run sent after the retirement, one for
    one — the result with the bare sentence, the turn with the note — so the
    model server reads the rest from its cache."""
    _echte_werkzeuge(client, tmp_path, bildsicht=True)
    chat_id = _chat_mit_ordner(client, tmp_path)
    for nummer in range(4):
        (tmp_path / f"foto{nummer}.png").write_bytes(png_bytes())
        letzter = _lauf(client, chat_id, {"path": f"foto{nummer}.png"})
    gesendet = letzter.alle_anfragen[1].nachrichten

    zweiter = _zweite_frage(client, chat_id)
    verlauf = zweiter.alle_anfragen[0].nachrichten

    assert len(verlauf) > len(gesendet) - 1
    assert [_wie_gesendet(n) for n in verlauf[: len(gesendet)]] == [
        _wie_gesendet(n) for n in gesendet
    ]
    # And what stands at the retired picture is the run's own form.
    ersatz = [n for n in gesendet if werkzeugkuerzung.BILD_ENTFERNT in n.content]
    assert len(ersatz) == 1 and "foto0.png" in ersatz[0].content


@pytest.mark.usefixtures("small_limits")
def test_a_round_that_retired_only_some_of_its_pictures_keeps_the_turn_of_the_rest(
    client, tmp_path
):
    """The first answer reads two pictures in one round, two more answers one
    each: only the first picture of that round goes out of the request. The
    round's turn is rewritten with the remaining picture, the way the run
    wrote it, and the history built afterwards says the same."""
    _echte_werkzeuge(client, tmp_path, bildsicht=True)
    chat_id = _chat_mit_ordner(client, tmp_path)
    for nummer in range(4):
        (tmp_path / f"foto{nummer}.png").write_bytes(png_bytes())
    _frage_stellen(client, chat_id, _lauf_mit_bildern(client, chat_id, ["foto0.png", "foto1.png"]))
    _lauf(client, chat_id, {"path": "foto2.png"})
    letzter = _lauf(client, chat_id, {"path": "foto3.png"})
    gesendet = letzter.alle_anfragen[1].nachrichten

    zweiter = _zweite_frage(client, chat_id)
    verlauf = zweiter.alle_anfragen[0].nachrichten

    assert [_wie_gesendet(n) for n in verlauf[: len(gesendet)]] == [
        _wie_gesendet(n) for n in gesendet
    ]
    teil = next(n for n in verlauf if werkzeugkuerzung.BILD_ENTFERNT in n.content)
    assert len(teil.alle_bild_urls()) == 1
    assert "foto0.png" in teil.content
    assert werkzeugbild.EINLEITUNG.format(namen="foto1.png") in teil.content
    ergebnisse = [n.content for n in verlauf if n.role == "tool"]
    assert ergebnisse[0] == werkzeugbild.NICHT_MEHR_DABEI
    assert werkzeugbild.ANHANG_SATZ in ergebnisse[1]


def test_the_weight_counts_the_turn_of_a_retired_picture(tmp_path):
    """The fold is judged on what the rebuilt history sends: for a picture
    that went out of the request, the bare sentence on the result and, on a
    turn of its own, the sentence of the retirement with the note."""
    eintrag = _bildeintrag()
    eintrag[werkzeugbild.READ_IMAGE_PATH] = "/geteilt/bilder/foto.png"
    zeile = _Zeile([eintrag])

    ohne_bilder = verlaufsbau.werkzeuggewicht(zeile)
    mit_bildern = verlaufsbau.werkzeuggewicht(zeile, True, set())

    assert mit_bildern - ohne_bilder == len(werkzeugkuerzung.BILD_ENTFERNT)
    # A picture of the newest few rides along: no retirement is counted.
    reitet = verlaufsbau.werkzeuggewicht(zeile, True, {id(eintrag)})
    assert reitet != mit_bildern


class _LiestDannScheitert(MockProvider):
    """The first call reads a picture, the call behind its result fails, the
    ones after that answer — and every request is kept as the model's server
    reads it: role, words, pictures, calls and their ids."""

    def __init__(self, *args, pfad, **kwargs):
        super().__init__(*args, **kwargs)
        self.pfad = pfad
        self.aufrufe_gezaehlt = 0
        self.anfragen_gesehen = []

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.anfragen_gesehen.append(
            [_wie_gesendet(n) for n in anfrage.nachrichten if n.role != "system"]
        )
        self.aufrufe_gezaehlt += 1
        if self.aufrufe_gezaehlt == 1:
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(id="a1", name="read_file", argumente={"path": self.pfad})
                ],
            )
            return
        if self.aufrufe_gezaehlt == 2:
            raise ProviderFehler("the server went away")
        yield Stueck("content", text="Gesehen.")


def _gescheitert_und_wiederholt(client, chat_id, pfad):
    """A question whose answer reads ``pfad`` and fails in the next call, then
    the arrow: the provider, which has kept the failed call's request and the
    repeated one."""
    provider = provider_setzen(client, _LiestDannScheitert(mock_endpunkt("test"), pfad=pfad))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Sieh nach."},
    )
    zeilen = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"]
    gescheitert = [z for z in zeilen if z["role"] == "assistant"][-1]
    assert gescheitert["zustand"] == "fehler"
    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "retries": gescheitert["id"]},
    )
    assert antwort.status_code == 200
    assert len(provider.anfragen_gesehen) == 3
    return provider


def test_the_repeated_call_carries_the_picture_the_failed_call_carried(client, tmp_path):
    """The answer read a picture and failed in the call behind its result.
    The arrow asks that call again: the request holds the same messages the
    failed call held, the picture as a picture — not the note with its path
    that a request without the answer's pictures wrote."""
    _echte_werkzeuge(client, tmp_path, bildsicht=True)
    (tmp_path / "foto.png").write_bytes(png_bytes())
    chat_id = _chat_mit_ordner(client, tmp_path)

    provider = _gescheitert_und_wiederholt(client, chat_id, "foto.png")

    gescheitert, wiederholt = provider.anfragen_gesehen[1], provider.anfragen_gesehen[2]
    assert any(bilder for _, _, bilder, _, _ in gescheitert)
    assert wiederholt == gescheitert


@pytest.mark.usefixtures("small_limits")
def test_the_pictures_of_the_failed_answer_count_with_those_before_it(client, tmp_path):
    """Three pictures were read in earlier answers, the failed answer reads a
    fourth: the run retired the first from its own request, and the repeated
    call retires it the same way — one rule over the rows and the answer."""
    _echte_werkzeuge(client, tmp_path, bildsicht=True)
    chat_id = _chat_mit_ordner(client, tmp_path)
    for nummer in range(3):
        (tmp_path / f"foto{nummer}.png").write_bytes(png_bytes())
        _lauf(client, chat_id, {"path": f"foto{nummer}.png"})
    (tmp_path / "foto3.png").write_bytes(png_bytes())

    provider = _gescheitert_und_wiederholt(client, chat_id, "foto3.png")

    gescheitert, wiederholt = provider.anfragen_gesehen[1], provider.anfragen_gesehen[2]
    assert wiederholt == gescheitert
    # Three pictures ride, the first one stands as the run's own sentence.
    assert sum(len(bilder) for _, _, bilder, _, _ in wiederholt) == 3
    assert any(
        werkzeugkuerzung.BILD_ENTFERNT in inhalt and "foto0.png" in inhalt
        for _, inhalt, _, _, _ in wiederholt
    )


def test_silence_a_model_without_vision_asks_the_failed_answer_again_with_the_note(
    client, tmp_path
):
    """A model that cannot see never carried the picture: the repeated call
    keeps the note with the path in the result, as before."""
    _echte_werkzeuge(client, tmp_path, bildsicht=False)
    (tmp_path / "foto.png").write_bytes(png_bytes())
    chat_id = _chat_mit_ordner(client, tmp_path)

    provider = _gescheitert_und_wiederholt(client, chat_id, "foto.png")

    wiederholt = provider.anfragen_gesehen[2]
    assert not any(bilder for _, _, bilder, _, _ in wiederholt)
    assert provider.anfragen_gesehen[1][-1][0] == "tool"
    assert wiederholt == provider.anfragen_gesehen[1]


def test_silence_a_model_without_vision_gets_no_old_picture_again(client, tmp_path):
    _echte_werkzeuge(client, tmp_path, bildsicht=True)
    (tmp_path / "foto.png").write_bytes(png_bytes())
    chat_id = _chat_mit_ordner(client, tmp_path)
    _lauf(client, chat_id, {"path": "foto.png"})
    # The model at the wheel now cannot see.
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.vision = False

    zweiter = _zweite_frage(client, chat_id)
    verlauf = zweiter.alle_anfragen[0].nachrichten

    assert not any(n.alle_bild_urls() for n in verlauf)
    ergebnis = next(n for n in verlauf if n.role == "tool")
    assert werkzeugbild.NICHT_MEHR_DABEI in ergebnis.content


def test_a_picture_that_is_gone_stays_a_note_with_its_path(client, tmp_path):
    _echte_werkzeuge(client, tmp_path, bildsicht=True)
    (tmp_path / "foto.png").write_bytes(png_bytes())
    chat_id = _chat_mit_ordner(client, tmp_path)
    _lauf(client, chat_id, {"path": "foto.png"})
    (tmp_path / "foto.png").unlink()

    zweiter = _zweite_frage(client, chat_id)
    verlauf = zweiter.alle_anfragen[0].nachrichten

    assert not any(n.alle_bild_urls() for n in verlauf)
    ergebnis = next(n for n in verlauf if n.role == "tool")
    assert werkzeugbild.NICHT_MEHR_DABEI in ergebnis.content
    assert "foto.png" in ergebnis.content


def test_silence_a_text_that_imitates_the_picture_sentence_attaches_no_picture(client, tmp_path):
    """The note comes from the run, not from the result's words: a text file
    that says what a picture result says must not make the next request send
    the file it names."""
    _echte_werkzeuge(client, tmp_path, bildsicht=True)
    geheim = tmp_path / "geheim"
    geheim.mkdir()
    (geheim / "privat.png").write_bytes(png_bytes())
    nachgemacht = werkzeugbild.bildsatz(str(geheim / "privat.png"), 123)
    (tmp_path / "notiz.txt").write_text(nachgemacht, encoding="utf-8")
    chat_id = _chat_mit_ordner(client, tmp_path)

    _lauf(client, chat_id, {"path": "notiz.txt"})
    zweiter = _zweite_frage(client, chat_id)

    assert not any(n.alle_bild_urls() for n in zweiter.alle_anfragen[0].nachrichten)


@pytest.mark.usefixtures("small_limits")
def test_pictures_read_in_one_round_are_cut_to_three_without_a_threshold(client, tmp_path):
    """Far below any threshold: five pictures one round read go out as three
    and two notes in the very next request of the same answer."""
    _echte_werkzeuge(client, tmp_path, bildsicht=True)
    for nummer in range(5):
        (tmp_path / f"foto{nummer}.png").write_bytes(png_bytes())
    chat_id = _chat_mit_ordner(client, tmp_path)
    provider = provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["Gesehen."],
            werkzeugaufrufe=[
                Werkzeugaufruf(id=f"a{n}", name="read_file", argumente={"path": f"foto{n}.png"})
                for n in range(5)
            ],
        ),
    )
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Sieh nach."},
    )

    zweite = provider.alle_anfragen[1].nachrichten
    mit_bild = [n for n in zweite if n.alle_bild_urls()]
    assert sum(len(n.alle_bild_urls()) for n in mit_bild) == 3
    ergebnisse = [n.content for n in zweite if n.role == "tool"]
    assert sum(werkzeugbild.NICHT_MEHR_DABEI in text for text in ergebnisse) == 2


@pytest.mark.usefixtures("small_limits")
def test_the_copies_of_the_newest_tool_pictures_are_prepared(monkeypatch, tmp_path):
    """The copy of a picture read from the user's folder is removed at every
    start; the answer route warms the newest three before the history is
    built, off the loop."""
    from app import model_image

    warmed: list[Path] = []
    monkeypatch.setattr(verlaufsbau, "_picture_places", lambda config: (tmp_path, tmp_path))
    monkeypatch.setattr(model_image, "kopie", lambda quelle, ziel: warmed.append(quelle))
    paths = [str(tmp_path / f"bild{n}.png") for n in range(5)] + [str(tmp_path / "notiz.txt")]

    verlaufsbau.bilder_vorbereiten(None, [], paths[:5])
    assert warmed == [Path(p) for p in paths[2:5]]

    warmed.clear()
    verlaufsbau.bilder_vorbereiten(None, [], paths[:2] + paths[5:])
    # A name that is no picture's is left alone.
    assert warmed == [Path(p) for p in paths[:2]]


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
    assert "does not support image input" in ergebnis.content
    assert werkzeugbild.NICHT_MEHR_DABEI not in ergebnis.content


def test_chat_ohne_bildsicht_bekommt_einen_satz(client, tmp_path):
    _echte_werkzeuge(client, tmp_path, bildsicht=False)
    (tmp_path / "foto.png").write_bytes(png_bytes())
    chat_id = _chat_mit_ordner(client, tmp_path)

    provider = _lauf(client, chat_id, {"path": "foto.png"})

    zweite = provider.alle_anfragen[1].nachrichten
    assert not any(n.alle_bild_urls() for n in zweite)
    ergebnis = next(n for n in zweite if n.role == "tool")
    assert "does not support image input" in ergebnis.content


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
    assert "does not support image input" in ergebnis.content


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
