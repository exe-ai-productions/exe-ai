"""The beginning of the service's end, and the time the servers get for it.

A window closing, a terminal's Ctrl+C and the ``stop`` of the command line
all end the service with a termination signal; where the system has no polite
one, the marker file of ``app/stoppmarke.py`` raises the same signal inside
the process. uvicorn answers it by waiting for every open connection to end
before the lifespan's shutdown, which is where the servers are stopped. An
open stream never ends on its own (a window holds one all the time), so
without a time limit on that wait the shutdown never began, and with the
limit of ``start.py`` (3 seconds) only 2 of the 5 seconds the shell grants
before it kills the service were left for the servers.

So the signal is also heard here, ahead of uvicorn's wait: everything that
waits on a stream is told to end it at once (``on_begin``), and the servers
get one short, shared period to end (``SERVER_GRACE_SECONDS``) instead of
one period each, one after the other.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

log = logging.getLogger(__name__)

# The shell waits 5 seconds after its termination signal before it kills the
# service (fenster-electron/main.js, KILL_AFTER_MS), and ``start.py`` lets
# uvicorn wait 3 seconds for open connections: 5 - 3 = 2 seconds are left for
# everything the shutdown does after that. A server that was asked politely
# gets 1.5 of them, a stuck one is killed then, and the join below returns
# half a second later at the latest. All servers share these seconds: they
# are stopped side by side.
SERVER_GRACE_SECONDS = 1.5
SHUTDOWN_DEADLINE_SECONDS = 2.0

_hooks: list[Callable[[], None]] = []
_begun = False
_lock = threading.Lock()


def begun() -> bool:
    """Has the service started to end? Whatever would start a server asks."""
    return _begun


def on_begin(hook: Callable[[], None]) -> None:
    """Registers what has to happen as soon as the end begins. Runs on the
    loop, once; a hook that fails is logged and does not hold up the others."""
    with _lock:
        _hooks.append(hook)


def begin() -> None:
    """The end begins. Safe to call again: only the first call does anything."""
    global _begun
    with _lock:
        if _begun:
            return
        _begun = True
        hooks = list(_hooks)
    for hook in hooks:
        try:
            hook()
        except Exception:
            log.warning("A hook of the shutdown failed", exc_info=True)


def reset() -> None:
    """Back to a service that has not started to end. For a new lifespan in
    the same process (the tests start several) and for the tests themselves."""
    global _begun
    with _lock:
        _begun = False
        _hooks.clear()


def listen(loop: asyncio.AbstractEventLoop) -> Callable[[], None]:
    """Hears the termination signals ahead of uvicorn's own handler.

    uvicorn's handler only sets a flag; this one runs it afterwards and also
    schedules ``begin`` on the loop (a signal handler must not touch what the
    loop is in the middle of). Returns what puts the handlers back. A thread
    that is not the main one has no signals to hear: it returns at once and
    does nothing, like uvicorn itself there.
    """
    if threading.current_thread() is not threading.main_thread():
        return lambda: None
    wrapped: dict[int, tuple[Callable[..., Any], Any]] = {}

    def make(previous: Any) -> Callable[..., Any]:
        def handler(signum, frame):
            try:
                loop.call_soon_threadsafe(begin)
            except RuntimeError:
                begin()
            previous(signum, frame)

        return handler

    for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            previous = signal.getsignal(number)
            if not callable(previous):
                # Default or ignored: nobody here to hand the signal on to,
                # and replacing the default would change what it does.
                continue
            ours = make(previous)
            signal.signal(number, ours)
        except (ValueError, OSError):
            continue
        wrapped[number] = (ours, previous)

    def restore() -> None:
        for number, (ours, previous) in wrapped.items():
            try:
                if signal.getsignal(number) is ours:
                    signal.signal(number, previous)
            except (ValueError, OSError):
                pass

    return restore


def stop_together(
    stoppers: Mapping[str, Callable[[], object]],
    deadline: float = SHUTDOWN_DEADLINE_SECONDS,
) -> list[str]:
    """Runs every stopper at the same time and waits for all of them, but not
    longer than ``deadline`` seconds in all.

    Each runs in a thread of its own that does not keep the process alive: a
    stop stuck on a lock must not hold the service up either. Returns the
    names of those that had not finished when the time was up; a stopper that
    raises is logged and counts as finished.
    """
    threads: dict[str, threading.Thread] = {}

    def run(name: str, stopper: Callable[[], object]) -> None:
        try:
            stopper()
        except Exception:
            log.warning("%s could not be stopped on shutdown", name, exc_info=True)

    for name, stopper in stoppers.items():
        thread = threading.Thread(target=run, args=(name, stopper), name=f"stop-{name}", daemon=True)
        threads[name] = thread
        thread.start()
    # One end for all, not a period for each: the joins share the time left.
    end = time.monotonic() + deadline
    for thread in threads.values():
        thread.join(max(0.0, end - time.monotonic()))
    return [name for name, thread in threads.items() if thread.is_alive()]
