"""``/agents edit`` and ``exe agents edit``: agents made, changed field by
field and deleted. The service is the stand-in; the editor is a function
that hands back the text the person saved."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from cli import commands, editor, outside
from cli.interfaces import Asker, Context
from cli.main import main
from cli.texts import Texts
from tests.cli.conftest import RecordingScreen
from tests.cli.stub_service import StubService, model
from tests.cli.test_agents import Recording


def texts() -> Texts:
    return Texts("en")


class Asking(Asker):
    """Answers from lists, in the order the walk asks."""

    def __init__(self) -> None:
        self.picks: list[int | None] = []
        self.typed: list[str | None] = []
        self.checks: list[list[int] | None] = []
        self.shown: list[list[list[str]]] = []
        self.notes: list[list[str]] = []
        self.heads: list[str] = []
        self.defaults: list[str | None] = []
        self.checked_in: list[list[int]] = []

    def choose(self, entries: Any, head: str = "") -> int | None:
        listed = list(entries)
        self.shown.append([[text for _, text in entry.cells] for entry in listed])
        self.notes.append([entry.note for entry in listed])
        self.heads.append(head)
        return self.picks.pop(0) if self.picks else None

    def check(self, entries: Any, head: str = "", checked: Any = ()) -> list[int] | None:
        listed = list(entries)
        self.shown.append([[text for _, text in entry.cells] for entry in listed])
        self.heads.append(head)
        self.checked_in.append(sorted(checked))
        return self.checks.pop(0) if self.checks else None

    def ask_text(
        self, head: str, *, secret: bool = False, default: str | None = None
    ) -> str | None:
        self.heads.append(head)
        self.defaults.append(default)
        return self.typed.pop(0) if self.typed else None


@pytest.fixture
def tool(
    stub: StubService,
    wire: Callable[[httpx.Client], Context],
    stub_http: httpx.Client,
    monkeypatch: pytest.MonkeyPatch,
) -> Context:
    stub.models = [model("local", "Local Model")]
    stub.agents = [
        {
            "name": "researcher",
            "description": "Reads and sums up.",
            "tools": ["read_file", "legacy_tool"],
            "folders": ["/work/a", "/work/b"],
            "max_rounds": 12,
            "max_minutes": 20.0,
            "max_tokens": 4000,
            "reasoning_budget": None,
            "max_command_seconds": None,
            "color": "#ff0000",
        },
        {"name": "writer", "description": "Writes texts.", "tools": None, "folders": [],
         "max_rounds": 30, "max_minutes": 20.0},
    ]
    stub.agent_prompts = {"researcher": "Read the sources.", "writer": "Write well."}
    stub.broken_agents = {"broken": "The head of broken.md cannot be read."}
    stub.tools = [
        {"name": "read_file", "server": "builtin"},
        {"name": "web_search", "server": "builtin"},
        {"name": "mcp__db__query", "anzeige": "query", "server": "db"},
    ]
    context = wire(stub_http)
    context.asker = Asking()
    context.renderer = Recording()  # type: ignore[assignment]
    context.screen = RecordingScreen(context)
    context.commands = commands.build_commands(context)
    monkeypatch.setattr(editor, "edit", lambda ctx, text: None)
    return context


def edited(monkeypatch: pytest.MonkeyPatch, *results: str | None) -> list[str]:
    """Lets the editor hand back ``results`` in turn; returns the texts it
    was opened with."""
    seen: list[str] = []
    queue = list(results)

    def fake(ctx: Context, text: str) -> str | None:
        seen.append(text)
        return queue.pop(0) if queue else None

    monkeypatch.setattr(editor, "edit", fake)
    return seen


def saved(stub: StubService) -> list[tuple[str, dict[str, Any]]]:
    return [(name, body) for what, name, body in stub.agent_actions if what == "save"]


# --- Changing an agent ------------------------------------------------------------------------


def test_the_walk_asks_the_fields_in_the_order_of_the_mask(tool, stub, monkeypatch):
    seen = edited(monkeypatch, None)
    tool.commands.run("/agents edit researcher")
    heads = tool.asker.heads
    # Description (typed), tools (checklist), folders (selection), limits
    # (selection), and the instruction goes to the editor with what stands.
    assert heads[0] == texts().t("agenten.purpose")
    assert tool.asker.defaults == ["Reads and sums up."]
    assert heads[1] == texts().t("werkzeuge.titel")
    assert heads[-1] == texts().t("agenten.grenzen")
    assert seen == ["Read the sources."]
    assert stub.agent_actions == []


def test_leaving_every_question_changes_nothing_and_sends_nothing(tool, stub):
    tool.commands.run("/agents edit researcher")
    assert stub.agent_actions == []
    assert tool.renderer.notices == []


def test_a_changed_description_is_the_only_field_that_goes_out(tool, stub):
    tool.asker.typed = ["Finds things out."]
    tool.commands.run("/agents edit researcher")
    assert saved(stub) == [("researcher", {"description": "Finds things out."})]
    assert tool.renderer.notices == [texts().t("agenten.gesichert", name="researcher")]


def test_the_checklist_has_all_tools_on_top_and_ticks_what_holds(tool, stub):
    tool.commands.run("/agents edit researcher")
    rows = tool.asker.shown[0]
    assert rows[0] == [texts().t("agenten.alle_werkzeuge")]
    # A tool of a server stands with the server's name in front; one the
    # agent names that is not offered stays on the list at the end.
    assert [row[0] for row in rows[1:]] == [
        "read_file", "web_search", "db · query", "legacy_tool",
    ]
    assert tool.asker.checked_in == [[1, 4]]


def test_all_tools_ticked_sends_null_for_the_tools(tool, stub):
    tool.asker.checks = [[0, 1]]
    tool.commands.run("/agents edit researcher")
    assert saved(stub) == [("researcher", {"tools": None})]


def test_a_chosen_set_of_tools_goes_out_as_a_list(tool, stub):
    tool.asker.checks = [[2, 3]]
    tool.commands.run("/agents edit researcher")
    assert saved(stub) == [("researcher", {"tools": ["web_search", "mcp__db__query"]})]


def test_no_tool_ticked_at_all_is_the_empty_list(tool, stub):
    tool.asker.checks = [[]]
    tool.commands.run("/agents edit researcher")
    assert saved(stub) == [("researcher", {"tools": []})]


def test_confirming_the_checklist_as_it_stands_sends_nothing(tool, stub):
    tool.asker.checks = [[1, 4]]
    tool.commands.run("/agents edit researcher")
    assert stub.agent_actions == []


def test_a_shared_folder_is_added_and_one_is_stopped_being_shared(tool, stub):
    # Folders: share another (entry 0), type its path; then the first folder
    # (entry 1) and "Yes"; then Esc ends the step.
    tool.asker.picks = [0, 1, 0, None]
    tool.asker.typed = [None, "/work/c"]
    tool.commands.run("/agents edit researcher")
    assert saved(stub) == [("researcher", {"folders": ["/work/b", "/work/c"]})]


def test_without_folders_left_the_field_goes_out_as_null(tool, stub):
    tool.asker.picks = [1, 0, 1, 0, None]
    tool.commands.run("/agents edit researcher")
    assert saved(stub) == [("researcher", {"folders": None})]


def test_no_to_the_question_about_a_folder_keeps_it(tool, stub):
    tool.asker.picks = [1, 1, None]
    tool.commands.run("/agents edit researcher")
    assert stub.agent_actions == []


def limits(tool: Context, *steps: tuple[int, str | None]) -> None:
    """Folders left at once, then each limit picked and answered in turn,
    then the step left."""
    asking = cast(Asking, tool.asker)
    asking.picks = [None]
    for number, typed in steps:
        asking.picks.append(number)
        asking.typed.append(typed)
    asking.picks.append(None)
    # The description question comes first and is left.
    asking.typed.insert(0, None)


def test_the_limits_stand_with_their_values_and_auto_where_none_is_set(tool, stub):
    limits(tool)
    tool.commands.run("/agents edit researcher")
    assert tool.asker.shown[-1] == [
        [texts().t("agenten.max_runden"), "12"],
        [texts().t("agenten.max_minuten"), "20"],
        [texts().t("agenten.max_token"), "4000"],
        [texts().t("agenten.denklaenge"), texts().t("parameter.auto")],
        [texts().t("agenten.max_befehlssekunden"), texts().t("parameter.auto")],
    ]


def test_a_limit_is_held_within_the_span_of_the_mask(tool, stub):
    limits(tool, (0, "5000"), (1, "0"), (4, "-3"))
    tool.commands.run("/agents edit researcher")
    assert saved(stub) == [
        ("researcher", {"max_rounds": 999, "max_minutes": 1, "max_command_seconds": 1})
    ]


def test_a_new_number_goes_out_as_typed(tool, stub):
    limits(tool, (0, "7"), (3, "2048"))
    tool.commands.run("/agents edit researcher")
    assert saved(stub) == [("researcher", {"max_rounds": 7, "reasoning_budget": 2048})]


def test_empty_or_the_word_for_auto_clears_a_limit_that_may_be_auto(tool, stub):
    limits(tool, (2, "Auto"))
    tool.commands.run("/agents edit researcher")
    assert saved(stub) == [("researcher", {"max_tokens": None})]


def test_empty_leaves_a_limit_that_has_no_auto_as_it_was(tool, stub):
    limits(tool, (0, ""))
    tool.commands.run("/agents edit researcher")
    assert stub.agent_actions == []


def test_a_word_that_is_no_number_changes_nothing(tool, stub):
    limits(tool, (0, "many"))
    tool.commands.run("/agents edit researcher")
    assert stub.agent_actions == []


def test_a_limit_question_shows_the_value_that_stands(tool, stub):
    limits(tool, (2, None))
    tool.commands.run("/agents edit researcher")
    assert tool.asker.defaults[-1] == "4000"
    assert tool.asker.heads[-2] == texts().t("agenten.max_token")


def test_a_locked_thinking_length_shows_the_reason_and_cannot_be_changed(tool, stub):
    stub.run_model = {
        "endpoint_id": "local", "name": "Local Model",
        "denklaenge": {"aktiv": False, "grund": "This model cannot think."},
    }
    limits(tool, (3, "512"))
    tool.commands.run("/agents edit researcher")
    assert tool.asker.notes[-1][3] == "This model cannot think."
    assert stub.agent_actions == []
    # Enter on it asked nothing: only the description question was asked.
    assert len(tool.asker.defaults) == 1


def test_the_model_is_asked_with_whether_the_agent_works_through_tools(tool, stub):
    limits(tool)
    tool.commands.run("/agents edit researcher")
    assert stub.run_model_asked == [{"werkzeuge": "true"}]
    stub.run_model_asked.clear()
    tool.asker.checks = [[]]
    limits(tool)
    tool.commands.run("/agents edit researcher")
    assert stub.run_model_asked == [{"werkzeuge": "false"}]


def test_a_new_instruction_from_the_editor_goes_out_and_the_same_one_does_not(tool, stub, monkeypatch):
    edited(monkeypatch, "Read the sources carefully.\n")
    tool.commands.run("/agents edit researcher")
    assert saved(stub) == [("researcher", {"prompt": "Read the sources carefully."})]


def test_the_color_never_goes_out(tool, stub, monkeypatch):
    tool.asker.typed = ["Another sentence."]
    tool.asker.checks = [[0]]
    edited(monkeypatch, "New.")
    tool.commands.run("/agents edit researcher")
    assert "color" not in saved(stub)[0][1]


def test_a_name_that_is_no_agent_says_it_is_not_available(tool, stub):
    tool.commands.run("/agents edit nobody")
    assert tool.renderer.errors == [texts().t("cli.unknown_choice", name="nobody")]
    assert stub.agent_actions == []


def test_a_broken_agent_says_its_sentence_and_is_not_walked(tool, stub):
    tool.commands.run("/agents edit broken")
    assert tool.renderer.errors == ["The head of broken.md cannot be read."]
    assert tool.asker.heads == []


def test_a_refusal_of_the_service_is_said_in_its_words(tool, stub):
    stub.refuse_agent = "The folder “/work/c” does not exist."
    tool.asker.typed = ["New sentence."]
    tool.commands.run("/agents edit researcher")
    assert tool.renderer.errors == ["The folder “/work/c” does not exist."]
    assert tool.renderer.notices == []


# --- The selection -------------------------------------------------------------------------------


def test_the_selection_has_new_agent_on_top_and_a_broken_one_with_its_sentence(tool, stub):
    tool.commands.run("/agents edit")
    assert tool.asker.shown[0] == [
        [texts().t("agenten.neu_kurz")], ["broken"], ["researcher"], ["writer"],
    ]
    assert tool.asker.notes[0][1] == "The head of broken.md cannot be read."


def test_a_broken_agent_offers_only_the_deleting(tool, stub):
    tool.asker.picks = [1, 0, 0]
    tool.commands.run("/agents edit")
    assert tool.asker.shown[1] == [[texts().t("agenten.loeschen")]]
    assert tool.asker.heads[-1] == texts().t("agenten.loeschen_frage", name="broken")
    assert stub.agent_actions == [("delete", "broken", None)]
    assert tool.renderer.notices == [texts().t("agenten.geloescht", name="broken")]


def test_a_working_agent_offers_to_edit_and_to_delete(tool, stub):
    tool.asker.picks = [2, 1]
    tool.commands.run("/agents edit")
    assert tool.asker.shown[1] == [
        [texts().t("agenten.bearbeiten")], [texts().t("agenten.loeschen")],
    ]
    # "Delete" was picked and the question stood: nothing is deleted until
    # the answer is yes.
    assert tool.asker.heads[-1] == texts().t("agenten.loeschen_frage", name="researcher")
    assert stub.agent_actions == []


def test_no_to_the_deleting_deletes_nothing(tool, stub):
    tool.asker.picks = [3, 1, 1]
    tool.commands.run("/agents edit")
    assert stub.agent_actions == []
    assert tool.renderer.notices == []


def test_edit_from_the_selection_walks_the_fields(tool, stub):
    tool.asker.picks = [3, 0]
    tool.asker.typed = ["Writes better texts."]
    tool.commands.run("/agents edit")
    assert saved(stub) == [("writer", {"description": "Writes better texts."})]


# --- A new agent -----------------------------------------------------------------------------------


def test_a_new_agent_starts_with_the_values_of_the_mask_and_goes_out_whole(tool, stub, monkeypatch):
    edited(monkeypatch, "Test things.\n")
    tool.asker.picks = [0]
    tool.asker.typed = ["tester"]
    tool.commands.run("/agents edit")
    assert saved(stub) == [
        (
            "tester",
            {
                "description": None, "tools": None, "folders": None, "max_rounds": 30,
                "max_minutes": 20, "max_tokens": None, "reasoning_budget": None,
                "max_command_seconds": None, "prompt": "Test things.",
            },
        )
    ]
    assert tool.renderer.notices == [texts().t("agenten.gesichert", name="tester")]


def test_a_name_against_the_rule_of_the_mask_is_refused(tool, stub):
    tool.asker.picks = [0]
    tool.asker.typed = ["a b"]
    tool.commands.run("/agents edit")
    assert tool.renderer.errors == [texts().t("fehler.agent_name_ungueltig")]
    assert stub.agent_actions == []


def test_without_an_instruction_nothing_is_saved(tool, stub):
    tool.asker.picks = [0]
    tool.asker.typed = ["tester"]
    tool.commands.run("/agents edit")
    assert stub.agent_actions == []


def test_leaving_the_name_question_makes_nothing(tool, stub):
    tool.asker.picks = [0]
    tool.commands.run("/agents edit")
    assert stub.agent_actions == []
    assert tool.asker.heads[-1] == texts().t("agenten.name")


def test_a_taken_name_changes_that_agent_and_never_writes_the_starting_values_over_it(
    tool, stub, monkeypatch
):
    tool.asker.picks = [0]
    tool.asker.typed = ["researcher", "Still reads."]
    tool.commands.run("/agents edit")
    assert saved(stub) == [("researcher", {"description": "Still reads."})]


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


def test_exe_agents_edit_without_a_terminal_says_what_to_give(stub, tmp_path, monkeypatch, capsys):
    stub.models = [model("local", "Local Model")]
    stub.agents = [{"name": "researcher", "description": ""}]
    code = run_outside(stub, tmp_path, monkeypatch, "agents", "edit", "researcher", terminal=False)
    assert code == 2
    assert capsys.readouterr().err.strip() == texts().t("cli.needs_terminal", program="exe")
    assert stub.agent_actions == []
