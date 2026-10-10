"""The doc folder: every file in one list, with its origin, narrowed by
origin and by project (app/docfolder.py, GET /doc-folder).

Two places feed it — the one dock and the documents of the chats. A file
dropped on the start page lands on the dock; one dropped in an open chat,
and one a job started from a chat delivers, land in that chat's own folder
and go with it.
"""

from __future__ import annotations

import functools
import json

from app import dokumentablage
from app.agenten import Agent
from app.agentendock import DATEI, dock_fuer
from app.tools import agentendock as delivery
from app.tools.registry import WerkzeugRegistry

AGENT = Agent(name="researcher", prompt="Prompt.")


def _project(client, name):
    answer = client.post("/api/v1/projects", json={"name": name})
    assert answer.status_code == 201, answer.text
    return answer.json()["id"]


def _chat(client, title, project_id=None):
    chat = client.post("/api/v1/chats", json={"title": title}).json()
    if project_id:
        moved = client.patch(f"/api/v1/chats/{chat['id']}", json={"project_id": project_id})
        assert moved.status_code == 200, moved.text
    return chat["id"]


def _upload(client, chat_id, name, text):
    answer = client.post(
        f"/api/v1/documents?chat_id={chat_id}&name={name}", content=text.encode()
    )
    assert answer.status_code == 201, answer.text
    return answer.json()["dokument"]["id"]


async def _deliver(client, chat_id, name, text, cronjob_id=None):
    """A job delivers one file, the way a run does: through the registry,
    the job's own id handed in as `chat_id`. `chat_id` is the chat the job
    was started from, or None for a job without one."""
    repos = client.app.state.repositories
    config = client.app.state.config
    job = repos.auftraege.erstellen(
        user_id="lokal",
        agent=AGENT.name,
        auftrag="deliver",
        chat_id=chat_id,
        cronjob_id=cronjob_id,
    )
    registry = WerkzeugRegistry(
        [],
        agentendock=dock_fuer(config),
        chat_delivery=functools.partial(
            dokumentablage.deliver_to_chat, repos, config.datenverzeichnis
        ),
    )
    await registry.ausfuehren(
        delivery.WERKZEUG_NAME,
        {"name": name, "content": text},
        herkunft="agent",
        agent=AGENT,
        chat_id=job.id,
    )
    return job.id


def _drop(client, name, text, chat=""):
    query = f"name={name}" + (f"&chat={chat}" if chat else "")
    answer = client.post(
        f"/api/v1/agentendock?{query}",
        content=text.encode(),
        headers={"Content-Type": "text/plain"},
    )
    assert answer.status_code == 201, answer.text
    return answer.json()["id"]


async def _three_places(client):
    web = _project(client, "Website")
    other = _project(client, "Moving")
    chat_web = _chat(client, "Web", web)
    chat_other = _chat(client, "Other", other)
    _upload(client, chat_web, "plan.txt", "the plan")
    _upload(client, chat_other, "boxes.txt", "the boxes")
    _drop(client, "clip.txt", "kept")
    await _deliver(client, chat_web, "report.md", "# Report")
    await _deliver(client, chat_other, "list.md", "# List")
    return web, other


def _names(client, **query):
    answer = client.get("/api/v1/doc-folder", params=query)
    assert answer.status_code == 200, answer.text
    return {row["name"]: row for row in answer.json()}


async def test_uploaded_and_delivered_files_stand_in_one_list(client):
    web, _ = await _three_places(client)

    rows = _names(client)

    assert set(rows) == {"plan.txt", "boxes.txt", "clip.txt", "report.md", "list.md"}
    assert rows["report.md"]["origin"] == "agent"
    assert rows["report.md"]["agent"] == "researcher"
    assert rows["report.md"]["source"] == "document"
    assert rows["report.md"]["project_id"] == web
    assert rows["plan.txt"]["origin"] == "user"
    assert rows["plan.txt"]["source"] == "document"
    assert rows["plan.txt"]["project_id"] == web
    assert rows["clip.txt"]["origin"] == "user"
    assert rows["clip.txt"]["source"] == "agent"
    assert rows["clip.txt"]["project_id"] is None


async def test_the_origin_filter_narrows_the_list(client):
    await _three_places(client)

    assert set(_names(client, origin="agent")) == {"report.md", "list.md"}
    assert set(_names(client, origin="user")) == {"plan.txt", "boxes.txt", "clip.txt"}
    assert set(_names(client, origin="cronjob")) == set()
    assert client.get("/api/v1/doc-folder", params={"origin": "nobody"}).status_code == 422


async def test_the_project_filter_shows_only_that_projects_files(client):
    """Silence probe: the other project's upload and delivery, and the dock
    file that belongs to no project, stay out."""
    web, other = await _three_places(client)

    assert set(_names(client, project=web)) == {"plan.txt", "report.md"}
    assert set(_names(client, project=other)) == {"boxes.txt", "list.md"}
    assert set(_names(client, project=web, origin="agent")) == {"report.md"}


