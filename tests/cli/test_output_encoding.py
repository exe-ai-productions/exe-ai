"""An output that cannot encode a character replaces it: no character of a
chat, a sentence or a name ends the client. An output that can encode
everything writes everything as it is."""

from __future__ import annotations

import io
import sys
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from prompt_toolkit.data_structures import Size
from prompt_toolkit.output import Output
from prompt_toolkit.output.vt100 import Vt100_Output

from cli.main import help_text, main
from cli.texts import Texts
from tests.cli.program import ENTER, Run, run_client
from tests.cli.stub_service import StubService, eventually

# What a chat may hold that a narrow console cannot write: letters beyond
# ASCII, and a sign beyond the letters.
SAID = "Schöne Grüße 🌱"
# The same line as an output in ASCII writes it: one mark per character it
# has no byte for.
SAID_IN_ASCII = "Sch?ne Gr??e ?"


def narrow_output(monkeypatch: pytest.MonkeyPatch, encoding: str) -> io.BytesIO:
    """Puts an output in place of the program's own that encodes the way a
    console of that encoding does — and fails on what it cannot encode,
    the way a console is set up by default."""
    raw = io.BytesIO()
    monkeypatch.setattr(
        sys, "stdout", io.TextIOWrapper(raw, encoding=encoding, errors="strict", write_through=True)
    )
    return raw


def narrow_terminal(
    monkeypatch: pytest.MonkeyPatch, encoding: str
) -> tuple[io.BytesIO, Output]:
    """The same output, and the screen's terminal on it: what the full
    screen draws is encoded the way that console encodes, a character it has
    no byte for standing as a mark."""
    raw = narrow_output(monkeypatch, encoding)
    return raw, Vt100_Output(sys.stdout, lambda: Size(rows=30, columns=100), term="xterm-256color")


def chat_with(stub: StubService, text: str) -> str:
    """A chat on the stand-in that holds one message, and its id."""
    chat_id = "chat-1"
    stub.chats[chat_id] = {"id": chat_id, "title": "Greetings", "endpoint_id": "local"}
    stub.messages[chat_id] = [
        {
            "id": "stored-1",
            "chat_id": chat_id,
            "role": "user",
            "content": text,
            "reasoning": None,
            "stats": {},
            "created_at": "2000-01-01T00:00:00",
        }
    ]
    return chat_id


def leave_at_once(stub: StubService) -> Callable[[Run, Callable[[str], None]], None]:
    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        run.parts()
        eventually(lambda: stub.watchers == 1)
        type_in(f"/quit{ENTER}")

    return drive


def test_a_chat_the_console_cannot_encode_is_shown_with_marks_and_ends_with_zero(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat_id = chat_with(stub, SAID)
    written, output = narrow_terminal(monkeypatch, "ascii")

    run = run_client(stub_http, tmp_path, monkeypatch, leave_at_once(stub), "--chat", chat_id, output=output)

    assert run.code == 0
    shown = written.getvalue().decode("ascii")
    assert SAID_IN_ASCII in shown


def test_a_console_of_the_western_code_page_keeps_its_letters_and_marks_the_rest(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat_id = chat_with(stub, SAID)
    written, output = narrow_terminal(monkeypatch, "cp1252")

    run = run_client(stub_http, tmp_path, monkeypatch, leave_at_once(stub), "--chat", chat_id, output=output)

    assert run.code == 0
    assert "Schöne Grüße ?" in written.getvalue().decode("cp1252")


def test_an_output_in_utf_8_writes_every_character_as_it_is(
    stub: StubService, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat_id = chat_with(stub, SAID)
    written, output = narrow_terminal(monkeypatch, "utf-8")

    run = run_client(stub_http, tmp_path, monkeypatch, leave_at_once(stub), "--chat", chat_id, output=output)

    assert run.code == 0
    assert SAID in written.getvalue().decode("utf-8")


def test_a_sentence_of_the_program_itself_is_written_with_marks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    written = narrow_output(monkeypatch, "ascii")
    beyond_ascii = [line for line in help_text(Texts("de")).splitlines() if not line.isascii()]
    assert beyond_ascii, "the help is to hold a letter beyond ASCII"

    assert main(["--help", "--lang", "de"], prefs_path=tmp_path / "cli.json") == 0

    shown = written.getvalue().decode("ascii")
    for line in beyond_ascii:
        assert line.encode("ascii", "replace").decode("ascii") in shown


def test_an_output_put_in_place_of_the_programs_own_is_left_as_it_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No console and no file: an output a caller put there, which has no
    # way of being told how to encode.
    written = io.StringIO()
    monkeypatch.setattr(sys, "stdout", written)

    assert main(["--help", "--lang", "de"], prefs_path=tmp_path / "cli.json") == 0

    assert written.getvalue() == help_text(Texts("de")) + "\n"
