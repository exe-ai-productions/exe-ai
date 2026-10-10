"""The doc folder: every file the person has, in one list, whoever brought it.

Two places hold files, and each keeps doing its own job:

* the dock (``app/agentendock.py``) — files without a chat: dropped on the
  start page, or delivered by a job that has no chat;
* the documents of a chat (the ``documents`` table) — files uploaded into a
  conversation, dropped while it was open, or delivered by a job started
  from it; they lie in that chat's own folder and go with the chat.

Nothing is copied or moved to make the folder. It is a READ over those two
places: one row per file with where it came from, and the address the file
is fetched from. The places stay the truth; the folder is how they are seen
together.

Origin is who brought the file, read off the entry itself: no agent named —
the person; an agent and a job a cron entry started — a cron job; any other
agent — an agent. The same rule for the dock and for a chat's documents.
The chat a file belongs to is a chat document's own chat and a dock file's
job's chat; the project is that chat's project.

A chat sees its own files and no other chat's; the start page, with no chat
open, sees every file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.agentendock import dock_fuer

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

    for document in repositories.documents.for_folder():
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

    if origin:
        rows = [row for row in rows if row["origin"] == origin]
    if project:
        rows = [row for row in rows if row["project_id"] == project]
    if chat:
        rows = [row for row in rows if row["chat_id"] == chat]
    rows.sort(key=lambda row: row["created"], reverse=True)
    return rows
