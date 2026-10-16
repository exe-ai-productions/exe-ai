"""``/settings``: the storage locations behind the selection, the value set
in one line, and the words that went with ``/set``. The service is the
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
        self.questions: list[tuple[str, str | None]] = []

    def choose(self, entries: Any, head: str = "") -> int | None:
        self.shown.append(list(entries))
        self.heads.append(head)
        return self.picks.pop(0) if self.picks else None

    def ask_text(
        self, head: str, *, secret: bool = False, default: str | None = None
    ) -> str | None:
        self.questions.append((head, default))
        return self.typed.pop(0) if self.typed else None

    def rows(self) -> list[list[str]]:
        return [[text for _, text in entry.cells] for entry in self.shown[-1]]


def place(name: str, path: str) -> dict[str, Any]:
    return {"name": name, "pfad": path, "standard": path, "ist_standard": True, "neustart_noetig": False}


@pytest.fixture
def stored(
    stub: StubService, wire: Callable[[httpx.Client], Context], stub_http: httpx.Client
) -> Context:
    stub.models = [model("local", "Local Model")]
    stub.places = [
        place("images", "/data/images"),
        place("scripts", "/data/scripts"),
        place("agent_dock", "/data/dock"),
        place("models", "/data/models"),
        place("image_models", "/data/image_models"),
        place("embedding_models", "/data/embedding_models"),
        place("speech_models", "/data/speech_models"),
    ]
    context = wire(stub_http)
    context.asker = Asking()
    context.renderer = RecordingRenderer()
    context.screen = RecordingScreen(context)
    context.commands = commands.build_commands(context)
    return context


# The storage locations are the fourth entry of the selection.
STORAGE = 3


def test_the_locations_show_their_word_and_path_and_the_model_folders_stay_out(stored):
    stored.asker.picks = [STORAGE]
    stored.commands.run("/settings")
    assert stored.asker.heads[-1] == texts().t("cli.storage_title")
    assert stored.asker.rows() == [
        [texts().t("bilder.bildordner"), "/data/images"],
        [texts().t("speicherorte.skripte_ordner"), "/data/scripts"],
        [texts().t("docfolder.ordner"), "/data/dock"],
    ]


def test_a_new_path_is_put_and_the_notice_says_the_location_changed(stored, stub):
    stored.asker.picks = [STORAGE, 1, 0]
    stored.asker.typed = ["/tmp/my-scripts"]
    stored.commands.run("/settings")
    # The menu of the location offers the change; the question holds the
    # path of today.
    assert stored.asker.rows() == [[texts().t("speicherorte.aendern")]]
    assert stored.asker.questions == [(texts().t("speicherorte.frage"), "/data/scripts")]
    assert stub.place_actions == [("scripts", {"pfad": "/tmp/my-scripts"})]
    assert stored.renderer.notices == [texts().t("speicherorte.geaendert")]


@pytest.mark.parametrize("typed", [None, "", "  ", "/data/scripts", " /data/scripts "])
def test_esc_an_empty_line_and_the_same_path_change_nothing(stored, stub, typed):
    stored.asker.picks = [STORAGE, 1, 0]
    stored.asker.typed = [typed]
    stored.commands.run("/settings")
    assert stub.place_actions == []
    assert stored.renderer.notices == []


def test_leaving_the_menu_or_the_list_asks_nothing(stored, stub):
    stored.asker.picks = [STORAGE, 0, None]
    stored.commands.run("/settings")
    assert stored.asker.questions == []
    assert stub.place_actions == []
    stored.asker.picks = [STORAGE, None]
    stored.commands.run("/settings")
    assert stub.place_actions == []


def test_a_refused_folder_stands_with_the_sentence_of_the_service(stored, stub):
    stub.refuse_place = "No write permission in this folder"
    stored.asker.picks = [STORAGE, 0, 0]
    stored.asker.typed = ["/root/nowhere"]
    stored.commands.run("/settings")
    assert stored.renderer.errors == ["No write permission in this folder"]
    assert stored.renderer.notices == []


# --- The words that went with /set -------------------------------------------------------------


def test_set_is_no_command_any_more(stored, stub):
    stored.commands.run("/set global.verdichtung_schwelle 70")
    assert stored.renderer.errors == [texts().t("cli.unbekannt", name="set")]
    assert "global" not in stub.settings


def test_the_help_does_not_list_set(stored):
    assert "set" not in stored.commands.names()
    assert "settings" in stored.commands.names()


def test_the_form_in_one_line_names_settings_in_its_example():
    assert "/settings global.verdichtung_schwelle 70" in texts().t("cli.set_form")
    assert "/set global" not in texts().t("cli.set_form")


@pytest.mark.parametrize("line", ["/settings global", "/settings nonsense", "/settings a.b.c.d 1"])
def test_any_other_form_names_the_form_and_sends_nothing(stored, stub, line):
    stored.commands.run(line)
    assert stored.renderer.errors == [texts().t("cli.set_form")]
    assert stub.settings == {}


def test_a_value_in_one_line_is_set_without_a_selection(stored, stub):
    stored.commands.run("/settings global.verdichtung_schwelle 70")
    assert stub.settings["global"]["verdichtung_schwelle"] == 70
    assert stored.asker.shown == []


# --- From outside ---------------------------------------------------------------------------------


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


def test_exe_settings_without_a_terminal_says_what_to_give(stub, tmp_path, monkeypatch, capsys):
    stub.models = [model("local", "Local Model")]
    assert run_outside(stub, tmp_path, monkeypatch, "settings", terminal=False) == 2
    assert capsys.readouterr().err.strip() == texts().t("cli.needs_terminal", program="exe")


def test_exe_settings_with_a_value_sets_it_without_a_terminal(stub, tmp_path, monkeypatch):
    stub.models = [model("local", "Local Model")]
    code = run_outside(
        stub, tmp_path, monkeypatch, "settings", "global.verdichtung_schwelle", "70", terminal=False
    )
    assert code == 0
    assert stub.settings["global"]["verdichtung_schwelle"] == 70


def test_exe_set_is_an_unknown_command(stub, tmp_path, monkeypatch, capsys):
    stub.models = [model("local", "Local Model")]
    assert run_outside(stub, tmp_path, monkeypatch, "set", "global.x", "1", terminal=False) == 2
    assert capsys.readouterr().err.strip() == texts().t(
        "cli.unknown_outside_command", name="set", program="exe"
    )
