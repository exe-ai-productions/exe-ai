"""``/download`` and ``exe download``: search a model, choose a file, fetch it,
cancel it, set and remove the token — and what stands in the lines while it
goes. The service is the stand-in; a fetch goes on beside the chat, and from
outside the command waits for its end."""

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

from cli import commands, glyphs, outside, servers
from cli.client import ServiceError
from cli.interfaces import Asker, Context, Entry
from cli.main import main
from cli.texts import Texts
from tests.cli.conftest import RecordingRenderer, RecordingScreen
from tests.cli.stub_service import StubService, eventually

TOKEN = "hf_not_a_real_value_123"
STATE_RUNNING = {"datei": "a.gguf", "geladen": 500_000_000, "gesamt": 2_000_000_000,
                 "anteil": 0.25, "fertig": False, "fehler": None}
STATE_DONE = {"datei": "a.gguf", "geladen": 2_000_000_000, "gesamt": 2_000_000_000,
              "anteil": 1.0, "fertig": True, "fehler": None}
HITS = [
    {"id": "acme/alpha-GGUF", "name": "alpha-GGUF", "anbieter": "acme", "ladungen": 12400, "beliebt": 3},
    {"id": "acme/beta-GGUF", "name": "beta-GGUF", "anbieter": "acme", "ladungen": 870, "beliebt": 1},
]
FILE_A = {"datei": "a.gguf", "groesse_gb": 1.2, "local_name": "a.gguf", "da": False,
          "collision": False, "teile": 1}
FILE_B = {"datei": "sub/b.gguf", "groesse_gb": 4.7, "local_name": "b.gguf", "da": True,
          "collision": False, "teile": 3}
VISION = {"datei": "mmproj-F16.gguf", "groesse_gb": 0.9}


def texts() -> Texts:
    return Texts("en")


class Asking(Asker):
    """Stands in for the selection and the line of text: keeps what it was
    shown and answers with what a test names."""

    def __init__(self) -> None:
        self.shown: list[list[Entry]] = []
        self.picks: list[int | None] = []
        self.heads: list[str] = []
        self.typed: str | None = None
        self.questions: list[tuple[str, bool]] = []

    def choose(self, entries: Any, head: str = "") -> int | None:
        self.shown.append(list(entries))
        self.heads.append(head)
        return self.picks.pop(0) if self.picks else None

    def ask_text(self, head: str, *, secret: bool = False) -> str | None:
        self.questions.append((head, secret))
        return self.typed

    def rows(self, which: int = -1) -> list[list[str]]:
        return [[text for _, text in entry.cells] for entry in self.shown[which]]


class Watching(RecordingScreen):
    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.activities: list[Any] = []

    def set_activity(self, text: Any) -> None:
        self.activities.append(text)


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(servers, "POLL_SECONDS", 0.01)


@pytest.fixture
def tool(stub: StubService, wire: Callable[[httpx.Client], Context], stub_http: httpx.Client) -> Context:
    stub.search_hits = [dict(hit) for hit in HITS]
    stub.repository_listing = {"dateien": [dict(FILE_A), dict(FILE_B)], "mmproj": dict(VISION)}
    context = wire(stub_http)
    context.asker = Asking()
    context.screen = Watching(context)
    context.renderer = RecordingRenderer()
    context.commands = commands.build_commands(context)
    # The fetch waits where the test stands, so what it did can be read.
    context.blocking = True
    return context


def downloaded(stub: StubService) -> list[tuple[str, str | None, str | None]]:
    return [(post["datei"], post.get("ziel"), post.get("rolle")) for post in stub.download_posts]


# --- Search ----------------------------------------------------------------------------


def test_the_words_are_searched_and_the_hits_stand_with_their_downloads(tool, stub):
    tool.commands.run("/download gemma 3 12b")
    assert stub.searches == [{"q": "gemma 3 12b", "art": "chat"}]
    arrow = glyphs.glyph("download")
    assert tool.asker.rows() == [
        ["acme/alpha-GGUF", f"12k {arrow}"],
        ["acme/beta-GGUF", f"870 {arrow}"],
    ]
    # While the search runs the line above the status line says so.
    assert tool.screen.activities[0] == texts().t("modell.suche_laeuft")


