"""The folder tool — `create_folder`.

Creates a folder and shares it with the chat as a working folder, the way a
folder chosen with the folder chip is shared: checked, an ``exe.md`` put into
it (app/arbeitsordnerpruefung.py, ``share``), and stored with the chat — or
with its project, when the chat lies in one, so every chat of the project
sees it. Before this tool a folder only came into being on the side, as the
parent of a file ``write_file`` wrote.

Asked about like the other file tools: the path rule of
``app/berechtigungen.py`` decides, inside the shared folders by the mode,
outside them like ``write_file``. The tool gives the model nothing it did
not have — in the mode that lets it write anywhere it can already reach the
folder, and in the others the question shows the path first.

The folder counts from the next tool call of the same run on: it is added to
the run's own list of folders. A job run shares it for that run only; nothing
is stored for a job, which has no chat to store it with. The system message
of the run stays as it was — it changes at the next fold, like every other
change the model made.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app import arbeitsordnerpruefung, ordnerwissen
from app.tools import grenzen
from app.tools.mcp_client import MCPWerkzeug

SERVER_NAME = "shell"
WERKZEUG_NAME = "create_folder"


def werkzeug_beschreibung() -> MCPWerkzeug:
    return MCPWerkzeug(
        name=WERKZEUG_NAME,
        beschreibung=(
            "Creates a folder, with any parents it needs, and shares it as a "
            "working folder: from the next tool call on, the file tools work in "
            "it like in every other shared folder. In a chat the share is kept "
            "with the chat; in a job it lasts for this run. A folder that "
            "already exists is only shared.\n"
            "Relative paths resolve against the first shared folder. A folder "
            "outside the shared folders may need the user's confirmation first."
        ),
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The folder to create and share.",
                },
            },
            "required": ["path"],
        },
        server=SERVER_NAME,
    )


def aussenpfad(argumente: dict[str, Any], ordner: list[str]) -> str | None:
    return grenzen.aussenpfad(argumente, ordner)


def braucht_bestaetigung(argumente: dict[str, Any], ordner: list[str]) -> bool:
    return aussenpfad(argumente, ordner) is not None


async def ausfuehren(
    argumente: dict[str, Any],
    ordner: list[str],
    share: Callable[[str], None] | None = None,
    data_dir: Path | None = None,
) -> str:
    """Creates the folder, shares it, and says which one it is.

    ``ordner`` is the run's own list of folders and is extended in place, so
    the next call of the same run finds the new folder inside. ``share``
    stores the share with the chat (``ChatFolderShare``); a job run passes
    none. ``data_dir`` is the program's own data folder: a chat that shares
    nothing resolves a relative path in its private document folder there,
    and a folder in the program's data is no working folder to hand out.
    """
    raw = str(argumente.get("path") or "").strip()
    if not raw:
        raise grenzen.GrenzeVerletzt("create_folder needs a path.")
    target = grenzen.ziel(raw, ordner, data_dir)
    if data_dir is not None and grenzen.inside(target, Path(data_dir)):
        raise grenzen.GrenzeVerletzt(
            f"'{target}' is inside the program's own data folder. Provide an absolute path "
            "to a user-owned folder instead."
        )
    if target.exists() and not target.is_dir():
        raise grenzen.GrenzeVerletzt(f"'{target}' is a file, not a folder.")
    existed = target.is_dir()
    # The outermost folder this call is about to make, so a failed share
    # can take back everything it made and nothing that was there before.
    first_new = target
    while not first_new.parent.exists():
        first_new = first_new.parent
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise grenzen.GrenzeVerletzt(
            f"'{target}' could not be created ({error.strerror or error})."
        ) from error
    path = str(target.resolve())
    if share is not None:
        try:
            share(path)
        except Exception:
            # Nothing half done: what this call made and could not share
            # goes again — the folder, its new parents and the exe.md the
            # share may already have put in. Nothing else can be in it yet.
            if not existed:
                _take_back(target, first_new)
            raise
    already = path in ordner
    if not already:
        ordner.append(path)
    where = "this chat" if share is not None else "this run"
    if already:
        return f"'{path}' is already a working folder for {where}."
    if existed:
        return f"'{path}' already existed and is now a working folder for {where}."
    return f"Created '{path}' as a working folder of {where}."


def _take_back(target: Path, first_new: Path) -> None:
    """Removes what a failed call made: the ``exe.md`` the share may have
    written, then the folders from ``target`` up to ``first_new`` — each
    only while it is empty, so nothing somebody else put there in the
    meantime is lost."""
    try:
        ordnerwissen.datei(str(target)).unlink(missing_ok=True)
    except OSError:
        # What went wrong with the share is the answer the model needs; a
        # file that will not go does not get to replace it.
        return
    folder = target
    while True:
        try:
            folder.rmdir()
        except OSError:
            return
        if folder == first_new:
            return
        folder = folder.parent


class ChatFolderShare:
    """Stores a folder the tool made with the chat it was made for, the way
    the folder chip stores one: ``share`` checks it and puts the ``exe.md``
    in, and the list goes where the chat takes its folders from — the chat
    itself, or its project. A chat read from the table already carries its
    project's folders (app/db/repositories/chats.py). A folder the list
    already holds is not added twice.

    Built once with the repositories and the program's data folder
    (app/tools/aufbau.py); the chat comes from the run, never from the
    model's arguments.
    """

    def __init__(self, repositories, data_dir: Path | None) -> None:
        self.repositories = repositories
        self.data_dir = data_dir

    def __call__(self, chat_id: str, path: str) -> None:
        chat = self.repositories.chats.holen(chat_id)
        if chat is None:
            return
        known = list(chat.working_dirs or [])
        if path in known:
            return
        try:
            folders = arbeitsordnerpruefung.share([*known, path], "en", known=known, data_dir=self.data_dir)
        except HTTPException as error:
            raise grenzen.GrenzeVerletzt(str(error.detail)) from error
        if chat.project_id:
            self.repositories.projects.update(chat.project_id, working_dirs=folders)
        else:
            self.repositories.chats.aktualisieren(chat_id, working_dirs=folders)
