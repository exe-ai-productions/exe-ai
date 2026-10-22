"""The client's screen is the whole window: the field of the history above
scrolls, the block below it never moves.

The screen is built and run on a stand-in terminal of a size, in a thread of
its own, and what it drew last is read back from the renderer — the rows of
the window as a terminal would show them. Nothing is asked of a service."""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from prompt_toolkit.data_structures import Point
from prompt_toolkit.input import PipeInput, create_pipe_input
from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType

from cli import history_view, render
from cli.app import CliApp, _ScreenOutput as ScreenOutput
from cli.history_view import History, HistoryControl
from tests.cli.program import FULL_COLOURS, Run, in_the_shared_session, run_client, terminal
from tests.cli.stub_service import StubService, eventually
from tests.cli.test_app_scaffold import (
    BLOCK_ROWS,
    ENTER,
    SAFETY_NET_SECONDS,
    Terminal,
    built,
    drawn,
    history_loaded,
    resized_and_seen,
)

PAGE_UP = "\x1b[5~"
PAGE_DOWN = "\x1b[6~"
ARROW_UP = "\x1b[A"
# What a terminal is sent to switch to its second screen, and back.
ENTER_THE_SECOND_SCREEN = "\x1b[?1049h"
LEAVE_THE_SECOND_SCREEN = "\x1b[?1049l"


@contextmanager
def running(tmp_path: Path, terminal: Terminal) -> Iterator[tuple[CliApp, PipeInput]]:
    """The screen, built and running on ``terminal`` in a thread of its own,
    and the input to type into it; left when the test is over."""
    with create_pipe_input() as pipe:
        ready = threading.Event()
        screens: list[CliApp] = []

        def run_the_screen() -> None:
            with in_the_shared_session(pipe, terminal):
                app = built(tmp_path)
                app._app.terminal_size_polling_interval = 0.02
                screens.append(app)
                ready.set()
                app.run()

        thread = threading.Thread(target=run_the_screen, daemon=True)
        thread.start()
        safety_net = threading.Timer(SAFETY_NET_SECONDS, pipe.close)
        safety_net.start()
        try:
            assert ready.wait(SAFETY_NET_SECONDS)
            eventually(lambda: screens[0]._app.is_running and screens[0]._app.renderer._last_screen)
            yield screens[0], pipe
        finally:
            if screens:
                screens[0].exit()
            thread.join(SAFETY_NET_SECONDS)
            safety_net.cancel()
            assert not thread.is_alive()


def drawn_rows(app: CliApp, rows: int, columns: int = 80) -> list[str]:
    """The rows of the window as the screen drew them last, each without the
    blanks behind its text."""
    screen = app._app.renderer._last_screen
    assert screen is not None
    shown = []
    for y in range(rows):
        # Read without creating a cell: the screen's buffer makes one for
        # every place it is asked about, and the renderer compares the next
        # drawing with it.
        cells = screen.data_buffer.get(y)
        shown.append(
            "".join(cells[x].char if cells is not None and x in cells else " " for x in range(columns)).rstrip()
        )
    return shown


def input_row(app: CliApp) -> int:
    """The row of the window the input field stands on."""
    screen = app._app.renderer._last_screen
    assert screen is not None
    return int(screen.visible_windows_to_write_positions[app._input.window].ypos)


def write_lines(app: CliApp, count: int) -> None:
    for number in range(count):
        app.print_above(f"line {number}")


def shows(app: CliApp, rows: int, text: str) -> bool:
    return any(text in row for row in drawn_rows(app, rows))


def shows_in(app: CliApp, rows: int, columns: int, text: str) -> bool:
    return any(text in row for row in drawn_rows(app, rows, columns))


# --- The screen as a whole ----------------------------------------------------------


def test_the_screen_is_a_full_screen_that_takes_the_mouse(tmp_path):
    with create_pipe_input() as pipe, in_the_shared_session(pipe, Terminal()):
        app = built(tmp_path)
        assert app._app.full_screen is True
        assert app._app.mouse_support() is True


def test_the_block_stands_on_the_last_rows_of_the_window_and_the_input_row_is_fixed(tmp_path):
    with running(tmp_path, Terminal(rows=30)) as (app, _):
        # Nothing was written: the history field is empty and the block is
        # on the last rows all the same.
        eventually(lambda: input_row(app) == 30 - BLOCK_ROWS + 2)
        assert drawn_rows(app, 30)[: 30 - BLOCK_ROWS] == [""] * (30 - BLOCK_ROWS)


