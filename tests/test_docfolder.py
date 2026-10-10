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

import pytest

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


# --- What lies in a chat's own folder without a row --------------------------
#
# A write tool or a command puts a file into the chat's folder, or into a
# folder below it, and enters it nowhere. The folder is the third place the
# list reads: every file below it that no document names, fetched at an
# address of its own and named by its path in the folder.


def _written(client, chat_id, name, text):
    """A file the way a write tool leaves it: below the chat's own folder,
    with no document row."""
    folder = dokumentablage.chatordner(client.app.state.config.datenverzeichnis, chat_id)
    file = folder / name
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")
    return file


async def test_a_file_written_into_the_chat_folder_stands_in_the_list(client):
    web = _project(client, "Website")
    chat = _chat(client, "Open", web)
    _written(client, chat, "notes.txt", "written by a tool")

    row = _names(client, chat=chat)["notes.txt"]

    assert row["source"] == "chat_file"
    assert row["origin"] == "user"
    assert row["agent"] == ""
    assert row["chat_id"] == chat
    assert row["project_id"] == web
    assert row["type"] == "text/plain"
    assert row["size"] == len("written by a tool")
    assert row["created"]
    assert row["path"] == f"/chat-files/{chat}/notes.txt"
    answer = client.get(f"/api/v1{row['path']}")
    assert answer.status_code == 200
    assert answer.content == b"written by a tool"


async def test_a_file_in_a_folder_below_stands_with_its_path(client):
    """Everything below the chat's folder is read, and a file there is named
    by its path in the folder — two files of one name in two folders are two
    rows, each fetched from its own address."""
    chat = _chat(client, "Open")
    _written(client, chat, "site/index.html", "<p>page</p>")
    _written(client, chat, "site/css/style.css", "p {}")
    _written(client, chat, "draft/index.html", "<p>draft</p>")

    rows = _names(client, chat=chat)

    assert set(rows) == {"site/index.html", "site/css/style.css", "draft/index.html"}
    assert rows["site/css/style.css"]["path"] == f"/chat-files/{chat}/site/css/style.css"
    assert rows["site/css/style.css"]["type"] == "text/css"
    assert client.get(f"/api/v1{rows['site/index.html']['path']}").content == b"<p>page</p>"
    assert client.get(f"/api/v1{rows['draft/index.html']['path']}").content == b"<p>draft</p>"
    assert len({row["id"] for row in rows.values()}) == 3


async def test_a_page_a_tool_wrote_is_never_served_as_a_page(client):
    """What a model wrote must not run under this service's address: like a
    document's file, everything but a PDF is handed out to be saved."""
    chat = _chat(client, "Open")
    _written(client, chat, "page.html", "<script>alert(1)</script>")
    _written(client, chat, "paper.pdf", "%PDF-1.4")

    rows = _names(client, chat=chat)
    page = client.get(f"/api/v1{rows['page.html']['path']}")
    paper = client.get(f"/api/v1{rows['paper.pdf']['path']}")

    assert page.headers["content-disposition"].startswith("attachment")
    assert paper.headers["content-disposition"].startswith("inline")


async def test_a_name_with_a_space_or_an_umlaut_is_fetched_from_its_path(client):
    chat = _chat(client, "Open")
    _written(client, chat, "Über sicht/Plan 1.md", "# x")

    row = _names(client, chat=chat)["Über sicht/Plan 1.md"]

    assert " " not in row["path"]
    assert client.get(f"/api/v1{row['path']}").content == b"# x"


async def test_a_path_that_leaves_the_chat_folder_is_refused(client):
    """The chat and a path below its folder are all the address may say.
    A path that climbs, an id that is no id, a folder and a file that is
    not there all get the same 404, and nothing outside is read."""
    chat = _chat(client, "Open")
    folder = _written(client, chat, "notes.txt", "in").parent
    (folder.parent / "secret.txt").write_text("out", encoding="utf-8")
    (folder / "sub").mkdir()

    for name in (
        "%2E%2E", "%2E%2E/secret.txt", "..%2Fsecret.txt", "sub/%2E%2E/%2E%2E/secret.txt",
        "%2Fetc%2Fhosts", "sub", "missing.txt", "sub/missing.txt",
    ):
        answer = client.get(f"/api/v1/chat-files/{chat}/{name}")
        assert answer.status_code == 404, name
        assert b"out" not in answer.content, name
    assert client.get("/api/v1/chat-files/%2E%2E/secret.txt").status_code == 404
    assert client.get("/api/v1/chat-files/missing/notes.txt").status_code == 404
    # And the list shows what the address hands out, no more: not the empty
    # folder below.
    assert set(_names(client, chat=chat)) == {"notes.txt"}


