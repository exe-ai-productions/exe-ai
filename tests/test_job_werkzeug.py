"""The job tool: the model of a chat sees and ends the runs it sent off.

`start_job` handed work to a helper or a named agent and the model heard
nothing until the report came, so it polled the folder and did the work
itself, and it could not end a run, so it advised restarting the program.
Now the answer of every start carries the ID and says the report comes by
itself, and the tool `job` shows the open runs of THIS chat (`list`) and ends
one the way the stop button does (`stop`) — and nothing else of anybody's.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from app import helper
from app.api.v1.auftraege import stop_job
from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Werkzeugaufruf
from app.tools import auftrag_werkzeug, cronjob, job_werkzeug
from app.tools.registry import WerkzeugRegistry, WerkzeugVerboten
from tests.conftest import provider_setzen
from tests.test_job_watchdog import SilentAfterStart, _until_ended, _start

USER = "standard"


def _row(client, chat, zustand="laeuft", agent="helper", **besonderes):
    return client.app.state.repositories.auftraege.erstellen(
        user_id=USER, agent=agent, auftrag="Write the file.", zustand=zustand,
        chat_id=chat, **besonderes,
    )


def _call(client, chat, **argumente):
    repositories = client.app.state.repositories
    generierungen = client.app.state.generierungen
    gestoppt = []

    def stoppen(auftrag):
        gestoppt.append(auftrag.id)
        stop_job(repositories, generierungen, auftrag)

    try:
        text = job_werkzeug.execute(
            argumente, repositories=repositories, chat_id=chat, stop=stoppen
        )
    except job_werkzeug.JobRefused as fehler:
        return str(fehler), gestoppt
    return text, gestoppt


def _other_chat(client) -> str:
    return client.post("/api/v1/chats", json={"title": "Anderer"}).json()["id"]


# --- list -------------------------------------------------------------------


def test_list_shows_the_open_runs_of_this_chat_with_state_and_last_tool(client, chat_id):
    repositories = client.app.state.repositories
    helfer = _row(client, chat_id)
    benannt = _row(client, chat_id, zustand="wartet", agent="bote")
    repositories.auftraege.schritt_anlegen(
        helfer.id, "tool_call", json.dumps({"name": "write_file"})
    )

    text, _ = _call(client, chat_id, action="list")

    assert "2 open job(s)" in text
    zeile_helfer = next(z for z in text.splitlines() if helfer.id in z)
    assert "helper" in zeile_helfer and "running" in zeile_helfer
    assert "last tool: write_file" in zeile_helfer
    assert "Write the file." in zeile_helfer
    zeile_benannt = next(z for z in text.splitlines() if benannt.id in z)
    assert "bote" in zeile_benannt and "waiting for an answer" in zeile_benannt
    assert "last tool: none yet" in zeile_benannt


def test_silence_list_shows_nothing_that_is_not_this_chats_own_send_off(client, chat_id):
    repositories = client.app.state.repositories
    eigener = _row(client, chat_id)
    fremder_chat = _other_chat(client)
    fremder = _row(client, fremder_chat)
    zeitplan = _row(
        client, chat_id,
        cronjob_id=repositories.cronjobs.erstellen(
            agent="bote", task="Water", zeitplan="08:00", herkunft="agent"
        ).id,
    )
    von_hand = _row(client, None)
    kind = _row(client, chat_id, eltern_id=eigener.id)
    fertig = _row(client, chat_id, zustand="fertig")

    text, _ = _call(client, chat_id, action="list")

    assert eigener.id in text
    for nicht in (fremder, zeitplan, von_hand, kind, fertig):
        assert nicht.id not in text


def test_silence_list_without_a_run_says_so(client, chat_id):
    text, _ = _call(client, chat_id, action="list")
    assert text == "No jobs started from this chat are open."


# --- stop -------------------------------------------------------------------


async def test_stop_ends_a_running_helper_and_a_running_named_agent(client, config, chat_id):
    provider_setzen(client, SilentAfterStart(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    registry = getattr(client.app.state, "werkzeuge", None)
    helfer, helferlauf = _start(
        client, config, chat_id, agent=helper.helper_agent(repositories, registry)
    )
    benannt, benanntlauf = _start(client, config, chat_id)

    for auftrag in (helfer, benannt):
        text, gestoppt = _call(client, chat_id, action="stop", id=auftrag.id)
        assert gestoppt == [auftrag.id]
        assert f"Job {auftrag.id} is being stopped" in text

    for auftrag in (helfer, benannt):
        beendet = await _until_ended(client, auftrag.id)
        assert beendet.zustand == "abgebrochen"
        assert beendet.ende_grund == "benutzer_abbruch"


async def test_the_stopped_run_reports_into_the_chat_as_stopped(client, config, chat_id):
    provider_setzen(client, SilentAfterStart(mock_endpunkt("test")))
    auftrag, _ = _start(client, config, chat_id)

    _call(client, chat_id, action="stop", id=auftrag.id)
    await _until_ended(client, auftrag.id)

    frist = time.monotonic() + 5
    meldung = None
    while time.monotonic() < frist and meldung is None:
        meldung = next(
            (
                n for n in client.app.state.repositories.messages.auflisten(chat_id=chat_id)
                if n.art == "werkzeugmeldung"
            ),
            None,
        )
        await asyncio.sleep(0.05)
    assert meldung is not None and "was stopped" in meldung.content


def test_silence_stop_leaves_every_run_that_is_not_this_chats_own_send_off(client, chat_id):
    repositories = client.app.state.repositories
    fremder = _row(client, _other_chat(client))
    zeitplan = _row(
        client, chat_id,
        cronjob_id=repositories.cronjobs.erstellen(
            agent="bote", task="Water", zeitplan="08:00", herkunft="agent"
        ).id,
    )
    von_hand = _row(client, None)
    eigener = _row(client, chat_id)
    kind = _row(client, chat_id, eltern_id=eigener.id)

    for ziel in (fremder, zeitplan, von_hand, kind):
        text, gestoppt = _call(client, chat_id, action="stop", id=ziel.id)
        assert f"No job with ID '{ziel.id}' was started from this chat" in text
        assert gestoppt == []
        assert repositories.auftraege.holen(ziel.id).zustand == "laeuft"


def test_silence_stop_with_an_unknown_or_missing_id_refuses_and_stops_nothing(client, chat_id):
    eigener = _row(client, chat_id)
    for kennung in ({"id": "0" * 32}, {}):
        text, gestoppt = _call(client, chat_id, action="stop", **kennung)
        assert "was started from this chat" in text and gestoppt == []
    assert client.app.state.repositories.auftraege.holen(eigener.id).zustand == "laeuft"


def test_stop_of_a_run_that_is_over_says_so_and_stops_nothing(client, chat_id):
    fertig = _row(client, chat_id, zustand="fertig")
    text, gestoppt = _call(client, chat_id, action="stop", id=fertig.id)
    assert "already over" in text and gestoppt == []


def test_an_unknown_action_is_refused(client, chat_id):
    text, _ = _call(client, chat_id, action="delete")
    assert "'action' must be one of: list, stop." in text


def test_a_cronjob_remove_with_a_run_id_answers_as_before(client, chat_id):
    """The schedule's own tool still knows nothing of runs."""
    repositories = client.app.state.repositories
    lauf = _row(client, chat_id)

    async def entfernen(kennung):
        return await cronjob.ausfuehren(
            {"action": "remove", "id": kennung}, repositories.cronjobs, None
        )

    with pytest.raises(cronjob.CronjobVerboten) as mit_lauf:
        asyncio.run(entfernen(lauf.id))
    with pytest.raises(cronjob.CronjobVerboten) as mit_unbekannt:
        asyncio.run(entfernen("0" * 32))
    assert str(mit_lauf.value).replace(lauf.id, "X") == str(mit_unbekannt.value).replace(
        "0" * 32, "X"
    )
    assert repositories.auftraege.holen(lauf.id).zustand == "laeuft"


