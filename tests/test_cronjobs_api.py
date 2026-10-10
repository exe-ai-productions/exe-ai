"""Cron entries in the settings window (app/api/v1/cronjobs.py, 6.7
extension) — list and the on/off switch. Creating stays the tool's job
(app/tools/cronjob.py, tests/test_cronjob_werkzeug.py)."""

from __future__ import annotations

import time
from datetime import datetime

from app.providers import MockProvider, mock_endpunkt
from tests.conftest import provider_setzen


def test_leere_liste(client):
    assert client.get("/api/v1/cronjobs").json() == []


def test_liste_zeigt_angelegten_eintrag(client):
    eintrag = client.app.state.repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    (antwort,) = client.get("/api/v1/cronjobs").json()
    assert antwort["id"] == eintrag.id
    assert antwort["agent"] == "recherche"
    assert antwort["aktiv"] is True


def test_pausieren_und_fortsetzen(client):
    eintrag = client.app.state.repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    antwort = client.post(f"/api/v1/cronjobs/{eintrag.id}/pause")
    assert antwort.status_code == 200
    assert antwort.json()["aktiv"] is False

    antwort = client.post(f"/api/v1/cronjobs/{eintrag.id}/resume")
    assert antwort.status_code == 200
    assert antwort.json()["aktiv"] is True


def test_pausieren_unbekannter_termin_gibt_404(client):
    assert client.post("/api/v1/cronjobs/phantom/pause").status_code == 404


def test_pausieren_und_fortsetzen_behalten_letzten_ausgang(client):
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    lauf = repositories.auftraege.erstellen(
        user_id="standard", agent="recherche", auftrag="Testlauf", cronjob_id=eintrag.id
    )
    repositories.auftraege.zustand_setzen(lauf.id, "gescheitert", ende_grund="zeitgrenze")

    pausiert = client.post(f"/api/v1/cronjobs/{eintrag.id}/pause").json()
    assert pausiert["letzter_ausgang"] == "gescheitert"

    fortgesetzt = client.post(f"/api/v1/cronjobs/{eintrag.id}/resume").json()
    assert fortgesetzt["letzter_ausgang"] == "gescheitert"


def test_loeschen(client):
    eintrag = client.app.state.repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    assert client.delete(f"/api/v1/cronjobs/{eintrag.id}").status_code == 204
    assert client.get("/api/v1/cronjobs").json() == []


def test_loeschen_unbekannter_termin_gibt_404(client):
    assert client.delete("/api/v1/cronjobs/phantom").status_code == 404


def _runs_of(client, cronjob_id):
    """The runs of one entry, read where the panel reads them: the one
    route for all runs (the per-entry route is gone)."""
    return [
        lauf for lauf in client.get("/api/v1/cronjobs/runs/all").json()
        if lauf["cronjob_id"] == cronjob_id
    ]


def test_abgebrochen_zaehlt_als_fehlschlag_unterbrochen_und_laufend_nicht(client):
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    abgebrochener = repositories.auftraege.erstellen(
        user_id="standard", agent="recherche", auftrag="Abgebrochen", cronjob_id=eintrag.id
    )
    repositories.auftraege.zustand_setzen(
        abgebrochener.id, "abgebrochen", ende_grund="nutzer_abbruch"
    )
    unterbrochener = repositories.auftraege.erstellen(
        user_id="standard", agent="recherche", auftrag="Unterbrochen", cronjob_id=eintrag.id
    )
    repositories.auftraege.zustand_setzen(
        unterbrochener.id, "unterbrochen", ende_grund="dienst_neustart"
    )
    repositories.auftraege.erstellen(
        user_id="standard", agent="recherche", auftrag="Läuft noch", cronjob_id=eintrag.id
    )

    (lauf,) = _runs_of(client, eintrag.id)
    assert lauf["id"] == abgebrochener.id
    assert lauf["task"] == "Abgebrochen"
    assert lauf["status"] == "gescheitert"
    assert lauf["grund"] == "nutzer_abbruch"


