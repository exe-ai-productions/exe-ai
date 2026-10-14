"""Cron entries in the settings window (app/api/v1/cronjobs.py, 6.7
extension) — list and the on/off switch. Creating stays the tool's job
(app/tools/cronjob.py, tests/test_cronjob_werkzeug.py)."""

from __future__ import annotations

import time
from datetime import datetime

import pytest

from app import cronablauf
from app.providers import MockProvider, mock_endpunkt
from tests.conftest import provider_setzen


@pytest.fixture(autouse=True)
def _no_hand_start_wish(monkeypatch):
    """The wish is the flow's own memory, one per process: each test starts
    without one."""
    monkeypatch.setattr(cronablauf, "_hand_start_wanted", set())


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


def test_row_names_a_missing_agent_with_the_english_field(client):
    """The row says that its agent file is gone under the English field; the
    old German field is no longer sent."""
    eintrag = client.app.state.repositories.cronjobs.erstellen(
        agent="verschwunden", task="Los", zeitplan="08:00", herkunft="chat"
    )
    (zeile,) = client.get("/api/v1/cronjobs").json()
    assert zeile["id"] == eintrag.id
    assert zeile["agent_missing"] is True
    assert "agent_fehlt" not in zeile


def test_row_without_agent_has_no_missing_agent(client):
    """Silence probe: an entry with no agent names no file, so none is missing."""
    from app.no_agent import NAME

    client.app.state.repositories.cronjobs.erstellen(
        agent=NAME, task="Los", zeitplan="08:00", herkunft="chat"
    )
    (zeile,) = client.get("/api/v1/cronjobs").json()
    assert zeile["agent_missing"] is False


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


def _runs_with_clock(repositories, schedules: int, runs_each: int) -> list[str]:
    """``runs_each`` ended runs for each of ``schedules`` schedules, every run
    one minute later than the one before; the run ids, oldest first."""
    ids: list[str] = []
    minute = 0
    for number in range(schedules):
        entry = repositories.cronjobs.erstellen(
            agent="recherche", task=f"Zeitplan {number}", zeitplan="08:00", herkunft="chat"
        )
        for _ in range(runs_each):
            run = repositories.auftraege.erstellen(
                user_id="standard", agent="recherche", auftrag="Gelaufen", cronjob_id=entry.id
            )
            repositories.auftraege.zustand_setzen(run.id, "fertig")
            repositories.auftraege.verbindung.execute(
                "UPDATE auftraege SET created_at = ? WHERE id = ?",
                (f"2026-10-01T{minute // 60:02d}:{minute % 60:02d}:00+00:00", run.id),
            )
            ids.append(run.id)
            minute += 1
    return ids


def test_all_runs_are_at_most_a_hundred_newest_first(client):
    """Thirty schedules with five runs each: a hundred and fifty runs behind
    the per-schedule cap, and the answer carries the hundred newest. It used
    to carry all of them — one more schedule, five more runs, for ever."""
    ids = _runs_with_clock(client.app.state.repositories, schedules=30, runs_each=5)

    runs = client.get("/api/v1/cronjobs/runs/all").json()

    assert len(runs) == 100
    assert [run["id"] for run in runs] == list(reversed(ids))[:100]


def test_all_runs_carry_the_number_of_all_runs_of_their_schedule(client):
    """The page shows five runs of a schedule and counts them as "5/37": the
    number behind the slash is on every run, and it is that schedule's — not
    the five the answer carries, and not a neighbour's."""
    repositories = client.app.state.repositories
    often = repositories.cronjobs.erstellen(
        agent="recherche", task="Oft", zeitplan="* * * * *", herkunft="chat"
    )
    rarely = repositories.cronjobs.erstellen(
        agent="recherche", task="Selten", zeitplan="08:00", herkunft="chat"
    )
    for entry, count in ((often, 37), (rarely, 2)):
        for _ in range(count):
            run = repositories.auftraege.erstellen(
                user_id="standard", agent="recherche", auftrag="Gelaufen",
                cronjob_id=entry.id,
            )
            repositories.auftraege.zustand_setzen(run.id, "fertig")
    # A run that is still going has no outcome and is not counted.
    repositories.auftraege.erstellen(
        user_id="standard", agent="recherche", auftrag="Läuft", cronjob_id=often.id
    )

    runs = client.get("/api/v1/cronjobs/runs/all").json()

    per_schedule = {}
    for run in runs:
        per_schedule.setdefault(run["cronjob_id"], []).append(run)
    assert len(per_schedule[often.id]) == 5
    assert {run["total"] for run in per_schedule[often.id]} == {37}
    assert len(per_schedule[rarely.id]) == 2
    assert {run["total"] for run in per_schedule[rarely.id]} == {2}


