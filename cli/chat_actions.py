"""What the commands do to chats: the selection of them with its search and
the archive, and renaming, deleting and archiving the open one.

The service owns the chats and every rule about them. What is written here
is the way to them: the selection that searches while the user types, the
questions before something is lost, and what stands open afterwards.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from cli import chat, servers
from cli.client import ServiceError
from cli.interfaces import Context, Entry
from cli.render import local_time

# The word behind ``/chats`` that shows the archive.
ARCHIVE = "archive"

# What waits for an answer, or answers, in a task of a chat.
_ACTIVE = ("laeuft", "wartet")


# --- The selection --------------------------------------------------------------------------


def entries_of(ctx: Context, listed: Sequence[dict[str, Any]]) -> list[Entry]:
    """The chats as the lines of a selection: the title, when it was last
    changed and whether an answer is being written into it. The chat that
    is open carries the sign."""
    open_id = ctx.session.chat_id()
    return [
        Entry(
            cells=[
                ("text", " ".join(str(entry.get("title") or "").split())),
                ("muted", local_time(entry.get("updated_at"))),
                ("blue", ctx.texts.t("cli.laeuft") if entry.get("laeuft") else ""),
            ],
            in_use=entry.get("id") == open_id,
            value=entry,
        )
        for entry in listed
    ]


def _listing(ctx: Context, *, archived: bool, word: str = "") -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    if word:
        params["suche"] = word
    if archived:
        params["archived"] = "true"
    found = ctx.client.get("/chats", params=params or None)
    return [entry for entry in found if isinstance(entry, dict)] if isinstance(found, list) else []


def choose(
    ctx: Context, listed: Sequence[dict[str, Any]], *, archived: bool = False, head: str = ""
) -> dict[str, Any] | None:
    """Shows ``listed`` as a selection that searches while the user types —
    the search asks the service for the chats that hold the word, in the
    archive where ``archived`` is true — and returns the chat that was
    picked, or ``None``."""
    texts = ctx.texts

    def find(word: str) -> list[Entry]:
        return entries_of(ctx, _listing(ctx, archived=archived, word=word))

    picked = ctx.asker.search(
        entries_of(ctx, listed),
        find,
        head=head or texts.t("chat.suchen"),
        empty=texts.t("chat.keine_treffer"),
    )
    value = picked.value if picked is not None else None
    return value if isinstance(value, dict) else None


def show_archive(ctx: Context) -> None:
    """The archived chats as a selection; a chat that is picked is offered
    to be brought back, and goes back to the list of chats."""
    texts = ctx.texts
    listed = _listing(ctx, archived=True)
    picked = choose(ctx, listed, archived=True, head=texts.t("archive.title"))
    if picked is None:
        return
    restore = ctx.asker.choose(
        [Entry(cells=[("text", texts.t("archive.restore"))])],
        head=" ".join(str(picked.get("title") or "").split()),
    )
    if restore != 0:
        return
    try:
        ctx.client.patch(f"/chats/{picked['id']}", json={"archived": False})
    except ServiceError as error:
        ctx.renderer.error(error.detail)


# --- The open chat ----------------------------------------------------------------------------


def rename(ctx: Context, argument: str) -> None:
    """Gives the open chat a name. Without one in the line the name is
    asked for, with the one that stands filled in; nothing typed, or the
    question left, changes nothing. A chat that is not at the service yet
    keeps the name until it is made, and its first message names it no
    more."""
    session = ctx.session
    name = " ".join(argument.split())
    if not name:
        current = str((session.chat or {}).get("title") or session.pending_title or chat.fresh_title(ctx))
        typed = ctx.asker.ask_text(ctx.texts.t("chat.neuer_titel"), default=current)
        name = (typed or "").strip()
        if not name or name == current:
            return
    if session.chat is None:
        session.pending_title = name
        session.unnamed = False
        ctx.screen.update_status(chat_title=name)
        return
    try:
        session.chat = ctx.client.patch(f"/chats/{session.chat['id']}", json={"title": name})
    except ServiceError as error:
        ctx.renderer.error(error.detail)
        return
    ctx.screen.update_status(chat_title=name)


def delete(ctx: Context, argument: str) -> None:
    """Deletes the open chat after the question, and opens a new one. A
    chat that is not at the service yet has nothing to delete."""
    session = ctx.session
    opened = session.chat
    if opened is None:
        return
    texts = ctx.texts
    question = texts.t("chat.loeschen_frage")
    agent = _agent_at_work(ctx, str(opened["id"]))
    if agent is not None:
        question = texts.t("chat.delete_with_agent_question", agent=agent)
    if not servers.ask(ctx, question):
        return
    try:
        ctx.client.delete(f"/chats/{opened['id']}")
    except ServiceError as error:
        ctx.renderer.error(error.detail)
        return
    ctx.renderer.notice(texts.t("chat.geloescht"))
    open_new(ctx)


def archive(ctx: Context, argument: str) -> None:
    """Puts the open chat into the archive, without a question, and opens a
    new one. A chat that is not at the service yet is not archived."""
    opened = ctx.session.chat
    if opened is None:
        return
    try:
        ctx.client.patch(f"/chats/{opened['id']}", json={"archived": True})
    except ServiceError as error:
        ctx.renderer.error(error.detail)
        return
    ctx.renderer.notice(ctx.texts.t("cli.chat_archived"))
    open_new(ctx)


def _agent_at_work(ctx: Context, chat_id: str) -> str | None:
    """The name of the agent of a task of this chat that still runs or
    waits for an answer — the one the question names."""
    try:
        found = ctx.client.get("/jobs")
    except ServiceError:
        return None
    for job in found if isinstance(found, list) else []:
        if isinstance(job, dict) and job.get("chat_id") == chat_id and job.get("state") in _ACTIVE:
            return str(job.get("agent") or "")
    return None


def open_new(ctx: Context) -> None:
    """Opens a new chat as ``/new`` does — behind the answer that is still
    being written into the chat that went, in its turn."""
    if ctx.session.answering:
        ctx.screen.new_chat()
        return
    chat.new_chat(ctx)
    # A stage belongs to the chat it was set in.
    ctx.session.thinking = None
