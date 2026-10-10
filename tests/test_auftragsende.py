"""The one announcement a finished run makes (app/auftragsende.py).

What is measured here is not that a row was written — the repository's own
tests do that — but how often the event fires, because that is the whole
point of the module: one piece of work, one announcement.
"""

from __future__ import annotations

import pytest

from app import auftragsende
from app.events import Ereignisse, bus


@pytest.fixture
def gehoert():
    """Collects every announcement made while a test runs."""
    liste: list[dict] = []

    def merken(**daten):
        liste.append(daten)

    bus.abonnieren(Ereignisse.AUFTRAG_BEENDET, merken)
    yield liste
    bus.abbestellen(Ereignisse.AUFTRAG_BEENDET, merken)


def _auftrag(repos, *, cronjob_id: str | None = None):
    return repos.auftraege.erstellen(
        user_id="benutzer",
        agent="Rechercheur",
        auftrag="Sieh nach",
        cronjob_id=cronjob_id,
    )


def test_ein_ende_meldet_sich_einmal_mit_allen_feldern(repos, gehoert):
    auftrag = _auftrag(repos)

    auftragsende.beenden(
        repos, auftrag.id, "fertig", ende_grund="fertig", ergebnis="Drei Quellen"
    )

    assert len(gehoert) == 1
    meldung = gehoert[0]
    assert meldung["auftrag_id"] == auftrag.id
    # Nothing scheduled this run, so it is its own piece of work.
    assert meldung["work_id"] == auftrag.id
    assert meldung["agent"] == "Rechercheur"
    assert meldung["ausgang"] == "fertig"
    assert meldung["grund"] == "fertig"
    assert meldung["ergebnis"] == "Drei Quellen"


def test_ein_laufender_auftrag_meldet_nichts(repos, gehoert):
    """The silence probe: only an end state is an ending."""
    auftrag = _auftrag(repos)

    auftragsende.beenden(repos, auftrag.id, "wartet")
    auftragsende.beenden(repos, auftrag.id, "laeuft")

    assert gehoert == []


def test_dasselbe_ende_zweimal_geschrieben_meldet_einmal(repos, gehoert):
    auftrag = _auftrag(repos)

    auftragsende.beenden(repos, auftrag.id, "gescheitert", ende_grund="zeitgrenze")
    auftragsende.beenden(repos, auftrag.id, "gescheitert", ende_grund="zeitgrenze")

    assert len(gehoert) == 1


def test_ein_weitergereichter_lauf_ist_kein_ende(repos, gehoert):
    auftrag = _auftrag(repos)

    auftragsende.beenden(
        repos, auftrag.id, "unterbrochen", ende_grund="kontext_voll"
    )

    assert gehoert == []


def test_ein_dienst_neustart_ist_ein_ende(repos, gehoert):
    """The one interrupted run nobody handed on — it was simply cut off."""
    auftrag = _auftrag(repos)

    auftragsende.beenden(
        repos, auftrag.id, "unterbrochen", ende_grund="dienst_neustart"
    )

    assert len(gehoert) == 1
    assert gehoert[0]["ausgang"] == "unterbrochen"


def test_eine_kette_mit_zwei_neustarts_meldet_einmal(repos, gehoert):
    """Three links, two of them handing the work on: one announcement."""
    for grund in ("kontext_voll", "anbieter_ausfall"):
        glied = _auftrag(repos)
        auftragsende.beenden(repos, glied.id, "unterbrochen", ende_grund=grund)

    letztes = _auftrag(repos)
    auftragsende.beenden(repos, letztes.id, "fertig", ende_grund="fertig")

    assert len(gehoert) == 1
    assert gehoert[0]["auftrag_id"] == letztes.id


def test_die_kette_meldet_ihren_ursprung_als_werk(repos, gehoert):
    """A continuation names the entry the chain started from, not its own."""
    ursprung = repos.cronjobs.erstellen(
        agent="Rechercheur", task="Sieh nach", zeitplan="08:00", herkunft="chat"
    )
    fortsetzung = repos.cronjobs.erstellen(
        agent="Rechercheur",
        task="Sieh weiter nach",
        zeitplan="09:00",
        herkunft="agent",
        ursprung_id=ursprung.id,
    )
    lauf = _auftrag(repos, cronjob_id=fortsetzung.id)

    auftragsende.beenden(repos, lauf.id, "fertig", ende_grund="fertig")

    assert len(gehoert) == 1
    assert gehoert[0]["work_id"] == ursprung.id


def test_ein_geloeschter_auftrag_meldet_nichts(repos, gehoert):
    """DELETE stops the run first and then deletes it — the ending arrives
    at a row that is no longer there."""
    auftrag = _auftrag(repos)
    repos.auftraege.loeschen(auftrag.id, user_id="benutzer")

    assert auftragsende.beenden(repos, auftrag.id, "fertig") is None
    assert gehoert == []
