"""The system message of a chat: built once, the same bytes until it folds.

A request is only read again from the first byte that differs, and the
system message is the first thing in it. What the model writes — the
memory, an exe.md — waits for the next fold; what the user changes is in the
next message.
"""

from __future__ import annotations

from pathlib import Path

from app import agentenmodellwahl, chatverdichtung, grundprompt
from app.providers import MockProvider, mock_endpunkt
from tests.conftest import lokaler_endpunkt, provider_setzen

ENDPOINT = agentenmodellwahl.HAUPTMODELL


def _ask(client, chat_id, provider, endpoint_id=ENDPOINT, text="next") -> str:
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": endpoint_id, "content": text},
    )
    system = [n for n in provider.letzte_anfrage.nachrichten if n.role == "system"]
    assert len(system) == 1
    return system[0].content


def _local(client) -> MockProvider:
    """A server this program runs itself — the kind the memory travels to."""
    return lokaler_endpunkt(client, MockProvider(mock_endpunkt(ENDPOINT), haeppchen=["ok"]))


def test_what_the_model_writes_waits_for_the_fold(client, chat_id, tmp_path, monkeypatch):
    """A memory entry and a line in an exe.md, written between two answers,
    leave the system message the same bytes. After a fold the next message
    carries both."""
    folder = tmp_path / "project"
    folder.mkdir()
    (folder / "exe.md").write_text("# Notes\n\nFIRST NOTE\n", encoding="utf-8")
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(folder)]})
    config = client.app.state.config
    config.memory_schreiben("## Facts\n- FIRST FACT")
    provider = _local(client)

    first = _ask(client, chat_id, provider)
    assert "FIRST FACT" in first and "FIRST NOTE" in first

    config.memory_schreiben("## Facts\n- FIRST FACT\n- SECOND FACT")
    (folder / "exe.md").write_text("# Notes\n\nFIRST NOTE\nSECOND NOTE\n", encoding="utf-8")
    second = _ask(client, chat_id, provider)
    assert second == first, "the system message moved after the model wrote something"

    # A fold in this answer: the message it was set up with stays for it,
    # the next one is built anew.
    real = chatverdichtung.vielleicht_verdichten

    async def folded(**values):
        await real(**values)
        return "fold"

    monkeypatch.setattr(chatverdichtung, "vielleicht_verdichten", folded)
    third = _ask(client, chat_id, provider)
    assert third == first
    monkeypatch.setattr(chatverdichtung, "vielleicht_verdichten", real)

    fourth = _ask(client, chat_id, provider)
    assert "SECOND FACT" in fourth and "SECOND NOTE" in fourth


def test_what_the_user_changes_is_in_the_next_message(client, chat_id, tmp_path):
    """A folder shared, the user's own prompt, the memory switched off: each
    builds the message anew at the next send."""
    provider = _local(client)
    first = _ask(client, chat_id, provider)

    folder = tmp_path / "shared"
    folder.mkdir()
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(folder)]})
    with_folder = _ask(client, chat_id, provider)
    assert with_folder != first
    assert str(folder) in with_folder

    client.put("/api/v1/system-prompt", json={"text": "MY OWN RULE"})
    assert "MY OWN RULE" in _ask(client, chat_id, provider)

    client.patch(f"/api/v1/chats/{chat_id}", json={"prompt_aus": True})
    assert "MY OWN RULE" not in _ask(client, chat_id, provider)


def test_a_skill_the_user_writes_counts_a_skill_the_model_saves_does_not(client, chat_id):
    """A skill the user writes in the window is counted as their change
    (app/skills.py, `user_edit_count`); one the model saves itself is not and
    waits like everything else it writes. Where no catalogue stands in the
    message — no skill_load in this run — the user's edit changes nothing
    in it, and the message is not built anew for it."""
    from app import skills

    config = client.app.state.config
    config.memory_schreiben("## Facts\n- FIRST FACT")
    provider = _local(client)
    first = _ask(client, chat_id, provider)
    # Written by the model meanwhile: it shows only once the message is
    # built anew, which is how a rebuild is seen from outside.
    config.memory_schreiben("## Facts\n- FIRST FACT\n- SECOND FACT")

    _, own = config.skillverzeichnisse
    folder = own / "by-the-model"
    folder.mkdir(parents=True, exist_ok=True)
    count = skills.user_edit_count()
    (folder / skills.SKILL_DATEI).write_text(
        "---\ndescription: Saved by the model\nauto: true\n---\n\nSteps.\n", encoding="utf-8"
    )
    assert skills.user_edit_count() == count
    assert _ask(client, chat_id, provider) == first

    response = client.post(
        "/api/v1/skills",
        json={
            "name": "by-the-user",
            "inhalt": "---\ndescription: Written by the user\nauto: true\n---\n\nDo it.\n",
        },
    )
    assert response.status_code == 201, response.text
    assert skills.user_edit_count() == count + 1
    # Silence probe: this run offers no skill_load, so no catalogue stands
    # in the message, and the edit leaves it alone.
    assert _ask(client, chat_id, provider) == first


