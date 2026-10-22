"""The scaffold as a whole: it starts against a service, shows its head,
takes commands and lines from the input field and ends — without a
terminal and without a service, on a pipe and a stand-in transport."""

from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput, Output
from rich.table import Table
from rich.text import Text

from prompt_toolkit.layout.screen import WritePosition

from cli import chat, commands, dialogs, events, glyphs, prefs, themes
from cli.app import (
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
from tests.cli.program import (
    Run,
    a_session_without_the_console,
    in_the_shared_session,
    local_clock,
    run_client,
)
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
    """An output of a window of a size: the screen draws on it and the
    window's size is what it reads. The window can change its height while
    the client runs."""

    def __init__(self, columns: int = 80, rows: int = 40) -> None:
        self.columns, self.rows = columns, rows

    def get_size(self) -> Size:
        return Size(rows=self.rows, columns=self.columns)

    def resize(self, rows: int) -> None:
        """The window gets ``rows`` rows."""
        self.rows = rows


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
            with in_the_shared_session(pipe, output or DummyOutput()):
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
    block = app._fixed
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
            with in_the_shared_session(pipe, terminal):
                app = built(tmp_path)
                app._app.terminal_size_polling_interval = SIZE_POLL_SECONDS
                screens.append(app)
                ready.set()
                app.run()

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


def drawn(app: CliApp) -> bool:
    """Whether the screen has drawn everything that was written into the
    history: the rows of every line are worked out at a drawing."""
    return len(app._history._first_row) == len(app._history._lines)


def history_loaded(app: CliApp) -> bool:
    """Whether the input field has taken its history up, which it does at a
    drawing: a key that comes before would find nothing to go back to."""
    task = app._input.buffer._load_history_task
    return task is not None and task.done()


def resized_and_seen(terminal: Terminal, rows: int, seen: Callable[[], Any]) -> None:
    """Gives the window ``rows`` rows and waits until the screen shows it.
    The screen notices a new size only against an older one it has read: a
    change that comes before its first reading is the size it starts from.
    So, until the screen shows the size, the window is moved to another one
    and back."""
    deadline = time.monotonic() + SAFETY_NET_SECONDS
    while True:
        terminal.resize(rows)
        try:
            eventually(seen, timeout=0.5)
            return
        except AssertionError:
            if time.monotonic() >= deadline:
                raise
            terminal.resize(rows + 1)
            time.sleep(SIZE_POLL_SECONDS * 3)


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


def test_a_list_is_written_to_the_history_without_the_blanks_that_fill_up_its_rows(tmp_path):
    """A list is set in columns, so every row of it is filled up with blanks
    to the same width. Drawn narrower, the field breaks each of them and
    sets the blanks that are left in a row of its own — more empty rows
    with every step. Nothing is lost by leaving them out: they show nothing."""
    table = Table(box=None, show_header=False, padding=(0, 2))
    table.add_column()
    table.add_column()
    table.add_row("first", "a long cell that sets the width of its column")
    table.add_row("second", "short")
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=Terminal(columns=100)):
        app = built(tmp_path)
        app.print_above(table)
    written = app.history_text()
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
