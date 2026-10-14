"""The server behind a model, in one of three words (app/server_state.py):
how the word is formed, when the service announces it, and that the model
list carries it."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import server_state
from app.events import Ereignisse, bus
from app.generationen import Generierungsverwaltung

ENDPOINT = "cloud-1"


# --- The word ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("running", "reachable", "expected"),
    [
        (True, True, "active"),
        (True, False, "active"),
        (False, True, "idle"),
        (False, False, "offline"),
    ],
)
def test_the_word_follows_running_before_reachable(running, reachable, expected):
    """An answer in flight outranks a reachability that turned meanwhile."""
    assert server_state.word(running=running, reachable=reachable) == expected


def test_the_word_of_an_endpoint_the_discovery_does_not_know_is_offline():
    app = _app()
    assert server_state.of(ENDPOINT, discovery=app.state.discovery, generierungen=app.state.generierungen) == "offline"


def test_the_word_of_a_reachable_quiet_endpoint_is_idle():
    app = _app(reachable={ENDPOINT: True})
    assert server_state.of(ENDPOINT, discovery=app.state.discovery, generierungen=app.state.generierungen) == "idle"


def test_the_word_of_an_endpoint_writing_an_answer_is_active():
    app = _app(reachable={ENDPOINT: True})
    app.state.generierungen.anmelden(chat_id="chat-1", endpoint_id=ENDPOINT)
    assert server_state.of(ENDPOINT, discovery=app.state.discovery, generierungen=app.state.generierungen) == "active"


# --- The announcement ----------------------------------------------------------


def _app(reachable: dict[str, bool] | None = None):
    """An app with the two registries the announcer reads: the discovery's
    states, reduced to what the word needs, and a real generation registry."""
    states = {
        endpoint: SimpleNamespace(erreichbar=flag) for endpoint, flag in (reachable or {}).items()
    }
    return SimpleNamespace(
        state=SimpleNamespace(
            discovery=SimpleNamespace(zustaende=states),
            generierungen=Generierungsverwaltung(),
        )
    )


def _heard() -> list[dict]:
    heard: list[dict] = []

    async def take(**fields):
        heard.append(fields)

    bus.abonnieren(Ereignisse.SERVER_STATE, take)
    return heard


async def test_an_answer_that_starts_makes_its_server_active():
    app = _app(reachable={ENDPOINT: True})
    server_state.subscribe(app)
    heard = _heard()
    run = app.state.generierungen.anmelden(chat_id="chat-1", endpoint_id=ENDPOINT)

    await bus.veroeffentlichen(
        Ereignisse.ANTWORT_BEGONNEN, chat_id="chat-1", generation_id=run.id, message_id="m1"
    )

    assert heard == [{"endpoint_id": ENDPOINT, "server_state": "active"}]


async def test_an_answer_that_ends_leaves_its_server_idle():
    app = _app(reachable={ENDPOINT: True})
    server_state.subscribe(app)
    heard = _heard()
    run = app.state.generierungen.anmelden(chat_id="chat-1", endpoint_id=ENDPOINT)
    app.state.generierungen.abmelden(run.id)

    await bus.veroeffentlichen(
        Ereignisse.ANTWORT_FERTIG, chat_id="chat-1", message_id="m1", endpoint_id=ENDPOINT
    )

    assert heard == [{"endpoint_id": ENDPOINT, "server_state": "idle"}]


async def test_an_answer_that_was_cancelled_ends_the_same_way():
    app = _app(reachable={ENDPOINT: True})
    server_state.subscribe(app)
    heard = _heard()

    await bus.veroeffentlichen(
        Ereignisse.ANTWORT_ABGEBROCHEN, chat_id="chat-1", message_id="m1", endpoint_id=ENDPOINT
    )

    assert heard == [{"endpoint_id": ENDPOINT, "server_state": "idle"}]


async def test_a_server_still_writing_another_chats_answer_stays_active():
    """Two chats on one server: the end of one answer does not make the
    server idle while the other is still being written."""
    app = _app(reachable={ENDPOINT: True})
    server_state.subscribe(app)
    heard = _heard()
    app.state.generierungen.anmelden(chat_id="chat-2", endpoint_id=ENDPOINT)

    await bus.veroeffentlichen(
        Ereignisse.ANTWORT_FERTIG, chat_id="chat-1", message_id="m1", endpoint_id=ENDPOINT
    )

    assert heard == [{"endpoint_id": ENDPOINT, "server_state": "active"}]


async def test_a_reachability_that_turns_announces_the_new_word():
    app = _app(reachable={ENDPOINT: False})
    server_state.subscribe(app)
    heard = _heard()

    await bus.veroeffentlichen(
        Ereignisse.ENDPUNKT_STATUS_GEAENDERT, endpoint_id=ENDPOINT, erreichbar=False
    )
    app.state.discovery.zustaende[ENDPOINT].erreichbar = True
    await bus.veroeffentlichen(
        Ereignisse.ENDPUNKT_STATUS_GEAENDERT, endpoint_id=ENDPOINT, erreichbar=True
    )

    assert heard == [
        {"endpoint_id": ENDPOINT, "server_state": "offline"},
        {"endpoint_id": ENDPOINT, "server_state": "idle"},
    ]


async def test_a_start_of_a_run_nobody_registered_announces_nothing():
    """The silence probe: a start that names no run of ours has no server
    to speak of, and an empty endpoint is no endpoint."""
    app = _app(reachable={ENDPOINT: True})
    server_state.subscribe(app)
    heard = _heard()

    await bus.veroeffentlichen(
        Ereignisse.ANTWORT_BEGONNEN, chat_id="chat-1", generation_id="unknown", message_id="m1"
    )
    await bus.veroeffentlichen(Ereignisse.ANTWORT_FERTIG, chat_id="chat-1", endpoint_id="")

    assert heard == []


# --- The list ------------------------------------------------------------------


def test_every_entry_of_the_model_list_carries_the_word(client):
    """Carried with the list so a client has the word before the first
    announcement. The test service's endpoints answer nothing, so every
    word is `offline` — and every one is one of the three."""
    entries = client.get("/api/v1/models", params={"alle": "true"}).json()
    assert entries, "the test configuration lists no endpoint"
    assert {entry["server_state"] for entry in entries} <= {"active", "idle", "offline"}
    assert all(entry["server_state"] == "offline" for entry in entries if not entry["erreichbar"])
