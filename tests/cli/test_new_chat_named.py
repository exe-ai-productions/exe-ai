"""A chat made with ``/new`` is named after its first message — also one
made while an answer was still running, which is opened behind that answer.
It comes into being on the service with that message, not before. A chat
that was opened, not made, keeps the name it has."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from cli import chat
from cli.interfaces import Asker, Context
from tests.cli.program import ENTER, Gated, Run, run_client
from tests.cli.stub_service import StubService, eventually
from tests.fensterquelle import WINDOW_SOURCE

TOOLS_ASKED = "GET /api/v1/tools"
PLACEHOLDER = "New chat"

WINDOW = WINDOW_SOURCE
WINDOW_RULE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "chatName.js"
STUDIO = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "studiozeichnen.svelte.js"

# One message and the name it gives a new chat — the same table runs through
# the terminal client and through the window's own function, so a message
# gets the same name in both.
SIXTY_TWO = "Which seeds will still bloom well in a north facing garden bed"
FORTY_EIGHT = "Which seeds will still bloom well in a north bed"
NAME_CASES: list[tuple[str, str]] = [
    ("What grows in the shade", "What grows in the shade"),
    # Longer than the limit, the limit inside a word: ends at the word before.
    (SIXTY_TWO, "Which seeds will still bloom well in a north…"),
    # Exactly the limit: whole, no mark.
    (FORTY_EIGHT, FORTY_EIGHT),
    # A blank right behind the limit: the limit is itself a word end.
    (FORTY_EIGHT + " and more", FORTY_EIGHT + "…"),
    # A one-letter word and a short tail across the limit.
    ("Which seeds will still bloom well in a north b ed", "Which seeds will still bloom well in a north b…"),
    # No word end inside the limit: cut at the limit.
    ("a" * 60, "a" * 48 + "…"),
    ("a" * 60 + " b", "a" * 48 + "…"),
    # A picture character counts once, in the window as in the client.
    ("\U0001f600" * 60, "\U0001f600" * 48 + "…"),
    # Only the first line counts, its white space drawn to single blanks.
    ("First line\nsecond line", "First line"),
    ("First line\r\nsecond line", "First line"),
    ("\n\n  Hello \t world  \n second", "Hello world"),
    ("   \n  ", ""),
]


class Unasked(Asker):
    """No question is asked in these tests."""


@pytest.fixture
def ctx(ctx: Context) -> Context:
    ctx.asker = Unasked()
    return ctx


def _beside_the_answer(stub: StubService, type_in: Callable[[str], None], line: str) -> None:
    """Types a command while an answer runs and waits until it is through:
    the status lines ask the service anew once a line has been handled."""
    asked = stub.requests.count(TOOLS_ASKED)
    type_in(line + ENTER)
    eventually(lambda: stub.requests.count(TOOLS_ASKED) > asked)


def test_a_chat_made_while_an_answer_runs_is_named_after_its_first_message(
    gated: Gated, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: gated.watchers == 1)
        type_in("What grows in the shade" + ENTER)
        eventually(lambda: ctx.session.answering and gated.running() == 1)
        _beside_the_answer(gated, type_in, "/new")
        # Nothing has been written into the new chat: the service has none.
        assert list(gated.chats) == ["chat-1"]
        # Typed while the first answer still runs: it waits its turn, behind
        # the switch to the new chat.
        type_in("Which seeds for a north wall" + ENTER)
        gated.gate.set()
        eventually(lambda: len(gated.sent) == 2 and gated.running() == 0)
        eventually(lambda: not ctx.session.answering)
        type_in("/quit" + ENTER)

    with gated.http() as http:
        run = run_client(http, tmp_path, monkeypatch, drive)
    assert run.code == 0
    assert [sent["chat_id"] for sent in gated.sent] == ["chat-1", "chat-2"]
    assert gated.chats["chat-2"]["title"] == "Which seeds for a north wall"
    # The chat the answer ran in kept the name of its own first message.
    assert gated.chats["chat-1"]["title"] == "What grows in the shade"
    # The status line names the open chat as the service now does.
    status = "".join(text for _, text in run.parts().status.fragments(200))
    assert "Which seeds for a north wall" in status


def test_of_two_chats_made_while_an_answer_runs_each_is_named_after_its_own_first_message(
    gated: Gated, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: gated.watchers == 1)
        type_in("What grows in the shade" + ENTER)
        eventually(lambda: ctx.session.answering and gated.running() == 1)
        _beside_the_answer(gated, type_in, "/new")
        type_in("Which seeds for a north wall" + ENTER)
        _beside_the_answer(gated, type_in, "/new")
        type_in("How deep do bulbs go" + ENTER)
        gated.gate.set()
        eventually(lambda: len(gated.sent) == 3 and gated.running() == 0)
        eventually(lambda: not ctx.session.answering)
        type_in("/quit" + ENTER)

    with gated.http() as http:
        run = run_client(http, tmp_path, monkeypatch, drive)
    assert run.code == 0
    assert {name: held["title"] for name, held in gated.chats.items()} == {
        "chat-1": "What grows in the shade",
        "chat-2": "Which seeds for a north wall",
        "chat-3": "How deep do bulbs go",
    }


def test_starts_and_new_chats_without_a_message_leave_the_services_list_as_long_as_it_was(
    stub: StubService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Four times started, a new chat asked for each time, and left again
    without a word: the service lists what it listed before."""
    stub.chats["c-old"] = {"id": "c-old", "title": "Garden plans", "endpoint_id": "local"}
    stub.messages["c-old"] = []

    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        run.parts()
        eventually(lambda: stub.watchers == 1)
        type_in("/new" + ENTER)
        type_in("/quit" + ENTER)

    for _ in range(4):
        with stub.http() as http:
            assert run_client(http, tmp_path, monkeypatch, drive).code == 0
    assert list(stub.chats) == ["c-old"]
    assert "POST /api/v1/chats" not in stub.requests


