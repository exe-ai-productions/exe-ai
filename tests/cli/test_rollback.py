"""``/rollback``: the snapshots of the working folder as a list, and putting
files back — what the model wrote, or everything, or one file.

The service behind the client is the stand-in with the real snapshot route
mounted on it and a real folder under it, so what comes back is what the store
really restored. The model's own writes go through the same hook the chat
uses."""

from __future__ import annotations

import asyncio
import io
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import Depends, FastAPI, Response
from rich.console import Console

from app import checkpoint_hooks, checkpoints
from app.api.v1 import checkpoints as checkpoints_route
from app.tools import datei_schreiben
from cli import commands
from cli.interfaces import Context
from cli.texts import Texts
from tests.cli.conftest import RecordingRenderer, RecordingScreen
from tests.cli.stub_service import StubService, model


def texts() -> Texts:
    return Texts("en")


def plain(renderables: list[Any]) -> list[str]:
    console = Console(file=io.StringIO(), width=200, color_system=None, force_terminal=False)
    for renderable in renderables:
        console.print(renderable)
    return [line.rstrip() for line in console.file.getvalue().splitlines() if line.strip()]  # type: ignore[attr-defined]


class _Switch:
    def __init__(self, on: bool) -> None:
        self.on = on

    def zusammengefuehrt(self, key: str, **_: Any) -> dict[str, bool]:
        return {"enabled": self.on}


class SnapshotStub(StubService):
    """The stand-in service, with the snapshot route as the service has it
    and the route that deletes one message."""

    def _build(self) -> FastAPI:
        app = super()._build()
        app.include_router(
            checkpoints_route.router, prefix="/api/v1", dependencies=[Depends(self._check_key)]
        )

        @app.delete("/api/v1/chats/{chat_id}/messages/{message_id}", status_code=204)
        async def delete_message(chat_id: str, message_id: str) -> Response:
            self.messages[chat_id] = [m for m in self.messages[chat_id] if m["id"] != message_id]
            return Response(status_code=204)

        return app


@pytest.fixture
def snapshot_stub(tmp_path: Path) -> Iterator[SnapshotStub]:
    service = SnapshotStub()
    service._app.state.config = SimpleNamespace(
        datenverzeichnis=tmp_path / "data", app=SimpleNamespace(language="en")
    )
    service._app.state.repositories = SimpleNamespace(einstellungen=_Switch(True))
    yield service
    service.close()


@pytest.fixture(autouse=True)
def _fresh_turns():
    checkpoints.forget_turns()
    yield
    checkpoints.forget_turns()


def _message(number: int, role: str) -> dict[str, Any]:
    return {"id": f"m-{number}", "chat_id": "c-1", "role": role, "content": f"text {number}"}


@pytest.fixture
def scene(
    snapshot_stub: SnapshotStub, wire: Callable[[httpx.Client], Context], tmp_path: Path
) -> SimpleNamespace:
    """A chat that shares a folder in which the model changed one file, made
    another and was followed by a person who edited two."""
    work = tmp_path / "work"
    work.mkdir()
    (work / "a.txt").write_text("old", encoding="utf-8")
    (work / "hand.txt").write_text("h0", encoding="utf-8")
    snapshot_stub.models = [model("local", "Local Model")]
    snapshot_stub.chats["c-1"] = {"id": "c-1", "title": "A chat", "working_dirs": [str(work)], "project_id": None}
    snapshot_stub.messages["c-1"] = [_message(1, "user"), _message(2, "assistant"), _message(3, "user"), _message(4, "assistant")]
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    repositories = SimpleNamespace(einstellungen=_Switch(True))
    for name, content in (("a.txt", "model text"), ("made.txt", "created by the model")):
        arguments = {"path": name, "content": content}
        pending = asyncio.run(
            checkpoint_hooks.before(repositories, data, "write_file", arguments, [str(work)], "c-1", "turn-1")
        )
        asyncio.run(datei_schreiben.ausfuehren(arguments, [str(work)], data))
        asyncio.run(checkpoint_hooks.after(pending, ran=True))
    (work / "hand.txt").write_text("h1", encoding="utf-8")
    (work / "made.txt").write_text("edited by hand", encoding="utf-8")
    context = wire(snapshot_stub.http())
    context.renderer = RecordingRenderer()
    context.screen = RecordingScreen(context)
    context.commands = commands.build_commands(context)
    context.session.chat = dict(snapshot_stub.chats["c-1"])
    return SimpleNamespace(ctx=context, work=work, stub=snapshot_stub)