# --- A run that handed its work on --------------------------------------------
#
# A helper whose context fills up hands the rest of its work to a continuation:
# a run of its own under a cron entry of its own. For the model it stays the one
# job `start_job` named.


def _handed_on(client, chat, entry_on=True, agent="helper"):
    """A run that handed its work on, and the entry its continuation waits in."""
    repositories = client.app.state.repositories
    head = _row(client, chat, agent=agent)
    repositories.auftraege.zustand_setzen(head.id, "unterbrochen", ende_grund="kontext_voll")
    entry = repositories.cronjobs.erstellen(
        agent=agent, task="Write the file.", zeitplan="08:00", herkunft="agent",
        basisaufgabe="Write the file.", ursprung_id=head.id,
    )
    if not entry_on:
        repositories.cronjobs.aktiv_setzen(entry.id, False)
    return repositories.auftraege.holen(head.id), entry


def _link(client, chat, entry, agent="helper"):
    """The run the continuation entry fired."""
    return client.app.state.repositories.auftraege.erstellen(
        user_id=USER, agent=agent, auftrag="Write the file.", cronjob_id=entry.id, chat_id=chat,
    )


def test_a_handed_on_job_is_listed_once_under_the_id_start_job_named(client, chat_id):
    head, entry = _handed_on(client, chat_id)

    text, _ = _call(client, chat_id, action="list")

    assert "1 open job(s)" in text
    assert head.id in text
    assert "handed on to a continuation that starts shortly" in text


