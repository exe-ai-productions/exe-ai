"""A line that starts with ``!``: the rest runs in the user's own shell,
what it prints stands in the history, and nothing of it reaches the
service."""

from __future__ import annotations

import sys
import threading

import pytest

from cli import shell
from cli.interfaces import Context, Renderer
from cli.texts import Texts
from stub_service import eventually
from test_stream import WAIT_SECONDS, Service, context

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="the shell of the test is a POSIX one")

# A command that says when what it started is running: it prints one line
# as soon as its sleep is under way. Interrupted any earlier, the shell may
# be caught in the middle of starting the sleep, and then there is nothing
# yet that it started.
STARTS_A_SLEEP = "!sleep 30 & echo started; wait; echo never"

# The line that command prints once its sleep runs.
SLEEP_RUNS = "started"


class Lines(Renderer):
    """A renderer that keeps the shell's lines, the client's remarks and
    its errors apart."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.remarks: list[str] = []
        self.errors: list[str] = []

    def shell_line(self, text: str) -> None:
        self.lines.append(text)

    def remark(self, text: str) -> None:
        self.remarks.append(text)

    def error(self, text: str) -> None:
        self.errors.append(text)


def ready() -> tuple[Context, Service, Lines]:
    service = Service()
    renderer = Lines()
    return context(service, renderer=renderer), service, renderer


@posix_only
def test_what_the_command_prints_reaches_the_history_line_by_line_and_the_service_not_at_all():
    ctx, service, shown = ready()
    assert shell.Shell().run(ctx, "!echo one; echo two") == 0
    assert shown.lines == ["one", "two"]
    assert shown.remarks == [] and shown.errors == []
    # Nothing went out: the line is the shell's, not the model's.
    assert [request for request in service.seen if request.url.path.endswith("/chat/completions")] == []


@posix_only
def test_the_error_output_comes_into_the_history_as_well():
    ctx, _, shown = ready()
    assert shell.Shell().run(ctx, "!echo loud 1>&2") == 0
    assert shown.lines == ["loud"]


@posix_only
def test_a_return_code_other_than_zero_is_named_below_the_output():
    ctx, _, shown = ready()
    assert shell.Shell().run(ctx, "!false") == 1
    assert shown.lines == []
    assert shown.remarks == [Texts("en").t("cli.shell_exit", code=1)]
    assert shown.errors == []


@posix_only
def test_a_line_with_nothing_behind_the_mark_runs_nothing():
    ctx, _, shown = ready()
    assert shell.Shell().run(ctx, "!") == 0 and shell.Shell().run(ctx, "!   ") == 0
    assert shown.lines == [] and shown.remarks == [] and shown.errors == []


@posix_only
def test_a_shell_that_cannot_start_is_said_and_the_client_goes_on(monkeypatch, tmp_path):
    monkeypatch.setenv("SHELL", str(tmp_path / "no-such-shell"))
    ctx, _, shown = ready()
    assert shell.Shell().run(ctx, "!echo hi") == shell.NOT_RUN
    assert shown.lines == [] and len(shown.errors) == 1
    assert "no-such-shell" in shown.errors[0]


def test_the_command_runs_in_the_users_shell_or_the_systems(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("SHELL", "/usr/local/bin/fish")
    assert shell.invocation("ls -la") == ["/usr/local/bin/fish", "-c", "ls -la"]
    monkeypatch.delenv("SHELL")
    assert shell.invocation("ls -la") == ["/bin/sh", "-c", "ls -la"]
    monkeypatch.setattr(sys, "platform", "win32")
    assert shell.invocation("dir") == ["cmd", "/c", "dir"]


def test_only_a_line_that_starts_with_the_mark_is_a_shell_line():
    assert shell.is_shell_line("!ls")
    assert shell.is_shell_line("! ls")
    assert not shell.is_shell_line("ls!")
    assert not shell.is_shell_line("/help")
    assert not shell.is_shell_line("Hello!")


@posix_only
def test_the_interrupt_ends_the_running_command_with_what_it_started_and_says_so():
    ctx, _, shown = ready()
    runner = shell.Shell()
    # Nothing runs: there is nothing to end.
    assert not runner.interrupt()
    codes: list[int] = []

    def the_sleep_runs() -> bool:
        return shown.lines == [SLEEP_RUNS]

    worker = threading.Thread(target=lambda: codes.append(runner.run(ctx, STARTS_A_SLEEP)))
    worker.start()
    eventually(the_sleep_runs)
    assert runner.interrupt()
    worker.join(WAIT_SECONDS)
    assert not worker.is_alive()
    # The shell and the sleep it started are gone: nothing holds the output
    # open any more, and nothing was printed after the interrupt. The
    # history says so, and names no return code for it.
    assert shown.lines == [SLEEP_RUNS]
    assert shown.remarks == [Texts("en").t("cli.shell_stopped")]
    assert codes and codes[0] != 0
