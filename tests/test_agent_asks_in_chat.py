"""An agent the chat model sends off asks in that chat.

It keeps its own tools, but its calls are judged by the chat's mode and
rules, the way a subagent works in its main session's mode: a call the chat
would ask about is asked about with the chat's own confirmation event, the
agent's name beside it. Nobody answering refuses that one call and the run
goes on. A run started by hand or by a schedule is judged as before.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from app.agenten import agenten_laden
from app.api.v1 import auftraege as auftraege_api
from app.api.v1 import generierung as generierung_api
from app.api.v1.auftraege import auftrag_anstossen
from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Werkzeugaufruf
from app.tools.registry import WerkzeugRegistry
from tests.conftest import provider_setzen, wakes_settled

ENDE = {"fertig", "abgebrochen", "gescheitert", "unterbrochen"}


def _rules(tmp_path: Path, *, chat: str, agent: str) -> Path:
    """A rule file where a call inside the shared folders gets ``chat`` in
    a chat and ``agent`` in an agent's own run."""
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps(
            {
                "standard": {"chat": "ja", "agent": "ja"},
                "dateien": {
                    "werkzeuge": ["run_command"],
                    "innerhalb_der_ordner": {"chat": chat, "agent": agent},
                    "ausserhalb_der_ordner": {"chat": "fragen", "agent": "nein"},
                },
            }
        ),
        encoding="utf-8",
    )
    return path


async def _run(client, config, tmp_path, *, ask_in_chat: bool, rules: Path, answer=None):
    """One job run whose model calls ``run_command`` once and then answers;
    returns the run's events, the request after the call and the run.

    ``answer`` is what the window sends once the run asks — ``None`` for
    nobody answering."""
    folder = tmp_path / "work"
    folder.mkdir(exist_ok=True)
    agents = Path(config.app.agenten_verzeichnis)
    agents.mkdir(parents=True, exist_ok=True)
    (agents / "bote.md").write_text(
        "---\nmodel: test\nmax_rounds: 3\n---\n\nDeliver things.\n", encoding="utf-8"
    )
    client.app.state.config.features.mcp = True
    state = client.app.state.discovery.zustaende["test"]
    state.endpunkt.capabilities.tool_calls = True
    provider = provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["Done."],
            werkzeugaufrufe=[
                Werkzeugaufruf(id="c1", name="run_command", argumente={"command": "echo hello"})
            ],
        ),
    )
    registry = WerkzeugRegistry([], shell_an=True, berechtigungen_pfad=rules)
    repositories = client.app.state.repositories
    generations = client.app.state.generierungen
    chat_id = client.post("/api/v1/chats", json={"title": "Chat"}).json()["id"]
    job = auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=generations,
        registry=registry,
        agent=agenten_laden(agents)["bote"],
        task="Say hello.",
        endpoint_id=None,
        ordner=[str(folder)],
        user_id="standard",
        sprache="de",
        chat_id=chat_id if ask_in_chat else None,
        ask_in_chat=ask_in_chat,
    )
    run = generations.holen(job.generation_id)
    deadline = time.monotonic() + 8.0
    answered = False
    states_while_asking: list[str] = []
    while time.monotonic() < deadline:
        if "c1" in run.bestaetigungen and not states_while_asking:
            states_while_asking.append(repositories.auftraege.holen(job.id).zustand)
        if not answered and "c1" in run.bestaetigungen and answer is not None:
            generations.bestaetigen(run.id, "c1", answer)
            answered = True
        row = repositories.auftraege.holen(job.id)
        if row is not None and row.zustand in ENDE:
            break
        await asyncio.sleep(0.01)
    await wakes_settled()
    events = [json.loads(line.removeprefix("data: ")) for line in run.ereignisse]
    return (
        events,
        provider.letzte_anfrage,
        repositories.auftraege.holen(job.id),
        {"chat_id": chat_id, "generation_id": run.id, "states": states_while_asking},
    )