async def test_every_file_is_fetched_from_its_path(client):
    await _three_places(client)

    rows = _names(client)
    assert client.get(f"/api/v1{rows['plan.txt']['path']}").content == b"the plan"
    assert client.get(f"/api/v1{rows['clip.txt']['path']}").content == b"kept"
    assert client.get(f"/api/v1{rows['report.md']['path']}").content == b"# Report"
    assert client.get("/api/v1/documents/missing/file").status_code == 404


async def test_a_delivery_remembers_its_agent_and_job(client):
    """A job started from a chat delivers into that chat's own folder, as a
    document of the chat with its agent and its job — nothing lands on the
    dock."""
    chat = _chat(client, "Plain")
    job = await _deliver(client, chat, "old.md", "x")

    documents = client.app.state.repositories.documents.auflisten(chat_id=chat)
    assert [(d.filename, d.agent, d.job) for d in documents] == [("old.md", "researcher", job)]
    folder = dokumentablage.chatordner(client.app.state.config.datenverzeichnis, chat)
    assert documents[0].pfad == str((folder / "old.md").resolve())
    assert dock_fuer(client.app.state.config).alle() == []
    assert _names(client)["old.md"]["chat_id"] == chat
    assert _names(client)["old.md"]["project_id"] is None


async def test_a_job_without_a_chat_delivers_onto_the_dock(client):
    job = await _deliver(client, None, "nightly.md", "# Night")

    entry = next(e for e in dock_fuer(client.app.state.config).alle() if e["name"] == "nightly.md")
    assert entry["job"] == job
    assert entry["agent"] == "researcher"
    row = _names(client)["nightly.md"]
    assert row["source"] == "agent"
    assert row["chat_id"] is None


async def test_deleting_a_chat_takes_its_deliveries_and_leaves_the_dock(client):
    """A chat deleted for good takes what its jobs delivered, like its
    uploads; silence probe: the dock file stays where it is."""
    chat = _chat(client, "Gone")
    await _deliver(client, chat, "report.md", "# Report")
    _drop(client, "kept-home.txt", "home")
    folder = dokumentablage.chatordner(client.app.state.config.datenverzeichnis, chat)
    assert (folder / "report.md").is_file()

    assert client.delete(f"/api/v1/chats/{chat}").status_code in (200, 204)

    assert not folder.exists()
    assert set(_names(client)) == {"kept-home.txt"}


async def test_origin_is_read_off_the_entry(client):
    """Three entries, three origins: no agent is the person, an agent whose
    job a cron entry started is a cron job, any other agent is an agent.
    The same rule on the dock and in a chat."""
    chat = _chat(client, "Mixed")
    _drop(client, "mine.txt", "mine", chat)
    await _deliver(client, chat, "by-hand.md", "# Hand")
    await _deliver(client, chat, "by-cron.md", "# Cron", cronjob_id="cron-1")
    await _deliver(client, None, "dock-cron.md", "# Cron", cronjob_id="cron-2")
    _drop(client, "dock-mine.txt", "mine")

    rows = _names(client)
    assert {name: row["origin"] for name, row in rows.items()} == {
        "mine.txt": "user",
        "by-hand.md": "agent",
        "by-cron.md": "cronjob",
        "dock-cron.md": "cronjob",
        "dock-mine.txt": "user",
    }
    assert set(_names(client, origin="cronjob")) == {"by-cron.md", "dock-cron.md"}
    assert set(_names(client, origin="cronjob", chat=chat)) == {"by-cron.md"}


async def test_a_chat_sees_only_its_own_files(client):
    """The same file uploaded into two chats stands once in each chat's
    folder, and nothing of the other chat stands beside it: its upload,
    its job's delivery and what was dropped in it."""
    chat_a = _chat(client, "A")
    chat_b = _chat(client, "B")
    _upload(client, chat_a, "llm-wiki.md", "same")
    _upload(client, chat_b, "llm-wiki.md", "same")
    await _deliver(client, chat_a, "report.md", "# Report")
    _drop(client, "kept-a.txt", "a", chat_a)
    _drop(client, "kept-home.txt", "home")

    in_a = client.get("/api/v1/doc-folder", params={"chat": chat_a}).json()
    in_b = client.get("/api/v1/doc-folder", params={"chat": chat_b}).json()

    assert sorted(row["name"] for row in in_a) == ["kept-a.txt", "llm-wiki.md", "report.md"]
    assert [row["name"] for row in in_b] == ["llm-wiki.md"]
    assert {row["chat_id"] for row in in_a} == {chat_a}
    assert {row["chat_id"] for row in in_b} == {chat_b}


