"""The folder tool `create_folder` (app/tools/create_folder.py).

It creates a folder and shares it the way the folder chip does: with the
chat, or with the chat's project. It is judged by the path rule of the file
tools (app/berechtigungen.py), counts from the next call of the same run on,
and leaves the run's system message as it was.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app import berechtigungen, berechtigungswahl
from app.berechtigungsregeln import laden
from app.configwanderung import file_tool_added
from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Stueck, Werkzeugaufruf
from app.tools import create_folder
from app.tools.registry import WerkzeugRegistry, WerkzeugVerboten
from tests.conftest import provider_setzen
from tests.test_auftraege_api import agent_schreiben, auf_ende_warten, mcp_client_echt  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent


def _registry(repos, data_dir=None) -> WerkzeugRegistry:
    return WerkzeugRegistry([], shell_an=True, folder_share=create_folder.ChatFolderShare(repos, data_dir))


def _chat(repos, folders: list[str]):
    chat = repos.chats.erstellen(user_id="u", title="t")
    repos.chats.aktualisieren(chat.id, working_dirs=folders)
    return chat


def _run(registry, path: str, folders: list[str], chat_id: str | None, origin="chat") -> str:
    return asyncio.run(registry.ausfuehren(
        create_folder.WERKZEUG_NAME, {"path": path}, ordner=folders, chat_id=chat_id, herkunft=origin,
    ))


def test_the_folder_is_made_shared_with_the_chat_and_counts_inside_in_the_same_run(repos, tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    chat = _chat(repos, [str(shared)])
    folders = [str(shared)]

    result = _run(_registry(repos), "../drafts", folders, chat.id)

    new = str((tmp_path / "drafts").resolve())
    assert (tmp_path / "drafts").is_dir()
    assert new in result and "this chat" in result
    assert repos.chats.holen(chat.id).working_dirs == [str(shared), new]
    # The run's own list grew in place: a write into the new folder is
    # inside from the next call on.
    assert folders == [str(shared), new]
    assert berechtigungen._dateiwerkzeug_aussenpfad("write_file", {"path": f"{new}/a.txt"}, folders) is None
    # Sharing puts an exe.md in, as the chip does.
    assert (tmp_path / "drafts" / "exe.md").exists()


def test_in_a_project_every_chat_of_the_project_gets_it(repos, tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    project = repos.projects.create(user_id="u", name="p")
    repos.projects.update(project.id, working_dirs=[str(shared)])
    first = repos.chats.erstellen(user_id="u", title="a")
    second = repos.chats.erstellen(user_id="u", title="b")
    outside = _chat(repos, [str(shared)])
    repos.projects.add_chat(project.id, first.id)
    repos.projects.add_chat(project.id, second.id)

    _run(_registry(repos), "new", [str(shared)], first.id)

    new = str((shared / "new").resolve())
    assert repos.projects.get(project.id).working_dirs == [str(shared), new]
    assert new in repos.chats.holen(second.id).working_dirs
    # Silence probe: a chat outside the project does not get it.
    assert repos.chats.holen(outside.id).working_dirs == [str(shared)]


def test_silence_probe_a_folder_already_shared_is_not_added_twice(repos, tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    chat = _chat(repos, [str(shared)])
    folders = [str(shared)]

    result = _run(_registry(repos), str(shared), folders, chat.id)

    assert "already a working folder" in result
    assert repos.chats.holen(chat.id).working_dirs == [str(shared)]
    assert folders == [str(shared)]


def test_nothing_is_made_in_the_programs_own_data_folder(repos, tmp_path):
    # A chat sharing nothing resolves a relative path in its private
    # document folder, which lies in the program's data.
    data_dir = tmp_path / "data"
    own = data_dir / "chats" / "c1"
    own.mkdir(parents=True)
    chat = _chat(repos, [])

    with pytest.raises(WerkzeugVerboten, match="own data folder"):
        _run(_registry(repos, data_dir), "notes", [str(own)], chat.id)
    # The same folder spelled with other capitals is still the data folder.
    shouted = str(own).replace("/data/", "/DATA/")
    with pytest.raises(WerkzeugVerboten, match="own data folder"):
        _run(_registry(repos, data_dir), f"{shouted}/notes", [str(own)], chat.id)

    assert not (own / "notes").exists()
    assert repos.chats.holen(chat.id).working_dirs == []


def test_a_folder_that_cannot_be_shared_is_taken_back(repos, tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    chat = _chat(repos, [str(shared)])

    def refuses(chat_id, path):
        raise RuntimeError("the table is locked")

    registry = WerkzeugRegistry([], shell_an=True, folder_share=refuses)
    with pytest.raises(RuntimeError):
        _run(registry, "later/deep/down", [str(shared)], chat.id)

    # Everything the call made goes, its new parents included.
    assert not (shared / "later").exists()


def test_taking_back_keeps_what_somebody_else_put_there(repos, tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    chat = _chat(repos, [str(shared)])

    def someone_writes_then_it_fails(chat_id, path):
        (Path(path).parent / "theirs.txt").write_text("keep")
        raise RuntimeError("the table is locked")

    registry = WerkzeugRegistry([], shell_an=True, folder_share=someone_writes_then_it_fails)
    with pytest.raises(RuntimeError):
        _run(registry, "later/deep", [str(shared)], chat.id)

    assert not (shared / "later" / "deep").exists()
    assert (shared / "later" / "theirs.txt").read_text() == "keep"


def test_a_job_run_shares_the_folder_with_the_run_only(repos, tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    chat = _chat(repos, [str(shared)])
    folders = [str(shared)]

    # A job run hands its own id in as `chat_id`; nothing is stored for it.
    result = _run(_registry(repos), "out", folders, chat.id, origin="agent")

    assert "this run" in result
    assert str((shared / "out").resolve()) in folders
    assert repos.chats.holen(chat.id).working_dirs == [str(shared)]


def _rules(tmp_path, origin: str, mode: str):
    path = tmp_path / f"{origin}-{mode}.json"
    berechtigungswahl.anwenden(path, origin, mode)
    return laden(path)


def test_inside_the_shared_folders_the_mode_decides(tmp_path):
    folders = [str(tmp_path)]
    for mode, answer in (("restricted", "fragen"), ("manuell", "ja"), ("auto", "ja")):
        verdict = berechtigungen.urteil(
            "create_folder", {"path": "inside"}, folders, "chat", regeln=_rules(tmp_path, "chat", mode),
        )
        assert verdict.antwort == answer, mode


def test_outside_it_asks_in_a_chat_and_is_refused_in_a_job(tmp_path):
    (tmp_path / "shared").mkdir()
    folders = [str(tmp_path / "shared")]
    elsewhere = {"path": str(tmp_path / "elsewhere")}
    rules = laden(tmp_path / "missing.json")
    assert berechtigungen.urteil("create_folder", elsewhere, folders, "chat", regeln=rules).antwort == "fragen"
    assert berechtigungen.urteil("create_folder", elsewhere, folders, "agent", regeln=rules).antwort == "nein"


def test_an_existing_permission_file_gets_the_tool_added_once(tmp_path):
    rules_file = tmp_path / "berechtigungen.json"
    template = (ROOT / "berechtigungen.example.json").read_text(encoding="utf-8")
    rules_file.write_text(template.replace(', "create_folder"', ""), encoding="utf-8")

    assert file_tool_added(rules_file, "create_folder") is True
    assert "create_folder" in json.loads(rules_file.read_text())["dateien"]["werkzeuge"]
    assert laden(rules_file).dateiwerkzeuge[-1] == "create_folder"
    # Silence probe: a second start changes nothing, an emptied list stays empty.
    assert file_tool_added(rules_file, "create_folder") is False
    empty = tmp_path / "empty.json"
    empty.write_text('{"dateien": {"werkzeuge": []}}', encoding="utf-8")
    assert file_tool_added(empty, "create_folder") is False


class _MakesAFolderThenWrites(MockProvider):
    """Calls create_folder in its first round, writes a file into the new
    folder in its second — by the folder's full path — then answers."""

    def __init__(self, target: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target = target
        self.requests: list = []

    async def streamen(self, anfrage):
        self.requests.append([(n.role, n.content) for n in anfrage.nachrichten])
        calls = {
            1: Werkzeugaufruf(id="c1", name="create_folder", argumente={"path": self.target}),
            2: Werkzeugaufruf(id="c2", name="write_file", argumente={"path": f"{self.target}/note.md", "content": "x"}),
        }
        if (call := calls.get(len(self.requests))) is not None:
            yield Stueck("tool_call", werkzeugaufrufe=[call])
            return
        yield Stueck("content", text="Done.")


def test_in_a_chat_run_the_system_message_stays_the_same_and_the_chat_gets_the_folder(
    client, chat_id, tmp_path
):
    repos = client.app.state.repositories
    shared = tmp_path / "shared"
    shared.mkdir()
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(shared)]})
    client.app.state.werkzeuge = _registry(repos, client.app.state.config.datenverzeichnis)
    client.app.state.config.features.mcp = True
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    target = str((shared / "made").resolve())
    provider = provider_setzen(client, _MakesAFolderThenWrites(target, mock_endpunkt("test")))

    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Make a folder."},
    ).text

    assert len(provider.requests) == 3
    first, second = provider.requests[0], provider.requests[1]
    assert first[0][0] == "system" and second[0] == first[0]
    assert provider.requests[2][0] == first[0]
    assert target in next(content for role, content in second if role == "tool")
    assert target in client.get(f"/api/v1/chats/{chat_id}").json()["working_dirs"]
    assert (shared / "made" / "note.md").read_text() == "x"