def _tool_result(request) -> str:
    return next(n.content for n in request.nachrichten if n.role == "tool")


async def test_a_call_the_chat_would_ask_about_is_asked_in_the_chat(client, config, tmp_path):
    rules = _rules(tmp_path, chat="fragen", agent="ja")

    events, request, job, ids = await _run(
        client, config, tmp_path, ask_in_chat=True, rules=rules, answer=True
    )

    (asked,) = [e for e in events if e["typ"] == "tool_confirm"]
    assert asked["name"] == "run_command"
    assert asked["aufruf_id"] == "c1"
    assert asked["agent"] == "bote"
    assert asked["chat_id"] == ids["chat_id"]
    # The id the window answers under: the run's, not the chat's.
    assert asked["generation_id"] == ids["generation_id"]
    assert "hello" in _tool_result(request)
    assert job.zustand == "fertig"


async def test_nobody_answering_refuses_the_call_and_the_run_goes_on(
    client, config, tmp_path, monkeypatch
):
    monkeypatch.setattr(generierung_api, "BESTAETIGUNG_WARTEZEIT", 0.2)
    rules = _rules(tmp_path, chat="fragen", agent="ja")

    _events, request, job, _chat = await _run(
        client, config, tmp_path, ask_in_chat=True, rules=rules
    )

    assert _tool_result(request) == auftraege_api.NOBODY_APPROVED.format(name="run_command")
    assert job.zustand == "fertig"


async def test_a_no_in_the_chat_refuses_the_call(client, config, tmp_path):
    rules = _rules(tmp_path, chat="fragen", agent="ja")

    _events, request, job, _chat = await _run(
        client, config, tmp_path, ask_in_chat=True, rules=rules, answer=False
    )

    assert "hello" not in _tool_result(request)
    assert "run_command" in _tool_result(request)
    assert job.zustand == "fertig"


async def test_the_chat_mode_lets_through_what_the_agent_mode_would_refuse(
    client, config, tmp_path
):
    """The chat's mode judges, not the agent's: what the chat runs without
    asking runs for the agent it sent off too."""
    rules = _rules(tmp_path, chat="ja", agent="fragen")

    events, request, _auftrag, _chat = await _run(
        client, config, tmp_path, ask_in_chat=True, rules=rules
    )

    assert not [e for e in events if e["typ"] == "tool_confirm"]
    assert "hello" in _tool_result(request)


async def test_silent_a_run_started_by_hand_or_schedule_is_judged_as_before(
    client, config, tmp_path
):
    """The agent's own mode: what it would ask about is refused outright,
    nothing is asked anywhere."""
    rules = _rules(tmp_path, chat="ja", agent="fragen")

    events, request, job, _chat = await _run(
        client, config, tmp_path, ask_in_chat=False, rules=rules
    )

    assert not [e for e in events if e["typ"] == "tool_confirm"]
    assert "unavailable during an unattended run" in _tool_result(request)
    assert job.zustand == "fertig"


def test_only_the_chat_models_start_job_asks_in_the_chat():
    """The chat's start_job is the one caller that sends a run off with
    ``ask_in_chat``; the start window, schedules, child runs and
    continuations leave it out."""
    import inspect

    from app.api.v1 import cronjobs as cronjobs_api
    from app import wecker

    chat = inspect.getsource(generierung_api)
    assert chat.count("ask_in_chat=True") == 1
    for module in (auftraege_api, cronjobs_api, wecker):
        assert "ask_in_chat=True" not in inspect.getsource(module)


async def test_the_run_stands_as_waiting_while_it_asks(client, config, tmp_path):
    """The job list shows the run waiting while the chat is asked, and
    running again once it is answered — as for a question of its own."""
    rules = _rules(tmp_path, chat="fragen", agent="ja")

    _events, _anfrage, job, ids = await _run(
        client, config, tmp_path, ask_in_chat=True, rules=rules, answer=True
    )

    assert ids["states"] == ["wartet"]
    assert job.zustand == "fertig"