def test_a_running_continuation_shows_with_its_own_state_and_last_tool(client, chat_id):
    repositories = client.app.state.repositories
    head, entry = _handed_on(client, chat_id)
    link = _link(client, chat_id, entry)
    repositories.auftraege.schritt_anlegen(
        link.id, "tool_call", json.dumps({"name": "edit_file"})
    )

    text, _ = _call(client, chat_id, action="list")

    assert "1 open job(s)" in text
    line = next(z for z in text.splitlines() if head.id in z)
    assert "running" in line and "last tool: edit_file" in line
    # The continuation's own ID is not what the model is told.
    assert link.id not in text


def test_stop_with_the_first_id_ends_the_continuation_and_switches_the_chain_off(client, chat_id):
    repositories = client.app.state.repositories
    head, entry = _handed_on(client, chat_id)
    link = _link(client, chat_id, entry)

    text, stopped = _call(client, chat_id, action="stop", id=head.id)

    assert stopped == [link.id]
    assert f"Job {head.id} is being stopped" in text
    assert repositories.cronjobs.holen(entry.id).aktiv is False


def test_stop_with_the_id_of_the_continuation_reaches_the_same_work(client, chat_id):
    """The report of a continuation names the continuation's own run."""
    repositories = client.app.state.repositories
    head, entry = _handed_on(client, chat_id)
    link = _link(client, chat_id, entry)

    text, stopped = _call(client, chat_id, action="stop", id=link.id)

    assert stopped == [link.id]
    assert f"Job {head.id} is being stopped" in text
    assert repositories.cronjobs.holen(entry.id).aktiv is False


def test_stop_while_the_continuation_waits_switches_it_off_and_ends_the_work(client, chat_id):
    repositories = client.app.state.repositories
    head, entry = _handed_on(client, chat_id)

    text, stopped = _call(client, chat_id, action="stop", id=head.id)

    assert stopped == []
    assert "had not started yet" in text and "will not start" in text
    assert repositories.cronjobs.holen(entry.id).aktiv is False
    ended = repositories.auftraege.holen(head.id)
    assert (ended.zustand, ended.ende_grund) == ("abgebrochen", "benutzer_abbruch")
    # Nothing of it is open any more.
    assert _call(client, chat_id, action="list")[0] == "No jobs started from this chat are open."


def test_a_finished_chain_is_not_listed_and_has_nothing_to_stop(client, chat_id):
    head, entry = _handed_on(client, chat_id, entry_on=False)

    assert _call(client, chat_id, action="list")[0] == "No jobs started from this chat are open."
    text, stopped = _call(client, chat_id, action="stop", id=head.id)
    assert "already over" in text and stopped == []


