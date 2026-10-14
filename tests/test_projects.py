"""Projects and the archive.

A project bundles chats under a name and shares its folders with them; a
chat in a project works in the project's folders only. Instead of deleting
from the list, chats and projects are put into the archive, and only the
archive deletes for good — a project together with its chats.
"""

from __future__ import annotations

from app.db import repositories_erstellen
from app.db.connection import SCHEMA_VERSION, Database


def _folders(tmp_path, *names):
    paths = []
    for name in names:
        folder = tmp_path / name
        folder.mkdir()
        paths.append(str(folder.resolve()))
    return paths


def _chat(client, title="Chat"):
    return client.post("/api/v1/chats", json={"title": title}).json()


def _project(client, name="Website"):
    answer = client.post("/api/v1/projects", json={"name": name})
    assert answer.status_code == 201, answer.text
    return answer.json()


def _patch_chat(client, chat_id, **fields):
    answer = client.patch(f"/api/v1/chats/{chat_id}", json=fields)
    assert answer.status_code == 200, answer.text
    return answer.json()


def _listed_ids(client, **query):
    return [chat["id"] for chat in client.get("/api/v1/chats", params=query).json()]


def test_a_chat_in_a_project_gets_the_projects_folders(client, tmp_path):
    folders = _folders(tmp_path, "site", "assets")
    project = _project(client)
    client.patch(f"/api/v1/projects/{project['id']}", json={"working_dirs": folders})
    chat = _chat(client)

    moved = _patch_chat(client, chat["id"], project_id=project["id"])

    assert moved["project_id"] == project["id"]
    assert moved["working_dirs"] == folders
    assert client.get(f"/api/v1/chats/{chat['id']}").json()["working_dirs"] == folders


def test_a_folder_change_counts_for_every_chat_in_the_project(client, tmp_path):
    first, second = _folders(tmp_path, "one", "two")
    project = _project(client)
    chat_a, chat_b = _chat(client, "A"), _chat(client, "B")
    _patch_chat(client, chat_a["id"], project_id=project["id"])
    _patch_chat(client, chat_b["id"], project_id=project["id"])

    _patch_chat(client, chat_a["id"], working_dirs=[first, second])

    assert client.get(f"/api/v1/chats/{chat_b['id']}").json()["working_dirs"] == [first, second]
    projects = client.get("/api/v1/projects").json()
    assert projects[0]["working_dirs"] == [first, second]
    assert projects[0]["chat_count"] == 2


def test_a_chat_with_own_folders_brings_them_into_the_project(client, tmp_path):
    shared, own = _folders(tmp_path, "shared", "own")
    project = _project(client)
    client.patch(f"/api/v1/projects/{project['id']}", json={"working_dirs": [shared]})
    chat = _chat(client)
    _patch_chat(client, chat["id"], working_dirs=[own])

    moved = _patch_chat(client, chat["id"], project_id=project["id"])

    assert moved["working_dirs"] == [shared, own]
    assert client.get("/api/v1/projects").json()[0]["working_dirs"] == [shared, own]


def test_a_chat_leaving_the_project_keeps_its_folders(client, tmp_path):
    folders = _folders(tmp_path, "site", "assets")
    project = _project(client)
    client.patch(f"/api/v1/projects/{project['id']}", json={"working_dirs": folders})
    chat = _chat(client)
    _patch_chat(client, chat["id"], project_id=project["id"])

    left = _patch_chat(client, chat["id"], project_id=None)

    assert left["project_id"] is None
    assert left["working_dirs"] == folders
    # The project keeps them too: leaving copies, it does not take away.
    assert client.get("/api/v1/projects").json()[0]["working_dirs"] == folders


def test_a_fifth_folder_is_accepted(client, tmp_path):
    folders = _folders(tmp_path, "a", "b", "c", "d", "e")
    project = _project(client)
    chat = _chat(client)
    _patch_chat(client, chat["id"], project_id=project["id"])

    changed = _patch_chat(client, chat["id"], working_dirs=folders)

    assert changed["working_dirs"] == folders
    loose = _chat(client, "Loose")
    assert _patch_chat(client, loose["id"], working_dirs=folders)["working_dirs"] == folders


