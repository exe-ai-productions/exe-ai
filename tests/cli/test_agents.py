"""``/agents`` and ``exe agents``: the tasks of the agents shown, started,
followed, stopped and deleted, and their questions answered. The service is
the stand-in; nothing is drawn."""

from __future__ import annotations

import json
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
from tests.cli.conftest import RecordingScreen
from tests.cli.stub_service import StubService, model


def texts() -> Texts:
    return Texts("en")


class Recording:
    """A renderer that keeps the lines of a log as they were handed to it."""

    def __init__(self) -> None:
        self.notices: list[str] = []
        self.errors: list[str] = []
        self.said: list[str] = []

    def notice(self, text: str) -> None:
        self.notices.append(text)

    def error(self, text: str) -> None:
        self.errors.append(text)

    def content(self, text: str) -> None:
        self.said.append(f"content:{text}")

    def reasoning(self, text: str) -> None:
        self.said.append(f"reasoning:{text}")

    def tool_call(self, event: Any) -> None:
        self.said.append(f"call:{event.get('name')}")

    def tool_result(self, event: Any) -> None:
        self.said.append(f"result:{event.get('name')}")

    def done(self, event: Any) -> None:
        self.said.append("done")

    def __getattr__(self, name: str) -> Callable[..., None]:
        # Whatever else a renderer is asked to do is nothing here.
        return lambda *args, **kwargs: None


class Asking(Asker):
    def __init__(self) -> None:
        self.shown: list[list[Entry]] = []
        self.heads: list[str] = []
        self.picks: list[int | None] = []
        self.typed: list[str | None] = []
        self.asked: list[dict[str, Any]] = []
        self.answers: list[dict[str, Any] | None] = []

    def choose(self, entries: Any, head: str = "") -> int | None:
        self.shown.append(list(entries))
        self.heads.append(head)
        return self.picks.pop(0) if self.picks else None

    def ask_text(
        self, head: str, *, secret: bool = False, default: str | None = None
    ) -> str | None:
        self.heads.append(head)
        return self.typed.pop(0) if self.typed else None

    def ask_user(self, event: Any) -> dict[str, Any] | None:
        self.asked.append(dict(event))
        return self.answers.pop(0) if self.answers else None

    def rows(self, which: int = -1) -> list[list[str]]:
        return [[text for _, text in entry.cells] for entry in self.shown[which]]

    def styles(self, which: int = -1) -> list[list[str]]:
        return [[style for style, _ in entry.cells] for entry in self.shown[which]]


def job(identifier: str, agent: str, task: str, state: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": identifier,
        "agent": agent,
        "task": task,
        "state": state,
        "result": None,
        "question": None,
        "created_at": "2026-10-15T10:00:00+00:00",
        "updated_at": "2026-10-15T10:03:05+00:00",
        **fields,
    }


@pytest.fixture
def tool(
    stub: StubService, wire: Callable[[httpx.Client], Context], stub_http: httpx.Client
) -> Context:
    stub.models = [model("local", "Local Model")]
    stub.jobs = {
        "job-a": job("job-a", "writer", "Draft the letter", "fertig", result="The letter is done."),
        "job-b": job("job-b", "researcher", "Read the\nreport", "laeuft"),
        "job-c": job(
            "job-c", "researcher", "Pick a colour", "wartet",
            question={"aufruf_id": "q-1", "frage": "Which colour?", "optionen": ["red", "blue"]},
        ),
    }
    stub.job_steps = {
        "job-a": [
            {"nummer": 1, "typ": "reasoning", "inhalt": "Let me think."},
            {"nummer": 2, "typ": "text", "inhalt": "I will write it."},
            {"nummer": 3, "typ": "werkzeug", "inhalt": "write_file …"},
            {"nummer": 4, "typ": "tool_call", "inhalt": json.dumps({"name": "write_file", "aufruf_id": "c1"})},
            {"nummer": 5, "typ": "tool_result", "inhalt": json.dumps({"name": "write_file", "aufruf_id": "c1"})},
            {"nummer": 6, "typ": "kontext", "inhalt": json.dumps({"tokens": 5})},
            {"nummer": 7, "typ": "status", "inhalt": "x"},
            {"nummer": 8, "typ": "ende", "inhalt": "fertig"},
        ],
        "job-b": [{"nummer": 1, "typ": "text", "inhalt": "Reading."}],
        "job-c": [],
    }
    context = wire(stub_http)
    context.asker = Asking()
    context.renderer = Recording()  # type: ignore[assignment]
    context.screen = RecordingScreen(context)
    context.commands = commands.build_commands(context)
    return context


