"""``/project``: the projects shown, made, renamed and deleted, and the
open chat moved into one or out of it.

The service owns the projects and every rule about them. What is written
here is the way to them: the selection, the questions before something is
lost, and what stands open afterwards. A project can only be deleted from
the archive; the way there is a step of this module, not of the user.
"""

from __future__ import annotations

from typing import Any

from cli import chat_actions, servers
from cli.client import ServiceError
from cli.interfaces import Context, Entry


def run_command(ctx: Context, argument: str) -> None:
    word = argument.strip()
    if not word:
        _choose(ctx)
    elif word.isdecimal():
        _numbered(ctx, int(word), word)
    else:
        ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=word))


# --- The selection --------------------------------------------------------------------------


def _listed(ctx: Context) -> list[dict[str, Any]]:
    found = ctx.client.get("/projects")
    listed = [entry for entry in found if isinstance(entry, dict)] if isinstance(found, list) else []
    # The numbers a word behind the command counts into from here on.
    ctx.session.shown_projects = listed
    return listed


def _choose(ctx: Context) -> None:
    listed = _listed(ctx)
    opened = (ctx.session.chat or {}).get("project_id")
    entries = [Entry(cells=[("text", ctx.texts.t("project.new"))])]
    entries += [
        Entry(
            cells=[
                ("text", " ".join(str(entry.get("name") or "").split())),
                ("muted", str(entry.get("chat_count", 0))),
            ],
            in_use=bool(opened) and entry.get("id") == opened,
        )
        for entry in listed
    ]
    picked = ctx.asker.choose(entries)
    if picked is None:
        return
    if picked == 0:
        _new(ctx)
    else:
        _menu(ctx, listed[picked - 1])


def _numbered(ctx: Context, number: int, word: str) -> None:
    """A number counts into the selection as it was last shown, where the
    first entry — the new project — is 1."""
    listed = ctx.session.shown_projects
    if listed is None:
        listed = _listed(ctx)
    if number == 1:
        _new(ctx)
    elif 2 <= number <= len(listed) + 1:
        _menu(ctx, listed[number - 2])
    else:
        ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=word))


# --- One project ------------------------------------------------------------------------------


def _menu(ctx: Context, project: dict[str, Any]) -> None:
    texts = ctx.texts
    opened = ctx.session.chat
    actions: list[tuple[str, str]] = []
    if opened is not None:
        inside = opened.get("project_id") == project.get("id")
        actions.append(
            ("remove" if inside else "move", texts.t("project.remove_from" if inside else "project.move_to"))
        )
    actions += [("rename", texts.t("chat.umbenennen")), ("delete", texts.t("chat.loeschen"))]
    picked = ctx.asker.choose(
        [Entry(cells=[("text", label)]) for _, label in actions],
        head=" ".join(str(project.get("name") or "").split()),
    )
    if picked is None:
        return
    what = actions[picked][0]
    if what in ("move", "remove"):
        _move(ctx, project, into=what == "move")
    elif what == "rename":
        _rename(ctx, project)
    else:
        _delete(ctx, project)


def _new(ctx: Context) -> None:
    typed = ctx.asker.ask_text(ctx.texts.t("project.name_question"))
    name = (typed or "").strip()
    if not name:
        return
    try:
        ctx.client.post("/projects", json={"name": name})
    except ServiceError as error:
        ctx.renderer.error(error.detail)


def _move(ctx: Context, project: dict[str, Any], *, into: bool) -> None:
    """Puts the open chat into the project, or takes it out; the open chat
    is the answer of the service from then on."""
    opened = ctx.session.chat
    if opened is None:
        return
    try:
        answer = ctx.client.patch(
            f"/chats/{opened['id']}", json={"project_id": project.get("id") if into else None}
        )
    except ServiceError as error:
        ctx.renderer.error(error.detail)
        return
    if isinstance(answer, dict):
        ctx.session.chat = answer


def _rename(ctx: Context, project: dict[str, Any]) -> None:
    current = str(project.get("name") or "")
    typed = ctx.asker.ask_text(ctx.texts.t("project.name_question"), default=current)
    name = (typed or "").strip()
    if not name or name == current:
        return
    try:
        ctx.client.patch(f"/projects/{project['id']}", json={"name": name})
    except ServiceError as error:
        ctx.renderer.error(error.detail)


def _delete(ctx: Context, project: dict[str, Any]) -> None:
    """Deletes the project with its chats after the question. The service
    deletes only from the archive: the project goes there first, and comes
    back from it where the deletion is refused. An open chat that went
    with it is replaced by a new one."""
    question = ctx.texts.t(
        "archive.delete_project_question",
        name=str(project.get("name") or ""),
        count=project.get("chat_count", 0),
    )
    if not servers.ask(ctx, question):
        return
    path = f"/projects/{project['id']}"
    try:
        ctx.client.patch(path, json={"archived": True})
    except ServiceError as error:
        ctx.renderer.error(error.detail)
        return
    try:
        gone = ctx.client.delete(path)
    except ServiceError as error:
        try:
            ctx.client.patch(path, json={"archived": False})
        except ServiceError:
            pass
        ctx.renderer.error(error.detail)
        return
    opened = ctx.session.chat
    if opened is not None and opened.get("id") in (gone if isinstance(gone, list) else []):
        chat_actions.open_new(ctx)
