"""A round of the chat beyond the plain case: a second message waits its
turn, a command does not, an error is shown as one, a broken stream is
picked up again, and a question of the service gets its answer. And what
holds around a round: a new chat reaches the service with the first thing
written into it and works in the folder the client was started in, a chat
without messages counts none, and the size of the context follows the
service."""

from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from cli import chat, events, glyphs, shell, themes
from cli.client import ServiceClient, ServiceUnreachable
from cli.interfaces import Asker, CommandSet, Context
from cli.texts import Texts
from test_stream import (
    ENTER,
    WAIT_SECONDS,
    Calls,
    Service,
    Step,
    context,
    recorded,
    run,
    shown_text,
    typed_line,
    where,
)

from tests.cli.program import Run, run_client
from tests.cli.stub_service import StubService, eventually, this_process

START: Step = {"typ": "start", "generation_id": "g1", "message_id": "m1"}
DONE: Step = {"typ": "done", "message_id": "m1", "abgebrochen": False}


def test_a_second_message_during_an_answer_goes_out_after_it_and_is_not_dropped(tmp_path):
    service = Service()
    typing: dict[str, Any] = {}

    def type_the_second_message() -> None:
        typing["pipe"].send_text("And a second one." + ENTER)

    service.answers.append(
        [START, type_the_second_message, {"typ": "content", "text": "First answer.\n"}, DONE]
    )
    service.answers.append([START, {"typ": "content", "text": "Second answer.\n"}, DONE])
    shown = recorded(
        "A first one." + ENTER,
        service=service,
        tmp_path=tmp_path,
        during=lambda pipe: typing.__setitem__("pipe", pipe),
    )

    sent = [body["content"] for body in service.bodies("/api/v1/chat/completions")]
    assert sent == ["A first one.", "And a second one."]
    lines = shown.splitlines()
    assert where(lines, "First answer.") < where(lines, "Second answer.")


STOPPED: Step = {"typ": "done", "message_id": "m1", "abgebrochen": True}
A_CALL: Step = {
    "typ": "tool_call", "name": "web_search", "server": "", "argumente": {}, "aufruf_id": "a1",
}
ITS_RESULT: Step = {
    "typ": "tool_result", "name": "web_search", "aufruf_id": "a1", "fehlgeschlagen": False,
    "text": "found", "dauer_sekunden": 0.1,
}


def _parts_of_the_run(parts: list[Context]) -> Callable[[Context], Any]:
    """A replacement for the client's event builder that keeps the context
    the run was built with: a script reads the screen from inside the stream."""
    built = events.build_events

    def remember(ctx: Context) -> Any:
        parts.append(ctx)
        return built(ctx)

    return remember