def test_all_runs_a_dozen_come_whole(client):
    """Silence probe: a dozen runs of two schedules are all there, as before."""
    _runs_with_clock(client.app.state.repositories, schedules=2, runs_each=6)

    assert len(client.get("/api/v1/cronjobs/runs/all").json()) == 10  # five each


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


# --- A hand start while the model is still coming up -----------------------
#
# The model the entry runs on is the slot's: its server is not running. The
# tick wakes it and waits; a hand start goes the same way and says so.


def _sleeping_slot(client, monkeypatch) -> list[dict]:
    """The one field names a slot model whose server is not running; the
    runner's start is recorded and answers like a start that worked."""
    from tests.conftest import agentenmodell_setzen

    agentenmodell_setzen(client, "klein.gguf", sorte="slot")
    started: list[dict] = []
    runner = client.app.state.agentenrunner
    monkeypatch.setattr(runner, "laeuft", lambda: False)
    monkeypatch.setattr(runner, "starten", lambda modell, **kw: started.append(kw))
    monkeypatch.setattr(runner, "lauf", lambda: None)
    return started


def test_a_hand_start_on_a_sleeping_model_wakes_the_server_and_says_so(
    config, client, monkeypatch
):
    from tests.test_auftraege_api import agent_schreiben

    agent_schreiben(config)
    started = _sleeping_slot(client, monkeypatch)
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )

    # The configuration says German and the interface stands on `auto`: the
    # notice speaks the language the tick takes, whatever the request asks.
    german = client.post(f"/api/v1/cronjobs/{eintrag.id}/run", headers={"Accept-Language": "de"})
    assert german.status_code == 200
    assert german.json()["notice"] == "Das Modell wird gestartet. Der Cronjob läuft, sobald es bereit ist."
    english = client.post(f"/api/v1/cronjobs/{eintrag.id}/run", headers={"Accept-Language": "en"})
    assert english.json()["notice"] == german.json()["notice"]

    # The server was woken, no run exists yet, and the entry has not booked a
    # start: the tick does that when the model answers.
    assert started
    assert repositories.auftraege.laeufe_fuer_cronjob(eintrag.id) == []
    assert not repositories.auftraege.laeuft_fuer_cronjob(eintrag.id)
    assert repositories.cronjobs.holen(eintrag.id).zuletzt_ausgeloest is None
    assert eintrag.id in cronablauf._hand_start_wanted


def _hand_start_language(client, monkeypatch, *, interface: str | None, header: str) -> str:
    """The language a hand start's run is started with — and, as a side
    effect the callers read, what the entry's rejections speak."""
    from app import sprachwahl
    from app.api.v1 import cronjobs as cronjobs_api
    from tests.test_auftraege_api import agent_schreiben

    agent_schreiben(client.app.state.config)
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    client.app.state.config.app.language = "de"
    repositories = client.app.state.repositories
    if interface is not None:
        repositories.einstellungen.setzen(
            "global", sprachwahl.SCHLUESSEL, {"sprache": interface}
        )
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    started: list[str] = []
    monkeypatch.setattr(
        cronjobs_api, "auftrag_anstossen", lambda **felder: started.append(felder["sprache"])
    )
    antwort = client.post(
        f"/api/v1/cronjobs/{eintrag.id}/run", headers={"Accept-Language": header}
    )
    assert antwort.status_code == 200, antwort.text
    return started[0]


def test_a_hand_start_takes_the_language_of_the_tick_not_of_the_request(client, monkeypatch):
    """The interface stands on `auto`, the configuration says German, the
    request asks for English: the run gets German, like the same entry's
    due time (app/wecker.py)."""
    assert _hand_start_language(client, monkeypatch, interface="auto", header="en") == "de"


def test_a_hand_start_follows_a_language_chosen_for_the_interface(client, monkeypatch):
    """Silence probe: a chosen interface language holds for hand and tick
    alike, whatever the request header says."""
    assert _hand_start_language(client, monkeypatch, interface="en", header="de") == "en"


def test_a_hand_start_with_a_matching_request_changes_nothing(client, monkeypatch):
    """Silence probe: request and tick agree, the run gets that language."""
    assert _hand_start_language(client, monkeypatch, interface=None, header="de") == "de"


