"""One answer as it streams in: every event reaches whoever shows it, in
the order the service sent it, and the interrupt key stops the answer."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Iterator
from html import unescape
from pathlib import Path
from typing import Any

import httpx
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.markdown import Markdown

from cli import chat, events, glyphs, render, themes
from cli.client import KEY_HEADER, ServiceClient
from cli.interfaces import Asker, Context, Renderer, Screen
from cli.main import main
from cli.texts import Texts
from stub_service import foreground, noted, process_by_name

KEY = "key-of-this-run"
PAGE = f'<html><head><script>window.__SITZUNGSSCHLUESSEL__="{KEY}";</script></head></html>'
ENTER = "\r"
INTERRUPT = "\x03"

# How long a step of a test may wait for another thread before it gives up,
# and after how long a run that never leaves is cut off. Both only bound a
# failure; a passing test waits for neither.
WAIT_SECONDS = 10
SAFETY_NET_SECONDS = 30

# One step of a scripted answer: an event to send, or something to do at
# that point of the stream.
Step = dict[str, Any] | Callable[[], None]


def line(event: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode()


class Played(httpx.SyncByteStream):
    """A scripted answer as a response body. ``close`` is called the moment
    the client lets go of the stream — a plain iterator would only notice
    that whenever it happens to be collected."""

    def __init__(self, script: list[Step], closed: Callable[[], None]) -> None:
        self._script = script
        self._closed = closed

    def __iter__(self) -> Iterator[bytes]:
        for step in self._script:
            if callable(step):
                step()
            else:
                yield line(step)

    def close(self) -> None:
        self._closed()


class Service:
    """A stand-in for the service that plays scripted answers.

    ``answers`` holds one script per message it will be sent, in order.
    Every request is kept; ``stopped`` is set when a stop arrives.
    """

    def __init__(
        self,
        answers: list[list[Step]] | None = None,
        *,
        chats: list[dict[str, Any]] | None = None,
        messages: dict[str, list[dict[str, Any]]] | None = None,
        totals: dict[str, int] | None = None,
    ) -> None:
        self.answers = list(answers or [])
        self.chats = {chat["id"]: dict(chat) for chat in chats or []}
        self.messages = messages or {}
        self.totals = totals or {}
        self.models = [
            {"id": "local", "name": "Local Model", "erreichbar": True, "context_tokens": 8192},
            {"id": "other", "name": "Other Model", "erreichbar": True, "context_tokens": 4096},
        ]
        self.seen: list[httpx.Request] = []
        self.stopped = threading.Event()
        # What a stream left unsent when it broke, for whoever attaches again.
        self.rest: list[dict[str, Any]] = []
        self.when_all_answers_are_over: Callable[[], None] | None = None
        # What the stand-in says of its process, by the name it is asked
        # under. A test puts another answer here.
        self.process: Callable[[str], dict[str, Any] | None] = process_by_name

    def paths(self) -> list[str]:
        return [
            f"{request.method} {request.url.path}"
            for request in self.seen
            if foreground(request)
        ]

    def bodies(self, path: str) -> list[dict[str, Any]]:
        return [json.loads(request.content) for request in self.seen if request.url.path == path]

    def _play(self, script: list[Step]) -> Played:
        return Played(script, self._an_answer_is_over)

    def _an_answer_is_over(self) -> None:
        if not self.answers and self.when_all_answers_are_over is not None:
            self.when_all_answers_are_over()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(noted(request))
        path = request.url.path
        if path == "/app/":
            return httpx.Response(200, text=PAGE)
        if request.headers.get(KEY_HEADER) != KEY:
            return httpx.Response(401, json={"detail": "Invalid or missing session key"})
        path = path.removeprefix("/api/v1")
        if path == "/health":
            said = {"status": "ok", "version": "9.8.7", "process": self.process(request.url.host)}
            return httpx.Response(200, json=said)
        if path == "/models":
            return httpx.Response(200, json=self.models)
        if path == "/chats" and request.method == "POST":
            created = {"id": "chat-1", "title": "A fresh chat", **json.loads(request.content)}
            self.chats[created["id"]] = created
            return httpx.Response(201, json=created)
        if path == "/chats":
            return httpx.Response(200, json=list(self.chats.values()))
        if path.startswith("/chats/") and path.endswith("/messages"):
            chat_id = path.split("/")[2]
            page = self.messages.get(chat_id, [])
            total = self.totals.get(chat_id, len(page))
            return httpx.Response(
                200, json={"nachrichten": page}, headers={"X-Nachrichten-Gesamt": str(total)}
            )
        if path.startswith("/chats/"):
            chat_id = path.split("/")[2]
            if chat_id not in self.chats:
                return httpx.Response(404, json={"detail": "Chat not found"})
            if request.method == "PATCH":
                self.chats[chat_id].update(json.loads(request.content))
            return httpx.Response(200, json=self.chats[chat_id])
        if path == "/chat/completions":
            return httpx.Response(200, stream=self._play(self.answers.pop(0)))
        if path.startswith("/chat/stream/"):
            return httpx.Response(200, stream=self._play(list(self.rest)))
        if path == "/chat/stop":
            self.stopped.set()
            return httpx.Response(200, json={"abgebrochen": 1})
        if path == "/chat/confirm":
            return httpx.Response(200, json={"zugestellt": True})
        return httpx.Response(404, json={"detail": "No such address"})


class Shown(Screen):
    """A screen that only keeps what it is handed."""

    def __init__(self) -> None:
        self.printed: list[Any] = []
        self.activity: list[Any] = []
        self.status: dict[str, Any] = {}

    def print_above(self, *renderables: Any) -> None:
        self.printed.extend(renderables)

    def set_activity(self, text: Any) -> None:
        self.activity.append(text() if callable(text) else text)

    def update_status(self, **fields: Any) -> None:
        self.status.update(fields)


class Declining(Asker):
    """An asker that never shows a question: a tool is refused, the model's
    own question gets no answer."""


class Calls(Renderer):
    """A renderer that only writes down which of its methods were called."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def __getattribute__(self, name: str) -> Any:
        if name.startswith("_") or name == "calls" or name not in vars(Renderer):
            return super().__getattribute__(name)
        return lambda value=None, *more: self.calls.append((name, value))


