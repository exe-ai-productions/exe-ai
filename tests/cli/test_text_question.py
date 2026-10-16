"""A line of text a command asks for — the words of a search, the token: the
question stands above the input field, the answer is what is typed, a hidden
one is not shown, and none of it goes into the history."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from prompt_toolkit.buffer import Buffer

from cli.dialogs import TerminalAsker
from cli.interfaces import Context
from cli.texts import Texts
from tests.cli.conftest import RecordingScreen
from tests.cli.stub_service import eventually


@pytest.fixture
def asker() -> TerminalAsker:
    context = Context(client=None, texts=Texts("en"))  # type: ignore[arg-type]
    context.screen = RecordingScreen(context)
    return TerminalAsker(context)


def ask(
    asker: TerminalAsker, head: str, *, secret: bool = False, default: str | None = None
) -> tuple[threading.Thread, list]:
    answers: list = []
    thread = threading.Thread(
        target=lambda: answers.append(asker.ask_text(head, secret=secret, default=default)),
        daemon=True,
    )
    thread.start()
    eventually(asker.pending)
    return thread, answers


def key(buffer: Buffer) -> SimpleNamespace:
    return SimpleNamespace(current_buffer=buffer)


def printed(asker: TerminalAsker) -> list:
    return asker._ctx.screen.printed  # type: ignore[attr-defined]


def test_what_is_typed_is_the_answer_and_the_question_stands_while_it_waits(asker):
    thread, answers = ask(asker, "Search for a model:")
    assert any("Search for a model:" in text for _, text in asker.fragments())
    buffer = Buffer()
    buffer.text = "  gemma 3  "
    asker._on_enter(key(buffer))
    thread.join(5)
    assert answers == ["gemma 3"]
    assert not asker.pending()
    # Nothing of it stands in the history.
    assert printed(asker) == []


def test_a_secret_question_is_hidden_while_it_is_open_and_not_after(asker):
    assert asker.secret() is False
    thread, answers = ask(asker, "Token", secret=True)
    assert asker.secret() is True
    buffer = Buffer()
    buffer.text = "hf_value"
    asker._on_enter(key(buffer))
    thread.join(5)
    assert answers == ["hf_value"]
    assert asker.secret() is False
    assert printed(asker) == []


def test_nothing_typed_closes_the_question_with_no_answer(asker):
    thread, answers = ask(asker, "Search for a model:")
    asker._on_enter(key(Buffer()))
    thread.join(5)
    assert answers == [None]
    assert not asker.pending()


def test_escape_closes_the_question_with_no_answer(asker):
    thread, answers = ask(asker, "Token", secret=True)
    asker._on_escape(key(Buffer()))
    thread.join(5)
    assert answers == [None]
    assert asker.secret() is False
    assert printed(asker) == []


def test_a_value_that_stands_is_shown_and_nothing_typed_takes_it(asker):
    thread, answers = ask(asker, "Preferred name", default="Kim")
    shown = [text for _, text in asker.fragments()]
    assert "Preferred name" in shown
    assert any(text.endswith("Kim") for text in shown)
    asker._on_enter(key(Buffer()))
    thread.join(5)
    assert answers == ["Kim"]
    assert printed(asker) == []


def test_a_value_that_stands_is_replaced_by_what_is_typed(asker):
    thread, answers = ask(asker, "Preferred name", default="Kim")
    buffer = Buffer()
    buffer.text = " Alex "
    asker._on_enter(key(buffer))
    thread.join(5)
    assert answers == ["Alex"]


def test_an_empty_value_that_stands_is_an_answer_of_its_own(asker):
    thread, answers = ask(asker, "Context size", default="")
    asker._on_enter(key(Buffer()))
    thread.join(5)
    assert answers == [""]


def test_escape_closes_a_question_that_has_a_value_with_no_answer(asker):
    thread, answers = ask(asker, "Context size", default="")
    asker._on_escape(key(Buffer()))
    thread.join(5)
    assert answers == [None]

