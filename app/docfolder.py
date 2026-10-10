"""The doc folder: every file the person has, in one list, whoever brought it.

Three places hold files, and each keeps doing its own job:

* the dock (``app/agentendock.py``) — files without a chat: dropped on the
  start page, or delivered by a job that has no chat;
* the documents of a chat (the ``documents`` table) — files uploaded into a
  conversation, dropped while it was open, or delivered by a job started
  from it; they lie in that chat's own folder and go with the chat;
* the chat's own folder itself (``app/dokumentablage.py``) — whatever lies
  in it, or in a folder below it, that no document names: a file a write
  tool or a command put there, in the chat or in a job started from it.
  Nobody entered it anywhere, so the folder is asked, the way the dock asks
  its own folder for what its record does not know. Such a file is named by
  its path below the chat's folder.

Nothing is copied or moved to make the folder. It is a READ over those
places: one row per file with where it came from, and the address the file
is fetched from. The places stay the truth; the folder is how they are seen
together.

Origin is who brought the file, read off the entry itself: no agent named —
the person; an agent and a job a cron entry started — a cron job; any other
agent — an agent. The same rule for the dock, for a chat's documents and for
a file lying loose in a chat's folder, which names nobody.
The chat a file belongs to is a chat document's own chat, a loose file's
folder's chat and a dock file's job's chat; the project is that chat's
project.

A chat sees its own files and no other chat's; the start page, with no chat
open, sees every file.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from app import dokumentablage
from app.agentendock import dock_fuer, type_from_name

if TYPE_CHECKING:
    from app.config import Config
    from app.db import Repositories

ORIGIN_AGENT = "agent"
ORIGIN_USER = "user"
ORIGIN_CRONJOB = "cronjob"
ORIGINS = (ORIGIN_AGENT, ORIGIN_USER, ORIGIN_CRONJOB)
# The one pattern the route checks an origin against, built from the list.
ORIGIN_PATTERN = "^(" + "|".join(ORIGINS) + ")$"

SOURCE_AGENT = "agent"
SOURCE_DOCUMENT = "document"
SOURCE_CHAT_FILE = "chat_file"


def origin_of(agent: str | None, job: str | None, cron_jobs: set[str]) -> str:
    """Who brought a file, from what its entry names."""
    if not agent:
        return ORIGIN_USER
    if job and job in cron_jobs:
        return ORIGIN_CRONJOB
    return ORIGIN_AGENT


def entries(
    config: "Config",
    repositories: "Repositories",
    *,
    origin: str | None = None,
    project: str | None = None,
    chat: str | None = None,
) -> list[dict[str, Any]]:
    """Every file, newest first, narrowed by origin, by project and by chat.

    ``path`` is the file's address under the API, or empty where there is no
    file to fetch (a chat document from before its file was kept).
    """
    rows: list[dict[str, Any]] = []
    cron_jobs = repositories.auftraege.cron_job_ids()

    # A job that has been deleted, or that no chat started, ties its file to
    # no chat and no project.
    chats = repositories.auftraege.chats_and_projects()
    for item in dock_fuer(config).alle():
        job = str(item.get("job") or "")
        chat_id, project_id = chats.get(job, (None, None))
        rows.append(
            {
                "id": str(item.get("id") or ""),
                "source": SOURCE_AGENT,
                "origin": origin_of(str(item.get("agent") or ""), job, cron_jobs),
                "name": str(item.get("name") or ""),
                "type": str(item.get("typ") or ""),
                "size": int(item.get("groesse") or 0),
                "created": str(item.get("abgelegt") or ""),
                "agent": str(item.get("agent") or ""),
                "chat_id": chat_id,
                "project_id": project_id,
                "path": f"/agentendock/{item.get('id')}",
            }
        )

    documents = repositories.documents.for_folder()
    for document in documents:
        rows.append(
            {
                "id": document["id"],
                "source": SOURCE_DOCUMENT,
                "origin": origin_of(document["agent"], document["job"], cron_jobs),
                "name": document["filename"],
                "type": document["mime_type"] or "",
                "size": int(document["size_bytes"] or 0),
                "created": document["created_at"],
                "agent": document["agent"] or "",
                "chat_id": document["chat_id"],
                "project_id": document["project_id"],
                "path": f"/documents/{document['id']}/file" if document["pfad"] else "",
            }
        )

    # What lies below a chat's folder without a row of its own — exactly
    # the files the address under ``path`` hands out, by the same test.
    named = _document_files(
        [document for document in documents if not chat or document["chat_id"] == chat]
    )
    for chat_id, project_id, folder in _chat_folders(config, repositories, chat):
        for file, name in _files_below(folder):
            try:
                state = file.stat()
            except OSError:
                # Gone since the listing. The next one will not see it either.
                continue
            if (state.st_dev, state.st_ino) in named:
                continue
            rows.append(
                {
                    # Chat and path identify the file — and stay the same on
                    # the next listing, which a tile's key has to.
                    "id": f"{chat_id}/{name}",
                    "source": SOURCE_CHAT_FILE,
                    "origin": origin_of("", None, cron_jobs),
                    "name": name,
                    "type": type_from_name(file.name),
                    "size": state.st_size,
                    "created": datetime.fromtimestamp(
                        state.st_mtime, tz=timezone.utc
                    ).isoformat(),
                    "agent": "",
                    "chat_id": chat_id,
                    "project_id": project_id,
                    "path": f"/chat-files/{chat_id}/{quote(name, safe='/')}",
                }
            )

    if origin:
        rows = [row for row in rows if row["origin"] == origin]
    if project:
        rows = [row for row in rows if row["project_id"] == project]
    if chat:
        rows = [row for row in rows if row["chat_id"] == chat]
    rows.sort(key=lambda row: row["created"], reverse=True)
    return rows


def _real(path: Path | str) -> Path | None:
    """Where a path really leads; nothing for a path that cannot be
    resolved — a link pointing at itself, a name no file system takes."""
    try:
        return Path(path).resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _document_files(documents: list[dict[str, Any]]) -> set[tuple[int, int]]:
    """The files the document rows name. A file among them already has its
    row and its address; listing it from the folder as well would show it
    twice.

    Each as the file itself, not as a spelling of its path: a row's path and
    the folder's own listing can write one name in two ways — another letter
    case, an accent stored composed here and decomposed there — and two
    spellings of one file must not make two tiles.
    """
    named: set[tuple[int, int]] = set()
    for document in documents:
        if not document["pfad"]:
            continue
        try:
            state = os.stat(document["pfad"])
        except (OSError, ValueError):
            # The row outlived its file. Nothing in the folder can be it.
            continue
        named.add((state.st_dev, state.st_ino))
    return named


def _chat_folders(
    config: "Config", repositories: "Repositories", chat: str | None
) -> list[tuple[str, str | None, Path]]:
    """The chat folders to look into, each with its chat and that chat's
    project: the one chat's when a chat is open, every chat's otherwise.

    Only a folder whose chat still exists. A chat deleted for good takes its
    folder with it, so a folder without a chat is a leftover, and a file in
    it belongs to nothing the list could name.
    """
    data = Path(config.datenverzeichnis)
    if chat:
        names = [chat]
    else:
        try:
            names = [entry.name for entry in (data / dokumentablage.CHATDATEIEN).iterdir()]
        except OSError:
            # No chat has kept a file yet.
            return []
    folders: list[tuple[str, str | None, Path]] = []
    for name in names:
        folder = dokumentablage.chatordner(data, name)
        if folder is None:
            continue
        owner = repositories.chats.holen(name)
        if owner is None:
            continue
        folders.append((owner.id, owner.project_id, folder))
    return folders


def _files_below(folder: Path) -> list[tuple[Path, str]]:
    """Every file in the folder and in the folders below it: where it really
    lies, and its path below the folder, written with ``/``.

    A missing folder is the state before the first file, and an empty list.

    A link is listed by where it leads, not by where it lies. One leading
    out of the folder is left out, and a linked folder is not walked into:
    the address resolves what it is asked for and refuses whatever ends up
    outside (``chat_file``), and a tile the address refuses is a tile
    nothing can open.
    """
    root = _real(folder)
    if root is None or not root.is_dir():
        return []
    found: list[tuple[Path, str]] = []
    waiting = [root]
    while waiting:
        place = waiting.pop()
        try:
            listed = list(os.scandir(place))
        except OSError:
            # Gone, or shut, since it was seen. Whatever is in it is not
            # there for the address either.
            continue
        for entry in listed:
            try:
                if entry.is_symlink():
                    # Only a link has to be resolved to know where it leads;
                    # everything else below a resolved folder lies where its
                    # path says, and a job's folder can hold tens of
                    # thousands of files.
                    file = _real(entry.path)
                    if file is None or not file.is_file() or not file.is_relative_to(root):
                        continue
                elif entry.is_dir(follow_symlinks=False):
                    waiting.append(Path(entry.path))
                    continue
                elif entry.is_file(follow_symlinks=False):
                    file = Path(entry.path)
                else:
                    continue
            except OSError:
                continue
            found.append((file, Path(entry.path).relative_to(root).as_posix()))
    return found


def chat_file(config: "Config", chat_id: str, name: str) -> Path | None:
    """One file below a chat's own folder, addressed by chat and by its path
    below that folder — or nothing.

    The chat's id only ever passes through ``chatordner``, which refuses
    whatever is not an id. The path is resolved before it is judged: that is
    what turns ``..`` and a link back into where they really lead, and what
    ends up outside the chat's folder — or is the folder itself, or is no
    file — is answered like a file that is not there.
    """
    folder = dokumentablage.chatordner(Path(config.datenverzeichnis), chat_id)
    if folder is None or not name:
        return None
    root = _real(folder)
    file = _real(folder / name) if root is not None else None
    if file is None or root is None:
        return None
    if file == root or not file.is_relative_to(root):
        return None
    return file if file.is_file() else None
