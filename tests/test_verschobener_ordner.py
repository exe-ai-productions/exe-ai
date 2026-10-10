"""A shared folder that was moved away — said out loud, and pulled along.

Two halves, and they are deliberately not one. The first only LOOKS: which
of a chat's shared folders is no longer there. Nothing is removed, nothing
is searched for. The second is the answer the user gives afterwards — this
folder now lies here — and only that answer moves the document paths that
lay in it.

What is guarded most closely is the pairing. With two folders gone and two
new ones named, no comparison of the two lists can say which new place
belongs to which old folder, so the pair comes from the button the user
pressed and from nowhere else.
"""

from __future__ import annotations

import shutil

from app.providers import MockProvider, mock_endpunkt
from tests.conftest import provider_setzen


def _dokument(client, chat_id: str, pfad):
    """One document row of this chat, pointing at a real file."""
    return client.app.state.repositories.documents.speichern(
        chat_id=chat_id, filename=pfad.name, pfad=str(pfad)
    )


def _naht(client, chat_id: str, text: str):
    """A saved compaction summary standing in a chat's history, the way
    ``app/chatverdichtung.py`` writes one — built directly against the
    repository, not through the trigger machinery this order does not
    touch."""
    repositories = client.app.state.repositories
    ersetzt = repositories.messages.speichern(chat_id=chat_id, role="user", content="alt")
    return repositories.messages.verdichten(
        chat_id=chat_id, text=text, ersetzte_ids=[ersetzt.id]
    )


def _pfad_von(client, dokument_id: str) -> str:
    return client.app.state.repositories.documents.holen(dokument_id).pfad


def _stand(client, chat_id: str) -> list[str]:
    antwort = client.get(f"/api/v1/chats/{chat_id}/ordnerstand")
    assert antwort.status_code == 200
    return antwort.json()["fehlend"]


# --- The look ------------------------------------------------------------


def test_ein_ordner_der_da_ist_wird_nicht_gemeldet(client, chat_id, tmp_path):
    """The silence test, and it is the normal case: nothing has moved."""
    ordner = tmp_path / "vertrag"
    ordner.mkdir()
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(ordner)]})

    assert _stand(client, chat_id) == []


def test_ein_verschobener_ordner_wird_genannt_und_bleibt_stehen(
    client, chat_id, tmp_path
):
    ordner = tmp_path / "vertrag"
    ordner.mkdir()
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(ordner)]})
    shutil.move(str(ordner), str(tmp_path / "woanders"))

    assert _stand(client, chat_id) == [str(ordner.resolve())]
    # Named, not removed: what was shared once stays readable tomorrow.
    chat = client.get(f"/api/v1/chats/{chat_id}").json()
    assert chat["working_dirs"] == [str(ordner.resolve())]


def test_ein_chat_ohne_freigegebenen_ordner_meldet_nichts(client, chat_id):
    """A chat that shares nothing has nothing that could be missing — its own
    document folder belongs to the program and does not travel."""
    assert _stand(client, chat_id) == []


# --- The answer ----------------------------------------------------------


def test_neu_gewaehlt_zieht_die_pfade_nach(client, chat_id, tmp_path):
    alt = tmp_path / "vertrag"
    alt.mkdir()
    (alt / "brief.pdf").write_text("x")
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(alt)]})
    dokument = _dokument(client, chat_id, alt / "brief.pdf")

    neu = tmp_path / "platte" / "vertrag"
    neu.parent.mkdir()
    shutil.move(str(alt), str(neu))

    antwort = client.patch(
        f"/api/v1/chats/{chat_id}",
        json={
            "working_dirs": [str(neu)],
            "ordner_ersatz": {"alt": str(alt.resolve()), "neu": str(neu)},
        },
    )
    assert antwort.status_code == 200
    assert _pfad_von(client, dokument.id) == str(neu.resolve() / "brief.pdf")
    assert _stand(client, chat_id) == []


def test_liegt_die_datei_dort_nicht_bleibt_der_alte_pfad(client, chat_id, tmp_path):
    """A path into nothing is more honest than one onto the wrong file."""
    alt = tmp_path / "vertrag"
    alt.mkdir()
    (alt / "brief.pdf").write_text("x")
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(alt)]})
    dokument = _dokument(client, chat_id, alt / "brief.pdf")

    neu = tmp_path / "leer"
    neu.mkdir()
    shutil.rmtree(alt)

    client.patch(
        f"/api/v1/chats/{chat_id}",
        json={
            "working_dirs": [str(neu)],
            "ordner_ersatz": {"alt": str(alt.resolve()), "neu": str(neu)},
        },
    )
    assert _pfad_von(client, dokument.id) == str(alt / "brief.pdf")