def test_no_hit_is_said_and_no_file_list_is_asked_for(tool, stub):
    stub.search_hits = []
    tool.commands.run("/download nothing")
    assert tool.renderer.notices == [texts().t("modell.keine_treffer")]
    assert stub.file_requests == []
    assert tool.asker.shown == []


def test_without_a_word_the_user_is_asked_for_the_words(tool, stub):
    tool.asker.typed = "  gemma   3 "
    tool.commands.run("/download")
    assert tool.asker.questions == [(texts().t("cli.download_ask"), False)]
    assert stub.searches == [{"q": "gemma 3", "art": "chat"}]


def test_an_empty_answer_to_that_question_searches_nothing(tool, stub):
    tool.asker.typed = None
    tool.commands.run("/download")
    assert stub.searches == []


def test_embedding_or_speech_in_front_names_the_kind_and_is_no_word_of_the_search(tool, stub):
    tool.commands.run("/download embedding nomic")
    tool.commands.run("/download speech whisper small")
    assert stub.searches == [
        {"q": "nomic", "art": "einbettung"},
        {"q": "whisper small", "art": "sprache"},
    ]


def test_the_kind_alone_asks_for_the_words_and_keeps_the_kind(tool, stub):
    tool.asker.typed = "nomic"
    tool.commands.run("/download embedding")
    assert stub.searches == [{"q": "nomic", "art": "einbettung"}]


def test_any_other_first_word_belongs_to_the_search(tool, stub):
    tool.commands.run("/download image models")
    assert stub.searches == [{"q": "image models", "art": "chat"}]


def test_closing_the_hit_list_asks_for_no_files(tool, stub):
    tool.asker.picks = [None]
    tool.commands.run("/download gemma")
    assert stub.file_requests == []


# --- The files ---------------------------------------------------------------------------


def test_the_files_of_a_hit_stand_with_size_parts_vision_and_the_mark_for_a_file_there(tool, stub):
    tool.asker.picks = [0, None]
    tool.commands.run("/download gemma")
    assert stub.file_requests == [{"repo": "acme/alpha-GGUF", "art": "chat"}]
    vision, there = texts().t("modell.augen"), texts().t("katalog.im_ordner")
    assert tool.asker.rows() == [
        ["a.gguf", "1.2 GB", "", vision, ""],
        ["b.gguf", "4.7 GB", texts().t("modell.teile", zahl=3), vision, there],
    ]
    assert stub.download_posts == []


def test_a_repository_without_a_file_says_so(tool, stub):
    stub.repository_listing = {"dateien": [], "mmproj": None}
    tool.asker.picks = [0]
    tool.commands.run("/download gemma")
    assert tool.renderer.notices == [texts().t("modell.keine_dateien")]


# --- Fetching ----------------------------------------------------------------------------


def test_the_file_is_fetched_then_its_vision_module_and_the_end_is_said(tool, stub):
    stub.download_steps = [STATE_RUNNING, STATE_DONE]
    tool.asker.picks = [0, 0]
    tool.commands.run("/download gemma")
    assert stub.download_posts == [
        {"repo": "acme/alpha-GGUF", "datei": "a.gguf", "ziel": None, "gehoert_zu": None,
         "rolle": None, "art": "chat", "unterordner": None},
        {"repo": "acme/alpha-GGUF", "datei": "mmproj-F16.gguf", "ziel": "a-mmproj-F16.gguf",
         "gehoert_zu": "a.gguf", "rolle": "mmproj", "art": "chat", "unterordner": None},
    ]
    assert tool.renderer.notices == [texts().t("cli.download_done", file="a.gguf")]
    assert tool.renderer.errors == []
    # How far it is stood in the line above the status line, with the file
    # and the percentage; it is given back at the end.
    progress = [a for a in tool.screen.activities if isinstance(a, str) and "25 %" in a]
    assert progress and progress[0].startswith("a.gguf")
    assert tool.screen.activities[-1] is None


