"""A run says which row it is writing, and nothing deduces it any more.

The defect these guard against: a window opening a chat mid-run had to work
out for itself which row was the answer, and did it by description — the
last row of the chat, of role assistant, whose metrics blob carried no
cancel mark. Everything a chat gains DURING a run fits that description as
well: a finished background command, a picture from the picture window, a
run's own picture row. Whichever landed last was adopted as the answer,
emptied, and refilled with the replayed stream, while the real answer stood
untouched above it. Two copies of the same text, and one more for every
further reattach — measured at roughly two dozen.

So these tests are about the ONE question the description used to answer
badly: given a chat with a run going and foreign rows behind the answer,
which row is the answer? Everything else that broke followed from getting
that wrong.
"""

from __future__ import annotations

import pytest

from app.providers import MockProvider
from tests.conftest import provider_setzen


def _fremde_zeile(client, chat_id, **felder):
    """A row that lands in the chat while a run is going, written by
    somebody who is not the model. Inserted through the repository so the
    columns are exercised exactly as the real writers set them."""
    repositories = client.app.state.repositories
    return repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="", **felder
    )


def test_der_lauf_nennt_seine_zeile(client, chat_id):
    """The route hands over WHICH row, not only THAT a run exists."""
    provider_setzen(client, MockProvider(haeppchen=["Hallo"]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Los"},
    )

    seite = client.get(f"/api/v1/chats/{chat_id}/messages").json()
    antwort = next(n for n in seite["nachrichten"] if n["role"] == "assistant")
    # Over by the time this is read, so there is no `laufend` any more --
    # what matters here is that the row carries its own closing state
    # instead of it having to be read out of which keys the blob happens to
    # have.
    assert antwort["zustand"] == "fertig"
    assert antwort["art"] == "nachricht"


def test_werkzeugmeldung_ist_keine_antwort(client, chat_id):
    """A finished background command used to be indistinguishable from an
    answer still being written: assistant, and no cancel mark."""
    meldung = _fremde_zeile(client, chat_id, art="werkzeugmeldung")

    geholt = client.app.state.repositories.messages.holen(meldung.id)
    assert geholt.art == "werkzeugmeldung"
    # No state at all -- it has no run of its own. A row that carried
    # `zustand` would be claiming one.
    assert geholt.zustand is None


def test_bild_ist_keine_antwort(client, chat_id):
    """Same shape, different writer: the picture window is not blocked while
    a chat answers, so its row can land behind a live answer."""
    bild = _fremde_zeile(client, chat_id, art="bild")

    geholt = client.app.state.repositories.messages.holen(bild.id)
    assert geholt.art == "bild"
    assert geholt.zustand is None


@pytest.mark.parametrize("fremde_art", ["werkzeugmeldung", "bild"])
def test_die_letzte_zeile_ist_nicht_die_laufende(client, chat_id, fremde_art):
    """The heart of it.

    A row of somebody else's lands BEHIND the answer -- which it does, since
    the answer's row is created at the start of the run and everything sorts
    by creation time. The old reading would have picked the foreign row.
    Asked properly, the answer is still the answer.
    """
    repositories = client.app.state.repositories
    antwort = repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="", zustand="laeuft"
    )
    fremd = _fremde_zeile(client, chat_id, art=fremde_art)

    zeilen = repositories.messages.auflisten(chat_id=chat_id)
    # The premise the old code got wrong: the answer is NOT last.
    assert zeilen[-1].id == fremd.id

    laufende = [z for z in zeilen if z.zustand == "laeuft"]
    assert [z.id for z in laufende] == [antwort.id]


def test_nur_eine_zeile_gilt_je_lauf_als_laufend(client, chat_id):
    """Two answers can never be live at once in one chat -- if they could,
    naming the row would be no better than guessing it."""
    repositories = client.app.state.repositories
    erste = repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="", zustand="laeuft"
    )
    repositories.messages.inhalt_aktualisieren(
        erste.id, content="fertig geworden", zustand="fertig"
    )
    zweite = repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="", zustand="laeuft"
    )

    zeilen = repositories.messages.auflisten(chat_id=chat_id)
    assert [z.id for z in zeilen if z.zustand == "laeuft"] == [zweite.id]


def test_laufende_zeile_verliert_ihren_zustand_nicht_beim_weiterschreiben(
    client, chat_id
):
    """The running saves carry text and nothing else, over and over. They
    must not blank the state or the token count they do not carry -- the
    reason both are COALESCEd."""
    repositories = client.app.state.repositories
    zeile = repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="", zustand="laeuft"
    )
    repositories.messages.tokenstand_setzen(zeile.id, 4321)

    repositories.messages.inhalt_aktualisieren(zeile.id, content="halb geschrieben")

    geholt = repositories.messages.holen(zeile.id)
    assert geholt.zustand == "laeuft"
    assert geholt.gesamt_tokens == 4321


def test_abgebrochen_fehler_und_fertig_sind_drei_verschiedene_worte(client, chat_id):
    """They used to be three readings of which keys a blob happened to
    carry, which is how "still running" ended up meaning "no cancel key"."""
    repositories = client.app.state.repositories
    for gesetzt in ("fertig", "abgebrochen", "fehler"):
        zeile = repositories.messages.speichern(
            chat_id=chat_id, role="assistant", content="", zustand="laeuft"
        )
        repositories.messages.inhalt_aktualisieren(
            zeile.id, content="x", zustand=gesetzt
        )
        assert repositories.messages.holen(zeile.id).zustand == gesetzt


def test_ein_dienstneustart_raeumt_haengengebliebene_antworten_auf(client, chat_id):
    """`zustand` only ever leaves 'laeuft' through the run's own closing
    write. A service killed mid-stream therefore leaves a row claiming to be
    live, and nothing else would ever correct it: the window would draw it
    as a running answer for good, and the context bar would read its token
    count as the current one.
    """
    repositories = client.app.state.repositories
    haengend = repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="halb geschrieben", zustand="laeuft"
    )
    fertig = repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="fertig", zustand="fertig"
    )

    anzahl = repositories.messages.beim_start_aufraeumen()

    assert anzahl == 1
    # Not 'fertig': the answer did not finish, and saying it did would hide
    # that whatever it was writing was cut off.
    assert repositories.messages.holen(haengend.id).zustand == "abgebrochen"
    assert repositories.messages.holen(fertig.id).zustand == "fertig"


def test_das_aufraeumen_laeuft_auch_ohne_haengende_zeile_durch(client, chat_id):
    repositories = client.app.state.repositories
    repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="fertig", zustand="fertig"
    )
    assert repositories.messages.beim_start_aufraeumen() == 0