def actions(stub: StubService) -> list[tuple[str, str]]:
    return [(what, which) for what, which, _ in stub.job_actions]


# --- The list --------------------------------------------------------------------------------


def test_the_list_has_new_task_on_top_then_waiting_then_running_then_the_rest(tool):
    tool.commands.run("/agents")
    rows = tool.asker.rows()
    assert rows[0] == [texts().t("jobs.starten")]
    assert [row[0] for row in rows[1:]] == ["researcher", "researcher", "writer"]
    # The waiting one stands before the running one.
    assert rows[1][1] == texts().t("jobs.zustand.wartet")
    assert rows[2][1] == texts().t("jobs.zustand.laeuft")
    assert rows[3][1] == texts().t("jobs.zustand.fertig")


def test_a_task_stands_in_one_line_with_its_state_in_its_colour_and_its_time(tool):
    tool.commands.run("/agents")
    rows, styles = tool.asker.rows(), tool.asker.styles()
    assert rows[2][2] == "Read the report"
    assert styles[1][1] == "yellow" and styles[2][1] == "blue" and styles[3][1] == "green"
    # Finished: from its making to its last change; waiting: no time.
    assert rows[3][3] == "3:05"
    assert rows[1][3] == ""


# --- Starting ---------------------------------------------------------------------------------


def test_new_task_asks_for_the_agent_then_the_words_and_starts_it(tool, stub):
    tool.asker.picks = [0, 1]
    tool.asker.typed = ["Write the summary"]
    tool.commands.run("/agents")
    assert tool.asker.rows(1) == [["researcher"], ["writer"]]
    assert tool.asker.heads[1] == texts().t("jobs.agent_waehlen")
    assert stub.job_actions[0][0] == "start"
    assert stub.job_actions[0][2] == {"agent": "writer", "task": "Write the summary"}
    assert tool.renderer.notices and "writer" in tool.renderer.notices[0]


def test_run_with_name_and_words_starts_it_at_once(tool, stub):
    tool.commands.run("/agents run researcher summarize the open issues")
    assert stub.job_actions[0][2] == {"agent": "researcher", "task": "summarize the open issues"}
    assert tool.asker.shown == []


def test_run_without_the_words_asks_for_them(tool, stub):
    tool.asker.typed = ["Look it up"]
    tool.commands.run("/agents run researcher")
    assert stub.job_actions[0][2] == {"agent": "researcher", "task": "Look it up"}
    assert tool.asker.heads == [texts().t("jobs.aufgabe_platzhalter")]


def test_run_without_a_name_opens_the_agent_selection(tool, stub):
    tool.asker.picks = [None]
    tool.commands.run("/agents run")
    assert tool.asker.heads == [texts().t("jobs.agent_waehlen")]
    assert stub.job_actions == []


def test_a_name_the_service_does_not_know_shows_its_sentence_and_starts_nothing(tool, stub):
    tool.commands.run("/agents run gibtsnicht do it")
    assert tool.renderer.errors and "researcher, writer" in tool.renderer.errors[0]
    assert stub.job_actions == []


def test_without_agents_the_selection_says_so(tool, stub):
    stub.agents = []
    tool.asker.picks = [0]
    tool.commands.run("/agents")
    assert tool.renderer.notices == [texts().t("jobs.keine_agenten")]
    assert stub.job_actions == []


