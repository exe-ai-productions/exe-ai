"""``/project`` and ``exe project``: the projects shown, made, renamed and
deleted, and the open chat moved into one or out of it. The service is the
stand-in; nothing is drawn."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

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
    def __init__(self) -> None:
        self.shown: list[list[Entry]] = []
        self.heads: list[str] = []
        self.picks: list[int | None] = []
        self.typed: list[str | None] = []
        self.defaults: list[str | None] = []

    def choose(self, entries: Any, head: str = "") -> int | None:
        self.shown.append(list(entries))
        self.heads.append(head)
        return self.picks.pop(0) if self.picks else None

    def ask_text(
        self, head: str, *, secret: bool = False, default: str | None = None
    ) -> str | None:
        self.heads.append(head)
        self.defaults.append(default)
        return self.typed.pop(0) if self.typed else None

    def rows(self, which: int = -1) -> list[list[str]]:
        return [[text for _, text in entry.cells] for entry in self.shown[which]]


class Screening(RecordingScreen):
    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.new_chats = 0

    def new_chat(self) -> None:
        self.new_chats += 1


@pytest.fixture
def tool(
    stub: StubService, wire: Callable[[httpx.Client], Context], stub_http: httpx.Client
) -> Context:
    stub.models = [model("local", "Local Model")]
    stub.projects = {
        "p-site": {"id": "p-site", "name": "Website", "archived": False},
        "p-tax": {"id": "p-tax", "name": "Taxes", "archived": False},
    }
    stub.chats["c-open"] = {"id": "c-open", "title": "Open chat", "project_id": None, "working_dirs": []}
    stub.chats["c-site"] = {"id": "c-site", "title": "Site notes", "project_id": "p-site", "working_dirs": []}
    context = wire(stub_http)
    context.asker = Asking()
    context.renderer = RecordingRenderer()
    context.screen = Screening(context)
    context.commands = commands.build_commands(context)
    context.session.chat = dict(stub.chats["c-open"])
    return context


def actions(stub: StubService) -> list[tuple[str, str]]:
    return [(what, which) for what, which, _ in stub.project_actions]


def moves(stub: StubService) -> list[Any]:
    return [change["project_id"] for change in stub.changes if "project_id" in change]


# --- The selection -----------------------------------------------------------------------------


def test_the_selection_has_new_project_on_top_and_the_projects_with_their_chats(tool):
    tool.commands.run("/project")
    assert tool.asker.rows() == [
        [texts().t("project.new")], ["Website", "1"], ["Taxes", "0"],
    ]


def test_the_project_of_the_open_chat_carries_the_sign(tool, stub):
    tool.session.chat = dict(stub.chats["c-site"])
    tool.commands.run("/project")
    assert [entry.in_use for entry in tool.asker.shown[0]] == [False, True, False]


def test_closing_the_selection_sends_nothing(tool, stub):
    tool.commands.run("/project")
    assert stub.project_actions == [] and moves(stub) == []


# --- A new project ---------------------------------------------------------------------------------


def test_new_project_asks_for_a_name_with_an_empty_field_and_makes_it_without_a_word(tool, stub):
    tool.asker.picks = [0]
    tool.asker.typed = ["Garden"]
    tool.commands.run("/project")
    assert tool.asker.heads[-1] == texts().t("project.name_question")
    assert tool.asker.defaults == [None]
    assert stub.project_actions == [("create", "project-1", {"name": "Garden"})]
    assert tool.renderer.notices == []


@pytest.mark.parametrize("answer", [None, "", "   "])
def test_an_empty_name_or_the_question_left_makes_nothing(tool, stub, answer):
    tool.asker.picks = [0]
    tool.asker.typed = [answer]
    tool.commands.run("/project")
    assert stub.project_actions == []


# --- Moving the open chat ----------------------------------------------------------------------


def test_a_project_offers_move_rename_and_delete_under_its_name(tool, stub):
    tool.asker.picks = [1, None]
    tool.commands.run("/project")
    assert tool.asker.heads[-1] == "Website"
    assert tool.asker.rows() == [
        [texts().t("project.move_to")], [texts().t("chat.umbenennen")], [texts().t("chat.loeschen")],
    ]


def test_move_to_project_sends_the_project_and_the_open_chat_takes_the_answer(tool, stub):
    tool.asker.picks = [1, 0]
    tool.commands.run("/project")
    assert moves(stub) == ["p-site"]
    assert tool.session.chat["project_id"] == "p-site"
    assert tool.renderer.notices == []
    tool.asker.picks = [1, None]
    tool.commands.run("/project")
    assert tool.asker.rows() == [
        [texts().t("project.remove_from")], [texts().t("chat.umbenennen")], [texts().t("chat.loeschen")],
    ]


def test_remove_from_project_sends_null(tool, stub):
    stub.chats["c-open"]["project_id"] = "p-site"
    tool.session.chat = dict(stub.chats["c-open"])
    tool.asker.picks = [1, 0]
    tool.commands.run("/project")
    assert moves(stub) == [None]
    assert tool.session.chat["project_id"] is None


def test_a_chat_the_service_does_not_have_yet_cannot_be_moved(tool, stub):
    tool.session.chat = None
    tool.asker.picks = [1, None]
    tool.commands.run("/project")
    assert tool.asker.rows() == [[texts().t("chat.umbenennen")], [texts().t("chat.loeschen")]]
    assert moves(stub) == []


# --- Renaming ---------------------------------------------------------------------------------------


def test_rename_asks_with_the_name_that_stands_and_sends_the_new_one(tool, stub):
    tool.asker.picks = [1, 1]
    tool.asker.typed = ["Web"]
    tool.commands.run("/project")
    assert tool.asker.defaults == ["Website"]
    assert stub.project_actions == [("change", "p-site", {"name": "Web"})]


@pytest.mark.parametrize("answer", [None, "", "Website"])
def test_a_name_left_empty_or_the_same_changes_nothing(tool, stub, answer):
    tool.asker.picks = [1, 1]
    tool.asker.typed = [answer]
    tool.commands.run("/project")
    assert stub.project_actions == []


# --- Deleting ---------------------------------------------------------------------------------------


def test_delete_names_the_project_and_its_chats_and_goes_through_the_archive(tool, stub):
    tool.asker.picks = [1, 2, 0]
    tool.commands.run("/project")
    assert tool.asker.heads[-1] == texts().t("archive.delete_project_question", name="Website", count=1)
    assert tool.asker.rows() == [[texts().t("app.ja")], [texts().t("app.nein")]]
    assert actions(stub) == [("change", "p-site"), ("delete", "p-site")]
    assert stub.project_actions[0][2] == {"archived": True}
    assert "c-site" not in stub.chats
    assert tool.renderer.notices == []
    # The open chat was not in it.
    assert tool.session.chat["id"] == "c-open"


def test_the_open_chat_that_went_with_the_project_is_replaced_by_a_new_one(tool, stub):
    tool.session.chat = dict(stub.chats["c-site"])
    # The chat is in the project: "remove from project", rename, delete.
    tool.asker.picks = [1, 2, 0]
    tool.commands.run("/project")
    assert tool.session.chat is None


def test_behind_a_running_answer_the_new_chat_opens_in_its_turn(tool, stub):
    tool.session.chat = dict(stub.chats["c-site"])
    tool.session.answering = True
    tool.asker.picks = [1, 2, 0]
    tool.commands.run("/project")
    assert tool.screen.new_chats == 1


@pytest.mark.parametrize("pick", [1, None])
def test_no_and_leaving_the_question_delete_nothing(tool, stub, pick):
    tool.asker.picks = [1, 2, pick]
    tool.commands.run("/project")
    assert stub.project_actions == []
    assert "p-site" in stub.projects


def test_a_refusal_of_the_deletion_brings_the_project_back_and_says_the_sentence(tool, stub):
    stub.refuse_project_delete = "A run in the project does not stop."
    tool.asker.picks = [1, 2, 0]
    tool.commands.run("/project")
    assert tool.renderer.errors == ["A run in the project does not stop."]
    assert [body for what, _, body in stub.project_actions if what == "change"] == [
        {"archived": True}, {"archived": False},
    ]
    assert stub.projects["p-site"]["archived"] is False


# --- A number ------------------------------------------------------------------------------------------


def test_a_number_shows_that_project_directly_and_one_is_the_new_project(tool, stub):
    tool.asker.picks = [None]
    tool.commands.run("/project 3")
    assert tool.asker.heads == ["Taxes"]
    tool.asker.typed = ["Garden"]
    tool.commands.run("/project 1")
    assert stub.project_actions == [("create", "project-1", {"name": "Garden"})]


def test_a_number_the_list_does_not_reach_and_another_word_are_unknown(tool, stub):
    tool.commands.run("/project 9")
    tool.commands.run("/project website")
    assert tool.renderer.errors == [
        texts().t("cli.unknown_choice", name="9"), texts().t("cli.unknown_choice", name="website"),
    ]
    assert stub.project_actions == []


# --- From outside --------------------------------------------------------------------------------------


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
                    [*words, "--lang", "en"], http=stub.http(), prefs_path=tmp_path / "cli.json"
                )
        finally:
            net.cancel()


def test_exe_project_without_a_terminal_says_what_to_give(stub, tmp_path, monkeypatch, capsys):
    stub.models = [model("local", "Local Model")]
    assert run_outside(stub, tmp_path, monkeypatch, "project", terminal=False) == 2
    assert capsys.readouterr().err.strip() == texts().t("cli.needs_terminal", program="exe")