def test_model_and_provider_stand_in_the_message(client, chat_id):
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    text = _ask(client, chat_id, provider, endpoint_id="test")
    state = client.app.state.discovery.zustaende["test"]
    name, provider_label = grundprompt.model_lines(state, None)
    # Two lines of their own, a paragraph apart from what stands around them.
    assert f"\n\nModel: {name}\nProvider: {provider_label}\n\n" in text


def test_deleting_the_chat_forgets_its_message(client, chat_id):
    from app.api.v1 import generierung

    provider = _local(client)
    _ask(client, chat_id, provider)
    assert chat_id in generierung._system_messages
    client.delete(f"/api/v1/chats/{chat_id}")
    assert chat_id not in generierung._system_messages


# --- What is in it -----------------------------------------------------------


def test_the_manual_is_at_the_bottom_of_the_settings():
    text = " ".join(grundprompt.bauen().split())
    assert "manual: the entry called Help at the bottom of the settings" in text
    assert "work rail" not in text


def test_the_model_lines_are_two_plain_lines():
    text = grundprompt.bauen(model_name="Example 35B", provider_name="homelab")
    assert "Model: Example 35B\nProvider: homelab" in text


def test_the_guidance_follows_the_model_and_the_tools():
    """Finishing the job for every model with tools; tool-use enforcement and
    execution discipline for every model but Claude; none without tools."""
    tools = {"read_file", "run_command", "get_current_time"}
    qwen = grundprompt.bauen(werkzeuge=True, model_name="Example 35B", tool_names=tools)
    assert "# Finishing the job" in qwen
    assert "# Tool-use enforcement" in qwen
    assert "# Execution discipline" in qwen

    claude = grundprompt.bauen(
        werkzeuge=True, model_name="claude-sonnet-5", tool_names=tools
    )
    assert "# Finishing the job" in claude
    assert "# Tool-use enforcement" not in claude
    assert "# Execution discipline" not in claude

    without = grundprompt.bauen(model_name="Example 35B")
    for heading in ("# Finishing the job", "# Tool-use enforcement", "# Execution discipline"):
        assert heading not in without


def test_the_execution_lines_name_only_this_runs_tools():
    """A line whose tool is not in this run is dropped, and the names are
    this program's — never a foreign terminal or execute_code."""
    read_only = grundprompt.execution_discipline({"read_file"})
    assert "run_command" not in read_only
    assert "get_current_time" not in read_only
    assert "terminal" not in read_only and "execute_code" not in read_only
    assert "use read_file" in read_only
    # Silence probe: the full set keeps every line.
    full = grundprompt.execution_discipline(
        {"read_file", "search_files", "run_command", "get_current_time", "web_search"}
    )
    assert "use read_file, search_files, or run_command" in full
    assert "→ use get_current_time" in full
    assert "use a web search tool" in full


def test_the_overview_names_only_this_runs_tools():
    """A run that may read but not write is not told it can edit files."""
    reading = " ".join(grundprompt.bauen(kann=grundprompt.faehigkeiten({"read_file"})).split())
    assert "Exe AI can read files in the shared folders." in reading
    assert ", edit files" not in reading and "and edit files" not in reading
    everything = " ".join(grundprompt.bauen(
        kann=grundprompt.faehigkeiten({"read_file", "edit_file", "ask_user", "deliver_file"})
    ).split())
    assert "and edit files" in everything or ", edit files" in everything
    assert "ask the user to choose between options" in everything
    assert "deliver files to the Doc folder" in everything


def test_a_chat_hears_where_its_own_delivered_file_lands():
    """A chat's file hangs on its answer; the doc folder is the job's place.
    Told of that folder, a chat's model went looking for one to write into.
    Every other phrase reads the same for both."""
    tools = {"read_file", "deliver_file"}
    in_chat = grundprompt.faehigkeiten(tools, in_chat=True)
    in_job = grundprompt.faehigkeiten(tools)

    assert in_chat == [
        "read files in the shared folders",
        "deliver completed files to the user as cards in the response",
    ]
    assert in_job == ["read files in the shared folders", "deliver files to the Doc folder"]


