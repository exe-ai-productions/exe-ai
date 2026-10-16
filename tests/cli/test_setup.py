"""``/setup`` and ``exe setup``: the four steps one after the other, the model
step alone, and the question at the start when nothing is set up yet. The
service is the stand-in; nothing is drawn."""

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

from cli import commands, outside, setup_steps
from cli.interfaces import Asker, Context, Entry
from cli.main import main
from cli.texts import Texts
from tests.cli.conftest import RecordingRenderer, RecordingScreen
from tests.cli.stub_service import StubService, model

KEY = "sk-not-a-real-key-123"


def texts() -> Texts:
    return Texts("en")


class Asking(Asker):
    """Keeps every selection and every line of text asked, and answers with
    what a test names — in the order they come."""

    def __init__(self) -> None:
        self.shown: list[list[Entry]] = []
        self.heads: list[str] = []
        self.picks: list[int | None] = []
        self.typed: list[str | None] = []
        self.questions: list[tuple[str, bool, str | None]] = []

    def choose(self, entries: Any, head: str = "") -> int | None:
        self.shown.append(list(entries))
        self.heads.append(head)
        return self.picks.pop(0) if self.picks else None

    def ask_text(
        self, head: str, *, secret: bool = False, default: str | None = None
    ) -> str | None:
        self.questions.append((head, secret, default))
        return self.typed.pop(0) if self.typed else None

    def rows(self, which: int = -1) -> list[list[str]]:
        return [[text for _, text in entry.cells] for entry in self.shown[which]]


class Remarking(RecordingRenderer):
    def __init__(self) -> None:
        super().__init__()
        self.remarks: list[str] = []

    def remark(self, text: str) -> None:
        self.remarks.append(text)


@pytest.fixture
def tool(stub: StubService, wire: Callable[[httpx.Client], Context], stub_http: httpx.Client) -> Context:
    stub.runner_files = [{"name": "gemma.gguf", "groesse_gb": 8.1}]
    context = wire(stub_http)
    context.asker = Asking()
    context.renderer = Remarking()
    context.screen = RecordingScreen(context)
    context.commands = commands.build_commands(context)
    return context


def name_setting(stub: StubService) -> Any:
    return stub.settings.get("global", {}).get("anrede")


# --- The four steps --------------------------------------------------------------------


def test_setup_goes_through_the_four_steps_in_order_with_their_counters(tool, stub, monkeypatch):
    # Language: English again; theme: closed; name: typed; model: closed.
    stub.system_name = "Sam"
    monkeypatch.setattr("cli.themes.WINDOW_VARIABLE", "EXE_NOT_SET_IN_THIS_TEST")
    tool.asker.picks = [1, None, None]
    tool.asker.typed = ["Alex"]
    tool.commands.run("/setup")
    t = texts()
    assert tool.renderer.remarks == [
        t.t("erststart.titel"),
        f"1/4 · {t.t('erststart.sprache')}",
        f"2/4 · {t.t('cli.theme_title')}",
        f"3/4 · {t.t('erststart.anrede')}",
        f"4/4 · {t.t('modell.titel')}",
    ]
    assert tool.renderer.notices[-1] == t.t("erststart.bereit")
    assert name_setting(stub) == {"name": "Alex"}


def test_the_name_step_starts_out_with_the_name_kept_and_writes_only_its_field(tool, stub):
    stub.settings = {"global": {"anrede": {"name": "Kim", "an": False, "erststart": True}}}
    stub.system_name = "Sam"
    tool.asker.typed = ["Alex"]
    tool.commands.run("/setup")
    head, secret, default = tool.asker.questions[0]
    assert head == f"{texts().t('erststart.anrede')}\n{texts().t('erststart.anrede_unter')}"
    assert (secret, default) == (False, "Kim")
    # The fields the setup does not own stay as they were.
    assert name_setting(stub) == {"name": "Alex", "an": False, "erststart": True}


def test_without_a_kept_name_the_suggestion_of_the_system_is_the_value_that_stands(tool, stub):
    stub.system_name = "Sam"
    tool.commands.run("/setup")
    assert tool.asker.questions[0][2] == "Sam"


def test_enter_on_the_name_keeps_what_stands_and_writes_nothing(tool, stub):
    stub.settings = {"global": {"anrede": {"name": "Kim", "an": True, "erststart": True}}}
    # What the field answers where nothing is typed: the value that stands.
    tool.asker.typed = ["Kim"]
    tool.commands.run("/setup")
    assert name_setting(stub) == {"name": "Kim", "an": True, "erststart": True}