def test_another_word_is_said_as_unknown(tool, stub):
    tool.commands.run("/agents foo")
    assert tool.renderer.errors == [texts().t("cli.unknown_choice", name="foo")]
    assert stub.job_actions == []


# --- One task -----------------------------------------------------------------------------------


def test_a_finished_task_shows_its_log_in_the_form_of_the_chat_and_its_report(tool, stub):
    tool.asker.picks = [3, None]
    tool.commands.run("/agents")
    said = tool.renderer.said
    assert said[0] == "reasoning:Let me think."
    assert "content:I will write it." in said
    assert "call:write_file" in said and "result:write_file" in said
    assert said.index("call:write_file") < said.index("result:write_file")
    assert "content:\n\nThe letter is done." in said
    assert said[-1] == "done"
    # What stands behind a click in the window is not written.
    assert not [line for line in said if "kontext" in line or "ende" in line]


def test_a_finished_task_offers_delete_and_no_cancel(tool, stub):
    tool.asker.picks = [3, None]
    tool.commands.run("/agents")
    assert tool.asker.rows(-1) == [[texts().t("jobs.loeschen")]]


def test_a_running_task_offers_cancel_and_cancel_sends_it(tool, stub):
    tool.asker.picks = [2, 0]
    tool.commands.run("/agents")
    assert tool.asker.rows(-1) == [[texts().t("jobs.abbrechen")], [texts().t("jobs.loeschen")]]
    assert actions(stub) == [("cancel", "job-b")]


def test_delete_asks_first_and_deletes_after_yes(tool, stub):
    tool.asker.picks = [3, 0, 0]
    tool.commands.run("/agents")
    assert tool.asker.heads[-1] == texts().t("jobs.loeschen_frage")
    assert tool.asker.rows(-1) == [[texts().t("app.ja")], [texts().t("app.nein")]]
    assert actions(stub) == [("delete", "job-a")]
    assert tool.renderer.notices == [texts().t("jobs.geloescht")]


def test_no_at_the_question_deletes_nothing(tool, stub):
    tool.asker.picks = [3, 0, 1]
    tool.commands.run("/agents")
    assert actions(stub) == []
    assert tool.renderer.notices == []


def test_a_waiting_task_puts_its_question_and_sends_the_answer(tool, stub):
    tool.asker.picks = [1, None]
    tool.asker.answers = [{"antwort": "blue"}]
    tool.commands.run("/agents")
    assert tool.asker.asked[0]["frage"] == "Which colour?"
    assert tool.asker.asked[0]["optionen"] == ["red", "blue"]
    assert stub.job_actions[0][0] == "answer"
    assert stub.job_actions[0][2] == {"antwort": "blue"}


def test_leaving_the_question_sends_nothing(tool, stub):
    tool.asker.picks = [1, None]
    tool.asker.answers = [{"antwort": ""}]
    tool.commands.run("/agents")
    assert actions(stub) == []


def test_closing_the_selection_sends_nothing(tool, stub):
    tool.asker.picks = [None]
    tool.commands.run("/agents")
    assert actions(stub) == []


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


def test_exe_agents_without_a_terminal_says_what_to_give(stub, tmp_path, monkeypatch, capsys):
    stub.models = [model("local", "Local Model")]
    assert run_outside(stub, tmp_path, monkeypatch, "agents", terminal=False) == 2
    assert capsys.readouterr().err.strip() == texts().t("cli.needs_terminal", program="exe")


def test_exe_agents_run_from_outside_starts_a_task_and_says_its_line(
    stub, tmp_path, monkeypatch, capsys
):
    stub.models = [model("local", "Local Model")]
    code = run_outside(stub, tmp_path, monkeypatch, "agents", "run", "writer", "x y", terminal=False)
    assert code == 0
    assert stub.job_actions[0][2] == {"agent": "writer", "task": "x y"}
    assert "writer" in capsys.readouterr().out
