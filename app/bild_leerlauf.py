"""The picture server's idle time, watched.

The sd-server has no switch to free its model after a while without work, so
the program does it: every few seconds it asks the stored idle time
(``app/bildgeraete.py``, minutes, empty is never) and ends the picture server
once it has drawn nothing for that long (``Bildturbo.im_leerlauf_stoppen``).
The next picture starts it again, the way it starts after any other start
value changed. The setting is read at every look, so a changed time counts
at once and a server that was never started costs a read of one setting.
"""

from __future__ import annotations

import asyncio
import logging

from app import bildgeraete

log = logging.getLogger(__name__)

# How often the stored time is looked at against the clock of the server.
INTERVALL_S = 15.0


def pruefen(app, jetzt: float | None = None) -> bool:
    """One look: ends the picture server when its idle time has passed.
    True when it was ended. Blocking — it reads a setting and may end a
    process — so the loop runs it off the event loop."""
    minuten = bildgeraete.lesen(app.state.repositories).idle_minutes
    if not minuten:
        return False
    return app.state.bildturbo.im_leerlauf_stoppen(minuten, jetzt)


async def watch(app, intervall: float = INTERVALL_S) -> None:
    """Looks every ``intervall`` seconds until cancelled. A failed look is
    logged and the next one goes on."""
    while True:
        await asyncio.sleep(intervall)
        try:
            await asyncio.to_thread(pruefen, app)
        except Exception:  # noqa: BLE001 — one failed look must not end the watch
            log.exception("Picture server idle check failed")
