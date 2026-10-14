"""The status line says "connected" once the event stream is open — not
when the service has merely answered a question. A service that answers
and refuses the stream is one the client is still trying to reach."""

from __future__ import annotations

import threading
from typing import Any

import httpx
import pytest

from cli.client import ServiceClient, ServiceError
from cli.interfaces import Context
from cli.status import CONNECTED, RECONNECTING
from tests.cli.stub_service import StubService, eventually

STREAM = "GET /api/v1/events/stream"
MODELS = "GET /api/v1/models"


def connections(ctx: Context) -> list[Any]:
    """Keeps every word for the connection the status line is given from
    here on, in the order it was given."""
    given: list[Any] = []
    update = ctx.screen.update_status

    def keep(**fields: Any) -> None:
        if "connection" in fields:
            given.append(fields["connection"])
        update(**fields)

    ctx.screen.update_status = keep  # type: ignore[method-assign]
    return given


def test_a_service_that_refuses_the_stream_is_never_said_to_be_connected(
    ctx: Context, stub: StubService, quick_pauses: None
) -> None:
    given = connections(ctx)
    stub.events_refused = True

    ctx.events.start()
    # Attempt after attempt: the question about the models is answered
    # every time, the stream is refused every time.
    eventually(lambda: stub.requests.count(STREAM) >= 4)
    ctx.events.stop()

    assert stub.requests.count(MODELS) >= 4
    assert CONNECTED not in given
    # The service did answer: this is a connection being made again.
    assert given and set(given) == {RECONNECTING}


def test_the_word_for_the_server_is_not_shown_before_the_stream_stands(
    ctx: Context, stub: StubService, quick_pauses: None
) -> None:
    shown: list[dict[str, Any]] = []
    update = ctx.screen.update_status

    def keep(**fields: Any) -> None:
        shown.append(fields)
        update(**fields)

    ctx.screen.update_status = keep  # type: ignore[method-assign]
    stub.models[0]["server_state"] = "active"
    stub.events_refused = True

    ctx.events.start()
    eventually(lambda: stub.requests.count(STREAM) >= 3)
    ctx.events.stop()

    # What the model list said is only shown with a stream that stands.
    assert all(not fields.get("server_states") for fields in shown)


def test_an_open_stream_is_said_to_be_connected_with_what_the_service_said(
    ctx: Context, stub: StubService
) -> None:
    shown: list[dict[str, Any]] = []
    update = ctx.screen.update_status

    def keep(**fields: Any) -> None:
        # How many streams stood open the moment the line was told.
        shown.append({**fields, "open": stub.requests.count(STREAM)})
        update(**fields)

    ctx.screen.update_status = keep  # type: ignore[method-assign]
    stub.models[0]["server_state"] = "active"

    ctx.events.start()
    eventually(lambda: stub.watchers == 1 and shown)
    ctx.events.stop()

    assert shown[0]["connection"] == CONNECTED
    assert shown[0]["server_states"] == {"local": "active"}
    # Told after the stream was asked for and answered, not before.
    assert shown[0]["open"] == 1


# --- The client's door -------------------------------------------------------------


def test_a_stream_says_that_it_is_open_before_its_first_event(
    ctx: Context, stub: StubService
) -> None:
    client: ServiceClient = ctx.client
    happened: list[str] = []
    events = client.stream(
        "/events/stream",
        method="GET",
        params={"schluessel": client.key},
        opened=lambda: happened.append("open"),
    )
    # Asking for the stream opens nothing yet; reading it does.
    assert happened == []
    try:
        reader = iter(events)
        first: list[Any] = []
        thread = threading.Thread(target=lambda: first.append(next(reader)), daemon=True)
        thread.start()
        eventually(lambda: stub.watchers == 1)
        eventually(lambda: happened == ["open"])
        assert first == []
        stub.announce("termin_gefeuert", cronjob_id="cron-1")
        thread.join(10)
        assert first and first[0]["typ"] == "termin_gefeuert"
        assert happened == ["open"]
    finally:
        client.hang_up()


def test_a_stream_the_service_refuses_never_says_that_it_is_open(
    ctx: Context, stub: StubService
) -> None:
    stub.events_refused = True
    happened: list[str] = []

    with pytest.raises(ServiceError) as refused:
        list(
            ctx.client.stream(
                "/events/stream",
                method="GET",
                params={"schluessel": ctx.client.key},
                opened=lambda: happened.append("open"),
            )
        )

    assert refused.value.status == 503
    assert happened == []


def test_a_stream_read_again_after_a_new_key_says_once_that_it_is_open() -> None:
    key = {"now": "first"}

    def service(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/app/":
            page = f'<script>window.__SITZUNGSSCHLUESSEL__="{key["now"]}";</script>'
            return httpx.Response(200, text=page)
        if request.headers.get("X-Sitzungsschluessel") != key["now"]:
            return httpx.Response(401, json={"detail": "Invalid or missing session key"})
        return httpx.Response(200, text='data: {"typ": "done"}\n\n')

    client = ServiceClient(
        "http://service.test", "en", http=httpx.Client(transport=httpx.MockTransport(service))
    )
    client.connect()
    key["now"] = "second"
    happened: list[str] = []

    assert list(client.stream("/x", opened=lambda: happened.append("open"))) == [{"typ": "done"}]
    assert happened == ["open"]
