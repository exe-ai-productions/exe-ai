"""An agent started from a chat belongs to that chat.

The job knows the chat it came from; deleting the chat stops it and every
run under it; and when it is done, its report goes back into the chat and
the model is woken to sum it up for the user.
"""

from __future__ import annotations

import logging
import time

from app import agent_report, hintergrundwecken
from app.api.v1.auftraege import _work_of
from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Werkzeugaufruf
from app.zwischenstand import kettenfelder
from tests.conftest import provider_setzen
from tests.test_auftrag_werkzeug import StartRegistry, _agent_anlegen, _ereignisse


def _start_from_chat(client, chat_id, config):
    """The chat's model calls start_job, the window says yes; returns the
    stream's events and the provider, whose last request is whatever ran
    last."""
    _agent_anlegen(config)
    client.app.state.werkzeuge = StartRegistry(client, True, None)
    client.app.state.config.features.mcp = True
    provider = provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["Good."],
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id="a1", name="start_job",
                    argumente={"agent": "bote", "task": "Collect the notes."},
                )
            ],
        ),
    )
    answer = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "send it off"},
    )
    return _ereignisse(answer), provider


def _wait_for(condition, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(0.05)
    return condition()


def _job(repos, chat_id, **fields):
    return repos.auftraege.erstellen(
        user_id="standard", agent="bote", auftrag=fields.pop("auftrag", "A"),
        chat_id=chat_id, **fields,
    )


def _continuation_of(repos, job):
    """The entry the service writes when a run hands its work on
    (app/zwischenstand.py)."""
    return repos.cronjobs.erstellen(
        agent="bote", task="carry on", zeitplan="* * * * *", herkunft="agent",
        **kettenfelder(None, job.id),
    )


def test_a_job_started_from_a_chat_carries_the_chat(client, chat_id, config):
    events, _ = _start_from_chat(client, chat_id, config)

    jobs = client.get("/api/v1/jobs").json()
    assert len(jobs) == 1
    assert jobs[0]["chat_id"] == chat_id
    result = next(e for e in events if e["typ"] == "tool_result")
    assert result["auftrag_id"] == jobs[0]["id"]


def test_a_job_from_the_start_window_has_no_chat(client, config):
    _agent_anlegen(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    answer = client.post("/api/v1/jobs", json={"agent": "bote", "task": "Go"})
    assert answer.status_code in (200, 201), answer.text
    job_id = answer.json()["id"]

    assert client.get(f"/api/v1/jobs/{job_id}").json()["chat_id"] is None


def test_a_child_and_a_continuation_take_the_chat_of_their_run(client, chat_id):
    repos = client.app.state.repositories
    parent = _job(repos, chat_id)
    continuation = _continuation_of(repos, parent)
    schedule = repos.cronjobs.erstellen(
        agent="bote", task="every day", zeitplan="0 9 * * *", herkunft="chat",
    )

    assert _work_of(repos, eltern_id=parent.id, cronjob_id=None) == (chat_id, None)
    found_chat, origin = _work_of(repos, eltern_id=None, cronjob_id=continuation.id)
    assert found_chat == chat_id
    assert origin.id == parent.id
    # A schedule's own entry names no run, so there is no chat to find.
    assert _work_of(repos, eltern_id=None, cronjob_id=schedule.id) == (None, None)
    assert _work_of(repos, eltern_id=None, cronjob_id=None) == (None, None)


def test_deleting_the_chat_stops_its_job_and_the_runs_under_it(client, chat_id, caplog):
    repos = client.app.state.repositories
    parent = _job(repos, chat_id, zustand="wartet")
    child = _job(repos, chat_id, auftrag="B", zustand="wartet", eltern_id=parent.id)

    with caplog.at_level(logging.INFO, logger="app.api.v1.auftraege"):
        assert client.delete(f"/api/v1/chats/{chat_id}").status_code == 204

    for job in (parent, child):
        after = client.get(f"/api/v1/jobs/{job.id}").json()
        assert after["state"] == "abgebrochen"
        assert after["end_reason"] == "chat_deleted"
    assert any("job(s) stopped with it" in record.getMessage() for record in caplog.records)


def test_deleting_another_chat_leaves_the_job_running(client, chat_id):
    """The silence probe: only the chat a job came from stops it."""
    repos = client.app.state.repositories
    job = _job(repos, chat_id, zustand="wartet")
    other = client.post("/api/v1/chats", json={"title": "Other"}).json()["id"]

    client.delete(f"/api/v1/chats/{other}")

    assert client.get(f"/api/v1/jobs/{job.id}").json()["state"] == "wartet"


def test_deleting_the_chat_switches_off_a_continuation_still_waiting(client, chat_id):
    """Work handed on waits as an active entry naming the run it began with;
    it must not start later for a chat that is gone."""
    repos = client.app.state.repositories
    handed_on = _job(repos, chat_id, zustand="unterbrochen")
    continuation = _continuation_of(repos, handed_on)
    schedule = repos.cronjobs.erstellen(
        agent="bote", task="every day", zeitplan="0 9 * * *", herkunft="chat",
    )

    client.delete(f"/api/v1/chats/{chat_id}")

    assert repos.cronjobs.holen(continuation.id).aktiv is False
    assert repos.cronjobs.holen(schedule.id).aktiv is True


def test_a_finished_job_reports_back_and_wakes_its_chat(client, chat_id, config):
    _, provider = _start_from_chat(client, chat_id, config)
    repos = client.app.state.repositories

    def report_and_answer():
        rows = repos.messages.auflisten(chat_id=chat_id)
        reports = [r for r in rows if r.art == "werkzeugmeldung"]
        if not reports:
            return None
        after = [
            r for r in rows
            if r.role == "assistant" and r.art != "werkzeugmeldung"
            and r.created_at > reports[0].created_at and r.zustand != "laeuft"
        ]
        return (reports[0], after) if after else None

    found = _wait_for(report_and_answer)
    assert found, "no report, or no answer after it"
    report, _ = found
    assert report.content.startswith("[Agent 'bote' finished")
    assert "Task: Collect the notes." in report.content
    assert report.stats["werkzeuge"][0]["name"] == "start_job"
    # The woken turn was told it is an agent's report to sum up — behind the
    # report, in the report's own turn, the last thing in its history; the
    # system message is left alone.
    request = provider.letzte_anfrage
    assert "An agent you had handed a job to has finished" not in request.nachrichten[0].content
    newest = request.nachrichten[-1]
    assert newest.content.startswith("[Agent 'bote' finished")
    assert newest.content.endswith(hintergrundwecken.AGENT_NOTICE)


def test_the_wake_after_an_agent_report_asks_for_a_summary(client, chat_id):
    repos = client.app.state.repositories
    repos.messages.speichern(
        chat_id=chat_id, role="assistant", content="[Agent 'bote' finished — job x]",
        art="werkzeugmeldung", stats={"werkzeuge": [{"name": "start_job"}]},
    )
    row = repos.messages.neueste_fuer_das_modell(chat_id=chat_id)

    assert hintergrundwecken._report_tool(row) == "start_job"
    assert hintergrundwecken._ist_befehlsbericht(row)
    assert "sum" not in hintergrundwecken.ANSTOSS
    assert "Tell them in a few sentences" in hintergrundwecken.AGENT_NOTICE


def test_a_job_without_a_chat_and_a_child_report_nowhere(client, chat_id):
    """The silence probe: a run another run started reports to that run,
    and a run nobody started from a chat has no chat to report to."""
    repos = client.app.state.repositories
    parent = _job(repos, chat_id)
    child = _job(repos, chat_id, auftrag="B", eltern_id=parent.id)
    loose = repos.auftraege.erstellen(user_id="standard", agent="bote", auftrag="C")
    repos.auftraege.zustand_setzen(child.id, "fertig", ergebnis="done")
    repos.auftraege.zustand_setzen(loose.id, "fertig", ergebnis="done")
    before = len(repos.messages.auflisten(chat_id=chat_id))

    handler = agent_report._subscribers[-1]
    handler(auftrag_id=child.id)
    handler(auftrag_id=loose.id)

    assert len(repos.messages.auflisten(chat_id=chat_id)) == before


def test_the_report_names_the_agent_the_ending_and_the_task():
    from app.db.models import Auftrag

    job = Auftrag(
        id="j1", user_id="u", agent="bote", auftrag="Collect.", zustand="gescheitert",
        created_at="t", updated_at="t", ende_grund="zeitgrenze", ergebnis="",
    )

    text = agent_report.report_text(job)

    assert text.splitlines()[0] == "[Agent 'bote' failed — job j1]"
    # The stored identifier is German and internal; the model reads the
    # sentence the catalogue holds for it — the same entry the job list
    # shows in the window's language (app/agent_report._reason_text).
    assert "Reason: time limit reached" in text
    assert "Task: Collect." in text
    assert text.endswith("The agent did not provide a report.")


def test_the_first_stop_keeps_its_reason():
    """The stop button names its own reason, so a stop after it — the chat
    deleted a moment later — cannot rewrite who stopped the run."""
    from app.generationen import Generierung, Generierungsverwaltung

    runs = Generierungsverwaltung()
    run = Generierung(id="g1", chat_id="c", endpoint_id="test")
    # Registered by hand: the run itself would need a loop and some work.
    runs._laufende[run.id] = run

    assert runs.abbrechen(run.id, reason="benutzer_abbruch")
    runs.abbrechen(run.id, reason="chat_deleted")

    assert run.soll_abbrechen
    assert run.stop_reason == "benutzer_abbruch"


def test_a_long_report_is_cut_where_a_tool_result_is():
    from app.api.v1.generierung import WERKZEUGERGEBNIS_GRENZE
    from app.db.models import Auftrag

    job = Auftrag(
        id="j1", user_id="u", agent="bote", auftrag="Collect.", zustand="fertig",
        created_at="t", updated_at="t", ergebnis="x" * (WERKZEUGERGEBNIS_GRENZE + 500),
    )

    text = agent_report.report_text(job)

    assert text.count("x") == WERKZEUGERGEBNIS_GRENZE
    assert text.endswith("the full report is available in the agents view.]")


def test_the_continuation_of_a_run_under_another_reports_nowhere(client, chat_id):
    """A child's work stays the child's part, handed on or not."""
    repos = client.app.state.repositories
    parent = _job(repos, chat_id)
    child = _job(repos, chat_id, auftrag="B", eltern_id=parent.id)
    entry = _continuation_of(repos, child)
    continuation = _job(repos, chat_id, auftrag="B again", cronjob_id=entry.id)
    repos.auftraege.zustand_setzen(continuation.id, "fertig", ergebnis="done")
    before = len(repos.messages.auflisten(chat_id=chat_id))

    agent_report._subscribers[-1](auftrag_id=continuation.id)

    assert len(repos.messages.auflisten(chat_id=chat_id)) == before