async def test_a_file_dropped_in_a_chat_lies_in_its_folder(client):
    chat = _chat(client, "Open")
    _drop(client, "kept.txt", "kept", chat)

    folder = dokumentablage.chatordner(client.app.state.config.datenverzeichnis, chat)
    assert (folder / "kept.txt").read_bytes() == b"kept"
    assert dock_fuer(client.app.state.config).alle() == []
    row = _names(client)["kept.txt"]
    assert row["source"] == "document"
    assert row["origin"] == "user"


async def test_a_drop_into_a_chat_that_does_not_exist_is_refused(client):
    answer = client.post(
        "/api/v1/agentendock?name=x.txt&chat=missing", content=b"x"
    )
    assert answer.status_code == 404
    assert dock_fuer(client.app.state.config).alle() == []


async def test_the_start_page_sees_every_file_and_narrows_by_project(client):
    """Silence probe: with no chat, every file — both chats' and the one
    dropped with no chat open — and the project filter narrows as before;
    a file dropped in a chat of a project belongs to that project."""
    web = _project(client, "Website")
    chat_a = _chat(client, "A", web)
    chat_b = _chat(client, "B")
    _upload(client, chat_a, "plan.txt", "plan")
    _upload(client, chat_b, "boxes.txt", "boxes")
    _drop(client, "kept-a.txt", "a", chat_a)
    _drop(client, "kept-home.txt", "home")

    assert set(_names(client)) == {"plan.txt", "boxes.txt", "kept-a.txt", "kept-home.txt"}
    assert set(_names(client, project=web)) == {"plan.txt", "kept-a.txt"}
    assert _names(client)["kept-home.txt"]["chat_id"] is None
    assert set(_names(client, chat=chat_a, origin="user")) == {"plan.txt", "kept-a.txt"}


async def test_a_file_dropped_without_a_chat_stands_in_no_chat(client):
    chat_a = _chat(client, "A")
    _drop(client, "kept-home.txt", "home")

    assert client.get("/api/v1/doc-folder", params={"chat": chat_a}).json() == []


def test_the_old_dock_route_is_gone(client):
    """Silence probe: the person's own dock had its own routes; there is
    one dock now, and nothing answers there any more."""
    assert client.get("/api/v1/notizen/dock/alle").status_code == 404
    assert client.post("/api/v1/notizen/dock?name=x.txt", content=b"x").status_code in (404, 405)


def test_the_old_dock_is_carried_onto_the_one_dock(client):
    """What the person kept on the old dock stands on the one dock after
    the first look at it, under its own id and name and with no agent —
    and the old folder and its list are gone."""
    data = client.app.state.config.datenverzeichnis
    old = data / "dock"
    old.mkdir()
    (old / "abc.txt").write_bytes(b"kept long ago")
    (data / "dock.json").write_text(
        json.dumps(
            [
                {
                    "id": "abc",
                    "name": "Notes.txt",
                    "datei": "abc.txt",
                    "typ": "text/plain",
                    "groesse": 13,
                    "abgelegt": "2026-01-01T00:00:00+00:00",
                    "chat": "some-chat",
                },
                # Its file is gone already: nothing to carry, nothing named.
                {"id": "lost", "name": "Lost.txt", "datei": "lost.txt"},
            ]
        ),
        encoding="utf-8",
    )

    dock = dock_fuer(client.app.state.config)

    assert [(e["id"], e["name"], e["agent"]) for e in dock.alle()] == [("abc", "Notes.txt", "")]
    assert dock.holen("abc")[1].read_bytes() == b"kept long ago"
    assert not old.exists()
    assert not (data / "dock.json").exists()
    # Once only: a second look neither duplicates nor complains.
    assert [e["id"] for e in dock_fuer(client.app.state.config).alle()] == ["abc"]
    row = _names(client)["Notes.txt"]
    assert row["origin"] == "user"
    assert row["chat_id"] is None


def test_an_unreadable_old_dock_is_left_alone(client):
    """The old list is the only thing that names those files: unreadable,
    it stays where it is, with its folder, and nothing lands on the dock."""
    data = client.app.state.config.datenverzeichnis
    (data / "dock").mkdir()
    (data / "dock" / "abc.txt").write_bytes(b"x")
    (data / "dock.json").write_text("{broken", encoding="utf-8")

    dock = dock_fuer(client.app.state.config)

    assert dock.alle() == []
    assert (data / "dock.json").exists()
    assert (data / "dock" / "abc.txt").exists()
    assert not (dock.ordner / DATEI).exists()


async def test_a_drop_whose_name_cannot_be_a_file_is_refused(client):
    """A name that climbs out of the chat's folder is refused, not a crash."""
    chat = _chat(client, "Odd")
    answer = client.post(f"/api/v1/agentendock?name=..&chat={chat}", content=b"x")
    assert answer.status_code == 422
    assert client.app.state.repositories.documents.auflisten(chat_id=chat) == []
