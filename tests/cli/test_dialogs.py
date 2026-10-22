"""The service's questions in the terminal: a tool that waits for
permission and a question of the model's, answered through the input field
of the whole client — on a pipe and a stand-in transport that plays a
scripted answer and holds it open until the question is answered. And the
selection a command opens above the input field: what it shows, which keys
pick from it, and that it gives way to every question of the service."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Window as LayoutWindow
from prompt_toolkit.layout import walk
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.output import DummyOutput, Output
from prompt_toolkit.utils import get_cwidth

from cli import commands, dialogs, events, glyphs, themes
from cli.app import CliApp
from cli.client import KEY_HEADER, ServiceClient
from cli.interfaces import Asker, Context, Entry, Screen
from cli.main import main
from cli.render import build_renderer
from cli.status import build_status
from cli.texts import Texts
from test_app_scaffold import BLOCK_ROWS, Terminal
from test_commands import Service as Lists
from test_stream import shown_text

KEY = "key-of-this-run"
PAGE = f'<html><head><script>window.__SITZUNGSSCHLUESSEL__="{KEY}";</script></head></html>'
ENTER = "\r"
ESCAPE = "\x1b"
DOWN = "\x1b[B"
UP = "\x1b[A"
TAB = "\t"
BACK_TAB = "\x1b[Z"
INTERRUPT = "\x03"
# Leaves from an empty input field.
END_OF_INPUT = "\x04"
# Empties the input field.
CLEAR_FIELD = "\x15"

# How long a step may wait for another thread before it gives up, and after
# how long a run that never leaves is cut off. Both only bound a failure.
WAIT_SECONDS = 10
SAFETY_NET_SECONDS = 30

START = {"typ": "start", "generation_id": "g1", "message_id": "m1"}
DONE = {"typ": "done", "message_id": "m1"}
TOOL_CONFIRM = {
    "typ": "tool_confirm",
    "name": "write_file",
    "argumente": {"path": "notes.txt", "content": "Test"},
    "grund": "Outside the shared folders",
    "grund_wert": "notes.txt",
    "aufruf_id": "a1",
}
USER_ASK = {
    "typ": "user_ask",
    "frage": "Which colour?",
    "optionen": [
        {"label": "Red", "description": "the warm one"},
        {"label": "Blue", "description": ""},
    ],
    "aufruf_id": "a2",
}
RAN = {
    "typ": "tool_result",
    "name": "write_file",
    "aufruf_id": "a1",
    "fehlgeschlagen": False,
    "text": "written",
    "dauer_sekunden": 0.1,
}


def line(event: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode()


class Asking(httpx.SyncByteStream):
    """An answer that asks: it sends the question and then stands still, as
    the service does, until an answer arrives or the wait is called off."""

    def __init__(self, service: Service, question: dict[str, Any], after: list[dict]) -> None:
        self._service = service
        self._question = question
        self._after = after

    def __iter__(self) -> Iterator[bytes]:
        yield line(START)
        yield line(self._question)
        self._service.go_on.wait(WAIT_SECONDS)
        for event in self._after:
            yield line(event)
        yield line(DONE)
        self._service.over.set()

    def close(self) -> None:
        self._service.over.set()


class Service:
    """A stand-in for the service whose first answer asks ``question``.
    Every later message is answered plainly. Every request is kept."""

    def __init__(self, question: dict[str, Any] | None, after: list[dict] | None = None) -> None:
        self.question = question
        self.after = after or []
        self.seen: list[httpx.Request] = []
        # Set when the answer to the question has arrived — or by a test
        # that plays the service giving up its wait.
        self.go_on = threading.Event()
        self.over = threading.Event()

    def bodies(self, path: str) -> list[dict[str, Any]]:
        return [
            json.loads(request.content)
            for request in self.seen
            if request.url.path == f"/api/v1{path}"
        ]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        path = request.url.path
        if path == "/app/":
            return httpx.Response(200, text=PAGE)
        if request.headers.get(KEY_HEADER) != KEY:
            return httpx.Response(401, json={"detail": "Invalid or missing session key"})
        path = path.removeprefix("/api/v1")
        if path == "/health":
            return httpx.Response(200, json={"status": "ok", "version": "9.8.7"})
        if path == "/models":
            return httpx.Response(
                200,
                json=[{"id": "local", "name": "Local Model", "erreichbar": True, "context_tokens": 8192}],
            )
        if path == "/chats" and request.method == "POST":
            return httpx.Response(201, json={"id": "chat-1", "title": "A fresh chat"})
        if path.startswith("/chats/"):
            return httpx.Response(200, json={"id": "chat-1", "title": "A fresh chat"})
        if path == "/chat/completions":
            question, self.question = self.question, None
            if question is None:
                self.over.set()
                return httpx.Response(200, content=line(START) + line(DONE))
            return httpx.Response(200, stream=Asking(self, question, self.after))
        if path == "/chat/confirm":
            self.go_on.set()
            return httpx.Response(200, json={"zugestellt": True})
        if path == "/chat/stop":
            self.go_on.set()
            return httpx.Response(200, json={"abgebrochen": 1})
        return httpx.Response(404, json={"detail": "No such address"})


def until(condition: Callable[[], Any]) -> None:
    """Waits for another thread to get somewhere."""
    deadline = time.monotonic() + WAIT_SECONDS
    while not condition():
        assert time.monotonic() < deadline, "the other thread never got there"
        time.sleep(0.01)


@pytest.fixture
def asker(monkeypatch: pytest.MonkeyPatch) -> list[Asker]:
    """The asker the client builds for itself, once it has: a test asks it
    whether a question stands, so it types an answer only when one does."""
    built: list[Asker] = []
    build = dialogs.build_asker

    def kept(ctx: Context) -> Asker:
        built.append(build(ctx))
        return built[-1]

    monkeypatch.setattr(dialogs, "build_asker", kept)
    return built


@pytest.fixture(autouse=True)
def the_default_look():
    yield
    themes.set_look(themes.DEFAULT_LOOK)


def played(
    steps: list[str | Callable[[], Any]],
    service: Callable[[httpx.Request], httpx.Response],
    tmp_path: Path,
    output: Output | None = None,
) -> str:
    """Runs the whole client and types ``steps`` into it, one after the
    other: a text is typed as it stands, a condition is waited for. Returns
    the plain text of everything shown, read back from an export of the
    history written once the client has left."""
    parts: list[Context] = []
    built = events.build_events

    def remember(ctx: Context) -> Any:
        parts.append(ctx)
        return built(ctx)

    with create_pipe_input() as pipe:

        def type_them() -> None:
            for step in steps:
                if callable(step):
                    until(step)
                else:
                    pipe.send_text(step)

        typing = threading.Thread(target=type_them, daemon=True)
        safety_net = threading.Timer(SAFETY_NET_SECONDS, pipe.close)
        safety_net.start()
        events.build_events = remember
        try:
            with create_app_session(input=pipe, output=output or DummyOutput()):
                typing.start()
                code = main(
                    ["--url", "http://service.test", "--lang", "en"],
                    http=httpx.Client(transport=httpx.MockTransport(service)),
                    prefs_path=tmp_path / "cli.json",
                )
        finally:
            events.build_events = built
            safety_net.cancel()
    assert code == 0
    target = tmp_path / "shown.html"
    parts[0].screen.export(target)
    return shown_text(target.read_text(encoding="utf-8"))


def answered(
    question: dict[str, Any], keys: str, asker: list[Asker], tmp_path: Path
) -> tuple[list[dict[str, Any]], str]:
    """Sends one message whose answer asks ``question``, types ``keys`` once
    the question stands and leaves when the answer is over. Returns what
    arrived at the confirm route and everything that was shown."""
    service = Service(question, after=[RAN])
    shown = played(
        [
            "Go on" + ENTER,
            lambda: asker and asker[0].pending(),
            keys,
            service.over.is_set,
            lambda: not asker[0].pending(),
            INTERRUPT,
        ],
        service,
        tmp_path,
    )
    return service.bodies("/chat/confirm"), shown


# --- May this tool run -------------------------------------------------------------


@pytest.mark.parametrize(
    ("keys", "allowed", "for_good"),
    [
        ("1" + ENTER, True, False),
        ("2" + ENTER, True, True),
        ("3" + ENTER, False, False),
        # An empty field takes the marked choice — the first one, until the
        # arrow keys move the mark.
        (ENTER, True, False),
        (DOWN + ENTER, True, True),
        (DOWN + DOWN + ENTER, False, False),
        (UP + ENTER, False, False),
        (ESCAPE, False, False),
    ],
)
def test_a_tool_that_waits_for_permission_is_answered_from_the_terminal(
    keys, allowed, for_good, asker, tmp_path
):
    sent, _ = answered(TOOL_CONFIRM, keys, asker, tmp_path)
    assert sent == [
        {
            "generation_id": "g1",
            "aufruf_id": "a1",
            "erlaubt": allowed,
            "dauerhaft": for_good,
            # The service writes a standing permission for this name.
            "name": "write_file",
        }
    ]


def test_the_answered_question_stays_in_the_history_with_the_choice_taken(asker, tmp_path):
    _, shown = answered(TOOL_CONFIRM, "2" + ENTER, asker, tmp_path)
    words = Texts("en")
    lines = [" ".join(line.split()) for line in shown.splitlines()]
    asked = lines.index(words.t("werkzeug.permission_label"))
    mark = glyphs.glyph("prompt")
    assert lines[asked + 1 : asked + 9] == [
        f"Local Model {words.t('werkzeug.wants_to_run_before')}write_file",
        "path: notes.txt",
        "content: Test",
        "Outside the shared folders: notes.txt",
        words.t("werkzeug.permission_question"),
        f"1. {words.t('werkzeug.just_this_once')}",
        f"{mark} 2. {words.t('werkzeug.yes_dont_ask_again')}",
        f"3. {words.t('app.nein')}",
    ]


def test_a_key_held_with_alt_does_not_decline_the_question(asker, tmp_path):
    # A terminal sends such a key as Escape and the key right behind it.
    sent, _ = answered(TOOL_CONFIRM, ESCAPE + "b" + "1" + ENTER, asker, tmp_path)
    assert [(reply["erlaubt"], reply["dauerhaft"]) for reply in sent] == [(True, False)]


def test_text_that_picks_no_choice_grants_nothing_and_stays_in_the_field(asker, tmp_path):
    service = Service(TOOL_CONFIRM, after=[RAN])
    played(
        [
            "Go on" + ENTER,
            lambda: asker and asker[0].pending(),
            # A sentence with a digit in it, as if typed while the question
            # came up, and a number no choice has.
            "give me 2 examples" + ENTER,
            "\x15" + "7" + ENTER,
            lambda: asker[0].pending(),
            "\x15" + "3" + ENTER,
            service.over.is_set,
            lambda: not asker[0].pending(),
            INTERRUPT,
        ],
        service,
        tmp_path,
    )
    assert [reply["erlaubt"] for reply in service.bodies("/chat/confirm")] == [False]
    # Neither line went to the model in its place.
    assert [body["content"] for body in service.bodies("/chat/completions")] == ["Go on"]


# --- What the model asks -----------------------------------------------------------


@pytest.mark.parametrize(
    ("keys", "reply"),
    [
        ("1" + ENTER, {"antwort": "Red"}),
        ("2" + ENTER, {"antwort": "Blue"}),
        (ENTER, {"antwort": "Red"}),
        (DOWN + ENTER, {"antwort": "Blue"}),
        ("Something green" + ENTER, {"antwort": "Something green"}),
        # A number no option has is an answer like any other text.
        ("3" + ENTER, {"antwort": "3"}),
        # Declined: an empty answer, so the model is told none came.
        (ESCAPE, {"erlaubt": False, "antwort": ""}),
    ],
)
def test_a_question_of_the_model_is_answered_by_number_or_in_own_words(
    keys, reply, asker, tmp_path
):
    sent, _ = answered(USER_ASK, keys, asker, tmp_path)
    assert sent == [{"generation_id": "g1", "aufruf_id": "a2", **reply}]


def test_the_models_question_stays_in_the_history_with_the_words_given(asker, tmp_path):
    _, shown = answered(USER_ASK, "Something green" + ENTER, asker, tmp_path)
    lines = [" ".join(line.split()) for line in shown.splitlines()]
    asked = lines.index("Which colour?")
    assert lines[asked + 1 : asked + 5] == [
        "1. Red the warm one",
        "2. Blue",
        Texts("en").t("benutzerfrage.frei"),
        f"{glyphs.glyph('prompt')} Something green",
    ]


# --- Without a question, and a question that goes away ------------------------------


def test_without_an_open_question_a_number_is_a_message_to_the_model(asker, tmp_path):
    service = Service(None)
    played(
        [
            "2" + ENTER,
            service.over.is_set,
            lambda: len(service.bodies("/chat/completions")) == 1,
            INTERRUPT,
        ],
        service,
        tmp_path,
    )
    assert [body["content"] for body in service.bodies("/chat/completions")] == ["2"]
    assert service.bodies("/chat/confirm") == []


def test_a_question_the_service_gives_up_on_is_withdrawn_and_sends_no_answer(asker, tmp_path):
    refused = {**RAN, "fehlgeschlagen": True, "text": "No answer to the confirmation"}
    service = Service(TOOL_CONFIRM, after=[refused])
    played(
        [
            "Go on" + ENTER,
            lambda: asker and asker[0].pending(),
            # The service's own wait runs out.
            lambda: service.go_on.set() or True,
            lambda: not asker[0].pending(),
            service.over.is_set,
            # What is typed now answers nothing: it is a message again.
            "2" + ENTER,
            lambda: len(service.bodies("/chat/completions")) == 2,
            INTERRUPT,
        ],
        service,
        tmp_path,
    )
    assert service.bodies("/chat/confirm") == []
    assert [body["content"] for body in service.bodies("/chat/completions")] == ["Go on", "2"]


# --- The asker by itself -----------------------------------------------------------


class Quiet(Screen):
    """A screen that keeps what is written into the history."""

    def __init__(self) -> None:
        self.printed: list[Any] = []

    def print_above(self, *renderables: Any) -> None:
        self.printed.extend(renderables)


def standing(ask: Callable[[], Any]) -> tuple[threading.Thread, list[Any]]:
    """Asks on a thread of its own, as the client does, and keeps what the
    call returns."""
    returned: list[Any] = []
    thread = threading.Thread(target=lambda: returned.append(ask()), daemon=True)
    thread.start()
    return thread, returned


def lone_asker(language: str = "en", screen: Screen | None = None) -> Asker:
    client = ServiceClient(
        "http://service.test", language, http=httpx.Client(transport=httpx.MockTransport(Service(None)))
    )
    ctx = Context(client=client, texts=Texts(language))
    ctx.screen = screen or Quiet()
    ctx.session.models = [{"id": "local", "name": "Local Model"}]
    ctx.session.endpoint_id = "local"
    return dialogs.build_asker(ctx)


def shown_lines(asker: Asker) -> list[str]:
    return "".join(text for _, text in asker.fragments()).splitlines()


def test_no_question_stands_until_one_is_asked():
    asker = lone_asker()
    assert not asker.pending()
    assert asker.fragments() == []
    # Withdrawing nothing is nothing.
    asker.cancel()


def test_the_question_names_the_tool_its_arguments_the_reason_and_three_numbered_choices():
    asker = lone_asker()
    thread, returned = standing(lambda: asker.confirm_tool(TOOL_CONFIRM))
    until(asker.pending)
    words = Texts("en")
    mark = glyphs.glyph("prompt")
    assert shown_lines(asker) == [
        words.t("werkzeug.permission_label"),
        f"Local Model {words.t('werkzeug.wants_to_run_before')}write_file",
        "  path: notes.txt",
        "  content: Test",
        "  Outside the shared folders: notes.txt",
        words.t("werkzeug.permission_question"),
        f"{mark} 1. {words.t('werkzeug.just_this_once')}",
        f"{' ' * len(mark)} 2. {words.t('werkzeug.yes_dont_ask_again')}",
        f"{' ' * len(mark)} 3. {words.t('app.nein')}",
    ]
    asker.cancel()
    thread.join(WAIT_SECONDS)
    # Withdrawn: whoever waited sends no answer.
    assert returned == [None] and not asker.pending()


def test_an_argument_of_any_length_takes_one_line_and_the_choices_stay_in_sight():
    asker = lone_asker()
    long = {**TOOL_CONFIRM, "argumente": {"content": "line one\nline two " + "x" * 500}}
    thread, _ = standing(lambda: asker.confirm_tool(long))
    until(asker.pending)
    lines = shown_lines(asker)
    assert len(lines) == 8
    # Line breaks of the value are gone, and the line ends at the edge of
    # the window — eighty columns where no terminal says otherwise.
    assert lines[2].startswith("  content: line one line two xxx") and lines[2].endswith("…")
    assert len(lines[2]) == 80
    asker.cancel()
    thread.join(WAIT_SECONDS)


class Window:
    """Stands in for the running screen where the asker asks how large the
    terminal is."""

    def __init__(self, columns: int, rows: int) -> None:
        self.output = self
        self._size = (columns, rows)

    def get_size(self) -> Any:
        columns, rows = self._size
        return type("Size", (), {"columns": columns, "rows": rows})()


class Low(Quiet):
    """A screen that says how many rows it has for a question or a selection."""

    def __init__(self, rows: int) -> None:
        super().__init__()
        self.rows = rows

    def rows_for_question(self) -> int | None:
        return self.rows


def test_in_a_low_window_the_arguments_give_way_and_the_choices_stay(monkeypatch):
    monkeypatch.setattr(dialogs, "get_app_or_none", lambda: Window(columns=60, rows=16))
    asker = lone_asker(screen=Low(rows=11))
    many = {**TOOL_CONFIRM, "argumente": {f"field_{number}": number for number in range(20)}}
    thread, _ = standing(lambda: asker.confirm_tool(many))
    until(asker.pending)
    lines = shown_lines(asker)
    # The screen has eleven rows for the question: seven of them are the
    # question and its choices, three the first arguments, and one mark
    # stands for the seventeen that were left out.
    assert len(lines) == 11
    assert lines[2:6] == ["  field_0: 0", "  field_1: 1", "  field_2: 2", "  …"]
    words = Texts("en")
    assert [line.split(". ", 1)[1] for line in lines[-3:]] == [
        words.t("werkzeug.just_this_once"),
        words.t("werkzeug.yes_dont_ask_again"),
        words.t("app.nein"),
    ]
    asker.cancel()
    thread.join(WAIT_SECONDS)


def test_the_question_is_laid_out_once_until_the_window_or_the_mark_changes(monkeypatch):
    window = Window(columns=60, rows=40)
    monkeypatch.setattr(dialogs, "get_app_or_none", lambda: window)
    asker = lone_asker()
    thread, _ = standing(lambda: asker.confirm_tool(TOOL_CONFIRM))
    until(asker.pending)
    first = asker.fragments()
    assert asker.fragments() is first
    window._size = (40, 40)
    assert asker.fragments() is not first
    asker.cancel()
    thread.join(WAIT_SECONDS)


def test_a_second_question_takes_the_place_of_the_first_which_gets_no_answer():
    asker = lone_asker()
    first, first_returned = standing(lambda: asker.confirm_tool(TOOL_CONFIRM))
    until(asker.pending)
    second, second_returned = standing(lambda: asker.ask_user(USER_ASK))
    first.join(WAIT_SECONDS)
    assert first_returned == [None]
    until(lambda: shown_lines(asker)[:1] == ["Which colour?"])
    asker.cancel()
    second.join(WAIT_SECONDS)
    assert second_returned == [None]


def test_a_question_without_options_shows_only_the_question_and_the_line_for_own_words():
    asker = lone_asker()
    thread, _ = standing(lambda: asker.ask_user({"frage": "What now?\nAnd why?", "aufruf_id": "a3"}))
    until(asker.pending)
    assert shown_lines(asker) == ["What now?", "And why?", Texts("en").t("benutzerfrage.frei")]
    asker.cancel()
    thread.join(WAIT_SECONDS)


# --- A selection: the asker by itself ------------------------------------------------


def entries(count: int, in_use: int | None = None) -> list[Entry]:
    """``count`` entries of two columns; ``in_use`` counts from zero."""
    return [
        Entry(
            cells=[("text", f"Entry {number}"), ("muted", f"info {number}")],
            in_use=number - 1 == in_use,
        )
        for number in range(1, count + 1)
    ]


def press(asker: Asker, key: str, typed: str = "") -> Buffer:
    """Presses ``key`` the way the screen would: the binding the asker
    claims for it right now, with ``typed`` standing in the input field.
    Returns the field as the key left it."""
    field = Buffer()
    field.text = typed
    bindings = asker.key_bindings()
    assert bindings is not None
    claimed = [binding for binding in bindings.get_bindings_for_keys((key,)) if binding.filter()]
    assert claimed, f"the asker claims no {key}"
    claimed[-1].handler(SimpleNamespace(current_buffer=field))  # type: ignore[arg-type]
    return field


def marked_number(asker: Asker) -> int | None:
    """The number of the entry that carries the mark, as it is drawn —
    ``None`` where no drawn line carries it."""
    mark = glyphs.glyph("prompt") + " "
    for line in shown_lines(asker):
        if line.startswith(mark):
            return int(line[len(mark) :].split(".")[0])
    return None


def in_use_sign() -> str:
    return "●" if glyphs.speaks_unicode() else "*"


@pytest.fixture
def wide(monkeypatch: pytest.MonkeyPatch) -> None:
    """A window wide enough for the line with the keys to stand whole."""
    monkeypatch.setattr(dialogs, "get_app_or_none", lambda: Window(columns=100, rows=40))


def test_a_selection_shows_every_entry_with_its_number_and_names_the_keys_below(wide: None) -> None:
    asker = lone_asker()
    thread, returned = standing(lambda: asker.choose(entries(3, in_use=1)))
    until(asker.pending)
    mark, sign = glyphs.glyph("prompt"), in_use_sign()
    none = " " * len(mark)
    # The mark opens on the entry in use, and that one carries the sign.
    assert shown_lines(asker) == [
        f"{none} 1. {' ' * len(sign)} Entry 1  info 1",
        f"{mark} 2. {sign} Entry 2  info 2",
        f"{none} 3. {' ' * len(sign)} Entry 3  info 3",
        Texts("en").t("cli.select_keys"),
    ]
    asker.close()
    thread.join(WAIT_SECONDS)
    assert returned == [None] and not asker.pending()


def test_a_selection_with_a_head_shows_its_lines_above_the_entries_and_counts_them_out(
    wide: None,
) -> None:
    asker = lone_asker()
    thread, returned = standing(
        lambda: asker.choose(entries(2), head="Stop it and start the other?\nIt is writing.")
    )
    until(asker.pending)
    mark = glyphs.glyph("prompt")
    none, sign = " " * len(mark), " " * len(in_use_sign())
    assert shown_lines(asker) == [
        "Stop it and start the other?",
        "It is writing.",
        f"{mark} 1. {sign} Entry 1  info 1",
        f"{none} 2. {sign} Entry 2  info 2",
        Texts("en").t("cli.select_keys"),
    ]
    # The head is no entry: the first number is the first entry's.
    assert marked_number(asker) == 1
    press(asker, Keys.Down)
    assert marked_number(asker) == 2
    press(asker, Keys.Enter)
    thread.join(WAIT_SECONDS)
    assert returned == [1]


def test_without_an_entry_in_use_the_mark_opens_on_the_first_and_no_sign_stands() -> None:
    asker = lone_asker()
    thread, _ = standing(lambda: asker.choose(entries(3)))
    until(asker.pending)
    assert marked_number(asker) == 1
    assert not any(in_use_sign() in line for line in shown_lines(asker)[:3])
    asker.close()
    thread.join(WAIT_SECONDS)


@pytest.mark.parametrize(("unicode", "sign"), [(True, "●"), (False, "*")])
def test_the_entry_in_use_carries_a_circle_and_a_star_where_the_output_has_no_circle(
    monkeypatch: pytest.MonkeyPatch, unicode: bool, sign: str
) -> None:
    monkeypatch.setattr(glyphs, "speaks_unicode", lambda: unicode)
    asker = lone_asker()
    thread, _ = standing(lambda: asker.choose(entries(2, in_use=0)))
    until(asker.pending)
    first, second = shown_lines(asker)[:2]
    assert first == f"{glyphs.glyph('prompt')} 1. {sign} Entry 1  info 1"
    assert sign not in second
    asker.close()
    thread.join(WAIT_SECONDS)


@pytest.mark.parametrize(
    ("keys", "typed", "picked"),
    [
        # The enter key takes the marked entry: the one in use, until the
        # mark is moved.
        ([], "", 1),
        ([Keys.Down], "", 2),
        ([Keys.Down, Keys.Down], "", 3),
        ([Keys.Up], "", 0),
        ([Keys.Tab], "", 2),
        ([Keys.Tab, Keys.Tab, Keys.BackTab], "", 2),
        ([Keys.BackTab], "", 0),
        # Past the last entry the mark stands on the first again, and back.
        ([Keys.Down, Keys.Down, Keys.Down], "", 0),
        ([Keys.Up, Keys.Up], "", 3),
        # A number takes the entry of that number, wherever the mark is.
        ([], "4", 3),
        ([Keys.Down], "1", 0),
        ([], " 3 ", 2),
    ],
)
def test_arrows_and_the_tabulator_move_the_mark_and_enter_or_a_number_picks(
    keys: list[str], typed: str, picked: int
) -> None:
    asker = lone_asker()
    thread, returned = standing(lambda: asker.choose(entries(4, in_use=1)))
    until(asker.pending)
    for key in keys:
        press(asker, key)
    field = press(asker, Keys.Enter, typed)
    thread.join(WAIT_SECONDS)
    assert returned == [picked] and not asker.pending()
    # The number went with the pick; it is no message.
    assert field.text == ""


def test_the_mark_is_drawn_where_the_keys_moved_it() -> None:
    asker = lone_asker()
    thread, _ = standing(lambda: asker.choose(entries(3)))
    until(asker.pending)
    seen = [marked_number(asker)]
    for key in (Keys.Down, Keys.Tab, Keys.Down, Keys.Up, Keys.BackTab):
        press(asker, key)
        seen.append(marked_number(asker))
    assert seen == [1, 2, 3, 1, 3, 2]
    asker.close()
    thread.join(WAIT_SECONDS)


def test_twelve_and_enter_pick_the_twelfth_of_fifteen_entries() -> None:
    asker = lone_asker()
    thread, returned = standing(lambda: asker.choose(entries(15)))
    until(asker.pending)
    lines = shown_lines(asker)
    # The numbers stand below each other, the short ones set in.
    assert lines[0].split(".")[0].endswith(" 1") and lines[11].split(".")[0].endswith("12")
    assert lines[0].index("Entry") == lines[11].index("Entry")
    press(asker, Keys.Enter, "12")
    thread.join(WAIT_SECONDS)
    assert returned == [11]


@pytest.mark.parametrize("typed", ["16", "0", "give me 2 examples", "/model", "2."])
def test_text_that_names_no_entry_picks_nothing_and_stays_in_the_field(typed: str) -> None:
    asker = lone_asker()
    thread, returned = standing(lambda: asker.choose(entries(15)))
    until(asker.pending)
    field = press(asker, Keys.Enter, typed)
    assert asker.pending() and returned == []
    assert field.text == typed
    asker.close()
    thread.join(WAIT_SECONDS)


def test_escape_closes_the_selection_with_nothing_picked() -> None:
    screen = Quiet()
    asker = lone_asker(screen=screen)
    thread, returned = standing(lambda: asker.choose(entries(3, in_use=1)))
    until(asker.pending)
    press(asker, Keys.Down)
    field = press(asker, Keys.Escape, "half a sentence")
    thread.join(WAIT_SECONDS)
    assert returned == [None] and not asker.pending()
    assert asker.fragments() == []
    # What stood in the field stays there, and nothing went into the history.
    assert field.text == "half a sentence"
    assert screen.printed == []


def test_the_interrupt_key_closes_the_selection_like_escape_and_leaves_the_field_alone() -> None:
    screen = Quiet()
    asker = lone_asker(screen=screen)
    thread, returned = standing(lambda: asker.choose(entries(3, in_use=1)))
    until(asker.pending)
    press(asker, Keys.Down)
    field = press(asker, Keys.ControlC, "half a sentence")
    thread.join(WAIT_SECONDS)
    assert returned == [None] and not asker.pending()
    assert field.text == "half a sentence"
    assert screen.printed == []


def test_the_interrupt_key_is_not_claimed_under_a_question_of_the_service() -> None:
    """Silence probe: under a question of the service the key stays the
    screen's — it stops the answer that is running."""
    asker = lone_asker()
    thread, _ = standing(lambda: asker.confirm_tool(TOOL_CONFIRM))
    until(asker.pending)
    bindings = asker.key_bindings()
    assert bindings is not None
    assert [binding for binding in bindings.get_bindings_for_keys((Keys.ControlC,)) if binding.filter()] == []
    asker.cancel()
    thread.join(WAIT_SECONDS)


