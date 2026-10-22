"""Switching the theme leaves nothing in the window in the colours of the
theme before: the window is emptied and the open chat's history is written
again in the new ones — once, however often the theme was switched while an
answer ran. Where nothing has been said in the open chat yet, the head is
what is written again. Opening the selection of the themes and closing it,
naming the theme in use or naming one that does not exist empties nothing.
No list of the themes is written behind any of it."""

from __future__ import annotations

import io
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from cli import chat, commands, themes, wordmark
from cli.client import ServiceUnreachable
from cli.interfaces import Asker, Context, Renderer, Screen
from cli.texts import Texts
from tests.cli.program import (
    EMPTIED,
    ENTER,
    FULL_COLOURS,
    Gated,
    Run,
    in_full_colours,
    run_client,
    taped_history,
    terminal,
)
from tests.cli.stub_service import StubService, eventually

ASKED = "What grows in the shade"
ANSWERED = "Hello."

# What the status lines ask the service once a line has been handled.
TOOLS_ASKED = "GET /api/v1/tools"
ESCAPE = "\x1b"


@pytest.fixture(autouse=True)
def the_default_look() -> Iterator[None]:
    themes.set_look(themes.DEFAULT_LOOK)
    yield
    themes.set_look(themes.DEFAULT_LOOK)


def text_of(look: str) -> str:
    return in_full_colours(look, "text")


def after_one_exchange(
    stub: StubService,
    http: httpx.Client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    line: str,
    written: str | None = None,
) -> str:
    """Runs the client in a terminal with the full colours, has one message
    answered, types ``line`` and returns what the terminal was sent from
    then on, until ``written`` stood in it — or, where the line writes
    nothing, until it was through: the status lines then ask the service
    anew."""
    sent, output = terminal(monkeypatch, FULL_COLOURS)
    tape = taped_history(monkeypatch)
    since: list[int] = []

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: stub.watchers == 1)
        type_in(ASKED + ENTER)
        eventually(lambda: ANSWERED in tape.getvalue())
        # Over on both sides: the next line is taken in its own turn.
        eventually(lambda: stub.running() == 0 and not ctx.session.answering)
        since.append(len(tape.getvalue()))
        handled = stub.requests.count(TOOLS_ASKED)
        type_in(line + ENTER)
        if written is None:
            eventually(lambda: stub.requests.count(TOOLS_ASKED) > handled)
        else:
            eventually(lambda: written in tape.getvalue()[since[0] :])
        type_in("/quit" + ENTER)

    assert run_client(http, tmp_path, monkeypatch, drive, output=output).code == 0
    return tape.getvalue()[since[0] :]


def test_a_switch_empties_the_window_and_writes_the_history_in_the_new_colours(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown = after_one_exchange(stub, stub_http, tmp_path, monkeypatch, "/theme moune", ANSWERED)
    assert shown.count(EMPTIED) == 1
    again = shown.split(EMPTIED)[1]
    # Both sides of the exchange stand there again, each once, in the new
    # theme's ink.
    assert ASKED in again and again.count(ANSWERED) == 1
    assert text_of("moune") in again
    assert text_of(themes.DEFAULT_LOOK) not in again
    # No list of the themes follows the history.
    assert "darkmatter" not in again


def through_the_selection(
    stub: StubService,
    http: httpx.Client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    keys: str,
    written: str | None = None,
) -> str:
    """The same, with the theme taken from the selection: one message is
    answered, ``/theme`` opens the selection, ``keys`` are typed into it.
    Returns what the terminal was sent from the command on, until the
    selection was closed and — where something is to be written again —
    ``written`` stood behind it."""
    sent, output = terminal(monkeypatch, FULL_COLOURS)
    tape = taped_history(monkeypatch)
    since: list[int] = []

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: stub.watchers == 1)
        type_in(ASKED + ENTER)
        eventually(lambda: ANSWERED in tape.getvalue())
        eventually(lambda: stub.running() == 0 and not ctx.session.answering)
        since.append(len(tape.getvalue()))
        type_in("/theme" + ENTER)
        eventually(ctx.asker.pending)
        type_in(keys)
        eventually(lambda: not ctx.asker.pending())
        if written is not None:
            eventually(lambda: written in tape.getvalue()[since[0] :].split(EMPTIED)[-1])
        type_in("/quit" + ENTER)

    assert run_client(http, tmp_path, monkeypatch, drive, output=output).code == 0
    return tape.getvalue()[since[0] :]


