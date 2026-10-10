"""Firing due cron entries (app/cronablauf.py) — the general,
user-created table. This is the only way a schedule fires at
all: an agent's own ``schedule:`` front-matter field is retired, and the tick
that drives this module (``Wecker.einmal_pruefen``, tests/test_wecker.py)
does nothing else.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import cronablauf
from app.ohne_agent import NAME as OHNE_AGENT
from app import fenstergroesse
from app.providers import MockProvider, mock_endpunkt
from tests.conftest import agentenmodell_setzen, provider_setzen


def schreiben(ordner: Path, name: str, inhalt: str = "---\n---\n\nPrompt.\n") -> None:
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / f"{name}.md").write_text(inhalt, encoding="utf-8")


def pruefen(client, jetzt: datetime) -> None:
    asyncio.run(client.app.state.wecker.einmal_pruefen(jetzt=jetzt))


def auftraege_von(client, agent: str) -> list[dict]:
    return [a for a in client.get("/api/v1/jobs").json() if a["agent"] == agent]


MORGEN_13 = datetime.now(timezone.utc).replace(
    hour=13, minute=0, second=0, microsecond=0
) + timedelta(days=1)


# --- A fresh entry must not fire the instant it is created -----------------


def test_frisch_angelegter_termin_wartet_bis_zum_eigenen_termin(config, client):
    """Created at 14:00 for a daily 08:00 — the 08:00 slot already lies in
    the past for today, and without a baseline that past due time would
    fire within the very next tick instead of waiting for tomorrow."""
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    heute_14 = MORGEN_13.replace(hour=14) - timedelta(days=1)
    repositories.cronjobs.verbindung.execute(
        "UPDATE cronjobs SET created_at = ? WHERE id = ?",
        (heute_14.isoformat(), eintrag.id),
    )

    pruefen(client, heute_14 + timedelta(minutes=1))
    assert auftraege_von(client, "recherche") == []

    pruefen(client, MORGEN_13.replace(hour=8, minute=1))
    assert len(auftraege_von(client, "recherche")) == 1


def test_frisch_angelegter_termin_fuer_spaeter_heute_feuert_nicht_sofort(config, client):
    """Created at 14:00 for a daily 22:00 — ``letzter_termin`` resolves that
    to YESTERDAY 22:00 (today's has not come yet), which is just as past
    as the previous case and must be caught the same way."""
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="22:00", herkunft="chat"
    )
    heute_14 = MORGEN_13.replace(hour=14) - timedelta(days=1)
    repositories.cronjobs.verbindung.execute(
        "UPDATE cronjobs SET created_at = ? WHERE id = ?",
        (heute_14.isoformat(), eintrag.id),
    )

    pruefen(client, heute_14 + timedelta(minutes=1))
    assert auftraege_von(client, "recherche") == []

    pruefen(client, heute_14.replace(hour=22, minute=1))
    assert len(auftraege_von(client, "recherche")) == 1


# --- Closing the loop with a context-full handoff --------------


def test_zwischenstand_cronjob_feuert_und_traegt_den_status_weiter(config, client):
    """What a context-full handoff (app/zwischenstand.py) leaves behind — an
    entry whose task carries the previous run's status — fires exactly like
    any other cron entry and starts the follow-up run with that status."""
    from app import zwischenstand

    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    status = "## Task\nx\n\n## Done\n- eins\n\n## Next\nweiter"
    aufgabe = zwischenstand.naechste_aufgabe("Los", status)
    client.app.state.repositories.cronjobs.erstellen(
        agent="recherche", task=aufgabe, zeitplan="12:00", herkunft="agent"
    )

    pruefen(client, MORGEN_13)

    (auftrag,) = auftraege_von(client, "recherche")
    assert "Los" in auftrag["task"]
    assert status in auftrag["task"]


def test_faelliger_cronjob_startet_einen_auftrag(config, client):
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    client.app.state.repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="12:00", herkunft="chat"
    )

    pruefen(client, MORGEN_13)
    assert len(auftraege_von(client, "recherche")) == 1


def test_derselbe_termin_feuert_nicht_zweimal(config, client):
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    client.app.state.repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="12:00", herkunft="chat"
    )

    pruefen(client, MORGEN_13)
    pruefen(client, MORGEN_13)
    pruefen(client, MORGEN_13 + timedelta(minutes=30))
    assert len(auftraege_von(client, "recherche")) == 1


def test_pausierter_cronjob_feuert_nicht(config, client):
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="12:00", herkunft="chat"
    )
    repositories.cronjobs.aktiv_setzen(eintrag.id, False)

    pruefen(client, MORGEN_13)
    assert auftraege_von(client, "recherche") == []


def test_laufender_agent_wird_uebersprungen(config, client):
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="12:00", herkunft="chat"
    )
    repositories.auftraege.erstellen(
        user_id="standard", agent="recherche", auftrag="läuft noch", zustand="laeuft"
    )

    pruefen(client, MORGEN_13)
    assert len(auftraege_von(client, "recherche")) == 1  # only the pre-existing one


def test_fehlender_agent_bleibt_offen_und_stuerzt_nicht(config, client):
    client.app.state.repositories.cronjobs.erstellen(
        agent="phantom", task="Los", zeitplan="12:00", herkunft="chat"
    )

    pruefen(client, MORGEN_13)  # must not raise
    assert auftraege_von(client, "phantom") == []


def test_cronjob_ohne_agent_feuert_ohne_agentendatei(config, client):
    """An entry with no agent needs no file: it fires with the run built in
    memory (app/ohne_agent.py)."""
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    client.app.state.repositories.cronjobs.erstellen(
        agent=OHNE_AGENT, task="Kaffee", zeitplan="12:00", herkunft="chat"
    )

    pruefen(client, MORGEN_13)
    assert len(auftraege_von(client, OHNE_AGENT)) == 1


def test_zwei_cronjobs_ohne_agent_warten_nicht_aufeinander(config, client):
    """Every entry without an agent carries the same marker; asked by name,
    the second would wait for the first. Each asks about its own run."""
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    for task in ("Kaffee", "Tee"):
        client.app.state.repositories.cronjobs.erstellen(
            agent=OHNE_AGENT, task=task, zeitplan="12:00", herkunft="chat"
        )

    pruefen(client, MORGEN_13)
    assert len(auftraege_von(client, OHNE_AGENT)) == 2


def test_fehlender_agent_steht_am_eintrag(config, client):
    """A named agent whose file is gone: the settings row says so at once,
    not only after a due time, and the tick starts no run."""
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    eintrag = client.app.state.repositories.cronjobs.erstellen(
        agent="verschwunden", task="Los", zeitplan="12:00", herkunft="chat"
    )
    zeilen = {z["id"]: z for z in client.get("/api/v1/cronjobs").json()}
    assert zeilen[eintrag.id]["agent_fehlt"] is True

    pruefen(client, MORGEN_13)
    assert auftraege_von(client, "verschwunden") == []
    zeilen = {z["id"]: z for z in client.get("/api/v1/cronjobs").json()}
    assert zeilen[eintrag.id]["agent_fehlt"] is True


def test_ohne_agent_fehlt_kein_agent(config, client):
    """Silence test: an entry with no agent names no file, so none is missing."""
    eintrag = client.app.state.repositories.cronjobs.erstellen(
        agent=OHNE_AGENT, task="Los", zeitplan="12:00", herkunft="chat"
    )
    zeilen = {z["id"]: z for z in client.get("/api/v1/cronjobs").json()}
    assert zeilen[eintrag.id]["agent_fehlt"] is False


def test_vorhandener_agent_fehlt_nicht(config, client):
    """Silence test: an entry whose agent is there never says it is missing."""
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    schreiben(Path(config.app.agenten_verzeichnis), "da")
    eintrag = client.app.state.repositories.cronjobs.erstellen(
        agent="da", task="Los", zeitplan="12:00", herkunft="chat"
    )

    pruefen(client, MORGEN_13)
    zeilen = {z["id"]: z for z in client.get("/api/v1/cronjobs").json()}
    assert zeilen[eintrag.id]["agent_fehlt"] is False


def test_nur_die_crontabelle_feuert(config, client):
    """The tick fires the cron table and nothing else. The other half of
    this test used to be an agent's own ``schedule:`` field firing beside
    it — retired, and kept here as the counter-example: the file
    below names the same 12:00 and stays quiet."""
    schreiben(
        Path(config.app.agenten_verzeichnis), "news",
        '---\nmodel: test\nschedule: "12:00"\nschedule_task: "Nachrichten"\n---\n\nPrompt.\n',
    )
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    client.app.state.repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="12:00", herkunft="chat"
    )

    pruefen(client, MORGEN_13)
    assert auftraege_von(client, "news") == []
    assert len(auftraege_von(client, "recherche")) == 1


# --- A one-off reminder fires once, a daily one keeps going ----


def test_einmaliger_cronjob_feuert_und_wird_inaktiv(config, client):
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Water the plants", zeitplan="12:00",
        herkunft="chat", einmalig=True,
    )

    pruefen(client, MORGEN_13)
    assert len(auftraege_von(client, "recherche")) == 1
    assert repositories.cronjobs.holen(eintrag.id).aktiv is False

    # The next day's same due time must not fire it again — it is inactive.
    pruefen(client, MORGEN_13 + timedelta(days=1))
    assert len(auftraege_von(client, "recherche")) == 1


def test_taeglicher_cronjob_bleibt_nach_dem_feuern_aktiv(config, client):
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="12:00", herkunft="chat",
    )

    pruefen(client, MORGEN_13)
    assert repositories.cronjobs.holen(eintrag.id).aktiv is True

    pruefen(client, MORGEN_13 + timedelta(days=1))
    assert len(auftraege_von(client, "recherche")) == 2


def test_uebersprungener_einmaliger_cronjob_bleibt_aktiv(config, client):
    """Skipped because a run was still active — never actually fired, so it
    keeps its chance instead of being silently lost."""
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="12:00", herkunft="chat", einmalig=True,
    )
    repositories.auftraege.erstellen(
        user_id="standard", agent="recherche", auftrag="läuft noch", zustand="laeuft"
    )

    pruefen(client, MORGEN_13)
    assert len(auftraege_von(client, "recherche")) == 1  # only the pre-existing one
    assert repositories.cronjobs.holen(eintrag.id).aktiv is True


def test_ein_uebersprungener_datierter_termin_wird_nachgeholt(config, client):
    """Skipped because a run was still going — and then caught up, the
    moment nothing is running any more: a missed run is meant to be caught
    up, not skipped.

    A dated one-off has no next occurrence. Stamping its due time on the
    skip made it count as fired, and the run the user asked for never
    happened at all.
    """
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Water the plants", zeitplan="12:00",
        herkunft="chat", einmalig=True, datum=MORGEN_13.date().isoformat(),
    )
    laufend = repositories.auftraege.erstellen(
        user_id="standard", agent="recherche", auftrag="läuft noch", zustand="laeuft"
    )

    # The moment is due, but the agent is busy: nothing is started, and the
    # entry keeps its chance.
    pruefen(client, MORGEN_13)
    assert len(auftraege_von(client, "recherche")) == 1  # only the pre-existing one
    assert repositories.cronjobs.holen(eintrag.id).zuletzt_ausgeloest is None

    # The run ends, the next pass comes — and now it fires.
    repositories.auftraege.zustand_setzen(laufend.id, "fertig")
    pruefen(client, MORGEN_13 + timedelta(minutes=1))

    assert len(auftraege_von(client, "recherche")) == 2
    assert repositories.cronjobs.holen(eintrag.id).aktiv is False


def test_ein_uebersprungener_zeitpunkt_termin_wird_nachgeholt(config, client):
    """The MAIN spelling of a one-off: an instant schedule, no `datum` at
    all. It has no next moment either, and asking only "is it dated" left
    exactly this form stamped and dead — the defect the fix is for."""
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Water the plants",
        zeitplan=MORGEN_13.strftime("%Y-%m-%dT%H:%M"), herkunft="chat", einmalig=True,
    )
    laufend = repositories.auftraege.erstellen(
        user_id="standard", agent="recherche", auftrag="läuft noch", zustand="laeuft"
    )

    pruefen(client, MORGEN_13)
    assert len(auftraege_von(client, "recherche")) == 1
    assert repositories.cronjobs.holen(eintrag.id).zuletzt_ausgeloest is None

    repositories.auftraege.zustand_setzen(laufend.id, "fertig")
    pruefen(client, MORGEN_13 + timedelta(minutes=1))

    assert len(auftraege_von(client, "recherche")) == 2
    assert repositories.cronjobs.holen(eintrag.id).aktiv is False


def test_ein_uebersprungener_einmaliger_ohne_datum_wird_nachgeholt(config, client):
    """`einmalig` with a plain daily time and no date. It does have a next
    occurrence tomorrow — but the user asked for ONE, and firing it a day
    late is not what "as soon as free" means."""
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="12:00", herkunft="chat", einmalig=True,
    )
    laufend = repositories.auftraege.erstellen(
        user_id="standard", agent="recherche", auftrag="läuft noch", zustand="laeuft"
    )

    pruefen(client, MORGEN_13)
    assert repositories.cronjobs.holen(eintrag.id).zuletzt_ausgeloest is None

    repositories.auftraege.zustand_setzen(laufend.id, "fertig")
    pruefen(client, MORGEN_13 + timedelta(minutes=1))

    assert len(auftraege_von(client, "recherche")) == 2


def test_auch_ein_skript_termin_wird_nachgeholt(config, client):
    """The script path asks a different question — `laeuft_fuer_cronjob`
    instead of `laeuft_gerade` — and goes through the same new booking. A
    one-off script entry must be caught up just like an agent one."""
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="skript", task="Sicherung", zeitplan="12:00", herkunft="chat",
        einmalig=True, datum=MORGEN_13.date().isoformat(), skript="sicherung.sh",
    )
    repositories.auftraege.erstellen(
        user_id="standard", agent="skript", auftrag="läuft noch",
        zustand="laeuft", cronjob_id=eintrag.id,
    )

    pruefen(client, MORGEN_13)

    # Skipped, and — this is the point — not stamped: its one moment is
    # still owed.
    assert repositories.cronjobs.holen(eintrag.id).zuletzt_ausgeloest is None
    assert repositories.cronjobs.holen(eintrag.id).aktiv is True


def test_die_uebersprungen_zeile_steht_einmal_je_moment(config, client, caplog):
    """Without the stamp the entry reaches the skip branch on every pass. A
    four-hour run would otherwise leave some five hundred identical lines —
    the same rule the module keeps for a missing script."""
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    repositories.cronjobs.erstellen(
        agent="recherche", task="Water the plants", zeitplan="12:00",
        herkunft="chat", einmalig=True, datum=MORGEN_13.date().isoformat(),
    )
    repositories.auftraege.erstellen(
        user_id="standard", agent="recherche", auftrag="läuft noch", zustand="laeuft"
    )

    with caplog.at_level("INFO", logger="app.cronablauf"):
        for minute in range(4):
            pruefen(client, MORGEN_13 + timedelta(minutes=minute))

    gesagt = [
        r for r in caplog.records
        if getattr(r, "ereignis", None) == "cronjob_uebersprungen"
    ]
    assert len(gesagt) == 1


def test_ein_uebersprungener_taeglicher_termin_holt_nichts_nach(config, client):
    """The silence probe: a recurring entry has a NEXT occurrence, so the
    skipped one stays spent. Catching it up would fire yesterday's task
    today, late and unasked for."""
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="12:00", herkunft="chat",
    )
    laufend = repositories.auftraege.erstellen(
        user_id="standard", agent="recherche", auftrag="läuft noch", zustand="laeuft"
    )

    pruefen(client, MORGEN_13)
    assert len(auftraege_von(client, "recherche")) == 1
    assert repositories.cronjobs.holen(eintrag.id).zuletzt_ausgeloest is not None

    repositories.auftraege.zustand_setzen(laufend.id, "fertig")
    pruefen(client, MORGEN_13 + timedelta(minutes=1))

    # Still only the pre-existing one: today's due time is spent.
    assert len(auftraege_von(client, "recherche")) == 1


# --- A dated one-off entry fires on its own day, not a recurring time ------
#


def test_datierter_cronjob_feuert_nicht_vor_seinem_datum(config, client):
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    repositories.cronjobs.erstellen(
        agent="recherche", task="Water the plants", zeitplan="12:00",
        herkunft="chat", einmalig=True, datum=MORGEN_13.date().isoformat(),
    )

    # Same time of day, a week before the entry's own date.
    pruefen(client, MORGEN_13 - timedelta(days=7))
    assert auftraege_von(client, "recherche") == []


def test_datierter_cronjob_feuert_am_eigenen_tag_und_wird_inaktiv(config, client):
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Water the plants", zeitplan="12:00",
        herkunft="chat", einmalig=True, datum=MORGEN_13.date().isoformat(),
    )

    pruefen(client, MORGEN_13)
    assert len(auftraege_von(client, "recherche")) == 1
    assert repositories.cronjobs.holen(eintrag.id).aktiv is False

    # The same time the next day must not fire it again — it is inactive,
    # and even if it were not, the date has already passed.
    pruefen(client, MORGEN_13 + timedelta(days=1))
    assert len(auftraege_von(client, "recherche")) == 1


def test_ein_stehengebliebenes_datum_wird_bei_nicht_einmaligen_terminen_ignoriert(config, client):
    """'datum' only ever applies together
    with 'einmalig' — a stale one left behind on an entry that is daily
    again must not pin it to a single day that has long since passed."""
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="12:00", herkunft="chat",
        einmalig=True, datum=(MORGEN_13 - timedelta(days=30)).date().isoformat(),
    )
    # A direct repository call, deliberately leaving 'datum' behind — this
    # exercises the firing loop's own guard, not the tool's write-side fix.
    repositories.cronjobs.aktualisieren(eintrag.id, einmalig=False)
    assert repositories.cronjobs.holen(eintrag.id).datum is not None

    pruefen(client, MORGEN_13)
    assert len(auftraege_von(client, "recherche")) == 1
    assert repositories.cronjobs.holen(eintrag.id).aktiv is True

    pruefen(client, MORGEN_13 + timedelta(days=1))
    assert len(auftraege_von(client, "recherche")) == 2


# --- Announcing a finished run ----------------------------------
# Firing and finishing happen in different places (see app/cronablauf.py's
# ``melde_wenn_faellig`` docstring) — these check the reading of ``deliver``
# and the passed-through outcome in isolation, with ``cronmeldung.melden``
# swapped out so nothing actually plays a sound or pops up a notification
# during the test run.


async def test_meldet_nur_bei_deliver_announce(repos, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(
        cronablauf.cronmeldung, "melden",
        lambda text, *, erfolgreich: aufrufe.append((text, erfolgreich)),
    )

    still = repos.cronjobs.erstellen(agent="a", task="x", zeitplan="08:00", herkunft="chat")
    await cronablauf.melde_wenn_faellig(repos, still.id, "Plant reminder")
    assert aufrufe == []

    ansage = repos.cronjobs.erstellen(
        agent="a", task="x", zeitplan="08:00", herkunft="chat", deliver="announce"
    )
    await cronablauf.melde_wenn_faellig(repos, ansage.id, "Plant reminder")
    assert aufrufe == [("Plant reminder", True)]


async def test_gescheiterter_lauf_meldet_sich_auch(repos, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(
        cronablauf.cronmeldung, "melden",
        lambda text, *, erfolgreich: aufrufe.append((text, erfolgreich)),
    )
    ansage = repos.cronjobs.erstellen(
        agent="a", task="x", zeitplan="08:00", herkunft="chat", deliver="announce"
    )
    await cronablauf.melde_wenn_faellig(
        repos, ansage.id, "Plant reminder", erfolgreich=False
    )
    assert aufrufe == [("Plant reminder", False)]


async def test_ohne_cronjob_id_passiert_nichts(repos, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(
        cronablauf.cronmeldung, "melden",
        lambda text, *, erfolgreich: aufrufe.append((text, erfolgreich)),
    )
    await cronablauf.melde_wenn_faellig(repos, None, "Plant reminder")
    assert aufrufe == []


async def test_geloeschter_cronjob_passiert_nichts(repos, monkeypatch):
    """A job the DELETE route stopped and removed while it was still
    running — the same gap the ``auftraege.holen(...) is not None`` guard
    around the whole finally block covers already, just for this call too."""
    aufrufe = []
    monkeypatch.setattr(
        cronablauf.cronmeldung, "melden",
        lambda text, *, erfolgreich: aufrufe.append((text, erfolgreich)),
    )
    await cronablauf.melde_wenn_faellig(repos, "phantom", "Plant reminder")
    assert aufrufe == []


# --- Waiting for a model instead of failing ----------------------
#
# What stood here was the preload: an entry whose agent named a local model
# file in its ``model:`` head started that file's server ahead of the due
# time. Both halves of it are gone — the head field is retired (that was the
# third place saying which model runs a job), and the slot the one field can
# hold replaces what the preload bought, because it is simply already loaded.


def test_ohne_erreichbares_modell_entsteht_kein_lauf(config, client):
    """A due time with nothing to run on creates no job, counts no failure
    and leaves the due time open — the next tick tries again."""
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    repositories = client.app.state.repositories
    # The field points at a model that is not there. Written that way rather
    # than by marking an existing endpoint unreachable: the discovery's own
    # check runs on its own schedule and would undo that again mid-test.
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    agentenmodell_setzen(client, "wolke:gibtsnicht")
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    repositories.cronjobs.verbindung.execute(
        "UPDATE cronjobs SET created_at = ? WHERE id = ?",
        ((MORGEN_13.replace(hour=7) - timedelta(days=1)).isoformat(), eintrag.id),
    )

    pruefen(client, MORGEN_13.replace(hour=8, minute=1))

    assert auftraege_von(client, "recherche") == []
    assert cronablauf.wartet_auf_modell(eintrag.id) is True
    frisch = repositories.cronjobs.holen(eintrag.id)
    assert frisch.fehlversuche == 0
    assert frisch.aktiv is True
    assert frisch.zuletzt_ausgeloest is None


def test_das_modell_kommt_und_der_versaeumte_termin_feuert_nach(config, client):
    """The catch-up rule does the rest: once something answers, the most
    recent missed due time fires and the waiting mark is cleared."""
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    repositories = client.app.state.repositories
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    agentenmodell_setzen(client, "wolke:gibtsnicht")
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    repositories.cronjobs.verbindung.execute(
        "UPDATE cronjobs SET created_at = ? WHERE id = ?",
        ((MORGEN_13.replace(hour=7) - timedelta(days=1)).isoformat(), eintrag.id),
    )
    pruefen(client, MORGEN_13.replace(hour=8, minute=1))
    assert cronablauf.wartet_auf_modell(eintrag.id) is True

    agentenmodell_setzen(client, "test")
    pruefen(client, MORGEN_13.replace(hour=8, minute=2))

    assert len(auftraege_von(client, "recherche")) == 1
    assert cronablauf.wartet_auf_modell(eintrag.id) is False


def test_die_wartemeldung_kommt_genau_einmal(config, client, monkeypatch):
    """Ten minutes of waiting are worth one notification, not one per tick.

    On 'announce': this sentence is a notification like the failure limit's
    and follows ``deliver``. The wait itself is booked and logged either
    way; only the notification follows the setting.
    """
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    repositories = client.app.state.repositories
    agentenmodell_setzen(client, "wolke:gibtsnicht")
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat",
        deliver="announce",
    )
    repositories.cronjobs.verbindung.execute(
        "UPDATE cronjobs SET created_at = ? WHERE id = ?",
        ((MORGEN_13.replace(hour=7) - timedelta(days=1)).isoformat(), eintrag.id),
    )
    gemeldet: list[str] = []
    monkeypatch.setattr(
        cronablauf.cronmeldung, "melden",
        lambda text, *, erfolgreich: gemeldet.append(text),
    )

    start = MORGEN_13.replace(hour=8, minute=1)
    pruefen(client, start)
    assert gemeldet == []
    pruefen(client, start + timedelta(minutes=9))
    assert gemeldet == []
    pruefen(client, start + timedelta(minutes=10))
    assert len(gemeldet) == 1
    pruefen(client, start + timedelta(minutes=20))
    assert len(gemeldet) == 1


def test_das_eine_feld_bestimmt_den_endpunkt(config, client):
    """The field hands out one id and the run resolves it like any other —
    a cron entry lands on the endpoint the field names, not on the first one
    that happens to answer."""
    schreiben(Path(config.app.agenten_verzeichnis), "recherche")
    repositories = client.app.state.repositories
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    zweiter = client.app.state.discovery.zustaende["abwesend"]
    zweiter.provider = MockProvider(mock_endpunkt("abwesend"))
    zweiter.erreichbar = True
    # What real discovery resolves for every reachable endpoint before it
    # counts as one (app/fenstergroesse.py) — a request's own answer ceiling
    # is measured against it (app/antwortgrenze.py).
    zweiter.context_tokens = fenstergroesse.ERSATZ
    zweiter.kontext_quelle = fenstergroesse.QUELLE_ERSATZ
    agentenmodell_setzen(client, "abwesend")
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    repositories.cronjobs.verbindung.execute(
        "UPDATE cronjobs SET created_at = ? WHERE id = ?",
        ((MORGEN_13.replace(hour=7) - timedelta(days=1)).isoformat(), eintrag.id),
    )

    pruefen(client, MORGEN_13.replace(hour=8, minute=1))

    laeufe = auftraege_von(client, "recherche")
    assert len(laeufe) == 1
    assert laeufe[0]["endpoint_id"] == "abwesend"


def test_das_kopffeld_model_gewinnt_nicht_mehr(config, client):
    """A file that still names a model is read and logged about, and
    the field decides anyway."""
    schreiben(
        Path(config.app.agenten_verzeichnis), "recherche",
        "---\nmodel: abwesend\n---\n\nPrompt.\n",
    )
    repositories = client.app.state.repositories
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    zweiter = client.app.state.discovery.zustaende["abwesend"]
    zweiter.provider = MockProvider(mock_endpunkt("abwesend"))
    zweiter.erreichbar = True
    # What real discovery resolves for every reachable endpoint before it
    # counts as one (app/fenstergroesse.py) — a request's own answer ceiling
    # is measured against it (app/antwortgrenze.py).
    zweiter.context_tokens = fenstergroesse.ERSATZ
    zweiter.kontext_quelle = fenstergroesse.QUELLE_ERSATZ
    agentenmodell_setzen(client, "test")
    eintrag = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat"
    )
    repositories.cronjobs.verbindung.execute(
        "UPDATE cronjobs SET created_at = ? WHERE id = ?",
        ((MORGEN_13.replace(hour=7) - timedelta(days=1)).isoformat(), eintrag.id),
    )

    pruefen(client, MORGEN_13.replace(hour=8, minute=1))

    laeufe = auftraege_von(client, "recherche")
    assert len(laeufe) == 1
    assert laeufe[0]["endpoint_id"] == "test"
