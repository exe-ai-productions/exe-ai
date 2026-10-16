"""``/cron`` and ``exe cron``: the scheduled tasks listed, created field by
field, run by hand, paused, resumed, changed, shown with their last runs
and removed. The service is the stand-in; nothing is drawn."""

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

from cli import commands, cron, outside
from cli.interfaces import Asker, Context, Entry
from cli.main import main
from cli.texts import Texts
from tests.cli.conftest import RecordingScreen
from tests.cli.stub_service import StubService, model

TODAY = "2026-10-15"
KEEP = object()


def texts() -> Texts:
    return Texts("en")


class Recording:
    def __init__(self) -> None:
        self.notices: list[str] = []
        self.errors: list[str] = []
        self.remarks: list[str] = []

    def notice(self, text: str) -> None:
        self.notices.append(text)

    def error(self, text: str) -> None:
        self.errors.append(text)

    def remark(self, text: str) -> None:
        self.remarks.append(text)

    def __getattr__(self, name: str) -> Callable[..., None]:
        return lambda *args, **kwargs: None


class Asking(Asker):
    def __init__(self) -> None:
        self.shown: list[list[Entry]] = []
        self.heads: list[str] = []
        self.picks: list[int | None] = []
        self.typed: list[Any] = []
        self.defaults: list[str | None] = []
        self.checks: list[list[int] | None] = []
        self.checked_in: list[list[int]] = []
        self.checklists: list[tuple[str, list[str]]] = []

    def choose(self, entries: Any, head: str = "") -> int | None:
        self.shown.append(list(entries))
        self.heads.append(head)
        return self.picks.pop(0) if self.picks else None

    def ask_text(
        self, head: str, *, secret: bool = False, default: str | None = None
    ) -> str | None:
        self.heads.append(head)
        self.defaults.append(default)
        if not self.typed:
            return None
        answer = self.typed.pop(0)
        return (default or "") if answer is KEEP else answer

    def check(self, entries: Any, head: str = "", checked: Any = ()) -> list[int] | None:
        listed = list(entries)
        self.checklists.append((head, [entry.cells[0][1] for entry in listed]))
        self.checked_in.append(sorted(checked))
        return self.checks.pop(0) if self.checks else None

    def rows(self, which: int = -1) -> list[list[str]]:
        return [[text for _, text in entry.cells] for entry in self.shown[which]]

    def styles(self, which: int = -1) -> list[list[str]]:
        return [[style for style, _ in entry.cells] for entry in self.shown[which]]


def entry(identifier: str, zeitplan: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": identifier,
        "agent": "writer",
        "task": "Morning mail",
        "zeitplan": zeitplan,
        "aktiv": True,
        "kind": "agent",
        "skript": None,
        "einmalig": False,
        "datum": None,
        "letzter_ausgang": None,
        **fields,
    }


@pytest.fixture
def tool(
    stub: StubService,
    wire: Callable[[httpx.Client], Context],
    stub_http: httpx.Client,
    monkeypatch: pytest.MonkeyPatch,
) -> Context:
    monkeypatch.setattr(cron, "_today", lambda: TODAY)
    stub.models = [model("local", "Local Model")]
    stub.cronjobs = {
        "cron-a": entry("cron-a", "08:00", letzter_ausgang="fertig"),
        "cron-b": entry(
            "cron-b", "30 9 15 * *", agent="(none)", task="Invoice", aktiv=False
        ),
        "cron-c": entry(
            "cron-c", "14:00", task="Release note", einmalig=True, datum="2026-11-01"
        ),
        "cron-d": entry(
            "cron-d", "0 3 * * 1-5", agent="(skript)", task="", kind="script",
            skript="backup.sh", letzter_ausgang="gescheitert",
        ),
        "cron-e": entry(
            "cron-e", "07:30", agent="(reminder)", task="Water the plants", kind="reminder",
            wartet_auf_modell=True,
        ),
    }
    context = wire(stub_http)
    context.asker = Asking()
    context.renderer = Recording()  # type: ignore[assignment]
    context.screen = RecordingScreen(context)
    context.commands = commands.build_commands(context)
    return context


def actions(stub: StubService) -> list[tuple[str, str]]:
    return [(what, which) for what, which, _ in stub.cronjob_actions]


# --- The list ------------------------------------------------------------------------------------