def test_a_pick_leaves_nothing_in_the_history() -> None:
    screen = Quiet()
    asker = lone_asker(screen=screen)
    thread, returned = standing(lambda: asker.choose(entries(3)))
    until(asker.pending)
    press(asker, Keys.Enter, "2")
    thread.join(WAIT_SECONDS)
    assert returned == [1]
    assert screen.printed == []


def test_no_entries_are_no_selection() -> None:
    asker = lone_asker()
    assert asker.choose([]) is None
    assert not asker.pending()


def test_the_columns_stand_below_each_other_whatever_the_names_are() -> None:
    asker = lone_asker()
    listed = [
        Entry(cells=[("text", "A"), ("muted", "first"), ("green", "connected"), ("muted", "8192")]),
        Entry(cells=[("text", "A longer name"), ("muted", "second"), ("red", "away"), ("muted", "")]),
        Entry(cells=[("text", "Mid"), ("muted", ""), ("green", ""), ("muted", "200000")]),
    ]
    thread, _ = standing(lambda: asker.choose(listed))
    until(asker.pending)
    first, second, third = shown_lines(asker)[:3]
    assert first.index("first") == second.index("second")
    assert first.index("connected") == second.index("away")
    assert first.index("8192") == third.index("200000")
    # A line ends with the last thing it says.
    assert second.endswith("away") and third.endswith("200000")
    asker.close()
    thread.join(WAIT_SECONDS)


