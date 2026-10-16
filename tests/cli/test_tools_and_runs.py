"""``/tools`` switching tools on and off, and ``/ps`` showing and stopping
the commands the model has running. The service is the stand-in; nothing is
drawn."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from cli import commands
from cli.interfaces import Asker, Context, Entry
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

    def choose(self, entries: Any, head: str = "") -> int | None:
        self.shown.append(list(entries))
        self.heads.append(head)
        return self.picks.pop(0) if self.picks else None

    def rows(self) -> list[list[str]]:
        return [[text for _, text in entry.cells] for entry in self.shown[-1]]


def run(number: int, command: str, **fields: Any) -> dict[str, Any]:
    return {
        "lauf": number, "befehl": command, "hintergrund": False, "zustand": "laeuft",
        "art": "befehl", "code": None, "ausgabe": "", **fields,
    }


@pytest.fixture
def tool(
    stub: StubService, wire: Callable[[httpx.Client], Context], stub_http: httpx.Client
) -> Context:
    stub.models = [model("local", "Local Model")]
    stub.tools = [
        {"name": "read_file", "server": "files", "beschreibung": "Reads."},
        {"name": "run_command", "server": "shell", "beschreibung": "Runs."},
    ]
    stub.always_allowed = {"run_command": "always"}
    stub.settings.setdefault("global", {})["werkzeuge_aus"] = ["run_command"]
    stub.chats["c-1"] = {"id": "c-1", "title": "A chat", "working_dirs": [], "project_id": None}
    context = wire(stub_http)
    context.asker = Asking()
    context.renderer = RecordingRenderer()
    context.screen = RecordingScreen(context)
    context.commands = commands.build_commands(context)
    context.session.chat = dict(stub.chats["c-1"])
    return context


def switched_off(stub: StubService) -> Any:
    return stub.settings["global"].get("werkzeuge_aus")


# --- /tools ------------------------------------------------------------------------------------


def test_tools_shows_the_count_of_active_over_all_and_each_tool_with_its_state(tool):
    tool.commands.run("/tools")
    assert tool.asker.heads == [texts().t("cli.tools_count", active=1, total=2)]
    assert [row[1:] for row in tool.asker.rows()] == [
        ["read_file", "files", "", texts().t("status.aktiv")],
        ["run_command", "shell", texts().t("werkzeug.yes_dont_ask_again"), texts().t("status.inaktiv")],
    ]


def test_enter_on_an_inactive_tool_puts_the_list_without_it_as_null_and_says_its_line(tool, stub):
    tool.asker.picks = [1]
    tool.commands.run("/tools")
    assert switched_off(stub) is None
    assert tool.renderer.notices == [
        f"{tool.asker.rows()[1][0]}  run_command  shell  {texts().t('werkzeug.yes_dont_ask_again')}  "
        f"{texts().t('status.aktiv')}"
    ]


def test_a_number_switches_that_tool_and_the_whole_new_list_goes_out(tool, stub):
    tool.commands.run("/tools 1")
    assert switched_off(stub) == ["run_command", "read_file"]
    assert tool.renderer.notices[0].endswith(texts().t("status.inaktiv"))


def test_a_number_counts_into_the_list_as_it_was_last_shown(tool, stub):
    tool.commands.run("/tools")
    tool.commands.run("/tools 2")
    assert switched_off(stub) is None


def test_leaving_the_selection_switches_nothing(tool, stub):
    tool.commands.run("/tools")
    assert switched_off(stub) == ["run_command"]
    assert tool.renderer.notices == []


def test_a_refusal_of_the_service_says_its_sentence(tool, stub, monkeypatch):
    from cli.client import ServiceError

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise ServiceError(400, "The setting cannot be written.")

    monkeypatch.setattr(tool.client, "put", refuse)
    tool.commands.run("/tools 1")
    assert tool.renderer.errors == ["The setting cannot be written."]
    assert tool.renderer.notices == []


@pytest.mark.parametrize("line", ["/tools 9", "/tools 0", "/tools on read_file", "/tools 1 2", "/tools forget"])
def test_a_number_that_is_no_tool_and_any_other_word_name_the_form(tool, stub, line):
    tool.commands.run(line)
    assert tool.renderer.errors == [texts().t("cli.werkzeug_syntax")]
    assert switched_off(stub) == ["run_command"]


def test_without_tools_the_sentence_for_none_stands(tool, stub):
    stub.tools = []
    tool.commands.run("/tools")
    assert tool.renderer.notices == [texts().t("cli.keine_werkzeuge")]
    assert tool.asker.shown == []


def test_forget_takes_a_permission_back_as_before(tool, stub):
    tool.commands.run("/tools forget run_command")
    assert tool.renderer.notices == [texts().t("cli.tool_asks_again", name="run_command")]
    assert "run_command" not in stub.always_allowed


# --- /ps ----------------------------------------------------------------------------------------


def test_ps_shows_the_commands_that_run_with_the_word_for_the_background(tool, stub):
    stub.runs["c-1"] = [
        run(1, "npm run dev", hintergrund=True),
        run(2, "make test"),
        run(3, "ls", zustand="fertig"),
        run(4, "image", art="bild"),
    ]
    tool.commands.run("/ps")
    assert tool.asker.rows() == [
        ["npm run dev", texts().t("terminal.hintergrund")],
        ["make test", ""],
    ]


def test_enter_stops_the_command_and_says_nothing(tool, stub):
    stub.runs["c-1"] = [run(1, "npm run dev"), run(7, "make test")]
    tool.asker.picks = [1]
    tool.commands.run("/ps")
    assert stub.run_stops == [("c-1", 7)]
    assert tool.renderer.notices == []


def test_a_number_stops_that_command_of_the_list_directly(tool, stub):
    stub.runs["c-1"] = [run(4, "npm run dev"), run(9, "make test")]
    tool.commands.run("/ps 2")
    assert stub.run_stops == [("c-1", 9)]
    assert tool.asker.shown == []


def test_leaving_the_selection_stops_nothing(tool, stub):
    stub.runs["c-1"] = [run(1, "npm run dev")]
    tool.commands.run("/ps")
    assert stub.run_stops == []


def test_without_a_running_command_the_sentence_stands_and_nothing_is_stopped(tool, stub):
    stub.runs["c-1"] = [run(1, "ls", zustand="fertig")]
    tool.commands.run("/ps")
    assert tool.renderer.notices == [texts().t("cli.ps_none")]
    assert stub.run_stops == []


def test_a_chat_the_service_does_not_have_yet_is_not_asked(tool, stub):
    tool.session.chat = None
    tool.commands.run("/ps")
    assert tool.renderer.notices == [texts().t("cli.ps_none")]
    assert stub.run_listings == []


@pytest.mark.parametrize("line", ["/ps 3", "/ps 0", "/ps now"])
def test_a_number_that_is_no_command_and_another_word_are_unknown(tool, stub, line):
    stub.runs["c-1"] = [run(1, "npm run dev"), run(2, "make test")]
    tool.commands.run(line)
    assert tool.renderer.errors == [texts().t("cli.unknown_choice", name=line.split()[1])]
    assert stub.run_stops == []
