"""``/files``: the files of the open chat as a list in the history, and the
folder they lie in under it. Only shown: nothing is opened, nothing is
removed, no chat is created. The service is the stand-in; nothing is
drawn."""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from rich.console import Console

from cli import commands, files
from cli.interfaces import Context
from cli.render import local_time
from cli.texts import Texts
from tests.cli.conftest import RecordingRenderer, RecordingScreen
from tests.cli.stub_service import StubService, model


def texts() -> Texts:
    return Texts("en")


def plain(renderables: list[Any]) -> list[str]:
    """What was handed to the screen, as the lines a person reads."""
    console = Console(file=io.StringIO(), width=160, color_system=None, force_terminal=False)
    for renderable in renderables:
        console.print(renderable)
    return [line.rstrip() for line in console.file.getvalue().splitlines() if line.strip()]  # type: ignore[attr-defined]


def doc(name: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": name, "source": "document", "origin": "user", "name": name, "type": "text/plain",
        "size": 120, "created": "2026-10-14T09:30:00+00:00", "agent": "", "chat_id": "c-1",
        "project_id": None, "path": f"/data/{name}", **fields,
    }


@pytest.fixture
def filed(
    stub: StubService, wire: Callable[[httpx.Client], Context], stub_http: httpx.Client
) -> Context:
    stub.models = [model("local", "Local Model")]
    stub.chats["c-1"] = {"id": "c-1", "title": "A chat", "working_dirs": [], "project_id": None}
    stub.doc_files = [
        doc("notes.md", size=2300),
        doc("report.pdf", origin="agent", agent="writer", size=3_400_000, created="2026-10-15T08:00:00+00:00"),
        doc("elsewhere.txt", chat_id="c-2"),
    ]
    stub.doc_places = {"c-1": "/data/chats/c-1"}
    context = wire(stub_http)
    context.renderer = RecordingRenderer()
    context.screen = RecordingScreen(context)
    context.commands = commands.build_commands(context)
    context.session.chat = dict(stub.chats["c-1"])
    return context


@pytest.mark.parametrize(
    ("size", "shown"),
    [(0, "0 B"), (1023, "1023 B"), (1024, "1 KB"), (2300, "2 KB"), (1_048_575, "1024 KB"),
     (1_048_576, "1.0 MB"), (3_400_000, "3.2 MB"), (None, ""), ("junk", "")],
)
def test_the_size_is_told_the_way_the_window_tells_it(size, shown):
    assert files.size_of(size) == shown


def test_files_lists_the_chats_files_with_origin_size_and_date_and_the_folder_under_them(filed):
    filed.commands.run("/files")
    lines = plain(filed.screen.printed)
    assert len(lines) == 3
    assert lines[0].split() == [
        "notes.md", *texts().t("docfolder.by_you").split(), "2", "KB", *local_time("2026-10-14T09:30:00+00:00").split()
    ]
    assert lines[1].split() == [
        "report.pdf", *texts().t("docfolder.by_agent", agent="writer").split(), "3.2", "MB",
        *local_time("2026-10-15T08:00:00+00:00").split(),
    ]
    assert lines[2] == f"{texts().t('docfolder.ordner')}: /data/chats/c-1"
    assert filed.renderer.notices == [] and filed.renderer.errors == []


def test_only_the_open_chats_files_are_asked_for(filed, stub):
    filed.commands.run("/files")
    assert "elsewhere.txt" not in " ".join(plain(filed.screen.printed))
    assert stub.requests.count("GET /api/v1/doc-folder") == 1
    assert stub.requests.count("GET /api/v1/doc-folder/place") == 1


def test_a_file_of_a_run_without_an_agent_says_the_word_and_no_marker(filed, stub):
    stub.doc_files = [doc("out.txt", origin="cronjob", agent="(reminder)")]
    filed.commands.run("/files")
    row = plain(filed.screen.printed)[0]
    assert texts().t("cronjobs.kind_reminder") in row and "(reminder)" not in row


def test_without_files_the_sentence_for_none_stands_and_the_folder_is_not_asked(filed, stub):
    stub.doc_files = []
    filed.commands.run("/files")
    assert filed.renderer.notices == [texts().t("docfolder.empty")]
    assert filed.screen.printed == []
    assert stub.requests.count("GET /api/v1/doc-folder/place") == 0


def test_a_new_chat_is_asked_nothing_and_none_is_created(filed, stub):
    filed.session.chat = None
    before = len(stub.requests)
    filed.commands.run("/files")
    assert filed.renderer.notices == [texts().t("docfolder.empty")]
    assert stub.requests[before:] == []
    assert "POST /api/v1/chats" not in stub.requests


def test_nothing_is_opened_or_removed_or_created(filed, stub):
    filed.commands.run("/files")
    changing = [request for request in stub.requests if not request.startswith("GET ")]
    assert not [request for request in changing if "/documents/" in request or request.startswith("DELETE")]
    assert "POST /api/v1/chats" not in stub.requests


def test_a_folder_the_service_names_none_for_leaves_the_files_alone(filed, stub):
    stub.doc_places = {}
    filed.commands.run("/files")
    lines = plain(filed.screen.printed)
    assert len(lines) == 2 and filed.renderer.errors == []


def test_a_word_behind_the_command_is_unknown(filed, stub):
    filed.commands.run("/files all")
    assert filed.renderer.errors == [texts().t("cli.unknown_choice", name="all")]
    assert filed.screen.printed == []