def test_the_first_message_names_a_fresh_chat_and_later_ones_leave_the_name():
    service = Service([ANSWER, ANSWER])
    ctx = context(service, renderer=Calls())
    chat.new_chat(ctx)
    chat.send(ctx, "Name three colours,\nas a list, and take your time with it please.")
    chat.send(ctx, "And three animals.")
    renamed = [
        json.loads(request.content) for request in service.seen if request.method == "PATCH"
    ]
    # Only the first line names the chat.
    assert renamed == [{"title": "Name three colours,"}]
    assert ctx.screen.status["chat_title"] == "Name three colours,"


def test_a_chat_that_was_opened_keeps_its_name():
    service = Service([ANSWER], chats=[{"id": "c9", "title": "An old chat", "endpoint_id": "local"}])
    ctx = context(service, renderer=Calls())
    chat.open_chat(ctx, service.chats["c9"])
    chat.send(ctx, "Go on.")
    assert not any(request.method == "PATCH" for request in service.seen)


def context(
    service: Service, *, renderer: Renderer | None = None, prefs_path: Path | None = None
) -> Context:
    """Everything a round needs, without a screen that runs. Without a
    renderer handed in, the client's own is built — then ``prefs_path`` names
    the file it may read its choices from."""
    client = ServiceClient(
        "http://service.test", "en", http=httpx.Client(transport=httpx.MockTransport(service))
    )
    client.connect()
    ctx = Context(client=client, texts=Texts("en"), prefs_path=prefs_path)
    ctx.screen = Shown()
    ctx.asker = Declining()
    ctx.renderer = renderer or render.build_renderer(ctx)
    ctx.session.models = service.models
    ctx.session.endpoint_id = "local"
    ctx.session.chat = {"id": "chat-1", "title": "A fresh chat"}
    return ctx