def test_laeufe_und_letzter_ausgang(client):
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    guter = repositories.auftraege.erstellen(
        user_id="standard",
        agent="recherche",
        auftrag="Fasse die Mails zusammen",
        cronjob_id=eintrag.id,
    )
    repositories.auftraege.zustand_setzen(guter.id, "fertig")
    schlechter = repositories.auftraege.erstellen(
        user_id="standard",
        agent="recherche",
        auftrag="Starte den Testlauf",
        cronjob_id=eintrag.id,
    )
    repositories.auftraege.zustand_setzen(
        schlechter.id, "gescheitert", ende_grund="zeitgrenze"
    )

    laeufe = _runs_of(client, eintrag.id)
    assert len(laeufe) == 2
    nach_status = {lauf["status"]: lauf for lauf in laeufe}
    assert nach_status["gut"]["task"] == "Fasse die Mails zusammen"
    assert nach_status["gut"]["grund"] is None
    assert nach_status["gescheitert"]["task"] == "Starte den Testlauf"
    assert nach_status["gescheitert"]["grund"] == "zeitgrenze"

    (antwort,) = client.get("/api/v1/cronjobs").json()
    assert antwort["letzter_ausgang"] == "gescheitert"


def test_letzter_ausgang_folgt_created_at_nicht_der_einfuegereihenfolge(client):
    """The three places asking 'what was the last run' — the list, pause
    and resume, and the runs — have to agree even when created_at disagrees
    with insertion order. Backdating the second insert past the first one
    makes the first insert the newer run by created_at."""
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    zuerst_eingefuegt = repositories.auftraege.erstellen(
        user_id="standard", agent="recherche", auftrag="Zuerst eingefügt", cronjob_id=eintrag.id
    )
    repositories.auftraege.zustand_setzen(
        zuerst_eingefuegt.id, "gescheitert", ende_grund="zeitgrenze"
    )
    danach_eingefuegt = repositories.auftraege.erstellen(
        user_id="standard", agent="recherche", auftrag="Danach eingefügt", cronjob_id=eintrag.id
    )
    repositories.auftraege.zustand_setzen(danach_eingefuegt.id, "fertig")

    # Give the later insert the earlier created_at — created_at now
    # disagrees with rowid/insertion order.
    repositories.auftraege.verbindung.execute(
        "UPDATE auftraege SET created_at = '2020-01-01T00:00:00' WHERE id = ?",
        (danach_eingefuegt.id,),
    )

    (antwort,) = client.get("/api/v1/cronjobs").json()
    assert antwort["letzter_ausgang"] == "gescheitert"

    pausiert = client.post(f"/api/v1/cronjobs/{eintrag.id}/pause").json()
    assert pausiert["letzter_ausgang"] == "gescheitert"

    (oberste, *_) = _runs_of(client, eintrag.id)
    assert oberste["task"] == "Zuerst eingefügt"


# --- The whole history, entries gone or not ---------------------------------


def test_alle_laeufe_zeigen_auch_die_zu_geloeschten_terminen(client):
    """The runs are the history; the entry only lends them a name.

    Measured on a live installation: 155 runs, zero entries, and a window
    that showed nothing at all — it asked per entry, so a run whose schedule
    had been deleted was gone although it was still in the table.
    """
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    lauf = repositories.auftraege.erstellen(
        user_id="standard", agent="recherche", auftrag="Gelaufen", cronjob_id=eintrag.id
    )
    repositories.auftraege.zustand_setzen(lauf.id, "fertig")
    repositories.cronjobs.loeschen(eintrag.id)

    (uebrig,) = client.get("/api/v1/cronjobs/runs/all").json()
    assert uebrig["task"] == "Gelaufen"
    assert uebrig["status"] == "gut"
    # The row has to be able to name what it deletes: the cross in the
    # history panel deletes through the job route, and without this field
    # there is nothing to hand it.
    assert uebrig["id"] == lauf.id
    assert uebrig["cronjob_id"] == eintrag.id
    # The name is what a deleted entry takes with it — the run's own agent
    # stands in, so the row is never nameless.
    assert uebrig["agent"] == "recherche"
    assert uebrig["skript"] is None


def test_alle_laeufe_tragen_den_namen_des_termins(client):
    """With the entry still there, its own agent and script are what the row
    says — the entry is the better name, the run's is only the fallback."""
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="pruefer", task="Los", zeitplan="08:00", herkunft="chat"
    )
    lauf = repositories.auftraege.erstellen(
        user_id="standard", agent="pruefer", auftrag="Gelaufen", cronjob_id=eintrag.id
    )
    repositories.auftraege.zustand_setzen(lauf.id, "fertig")

    (uebrig,) = client.get("/api/v1/cronjobs/runs/all").json()
    assert uebrig["agent"] == "pruefer"