def test_closing_the_name_step_writes_nothing_and_goes_on(tool, stub):
    stub.system_name = "Sam"
    tool.commands.run("/setup")
    assert name_setting(stub) is None
    assert tool.renderer.remarks[-1] == f"4/4 · {texts().t('modell.titel')}"


def test_the_model_step_has_add_provider_and_download_above_the_models(tool):
    tool.commands.run("/setup model")
    assert tool.asker.rows(-1)[:2] == [
        [texts().t("modell.anbieter_hinzufuegen")],
        [texts().t("cli.cmd_download").split("\n", 1)[0]],
    ]
    # The models the service lists come next, then the files of the folder.
    assert [row[0] for row in tool.asker.rows(-1)[2:]] == ["Local Model", "gemma.gguf"]


def test_setup_model_alone_shows_only_the_model_step(tool, stub):
    tool.commands.run("/setup model")
    assert tool.renderer.remarks == []
    assert len(tool.asker.shown) == 1
    assert tool.asker.questions == []


def test_a_model_picked_in_the_step_is_chosen_the_way_model_chooses_it(tool, stub):
    stub.runner_files = [{"name": "gemma.gguf", "groesse_gb": 8.1}]
    stub.models = [model("local", "Local Model")]
    tool.asker.picks = [2]
    tool.commands.run("/setup model")
    assert tool.session.endpoint_id == "local"
    assert tool.renderer.notices == [texts().t("cli.modell_gewaehlt", name="Local Model")]


def test_add_provider_in_the_step_runs_the_provider_command(tool, stub):
    stub.models = []
    tool.asker.picks = [0, 0]
    tool.asker.typed = [KEY]
    tool.commands.run("/setup model")
    assert stub.provider_requests[0][1]["art"] == "anthropic"
    assert tool.renderer.notices == [texts().t("modell.anbieter_da")]


def test_download_in_the_step_asks_what_to_search(tool, stub):
    tool.asker.picks = [1]
    tool.commands.run("/setup model")
    assert [question[0] for question in tool.asker.questions] == [texts().t("cli.download_ask")]


def test_a_word_that_is_no_step_is_said_and_nothing_is_asked(tool):
    tool.commands.run("/setup language")
    assert tool.renderer.errors == [texts().t("cli.unknown_choice", name="language")]
    assert tool.asker.shown == [] and tool.asker.questions == []


def test_closing_the_model_step_writes_nothing(tool, stub):
    tool.commands.run("/setup model")
    assert stub.provider_requests == []
    assert tool.renderer.notices == []


# --- At the start --------------------------------------------------------------------------


@pytest.fixture
def bare(stub: StubService, wire: Callable[[httpx.Client], Context], stub_http: httpx.Client) -> Context:
    """A service nothing is set up on: no model answers, no provider is
    entered and the model folder is empty."""
    stub.models = []
    return wire(stub_http)


def test_nothing_set_up_is_needed(bare):
    assert setup_steps.needed(bare) is True


def test_a_model_that_answers_needs_no_setup(stub, wire, stub_http):
    context = wire(stub_http)
    assert context.session.models
    assert setup_steps.needed(context) is False


def test_a_file_in_the_model_folder_needs_no_setup(stub, bare):
    stub.runner_files = [{"name": "gemma.gguf", "groesse_gb": 8.1}]
    assert setup_steps.needed(bare) is False


def test_a_provider_that_does_not_answer_needs_no_setup(stub, bare):
    entry = model("far", "Far Model")
    entry.update({"anbieter": "far", "group": "cloud", "erreichbar": False})
    stub.models = [entry]
    assert setup_steps.needed(bare) is False


def test_an_entry_of_this_machine_that_does_not_answer_is_no_setup(stub, bare):
    entry = model("mine", "My Model")
    entry["erreichbar"] = False
    stub.models = [entry]
    assert setup_steps.needed(bare) is True


def test_yes_to_the_question_at_the_start_runs_the_steps(bare):
    bare.asker = Asking()
    bare.renderer = Remarking()
    bare.screen = RecordingScreen(bare)
    bare.commands = commands.build_commands(bare)
    bare.asker.picks = [0]
    setup_steps.ask_first_start(bare)
    assert bare.asker.heads[0] == texts().t("cli.setup_ask")
    assert [text for _, text in bare.asker.shown[0][0].cells] == [texts().t("app.ja")]
    assert bare.renderer.remarks[0] == texts().t("erststart.titel")