def run(
    typed: str,
    *arguments: str,
    service: Service,
    tmp_path: Path,
    during: Callable[[Any], None] | None = None,
) -> int:
    """Starts the whole client with ``typed`` waiting in its input.
    ``during`` is handed the input once, before the client starts, for
    whatever a script wants to type later. After the last scripted answer
    the client is told to leave."""
    with create_pipe_input() as pipe:
        pipe.send_text(typed)
        if during is not None:
            during(pipe)
        if service.when_all_answers_are_over is None and service.answers:
            service.when_all_answers_are_over = lambda: pipe.send_text("/quit" + ENTER)
        safety_net = threading.Timer(SAFETY_NET_SECONDS, pipe.close)
        safety_net.start()
        try:
            with create_app_session(input=pipe, output=DummyOutput()):
                return main(
                    ["--url", "http://service.test", "--lang", "en", *arguments],
                    http=httpx.Client(transport=httpx.MockTransport(service)),
                    prefs_path=tmp_path / "cli.json",
                )
        finally:
            safety_net.cancel()
            themes.set_look(themes.DEFAULT_LOOK)


def shown_text(html: str) -> str:
    """The plain text of an exported page: what the history showed, line
    by line, without the page's markup."""
    start = html.index(">", html.index("<code")) + 1
    return unescape(re.sub(r"<[^>]+>", "", html[start : html.index("</code>", start)]))


def recorded(typed: str, *arguments: str, service: Service, tmp_path: Path, **more: Any) -> str:
    """The same, and afterwards the plain text of everything shown — read
    back from an export of the history, written once the client has left."""
    parts: list[Context] = []
    built = events.build_events

    def remember(ctx: Context) -> Any:
        parts.append(ctx)
        return built(ctx)

    events.build_events = remember
    try:
        assert run(typed, *arguments, service=service, tmp_path=tmp_path, **more) == 0
    finally:
        events.build_events = built
    target = tmp_path / "shown.html"
    parts[0].screen.export(target)
    return shown_text(target.read_text(encoding="utf-8"))


def where(lines: list[str], text: str, after: int = -1) -> int:
    """The number of the first line behind ``after`` that says ``text``.
    Asked this way, a test holds whatever stands around the text — a mark in
    front of it, an indent, a frame."""
    for number, line in enumerate(lines):
        if number > after and text in line:
            return number
    raise AssertionError(f"no line behind {after} says {text!r}")


def typed_line(text: str) -> str:
    """A line as the input field shows it."""
    return f"{glyphs.glyph('prompt')} {text}"


ANSWER: list[Step] = [
    {"typ": "start", "generation_id": "g1", "message_id": "m1", "chat_id": "chat-1"},
    {"typ": "content", "text": "Three "},
    {"typ": "content", "text": "colours:\n\n"},
    {"typ": "content", "text": "- red\n- green\n"},
    {"typ": "reasoning", "text": "Let me look."},
    {"typ": "tool_call", "name": "list_files", "server": "files", "argumente": {"path": "."}, "aufruf_id": "a1"},
    {"typ": "tool_result", "name": "list_files", "aufruf_id": "a1", "fehlgeschlagen": False, "text": "a.txt", "dauer_sekunden": 0.2},
    {"typ": "kontext", "message_id": "m1", "gesamt_tokens": 1234},
    {"typ": "stats", "daten": {"dauer_sekunden": 3.0, "tokens_pro_sekunde": 20.5}},
    {"typ": "done", "message_id": "m1", "abgebrochen": False},
]


def test_every_event_reaches_the_renderer_in_the_order_it_was_sent():
    service = Service([ANSWER])
    calls = Calls()
    ctx = context(service, renderer=calls)

    chat.send(ctx, "Name three colours.")

    assert [name for name, _ in calls.calls] == [
        "user_message",
        "start",
        "content",
        "content",
        "content",
        "reasoning",
        "tool_call",
        "tool_result",
        "stats",
        "done",
    ]
    assert calls.calls[0] == ("user_message", "Name three colours.")
    assert [value for name, value in calls.calls if name == "content"] == [
        "Three ",
        "colours:\n\n",
        "- red\n- green\n",
    ]
    assert calls.calls[6][1]["name"] == "list_files"
    assert calls.calls[8] == ("stats", {"dauer_sekunden": 3.0, "tokens_pro_sekunde": 20.5})
    # The context number goes to the status line, not into the history.
    assert ctx.screen.status["context_tokens"] == 1234