def test_a_refusal_of_a_hand_start_speaks_the_language_of_the_tick(client):
    """A paused entry is refused in the tick's language — German here —
    although the request asks for English."""
    from app.i18n import t

    eintrag = client.app.state.repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    client.app.state.repositories.cronjobs.aktiv_setzen(eintrag.id, False)
    antwort = client.post(
        f"/api/v1/cronjobs/{eintrag.id}/run", headers={"Accept-Language": "en"}
    )
    assert antwort.status_code == 409
    assert antwort.json()["detail"] == t("fehler.cronjob_pausiert", "de")
    assert t("fehler.cronjob_pausiert", "de") != t("fehler.cronjob_pausiert", "en")


def test_a_hand_start_on_a_model_that_answers_runs_at_once_without_a_notice(config, client):
    from tests.test_auftraege_api import agent_schreiben

    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )

    antwort = client.post(f"/api/v1/cronjobs/{eintrag.id}/run")
    assert antwort.status_code == 200
    assert antwort.json()["notice"] is None
    assert repositories.cronjobs.holen(eintrag.id).zuletzt_ausgeloest is not None


def test_a_hand_start_with_no_server_the_program_can_start_is_refused_as_before(
    config, client
):
    """Silence probe: the one field names a model that is not there at all —
    no slot, nothing to wake. The refusal stays a refusal, and no wish is
    left behind for the tick."""
    from tests.conftest import agentenmodell_setzen
    from tests.test_auftraege_api import agent_schreiben

    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    agentenmodell_setzen(client, "wolke:gibtsnicht")
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )

    antwort = client.post(f"/api/v1/cronjobs/{eintrag.id}/run")
    assert antwort.status_code >= 400
    assert "notice" not in antwort.json()
    assert eintrag.id not in cronablauf._hand_start_wanted
    assert repositories.cronjobs.holen(eintrag.id).zuletzt_ausgeloest is None


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


# --- The agent an entry names: missing, broken, spelled differently ----------


def _write_agent(config, name, text="---\n---\n\nPrompt.\n"):
    from pathlib import Path

    folder = Path(config.app.agenten_verzeichnis)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.md").write_text(text, encoding="utf-8")


BROKEN_AGENT = "---\nmodel: [unclosed\n---\n\nPrompt.\n"


def _row(client, entry_id):
    return {z["id"]: z for z in client.get("/api/v1/cronjobs").json()}[entry_id]


def test_an_agent_spelled_with_capitals_is_not_missing(config, client):
    """The tick finds an agent regardless of capitals; the row says "missing"
    by the same finder, not by an exact comparison of the stored word."""
    _write_agent(config, "mein-agent")
    entry = client.app.state.repositories.cronjobs.erstellen(
        agent="Mein-Agent", task="Los", zeitplan="08:00", herkunft="chat"
    )
    row = _row(client, entry.id)
    assert row["agent_missing"] is False
    assert row["agent_broken"] is False
    # Silence probe: an agent no file stands behind is still missing.
    other = client.app.state.repositories.cronjobs.erstellen(
        agent="gibt-es-nicht", task="Los", zeitplan="08:00", herkunft="chat"
    )
    assert _row(client, other.id)["agent_missing"] is True


def test_a_broken_agent_file_is_broken_not_missing(config, client):
    _write_agent(config, "kaputt", BROKEN_AGENT)
    entry = client.app.state.repositories.cronjobs.erstellen(
        agent="kaputt", task="Los", zeitplan="08:00", herkunft="chat"
    )
    row = _row(client, entry.id)
    assert row["agent_missing"] is False
    assert row["agent_broken"] is True
    # The line the YAML reader names (the second line of the file, where the
    # unclosed bracket stands), and nothing of the reader's own message.
    assert row["agent_broken_line"] == 2
    assert "kaputt.md" not in str(row)


def test_a_broken_agent_names_the_line_of_the_file_the_reader_names(config, client):
    """Line four of the file, not line three of the header and not the
    reader's three lines of message."""
    _write_agent(config, "vier", "---\ntools: []\nmax_rounds: 3\nmodel: [unclosed\n---\n\nPrompt.\n")
    entry = client.app.state.repositories.cronjobs.erstellen(
        agent="vier", task="Los", zeitplan="08:00", herkunft="chat"
    )

    row = _row(client, entry.id)

    assert row["agent_broken"] is True
    assert row["agent_broken_line"] == 4


def test_a_broken_agent_without_a_line_says_it_without_one(config, client):
    """Silence probe: a header that is no list of fields has no line of its
    own — the row is still broken, with no line."""
    _write_agent(config, "ohne-zeile", "---\n- a\n- b\n---\n\nPrompt.\n")
    entry = client.app.state.repositories.cronjobs.erstellen(
        agent="ohne-zeile", task="Los", zeitplan="08:00", herkunft="chat"
    )

    row = _row(client, entry.id)

    assert row["agent_broken"] is True
    assert row["agent_broken_line"] is None


