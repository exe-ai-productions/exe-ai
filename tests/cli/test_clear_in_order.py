"""``/clear`` empties the terminal window, and the chat stays as it is. It
takes its place among the pieces of the history, whenever it is sent: what
was written before it goes with the window — a piece that is still on its
way to the terminal included — and what is written after it stands in the
emptied window."""

from __future__ import annotations

import shlex
import sys
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from cli import commands
from cli.interfaces import Context
from tests.cli.program import ENTER, FULL_COLOURS, Gated, Run, run_client, terminal
from tests.cli.stub_service import StubService, eventually

# What a terminal is sent to empty its window.
EMPTIED = "\x1b[2J"

ASKED = "What grows in the shade"
ANSWERED = "Hello."

EARLY = "an early piece"
ON_ITS_WAY = "a piece on its way"
LATER = "a later piece"


def write_a_piece_and_one_that_waits(ctx: Context, sent: Callable[[], str]) -> None:
    """The first piece goes out at once; the output then holds the next
    ones back for a moment, to hand them to the terminal together."""
    ctx.screen.print_above(EARLY)
    eventually(lambda: EARLY in sent())
    ctx.screen.print_above(ON_ITS_WAY)


def test_sent_beside_a_running_answer_it_takes_a_piece_still_on_its_way_with_it(
    gated: Gated, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent, output = terminal(monkeypatch, FULL_COLOURS)

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: gated.watchers == 1)
        type_in(ASKED + ENTER)
        eventually(lambda: ctx.session.answering and gated.running() == 1)
        write_a_piece_and_one_that_waits(ctx, sent.getvalue)
        type_in("/clear" + ENTER)
        eventually(lambda: EMPTIED in sent.getvalue())
        ctx.screen.print_above(LATER)
        eventually(lambda: LATER in sent.getvalue())
        assert gated.running() == 1
        gated.gate.set()
        eventually(lambda: gated.running() == 0 and not ctx.session.answering)
        type_in("/quit" + ENTER)

    with gated.http() as http:
        assert run_client(http, tmp_path, monkeypatch, drive, output=output).code == 0
    assert sent.getvalue().count(EMPTIED) == 1
    before, after = sent.getvalue().split(EMPTIED)
    assert ON_ITS_WAY in before
    assert ON_ITS_WAY not in after
    # What was written after the emptying stands in the emptied window.
    assert LATER in after
    # The chat is as it was.
    assert [held["title"] for held in gated.chats.values()] == [ASKED]


def test_sent_beside_an_answer_that_is_over_by_then_it_still_takes_its_place(
    gated: Gated, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whether an answer still runs when the command gets to the screen
    makes no difference: what was written until then is on its way like
    any piece of the answer."""
    sent, output = terminal(monkeypatch, FULL_COLOURS)

    def only_after_the_answer(ctx: Context, argument: str) -> None:
        gated.gate.set()
        eventually(lambda: gated.running() == 0 and not ctx.session.answering)
        write_a_piece_and_one_that_waits(ctx, sent.getvalue)
        ctx.screen.clear()

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        assert isinstance(ctx.commands, commands.Commands)
        # The command as it is, only later: it gets to the screen once the
        # answer it was sent beside is over.
        ctx.commands.register(commands.Command("clear", "cli.cmd_clear", only_after_the_answer))
        eventually(lambda: gated.watchers == 1)
        type_in(ASKED + ENTER)
        eventually(lambda: ctx.session.answering and gated.running() == 1)
        type_in("/clear" + ENTER)
        eventually(lambda: EMPTIED in sent.getvalue())
        ctx.screen.print_above(LATER)
        eventually(lambda: LATER in sent.getvalue())
        type_in("/quit" + ENTER)

    with gated.http() as http:
        assert run_client(http, tmp_path, monkeypatch, drive, output=output).code == 0
    assert sent.getvalue().count(EMPTIED) == 1
    before, after = sent.getvalue().split(EMPTIED)
    assert ANSWERED in before
    assert ON_ITS_WAY in before
    assert ON_ITS_WAY not in after
    assert LATER in after


@pytest.mark.skipif(sys.platform == "win32", reason="the shell of the test is a POSIX one")
def test_waiting_behind_a_shell_line_it_takes_that_lines_last_output_with_it(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No answer runs: the command waits in the queue behind the shell
    line and is taken the moment that line is over — while the last thing
    it printed is still on its way."""
    sent, output = terminal(monkeypatch, FULL_COLOURS)
    go_on = tmp_path / "go-on"
    waiting = f"while [ ! -e {shlex.quote(str(go_on))} ]; do sleep 0.02; done"
    # Each line is typed in two halves, so it stands in what the terminal
    # is sent only once the shell has printed it.
    line = f'!echo shell-li""ne-1; {waiting}; echo shell-li""ne-2; sleep 0.05; echo shell-li""ne-3'
    printed = ("shell-line-1", "shell-line-2", "shell-line-3")

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: stub.watchers == 1)
        type_in(line + ENTER)
        eventually(lambda: printed[0] in sent.getvalue())
        # Behind the shell line, which still runs.
        type_in("/clear" + ENTER)
        go_on.touch()
        eventually(lambda: EMPTIED in sent.getvalue())
        ctx.screen.print_above(LATER)
        eventually(lambda: LATER in sent.getvalue())
        type_in("/quit" + ENTER)

    assert run_client(stub_http, tmp_path, monkeypatch, drive, output=output).code == 0
    assert sent.getvalue().count(EMPTIED) == 1
    before, after = sent.getvalue().split(EMPTIED)
    assert all(word in before for word in printed)
    assert not any(word in after for word in printed)
    assert LATER in after


def test_sent_while_nothing_runs_the_window_is_emptied_once_and_the_chat_stays(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent, output = terminal(monkeypatch, FULL_COLOURS)

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: stub.watchers == 1)
        type_in(ASKED + ENTER)
        eventually(lambda: ANSWERED in sent.getvalue())
        # Over on both sides: the next line is taken in its own turn.
        eventually(lambda: stub.running() == 0 and not ctx.session.answering)
        type_in("/clear" + ENTER)
        eventually(lambda: EMPTIED in sent.getvalue())
        ctx.screen.print_above(LATER)
        eventually(lambda: LATER in sent.getvalue())
        type_in("/quit" + ENTER)

    assert run_client(stub_http, tmp_path, monkeypatch, drive, output=output).code == 0
    assert sent.getvalue().count(EMPTIED) == 1
    before, after = sent.getvalue().split(EMPTIED)
    assert ANSWERED in before
    assert ANSWERED not in after
    assert LATER in after
    # The chat is as it was.
    assert [held["title"] for held in stub.chats.values()] == [ASKED]