@pytest.mark.platforms("posix", reason="a symlink needs a privilege on Windows")
async def test_a_link_leading_out_of_the_chat_folder_is_refused(client):
    """A command can leave a link in the chat's folder. One leading out — to
    a file, or to a folder — is neither handed out nor listed, and nothing
    behind a linked folder is. Silence probe: a link to a file inside the
    folder is a second name for that file, and is as good as the file."""
    chat = _chat(client, "Open")
    folder = _written(client, chat, "notes.txt", "in").parent
    secret = folder.parent / "secret.txt"
    secret.write_text("out", encoding="utf-8")
    outside = folder.parent / "outside"
    outside.mkdir()
    (outside / "deep.txt").write_text("out", encoding="utf-8")
    (folder / "link.txt").symlink_to(secret)
    (folder / "door").symlink_to(outside, target_is_directory=True)
    (folder / "again.txt").symlink_to(folder / "notes.txt")

    for name in ("link.txt", "door/deep.txt", "door"):
        answer = client.get(f"/api/v1/chat-files/{chat}/{name}")
        assert answer.status_code == 404, name
        assert b"out" not in answer.content, name

    assert set(_names(client, chat=chat)) == {"notes.txt", "again.txt"}
    assert client.get(f"/api/v1/chat-files/{chat}/again.txt").content == b"in"


async def test_a_file_with_a_document_row_stands_once(client):
    """Silence probe: an upload, a drop and a delivery lie in the same
    folder and each has its row already — none of them appears a second
    time as a loose file."""
    chat = _chat(client, "Open")
    _upload(client, chat, "plan.txt", "plan")
    _drop(client, "kept.txt", "kept", chat)
    await _deliver(client, chat, "report.md", "# Report")
    _written(client, chat, "notes.txt", "loose")

    rows = client.get("/api/v1/doc-folder", params={"chat": chat}).json()

    assert {row["name"]: row["source"] for row in rows} == {
        "kept.txt": "document",
        "notes.txt": "chat_file",
        "plan.txt": "document",
        "report.md": "document",
    }
    assert len(rows) == 4


async def test_a_chat_sees_only_the_loose_files_of_its_own_folder(client):
    """Silence probe: two chats each wrote a file of the same name."""
    chat_a = _chat(client, "A")
    chat_b = _chat(client, "B")
    _written(client, chat_a, "notes.txt", "a")
    _written(client, chat_b, "notes.txt", "b")
    _written(client, chat_b, "more.txt", "b")

    in_a = _names(client, chat=chat_a)
    in_b = _names(client, chat=chat_b)

    assert set(in_a) == {"notes.txt"}
    assert set(in_b) == {"notes.txt", "more.txt"}
    assert client.get(f"/api/v1{in_a['notes.txt']['path']}").content == b"a"
    assert client.get(f"/api/v1{in_b['notes.txt']['path']}").content == b"b"


async def test_a_chat_without_a_folder_has_no_loose_files(client):
    """Silence probe: a folder that does not exist is an empty list, for a
    chat that never kept a file and for a chat that does not exist."""
    chat = _chat(client, "Empty")

    assert client.get("/api/v1/doc-folder", params={"chat": chat}).json() == []
    assert client.get("/api/v1/doc-folder", params={"chat": "missing"}).json() == []
    assert client.get("/api/v1/doc-folder").json() == []


async def test_the_start_page_shows_the_loose_files_of_every_chat(client):
    """With no chat open: every chat's loose files, like every chat's
    documents, narrowed by project and by origin as the rest is. A folder
    whose chat is gone is a leftover and shows nothing."""
    web = _project(client, "Website")
    chat_a = _chat(client, "A", web)
    chat_b = _chat(client, "B")
    _written(client, chat_a, "a.txt", "a")
    _written(client, chat_b, "b.txt", "b")
    _upload(client, chat_b, "boxes.txt", "boxes")
    data = client.app.state.config.datenverzeichnis
    leftover = data / dokumentablage.CHATDATEIEN / "0000deadbeef"
    leftover.mkdir(parents=True)
    (leftover / "ghost.txt").write_text("x", encoding="utf-8")

    assert set(_names(client)) == {"a.txt", "b.txt", "boxes.txt"}
    assert set(_names(client, project=web)) == {"a.txt"}
    assert set(_names(client, origin="user")) == {"a.txt", "b.txt", "boxes.txt"}
    assert set(_names(client, origin="agent")) == set()
    assert _names(client)["a.txt"]["chat_id"] == chat_a
    assert _names(client)["b.txt"]["project_id"] is None


async def test_a_loose_file_cannot_be_removed_at_its_address(client):
    """Silence probe: a loose file carries no cross, like a chat's document,
    and its address only ever hands the file out."""
    chat = _chat(client, "Open")
    file = _written(client, chat, "notes.txt", "loose")
    path = _names(client, chat=chat)["notes.txt"]["path"]

    assert client.delete(f"/api/v1{path}").status_code == 405

    assert file.read_text(encoding="utf-8") == "loose"


async def test_a_loose_file_is_fetched_with_the_key_in_the_address(client):
    """A tile's picture and the reader's link cannot send a header, so the
    address takes the key as a parameter — also for a file in a folder
    below. Without any key it stays shut."""
    chat = _chat(client, "Open")
    _written(client, chat, "site/notes.txt", "loose")
    path = _names(client, chat=chat)["site/notes.txt"]["path"]
    key = client.headers.pop("X-Sitzungsschluessel")
    try:
        assert client.get(f"/api/v1{path}?schluessel={key}").content == b"loose"
        assert client.get(f"/api/v1{path}").status_code == 401
        assert client.get(f"/api/v1{path}?schluessel=wrong").status_code == 401
    finally:
        client.headers["X-Sitzungsschluessel"] = key