def test_ein_dokument_eines_anderen_chats_bleibt_unberuehrt(client, chat_id, tmp_path):
    alt = tmp_path / "vertrag"
    alt.mkdir()
    (alt / "brief.pdf").write_text("x")
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(alt)]})

    fremder = client.post("/api/v1/chats", json={"title": "Anderer"}).json()["id"]
    fremdes = _dokument(client, fremder, alt / "brief.pdf")

    neu = tmp_path / "platte" / "vertrag"
    neu.parent.mkdir()
    shutil.move(str(alt), str(neu))

    client.patch(
        f"/api/v1/chats/{chat_id}",
        json={
            "working_dirs": [str(neu)],
            "ordner_ersatz": {"alt": str(alt.resolve()), "neu": str(neu)},
        },
    )
    assert _pfad_von(client, fremdes.id) == str(alt / "brief.pdf")


def test_ein_pfad_ausserhalb_des_alten_ordners_bleibt_unberuehrt(
    client, chat_id, tmp_path
):
    alt = tmp_path / "vertrag"
    alt.mkdir()
    daneben = tmp_path / "daneben"
    daneben.mkdir()
    (daneben / "brief.pdf").write_text("x")
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(alt)]})
    draussen = _dokument(client, chat_id, daneben / "brief.pdf")

    neu = tmp_path / "platte" / "vertrag"
    neu.parent.mkdir()
    shutil.move(str(alt), str(neu))

    client.patch(
        f"/api/v1/chats/{chat_id}",
        json={
            "working_dirs": [str(neu)],
            "ordner_ersatz": {"alt": str(alt.resolve()), "neu": str(neu)},
        },
    )
    assert _pfad_von(client, draussen.id) == str(daneben / "brief.pdf")


def test_zwei_fehlende_ordner_ziehen_nur_ihre_eigenen_pfade_nach(
    client, chat_id, tmp_path
):
    """The case the pairing exists for: two gone, two named, nothing crossed.

    And the reason it has to work in TWO saves — while the first folder is
    being re-chosen, the second missing one is still in the list.
    """
    eins, zwei = tmp_path / "eins", tmp_path / "zwei"
    eins.mkdir()
    zwei.mkdir()
    (eins / "a.pdf").write_text("x")
    (zwei / "b.pdf").write_text("x")
    client.patch(
        f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(eins), str(zwei)]}
    )
    a = _dokument(client, chat_id, eins / "a.pdf")
    b = _dokument(client, chat_id, zwei / "b.pdf")

    ziel = tmp_path / "platte"
    ziel.mkdir()
    shutil.move(str(eins), str(ziel / "eins"))
    shutil.move(str(zwei), str(ziel / "zwei"))
    assert _stand(client, chat_id) == [str(eins.resolve()), str(zwei.resolve())]

    erste = client.patch(
        f"/api/v1/chats/{chat_id}",
        json={
            "working_dirs": [str(ziel / "eins"), str(zwei)],
            "ordner_ersatz": {"alt": str(eins.resolve()), "neu": str(ziel / "eins")},
        },
    )
    assert erste.status_code == 200
    assert _pfad_von(client, a.id) == str((ziel / "eins" / "a.pdf").resolve())
    assert _pfad_von(client, b.id) == str(zwei / "b.pdf")

    client.patch(
        f"/api/v1/chats/{chat_id}",
        json={
            "working_dirs": [str(ziel / "eins"), str(ziel / "zwei")],
            "ordner_ersatz": {"alt": str(zwei.resolve()), "neu": str(ziel / "zwei")},
        },
    )
    assert _pfad_von(client, b.id) == str((ziel / "zwei" / "b.pdf").resolve())
    assert _stand(client, chat_id) == []


# --- Everything that must NOT move a path --------------------------------


def test_entfernt_statt_neu_gewaehlt_schreibt_nichts_um(client, chat_id, tmp_path):
    alt = tmp_path / "vertrag"
    alt.mkdir()
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(alt)]})
    dokument = _dokument(client, chat_id, alt / "brief.pdf")

    neu = tmp_path / "platte" / "vertrag"
    neu.parent.mkdir()
    shutil.move(str(alt), str(neu))

    antwort = client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": []})
    assert antwort.status_code == 200
    assert _pfad_von(client, dokument.id) == str(alt / "brief.pdf")


def test_ein_hinzugefuegter_ordner_schreibt_nichts_um(client, chat_id, tmp_path):
    eins, zwei = tmp_path / "eins", tmp_path / "zwei"
    eins.mkdir()
    zwei.mkdir()
    (eins / "a.pdf").write_text("x")
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(eins)]})
    dokument = _dokument(client, chat_id, eins / "a.pdf")

    client.patch(
        f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(eins), str(zwei)]}
    )
    assert _pfad_von(client, dokument.id) == str(eins / "a.pdf")