def test_the_list_has_new_cronjob_on_top_then_every_entry_with_its_words(tool):
    tool.commands.run("/cron")
    rows = tool.asker.rows()
    assert rows[0] == [texts().t("cronjobs.neuer_cronjob")]
    assert rows[1] == ["daily", "08:00", "writer", "Morning mail", "Active"]
    assert rows[2] == ["monthly on day 15", "09:30", "No agent", "Invoice", "Inactive"]
    assert rows[3] == ["once on 2026-11-01", "14:00", "writer", "Release note", "Active"]
    assert rows[4] == ["Custom", "0 3 * * 1-5", "Script", "backup.sh", "Active"]
    assert rows[5] == ["daily", "07:30", "Reminder", "Water the plants", "Active"]


def test_the_state_of_a_row_is_coloured_by_how_it_stands(tool):
    tool.commands.run("/cron")
    states = [row[-1] for row in tool.asker.styles()[1:]]
    # On and quiet, off, on, failed last time, waiting for a model.
    assert states == ["blue", "muted", "blue", "red", "yellow"]


def test_an_entry_that_cannot_start_is_red(tool, stub):
    stub.cronjobs["cron-a"]["agent_missing"] = True
    tool.commands.run("/cron")
    assert tool.asker.styles()[1][-1] == "red"


def test_closing_the_list_sends_nothing(tool, stub):
    tool.asker.picks = [None]
    tool.commands.run("/cron")
    assert stub.cronjob_actions == []


# --- Creating ------------------------------------------------------------------------------------


def test_new_cronjob_asks_the_kind_first_and_offers_the_three_kinds(tool, stub):
    tool.asker.picks = [0, None]
    tool.commands.run("/cron")
    assert tool.asker.rows(1) == [["Agent"], ["Script"], ["Reminder"]]
    assert tool.asker.heads[1] == texts().t("cronjobs.field_kind")


def test_add_offers_the_five_repetitions_of_the_mask(tool, stub):
    tool.asker.picks = [2, None]
    tool.asker.typed = ["Call mum"]
    tool.commands.run("/cron add")
    assert tool.asker.rows(1) == [["Once"], ["Daily"], ["Weekly"], ["Monthly"], ["Custom"]]


def test_add_a_daily_reminder(tool, stub):
    tool.asker.picks = [2, 1]
    tool.asker.typed = ["Call mum", "08:00"]
    tool.commands.run("/cron add")
    assert stub.cronjob_actions[0][2] == {
        "task": "Call mum", "reminder": True, "zeitplan": "08:00", "einmalig": False, "datum": None,
    }
    assert tool.renderer.notices == [texts().t("cronjobs.angelegt")]


def test_add_an_agent_task_monthly_with_an_agent_and_a_day(tool, stub):
    # Kind agent, the agent writer (0 is "no agent"), repetition monthly.
    tool.asker.picks = [0, 2, 3]
    tool.asker.typed = ["Write the invoice", "15", "09:30"]
    tool.commands.run("/cron add")
    assert tool.asker.rows(1) == [["No agent"], ["researcher"], ["writer"]]
    assert stub.cronjob_actions[0][2] == {
        "task": "Write the invoice", "agent": "writer", "zeitplan": "30 9 15 * *",
        "einmalig": False, "datum": None,
    }


def test_an_agent_task_without_an_agent_leaves_the_field_out(tool, stub):
    tool.asker.picks = [0, 0, 1]
    tool.asker.typed = ["Sum up", "06:00"]
    tool.commands.run("/cron add")
    assert "agent" not in stub.cronjob_actions[0][2]


def test_add_a_one_time_run_asks_for_the_day_with_today_standing_and_the_time(tool, stub):
    tool.asker.picks = [2, 0]
    tool.asker.typed = ["Pick up the parcel", KEEP, "14:00"]
    tool.commands.run("/cron add")
    assert TODAY in tool.asker.defaults
    assert stub.cronjob_actions[0][2] == {
        "task": "Pick up the parcel", "reminder": True, "zeitplan": "14:00",
        "einmalig": True, "datum": TODAY,
    }


def test_add_a_script_with_its_own_expression(tool, stub):
    tool.asker.picks = [1, 4]
    tool.asker.typed = ["backup.sh", "0 3 * * *"]
    tool.commands.run("/cron add")
    assert stub.cronjob_actions[0][2] == {
        "skript": "backup.sh", "zeitplan": "0 3 * * *", "einmalig": False, "datum": None,
    }