def test_a_paused_entry_shows_no_agent_trouble(config, client):
    """The live states belong to an entry that is switched on."""
    repositories = client.app.state.repositories
    _write_agent(config, "kaputt", BROKEN_AGENT)
    missing = repositories.cronjobs.erstellen(
        agent="gibt-es-nicht", task="Los", zeitplan="08:00", herkunft="chat"
    )
    broken = repositories.cronjobs.erstellen(
        agent="kaputt", task="Los", zeitplan="08:00", herkunft="chat"
    )
    assert _row(client, missing.id)["agent_missing"] is True
    for entry in (missing, broken):
        client.post(f"/api/v1/cronjobs/{entry.id}/pause")
    for entry in (missing, broken):
        row = _row(client, entry.id)
        assert row["aktiv"] is False
        assert row["agent_missing"] is False
        assert row["agent_broken"] is False
    # Silence probe: switched on again, the row says it again.
    client.post(f"/api/v1/cronjobs/{missing.id}/resume")
    assert _row(client, missing.id)["agent_missing"] is True


def test_changing_one_entry_reads_no_agent_directory(config, client, monkeypatch):
    """Pausing, resuming or changing one entry asks for ITS agent only; the
    whole directory is read by the list alone."""
    from app.api.v1 import cronjobs as route

    _write_agent(config, "da")
    entry = client.app.state.repositories.cronjobs.erstellen(
        agent="da", task="Los", zeitplan="08:00", herkunft="chat"
    )
    reads = []
    original = route.agenten_laden

    def counting(*folders):
        reads.append(folders)
        return original(*folders)

    monkeypatch.setattr(route, "agenten_laden", counting)
    assert client.post(f"/api/v1/cronjobs/{entry.id}/pause").status_code == 200
    assert client.post(f"/api/v1/cronjobs/{entry.id}/resume").status_code == 200
    assert reads == []
    # Silence probe: the list reads the directory once and shows the state.
    client.get("/api/v1/cronjobs")
    assert len(reads) == 1


def test_an_old_entry_naming_a_gone_agent_can_be_changed_to_no_agent(config, client):
    """The agent of a schedule from before the rebuild is gone and cannot be
    named again; the form must be able to send it to "no agent"."""
    from app.no_agent import NAME

    repositories = client.app.state.repositories
    entry = repositories.cronjobs.erstellen(
        agent="erinnerung", task="Los", zeitplan="08:00", herkunft="chat"
    )
    assert _row(client, entry.id)["agent_missing"] is True

    antwort = client.patch(f"/api/v1/cronjobs/{entry.id}", json={"agent": ""})
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["agent"] == NAME
    assert antwort.json()["agent_missing"] is False
    assert repositories.cronjobs.holen(entry.id).agent == NAME


def test_changing_to_an_existing_agent_works_as_before(config, client):
    """Silence probe for the change above: a named agent is still looked up,
    and an unknown name is still refused."""
    _write_agent(config, "neu")
    repositories = client.app.state.repositories
    entry = repositories.cronjobs.erstellen(
        agent="erinnerung", task="Los", zeitplan="08:00", herkunft="chat"
    )
    assert client.patch(f"/api/v1/cronjobs/{entry.id}", json={"agent": "Neu"}).json()["agent"] == "neu"
    assert client.patch(f"/api/v1/cronjobs/{entry.id}", json={"agent": "gibt-es-nicht"}).status_code == 400


def test_the_single_lookup_finds_what_the_whole_directory_finds(config):
    """The row asks for one agent's file only, the tick reads them all: the
    two must agree on every spelling, a broken file and a missing name."""
    from app.agenten import agent_lookup, agenten_laden

    _write_agent(config, "alpha")
    _write_agent(config, "Beta")
    _write_agent(config, "kaputt", BROKEN_AGENT)
    folders = config.agentenverzeichnisse
    loaded = agenten_laden(*folders)
    for name in ("alpha", "ALPHA", "beta", "Beta", "kaputt", "Kaputt", "nix", ""):
        agent, broken = agent_lookup(name, *folders)
        assert (agent is not None) == (name in loaded), name
        assert (broken is not None) == (name.casefold() == "kaputt"), name


# --- the service announces every change of a schedule ------------------------