def test_a_chat_without_a_project_keeps_its_own_folders(client, tmp_path):
    """The silence probe: a project and its folders leave a chat outside it
    alone."""
    own, shared = _folders(tmp_path, "own", "shared")
    chat = _chat(client)
    _patch_chat(client, chat["id"], working_dirs=[own])
    project = _project(client)
    client.patch(f"/api/v1/projects/{project['id']}", json={"working_dirs": [shared]})
    other = _chat(client, "Other")
    _patch_chat(client, other["id"], project_id=project["id"])

    fetched = client.get(f"/api/v1/chats/{chat['id']}").json()
    assert fetched["project_id"] is None
    assert fetched["working_dirs"] == [own]


def test_archiving_takes_a_chat_out_of_the_list_and_restoring_brings_it_back(client):
    chat = _chat(client)
    client.post(f"/api/v1/chats/{chat['id']}/messages", json={"content": "Hello"})

    _patch_chat(client, chat["id"], archived=True)
    assert chat["id"] not in _listed_ids(client)
    assert _listed_ids(client, archived=True) == [chat["id"]]

    _patch_chat(client, chat["id"], archived=False)
    assert chat["id"] in _listed_ids(client)
    assert _listed_ids(client, archived=True) == []
    messages = client.get(f"/api/v1/chats/{chat['id']}/messages").json()["nachrichten"]
    assert [m["content"] for m in messages] == ["Hello"]


def test_archiving_and_restoring_leave_messages_and_folders_as_they_were(client, tmp_path):
    """The silence probe for the archive: putting a chat away changes where
    it is listed and nothing else."""
    folders = _folders(tmp_path, "keep")
    chat = _chat(client)
    _patch_chat(client, chat["id"], working_dirs=folders)
    for text in ("one", "two", "three"):
        client.post(f"/api/v1/chats/{chat['id']}/messages", json={"content": text})

    _patch_chat(client, chat["id"], archived=True)
    back = _patch_chat(client, chat["id"], archived=False)

    assert back["working_dirs"] == folders
    messages = client.get(f"/api/v1/chats/{chat['id']}/messages").json()["nachrichten"]
    assert len(messages) == 3


def test_an_archived_project_takes_its_chats_along(client):
    project = _project(client)
    inside, outside = _chat(client, "Inside"), _chat(client, "Outside")
    _patch_chat(client, inside["id"], project_id=project["id"])

    client.patch(f"/api/v1/projects/{project['id']}", json={"archived": True})

    assert _listed_ids(client) == [outside["id"]]
    assert client.get("/api/v1/projects").json() == []
    archived = client.get("/api/v1/projects", params={"archived": True}).json()
    assert [p["id"] for p in archived] == [project["id"]]
    assert archived[0]["chat_count"] == 1
    # Listed under its project in the archive, not as a chat of its own.
    assert _listed_ids(client, archived=True) == []

    client.patch(f"/api/v1/projects/{project['id']}", json={"archived": False})
    assert set(_listed_ids(client)) == {inside["id"], outside["id"]}


def test_deleting_in_the_archive_removes_the_project_and_its_chats(client):
    project = _project(client)
    chats = [_chat(client, "One"), _chat(client, "Two")]
    for chat in chats:
        _patch_chat(client, chat["id"], project_id=project["id"])
    kept = _chat(client, "Kept")
    client.patch(f"/api/v1/projects/{project['id']}", json={"archived": True})

    answer = client.delete(f"/api/v1/projects/{project['id']}")

    assert answer.status_code == 200
    assert sorted(answer.json()) == sorted(chat["id"] for chat in chats)
    for chat in chats:
        assert client.get(f"/api/v1/chats/{chat['id']}").status_code == 404
    assert client.get("/api/v1/projects", params={"archived": True}).json() == []
    assert _listed_ids(client) == [kept["id"]]


def test_a_run_that_does_not_end_leaves_the_project_whole(client, monkeypatch):
    """The project goes only when every chat's run has ended: a delete that
    stopped half-way would leave some chats gone and the window unaware."""
    from app import generationen

    monkeypatch.setattr(generationen, "RUN_END_TIMEOUT_SECONDS", 0.3)
    project = _project(client)
    chats = [_chat(client, "One"), _chat(client, "Two")]
    for chat in chats:
        _patch_chat(client, chat["id"], project_id=project["id"])
    client.patch(f"/api/v1/projects/{project['id']}", json={"archived": True})
    registry = client.app.state.generierungen
    stuck = registry.anmelden(chat_id=chats[1]["id"], endpoint_id="test")

    answer = client.delete(f"/api/v1/projects/{project['id']}")

    assert answer.status_code == 409
    for chat in chats:
        assert client.get(f"/api/v1/chats/{chat['id']}").status_code == 200
    assert stuck.soll_abbrechen
    registry.abmelden(stuck.id)
    assert client.delete(f"/api/v1/projects/{project['id']}").status_code == 200


