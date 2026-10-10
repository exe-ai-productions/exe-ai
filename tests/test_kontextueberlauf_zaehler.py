"""A context overflow that hands its work on is not a failed run
(Nachtrag 01.09.).

The failure counter's own rule is "the run could not do its work at all". A proactive
handoff (app/zwischenstand.py) is the opposite of that: the run did its
work, got far, wrote down where it stood and put the continuation on the
clock. Counted as a failure it killed two things —

* the restart chain, at ``fehlergrenze`` (5) instead of at
  ``MAX_NEUSTARTS`` (10), and it killed exactly the entry the run had
  written its own continuation into a second earlier;
* the ORIGINAL entry: every handed-off run carries its id, and a 'fertig'
  never reaches it, because it is the continuation that finishes. A big
  daily job that overflows every day was therefore dead after five
  perfectly normal days.

What still counts is checked here too: a real failure, and an overflow with
nothing behind it.
"""

from __future__ import annotations

from app import wiederversuch, zwischenstand
from app.agenten import agenten_laden
from app.api.abhaengigkeiten import STANDARD_BENUTZER
from app.api.v1.auftraege import auftrag_anstossen
from app.providers import MockProvider, mock_endpunkt
from tests.conftest import provider_setzen
from tests.test_auftraege_api import (
    HANDOFF_ZWEI_PUNKTE,
    NahezuVollerKontext,
    _bis_beendet,
    agent_schreiben,
)


def eintrag_anlegen(client, **felder):
    felder.setdefault("fehlergrenze", 2)
    return client.app.state.repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat", **felder
    )


async def lauf_starten(client, cronjob_id: str):
    """One run of this entry, taken to its end — the same path the firing
    loop takes, minus the waiting. Async, and awaited on the very loop the
    background run was created on (see ``_bis_beendet``)."""
    app = client.app
    config = app.state.config
    agent = agenten_laden(*config.agentenverzeichnisse)["recherche"]
    auftrag = auftrag_anstossen(
        config=config,
        repositories=app.state.repositories,
        discovery=app.state.discovery,
        generierungen=app.state.generierungen,
        registry=getattr(app.state, "werkzeuge", None),
        agent=agent,
        task="Los",
        endpoint_id=None,
        user_id=getattr(app.state, "standard_benutzer", STANDARD_BENUTZER),
        sprache=config.app.language,
        cronjob_id=cronjob_id,
    )
    return await _bis_beendet(app.state.repositories, auftrag.id)


def voller_kontext(client, handoff_text: str = HANDOFF_ZWEI_PUNKTE) -> None:
    provider_setzen(
        client, NahezuVollerKontext(mock_endpunkt("test"), handoff_text=handoff_text)
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 1000


# --- The handed-off run ------------------------------------------------------


async def test_uebergabe_zaehlt_keinen_fehlversuch(config, client):
    agent_schreiben(config)
    voller_kontext(client)
    eintrag = eintrag_anlegen(client)

    auftrag = await lauf_starten(client, eintrag.id)
    assert auftrag.ende_grund == "kontext_voll"

    frisch = client.app.state.repositories.cronjobs.holen(eintrag.id)
    assert frisch.fehlversuche == 0
    assert frisch.aktiv is True


async def test_ein_grosser_taeglicher_job_stirbt_nicht_nach_fuenf_tagen(config, client):
    """The heavier of the two consequences: the ORIGINAL entry. Every
    handed-off run carries its id and a 'fertig' never reaches it, so
    before this the entry was switched off after ``fehlergrenze`` days of
    working exactly as intended."""
    agent_schreiben(config)
    voller_kontext(client)
    eintrag = eintrag_anlegen(client, fehlergrenze=2)

    for _ in range(4):
        await lauf_starten(client, eintrag.id)

    frisch = client.app.state.repositories.cronjobs.holen(eintrag.id)
    assert frisch.fehlversuche == 0
    assert frisch.aktiv is True


async def test_die_kette_laeuft_bis_zu_ihren_zehn_neustarts(config, client):
    """Not to five. The chain's own entry is what the run wrote its
    continuation into a second earlier — switching it off there would kill
    the very thing that was supposed to carry on."""
    agent_schreiben(config)
    voller_kontext(client)
    repos = client.app.state.repositories
    kette = eintrag_anlegen(client, basisaufgabe="Los", fehlergrenze=5)
    repos.cronjobs.verbindung.execute(
        "UPDATE cronjobs SET neustarts = 5, fehlversuche = 4 WHERE id = ?", (kette.id,)
    )
    assert zwischenstand.ist_kette(repos.cronjobs.holen(kette.id))

    await lauf_starten(client, kette.id)

    frisch = repos.cronjobs.holen(kette.id)
    # The old behaviour: fehlversuche 4 -> 5 == fehlergrenze -> switched off,
    # at restart six of ten.
    assert frisch.fehlversuche == 4
    assert frisch.neustarts == 6
    assert frisch.aktiv is True
    assert zwischenstand.MAX_NEUSTARTS == 10


# --- What still counts -------------------------------------------------------


async def test_ueberlauf_ohne_fortsetzung_zaehlt_weiter(config, client):
    """The handoff came back empty — a real ending with nothing behind it,
    and the one overflow shape that is not a handoff at all."""
    agent_schreiben(config)
    voller_kontext(client, handoff_text="   ")
    eintrag = eintrag_anlegen(client, fehlergrenze=1)

    auftrag = await lauf_starten(client, eintrag.id)
    assert auftrag.ende_grund == "kontext_voll"

    frisch = client.app.state.repositories.cronjobs.holen(eintrag.id)
    assert frisch.fehlversuche == 1
    assert frisch.aktiv is False


async def test_echter_fehler_ohne_fortsetzung_zaehlt_weiter(config, client, monkeypatch):
    """The failure counter itself: the model was unreachable and nothing carries the
    work on, so the run could not do its work at all.

    An outage writes a continuation of its own while the restart ceiling
    still allows one, and the same rule as the overflow's applies to it
    (Kettenband) — so the ending that still counts is the one with no
    restart left, which is what this sets up."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), fehler="kaputt"))
    eintrag = eintrag_anlegen(client, fehlergrenze=1)
    repos = client.app.state.repositories
    repos.cronjobs.verbindung.execute(
        "UPDATE cronjobs SET neustarts = ? WHERE id = ?",
        (zwischenstand.MAX_NEUSTARTS - 1, eintrag.id),
    )

    auftrag = await lauf_starten(client, eintrag.id)
    assert auftrag.zustand == "gescheitert"
    assert auftrag.ende_grund == "anbieter_ausfall"

    frisch = repos.cronjobs.holen(eintrag.id)
    assert frisch.fehlversuche == 1
    assert frisch.aktiv is False
