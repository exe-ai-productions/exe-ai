"""The server behind a model, in one of three words.

``active`` while an answer is being written on it, ``idle`` while it is
reachable and nothing runs there, ``offline`` while it is not reachable.
Two readouts show the word for the model in use — the first status line of
the terminal client and the footer of the window — and both used to show
the service's own llama-server instead: "inactive" under a cloud model that
was answering at that very moment.

Computed once, here, from two facts the service already holds: the answers
running right now (app/generationen.py) and what the discovery knows about
reachability (app/discovery.py). Told, not asked: the word travels with
every entry of the model list, and whenever it may have changed for one
endpoint — an answer starts or ends there, its reachability turns — the
service announces that endpoint's new word on the bus, and the live line
carries it to every client (app/ereignisstrom.py).

The three words are the wire itself: the clients show them as they are,
in both languages.
"""

from __future__ import annotations

from typing import Any

from app.events import Ereignisse, bus

ACTIVE = "active"
IDLE = "idle"
OFFLINE = "offline"


def word(*, running: bool, reachable: bool) -> str:
    """The word for a server that is writing an answer (``running``) or
    not, and that answers the discovery (``reachable``) or not. An answer
    in flight outranks a reachability that turned meanwhile: the stream is
    still coming from somewhere."""
    if running:
        return ACTIVE
    return IDLE if reachable else OFFLINE


def of(endpoint_id: str, *, discovery: Any, generierungen: Any) -> str:
    """The word for one endpoint, from the two registries."""
    known = discovery.zustaende.get(endpoint_id)
    return word(
        running=endpoint_id in generierungen.active_endpoints(),
        reachable=bool(known is not None and known.erreichbar),
    )


def subscribe(app: Any) -> None:
    """Hooks the announcer onto the bus for this app: whenever one
    endpoint's word may have changed, its new word is published as
    ``SERVER_STATE``. Called once at startup, after both registries exist
    on ``app.state``."""

    async def announce(endpoint_id: str) -> None:
        if not endpoint_id:
            return
        await bus.veroeffentlichen(
            Ereignisse.SERVER_STATE,
            endpoint_id=endpoint_id,
            server_state=of(
                endpoint_id,
                discovery=app.state.discovery,
                generierungen=app.state.generierungen,
            ),
        )

    async def answer_started(generation_id: str = "", **_rest: Any) -> None:
        # The start names the run, not its server: the run knows.
        run = app.state.generierungen.holen(generation_id)
        if run is not None:
            await announce(run.endpoint_id)

    async def answer_ended(endpoint_id: str = "", **_rest: Any) -> None:
        await announce(endpoint_id)

    async def reachability_changed(endpoint_id: str = "", **_rest: Any) -> None:
        await announce(endpoint_id)

    bus.abonnieren(Ereignisse.ANTWORT_BEGONNEN, answer_started)
    bus.abonnieren(Ereignisse.ANTWORT_FERTIG, answer_ended)
    bus.abonnieren(Ereignisse.ANTWORT_ABGEBROCHEN, answer_ended)
    bus.abonnieren(Ereignisse.ENDPUNKT_STATUS_GEAENDERT, reachability_changed)