def _the_run_with_a_message_typed_meanwhile(
    tmp_path: Path, service: Service, typing: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> str:
    """Runs the client on "A first one." with the pipe handed to the script
    and returns what the history showed, read back from an export."""
    parts: list[Context] = typing.setdefault("parts", [])
    monkeypatch.setattr(events, "build_events", _parts_of_the_run(parts))
    assert (
        run(
            "A first one." + ENTER,
            service=service,
            tmp_path=tmp_path,
            during=lambda pipe: typing.__setitem__("pipe", pipe),
        )
        == 0
    )
    target = tmp_path / "shown.html"
    parts[0].screen.export(target)
    return shown_text(target.read_text(encoding="utf-8"))


def test_a_message_during_an_answer_stops_it_and_goes_out_at_once(tmp_path, monkeypatch):
    service = Service()
    typing: dict[str, Any] = {}

    def type_the_second_message_and_wait_for_the_stop() -> None:
        typing["pipe"].send_text("And a second one." + ENTER)
        typing["stopped"] = service.stopped.wait(WAIT_SECONDS)

    service.answers.append(
        [
            START,
            {"typ": "content", "text": "Half an answer.\n"},
            type_the_second_message_and_wait_for_the_stop,
            STOPPED,
        ]
    )
    service.answers.append([START, {"typ": "content", "text": "Second answer.\n"}, DONE])
    shown = _the_run_with_a_message_typed_meanwhile(tmp_path, service, typing, monkeypatch)

    # Without the fix the message only waited: no stop ever came.
    assert typing["stopped"] is True
    sent = [body["content"] for body in service.bodies("/api/v1/chat/completions")]
    assert sent == ["A first one.", "And a second one."]
    paths = service.paths()
    stop = paths.index("POST /api/v1/chat/stop")
    assert stop < len(paths) - 1 - paths[::-1].index("POST /api/v1/chat/completions")
    lines = shown.splitlines()
    # What had come of the first answer stays, and the second one stands below it.
    first = where(lines, "Half an answer.")
    second = where(lines, typed_line("And a second one."), after=first)
    assert second < where(lines, "Second answer.")


def test_a_message_during_a_tool_waits_in_the_hint_line_and_goes_after_its_result(
    tmp_path, monkeypatch
):
    service = Service()
    typing: dict[str, Any] = {}

    def type_the_message_while_the_tool_runs() -> None:
        typing["pipe"].send_text("Wait for it." + ENTER)
        screen = typing["parts"][0].screen
        deadline = time.monotonic() + WAIT_SECONDS
        while "Wait for it." not in screen.hint_line() and time.monotonic() < deadline:
            time.sleep(0.02)
        typing["hint"] = screen.hint_line()
        # The tool is not cut off: no stop comes while it runs.
        typing["stopped_early"] = service.stopped.wait(0.5)

    def wait_for_the_stop_after_the_result() -> None:
        typing["stopped_late"] = service.stopped.wait(WAIT_SECONDS)

    service.answers.append(
        [
            START,
            A_CALL,
            type_the_message_while_the_tool_runs,
            ITS_RESULT,
            wait_for_the_stop_after_the_result,
            STOPPED,
        ]
    )
    service.answers.append([START, {"typ": "content", "text": "Second answer.\n"}, DONE])
    _the_run_with_a_message_typed_meanwhile(tmp_path, service, typing, monkeypatch)

    assert glyphs.glyph("waiting") + " Wait for it." in typing["hint"]
    assert typing["stopped_early"] is False
    assert typing["stopped_late"] is True
    sent = [body["content"] for body in service.bodies("/api/v1/chat/completions")]
    assert sent == ["A first one.", "Wait for it."]


def test_the_answer_is_not_stopped_while_a_second_tool_still_runs(tmp_path, monkeypatch):
    service = Service()
    typing: dict[str, Any] = {}
    second_call: Step = {**A_CALL, "aufruf_id": "a2"}
    first_result: Step = dict(ITS_RESULT)
    second_result: Step = {**ITS_RESULT, "aufruf_id": "a2"}

    def type_the_message() -> None:
        typing["pipe"].send_text("Wait for it." + ENTER)
        screen = typing["parts"][0].screen
        deadline = time.monotonic() + WAIT_SECONDS
        while "Wait for it." not in screen.hint_line() and time.monotonic() < deadline:
            time.sleep(0.02)

    def look_for_a_stop_between_the_results() -> None:
        typing["stopped_between"] = service.stopped.wait(0.5)

    def wait_for_the_stop() -> None:
        typing["stopped_after"] = service.stopped.wait(WAIT_SECONDS)

    service.answers.append(
        [
            START,
            A_CALL,
            second_call,
            type_the_message,
            first_result,
            look_for_a_stop_between_the_results,
            second_result,
            wait_for_the_stop,
            STOPPED,
        ]
    )
    service.answers.append([START, DONE])
    _the_run_with_a_message_typed_meanwhile(tmp_path, service, typing, monkeypatch)

    # The result of one of two calls leaves the other one running.
    assert typing["stopped_between"] is False
    assert typing["stopped_after"] is True


def test_two_waiting_messages_ask_for_one_stop_and_go_out_in_order(tmp_path, monkeypatch):
    service = Service()
    typing: dict[str, Any] = {}

    def type_two_messages_and_wait_for_the_stop() -> None:
        typing["pipe"].send_text("One." + ENTER)
        typing["pipe"].send_text("Two." + ENTER)
        screen = typing["parts"][0].screen
        deadline = time.monotonic() + WAIT_SECONDS
        while "Two." not in screen.hint_line() and time.monotonic() < deadline:
            time.sleep(0.02)
        typing["stopped"] = service.stopped.wait(WAIT_SECONDS)

    service.answers.append(
        [START, {"typ": "content", "text": "Half.\n"}, type_two_messages_and_wait_for_the_stop, STOPPED]
    )
    service.answers.append([START, {"typ": "content", "text": "To one.\n"}, DONE])
    service.answers.append([START, {"typ": "content", "text": "To two.\n"}, DONE])
    _the_run_with_a_message_typed_meanwhile(tmp_path, service, typing, monkeypatch)

    assert typing["stopped"] is True
    sent = [body["content"] for body in service.bodies("/api/v1/chat/completions")]
    assert sent == ["A first one.", "One.", "Two."]
    # One stop for the answer they waited behind; the answer to the first of
    # them is not cut short for the second.
    assert service.paths().count("POST /api/v1/chat/stop") == 1


def test_the_interrupt_key_takes_the_waiting_messages_back_instead_of_sending_them(
    tmp_path, monkeypatch
):
    service = Service()
    typing: dict[str, Any] = {}

    def type_the_message_and_interrupt() -> None:
        typing["pipe"].send_text("Wait for it." + ENTER)
        screen = typing["parts"][0].screen
        deadline = time.monotonic() + WAIT_SECONDS
        while "Wait for it." not in screen.hint_line() and time.monotonic() < deadline:
            time.sleep(0.02)
        typing["pipe"].send_text("\x03")
        typing["stopped"] = service.stopped.wait(WAIT_SECONDS)
        deadline = time.monotonic() + WAIT_SECONDS
        while not screen._input.text and time.monotonic() < deadline:
            time.sleep(0.02)
        typing["field"] = screen._input.text
        screen._input.buffer.reset()

    service.answers.append([START, A_CALL, type_the_message_and_interrupt, ITS_RESULT, STOPPED])
    _the_run_with_a_message_typed_meanwhile(tmp_path, service, typing, monkeypatch)

    assert typing["stopped"] is True
    assert typing["field"] == "Wait for it."
    # The stop ended the answer, and the message was not sent into it.
    assert [body["content"] for body in service.bodies("/api/v1/chat/completions")] == ["A first one."]


def test_escape_takes_a_waiting_message_back_into_the_field(tmp_path, monkeypatch):
    service = Service()
    typing: dict[str, Any] = {}

    def type_the_message_and_take_it_back() -> None:
        typing["pipe"].send_text("Wait for it." + ENTER)
        parts = typing["parts"]
        screen = parts[0].screen
        deadline = time.monotonic() + WAIT_SECONDS
        while "Wait for it." not in screen.hint_line() and time.monotonic() < deadline:
            time.sleep(0.02)
        typing["pipe"].send_text("\x1b")
        deadline = time.monotonic() + WAIT_SECONDS
        while "Wait for it." in screen.hint_line() and time.monotonic() < deadline:
            time.sleep(0.02)
        typing["field"] = screen._input.text
        typing["hint_after"] = screen.hint_line()
        # The field is emptied again: the run ends by typing a command into it.
        screen._input.buffer.reset()

    service.answers.append(
        [START, A_CALL, type_the_message_and_take_it_back, ITS_RESULT, {"typ": "content", "text": "Done.\n"}, DONE]
    )
    _the_run_with_a_message_typed_meanwhile(tmp_path, service, typing, monkeypatch)

    assert typing["field"] == "Wait for it."
    assert "Wait for it." not in typing["hint_after"]
    # Nothing was stopped and nothing was sent but the first message.
    assert not service.stopped.is_set()
    assert [body["content"] for body in service.bodies("/api/v1/chat/completions")] == ["A first one."]


class TwoCommands(CommandSet):
    """A command set of two: one leaves, any other says that it ran."""

    SAID = "the command ran"

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx
        self.ran = threading.Event()

    def run(self, line: str) -> None:
        if line == "/quit":
            self._ctx.screen.exit()
            return
        self._ctx.renderer.remark(self.SAID)
        self.ran.set()


def test_a_command_during_an_answer_runs_at_once_and_never_reaches_the_model(tmp_path, monkeypatch):
    service = Service()
    typing: dict[str, Any] = {}
    built: list[TwoCommands] = []

    def build(ctx: Context) -> TwoCommands:
        built.append(TwoCommands(ctx))
        return built[0]

    monkeypatch.setattr("cli.commands.build_commands", build)

    def type_a_command_and_wait_for_it() -> None:
        typing["pipe"].send_text("/anything" + ENTER)
        assert built[0].ran.wait(WAIT_SECONDS)

    service.answers.append(
        [START, type_a_command_and_wait_for_it, {"typ": "content", "text": "The answer.\n"}, DONE]
    )
    shown = recorded(
        "A question." + ENTER,
        service=service,
        tmp_path=tmp_path,
        during=lambda pipe: typing.__setitem__("pipe", pipe),
    )

    lines = shown.splitlines()
    # What the command said stands before the answer it was typed during.
    assert where(lines, TwoCommands.SAID) < where(lines, "The answer.")
    assert [body["content"] for body in service.bodies("/api/v1/chat/completions")] == ["A question."]


@pytest.mark.skipif(sys.platform == "win32", reason="the shell of the test is a POSIX one")
def test_a_shell_line_during_an_answer_runs_at_once_and_never_reaches_the_model(tmp_path, monkeypatch):
    service = Service()
    typing: dict[str, Any] = {}
    ran = threading.Event()
    original = shell.Shell.run

    def run_and_tell(runner: shell.Shell, ctx: Context, line: str) -> int:
        code = original(runner, ctx, line)
        ran.set()
        return code

    monkeypatch.setattr(shell.Shell, "run", run_and_tell)

    def type_a_shell_line_and_wait_for_it() -> None:
        typing["pipe"].send_text("!echo during the answer" + ENTER)
        assert ran.wait(WAIT_SECONDS)

    service.answers.append(
        [START, type_a_shell_line_and_wait_for_it, {"typ": "content", "text": "The answer.\n"}, DONE]
    )
    shown = recorded(
        "A question." + ENTER,
        service=service,
        tmp_path=tmp_path,
        during=lambda pipe: typing.__setitem__("pipe", pipe),
    )

    lines = shown.splitlines()
    # What the command printed stands before the answer it was typed during.
    assert where(lines, "during the answer") < where(lines, "The answer.")
    assert [body["content"] for body in service.bodies("/api/v1/chat/completions")] == ["A question."]


def test_a_command_creates_no_request_for_an_answer(tmp_path):
    service = Service()
    assert run("/help" + ENTER + "/quit" + ENTER, service=service, tmp_path=tmp_path) == 0
    assert service.bodies("/api/v1/chat/completions") == []


def test_an_error_event_reaches_the_renderer_as_an_error():
    service = Service([[START, {"typ": "error", "text": "The model went away"}, {"typ": "stats", "daten": {}}, DONE]])
    calls = Calls()
    chat.send(context(service, renderer=calls), "Hello")
    assert ("error", "The model went away") in calls.calls
    assert [name for name, _ in calls.calls][-2:] == ["stats", "done"]


def test_a_refused_message_is_raised_with_the_services_sentence_and_the_round_is_over():
    class NoModel(Service):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/chat/completions"):
                self.seen.append(request)
                return httpx.Response(400, json={"detail": "No model reachable"})
            return super().__call__(request)

    ctx = context(NoModel(), renderer=Calls())
    try:
        chat.send(ctx, "Hello")
    except Exception as error:  # noqa: BLE001
        assert str(error) == "No model reachable"
    else:
        raise AssertionError("the refusal was swallowed")
    assert ctx.session.answering is False
    assert ctx.screen.activity[-1] is None


def test_a_stream_that_breaks_off_is_attached_to_again_where_it_stopped():
    def break_off() -> None:
        raise httpx.ReadError("the connection dropped")

    service = Service(
        [[START, {"typ": "content", "text": "Before the break. "}, break_off]]
    )
    service.rest = [{"typ": "content", "text": "After it.\n"}, DONE]
    calls = Calls()
    chat.send(context(service, renderer=calls), "Hello")

    attached = next(request for request in service.seen if "/chat/stream/" in request.url.path)
    assert attached.method == "GET"
    assert attached.url.path == "/api/v1/chat/stream/g1"
    # Two events had arrived, so reading goes on from the third.
    assert attached.url.query == b"ab=2"
    assert [value for name, value in calls.calls if name == "content"] == [
        "Before the break. ",
        "After it.\n",
    ]
    assert calls.calls[-1][0] == "done"
    assert not any(name == "error" for name, _ in calls.calls)


def test_a_stream_that_ends_without_its_last_event_and_brings_nothing_more_is_said_so():
    service = Service([[START, {"typ": "content", "text": "Half an ans"}]])
    service.rest = []
    calls = Calls()
    ctx = context(service, renderer=calls)
    chat.send(ctx, "Hello")
    assert ("error", Texts("en").t("fehler.strom_abriss")) in calls.calls
    # The round is closed all the same: what had arrived is written out.
    assert calls.calls[-1][0] == "done"
    assert len([request for request in service.seen if "/chat/stream/" in request.url.path]) == 1


def test_a_message_the_service_was_not_there_for_is_raised_as_that_and_not_as_a_broken_answer():
    def break_off() -> None:
        raise httpx.ReadError("the connection dropped")

    service = Service([[break_off]])
    calls = Calls()
    ctx = context(service, renderer=calls)
    try:
        chat.send(ctx, "Hello")
    except ServiceUnreachable as error:
        assert error.address == "http://service.test"
    else:
        raise AssertionError("an answer that never began was not reported")
    # No answer began, so there is none to attach to and none to close.
    assert [name for name, _ in calls.calls] == ["user_message"]
    assert not any("/chat/stream/" in request.url.path for request in service.seen)
    assert ctx.session.answering is False


def test_a_broken_stream_the_service_no_longer_hands_out_is_closed_with_its_sentence():
    class Forgotten(Service):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if "/chat/stream/" in request.url.path:
                self.seen.append(request)
                return httpx.Response(404, json={"detail": "No such run"})
            return super().__call__(request)

    service = Forgotten([[START, {"typ": "content", "text": "Half an ans"}]])
    calls = Calls()
    chat.send(context(service, renderer=calls), "Hello")
    # The refusal is shown, and the round is closed all the same: what had
    # arrived of the answer is written out.
    assert [name for name, _ in calls.calls][-2:] == ["error", "done"]
    assert ("error", "No such run") in calls.calls


def test_a_refused_first_message_names_nothing_and_the_next_one_still_does():
    class NoModelAtFirst(Service):
        refused = False

        def __call__(self, request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/chat/completions") and not self.refused:
                self.refused = True
                self.seen.append(request)
                return httpx.Response(400, json={"detail": "No model reachable"})
            return super().__call__(request)

    service = NoModelAtFirst([[START, DONE]])
    ctx = context(service, renderer=Calls())
    chat.new_chat(ctx)
    try:
        chat.send(ctx, "A first try")
    except Exception:  # noqa: BLE001
        pass
    assert not any(request.method == "PATCH" for request in service.seen)
    chat.send(ctx, "A second try")
    assert ctx.screen.status["chat_title"] == "A second try"


def _wait_for(condition: Any) -> bool:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return bool(condition())


CONFIRM: Step = {
    "typ": "tool_confirm",
    "name": "write_file",
    "argumente": {"path": "note.txt"},
    "grund": "It writes outside the shared folder",
    "aufruf_id": "a1",
}


def test_what_an_asker_declines_is_sent_to_the_service_as_declined():
    service = Service()

    def wait_for_the_answer() -> None:
        assert _wait_for(lambda: service.bodies("/api/v1/chat/confirm"))

    service.answers.append([START, CONFIRM, wait_for_the_answer, DONE])
    chat.send(context(service, renderer=Calls()), "Write a note.")
    assert service.bodies("/api/v1/chat/confirm") == [
        {
            "generation_id": "g1",
            "aufruf_id": "a1",
            "erlaubt": False,
            "dauerhaft": False,
            "name": "write_file",
        }
    ]


def test_only_the_result_of_the_call_in_question_withdraws_the_question():
    class Watched(Asker):
        """Leaves every question open until it is withdrawn."""

        def __init__(self) -> None:
            self.asked = threading.Event()
            self.withdrawn = threading.Event()

        def confirm_tool(self, event: Any) -> dict[str, Any] | None:
            self.asked.set()
            self.withdrawn.wait(WAIT_SECONDS)
            return None

        def cancel(self) -> None:
            self.withdrawn.set()

    asker = Watched()
    standing: dict[str, bool] = {}

    def result(call: str) -> Step:
        return {"typ": "tool_result", "name": "x", "aufruf_id": call, "fehlgeschlagen": False, "text": ""}

    def note(name: str) -> Any:
        return lambda: standing.__setitem__(name, not asker.withdrawn.is_set())

    service = Service(
        [
            [
                START,
                CONFIRM,
                lambda: asker.asked.wait(WAIT_SECONDS),
                result("another-call"),
                note("after another call's result"),
                result("a1"),
                note("after its own call's result"),
                DONE,
            ]
        ]
    )
    ctx = context(service, renderer=Calls())
    ctx.asker = asker
    chat.send(ctx, "Write a note.")
    assert standing == {"after another call's result": True, "after its own call's result": False}


def test_an_askers_answer_is_sent_and_an_open_question_is_withdrawn_at_the_end():
    class Patient(Asker):
        """Allows a tool for good; leaves a question of the model open
        until it is withdrawn."""

        def __init__(self) -> None:
            self.withdrawn = threading.Event()

        def confirm_tool(self, event: Any) -> dict[str, Any] | None:
            return {"erlaubt": True, "dauerhaft": True}

        def ask_user(self, event: Any) -> dict[str, Any] | None:
            self.withdrawn.wait(WAIT_SECONDS)
            return None

        def cancel(self) -> None:
            self.withdrawn.set()

    service = Service()

    def wait_for_the_answer() -> None:
        assert _wait_for(lambda: service.bodies("/api/v1/chat/confirm"))

    question: Step = {"typ": "user_ask", "frage": "Which one?", "optionen": ["a", "b"], "aufruf_id": "a2"}
    service.answers.append([START, CONFIRM, wait_for_the_answer, question, DONE])
    ctx = context(service, renderer=Calls())
    asker = Patient()
    ctx.asker = asker
    chat.send(ctx, "Write a note.")

    assert service.bodies("/api/v1/chat/confirm") == [
        {
            "generation_id": "g1",
            "aufruf_id": "a1",
            "erlaubt": True,
            "dauerhaft": True,
            "name": "write_file",
        }
    ]
    # The model's question got no answer; the end of the round withdrew it.
    assert asker.withdrawn.is_set()


# --- A new chat and the service ---------------------------------------------------


def test_a_new_chat_is_the_clients_alone_until_something_is_written_into_it():
    service = Service([[START, DONE]])
    ctx = context(service, renderer=Calls())

    chat.new_chat(ctx)

    assert ctx.session.chat is None and ctx.session.chat_id() is None
    assert ctx.screen.status["chat_title"] == Texts("en").t("chat.unbenannt")
    assert "POST /api/v1/chats" not in service.paths()

    chat.send(ctx, "Hello")

    assert service.bodies("/api/v1/chats") == [{"endpoint_id": "local"}]
    assert ctx.session.chat_id() == "chat-1"


def test_asked_for_twice_the_chat_is_created_once():
    service = Service()
    ctx = context(service, renderer=Calls())
    chat.new_chat(ctx)

    first = chat.service_chat(ctx)
    second = chat.service_chat(ctx)

    assert first is second and first["id"] == "chat-1"
    assert service.paths().count("POST /api/v1/chats") == 1


def test_a_chat_that_is_open_already_is_asked_of_nobody():
    """Silence probe: an opened chat is the one the service has; nothing is
    created in its place."""
    service = Service(chats=[{"id": "c9", "title": "An old chat", "endpoint_id": "local"}])
    ctx = context(service, renderer=Calls())
    chat.enter_chat(ctx, service.chats["c9"])

    assert chat.service_chat(ctx)["id"] == "c9"
    assert "POST /api/v1/chats" not in service.paths()


# --- The folder a new chat works in ---------------------------------------------------

OWN_ADDRESS = "http://127.0.0.1:8123"

# The whole of a chat's address at the stand-in: where its changes go.
CHAT_ONE = "/api/v1/chats/chat-1"


def at_the_service(service: Service, renderer: Calls, address: str) -> Context:
    """The parts of a client that talks to the service at ``address``, with
    a new chat open."""
    ctx = context(service, renderer=renderer)
    ctx.client = ServiceClient(
        address, "en", http=httpx.Client(transport=httpx.MockTransport(service))
    )
    ctx.client.connect()
    chat.new_chat(ctx)
    return ctx


def at_the_own_service(service: Service, renderer: Calls) -> Context:
    """The same at the service of this machine: the stand-in names the
    process the test runs in as its own."""
    service.process = lambda host: this_process()
    return at_the_service(service, renderer, OWN_ADDRESS)


def about_chats(service: Service) -> list[str]:
    """What was asked about chats and answers, in the order it was asked."""
    return [asked for asked in service.paths() if "/api/v1/chat" in asked]


def test_the_first_message_of_a_new_chat_shares_the_start_folder_before_it_goes_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Falls over without the fix: a chat made here was never given a
    folder, and the model worked in the chat's own folder among the
    program's data instead of where the client was started."""
    monkeypatch.delenv(themes.WINDOW_VARIABLE, raising=False)
    monkeypatch.chdir(tmp_path)
    here = os.getcwd()
    service = Service([[START, DONE], [START, DONE]])
    ctx = at_the_own_service(service, Calls())

    chat.send(ctx, "Hello")

    # The folder follows the creation at once, before the message; the name
    # comes with the answer's first event, as it always did.
    assert about_chats(service) == [
        "POST /api/v1/chats",
        f"PATCH {CHAT_ONE}",
        "POST /api/v1/chat/completions",
        f"PATCH {CHAT_ONE}",
    ]
    assert service.bodies(CHAT_ONE) == [{"working_dirs": [here]}, {"title": "Hello"}]
    assert os.path.samefile(here, tmp_path)
    assert ctx.session.chat is not None and ctx.session.chat["working_dirs"] == [here]

    # The second message of the same chat sets nothing anew.
    chat.send(ctx, "And again")
    assert service.bodies(CHAT_ONE) == [{"working_dirs": [here]}, {"title": "Hello"}]


@pytest.mark.parametrize("where_it_runs", ["in the tab of the window", "at a service elsewhere"])
def test_silence_probe_no_folder_is_shared_from_the_windows_tab_or_with_a_service_elsewhere(
    where_it_runs: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Started by the window, the client stands in no folder the user chose;
    and a service elsewhere could not find a folder of this machine."""
    monkeypatch.chdir(tmp_path)
    service = Service([[START, DONE]])
    if where_it_runs == "in the tab of the window":
        monkeypatch.setenv(themes.WINDOW_VARIABLE, "1")
        ctx = at_the_own_service(service, Calls())
    else:
        monkeypatch.delenv(themes.WINDOW_VARIABLE, raising=False)
        ctx = context(service, renderer=Calls())
        chat.new_chat(ctx)

    chat.send(ctx, "Hello")

    assert service.bodies(CHAT_ONE) == [{"title": "Hello"}]
    assert "working_dirs" not in service.chats["chat-1"]


@pytest.mark.parametrize("name", ["127.0.0.1", "localhost", "[::1]"])
def test_a_stand_in_under_a_name_of_this_machine_is_a_service_elsewhere_by_default(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Falls over where a stand-in names the process of the test under any
    name of this machine: the client then took it for its own service and
    shared the folder it stands in."""
    monkeypatch.delenv(themes.WINDOW_VARIABLE, raising=False)
    monkeypatch.chdir(tmp_path)
    service = Service([[START, DONE]])
    ctx = at_the_service(service, Calls(), f"http://{name}:8123")

    chat.send(ctx, "Hello")

    assert service.bodies(CHAT_ONE) == [{"title": "Hello"}]
    assert "working_dirs" not in service.chats["chat-1"]


def test_silence_probe_a_chat_that_is_opened_keeps_the_folders_it_has(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(themes.WINDOW_VARIABLE, raising=False)
    monkeypatch.chdir(tmp_path)
    old = {
        "id": "c9", "title": "An old chat", "endpoint_id": "local",
        "working_dirs": ["/a/folder/shared/before"],
    }
    service = Service([[START, DONE]], chats=[old])
    ctx = at_the_own_service(service, Calls())
    chat.enter_chat(ctx, service.chats["c9"])

    chat.send(ctx, "Go on.")

    assert not any(request.method == "PATCH" for request in service.seen)
    assert service.chats["c9"]["working_dirs"] == ["/a/folder/shared/before"]


class TakesNoFolder(Service):
    """A stand-in that refuses every working folder it is sent."""

    SAID = "The working directory does not exist."

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH" and b"working_dirs" in request.content:
            return httpx.Response(400, json={"detail": self.SAID})
        return super().__call__(request)


def test_a_folder_the_service_refuses_is_said_above_the_input_and_the_message_goes_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(themes.WINDOW_VARIABLE, raising=False)
    monkeypatch.chdir(tmp_path)
    service = TakesNoFolder([[START, {"typ": "content", "text": "An answer.\n"}, DONE]])
    calls = Calls()
    ctx = at_the_own_service(service, calls)

    chat.send(ctx, "Hello")

    # The service's own sentence, as a word for the moment — not an error in
    # the history.
    assert ("notice", TakesNoFolder.SAID) in calls.calls
    assert not any(name == "error" for name, _ in calls.calls)
    # The message went out all the same, was answered, and named the chat.
    assert [body["content"] for body in service.bodies("/api/v1/chat/completions")] == ["Hello"]
    assert ("content", "An answer.\n") in calls.calls
    assert service.chats["chat-1"]["title"] == "Hello"
    assert "working_dirs" not in service.chats["chat-1"]


def test_a_start_folder_that_is_gone_shares_nothing_and_the_message_goes_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The folder the client was started in can be removed under it; then
    the system names none, and there is none to share."""
    monkeypatch.delenv(themes.WINDOW_VARIABLE, raising=False)

    def no_folder() -> str:
        raise FileNotFoundError("the folder is gone")

    service = Service([[START, DONE]])
    calls = Calls()
    ctx = at_the_own_service(service, calls)

    # Only for the round itself: whatever looks at the result afterwards
    # stands in a folder again.
    with monkeypatch.context() as during_the_round:
        during_the_round.setattr(os, "getcwd", no_folder)
        chat.send(ctx, "Hello")

    assert service.bodies(CHAT_ONE) == [{"title": "Hello"}]
    assert not any(name in ("error", "notice") for name, _ in calls.calls)


def test_through_the_whole_client_every_new_chat_works_in_the_start_folder(
    stub: StubService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The client as it is started, at the service of this machine: the
    first chat and one made with ``/new`` each get the folder, once, before
    their first message."""
    monkeypatch.delenv(themes.WINDOW_VARIABLE, raising=False)
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    here = os.getcwd()

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: stub.watchers == 1)
        type_in("Hello" + ENTER)
        eventually(lambda: len(stub.sent) == 1 and stub.running() == 0)
        eventually(lambda: not ctx.session.answering)
        type_in("Once more" + ENTER)
        eventually(lambda: len(stub.sent) == 2 and stub.running() == 0)
        eventually(lambda: not ctx.session.answering)
        type_in("/new" + ENTER)
        # A command runs beside the worker that sends: the message waits
        # until the new chat is the open one.
        eventually(lambda: ctx.session.chat is None)
        type_in("A second chat" + ENTER)
        eventually(lambda: len(stub.sent) == 3 and stub.running() == 0)
        eventually(lambda: not ctx.session.answering)
        type_in("/quit" + ENTER)

    stub.process = lambda host: this_process()
    with stub.http() as http:
        done = run_client(http, tmp_path, monkeypatch, drive, address=OWN_ADDRESS)

    assert done.code == 0
    assert stub.changes == [
        {"chat": "chat-1", "working_dirs": [here]},
        {"chat": "chat-1", "title": "Hello"},
        {"chat": "chat-2", "working_dirs": [here]},
        {"chat": "chat-2", "title": "A second chat"},
    ]
    assert stub.chats["chat-1"]["working_dirs"] == [here]
    created = stub.requests.index("POST /api/v1/chats")
    shared = stub.requests.index(f"PATCH {CHAT_ONE}")
    assert created < shared < stub.requests.index("POST /api/v1/chat/completions")


@pytest.mark.parametrize("opened_with", ["--chat", "/chats"])
def test_silence_probe_through_the_whole_client_an_opened_chat_keeps_its_folders(
    opened_with: str, stub: StubService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A chat opened at the start or with the command is not a new one:
    nothing about it is changed, whatever folder the client stands in."""
    monkeypatch.delenv(themes.WINDOW_VARIABLE, raising=False)
    monkeypatch.chdir(tmp_path)
    stub.chats["c-old"] = {
        "id": "c-old", "title": "An old chat", "endpoint_id": stub.models[0]["id"],
        "working_dirs": ["/a/folder/shared/before"],
    }
    stub.messages["c-old"] = []

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: stub.watchers == 1)
        if opened_with == "/chats":
            type_in("/chats c-old" + ENTER)
        # A command runs beside the worker that sends: the message waits
        # until the chat is the open one.
        eventually(lambda: ctx.session.chat_id() == "c-old")
        type_in("Go on." + ENTER)
        eventually(lambda: len(stub.sent) == 1 and stub.running() == 0)
        eventually(lambda: not ctx.session.answering)
        type_in("/quit" + ENTER)

    arguments = ["--chat", "c-old"] if opened_with == "--chat" else []
    stub.process = lambda host: this_process()
    with stub.http() as http:
        done = run_client(http, tmp_path, monkeypatch, drive, *arguments, address=OWN_ADDRESS)

    assert done.code == 0
    assert [sent["chat_id"] for sent in stub.sent] == ["c-old"]
    assert stub.changes == []
    assert stub.chats["c-old"]["working_dirs"] == ["/a/folder/shared/before"]
    assert "POST /api/v1/chats" not in stub.requests


# --- The line that counts a chat's messages ----------------------------------------


def stored(number: int, role: str, said: str) -> dict[str, Any]:
    return {"id": f"m{number}", "role": role, "content": said, "reasoning": None, "stats": {}}


def test_a_chat_without_messages_gets_no_line_that_counts_them():
    service = Service(chats=[{"id": "c-empty", "title": "Nothing yet", "endpoint_id": "local"}])
    calls = Calls()
    ctx = context(service, renderer=calls)

    chat.open_chat(ctx, service.chats["c-empty"])

    # Its messages were asked for and none came: nothing is written, and no
    # line says "0/0".
    assert any(request.url.path.endswith("/c-empty/messages") for request in service.seen)
    assert calls.calls == []
    assert chat.show_history(ctx, service.chats["c-empty"]) == 0
    assert ctx.screen.status["chat_title"] == "Nothing yet"


def test_a_chat_with_two_messages_says_two_of_two_above_them():
    """Silence probe: where there is something to count, the line stands
    above the messages as before."""
    service = Service(
        chats=[{"id": "c-two", "title": "Two of them", "endpoint_id": "local"}],
        messages={"c-two": [stored(1, "user", "One."), stored(2, "assistant", "Two.")]},
    )
    calls = Calls()
    ctx = context(service, renderer=calls)

    assert chat.show_history(ctx, service.chats["c-two"]) == 2

    assert calls.calls[0] == ("remark", f"2/2 {Texts('en').t('cli.messages')}")
    assert [name for name, _ in calls.calls[1:]] == ["stored_message"] * 2


# --- The context a chat shows when it is opened ------------------------------------


def _opened(*messages: dict[str, Any], via: str = "open") -> Context:
    service = Service(
        chats=[
            {"id": "c-old", "title": "An old chat", "endpoint_id": "local"},
            {"id": "c-new", "title": "Nothing counted", "endpoint_id": "local"},
        ],
        messages={"c-old": list(messages), "c-new": [stored(1, "user", "Only me.")]},
    )
    ctx = context(service, renderer=Calls())
    if via == "open":
        chat.open_chat(ctx, service.chats["c-old"])
    else:
        chat.enter_chat(ctx, service.chats["c-old"])
        chat.show_history(ctx, service.chats["c-old"])
    return ctx


def _answer(number: int, **fields: Any) -> dict[str, Any]:
    return {**stored(number, "assistant", "An answer."), **fields}


@pytest.mark.parametrize(
    ("fields", "shown"),
    [
        ({"gesamt_tokens": 3200}, 3200),
        ({"stats": {"gesamt_tokens": 3100}}, 3100),
        ({"stats": {"nutzung": {"total_tokens": 3000}}}, 3000),
        ({"stats": {"nutzung": {"prompt_tokens": 2000, "completion_tokens": 400}}}, 2400),
        ({"stats": {"nutzung": {"prompt_tokens": 2000}}}, 2000),
        ({"stats": {"nutzung": {"completion_tokens": 400}}}, 400),
        # Where more than one is there, the order of the window of Exe AI.
        ({"gesamt_tokens": 3200, "stats": {"gesamt_tokens": 1, "nutzung": {"total_tokens": 2}}}, 3200),
        ({"stats": {"gesamt_tokens": 3100, "nutzung": {"total_tokens": 2}}}, 3100),
    ],
)
def test_an_opened_chat_shows_the_context_of_its_newest_answer_before_any_new_one(fields, shown):
    ctx = _opened(stored(1, "user", "Question."), _answer(2, **fields))

    assert ctx.screen.status["context_tokens"] == shown


def test_the_newest_message_that_carries_a_number_counts():
    ctx = _opened(
        stored(1, "user", "First."),
        _answer(2, gesamt_tokens=1000),
        stored(3, "user", "Second."),
        _answer(4, gesamt_tokens=3200),
        stored(5, "user", "Third, not answered yet."),
    )

    assert ctx.screen.status["context_tokens"] == 3200


def test_a_chat_opened_with_its_name_or_the_command_shows_it_the_same_way():
    """One place, every way in: `--chat` and the history written anew enter
    the chat and then call `show_history`; the number is set there."""
    ctx = _opened(stored(1, "user", "Question."), _answer(2, gesamt_tokens=3200), via="enter")

    assert ctx.screen.status["context_tokens"] == 3200


def test_silence_a_chat_without_an_answer_shows_no_number():
    ctx = _opened(stored(1, "user", "Question."), stored(2, "assistant", "Not counted."))

    assert "context_tokens" not in ctx.screen.status


def test_silence_the_number_of_another_chat_is_none_under_the_title_of_an_opened_one():
    """The status line books a count to the chat it came in under. The way
    into a chat without a number books nothing, and the line reads what it
    holds as the other chat's: none."""
    from cli.status import ServiceStatus

    service = Service(
        chats=[
            {"id": "c-old", "title": "An old chat", "endpoint_id": "local"},
            {"id": "c-new", "title": "Nothing counted", "endpoint_id": "local"},
        ],
        messages={
            "c-old": [stored(1, "user", "Question."), _answer(2, gesamt_tokens=3200)],
            "c-new": [stored(1, "user", "Only me.")],
        },
    )
    ctx = context(service, renderer=Calls())
    ctx.status = ServiceStatus(ctx)
    ctx.screen.update_status = ctx.status.update  # the line the client really has

    chat.open_chat(ctx, service.chats["c-old"])
    assert ctx.status._count()[0] == 3200

    chat.open_chat(ctx, service.chats["c-new"])

    assert ctx.session.chat_id() == "c-new"
    assert ctx.status._count()[0] is None


# --- The size of the context ----------------------------------------------------------


def with_its_own_list(service: Service) -> Context:
    """A context that keeps the models as it read them at start — a copy,
    as the client's is, so that what the service says later is news."""
    ctx = context(service, renderer=Calls())
    ctx.session.models = [dict(model) for model in service.models]
    ctx.screen.update_status(model_name="Local Model", context_window=8192)
    return ctx


def test_the_size_of_the_context_follows_what_the_service_names_now():
    service = Service()
    ctx = with_its_own_list(service)

    service.models[0]["context_tokens"] = 128000
    chat.follow_context_size(ctx)
    assert ctx.screen.status["context_window"] == 128000

    service.models[0]["context_tokens"] = 784000
    chat.follow_context_size(ctx)
    assert ctx.screen.status["context_window"] == 784000
    # Only the model in use was looked at, and its name is as it was.
    assert ctx.screen.status["model_name"] == "Local Model"
    assert [model["context_tokens"] for model in ctx.session.models] == [784000, 4096]


def test_a_chat_opened_after_that_shows_the_size_the_service_named_last():
    service = Service(chats=[{"id": "c9", "title": "An old chat", "endpoint_id": "local"}])
    ctx = with_its_own_list(service)
    service.models[0]["context_tokens"] = 784000
    chat.follow_context_size(ctx)

    chat.open_chat(ctx, service.chats["c9"])

    assert ctx.screen.status["context_window"] == 784000


def test_a_model_the_service_does_not_list_right_now_keeps_its_name_and_its_size():
    """Silence probe: the server of the model in use does not answer, so
    the service leaves the model out of its list. Nothing is taken in its
    place, and nothing is blanked."""
    service = Service()
    ctx = with_its_own_list(service)
    service.models[:] = [model for model in service.models if model["id"] != "local"]

    chat.follow_context_size(ctx)

    assert ctx.screen.status == {"model_name": "Local Model", "context_window": 8192}
    assert ctx.session.endpoint_id == "local"
    assert ctx.session.model() == {
        "id": "local",
        "name": "Local Model",
        "erreichbar": True,
        "context_tokens": 8192,
    }


class WithoutAList(Service):
    """A stand-in whose list of models is not to be had: refused, or the
    service is not there at all."""

    def __init__(self, gone: bool) -> None:
        super().__init__()
        self.gone = gone
        self.silent = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.silent and request.url.path == "/api/v1/models":
            if self.gone:
                raise httpx.ConnectError("nobody there", request=request)
            return httpx.Response(500, json={"detail": "Not now"})
        return super().__call__(request)


@pytest.mark.parametrize("gone", [False, True])
def test_a_service_that_does_not_hand_out_its_list_changes_nothing_and_raises_nothing(gone: bool):
    service = WithoutAList(gone)
    ctx = with_its_own_list(service)
    service.silent = True

    chat.follow_context_size(ctx)

    assert ctx.screen.status == {"model_name": "Local Model", "context_window": 8192}