def test_silence_the_chain_of_a_schedule_a_hand_started_run_and_another_chat_are_left_out(
    client, chat_id
):
    repositories = client.app.state.repositories
    # A schedule somebody made: its continuation names the schedule's entry.
    plan = repositories.cronjobs.erstellen(
        agent="bote", task="Water", zeitplan="08:00", herkunft="agent"
    )
    plan_entry = repositories.cronjobs.erstellen(
        agent="bote", task="Water", zeitplan="08:00", herkunft="agent",
        basisaufgabe="Water", ursprung_id=plan.id,
    )
    plan_run = _link(client, chat_id, plan_entry, agent="bote")
    # A run the user started in the start window, and its continuation.
    by_hand, by_hand_entry = _handed_on(client, None)
    by_hand_run = _link(client, None, by_hand_entry)
    # A run of another chat, and its continuation.
    other_head, other_entry = _handed_on(client, _other_chat(client))
    other_run = _link(client, _other_chat(client), other_entry)

    assert _call(client, chat_id, action="list")[0] == "No jobs started from this chat are open."
    for target in (plan_run, by_hand, by_hand_run, other_head, other_run):
        text, stopped = _call(client, chat_id, action="stop", id=target.id)
        assert "was started from this chat" in text and stopped == []
    for entry in (plan_entry, by_hand_entry, other_entry):
        assert repositories.cronjobs.holen(entry.id).aktiv is True


async def test_stop_with_the_first_id_ends_a_running_continuation_for_good(
    client, config, chat_id
):
    provider_setzen(client, SilentAfterStart(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    head, entry = _handed_on(client, chat_id, agent="bote")
    link, _ = _start(client, config, None, cronjob_id=entry.id)

    text, stopped = _call(client, chat_id, action="stop", id=head.id)

    assert stopped == [link.id]
    ended = await _until_ended(client, link.id)
    assert (ended.zustand, ended.ende_grund) == ("abgebrochen", "benutzer_abbruch")
    assert repositories.cronjobs.holen(entry.id).aktiv is False
    assert _call(client, chat_id, action="list")[0] == "No jobs started from this chat are open."


# --- Who is offered the tool ------------------------------------------------


def test_the_chat_is_offered_the_tool_and_no_run_is(tmp_path):
    registry = WerkzeugRegistry([], agenten_orte=(tmp_path,))

    def namen(**optionen):
        return [w["function"]["name"] for w in registry.als_openai_werkzeuge(**optionen)]

    assert job_werkzeug.WERKZEUG_NAME in namen()
    assert job_werkzeug.WERKZEUG_NAME not in namen(for_job=True)
    # An agent's own list of tools can name it and still gets nothing.
    assert job_werkzeug.WERKZEUG_NAME not in namen(nur={"job"}, for_job=True)
    assert job_werkzeug.WERKZEUG_NAME not in namen(nur={"start_job"})
    registry.abgeschaltet = {job_werkzeug.WERKZEUG_NAME}
    assert job_werkzeug.WERKZEUG_NAME not in namen()


def test_silence_a_service_without_agents_has_no_such_tool(tmp_path):
    registry = WerkzeugRegistry([])
    assert job_werkzeug.WERKZEUG_NAME not in registry.namen()
    assert job_werkzeug.WERKZEUG_NAME not in [
        w["function"]["name"] for w in registry.als_openai_werkzeuge()
    ]


def test_a_helper_is_not_offered_the_tool_and_a_call_of_it_is_refused(client):
    repositories = client.app.state.repositories
    registry = WerkzeugRegistry([], agenten_orte=(Path("."),))
    assert job_werkzeug.WERKZEUG_NAME in registry.namen()
    assert job_werkzeug.WERKZEUG_NAME not in helper.helper_agent(repositories, registry).werkzeuge
    assert helper.refused_call("helper", job_werkzeug.WERKZEUG_NAME) is not None
    # The tool a helper IS offered stays so, and the chat's other tools stay.
    assert helper.refused_call("helper", "read_file") is None


def test_the_registry_executes_nothing_itself(tmp_path):
    registry = WerkzeugRegistry([], agenten_orte=(tmp_path,))
    with pytest.raises(WerkzeugVerboten, match="No chat is available"):
        asyncio.run(registry.ausfuehren(job_werkzeug.WERKZEUG_NAME, {"action": "list"}))


# --- What the model is told -------------------------------------------------


def test_the_answer_of_a_start_carries_the_id_and_tells_the_model_to_leave_the_work():
    text = auftrag_werkzeug.started_text("helper", "abc123", with_job_tool=True)
    assert text.startswith("Job started: agent 'helper', ID abc123.")
    assert "report comes into this chat by itself" in text
    assert "do not look in folders, do not wait with commands and do not do its work yourself" in text
    assert "'list'" in text and "'stop'" in text


def test_silence_the_answer_names_no_tool_the_model_does_not_have():
    text = auftrag_werkzeug.started_text("helper", "abc123", with_job_tool=False)
    assert "ID abc123" in text and "by itself" in text
    assert "job tool" not in text


def test_the_description_of_start_job_says_the_report_comes_by_itself():
    ohne = auftrag_werkzeug.werkzeug_beschreibung().beschreibung
    mit = auftrag_werkzeug.werkzeug_beschreibung(with_job_tool=True).beschreibung
    for beschreibung in (ohne, mit):
        assert "report comes into this chat by itself" in beschreibung
        assert "do not wait with commands" in beschreibung
        assert "starts at once" in beschreibung
    assert "job tool" in mit and "job tool" not in ohne


# --- The flow through the chat ----------------------------------------------


class JobRegistry:
    """Offers `job` and nothing else. The chat run answers the call itself —
    reaching ``ausfuehren`` here would be the bug."""

    def __init__(self):
        self.ausgefuehrt = []
        self.abgeschaltet = set()

    def als_openai_werkzeuge(self, nur=None, **_options):
        return [{"type": "function", "function": {"name": "job", "parameters": {}}}]

    def known_names(self):
        return {"job"}

    def braucht_bestaetigung(self, name, argumente=None, ordner=None):
        return False

    def server_von(self, name):
        return "shell"

    def bestaetigungsgrund(self, name, argumente=None, ordner=None):
        return ""

    async def ausfuehren(self, name, argumente, bild_senke=None, ordner=None,
                         chat_id=None, herkunft="chat", agent=None):
        self.ausgefuehrt.append(name)
        raise WerkzeugVerboten(job_werkzeug.ONLY_IN_A_CHAT)


def _model_calls_job(client, **argumente):
    registry = JobRegistry()
    client.app.state.werkzeuge = registry
    client.app.state.config.features.mcp = True
    provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["Gut."],
            werkzeugaufrufe=[Werkzeugaufruf(id="j1", name="job", argumente=argumente)],
        ),
    )
    return registry