def test_der_umzug_wird_dem_modell_in_jeder_anfrage_gesagt(client, chat_id, tmp_path):
    """From the re-choosing onward, the model is told in plain English
    where the folder it remembers has gone — otherwise it keeps calling
    read_file with the dead path from its own history and runs into a
    refusal instead of an answer."""
    alt = tmp_path / "vertrag"
    alt.mkdir()
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(alt)]})

    neu = tmp_path / "platte" / "vertrag"
    neu.parent.mkdir()
    shutil.move(str(alt), str(neu))
    client.patch(
        f"/api/v1/chats/{chat_id}",
        json={
            "working_dirs": [str(neu)],
            "ordner_ersatz": {"alt": str(alt.resolve()), "neu": str(neu)},
        },
    )

    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Weiter"},
    )
    system = provider.letzte_anfrage.nachrichten[0].content
    assert str(alt.resolve()) in system
    assert str(neu.resolve()) in system


def test_ein_ordner_ohne_umzug_bekommt_keinen_satz(client, chat_id, tmp_path):
    """Schweigeprobe: sharing or switching a folder that never went missing
    says nothing about a move — there was none."""
    ordner = tmp_path / "vertrag"
    ordner.mkdir()
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(ordner)]})

    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Los"},
    )
    system = provider.letzte_anfrage.nachrichten[0].content
    assert "now lives at" not in system


def test_eine_verdichtete_naht_behaelt_ihren_text_und_bekommt_den_satz(
    client, chat_id, tmp_path
):
    """A summary saved before the move still names the dead path —
    folding does not touch it, and rewriting it would make it a text the
    model never actually wrote. The same sentence that tells the model
    about the move covers it instead: both travel in the same request."""
    alt = tmp_path / "vertrag"
    alt.mkdir()
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(alt)]})
    naht_text = f"[Documents attached in the stretch summarized above: \"brief.pdf\" — at '{alt}/brief.pdf'.]"
    _naht(client, chat_id, naht_text)

    neu = tmp_path / "platte" / "vertrag"
    neu.parent.mkdir()
    shutil.move(str(alt), str(neu))
    client.patch(
        f"/api/v1/chats/{chat_id}",
        json={
            "working_dirs": [str(neu)],
            "ordner_ersatz": {"alt": str(alt.resolve()), "neu": str(neu)},
        },
    )

    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Weiter"},
    )
    inhalte = [n.content for n in provider.letzte_anfrage.nachrichten]
    assert naht_text in inhalte
    system = inhalte[0]
    assert str(alt.resolve()) in system
    assert str(neu.resolve()) in system


def test_eine_naht_ohne_umzug_bekommt_keinen_satz(client, chat_id, tmp_path):
    """Schweigeprobe: a summary naming a path under a folder that never
    moved gets no sentence — the chat itself was not moved."""
    ordner = tmp_path / "vertrag"
    ordner.mkdir()
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(ordner)]})
    naht_text = f"[Documents attached in the stretch summarized above: \"brief.pdf\" — at '{ordner}/brief.pdf'.]"
    _naht(client, chat_id, naht_text)

    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Los"},
    )
    inhalte = [n.content for n in provider.letzte_anfrage.nachrichten]
    assert naht_text in inhalte
    assert "now lives at" not in inhalte[0]


def test_geloeschter_chat_vergisst_seinen_umzug(client, chat_id, tmp_path):
    """A deleted chat cannot be opened again to read the sentence anyway —
    the in-memory record has to be told the same way the run history is
    (``app/tools/hintergrund.py`` ``laeufe.vergessen``, called from the
    same route), or it is kept for the life of the process for a
    conversation nobody can open any more."""
    from app.api.v1.generierung import _ordner_umzuege

    alt = tmp_path / "vertrag"
    alt.mkdir()
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(alt)]})

    neu = tmp_path / "platte" / "vertrag"
    neu.parent.mkdir()
    shutil.move(str(alt), str(neu))
    client.patch(
        f"/api/v1/chats/{chat_id}",
        json={
            "working_dirs": [str(neu)],
            "ordner_ersatz": {"alt": str(alt.resolve()), "neu": str(neu)},
        },
    )
    assert chat_id in _ordner_umzuege

    antwort = client.delete(f"/api/v1/chats/{chat_id}")
    assert antwort.status_code == 204
    assert chat_id not in _ordner_umzuege


def test_ein_paar_das_nicht_zum_chat_gehoert_schreibt_nichts_um(
    client, chat_id, tmp_path
):
    """The boundary: the old path has to be one this chat really shared.

    Without it, the pair would be a free instruction to rewrite any path —
    exactly what the route showing a folder refuses for the same reason.
    """
    eins, zwei = tmp_path / "eins", tmp_path / "zwei"
    eins.mkdir()
    zwei.mkdir()
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(eins)]})
    fremd = tmp_path / "niefreigegeben"
    fremd.mkdir()
    (fremd / "a.pdf").write_text("x")
    (zwei / "a.pdf").write_text("x")
    dokument = _dokument(client, chat_id, fremd / "a.pdf")

    client.patch(
        f"/api/v1/chats/{chat_id}",
        json={
            "working_dirs": [str(eins), str(zwei)],
            "ordner_ersatz": {"alt": str(fremd.resolve()), "neu": str(zwei)},
        },
    )
    assert _pfad_von(client, dokument.id) == str(fremd / "a.pdf")