def test_alle_laeufe_lassen_laufende_und_unterbrochene_aus(client):
    """Same outcome filter the per-entry listing uses: a run still going, or
    one a restart cut off, has no outcome to list yet."""
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    unterbrochener = repositories.auftraege.erstellen(
        user_id="standard", agent="recherche", auftrag="Unterbrochen", cronjob_id=eintrag.id
    )
    repositories.auftraege.zustand_setzen(
        unterbrochener.id, "unterbrochen", ende_grund="dienst_neustart"
    )
    repositories.auftraege.erstellen(
        user_id="standard", agent="recherche", auftrag="Laeuft noch", cronjob_id=eintrag.id
    )
    abgebrochener = repositories.auftraege.erstellen(
        user_id="standard", agent="recherche", auftrag="Abgebrochen", cronjob_id=eintrag.id
    )
    repositories.auftraege.zustand_setzen(
        abgebrochener.id, "abgebrochen", ende_grund="nutzer_abbruch"
    )

    laeufe = client.get("/api/v1/cronjobs/runs/all").json()
    assert [lauf["task"] for lauf in laeufe] == ["Abgebrochen"]
    assert laeufe[0]["status"] == "gescheitert"


def test_alle_laeufe_lassen_laeufe_ohne_termin_aus(client):
    """A run nobody scheduled is not part of the schedules' history."""
    repositories = client.app.state.repositories
    frei = repositories.auftraege.erstellen(
        user_id="standard", agent="recherche", auftrag="Von Hand"
    )
    repositories.auftraege.zustand_setzen(frei.id, "fertig")

    assert client.get("/api/v1/cronjobs/runs/all").json() == []


# --- When the entry is next due ---------------------------------------------
#
# The list said what an entry runs, how it has been doing and when it last
# fired — and left the one question a standing schedule is actually kept for
# to be worked out from the expression by hand. Computed from the schedule on
# every answer rather than stored: the schedule IS the answer, and a column
# beside it would be a second one to keep in step.


def _wann(antwort) -> datetime | None:
    wert = antwort["naechste_faelligkeit"]
    return datetime.fromisoformat(wert) if wert else None


def test_taeglicher_termin_nennt_seine_naechste_faelligkeit(client):
    client.app.state.repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    (zeile,) = client.get("/api/v1/cronjobs").json()
    faellig = _wann(zeile)
    assert faellig is not None
    assert (faellig.hour, faellig.minute) == (8, 0)
    # At or after now, never behind it: a daily time already gone today is
    # tomorrow's, not this morning's.
    assert faellig >= datetime.now(faellig.tzinfo)


def test_cron_ausdruck_nennt_seine_naechste_faelligkeit(client):
    """The shape the mask cannot read for itself — the whole reason the
    server answers this rather than the interface."""
    client.app.state.repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="*/15 * * * *", herkunft="chat"
    )
    (zeile,) = client.get("/api/v1/cronjobs").json()
    faellig = _wann(zeile)
    assert faellig is not None
    assert faellig.minute % 15 == 0
    assert faellig >= datetime.now(faellig.tzinfo)


def test_pausierter_termin_ist_nie_faellig(client):
    """A paused entry has no next due time — the tick skips it, and naming a
    moment it will not run at would be the list saying something untrue."""
    eintrag = client.app.state.repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    pausiert = client.post(f"/api/v1/cronjobs/{eintrag.id}/pause").json()
    assert pausiert["naechste_faelligkeit"] is None
    (aus_der_liste,) = client.get("/api/v1/cronjobs").json()
    assert aus_der_liste["naechste_faelligkeit"] is None

    fortgesetzt = client.post(f"/api/v1/cronjobs/{eintrag.id}/resume").json()
    assert fortgesetzt["naechste_faelligkeit"] is not None


def test_vergangener_einmaliger_termin_ist_nie_wieder_faellig(client):
    """One fixed moment, and it has gone by. Unlike a recurring schedule it
    has no second one, so the answer is nothing rather than a moment in the
    past."""
    client.app.state.repositories.cronjobs.erstellen(
        agent="recherche",
        task="Los",
        zeitplan="09:00",
        herkunft="chat",
        einmalig=True,
        datum="2020-01-01",
    )
    (zeile,) = client.get("/api/v1/cronjobs").json()
    assert zeile["naechste_faelligkeit"] is None


def test_unlesbarer_zeitplan_laesst_die_liste_stehen(client):
    """A row that got in before the shapes were tightened answers with
    nothing. A list that refused to load over one such row would hide the
    entry somebody has to go and fix."""
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    repositories.cronjobs.verbindung.execute(
        "UPDATE cronjobs SET zeitplan = ? WHERE id = ?", ("jeden Montag", eintrag.id)
    )

    antwort = client.get("/api/v1/cronjobs")
    assert antwort.status_code == 200
    (zeile,) = antwort.json()
    assert zeile["naechste_faelligkeit"] is None


