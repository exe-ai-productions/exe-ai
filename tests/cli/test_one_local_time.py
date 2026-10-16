"""The head and the selection of ``/chats`` show a chat's time of last
change the same way: one function turns the service's time into the clock
of this machine, and both call it."""

from __future__ import annotations

import io
import re
from datetime import UTC, datetime
from typing import Any

import pytest
from rich.console import Console

from cli import chat_actions, commands, render
from cli.interfaces import Asker, Context, Entry, Screen
from tests.cli.stub_service import StubService

# A time with its zone, as the service may send it.
STAMP = "2024-03-09T17:05:00+00:00"
A_TIME = r"\d{4}-\d\d-\d\d \d\d:\d\d"


class Written(Screen):
    """A screen that writes what it is handed into a wide console."""

    def __init__(self) -> None:
        self._console = Console(file=io.StringIO(), width=120, record=True, force_terminal=False)

    def print_above(self, *renderables: Any) -> None:
        for renderable in renderables:
            self._console.print(renderable)

    def text(self) -> str:
        """What was written since this was last asked."""
        return self._console.export_text(clear=True)


class Listed(Asker):
    """Keeps the entries of the selection it is shown, and picks none."""

    def __init__(self) -> None:
        self.entries: list[Entry] = []

    def choose(self, entries: Any, head: str = "") -> int | None:
        self.entries = list(entries)
        return None

    def lines(self) -> list[str]:
        """The entries as they read: their columns, two blanks between."""
        return ["  ".join(text for _, text in entry.cells if text) for entry in self.entries]


@pytest.fixture
def written(ctx: Context) -> Written:
    screen = Written()
    ctx.screen = screen
    ctx.renderer = render.build_renderer(ctx)
    ctx.asker = Listed()
    ctx.commands = commands.build_commands(ctx)
    return screen


@pytest.fixture
def listed(ctx: Context, written: Written) -> Listed:
    asker = ctx.asker
    assert isinstance(asker, Listed)
    return asker


def changed_at(stub: StubService, ctx: Context, stamp: str) -> None:
    """One chat on the service, last changed at ``stamp``."""
    held = ctx.client.post("/chats", json={"title": "Garden plans"})
    stub.chats[held["id"]]["updated_at"] = stamp


def test_the_head_and_the_selection_show_the_same_time_for_the_same_stamp(
    stub: StubService, ctx: Context, written: Written, listed: Listed
) -> None:
    changed_at(stub, ctx, STAMP)
    here = datetime(2024, 3, 9, 17, 5, tzinfo=UTC).astimezone().strftime("%Y-%m-%d %H:%M")
    ctx.renderer.header("9.8.7", "http://stub.test")
    in_the_head = re.findall(A_TIME, written.text())
    ctx.commands.run("/chats")
    in_the_selection = re.findall(A_TIME, "\n".join(listed.lines()))
    assert in_the_head == in_the_selection == [here]
    # The selection is all the command shows: nothing went into the history.
    assert written.text() == ""


def test_a_stamp_that_is_no_time_stands_as_it_came_in_both(
    stub: StubService, ctx: Context, written: Written, listed: Listed
) -> None:
    changed_at(stub, ctx, "a moment ago")
    ctx.renderer.header("9.8.7", "http://stub.test")
    assert "Garden plans  a moment ago" in written.text()
    ctx.commands.run("/chats")
    assert listed.lines() == ["Garden plans  a moment ago"]


def test_one_function_formats_the_time_for_both() -> None:
    assert chat_actions.local_time is render.local_time
    assert render.local_time(None) == ""
