"""``/rollback``: the snapshots of the working folder, and putting files back.

Without a word it lists the snapshots the service took before the model
changed files, newest first, each with the files that changed after it. A
number puts back what the model changed since that snapshot and leaves a file
alone that was changed by hand afterwards; ``--all`` puts back every file and
takes the last question with its answer out of the chat; a file name puts back
just that file.

Which snapshots there are, and what a restore does, is the service's: the
client names a folder and a snapshot and shows what comes back.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text

from cli import tables
from cli.client import ServiceError
from cli.interfaces import Context, Entry
from cli.render import local_time

_ALL = "--all"
# How many file names a row of the list shows before it only counts.
_NAMES_SHOWN = 3


def run_command(ctx: Context, argument: str) -> None:
    folder = _folder(ctx)
    if folder is None:
        return
    try:
        found = ctx.client.get("/checkpoints", params={"directory": folder})
    except ServiceError as error:
        ctx.renderer.error(error.detail)
        return
    found = found if isinstance(found, dict) else {}
    texts = ctx.texts
    snapshots = [entry for entry in found.get("snapshots") or [] if isinstance(entry, dict)]
    if not snapshots:
        ctx.renderer.notice(texts.t("cli.rollback_none" if found.get("enabled") else "cli.rollback_inactive"))
        return
    wanted, _, rest = argument.strip().partition(" ")
    if not wanted:
        _list(ctx, snapshots)
        return
    snapshot = next((entry for entry in snapshots if str(entry.get("nr")) == wanted), None)
    if snapshot is None:
        ctx.renderer.error(texts.t("cli.unknown_choice", name=wanted))
        return
    _restore(ctx, folder, snapshot, rest.strip())


def _folder(ctx: Context) -> str | None:
    """The working folder the snapshots are about: the chat's only one, or
    the one picked of several."""
    texts = ctx.texts
    opened = ctx.session.chat
    folders: list[str] = []
    if opened is not None:
        fresh = ctx.client.get(f"/chats/{opened['id']}")
        listed = fresh.get("working_dirs") if isinstance(fresh, dict) else None
        folders = [str(folder) for folder in listed] if isinstance(listed, list) else []
    if not folders:
        ctx.renderer.notice(texts.t("cli.rollback_no_folder"))
        return None
    if len(folders) == 1:
        return folders[0]
    picked = ctx.asker.choose([Entry(cells=[("text", folder)]) for folder in folders])
    return None if picked is None else folders[picked]


def _list(ctx: Context, snapshots: list[dict[str, Any]]) -> None:
    rows = []
    for snapshot in snapshots:
        files = [str(name) for name in snapshot.get("files") or []]
        shown = ", ".join(files[:_NAMES_SHOWN]) + (" …" if len(files) > _NAMES_SHOWN else "")
        count = ctx.texts.t("cli.rollback_files", count=len(files))
        rows.append(
            (
                Text(str(snapshot.get("nr")), style="exe.accent"),
                Text(local_time(snapshot.get("time")), style="exe.muted"),
                Text(tables.one_line(snapshot.get("reason")), style="exe.text"),
                Text(f"{count}: {shown}" if files else count, style="exe.muted"),
            )
        )
    ctx.screen.print_above(tables.grid(rows, wide=2))


def _restore(ctx: Context, folder: str, snapshot: dict[str, Any], rest: str) -> None:
    texts = ctx.texts
    body: dict[str, Any] = {"directory": folder, "snapshot": snapshot["id"]}
    if rest == _ALL:
        body["all"] = True
    elif rest:
        body["file"] = rest
    try:
        result = ctx.client.post("/checkpoints/restore", json=body)
    except ServiceError as error:
        ctx.renderer.error(error.detail)
        return
    result = result if isinstance(result, dict) else {}
    restored, skipped, failed = (_names(result.get(key)) for key in ("restored", "skipped", "failed"))
    if restored:
        ctx.renderer.notice(texts.t("cli.rollback_done", count=len(restored), names=", ".join(restored)))
    elif not skipped and not failed:
        ctx.renderer.notice(texts.t("cli.rollback_nothing"))
    if skipped:
        ctx.renderer.notice(texts.t("cli.rollback_kept", count=len(skipped), names=", ".join(skipped)))
    if failed:
        ctx.renderer.error(texts.t("cli.rollback_failed", names=", ".join(failed)))
    # The conversation is only taken back when files were: a restore that
    # failed, or put nothing back, must not leave a chat without its last
    # turn as well.
    if rest == _ALL and restored and not failed:
        try:
            removed = _remove_last_turn(ctx)
        except ServiceError as error:
            ctx.renderer.error(error.detail)
            return
        if removed:
            ctx.renderer.notice(texts.t("cli.rollback_turn_removed"))


def _names(value: Any) -> list[str]:
    return [str(name) for name in value] if isinstance(value, list) else []


def _remove_last_turn(ctx: Context) -> bool:
    """Takes the last question and everything after it out of the chat,
    through the route that deletes a single message. Returns whether
    anything was removed."""
    opened = ctx.session.chat
    if opened is None:
        return False
    page = ctx.client.get(f"/chats/{opened['id']}/messages", params={"neueste": "true"})
    listed = page.get("nachrichten") if isinstance(page, dict) else None
    messages = [entry for entry in listed if isinstance(entry, dict)] if isinstance(listed, list) else []
    last_question = next(
        (index for index in range(len(messages) - 1, -1, -1) if messages[index].get("role") == "user"),
        None,
    )
    if last_question is None:
        return False
    for message in messages[last_question:]:
        ctx.client.delete(f"/chats/{opened['id']}/messages/{message['id']}")
    return True
