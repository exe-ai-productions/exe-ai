"""The model server's state, announced instead of asked for.

Three readouts show it — is the server up, did flash attention end up on,
did the drafter really engage — and every one of them used to ask on a beat
of its own for an answer that changes about twice a day. Measured before
this: 29 fetches of ``/runner`` in the first 120 seconds of an idle window.

That was not the readouts' fault. There was nothing to listen to, so this
builds it: the runner reports a change (``zustand_callback``,
app/modellrunner.py), it goes onto the bus, and the live line carries it to
every open window (app/ereignisstrom.py).

WHICH RUNNER IS PART OF THE MESSAGE. Five servers share the runner class,
and the announcement says which of them it is about. Not because five of
them speak today — only the chat server does — but because the answer to
"can the next one use this?" has to be yes without a second event, a second
forwarder and a second store. A listener that cares about one server reads
the name; one that cares about all of them keeps them apart.

Getting the announcement from the reader thread back onto the service's
loop is NOT this module's business, and used to be: it belongs to the bus,
where every other worker thread in the program publishes from
(``veroeffentlichen_ohne_warten``, app/events.py). Fixed there, this is a
name and a call.
"""

from __future__ import annotations

from typing import Callable

from app.events import Ereignisse, bus

# The chat model server — the one the header and the input bar report on.
CHAT = "chat"


def melder(runner: str) -> Callable[[bool, bool | None, str | None], None]:
    """Builds the callback a model runner reports its state through.

    ``runner`` names the server this callback speaks for and travels with
    every announcement; use ``CHAT`` for the main model server.
    """

    def melden(
        laeuft: bool, flash_aktiv: bool | None, mtp_aktiv: str | None
    ) -> None:
        bus.veroeffentlichen_ohne_warten(
            Ereignisse.MODELLSERVER_ZUSTAND,
            runner=runner,
            laeuft=laeuft,
            flash_aktiv=flash_aktiv,
            mtp_aktiv=mtp_aktiv,
        )

    return melden
