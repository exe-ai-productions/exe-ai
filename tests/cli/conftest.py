"""What the tests of the terminal client share: the stand-in service, a way
to reach it without a port, and a client's parts wired to it without a
terminal."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from prompt_toolkit.utils import get_cwidth
from rich.console import RenderableType

from cli import events, outside, status
from cli.client import ServiceClient
from cli.interfaces import Context, Renderer, Screen
from cli.texts import Texts
from tests.cli.program import Gated
from tests.cli.stub_service import StubService

STUB_ADDRESS = "http://stub.test"


class RecordingScreen(Screen):
    """Takes what the modules hand to the screen and keeps it. Nothing is
    drawn."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx
        self.printed: list[RenderableType] = []
        self.redraws = 0

    def print_above(self, *renderables: RenderableType) -> None:
        self.printed.extend(renderables)

    def invalidate(self) -> None:
        self.redraws += 1

    def update_status(self, **fields: Any) -> None:
        self._ctx.status.update(**fields)
        self.redraws += 1


class RecordingRenderer(Renderer):
    """Keeps the client's own lines instead of writing them."""

    def __init__(self) -> None:
        self.notices: list[str] = []
        self.errors: list[str] = []

    def notice(self, text: str) -> None:
        self.notices.append(text)

    def error(self, text: str) -> None:
        self.errors.append(text)


@pytest.fixture(autouse=True)
def a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """The chat only starts at a terminal. A test drives it through a pipe
    and a screen of its own, which stands in for one; a test about the
    absence of a terminal says so itself."""
    monkeypatch.setattr(outside, "has_terminal", lambda: True)


@pytest.fixture
def stub() -> Iterator[StubService]:
    """The stand-in service. Closing it ends every stream still open."""
    service = StubService()
    yield service
    service.close()


@pytest.fixture
def gated() -> Iterator[Gated]:
    """A stand-in service whose answers run until the test opens the gate."""
    service = Gated()
    yield service
    service.close()


@pytest.fixture
def stub_http(stub: StubService) -> Iterator[httpx.Client]:
    """An HTTP client whose every request ends in the stand-in."""
    with stub.http() as http:
        yield http


@pytest.fixture
def wire() -> Iterator[Callable[[httpx.Client], Context]]:
    """Wires a client's parts to whatever answers behind ``http``, the way
    ``cli/main.py`` does — with the real status line and the real listener,
    and a screen and a renderer that only keep what they are handed. Every
    listener is stopped when the test is over."""
    wired: list[Context] = []

    def build(http: httpx.Client) -> Context:
        client = ServiceClient(STUB_ADDRESS, "en", http=http)
        client.connect()
        context = Context(client=client, texts=Texts("en"))
        context.session.models = client.get("/models")
        if context.session.models:
            context.session.endpoint_id = context.session.models[0]["id"]
        context.status = status.build_status(context)
        context.renderer = RecordingRenderer()
        context.screen = RecordingScreen(context)
        context.events = events.build_events(context)
        wired.append(context)
        return context

    yield build
    for context in wired:
        context.events.stop()


@pytest.fixture
def ctx(wire: Callable[[httpx.Client], Context], stub_http: httpx.Client) -> Context:
    """A client's parts wired to the stand-in service."""
    return wire(stub_http)


@pytest.fixture
def status_line() -> Callable[..., str]:
    """Reads the status lines as the terminal shows them: plain text, one
    line below the other, with the promise checked that no line takes more
    than the width it was given."""

    def read(context: Context, width: int = 120) -> str:
        text = "".join(piece for _, piece in context.status.fragments(width))
        for line in text.split("\n"):
            assert get_cwidth(line) <= width
        return text

    return read


@pytest.fixture
def quick_pauses(monkeypatch: pytest.MonkeyPatch) -> None:
    """The waits between two connection attempts, cut down so a test of
    reconnecting takes no seconds. Their proportions stay."""
    monkeypatch.setattr(events, "FIRST_PAUSE_SECONDS", 0.01)
    monkeypatch.setattr(events, "LONGEST_PAUSE_SECONDS", 0.3)
