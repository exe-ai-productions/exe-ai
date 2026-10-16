"""A stop in the middle of a handoff hands nothing on, and a stopped chain run
leaves its own entry switched off.

A run that fills its context writes a handoff and schedules its continuation.
The stop route runs on its own thread, so a stop can land after the loop has
last read the signal and before (or while) the continuation is written. The
run must then end as stopped with no continuation behind it, and the entry of
a restart chain a stopped run came from must not fire tomorrow with the text
the stop made stale. A schedule somebody made themselves stays on.
"""

from __future__ import annotations

from pathlib import Path

from app import kontextdruck, zwischenstand
from app.agenten import agenten_laden
from app.api.v1.auftraege import auftrag_anstossen
from app.providers import mock_endpunkt
from tests.conftest import provider_setzen
from tests.test_auftraege_api import (
    HANDOFF_ZWEI_PUNKTE,
    NahezuVollerKontext,
    _bis_beendet,
    agent_schreiben,
)


def _start(client, config, cronjob_id: str):
    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]
    return auftrag_anstossen(
        config=client.app.state.config,
        repositories=client.app.state.repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=getattr(client.app.state, "werkzeuge", None),
        agent=agent,
        task="Go",
        endpoint_id=None,
        user_id="standard",
        sprache="de",
        cronjob_id=cronjob_id,
    )


def _stop_all(client) -> None:
    for run in client.app.state.generierungen.laufende():
        run.signal.set()


def _stop_when_deciding(client, monkeypatch) -> list[int]:
    """The stop lands exactly between the last read of the signal and the
    write of the continuation: ``entscheiden`` is the first thing that runs
    after the handoff text was accepted."""
    real = zwischenstand.entscheiden
    stopped: list[int] = []

    def stopping(*args, **kwargs):
        stopped.append(1)
        _stop_all(client)
        return real(*args, **kwargs)

    monkeypatch.setattr(zwischenstand, "entscheiden", stopping)
    return stopped


def _full_context(client, config) -> None:
    agent_schreiben(config)
    provider_setzen(
        client, NahezuVollerKontext(mock_endpunkt("test"), handoff_text=HANDOFF_ZWEI_PUNKTE)
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 1000


async def test_a_stop_after_the_handoff_was_accepted_schedules_no_continuation(
    config, client, monkeypatch
):
    _full_context(client, config)
    repositories = client.app.state.repositories
    eigener = repositories.cronjobs.erstellen(
        agent="recherche", task="Go", zeitplan="08:00", herkunft="chat",
    )
    stopped = _stop_when_deciding(client, monkeypatch)

    auftrag = _start(client, config, eigener.id)
    finished = await _bis_beendet(repositories, auftrag.id)

    assert stopped == [1]
    assert finished.zustand == "abgebrochen"
    # The continuation the run had begun to write is gone; the schedule the
    # person made is the only entry, and it is still on.
    eintraege = repositories.cronjobs.auflisten()
    assert [e.id for e in eintraege] == [eigener.id]
    assert eintraege[0].aktiv is True


async def test_a_stop_after_the_handoff_was_accepted_switches_the_chains_own_entry_off(
    config, client, monkeypatch
):
    _full_context(client, config)
    repositories = client.app.state.repositories
    kette = repositories.cronjobs.erstellen(
        agent="recherche", task="weiter", zeitplan="08:00", herkunft="agent",
        basisaufgabe="Ordner aufräumen",
    )
    stopped = _stop_when_deciding(client, monkeypatch)

    auftrag = _start(client, config, kette.id)
    finished = await _bis_beendet(repositories, auftrag.id)

    assert stopped == [1]
    assert finished.zustand == "abgebrochen"
    assert repositories.cronjobs.holen(kette.id).aktiv is False
    assert len(repositories.cronjobs.auflisten()) == 1


async def test_a_stopped_run_of_a_chain_switches_its_entry_off(config, client, monkeypatch):
    """The stop comes before the handoff is asked for: no continuation was
    ever written, and the row the run came from still carried the text of the
    run that was stopped."""
    _full_context(client, config)
    repositories = client.app.state.repositories
    kette = repositories.cronjobs.erstellen(
        agent="recherche", task="weiter", zeitplan="08:00", herkunft="agent",
        basisaufgabe="Ordner aufräumen",
    )
    real = kontextdruck.stand
    stopped: list[int] = []

    def stopping(*args, **kwargs):
        if not stopped:
            stopped.append(1)
            _stop_all(client)
        return real(*args, **kwargs)

    monkeypatch.setattr(kontextdruck, "stand", stopping)

    auftrag = _start(client, config, kette.id)
    finished = await _bis_beendet(repositories, auftrag.id)

    assert stopped == [1]
    assert finished.zustand == "abgebrochen"
    assert repositories.cronjobs.holen(kette.id).aktiv is False


async def test_a_stopped_run_of_a_schedule_somebody_made_leaves_it_on(
    config, client, monkeypatch
):
    """Silence: the schedule of the person is never switched off by a stop."""
    _full_context(client, config)
    repositories = client.app.state.repositories
    eigener = repositories.cronjobs.erstellen(
        agent="recherche", task="Go", zeitplan="08:00", herkunft="chat",
    )
    real = kontextdruck.stand
    stopped: list[int] = []

    def stopping(*args, **kwargs):
        if not stopped:
            stopped.append(1)
            _stop_all(client)
        return real(*args, **kwargs)

    monkeypatch.setattr(kontextdruck, "stand", stopping)

    auftrag = _start(client, config, eigener.id)
    finished = await _bis_beendet(repositories, auftrag.id)

    assert stopped == [1]
    assert finished.zustand == "abgebrochen"
    assert repositories.cronjobs.holen(eigener.id).aktiv is True


async def test_a_run_nobody_stops_still_hands_its_work_on(config, client):
    """Silence: without a stop the continuation is written and the run ends
    as interrupted — the rollback never fires."""
    _full_context(client, config)
    repositories = client.app.state.repositories
    eigener = repositories.cronjobs.erstellen(
        agent="recherche", task="Go", zeitplan="08:00", herkunft="chat",
    )

    auftrag = _start(client, config, eigener.id)
    finished = await _bis_beendet(repositories, auftrag.id)

    assert finished.zustand == "unterbrochen"
    eintraege = repositories.cronjobs.auflisten()
    fortsetzungen = [e for e in eintraege if e.id != eigener.id]
    assert len(fortsetzungen) == 1
    assert fortsetzungen[0].aktiv is True