@pytest.mark.parametrize(
    ("picks", "typed"),
    [
        ([None], []),
        ([2], [None]),
        ([2], [""]),
        ([2, None], ["Call mum"]),
        ([2, 1], ["Call mum", None]),
        ([0, 0, 1], ["Sum up", None]),
    ],
)
def test_leaving_any_question_creates_nothing(tool, stub, picks, typed):
    tool.asker.picks = list(picks)
    tool.asker.typed = list(typed)
    tool.commands.run("/cron add")
    assert stub.cronjob_actions == []
    assert tool.renderer.notices == []


def test_a_refusal_of_the_service_shows_its_sentence(tool, stub):
    tool.asker.picks = [2, 4]
    tool.asker.typed = ["Call mum", "not a schedule"]
    stub.cronjobs.clear()

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise cron.ServiceError(422, "Not a schedule.")

    tool.client.post = refuse  # type: ignore[method-assign]
    tool.commands.run("/cron add")
    assert tool.renderer.errors == ["Not a schedule."]


def test_add_a_weekly_reminder_asks_the_days_as_a_checklist_and_then_the_time(tool, stub):
    tool.asker.picks = [2, 2]
    tool.asker.typed = ["Call mum", "09:00"]
    tool.asker.checks = [[0, 2]]
    tool.commands.run("/cron add")
    assert tool.asker.checklists == [("Weekly", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])]
    assert stub.cronjob_actions[0][2] == {
        "task": "Call mum", "reminder": True, "zeitplan": "0 9 * * 1,3", "einmalig": False, "datum": None,
    }


def test_the_day_of_today_is_ticked_when_a_weekly_schedule_is_made(tool, stub):
    # 2026-10-15 is a Thursday.
    tool.asker.picks = [2, 2]
    tool.asker.typed = ["Call mum"]
    tool.commands.run("/cron add")
    assert tool.asker.checked_in == [[3]]


def test_sunday_alone_is_day_zero_of_cron(tool, stub):
    tool.asker.picks = [2, 2]
    tool.asker.typed = ["Rest", "09:00"]
    tool.asker.checks = [[6]]
    tool.commands.run("/cron add")
    assert stub.cronjob_actions[0][2]["zeitplan"] == "0 9 * * 0"


@pytest.mark.parametrize("answer", [[], None])
def test_no_day_ticked_and_leaving_the_checklist_make_nothing(tool, stub, answer):
    tool.asker.picks = [2, 2]
    tool.asker.typed = ["Call mum", "09:00"]
    tool.asker.checks = [answer]
    tool.commands.run("/cron add")
    assert stub.cronjob_actions == []
    assert tool.renderer.notices == []


# --- A line with a number --------------------------------------------------------------------


def test_pause_with_a_number_pauses_that_entry_and_shows_its_row(tool, stub):
    tool.commands.run("/cron pause 2")
    assert actions(stub) == [("pause", "cron-a")]
    assert tool.renderer.notices == ["daily  08:00  writer  Morning mail  Inactive"]


def test_resume_with_a_number_resumes_it(tool, stub):
    tool.commands.run("/cron resume 3")
    assert actions(stub) == [("resume", "cron-b")]
    assert tool.renderer.notices[0].endswith("Active")


def test_run_with_a_number_starts_it_and_says_so(tool, stub):
    tool.commands.run("/cron run 2")
    assert actions(stub) == [("run", "cron-a")]
    assert tool.renderer.notices == [texts().t("cronjobs.gestartet")]


def test_run_says_the_sentence_the_service_gives_when_the_model_is_still_coming_up(tool, stub):
    stub.cronjob_notice = "The model is starting; the run follows by itself."
    tool.commands.run("/cron run 2")
    assert tool.renderer.notices == ["The model is starting; the run follows by itself."]


def test_run_of_a_paused_entry_shows_the_services_refusal(tool, stub):
    tool.commands.run("/cron run 3")
    assert tool.renderer.errors == ["This schedule is paused."]
    assert stub.cronjob_actions == []


def test_remove_asks_first_and_deletes_after_yes(tool, stub):
    tool.asker.picks = [0]
    tool.commands.run("/cron remove 4")
    assert tool.asker.heads[-1] == texts().t("cronjobs.loeschen_frage", aufgabe="Release note")
    assert tool.asker.rows(-1) == [["Yes"], ["No"]]
    assert actions(stub) == [("delete", "cron-c")]
    assert tool.renderer.notices == [texts().t("cronjobs.geloescht")]


