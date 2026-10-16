"""``/dir``: the working folders of the open chat — shown, shared, and
stopped being shared.

A shared folder is one the model works in without asking. The list lives
with the chat at the service, which checks a path (absolute or ``~``, an
existing folder) and refuses a wrong one with its own sentence; the client
sends the path as it was typed, with the rest of the list, and says what
the service says.

The selection of the folders — an entry to share another one, the folders
below it, and for one of them the question whether to stop sharing it —
stands here once, for every command that has folders to show.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

from cli import chat
from cli.client import ServiceError
from cli.interfaces import Context, Entry

# The words behind ``/dir``.
ADD = "add"
REMOVE = "remove"

# What ``pick`` returns for the entry that shares another folder.
SHARE = -1


def run_command(ctx: Context, argument: str) -> None:
    word, _, rest = argument.strip().partition(" ")
    word, rest = word.casefold(), rest.strip()
    if not word:
        _choose(ctx)
    elif word == ADD:
        _share(ctx, rest or None)
    elif word == REMOVE:
        _remove(ctx, rest, argument.strip())
    else:
        ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=argument.strip()))


# --- The selection ------------------------------------------------------------------


def pick(ctx: Context, folders: Sequence[str], missing: Collection[str] = ()) -> int | None:
    """Shows the folders as a selection with the entry to share another one
    on top, and returns what was picked: ``SHARE`` for that entry, the
    position of a folder in ``folders`` — or ``None`` where the selection
    was closed. A folder that is gone stands in yellow, with the sentence
    that says so above the selection."""
    texts = ctx.texts
    entries = [Entry(cells=[("text", texts.t("arbeitsordner.hinzufuegen" if folders else "arbeitsordner.waehlen"))])]
    gone = False
    for folder in folders:
        is_missing = folder in missing
        gone = gone or is_missing
        entries.append(Entry(cells=[("yellow" if is_missing else "text", folder)]))
    head = texts.t("arbeitsordner.fehlt_satz") if gone else ""
    picked = ctx.asker.choose(entries, head=head)
    if picked is None:
        return None
    return SHARE if picked == 0 else picked - 1


def ask_path(ctx: Context) -> str | None:
    """The path of a folder to share, typed — or ``None`` where nothing was
    typed or the question was left."""
    typed = ctx.asker.ask_text(ctx.texts.t("arbeitsordner.waehlen"))
    typed = (typed or "").strip()
    return typed or None


def confirm_release(ctx: Context, folder: str) -> bool:
    """Whether the user chose to stop sharing ``folder``."""
    entry = Entry(cells=[("text", ctx.texts.t("arbeitsordner.loesen"))])
    return ctx.asker.choose([entry], head=folder) == 0


# --- The open chat's folders ----------------------------------------------------------


def _current(ctx: Context) -> tuple[list[str], set[str]]:
    """The folders the open chat shares, read now, and those of them that
    are no longer there. A chat the service does not have yet shares none."""
    opened = ctx.session.chat
    if opened is None:
        return [], set()
    fresh = ctx.client.get(f"/chats/{opened['id']}")
    folders = fresh.get("working_dirs") if isinstance(fresh, dict) else None
    listed = [str(folder) for folder in folders] if isinstance(folders, list) else []
    state = ctx.client.get(f"/chats/{opened['id']}/ordnerstand")
    gone = state.get("fehlend") if isinstance(state, dict) else None
    return listed, {str(folder) for folder in gone} if isinstance(gone, list) else set()


def _choose(ctx: Context) -> None:
    folders, missing = _current(ctx)
    picked = pick(ctx, folders, missing)
    if picked is None:
        return
    if picked == SHARE:
        _share(ctx, None)
    elif confirm_release(ctx, folders[picked]):
        _save(ctx, [folder for index, folder in enumerate(folders) if index != picked])


def _share(ctx: Context, path: str | None) -> None:
    wanted = path or ask_path(ctx)
    if wanted is None:
        return
    # The chat is made at the service now, if it is only a new one here —
    # the way the window makes it when the first folder is shared.
    folders, _ = _current(ctx)
    if ctx.session.chat is None:
        # The folder the client started in is already shared by then.
        created = chat.service_chat(ctx)
        folders = [str(folder) for folder in created.get("working_dirs") or []]
    if wanted in folders:
        return
    _save(ctx, [*folders, wanted])


def _remove(ctx: Context, number: str, argument: str) -> None:
    if not number:
        _choose(ctx)
        return
    folders, _ = _current(ctx)
    # Entry 1 of the selection shares another folder; the folders count on
    # from 2.
    if not (number.isdecimal() and 2 <= int(number) <= len(folders) + 1):
        ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=argument))
        return
    gone = int(number) - 2
    _save(ctx, [folder for index, folder in enumerate(folders) if index != gone])


def _save(ctx: Context, folders: list[str]) -> None:
    """Sends the whole list; the answer is the chat as it stands."""
    opened = chat.service_chat(ctx)
    try:
        ctx.session.chat = ctx.client.patch(f"/chats/{opened['id']}", json={"working_dirs": folders})
    except ServiceError as error:
        ctx.renderer.error(error.detail)
