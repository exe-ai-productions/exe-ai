"""For tests that need the client as it really runs: started in this
process with something to type into it, or as a program of its own in a
terminal of its own, against the stand-in service on a real port.

In this process a test can look at the client's parts; as a program of its
own the client ends the way a program ends — with an exit code, and with
whatever the interpreter itself has to say on the way out.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import select
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from prompt_toolkit.application import create_app_session, get_app_session
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import ColorDepth, DummyOutput, Output
from prompt_toolkit.output.vt100 import Vt100_Output
from rich.style import Style

from cli import events, themes
from cli.interfaces import Context
from cli.main import main
from tests.cli.stub_service import StubService, eventually

ENTER = "\r"
END_OF_INPUT = "\x04"
ADDRESS = "http://stub.test"
ROOT = Path(__file__).resolve().parent.parent.parent

# If a run never leaves by itself, its input is closed after this many
# seconds: the test then fails on what it asserts instead of hanging.
SAFETY_NET_SECONDS = 20

# How long a program of its own gets for a step that should take a moment.
PATIENCE_SECONDS = 20.0

# How long a held tool stands still: longer than any test waits.
HELD_SECONDS = 120.0

# What a terminal is sent with the first drawing of the client's block, and
# not before: the screen switches bracketed paste on as it draws.
FIRST_DRAWING = b"\x1b[?2004h"

# Everything in the environment that says how many colours a terminal shows.
COLOUR_VARIABLES = ("COLORTERM", "NO_COLOR", "TERM", "FORCE_COLOR", "PROMPT_TOOLKIT_COLOR_DEPTH")

# What tells the probe that the output is a terminal although a test reads it.
A_TERMINAL = {"FORCE_COLOR": "1"}

# A terminal that reports the full colours.
FULL_COLOURS = {"TERM": "xterm-256color", "COLORTERM": "truecolor", **A_TERMINAL}

# How a colour of 24 bits begins where a terminal is sent it.
FULL = "38;2;"

posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="the terminal of the test is a POSIX one"
)


class Held(StubService):
    """A stand-in whose answers stand still before a tool's result — a tool
    that is still running, for as long as a test needs it to."""

    async def _emit(self, run: Any, kind: str, **fields: Any) -> None:
        if kind == "tool_result":
            await asyncio.sleep(HELD_SECONDS)
        await super()._emit(run, kind, **fields)


class Gated(StubService):
    """A stand-in whose answers do not end before the test opens the gate:
    an answer that is still running, for exactly as long as a test needs."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = threading.Event()

    async def _emit(self, run: Any, kind: str, **fields: Any) -> None:
        while kind == "done" and not self.gate.is_set():
            await asyncio.sleep(0.01)
        await super()._emit(run, kind, **fields)


# --- In this process ---------------------------------------------------------------


def local_clock(stamp: str) -> str:
    """A time of the service as the client shows it: in the clock of the
    machine the test runs on, which is not the zone the stamp was written
    in."""
    return datetime.fromisoformat(stamp).astimezone().strftime("%Y-%m-%d %H:%M")


def in_full_colours(look: str, colour_name: str) -> str:
    """A colour of a look as a terminal is sent it in 24 bits."""
    colour = themes.get(look).colours[colour_name]
    red, green, blue = (int(colour[at : at + 2], 16) for at in (1, 3, 5))
    return f"{FULL}{red};{green};{blue}"


@contextlib.contextmanager
def a_session_without_the_console() -> Iterator[None]:
    """The session a screen is built in. A test that gave its thread an
    output keeps it; otherwise the screen would be handed the console of
    the program that runs the tests — and on Windows a runner has none, so
    looking for it ends in an error of its own. Here it gets an output that
    is eighty columns wide and forty rows high, and an input nobody types
    into."""
    if get_app_session()._output is not None:
        yield
        return
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        yield


def terminal(
    monkeypatch: pytest.MonkeyPatch, environment: dict[str, str]
) -> tuple[io.StringIO, Output]:
    """A terminal of that environment for a run in this process: what it is
    sent, colour codes included, and the output to hand to the run. What
    the environment says about colours is read as at a real start — on
    every system the way a POSIX one reads it: where Windows would ask the
    console of the machine, the environment of the test is what says."""
    for name in COLOUR_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr("rich.console.WINDOWS", False)
    # rich writes the codes of a style onto the style itself, for whatever
    # colours the first console that wrote it had, and hands the same style
    # to every console after that. A test that wrote a look in fewer colours
    # earlier in the same process would leave these colours behind: styles
    # parsed anew are written afresh.
    for cached in (Style.parse, Style._add):
        cached.cache_clear()  # type: ignore[attr-defined]
    sent = io.StringIO()
    output = Vt100_Output(
        sent,
        lambda: Size(rows=30, columns=100),
        term=environment.get("TERM"),
        default_color_depth=ColorDepth.from_env(),
    )
    return sent, output


class Run:
    """One run of the client in this process: its parts while it runs, and
    the code it ended with."""

    def __init__(self) -> None:
        self.ctx: Context | None = None
        self.code: int | None = None

    def parts(self) -> Context:
        """The client's parts, once it has built them."""
        return eventually(lambda: self.ctx)