def test_no_at_the_question_deletes_nothing(tool, stub):
    tool.asker.picks = [1]
    tool.commands.run("/cron remove 4")
    assert stub.cronjob_actions == []
    assert tool.renderer.notices == []


def test_a_word_without_a_number_opens_the_list(tool, stub):
    tool.asker.picks = [None]
    tool.commands.run("/cron pause")
    assert len(tool.asker.shown) == 1 and tool.asker.rows()[0] == ["New cronjob"]
    assert stub.cronjob_actions == []


@pytest.mark.parametrize(
    "line", ["/cron run 1", "/cron pause 1", "/cron pause 7", "/cron pause x", "/cron run 0"]
)
def test_a_number_that_is_no_cronjob_is_said_as_unknown(tool, stub, line):
    tool.commands.run(line)
    assert tool.renderer.errors == [texts().t("cli.unknown_choice", name=line[len("/cron "):])]
    assert stub.cronjob_actions == []


def test_another_word_is_said_as_unknown(tool, stub):
    tool.commands.run("/cron foo")
    assert tool.renderer.errors == [texts().t("cli.unknown_choice", name="foo")]
    assert stub.cronjob_actions == []


# --- One entry ---------------------------------------------------------------------------------


def test_an_active_entry_offers_run_pause_change_runs_and_remove(tool, stub):
    tool.asker.picks = [1, None]
    tool.commands.run("/cron")
    assert tool.asker.rows(-1) == [
        ["Run now"], ["Pause"], ["Change schedule"], ["Recent runs"], ["Remove"],
    ]


def test_a_paused_entry_offers_resume_and_no_run(tool, stub):
    tool.asker.picks = [2, 0]
    tool.commands.run("/cron")
    assert tool.asker.rows(-1) == [
        ["Resume"], ["Change schedule"], ["Recent runs"], ["Remove"],
    ]
    assert actions(stub) == [("resume", "cron-b")]


def test_pause_from_the_menu_pauses_it(tool, stub):
    tool.asker.picks = [1, 1]
    tool.commands.run("/cron")
    assert actions(stub) == [("pause", "cron-a")]


def test_change_without_a_change_sends_nothing(tool, stub):
    # Entry 1, "Change schedule", the agent selection and the repetition
    # closed (what stands stays), the task and the time kept.
    tool.asker.picks = [1, 2, None, None]
    tool.asker.typed = [KEEP, KEEP]
    tool.commands.run("/cron")
    assert stub.cronjob_actions == []


def test_change_sends_only_what_changed(tool, stub):
    # Entry 1, "Change schedule", agent writer stays in use (index 2), the
    # repetition stays daily (index 1), the time is changed.
    tool.asker.picks = [1, 2, 2, 1]
    tool.asker.typed = [KEEP, "09:15"]
    tool.commands.run("/cron")
    assert stub.cronjob_actions == [("change", "cron-a", {"zeitplan": "09:15"})]
    assert tool.renderer.notices == [texts().t("cronjobs.changed")]


def test_change_to_a_one_time_run_sends_the_flag_the_time_and_the_day(tool, stub):
    tool.asker.picks = [1, 2, 2, 0]
    tool.asker.typed = [KEEP, "2026-12-24", "18:00"]
    tool.commands.run("/cron")
    assert stub.cronjob_actions[0][2] == {
        "einmalig": True, "zeitplan": "18:00", "datum": "2026-12-24",
    }


def test_change_shows_the_values_that_stand(tool, stub):
    tool.asker.picks = [3, 2, None, None]
    tool.asker.typed = [KEEP, KEEP]
    tool.commands.run("/cron")
    assert tool.asker.defaults[:2] == ["Release note", "2026-11-01"]


def test_change_from_weekly_to_daily_sends_the_time_as_a_daily_one(tool, stub):
    stub.cronjobs["cron-a"]["zeitplan"] = "0 8 * * 1,3"
    # Entry 1, "Change schedule", the agent stays, the repetition Daily.
    tool.asker.picks = [1, 2, None, 1]
    tool.asker.typed = [KEEP, KEEP]
    tool.commands.run("/cron")
    assert stub.cronjob_actions == [("change", "cron-a", {"zeitplan": "08:00"})]