def test_the_colours_of_the_columns_are_the_entries_own_and_the_marked_name_is_set_off(
    wide: None,
) -> None:
    asker = lone_asker()
    listed = [
        Entry(cells=[("text", "One"), ("green", "connected")], in_use=True),
        Entry(cells=[("text", "Two"), ("red", "away")]),
    ]
    thread, _ = standing(lambda: asker.choose(listed))
    until(asker.pending)
    styled = {text.strip(): style for style, text in asker.fragments() if text.strip()}
    assert styled["One"] == "class:accent" and styled["Two"] == "class:text"
    assert styled["connected"] == "class:green" and styled["away"] == "class:red"
    assert styled[Texts("en").t("cli.select_keys")] == "class:muted"
    asker.close()
    thread.join(WAIT_SECONDS)


def test_a_name_too_long_for_the_window_is_cut_and_the_columns_behind_it_stay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dialogs, "get_app_or_none", lambda: Window(columns=40, rows=40))
    asker = lone_asker()
    listed = [
        Entry(cells=[("text", "A title that runs on and on and on and on"), ("muted", "2026-10-12 16:27")]),
        Entry(cells=[("text", "Short"), ("muted", "2026-10-11 09:00")]),
    ]
    thread, _ = standing(lambda: asker.choose(listed))
    until(asker.pending)
    long, short = shown_lines(asker)[:2]
    assert get_cwidth(long) == 40 and "…" in long
    assert long.endswith("2026-10-12 16:27") and short.endswith("2026-10-11 09:00")
    assert long.index("2026-10-12") == short.index("2026-10-11")
    asker.close()
    thread.join(WAIT_SECONDS)


