"""``exe --continue``: the chat used most recently is opened, with its
history. The service is the stand-in."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from cli.main import main
from cli.texts import Texts
from tests.cli.stub_service import StubService, model


def texts() -> Texts:
    return Texts("en")


def chat_entry(identifier: str, title: str, updated: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": identifier,
        "title": title,
        "updated_at": updated,
        "working_dirs": [],
        "project_id": None,
        "archived": False,
        **fields,
    }


def message(identifier: str, text: str) -> dict[str, Any]:
    return {"id": identifier, "role": "user", "content": text, "reasoning": None, "stats": {}}


def start(stub: StubService, tmp_path: Path, *words: str, typed: str = "/quit\r") -> int:
    """Starts the whole client with the words and ends it by typing ``typed``."""
    stub.models = [model("local", "Local Model")]
    with create_pipe_input() as pipe:
        pipe.send_text(typed)
        net = threading.Timer(20.0, pipe.close)
        net.start()
        try:
            with create_app_session(input=pipe, output=DummyOutput()):
                return main(
                    [*words, "--lang", "en"], http=stub.http(), prefs_path=tmp_path / "cli.json"
                )
        finally:
            net.cancel()


def opened(stub: StubService) -> list[str]:
    """The chats whose history the client asked for, in order."""
    return [
        request.split("/")[-2]
        for request in stub.requests
        if request.startswith("GET /api/v1/chats/") and request.endswith("/messages")
    ]


@pytest.fixture
def chats(stub: StubService) -> StubService:
    stub.chats["c-old"] = chat_entry("c-old", "Old chat", "2026-10-01T10:00:00+00:00", pinned=True)
    stub.chats["c-new"] = chat_entry("c-new", "Newest chat", "2026-10-14T10:00:00+00:00")
    stub.chats["c-mid"] = chat_entry("c-mid", "Middle chat", "2026-10-10T10:00:00+00:00")
    stub.messages = {
        "c-old": [message("m1", "Old words")],
        "c-new": [message("m2", "Newest words")],
        "c-mid": [message("m3", "Middle words")],
    }
    return stub


def test_continue_opens_the_chat_with_the_newest_change_not_the_first_listed(chats, tmp_path):
    # The pinned chat stands first in the list and is the oldest.
    assert start(chats, tmp_path, "--continue") == 0
    assert opened(chats) == ["c-new"]


def test_a_chat_named_with_chat_goes_before_continue(chats, tmp_path):
    assert start(chats, tmp_path, "--continue", "--chat", "c-mid") == 0
    assert opened(chats) == ["c-mid"]


def test_an_archived_chat_is_not_taken(chats, tmp_path):
    chats.chats["c-new"]["archived"] = True
    assert start(chats, tmp_path, "--continue") == 0
    assert opened(chats) == ["c-mid"]


def test_without_a_chat_it_says_so_and_ends_with_one(stub, tmp_path, capfd):
    assert start(stub, tmp_path, "--continue") == 1
    assert texts().t("chat.leer") in capfd.readouterr().err
    assert opened(stub) == []


def test_without_the_switch_a_new_chat_opens_as_before(chats, tmp_path):
    assert start(chats, tmp_path) == 0
    assert opened(chats) == []


def test_help_names_the_switch_with_its_sentence(stub, tmp_path, capsys):
    assert start(stub, tmp_path, "--help") == 0
    line = next(
        text for text in capsys.readouterr().out.splitlines() if text.strip().startswith("--continue")
    )
    assert texts().t("cli.help_continue") in line
