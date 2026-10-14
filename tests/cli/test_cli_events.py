"""The listener on the service's own event stream: what each event turns
into, and what happens when the stream breaks."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from cli import events, glyphs
from cli.client import KEY_HEADER
from cli.interfaces import Context
from cli.texts import Texts
from tests.cli.stub_service import HEARTBEAT, StubService, eventually, model

Line = Callable[..., str]
Wire = Callable[[httpx.Client], Context]

STREAM = "GET /api/v1/events/stream"


def words(key: str, **placeholders: Any) -> str:
    return Texts("en").t(key, **placeholders)


def listen(ctx: Context, stub: StubService) -> None:
    """Starts the listener and waits until its stream stands."""
    ctx.events.start()
    eventually(lambda: stub.watchers == 1)


def mode_line(shown: str) -> str:
    """The second status line: the one that ends in the connection."""
    return shown.split("\n")[1]


def notices(ctx: Context) -> list[str]:
    lines: list[str] = ctx.renderer.notices  # type: ignore[attr-defined]
    return lines


def about(agent: str, said: str) -> str:
    """One line about a run, as the listener words it."""
    return f"{agent} {glyphs.glyph('separator')} {said}"


# --- The stream, against the stand-in service -----------------------------------


def test_on_arrival_the_client_asks_for_the_servers_word(
    ctx: Context, stub: StubService, status_line: Line
) -> None:
    stub.models[0]["server_state"] = "idle"
    # A server that is down has a word too: the ask covers the unreachable
    # models as well, and a model chosen on such a server says `offline`.
    stub.models.append({**model("down", "Down Model", server_state="offline"), "erreichbar": False})
    listen(ctx, stub)
    # No event said so: the stream only ever reports a change.
    eventually(lambda: words("kopf.bereit") in status_line(ctx))
    assert mode_line(status_line(ctx)).endswith(words("cli.connected"))
    ctx.session.endpoint_id = "down"
    assert words("kopf.server_aus") in status_line(ctx)


def test_a_change_of_the_servers_word_changes_the_status_line(
    ctx: Context, stub: StubService, status_line: Line
) -> None:
    stub.models[0]["server_state"] = "offline"
    listen(ctx, stub)
    eventually(lambda: words("kopf.server_aus") in status_line(ctx))

    stub.announce("server_state", endpoint_id="local", server_state="active")
    eventually(lambda: words("kopf.server_active") in status_line(ctx))

    stub.announce("server_state", endpoint_id="local", server_state="idle")
    eventually(lambda: words("kopf.bereit") in status_line(ctx))
    # The status line is where it shows, and only there.
    assert notices(ctx) == []


def test_the_word_of_another_model_is_not_the_one_in_use(
    ctx: Context, stub: StubService, status_line: Line
) -> None:
    stub.models[0]["server_state"] = "offline"
    listen(ctx, stub)
    eventually(lambda: words("kopf.server_aus") in status_line(ctx))
    stub.announce("server_state", endpoint_id="cloud", server_state="active")
    # The next event marks the point by which the first one was handled.
    stub.announce("termin_gefeuert", cronjob_id="cron-1")
    eventually(lambda: notices(ctx))
    assert words("kopf.server_aus") in status_line(ctx)
    # Kept all the same: a switch to that model shows its word at once.
    ctx.session.endpoint_id = "cloud"
    assert words("kopf.server_active") in status_line(ctx)


def test_the_list_keys_the_word_by_the_server_behind_each_model(
    ctx: Context, stub: StubService, status_line: Line
) -> None:
    """A catalogue lists many models on one server; the announcement names
    the server, and the model in use is traced back to it."""
    stub.models.append(model("cloud:gpt", "GPT", server_state="offline"))
    listen(ctx, stub)
    eventually(lambda: words("kopf.bereit") in status_line(ctx))
    ctx.session.endpoint_id = "cloud:gpt"
    assert words("kopf.server_aus") in status_line(ctx)
    stub.announce("server_state", endpoint_id="cloud", server_state="active")
    eventually(lambda: words("kopf.server_active") in status_line(ctx))


def test_a_word_the_line_cannot_show_is_left_out(ctx: Context, status_line: Line) -> None:
    """The silence probe: a word that is none of the three, or an
    announcement without a model, changes nothing."""
    before = status_line(ctx)
    ctx.events.handle({"typ": "server_state", "endpoint_id": "local", "server_state": "busy"})
    ctx.events.handle({"typ": "server_state", "server_state": "active"})
    assert status_line(ctx) == before
    ctx.events.handle({"typ": "server_state", "endpoint_id": "local", "server_state": "active"})
    assert words("kopf.server_active") in status_line(ctx)


def test_the_model_servers_own_announcement_writes_no_line(ctx: Context) -> None:
    """The runner's three flags still arrive; the terminal shows none of
    them, and writes nothing for them either."""
    ctx.events.handle({"typ": "modellserver_zustand", "runner": "chat", "laeuft": True})
    assert notices(ctx) == []


def test_a_schedule_that_fired_writes_one_quiet_line(ctx: Context, stub: StubService) -> None:
    listen(ctx, stub)
    stub.announce("termin_gefeuert", cronjob_id="cron-1")
    eventually(lambda: notices(ctx))
    assert notices(ctx) == [words("cronjobs.gestartet")]
    # Sentences of the catalogue, not a key left standing.
    assert words("cronjobs.gestartet") != "cronjobs.gestartet"


def test_the_heartbeat_writes_nothing(
    ctx: Context, stub: StubService, status_line: Line
) -> None:
    listen(ctx, stub)
    eventually(lambda: mode_line(status_line(ctx)).endswith(words("cli.connected")))
    before = status_line(ctx)
    for _ in range(3):
        stub.heartbeat()
    stub.announce("termin_gefeuert", cronjob_id="cron-1")
    eventually(lambda: notices(ctx))
    assert notices(ctx) == [words("cronjobs.gestartet")]
    assert ctx.screen.printed == []  # type: ignore[attr-defined]
    assert status_line(ctx) == before


def test_before_the_first_connection_the_line_says_disconnected(
    ctx: Context, status_line: Line
) -> None:
    assert mode_line(status_line(ctx)).endswith(words("cli.disconnected"))
    assert words("cli.disconnected") != words("cli.reconnecting")


def test_a_broken_stream_reads_as_reconnecting_until_it_stands_again(
    ctx: Context, stub: StubService, status_line: Line, quick_pauses: None
) -> None:
    stub.models[0]["server_state"] = "idle"
    listen(ctx, stub)
    eventually(lambda: words("kopf.bereit") in status_line(ctx))

    stub.events_refused = True
    stub.break_events()
    # Not disconnected: the service answered once, the stream is being
    # opened again.
    eventually(lambda: mode_line(status_line(ctx)).endswith(words("cli.reconnecting")))
    # What the stream said last is not known to hold any more.
    assert words("kopf.bereit") not in status_line(ctx)
    # The break itself is no line in the history; the status line says it.
    assert notices(ctx) == [] and ctx.renderer.errors == []  # type: ignore[attr-defined]

    stub.events_refused = False
    eventually(lambda: stub.watchers == 1)
    eventually(lambda: mode_line(status_line(ctx)).endswith(words("cli.connected")))
    assert words("kopf.bereit") in status_line(ctx)
    # And the next event arrives over the new connection.
    stub.announce("termin_gefeuert", cronjob_id="cron-1")
    eventually(lambda: notices(ctx))
    assert notices(ctx) == [words("cronjobs.gestartet")]


def test_after_a_restart_of_the_service_the_stream_stands_again_with_the_new_key(
    ctx: Context, stub: StubService, status_line: Line, quick_pauses: None
) -> None:
    listen(ctx, stub)
    # A service that starts again mints a new key and drops every stream.
    stub.key = stub.page_key = "the-key-after-the-restart"
    stub.break_events()
    eventually(lambda: stub.requests.count(STREAM) >= 2 and stub.watchers == 1)
    assert ctx.client.key == "the-key-after-the-restart"
    eventually(lambda: mode_line(status_line(ctx)).endswith(words("cli.connected")))


def test_a_stream_that_stays_silent_too_long_is_given_up_and_opened_again(
    ctx: Context, stub: StubService, quick_pauses: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(events, "READ_TIMEOUT_SECONDS", 0.1)
    listen(ctx, stub)
    # Not even a heartbeat arrives: the connection claims to stand and is dead.
    eventually(lambda: stub.requests.count(STREAM) >= 2)


def test_a_stream_kept_warm_by_heartbeats_is_not_given_up(
    ctx: Context, stub: StubService, quick_pauses: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(events, "READ_TIMEOUT_SECONDS", 1.0)
    listen(ctx, stub)
    # Longer than the timeout in all, with never that long between two signs.
    until = time.monotonic() + 1.5
    while time.monotonic() < until:
        stub.heartbeat()
        time.sleep(0.1)
    assert stub.requests.count(STREAM) == 1
    assert stub.watchers == 1


def test_the_stream_is_given_up_after_three_missed_heartbeats() -> None:
    assert events.HEARTBEAT_SECONDS == 20.0
    assert events.READ_TIMEOUT_SECONDS == 3 * events.HEARTBEAT_SECONDS == 60.0


def test_starting_twice_opens_one_stream(ctx: Context, stub: StubService) -> None:
    ctx.events.start()
    ctx.events.start()
    eventually(lambda: stub.watchers == 1)
    stub.announce("termin_gefeuert", cronjob_id="cron-1")
    eventually(lambda: notices(ctx))
    assert stub.requests.count(STREAM) == 1 and stub.watchers == 1
    assert notices(ctx) == [words("cronjobs.gestartet")]


def test_after_stopping_nothing_more_is_shown(
    ctx: Context, stub: StubService, status_line: Line
) -> None:
    listen(ctx, stub)
    eventually(lambda: mode_line(status_line(ctx)).endswith(words("cli.connected")))
    ctx.events.stop()
    before = status_line(ctx)
    stub.announce("termin_gefeuert", cronjob_id="cron-1")
    stub.announce("server_state", endpoint_id="local", server_state="active")
    stub.break_events()
    eventually(lambda: stub.watchers == 0)
    ctx.events.handle({"typ": "termin_gefeuert", "cronjob_id": "cron-2"})
    assert notices(ctx) == []
    assert status_line(ctx) == before


def test_an_event_that_cannot_be_shown_does_not_cost_the_connection(
    ctx: Context, stub: StubService, status_line: Line
) -> None:
    asked: list[str] = []

    def failing_once(text: str) -> None:
        asked.append(text)
        if len(asked) == 1:
            raise ValueError("cannot draw this")

    ctx.renderer.notice = failing_once  # type: ignore[method-assign]
    listen(ctx, stub)
    stub.announce("termin_gefeuert", cronjob_id="cron-1")
    stub.announce("termin_gefeuert", cronjob_id="cron-2")
    eventually(lambda: len(asked) == 2)
    # What went wrong stands where the line would have stood.
    assert ctx.renderer.errors == ["ValueError: cannot draw this"]  # type: ignore[attr-defined]
    assert stub.requests.count(STREAM) == 1 and stub.watchers == 1
    assert mode_line(status_line(ctx)).endswith(words("cli.connected"))


def test_stopping_a_listener_that_never_started_is_fine(ctx: Context) -> None:
    ctx.events.stop()
    ctx.events.stop()


# --- The requests themselves, against a stand-in that keeps them -----------------


class Kept:
    """Answers the addresses the listener asks and keeps every request."""

    KEY = "key-of-this-run"

    def __init__(self) -> None:
        self.seen: list[httpx.Request] = []
        # What each address answers with; a test replaces what it needs.
        self.models: Callable[[], httpx.Response] = lambda: httpx.Response(
            200, json=[{"id": "local", "server_state": "idle"}]
        )
        # Handed the request, so a stand-in stream can read what the client
        # asked for along with it.
        self.stream: Callable[[httpx.Request], httpx.Response] = lambda request: httpx.Response(
            200, text=f'data: {json.dumps({"typ": "termin_gefeuert", "cronjob_id": "c"})}\n\n'
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        path = request.url.path
        if path == "/app/":
            page = f'<script>window.__SITZUNGSSCHLUESSEL__="{self.KEY}";</script>'
            return httpx.Response(200, text=page)
        if path == "/api/v1/models":
            return self.models()
        if path == "/api/v1/events/stream":
            return self.stream(request)
        return httpx.Response(404, json={"detail": "No such address"})

    def asked(self, path: str) -> list[httpx.Request]:
        return [request for request in self.seen if request.url.path == path]


def test_the_key_travels_as_a_query_parameter_and_the_read_is_bounded(
    wire: Wire, quick_pauses: None
) -> None:
    service = Kept()
    ctx = wire(httpx.Client(transport=httpx.MockTransport(service)))
    ctx.events.start()
    eventually(lambda: service.asked("/api/v1/events/stream"))
    opened = service.asked("/api/v1/events/stream")[0]
    assert opened.method == "GET"
    assert opened.url.params["schluessel"] == Kept.KEY
    assert opened.headers[KEY_HEADER] == Kept.KEY
    assert opened.extensions["timeout"]["read"] == events.READ_TIMEOUT_SECONDS
    # The question on arrival went out first.
    paths = [request.url.path for request in service.seen]
    assert paths.index("/api/v1/models") < paths.index("/api/v1/events/stream")


def test_a_service_that_will_not_hand_out_its_models_is_still_listened_to(
    wire: Wire, status_line: Line, quick_pauses: None
) -> None:
    service = Kept()
    ctx = wire(httpx.Client(transport=httpx.MockTransport(service)))
    # The list the client read at its start was there; the one the listener
    # asks for on arrival is refused.
    service.models = lambda: httpx.Response(500, json={"detail": "No models here"})
    ctx.events.start()
    eventually(lambda: notices(ctx))
    assert notices(ctx)[0] == words("cronjobs.gestartet")
    # Nothing was said about any server, so nothing is claimed.
    shown = status_line(ctx)
    for key in ("kopf.server_active", "kopf.bereit", "kopf.server_aus"):
        assert words(key) not in shown
    assert ctx.renderer.errors == []  # type: ignore[attr-defined]


def test_a_service_that_is_gone_reads_as_disconnected_and_writes_no_line(
    wire: Wire, status_line: Line, quick_pauses: None
) -> None:
    service = Kept()

    def gone() -> httpx.Response:
        raise httpx.ConnectError("nothing answers")

    ctx = wire(httpx.Client(transport=httpx.MockTransport(service)))
    service.models = gone
    ctx.events.start()
    eventually(lambda: len(service.asked("/api/v1/models")) >= 3)
    assert service.asked("/api/v1/events/stream") == []
    # Never answered: not a connection being made again, none at all.
    assert mode_line(status_line(ctx)).endswith(words("cli.disconnected"))
    assert notices(ctx) == [] and ctx.renderer.errors == []  # type: ignore[attr-defined]


# --- How long a silent stream is read ---------------------------------------------


class SilentFor(httpx.SyncByteStream):
    """The body of an event stream that stays silent for ``seconds`` before
    its next sign of life — measured against the read the client allowed
    for, the way the transport measures real silence: longer than allowed,
    and the read ends in the timeout; within it, the sign of life arrives
    and the stream stands on until the test lets it go."""

    def __init__(
        self, seconds: float, request: httpx.Request, released: threading.Event
    ) -> None:
        self._seconds = seconds
        self._request = request
        self._released = released

    def __iter__(self) -> Iterator[bytes]:
        allowed = (self._request.extensions.get("timeout") or {}).get("read")
        if allowed is not None and self._seconds > allowed:
            raise httpx.ReadTimeout(f"silent for {self._seconds} s", request=self._request)
        yield HEARTBEAT.encode()
        self._released.wait()


@pytest.mark.parametrize("seconds", [50.0, 59.0])
def test_a_sign_of_life_within_sixty_seconds_keeps_the_stream(
    wire: Wire, status_line: Line, quick_pauses: None, seconds: float
) -> None:
    service = Kept()
    released = threading.Event()
    service.stream = lambda request: httpx.Response(
        200, stream=SilentFor(seconds, request, released)
    )
    ctx = wire(httpx.Client(transport=httpx.MockTransport(service)))
    try:
        ctx.events.start()
        eventually(lambda: service.asked("/api/v1/events/stream"))
        time.sleep(0.3)
        # Still the first stream, still connected.
        assert len(service.asked("/api/v1/events/stream")) == 1
        assert mode_line(status_line(ctx)).endswith(words("cli.connected"))
    finally:
        released.set()


def test_sixty_one_seconds_of_silence_end_the_stream_and_it_is_opened_again(
    wire: Wire, status_line: Line, quick_pauses: None
) -> None:
    service = Kept()
    released = threading.Event()
    service.stream = lambda request: httpx.Response(
        200, stream=SilentFor(61.0, request, released)
    )
    ctx = wire(httpx.Client(transport=httpx.MockTransport(service)))
    try:
        ctx.events.start()
        eventually(lambda: len(service.asked("/api/v1/events/stream")) >= 2)
    finally:
        released.set()


# --- How long the listener waits between two attempts ----------------------------


class Waits:
    """Stands in for the listener's own clock: keeps every wait it is asked
    for, waits for none of them, and says that the client is leaving after
    a set number of them."""

    def __init__(self, limit: int) -> None:
        self.asked: list[float] = []
        self._limit = limit

    def is_set(self) -> bool:
        return len(self.asked) >= self._limit

    def set(self) -> None:
        self._limit = 0

    def wait(self, seconds: float) -> bool:
        self.asked.append(seconds)
        return self.is_set()


def waits_of(ctx: Context, limit: int) -> list[float]:
    """Runs the listener in this thread until it has waited ``limit`` times
    and returns the waits it asked for."""
    waits = Waits(limit)
    listener = ctx.events
    listener._leaving = waits  # type: ignore[attr-defined]
    listener._listen()  # type: ignore[attr-defined]
    return waits.asked


def test_every_failed_attempt_doubles_the_wait_up_to_the_longest(wire: Wire) -> None:
    service = Kept()

    def gone() -> httpx.Response:
        raise httpx.ConnectError("nothing answers")

    ctx = wire(httpx.Client(transport=httpx.MockTransport(service)))
    service.models = gone
    assert waits_of(ctx, 8) == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]


def test_a_stream_that_is_refused_counts_as_a_failed_attempt(wire: Wire) -> None:
    service = Kept()
    service.stream = lambda request: httpx.Response(503, json={"detail": "Closed"})
    ctx = wire(httpx.Client(transport=httpx.MockTransport(service)))
    assert waits_of(ctx, 4) == [1.0, 2.0, 4.0, 8.0]


class Clock:
    """Stands in for the listener's clock: time passes only when a test
    says so."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


