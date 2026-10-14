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

from app import docfolder, dokumentablage, folder_names
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


async def test_a_picture_dropped_without_a_type_stands_in_the_folder_as_a_picture(client):
    """The page sends octet-stream where the browser knows no type; the wall
    shows a picture only for an `image/…` type, so the name has to decide."""
    chat = _chat(client, "Pictures")
    answer = client.post(
        f"/api/v1/agentendock?name=foto.jpg&chat={chat}",
        content=b"\xff\xd8\xff",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert answer.status_code == 201, answer.text
    rows = client.get("/api/v1/doc-folder", params={"chat": chat}).json()
    assert [(row["name"], row["type"]) for row in rows] == [("foto.jpg", "image/jpeg")]


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


async def test_a_hidden_folder_and_a_package_managers_are_not_listed(client):
    """A hidden folder and the folder a package manager fills are left out
    with everything in them, on any depth below the chat's folder."""
    chat = _chat(client, "Open")
    for name in (
        "report.md",
        "src/a.py",
        ".git/config",
        ".venv/lib/x.py",
        "src/.cache/y.bin",
        "node_modules/pkg/index.js",
        "src/node_modules/z.js",
    ):
        _written(client, chat, name, "x")

    assert set(_names(client, chat=chat)) == {"report.md", "src/a.py"}
    assert set(_names(client)) == {"report.md", "src/a.py"}


async def test_only_a_folder_by_its_whole_name_is_kept_out(client):
    """Silence probe: a folder whose name merely begins like the package
    manager's, one with a dot inside its name, and a file named like that
    folder all stand as before."""
    chat = _chat(client, "Open")
    names = {
        "node_modules_old/pkg.js",
        "my.folder/notes.txt",
        "site/node_modules.txt",
    }
    for name in names:
        _written(client, chat, name, "x")

    assert set(_names(client, chat=chat)) == names


async def test_the_folder_of_compiled_python_files_is_not_listed(client):
    """A script run in the chat's folder leaves its compiled form in a
    folder beside it. That folder is left out with everything in it, on any
    depth below the chat's folder, like a hidden one."""
    chat = _chat(client, "Open")
    for name in (
        "script.py",
        "__pycache__/script.cpython-312.pyc",
        "src/pkg/mod.py",
        "src/pkg/__pycache__/mod.cpython-312.pyc",
        "src/pkg/__pycache__/deeper/more.pyc",
    ):
        _written(client, chat, name, "x")

    assert set(_names(client, chat=chat)) == {"script.py", "src/pkg/mod.py"}
    assert set(_names(client)) == {"script.py", "src/pkg/mod.py"}


async def test_only_the_folder_of_compiled_files_by_its_whole_name_is_kept_out(client):
    """Silence probe: a folder merely named like a cache, one whose name
    only holds the interpreter's, and a file that carries that name — with
    an ending, or bare — all stand."""
    chat = _chat(client, "Open")
    names = {
        "cache/data.bin",
        "pycache/data.bin",
        "__pycache__old/mod.pyc",
        "my__pycache__/mod.pyc",
        "__pycache__.txt",
        "site/__pycache__",
    }
    for name in names:
        _written(client, chat, name, "x")

    assert set(_names(client, chat=chat)) == names


def test_what_a_file_manager_leaves_is_named_in_one_list():
    """The doc folder asks the list the program already keeps for these
    names, and keeps none of its own."""
    assert docfolder.is_viewer_file is folder_names.is_viewer_file
    assert folder_names.VIEWER_FILES == {".DS_Store", "Thumbs.db", "desktop.ini"}


async def test_hidden_files_and_what_a_file_manager_leaves_are_not_listed(client):
    """A file whose name begins with a dot, and the ones a file manager
    leaves in a folder it only showed, are left out — in the chat's folder
    and in a folder below it. Left out of the list is all they are: each
    lies where it lay, with what it held."""
    chat = _chat(client, "Open")
    hidden = [".env", ".gitignore", *sorted(folder_names.VIEWER_FILES)]
    kept = [
        _written(client, chat, place + name, f"kept as {place}{name}")
        for place in ("", "site/")
        for name in hidden
    ]
    _written(client, chat, "notes.txt", "x")
    _written(client, chat, "site/index.html", "x")

    assert set(_names(client, chat=chat)) == {"notes.txt", "site/index.html"}
    assert set(_names(client)) == {"notes.txt", "site/index.html"}

    folder = kept[0].parent
    assert len(kept) == 10
    for file in kept:
        assert file.read_text(encoding="utf-8") == f"kept as {file.relative_to(folder).as_posix()}"


async def test_what_a_file_manager_leaves_is_left_out_in_any_capitals(client):
    """The names are the same names in any spelling: one system writes
    ``Thumbs.db``, another finds ``thumbs.db`` or ``THUMBS.DB`` on its disk.
    Each lies where it lay, in a folder of its own so that a disk that does
    not tell capitals apart keeps all of them."""
    chat = _chat(client, "Open")
    left = [
        _written(client, chat, f"{place}/{name}", f"kept as {name}")
        for place, name in (
            ("a", "thumbs.db"),
            ("b", "THUMBS.DB"),
            ("c", "Desktop.ini"),
            ("d", "DESKTOP.INI"),
        )
    ]
    _written(client, chat, "notes.txt", "x")

    assert set(_names(client, chat=chat)) == {"notes.txt"}
    for file in left:
        assert file.read_text(encoding="utf-8") == f"kept as {file.name}"


async def test_only_a_file_hidden_by_its_whole_name_is_kept_out(client):
    """Silence probe: a name without the dot in front, one that only holds
    a file manager's name, and one that differs from it by a letter all
    stand, in the chat's folder and below it."""
    chat = _chat(client, "Open")
    names = {
        "notes.txt",
        "env",
        "my.env",
        "gitignore",
        "report.DS_Store.txt",
        "Thumbs.db.bak",
        "site/desktop.ini.txt",
        "site/Thumbs.dbx",
        "site/env",
        "Thumbs.db.txt",
        "site/desktop.ini.bak",
        "my-thumbs.db",
        "site/my-Desktop.ini",
    }
    for name in names:
        _written(client, chat, name, "x")

    assert set(_names(client, chat=chat)) == names


async def test_a_document_named_like_a_hidden_file_still_stands(client):
    """Silence probe: only a file nobody entered is asked for its name. An
    upload, a drop and a delivery have their rows and stand, dot or not —
    and none of them comes a second time, or goes, as a loose file."""
    chat = _chat(client, "Open")
    _upload(client, chat, ".plan.txt", "plan")
    _drop(client, ".kept.txt", "kept", chat)
    await _deliver(client, chat, ".report.md", "# Report")
    _written(client, chat, ".loose.txt", "loose")

    rows = client.get("/api/v1/doc-folder", params={"chat": chat}).json()

    assert {row["name"]: row["source"] for row in rows} == {
        ".kept.txt": "document",
        ".plan.txt": "document",
        ".report.md": "document",
    }


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


@pytest.mark.platforms("posix", reason="a symlink needs a privilege on Windows")
async def test_a_link_into_a_folder_that_is_left_out_is_not_listed(client):
    """A link is listed by where it leads: one lying in a folder that is
    shown and leading to a file in a hidden folder is left out like that
    file. Silence probe: a link to a file in a folder that is shown stands."""
    chat = _chat(client, "Open")
    folder = _written(client, chat, "site/index.html", "<p>page</p>").parent.parent
    kept = _written(client, chat, ".git/config", "[core]")
    deep = _written(client, chat, "site/node_modules/pkg/index.js", "x")
    (folder / "config.txt").symlink_to(kept)
    (folder / "site" / "pkg.js").symlink_to(deep)
    (folder / "page.html").symlink_to(folder / "site" / "index.html")

    assert set(_names(client, chat=chat)) == {"site/index.html", "page.html"}


@pytest.mark.platforms("posix", reason="a symlink needs a privilege on Windows")
async def test_a_link_is_listed_by_its_own_name_too(client):
    """A link stands in the list under its own name, so a name that is left
    out is left out for a link as for a file: one beginning with a dot and
    one a file manager leaves, in any capitals. Whatever it leads to stays
    where it is listed. Silence probe: a link to the same file under a name
    that is shown stands, and so does a link whose name only holds one."""
    chat = _chat(client, "Open")
    folder = _written(client, chat, "site/index.html", "<p>page</p>").parent.parent
    target = folder / "site" / "index.html"
    for name in (".page.html", "site/.hidden.html", "Thumbs.db", "site/DESKTOP.INI"):
        (folder / name).symlink_to(target)
    for name in ("page.html", "site/Thumbs.db.txt", "my.page.html"):
        (folder / name).symlink_to(target)

    assert set(_names(client, chat=chat)) == {
        "site/index.html",
        "page.html",
        "site/Thumbs.db.txt",
        "my.page.html",
    }


@pytest.mark.platforms("posix", reason="a symlink needs a privilege on Windows")
async def test_a_link_to_what_is_not_listed_is_not_listed(client):
    """A link is listed by where it leads: one leading into the folder of
    compiled files, to a hidden file or to one a file manager left behind
    is left out like the file it leads to. Silence probe: a link to a file
    that is listed stands."""
    chat = _chat(client, "Open")
    folder = _written(client, chat, "notes.txt", "in").parent
    compiled = _written(client, chat, "src/__pycache__/mod.cpython-312.pyc", "x")
    settings = _written(client, chat, ".env", "KEY=1")
    thumbs = _written(client, chat, "site/Thumbs.db", "x")
    (folder / "compiled.pyc").symlink_to(compiled)
    (folder / "settings.txt").symlink_to(settings)
    (folder / "site" / "thumbs.txt").symlink_to(thumbs)
    (folder / "again.txt").symlink_to(folder / "notes.txt")

    assert set(_names(client, chat=chat)) == {"notes.txt", "again.txt"}


def _below(folder):
    return {name for _, name in docfolder._files_below(folder)}


def test_where_the_chat_folder_itself_lies_hides_nothing(tmp_path):
    """Silence probe: only the names below the chat's folder are asked. A
    data folder inside a hidden folder is where some systems keep it."""
    folder = tmp_path / ".local" / "node_modules" / "chat"
    (folder / "site").mkdir(parents=True)
    (folder / "notes.txt").write_text("x", encoding="utf-8")
    (folder / "site" / "index.html").write_text("x", encoding="utf-8")

    assert _below(folder) == {"notes.txt", "site/index.html"}


@pytest.mark.platforms("posix", reason="a symlink needs a privilege on Windows")
def test_a_link_is_judged_below_the_chat_folder_only(tmp_path):
    """Silence probe: a link is judged by where it leads below the chat's
    folder, not by the hidden folder the chat's folder lies in."""
    folder = tmp_path / ".local" / "node_modules" / "chat"
    folder.mkdir(parents=True)
    (folder / "notes.txt").write_text("x", encoding="utf-8")
    (folder / "again.txt").symlink_to(folder / "notes.txt")

    assert _below(folder) == {"notes.txt", "again.txt"}


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


# --- The place a chat's folder row names ---------------------------------------


def test_a_chats_folder_row_names_the_chats_own_folder(client):
    """The row of an open chat shows where its files lie and opens that
    place; the route answers the path without making the folder."""
    chat_id = _chat(client, "Place")
    answer = client.get("/api/v1/doc-folder/place", params={"chat": chat_id})
    assert answer.status_code == 200, answer.text
    config = client.app.state.config
    expected = dokumentablage.chatordner(docfolder.Path(config.datenverzeichnis), chat_id)
    assert answer.json() == {"path": str(expected)}
    assert not expected.exists()


def test_silence_a_name_that_is_no_chat_id_has_no_place(client):
    """The id travels in from a URL: what could climb out of the data
    folder is refused, as the files route refuses it."""
    for name in ("..", "a/b", "x y"):
        answer = client.get("/api/v1/doc-folder/place", params={"chat": name})
        assert answer.status_code == 404, name


# --- One file on the disk, one tile ---------------------------------------------


def _tiles(client, name, **query):
    rows = client.get("/api/v1/doc-folder", params=query).json()
    return [row for row in rows if row["name"] == name]


def test_the_same_file_put_into_a_chat_twice_stands_as_one_tile(client):
    """The defect: a file put into the same chat a second time has a second
    row and no second file, and the folder showed it twice. One file on the
    disk is one tile; it is the newest row that stands."""
    chat_id = _chat(client, "Twice")
    first = _upload(client, chat_id, "llm-wiki.md", "# wiki\n")
    second = _upload(client, chat_id, "llm-wiki.md", "# wiki\n")
    assert first != second

    tiles = _tiles(client, "llm-wiki.md")
    assert len(tiles) == 1
    assert tiles[0]["source"] == "document"
    assert len(_tiles(client, "llm-wiki.md", chat=chat_id)) == 1


def test_silence_files_of_one_name_in_two_chats_stay_two_tiles(client):
    one = _chat(client, "One")
    two = _chat(client, "Two")
    _upload(client, one, "plan.md", "the plan")
    _upload(client, two, "plan.md", "the plan")

    assert len(_tiles(client, "plan.md")) == 2
    assert len(_tiles(client, "plan.md", chat=one)) == 1


def test_silence_the_dock_copy_and_the_chat_copy_of_a_file_stay_two_tiles(client):
    """Two copies on the disk are two files, whatever their name says."""
    chat_id = _chat(client, "Dock")
    _upload(client, chat_id, "notes.md", "same words")
    _drop(client, "notes.md", "same words")

    tiles = _tiles(client, "notes.md")
    assert sorted(row["source"] for row in tiles) == ["agent", "document"]
