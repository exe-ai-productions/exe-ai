"""The cron table (schema 12): independent, user-created
standing schedules — several per agent are possible, unlike an agent's own
single ``schedule:`` front-matter field (app/wecker.py).
"""

from __future__ import annotations

from app.db import Database
from app.db.connection import SCHEMA_VERSION


def test_frische_datenbank_hat_den_aktuellen_stand(db: Database):
    assert db.schema_version() == SCHEMA_VERSION


def test_erstellen_und_holen(repos):
    eintrag = repos.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    geholt = repos.cronjobs.holen(eintrag.id)
    assert geholt.agent == "recherche"
    assert geholt.task == "Los"
    assert geholt.zeitplan == "08:00"
    assert geholt.herkunft == "chat"
    assert geholt.deliver == "log"
    assert geholt.aktiv is True
    assert geholt.zuletzt_ausgeloest is None


def test_unbekannte_id_gibt_nichts(repos):
    assert repos.cronjobs.holen("phantom") is None


def test_auflisten_zeigt_alles(repos):
    repos.cronjobs.erstellen(agent="a", task="x", zeitplan="08:00", herkunft="chat")
    repos.cronjobs.erstellen(agent="b", task="y", zeitplan="09:00", herkunft="agent")
    assert {e.agent for e in repos.cronjobs.auflisten()} == {"a", "b"}


def test_aktive_laesst_pausierte_aus(repos):
    an = repos.cronjobs.erstellen(agent="a", task="x", zeitplan="08:00", herkunft="chat")
    aus = repos.cronjobs.erstellen(agent="b", task="y", zeitplan="09:00", herkunft="chat")
    repos.cronjobs.aktiv_setzen(aus.id, False)
    assert [e.id for e in repos.cronjobs.aktive()] == [an.id]


def test_aktiv_setzen_pausiert_und_setzt_fort(repos):
    eintrag = repos.cronjobs.erstellen(agent="a", task="x", zeitplan="08:00", herkunft="chat")
    repos.cronjobs.aktiv_setzen(eintrag.id, False)
    assert repos.cronjobs.holen(eintrag.id).aktiv is False
    repos.cronjobs.aktiv_setzen(eintrag.id, True)
    assert repos.cronjobs.holen(eintrag.id).aktiv is True


def test_aktualisieren_aendert_nur_gegebene_felder(repos):
    eintrag = repos.cronjobs.erstellen(agent="a", task="x", zeitplan="08:00", herkunft="chat")
    repos.cronjobs.aktualisieren(eintrag.id, zeitplan="09:30")
    geaendert = repos.cronjobs.holen(eintrag.id)
    assert geaendert.zeitplan == "09:30"
    assert geaendert.task == "x"
    assert geaendert.agent == "a"


def test_erstellen_nimmt_deliver_entgegen(repos):
    eintrag = repos.cronjobs.erstellen(
        agent="a", task="x", zeitplan="08:00", herkunft="chat", deliver="announce",
    )
    assert repos.cronjobs.holen(eintrag.id).deliver == "announce"


def test_aktualisieren_kann_deliver_aendern(repos):
    eintrag = repos.cronjobs.erstellen(agent="a", task="x", zeitplan="08:00", herkunft="chat")
    repos.cronjobs.aktualisieren(eintrag.id, deliver="announce")
    assert repos.cronjobs.holen(eintrag.id).deliver == "announce"


def test_erstellen_ist_standardmaessig_nicht_einmalig(repos):
    eintrag = repos.cronjobs.erstellen(agent="a", task="x", zeitplan="08:00", herkunft="chat")
    assert repos.cronjobs.holen(eintrag.id).einmalig is False


def test_erstellen_nimmt_einmalig_entgegen(repos):
    eintrag = repos.cronjobs.erstellen(
        agent="a", task="x", zeitplan="08:00", herkunft="chat", einmalig=True,
    )
    assert repos.cronjobs.holen(eintrag.id).einmalig is True


def test_erstellen_ist_standardmaessig_ohne_datum(repos):
    eintrag = repos.cronjobs.erstellen(agent="a", task="x", zeitplan="08:00", herkunft="chat")
    assert repos.cronjobs.holen(eintrag.id).datum is None


def test_erstellen_nimmt_datum_entgegen(repos):
    eintrag = repos.cronjobs.erstellen(
        agent="a", task="x", zeitplan="08:00", herkunft="chat",
        einmalig=True, datum="2026-09-01",
    )
    assert repos.cronjobs.holen(eintrag.id).datum == "2026-09-01"


def test_aktualisieren_kann_datum_raeumen(repos):
    """Turning 'einmalig' back off must not
    leave a stale 'datum' behind that firing logic elsewhere still reads."""
    eintrag = repos.cronjobs.erstellen(
        agent="a", task="x", zeitplan="09:00", herkunft="chat",
        einmalig=True, datum="2026-09-01",
    )
    repos.cronjobs.aktualisieren(eintrag.id, einmalig=False, datum_loeschen=True)
    assert repos.cronjobs.holen(eintrag.id).datum is None


def test_aktualisieren_ohne_datum_loeschen_laesst_datum_unangetastet(repos):
    eintrag = repos.cronjobs.erstellen(
        agent="a", task="x", zeitplan="09:00", herkunft="chat",
        einmalig=True, datum="2026-09-01",
    )
    repos.cronjobs.aktualisieren(eintrag.id, task="y")
    assert repos.cronjobs.holen(eintrag.id).datum == "2026-09-01"


def test_aktualisieren_kann_datum_setzen(repos):
    """Moving a one-off's date works at the
    repository layer — the tool above it is what enforces the three rejects."""
    eintrag = repos.cronjobs.erstellen(
        agent="a", task="x", zeitplan="09:00", herkunft="chat",
        einmalig=True, datum="2026-09-01",
    )
    repos.cronjobs.aktualisieren(eintrag.id, datum="2026-09-05")
    assert repos.cronjobs.holen(eintrag.id).datum == "2026-09-05"


def test_aktualisieren_datum_loeschen_geht_vor_datum(repos):
    """The two answer opposite questions — clearing wins if both somehow
    arrive together, rather than the values racing each other."""
    eintrag = repos.cronjobs.erstellen(
        agent="a", task="x", zeitplan="09:00", herkunft="chat",
        einmalig=True, datum="2026-09-01",
    )
    repos.cronjobs.aktualisieren(eintrag.id, datum="2026-09-05", datum_loeschen=True)
    assert repos.cronjobs.holen(eintrag.id).datum is None


def test_loeschen(repos):
    eintrag = repos.cronjobs.erstellen(agent="a", task="x", zeitplan="08:00", herkunft="chat")
    assert repos.cronjobs.loeschen(eintrag.id) is True
    assert repos.cronjobs.holen(eintrag.id) is None
    assert repos.cronjobs.loeschen(eintrag.id) is False


def test_ausgeloest_setzen(repos):
    eintrag = repos.cronjobs.erstellen(agent="a", task="x", zeitplan="08:00", herkunft="chat")
    repos.cronjobs.ausgeloest_setzen(eintrag.id, "2026-08-24T08:00:00+00:00")
    assert repos.cronjobs.holen(eintrag.id).zuletzt_ausgeloest == "2026-08-24T08:00:00+00:00"
