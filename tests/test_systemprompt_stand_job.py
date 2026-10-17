"""A job's system message as the run really builds it.

The sentences themselves are pinned in tests/test_systemprompt_stand_prompt.py;
here it is the wiring: who started the run decides the access sentence, the
dock is named as the program's folder, the memory tool promises what holds
for the model's side, and a skill is listed only with its tool.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from app import gedaechtnis, skills
from app.agenten import agenten_laden
from app.agentendock import AgentenDock
from app.api.v1.auftraege import auftrag_anstossen
from app.providers import MockProvider, mock_endpunkt
from app.tools import memory, skill
from app.tools.registry import WerkzeugRegistry
from tests.conftest import provider_setzen, wakes_settled

ENDE = {"fertig", "abgebrochen", "gescheitert", "unterbrochen"}


def _rules(tmp_path: Path) -> Path:
    """Inside the folders everybody runs; outside, a chat asks and an agent
    of its own is refused."""
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps(
            {
                "standard": {"chat": "ja", "agent": "ja"},
                "dateien": {
                    "werkzeuge": ["run_command", "read_file", "write_file", "edit_file"],
                    "innerhalb_der_ordner": {"chat": "ja", "agent": "ja"},
                    "ausserhalb_der_ordner": {"chat": "fragen", "agent": "nein"},
                },
            }
        ),
        encoding="utf-8",
    )
    return path


async def _request(
    client, config, tmp_path, *, ask_in_chat=False, folders=True, tools="", registry=None
):
    """One job run that answers at once; returns its first request."""
    agents = Path(config.app.agenten_verzeichnis)
    agents.mkdir(parents=True, exist_ok=True)
    head = "---\nmodel: test\nmax_rounds: 3\n"
    if tools:
        head += f"tools: [{tools}]\n"
    (agents / "bote.md").write_text(head + "---\n\nDeliver things.\n", encoding="utf-8")
    folder = tmp_path / "work"
    folder.mkdir(exist_ok=True)
    client.app.state.config.features.mcp = True
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Done."]))
    registry = registry or WerkzeugRegistry(
        [], shell_an=True, berechtigungen_pfad=_rules(tmp_path),
        agentendock=AgentenDock(tmp_path / "dock"),
    )
    repositories = client.app.state.repositories
    chat_id = client.post("/api/v1/chats", json={"title": "Chat"}).json()["id"]
    job = auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=registry,
        agent=agenten_laden(agents)["bote"],
        task="Say hello.",
        endpoint_id=None,
        ordner=[str(folder)] if folders else None,
        user_id="standard",
        sprache="de",
        chat_id=chat_id if ask_in_chat else None,
        ask_in_chat=ask_in_chat,
    )
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        row = repositories.auftraege.holen(job.id)
        if row is not None and row.zustand in ENDE:
            break
        await asyncio.sleep(0.01)
    await wakes_settled()
    return provider.alle_anfragen[0], folder


def _system(request) -> str:
    return " ".join(request.nachrichten[0].content.split())


async def test_a_run_the_chat_sent_off_reads_the_chats_access(client, config, tmp_path):
    request, _folder = await _request(client, config, tmp_path, ask_in_chat=True)
    text = _system(request)
    assert "outside them, they ask the user first" in text
    assert "put to them in the chat this job was started from" in text
    assert "rejected outright" not in text


async def test_a_run_started_by_hand_reads_the_agents_access(client, config, tmp_path):
    """The silence probe: nobody is asked, and the prompt says so."""
    request, _folder = await _request(client, config, tmp_path, ask_in_chat=False)
    text = _system(request)
    assert "outside them, they are refused" in text
    assert "rejected outright" in text
    assert "put to them in the chat" not in text


async def test_the_dock_is_not_named_a_share(client, config, tmp_path):
    from app import agentendock, speicherorte

    request, folder = await _request(client, config, tmp_path)
    content = request.nachrichten[0].content
    dock = str(speicherorte.ort(config, agentendock.ORT_NAME))
    shared = content.split("The user has shared these working folders with you:\n\n")[1]
    assert shared.split("\n\n")[0] == f"- {folder}"
    assert "The dock folder holds finished files delivered to the user" in " ".join(content.split())
    assert f"- {dock}" in content


async def test_a_run_with_only_the_dock_has_no_note_duty(client, config, tmp_path):
    """No folder of the user's: the dock is the only one, and it is no
    share — no exe.md to keep, even with both file tools in hand."""
    request, _folder = await _request(
        client, config, tmp_path, folders=False, tools="read_file, write_file, edit_file"
    )
    text = _system(request)
    assert "The user has shared" not in text
    assert "Keeping each `exe.md` current" not in text
    assert "The dock folder holds finished files delivered to the user" in text


async def test_a_shared_folder_keeps_the_note_duty(client, config, tmp_path):
    """The silence probe: with a folder of the user's the duty stands."""
    request, _folder = await _request(
        client, config, tmp_path, tools="read_file, write_file, edit_file"
    )
    assert "Keeping each `exe.md` current" in _system(request)


def _memory_tools(request) -> list[dict]:
    return [w for w in request.werkzeuge if w["function"]["name"] == memory.WERKZEUG_NAME]


async def test_the_memory_tool_of_a_job_follows_the_switch(client, config, tmp_path):
    """The test endpoint is a provider: the memory stays away by default and
    the job has no memory tool then; it has it once its side is switched on."""
    registry = WerkzeugRegistry(
        [], shell_an=True, berechtigungen_pfad=_rules(tmp_path),
        memory_pfad=tmp_path / "memory.md",
    )
    request, _folder = await _request(
        client, config, tmp_path, tools="memory_save", registry=registry
    )
    assert _memory_tools(request) == []

    client.app.state.repositories.einstellungen.setzen(
        "global", gedaechtnis.SCHLUESSEL, {"lokal": True, "cloud": True}
    )
    request, _folder = await _request(
        client, config, tmp_path, tools="memory_save", registry=registry
    )
    (entry,) = _memory_tools(request)
    assert "in the next conversation, not immediately" in entry["function"]["description"]


async def test_a_job_lists_no_skill_whose_tool_it_lacks(client, config, tmp_path, monkeypatch):
    """Only the shipped skills, read from the program's own folder: the ones
    built on draw_image, cronjob and ask_user stay out of a run that has
    none of them; one that needs no tool stays in."""
    project = Path(__file__).resolve().parent.parent
    places = (project / "skills", tmp_path / "own-skills")
    original = skills.skills_laden
    monkeypatch.setattr(skills, "skills_laden", lambda *_places: original(*places))
    registry = WerkzeugRegistry(
        [], shell_an=True, berechtigungen_pfad=_rules(tmp_path), skills_orte=places,
    )
    request, _folder = await _request(
        client, config, tmp_path, tools=skill.LADEN, registry=registry
    )
    text = request.nachrichten[0].content
    assert "- handoff —" in text
    assert "- image-generator —" not in text
    assert "- cronjob —" not in text
    assert "- grill-me —" not in text