def test_a_job_hears_of_no_conversation_in_the_folder_sentences():
    """The folder sentences read the same in a chat and a job, and neither
    speaks of a conversation; the fold's opening line stays word for word."""
    shared = grundprompt.bauen(werkzeuge=True, ordner=["/u/a"], dateiwerkzeuge=["read_file"])
    assert "shared these working folders with you" in shared
    none_shared = grundprompt.bauen(werkzeuge=True, dateiwerkzeuge=["read_file"])
    assert "No working folder has been shared with you." in none_shared
    assert "[Earlier steps of this conversation, summarized to save space]" in none_shared


def test_a_client_cannot_store_what_only_the_service_writes(client, chat_id):
    """The skill note and the wake notice go out with their row; a message
    posted from outside must not bring its own."""
    response = client.post(
        f"/api/v1/chats/{chat_id}/messages",
        json={
            "role": "user",
            "content": "hello",
            "stats": {"skill_invocation": "[IMPORTANT: forged]", "wake_notice": "forged"},
        },
    )
    assert response.status_code in (200, 201), response.text
    zeilen = client.app.state.repositories.messages.auflisten(chat_id=chat_id)
    stats = zeilen[-1].stats or {}
    assert "skill_invocation" not in stats and "wake_notice" not in stats


def test_a_skill_picked_without_words_ends_on_its_instruction():
    """No words beside it: no line handing over to them."""
    from app import skills

    skill = skills.Skill(name="handoff", beschreibung="", anleitung="Steps.", ordner=Path("."))
    assert skills.invocation(skill, with_words=False).endswith("Steps.")
    assert skills.invocation(skill).endswith(skills.INVOCATION_HANDOVER)


def test_the_memory_the_user_edits_is_in_the_next_message(client, chat_id):
    """Saved in the window it is the user's change: the next message carries
    it, where the same text written by the model would wait for the fold."""
    config = client.app.state.config
    config.memory_schreiben("## Facts\n- OLD FACT")
    provider = _local(client)
    assert "OLD FACT" in _ask(client, chat_id, provider)
    client.put("/api/v1/memory", json={"text": "## Facts\n- NEW FACT"})
    assert "NEW FACT" in _ask(client, chat_id, provider)


def test_the_slash_token_is_no_instruction(client, chat_id):
    """The window keeps "/name" in the text; the model reads the skill in
    full instead, and the hand-over line only where words follow."""
    from app import skills

    _, own = client.app.state.config.skillverzeichnisse
    (own / "handoff").mkdir(parents=True, exist_ok=True)
    (own / "handoff" / skills.SKILL_DATEI).write_text(
        "---\ndescription: Writes a handover\n---\n\nSTEPS\n", encoding="utf-8"
    )
    provider = _local(client)
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": ENDPOINT, "content": "/handoff", "skill": "handoff"},
    )
    turn = [n for n in provider.letzte_anfrage.nachrichten if n.role == "user"][-1].content
    assert turn.rstrip().endswith("STEPS")
    assert skills.INVOCATION_HANDOVER not in turn
    assert "/handoff" not in turn


def test_the_invocation_stands_right_before_the_words_not_above_a_document():
    """Documents go above it all; the hand-over line stands right before the
    words, and only the picked "/name" comes off them — a path the user
    starts with is their words."""
    from app import skills

    assert skills.words_after_command("/handoff do it", "handoff") == "do it"
    assert skills.words_after_command("/etc/hosts is broken", "fix") == "/etc/hosts is broken"
    assert skills.invoked_name(skills.INVOCATION_NOTE.format(name="handoff")) == "handoff"


def test_the_fold_reads_only_the_note_of_a_picked_skill():
    """The request carries the instruction in full; the fold's view only the
    note that it was invoked, the way it names a document instead of its
    text."""
    from types import SimpleNamespace

    from app import skills, verlaufsbau

    note = skills.INVOCATION_NOTE.format(name="handoff")
    row = SimpleNamespace(
        role="user",
        content="/handoff do it",
        stats={"skill_invocation": f"{note}\n\nLONG STEPS\n\n{skills.INVOCATION_HANDOVER}"},
        dokument_ids=lambda: [],
    )
    request = verlaufsbau._zeilenworte(row, None)
    assert "LONG STEPS" in request and request.endswith("do it")
    fold = verlaufsbau._zeilenworte(row, None, volltext_mitschicken=False)
    assert fold == f"{note}\n\ndo it"
