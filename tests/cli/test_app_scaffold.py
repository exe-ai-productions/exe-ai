"""The scaffold as a whole: it starts against a service, shows its head,
takes commands and lines from the input field and ends — without a
terminal and without a service, on a pipe and a stand-in transport."""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from prompt_toolkit.application import create_app_session, get_app_session
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput, Output
from prompt_toolkit.utils import get_cwidth
from rich.table import Table
from rich.text import Text

from prompt_toolkit.layout.screen import WritePosition

from cli import chat, commands, dialogs, events, glyphs, prefs, themes
from cli.app import (
    COMPLETION_ROWS,
    EMPTY_WINDOW,
    MAX_INPUT_LINES,
    STATUS_LINES,
    CliApp,
    _without_trailing_blanks,
)
from cli.client import KEY_HEADER, ServiceClient
from cli.interfaces import Context
from cli.main import main
from cli.render import build_renderer, clock, split_blocks
from cli.status import build_status
from cli.texts import Texts
from stub_service import eventually, foreground, noted
from tests.cli.program import Run, a_session_without_the_console, local_clock, run_client
from tests.cli.stub_service import StubService
from test_shell import SLEEP_RUNS, STARTS_A_SLEEP
from test_stream import shown_text, typed_line, where

# What the status lines read from the service after every line the user
# sent, and once at start; never counted where a test counts requests.
STATUS_PATHS = ("/api/v1/settings/resolved", "/api/v1/tools")

KEY = "key-of-this-run"
# What a new chat goes by until the service has it.
FRESH_TITLE = Texts("en").t("chat.unbenannt")
PAGE = f'<html><head><script>window.__SITZUNGSSCHLUESSEL__="{KEY}";</script></head></html>'
ENTER = "\r"

# If a run never leaves by itself, the input is closed after this many
# seconds: the test then fails on what it asserts instead of hanging.
SAFETY_NET_SECONDS = 20


class Service:
    """The addresses the scaffold talks to, and every request kept. The
    chats it lists in the head are given to it; by default there are none."""

    def __init__(
        self,
        models: list[dict] | None = None,
        chats: list[dict[str, Any]] | None = None,
        last_model: str | None = None,
    ) -> None:
        self.seen: list[httpx.Request] = []
        self.models = (
            [{"id": "local", "name": "Local Model", "erreichbar": True, "context_tokens": 8192}]
            if models is None
            else models
        )
        self.chats = chats
        # The model chosen last, as the service keeps it; ``None`` and the
        # service knows no such setting.
        self.last_model = last_model

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(noted(request))
        path = request.url.path
        if path == "/app/":
            return httpx.Response(200, text=PAGE)
        if request.headers.get(KEY_HEADER) != KEY:
            return httpx.Response(401, json={"detail": "Invalid or missing session key"})
        if path == "/api/v1/health":
            return httpx.Response(200, json={"status": "ok", "version": "9.8.7"})
        if path == "/api/v1/models":
            # The full list on request, else the models that answer.
            listed = [
                entry
                for entry in self.models
                if entry.get("erreichbar") or request.url.params.get("alle")
            ]
            return httpx.Response(200, json=listed)
        if path == "/api/v1/chats" and request.method == "POST":
            wanted = json.loads(request.content)
            return httpx.Response(
                201, json={"id": "chat-1", "title": "A fresh chat", **wanted}
            )
        if path == "/api/v1/chats" and self.chats is not None:
            return httpx.Response(200, json=self.chats)
        if (
            path == "/api/v1/settings/resolved"
            and request.url.params.get("keys") == commands.LAST_MODEL_KEY
            and self.last_model
        ):
            return httpx.Response(
                200,
                json={commands.LAST_MODEL_KEY: {"wert": {"id": self.last_model}, "herkunft": "global"}},
            )
        return httpx.Response(404, json={"detail": "No such address"})

    def paths(self) -> list[str]:
        return [
            f"{request.method} {request.url.path}"
            for request in self.seen
            if foreground(request) and request.url.path not in STATUS_PATHS
        ]


