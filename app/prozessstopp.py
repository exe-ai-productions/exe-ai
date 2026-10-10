"""Ending a spawned process together with everything it spawned.

Every long-running helper this program starts — llama-server, the image
generator — starts helpers of its own. A signal to the parent alone leaves
those holding the port or the graphics memory, so stopping has to reach the
whole tree.

POSIX and Windows have nothing in common here. POSIX puts the child in its
own session (`start_new_session=True`) and the whole group can be signalled
at once. Windows has no process groups in that sense and no `os.killpg` at
all — reaching for it there raises `AttributeError`, which is how a stop
button ends up doing nothing while the process keeps running. The tree is
ended with `taskkill /T` instead, the one call that walks the children.

Both paths ask first and insist afterwards: a term signal, a grace period,
then a kill.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from typing import Callable

from app.no_console import no_window

FRIST = 10
"""Seconds a process gets to end on its own before it is killed."""

WINDOWS = sys.platform == "win32"


def beenden(prozess: subprocess.Popen, frist: int = FRIST) -> None:
    """Ends the process and its children, or returns if it is already gone.

    Never raises: a stop that fails must not take the caller with it, because
    the caller has state to clear either way.
    """
    if prozess.poll() is not None:
        return
    try:
        _term(prozess.pid)
    except (ProcessLookupError, PermissionError, OSError):
        # Gone between the check and the signal, or not ours to signal.
        return
    try:
        prozess.wait(timeout=frist)
    except subprocess.TimeoutExpired:
        try:
            _kill(prozess.pid)
        except (ProcessLookupError, PermissionError, OSError):
            pass


async def stop_watched(
    ended: Callable[[], bool],
    term: Callable[[], None],
    kill: Callable[[], None],
    grace: float = FRIST,
) -> None:
    """The same two steps for a process somebody else is watching — a
    command run, whose end its companion records (app/tools/shell.py).

    ``ended`` says whether it is over; waited on rather than the process,
    because a run is over when its output is closed, not when the shell
    around it exits. ``term`` and ``kill`` are the caller's own polite and
    hard step: it knows the tree better than a bare signal to a process id
    does — a leader already reaped, a group number that may no longer be
    ours. This keeps only the order and the grace period. Never raises.
    """
    if ended():
        return
    try:
        term()
    except (ProcessLookupError, PermissionError, OSError):
        pass
    deadline = time.monotonic() + grace
    while not ended() and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    if not ended():
        try:
            kill()
        except (ProcessLookupError, PermissionError, OSError):
            pass


def beenden_nach_pid(pid: int) -> bool:
    """Ends a process this program started in an earlier run.

    After a service crash there is no `Popen` left, only the number written
    to the note beside the model folder. The caller has already made sure the
    id still belongs to one of ours — ids get recycled.

    Returns whether the signal reached something.
    """
    try:
        _term(pid)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    return True


def _term(pid: int) -> None:
    if WINDOWS:
        # /T walks the children, /F is needed because a console process
        # without a window ignores the polite request. A non-zero code means
        # there was nothing left to end — the same case POSIX reports as
        # ProcessLookupError, so it is raised as that and handled in one place.
        ergebnis = subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            check=False,
            capture_output=True,
            **no_window(),
        )
        if ergebnis.returncode != 0:
            raise ProcessLookupError(pid)
        return
    os.killpg(os.getpgid(pid), signal.SIGTERM)


def _kill(pid: int) -> None:
    if WINDOWS:
        # taskkill /F already kills; there is no harder step to take.
        return
    os.killpg(os.getpgid(pid), signal.SIGKILL)