# --- A goal nobody has heard about ------------------------------------------
#
# A recurring entry with a goal that runs and reports nothing is the entry
# doing exactly what it is for — and on ``log`` it left no trace anybody
# could see: the notification is off by design, the lamp is green because the
# runs themselves worked, and none of the window's four state lines fits.
# The count the flow itself acts on travels to the mask, raw.


def test_stille_laeufe_stehen_in_der_antwort(client):
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat", ziel="Mail da"
    )
    (frisch,) = client.get("/api/v1/cronjobs").json()
    assert frisch["laeufe_ohne_ruf"] == 0

    repositories.cronjobs.stillen_lauf_zaehlen(eintrag.id)
    repositories.cronjobs.stillen_lauf_zaehlen(eintrag.id)
    (zeile,) = client.get("/api/v1/cronjobs").json()
    assert zeile["laeufe_ohne_ruf"] == 2


def test_gemeldetes_ziel_setzt_die_stillen_laeufe_zurueck(client):
    """The silence test for this one: an entry that has just reported its
    goal is not quiet, and must not carry a count that says it is."""
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat", ziel="Mail da"
    )
    repositories.cronjobs.stillen_lauf_zaehlen(eintrag.id)
    repositories.cronjobs.stille_laeufe_zuruecksetzen(eintrag.id)

    (zeile,) = client.get("/api/v1/cronjobs").json()
    assert zeile["laeufe_ohne_ruf"] == 0


# --- Running an entry by hand -----------------------------------------------
#
# A standing schedule could be switched off, switched on and deleted from this
# window, and the one thing somebody actually wants after setting one up — see
# it run once — had no button anywhere. The run it starts is the run the tick
# would have started: same job row, same entry id on it, so it shows up in the
# entry's own history and its ending counts where every other ending counts.


def test_handstart_startet_einen_lauf_des_termins(config, client):
    from tests.test_auftraege_api import agent_schreiben, auf_ende_warten

    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )

    assert client.post(f"/api/v1/cronjobs/{eintrag.id}/run").status_code == 200

    # The job row carries the entry's id, which is the whole point: that is
    # what puts the run in the entry's own history and what makes its ending
    # count against the entry's failure limit. ``laeufe_fuer_cronjob`` only
    # names ENDED runs, and starting one is fire-and-forget — waited for the
    # fact, not assumed to already be true the moment the response is back.
    frist = time.time() + 8.0
    laeufe: list = []
    while time.time() < frist:
        laeufe = repositories.auftraege.laeufe_fuer_cronjob(eintrag.id)
        if laeufe:
            break
        time.sleep(0.05)
    (lauf,) = laeufe
    auf_ende_warten(client, lauf.id)
    (aus_der_historie,) = _runs_of(client, eintrag.id)
    assert aus_der_historie["id"] == lauf.id
    assert aus_der_historie["task"] == "Los"


def test_handstart_stempelt_die_uhr_des_termins(config, client):
    """What stops the next tick from firing the same past due time again: the
    stamp the tick itself reads (``zuletzt_ausgeloest``)."""
    from tests.test_auftraege_api import agent_schreiben

    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    assert eintrag.zuletzt_ausgeloest is None

    client.post(f"/api/v1/cronjobs/{eintrag.id}/run")
    assert repositories.cronjobs.holen(eintrag.id).zuletzt_ausgeloest is not None


def test_a_hand_start_keeps_a_one_off_whose_moment_is_ahead(config, client):
    """A hand start before a one-off's moment is a trial run: the plan
    stays, and the entry still fires at its moment."""
    import asyncio
    from datetime import datetime, timedelta, timezone

    from tests.test_auftraege_api import agent_schreiben

    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    morgen = datetime.now(timezone.utc) + timedelta(days=1)
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat",
        einmalig=True, datum=morgen.date().isoformat(),
    )

    antwort = client.post(f"/api/v1/cronjobs/{eintrag.id}/run").json()
    assert antwort["aktiv"] is True
    assert repositories.cronjobs.holen(eintrag.id).aktiv is True

    # Let the hand start's run end, then the moment comes: it fires.
    for _ in range(100):
        if not repositories.auftraege.laeuft_fuer_cronjob(eintrag.id):
            break
        asyncio.run(asyncio.sleep(0.05))
    moment = datetime.fromisoformat(f"{morgen.date().isoformat()}T08:00").replace(
        tzinfo=timezone.utc
    ) + timedelta(hours=14)
    asyncio.run(client.app.state.wecker.einmal_pruefen(jetzt=moment))
    assert len(repositories.auftraege.laeufe_fuer_cronjob(eintrag.id)) == 2
    assert repositories.cronjobs.holen(eintrag.id).aktiv is False


