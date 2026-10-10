"""An advisory lock the kernel lets go of the moment its holder dies.

The service's note on a shared data folder (``app/main.py``) says who is
using it; this says whether that somebody is still there. A process id can
be recycled and a port is bound only after the whole startup has run, so
neither answers for a service that is alive but not yet listening. A lock
held for the life of the process answers exactly that: nobody but a live
holder can hold it, and a holder that is killed drops it without being
asked.

POSIX gives it as ``flock``, Windows as ``msvcrt.locking``; both are taken
on a file of their own beside the note, so the note itself stays readable
by everybody while the lock is held.
"""

from __future__ import annotations

import errno
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import IO

if sys.platform == "win32":  # pragma: no cover - the Windows half
    import msvcrt
else:
    import fcntl

log = logging.getLogger(__name__)


@dataclass
class Schloss:
    """A held lock: the open file it lives on. Dropped by :func:`loslassen`
    or by the kernel when the process ends."""

    datei: IO[bytes]


def halten(pfad: Path) -> Schloss | None:
    """Takes the lock on ``pfad``, or answers ``None`` when it cannot be
    had — somebody else holds it, or it cannot be taken at all. Never
    blocks."""
    schloss, _error = try_lock(pfad)
    return schloss


# What the kernel answers when the lock is free of faults but somebody else
# holds it. POSIX ``flock`` with ``LOCK_NB`` may answer either of the first
# two, so both are checked; ``msvcrt.locking`` answers a locked byte range
# with the last two.
_HELD_ELSEWHERE = (
    {errno.EACCES, errno.EDEADLK}
    if sys.platform == "win32"
    else {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}
)


def try_lock(path: Path) -> tuple[Schloss | None, OSError | None]:
    """One try at the lock on ``path``: the file opened once and locked,
    never blocking. ``(lock, None)`` when it was taken, ``(None, None)``
    while somebody else holds it, ``(None, error)`` when the file cannot be
    opened or the lock cannot be taken on it at all — no file system lock,
    no lock table left. The reason comes from that one try, so a caller can
    tell the two cases apart without opening the file a second time."""
    try:
        file = open(path, "a+b")
    except OSError as error:
        return None, error
    try:
        if sys.platform == "win32":  # pragma: no cover - the Windows half
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        file.close()
        if error.errno in _HELD_ELSEWHERE:
            return None, None
        return None, error
    return Schloss(file), None


def loslassen(schloss: Schloss | None) -> None:
    """Gives the lock back and closes the file. Safe to call twice."""
    if schloss is None or schloss.datei.closed:
        return
    try:
        if sys.platform == "win32":  # pragma: no cover - the Windows half
            schloss.datei.seek(0)
            msvcrt.locking(schloss.datei.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(schloss.datei.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    schloss.datei.close()


# The lock files whose unknown state was already said as a warning.
_SAID_UNKNOWN: set[Path] = set()


def gehalten(pfad: Path) -> bool | None:
    """Is somebody holding the lock on ``pfad`` right now?

    Asked by trying to take it: a lock somebody else holds is held
    (``True``), one that can be taken is given straight back (``False``). A
    file that is not there is held by nobody. A lock that cannot be taken at
    all — a file that cannot be opened, a file system without locks —
    answers nothing (``None``): whether its holder is alive has to be asked
    another way. That case is said in the log.
    """
    if not pfad.exists():
        return False
    schloss, error = try_lock(pfad)
    if error is not None:
        # Said once per lock and process: a scan asks about the same lock
        # file on every start check, and one line says all there is to say.
        level = logging.DEBUG if pfad in _SAID_UNKNOWN else logging.WARNING
        _SAID_UNKNOWN.add(pfad)
        log.log(level, "Lock %s cannot be taken (%s): whether it is held is not known", pfad, error)
        return None
    if schloss is None:
        return True
    loslassen(schloss)
    return False
