"""``/export``: the chat as a file — a Markdown transcript of its messages
where the name ends in ``.md``, else the history as it was shown, as an HTML
page — and the switch that used to record the history is gone. After a
switch of the look the page begins with the history as it was written
again: once, in the colours of the look in use."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from cli import commands, events, themes
from cli.interfaces import Context
from cli.main import main
from cli.texts import Texts
from test_stream import shown_text
from tests.cli import stub_service as service
from tests.cli.program import Gated
from tests.cli.stub_service import StubService, eventually

ENTER = "\r"
ADDRESS = "http://stub.test"

# If a run never leaves by itself, its input is closed after this many
# seconds: the test then fails on what it asserts instead of hanging.
SAFETY_NET_SECONDS = 30

# One step of a run: a line to type, or a condition to wait for first.
Step = str | Callable[[Context], Any]

# How a page written without a name is called: the moment, and a number
# where that moment already has a page.
SAVED_NAME = re.escape(commands.SAVED_PREFIX) + r"\d{8}_\d{6}(-\d+)?\.html"


@pytest.fixture(autouse=True)
def the_default_look() -> Iterator[None]:
    yield
    themes.set_look(themes.DEFAULT_LOOK)


def words(key: str, **placeholders: Any) -> str:
    return Texts("en").t(key, **placeholders)


def answered(stub: StubService) -> Callable[[Context], bool]:
    """Whether the one message went out and its answer is over, on both
    sides — only then is the next line typed, so it never runs beside the
    answer."""
    return lambda ctx: len(stub.sent) == 1 and stub.running() == 0 and not ctx.session.answering


def exists(path: Path) -> Callable[[Context], bool]:
    return lambda ctx: path.exists()


def hint(ctx: Context) -> str:
    """The line above the input field as it stands right now."""
    return ctx.screen.hint_line()  # type: ignore[attr-defined]


def said(path: Path) -> Callable[[Context], bool]:
    """Whether the line above the input field says the file was saved,
    with its path; a long path may wrap, the words stay."""
    return lambda ctx: words("cli.exported", path="").strip() in hint(ctx) and path.name in hint(ctx)


def saved(tmp_path: Path, count: int) -> Callable[[Context], bool]:
    """Whether ``count`` pages lie in the client's own folder for exports."""
    return lambda ctx: len(list((tmp_path / commands.SAVED_FOLDER).glob("*.html"))) == count


def play(
    http: httpx.Client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    steps: list[Step],
    *arguments: str,
) -> tuple[int, str]:
    """Starts the client against the stand-in and types ``steps`` into it,
    one after the other; a condition is waited for before the next line
    goes in. Returns the exit code and, read back from an export written
    once the client has left, the plain text of everything shown."""
    parts: list[Context] = []
    build = events.build_events

    def remember(ctx: Context) -> Any:
        parts.append(ctx)
        return build(ctx)

    monkeypatch.setattr(events, "build_events", remember)
    with create_pipe_input() as pipe:

        def driver() -> None:
            ctx = eventually(lambda: parts and parts[0])
            for step in steps:
                if callable(step):
                    eventually(lambda: step(ctx))
                else:
                    pipe.send_text(step + ENTER)

        safety_net = threading.Timer(SAFETY_NET_SECONDS, pipe.close)
        safety_net.start()
        threading.Thread(target=driver, daemon=True).start()
        try:
            with create_app_session(input=pipe, output=DummyOutput()):
                code = main(
                    ["--url", ADDRESS, "--lang", "en", *arguments],
                    http=http,
                    prefs_path=tmp_path / "cli.json",
                )
        finally:
            safety_net.cancel()
    target = tmp_path / "afterwards.html"
    parts[0].screen.export(target)
    return code, shown_text(target.read_text(encoding="utf-8"))