def test_after_a_stream_that_held_the_waits_start_over(
    wire: Wire, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    monkeypatch.setattr(events, "time", clock)
    service = Kept()
    attempts = 0

    def third_one_holds(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 3:
            # It stands for an hour before it ends.
            clock.now += 3600.0
            return httpx.Response(200, text=": still here\n\n")
        return httpx.Response(503, json={"detail": "Closed"})

    service.stream = third_one_holds
    ctx = wire(httpx.Client(transport=httpx.MockTransport(service)))
    assert waits_of(ctx, 5) == [1.0, 2.0, 1.0, 2.0, 4.0]


def test_a_stream_that_held_for_less_than_the_wait_before_it_is_a_failed_attempt(
    wire: Wire, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    monkeypatch.setattr(events, "time", clock)
    service = Kept()
    attempts = 0

    def third_one_holds_briefly(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 3:
            # Shorter than the four seconds waited before it.
            clock.now += 3.0
            return httpx.Response(200, text=": still here\n\n")
        return httpx.Response(503, json={"detail": "Closed"})

    service.stream = third_one_holds_briefly
    ctx = wire(httpx.Client(transport=httpx.MockTransport(service)))
    assert waits_of(ctx, 4) == [1.0, 2.0, 4.0, 8.0]


# --- What an event turns into ----------------------------------------------------


def test_a_run_that_began_is_named_with_its_agent(ctx: Context) -> None:
    ctx.events.handle({"typ": "auftrag_begonnen", "auftrag_id": "run-1", "agent": "Researcher"})
    assert notices(ctx) == [about("Researcher", words("jobs.zustand.laeuft"))]


def test_a_run_that_ended_says_how(ctx: Context) -> None:
    def ended(**fields: Any) -> str:
        notices(ctx).clear()
        ctx.events.handle({"typ": "auftrag_beendet", "agent": "Researcher", **fields})
        return notices(ctx)[0]

    assert ended(ausgang="fertig", grund="fertig") == about("Researcher", words("jobs.zustand.fertig"))
    assert ended(ausgang="fertig", grund=None) == about("Researcher", words("jobs.zustand.fertig"))
    # A reason beyond having finished is what gets said.
    assert ended(ausgang="gescheitert", grund="zeitgrenze") == about(
        "Researcher", words("jobs.grund.zeitgrenze")
    )
    assert ended(ausgang="abgebrochen", grund="benutzer_abbruch") == about(
        "Researcher", words("jobs.grund.benutzer_abbruch")
    )
    # A reason the catalogue has no sentence for is the message itself.
    assert ended(ausgang="gescheitert", grund="fehler: connection reset") == about(
        "Researcher", "fehler: connection reset"
    )


def test_a_run_that_ended_without_saying_how_writes_nothing(ctx: Context) -> None:
    ctx.events.handle({"typ": "auftrag_beendet", "auftrag_id": "run-1", "agent": "", "ausgang": ""})
    assert notices(ctx) == []


def test_a_run_without_an_agents_name_is_a_line_all_the_same(ctx: Context) -> None:
    ctx.events.handle({"typ": "auftrag_begonnen", "auftrag_id": "run-1", "agent": ""})
    assert notices(ctx) == [words("jobs.zustand.laeuft")]


def test_a_run_that_asks_without_a_name_is_not_worded_around_an_empty_one(ctx: Context) -> None:
    ctx.events.handle({"typ": "auftrag_fragt", "agent": "", "wartet": True})
    assert notices(ctx) == [words("jobs.zustand.wartet")]


def test_a_run_that_asks_and_one_that_was_answered(ctx: Context) -> None:
    ctx.events.handle({"typ": "auftrag_fragt", "agent": "Researcher", "wartet": True})
    ctx.events.handle({"typ": "auftrag_fragt", "agent": "Researcher", "wartet": False})
    assert notices(ctx) == [
        words("jobs.banner", agent="Researcher"),
        about("Researcher", words("jobs.zustand.laeuft")),
    ]
    assert "Researcher" in notices(ctx)[0] and notices(ctx)[0] != "jobs.banner"


def test_compression_is_named_for_the_open_chat_only(ctx: Context) -> None:
    ctx.session.chat = {"id": "chat-1"}
    ctx.events.handle({"typ": "verdichtung_laeuft", "chat_id": "chat-2"})
    assert notices(ctx) == []
    ctx.events.handle({"typ": "verdichtung_laeuft", "chat_id": "chat-1"})
    assert notices(ctx) == [words("status.komprimiert")]


@pytest.mark.parametrize(
    "event",
    [
        # The client's own answers reach it over their own stream already.
        {"typ": "antwort_begonnen", "chat_id": "chat-1", "generation_id": "run-1"},
        {"typ": "auftrag_kontext", "auftrag_id": "run-1"},
        {"typ": "exemd_zu_gross", "chat_id": "chat-1", "meldung": "Too large"},
        {"typ": "something_newer_than_this_client"},
        {"no": "type at all"},
    ],
)
def test_an_event_this_client_has_no_line_for_writes_nothing(
    ctx: Context, status_line: Line, event: dict[str, Any]
) -> None:
    ctx.session.chat = {"id": "chat-1"}
    before = status_line(ctx)
    ctx.events.handle(event)
    assert notices(ctx) == [] and ctx.renderer.errors == []  # type: ignore[attr-defined]
    assert status_line(ctx) == before


def test_a_model_reported_as_gone_is_marked_until_it_is_back(
    ctx: Context, status_line: Line
) -> None:
    ctx.status.update(model_name="Local Model")
    gone = f"Local Model {words('status.nicht_erreichbar')}"

    ctx.events.handle({"typ": "endpunkt_status", "endpoint_id": "local", "erreichbar": False})
    assert gone in status_line(ctx)
    # One of the two facts about the models, so no line in the history.
    assert notices(ctx) == []

    ctx.events.handle({"typ": "endpunkt_status", "endpoint_id": "elsewhere", "erreichbar": False})
    ctx.events.handle({"typ": "endpunkt_status", "endpoint_id": "local", "erreichbar": True})
    assert gone not in status_line(ctx) and "Local Model" in status_line(ctx)

    # An event that names no model changes nothing.
    ctx.events.handle({"typ": "endpunkt_status", "erreichbar": False})
    assert gone not in status_line(ctx)


def test_what_was_reported_as_gone_is_forgotten_when_the_stream_breaks(
    ctx: Context, stub: StubService, status_line: Line, quick_pauses: None
) -> None:
    ctx.status.update(model_name="Local Model")
    gone = f"Local Model {words('status.nicht_erreichbar')}"
    listen(ctx, stub)
    stub.announce("endpunkt_status", endpoint_id="local", erreichbar=False)
    eventually(lambda: gone in status_line(ctx))
    # Whether it came back while nobody listened, nobody can say.
    stub.break_events()
    eventually(lambda: stub.requests.count(STREAM) >= 2 and stub.watchers == 1)
    eventually(lambda: gone not in status_line(ctx))


def test_the_lines_come_in_the_language_in_use(ctx: Context) -> None:
    ctx.texts.set_language("de")
    ctx.events.handle({"typ": "auftrag_begonnen", "agent": "Researcher"})
    ctx.events.handle({"typ": "termin_gefeuert", "cronjob_id": "cron-1"})
    german = Texts("de")
    assert notices(ctx) == [
        about("Researcher", german.t("jobs.zustand.laeuft")),
        german.t("cronjobs.gestartet"),
    ]
    assert german.t("cronjobs.gestartet") != words("cronjobs.gestartet")
