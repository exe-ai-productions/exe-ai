"""The llama.cpp servers that run when a new build of the program is fetched
start again on that build.

One program serves every server this program starts, and a server takes the
program at its start. A build fetched while servers run would reach them only
at their next start, so the window would name a build the servers do not run.
Here the servers that run at that moment are stopped and, once the new build is
the one that starts, started again with the values they ran with. A server
that did not run stays off.

The sequence is the downloader's (``app/serverdownload.py``):

    stop()   — remember what runs, end it
    ...        the new build becomes the one that starts
    start()  — start what was remembered, wait until each model is loaded

and, when ``start()`` says no, the same two calls once more around the old
build. ``forget()`` ends the sequence.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.modellrunner import Lauf, Modellrunner, RunnerFehler

log = logging.getLogger(__name__)

# How often a server that was started is asked whether its model is loaded.
POLL_S = 0.5
# How long a registration with the model list may take.
ANNOUNCE_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class Member:
    """One server the program may hold, and what its start tells the rest of
    the program — ``announce`` is called with the run that came up."""

    name: str
    runner: Modellrunner
    announce: Callable[[Lauf], None] | None = None


def _start_values(lauf: Lauf) -> dict:
    """What the run was started with, in the words ``Modellrunner.starten``
    takes."""
    return {
        "kontext": lauf.kontext,
        "schichten": lauf.schichten,
        "port": lauf.port,
        "drafter": lauf.drafter,
        "vision": lauf.vision,
        "fein": lauf.fein,
        "faeden": lauf.faeden,
        "sampling": lauf.sampling,
    }


def _loaded(runner: Modellrunner) -> bool:
    """Waits until the model is loaded. A server whose process ends first
    failed to start; there is no time limit, a load takes as long as the model
    is large, and ending the process by hand ends the wait."""
    while True:
        if runner.bereit():
            return True
        if not runner.laeuft():
            return False
        time.sleep(POLL_S)


class Restart:
    """The servers of one program, stopped and started again around a change
    of the program's build."""

    def __init__(self, members: list[Member]) -> None:
        self._members = members
        self._running: list[tuple[Member, Lauf]] | None = None

    def stop(self) -> None:
        """Remembers the servers that run now and ends them. Called a second
        time it ends what runs of the same servers again and remembers
        nothing new — the servers of the first call are the ones to bring
        back."""
        if self._running is None:
            self._running = [
                (member, lauf)
                for member in self._members
                if (lauf := member.runner.lauf()) is not None
            ]
        for member, _ in self._running:
            member.runner.stoppen()

    def start(self) -> bool:
        """Starts the remembered servers with the values they ran with and
        waits until every model is loaded. False when one did not start or
        ended while loading; the others are left as they are."""
        if not self._running:
            return True
        started: list[tuple[Member, Lauf]] = []
        for member, lauf in self._running:
            try:
                new = member.runner.starten(lauf.modell, **_start_values(lauf))
            except RunnerFehler as fehler:
                log.warning("%s could not be started again: %s", member.name, fehler)
                return False
            started.append((member, new or lauf))
        for member, _ in started:
            if not _loaded(member.runner):
                log.warning("%s ended while loading", member.name)
                return False
        for member, lauf in started:
            if member.announce is None:
                continue
            try:
                member.announce(lauf)
            except Exception:  # noqa: BLE001 - a registration must not undo a restart
                log.warning("%s could not be announced again", member.name, exc_info=True)
        return True

    def forget(self) -> None:
        self._running = None


def announcer(
    loop: asyncio.AbstractEventLoop, coroutine_for: Callable[[Lauf], Awaitable[Any]]
) -> Callable[[Lauf], None]:
    """A registration written as a coroutine, run on the service's loop from
    the thread the restart runs in."""

    def announce(lauf: Lauf) -> None:
        async def run() -> None:
            await coroutine_for(lauf)

        asyncio.run_coroutine_threadsafe(run(), loop).result(timeout=ANNOUNCE_TIMEOUT_S)

    return announce


def members_of(app, loop: asyncio.AbstractEventLoop) -> list[Member]:
    """The five servers the service holds, each with the registration its
    own start makes (the model server and the agent model join the model
    list; the embedding, speech and clean-up servers do not)."""
    from app.agentenserver import endpunkt_bauen
    from app.api.v1.runner import _runner_endpunkt

    def chat(lauf: Lauf):
        return app.state.discovery.anmelden(_runner_endpunkt(lauf.port))

    def agent(lauf: Lauf):
        return app.state.discovery.anmelden(endpunkt_bauen(lauf.port))

    state = app.state
    return [
        Member("model server", state.modellrunner, announcer(loop, chat)),
        Member("agent model server", state.agentenrunner, announcer(loop, agent)),
        Member("embedding server", state.einbettungsrunner),
        Member("speech server", state.sprachrunner),
        Member("clean-up server", state.sprachputzrunner),
    ]
