"""The request to end a running service where the system has no polite one.

On Windows a termination signal is the end of the process on the spot: the
service's own shutdown never runs, and the model server and the other
servers it started stay behind. So the client does not signal the process —
it lays a marker file beside the service's note, and the service, which
looks for that file while it runs, ends itself the way it ends on a window
closing: through the ordinary shutdown, which takes its servers with it.

Only the client's ``stop`` writes the marker (cli/service.py), only a
running service reads and removes it, and a marker found at the start is a
leftover of a request nobody answered: it is removed before the watch
begins, so a service that has just started is not ended by it.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

# The marker's name beside the note ``.dienst-<port>.json`` (app/main.py,
# cli/service.py): the same prefix and port, another ending. A scan for
# notes (``*.json``) never meets it.
MARKER_PREFIX = ".dienst"
MARKER_SUFFIX = ".stop"
# How often the running service looks for the marker.
LOOK_SECONDS = 0.5


def marker_file(data_folder: Path, port: int) -> Path:
    """Where the request to end the service on ``port`` lies."""
    return data_folder / f"{MARKER_PREFIX}-{int(port)}{MARKER_SUFFIX}"


def clear(marker: Path) -> None:
    """Removes a marker that is left over from an earlier request."""
    marker.unlink(missing_ok=True)


def _end_like_a_signal() -> None:
    """Ends the process the way the window closing does: the termination
    signal's handler runs in-process (uvicorn's), which starts the ordinary
    shutdown. Raised, not sent: on Windows a sent one would not reach it."""
    signal.raise_signal(signal.SIGTERM)


async def watch(
    marker: Path,
    end: Callable[[], None] = _end_like_a_signal,
    interval: float = LOOK_SECONDS,
) -> None:
    """Looks for the marker until it is there; then removes it, says so and
    ends the service. Returns afterwards: one request is one ending."""
    while True:
        await asyncio.sleep(interval)
        if marker.exists():
            clear(marker)
            log.info("A request to end the service was found; shutting down")
            end()
            return
