"""Leaving while something still runs: the answer's stream is ended, the
threads that worked for the run are over, and nothing is written any more
— so the program ends with the code it was given, and the interpreter has
nothing to say on its way out.

A thread that still writes to the output while the interpreter closes that
output makes the interpreter give up with an error of its own and the code
of an abort. Whether that happens is a matter of timing, so the runs as a
program of its own are repeated.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import io
import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from prompt_toolkit.application import create_app_session, get_app
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.patch_stdout import patch_stdout

from cli import app as screen
from cli import themes
from cli.app import CliApp
from cli.client import ServiceClient, ServiceUnreachable
from cli.interfaces import Asker, Context
from cli.main import _keep_quiet_about_a_gone_terminal, _leave_nothing_unwritten
from tests.cli import program as programs
from tests.cli import stub_service as service
from tests.cli.program import (
    END_OF_INPUT,
    ENTER,
    FIRST_DRAWING,
    SAFETY_NET_SECONDS,
    Held,
    Program,
    Run,
    a_session_without_the_console,
    on_a_port,
    posix_only,
    run_client,
)
from tests.cli.stub_service import StubService, eventually

# One answer whose tool is still running: the text, the call, and then
# nothing for as long as the stand-in holds the result back.
ANSWER_WITH_A_RUNNING_TOOL = [
    service.content("I will run that.\n\n"),
    service.tool_call("run_command", {"command": "sleep 120"}, "call-1"),
    service.tool_result("run_command", "call-1", "done"),
    service.done(),
]

# How often a run as a program of its own is repeated. A client that leaves
# its threads writing ends with the interpreter's error in 23 of 40 such
# runs on ``/quit`` and in 13 of 40 on a request to end, as measured; twelve
# runs in a row without one are no accident.
RUNS = 12

# What the interpreter writes when it gives up at its end.
INTERPRETER_ERROR = "Fatal Python error"

# The threads the client starts for a run, by what each one does.
CLIENT_THREADS = ("(_work)", "(_spin)", "(_handle)", "cli-events")

# What a terminal is sent when it gets its own ground and text colour back.
OWN_GROUND_BACK = "\x1b]111\x1b\\\x1b]110\x1b\\"

# The last thing the client asks the service before its screen takes over.
LAST_QUESTION_OF_THE_START = "/tools"


class SilentAtTheStart(StubService):
    """A stand-in that does not answer the last question of the client's
    start before the test opens the gate: a start that stands still for
    exactly as long as a test needs it to."""

    def __init__(self) -> None:
        super().__init__()
        self.asked = threading.Event()
        self.gate = threading.Event()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope["path"].endswith(LAST_QUESTION_OF_THE_START):
            self.asked.set()
            while not self.gate.is_set():
                await asyncio.sleep(0.01)
        await super().__call__(scope, receive, send)


@pytest.fixture
def held() -> Held:
    stub = Held()
    stub.script = list(ANSWER_WITH_A_RUNNING_TOOL)
    yield stub
    stub.close()


def still_running() -> list[str]:
    """The client's own threads that are alive right now."""
    return [
        thread.name
        for thread in threading.enumerate()
        if thread.is_alive() and any(mark in thread.name for mark in CLIENT_THREADS)
    ]


def tool_runs(stub: StubService) -> bool:
    """Whether the answer has got as far as its tool call."""
    return stub.running() == 1 and any(
        event.get("typ") == "tool_call" for run in stub._runs.values() for event in run.events
    )


def leave_during_the_tool(stub: StubService, leave: str) -> Callable[[Run, Callable[[str], None]], None]:
    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: stub.watchers == 1)
        type_in(f"Run it{ENTER}")
        eventually(lambda: tool_runs(stub) and ctx.session.answering)
        type_in(leave)

    return drive


# --- In this process: what is over when the client has left ------------------------


@pytest.mark.parametrize("leave", [f"/quit{ENTER}", END_OF_INPUT])
def test_leaving_while_a_tool_runs_ends_the_stream_and_every_thread(
    held: Held, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leave: str
) -> None:
    with held.http() as http:
        run = run_client(http, tmp_path, monkeypatch, leave_during_the_tool(held, leave))
        assert run.code == 0
        # Over when the client returns — not at some point after it.
        assert still_running() == []
        # The answer itself goes on in the service: leaving stops nothing there.
        assert held.stops == []
        assert held.running() == 1
        # And the listener's stream is closed, not left hanging.
        eventually(lambda: held.watchers == 0)


