"""One way to write a file whole: a side file, then a rename onto the name.

Every file this program rewrites goes through here — the memory, the
system prompt, the endpoints, the dock's record, the notes beside a
model, a scaled copy of a picture. Writing in place truncates before it
writes, so a full disk, a process ending halfway or a reader landing in
between leaves half a file where a whole one stood; and half a record is
read as an empty one and written back as that. The side file takes the
bytes, reaches the disk, and only then takes the name in one step: a reader
sees the whole old file or the whole new one, and a write that fails leaves
the old file untouched and no side file behind.

The side file has a name of its own and is created exclusively, so it
never follows a link or replaces something somebody left in the folder. A
file that is a link keeps the link: the file it points to is the one
replaced. An existing file keeps its permission bits; a new one gets the
bits a plain write would give. A file its owner made read-only stays
refused, as a write in place refused it — a rename only asks the folder.

On Windows a rename onto a file that somebody has open is refused: a
second window reading the record, an editor holding the file, a scanner
passing by. The system reports it as access denied, so the refusal is
repeated — for up to a minute, with a pause that grows to a tenth of a
second — the way VS Code's file service renames. Across devices (a folder
on another drive, a bind mount) the file is copied over and the side file
deleted. Nothing is ever written through the target itself: that would be
exactly the half-file window this module exists against.
"""

from __future__ import annotations

import errno
import logging
import os
import secrets
import shutil
import stat
import sys
import time
from contextlib import suppress
from pathlib import Path

log = logging.getLogger(__name__)

WINDOWS = sys.platform == "win32"

# The retry on Windows: a held target is tried again for this long, with a
# pause that grows by one step per attempt up to the cap.
RETRY_SECONDS = 60.0
PAUSE_STEP_SECONDS = 0.01
PAUSE_MAX_SECONDS = 0.1

# What Windows reports for a target somebody has open: access denied (5), a
# sharing violation (32) and a lock violation (33) arrive as EACCES or
# EPERM, a busy file as EBUSY. Ambiguous — a real refusal is EACCES as well —
# so the retry is bounded, and a rename still refused at its end is raised
# as it came.
_HELD = frozenset({errno.EACCES, errno.EPERM, errno.EBUSY})


def write(
    path: Path, data: bytes | str, *, encoding: str = "utf-8", newline: str | None = None
) -> None:
    """Writes ``data`` to ``path`` whole, or not at all.

    ``bytes`` go to the disk as they are. A ``str`` is written as text,
    ``encoding`` and ``newline`` as ``open`` reads them — ``None`` turns a
    line break into the platform's, ``""`` keeps the text's own.
    """
    target = Path(os.path.realpath(path)) if path.is_symlink() else Path(path)
    if target.exists() and not os.access(target, os.W_OK):
        raise PermissionError(errno.EACCES, "Permission denied", str(target))
    side = target.with_name(side_file_name(target.name))
    created = False
    try:
        fd = os.open(side, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        created = True
        if isinstance(data, bytes):
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        else:
            with os.fdopen(fd, "w", encoding=encoding, newline=newline) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        with suppress(FileNotFoundError):
            os.chmod(side, stat.S_IMODE(target.stat().st_mode))
        rename_onto(side, target)
    except BaseException:
        if created:
            with suppress(OSError):
                os.unlink(side)
        raise


def side_file_name(target_name: str) -> str:
    """The name a side file for ``target_name`` gets: hidden, marked, and
    unique, so two writers of the same file never meet in one side file."""
    return f".{target_name}.{secrets.token_hex(8)}.tmp"


def is_side_file(name: str, target_name: str | None = None) -> bool:
    """Whether ``name`` is a side file of this module's — of ``target_name``
    where one is given. A listing of a folder that holds files of the user's
    must not count a write's side file as one of them: it exists only
    between the write's two steps, under a name nobody chose."""
    if not (name.startswith(".") and name.endswith(".tmp")):
        return False
    return target_name is None or name.startswith(f".{target_name}.")


def rename_onto(side: Path, target: Path) -> None:
    """Moves ``side`` onto ``target`` in one step; the target, if any, goes.

    ``os.replace`` as it stands, with the two cases it cannot do by itself:
    a target held open on Windows is tried again (see the module), and a
    target on another device is reached by a copy, the side file deleted
    after it. Any other refusal is raised as it came, for the caller to
    handle the way it handles its own writing.
    """
    try:
        os.replace(side, target)
        return
    except OSError as failure:
        if failure.errno == errno.EXDEV:
            _copy_over(side, target)
            return
        if not (WINDOWS and failure.errno in _HELD):
            raise
        refused = failure
    started = time.monotonic()
    log.info("Rename onto %s refused (%s): trying again", target, refused.strerror)
    attempt = 0
    while True:
        attempt += 1
        time.sleep(min(PAUSE_MAX_SECONDS, PAUSE_STEP_SECONDS * attempt))
        try:
            os.replace(side, target)
        except OSError as failure:
            if failure.errno == errno.EXDEV:
                _copy_over(side, target)
                return
            if not (WINDOWS and failure.errno in _HELD):
                raise
            if time.monotonic() - started >= RETRY_SECONDS:
                log.warning(
                    "Rename onto %s still refused after %d attempts: %s",
                    target, attempt, failure.strerror,
                )
                raise
            continue
        log.info("Rename onto %s landed on attempt %d", target, attempt + 1)
        return


def _copy_over(side: Path, target: Path) -> None:
    """The way across a device boundary: the bytes are copied to a second
    side file BESIDE the target — on its device — reach the disk there, and
    take the name in one step after all; then the first side file goes.
    Never through the target itself: a copy that broke off halfway would
    leave the half file this module exists against."""
    beside = target.with_name(side_file_name(target.name))
    try:
        shutil.copyfile(side, beside)
        with suppress(OSError):
            shutil.copystat(side, beside)
        with suppress(OSError), open(beside, "rb") as handle:
            os.fsync(handle.fileno())
        os.replace(beside, target)
    except BaseException:
        with suppress(OSError):
            os.unlink(beside)
        raise
    os.unlink(side)
