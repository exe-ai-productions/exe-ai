"""``/chats`` with its search and its archive, and ``/rename``, ``/delete``
and ``/archive`` on the open chat. The service is the stand-in; nothing is
drawn."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from cli import chat, commands, outside
from cli.client import ServiceError
from cli.interfaces import Asker, Context, Entry
from cli.main import main
from cli.texts import Texts
from tests.cli.conftest import RecordingRenderer, RecordingScreen
from tests.cli.stub_service import StubService, model


def texts() -> Texts:
    return Texts("en")


class Asking(Asker):
    """Keeps what the selections showed and answers as a test says."""

    def __init__(self) -> None:
        self.shown: list[list[Entry]] = []
        self.heads: list[str] = []
        self.picks: list[int | None] = []
        self.typed: list[str | None] = []
        self.defaults: list[str | None] = []
        # What the selection that searches was opened with, the words
        # "typed" into it, and which of the entries then standing is picked
        # (by title).
        self.searched: list[dict[str, Any]] = []
        self.words: list[str] = []
        self.pick_title: str | None = None
        self.found: list[list[str]] = []

    def choose(self, entries: Any, head: str = "") -> int | None:
        self.shown.append(list(entries))
        self.heads.append(head)
        return self.picks.pop(0) if self.picks else None

    def search(
        self,
        entries: Sequence[Entry],
        find: Callable[[str], Sequence[Entry]],
        head: str = "",
        empty: str = "",
    ) -> Entry | None:
        self.searched.append(
            {"head": head, "empty": empty, "titles": [e.cells[0][1] for e in entries]}
        )
        standing = list(entries)
        for word in self.words:
            standing = list(find(word))
            self.found.append([e.cells[0][1] for e in standing])
        for entry in standing:
            if entry.cells[0][1] == self.pick_title:
                return entry
        return None

    def ask_text(
        self, head: str, *, secret: bool = False, default: str | None = None
    ) -> str | None:
        self.heads.append(head)
        self.defaults.append(default)
        return self.typed.pop(0) if self.typed else None


class Screening(RecordingScreen):
    """A screen that also keeps the switches of the open chat."""

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.opened: list[str] = []
        self.new_chats = 0

    def open_chat(self, chat: Any) -> None:
        self.opened.append(str(chat.get("id")))

    def new_chat(self) -> None:
        self.new_chats += 1


def chat_entry(identifier: str, title: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": identifier,
        "title": title,
        "updated_at": "2026-10-14T10:00:00+00:00",
        "working_dirs": [],
        "project_id": None,
        "archived": False,
        **fields,
    }


@pytest.fixture
def tool(
    stub: StubService, wire: Callable[[httpx.Client], Context], stub_http: httpx.Client
) -> Context:
    stub.models = [model("local", "Local Model")]
    stub.chats["chat-a"] = chat_entry("chat-a", "Website-Texte")
    stub.chats["chat-b"] = chat_entry("chat-b", "Steuer 2025")
    stub.chats["chat-c"] = chat_entry("chat-c", "Old notes", archived=True)
    context = wire(stub_http)
    context.asker = Asking()
    context.renderer = RecordingRenderer()
    context.screen = Screening(context)
    context.commands = commands.build_commands(context)
    context.session.chat = dict(stub.chats["chat-b"])
    return context


def refusing(status: int, sentence: str) -> Callable[..., Any]:
    """A request that the service answers with ``sentence``."""

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise ServiceError(status, sentence)

    return refuse


def changes(stub: StubService, field: str) -> list[Any]:
    return [change[field] for change in stub.changes if field in change]


# --- /chats and its search ----------------------------------------------------------------------


def test_the_selection_is_one_that_searches_with_the_head_for_the_search(tool):
    tool.asker.pick_title = None
    tool.commands.run("/chats")
    assert tool.asker.searched == [
        {
            "head": texts().t("chat.suchen"),
            "empty": texts().t("chat.keine_treffer"),
            "titles": ["Website-Texte", "Steuer 2025"],
        }
    ]


def test_a_word_typed_asks_the_service_for_that_word_and_the_hit_is_opened(tool, stub):
    tool.asker.words = ["web"]
    tool.asker.pick_title = "Website-Texte"
    tool.commands.run("/chats")
    assert tool.asker.found == [["Website-Texte"]]
    assert {"suche": "web", "archived": False} in stub.chat_listings
    assert tool.screen.opened == ["chat-a"]


def test_a_word_without_a_hit_leaves_nothing_to_pick(tool, stub):
    tool.asker.words = ["nothing like it"]
    tool.asker.pick_title = "Website-Texte"
    tool.commands.run("/chats")
    assert tool.asker.found == [[]]
    assert tool.screen.opened == []


def test_the_search_leaves_the_numbers_of_the_whole_list_alone(tool, stub):
    tool.asker.words = ["web"]
    tool.commands.run("/chats")
    assert [chat["title"] for chat in tool.session.shown_chats or []] == [
        "Website-Texte", "Steuer 2025",
    ]
    tool.commands.run("/chats 2")
    assert tool.screen.opened == ["chat-b"]


def test_the_archive_is_the_same_selection_over_the_archived_chats(tool, stub):
    tool.commands.run("/chats archive")
    assert tool.asker.searched[0]["titles"] == ["Old notes"]
    assert tool.asker.searched[0]["head"] == texts().t("archive.title")
    assert {"suche": "", "archived": True} in stub.chat_listings


def test_the_search_in_the_archive_stays_in_the_archive(tool, stub):
    tool.asker.words = ["old"]
    tool.asker.pick_title = "Old notes"
    tool.asker.picks = [None]
    tool.commands.run("/chats archive")
    assert {"suche": "old", "archived": True} in stub.chat_listings
    assert {"suche": "old", "archived": False} not in stub.chat_listings


def test_a_chat_of_the_archive_is_offered_to_be_restored_and_goes_back_without_a_word(tool, stub):
    tool.asker.pick_title = "Old notes"
    tool.asker.words = ["old"]
    tool.asker.picks = [0]
    tool.commands.run("/chats archive")
    assert tool.asker.shown[-1][0].cells == [("text", texts().t("archive.restore"))]
    assert changes(stub, "archived") == [False]
    assert tool.renderer.notices == []


def test_leaving_the_offer_to_restore_sends_nothing(tool, stub):
    tool.asker.pick_title = "Old notes"
    tool.asker.words = ["old"]
    tool.asker.picks = [None]
    tool.commands.run("/chats archive")
    assert changes(stub, "archived") == []


# --- /rename -----------------------------------------------------------------------------------


def test_rename_with_a_name_sends_the_title_and_the_status_line_shows_it(tool, stub):
    tool.commands.run("/rename Steuererklärung 2026")
    assert changes(stub, "title") == ["Steuererklärung 2026"]
    assert tool.session.chat["title"] == "Steuererklärung 2026"
    assert tool.renderer.notices == []


def test_rename_without_a_name_asks_with_the_name_that_stands(tool, stub):
    tool.asker.typed = ["Tax return"]
    tool.commands.run("/rename")
    assert tool.asker.heads == [texts().t("chat.neuer_titel")]
    assert tool.asker.defaults == ["Steuer 2025"]
    assert changes(stub, "title") == ["Tax return"]


@pytest.mark.parametrize("answer", [None, "", "Steuer 2025"])
def test_nothing_typed_or_the_question_left_changes_nothing(tool, stub, answer):
    tool.asker.typed = [answer]
    tool.commands.run("/rename")
    assert changes(stub, "title") == []


def test_a_chat_the_service_does_not_have_keeps_the_name_for_its_creation(tool, stub):
    tool.session.chat = None
    tool.session.unnamed = True
    tool.commands.run("/rename Planning")
    assert changes(stub, "title") == []
    assert tool.session.pending_title == "Planning"
    assert tool.session.unnamed is False
    created = chat.service_chat(tool)
    assert created["title"] == "Planning"
    assert tool.session.pending_title is None


def test_a_new_chat_forgets_a_name_given_before(tool, stub):
    tool.session.chat = None
    tool.commands.run("/rename Planning")
    chat.new_chat(tool)
    assert tool.session.pending_title is None and tool.session.unnamed is True


def test_a_refusal_of_the_service_says_its_sentence_and_keeps_the_name(tool, stub, monkeypatch):
    monkeypatch.setattr(tool.client, "patch", refusing(422, "Title too long."))
    tool.commands.run("/rename Steuererklärung 2026")
    assert tool.renderer.errors == ["Title too long."]
    assert tool.session.chat["title"] == "Steuer 2025"


# --- /delete -----------------------------------------------------------------------------------


def test_delete_asks_first_and_deletes_after_yes_and_a_new_chat_is_open(tool, stub):
    tool.asker.picks = [0]
    tool.commands.run("/delete")
    assert tool.asker.heads == [texts().t("chat.loeschen_frage")]
    assert tool.asker.shown[0][0].cells == [("text", texts().t("app.ja"))]
    assert stub.chat_deletions == ["chat-b"]
    assert tool.renderer.notices == [texts().t("chat.geloescht")]
    assert tool.session.chat is None


@pytest.mark.parametrize("pick", [1, None])
def test_no_and_leaving_the_question_delete_nothing(tool, stub, pick):
    tool.asker.picks = [pick]
    tool.commands.run("/delete")
    assert stub.chat_deletions == []
    assert tool.session.chat["id"] == "chat-b"
    assert tool.renderer.notices == []


def test_a_task_that_works_in_the_chat_is_named_in_the_question(tool, stub):
    stub.jobs = {
        "job-1": {"id": "job-1", "chat_id": "chat-b", "state": "laeuft", "agent": "researcher"},
        "job-2": {"id": "job-2", "chat_id": "chat-a", "state": "laeuft", "agent": "writer"},
    }
    tool.asker.picks = [1]
    tool.commands.run("/delete")
    assert tool.asker.heads == [texts().t("chat.delete_with_agent_question", agent="researcher")]


def test_a_task_that_is_done_does_not_change_the_question(tool, stub):
    stub.jobs = {"job-1": {"id": "job-1", "chat_id": "chat-b", "state": "fertig", "agent": "writer"}}
    tool.asker.picks = [1]
    tool.commands.run("/delete")
    assert tool.asker.heads == [texts().t("chat.loeschen_frage")]


def test_a_refusal_of_the_deletion_says_the_sentence_and_the_chat_stays_open(tool, stub):
    stub.refuse_chat_delete = "The answer does not stop."
    tool.asker.picks = [0]
    tool.commands.run("/delete")
    assert tool.renderer.errors == ["The answer does not stop."]
    assert tool.session.chat["id"] == "chat-b"
    assert tool.renderer.notices == []


def test_behind_a_running_answer_the_new_chat_opens_in_its_turn(tool, stub):
    tool.session.answering = True
    tool.asker.picks = [0]
    tool.commands.run("/delete")
    assert stub.chat_deletions == ["chat-b"]
    assert tool.screen.new_chats == 1


def test_a_chat_the_service_does_not_have_has_nothing_to_delete_or_archive(tool, stub):
    tool.session.chat = None
    tool.commands.run("/delete")
    tool.commands.run("/archive")
    assert tool.asker.shown == [] and tool.asker.heads == []
    assert stub.chat_deletions == [] and changes(stub, "archived") == []
    assert tool.renderer.notices == [] and tool.renderer.errors == []


# --- /archive ----------------------------------------------------------------------------------


def test_archive_sends_the_flag_without_a_question_and_opens_a_new_chat(tool, stub):
    tool.commands.run("/archive")
    assert changes(stub, "archived") == [True]
    assert tool.asker.shown == []
    assert tool.renderer.notices == [texts().t("cli.chat_archived")]
    assert tool.session.chat is None


def test_a_refusal_of_the_archive_keeps_the_chat_open(tool, stub, monkeypatch):
    monkeypatch.setattr(tool.client, "patch", refusing(409, "Busy."))
    tool.commands.run("/archive")
    assert tool.renderer.errors == ["Busy."]
    assert tool.session.chat["id"] == "chat-b"


# --- From outside --------------------------------------------------------------------------------


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


def test_exe_chats_without_a_terminal_says_what_to_give(stub, tmp_path, monkeypatch, capsys):
    stub.models = [model("local", "Local Model")]
    stub.chats["chat-a"] = chat_entry("chat-a", "Website-Texte")
    assert run_outside(stub, tmp_path, monkeypatch, "chats", terminal=False) == 2
    assert capsys.readouterr().err.strip() == texts().t("cli.needs_terminal", program="exe")


def test_exe_delete_from_outside_has_no_open_chat_and_does_nothing(stub, tmp_path, monkeypatch):
    stub.models = [model("local", "Local Model")]
    stub.chats["chat-a"] = chat_entry("chat-a", "Website-Texte")
    assert run_outside(stub, tmp_path, monkeypatch, "delete", terminal=False) == 0
    assert stub.chat_deletions == []
