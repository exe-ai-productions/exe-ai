"""Which process this service is: the number the system gave it, and when
that process began.

A client hands the service a folder of its own machine only where both run
on the same one, and the name of an address does not say that: a forwarded
port answers under a name of the client's machine, and the service of that
machine answers under any of its addresses. What a client on the same
machine can check, and no other, is the process — the system knows the
number and when the process behind it began. The number alone would prove
nothing: every machine counts its own, and hands the number of a process
that is gone on to a later one.

The beginning is read from the system by the process library, where the
terminal client reads it (cli/service.py, ``began``): no program of the
system is started for it, and no running time is reckoned back from the
clock of the moment. On Linux the library works the start out from the time
the machine booted, which a clock set since moves; the client allows for
that with a tolerance.
"""

from __future__ import annotations

import os
from typing import NamedTuple

import psutil


def _began(pid: int) -> float | None:
    """When the process behind ``pid`` began, in seconds since the epoch —
    ``None`` where the system does not say."""
    try:
        return psutil.Process(int(pid)).create_time()
    except (psutil.Error, OSError, OverflowError, ValueError):
        return None


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