class Terminal(DummyOutput):
    """An output that knows where its cursor stands, the way a terminal
    does: every line written moves it down, to the last row at most — below
    that the terminal scrolls — the screen's own cursor moves move it too,
    and what empties the window puts it on the first row. What is written
    is dropped, except the runs of empty lines that push the block down:
    those are kept, each by its length. How many rows the content went up
    by, because a line was written below the last row, is counted. The
    window can change its height while the client runs."""

    def __init__(self, columns: int = 80, rows: int = 40) -> None:
        self.columns, self.rows = columns, rows
        self.row = 0
        self.pushes: list[int] = []
        # How many rows the window's content was moved down by, each time.
        self.shifts: list[int] = []
        self.scrolled = 0

    def get_size(self) -> Size:
        return Size(rows=self.rows, columns=self.columns)

    def get_rows_below_cursor_position(self) -> int:
        return self.rows - self.row

    def write(self, data: str) -> None:
        self.write_raw(data)

    def write_raw(self, data: str) -> None:
        if data and not data.strip("\n"):
            self.pushes.append(len(data))
        for run in re.findall(r"\x1b\[H((?:\x1bM)+)", data):
            self.shifts.append(len(run) // 2)
        for row in re.findall(r"\x1b\[(\d+);1H", data):
            self.row = min(self.rows - 1, int(row) - 1)
        _, emptied, data = data.rpartition(EMPTY_WINDOW)
        if emptied:
            self.row = 0
        moved = self.row + data.count("\n")
        self.scrolled += max(0, moved - (self.rows - 1))
        self.row = min(self.rows - 1, moved)

    def cursor_up(self, amount: int) -> None:
        self.row = max(0, self.row - amount)

    def cursor_down(self, amount: int) -> None:
        self.row = min(self.rows - 1, self.row + amount)

    def cursor_goto(self, row: int = 0, column: int = 0) -> None:
        self.row = row

    def resize(self, rows: int) -> None:
        """The window gets ``rows`` rows; a cursor below the new bottom
        stands on the last row, the content above it having scrolled."""
        self.rows = rows
        self.row = min(self.row, rows - 1)


def run(
    typed: str,
    *arguments: str,
    service: Service | None = None,
    tmp_path: Path,
    output: Output | None = None,
) -> int:
    """Starts the client with ``typed`` already waiting in its input."""
    service = service or Service()
    with create_pipe_input() as pipe:
        pipe.send_text(typed)
        safety_net = threading.Timer(SAFETY_NET_SECONDS, pipe.close)
        safety_net.start()
        try:
            with create_app_session(input=pipe, output=output or DummyOutput()):
                return main(
                    ["--url", "http://service.test", "--lang", "en", *arguments],
                    http=httpx.Client(transport=httpx.MockTransport(service)),
                    prefs_path=tmp_path / "cli.json",
                )
        finally:
            safety_net.cancel()


def recorded(
    typed: str,
    *arguments: str,
    service: Service | None = None,
    tmp_path: Path,
    output: Output | None = None,
) -> str:
    """The same, and afterwards the plain text of everything shown — read
    back from an export of the history, written once the client has left."""
    parts: list[Context] = []
    built = events.build_events

    def remember(ctx: Context) -> Any:
        parts.append(ctx)
        return built(ctx)

    events.build_events = remember
    try:
        assert run(typed, *arguments, service=service, tmp_path=tmp_path, output=output) == 0
    finally:
        events.build_events = built
    target = tmp_path / "shown.html"
    parts[0].screen.export(target)
    return shown_text(target.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def the_default_look():
    yield
    themes.set_look(themes.DEFAULT_LOOK)


def test_quit_is_taken_and_the_client_ends(tmp_path):
    service = Service()
    assert run("/quit" + ENTER, service=service, tmp_path=tmp_path) == 0
    assert service.paths() == [
        "GET /app/",
        "GET /api/v1/health",
        "GET /api/v1/models",
        # The head: how many tools run without asking, and the newest chats.
        "GET /api/v1/permissions/always-allow",
        "GET /api/v1/chats",
        # And no chat is created: nothing was written into the new one.
    ]


def test_help_writes_the_commands_into_the_history(tmp_path):
    shown = recorded("/help" + ENTER + "/quit" + ENTER, tmp_path=tmp_path)
    listed = [line for line in shown.splitlines() if not line.startswith(glyphs.glyph("prompt"))]
    # Each command stands in a line of its own, with something said about it.
    for name in ("/help", "/quit"):
        row = next(line for line in listed if line.strip().startswith(name))
        assert row.strip() != name


def test_the_head_names_the_services_version_and_its_address(tmp_path):
    shown = recorded("/quit" + ENTER, tmp_path=tmp_path)
    lines = shown.splitlines()
    # The head is what stands above the first line the user sent.
    head = "\n".join(lines[: lines.index(typed_line("/quit"))])
    assert "9.8.7" in head
    assert "http://service.test" in head


def test_the_status_line_shows_the_chats_title_and_the_model_behind_it(tmp_path):
    shown = recorded("/quit" + ENTER, tmp_path=tmp_path)
    status = next(line for line in shown.splitlines() if FRESH_TITLE in line)
    assert status.startswith(f"{glyphs.glyph('line_chat')} {FRESH_TITLE}")
    assert "Local Model" in status


def test_the_new_chat_is_created_with_the_first_model_the_service_lists(tmp_path):
    # This stand-in knows no model chosen last: the service does not say.
    service = Service()
    run("Hello there" + ENTER + "/quit" + ENTER, service=service, tmp_path=tmp_path)
    created = next(request for request in service.seen if request.method == "POST")
    assert created.url.path == "/api/v1/chats"
    assert json.loads(created.content) == {"endpoint_id": "local"}


def test_a_new_chat_and_no_message_leave_the_service_without_a_chat(tmp_path):
    """Started, a new chat asked for twice, and left: nothing was written,
    so the service was never asked to create a chat."""
    service = Service()
    assert run("/new" + ENTER + "/new" + ENTER + "/quit" + ENTER, service=service, tmp_path=tmp_path) == 0
    assert not [request for request in service.seen if request.method == "POST"]


TWO_MODELS = [
    {"id": "local", "name": "Local Model", "erreichbar": True, "context_tokens": 8192},
    {"id": "remote", "name": "Remote Model", "erreichbar": True, "context_tokens": 200000},
]


def test_the_model_chosen_last_is_the_one_the_first_message_goes_to(tmp_path):
    service = Service(models=TWO_MODELS, last_model="remote")
    shown = recorded("Hello there" + ENTER + "/quit" + ENTER, service=service, tmp_path=tmp_path)
    created = next(request for request in service.seen if request.method == "POST")
    assert json.loads(created.content) == {"endpoint_id": "remote"}
    # The status line names it, behind the chat's title.
    status = next(line for line in shown.splitlines() if FRESH_TITLE in line)
    assert "Remote Model" in status and "Local Model" not in status


def test_the_head_names_the_model_chosen_last_like_the_status_line(tmp_path):
    service = Service(models=TWO_MODELS, last_model="remote")
    shown = recorded("/quit" + ENTER, service=service, tmp_path=tmp_path)
    lines = shown.splitlines()
    stand = next(line for line in lines if line.startswith("CLI 9.8.7"))
    status = next(line for line in lines if FRESH_TITLE in line)
    assert "Remote Model" in stand and "Local Model" not in stand
    assert "Remote Model" in status


def test_a_model_chosen_last_that_the_service_no_longer_lists_leaves_the_first(tmp_path):
    service = Service(models=TWO_MODELS, last_model="gone")
    shown = recorded("/quit" + ENTER, service=service, tmp_path=tmp_path)
    status = next(line for line in shown.splitlines() if FRESH_TITLE in line)
    assert "Local Model" in status
    # Nothing is said about it.
    assert not any(glyphs.glyph("error") in line for line in shown.splitlines())
    # And the first message creates the chat with the first model.
    service = Service(models=TWO_MODELS, last_model="gone")
    run("Hello there" + ENTER + "/quit" + ENTER, service=service, tmp_path=tmp_path)
    created = next(request for request in service.seen if request.method == "POST")
    assert json.loads(created.content) == {"endpoint_id": "local"}


def test_without_a_reachable_model_the_chat_is_created_without_one(tmp_path):
    # A provider is entered, and it does not answer: nothing is left to set up.
    service = Service(models=[{"id": "gone", "name": "Gone Model", "erreichbar": False}])
    shown = recorded("Hello there" + ENTER + "/quit" + ENTER, service=service, tmp_path=tmp_path)
    created = next(request for request in service.seen if request.method == "POST")
    assert json.loads(created.content) == {}
    status = next(line for line in shown.splitlines() if FRESH_TITLE in line)
    assert status.startswith(f"{glyphs.glyph('line_chat')} {FRESH_TITLE}")
    assert "Local Model" not in status


def test_any_other_line_stands_in_the_history_and_goes_to_the_open_chat(tmp_path):
    service = Service()
    shown = recorded("Hello there" + ENTER + "/quit" + ENTER, service=service, tmp_path=tmp_path)
    lines = shown.splitlines()
    # Once in the input field, once more as a line of the history.
    assert sum("Hello there" in line for line in lines) == 2
    assert typed_line("Hello there") in lines
    sent = next(request for request in service.seen if request.url.path.endswith("/chat/completions"))
    assert json.loads(sent.content) == {
        "chat_id": "chat-1",
        "content": "Hello there",
        "endpoint_id": "local",
    }
    # This stand-in knows no such address; its refusal is shown, not swallowed.
    assert any("No such address" in line for line in lines)


@pytest.mark.skipif(sys.platform == "win32", reason="the shell of the test is a POSIX one")
def test_a_line_with_the_shell_mark_runs_in_the_shell_and_never_reaches_the_service(tmp_path):
    service = Service()
    shown = recorded(
        "!echo hi there" + ENTER + "!false" + ENTER + "/quit" + ENTER,
        service=service,
        tmp_path=tmp_path,
    )
    lines = shown.splitlines()
    # What the command printed stands in the history as a line of its own,
    # behind the line that was typed. (The three lines go in at once here,
    # so their blocks are recorded before the worker reaches the first.)
    typed = lines.index(typed_line("!echo hi there"))
    assert lines[where(lines, "hi there", after=typed)] == "hi there"
    # A return code other than zero is named; nothing went to the chat.
    assert Texts("en").t("cli.shell_exit", code=1) in shown
    assert "POST /api/v1/chat/completions" not in service.paths()


@pytest.mark.skipif(sys.platform == "win32", reason="the shell of the test is a POSIX one")
def test_the_interrupt_key_ends_a_running_shell_command_and_not_the_client(tmp_path):
    app = built(tmp_path)
    left: list[bool] = []
    app.exit = lambda: left.append(True)  # type: ignore[method-assign]
    # What the command prints is noted on its way into the history: the key
    # is pressed once the command has said that what it started is running.
    printed = []
    into_the_history = app._ctx.renderer.shell_line

    def kept(text: str) -> None:
        printed.append(text)
        into_the_history(text)

    app._ctx.renderer.shell_line = kept  # type: ignore[method-assign]

    def the_sleep_runs() -> bool:
        return printed == [SLEEP_RUNS]

    worker = threading.Thread(target=app._do, args=(STARTS_A_SLEEP,), daemon=True)
    worker.start()
    eventually(the_sleep_runs)
    app._on_interrupt(None)  # type: ignore[arg-type]
    worker.join(SAFETY_NET_SECONDS)
    assert not worker.is_alive()
    # The command is gone, the client stays, and the history says so.
    assert left == []
    page = tmp_path / "shown.html"
    app.export(page)
    shown = shown_text(page.read_text(encoding="utf-8"))
    assert Texts("en").t("cli.shell_stopped") in shown and "never" not in shown
    # With nothing running, the key leaves as before.
    app._on_interrupt(None)  # type: ignore[arg-type]
    assert left == [True]


def test_an_unknown_command_is_answered_and_never_sent(tmp_path):
    service = Service()
    shown = recorded("/nope now" + ENTER + "/quit" + ENTER, service=service, tmp_path=tmp_path)
    assert Texts("en").t("cli.unbekannt", name="nope") in shown
    assert not [request for request in service.seen if request.method == "POST"]


def test_what_the_user_typed_is_recorded_with_the_fixed_block_around_it(tmp_path):
    shown = recorded("/help" + ENTER + "/quit" + ENTER, tmp_path=tmp_path)
    lines = shown.splitlines()
    typed = lines.index(typed_line("/help"))
    rule = {glyphs.glyph("rule")}
    # A rule above and below the typed line, the two status lines below the
    # lower rule: the chat's line first, the mode's line with the connection
    # second.
    assert set(lines[typed - 1]) == rule and set(lines[typed + 1]) == rule
    assert lines[typed + 2].startswith(f"{glyphs.glyph('line_chat')} {FRESH_TITLE}")
    assert lines[typed + 3].startswith(glyphs.glyph("line_mode"))
    words = Texts("en")
    states = (words.t("cli.connected"), words.t("cli.reconnecting"), words.t("cli.disconnected"))
    assert lines[typed + 3].rstrip().endswith(states)
    # The third status line: the context, with the bar and the count.
    assert lines[typed + 4].startswith(words.t("cli.context_label"))
    assert lines[typed + 4].rstrip().endswith("/8192")


# --- The notice above the input field -----------------------------------------------


def hint_shown(app: CliApp) -> str:
    """The line above the input field as the block draws it."""
    return "".join(text for _, text in app._activity_fragments())


def test_a_notice_stands_above_the_field_without_the_spinner_and_never_in_the_history(tmp_path):
    app = built(tmp_path)
    # Without a notice the line is empty.
    assert app.hint_line() == "" and hint_shown(app) == ""
    app.set_notice("One word")
    assert app.hint_line() == "One word"
    drawn = hint_shown(app)
    assert drawn.endswith("One word")
    assert not any(frame in drawn for frame in glyphs.spinner_frames())
    # The next notice takes the place of the one before; one of several
    # lines gets a row for each.
    app.set_notice("Another word\nand one more")
    assert app.hint_line() == "Another word\nand one more"
    assert app._activity_height() == 2
    # The next line sent takes it away.
    app.submit("/help")
    assert app.hint_line() == "" and hint_shown(app) == ""
    # Neither stood in the history.
    page = tmp_path / "shown.html"
    app.export(page)
    shown = shown_text(page.read_text(encoding="utf-8"))
    assert "One word" not in shown and "Another word" not in shown
    assert typed_line("/help") in shown.splitlines()


def test_while_something_runs_the_activity_stands_in_front_of_the_notice(tmp_path):
    app = built(tmp_path)
    app.set_notice("A word")
    app.set_activity("Thinking")
    assert app.hint_line() == "Thinking"
    drawn = hint_shown(app)
    assert any(frame in drawn for frame in glyphs.spinner_frames())
    # Once it is over, the notice stands there again.
    app.set_activity(None)
    assert app.hint_line() == "A word"


def test_a_commands_word_stands_above_the_field_and_not_in_the_history(tmp_path):
    shown = recorded("/new" + ENTER + "/quit" + ENTER, tmp_path=tmp_path)
    assert Texts("en").t("cli.chat_neu") not in shown
    assert typed_line("/new") in shown.splitlines()


# --- The height of the input field -------------------------------------------------


def built(tmp_path: Path) -> CliApp:
    """The screen, built and not running, with its parts wired to the
    stand-in service — on the session's output, which is eighty columns
    and forty rows wide."""
    client = ServiceClient(
        "http://service.test", "en", http=httpx.Client(transport=httpx.MockTransport(Service()))
    )
    client.connect()
    ctx = Context(client=client, texts=Texts("en"), prefs_path=tmp_path / "cli.json")
    ctx.status = build_status(ctx)
    ctx.renderer = build_renderer(ctx)
    ctx.asker = dialogs.build_asker(ctx)
    ctx.commands = commands.build_commands(ctx)
    with a_session_without_the_console():
        app = CliApp(ctx)
    # Wired the way the client wires it: a command that leaves reaches
    # this screen and not the one the context started with.
    ctx.screen = app
    return app


def rows_of(app: CliApp, typed: str) -> tuple[int, int, int]:
    """How many rows the hint line, the input field and the status lines
    get when the block is handed far more rows than it asks for — forty, as
    a terminal whose cursor stands at the top hands it. Read off the
    block's own division of the rows, the way the screen draws it."""
    app._input.buffer.text = typed
    block = app._app.layout.container
    sizes = block._divide_heights(WritePosition(0, 0, 80, 40))
    assert sizes is not None
    children = block._all_children
    # The question above the field comes first and is hidden; then the
    # hint line; the status lines are the last part of the block.
    hint = sizes[children.index(block.children[1])]
    field = sizes[children.index(app._input.window)]
    lines = sizes[children.index(block.children[-1])]
    return hint, field, lines


def test_the_input_field_takes_as_many_rows_as_its_text_and_no_more(tmp_path):
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        app = built(tmp_path)
        assert rows_of(app, "")[1] == 1
        assert rows_of(app, "one\ntwo\nthree")[1] == 3
        assert rows_of(app, "\n".join(str(number) for number in range(9)))[1] == MAX_INPUT_LINES
        # Emptied again, it shrinks back.
        assert rows_of(app, "")[1] == 1


# In a window of forty columns the mark takes two, the text thirty-eight.
NARROW_COLUMNS = 40
ROW_OF_TEXT = NARROW_COLUMNS - 2
# A sign the screen draws two cells wide.
WIDE_SIGN = "\U0001F600"
# A sign every terminal draws two cells wide.
WIDE_IN_EVERY_FONT = "\u6f22"


def test_a_line_that_fills_its_row_takes_one_row_more_for_the_cursor_behind_it(tmp_path):
    with create_pipe_input() as pipe, create_app_session(
        input=pipe, output=Terminal(columns=NARROW_COLUMNS)
    ):
        app = built(tmp_path)
        assert rows_of(app, "x" * ROW_OF_TEXT)[1] == 2
        assert rows_of(app, "x" * (2 * ROW_OF_TEXT))[1] == 3
        # In a text of several lines every line that fills its row does.
        assert rows_of(app, "x" * ROW_OF_TEXT + "\n" + "x" * ROW_OF_TEXT)[1] == 4


def test_a_line_one_sign_short_of_its_row_takes_no_row_for_the_cursor(tmp_path):
    """Silence probe: the row is added only where the text leaves the
    cursor no cell."""
    with create_pipe_input() as pipe, create_app_session(
        input=pipe, output=Terminal(columns=NARROW_COLUMNS)
    ):
        app = built(tmp_path)
        assert rows_of(app, "")[1] == 1
        assert rows_of(app, "x" * (ROW_OF_TEXT - 1))[1] == 1
        assert rows_of(app, "x" * (ROW_OF_TEXT + 1))[1] == 2
        assert rows_of(app, "x" * (2 * ROW_OF_TEXT - 1))[1] == 2
        # More than the limit stays the limit, with the cursor's row or without.
        assert rows_of(app, "x" * (MAX_INPUT_LINES * ROW_OF_TEXT))[1] == MAX_INPUT_LINES
        assert rows_of(app, "x" * (MAX_INPUT_LINES * ROW_OF_TEXT - 1))[1] == MAX_INPUT_LINES
        assert rows_of(app, "x" * (20 * ROW_OF_TEXT))[1] == MAX_INPUT_LINES


def test_a_wide_sign_that_meets_the_last_cell_of_a_row_goes_to_the_next_row(tmp_path):
    """The cells alone say two rows: one letter and thirty-seven wide signs
    are seventy-five cells, and the cursor's makes seventy-six. The first
    row ends one cell early, so the cursor's cell needs a third row."""
    with create_pipe_input() as pipe, create_app_session(
        input=pipe, output=Terminal(columns=NARROW_COLUMNS)
    ):
        app = built(tmp_path)
        assert rows_of(app, "a" + WIDE_SIGN * (ROW_OF_TEXT - 1))[1] == 3
        # Wide signs alone fill every row to its last cell.
        assert rows_of(app, WIDE_SIGN * (ROW_OF_TEXT // 2 - 1))[1] == 1
        assert rows_of(app, WIDE_SIGN * (ROW_OF_TEXT // 2))[1] == 2
        # A control sign stands as two signs: nineteen of them fill the row.
        assert rows_of(app, "\t" * (ROW_OF_TEXT // 2 - 1))[1] == 1
        assert rows_of(app, "\t" * (ROW_OF_TEXT // 2))[1] == 2


def cursor_in_field(app: CliApp) -> bool:
    """Whether the cursor of the running screen stands on one of the rows
    the input field was drawn in the last time."""
    screen = app._app.renderer.last_rendered_screen
    field = app._input.window
    if screen is None or field not in screen.visible_windows_to_write_positions:
        return False
    place = screen.visible_windows_to_write_positions[field]
    return place.ypos <= screen.get_cursor_position(field).y < place.ypos + place.height


def put_in_field(app: CliApp, typed: str, cursor: int | None = None) -> None:
    """Sets the field of the running screen to ``typed`` with the cursor at
    ``cursor`` — behind the text where none is named — and waits until the
    screen has drawn that."""
    place = len(typed) if cursor is None else cursor
    drawn = threading.Event()

    def put() -> None:
        app._input.buffer.text = typed
        app._input.buffer.cursor_position = place
        app._app.after_render += lambda _: drawn.set()
        app._app.invalidate()

    # The screen is handed over as soon as it is built; what is to happen
    # on its thread has to wait until it runs.
    eventually(lambda: app._app.is_running and app._app.loop is not None)
    app._on_screen_thread(put)
    assert drawn.wait(SAFETY_NET_SECONDS)
    eventually(lambda: app._input.buffer.cursor_position == place)


@pytest.mark.parametrize("signs", [ROW_OF_TEXT, 2 * ROW_OF_TEXT, 3 * ROW_OF_TEXT])
def test_behind_a_line_that_fills_its_row_the_cursor_stands_in_the_field(tmp_path, signs):
    with running(tmp_path, Terminal(columns=NARROW_COLUMNS)) as app:
        put_in_field(app, "x" * signs)
        eventually(lambda: cursor_in_field(app))


@pytest.mark.parametrize(
    "typed",
    [
        "x" * (MAX_INPUT_LINES * ROW_OF_TEXT),
        "x" * (10 * ROW_OF_TEXT),
        "x" * (10 * ROW_OF_TEXT + 5),
    ],
)
def test_in_a_line_taller_than_the_field_the_cursor_stays_in_the_field_wherever_it_goes(
    tmp_path, typed
):
    """The field shows a part of such a line. On the first cell of a row —
    behind a text that fills its last row, or on the way through it — the
    part used to end one row above the cursor."""
    with running(tmp_path, Terminal(columns=NARROW_COLUMNS)) as app:
        # Behind the text, then back to its beginning and forth again, row
        # by row: at every beginning of a row and in the middle of it.
        ends = [signs for signs in range(0, len(typed) + 1, ROW_OF_TEXT)] + [len(typed)]
        places = sorted({place for end in ends for place in (end, max(0, end - 7))})
        for place in [len(typed), *reversed(places), *places]:
            put_in_field(app, typed, place)
            eventually(lambda: cursor_in_field(app))


def test_in_a_window_too_low_for_the_whole_field_the_cursor_stays_in_the_rows_it_gets(tmp_path):
    """Ten rows for a block that asks for fourteen: the field is drawn in
    four rows instead of eight, and the part of the line it shows goes by
    those four."""
    typed = "x" * (10 * ROW_OF_TEXT)
    with running(tmp_path, Terminal(columns=NARROW_COLUMNS, rows=10)) as app:
        for place in [len(typed), *range(len(typed), -1, -ROW_OF_TEXT), *range(0, len(typed) + 1, ROW_OF_TEXT)]:
            put_in_field(app, typed, place)
            eventually(lambda: cursor_in_field(app))
        field = app._input.window.render_info
        assert field is not None and field.window_height == 10 - (BLOCK_ROWS - 1)


def test_the_hint_line_and_the_status_lines_keep_their_height_whatever_is_typed(tmp_path):
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        app = built(tmp_path)
        for typed in ("", "one\ntwo\nthree", "\n".join(str(number) for number in range(9))):
            hint, _, lines = rows_of(app, typed)
            assert (hint, lines) == (1, STATUS_LINES) == (1, 3)


# --- The block on the last rows of the window -----------------------------------

# The block at the start: the hint line, a rule, one line of input, a rule
# and the status lines.
BLOCK_ROWS = 1 + 1 + 1 + 1 + STATUS_LINES

# How often the running screen looks at the size of its window, in seconds.
SIZE_POLL_SECONDS = 0.02


@contextmanager
def running(tmp_path: Path, terminal: Terminal) -> Iterator[CliApp]:
    """The screen, built and running on ``terminal`` in a thread of its
    own, so a test can change the window and look at what happens; it is
    left when the test is over.

    It runs in the session every thread shares, as the client does at a
    terminal — not in one of its own, which only the thread that made it
    would see. What the client writes into the history reaches the output
    from a thread of the output's own; only where that thread finds the
    running screen is the block taken off for a piece, the piece written
    and the block drawn again below it, measured anew."""
    with create_pipe_input() as pipe:
        ready = threading.Event()
        screens: list[CliApp] = []

        def run_the_screen() -> None:
            # A thread that made no session of its own stands in the shared
            # one; it is lent the pipe and the terminal for this run.
            shared = get_app_session()
            former = shared._input, shared._output
            shared._input, shared._output = pipe, terminal
            try:
                app = built(tmp_path)
                app._app.terminal_size_polling_interval = SIZE_POLL_SECONDS
                screens.append(app)
                ready.set()
                app.run()
            finally:
                shared._input, shared._output = former

        if hasattr(terminal, "bind_input"):
            terminal.bind_input(pipe)
        thread = threading.Thread(target=run_the_screen, daemon=True)
        thread.start()
        # A screen that never leaves gets its input closed, so the test
        # fails on what it asserts and leaves no running screen behind.
        safety_net = threading.Timer(SAFETY_NET_SECONDS, pipe.close)
        safety_net.start()
        try:
            assert ready.wait(SAFETY_NET_SECONDS)
            yield screens[0]
        finally:
            if screens:
                screens[0].exit()
            thread.join(SAFETY_NET_SECONDS)
            safety_net.cancel()
            assert not thread.is_alive()


def settled() -> None:
    """Long enough for the screen to have looked at its window more than
    once, so it has seen a change of it and drawn again."""
    time.sleep(SIZE_POLL_SECONDS * 10)


def test_the_block_is_pushed_to_the_last_rows_at_start_when_the_window_grows_and_after_a_clear(
    tmp_path,
):
    terminal = Terminal(rows=40)
    with running(tmp_path, terminal) as app:
        # The terminal hands the block every row below the cursor, which
        # stands at the top: as many empty lines go above it as leave it
        # the last rows alone.
        eventually(lambda: terminal.pushes == [40 - BLOCK_ROWS])
        assert terminal.pushes == [33]
        # Ten rows more at the bottom: ten more empty lines.
        settled()
        terminal.resize(50)
        eventually(lambda: terminal.pushes == [33, 10])
        # Ten rows fewer: the terminal cut them, nothing is pushed.
        settled()
        terminal.resize(30)
        settled()
        assert terminal.pushes == [33, 10]
        # The screen emptied: the block would stand at the top of it, and
        # is pushed to the last rows again.
        app.clear()
        eventually(lambda: terminal.pushes == [33, 10, 30 - BLOCK_ROWS])
        settled()
        assert terminal.pushes == [33, 10, 23]


def typed_into(app: CliApp, text: str) -> None:
    """Puts ``text`` into the input field the way typing does, on the
    screen's own thread, and waits until the field has it."""
    app._on_screen_thread(lambda: app._input.buffer.insert_text(text))
    eventually(lambda: app._input.text.endswith(text))


def the_list_is_open(app: CliApp) -> bool:
    state = app._input.buffer.complete_state
    return state is not None and bool(state.completions)


def emptied(app: CliApp) -> None:
    """The input field emptied, and the screen asked to draw it again — a
    key would have done the second on its own."""
    app._on_screen_thread(lambda: (app._input.buffer.reset(), app.invalidate()))


def test_a_list_that_opens_below_the_field_takes_the_empty_rows_and_nothing_scrolls(tmp_path):
    """At the start the head stands at the top and the empty rows above the
    block are all there is below it. The list takes them, and the head
    does not move; when the list is gone, the block is on the last rows
    again and the rows are empty again — once and once more."""
    terminal = Terminal(rows=40)
    with running(tmp_path, terminal) as app:
        eventually(lambda: terminal.pushes == [40 - BLOCK_ROWS])
        settled()
        assert terminal.scrolled == 0
        pushes = [40 - BLOCK_ROWS]
        for _ in range(2):
            typed_into(app, "/")
            eventually(lambda: the_list_is_open(app))
            settled()
            assert terminal.scrolled == 0
            emptied(app)
            pushes.append(COMPLETION_ROWS)
            eventually(lambda: terminal.pushes == pushes)
            settled()
            assert terminal.scrolled == 0
            assert terminal.pushes == pushes


def test_a_list_of_another_length_takes_only_the_rows_it_needs_and_gives_them_back(tmp_path):
    """The list is as long as the commands that match what is typed: twelve
    rows for a slash, three for a slash and a letter. What it does not need
    any more is empty again, and the next list starts from there."""
    terminal = Terminal(rows=40)
    free = 40 - BLOCK_ROWS
    with running(tmp_path, terminal) as app:
        eventually(lambda: terminal.pushes == [free])
        typed_into(app, "/")
        eventually(lambda: the_list_is_open(app))
        # Read off what the screen knows to be empty above the block, not
        # off the pushes that led there: the drawing of a letter may land
        # between the key and the new list, and the list is then given
        # back whole before the shorter one takes its rows — one push
        # more, the same rows empty.
        eventually(lambda: app._free_rows._count == free - COMPLETION_ROWS)
        typed_into(app, "t")
        eventually(lambda: app._free_rows._count == free - 3)
        assert len(app._input.buffer.complete_state.completions) == 3
        emptied(app)
        eventually(lambda: app._free_rows._count == free)
        typed_into(app, "/")
        eventually(lambda: the_list_is_open(app))
        eventually(lambda: app._free_rows._count == free - COMPLETION_ROWS)
        settled()
        assert terminal.scrolled == 0
        assert terminal.pushes[0] == free


def test_each_printed_line_pushes_the_head_up_by_one_row_and_the_block_stays_down(tmp_path):
    terminal = Terminal(rows=40)
    with running(tmp_path, terminal) as app:
        eventually(lambda: terminal.pushes == [40 - BLOCK_ROWS])
        settled()
        app.print_above(Text("first"))
        eventually(lambda: terminal.scrolled == 1)
        settled()
        assert terminal.scrolled == 1
        for number in range(9):
            app.print_above(Text(f"line {number}"))
        eventually(lambda: terminal.scrolled == 10)
        settled()
        assert terminal.scrolled == 10
        # The block was on the last rows all the time: nothing was pushed.
        assert terminal.pushes == [40 - BLOCK_ROWS]


def test_a_list_that_opens_right_below_printed_lines_scrolls_and_does_not_write_over_them(tmp_path):
    """Nothing is known to be empty above the block once a line stands
    there: the list takes no row of it, and the terminal scrolls as it
    always did."""
    terminal = Terminal(rows=40)
    with running(tmp_path, terminal) as app:
        eventually(lambda: terminal.pushes == [40 - BLOCK_ROWS])
        settled()
        app.print_above(Text("printed"))
        eventually(lambda: terminal.scrolled == 1)
        settled()
        typed_into(app, "/")
        eventually(lambda: the_list_is_open(app))
        settled()
        assert terminal.scrolled == 1 + COMPLETION_ROWS


def test_a_list_that_opens_after_the_window_changed_its_height_takes_no_rows_on_trust(tmp_path):
    """A new height may have cut or moved what stands above the block:
    nothing is known to be empty there any more, and the list scrolls."""
    terminal = Terminal(rows=40)
    with running(tmp_path, terminal) as app:
        eventually(lambda: terminal.pushes == [40 - BLOCK_ROWS])
        settled()
        terminal.resize(30)
        settled()
        typed_into(app, "/")
        eventually(lambda: the_list_is_open(app))
        settled()
        assert terminal.scrolled > 0


class AnswersOnCue(Terminal):
    """A terminal that says where its cursor stands only when told to: the
    question is kept with the row the cursor stood on when it was asked, and
    the answer goes into the client's input in the order of the questions —
    as late as the test wants."""

    def __init__(self, columns: int = 80, rows: int = 40) -> None:
        super().__init__(columns, rows)
        self.asked: list[int] = []
        self.answered = 0
        self._pipe: Any = None

    def bind_input(self, pipe: Any) -> None:
        self._pipe = pipe

    @property
    def responds_to_cpr(self) -> bool:
        return True

    def get_rows_below_cursor_position(self) -> int:
        raise NotImplementedError

    def ask_for_cpr(self) -> None:
        self.asked.append(self.row)

    def answer(self, count: int = 1) -> None:
        """The oldest ``count`` questions that wait are answered, all in one
        piece of input — the answers that come late come together."""
        text = ""
        for _ in range(count):
            row = self.asked[self.answered]
            self.answered += 1
            text += f"\x1b[{row + 1};1R"
        self._pipe.send_text(text)

    def answer_all(self) -> None:
        """Everything asked so far, and what is asked in answer to that."""
        for _ in range(20):
            if self.answered >= len(self.asked):
                return
            self.answer(len(self.asked) - self.answered)
            settled()


def test_a_second_clear_before_the_push_was_measured_pushes_again(tmp_path):
    """The terminal says where its cursor stands late. A second clear comes
    before a drawing has measured the push of the first: the block stands at
    the top again, and nothing but a push brings it to the last rows."""
    terminal = AnswersOnCue(rows=40)
    free = 40 - BLOCK_ROWS
    with running(tmp_path, terminal) as app:
        eventually(lambda: terminal.asked)
        terminal.answer_all()
        eventually(lambda: terminal.pushes == [free])
        terminal.answer_all()
        settled()
        assert terminal.pushes == [free]

        app.clear()
        eventually(lambda: len(terminal.asked) > terminal.answered)
        terminal.answer(len(terminal.asked) - terminal.answered)
        eventually(lambda: terminal.pushes == [free, free])
        # The push is not measured yet — nothing has answered since — when
        # the window is emptied again.
        app.clear()
        # Two questions wait: the one of the first push and the one of the
        # second clear. They are answered together, and only then is the
        # block measured again — at the top, where the first push had put
        # it before it moved.
        eventually(lambda: len(terminal.asked) - terminal.answered >= 2)
        terminal.answer_all()
        eventually(lambda: terminal.pushes == [free, free, free])
        settled()
        assert terminal.pushes == [free, free, free]


def rows_between_the_history_and_the_block(app: CliApp, terminal: WindowTerminal) -> int:
    """How many rows right above the block hold nothing: the history ends
    that many rows above it."""
    count = 0
    for line in reversed(above_the_block(app, terminal)):
        if "".join(line).strip():
            break
        count += 1
    return count


def test_a_list_closed_over_a_full_window_leaves_no_blank_rows_above_the_block(tmp_path):
    """The history fills the window, so the list scrolls it up when it
    opens. Closed, the block is one row high again: the history moves down
    into the rows the list left, and no empty row is written between it and
    the block."""
    terminal = with_a_history(WindowTerminal(WIDE_COLUMNS, rows=30), 60)
    with running(tmp_path, terminal) as app:
        settled()
        history = right_above_the_block(app, terminal)
        assert history
        assert rows_between_the_history_and_the_block(app, terminal) == 0
        for _ in range(2):
            typed_into(app, "/")
            eventually(lambda: the_list_is_open(app))
            settled()
            emptied(app)
            eventually(lambda: not the_list_is_open(app))
            settled()
            assert right_above_the_block(app, terminal) == history
            assert rows_between_the_history_and_the_block(app, terminal) == 0
            # The block is on the last row of the window all the time.
            assert terminal.y == len(terminal.lines) - 1 - (STATUS_LINES + 1)


def test_a_command_list_below_one_printed_line_leaves_no_blank_rows_either(tmp_path):
    """The running chat: a line stands above the block, nothing is known to
    be empty there, the list scrolls the line and the rows over it up."""
    terminal = with_a_history(WindowTerminal(WIDE_COLUMNS, rows=30), 60)
    with running(tmp_path, terminal) as app:
        settled()
        app.print_above(Text("the last printed line"))
        eventually(lambda: "thelastprintedline" in right_above_the_block(app, terminal))
        settled()
        history = right_above_the_block(app, terminal)
        typed_into(app, "/")
        eventually(lambda: the_list_is_open(app))
        settled()
        emptied(app)
        eventually(lambda: not the_list_is_open(app))
        settled()
        assert right_above_the_block(app, terminal) == history
        assert rows_between_the_history_and_the_block(app, terminal) == 0


def test_silence_probe_a_list_closed_in_a_window_with_room_still_pushes_the_block_down(tmp_path):
    """Nothing scrolled for the list here: the empty rows it took are given
    back as empty rows between the head and the block, as before."""
    terminal = Terminal(rows=40)
    with running(tmp_path, terminal) as app:
        eventually(lambda: terminal.pushes == [40 - BLOCK_ROWS])
        settled()
        typed_into(app, "/")
        eventually(lambda: the_list_is_open(app))
        settled()
        emptied(app)
        eventually(lambda: terminal.pushes == [40 - BLOCK_ROWS, COMPLETION_ROWS])
        settled()
        assert terminal.shifts == []
        assert terminal.scrolled == 0


def test_a_list_that_opens_in_a_cleared_window_takes_the_rows_the_block_was_pushed_by(tmp_path):
    """A line stands above the block, so nothing is known to be empty; the
    window is cleared and the block pushed to the last rows again, and
    those rows are empty and known to be."""
    terminal = Terminal(rows=40)
    with running(tmp_path, terminal) as app:
        eventually(lambda: terminal.pushes == [40 - BLOCK_ROWS])
        settled()
        app.print_above(Text("printed"))
        eventually(lambda: terminal.scrolled == 1)
        settled()
        app.clear()
        eventually(lambda: terminal.pushes == [40 - BLOCK_ROWS, 40 - BLOCK_ROWS])
        settled()
        typed_into(app, "/")
        eventually(lambda: the_list_is_open(app))
        settled()
        assert terminal.scrolled == 1


def test_an_output_whose_cursor_the_lines_do_not_move_is_pushed_once(tmp_path):
    """A stand-in that always reports the same rows below the cursor would
    otherwise have the block pushed without end."""
    pushes: list[int] = []

    class Unmoved(DummyOutput):
        def write_raw(self, data: str) -> None:
            if data and not data.strip("\n"):
                pushes.append(len(data))

        def write(self, data: str) -> None:
            self.write_raw(data)

    with create_pipe_input() as pipe:
        pipe.send_text("/quit" + ENTER)
        with create_app_session(input=pipe, output=Unmoved()):
            app = built(tmp_path)
            app.run()
    assert pushes == [40 - BLOCK_ROWS]


# --- A window that gets narrower ------------------------------------------------

# What reaches a terminal, piece by piece: a sequence that tells it what to
# do, or one sign.
WRITTEN = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1bM|.", re.DOTALL)

# The width the block is drawn in first, and the widths the window is drawn
# down to: by one column, by a third — every row of the block takes two
# rows then — and to less than half, where every row takes three.
WIDE_COLUMNS = 106
DRAWN_DOWN_COLUMNS = [105, 69, 40]

# How many signs of what stands right above the block are compared: several
# rows of the history, and more than any row of the block holds.
LAST_OF_THE_HISTORY = 300


class WindowTerminal(DummyOutput):
    """An output that keeps what is written to it in rows and breaks them
    anew when it is drawn narrower, the way the terminal in the window of
    Exe AI does: the client is told the new width first, and the terminal
    breaks its rows once the client has taken its block off — at the first
    erase after it, which is what the window waits for. It goes through its
    rows from the last to the first; a row longer than the new width goes
    on in rows added below it — the cursor's own row like every other, as
    the window tells its terminal.
    What becomes of the cursor depends on the history the terminal keeps
    above its window, ``kept`` rows at the most with the window's:

    - none yet: the cursor moves down with every row added, and for each
      the last row is dropped, until the cursor stands on the last row;
    - some, and room for more: the window moves down with every row added,
      and the cursor with it;
    - as much as it keeps: the cursor stays on its row of the window, and
      as many rows leave at the top as were added.

    A sign two cells wide never stands half in one row and half in the
    next: where it meets the last cell, it goes to the next row whole. A
    window drawn wider leaves the rows as they are: only rows the terminal
    broke itself would be joined again."""

    def __init__(self, columns: int, rows: int = 30, kept: int = 5000) -> None:
        self.columns, self.rows, self.kept = columns, rows, kept
        # The width the client was told, and the width the terminal still
        # breaks its rows to until the client has taken its block off.
        self.told = columns
        self._breaks_to: int | None = None
        self.lines: list[list[str]] = [[] for _ in range(rows)]
        # The cursor: its column, and its row counted from the first row
        # kept.
        self.x = self.y = 0
        self.wraps = True

    @property
    def top(self) -> int:
        """The first row of the window."""
        return len(self.lines) - self.rows

    def get_size(self) -> Size:
        return Size(rows=self.rows, columns=self.told)

    def get_rows_below_cursor_position(self) -> int:
        return self.rows - (self.y - self.top)

    def write(self, data: str) -> None:
        self.write_raw(data)

    def write_raw(self, data: str) -> None:
        for written in WRITTEN.findall(data):
            if written == "\x1b[2J":
                self.erase_screen()
            elif written == "\x1b[H":
                self.x, self.y = 0, self.top
            elif written == "\n":
                # The history's line ends come through a terminal that
                # goes to the first column with them.
                self.x = 0
                self._next_row()
            elif written == "\r":
                self.x = 0
            elif written == "\x1bM":
                # Reverse index: up a row, and at the top of the window the
                # content moves down by one.
                if self.y == self.top:
                    self._scroll_down(1)
                else:
                    self.y -= 1
            elif re.fullmatch(r"\x1b\[\d+;\d+H", written):
                row, column = (int(part) for part in written[2:-1].split(";"))
                self.cursor_goto(row, column)
            elif written >= " ":
                self._put(written)

    def _scroll_down(self, amount: int) -> None:
        """What the window shows moves down by ``amount`` rows, empty rows
        come in at the top and the rows at the bottom leave; the history
        above the window and the cursor stay where they are."""
        window = self.lines[self.top :]
        self.lines[self.top :] = [[] for _ in range(amount)] + window[: len(window) - amount]

    def _put(self, sign: str) -> None:
        # A wide sign holds its cell and, with nothing in it, the next.
        cells = [sign, ""][: get_cwidth(sign)]
        if not cells:
            return
        if self.x + len(cells) > self.columns:
            if self.wraps:
                self.x = 0
                self._next_row()
            else:
                self.x = self.columns - len(cells)
        line = self.lines[self.y]
        line.extend(" " * (self.x - len(line)))
        line[self.x : self.x + len(cells)] = cells
        self.x += len(cells)

    def _next_row(self) -> None:
        if self.y < len(self.lines) - 1:
            self.y += 1
            return
        self.lines.append([])
        if len(self.lines) > self.kept:
            del self.lines[0]
        else:
            self.y += 1

    def enable_autowrap(self) -> None:
        self.wraps = True

    def disable_autowrap(self) -> None:
        self.wraps = False

    def cursor_up(self, amount: int) -> None:
        self.y = max(self.top, self.y - amount)

    def cursor_down(self, amount: int) -> None:
        self.y = min(len(self.lines) - 1, self.y + amount)

    def cursor_forward(self, amount: int) -> None:
        self.x = min(self.columns - 1, self.x + amount)

    def cursor_backward(self, amount: int) -> None:
        self.x = max(0, self.x - amount)

    def cursor_goto(self, row: int = 0, column: int = 0) -> None:
        self.x, self.y = max(0, column - 1), self.top + max(0, row - 1)

    def erase_end_of_line(self) -> None:
        del self.lines[self.y][self.x :]

    def erase_down(self) -> None:
        self.erase_end_of_line()
        for line in self.lines[self.y + 1 :]:
            line.clear()
        if self._breaks_to is not None:
            # The block is off: now the rows that are left are broken anew.
            columns, self._breaks_to = self._breaks_to, None
            self._break_anew(columns)
            self.columns = columns
            self.x = min(self.x, columns - 1)

    def erase_screen(self) -> None:
        for line in self.lines[self.top :]:
            line.clear()

    def set_width(self, columns: int) -> None:
        """The window is drawn at another width. The client is told at
        once. A wider window breaks nothing; a narrower one breaks the
        rows when the client has erased its block."""
        self.told = columns
        if columns < self.columns:
            self._breaks_to = columns
            return
        self._breaks_to = None
        self.columns = columns
        self.x = min(self.x, columns - 1)

    def _break_anew(self, columns: int) -> None:
        lines, rows = self.lines, self.rows
        # The rows as they stand: the terminal still goes through the ones
        # it has dropped at the end.
        standing = list(lines)
        # The first row of the window, and the cursor's row in it.
        top, row = self.top, self.y - self.top
        added: list[tuple[int, list[list[str]]]] = []
        count = 0
        for index in range(len(standing) - 1, -1, -1):
            line = standing[index]
            pieces = []
            while len(line) > columns:
                # The second half of a wide sign begins no row.
                cut = columns - 1 if line[columns] == "" else columns
                pieces.append(line[:cut])
                del line[:cut]
            if not pieces:
                continue
            pieces.append(line[:])
            more = len(pieces) - 1
            line[:] = pieces[0]
            added.append((index + 1 + count, pieces[1:]))
            count += more
            filled = row if top == 0 and row != len(lines) - 1 else len(lines)
            for _ in range(more - max(0, filled - self.kept + more)):
                if top == 0 and row < rows - 1:
                    row += 1
                    lines.pop()
                elif top == 0 or top < min(self.kept, len(lines) + count) - rows:
                    top += 1
        # The rows that are left and the added ones, set in their places
        # from the last row up; what no longer fits leaves at the top.
        anew: list[list[str]] = [[] for _ in range(min(self.kept, len(lines) + count))]
        left, placed = len(lines) - 1, 0
        index = len(anew) - 1
        while index >= 0:
            if added and added[0][0] > left + placed:
                pieces = added.pop(0)[1]
                for piece in reversed(pieces):
                    if index >= 0:
                        anew[index] = piece
                    index -= 1
                placed += len(pieces)
            else:
                anew[index] = lines[left]
                left -= 1
                index -= 1
        for line in anew:
            del line[columns:]
        lines[:] = anew
        self.y = top + row


def with_a_history(terminal: WindowTerminal, lines: int) -> WindowTerminal:
    """``terminal`` with ``lines`` lines written into it before the client
    starts — every other one longer than the width the window is drawn
    down to, so the terminal breaks it too."""
    for number in range(lines):
        terminal.write_raw(f"line {number} of the history " + "h" * (number % 2 * 70) + "\n")
    return terminal


def above_the_block(app: CliApp, terminal: WindowTerminal) -> list[list[str]]:
    """The rows of ``terminal`` above the block of the running screen."""
    screen = app._app.renderer.last_rendered_screen
    if screen is None:
        return []
    return terminal.lines[: len(terminal.lines) - screen.height]


def right_above_the_block(app: CliApp, terminal: WindowTerminal) -> str:
    """The last signs that stand in ``terminal`` above the block of the
    running screen, the blanks left out: the end of the history where
    nothing else stands there. However the terminal has broken the rows,
    the signs are the same."""
    signs = "".join("".join(line).replace(" ", "") for line in above_the_block(app, terminal))
    return signs[-LAST_OF_THE_HISTORY:]


def blank_rows_written_above_the_block(app: CliApp, terminal: WindowTerminal) -> int:
    """How many rows above the block were written and hold nothing but
    blanks. The history has none: its empty rows were never written to. A
    row of the block has — the hint line above the field is one — and
    left standing it is such a row."""
    return sum(1 for line in above_the_block(app, terminal) if line and not "".join(line).strip())


def drawn_in(app: CliApp) -> int:
    """The columns the running screen drew itself in the last time."""
    size = app._app.renderer._last_size
    return size.columns if size is not None else 0


# The history the terminal keeps above its window when the window is drawn
# narrower: the lines written before the client starts, and the rows the
# terminal keeps at the most.
NONE_YET = (3, 5000)
ROOM_FOR_MORE = (50, 5000)
AS_MUCH_AS_IT_KEEPS = (50, 40)


THE_HISTORY_KEPT = pytest.mark.parametrize(
    ("lines", "kept"),
    [NONE_YET, ROOM_FOR_MORE, AS_MUCH_AS_IT_KEEPS],
    ids=["no history kept yet", "room for more history", "as much history as it keeps"],
)

# Two rows of text in the field at the wide width.
TWO_ROWS_OF_TEXT = 150

# What stands in the field when the window is drawn narrower: how many
# signs, and how many of them the cursor stands back from the end.
IN_THE_FIELD = {
    "an empty field": (0, 0),
    "one row of text": (40, 0),
    "two rows of text": (TWO_ROWS_OF_TEXT, 0),
    "three rows of text": (TWO_ROWS_OF_TEXT + WIDE_COLUMNS, 0),
    "the cursor a row above the last": (TWO_ROWS_OF_TEXT, 110),
}


@THE_HISTORY_KEPT
@pytest.mark.parametrize(
    ("columns", "signs", "back"),
    [
        # Two rows of text at every width, everything else at one of them.
        pytest.param(columns, *IN_THE_FIELD[field], id=f"{field}, down to {columns} columns")
        for field in IN_THE_FIELD
        for columns in DRAWN_DOWN_COLUMNS
        if field == "two rows of text" or columns == DRAWN_DOWN_COLUMNS[1]
    ],
)
def test_a_window_drawn_narrower_keeps_nothing_of_the_block_it_showed(
    tmp_path, lines, kept, columns, signs, back
):
    """The client is told the new width first and takes its block off; the
    terminal breaks the rows that are left once that is done. The block is
    drawn anew below the history, which is the same as before, with no row
    left over between the two."""
    terminal = with_a_history(WindowTerminal(WIDE_COLUMNS, kept=kept), lines)
    with running(tmp_path, terminal) as app:
        put_in_field(app, "x" * signs, signs - back)
        settled()
        history = right_above_the_block(app, terminal)
        assert history
        assert blank_rows_written_above_the_block(app, terminal) == 0
        terminal.set_width(columns)
        eventually(lambda: right_above_the_block(app, terminal) == history)
        settled()
        assert drawn_in(app) == columns
        assert right_above_the_block(app, terminal) == history
        assert blank_rows_written_above_the_block(app, terminal) == 0


@THE_HISTORY_KEPT
def test_silence_probe_a_window_drawn_wider_keeps_nothing_of_its_block_either(
    tmp_path, lines, kept
):
    """No row is longer than a wider window: the terminal breaks nothing."""
    terminal = with_a_history(WindowTerminal(69, kept=kept), lines)
    with running(tmp_path, terminal) as app:
        put_in_field(app, "x" * 100)
        settled()
        history = right_above_the_block(app, terminal)
        assert history
        terminal.set_width(WIDE_COLUMNS)
        eventually(lambda: drawn_in(app) == WIDE_COLUMNS)
        settled()
        assert right_above_the_block(app, terminal) == history
        assert blank_rows_written_above_the_block(app, terminal) == 0


def test_a_wide_sign_at_the_new_last_cell_goes_to_the_next_row_and_nothing_is_left_behind(
    tmp_path,
):
    """The first row of the field holds fifty-two wide signs behind the
    mark, a hundred and six cells. Drawn down to fifty-three columns, the
    sign that would stand half in the last cell goes to the next row, and
    the same happens there: the row takes three rows, where its length
    alone says two. The client has taken its block off before the terminal
    breaks anything, so no row of it is left."""
    lines, kept = ROOM_FOR_MORE
    terminal = with_a_history(WindowTerminal(WIDE_COLUMNS, kept=kept), lines)
    with running(tmp_path, terminal) as app:
        put_in_field(app, WIDE_IN_EVERY_FONT * 60)
        settled()
        history = right_above_the_block(app, terminal)
        terminal.set_width(53)
        eventually(lambda: right_above_the_block(app, terminal) == history)
        settled()
        assert right_above_the_block(app, terminal) == history
        assert blank_rows_written_above_the_block(app, terminal) == 0


# --- The width of the history ---------------------------------------------------


def exported(app: CliApp, tmp_path: Path, name: str) -> list[str]:
    target = tmp_path / f"{name}.html"
    app.export(target)
    return [line for line in shown_text(target.read_text(encoding="utf-8")).splitlines() if line.strip()]


def test_the_history_is_set_as_wide_as_the_window(tmp_path):
    paragraph = "word " * 30
    for columns, rows in ((200, 1), (80, 2)):
        with create_pipe_input() as pipe, create_app_session(
            input=pipe, output=Terminal(columns=columns)
        ):
            app = built(tmp_path)
            app.print_above(Text(paragraph.strip()))
            lines = exported(app, tmp_path, str(columns))
            # One line of a hundred and fifty cells in a wide window; two
            # in one of eighty columns, as before.
            assert len(lines) == rows, columns
            assert max(len(line) for line in lines) <= columns


def test_a_list_is_written_to_the_history_without_the_blanks_that_fill_up_its_rows(tmp_path, capsys):
    """A list is set in columns, so every row of it is filled up with blanks
    to the same width. Drawn narrower, the terminal breaks each of them and
    sets the blanks that are left in a row of their own — more empty rows
    with every step. Nothing is lost by leaving them out: they show nothing."""
    table = Table(box=None, show_header=False, padding=(0, 2))
    table.add_column()
    table.add_column()
    table.add_row("first", "a long cell that sets the width of its column")
    table.add_row("second", "short")
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=Terminal(columns=100)):
        app = built(tmp_path)
        app.print_above(table)
    written = capsys.readouterr().out
    lines = [line for line in written.splitlines() if line.strip()]
    assert len(lines) == 2
    assert all(line == line.rstrip(" ") for line in lines)
    assert "short" in lines[1] and "a long cell that sets the width of its column" in lines[0]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("word   \n", "word\n"),
        ("word\n", "word\n"),
        ("a b   c\n", "a b   c\n"),
        ("   \n", "\n"),
        # The colour codes between and behind the blanks stay.
        ("\x1b[1mword  \x1b[0m  \n", "\x1b[1mword\x1b[0m\n"),
        ("\x1b[1mword\x1b[0m\n", "\x1b[1mword\x1b[0m\n"),
        # Every line of a piece of text, not only the last.
        ("one  \ntwo \n\nthree", "one\ntwo\n\nthree"),
        # A blank at the very end of the text has no line break behind it.
        ("last   ", "last"),
    ],
)
def test_blanks_at_the_end_of_a_line_are_taken_off_and_the_colour_codes_stay(text, expected):
    assert _without_trailing_blanks(text) == expected


def test_a_chats_title_in_the_head_is_shown_whole_where_the_window_has_room(tmp_path):
    title = "A long conversation about the plans for the garden and the house in spring".ljust(90, ".")
    assert len(title) == 90
    stamp = "2026-10-11T04:34:00+02:00"
    chats = [{"id": "c-1", "title": title, "updated_at": stamp}]
    wide = recorded(
        "/quit" + ENTER, service=Service(chats=chats), tmp_path=tmp_path, output=Terminal(columns=200)
    )
    row = next(line for line in wide.splitlines() if line.strip().startswith("1"))
    # The whole title, and the time of the chat behind it.
    assert title in row and row.rstrip().endswith(local_clock(stamp))
    narrow = recorded(
        "/quit" + ENTER, service=Service(chats=chats), tmp_path=tmp_path, output=Terminal(columns=60)
    )
    row = next(line for line in narrow.splitlines() if line.strip().startswith("1"))
    assert title not in row and glyphs.glyph("more") in row and len(row) <= 60


def test_empty_input_sends_nothing(tmp_path):
    service = Service()
    shown = recorded(ENTER + "   " + ENTER + "/quit" + ENTER, service=service, tmp_path=tmp_path)
    assert not [request for request in service.seen if request.method == "POST"]
    typed = [line for line in shown.splitlines() if line.startswith(glyphs.glyph("prompt"))]
    assert typed == [typed_line("/quit")]


def test_a_backslash_at_the_end_of_a_line_continues_it(tmp_path):
    shown = recorded("first\\" + ENTER + "second" + ENTER + "/quit" + ENTER, tmp_path=tmp_path)
    lines = shown.splitlines()
    typed = lines.index(typed_line("first"))
    assert lines[typed + 1] == "  second"


def test_a_backslash_inside_a_line_is_an_ordinary_character(tmp_path):
    cursor_left = "\x1b[D"
    service = Service()
    shown = recorded(
        "a\\b" + cursor_left + ENTER + "/quit" + ENTER, service=service, tmp_path=tmp_path
    )
    # The cursor stood right behind the backslash; the line is sent whole.
    assert typed_line("a\\b") in shown.splitlines()


def test_a_line_break_key_breaks_the_line_instead_of_sending(tmp_path):
    line_break = "\n"
    shown = recorded("one" + line_break + "two" + ENTER + "/quit" + ENTER, tmp_path=tmp_path)
    lines = shown.splitlines()
    typed = lines.index(typed_line("one"))
    assert lines[typed + 1] == "  two"


def test_the_end_of_input_key_leaves_only_on_an_empty_field(tmp_path):
    end_of_input = "\x04"
    assert run(end_of_input, tmp_path=tmp_path) == 0
    # With text in the field the key deletes a character and nothing ends:
    # the line is still sent, and only the command after it leaves.
    shown = recorded("ab" + end_of_input + ENTER + "/quit" + ENTER, tmp_path=tmp_path)
    assert typed_line("ab") in shown.splitlines()


def test_the_interrupt_key_leaves(tmp_path):
    assert run("\x03", tmp_path=tmp_path) == 0


def test_the_interrupt_key_empties_a_field_with_text_and_the_client_stays(tmp_path):
    """Typed, thought better of, and the key pressed: the text goes and the
    client runs on — the next line is taken as any other. Only the key in
    the emptied field leaves."""
    service = Service()
    shown = recorded(
        "a long line nobody wants to lose the client over" + "\x03" + "/help" + ENTER + "\x03",
        service=service,
        tmp_path=tmp_path,
    )
    lines = shown.splitlines()
    # The line after the key was taken, and what stood in the field before
    # the key is not part of it.
    assert typed_line("/help") in lines
    assert not any("a long line nobody wants" in line for line in lines)


def test_the_interrupt_key_means_the_answer_first_then_the_text_then_the_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Silence probe: beside a running answer the key stops the answer and
    the field keeps what is typed, as before. With nothing running it
    empties the field; in the empty field it leaves."""
    app = built(tmp_path)
    left: list[bool] = []
    app.exit = lambda: left.append(True)  # type: ignore[method-assign]
    stopped: list[Context] = []
    monkeypatch.setattr(chat, "stop", stopped.append)
    app._input.buffer.text = "a thought for later"
    app._ctx.session.answering = True
    app._on_interrupt(None)  # type: ignore[arg-type]
    eventually(lambda: stopped)
    assert app._input.text == "a thought for later" and left == []
    app._ctx.session.answering = False
    app._on_interrupt(None)  # type: ignore[arg-type]
    assert app._input.text == "" and left == [] and len(stopped) == 1
    app._on_interrupt(None)  # type: ignore[arg-type]
    assert left == [True]


def test_the_interrupt_key_ends_the_wait_for_a_model_server_and_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While a model server is starting, the key ends the wait: the text in
    the field stays, a running answer is not stopped, the client does not
    leave. With no wait standing it is the key it was."""
    app = built(tmp_path)
    left: list[bool] = []
    app.exit = lambda: left.append(True)  # type: ignore[method-assign]
    stopped: list[Context] = []
    monkeypatch.setattr(chat, "stop", stopped.append)
    ended: list[bool] = []
    app._ctx.session.cancel_wait = lambda: ended.append(True)
    app._input.buffer.text = "a thought for later"
    app._ctx.session.answering = True
    app._on_interrupt(None)  # type: ignore[arg-type]
    assert ended == [True]
    assert app._input.text == "a thought for later" and left == [] and stopped == []
    # The wait is over: the key means the answer again.
    app._ctx.session.cancel_wait = None
    app._on_interrupt(None)  # type: ignore[arg-type]
    eventually(lambda: stopped)
    assert ended == [True] and left == []


def test_the_interrupt_key_takes_blanks_for_text_too(tmp_path: Path) -> None:
    """On the edge: a field that holds only blanks is not empty, and the
    key empties it instead of leaving."""
    app = built(tmp_path)
    left: list[bool] = []
    app.exit = lambda: left.append(True)  # type: ignore[method-assign]
    app._input.buffer.text = "   "
    app._on_interrupt(None)  # type: ignore[arg-type]
    assert app._input.text == "" and left == []


# --- The size of the context in the third status line -------------------------------


def status_lines(ctx: Context) -> str:
    return "".join(text for _, text in ctx.status.fragments(200))


def after_a_line(stub: StubService, type_in: Any, line: str) -> None:
    """Types a line and waits until it is through: the model list is read
    anew once a line has been handled, as the last thing of all — so a
    second line is waited for as well, and by then the first one is done."""
    for _ in range(2):
        asked = stub.requests.count("GET /api/v1/models")
        type_in(line + ENTER)
        eventually(lambda: stub.requests.count("GET /api/v1/models") > asked)  # noqa: B023


def test_the_size_of_the_context_follows_the_service_with_the_next_line_sent(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Set in the service while the client runs — no restart, and the model
    is not chosen again: the line sent next brings the new size along."""
    stub.models[0]["context_tokens"] = 128000
    stood: list[str] = []

    def drive(run: Run, type_in: Any) -> None:
        ctx = run.parts()
        eventually(lambda: stub.watchers == 1)
        eventually(lambda: "/128000" in status_lines(ctx))
        stub.models[0]["context_tokens"] = 784000
        # Nothing was sent yet: the line still says what was read at start.
        stood.append(status_lines(ctx))
        after_a_line(stub, type_in, "/help")
        stood.append(status_lines(ctx))
        type_in("/quit" + ENTER)

    assert run_client(stub_http, tmp_path, monkeypatch, drive).code == 0
    before, after = stood
    assert "/128000" in before and "/784000" not in before
    assert "/784000" in after and "/128000" not in after
    assert "Local Model" in after


def test_a_model_whose_server_went_silent_keeps_its_name_and_its_last_size(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Silence probe: the service leaves a model whose server does not
    answer out of its list. The lines sent meanwhile change neither the
    name nor the size the status lines show."""
    stub.models[0]["context_tokens"] = 128000
    stood: list[str] = []

    def drive(run: Run, type_in: Any) -> None:
        ctx = run.parts()
        eventually(lambda: stub.watchers == 1)
        eventually(lambda: "/128000" in status_lines(ctx))
        stub.models[0]["erreichbar"] = False
        after_a_line(stub, type_in, "/help")
        stood.append(status_lines(ctx))
        type_in("/quit" + ENTER)

    assert run_client(stub_http, tmp_path, monkeypatch, drive).code == 0
    assert "Local Model" in stood[0] and "/128000" in stood[0]


def test_what_was_asked_for_on_the_command_line_is_remembered(tmp_path):
    run("/quit" + ENTER, "--theme", "exe", tmp_path=tmp_path)
    assert prefs.load(tmp_path / "cli.json") == {
        "look": "exe",
        "language": "en",
        "url": "http://service.test",
        "keys": None,
    }


def test_what_the_window_hands_the_client_is_not_remembered(tmp_path, monkeypatch):
    """Inside the window's tab the address, the theme and the language are
    the window's, not the user's own choice: the file stays as it was, and
    the next start in a terminal finds what the user chose there."""
    prefs.save(
        {"url": "http://own.test", "language": "de", "look": "pearl"}, tmp_path / "cli.json"
    )
    before = (tmp_path / "cli.json").read_text(encoding="utf-8")
    monkeypatch.setenv(themes.WINDOW_VARIABLE, "1")

    run("/quit" + ENTER, "--theme", "exe", tmp_path=tmp_path)

    assert (tmp_path / "cli.json").read_text(encoding="utf-8") == before


def test_silence_probe_outside_the_window_the_same_start_is_remembered(tmp_path, monkeypatch):
    prefs.save(
        {"url": "http://own.test", "language": "de", "look": "pearl"}, tmp_path / "cli.json"
    )
    monkeypatch.delenv(themes.WINDOW_VARIABLE, raising=False)

    run("/quit" + ENTER, "--theme", "exe", tmp_path=tmp_path)

    kept = prefs.load(tmp_path / "cli.json")
    assert (kept["url"], kept["language"], kept["look"]) == ("http://service.test", "en", "exe")


def test_the_remembered_address_is_used_when_none_is_given(tmp_path):
    prefs.save({"url": "http://remembered.test", "language": "en"}, tmp_path / "cli.json")
    service = Service()
    with create_pipe_input() as pipe:
        pipe.send_text("/quit" + ENTER)
        with create_app_session(input=pipe, output=DummyOutput()):
            code = main(
                [],
                http=httpx.Client(transport=httpx.MockTransport(service)),
                prefs_path=tmp_path / "cli.json",
            )
    assert code == 0
    assert {request.url.host for request in service.seen} == {"remembered.test"}


def test_a_service_that_refuses_at_start_ends_the_client_with_its_sentence(capsys, tmp_path):
    class Broken(Service):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/models":
                self.seen.append(noted(request))
                return httpx.Response(500, json={"detail": "The model list is broken"})
            return super().__call__(request)

    assert run("", service=Broken(), tmp_path=tmp_path) == 1
    assert capsys.readouterr().err.strip() == "The model list is broken"


def test_an_answer_is_cut_into_blocks_at_blank_lines():
    blocks, rest = split_blocks("One.\n\nTwo is still gro")
    assert blocks == ["One.\n"] and rest == "Two is still gro"
    # The second block is finished only once a blank line follows it.
    blocks, rest = split_blocks("Two is done.\n")
    assert blocks == [] and rest == "Two is done.\n"
    blocks, rest = split_blocks("Two is done.\n\n")
    assert blocks == ["Two is done.\n"] and rest == ""


def test_a_code_block_waits_for_its_closing_fence():
    opened = "Look:\n```python\nprint(1)\n\nprint(2)\n"
    blocks, rest = split_blocks(opened)
    assert blocks == [] and rest == opened
    blocks, rest = split_blocks(opened + "```\nAfter")
    assert blocks == [opened + "```\n"] and rest == "After"
    # A fence of the other kind inside the block closes nothing.
    blocks, rest = split_blocks("```\n~~~\n")
    assert blocks == []
    # Neither does a shorter one, nor a line that opens a block of its own.
    longer = "````markdown\n```python\nprint(1)\n```\n"
    blocks, rest = split_blocks(longer)
    assert blocks == [] and rest == longer
    blocks, rest = split_blocks(longer + "````\n")
    assert blocks == [longer + "````\n"] and rest == ""


def test_inline_code_at_the_start_of_a_line_opens_no_code_block():
    blocks, rest = split_blocks("```print(1)``` prints one.\n\nNext")
    assert blocks == ["```print(1)``` prints one.\n"] and rest == "Next"


def test_a_duration_reads_as_minutes_and_seconds():
    assert [clock(0), clock(5.9), clock(65), clock(600)] == ["0:00", "0:05", "1:05", "10:00"]