def test_a_project_in_the_list_is_not_deleted(client):
    """Deleting goes only through the archive."""
    project = _project(client)
    chat = _chat(client)
    _patch_chat(client, chat["id"], project_id=project["id"])

    answer = client.delete(f"/api/v1/projects/{project['id']}")

    assert answer.status_code == 409
    assert client.get(f"/api/v1/chats/{chat['id']}").status_code == 200


def test_a_field_sent_as_null_changes_nothing(client, tmp_path):
    folders = _folders(tmp_path, "keep")
    project = _project(client)
    client.patch(f"/api/v1/projects/{project['id']}", json={"working_dirs": folders})

    answer = client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"archived": None, "name": None, "working_dirs": None},
    )

    assert answer.status_code == 200
    assert answer.json()["archived"] is False
    assert answer.json()["name"] == "Website"
    assert answer.json()["working_dirs"] == folders


def test_leaving_and_new_folders_in_one_change_stay_with_the_chat(client, tmp_path):
    """Both in one request: the new folders are the chat's own, and the
    project it left keeps what it had."""
    shared, own = _folders(tmp_path, "shared", "own")
    project = _project(client)
    client.patch(f"/api/v1/projects/{project['id']}", json={"working_dirs": [shared]})
    chat = _chat(client)
    _patch_chat(client, chat["id"], project_id=project["id"])

    left = _patch_chat(client, chat["id"], project_id=None, working_dirs=[own])

    assert left["project_id"] is None
    assert left["working_dirs"] == [own]
    assert client.get("/api/v1/projects").json()[0]["working_dirs"] == [shared]


def test_joining_with_a_folder_list_makes_it_the_projects_list(client, tmp_path):
    """A list sent along with the move is the project's whole new list, and
    it is checked against what the project already shares."""
    shared, extra = _folders(tmp_path, "shared", "extra")
    project = _project(client)
    client.patch(f"/api/v1/projects/{project['id']}", json={"working_dirs": [shared]})
    chat = _chat(client)

    joined = _patch_chat(client, chat["id"], project_id=project["id"], working_dirs=[shared, extra])

    assert joined["working_dirs"] == [shared, extra]
    assert client.get("/api/v1/projects").json()[0]["working_dirs"] == [shared, extra]


def test_a_refused_folder_list_leaves_the_chat_where_it_was(client, tmp_path):
    project = _project(client)
    chat = _chat(client)

    answer = client.patch(
        f"/api/v1/chats/{chat['id']}",
        json={"project_id": project["id"], "working_dirs": [str(tmp_path / "missing")]},
    )

    assert answer.status_code == 400
    assert client.get(f"/api/v1/chats/{chat['id']}").json()["project_id"] is None


def test_a_project_needs_a_name(client):
    assert client.post("/api/v1/projects", json={"name": "   "}).status_code == 400
    assert client.post("/api/v1/projects", json={"name": ""}).status_code == 422


def test_an_existing_database_moves_its_chats_along(tmp_path):
    """Version 37 knew neither projects nor the archive. Its chats come
    through in no project and not archived, and the projects table is
    there afterwards."""
    path = tmp_path / "old.db"
    db = Database(path)
    db.schema_einrichten()
    repos = repositories_erstellen(db)
    chat = repos.chats.erstellen(user_id="benutzer", title="Before projects")
    for statement in (
        "DROP INDEX IF EXISTS idx_chats_project",
        "ALTER TABLE chats DROP COLUMN project_id",
        "ALTER TABLE chats DROP COLUMN archived",
        "DROP TABLE projects",
        "DELETE FROM schema_version",
        "INSERT INTO schema_version (version, applied_at) VALUES (37, '2026-09-27T00:00:00')",
    ):
        db.verbindung.execute(statement)
    db.schliessen()

    db = Database(path)
    db.schema_einrichten()
    repos = repositories_erstellen(db)

    assert db.schema_version() == SCHEMA_VERSION
    moved = repos.chats.holen(chat.id)
    assert moved is not None
    assert moved.project_id is None
    assert moved.archived is False
    assert [c.id for c in repos.chats.auflisten(user_id="benutzer")] == [chat.id]
    assert repos.projects.list_for(user_id="benutzer") == []
    db.schliessen()
