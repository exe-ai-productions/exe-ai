"""``/dir`` and ``exe dir``: the working folders of the open chat, shown,
shared and stopped being shared. The service is the stand-in; nothing is
drawn."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import threading
from pathlib import Path

import httpx
import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from cli import commands, outside
from cli.interfaces import Asker, Context, Entry
from cli.main import main
from cli.texts import Texts
from tests.cli.conftest import RecordingRenderer, RecordingScreen
from tests.cli.stub_service import StubService, model


def texts() -> Texts:
    return Texts("en")


class Asking(Asker):
    """Keeps what the selections showed and answers with what a test
    names."""

    def __init__(self) -> None:
        self.shown: list[list[Entry]] = []
        self.heads: list[str] = []
        self.picks: list[int | None] = []
        self.typed: list[str | None] = []
        self.questions: list[str] = []

    def choose(self, entries: Any, head: str = "") -> int | None:
        self.shown.append(list(entries))
        self.heads.append(head)
        return self.picks.pop(0) if self.picks else None

    def ask_text(
        self, head: str, *, secret: bool = False, default: str | None = None
    ) -> str | None:
        self.questions.append(head)
        return self.typed.pop(0) if self.typed else None

    def rows(self, which: int = -1) -> list[list[tuple[str, str]]]:
        return [entry.cells for entry in self.shown[which]]


@pytest.fixture
def tool(
    stub: StubService, wire: Callable[[httpx.Client], Context], stub_http: httpx.Client
) -> Context:
    stub.models = [model("local", "Local Model")]
    stub.chats["chat-seed"] = {
        "id": "chat-seed",
        "title": "Work",
        "working_dirs": ["/work/site", "/work/notes"],
        "project_id": None,
    }
    context = wire(stub_http)
    context.asker = Asking()
    context.renderer = RecordingRenderer()
    context.screen = RecordingScreen(context)
    context.commands = commands.build_commands(context)
    context.session.chat = dict(stub.chats["chat-seed"])
    return context


def patches(stub: StubService) -> list[Any]:
    return [change["working_dirs"] for change in stub.changes if "working_dirs" in change]


# --- The selection ------------------------------------------------------------------------


def test_the_selection_shows_the_share_entry_on_top_and_the_folders_below(tool):
    tool.commands.run("/dir")
    assert tool.asker.rows() == [
        [("text", texts().t("arbeitsordner.hinzufuegen"))],
        [("text", "/work/site")],
        [("text", "/work/notes")],
    ]
    assert tool.asker.heads == [""]


def test_a_missing_folder_stands_in_yellow_with_the_sentence_above(tool, stub):
    stub.missing_folders = ["/work/notes"]
    tool.commands.run("/dir")
    assert tool.asker.rows()[2] == [("yellow", "/work/notes")]
    assert tool.asker.rows()[1] == [("text", "/work/site")]
    assert tool.asker.heads == [texts().t("arbeitsordner.fehlt_satz")]


def test_a_chat_the_service_does_not_have_yet_shows_only_the_share_entry(tool, stub):
    tool.session.chat = None
    tool.commands.run("/dir")
    assert tool.asker.rows() == [[("text", texts().t("arbeitsordner.waehlen"))]]
    assert not stub.chats.get("chat-2")
    assert patches(stub) == []


def test_picking_the_share_entry_asks_for_a_path_and_sends_the_whole_list(tool, stub):
    tool.asker.picks = [0]
    tool.asker.typed = ["~/Projects/new"]
    tool.commands.run("/dir")
    assert tool.asker.questions == [texts().t("arbeitsordner.waehlen")]
    assert patches(stub) == [["/work/site", "/work/notes", "~/Projects/new"]]
    assert tool.renderer.errors == []


def test_picking_a_folder_asks_whether_to_stop_sharing_it_and_sends_the_rest(tool, stub):
    tool.asker.picks = [1, 0]
    tool.commands.run("/dir")
    assert tool.asker.rows()[-1] == [("text", texts().t("arbeitsordner.loesen"))]
    assert tool.asker.heads[-1] == "/work/site"
    assert patches(stub) == [["/work/notes"]]


def test_closing_the_selection_sends_nothing(tool, stub):
    tool.asker.picks = [None]
    tool.commands.run("/dir")
    assert patches(stub) == []
    assert tool.renderer.errors == []


def test_leaving_the_question_about_stopping_sends_nothing(tool, stub):
    tool.asker.picks = [1, None]
    tool.commands.run("/dir")
    assert patches(stub) == []


def test_leaving_the_question_for_the_path_sends_nothing(tool, stub):
    tool.asker.picks = [0]
    tool.asker.typed = [None]
    tool.commands.run("/dir")
    assert patches(stub) == []


# --- In one line --------------------------------------------------------------------------


def test_add_with_a_path_shares_it_as_it_was_typed(tool, stub):
    tool.commands.run("/dir add ~/Projects/website")
    assert patches(stub) == [["/work/site", "/work/notes", "~/Projects/website"]]
    assert tool.asker.shown == []
    assert tool.session.chat["working_dirs"] == ["/work/site", "/work/notes", "~/Projects/website"]


def test_add_without_a_path_asks_for_it(tool, stub):
    tool.asker.typed = ["/work/more"]
    tool.commands.run("/dir add")
    assert patches(stub) == [["/work/site", "/work/notes", "/work/more"]]


def test_a_path_that_is_shared_already_sends_nothing(tool, stub):
    tool.commands.run("/dir add /work/site")
    assert patches(stub) == []
    assert tool.renderer.errors == []


def test_remove_counts_from_two_because_the_first_entry_shares(tool, stub):
    tool.commands.run("/dir remove 2")
    assert patches(stub) == [["/work/notes"]]
    tool.commands.run("/dir remove 2")
    assert patches(stub) == [["/work/notes"], []]


def test_remove_one_is_not_a_folder(tool, stub):
    tool.commands.run("/dir remove 1")
    assert tool.renderer.errors == [texts().t("cli.unknown_choice", name="remove 1")]
    assert patches(stub) == []


def test_remove_a_number_beyond_the_list_is_not_a_folder(tool, stub):
    tool.commands.run("/dir remove 9")
    assert tool.renderer.errors == [texts().t("cli.unknown_choice", name="remove 9")]
    assert patches(stub) == []


def test_remove_without_a_number_opens_the_selection(tool, stub):
    tool.commands.run("/dir remove")
    assert len(tool.asker.shown) == 1
    assert patches(stub) == []


def test_another_word_is_said_as_unknown(tool, stub):
    tool.commands.run("/dir delete 2")
    assert tool.renderer.errors == [texts().t("cli.unknown_choice", name="delete 2")]
    assert patches(stub) == []


# --- The service says no --------------------------------------------------------------------


def test_a_path_the_service_refuses_stands_with_its_sentence_and_the_list_stays(tool, stub):
    stub.refuse_folder = "The folder does not exist."
    tool.commands.run("/dir add /nowhere")
    assert tool.renderer.errors == ["The folder does not exist."]
    assert tool.session.chat["working_dirs"] == ["/work/site", "/work/notes"]


# --- A new chat -------------------------------------------------------------------------------


def test_sharing_in_a_new_chat_makes_the_chat_first_and_then_shares(tool, stub):
    tool.session.chat = None
    tool.commands.run("/dir add /work/fresh")
    assert tool.session.chat is not None
    made = tool.session.chat["id"]
    assert made in stub.chats and made != "chat-seed"
    assert stub.chats[made]["working_dirs"] == ["/work/fresh"]
    assert patches(stub) == [["/work/fresh"]]


# --- From outside --------------------------------------------------------------------------


def run_outside(
    stub: StubService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *words: str, terminal: bool
) -> int:
    monkeypatch.setattr(outside, "has_terminal", lambda: terminal)
    with create_pipe_input() as pipe:
        net = threading.Timer(20.0, pipe.close)
        net.start()
        try:
            with create_app_session(input=pipe, output=DummyOutput()):
                return main(
                    [*words, "--lang", "en"],
                    http=stub.http(),
                    prefs_path=tmp_path / "cli.json",
                )
        finally:
            net.cancel()


def test_exe_dir_without_a_terminal_says_what_to_give(stub, tmp_path, monkeypatch, capsys):
    stub.models = [model("local", "Local Model")]
    assert run_outside(stub, tmp_path, monkeypatch, "dir", terminal=False) == 2
    assert capsys.readouterr().err.strip() == texts().t("cli.needs_terminal", program="exe")


def test_exe_dir_add_with_a_path_needs_no_terminal(stub, tmp_path, monkeypatch, capsys):
    stub.models = [model("local", "Local Model")]
    assert run_outside(stub, tmp_path, monkeypatch, "dir", "add", "/work/site", terminal=False) == 0
    # The folder the client started in is shared first, as with every chat
    # made at a service of this machine; the path comes after it.
    shared = [change["working_dirs"] for change in stub.changes if "working_dirs" in change]
    assert shared[-1][-1] == "/work/site" and "/work/site" not in shared[0]