def test_leaving_with_nothing_running_ends_every_thread_too(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        run.parts()
        eventually(lambda: stub.watchers == 1)
        type_in(f"/quit{ENTER}")

    run = run_client(stub_http, tmp_path, monkeypatch, drive)
    assert run.code == 0
    assert still_running() == []


@posix_only
def test_leaving_ends_a_shell_command_that_still_runs(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[Any] = []

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: stub.watchers == 1)
        type_in(f"!sleep 120{ENTER}")
        shell = ctx.screen._shell  # type: ignore[attr-defined]
        commands.append(eventually(lambda: shell._running))
        type_in(END_OF_INPUT)

    run = run_client(stub_http, tmp_path, monkeypatch, drive)

    assert run.code == 0
    # The command went with the screen that showed what it printed, and
    # the thread that read it is over.
    assert commands[0].poll() is not None
    assert still_running() == []


# --- The screen and the client, each by itself -------------------------------------


def test_a_request_to_leave_that_came_before_the_screen_ran_is_carried_out_once_it_does(
    ctx: Context,
) -> None:
    ctx.commands = _NoCommands()  # type: ignore[assignment]
    ctx.asker = _NoQuestions()  # type: ignore[assignment]
    given_up: list[str] = []
    with create_pipe_input() as pipe:

        def give_up() -> None:
            given_up.append("the screen never left")
            pipe.close()

        safety_net = threading.Timer(SAFETY_NET_SECONDS, give_up)
        safety_net.start()
        try:
            with create_app_session(input=pipe, output=DummyOutput()):
                app = CliApp(ctx)
                # Nothing runs yet that the request could end.
                app.exit()
                app.run()
        finally:
            safety_net.cancel()
    assert given_up == []


def test_nothing_is_written_once_the_screen_is_leaving(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    written = io.StringIO()
    monkeypatch.setattr(sys, "stdout", written)
    ctx.commands = _NoCommands()  # type: ignore[assignment]
    ctx.asker = _NoQuestions()  # type: ignore[assignment]
    with a_session_without_the_console():
        app = CliApp(ctx)

    app.print_above("before")
    assert "before" in written.getvalue()

    app.exit()
    app.print_above("after")
    assert "after" not in written.getvalue()


class _NoCommands:
    def completer(self) -> None:
        return None


class _NoQuestions(Asker):
    def fragments(self) -> list[tuple[str, str]]:
        return []

    def pending(self) -> bool:
        return False

    def key_bindings(self) -> None:
        return None


def test_hanging_up_ends_a_stream_under_whoever_reads_it(ctx: Context, stub: StubService) -> None:
    client = ctx.client
    read: list[object] = []

    def reader() -> None:
        try:
            for event in client.stream("/events/stream", method="GET", params={"schluessel": client.key}):
                read.append(event)
        except ServiceUnreachable as error:
            read.append(error)
        read.append("over")

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    eventually(lambda: stub.watchers == 1)

    client.hang_up()
    thread.join(service.PATIENCE_SECONDS)

    assert not thread.is_alive()
    assert read[-1] == "over"
    eventually(lambda: stub.watchers == 0)


def test_hanging_up_wakes_a_reader_that_waits_on_a_real_connection() -> None:
    stub = StubService()
    try:
        with on_a_port(stub) as address:
            client = ServiceClient(address, "en")
            client.connect()
            read: list[object] = []

            def reader() -> None:
                try:
                    read.extend(
                        client.stream("/events/stream", method="GET", params={"schluessel": client.key})
                    )
                except ServiceUnreachable:
                    read.append("gone")

            thread = threading.Thread(target=reader, daemon=True)
            thread.start()
            eventually(lambda: stub.watchers == 1)

            # Nothing arrives on the stream: the reader waits on the socket.
            client.hang_up()
            thread.join(service.PATIENCE_SECONDS)

            assert not thread.is_alive()
            assert read == ["gone"]
            client.close()
    finally:
        stub.close()


def test_after_hanging_up_nothing_more_is_asked(ctx: Context, stub: StubService) -> None:
    ctx.client.hang_up()
    asked = len(stub.requests)

    with pytest.raises(ServiceUnreachable):
        ctx.client.get("/health")
    with pytest.raises(ServiceUnreachable):
        list(ctx.client.stream("/events/stream", method="GET"))

    assert len(stub.requests) == asked


def test_a_client_that_did_not_hang_up_asks_as_ever(ctx: Context) -> None:
    assert ctx.client.get("/health")["status"] == "ok"


# --- In this process: a request to end and the screen that is not running yet ------


def raise_a_request_to_end(before: Any) -> None:
    """Raises the signal in this process, where the client runs. Only with
    a handler the client took since ``before``: any other one would answer
    for the whole test run."""
    taken = signal.getsignal(signal.SIGTERM)
    assert callable(taken) and taken is not before
    signal.raise_signal(signal.SIGTERM)


@posix_only
@pytest.mark.parametrize("times", [1, 2])
def test_a_request_to_end_on_the_screens_way_up_is_carried_out_once_it_runs(
    stub: StubService,
    stub_http: httpx.Client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    times: int,
) -> None:
    before = signal.getsignal(signal.SIGTERM)

    @contextlib.contextmanager
    def asked_on_the_way_up(**options: Any) -> Iterator[None]:
        # Here the start has asked the service all it had to ask, and the
        # screen does not run yet.
        for _ in range(times):
            raise_a_request_to_end(before)
        with patch_stdout(**options):
            yield

    monkeypatch.setattr(screen, "patch_stdout", asked_on_the_way_up)

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        # Nothing is typed: the client leaves because it was asked to.
        eventually(lambda: run.code is not None)

    run = run_client(stub_http, tmp_path, monkeypatch, drive)

    assert run.code == 0
    assert still_running() == []
    eventually(lambda: stub.watchers == 0)


def test_the_client_takes_a_request_to_end_while_it_runs_and_gives_it_back_after(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = signal.getsignal(signal.SIGTERM)
    during: list[Any] = []

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        run.parts()
        eventually(lambda: stub.watchers == 1)
        during.append(signal.getsignal(signal.SIGTERM))
        type_in(f"/quit{ENTER}")

    run = run_client(stub_http, tmp_path, monkeypatch, drive)

    assert run.code == 0
    assert callable(during[0])
    assert during[0] is not before
    assert signal.getsignal(signal.SIGTERM) is before


@posix_only
def test_a_request_to_end_when_a_failed_start_begins_to_leave_is_not_raised_into_the_leave(
    stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = signal.getsignal(signal.SIGTERM)
    take = CliApp.leave_on_signals
    asked: list[bool] = []

    def take_and_ask_when_giving_back(self: CliApp) -> Callable[[], None]:
        give_back = take(self)

        def asked_then_given_back() -> None:
            # The first step of leaving: the handlers are still the client's.
            raise_a_request_to_end(before)
            asked.append(True)
            give_back()

        return asked_then_given_back

    monkeypatch.setattr(CliApp, "leave_on_signals", take_and_ask_when_giving_back)

    # No chat answers to that name: the start says so, and the client
    # leaves without its screen ever having run.
    run = run_client(
        stub_http, tmp_path, monkeypatch, lambda run, type_in: None, "--chat", "no such chat"
    )

    assert asked == [True]
    assert run.code == 1
    assert signal.getsignal(signal.SIGTERM) is before


# --- In this process: a terminal that is gone --------------------------------------


class FailsAtLeaving(DummyOutput):
    """An output that takes everything until the screen has left, and then
    fails on what the screen still writes — with the error it is given."""

    def __init__(self, number: int) -> None:
        self.number = number

    def flush(self) -> None:
        if get_app().is_done:
            raise OSError(self.number, os.strerror(self.number))


def leave_by_the_end_of_input(stub: StubService) -> Callable[[Run, Callable[[str], None]], None]:
    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        run.parts()
        eventually(lambda: stub.watchers == 1)
        type_in(END_OF_INPUT)

    return drive


def test_a_screen_that_fails_on_a_gone_terminal_is_a_way_of_leaving(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = run_client(
        stub_http,
        tmp_path,
        monkeypatch,
        leave_by_the_end_of_input(stub),
        output=FailsAtLeaving(errno.EIO),
    )
    assert run.code == 0
    assert still_running() == []
    eventually(lambda: stub.watchers == 0)


def test_a_screen_that_fails_for_any_other_reason_fails_as_ever(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(OSError) as failure:
        run_client(
            stub_http,
            tmp_path,
            monkeypatch,
            leave_by_the_end_of_input(stub),
            output=FailsAtLeaving(errno.ENOSPC),
        )
    assert failure.value.errno == errno.ENOSPC
    # The client left all the same: nothing of it is still running.
    assert still_running() == []


class RefusesToWrite(io.StringIO):
    """A terminal that fails on what it is to write out, with the error it
    is given."""

    def __init__(self, number: int) -> None:
        super().__init__()
        self.number = number

    def isatty(self) -> bool:
        return True

    def flush(self) -> None:
        raise OSError(self.number, os.strerror(self.number))


def test_a_gone_terminal_has_no_ground_to_give_back_and_any_other_failure_is_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(themes, "owns_ground", lambda out=None: True)
    themes.unpaint(RefusesToWrite(errno.EIO))
    with pytest.raises(OSError):
        themes.unpaint(RefusesToWrite(errno.ENOSPC))


@posix_only
def test_what_a_gone_terminal_has_not_taken_is_let_go_of() -> None:
    import pty

    ours, theirs = pty.openpty()
    out = os.fdopen(theirs, "w", encoding="utf-8")
    try:
        out.write("left over")
        os.close(ours)
        _leave_nothing_unwritten(out)
        # Nothing waits any more, and what is written from here on fails
        # on nothing: the output points at nothing.
        out.write("more")
        out.flush()
        assert os.path.samestat(os.fstat(out.fileno()), os.stat(os.devnull))
    finally:
        out.close()


def test_a_thread_that_fails_on_a_gone_terminal_is_not_reported_and_any_other_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reported: list[BaseException | None] = []

    def as_before(failed: threading.ExceptHookArgs) -> None:
        reported.append(failed.exc_value)

    monkeypatch.setattr(threading, "excepthook", as_before)

    def fail(number: int) -> None:
        raise OSError(number, os.strerror(number))

    report_again = _keep_quiet_about_a_gone_terminal()
    try:
        for number in (errno.EIO, errno.ENOSPC):
            thread = threading.Thread(target=fail, args=(number,))
            thread.start()
            thread.join()
    finally:
        report_again()

    assert [getattr(error, "errno", None) for error in reported] == [errno.ENOSPC]
    assert threading.excepthook is as_before


# --- As a program of its own: the code it ends with --------------------------------


def running_tool(program: Program, stub: StubService, before: int) -> None:
    """Types a message and waits until the tool of its answer is running."""
    program.wait_for(lambda: stub.watchers >= 1)
    program.wait_until_it_listens()
    program.type(f"Run it{ENTER}")
    program.wait_for(lambda: len(stub.sent) > before)
    program.wait_for(lambda: "run_command" in program.shown())


@posix_only
def test_quit_while_a_tool_runs_ends_with_zero_every_time(tmp_path: Path) -> None:
    stub = Held()
    stub.script = list(ANSWER_WITH_A_RUNNING_TOOL)
    codes: list[int] = []
    said: list[str] = []
    try:
        with on_a_port(stub) as address:
            for _ in range(RUNS):
                program = Program(address, tmp_path)
                running_tool(program, stub, len(stub.sent))
                program.type(f"/quit{ENTER}")
                code, errors = program.ended()
                codes.append(code)
                said.append(errors)
    finally:
        stub.close()
    assert codes == [0] * RUNS
    assert not any(INTERPRETER_ERROR in errors for errors in said)


@posix_only
def test_a_request_to_end_during_an_answer_leaves_without_a_word_of_the_interpreter(
    tmp_path: Path,
) -> None:
    stub = Held()
    stub.script = list(ANSWER_WITH_A_RUNNING_TOOL)
    codes: list[int] = []
    said: list[str] = []
    try:
        with on_a_port(stub) as address:
            for _ in range(RUNS):
                program = Program(address, tmp_path)
                running_tool(program, stub, len(stub.sent))
                program.signal(signal.SIGTERM)
                code, errors = program.ended()
                codes.append(code)
                said.append(errors)
    finally:
        stub.close()
    assert not any(INTERPRETER_ERROR in errors for errors in said)
    assert said == [""] * RUNS
    assert codes == [0] * RUNS


@posix_only
@pytest.mark.parametrize("leave", ["quit", "end of input", "request to end"])
def test_leaving_with_nothing_running_ends_with_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leave: str
) -> None:
    # Started from the window's own terminal, the look would leave the
    # ground alone, and there would be none to give back.
    monkeypatch.delenv(themes.WINDOW_VARIABLE, raising=False)
    stub = StubService()
    try:
        with on_a_port(stub) as address:
            program = Program(address, tmp_path)
            program.wait_for(lambda: stub.watchers >= 1)
            program.wait_until_it_listens()
            if leave == "quit":
                program.type(f"/quit{ENTER}")
            elif leave == "end of input":
                program.type(END_OF_INPUT)
            else:
                program.signal(signal.SIGTERM)
            code, errors = program.ended()
    finally:
        stub.close()
    assert code == 0
    assert errors == ""
    # The terminal is still there, so the last thing it is sent is its own
    # ground back.
    assert program.shown().endswith(OWN_GROUND_BACK)


@posix_only
def test_a_request_to_end_during_the_start_leaves_like_any_other(tmp_path: Path) -> None:
    stub = SilentAtTheStart()
    try:
        with on_a_port(stub) as address:
            program = Program(address, tmp_path)
            try:
                # The client reads the event stream and waits for an answer
                # the service does not give: it is in the middle of its start.
                program.wait_for(lambda: stub.asked.is_set() and stub.watchers == 1)
                program.signal(signal.SIGTERM)
                code, errors = program.ended()
            finally:
                # Nothing is held any more when the stand-in stops serving.
                stub.gate.set()
            eventually(lambda: stub.watchers == 0)
    finally:
        stub.close()
    assert code == 0
    assert errors == ""
    # The request came before the block was drawn for the first time.
    assert FIRST_DRAWING.decode() not in program.shown()


# --- As a program of its own: its terminal goes away -------------------------------


class Unpluggable(Program):
    """The client as a program of its own, in a terminal that can go away
    under it."""

    _terminal: int

    def unplug(self) -> None:
        """Closes the test's side of the terminal: for the client the
        terminal is gone, as when its window is closed."""
        os.close(self._terminal)
        self._terminal = -1

    def _read(self, seconds: float) -> None:
        if self._terminal < 0:
            # Nothing is left to read from; only the wait remains.
            time.sleep(seconds)
            return
        super()._read(seconds)


@posix_only
@pytest.mark.parametrize("busy", [False, True], ids=["with nothing running", "during an answer"])
def test_a_terminal_that_goes_away_ends_the_client_without_a_word(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, busy: bool
) -> None:
    # The look owns the ground, so leaving has a ground to give back to a
    # terminal that is no longer there.
    monkeypatch.delenv(themes.WINDOW_VARIABLE, raising=False)
    stub = Held() if busy else StubService()
    if busy:
        stub.script = list(ANSWER_WITH_A_RUNNING_TOOL)
    try:
        with on_a_port(stub) as address:
            program = Unpluggable(address, tmp_path)
            if busy:
                running_tool(program, stub, len(stub.sent))
            else:
                program.wait_for(lambda: stub.watchers >= 1)
                program.wait_until_it_listens()
            program.unplug()
            code, errors = program.ended()
            eventually(lambda: stub.watchers == 0)
    finally:
        stub.close()
    assert code == 0
    assert errors == ""


# --- As a program of its own: a test that gives up on it ---------------------------


@posix_only
def test_a_wait_that_never_comes_true_leaves_no_program_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = StubService()
    try:
        with on_a_port(stub) as address:
            program = Program(address, tmp_path)
            with monkeypatch.context() as shorter:
                # Giving up is what is looked at here, not how long it takes.
                shorter.setattr(programs, "PATIENCE_SECONDS", 0.5)
                with pytest.raises(AssertionError, match="never happened"):
                    program.wait_for(lambda: False)
            assert not program.runs()
    finally:
        stub.close()


@posix_only
def test_a_wait_that_comes_true_leaves_the_program_running(tmp_path: Path) -> None:
    stub = StubService()
    try:
        with on_a_port(stub) as address:
            program = Program(address, tmp_path)
            program.wait_until_it_listens()
            still_there = program.runs()
            program.type(f"/quit{ENTER}")
            code, _ = program.ended()
    finally:
        stub.close()
    assert still_there
    assert code == 0