@pytest.fixture
def announced():
    """The ids of every CRON_CHANGED the bus carries while the test runs."""
    from app.events import Ereignisse, bus

    seen: list[str] = []

    def collect(cronjob_id: str = "", **_rest) -> None:
        seen.append(cronjob_id)

    bus.abonnieren(Ereignisse.CRON_CHANGED, collect)
    yield seen
    bus.abbestellen(Ereignisse.CRON_CHANGED, collect)


def _arrived(seen: list[str], count: int, timeout: float = 5.0) -> list[str]:
    """Waits for ``count`` announcements: the route fires from a worker
    thread and the bus hands them to the service's loop."""
    deadline = time.monotonic() + timeout
    while len(seen) < count and time.monotonic() < deadline:
        time.sleep(0.01)
    return list(seen)


def _probe(client, seen: list[str]) -> list[str]:
    """Pauses a real entry and waits for its announcement. Announcements
    reach the loop in the order they were fired, so what was not announced
    before the probe never is."""
    probe = client.app.state.repositories.cronjobs.erstellen(
        agent="probe", task="Los", zeitplan="23:59", herkunft="chat"
    )
    before = len(seen)
    assert client.post(f"/api/v1/cronjobs/{probe.id}/pause").status_code == 200
    got = _arrived(seen, before + 1)
    assert got[-1] == probe.id
    return got[:-1]


def test_every_change_of_a_schedule_is_announced_once_with_its_id(client, announced):
    """Made, changed, paused, resumed, removed: one announcement each, never
    two — made and changed go through the tool, which says so itself."""
    made = client.post("/api/v1/cronjobs", json={"zeitplan": "08:00", "task": "Los"})
    assert made.status_code == 201
    entry_id = made.json()["id"]
    assert _arrived(announced, 1) == [entry_id]

    assert client.patch(f"/api/v1/cronjobs/{entry_id}", json={"zeitplan": "09:00"}).status_code == 200
    assert _arrived(announced, 2) == [entry_id] * 2

    assert client.post(f"/api/v1/cronjobs/{entry_id}/pause").status_code == 200
    assert client.post(f"/api/v1/cronjobs/{entry_id}/resume").status_code == 200
    assert client.delete(f"/api/v1/cronjobs/{entry_id}").status_code == 204
    assert _arrived(announced, 5) == [entry_id] * 5
    time.sleep(0.2)
    assert announced == [entry_id] * 5


def test_a_change_that_did_not_take_is_not_announced(config, client, announced):
    """Silence probe: an unknown id, a refused change and a hand start write
    no schedule and say nothing."""
    from tests.test_auftraege_api import agent_schreiben, auf_ende_warten

    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    entry = client.app.state.repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    assert client.post("/api/v1/cronjobs/phantom/pause").status_code == 404
    assert client.post("/api/v1/cronjobs/phantom/resume").status_code == 404
    assert client.delete("/api/v1/cronjobs/phantom").status_code == 404
    assert client.patch("/api/v1/cronjobs/phantom", json={"zeitplan": "09:00"}).status_code == 404
    assert client.patch(f"/api/v1/cronjobs/{entry.id}", json={"zeitplan": "not a time"}).status_code == 400
    assert client.post("/api/v1/cronjobs", json={"zeitplan": "not a time", "task": "x"}).status_code == 400
    assert client.post(f"/api/v1/cronjobs/{entry.id}/run").status_code == 200
    # Fire-and-forget: wait for the run the start made, so that its ending
    # is behind us before the probe.
    repositories = client.app.state.repositories
    deadline = time.time() + 8.0
    runs: list = []
    while not runs and time.time() < deadline:
        runs = repositories.auftraege.laeufe_fuer_cronjob(entry.id)
        time.sleep(0.05)
    assert runs
    auf_ende_warten(client, runs[0].id)
    assert client.get("/api/v1/cronjobs").status_code == 200
    assert _probe(client, announced) == []


def test_a_schedule_that_fires_is_announced_as_fired_and_not_as_changed(client, announced):
    """Silence probe: what a firing reports stays what it was — the entry's
    own clock moved, no one changed the schedule."""
    from app.events import Ereignisse, bus

    fired: list[str] = []

    def collect(cronjob_id: str = "", **_rest) -> None:
        fired.append(cronjob_id)

    bus.abonnieren(Ereignisse.TERMIN_GEFEUERT, collect)
    try:
        repositories = client.app.state.repositories
        entry = repositories.cronjobs.erstellen(
            agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
        )
        cronablauf._ausgeloest_merken(repositories, entry.id, "2026-10-13T08:00:00+02:00")
        assert _arrived(fired, 1) == [entry.id]
    finally:
        bus.abbestellen(Ereignisse.TERMIN_GEFEUERT, collect)
    assert _probe(client, announced) == []