@pytest.mark.parametrize("language", ["en", "de"])
def test_a_remark_too_long_for_the_line_goes_on_below_its_own_beginning(
    monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    monkeypatch.setattr(dialogs, "get_app_or_none", lambda: Window(columns=60, rows=40))
    asker = lone_asker(language)
    remark = Texts(language).t("cli.theme_auto")
    listed = [
        Entry(cells=[("text", "auto")], note=remark),
        Entry(cells=[("text", "darkmatter")], in_use=True),
    ]
    thread, _ = standing(lambda: asker.choose(listed))
    until(asker.pending)
    lines = shown_lines(asker)
    below = lines.index(next(line for line in lines if "darkmatter" in line))
    carried = lines[:below]
    assert len(carried) > 1
    # It begins behind the widest name and goes on in that very column.
    begins = carried[0].index(remark.split()[0])
    assert begins > lines[below].index("darkmatter") + len("darkmatter")
    assert all(line[:begins].strip() == "" for line in carried[1:])
    # Broken at blanks only, nothing lost, no line wider than the window.
    assert " ".join(line[begins:] for line in carried) == remark
    assert all(get_cwidth(line) <= 60 for line in lines)
    asker.close()
    thread.join(WAIT_SECONDS)


@pytest.mark.parametrize("language", ["en", "de"])
@pytest.mark.parametrize("columns", [200, 60, 45, 12])
def test_the_line_with_the_keys_is_broken_between_two_groups_only(
    monkeypatch: pytest.MonkeyPatch, language: str, columns: int
) -> None:
    monkeypatch.setattr(dialogs, "get_app_or_none", lambda: Window(columns=columns, rows=40))
    asker = lone_asker(language)
    thread, _ = standing(lambda: asker.choose(entries(2)))
    until(asker.pending)
    sentence = Texts(language).t("cli.select_keys")
    groups = sentence.split(" · ")
    assert len(groups) == 4
    foot = shown_lines(asker)[2:]
    # Every line is whole groups, in their order; none is left out.
    assert [group for line in foot for group in line.split(" · ")] == groups
    # As many groups in a line as the window takes; one alone is never cut.
    assert all(get_cwidth(line) <= columns or " · " not in line for line in foot)
    assert len(foot) == {200: 1, 60: 2, 12: 4}.get(columns, len(foot))
    asker.close()
    thread.join(WAIT_SECONDS)


def test_more_entries_than_rows_show_the_ones_around_the_mark_with_a_sign_at_each_open_side(
    wide: None,
) -> None:
    screen = Low(rows=8)
    asker = lone_asker(screen=screen)
    thread, _ = standing(lambda: asker.choose(entries(20)))
    until(asker.pending)
    more = " " * (len(glyphs.glyph("prompt")) + 1) + glyphs.glyph("more")
    keys = Texts("en").t("cli.select_keys")

    def numbers() -> list[str]:
        return [line.split(".")[0].split()[-1] for line in shown_lines(asker) if ". " in line[:8]]

    # At the top: nothing is left out above, so no sign stands there.
    lines = shown_lines(asker)
    assert len(lines) == 8 and lines[-1] == keys and lines[-2] == more
    assert numbers() == ["1", "2", "3", "4", "5", "6"]
    # In the middle: a sign at each side, and the marked entry among the
    # ones between them.
    for _ in range(9):
        press(asker, Keys.Down)
    lines = shown_lines(asker)
    assert len(lines) == 8 and lines[0] == more and lines[-2] == more
    assert marked_number(asker) == 10 and "10" in numbers()
    # At the end: nothing is left out below.
    press(asker, Keys.Up)
    for _ in range(10):
        press(asker, Keys.Up)
    assert marked_number(asker) == 19
    press(asker, Keys.Down)
    lines = shown_lines(asker)
    assert len(lines) == 8 and lines[0] == more and lines[-2] != more
    assert numbers()[-1] == "20" and marked_number(asker) == 20
    asker.close()
    thread.join(WAIT_SECONDS)


def test_the_section_moves_no_further_than_the_mark_needs() -> None:
    asker = lone_asker(screen=Low(rows=8))
    thread, _ = standing(lambda: asker.choose(entries(20)))
    until(asker.pending)

    def first_shown() -> int:
        return next(int(line.split(".")[0].split()[-1]) for line in shown_lines(asker) if ". " in line[:8])

    for _ in range(12):
        press(asker, Keys.Down)
    at = first_shown()
    # One step back up: the mark is still in sight, so nothing moves.
    press(asker, Keys.Up)
    assert first_shown() == at and marked_number(asker) == 12
    asker.close()
    thread.join(WAIT_SECONDS)


def test_a_selection_keeps_its_height_whichever_entries_it_shows() -> None:
    """Entries of one row and of several: the rows the selection takes stay
    the same while the mark runs through all of them, so the block below it
    never moves."""
    asker = lone_asker(screen=Low(rows=9))
    remark = Texts("en").t("cli.theme_auto") + " " + Texts("en").t("cli.theme_auto")
    listed = [
        Entry(cells=[("text", f"Entry {number}")], note=remark if number % 4 == 0 else "")
        for number in range(1, 17)
    ]
    thread, _ = standing(lambda: asker.choose(listed))
    until(asker.pending)
    heights, marked = [], []
    for _ in range(len(listed) + 2):
        heights.append(len(shown_lines(asker)))
        marked.append(marked_number(asker))
        press(asker, Keys.Down)
    assert set(heights) == {9}
    assert marked == [*range(1, 17), 1, 2]
    asker.close()
    thread.join(WAIT_SECONDS)


def test_a_selection_is_laid_out_once_until_the_mark_or_its_room_changes() -> None:
    screen = Low(rows=8)
    asker = lone_asker(screen=screen)
    thread, _ = standing(lambda: asker.choose(entries(20)))
    until(asker.pending)
    first = asker.fragments()
    assert asker.fragments() is first
    press(asker, Keys.Down)
    moved = asker.fragments()
    assert moved is not first and asker.fragments() is moved
    screen.rows = 12
    assert len(shown_lines(asker)) == 12
    asker.close()
    thread.join(WAIT_SECONDS)


# --- A selection and the questions of the service ------------------------------------


def test_while_a_question_of_the_service_stands_no_selection_opens_and_it_stays_answerable() -> None:
    asker = lone_asker()
    thread, returned = standing(lambda: asker.confirm_tool(TOOL_CONFIRM))
    until(asker.pending)
    asked = shown_lines(asker)
    # Returns at once: nothing is waited for, and nothing was shown.
    assert asker.choose(entries(3)) is None
    assert shown_lines(asker) == asked
    press(asker, Keys.Enter, "1")
    thread.join(WAIT_SECONDS)
    assert returned == [{"erlaubt": True, "dauerhaft": False}]


def test_a_question_of_the_service_that_arrives_closes_the_selection_with_nothing_picked() -> None:
    asker = lone_asker()
    selecting, picked = standing(lambda: asker.choose(entries(3)))
    until(asker.pending)
    asking, answer = standing(lambda: asker.ask_user(USER_ASK))
    selecting.join(WAIT_SECONDS)
    assert picked == [None]
    until(lambda: shown_lines(asker)[:1] == ["Which colour?"])
    press(asker, Keys.Enter, "2")
    asking.join(WAIT_SECONDS)
    assert answer == [{"antwort": "Blue"}]


def test_a_second_selection_does_not_take_the_place_of_the_first(wide: None) -> None:
    asker = lone_asker()
    thread, returned = standing(lambda: asker.choose(entries(3)))
    until(asker.pending)
    assert asker.choose(entries(5)) is None
    assert len(shown_lines(asker)) == 4
    press(asker, Keys.Enter, "3")
    thread.join(WAIT_SECONDS)
    assert returned == [2]


def test_the_end_of_an_answer_leaves_a_selection_standing_and_leaving_closes_it() -> None:
    asker = lone_asker()
    thread, returned = standing(lambda: asker.choose(entries(3)))
    until(asker.pending)
    # What the client calls when an answer is over, or its question has
    # been settled: the selection is none of the answer's.
    asker.cancel()
    assert asker.pending() and returned == []
    asker.close()
    thread.join(WAIT_SECONDS)
    assert returned == [None] and not asker.pending()


def test_leaving_withdraws_a_question_of_the_service_as_well() -> None:
    asker = lone_asker()
    thread, returned = standing(lambda: asker.confirm_tool(TOOL_CONFIRM))
    until(asker.pending)
    asker.close()
    thread.join(WAIT_SECONDS)
    assert returned == [None] and not asker.pending()
    # Closing nothing is nothing.
    asker.close()


def test_once_the_client_has_left_nothing_is_asked_and_nobody_waits() -> None:
    """A command that reaches its selection only after the screen is gone
    is not left waiting for a pick nobody can make."""
    asker = lone_asker()
    asker.close()
    assert asker.choose(entries(3)) is None
    assert asker.confirm_tool(TOOL_CONFIRM) is None
    assert asker.ask_user(USER_ASK) is None
    assert not asker.pending()


def drawn_rows(asker: Asker, columns: int) -> int:
    """The rows the window draws the selection in: a line wider than the
    window goes on in the next row."""
    return sum(max(1, -(-get_cwidth(line) // columns)) for line in shown_lines(asker))


@pytest.mark.parametrize("language", ["en", "de"])
def test_in_a_window_narrower_than_a_group_of_keys_the_selection_still_keeps_to_its_rows(
    monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    """The line with the keys cannot be broken inside a group, so the window
    breaks it; the rows that takes are the selection's own, and the marked
    entry stays among the ones drawn."""
    columns = 24
    monkeypatch.setattr(dialogs, "get_app_or_none", lambda: Window(columns=columns, rows=40))
    asker = lone_asker(language, screen=Low(rows=12))
    thread, _ = standing(lambda: asker.choose(entries(30)))
    until(asker.pending)
    assert any(get_cwidth(line) > columns for line in shown_lines(asker))
    for expected in range(1, 34):
        assert marked_number(asker) == (expected - 1) % 30 + 1
        assert drawn_rows(asker, columns) == 12
        press(asker, Keys.Down)
    asker.close()
    thread.join(WAIT_SECONDS)


def test_under_a_question_of_the_service_the_tabulator_is_not_the_askers() -> None:
    """Silence probe: there it keeps what it does in the input field."""
    asker = lone_asker()
    thread, _ = standing(lambda: asker.confirm_tool(TOOL_CONFIRM))
    until(asker.pending)
    bindings = asker.key_bindings()
    assert bindings is not None
    for key in (Keys.Tab, Keys.BackTab):
        assert not [binding for binding in bindings.get_bindings_for_keys((key,)) if binding.filter()]
    asker.cancel()
    thread.join(WAIT_SECONDS)


# --- A selection on the real screen --------------------------------------------------


def screen_on(service: Callable[[httpx.Request], httpx.Response], tmp_path: Path) -> Context:
    """The client's parts with the real screen, built and not running, on
    the session's output — wired to ``service``."""
    client = ServiceClient(
        "http://service.test", "en", http=httpx.Client(transport=httpx.MockTransport(service))
    )
    client.connect()
    ctx = Context(client=client, texts=Texts("en"), prefs_path=tmp_path / "cli.json")
    ctx.status = build_status(ctx)
    ctx.renderer = build_renderer(ctx)
    ctx.asker = dialogs.build_asker(ctx)
    ctx.commands = commands.build_commands(ctx)
    ctx.screen = CliApp(ctx)
    return ctx


def test_the_screen_says_how_many_rows_stand_above_the_rest_of_its_block(tmp_path: Path) -> None:
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=Terminal(columns=100, rows=20)):
        ctx = screen_on(Lists(), tmp_path)
        screen = ctx.screen
        assert isinstance(screen, CliApp)
        assert screen.rows_for_question() == 20 - BLOCK_ROWS == 13
        # A field that grew leaves less.
        screen._input.buffer.text = "one\ntwo\nthree"
        assert screen.rows_for_question() == 11
        # So does a hint of several lines.
        screen._input.buffer.text = ""
        screen.set_notice("one\ntwo")
        assert screen.rows_for_question() == 12


@pytest.mark.parametrize(("rows", "arguments_stand"), [(15, False), (40, True)])
def test_a_question_of_the_service_takes_the_rows_the_screen_has_above_its_block(
    rows: int, arguments_stand: bool, tmp_path: Path
) -> None:
    """The fixed block takes seven rows, and the question reckons with what
    is left of the window: in a low one the question and its three answers
    stand whole in it and the arguments give way — a window of fifteen rows
    leaves eight, and a count that took five for the block would draw ten.
    In a high one nothing is left out."""
    many = {**TOOL_CONFIRM, "argumente": {f"field_{number}": number for number in range(20)}}
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=Terminal(columns=100, rows=rows)):
        ctx = screen_on(Lists(), tmp_path)
        thread, _ = standing(lambda: ctx.asker.confirm_tool(many))
        until(ctx.asker.pending)
        room = ctx.screen.rows_for_question()
        assert room == rows - BLOCK_ROWS
        lines = shown_lines(ctx.asker)
        words = Texts("en")
        assert [line.split(". ", 1)[1] for line in lines[-3:]] == [
            words.t("werkzeug.just_this_once"),
            words.t("werkzeug.yes_dont_ask_again"),
            words.t("app.nein"),
        ]
        assert len(lines) <= room
        assert ("  field_19: 19" in lines) is arguments_stand
        assert ("  …" in lines) is not arguments_stand
        ctx.asker.cancel()
        thread.join(WAIT_SECONDS)


@pytest.mark.parametrize("look", themes.available())
def test_a_question_and_a_selection_stand_on_the_terminals_ground_in_every_look(
    look: str, tmp_path: Path
) -> None:
    themes.set_look(look)
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=Terminal(columns=100, rows=20)):
        ctx = screen_on(Lists(), tmp_path)
        screen = ctx.screen
        assert isinstance(screen, CliApp)
        asked = [
            window
            for window in walk(screen._app.layout.container)
            if isinstance(window, LayoutWindow)
            and isinstance(window.content, FormattedTextControl)
            and window.content.text == ctx.asker.fragments
        ]
        assert len(asked) == 1
        style = asked[0].style
        assert isinstance(style, str)
        drawn = screen._app.renderer.style.get_attrs_for_style_str(style)
        # No ground of its own: not the library's blue, and no other one.
        assert drawn.bgcolor in ("", "default")
        # The writing is the look's.
        assert drawn.color == themes.current().prompt_style().get_attrs_for_style_str("class:input").color
        # The rest of the block has no ground either, so the two match.
        assert screen._app.renderer.style.get_attrs_for_style_str("class:input").bgcolor == ""


def test_with_forty_chats_in_a_window_of_twenty_rows_the_marked_one_is_drawn_after_every_key(
    tmp_path: Path,
) -> None:
    service = Lists()
    service.chats = {
        f"c{number}": {"id": f"c{number}", "title": f"Chat {number}", "updated_at": "2026-03-04T10:00:00+00:00"}
        for number in range(1, 41)
    }
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=Terminal(columns=100, rows=20)):
        ctx = screen_on(service, tmp_path)
        thread, _ = standing(lambda: ctx.commands.run("/chats"))
        until(ctx.asker.pending)
        room = ctx.screen.rows_for_question()
        assert room == 13
        drawn: list[tuple[int | None, int]] = []
        keys = [Keys.Down] * 45 + [Keys.Up] * 50 + [Keys.Tab] * 3 + [Keys.BackTab] * 6
        expected, at = [], 1
        for key in keys:
            press(ctx.asker, key)
            at = (at - 1 + (1 if key in (Keys.Down, Keys.Tab) else -1)) % 40 + 1
            expected.append(at)
            drawn.append((marked_number(ctx.asker), len(shown_lines(ctx.asker))))
        # After every key the marked chat stands among the drawn lines, and
        # the selection takes exactly the rows the screen has for it.
        assert [number for number, _ in drawn] == expected
        assert {rows for _, rows in drawn} == {room}
        press(ctx.asker, Keys.Escape)
        thread.join(WAIT_SECONDS)
        assert ctx.session.chat is None


def test_a_command_that_finds_a_question_standing_opens_nothing_and_the_question_is_answered(
    tmp_path: Path,
) -> None:
    service = Lists()
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        ctx = screen_on(service, tmp_path)
        ctx.session.endpoint_id = "local"
        asking, answer = standing(lambda: ctx.asker.confirm_tool(TOOL_CONFIRM))
        until(ctx.asker.pending)
        asked = shown_lines(ctx.asker)
        # Returns by itself: no selection waits for a pick.
        ctx.commands.run("/model")
        assert shown_lines(ctx.asker) == asked
        assert ctx.session.endpoint_id == "local"
        assert not service.asked("PUT", f"/settings/global/{commands.LAST_MODEL_KEY}")
        press(ctx.asker, Keys.Enter, "1")
        asking.join(WAIT_SECONDS)
        assert answer == [{"erlaubt": True, "dauerhaft": False}]


# --- A selection, through the whole client ---------------------------------------------


def selecting(asker: list[Asker]) -> bool:
    return bool(asker) and asker[0].pending()


def chosen(service: Lists) -> list[Any]:
    return service.bodies("PUT", f"/settings/global/{commands.LAST_MODEL_KEY}")


@pytest.mark.parametrize(
    ("keys", "model"),
    [
        (DOWN + ENTER, "remote"),
        (TAB + ENTER, "remote"),
        (TAB + BACK_TAB + ENTER, "local"),
        (UP + ENTER, "remote"),
        ("2" + ENTER, "remote"),
        (ENTER, "local"),
    ],
)
def test_the_keys_pick_a_model_from_the_selection_and_nothing_goes_to_the_model_or_the_history(
    keys: str, model: str, asker: list[Asker], tmp_path: Path
) -> None:
    service = Lists()
    shown = played(
        ["/model" + ENTER, lambda: selecting(asker), keys, lambda: chosen(service), "/quit" + ENTER],
        service,
        tmp_path,
    )
    assert [body["wert"]["id"] for body in chosen(service)] == [model]
    assert not service.asked("POST", "/chat/completions")
    # Neither the selection nor a list of models stands in the history:
    # not the line with the keys, and not the column only the list has.
    assert Texts("en").t("cli.select_keys") not in shown
    assert "there" not in shown and "here" not in shown.split()


def test_twelve_and_enter_open_the_twelfth_of_fifteen_chats(asker: list[Asker], tmp_path: Path) -> None:
    service = Lists()
    service.chats = {
        f"c{number}": {"id": f"c{number}", "title": f"Chat {number}", "updated_at": "2026-03-04T10:00:00+00:00"}
        for number in range(1, 16)
    }
    played(
        [
            "/chats" + ENTER,
            lambda: selecting(asker),
            "12" + ENTER,
            lambda: service.asked("GET", "/chats/c12/messages"),
            "/quit" + ENTER,
        ],
        service,
        tmp_path,
    )
    opened = [request.url.path for request in service.seen if request.url.path.endswith("/messages")]
    assert opened == ["/api/v1/chats/c12/messages"]
    assert not service.asked("POST", "/chat/completions")


def test_escape_changes_nothing_and_a_number_typed_afterwards_is_a_message(
    asker: list[Asker], tmp_path: Path
) -> None:
    service = Lists()
    shown = played(
        [
            "/model" + ENTER,
            lambda: selecting(asker),
            DOWN + ESCAPE,
            lambda: not asker[0].pending(),
            # No selection stands: this is no pick, it is said to the model.
            "2" + ENTER,
            lambda: service.asked("POST", "/chat/completions"),
            "/quit" + ENTER,
        ],
        service,
        tmp_path,
    )
    assert chosen(service) == []
    sent = service.bodies("POST", "/chat/completions")
    assert [(body["content"], body["endpoint_id"]) for body in sent] == [("2", "local")]
    assert Texts("en").t("cli.select_keys") not in shown


def test_the_interrupt_key_closes_the_selection_in_an_empty_field_and_the_client_runs_on(
    asker: list[Asker], tmp_path: Path
) -> None:
    service = Lists()
    played(
        [
            "/model" + ENTER,
            lambda: selecting(asker),
            INTERRUPT,
            lambda: not asker[0].pending(),
            # The client is still there: with no selection standing, this
            # goes to the model as a message.
            "hello" + ENTER,
            lambda: service.asked("POST", "/chat/completions"),
            "/quit" + ENTER,
        ],
        service,
        tmp_path,
    )
    assert chosen(service) == []
    sent = service.bodies("POST", "/chat/completions")
    assert [body["content"] for body in sent] == ["hello"]


def test_other_text_picks_nothing_stays_in_the_field_and_never_reaches_the_model(
    asker: list[Asker], tmp_path: Path
) -> None:
    service = Lists()
    played(
        [
            "/model" + ENTER,
            lambda: selecting(asker),
            "give me 2 examples" + ENTER,
            CLEAR_FIELD + "7" + ENTER,
            lambda: asker[0].pending(),
            CLEAR_FIELD + ESCAPE,
            lambda: not asker[0].pending(),
            "/quit" + ENTER,
        ],
        service,
        tmp_path,
    )
    assert chosen(service) == []
    assert not service.asked("POST", "/chat/completions")


def test_leaving_with_a_selection_open_lets_go_of_the_command_that_waits_for_the_pick(
    asker: list[Asker], tmp_path: Path
) -> None:
    service = Lists()
    played(["/model" + ENTER, lambda: selecting(asker), END_OF_INPUT], service, tmp_path)
    # The selection went with the screen, and the command with it. Still
    # waiting for a pick, it would hold the client for as long as that
    # waits for its threads, and the selection would stand for good.
    assert not asker[0].pending()
    assert chosen(service) == []


# --- A checklist ------------------------------------------------------------------------


def box(ticked: bool) -> str:
    return glyphs.glyph("checked" if ticked else "unchecked")


def test_a_checklist_shows_which_entries_are_ticked_and_names_its_own_keys(wide: None) -> None:
    asker = lone_asker()
    thread, returned = standing(lambda: asker.check(entries(3), checked=[1]))
    until(asker.pending)
    mark = glyphs.glyph("prompt")
    none = " " * len(mark)
    assert shown_lines(asker) == [
        f"{mark} 1. {box(False)} Entry 1  info 1",
        f"{none} 2. {box(True)} Entry 2  info 2",
        f"{none} 3. {box(False)} Entry 3  info 3",
        Texts("en").t("cli.select_keys_check"),
    ]
    asker.close()
    thread.join(WAIT_SECONDS)
    assert returned == [None]


def test_the_space_bar_ticks_the_marked_entry_writes_nothing_and_enter_confirms(wide: None) -> None:
    asker = lone_asker()
    thread, returned = standing(lambda: asker.check(entries(3), checked=[2]))
    until(asker.pending)
    assert press(asker, " ").text == ""
    press(asker, Keys.Down)
    press(asker, " ")
    # Entry 1 and entry 2 were ticked beside entry 3: all three stand ticked.
    assert [line for line in shown_lines(asker) if box(True) in line].__len__() == 3
    # Ticking the marked one again unticks it.
    press(asker, " ")
    assert [line for line in shown_lines(asker) if box(True) in line].__len__() == 2
    press(asker, Keys.Enter)
    thread.join(WAIT_SECONDS)
    assert returned == [[0, 2]]


def test_a_checklist_confirmed_as_it_stands_returns_what_was_ticked_and_ignores_typing() -> None:
    asker = lone_asker()
    thread, returned = standing(lambda: asker.check(entries(3), checked=[2, 0]))
    until(asker.pending)
    press(asker, Keys.Enter, typed="2")
    thread.join(WAIT_SECONDS)
    assert returned == [[0, 2]]


def test_escape_closes_a_checklist_with_nothing_confirmed() -> None:
    asker = lone_asker()
    thread, returned = standing(lambda: asker.check(entries(2), checked=[0]))
    until(asker.pending)
    press(asker, Keys.Escape)
    thread.join(WAIT_SECONDS)
    assert returned == [None]


def test_a_list_without_entries_is_no_checklist() -> None:
    assert lone_asker().check([]) is None


def test_the_space_bar_does_nothing_where_no_checklist_stands() -> None:
    asker = lone_asker()
    thread, _ = standing(lambda: asker.choose(entries(2)))
    until(asker.pending)
    bindings = asker.key_bindings()
    assert bindings is not None
    claimed = [b for b in bindings.get_bindings_for_keys((" ",)) if b.filter()]
    assert claimed == []
    asker.close()
    thread.join(WAIT_SECONDS)


# --- A selection that searches --------------------------------------------------------------


def named(*titles: str) -> list[Entry]:
    return [Entry(cells=[("text", title)], value=title) for title in titles]


def until_lines(asker: Asker, wanted: Callable[[list[str]], bool]) -> None:
    until(lambda: wanted(shown_lines(asker)))


def test_a_word_typed_replaces_the_entries_with_what_was_found_renumbered(wide: None) -> None:
    asker = lone_asker()
    asked: list[str] = []

    def find(word: str) -> list[Entry]:
        asked.append(word)
        return named("Website texts") if word == "web" else []

    thread, returned = standing(lambda: asker.search(named("Tax", "Website texts", "Notes"), find))
    until(asker.pending)
    assert [line for line in shown_lines(asker) if "Tax" in line or "Notes" in line]
    asker.typed("web")
    until_lines(asker, lambda lines: any("Website texts" in line for line in lines)
                and not any("Tax" in line for line in lines))
    assert asked == ["web"]
    keys = Texts("en").t("cli.select_keys_search")
    assert shown_lines(asker)[-1] == keys
    press(asker, Keys.Enter, typed="web")
    thread.join(WAIT_SECONDS)
    assert returned and returned[0].value == "Website texts"


def test_a_number_or_an_empty_field_shows_the_opening_entries_again_and_picks_by_number(wide: None) -> None:
    asker = lone_asker()
    thread, returned = standing(
        lambda: asker.search(named("Tax", "Website texts", "Notes"), lambda word: named("Website texts"))
    )
    until(asker.pending)
    asker.typed("web")
    until_lines(asker, lambda lines: not any("Tax" in line for line in lines))
    asker.typed("")
    until_lines(asker, lambda lines: any("Tax" in line for line in lines))
    asker.typed("3")
    until_lines(asker, lambda lines: any("Notes" in line for line in lines))
    press(asker, Keys.Enter, typed="3")
    thread.join(WAIT_SECONDS)
    assert returned and returned[0].value == "Notes"


def test_an_answer_that_comes_after_a_younger_one_changes_nothing(wide: None) -> None:
    asker = lone_asker()
    gate = threading.Event()
    seen: list[str] = []

    def find(word: str) -> list[Entry]:
        seen.append(word)
        if word == "slow":
            gate.wait(WAIT_SECONDS)
            return named("From the old word")
        return named("From the young word")

    thread, returned = standing(lambda: asker.search(named("Tax"), find))
    until(asker.pending)
    asker.typed("slow")
    until(lambda: seen == ["slow"])
    asker.typed("fast")
    until_lines(asker, lambda lines: any("From the young word" in line for line in lines))
    gate.set()
    time.sleep(0.4)
    assert any("From the young word" in line for line in shown_lines(asker))
    assert not any("From the old word" in line for line in shown_lines(asker))
    asker.close()
    thread.join(WAIT_SECONDS)


def test_nothing_found_shows_the_sentence_for_it_and_enter_picks_nothing(wide: None) -> None:
    asker = lone_asker()
    thread, returned = standing(
        lambda: asker.search(named("Tax"), lambda word: [], empty="No matches")
    )
    until(asker.pending)
    asker.typed("zzz")
    until_lines(asker, lambda lines: "No matches" in lines)
    press(asker, Keys.Enter, typed="zzz")
    assert asker.pending()
    asker.close()
    thread.join(WAIT_SECONDS)
    assert returned == [None]


def test_enter_before_the_pause_is_over_searches_for_the_word_at_once(wide: None) -> None:
    asker = lone_asker()
    thread, returned = standing(
        lambda: asker.search(named("Tax", "Website texts"), lambda word: named("Website texts"))
    )
    until(asker.pending)
    asker.typed("web")
    press(asker, Keys.Enter, typed="web")
    thread.join(WAIT_SECONDS)
    assert returned and returned[0].value == "Website texts"


def test_escape_closes_the_selection_and_takes_what_was_typed_with_it(wide: None) -> None:
    asker = lone_asker()
    thread, returned = standing(lambda: asker.search(named("Tax"), lambda word: named("Tax")))
    until(asker.pending)
    asker.typed("ta")
    field = press(asker, Keys.Escape, typed="ta")
    thread.join(WAIT_SECONDS)
    assert returned == [None]
    assert field.text == ""