def test_the_message_goes_out_with_the_chat_the_model_and_no_answer_limit():
    service = Service([ANSWER])
    ctx = context(service, renderer=Calls())
    chat.send(ctx, "Name three colours.")
    assert service.bodies("/api/v1/chat/completions") == [
        {"chat_id": "chat-1", "content": "Name three colours.", "endpoint_id": "local"}
    ]


def test_a_chosen_thinking_stage_travels_with_the_message_and_none_is_not_sent():
    service = Service([ANSWER, ANSWER])
    ctx = context(service, renderer=Calls())
    chat.send(ctx, "one")
    ctx.session.thinking = "high"
    chat.send(ctx, "two")
    first, second = service.bodies("/api/v1/chat/completions")
    assert "thinking" not in first
    assert second["thinking"] == "high"


def test_a_paragraph_is_written_as_markdown_once_it_is_over_and_a_code_block_after_its_end(tmp_path):
    seen_at: dict[str, int] = {}
    service = Service()
    ctx = context(service, prefs_path=tmp_path / "cli.json")
    shown = ctx.screen.printed

    def mark(name: str) -> Callable[[], None]:
        return lambda: seen_at.__setitem__(name, sum(isinstance(item, Markdown) for item in shown))

    service.answers.append(
        [
            {"typ": "start", "generation_id": "g1"},
            {"typ": "content", "text": "A first paragraph"},
            mark("paragraph still open"),
            {"typ": "content", "text": ".\n\n```python\nprint(1)\n"},
            mark("paragraph over, code block open"),
            {"typ": "content", "text": "\nprint(2)\n```\n"},
            mark("code block over"),
            {"typ": "content", "text": "A last line without its end"},
            mark("last line still open"),
            {"typ": "done"},
        ]
    )
    chat.send(ctx, "Show me code.")

    assert seen_at == {
        "paragraph still open": 0,
        "paragraph over, code block open": 1,
        "code block over": 2,
        "last line still open": 2,
    }
    blocks = [item.markup for item in shown if isinstance(item, Markdown)]
    assert blocks == [
        "A first paragraph.\n",
        "```python\nprint(1)\n\nprint(2)\n```\n",
        "A last line without its end",
    ]


def test_the_line_above_the_status_line_says_what_goes_on_and_is_empty_afterwards():
    service = Service([ANSWER])
    ctx = context(service, renderer=Calls())
    chat.send(ctx, "Name three colours.")
    words = Texts("en")
    said = ctx.screen.activity
    assert said[0] == words.t("status.erzeugt_antwort")
    assert any(isinstance(text, str) and text.startswith(words.t("nachricht.gedankengang")) for text in said)
    assert any(isinstance(text, str) and "list_files" in text for text in said)
    assert said[-1] is None
    assert ctx.session.answering is False and ctx.session.generation_id is None


def test_the_interrupt_key_during_an_answer_stops_it_and_does_not_leave(tmp_path):
    service = Service()
    typing: dict[str, Any] = {}

    def interrupt_and_wait_for_the_stop() -> None:
        typing["pipe"].send_text(INTERRUPT)
        assert service.stopped.wait(WAIT_SECONDS)

    service.answers.append(
        [
            {"typ": "start", "generation_id": "g1"},
            {"typ": "content", "text": "A long answer begins"},
            interrupt_and_wait_for_the_stop,
            {"typ": "done", "abgebrochen": True, "zustand": "abgebrochen"},
        ]
    )
    shown = recorded(
        "Tell me everything." + ENTER,
        service=service,
        tmp_path=tmp_path,
        during=lambda pipe: typing.__setitem__("pipe", pipe),
    )

    assert service.bodies("/api/v1/chat/stop") == [{"chat_id": "chat-1"}]
    lines = [text.strip() for text in shown.splitlines()]
    # What had arrived is written, the stop is said below it, and the client
    # went on to take the command that left it.
    arrived = where(lines, "A long answer begins")
    stopped = where(lines, Texts("en").t("nachricht.abgebrochen_kurz"), after=arrived)
    assert where(lines, typed_line("/quit"), after=stopped)


def test_the_interrupt_key_without_an_answer_sends_no_stop(tmp_path):
    service = Service()
    assert run(INTERRUPT, service=service, tmp_path=tmp_path) == 0
    assert service.bodies("/api/v1/chat/stop") == []
