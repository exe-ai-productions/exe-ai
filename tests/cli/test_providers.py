"""``/provider`` and ``exe provider``: the list of cloud providers, adding one
with a hidden key, removing one after the window's own question, and the
context size, time limit and capabilities of one. The service is the
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
from cli.client import ServiceError
from cli.interfaces import Asker, Context, Entry
from cli.main import main
from cli.texts import Texts
from tests.cli.conftest import RecordingRenderer, RecordingScreen
from tests.cli.stub_service import StubService, model

KEY = "sk-not-a-real-key-123"


def texts() -> Texts:
    return Texts("en")


def provider(identifier: str, name: str, **fields: Any) -> dict[str, Any]:
    entry = model(f"{identifier}-model", f"{name} model")
    entry.update(
        {
            "anbieter": identifier,
            "anbieter_name": name,
            "group": "cloud",
            "erreichbar": True,
            "schluessel_gesetzt": True,
            "key_goes_with_provider": True,
            **fields,
        }
    )
    return entry


class Asking(Asker):
    """Stands in for the selection and the line of text: keeps what it was
    shown and answers with what a test names."""

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


@pytest.fixture
def tool(stub: StubService, wire: Callable[[httpx.Client], Context], stub_http: httpx.Client) -> Context:
    stub.models = [
        model("local", "Local Model"),
        provider("anthropic", "Anthropic"),
        provider(
            "acme",
            "Acme",
            erreichbar=False,
            schluessel_gesetzt=False,
            key_goes_with_provider=False,
            capabilities={"vision": True},
            timeout_enabled=False,
            kontext_eigen=64000,
        ),
    ]
    context = wire(stub_http)
    context.asker = Asking()
    context.renderer = RecordingRenderer()
    context.screen = RecordingScreen(context)
    context.commands = commands.build_commands(context)
    return context


def requests(stub: StubService) -> list[tuple[str, Any]]:
    return stub.provider_requests


# --- The list ----------------------------------------------------------------------------


def test_the_list_shows_add_on_top_and_each_cloud_provider_with_its_state_and_key(tool):
    tool.commands.run("/provider")
    assert tool.asker.rows() == [
        [texts().t("modell.anbieter_hinzufuegen")],
        [
            "Anthropic",
            texts().t("status.erreichbar"),
            f"{texts().t('modell.schluessel')} {texts().t('modell.schluessel_gesetzt')}",
        ],
        ["Acme", texts().t("status.nicht_erreichbar"), texts().t("modell.schluessel_fehlt")],
    ]


def test_an_entry_of_this_machine_is_no_provider(tool):
    tool.commands.run("/provider")
    assert all("Local Model" not in cells for cells in tool.asker.rows())


def test_a_closed_list_sends_nothing(tool, stub):
    tool.commands.run("/provider")
    assert requests(stub) == []


# --- Adding ------------------------------------------------------------------------------


def test_add_anthropic_asks_the_key_hidden_posts_it_and_says_it_is_there(tool, stub):
    stub.models = [model("local", "Local Model")]
    tool.asker.typed = [KEY]
    tool.commands.run("/provider add anthropic")
    assert tool.asker.questions == [(texts().t("modell.schluessel"), True, None)]
    assert requests(stub) == [
        ("add", {"art": "anthropic", "schluessel": KEY, "kennung": None, "url": None})
    ]
    assert tool.renderer.notices == [texts().t("modell.anbieter_da")]


def test_a_provider_that_does_not_answer_is_said_as_saved_but_not_reachable(tool, stub):
    stub.models = [model("local", "Local Model")]
    stub.provider_reachable = False
    tool.asker.typed = [KEY]
    tool.commands.run("/provider add openai")
    assert requests(stub)[0][1]["art"] == "openai"
    assert tool.renderer.notices == [texts().t("modell.anbieter_da_nicht_erreichbar")]


def test_a_custom_provider_asks_name_address_and_key_and_sends_all_three(tool, stub):
    stub.models = [model("local", "Local Model")]
    tool.asker.picks = [2]
    tool.asker.typed = ["acme2", "http://127.0.0.1:9/v1", KEY]
    tool.commands.run("/provider add")
    assert tool.asker.heads[0] == texts().t("modell.anbieter_waehlen")
    assert [text for _, text in tool.asker.shown[0][2].cells] == [texts().t("modell.eigener")]
    assert tool.asker.shown[0][2].note == texts().t("modell.eigener_unter")
    assert [question[:2] for question in tool.asker.questions] == [
        (texts().t("modell.eigener_name"), False),
        (texts().t("modell.eigener_adresse"), False),
        (texts().t("modell.schluessel"), True),
    ]
    assert requests(stub) == [
        (
            "add",
            {"art": "eigen", "schluessel": KEY, "kennung": "acme2", "url": "http://127.0.0.1:9/v1"},
        )
    ]


def test_add_from_the_list_opens_the_choice_of_kind(tool, stub):
    stub.models = [model("local", "Local Model")]
    tool.asker.picks = [0, 0]
    tool.asker.typed = [KEY]
    tool.commands.run("/provider")
    assert tool.asker.heads[1] == texts().t("modell.anbieter_waehlen")
    assert requests(stub)[0][1]["art"] == "anthropic"


def test_the_key_stands_in_no_line_and_not_in_a_refusal_that_repeats_it(tool, stub):
    stub.models = [model("local", "Local Model")]
    tool.asker.typed = ["short"]
    with pytest.raises(ServiceError) as raised:
        tool.commands.run("/provider add anthropic")
    assert "short" not in raised.value.detail
    assert "…" in raised.value.detail
    assert tool.renderer.notices == []


def test_a_word_that_names_no_kind_is_said_and_nothing_is_sent(tool, stub):
    tool.commands.run("/provider add nothing")
    assert tool.renderer.errors == [texts().t("cli.unknown_choice", name="nothing")]
    assert requests(stub) == []
    assert tool.asker.questions == []


@pytest.mark.parametrize("closed_at", [0, 1])
def test_a_question_closed_on_the_way_sends_nothing(tool, stub, closed_at):
    stub.models = [model("local", "Local Model")]
    tool.asker.picks = [2]
    tool.asker.typed = ["acme2", "http://127.0.0.1:9/v1"][:closed_at]
    tool.commands.run("/provider add")
    assert requests(stub) == []


def test_a_key_that_is_closed_sends_nothing(tool, stub):
    stub.models = [model("local", "Local Model")]
    tool.commands.run("/provider add anthropic")
    assert requests(stub) == []
    assert tool.renderer.notices == []


# --- What one provider takes -------------------------------------------------------------


def test_the_selection_of_a_provider_shows_context_time_limit_and_the_three_capabilities(tool):
    tool.asker.picks = [2]
    tool.commands.run("/provider")
    assert tool.asker.heads[1] == "Acme"
    assert tool.asker.rows(1) == [
        [texts().t("modell.kontext_feld"), "64000"],
        [texts().t("modell.zeitgrenze_schalter"), texts().t("status.inaktiv")],
        [texts().t("modell.vision_schalter"), texts().t("status.aktiv")],
        [texts().t("modell.denken_schalter"), texts().t("status.inaktiv")],
        [texts().t("modell.werkzeuge_schalter"), texts().t("status.inaktiv")],
        [texts().t("modell.anbieter_entfernen")],
    ]


def test_a_context_size_that_is_not_set_stands_as_auto(tool):
    tool.asker.picks = [1]
    tool.commands.run("/provider")
    assert tool.asker.rows(1)[0] == [texts().t("modell.kontext_feld"), texts().t("parameter.auto")]


@pytest.mark.parametrize(
    ("row", "route", "body"),
    [
        (1, "acme/timeout", {"timeout_enabled": True}),
        (2, "acme/capabilities", {"vision": False}),
        (3, "acme/capabilities", {"thinking": True}),
        (4, "acme/capabilities", {"tool_calls": True}),
    ],
)
def test_a_switch_is_turned_over_without_a_sentence_and_the_selection_shows_it(
    tool, stub, row, route, body
):
    tool.asker.picks = [2, row, None]
    tool.commands.run("/provider")
    assert requests(stub) == [(route, body)]
    assert tool.renderer.notices == []
    # The selection opened again, with what stands now.
    assert len(tool.asker.shown) == 3


def test_a_number_typed_for_the_context_size_is_sent(tool, stub):
    tool.asker.picks = [2, 0, None]
    tool.asker.typed = ["32000"]
    tool.commands.run("/provider")
    assert tool.asker.questions == [(texts().t("modell.kontext_feld"), False, "")]
    assert requests(stub) == [("acme/context", {"context_tokens": 32000})]


def test_nothing_typed_for_the_context_size_goes_back_to_auto(tool, stub):
    tool.asker.picks = [2, 0, None]
    tool.asker.typed = [""]
    tool.commands.run("/provider")
    assert requests(stub) == [("acme/context", {"context_tokens": None})]


def test_a_context_size_that_is_no_number_is_said_and_not_sent(tool, stub):
    tool.asker.picks = [2, 0, None]
    tool.asker.typed = ["a lot"]
    tool.commands.run("/provider")
    assert tool.renderer.errors == [texts().t("cli.unknown_choice", name="a lot")]
    assert requests(stub) == []


def test_a_context_question_that_is_closed_changes_nothing_and_ends_the_selection(tool, stub):
    tool.asker.picks = [2, 0]
    tool.commands.run("/provider")
    assert requests(stub) == []
    assert len(tool.asker.shown) == 2


# --- Removing ----------------------------------------------------------------------------


def test_remove_in_the_selection_of_a_provider_asks_then_removes_and_says_so(tool, stub):
    # Yes and No are the two entries of the question; Acme's key stays.
    tool.asker.picks = [2, 5, 0]
    tool.commands.run("/provider")
    assert tool.asker.heads[2] == texts().t("modell.anbieter_loeschen_frage", name="Acme")
    assert requests(stub) == [("acme/remove", None)]
    assert tool.renderer.notices == [texts().t("modell.anbieter_entfernt")]


def test_the_question_names_the_key_where_it_goes_with_the_provider(tool, stub):
    tool.asker.picks = [0]
    tool.commands.run("/provider remove anthropic")
    assert tool.asker.heads[0] == texts().t(
        "modell.anbieter_loeschen_frage_mit_schluessel", name="Anthropic"
    )
    assert [text for _, text in tool.asker.shown[0][0].cells] == [texts().t("app.ja")]
    assert requests(stub) == [("anthropic/remove", None)]


def test_no_to_the_question_removes_nothing(tool, stub):
    tool.asker.picks = [1]
    tool.commands.run("/provider remove anthropic")
    assert requests(stub) == []
    assert tool.renderer.notices == []


def test_a_closed_question_removes_nothing(tool, stub):
    tool.commands.run("/provider remove acme")
    assert requests(stub) == []


def test_remove_without_a_word_opens_the_selection_of_the_providers(tool, stub):
    tool.asker.picks = [0, 0]
    tool.commands.run("/provider remove")
    assert tool.asker.rows(0) == [["Anthropic"], ["Acme"]]
    assert requests(stub) == [("anthropic/remove", None)]


def test_remove_of_a_word_that_is_no_provider_is_said(tool, stub):
    tool.commands.run("/provider remove nobody")
    assert tool.renderer.errors == [texts().t("cli.unknown_choice", name="nobody")]
    assert requests(stub) == []


def test_another_word_behind_the_command_is_said(tool, stub):
    tool.commands.run("/provider delete anthropic")
    assert tool.renderer.errors == [texts().t("cli.unknown_choice", name="delete anthropic")]
    assert requests(stub) == []


# --- From outside ------------------------------------------------------------------------


def run_outside(
    stub: StubService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *words: str,
    terminal: bool = False,
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


def test_exe_provider_without_a_terminal_says_what_to_give(stub, tmp_path, monkeypatch, capsys):
    code = run_outside(stub, tmp_path, monkeypatch, "provider")
    assert code == 2
    assert capsys.readouterr().err.strip() == texts().t("cli.needs_terminal", program="exe")
    assert requests(stub) == []


def test_exe_provider_add_anthropic_from_outside_posts_the_key_the_terminal_gave(
    stub, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": KEY)
    code = run_outside(stub, tmp_path, monkeypatch, "provider", "add", "anthropic", terminal=True)
    shown = capsys.readouterr()
    assert code == 0
    assert shown.out.strip() == texts().t("modell.anbieter_da")
    assert KEY not in shown.out + shown.err
    assert requests(stub)[0][1]["art"] == "anthropic"