def test_no_to_the_question_at_the_start_leaves_the_chat_without_a_model(bare, stub):
    bare.asker = Asking()
    bare.renderer = Remarking()
    bare.screen = RecordingScreen(bare)
    bare.commands = commands.build_commands(bare)
    bare.asker.picks = [1]
    setup_steps.ask_first_start(bare)
    assert bare.renderer.remarks == []
    assert stub.provider_requests == []


# --- From outside and at the start of the program -------------------------------------


def run_program(
    stub: StubService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *words: str,
    terminal: bool = False, typed: str = "",
) -> int:
    monkeypatch.setattr(outside, "has_terminal", lambda: terminal)
    with create_pipe_input() as pipe:
        pipe.send_text(typed)
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


def test_exe_setup_without_a_terminal_says_what_to_give(stub, tmp_path, monkeypatch, capsys):
    code = run_program(stub, tmp_path, monkeypatch, "setup")
    assert code == 2
    assert capsys.readouterr().err.strip() == texts().t("cli.needs_terminal", program="exe")


def test_exe_setup_model_from_outside_shows_the_model_step_only(
    stub, tmp_path, monkeypatch, capsys
):
    stub.runner_files = [{"name": "gemma.gguf", "groesse_gb": 8.1}]
    seen: list[list[Entry]] = []

    def choose(self: Any, entries: Any, head: str = "") -> int | None:
        seen.append(list(entries))
        return None

    monkeypatch.setattr(outside.OutsideAsker, "choose", choose)
    code = run_program(stub, tmp_path, monkeypatch, "setup", "model", terminal=True)
    assert code == 0
    assert len(seen) == 1
    assert [text for _, text in seen[0][0].cells] == [texts().t("modell.anbieter_hinzufuegen")]
    assert capsys.readouterr().out == ""


def test_the_start_without_a_terminal_and_without_a_model_says_how_and_ends_with_two(
    stub, tmp_path, monkeypatch, capsys
):
    stub.models = []
    code = run_program(stub, tmp_path, monkeypatch)
    assert code == 2
    assert capsys.readouterr().err.strip() == texts().t("cli.setup_hint")
    assert stub.provider_requests == []


def test_the_start_with_a_model_asks_nothing_and_needs_no_terminal(
    stub, tmp_path, monkeypatch, capsys
):
    code = run_program(stub, tmp_path, monkeypatch, typed="/quit\r")
    assert code == 0
    assert texts().t("cli.setup_hint") not in capsys.readouterr().err


# --- The value that stands, from outside ------------------------------------------------


@pytest.fixture
def line_asker(monkeypatch: pytest.MonkeyPatch) -> tuple[outside.OutsideAsker, list[str]]:
    """The asker of a command run from outside, at a terminal whose line is
    typed by the test; the prompts it wrote are kept."""
    monkeypatch.setattr(outside, "has_terminal", lambda: True)
    prompts: list[str] = []
    typed: list[str] = []

    def line(prompt: str) -> str:
        prompts.append(prompt)
        return typed.pop(0) if typed else ""

    monkeypatch.setattr(outside, "input_line", line)
    context = Context(client=None, texts=Texts("en"))  # type: ignore[arg-type]
    asker = outside.OutsideAsker(context)
    asker.typed = typed  # type: ignore[attr-defined]
    return asker, prompts


def test_the_value_that_stands_is_written_in_brackets_and_nothing_typed_takes_it(line_asker):
    asker, prompts = line_asker
    assert asker.ask_text("Preferred name", default="Kim") == "Kim"
    assert prompts == ["Preferred name [Kim] "]


def test_what_is_typed_replaces_the_value_that_stands(line_asker):
    asker, _ = line_asker
    asker.typed.append(" Alex ")  # type: ignore[attr-defined]
    assert asker.ask_text("Preferred name", default="Kim") == "Alex"


def test_an_empty_value_that_stands_answers_with_nothing_typed_as_an_empty_line(line_asker):
    asker, prompts = line_asker
    assert asker.ask_text("Context size", default="") == ""
    assert prompts == ["Context size "]


def test_without_a_value_that_stands_nothing_typed_is_no_answer(line_asker):
    asker, _ = line_asker
    assert asker.ask_text("Search for a model:") is None