def test_export_md_writes_the_messages_as_a_markdown_transcript(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub.script = [service.content("Hello **you**.\n"), service.done()]
    notes = tmp_path / "out" / "notes.md"
    code, shown = play(
        stub_http,
        tmp_path,
        monkeypatch,
        ["Hi there", answered(stub), f"/export {notes}", exists(notes), said(notes), "/quit"],
    )
    assert code == 0
    # The chat as the service stores it: its title, then every message
    # under who wrote it, in the words that were sent and answered.
    assert notes.read_text(encoding="utf-8") == (
        "# Hi there\n\n## User\n\nHi there\n\n## Assistant\n\nHello **you**.\n"
    )
    # Said above the input field, never in the history.
    assert words("cli.exported", path="").strip() not in shown


def test_export_md_of_a_new_chat_nobody_wrote_into_is_headed_by_the_name_it_goes_by(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    notes = tmp_path / "notes.md"
    code, _ = play(stub_http, tmp_path, monkeypatch, [f"/export {notes}", exists(notes), "/quit"])
    assert code == 0
    assert notes.read_text(encoding="utf-8") == f"# {words('chat.unbenannt')}\n"
    # Writing the file wrote nothing into the chat: the service has none.
    assert not stub.chats


def test_export_with_any_other_ending_writes_the_history_as_it_was_shown(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = tmp_path / "shown.html"
    code, shown = play(
        stub_http,
        tmp_path,
        monkeypatch,
        ["Hi there", answered(stub), f"/export {page}", exists(page), said(page), "/quit"],
    )
    assert code == 0
    html = page.read_text(encoding="utf-8")
    assert html.lstrip().startswith("<!DOCTYPE html>")
    # What was shown: the line that was typed, the answer, the status line
    # as it stood — and the look's ground behind it all.
    text = shown_text(html)
    assert "Hi there" in text and "Hello." in text
    assert words("cli.connected") in text
    assert themes.current().colours["ground"] in html
    # The export itself is in no page: it is said above the input field,
    # never in the history.
    assert words("cli.exported", path="").strip() not in text
    assert words("cli.exported", path="").strip() not in shown


# A first message longer than a chat's title: the status line, which names
# the chat by its title, never carries the whole of it.
# Longer than a chat's name can be, so that the name in the page's head is a
# cut of it and the question stands once in the history.
ASKED = "What grows in the shade of a north wall in March and in April"
ANSWERED = "Hello."


def switched_to(look: str) -> Callable[[Context], bool]:
    return lambda ctx: themes.current().name == look


def colours_of_the_default_look_only() -> set[str]:
    """The colours a page in Pearl has no use for."""
    former = {colour.lower() for colour in themes.get(themes.DEFAULT_LOOK).colours.values()}
    return former - {colour.lower() for colour in themes.get("pearl").colours.values()}


def assert_the_exchange_stands_once_in_pearl(page: Path) -> None:
    html = page.read_text(encoding="utf-8")
    text = shown_text(html)
    assert text.count(ASKED) == 1 and text.count(ANSWERED) == 1
    assert themes.get("pearl").colours["ground"].lower() in html.lower()
    left_over = sorted(colour for colour in colours_of_the_default_look_only() if colour in html.lower())
    assert left_over == []


def test_after_a_switch_of_the_theme_the_page_shows_the_history_once_in_the_theme_in_use(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert colours_of_the_default_look_only()
    page = tmp_path / "shown.html"
    code, _ = play(
        stub_http,
        tmp_path,
        monkeypatch,
        [
            ASKED,
            answered(stub),
            "/theme pearl",
            switched_to("pearl"),
            f"/export {page}",
            exists(page),
            said(page),
            "/quit",
        ],
    )
    assert code == 0
    assert_the_exchange_stands_once_in_pearl(page)


def test_a_switch_beside_a_running_answer_leaves_the_page_with_the_history_once_too(
    gated: Gated, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the answer wrote while it ran, in whichever look, went with the
    window when the history was written again behind it."""
    page = tmp_path / "shown.html"

    def histories_read() -> int:
        return sum(1 for asked in gated.requests if asked.endswith("/messages"))

    def let_the_answer_end(ctx: Context) -> bool:
        gated.gate.set()
        return True

    with gated.http() as http:
        code, _ = play(
            http,
            tmp_path,
            monkeypatch,
            [
                ASKED,
                lambda ctx: ctx.session.answering and gated.running() == 1,
                "/theme pearl",
                switched_to("pearl"),
                let_the_answer_end,
                lambda ctx: histories_read() == 1 and not ctx.session.answering,
                f"/export {page}",
                exists(page),
                said(page),
                "/quit",
            ],
        )
    assert code == 0
    assert_the_exchange_stands_once_in_pearl(page)


def test_export_txt_is_a_page_too_only_md_is_markdown(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = tmp_path / "shown.txt"
    code, _ = play(stub_http, tmp_path, monkeypatch, [f"/export {plain}", exists(plain), "/quit"])
    assert code == 0
    assert plain.read_text(encoding="utf-8").lstrip().startswith("<!DOCTYPE html>")


def test_without_a_name_a_page_is_written_into_the_clients_own_folder_named_by_the_moment(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / commands.SAVED_FOLDER
    code, shown = play(
        stub_http,
        tmp_path,
        monkeypatch,
        ["Hi there", answered(stub), "/export", saved(tmp_path, 1), "/export", saved(tmp_path, 2), "/quit"],
    )
    assert code == 0
    # Two exports are two files: the second never writes over the first.
    pages = sorted(folder.iterdir())
    assert all(re.fullmatch(SAVED_NAME, page.name) for page in pages), pages
    assert len({page.name for page in pages}) == 2
    for page in pages:
        html = page.read_text(encoding="utf-8")
        assert html.lstrip().startswith("<!DOCTYPE html>")
        assert "Hi there" in shown_text(html)
    # Said above the input field with the path, never in the history.
    assert words("cli.exported", path="").strip() not in shown
    assert sorted(entry.name for entry in tmp_path.iterdir()) == [
        "afterwards.html",
        "cli.json",
        commands.SAVED_FOLDER,
    ]


def test_without_export_no_file_is_written(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, _ = play(stub_http, tmp_path, monkeypatch, ["Hi there", answered(stub), "/quit"])
    assert code == 0
    # The address and the language are remembered, and the export the test
    # itself wrote afterwards; nothing else.
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["afterwards.html", "cli.json"]


def test_an_export_that_cannot_be_written_is_said_and_the_client_goes_on(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    in_the_way = tmp_path / "a-file"
    in_the_way.write_text("x", encoding="utf-8")
    code, shown = play(
        stub_http, tmp_path, monkeypatch, [f"/export {in_the_way / 'shown.html'}", "/quit"]
    )
    assert code == 0
    assert "a-file" in shown
    assert words("cli.exported", path="").strip() not in shown


def test_the_record_switch_is_no_longer_taken(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--url", ADDRESS, "--lang", "en", "--record"]) == 2
    assert capsys.readouterr().err == (
        "Unknown option: --record. Use exe --help to list available options.\n"
    )