def _events(antwort):
    return [
        json.loads(z[5:].strip()) for z in antwort.text.splitlines() if z.startswith("data:")
    ]


def _send(client, chat_id):
    return _events(
        client.post(
            "/api/v1/chat/completions",
            json={"chat_id": chat_id, "endpoint_id": "test", "content": "wie weit?"},
        )
    )


def test_the_chat_run_answers_list_with_the_runs_of_the_chat(client, chat_id):
    eigener = _row(client, chat_id)
    registry = _model_calls_job(client, action="list")

    ereignisse = _send(client, chat_id)

    ergebnis = next(e for e in ereignisse if e["typ"] == "tool_result")
    assert ergebnis["fehlgeschlagen"] is False
    assert eigener.id in ergebnis["text"] and "running" in ergebnis["text"]
    assert registry.ausgefuehrt == []


def test_the_chat_run_ends_a_run_of_the_chat_on_stop_and_a_foreign_one_never(client, chat_id):
    eigener = _row(client, chat_id)
    fremder = _row(client, _other_chat(client))
    repositories = client.app.state.repositories

    _model_calls_job(client, action="stop", id=fremder.id)
    ergebnis = next(e for e in _send(client, chat_id) if e["typ"] == "tool_result")
    assert ergebnis["fehlgeschlagen"] is True
    assert repositories.auftraege.holen(fremder.id).zustand == "laeuft"

    _model_calls_job(client, action="stop", id=eigener.id)
    ergebnis = next(e for e in _send(client, chat_id) if e["typ"] == "tool_result")
    assert ergebnis["fehlgeschlagen"] is False
    assert "is being stopped" in ergebnis["text"]
    assert repositories.auftraege.holen(eigener.id).zustand == "abgebrochen"
    assert repositories.auftraege.holen(eigener.id).ende_grund == "benutzer_abbruch"
