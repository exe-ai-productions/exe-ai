"""`MessageRepository.lauf_hat_nachricht` (H1d): a run's own question must
be found by asking for the question itself, not by any row that happens
to carry the run's marker -- a picture row surviving the question's own
deletion looked exactly like proof a question already existed.
"""

from __future__ import annotations

import pytest


def _chat(client):
    return client.post("/api/v1/chats", json={"title": "Lauf"}).json()


def test_die_hoechste_laufnummer_kommt_aus_den_zeilen(client):
    """Run numbers live in the tool logs of the rows; the highest one is
    where a chat's numbering continues after a restart. A report row
    counts, a blob that is not JSON counts as nothing, and a chat without
    runs answers zero."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    assert repositories.messages.hoechste_laufnummer(chat_id=chat["id"]) == 0
    repositories.messages.speichern(
        chat_id=chat["id"], role="assistant", content="a", zustand="fertig",
        stats={"werkzeuge": [
            {"name": "run_command", "argumente": {"command": "ls"}, "lauf_nummer": 3},
            {"name": "read_file", "argumente": {"path": "x"}},
        ]},
    )
    repositories.messages.speichern(
        chat_id=chat["id"], role="assistant", content="[report]", art="werkzeugmeldung",
        stats={"werkzeuge": [{"name": "run_command", "lauf_nummer": 5, "ergebnis": ""}]},
    )
    assert repositories.messages.hoechste_laufnummer(chat_id=chat["id"]) == 5
    repositories.messages.verbindung.execute(
        "UPDATE messages SET stats_json = '{lauf_nummer: kaputt' WHERE chat_id = ? AND art = 'werkzeugmeldung'",
        (chat["id"],),
    )
    assert repositories.messages.hoechste_laufnummer(chat_id=chat["id"]) == 3
    anderer = _chat(client)
    assert repositories.messages.hoechste_laufnummer(chat_id=anderer["id"]) == 0


def test_die_aktualisierung_weist_einen_unbekannten_zustand_ab(client):
    """Same rule as `speichern`: a fresh database refuses an unknown state
    through its CHECK, a migrated one would swallow it — the writer refuses
    before either gets to see it."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    zeile = repositories.messages.speichern(
        chat_id=chat["id"], role="assistant", content="", zustand="laeuft"
    )
    with pytest.raises(ValueError):
        repositories.messages.inhalt_aktualisieren(zeile.id, content="x", zustand="halbfertig")
    assert repositories.messages.holen(zeile.id).zustand == "laeuft"
    repositories.messages.inhalt_aktualisieren(zeile.id, content="x", zustand="fertig")
    assert repositories.messages.holen(zeile.id).zustand == "fertig"


def test_lauf_hat_nachricht_findet_die_frage_selbst(client):
    repositories = client.app.state.repositories
    chat = _chat(client)
    repositories.messages.speichern(
        chat_id=chat["id"], role="user", content="Zeichne vier Bilder.",
        lauf_id="l1",
    )
    assert repositories.messages.lauf_hat_nachricht(chat_id=chat["id"], lauf_kennung="l1") is True


def test_lauf_hat_nachricht_zaehlt_eine_bildzeile_nicht_als_frage(client):
    """The bug this guards: an assistant row carrying the same `lauf`
    marker (a surviving picture, no question left) must not read as
    "the question already exists" -- that reading is how a run's own
    question stayed gone for good once its first message was deleted."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    repositories.messages.speichern(
        chat_id=chat["id"], role="assistant", content="", stats={"lauf": "l2"},
    )
    assert repositories.messages.lauf_hat_nachricht(chat_id=chat["id"], lauf_kennung="l2") is False


def test_letzter_tokenstand_ist_die_neueste_lesung_die_das_modell_noch_sieht(client):
    """One query for the one integer the next answer estimates from. The
    newest reading wins, a folded row's reading no longer counts — it is
    not in the prompt any more — and zero is no reading."""
    repositories = client.app.state.repositories
    chat = _chat(client)
    assert repositories.messages.letzter_tokenstand(chat_id=chat["id"]) is None
    alt = repositories.messages.speichern(
        chat_id=chat["id"], role="assistant", content="a", gesamt_tokens=4000, zustand="fertig",
    )
    repositories.messages.speichern(
        chat_id=chat["id"], role="assistant", content="b", gesamt_tokens=0, zustand="fertig",
    )
    assert repositories.messages.letzter_tokenstand(chat_id=chat["id"]) == 4000
    neu = repositories.messages.speichern(
        chat_id=chat["id"], role="assistant", content="c", gesamt_tokens=5200, zustand="fertig",
    )
    assert repositories.messages.letzter_tokenstand(chat_id=chat["id"]) == 5200
    repositories.messages.verbindung.execute(
        "UPDATE messages SET verdichtet_in = ? WHERE id = ?", ("naht", neu.id)
    )
    assert repositories.messages.letzter_tokenstand(chat_id=chat["id"]) == 4000
    repositories.messages.verbindung.execute(
        "UPDATE messages SET verdichtet_in = ? WHERE id = ?", ("naht", alt.id)
    )
    assert repositories.messages.letzter_tokenstand(chat_id=chat["id"]) is None


def test_eine_gefaltete_zeile_wird_von_der_naht_nie_umgestempelt(repos):
    """`_kurz_nach` itself creates stamp ties: a seam with no room keeps
    the last folded row's exact stamp. A later fold whose middle ends on
    that summary used to shove the EARLIER-FOLDED row two microseconds on
    — behind the summary that speaks for it, so the reader saw it sorted
    after its own fold. Folded rows keep their stamps now."""
    repositories = repos
    chat = repositories.chats.erstellen(user_id="u", title="t", endpoint_id="e")
    stempel = "2026-01-01T10:00:00.000100+00:00"
    alt_ids = []
    for nr in range(2):
        m = repositories.messages.speichern(
            chat_id=chat.id, role="user" if nr % 2 == 0 else "assistant", content=f"m{nr}"
        )
        repositories.messages.verbindung.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?",
            (stempel[:-8] + f"{nr:03d}0+00:00", m.id),
        )
        alt_ids.append(m.id)
    # Fold #1: the seam has no room, the summary keeps the last folded
    # row's exact stamp (forced here rather than staged through a real
    # no-room neighbour — the tie itself is the case under test).
    naht1 = repositories.messages.verdichten(
        chat_id=chat.id, text="Zusammenfassung 1", ersetzte_ids=alt_ids
    )
    assert naht1 is not None
    gefaltet = alt_ids[-1]
    zeile = repositories.messages.verbindung.execute(
        "SELECT created_at FROM messages WHERE id = ?", (gefaltet,)
    ).fetchone()
    repositories.messages.verbindung.execute(
        "UPDATE messages SET created_at = ? WHERE id = ?",
        (zeile["created_at"], naht1.id),
    )
    stempel_vorher = zeile["created_at"]
    # Fold #2 ends on the summary: its `letzte` carries the tied stamp.
    neu = repositories.messages.speichern(chat_id=chat.id, role="user", content="danach")
    naht2 = repositories.messages.verdichten(
        chat_id=chat.id, text="Zusammenfassung 2", ersetzte_ids=[naht1.id, neu.id]
    )
    assert naht2 is not None
    zeile = repositories.messages.verbindung.execute(
        "SELECT created_at FROM messages WHERE id = ?", (gefaltet,)
    ).fetchone()
    assert zeile["created_at"] == stempel_vorher, (
        "the row folded earlier was restamped"
    )