def test_change_of_a_weekly_schedule_opens_with_its_days_ticked(tool, stub):
    stub.cronjobs["cron-a"]["zeitplan"] = "0 8 * * 1,3"
    tool.asker.picks = [1, 2, None, 2]
    tool.asker.typed = [KEEP, KEEP]
    tool.asker.checks = [[0, 1, 2]]
    tool.commands.run("/cron")
    assert tool.asker.checked_in == [[0, 2]]
    assert stub.cronjob_actions == [("change", "cron-a", {"zeitplan": "0 8 * * 1,2,3"})]


def test_leaving_the_days_of_a_weekly_schedule_keeps_them(tool, stub):
    stub.cronjobs["cron-a"]["zeitplan"] = "0 8 * * 1,3"
    tool.asker.picks = [1, 2, None, 2]
    tool.asker.typed = [KEEP, "10:00"]
    tool.commands.run("/cron")
    assert stub.cronjob_actions == [("change", "cron-a", {"zeitplan": "0 10 * * 1,3"})]


def test_changing_to_weekly_and_leaving_the_days_changes_nothing(tool, stub):
    tool.asker.picks = [1, 2, None, 2]
    tool.asker.typed = [KEEP]
    tool.commands.run("/cron")
    assert stub.cronjob_actions == []


def test_change_does_not_offer_the_kind(tool, stub):
    tool.asker.picks = [1, 2, None, None]
    tool.asker.typed = [KEEP, KEEP]
    tool.commands.run("/cron")
    assert texts().t("cronjobs.field_kind") not in tool.asker.heads


def test_closing_a_question_of_the_change_keeps_the_value_that_stood(tool, stub):
    # The day is changed, the time question is closed: the day goes, the time
    # stays as it was.
    tool.asker.picks = [3, 2, None, None]
    tool.asker.typed = [KEEP, "2026-12-24", None]
    tool.commands.run("/cron")
    assert stub.cronjob_actions == [
        ("change", "cron-c", {"zeitplan": "14:00", "datum": "2026-12-24"})
    ]


def test_a_weekly_schedule_stands_with_its_days_and_its_time(tool, stub):
    stub.cronjobs["cron-a"]["zeitplan"] = "0 8 * * 1,3"
    tool.commands.run("/cron")
    assert tool.asker.rows()[1][:2] == ["Mon, Wed", "08:00"]


def test_the_days_stand_in_the_language_of_the_client(tool, stub):
    stub.cronjobs["cron-a"]["zeitplan"] = "30 7 * * 0,6,5"
    tool.texts = Texts("de")
    tool.commands.run("/cron")
    assert tool.asker.rows()[1][:2] == ["Fr, Sa, So", "07:30"]


def test_an_expression_with_a_range_stays_custom(tool, stub):
    tool.commands.run("/cron")
    assert tool.asker.rows()[4][:2] == ["Custom", "0 3 * * 1-5"]


def test_the_last_runs_stand_newest_first_with_how_many_of_how_many(tool, stub):
    stub.cronjob_runs = [
        {"cronjob_id": "cron-a", "wann": "2026-10-14T08:00:00+00:00", "status": "fertig", "total": 7},
        {"cronjob_id": "cron-x", "wann": "2026-10-14T09:00:00+00:00", "status": "fertig", "total": 1},
        {
            "cronjob_id": "cron-a", "wann": "2026-10-15T08:00:00+00:00", "status": "gescheitert",
            "grund": "skript_fehler", "total": 7,
        },
    ]
    tool.asker.picks = [1, 3]
    tool.commands.run("/cron")
    lines = tool.renderer.remarks
    assert lines[0] == f"{texts().t('cronjobs.letzte_laeufe')} 2/7"
    assert "failed" in lines[1] and "script ended with an error" in lines[1]
    assert "done" in lines[2]


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


def test_exe_cron_without_a_terminal_says_what_to_give(stub, tmp_path, monkeypatch, capsys):
    stub.models = [model("local", "Local Model")]
    assert run_outside(stub, tmp_path, monkeypatch, "cron", terminal=False) == 2
    assert capsys.readouterr().err.strip() == texts().t("cli.needs_terminal", program="exe")


def test_exe_cron_pause_with_a_number_needs_no_terminal(stub, tmp_path, monkeypatch):
    stub.models = [model("local", "Local Model")]
    stub.cronjobs = {"cron-a": entry("cron-a", "08:00")}
    code = run_outside(stub, tmp_path, monkeypatch, "cron", "pause", "2", terminal=False)
    assert code == 0
    assert actions(stub) == [("pause", "cron-a")]