def run_client(
    http: httpx.Client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drive: Callable[[Run, Callable[[str], None]], None],
    *arguments: str,
    address: str = ADDRESS,
    output: Output | None = None,
    run: Run | None = None,
) -> Run:
    """Starts the client in this thread and hands ``drive`` — in a thread
    of its own — the run and a way to type into it. Returns once the client
    has left. ``run`` takes a run of the caller's own making, for a test
    that keeps more about it."""
    run = run or Run()
    build = events.build_events

    def remember(ctx: Context) -> Any:
        run.ctx = ctx
        return build(ctx)

    monkeypatch.setattr(events, "build_events", remember)
    failures: list[BaseException] = []

    with create_pipe_input() as pipe:

        def driver() -> None:
            try:
                drive(run, pipe.send_text)
            except BaseException as error:  # noqa: BLE001
                failures.append(error)
                # Without its input the client leaves; the failure is
                # raised below, in the test's own thread.
                pipe.close()

        safety_net = threading.Timer(SAFETY_NET_SECONDS, pipe.close)
        safety_net.start()
        typing = threading.Thread(target=driver, daemon=True)
        typing.start()
        try:
            with create_app_session(input=pipe, output=output or DummyOutput()):
                run.code = main(
                    ["--url", address, "--lang", "en", *arguments],
                    http=http,
                    prefs_path=tmp_path / "cli.json",
                )
        finally:
            safety_net.cancel()
        typing.join(SAFETY_NET_SECONDS)
    if failures:
        raise failures[0]
    return run


# --- As a program of its own -------------------------------------------------------


def free_port() -> int:
    """A port nothing listens on right now."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


@contextlib.contextmanager
def on_a_port(stub: StubService) -> Iterator[str]:
    """Serves the stand-in on a port of this machine for as long as the
    block runs, and yields its address."""
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            stub,
            host="127.0.0.1",
            port=port,
            log_level="error",
            lifespan="off",
            timeout_graceful_shutdown=1,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    eventually(lambda: server.started)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(PATIENCE_SECONDS)


class Program:
    """The client as a program of its own, in a terminal of its own: what
    it showed there, a way to type into it, and how it ended."""

    def __init__(self, address: str, home: Path, *arguments: str, **environment: str) -> None:
        import pty

        self._terminal, theirs = pty.openpty()
        env = {
            **os.environ,
            # Its choices go into a home of this test's own.
            "HOME": str(home),
            "USERPROFILE": str(home),
            "TERM": "xterm-256color",
            # Nothing on the other side of this terminal answers a question
            # about where the cursor stands.
            "PROMPT_TOOLKIT_NO_CPR": "1",
            **environment,
        }
        env.pop("NO_COLOR", None)
        self._process = subprocess.Popen(
            [sys.executable, "-m", "cli", "--url", address, "--lang", "en", *arguments],
            stdin=theirs,
            stdout=theirs,
            stderr=subprocess.PIPE,
            env=env,
            cwd=ROOT,
        )
        os.close(theirs)
        self._shown = bytearray()

    def _read(self, seconds: float) -> None:
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            ready, _, _ = select.select([self._terminal], [], [], 0.02)
            if not ready:
                continue
            try:
                piece = os.read(self._terminal, 65536)
            except OSError:
                return
            if not piece:
                return
            self._shown.extend(piece)

    def shown(self) -> str:
        """Everything the terminal was sent so far."""
        return self._shown.decode("utf-8", "replace")

    def wait_for(self, check: Callable[[], Any]) -> None:
        """Reads on until ``check`` holds."""
        until = time.monotonic() + PATIENCE_SECONDS
        while not check():
            if time.monotonic() >= until or self._process.poll() is not None:
                # A test that fails here leaves no program behind: one that
                # still ran would go on to the end of the whole test run.
                self._end()
                raise AssertionError(f"never happened: {check!r}\n{self.shown()[-2000:]}")
            self._read(0.02)

    def wait_until_it_listens(self) -> None:
        """Reads on until the client has drawn its block for the first time:
        from then on it takes what is typed, and a request to end finds a
        running screen.

        Before that the program is still starting. The terminal keeps what
        is typed for a whole line and hands Enter over as a line feed, so a
        line typed then stands in the field and is never sent. A request to
        end is taken during the start as well, but there it ends the start
        and no running screen. How long the start takes depends on what
        else the machine is doing, so a test that types or signals earlier
        goes by the machine's load and not by what it claims."""

        def the_block_is_drawn() -> bool:
            return FIRST_DRAWING in self._shown

        self.wait_for(the_block_is_drawn)

    def _end(self) -> None:
        """Ends the program if it still runs, waits until it is gone, and
        closes what this side held of it."""
        if self._process.poll() is None:
            self._process.kill()
        self._process.wait()
        self._close()

    def _close(self) -> None:
        if self._process.stderr is not None:
            self._process.stderr.close()
        if self._terminal >= 0:
            os.close(self._terminal)
            self._terminal = -1

    def type(self, text: str) -> None:
        os.write(self._terminal, text.encode("utf-8"))

    def signal(self, number: signal.Signals) -> None:
        self._process.send_signal(number)

    def runs(self) -> bool:
        """Whether the program has not ended yet."""
        return self._process.poll() is None

    def ended(self) -> tuple[int, str]:
        """Waits for the program to end: its exit code, and what it wrote
        to its error output."""
        until = time.monotonic() + PATIENCE_SECONDS
        while self._process.poll() is None:
            if time.monotonic() >= until:
                self._end()
                raise AssertionError(f"the program never ended\n{self.shown()[-2000:]}")
            self._read(0.02)
        self._read(0.1)
        assert self._process.stderr is not None
        errors = self._process.stderr.read().decode("utf-8", "replace")
        self._close()
        return self._process.returncode, errors
