"""The history as the renderer writes it: an answer block by block, the
thinking beside the spinner and then in one line, a tool in the one line it
gets when it has come back, the numbers and marks of an answer below it."""

from __future__ import annotations

import io
import sys
from typing import Any

import httpx
import pytest
from rich.cells import cell_len
from rich.console import Console
from rich.markdown import Markdown

from cli import glyphs, prefs, render, themes, wordmark
from cli.client import ServiceClient
from cli.interfaces import Context, Screen
from cli.texts import Texts
from tests.cli.program import local_clock

WIDTH = 80
ESCAPE = "\x1b"

# What the head asks the service for: the chats, newest first, and the
# tools that run without asking.
CHATS = [
    {"id": "c-1", "title": "Say hello in one sentence", "updated_at": "2026-10-11T04:34:00+02:00"},
    {"id": "c-2", "title": "Image ideas for October", "updated_at": "2026-10-10T18:00:00+02:00"},
    {"id": "c-3", "title": "Project plan", "updated_at": "2026-10-09T09:00:00+02:00"},
    {"id": "c-4", "title": "An older one", "updated_at": "2026-10-01T09:00:00+02:00"},
]
ALWAYS = {"read_file": "ja", "write_file": "ja", "run_command": "ja"}


class HeadService:
    """Answers the two addresses the head asks; a test may empty either."""

    def __init__(self) -> None:
        self.chats: list[dict[str, Any]] = [dict(chat) for chat in CHATS]
        self.always: dict[str, str] = dict(ALWAYS)
        # While true, every question is refused.
        self.refuses = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.refuses:
            return httpx.Response(503, json={"detail": "Closed"})
        if request.url.path == "/api/v1/chats":
            return httpx.Response(200, json=self.chats)
        if request.url.path == "/api/v1/permissions/always-allow":
            return httpx.Response(200, json=self.always)
        return httpx.Response(404, json={"detail": "No such address"})


class Stage(Screen):
    """A screen that writes the history into a recording and keeps what
    the line beside the spinner was set to."""

    def __init__(self, width: int = WIDTH) -> None:
        self.console = Console(
            file=io.StringIO(),
            record=True,
            width=width,
            force_terminal=True,
            color_system="truecolor",
            no_color=False,
            legacy_windows=False,
            highlight=False,
        )
        self.console.push_theme(themes.current().rich_theme())
        self.printed: list[Any] = []
        self.activity: list[Any] = []

    def print_above(self, *renderables: Any) -> None:
        self.printed.extend(renderables)
        for renderable in renderables:
            self.console.print(renderable)

    def set_activity(self, text: Any) -> None:
        self.activity.append(text)

    def beside_the_spinner(self) -> str:
        """What stands beside the spinner right now."""
        latest = self.activity[-1]
        return latest() if callable(latest) else (latest or "")

    def lines(self) -> list[str]:
        """The history as text, line by line, without its colours."""
        return [line.rstrip() for line in self.console.export_text(clear=False).splitlines()]

    def sent(self) -> str:
        """The history as a terminal is sent it, colour codes included."""
        return self.console.export_text(styles=True, clear=False)


