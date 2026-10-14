"""Which process this service is: the number the system gave it, and when
that process began.

A client hands the service a folder of its own machine only where both run
on the same one, and the name of an address does not say that: a forwarded
port answers under a name of the client's machine, and the service of that
machine answers under any of its addresses. What a client on the same
machine can check, and no other, is the process — the system's process list
knows the number and when the process behind it began. The number alone
would prove nothing: every machine counts its own, and hands the number of a
process that is gone on to a later one.

The beginning is read where the terminal client reads it (cli/service.py,
``began``), from the system's own tools: the process list, which names the
running time, and on Windows the shell that names the start itself. Read by
the same means, the two readings agree to the second the list counts in.

A running time says how long ago, and the machine's clock turns that into a
moment. So the list is read anew whenever the service is asked: a clock set
since then moves this reading the way it moves the client's. A beginning
kept from an earlier clock would be one no client finds.
"""

from __future__ import annotations

import functools
import os
import subprocess
import sys
import time
from typing import NamedTuple

from app.no_console import no_window

# How the process list writes a running time: days, then hours, minutes and
# seconds — sixty of each place make one of the place before it.
CLOCK_STEP = 60
SECONDS_PER_DAY = 24 * 60 * 60

# Windows counts time in steps of a hundred nanoseconds since 1601; this
# many of them make a second, and this many seconds lie between that start
# and the one the rest of the program counts from.
WINDOWS_TICKS_PER_SECOND = 10_000_000
WINDOWS_EPOCH_SECONDS = 11_644_473_600


def _elapsed(text: str) -> float | None:
    """The seconds a running time of the form ``[[dd-]hh:]mm:ss`` stands
    for, or ``None`` for anything else."""
    days, _, clock = text.rpartition("-")
    parts = clock.split(":")
    if len(parts) not in (2, 3):
        return None
    try:
        seconds = 0
        for part in parts:
            seconds = seconds * CLOCK_STEP + int(part)
        return float((int(days) if days else 0) * SECONDS_PER_DAY + seconds)
    except ValueError:
        return None


def _listed(command: list[str]) -> str | None:
    """What a system tool prints, or ``None`` where the tool is not there
    or refuses."""
    try:
        asked = subprocess.run(
            command,
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
            **no_window(),
        )
    except OSError:
        return None
    return asked.stdout.strip() if asked.returncode == 0 else None


@functools.cache
def _start_on_windows(pid: int) -> float:
    """When the process behind ``pid`` began, as the shell on Windows names
    it: the start itself, in the system's own count of time. That figure
    never changes and the shell takes its time over it, so it is asked for
    once. Raises ``LookupError`` where the shell does not say — an answer
    that is not kept: the next ask asks again."""
    asked = f"(Get-Process -Id {int(pid)}).StartTime.ToFileTimeUtc()"
    ticks = _listed(["powershell", "-NoProfile", "-NonInteractive", "-Command", asked])
    if ticks is None or not ticks.isdigit():
        raise LookupError(pid)
    return int(ticks) / WINDOWS_TICKS_PER_SECOND - WINDOWS_EPOCH_SECONDS


def _began(pid: int) -> float | None:
    """When the process behind ``pid`` began, in seconds since the epoch —
    ``None`` where the system does not say."""
    if sys.platform == "win32":
        try:
            return _start_on_windows(pid)
        except LookupError:
            return None
    now = time.time()
    running = _listed(["ps", "-o", "etime=", "-p", str(int(pid))])
    age = _elapsed(running) if running is not None else None
    return None if age is None else now - age


class Process(NamedTuple):
    """A process as the system knows it: its number, and when it began in
    seconds since the epoch."""

    pid: int
    began: float


def named() -> Process | None:
    """This process, as a client on the same machine can find it again.
    ``None`` where the system does not say when it began — then the service
    names no process, and no client takes it for the one of its own machine.
    """
    pid = os.getpid()
    began = _began(pid)
    return None if began is None else Process(pid, began)
