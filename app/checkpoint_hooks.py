"""The calls that put a snapshot away before they change files.

The file tools write and edit; the shell may delete, move, copy or overwrite.
Just before such a call runs, the folders it can reach are snapshotted
(``app/checkpoints.py``), and afterwards what it changed goes into the ledger
so a restore can tell the model's work from the person's.

Everything here is a no-op while the switch is off, and a failure never
reaches the call: the tool runs as it always did.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any, NamedTuple

from app import checkpoints
from app.checkpoint_choice import enabled
from app.tools import datei_aendern, datei_schreiben, grenzen, shell

log = logging.getLogger(__name__)

# Where the snapshots live, inside the program's data folder.
FOLDER_NAME = "checkpoints"

_FILE_TOOLS = (datei_schreiben.WERKZEUG_NAME, datei_aendern.WERKZEUG_NAME)

_START = r"(?:^|[\s;&|`('\"/])"
# Commands that remove, replace or overwrite files.
_DESTRUCTIVE = re.compile(
    rf"{_START}(?:rm|rmdir|cp|install|mv|truncate|dd|shred)\s"
    rf"|{_START}sed\s+(?:\S+\s+)*?-[A-Za-z]*i"
    rf"|{_START}git\s+(?:reset|clean|checkout)\s"
)
# ``tee`` writes the file it is given (``-a`` only appends, but that is not told
# apart here: a snapshot too many costs one copy, one too few costs files).
_TEE = re.compile(rf"{_START}tee\s")
# ``find`` with ``-delete`` removes what it finds.
_FIND_DELETE = re.compile(rf"{_START}find\s+(?:\S+\s+)*?-delete\b")
# ``rsync`` removes on the receiving side with every ``--del…`` option and on the
# sending side with ``--remove-source-files``.
_RSYNC_DELETE = re.compile(rf"{_START}rsync\s+(?:\S+\s+)*?--(?:del\w*|remove-source-files)\b")
# An interpreter or a shell running a script or a one-liner: what it does to
# files cannot be read from the command.
_SCRIPT = re.compile(rf"{_START}(?:python[\d.]*|node|perl|ruby|sh|bash|zsh)\s")
# A redirect that replaces a file: ``>`` but neither ``>>`` (appends) nor
# ``>&`` (copies a stream).
_OVERWRITE = re.compile(r"(?<!>)>(?![>&])")


class Pending(NamedTuple):
    """What to note once the call has run: the file it wrote, or — for a
    command, which names none — the folders whose changes are the model's."""

    base: Path
    directories: tuple[Path, ...]
    file: Path | None


def is_destructive(command: str) -> bool:
    return bool(command) and any(
        pattern.search(command)
        for pattern in (_DESTRUCTIVE, _OVERWRITE, _TEE, _FIND_DELETE, _RSYNC_DELETE, _SCRIPT)
    )


def store_folder(data_dir: Path | str) -> Path:
    return Path(data_dir) / FOLDER_NAME


def shared_folders(folders: list[str], data_dir: Path | str) -> list[Path]:
    """The folders the person shared, without the chat's own private folder
    in the data folder and without a folder that holds the data folder —
    nothing there is snapshotted, listed or restored."""
    data = Path(data_dir)
    # A folder that holds the data folder would take the snapshots into
    # its own snapshots.
    return [
        root for root in grenzen.wurzeln(folders)
        if not grenzen.inside(root, data) and not grenzen.inside(data, root)
    ]


async def before(
    repositories: Any, data_dir: Path | str | None, name: str, arguments: dict[str, Any],
    folders: list[str] | None, chat_id: str | None, turn: str | None,
) -> Pending | None:
    """Takes the snapshots this call calls for, if any. ``turn`` is the answer
    or run the call belongs to: a folder is snapshotted once per turn."""
    if data_dir is None or not folders or turn is None or repositories is None:
        return None
    if name != shell.WERKZEUG_NAME and name not in _FILE_TOOLS:
        return None
    try:
        if not enabled(repositories):
            return None
        base = store_folder(data_dir)
        roots = shared_folders(folders, data_dir)
        if name == shell.WERKZEUG_NAME:
            command = str(arguments.get("command") or "")
            if not is_destructive(command):
                return None
            # A command can reach any folder that is shared, not only the one
            # it starts in.
            for root in roots:
                await asyncio.to_thread(checkpoints.snapshot, base, root, turn, f"{name}: {command}")
            # What a command running in the background changes is not yet
            # changed when the call returns: nothing to note.
            if arguments.get("background"):
                return None
            return Pending(base, tuple(roots), None)
        raw = str(arguments.get("path") or "").strip()
        if not raw:
            return None
        target = grenzen.aufgeloest(raw, grenzen.wurzeln(folders)[0])
        home = next((root for root in roots if grenzen.inside(target, root)), None)
        if home is None:
            return None
        shown = _shown(target, home, raw)
        await asyncio.to_thread(checkpoints.snapshot, base, home, turn, f"{name} {shown}")
        return Pending(base, (home,), target)
    except Exception:  # noqa: BLE001 - the call must run whatever happens here
        log.warning("Snapshot before %s failed", name, exc_info=True)
        return None


def _shown(target: Path, root: Path, raw: str) -> str:
    """The file as the reason of a snapshot names it: relative to its folder."""
    try:
        return target.relative_to(root).as_posix() if target != root else raw
    except ValueError:
        # Matched to the folder without regard to case, so the spellings differ.
        return raw


async def after(pending: Pending | None, *, ran: bool) -> None:
    """Notes what the call changed, so a restore knows it for the model's:
    the file a write left behind, or everything a command changed. A write
    that failed changed nothing; a command that failed may have."""
    if pending is None:
        return
    if pending.file is not None:
        if ran:
            await asyncio.to_thread(
                checkpoints.record_write, pending.base, pending.directories[0], pending.file
            )
        return
    for root in pending.directories:
        await asyncio.to_thread(checkpoints.record_changes, pending.base, root)
