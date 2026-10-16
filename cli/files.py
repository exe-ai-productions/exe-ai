"""``/files``: the files of the open chat as a list in the history — name,
who they are from, size and date — and under it the folder they lie in.

Only shown: nothing is opened and nothing is removed, and a chat that is
not there yet is not created for it.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text

from cli import tables
from cli.client import ServiceError
from cli.interfaces import Context
from cli.render import local_time

# What stands in the agent field of a file that no agent made: the markers
# the service uses for work that runs without an agent.
_MARKERS = {
    "(none)": "cronjobs.ohne_agent",
    "(skript)": "cronjobs.kind_script",
    "(reminder)": "cronjobs.kind_reminder",
}
_USER = "user"


def run_command(ctx: Context, argument: str) -> None:
    word = argument.strip()
    if word:
        ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=word))
        return
    texts = ctx.texts
    opened = ctx.session.chat
    # A chat the service does not have yet has no files; nothing is asked.
    found = (
        ctx.client.get("/doc-folder", params={"chat": opened["id"]}) if opened is not None else []
    )
    files = [entry for entry in found if isinstance(entry, dict)] if isinstance(found, list) else []
    if not files:
        ctx.renderer.notice(texts.t("docfolder.empty"))
        return
    rows = [
        (
            Text(str(entry.get("name") or ""), style="exe.accent"),
            Text(_origin(ctx, entry), style="exe.muted"),
            Text(size_of(entry.get("size")), style="exe.muted"),
            Text(local_time(entry.get("created")) if entry.get("created") else "", style="exe.muted"),
        )
        for entry in files
    ]
    ctx.screen.print_above(tables.grid(rows))
    path = _folder(ctx, str(opened["id"]) if opened is not None else "")
    if path:
        ctx.screen.print_above(Text(f"{texts.t('docfolder.ordner')}: {path}", style="exe.muted"))


def _origin(ctx: Context, entry: dict[str, Any]) -> str:
    """Who a file is from, as the window says it."""
    texts = ctx.texts
    if entry.get("origin") == _USER:
        return texts.t("docfolder.by_you")
    agent = str(entry.get("agent") or "")
    shown = texts.t(_MARKERS[agent]) if agent in _MARKERS else agent
    return texts.t("docfolder.by_agent", agent=shown or "—")


def _folder(ctx: Context, chat_id: str) -> str:
    """The folder the files of the chat lie in; nothing where the service
    names none."""
    try:
        answer = ctx.client.get("/doc-folder/place", params={"chat": chat_id})
    except ServiceError:
        return ""
    path = answer.get("path") if isinstance(answer, dict) else None
    return path if isinstance(path, str) else ""


def size_of(size: Any) -> str:
    """What a file weighs, in the shortest honest form, as the window says
    it: bytes, then kilobytes, then megabytes with one decimal."""
    try:
        count = int(size)
    except (TypeError, ValueError):
        return ""
    if count < 1024:
        return f"{count} B"
    if count < 1024 * 1024:
        return f"{round(count / 1024)} KB"
    return f"{count / 1024 / 1024:.1f} MB"