def test_a_theme_picked_from_the_selection_is_redrawn_like_one_named_by_its_word(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    number = list(themes.available()).index("moune") + 1
    shown = through_the_selection(stub, stub_http, tmp_path, monkeypatch, f"{number}{ENTER}", ANSWERED)
    assert themes.current().name == "moune"
    assert shown.count(EMPTIED) == 1
    again = shown.split(EMPTIED)[1]
    assert ASKED in again and again.count(ANSWERED) == 1
    assert text_of("moune") in again
    assert text_of(themes.DEFAULT_LOOK) not in again


def test_opening_the_selection_and_closing_it_empties_nothing(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown = through_the_selection(stub, stub_http, tmp_path, monkeypatch, ESCAPE)
    assert EMPTIED not in shown
    assert themes.current().name == themes.DEFAULT_LOOK


def test_picking_the_theme_in_use_from_the_selection_empties_nothing(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The mark opens on the theme in use: the enter key takes that one.
    shown = through_the_selection(stub, stub_http, tmp_path, monkeypatch, ENTER)
    assert EMPTIED not in shown
    assert themes.current().name == themes.DEFAULT_LOOK


def test_naming_the_theme_in_use_empties_nothing(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    line = f"/theme {themes.DEFAULT_LOOK}"
    shown = after_one_exchange(stub, stub_http, tmp_path, monkeypatch, line)
    assert EMPTIED not in shown


def test_a_theme_that_does_not_exist_empties_nothing(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown = after_one_exchange(stub, stub_http, tmp_path, monkeypatch, "/theme neon")
    assert EMPTIED not in shown
    assert themes.current().name == themes.DEFAULT_LOOK


def test_beside_a_running_answer_the_window_is_emptied_at_once_and_the_history_follows_the_answer(
    gated: Gated, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent, output = terminal(monkeypatch, FULL_COLOURS)
    tape = taped_history(monkeypatch)
    since: list[int] = []

    def shown() -> str:
        return tape.getvalue()[since[0] :]

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: gated.watchers == 1)
        type_in(ASKED + ENTER)
        eventually(lambda: ctx.session.answering and gated.running() == 1)
        since.append(len(tape.getvalue()))
        type_in("/theme moune" + ENTER)
        # Emptied while the answer still runs.
        eventually(lambda: EMPTIED in shown())
        assert gated.running() == 1
        gated.gate.set()
        eventually(lambda: shown().count(EMPTIED) == 2 and ANSWERED in shown().split(EMPTIED)[2])
        type_in("/quit" + ENTER)

    with gated.http() as http:
        assert run_client(http, tmp_path, monkeypatch, drive, output=output).code == 0
    again = shown().split(EMPTIED)[2]
    # The whole exchange, the answer as the service keeps it now — and
    # once: nothing of the answer as it ran came in behind the emptying.
    assert ASKED in again and again.count(ANSWERED) == 1
    assert text_of("moune") in again
    assert text_of(themes.DEFAULT_LOOK) not in again


def test_five_switches_beside_a_running_answer_read_and_write_the_history_once(
    gated: Gated, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent, output = terminal(monkeypatch, FULL_COLOURS)
    tape = taped_history(monkeypatch)
    since: list[int] = []
    looks = ("heaven", "pearl", "darkmatter", "exe", "moune")

    def shown() -> str:
        return tape.getvalue()[since[0] :]

    def histories_read() -> int:
        return sum(1 for asked in gated.requests if asked.endswith("/messages"))

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: gated.watchers == 1)
        type_in(ASKED + ENTER)
        eventually(lambda: ctx.session.answering and gated.running() == 1)
        since.append(len(tape.getvalue()))
        for number, look in enumerate(looks, start=1):
            type_in(f"/theme {look}" + ENTER)
            # Every switch empties the window at once.
            eventually(lambda: shown().count(EMPTIED) == number)  # noqa: B023
        assert histories_read() == 0
        gated.gate.set()
        eventually(lambda: histories_read() >= 1 and not ctx.session.answering)
        # In its turn behind whatever still waits: by then every redraw
        # that was asked for has been made.
        type_in("/quit" + ENTER)

    with gated.http() as http:
        assert run_client(http, tmp_path, monkeypatch, drive, output=output).code == 0
    assert histories_read() == 1
    assert shown().count(EMPTIED) == len(looks) + 1
    again = shown().split(EMPTIED)[-1]
    # In the theme that holds when the answer is over, not in the one the
    # first switch asked for.
    assert again.count(ANSWERED) == 1
    assert text_of("moune") in again
    assert text_of("heaven") not in again


def test_a_switch_beside_the_next_answer_is_redrawn_again(
    gated: Gated, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The redraw that waited is made and done with: the one asked for
    beside the answer after it waits its own turn."""
    sent, output = terminal(monkeypatch, FULL_COLOURS)

    def histories_read() -> int:
        return sum(1 for asked in gated.requests if asked.endswith("/messages"))

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: gated.watchers == 1)
        for answers, look in enumerate(("moune", "heaven"), start=1):
            gated.gate.clear()
            type_in(ASKED + ENTER)
            eventually(lambda: ctx.session.answering and gated.running() == 1)
            type_in(f"/theme {look}" + ENTER)
            eventually(lambda: themes.current().name == look)  # noqa: B023
            gated.gate.set()
            eventually(lambda: histories_read() == answers and not ctx.session.answering)  # noqa: B023
        type_in("/quit" + ENTER)

    with gated.http() as http:
        assert run_client(http, tmp_path, monkeypatch, drive, output=output).code == 0
    assert histories_read() == 2


def test_a_waiting_redraw_that_fails_leaves_the_next_one_its_turn(
    gated: Gated, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent, output = terminal(monkeypatch, FULL_COLOURS)
    asked: list[str] = []
    read = chat.show_history

    def once_unreachable(ctx: Context, opened: Any) -> int:
        asked.append(themes.current().name)
        if len(asked) == 1:
            raise ServiceUnreachable(ctx.client.address)
        return read(ctx, opened)

    monkeypatch.setattr(chat, "show_history", once_unreachable)

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: gated.watchers == 1)
        for answers, look in enumerate(("moune", "heaven"), start=1):
            gated.gate.clear()
            type_in(ASKED + ENTER)
            eventually(lambda: ctx.session.answering and gated.running() == 1)
            type_in(f"/theme {look}" + ENTER)
            eventually(lambda: themes.current().name == look)  # noqa: B023
            gated.gate.set()
            eventually(lambda: len(asked) == answers and not ctx.session.answering)  # noqa: B023
        type_in("/quit" + ENTER)

    with gated.http() as http:
        assert run_client(http, tmp_path, monkeypatch, drive, output=output).code == 0
    assert asked == ["moune", "heaven"]


# --- Before anything was said -----------------------------------------------------


def head_again(
    stub: StubService,
    http: httpx.Client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *arguments: str,
) -> str:
    """Runs the client in a terminal with the full colours, switches the
    theme with nothing said in the open chat, and returns what the terminal
    was sent from the switch on, until the head stood in it again."""
    sent, output = terminal(monkeypatch, FULL_COLOURS)
    tape = taped_history(monkeypatch)
    since: list[int] = []

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        run.parts()
        eventually(lambda: stub.watchers == 1)
        since.append(len(tape.getvalue()))
        type_in("/theme pearl" + ENTER)
        eventually(
            lambda: Texts("en").t("cli.tip_help") in tape.getvalue()[since[0] :].split(EMPTIED)[-1]
            and EMPTIED in tape.getvalue()[since[0] :]
        )
        type_in("/quit" + ENTER)

    assert run_client(http, tmp_path, monkeypatch, drive, *arguments, output=output).code == 0
    return tape.getvalue()[since[0] :]


def assert_the_head_stands_in_pearl(shown: str) -> str:
    """The window was emptied once, and behind that stands the head — the
    mark, where the client stands, the tips — in the new theme's ink, and
    no list of the themes. Returns what was written behind the emptying.

    The terminal of the test names no encoding, so the mark is the plain
    one; a terminal that speaks Unicode is sent the block letters."""
    assert shown.count(EMPTIED) == 1
    again = shown.split(EMPTIED)[1]
    assert wordmark.WORDMARK_PLAIN in again
    assert "CLI 9.8.7" in again
    assert Texts("en").t("cli.tip_help") in again
    assert text_of("pearl") in again
    assert text_of(themes.DEFAULT_LOOK) not in again
    assert "darkmatter" not in again
    return again


def test_a_switch_before_the_first_message_writes_the_head_again_in_the_new_colours(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    again = assert_the_head_stands_in_pearl(head_again(stub, stub_http, tmp_path, monkeypatch))
    # The new chat is still the client's alone: nothing was read or made.
    assert not stub.chats
    assert not any(asked.endswith("/messages") for asked in stub.requests)
    assert Texts("en").t("cli.messages") not in again


def test_a_switch_in_an_opened_chat_nobody_wrote_into_writes_the_head_again_too(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub.chats["c-empty"] = {"id": "c-empty", "title": "Nothing yet", "endpoint_id": "local"}
    stub.messages["c-empty"] = []
    shown = head_again(stub, stub_http, tmp_path, monkeypatch, "--chat", "c-empty")
    again = assert_the_head_stands_in_pearl(shown)
    # The chat's messages were asked for, and none came: no line counts them.
    assert "GET /api/v1/chats/c-empty/messages" in stub.requests
    assert Texts("en").t("cli.messages") not in again


# --- The command alone ----------------------------------------------------------


class Terminal(io.StringIO):
    """An output that says it is a terminal."""

    def isatty(self) -> bool:
        return True


class Unpicked(Asker):
    """A selection nothing is picked from."""


class Watched(Screen, Renderer):
    """Keeps, in their order, what the command asked the screen for and
    what it said."""

    def __init__(self) -> None:
        self.did: list[str] = []
        self.status: dict[str, Any] = {}

    def update_status(self, **fields: Any) -> None:
        self.status.update(fields)

    def redraw(self) -> None:
        self.did.append("redraw")

    def print_above(self, *renderables: Any) -> None:
        self.did.append("written")

    def error(self, text: str) -> None:
        self.did.append("error")


@pytest.fixture
def watched(ctx: Context, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Watched:
    for name in ("NO_COLOR", "TERM", themes.WINDOW_VARIABLE):
        monkeypatch.delenv(name, raising=False)
    both = Watched()
    ctx.screen = both
    ctx.renderer = both
    ctx.asker = Unpicked()
    ctx.prefs_path = tmp_path / "cli.json"
    ctx.commands = commands.build_commands(ctx)
    return both


def test_the_switch_asks_for_the_redraw_and_writes_no_list(ctx: Context, watched: Watched) -> None:
    ctx.commands.run("/theme moune")
    assert watched.did == ["redraw"]


def test_without_a_switch_nothing_is_drawn_again(ctx: Context, watched: Watched) -> None:
    ctx.commands.run("/theme")
    ctx.commands.run(f"/theme {themes.DEFAULT_LOOK}")
    ctx.commands.run("/theme neon")
    ctx.commands.run("/theme nerd on")
    assert watched.did == ["error"]


def test_the_status_line_names_the_new_theme_even_where_the_history_cannot_be_written(
    ctx: Context, watched: Watched, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreachable() -> None:
        raise ServiceUnreachable(ctx.client.address)

    monkeypatch.setattr(watched, "redraw", unreachable)
    with pytest.raises(ServiceUnreachable):
        ctx.commands.run("/theme moune")
    assert themes.current().name == "moune"
    assert watched.status == {"look": "moune"}


def test_a_theme_that_cannot_be_remembered_is_switched_to_whole_and_the_reason_stays_in_sight(
    ctx: Context, watched: Watched, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    in_the_way = tmp_path / "a-file"
    in_the_way.write_text("x", encoding="utf-8")
    ctx.prefs_path = in_the_way / "cli.json"
    out = Terminal()
    monkeypatch.setattr(sys, "stdout", out)
    ctx.commands.run("/theme heaven")
    assert themes.current().name == "heaven"
    # The ground went with the colours, and the reason was said after the
    # history was written again.
    assert out.getvalue() == themes.get("heaven").ground()
    assert watched.did == ["redraw", "error"]