def test_scrolling_the_history_up_leaves_the_block_where_it_is(tmp_path):
    with running(tmp_path, Terminal(rows=30)) as (app, pipe):
        write_lines(app, 200)
        eventually(lambda: shows(app, 30, "line 199"))
        before = (input_row(app), drawn_rows(app, 30)[-BLOCK_ROWS + 1 :])
        pipe.send_text(PAGE_UP * 3)
        eventually(lambda: not shows(app, 30, "line 199"))
        # The history moved, the block did not: the same row, the same lines.
        assert input_row(app) == before[0]
        assert drawn_rows(app, 30)[-BLOCK_ROWS + 1 :] == before[1]
        # The rows above the block hold the history, row for row.
        history_rows = [row for row in drawn_rows(app, 30 - BLOCK_ROWS) if row]
        assert len(history_rows) == 30 - BLOCK_ROWS


def test_the_wheel_scrolls_the_history_and_a_scrolled_view_stays_where_it_is(tmp_path):
    with running(tmp_path, Terminal(rows=30)) as (app, pipe):
        write_lines(app, 100)
        eventually(lambda: shows(app, 30, "line 99"))
        pipe.send_text(PAGE_UP)
        eventually(lambda: not shows(app, 30, "line 99"))
        top_before = drawn_rows(app, 30 - BLOCK_ROWS)
        # More is written: the scrolled view does not move.
        write_lines(app, 20)
        eventually(lambda: drawn(app))
        assert drawn_rows(app, 30 - BLOCK_ROWS) == top_before
        # Down to the end again: the end follows once more.
        pipe.send_text(PAGE_DOWN * 20)
        eventually(lambda: shows(app, 30, "line 19"))
        write_lines(app, 5)
        eventually(lambda: shows(app, 30, "line 4"))


def test_the_head_stands_at_the_top_and_nothing_is_written_to_fill_the_field(tmp_path):
    with running(tmp_path, Terminal(rows=40, columns=100)) as (app, _):
        render.show_head(app._ctx)
        eventually(lambda: shows_in(app, 40, 100, "Tips to get started"))
        rows = drawn_rows(app, 40, 100)
        # The first row is the empty line the head starts with, the mark
        # follows at once, and the text of the head ends the field's content.
        assert rows[0] == ""
        assert rows[1] != ""
        last = max(number for number, row in enumerate(rows[: 40 - BLOCK_ROWS]) if row)
        assert last < 40 - BLOCK_ROWS - 5
        # No empty lines were written to push the block down: the history
        # ends with the lines of the head, and one empty line at the most.
        written = app.history_text().rstrip("\n").split("\n")
        assert written[-1] != ""
        assert len(app.history_text()) - len(app.history_text().rstrip("\n")) <= 2


def test_a_window_that_grows_or_shrinks_writes_nothing_into_the_history(tmp_path):
    terminal = Terminal(rows=40)
    with running(tmp_path, terminal) as (app, _):
        write_lines(app, 10)
        eventually(lambda: shows(app, 40, "line 9"))
        before = app.history_text()
        for rows in (50, 20, 40):
            resized_and_seen(
                terminal, rows,
                lambda: input_row(app) == rows - BLOCK_ROWS + 2,  # noqa: B023
            )
            assert app.history_text() == before


def test_the_input_grows_into_the_field_and_the_block_stays_on_the_last_row(tmp_path):
    with running(tmp_path, Terminal(rows=30)) as (app, pipe):
        write_lines(app, 100)
        eventually(lambda: shows(app, 30, "line 99"))
        one_line = input_row(app)
        pipe.send_text("one\x1b" + ENTER + "two\x1b" + ENTER + "three")
        eventually(lambda: shows(app, 30, "three"))
        # Two rows more for the field: it starts higher, the block ends on
        # the same last row.
        assert input_row(app) == one_line - 2
        assert drawn_rows(app, 30)[-1] != ""