def test_a_running_answer_keeps_the_line_above_the_status_line(tool, stub):
    tool.session.answering = True
    stub.download_steps = [STATE_RUNNING, STATE_DONE]
    tool.asker.picks = [0, 0]
    tool.commands.run("/download gemma")
    shown = [a for a in tool.screen.activities if isinstance(a, str) and "%" in a]
    assert shown == []
    assert tool.renderer.notices == [texts().t("cli.download_done", file="a.gguf")]


def test_a_file_in_a_sub_folder_of_the_repository_is_kept_under_its_last_segment(tool, stub):
    stub.repository_listing = {
        "dateien": [{**FILE_A, "datei": "deep/path/a.gguf", "local_name": "acme-a.gguf"}],
        "mmproj": None,
    }
    stub.download_steps = [STATE_DONE]
    tool.asker.picks = [0, 0]
    tool.commands.run("/download gemma")
    assert downloaded(stub) == [("deep/path/a.gguf", "acme-a.gguf", None)]
    assert tool.renderer.notices == [texts().t("cli.download_done", file="acme-a.gguf")]


def test_a_file_that_lies_in_the_folder_starts_no_download(tool, stub):
    tool.asker.picks = [0, 1]
    tool.commands.run("/download gemma")
    assert stub.download_posts == []
    assert tool.renderer.notices == []


def test_a_vision_module_that_lies_in_the_folder_is_not_fetched_again(tool, stub):
    stub.runner_files = [{"name": "a-mmproj-F16.gguf", "groesse_gb": 0.9}]
    stub.download_steps = [STATE_DONE]
    tool.asker.picks = [0, 0]
    tool.commands.run("/download gemma")
    assert downloaded(stub) == [("a.gguf", None, None)]


def test_the_refusal_of_the_service_is_raised_with_its_own_sentence(tool, stub):
    stub.download_refusal = (409, "A download is already running.")
    tool.asker.picks = [0, 0]
    with pytest.raises(ServiceError) as raised:
        tool.commands.run("/download gemma")
    assert raised.value.detail == "A download is already running."
    assert stub.download_posts == []


def test_a_failed_fetch_says_the_catalogues_sentence(tool, stub):
    stub.download_steps = [{**STATE_RUNNING, "fehler": "fehlgeschlagen"}]
    tool.asker.picks = [0, 0]
    tool.commands.run("/download gemma")
    assert tool.renderer.errors == [texts().t("bildserver.generator_fehler")]
    assert tool.renderer.notices == []


def test_a_fetch_that_was_cancelled_by_another_says_it_once(tool, stub):
    stub.download_steps = [{**STATE_RUNNING, "fehler": "abgebrochen"}]
    tool.asker.picks = [0, 0]
    tool.commands.run("/download gemma")
    assert tool.renderer.errors == [texts().t("fehler.download_abgebrochen")]


def test_in_the_chat_the_command_returns_and_the_fetch_goes_on_beside_it(tool, stub):
    tool.blocking = False
    stub.download_steps = [STATE_RUNNING, STATE_RUNNING, STATE_DONE]
    tool.asker.picks = [0, 0]
    tool.commands.run("/download gemma")
    # The command is over; what it set going ends in the history.
    eventually(lambda: tool.renderer.notices == [texts().t("cli.download_done", file="a.gguf")])


# --- Stopping ------------------------------------------------------------------------------


def test_stop_asks_the_service_to_end_the_fetch_and_says_so_once(tool, stub):
    stub.download_steps = [STATE_RUNNING]
    tool.commands.run("/download stop")
    assert stub.download_deletes == 1
    assert tool.renderer.errors == [texts().t("fehler.download_abgebrochen")]


def test_stop_without_a_running_fetch_says_so_and_asks_for_no_cancel(tool, stub):
    tool.commands.run("/download stop")
    assert tool.renderer.notices == [texts().t("downloads.leer")]
    assert stub.download_deletes == 0
    stub.download_steps = [STATE_DONE]
    tool.commands.run("/download stop")
    assert stub.download_deletes == 0