class Clock:
    """Stands in for the clock the durations are read from."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def a_plain_start(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    yield
    themes.set_look(themes.DEFAULT_LOOK)
    glyphs.use_nerd(False)


@pytest.fixture
def clock(monkeypatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(render, "_now", clock)
    return clock


@pytest.fixture
def stage() -> Stage:
    return Stage()


@pytest.fixture
def head_service() -> HeadService:
    return HeadService()


def build(
    stage: Stage, head_service: HeadService, tmp_path, language: str = "en"
) -> render.HistoryRenderer:
    client = ServiceClient(
        "http://service.test", language, http=httpx.Client(transport=httpx.MockTransport(head_service))
    )
    client.key = "key-of-this-run"
    ctx = Context(client=client, texts=Texts(language), prefs_path=tmp_path / "cli.json")
    ctx.session.models = [{"id": "local", "name": "Local Model", "context_tokens": 8192}]
    ctx.session.endpoint_id = "local"
    ctx.screen = stage
    built = render.build_renderer(ctx)
    assert isinstance(built, render.HistoryRenderer)
    return built


@pytest.fixture
def renderer(stage: Stage, head_service: HeadService, tmp_path) -> render.HistoryRenderer:
    return build(stage, head_service, tmp_path)


def sign(name: str) -> str:
    return glyphs.glyph(name)


WORDS = Texts("en")


# --- The answer's text --------------------------------------------------------


def test_a_paragraph_is_written_as_soon_as_the_next_one_begins(renderer, stage):
    renderer.start({})
    renderer.content("A first paragraph")
    renderer.content(" that goes on.\n")
    assert stage.lines() == []
    renderer.content("\nA second ")
    assert stage.lines() == [f"{sign('assistant')} A first paragraph that goes on."]
    renderer.content("one.")
    assert len(stage.lines()) == 1
    renderer.done({})
    assert stage.lines() == [
        f"{sign('assistant')} A first paragraph that goes on.",
        "",
        "  A second one.",
    ]


def test_a_code_block_is_written_only_after_its_closing_fence(renderer, stage):
    renderer.start({})
    renderer.content("```python\nprint(1)\n\nprint(2)\n")
    assert stage.lines() == []
    renderer.content("```\n")
    assert stage.lines() == [
        f"{sign('assistant')} {sign('gutter')} print(1)",
        f"  {sign('gutter')}",
        f"  {sign('gutter')} print(2)",
    ]


def test_each_block_is_markdown_and_only_the_one_an_answer_opens_with_carries_the_models_sign(
    renderer, stage
):
    renderer.start({})
    renderer.content("One.\n\nTwo.\n\n")
    blocks = [item for item in stage.printed if isinstance(item, Markdown)]
    assert [block.markup for block in blocks] == ["One.\n", "Two.\n"]
    assert [line[:1] for line in stage.lines() if line] == [sign("assistant"), " "]


def test_markdown_is_written_in_the_looks_signs(renderer, stage):
    renderer.start({})
    renderer.content("## Colours\n\n- red\n- green\n\n1. first\n2. second\n\n> quoted\n\n---\n\n")
    assert stage.lines() == [
        f"{sign('assistant')} Colours",
        "",
        f"   {sign('bullet')} red",
        f"   {sign('bullet')} green",
        "",
        "   1. first",
        "   2. second",
        "",
        f"  {sign('quote')} quoted",
        "",
        "  " + sign("rule") * (WIDTH - 2),
    ]


def test_the_numbers_of_a_long_list_stand_in_one_column(renderer, stage):
    renderer.start({})
    renderer.content("".join(f"{number}. item\n" for number in range(1, 10)) + "\n")
    assert stage.lines()[0] == f"{sign('assistant')}  1. item" and stage.lines()[8] == "   9. item"
    renderer.content("".join(f"{number}. item\n" for number in range(1, 11)) + "\n")
    assert stage.lines()[-10] == "    1. item" and stage.lines()[-1] == "   10. item"


def test_a_link_is_written_with_its_address(renderer, stage):
    renderer.start({})
    renderer.content("See [the page](https://example.org/page).\n\n")
    assert stage.lines() == [f"{sign('assistant')} See the page (https://example.org/page)."]


def test_an_empty_paragraph_writes_nothing(renderer, stage):
    renderer.start({})
    renderer.content("\n\n   \n\n")
    renderer.done({})
    assert stage.printed == [] and stage.lines() == []


def test_a_look_with_an_accent_draws_the_bar_beside_code_in_its_line_colour(head_service, tmp_path):
    themes.set_look("darkmatter")
    stage = Stage()
    renderer = build(stage, head_service, tmp_path)
    renderer.start({})
    renderer.content("```python\npass\n```\n")
    colour = themes.current().colours["line"]
    red, green, blue = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
    assert f"38;2;{red};{green};{blue}" in stage.sent()


def test_the_answer_is_written_in_the_looks_colours_and_no_ground_is_painted(renderer, stage):
    renderer.start({})
    renderer.content("Plain and `code`.\n\n```python\nfor x in y:\n    pass  # nothing\n```\n")
    sent = stage.sent()

    def code_for(colour_name: str) -> str:
        colour = themes.current().colours[colour_name]
        red, green, blue = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
        return f"38;2;{red};{green};{blue}"

    # The bar beside the code stands in the quiet tone in this look: its line
    # colour lies on the window's ground so close that no bar is seen.
    for colour_name in ("accent", "text", "call", "keyword", "comment", "muted"):
        assert code_for(colour_name) in sent, colour_name
    assert code_for("line") not in sent
    # A ground would be written as 48;…
    assert "48;" not in sent


def test_what_steers_a_terminal_is_not_written(renderer, stage):
    renderer.start({})
    renderer.content(f"Before{ESCAPE}[2J after\a.\n\n")
    renderer.tool_result({"name": "run_command", "text": f"line{ESCAPE}[31m one\r\n"})
    renderer.error(f"broken{ESCAPE}c")
    written = stage.console.export_text(clear=False)
    assert ESCAPE not in written and "\a" not in written and "\r" not in written
    assert "Before[2J after." in written


# --- Thinking -----------------------------------------------------------------


def test_thinking_stands_beside_the_spinner_cut_to_its_last_three_lines(renderer, stage, clock):
    renderer.start({})
    renderer.reasoning("First thought.\nSecond thought.\n")
    renderer.reasoning("Third thought.\nFourth ")
    clock.now += 65
    renderer.reasoning("thought.")
    # Nothing of it is in the history while it goes on.
    assert stage.lines() == []
    assert stage.beside_the_spinner().splitlines() == [
        WORDS.t("nachricht.gedankengang_laeuft", zeit="1:05"),
        "Second thought.",
        "Third thought.",
        "Fourth thought.",
    ]


def test_a_long_thought_is_broken_into_lines_and_its_end_is_what_shows(renderer, stage):
    renderer.start({})
    renderer.reasoning(" ".join(f"word{number}" for number in range(200)))
    rows = stage.beside_the_spinner().splitlines()[1:]
    assert len(rows) == render.THINKING_LINES
    assert rows[-1].endswith("word199")
    assert all(len(row) <= WIDTH for row in rows)


def test_thinking_ends_in_one_quiet_line_that_says_how_long_it_took(renderer, stage, clock):
    renderer.start({})
    renderer.reasoning("Let me look.")
    clock.now += 125
    renderer.content("The answer.\n\n")
    thought = f"{sign('thinking')} {WORDS.t('nachricht.gedankengang')} {sign('separator')} 2:05"
    assert stage.lines() == [thought, "", f"{sign('assistant')} The answer."]
    # The thinking itself is not in the history, and its line is the quiet tone.
    assert "Let me look." not in "\n".join(stage.lines())
    line = next(item for item in stage.printed if isinstance(item, render.OneLine))
    assert line.text.plain == thought and line.text.style == "exe.muted"
    styles = themes.current().styles()
    assert styles["thinking"] == styles["muted"] != styles["text"]


def test_once_thinking_is_over_the_line_beside_the_spinner_no_longer_says_it(renderer, stage):
    renderer.start({})
    renderer.reasoning("A thought.")
    renderer.error("The model went away")
    assert stage.beside_the_spinner() == WORDS.t("status.erzeugt_antwort")


def test_thinking_that_ends_with_the_answer_gets_its_line_too(renderer, stage):
    renderer.start({})
    renderer.reasoning("Only a thought.")
    renderer.done({})
    assert stage.lines() == [
        f"{sign('thinking')} {WORDS.t('nachricht.gedankengang')} {sign('separator')} 0:00"
    ]


def test_without_thinking_there_is_no_line_about_it(renderer, stage):
    renderer.start({})
    renderer.content("The answer.\n\n")
    renderer.done({})
    assert WORDS.t("nachricht.gedankengang") not in "\n".join(stage.lines())
    assert stage.activity == []


# --- Tools --------------------------------------------------------------------

CALL = {"name": "list_dir", "server": "files", "argumente": {"path": "./src", "deep": True}, "aufruf_id": "a1"}


def test_a_running_tool_stands_beside_the_spinner_with_what_it_was_called_with(
    renderer, stage, clock
):
    renderer.start({})
    renderer.tool_call(CALL)
    assert stage.lines() == []
    clock.now += 7
    assert stage.beside_the_spinner().splitlines() == [
        f"{WORDS.t('werkzeug.laeuft', name='list_dir')} 0:07",
        "./src",
    ]


def test_a_tool_gets_one_line_with_its_duration_and_how_it_went(renderer, stage):
    renderer.start({})
    renderer.tool_call(CALL)
    renderer.tool_result(
        {"name": "list_dir", "aufruf_id": "a1", "fehlgeschlagen": False, "text": "app\ncli", "dauer_sekunden": 65.2}
    )
    head, *below = stage.lines()
    assert head.startswith(
        f"{glyphs.tool_glyph('list_dir')} list_dir {sign('separator')} files  ./src"
    )
    assert head.endswith(f"1:05 {sign('ok')}") and len(head) == WIDTH
    assert below == ["    app", "    cli"]


def test_a_failed_tool_shows_its_duration_and_the_error_sign(renderer, stage):
    renderer.start({})
    renderer.tool_call(CALL)
    renderer.tool_result(
        {"name": "list_dir", "aufruf_id": "a1", "fehlgeschlagen": True, "text": "No such folder", "dauer_sekunden": 2.4}
    )
    head, below = stage.lines()
    assert "list_dir" in head and head.endswith(f"0:02 {sign('error')}")
    assert below == "    No such folder"
    red = themes.current().colours["red"]
    code = ";".join(str(int(red[i : i + 2], 16)) for i in (1, 3, 5))
    assert f"38;2;{code}m{sign('error')}" in stage.sent()


def test_a_long_argument_is_cut_and_the_duration_still_stands_at_the_edge(renderer, stage):
    renderer.start({})
    renderer.tool_call({"name": "web_search", "argumente": {"query": "word " * 60}, "aufruf_id": "a1"})
    renderer.tool_result({"name": "web_search", "aufruf_id": "a1", "dauer_sekunden": 3})
    (head,) = stage.lines()
    assert len(head) == WIDTH and head.endswith(f"{sign('more')} 0:03 {sign('ok')}")


def test_a_result_is_cut_to_its_first_three_lines_and_says_how_many_there_were(renderer, stage):
    renderer.start({})
    renderer.tool_call(CALL)
    renderer.tool_result(
        {"name": "list_dir", "aufruf_id": "a1", "text": "one\n\ntwo\nthree\nfour\nfive\n", "dauer_sekunden": 0}
    )
    assert stage.lines()[1:] == ["    one", "    two", "    three", f"    {sign('more')} 3/5"]


def test_a_long_line_of_a_result_is_cut_at_the_edge_and_not_wrapped(renderer, stage):
    renderer.start({})
    renderer.tool_call(CALL)
    renderer.tool_result({"name": "list_dir", "aufruf_id": "a1", "text": "word " * 60, "dauer_sekunden": 1})
    head, row = stage.lines()
    assert len(row) == WIDTH and row.startswith("    word word") and row.endswith(sign("more"))


def test_a_tool_without_a_result_text_has_nothing_below_its_line(renderer, stage):
    renderer.start({})
    renderer.tool_call(CALL)
    renderer.tool_result({"name": "list_dir", "aufruf_id": "a1", "text": "", "dauer_sekunden": 1})
    assert len(stage.lines()) == 1


def test_two_tools_at_once_each_get_their_line_when_they_come_back(renderer, stage):
    renderer.start({})
    renderer.tool_call({"name": "read_file", "argumente": {"path": "a.txt"}, "aufruf_id": "a1"})
    renderer.tool_call({"name": "read_file", "argumente": {"path": "b.txt"}, "aufruf_id": "a2"})
    renderer.tool_result({"name": "read_file", "aufruf_id": "a2", "dauer_sekunden": 1})
    renderer.tool_result({"name": "read_file", "aufruf_id": "a1", "dauer_sekunden": 2})
    first, second = stage.lines()
    assert "b.txt" in first and first.endswith(f"0:01 {sign('ok')}")
    assert "a.txt" in second and second.endswith(f"0:02 {sign('ok')}")


def test_two_calls_that_share_one_name_and_no_id_keep_their_own_arguments(renderer, stage):
    renderer.start({})
    renderer.tool_call({"name": "read_file", "argumente": {"path": "a.txt"}})
    renderer.tool_call({"name": "read_file", "argumente": {"path": "b.txt"}})
    renderer.tool_result({"name": "read_file", "dauer_sekunden": 1})
    renderer.tool_result({"name": "read_file", "dauer_sekunden": 2})
    first, second = stage.lines()
    assert "a.txt" in first and "b.txt" in second


def test_a_tool_that_never_came_back_gets_its_line_without_an_end(renderer, stage):
    renderer.start({})
    renderer.tool_call(CALL)
    renderer.done({"abgebrochen": True})
    head, stopped = stage.lines()
    assert head.startswith(f"{glyphs.tool_glyph('list_dir')} list_dir") and head.endswith(sign("waiting"))
    assert ":" not in head.split("./src")[1]
    assert stopped.strip() == WORDS.t("nachricht.abgebrochen_kurz")


def test_text_before_a_tool_is_written_before_its_line(renderer, stage):
    renderer.start({})
    renderer.content("I will look")
    renderer.tool_call(CALL)
    renderer.tool_result({"name": "list_dir", "aufruf_id": "a1", "dauer_sekunden": 1})
    renderer.content("Done.\n\n")
    lines = [line for line in stage.lines() if line]
    assert lines[0] == f"{sign('assistant')} I will look"
    assert "list_dir" in lines[1]
    # The text after the tool is a new stretch of the answer and is marked as one.
    assert lines[2] == f"{sign('assistant')} Done."


# --- Errors, numbers, marks ---------------------------------------------------


def test_an_error_stands_in_the_error_colour_below_what_had_arrived(renderer, stage):
    renderer.start({})
    renderer.reasoning("Thinking.")
    renderer.content("Half an answer")
    renderer.error("The model went away")
    lines = [line for line in stage.lines() if line]
    assert lines == [
        f"{sign('thinking')} {WORDS.t('nachricht.gedankengang')} {sign('separator')} 0:00",
        f"{sign('assistant')} Half an answer",
        f"{sign('error')} The model went away",
    ]
    red = themes.current().colours["red"]
    code = ";".join(str(int(red[i : i + 2], 16)) for i in (1, 3, 5))
    assert f"38;2;{code}mThe model went away" in stage.sent()


def test_a_shell_line_keeps_its_colours_loses_other_controls_and_stands_below_the_answer(renderer, stage):
    renderer.start({})
    renderer.content("Half an answer")
    renderer.shell_line("\x1b[31mred\x1b[0m plain\x1b[2K")
    lines = [line for line in stage.lines() if line]
    # Written below what of the answer had arrived, as a line of its own.
    assert lines == [f"{sign('assistant')} Half an answer", "red plain"]
    # The red the command asked for stays; the clearing sequence is gone.
    assert "31mred" in stage.sent() and "\x1b[2K" not in stage.sent()


def test_the_numbers_stand_quietly_below_the_answer(renderer, stage):
    renderer.start({})
    renderer.content("The answer.")
    renderer.stats(
        {"dauer_sekunden": 72.4, "tokens_pro_sekunde": 21.4, "tempo_quelle": "server", "gesamt_tokens": 1234}
    )
    renderer.done({})
    used = WORDS.t("kontext.auslastung", genutzt=1234, gesamt=8192)
    numbers = f"  1:12 {sign('separator')} 21 {WORDS.t('nachricht.tps')} {sign('separator')} {used}"
    assert stage.lines() == [f"{sign('assistant')} The answer.", "", numbers]
    muted = themes.current().colours["muted"]
    code = ";".join(str(int(muted[i : i + 2], 16)) for i in (1, 3, 5))
    assert f"38;2;{code}m1:12" in stage.sent()


def test_numbers_without_marks_name_none(renderer, stage):
    renderer.start({})
    renderer.stats({"dauer_sekunden": 3.0, "abgebrochen": False, "kontextfenster_voll": False})
    renderer.done({"abgebrochen": False})
    assert stage.lines() == ["  0:03"]
    assert len(stage.printed) == 1


@pytest.mark.parametrize("no_number", [float("nan"), float("inf"), "fast", None, True])
def test_numbers_that_are_none_are_left_out_and_break_nothing(renderer, stage, no_number):
    renderer.start({})
    renderer.tool_result({"name": "list_dir", "dauer_sekunden": no_number})
    renderer.stats(
        {
            "dauer_sekunden": no_number,
            "tokens_pro_sekunde": no_number,
            "tempo_quelle": "server",
            "gesamt_tokens": no_number,
        }
    )
    renderer.done({})
    (head,) = stage.lines()
    assert head.endswith(f" {sign('ok')}") and ":" not in head
    assert render.clock(float("nan")) == render.clock(float("inf")) == "0:00"


def test_a_speed_that_was_only_counted_is_not_shown(renderer, stage):
    renderer.start({})
    renderer.stats({"dauer_sekunden": 3.0, "tokens_pro_sekunde": 999.0, "tempo_quelle": "haeppchen"})
    assert stage.lines() == ["  0:03"]


def test_numbers_that_say_nothing_write_nothing(renderer, stage):
    renderer.start({})
    renderer.stats({})
    renderer.done({})
    assert stage.lines() == []


@pytest.mark.parametrize(
    ("marks", "sentences"),
    [
        ({"kontextfenster_voll": True}, ["nachricht.kontextfenster_voll"]),
        ({"anbietergrenze": True}, ["nachricht.anbietergrenze"]),
        ({"abgeschnitten": True}, ["nachricht.abgeschnitten"]),
        ({"antwortlaenge_zu_gross": True}, ["nachricht.antwortlaenge_zu_gross"]),
        (
            {"denken_aufgebraucht": "denken_aufgebraucht_eigene_grenze"},
            ["nachricht.denken_aufgebraucht_eigene_grenze"],
        ),
        # Of the ways an answer is cut short, one is named.
        ({"abgeschnitten": True, "kontextfenster_voll": True}, ["nachricht.kontextfenster_voll"]),
        # A failed compaction stands beside whichever of them it is.
        (
            {"anbietergrenze": True, "komprimieren_fehlgeschlagen": True},
            ["nachricht.anbietergrenze", "nachricht.komprimieren_fehlgeschlagen"],
        ),
    ],
)
def test_the_marks_of_an_answer_are_written_out(renderer, stage, marks, sentences):
    renderer.start({})
    renderer.stats({"dauer_sekunden": 3.0, **marks})
    lines = stage.lines()
    assert lines[0] == "  0:03"
    # One mark, one line that starts with the sign; a sentence longer than
    # the stage runs on into the lines below it, which are read back into it.
    marks_written: list[str] = []
    for line in lines[1:]:
        if line.startswith(sign("warning")):
            marks_written.append(line)
        else:
            marks_written[-1] += " " + line.strip()
    assert marks_written == [f"{sign('warning')} {WORDS.t(key)}" for key in sentences]


def test_a_stopped_answer_says_so_once(renderer, stage):
    stopped = WORDS.t("nachricht.abgebrochen_kurz")
    renderer.start({})
    renderer.stats({"dauer_sekunden": 3.0, "abgebrochen": True})
    renderer.done({"abgebrochen": True})
    assert stage.lines() == [f"  0:03 {sign('separator')} {stopped}"]


def test_a_stopped_answer_without_numbers_still_says_so(renderer, stage):
    renderer.start({})
    renderer.content("Cut")
    renderer.done({"abgebrochen": True})
    assert stage.lines() == [
        f"{sign('assistant')} Cut",
        "",
        f"  {WORDS.t('nachricht.abgebrochen_kurz')}",
    ]


# --- The client's own lines, and a chat that already has messages --------------


def standing() -> str:
    """The line below the mark that says where the client stands."""
    separator = sign("separator")
    return (
        f"{WORDS.t('cli.titel')} 9.8.7 {separator} http://service.test {separator} Local Model "
        f"{separator} {WORDS.t('cli.tools_always_allowed', n=3)}"
    )


def recent() -> list[str]:
    """The newest three chats with the number each one opens by."""
    return [
        WORDS.t("cli.recent_chats"),
        f"1  Say hello in one sentence  {local_clock(CHATS[0]['updated_at'])}",
        f"2  Image ideas for October    {local_clock(CHATS[1]['updated_at'])}",
        f"3  Project plan               {local_clock(CHATS[2]['updated_at'])}",
        "",
    ]


def tips(*, a_chat_by_number: bool = True) -> list[str]:
    """The tips under their heading, each on a line of its own — the one
    about opening a chat by its number among them or not."""
    keys = ("cli.tip_open", "cli.tip_new", "cli.tip_help")
    return [
        WORDS.t("cli.tips_title"),
        *(WORDS.t(key) for key in keys[0 if a_chat_by_number else 1 :]),
        "",
    ]


def letters() -> list[str]:
    """The block letters with their two columns of margin."""
    return [(" " * render.WORDMARK_MARGIN + line).rstrip() for line in wordmark.WORDMARK]


def colour_code(colour_name: str) -> str:
    colour = themes.current().colours[colour_name]
    return "38;2;" + ";".join(str(int(colour[i : i + 2], 16)) for i in (1, 3, 5))


def test_at_one_hundred_and_twenty_columns_the_head_is_the_letters_the_standing_line_the_chats_and_the_tips(
    head_service, tmp_path
):
    # Under a theme with an accent of its own: only there can the letters
    # be told from it.
    themes.set_look("darkmatter")
    assert colour_code("accent") != colour_code("text")
    stage = Stage(width=120)
    build(stage, head_service, tmp_path).header("9.8.7", "http://service.test")
    assert stage.lines() == ["", *letters(), "", standing(), "", *recent(), *tips()]
    # The letters stand in the text colour, not the accent; the standing
    # line is quiet.
    margin = " " * render.WORDMARK_MARGIN
    assert f"{colour_code('text')}m{margin}{wordmark.WORDMARK[0]}" in stage.sent()
    assert f"{colour_code('accent')}m{margin}{wordmark.WORDMARK[0]}" not in stage.sent()
    assert f"{colour_code('muted')}m{standing()}" in stage.sent()


def test_at_sixty_columns_the_letters_still_stand_and_below_that_the_name_takes_their_place(
    head_service, tmp_path
):
    stage = Stage(width=render.WORDMARK_FROM)
    build(stage, head_service, tmp_path).header("9.8.7", "http://service.test")
    assert stage.lines()[: len(letters()) + 2] == ["", *letters(), ""]
    # One column less: the name in one line, in bold, where the letters stood.
    stage = Stage(width=render.WORDMARK_FROM - 1)
    build(stage, head_service, tmp_path).header("9.8.7", "http://service.test")
    lines = stage.lines()
    assert lines[:3] == ["", wordmark.WORDMARK_PLAIN, ""]
    assert lines[3].startswith(f"{WORDS.t('cli.titel')} 9.8.7 {sign('separator')} http://service.test")
    assert f"\x1b[1;{colour_code('text')}m{wordmark.WORDMARK_PLAIN}" in stage.sent()
    assert not any(wordmark.WORDMARK[0].strip() in line for line in lines)
    # The chats and the tips stand below it as they do under the letters.
    assert lines[5:] == [*recent(), *tips()]


def test_a_tip_wider_than_the_window_ends_at_its_edge_and_the_head_keeps_three_tip_lines(
    head_service, tmp_path
):
    """The German tip about opening a chat is 73 cells wide; in sixty
    columns it is cut short with the mark for that, like the line with the
    version and the address above it — it does not run into a second line.
    Silence probe: in a hundred columns the three tips stand whole, and the
    English tip, which is 59 cells wide, stands whole in sixty."""
    words = Texts("de")
    stage = Stage(width=60)
    build(stage, head_service, tmp_path, "de").header("9.8.7", "http://service.test")
    lines = stage.lines()
    start = lines.index(words.t("cli.tips_title"))
    tips_shown = lines[start + 1 :]
    assert tips_shown[1:] == [words.t("cli.tip_new"), words.t("cli.tip_help"), ""]
    assert cell_len(tips_shown[0]) == 60 and tips_shown[0].endswith("…")
    assert words.t("cli.tip_open").startswith(tips_shown[0].removesuffix("…"))

    stage = Stage(width=100)
    build(stage, head_service, tmp_path, "de").header("9.8.7", "http://service.test")
    lines = stage.lines()
    start = lines.index(words.t("cli.tips_title"))
    assert lines[start + 1 :] == [words.t(key) for key in ("cli.tip_open", "cli.tip_new", "cli.tip_help")] + [""]

    stage = Stage(width=60)
    build(stage, head_service, tmp_path).header("9.8.7", "http://service.test")
    assert stage.lines()[-len(tips()) :] == tips()


def test_no_command_of_the_help_stands_in_the_head(stage, head_service, tmp_path):
    """The tips say where the commands are; the head lists none of them."""
    build(stage, head_service, tmp_path).header("9.8.7", "http://service.test")
    shown = "\n".join(stage.lines())
    for key in ("cli.cmd_chats", "cli.cmd_model", "cli.cmd_lang", "cli.cmd_clear", "cli.cmd_help"):
        assert WORDS.t(key) not in shown, key
    assert WORDS.t("cli.tip_help") in shown


def test_without_chats_the_head_lists_none_and_has_no_empty_heading(
    head_service, tmp_path
):
    stage = Stage(width=120)
    head_service.chats = []
    build(stage, head_service, tmp_path).header("9.8.7", "http://service.test")
    lines = stage.lines()
    assert WORDS.t("cli.recent_chats") not in lines
    # And no tip names a number the list above does not have.
    assert lines == ["", *letters(), "", standing(), "", *tips(a_chat_by_number=False)]


@pytest.mark.parametrize("language", ["en", "de"])
def test_the_tip_about_opening_a_chat_names_the_number_it_is_shown_for(language):
    """The sentence carries its number in the catalogue; the head shows it
    for exactly that number. One that changed alone would be seen here."""
    assert f"/chats {render.TIP_CHAT_NUMBER} " in Texts(language).t("cli.tip_open")
    assert render.TIP_CHAT_NUMBER <= render.RECENT_CHATS


@pytest.mark.parametrize(("listed", "tip_stands"), [(0, False), (1, False), (2, True), (3, True), (4, True)])
def test_the_tip_about_opening_a_chat_stands_only_where_the_list_has_its_number(
    head_service, tmp_path, listed, tip_stands
):
    """The tip names chat 2. With no chat or one chat in the list there is
    no chat 2 to open; the two other tips stand in every head."""
    stage = Stage(width=120)
    head_service.chats = [dict(chat) for chat in CHATS[:listed]]
    build(stage, head_service, tmp_path).header("9.8.7", "http://service.test")
    lines = stage.lines()
    assert (WORDS.t("cli.tip_open") in lines) is tip_stands
    assert WORDS.t("cli.tip_new") in lines and WORDS.t("cli.tip_help") in lines
    assert lines[-len(tips(a_chat_by_number=tip_stands)) :] == tips(a_chat_by_number=tip_stands)


def test_the_head_keeps_the_chats_it_numbered_for_whoever_takes_a_number(head_service, tmp_path):
    """The numbers the head shows are the ones a number typed later counts
    into — all of the list the head read, also beyond the ones it shows."""
    built = build(Stage(width=120), head_service, tmp_path)
    session = built._ctx.session
    assert session.shown_chats is None
    built.header("9.8.7", "http://service.test")
    assert [chat["id"] for chat in session.shown_chats] == [chat["id"] for chat in CHATS]
    assert len(CHATS) > render.RECENT_CHATS


def test_a_head_the_service_refused_its_chats_numbers_none(head_service, tmp_path):
    """Silence probe: nothing was shown with a number, so nothing is kept."""
    head_service.refuses = True
    built = build(Stage(width=120), head_service, tmp_path)
    built.header("9.8.7", "http://service.test")
    assert built._ctx.session.shown_chats is None


def test_a_service_that_refuses_the_heads_questions_still_gets_a_head(
    stage, head_service, tmp_path, monkeypatch
):
    head_service.refuses = True
    renderer = build(stage, head_service, tmp_path)
    renderer.header("9.8.7", "http://service.test")
    lines = stage.lines()
    separator = sign("separator")
    assert f"{WORDS.t('cli.titel')} 9.8.7 {separator} http://service.test {separator} Local Model" in lines
    assert WORDS.t("cli.recent_chats") not in lines


def test_the_users_lines_stand_beside_the_mark_they_were_typed_at(renderer, stage):
    renderer.header("9.8.7", "http://service.test")
    renderer.user_message("First line\nsecond line")
    head = 1 + len(wordmark.WORDMARK) + 1 + 1 + 1 + len(recent()) + len(tips())
    assert stage.lines()[head:] == [f"{sign('user')} First line", "  second line"]


def test_long_lines_of_the_user_and_of_an_error_wrap_below_their_text(renderer, stage):
    renderer.user_message("word " * 30)
    renderer.error("fail " * 30)
    question_first, question_second, _, error_first, error_second = stage.lines()
    assert question_first.startswith(f"{sign('user')} word") and question_second.startswith("  word")
    assert error_first.startswith(f"{sign('error')} fail") and error_second.startswith("  fail")


def test_text_gets_an_empty_line_around_it_and_lines_about_what_happened_stand_together(
    renderer, stage
):
    renderer.user_message("A question")
    renderer.start({})
    renderer.reasoning("Thinking.")
    renderer.tool_call(CALL)
    renderer.tool_result({"name": "list_dir", "aufruf_id": "a1", "dauer_sekunden": 1})
    renderer.content("An answer.\n\n")
    renderer.stats({"dauer_sekunden": 3.0})
    renderer.done({})
    renderer.user_message("Thanks")
    assert [bool(line) for line in stage.lines()] == [
        True,  # the question
        False,
        True,  # thinking
        True,  # the tool
        False,
        True,  # the answer
        False,
        True,  # the numbers
        False,
        True,  # the next question
    ]


def test_a_stored_message_is_written_with_its_thinking_its_tools_and_its_text(renderer, stage):
    renderer.stored_message({"role": "user", "content": "List the folders."})
    renderer.stored_message(
        {
            "role": "assistant",
            "content": "Here they are:\n\n- app\n- cli\n",
            "reasoning": "The user wants folders.",
            "stats": {
                "werkzeuge": [
                    {
                        "name": "list_dir",
                        "server": "files",
                        "argumente": {"path": "."},
                        "fehlgeschlagen": False,
                        "ergebnis": "app\ncli",
                        "dauer_sekunden": 0.4,
                    }
                ]
            },
        }
    )
    lines = [line for line in stage.lines() if line]
    assert lines[0] == f"{sign('user')} List the folders."
    assert lines[1] == f"{sign('thinking')} {WORDS.t('nachricht.gedankengang')}"
    assert lines[2].startswith(f"{glyphs.tool_glyph('list_dir')} list_dir {sign('separator')} files  .")
    assert lines[2].endswith(f"0:00 {sign('ok')}")
    assert lines[3:] == [
        "    app",
        "    cli",
        f"{sign('assistant')} Here they are:",
        f"   {sign('bullet')} app",
        f"   {sign('bullet')} cli",
    ]


# --- Signs --------------------------------------------------------------------


def test_the_remembered_choice_switches_the_nerd_font_signs_on_at_start(stage, tmp_path):
    file = tmp_path / "cli.json"
    ctx = Context(client=None, texts=Texts("en"), prefs_path=file)  # type: ignore[arg-type]
    ctx.screen = stage
    prefs.save({"nerd": True}, file)
    render.build_renderer(ctx)
    assert ord(glyphs.glyph("ok")) in range(0xE000, 0xF900)
    # Anything but a plain yes leaves them off.
    prefs.save({"nerd": "yes"}, file)
    render.build_renderer(ctx)
    assert glyphs.glyph("ok") == "✓"


def test_an_output_without_utf8_is_written_a_history_of_ascii_alone(renderer, stage, monkeypatch):
    class Ascii:
        encoding = "ascii"

    monkeypatch.setattr(sys, "stdout", Ascii())
    renderer.header("9.8.7", "http://service.test")
    renderer.user_message("A question")
    renderer.start({})
    renderer.reasoning("Thinking.")
    renderer.tool_call(CALL)
    renderer.tool_result({"name": "list_dir", "aufruf_id": "a1", "text": "1\n2\n3\n4", "dauer_sekunden": 1})
    renderer.content(
        "# Head\n\n- item\n\n1. first\n\n> quote\n\n```python\nprint(1)\n```\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n---\n\n![a picture](picture.png)\n\n"
    )
    renderer.stats({"dauer_sekunden": 3.0, "abgebrochen": True, "kontextfenster_voll": True})
    renderer.error("Broken")
    renderer.done({})
    written = stage.console.export_text(clear=False)
    assert written.isascii(), [character for character in written if not character.isascii()]
    assert wordmark.WORDMARK_PLAIN in written and "ok" in written
    # The standing line is longer than the window: cut short, without the
    # mark a wider output would end it with.
    assert "Tools allowed without" in written