def test_in_a_job_run_a_folder_outside_is_refused(config, mcp_client_echt, tmp_path):  # noqa: F811
    """A job cannot be asked, so outside its folders `create_folder` is
    refused like `write_file`, and nothing is made."""
    shared = tmp_path / "shared"
    shared.mkdir()
    agent_schreiben(
        config,
        kopf=f"model: test\ntools:\n  - create_folder\n  - write_file\nfolders:\n  - {shared}\nmax_rounds: 4",
    )
    target = str((tmp_path / "made").resolve())
    provider_setzen(mcp_client_echt, _MakesAFolderThenWrites(target, mock_endpunkt("test")))

    job = mcp_client_echt.post("/api/v1/jobs", json={"agent": "recherche", "task": "Go"}).json()["id"]
    auf_ende_warten(mcp_client_echt, job)

    assert not (tmp_path / "made").exists()


def test_in_a_job_run_a_folder_made_inside_takes_the_next_write(config, mcp_client_echt, tmp_path):  # noqa: F811
    shared = tmp_path / "shared"
    shared.mkdir()
    agent_schreiben(
        config,
        kopf=f"model: test\ntools:\n  - create_folder\n  - write_file\nfolders:\n  - {shared}\nmax_rounds: 4",
    )
    target = str((shared / "made").resolve())
    provider_setzen(mcp_client_echt, _MakesAFolderThenWrites(target, mock_endpunkt("test")))

    job = mcp_client_echt.post("/api/v1/jobs", json={"agent": "recherche", "task": "Go"}).json()["id"]
    state = auf_ende_warten(mcp_client_echt, job)

    assert state["state"] == "fertig"
    assert (shared / "made" / "note.md").read_text() == "x"
    # No exe.md: a job's folder is shared with the run, not stored.
    assert not (shared / "made" / "exe.md").exists()