def test_the_client_runs_on_the_second_screen_of_the_terminal_and_gives_the_first_back(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent, output = terminal(monkeypatch, FULL_COLOURS)

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        run.parts()
        eventually(lambda: stub.watchers == 1)
        eventually(lambda: ENTER_THE_SECOND_SCREEN in sent.getvalue())
        type_in("/quit" + ENTER)

    assert run_client(stub_http, tmp_path, monkeypatch, drive, output=output).code == 0
    shown = sent.getvalue()
    assert shown.index(ENTER_THE_SECOND_SCREEN) < shown.index(LEAVE_THE_SECOND_SCREEN)
    # The mouse is the screen's while it runs, and the terminal has it back.
    assert shown.index("\x1b[?1000h") < shown.index("\x1b[?1000l")


def test_silence_the_arrow_up_key_brings_back_the_last_input_into_the_field(tmp_path):
    with running(tmp_path, Terminal(rows=30)) as (app, pipe):
        # A shell line: no command list opens while it is typed, so the key
        # is the field's and nothing else's.
        pipe.send_text("!true" + ENTER)
        eventually(lambda: list(app._input.buffer.history.get_strings()) == ["!true"])
        eventually(lambda: not app._input.text)
        # The field takes its history up at the next drawing: a key that
        # comes before it would find nothing to go back to.
        eventually(lambda: history_loaded(app))
        pipe.send_text(ARROW_UP)
        eventually(lambda: app._input.text == "!true")


class Capturing(Terminal):
    """A terminal that keeps what the screen writes raw."""

    def __init__(self) -> None:
        super().__init__()
        self.raw: list[str] = []

    def write_raw(self, data: str) -> None:
        self.raw.append(data)


def test_what_the_program_writes_to_standard_output_while_the_screen_runs_goes_through_the_screen(
    tmp_path,
):
    terminal_ = Capturing()
    with running(tmp_path, terminal_) as (app, _):
        sys.stdout.write("\x1b]11;#101010\x1b\\")
        eventually(lambda: any("\x1b]11;#101010" in data for data in terminal_.raw))
        assert sys.stdout.encoding == app._app.output.encoding()
    # Back to the program's own output once the screen has left.
    assert not isinstance(sys.stdout, ScreenOutput)


# --- The history field on its own ---------------------------------------------------


def lines_of(rows: list[list[history_view.Run]]) -> list[str]:
    return ["".join(run.text for run in row) for row in rows]


def test_the_field_reads_the_lines_of_a_piece_and_sets_them_to_the_width():
    history = History()
    history.add("one\ntwo words here\n")
    assert lines_of(history.rows(8, 10)) == ["one", "two word", "s here"]
    assert lines_of(history.rows(40, 10)) == ["one", "two words here"]


def test_a_wide_sign_at_the_last_cell_goes_to_the_next_row():
    history = History()
    history.add("abc漢\n")
    assert lines_of(history.rows(4, 10)) == ["abc", "漢"]


def test_the_field_starts_at_the_top_and_leaves_the_rest_empty():
    history = History()
    history.add("one\ntwo\n")
    assert lines_of(history.rows(20, 10)) == ["one", "two"]


def test_the_colours_of_a_piece_are_kept_in_the_runs():
    history = History()
    history.add("\x1b[38;2;10;20;30mred\x1b[0m plain\n")
    (row,) = history.rows(40, 5)
    assert [run.text for run in row] == ["red", " plain"]
    assert row[0].style != row[1].style
    assert "#0a141e" in row[0].style


def test_a_link_stays_a_link_across_the_rows_it_is_wrapped_in():
    history = History()
    history.add("see \x1b]8;id=1;https://x.test/a\x1b\\https://x.test/a\x1b]8;;\x1b\\ end\n")
    rows = history.rows(10, 5)
    linked = "".join(run.text for row in rows for run in row if run.link == "https://x.test/a")
    assert linked == "https://x.test/a"
    # The letters of the sequences are no part of the text.
    assert "8;" not in "".join(lines_of(rows))


def test_the_field_follows_the_end_until_it_is_scrolled_and_follows_again_at_the_end():
    history = History()
    for number in range(30):
        history.add(f"line {number}\n")
    assert lines_of(history.rows(20, 10))[-1] == "line 29"
    history.scroll(-5)
    assert lines_of(history.rows(20, 10))[-1] == "line 24"
    history.add("line 30\n")
    assert lines_of(history.rows(20, 10))[-1] == "line 24"
    history.scroll(100)
    assert history.follows_the_end()
    assert lines_of(history.rows(20, 10))[-1] == "line 30"


def test_emptied_the_field_holds_nothing_and_the_next_piece_stands_at_the_top():
    history = History()
    history.add("old\n")
    history.clear()
    assert history.rows(20, 10) == []
    history.add("new\n")
    assert lines_of(history.rows(20, 10)) == ["new"]


def mouse(kind: MouseEventType, x: int = 0, y: int = 0) -> MouseEvent:
    return MouseEvent(Point(x, y), kind, MouseButton.LEFT, frozenset())


def test_a_click_on_an_address_opens_it_and_a_click_elsewhere_opens_nothing():
    history = History()
    history.add("go \x1b]8;;https://x.test/a\x1b\\here\x1b]8;;\x1b\\ now\n")
    opened: list[str] = []
    control = HistoryControl(history, lambda: None, opened.append)
    control.create_content(40, 5)
    assert control.mouse_handler(mouse(MouseEventType.MOUSE_UP, x=4, y=0)) is None
    assert opened == ["https://x.test/a"]
    assert control.mouse_handler(mouse(MouseEventType.MOUSE_UP, x=1, y=0)) is NotImplemented
    assert control.mouse_handler(mouse(MouseEventType.MOUSE_UP, x=0, y=3)) is NotImplemented
    assert opened == ["https://x.test/a"]


def test_once_the_pieces_are_not_kept_the_history_is_held_as_lines_only():
    history = History()
    history.add("\x1b[31mred\x1b[0m\nsecond")
    assert history.text() == "\x1b[31mred\x1b[0m\nsecond"
    history.keep_no_pieces()
    assert history.text() == "red\nsecond\n"
    history.add("third\n")
    assert history.text() == "red\nsecond\nthird\n"
    assert history._pieces == []


def test_only_the_left_button_opens_an_address():
    history = History()
    history.add("go \x1b]8;;https://x.test/a\x1b\\here\x1b]8;;\x1b\\ now\n")
    opened: list[str] = []
    control = HistoryControl(history, lambda: None, opened.append)
    control.create_content(40, 5)
    for button in (MouseButton.RIGHT, MouseButton.MIDDLE):
        event = MouseEvent(Point(4, 0), MouseEventType.MOUSE_UP, button, frozenset())
        assert control.mouse_handler(event) is NotImplemented
    assert opened == []


def test_the_wheel_scrolls_the_field_by_rows():
    history = History()
    for number in range(30):
        history.add(f"line {number}\n")
    changed: list[bool] = []
    control = HistoryControl(history, lambda: changed.append(True))
    control.create_content(20, 10)
    control.mouse_handler(mouse(MouseEventType.SCROLL_UP))
    assert lines_of(history.rows(20, 10))[-1] == f"line {29 - history_view.WHEEL_ROWS}"
    control.mouse_handler(mouse(MouseEventType.SCROLL_DOWN))
    assert history.follows_the_end()
    assert changed == [True, True]


@pytest.mark.parametrize("address", ["file:///etc/passwd", "javascript:alert(1)", "ftp://x.test"])
def test_only_web_addresses_are_opened(address, monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    history_view.open_in_browser(address)
    assert opened == []


def test_a_web_address_is_opened_in_the_browser_of_the_system(monkeypatch):
    done = threading.Event()
    opened: list[str] = []

    def record(address: str) -> bool:
        opened.append(address)
        done.set()
        return True

    monkeypatch.setattr("webbrowser.open", record)
    history_view.open_in_browser("https://x.test/a")
    assert done.wait(SAFETY_NET_SECONDS)
    assert opened == ["https://x.test/a"]


def test_silence_a_client_that_ends_before_its_screen_ran_writes_its_history_out(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with create_pipe_input() as pipe, in_the_shared_session(pipe, Terminal()):
        app = built(tmp_path)
        app.print_above("what went wrong")
        assert capsys.readouterr().out == ""
        app.show_unseen()
        assert "what went wrong" in capsys.readouterr().out


def test_silence_nothing_is_written_out_after_the_screen_ran(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    holder: dict[str, Any] = {}
    with running(tmp_path, Terminal()) as (app, _):
        app.print_above("shown in the field")
        holder["app"] = app
    holder["app"].show_unseen()
    assert "shown in the field" not in capsys.readouterr().out