def test_a_chat_made_with_no_answer_running_is_named_after_its_first_message(
    stub: StubService, ctx: Context
) -> None:
    """The way that always worked stays the way it was."""
    chat.new_chat(ctx)
    assert ctx.session.unnamed and not stub.chats
    chat.send(ctx, "What grows in the shade")
    assert stub.chats["chat-1"]["title"] == "What grows in the shade"
    assert not ctx.session.unnamed


def test_a_chat_that_was_opened_keeps_its_name_after_a_message(
    stub: StubService, ctx: Context
) -> None:
    held = ctx.client.post("/chats", json={"title": "Garden plans"})
    chat.open_chat(ctx, held)
    assert not ctx.session.unnamed
    chat.send(ctx, "What grows in the shade")
    assert stub.chats[held["id"]]["title"] == "Garden plans"


def test_a_chat_that_was_opened_while_an_answer_runs_keeps_its_name(
    gated: Gated, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        ctx = run.parts()
        eventually(lambda: gated.watchers == 1)
        held = ctx.client.post("/chats", json={"title": "Garden plans"})
        type_in("What grows in the shade" + ENTER)
        eventually(lambda: ctx.session.answering and gated.running() == 1)
        _beside_the_answer(gated, type_in, f"/chats {held['id']}")
        type_in("Which seeds for a north wall" + ENTER)
        gated.gate.set()
        eventually(lambda: len(gated.sent) == 2 and gated.running() == 0)
        eventually(lambda: not ctx.session.answering)
        type_in("/quit" + ENTER)

    with gated.http() as http:
        run = run_client(http, tmp_path, monkeypatch, drive)
    assert run.code == 0
    opened = next(name for name, held in gated.chats.items() if held["title"] == "Garden plans")
    assert gated.sent[1]["chat_id"] == opened
    assert sorted(held["title"] for held in gated.chats.values()) == [
        "Garden plans",
        "What grows in the shade",
    ]


def test_a_chat_that_is_opened_is_never_taken_for_a_new_one(
    stub: StubService, ctx: Context
) -> None:
    """Also one that still carries the service's placeholder, and also
    right after a new chat nobody wrote into."""
    created = ctx.client.post("/chats", json={})
    assert created["title"] == PLACEHOLDER
    chat.new_chat(ctx)
    assert ctx.session.unnamed
    chat.open_chat(ctx, created)
    assert not ctx.session.unnamed
    chat.send(ctx, "What grows in the shade")
    assert stub.chats[created["id"]]["title"] == PLACEHOLDER


@pytest.mark.parametrize(("message", "name"), NAME_CASES)
def test_a_message_gives_a_new_chat_a_name_of_at_most_48_characters_cut_at_a_word_end(
    message: str, name: str
) -> None:
    assert chat._title_of(message) == name
    assert len(name.rstrip("…")) <= 48


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_window_names_a_chat_the_same_as_the_terminal_client() -> None:
    """The two hold the rule once each, in their own language; the same table
    runs through the window's function as it really stands in its source."""
    script = (
        WINDOW_RULE.read_text(encoding="utf-8")
        + "\nconsole.log(JSON.stringify("
        + json.dumps([message for message, _ in NAME_CASES])
        + ".map(chatNameFrom)))\n"
    )
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout.strip().splitlines()[-1]) == [name for _, name in NAME_CASES]


def test_the_window_holds_the_rule_once_and_the_studio_opens_no_chat() -> None:
    """The message field names the chat it opens by the one function and
    carries no cut of its own; the picture studio opens no chat, so it
    names none."""
    window = WINDOW.read_text(encoding="utf-8")
    studio = STUDIO.read_text(encoding="utf-8")
    assert "import { chatNameFrom } from './chatName.js'" in window
    assert "chatNameFrom(fuerTitel)" in window
    assert "function chatNameFrom" not in window and "CHAT_NAME_LIMIT" not in window
    assert "chatName" not in studio and "openNewChat" not in studio
    assert "slice(0, 40)" not in studio


def test_a_long_first_message_names_a_new_chat_at_a_word_end(
    stub: StubService, ctx: Context
) -> None:
    chat.new_chat(ctx)
    chat.send(ctx, SIXTY_TWO + "\nand a second line")
    assert stub.chats["chat-1"]["title"] == "Which seeds will still bloom well in a north…"