def _text(work: Path, name: str) -> str | None:
    path = work / name
    return path.read_text(encoding="utf-8") if path.exists() else None


def test_the_list_shows_each_snapshot_with_its_reason_and_the_files_after_it(scene):
    scene.ctx.commands.run("/rollback")
    [row] = plain(scene.ctx.screen.printed)
    assert row.split()[0] == "1"
    assert "write_file a.txt" in row
    # What differs from the snap now, the person's own edits included.
    assert row.endswith(f"{texts().t('cli.rollback_files', count=3)}: a.txt, hand.txt, made.txt")


def test_a_number_puts_back_what_the_model_wrote_and_leaves_the_hand_made_change(scene):
    scene.ctx.commands.run("/rollback 1")
    assert _text(scene.work, "a.txt") == "old"
    assert _text(scene.work, "hand.txt") == "h1"
    assert _text(scene.work, "made.txt") == "edited by hand"
    assert scene.ctx.renderer.notices == [
        texts().t("cli.rollback_done", count=1, names="a.txt"),
        texts().t("cli.rollback_kept", count=2, names="hand.txt, made.txt"),
    ]
    assert len(scene.stub.messages["c-1"]) == 4


def test_all_puts_back_both_and_takes_the_last_question_with_its_answer_out(scene):
    scene.ctx.commands.run("/rollback 1 --all")
    assert _text(scene.work, "a.txt") == "old"
    assert _text(scene.work, "hand.txt") == "h0"
    assert scene.ctx.renderer.notices[-1] == texts().t("cli.rollback_turn_removed")
    assert [m["id"] for m in scene.stub.messages["c-1"]] == ["m-1", "m-2"]


def test_a_restore_that_failed_leaves_the_chat_as_it_is(scene, monkeypatch):
    real = scene.ctx.client.post
    monkeypatch.setattr(
        scene.ctx.client, "post",
        lambda path, json=None: {**real(path, json=json), "failed": ["a.txt"]},
    )
    scene.ctx.commands.run("/rollback 1 --all")
    assert scene.ctx.renderer.errors == [texts().t("cli.rollback_failed", names="a.txt")]
    assert len(scene.stub.messages["c-1"]) == 4


def test_a_restore_that_put_nothing_back_leaves_the_chat_as_it_is(scene, monkeypatch):
    monkeypatch.setattr(
        scene.ctx.client, "post",
        lambda path, json=None: {"restored": [], "skipped": [], "failed": []},
    )
    scene.ctx.commands.run("/rollback 1 --all")
    assert scene.ctx.renderer.notices == [texts().t("cli.rollback_nothing")]
    assert len(scene.stub.messages["c-1"]) == 4


def test_a_file_name_puts_back_that_file_alone(scene):
    scene.ctx.commands.run("/rollback 1 a.txt")
    assert _text(scene.work, "a.txt") == "old"
    assert _text(scene.work, "hand.txt") == "h1"
    assert scene.ctx.renderer.notices == [texts().t("cli.rollback_done", count=1, names="a.txt")]
    assert len(scene.stub.messages["c-1"]) == 4


def test_a_number_that_is_no_snapshot_is_unknown_and_nothing_changes(scene):
    scene.ctx.commands.run("/rollback 7")
    assert scene.ctx.renderer.errors == [texts().t("cli.unknown_choice", name="7")]
    assert _text(scene.work, "a.txt") == "model text"


def test_a_file_outside_the_folder_is_refused_in_the_services_words(scene):
    scene.ctx.commands.run("/rollback 1 ../elsewhere.txt")
    assert scene.ctx.renderer.errors == [texts().t("fehler.checkpoints_bad_file")]


def test_a_chat_without_a_shared_folder_says_so(scene):
    scene.stub.chats["c-1"]["working_dirs"] = []
    scene.ctx.commands.run("/rollback")
    assert scene.ctx.renderer.notices == [texts().t("cli.rollback_no_folder")]
    assert scene.ctx.screen.printed == []


def test_a_folder_never_snapshotted_while_inactive_tells_how_to_activate(scene, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    scene.stub.chats["c-1"]["working_dirs"] = [str(other)]
    scene.stub._app.state.repositories = SimpleNamespace(einstellungen=_Switch(False))
    scene.ctx.commands.run("/rollback")
    assert scene.ctx.renderer.notices == [texts().t("cli.rollback_inactive")]
    scene.stub._app.state.repositories = SimpleNamespace(einstellungen=_Switch(True))
    scene.ctx.commands.run("/rollback")
    assert scene.ctx.renderer.notices[-1] == texts().t("cli.rollback_none")
