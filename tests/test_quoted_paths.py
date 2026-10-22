"""A path pasted with its quotes is the path without them.

"Copy as path" in the Windows file manager puts the path in double quotes,
and a shell lets one paste it in single quotes. Pasted into a path field it
used to be refused as not absolute, or taken as a name to make a folder of.
The one place that takes one enclosing pair off is the service, because the
command line client sends the path as it was typed: the folder check of a
chat's shares, the re-choosing of a missing folder, the start window of a
job and the storage locations all go through it.

What stays as it was: a relative path is still refused, a quote that does not
enclose the whole text, or that does not match its partner, is a character of
the path, and an unquoted path passes through untouched.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import arbeitsordnerpruefung
from app.arbeitsordnerpruefung import typed_path
from app.providers import MockProvider, mock_endpunkt
from tests.conftest import provider_setzen
from tests.test_auftraege_api import agent_schreiben, auf_ende_warten


def test_one_enclosing_pair_of_quotes_is_taken_off():
    assert typed_path('"C:\\Users\\exe\\Test Ordner"') == "C:\\Users\\exe\\Test Ordner"
    assert typed_path("'/Users/exe/Test Ordner'") == "/Users/exe/Test Ordner"
    assert typed_path('  "/a/b"  ') == "/a/b"
    # Only one pair: what is inside stays.
    assert typed_path("\"'/a/b'\"") == "'/a/b'"


@pytest.mark.parametrize(
    "text",
    [
        "/a/b",
        '"/a/b',
        "/a/b'",
        "\"/a/b'",
        '/a/"b"/c',
        '"',
        "''x",
        '""',
        "''",
        '" "',
        "",
        "  /a/b ",
    ],
)
def test_silence_everything_else_comes_back_as_it_was(text):
    assert typed_path(text) == text


@pytest.mark.parametrize("quote", ['"', "'"])
def test_a_chat_accepts_a_quoted_share(client, chat_id, tmp_path, quote):
    ordner = tmp_path / "Test Ordner"
    ordner.mkdir()

    antwort = client.patch(
        f"/api/v1/chats/{chat_id}", json={"working_dirs": [f"{quote}{ordner}{quote}"]}
    )

    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["working_dirs"] == [str(ordner.resolve())]


def test_the_check_merges_a_quoted_and_a_plain_spelling_of_one_folder(tmp_path):
    ordner = tmp_path / "x"
    ordner.mkdir()

    assert arbeitsordnerpruefung.pruefen([str(ordner), f'"{ordner}"'], "en") == [
        str(ordner.resolve())
    ]


def test_a_relative_path_stays_refused_even_in_quotes(client, chat_id):
    antwort = client.patch(
        f"/api/v1/chats/{chat_id}", json={"working_dirs": ['"relative/path"']}
    )

    assert antwort.status_code == 400
    with pytest.raises(HTTPException) as fehler:
        arbeitsordnerpruefung.pruefen(["'relative/path'"], "en")
    assert fehler.value.status_code == 400


def test_a_quoted_new_place_for_a_missing_folder_moves_the_documents(
    client, chat_id, tmp_path
):
    alt = tmp_path / "alt"
    alt.mkdir()
    datei = alt / "vertrag.txt"
    datei.write_text("x", encoding="utf-8")
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(alt)]})
    dokument = client.app.state.repositories.documents.speichern(
        chat_id=chat_id, filename=datei.name, pfad=str(datei)
    )
    neu = tmp_path / "neu"
    alt.rename(neu)

    antwort = client.patch(
        f"/api/v1/chats/{chat_id}",
        json={
            "working_dirs": [f'"{neu}"'],
            "ordner_ersatz": {"alt": str(alt.resolve()), "neu": f'"{neu}"'},
        },
    )

    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["working_dirs"] == [str(neu.resolve())]
    gespeichert = client.app.state.repositories.documents.holen(dokument.id).pfad
    assert gespeichert == str(neu.resolve() / "vertrag.txt")


def test_the_start_window_of_a_job_accepts_a_quoted_folder(
    config, client, tmp_path, monkeypatch
):
    from app.api.v1 import auftraege
    from tests.test_helper import PromptSeen

    seen = PromptSeen()
    monkeypatch.setattr(auftraege, "grundprompt", seen)
    gewaehlt = tmp_path / "Test Ordner"
    gewaehlt.mkdir()
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["done"]))

    antwort = client.post(
        "/api/v1/jobs",
        json={"agent": "recherche", "task": "go", "folders": [f'"{gewaehlt}"']},
    )

    assert antwort.status_code in (200, 201, 202), antwort.text
    auf_ende_warten(client, antwort.json()["id"])
    (teile,) = seen.calls
    assert teile["ordner"][0] == str(gewaehlt.resolve())


@pytest.mark.parametrize("quote", ['"', "'"])
def test_a_storage_location_accepts_a_quoted_path(client, tmp_path, quote):
    ziel = tmp_path / "Bilder Ort"

    antwort = client.put(
        "/api/v1/speicherorte/images", json={"pfad": f"{quote}{ziel}{quote}"}
    )

    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["pfad"] == str(ziel.resolve())
    assert ziel.is_dir()
    client.delete("/api/v1/speicherorte/images")