def test_a_hand_start_uses_up_a_one_off_whose_moment_has_come(config, client):
    """Silence probe: a one-off whose moment has come and was not served is
    switched off by the start, as before."""
    from datetime import datetime, timedelta, timezone

    from tests.test_auftraege_api import agent_schreiben

    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    gestern = datetime.now(timezone.utc) - timedelta(days=1)
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat",
        einmalig=True, datum=gestern.date().isoformat(),
    )
    repositories.cronjobs.verbindung.execute(
        "UPDATE cronjobs SET created_at = ? WHERE id = ?",
        ((gestern - timedelta(days=1)).isoformat(), eintrag.id),
    )

    antwort = client.post(f"/api/v1/cronjobs/{eintrag.id}/run").json()
    assert antwort["aktiv"] is False
    assert repositories.cronjobs.holen(eintrag.id).aktiv is False


def test_handstart_eines_pausierten_termins_wird_abgewiesen(client):
    """Off means off. Switching it on here instead would be a second thing
    happening behind one press — and it would clear the failure count."""
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    client.post(f"/api/v1/cronjobs/{eintrag.id}/pause")

    antwort = client.post(f"/api/v1/cronjobs/{eintrag.id}/run")
    assert antwort.status_code == 409
    # And nothing happened: no run, and the clock did not move.
    assert repositories.auftraege.laeufe_fuer_cronjob(eintrag.id) == []
    assert repositories.cronjobs.holen(eintrag.id).zuletzt_ausgeloest is None


def test_handstart_ohne_agentendatei_wird_abgewiesen(config, client):
    """The tick leaves this open and tries again — a person pressing a button
    is told instead."""
    from tests.test_auftraege_api import agent_schreiben

    agent_schreiben(config)
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="verschwunden", task="Los", zeitplan="08:00", herkunft="chat"
    )

    antwort = client.post(f"/api/v1/cronjobs/{eintrag.id}/run")
    assert antwort.status_code == 404
    # The refusal names the real agents, the same wording as the direct
    # start (POST /jobs) and the schedule tool's schema.
    assert "recherche" in antwort.json()["detail"]
    assert repositories.cronjobs.holen(eintrag.id).zuletzt_ausgeloest is None


def test_handstart_eines_unbekannten_termins_gibt_404(client):
    assert client.post("/api/v1/cronjobs/phantom/run").status_code == 404


def test_offener_termin_bleibt_die_naechste_faelligkeit(client):
    """A due time that has passed and was never served is what the next tick
    fires — so it is what the list has to name, not tomorrow's. The entry
    whose script was missing at 08:00 runs the moment the file is back."""
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    # Backdated, so today's due time counts as one this entry never served —
    # a fresh entry's own creation is otherwise the baseline.
    repositories.cronjobs.verbindung.execute(
        "UPDATE cronjobs SET created_at = ? WHERE id = ?",
        ("2020-01-01T00:00:00", eintrag.id),
    )

    (zeile,) = client.get("/api/v1/cronjobs").json()
    faellig = datetime.fromisoformat(zeile["naechste_faelligkeit"])
    assert (faellig.hour, faellig.minute) == (8, 0)
    assert faellig <= datetime.now(faellig.tzinfo)


def test_ein_fleissiger_termin_verdraengt_die_laeufe_der_anderen_nicht(client):
    """Five runs per schedule, not a cap for all of them: an older schedule
    whose last run failed still shows it beside its red dot."""
    repositories = client.app.state.repositories
    alt = repositories.cronjobs.erstellen(
        agent="recherche", task="Alt", zeitplan="08:00", herkunft="chat"
    )
    gescheitert = repositories.auftraege.erstellen(
        user_id="standard", agent="recherche", auftrag="Alt", cronjob_id=alt.id
    )
    repositories.auftraege.zustand_setzen(
        gescheitert.id, "gescheitert", ende_grund="anbieter_ausfall"
    )
    fleissig = repositories.cronjobs.erstellen(
        agent="recherche", task="Oft", zeitplan="*/5 * * * *", herkunft="chat"
    )
    for _ in range(7):
        lauf = repositories.auftraege.erstellen(
            user_id="standard", agent="recherche", auftrag="Oft", cronjob_id=fleissig.id
        )
        repositories.auftraege.zustand_setzen(lauf.id, "fertig")

    assert len(_runs_of(client, fleissig.id)) == 5
    (alter_lauf,) = _runs_of(client, alt.id)
    assert alter_lauf["id"] == gescheitert.id
    assert alter_lauf["grund"] == "anbieter_ausfall"
