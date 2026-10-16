"""``exe -p``: one message from a script. Only the answer's text stands on
the standard output; what the program says itself stands on the error
output; the exit code says how it went. The service is the stand-in."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from cli import chat, main as main_module
from cli.main import help_text, main
from cli.texts import Texts
from tests.cli import stub_service as service
from tests.cli.stub_service import StubService


class Terminal(io.StringIO):
    """A standard input that is a terminal."""

    def isatty(self) -> bool:
        return True


def texts() -> Texts:
    return Texts("en")


@pytest.fixture
def run(
    stub: StubService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Any:
    """Runs the program with the stand-in service and a standard input that
    is empty and not a terminal, as under a script."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    def go(*words: str, piped: str | None = None) -> int:
        if piped is not None:
            monkeypatch.setattr(sys, "stdin", io.StringIO(piped))
        return main([*words, "--lang", "en"], http=stub.http(), prefs_path=tmp_path / "cli.json")

    return go


def test_the_answer_and_nothing_else_stands_on_the_output(run, stub, capsys):
    stub.script = [
        service.reasoning("Let me think."),
        service.content("It is "),
        service.content("noon.\n"),
        service.stats(dauer_sekunden=1.0),
        service.context(1234),
        service.done(),
    ]
    code = run("-p", "What time is it?")
    shown = capsys.readouterr()
    assert code == 0
    assert shown.out == "It is noon.\n"
    assert shown.err == ""


def test_an_answer_without_a_final_line_break_gets_one(run, stub, capsys):
    stub.script = [service.content("Noon."), service.done()]
    assert run("-p", "Time?") == 0
    assert capsys.readouterr().out == "Noon.\n"


def test_one_message_goes_to_a_new_chat_named_after_the_question(run, stub):
    run("-p", "What time is it?")
    assert len(stub.sent) == 1
    assert stub.sent[0]["content"] == "What time is it?"
    assert stub.sent[0].get("endpoint_id") == "local"
    assert list(stub.chats.values())[0]["title"] == "What time is it?"


def test_piped_text_goes_in_front_and_the_question_on_a_line_of_its_own(run, stub):
    run("-p", "explain this error", piped="FileNotFoundError: config.yaml\nline two\n")
    assert stub.sent[0]["content"] == (
        "FileNotFoundError: config.yaml\nline two\nexplain this error"
    )
    # The name of the chat is the first line of the message.
    assert list(stub.chats.values())[0]["title"] == "FileNotFoundError: config.yaml"


def test_without_a_pipe_only_the_question_goes_out(run, stub, monkeypatch):
    monkeypatch.setattr(sys, "stdin", Terminal(""))
    assert main(["-p", "Just this", "--lang", "en"], http=stub.http()) == 0
    assert stub.sent[0]["content"] == "Just this"


def test_a_tool_that_asks_is_allowed_this_once_and_never_for_good(run, stub, capsys):
    stub.script = [
        service.content("Before.\n"),
        service.tool_confirm("write_file", {"path": "a.txt"}, "call-1", reason="Writes a file"),
        service.tool_call("write_file", {"path": "a.txt"}, "call-1", server="files"),
        service.tool_result("write_file", "call-1", "Wrote 5 characters to a.txt"),
        service.content("After.\n"),
        service.done(),
    ]
    assert run("-p", "Write it") == 0
    assert len(stub.confirmations) == 1
    assert stub.confirmations[0]["erlaubt"] is True
    assert stub.confirmations[0]["dauerhaft"] is False
    shown = capsys.readouterr()
    # No tool line and no figure stands in what a script reads.
    assert shown.out == "Before.\nAfter.\n"
    assert "write_file" not in shown.out + shown.err


def test_a_question_of_the_model_gets_the_empty_answer_and_the_model_goes_on(run, stub, capsys):
    stub.script = [
        {"typ": "user_ask", "frage": "Which one?", "optionen": [], "aufruf_id": "ask-1"},
        service.content("Went on.\n"),
        service.done(),
    ]
    assert run("-p", "Pick") == 0
    assert stub.confirmations[0]["antwort"] == ""
    assert capsys.readouterr().out == "Went on.\n"


def test_an_error_of_the_stream_ends_with_one_and_says_it_on_the_error_output(run, stub, capsys):
    stub.script = [service.content("Partial"), {"typ": "error", "text": "The model failed."}, service.done()]
    code = run("-p", "Go")
    shown = capsys.readouterr()
    assert code == 1
    assert shown.out == "Partial\n"
    assert "The model failed." in shown.err


def test_without_a_question_and_without_a_pipe_the_line_of_the_switch_stands_there(
    run, stub, monkeypatch, capsys
):
    monkeypatch.setattr(sys, "stdin", Terminal(""))
    code = main(["-p", "", "--lang", "en"], http=stub.http())
    shown = capsys.readouterr()
    assert code == 2
    assert shown.out == ""
    assert "-p" in shown.err and "Send one message" in shown.err
    assert stub.sent == []


def test_the_switch_without_its_value_says_what_it_takes(run, stub, capsys):
    code = run("-p")
    assert code == 2
    assert "Send one message" in capsys.readouterr().err
    assert stub.sent == []


def test_help_names_the_switch_with_its_sentence():
    assert "Send one message, print the response and exit" in help_text(texts())
    assert '-p "explain this error"' in help_text(texts())


def test_the_interrupt_key_stops_the_answer_and_ends_with_one(run, stub, monkeypatch, capsys):
    def interrupted(ctx: Any, text: str, **_: Any) -> None:
        chat.service_chat(ctx)
        raise KeyboardInterrupt

    monkeypatch.setattr(chat, "send", interrupted)
    code = run("-p", "Go")
    assert code == 1
    assert stub.stops == [{"chat_id": "chat-1"}]
    assert capsys.readouterr().out == ""


def test_a_service_that_does_not_answer_is_said_on_the_error_output(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no service", request=request)

    http = httpx.Client(transport=httpx.MockTransport(refuse))
    code = main(["-p", "Hello", "--url", "http://203.0.113.9:8090", "--lang", "en"], http=http,
                prefs_path=tmp_path / "cli.json")
    shown = capsys.readouterr()
    assert code == 1
    assert shown.out == ""
    assert shown.err.strip()


def test_the_parser_still_refuses_an_unknown_switch(run, capsys):
    assert run("--answer", "x") == 2
    assert main_module.PROGRAM in capsys.readouterr().err