def test_the_interrupt_key_from_outside_ends_the_fetch_and_says_so(tool, stub, monkeypatch):
    stub.download_steps = [STATE_RUNNING]
    tool.asker.picks = [0, 0]
    real = tool.client.get
    polls = []

    def interrupted(path: str, **more: Any) -> Any:
        if path == "/runner/download":
            polls.append(path)
            if len(polls) > 1:
                raise KeyboardInterrupt
        return real(path, **more)

    monkeypatch.setattr(tool.client, "get", interrupted)
    tool.commands.run("/download gemma")
    assert stub.download_deletes == 1
    assert tool.renderer.errors == [texts().t("fehler.download_abgebrochen")]


# --- The token ------------------------------------------------------------------------------


def test_the_token_is_asked_hidden_saved_and_stands_in_no_line(tool, stub):
    tool.asker.typed = TOKEN
    tool.commands.run("/download token")
    assert tool.asker.questions == [(texts().t("modell.hf_token"), True)]
    assert stub.token == TOKEN
    assert tool.renderer.notices == [texts().t("cli.token_saved")]
    shown = repr(tool.renderer.notices) + repr(tool.renderer.errors) + repr(tool.screen.printed)
    assert TOKEN not in shown + repr(tool.screen.activities)


def test_an_empty_answer_changes_nothing(tool, stub):
    tool.asker.typed = None
    tool.commands.run("/download token")
    assert stub.token_posts == []
    assert tool.renderer.notices == []


def test_a_token_the_service_refuses_is_said_without_the_token(tool, stub):
    tool.asker.typed = "short"
    with pytest.raises(ServiceError) as raised:
        tool.commands.run("/download token")
    assert "short" not in raised.value.detail


def test_the_token_is_removed_and_said(tool, stub):
    stub.token = TOKEN
    tool.commands.run("/download token remove")
    assert stub.token is None
    assert stub.token_deletes == 1
    assert tool.renderer.notices == [texts().t("cli.token_removed")]
    assert tool.asker.questions == []


# --- From outside ------------------------------------------------------------------------------


def run_outside(stub: StubService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *words: str,
                terminal: bool = False, typed: str = "") -> int:
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


def test_exe_download_stop_from_outside_cancels_and_ends_with_a_failure_code(
    stub, tmp_path, monkeypatch, capsys
):
    stub.download_steps = [STATE_RUNNING]
    code = run_outside(stub, tmp_path, monkeypatch, "download", "stop")
    assert code == 1
    assert stub.download_deletes == 1
    assert capsys.readouterr().err.strip().splitlines()[-1] == texts().t("fehler.download_abgebrochen")


def test_exe_download_stop_without_a_running_fetch_ends_well(stub, tmp_path, monkeypatch, capsys):
    code = run_outside(stub, tmp_path, monkeypatch, "download", "stop")
    assert code == 0
    assert stub.download_deletes == 0
    assert capsys.readouterr().out.strip() == texts().t("downloads.leer")


def test_exe_download_without_words_and_without_a_terminal_says_what_to_give(
    stub, tmp_path, monkeypatch, capsys
):
    code = run_outside(stub, tmp_path, monkeypatch, "download")
    assert code == 2
    assert capsys.readouterr().err.strip() == texts().t("cli.needs_terminal", program="exe")
    assert stub.searches == []


def test_the_progress_of_a_fetch_from_outside_is_written_line_by_line(
    stub, tmp_path, monkeypatch, capsys
):
    stub.search_hits = [dict(HITS[0])]
    stub.repository_listing = {"dateien": [dict(FILE_A)], "mmproj": None}
    stub.download_steps = [STATE_RUNNING, STATE_DONE]
    # Each selection takes its first entry; a selection is a block of its
    # own and takes what the pipe holds, so two cannot be typed in one go.
    monkeypatch.setattr(outside.OutsideAsker, "choose", lambda self, entries, head="": 0)
    code = run_outside(stub, tmp_path, monkeypatch, "download", "gemma", terminal=True)
    shown = capsys.readouterr()
    assert code == 0
    assert "25 %" in shown.err
    assert shown.out.strip().splitlines()[-1] == texts().t("cli.download_done", file="a.gguf")
