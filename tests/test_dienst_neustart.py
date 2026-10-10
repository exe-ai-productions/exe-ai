"""A service restart must not lose a scheduled restart chain ("a program
restart kills the run").

app/main.py's own startup cleanup only ever marks a 'laeuft' job
'unterbrochen' — it never touches the cron table. A restart chain a
context-full handoff or a provider outage already
set up survives on its own: the entry lives in the database, not in
memory, and the alarm clock's own startup pass (app/wecker.py, rule 1 —
"catch up once") picks up any due entry exactly like it would on any other
30-second tick. No new code was needed for this gap; this test is the
verification that claim actually holds.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app_erstellen
from app.providers import MockProvider, mock_endpunkt
from app.zwischenstand import MAX_NEUSTARTS
from tests.conftest import agentenmodell_setzen, provider_setzen


def schreiben(ordner: Path, name: str = "recherche") -> None:
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / f"{name}.md").write_text("---\nmodel: test\n---\n\nPrompt.\n", encoding="utf-8")


def test_geplanter_termin_ueberlebt_einen_dienst_neustart(config):
    schreiben(Path(config.app.agenten_verzeichnis))

    with TestClient(app_erstellen(config)) as erster:
        # The one field, written before the restart. It is a stored
        # setting, so it is what the catch-up pass of the SECOND service
        # reads — the agent file's own ``model:`` used to do this job and is
        # retired.
        agentenmodell_setzen(erster, "test")
        eintrag = erster.app.state.repositories.cronjobs.erstellen(
            agent="recherche", task="Weiter", zeitplan="08:00", herkunft="agent",
        )
        # Backdated well past a day: `letzter_termin` always resolves to a
        # moment at or before "now", so this guarantees the entry counts as
        # due on the very next pass regardless of what time this test
        # happens to run (the fix that takes created_at as the
        # baseline for a never-fired entry — would otherwise hold a
        # freshly-created one back until its first real occurrence).
        erster.app.state.repositories.cronjobs.verbindung.execute(
            "UPDATE cronjobs SET created_at = ? WHERE id = ?",
            ((datetime.now(timezone.utc) - timedelta(days=2)).isoformat(), eintrag.id),
        )
    # The service is gone here — the TestClient context exited, tearing
    # down discovery, the alarm clock and every in-memory tracker with it.
    # Only the database file (config.database.path) survives.

    with TestClient(app_erstellen(config)) as zweiter:
        zweiter.headers["X-Sitzungsschluessel"] = zweiter.app.state.sitzungsschluessel
        provider_setzen(zweiter, MockProvider(mock_endpunkt("test")))
        frist = time.time() + 5.0
        gefunden = []
        while time.time() < frist:
            gefunden = [
                a for a in zweiter.get("/api/v1/jobs").json() if a["agent"] == "recherche"
            ]
            if gefunden:
                break
            time.sleep(0.05)
        assert gefunden, "The cron job did not fire after the restart"


# --- A run with neither trigger, cut off by the restart itself --


def test_ein_lauf_ohne_kontextgrenze_und_ausfall_wird_mit_zwischenstand_fortgesetzt(config):
    """The actual gap this step closes: a run that never crossed 90% context
    and never hit a provider outage used to have no cronjob entry at all, so
    a hard restart just left it 'unterbrochen' — forever. The periodic write
    during the run is what gives THIS run a status too."""
    with TestClient(app_erstellen(config)) as erster:
        auftrag = erster.app.state.repositories.auftraege.erstellen(
            user_id="standard", agent="recherche", auftrag="Ordner aufräumen",
        )
        erster.app.state.repositories.auftraege.zwischenstand_setzen(
            auftrag.id, "## Task\nOrdner aufräumen\n\n## Done\n- Hälfte durchsucht"
        )
        auftrag_id = auftrag.id
    # The service is gone here, same as above — only the database survives.

    with TestClient(app_erstellen(config)) as zweiter:
        repositories = zweiter.app.state.repositories
        danach = repositories.auftraege.holen(auftrag_id)
        assert danach.zustand == "unterbrochen"
        assert danach.ende_grund == "dienst_neustart"

        (eintrag,) = repositories.cronjobs.auflisten()
        assert eintrag.agent == "recherche"
        assert eintrag.basisaufgabe == "Ordner aufräumen"
        assert "Hälfte durchsucht" in eintrag.task
        assert eintrag.neustarts == 1
        assert eintrag.aktiv is True

    # A third service start — nothing ran in between, the job simply stayed
    # 'unterbrochen'. Closing the app every evening and reopening it every
    # morning must not replan the same restart on every single one: the
    # first review round's bug did exactly that, one fresh chain per start,
    # the ceiling never actually reached.
    with TestClient(app_erstellen(config)) as dritter:
        repositories = dritter.app.state.repositories
        assert len(repositories.cronjobs.auflisten()) == 1
        assert repositories.cronjobs.auflisten()[0].neustarts == 1


def test_die_neustart_obergrenze_bremst_auch_einen_dienst_neustart(config):
    """A chain already at the ceiling from earlier restarts (of any cause)
    does not get a fresh budget just because this particular restart was a
    plain service restart rather than a context-full handoff."""
    with TestClient(app_erstellen(config)) as erster:
        repositories = erster.app.state.repositories
        kette = repositories.cronjobs.erstellen(
            agent="recherche", task="Weiter", zeitplan="08:00", herkunft="agent",
            basisaufgabe="Ordner aufräumen",
        )
        repositories.cronjobs.fortschritt_setzen(
            kette.id, erledigt_anzahl=3, ohne_fortschritt=0, neustarts=MAX_NEUSTARTS - 1,
        )
        auftrag = repositories.auftraege.erstellen(
            user_id="standard", agent="recherche", auftrag="Weiter", cronjob_id=kette.id,
        )
        repositories.auftraege.zwischenstand_setzen(auftrag.id, "Noch mehr geschafft.")
        kette_id = kette.id

    with TestClient(app_erstellen(config)) as zweiter:
        repositories = zweiter.app.state.repositories
        danach = repositories.cronjobs.holen(kette_id)
        assert danach.aktiv is False
        # The chain stopped, not moved forward — no fresh restart count.
        assert danach.task == "Weiter"
