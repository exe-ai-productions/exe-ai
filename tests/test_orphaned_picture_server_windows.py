"""A picture server a crashed service left behind is ended at the next start.

Windows has no ``ps``: the check raised, the note with the old process id
stayed on disk and the old ``sd-server.exe`` kept its port and its memory.
``tasklist`` names the image behind one process id instead, and the same
question is asked by the llama servers (``app/prozessstopp.py``,
``runs_program``). Only the platform and the calls are made up; no signal is
sent to any real process.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app import prozessstopp
from app.bildturbo import Bildturbo


@pytest.fixture
def turbo(tmp_path: Path) -> Bildturbo:
    """A picture server with a note naming the process id 4242."""
    server = Bildturbo(tmp_path, app_port=8095)
    note = tmp_path / ".bildturbo-8095.pid"
    note.write_text("4242", encoding="utf-8")
    assert server._pid_datei == note
    return server


def _fake_commands(monkeypatch, listing: str, seen: list) -> None:
    """``tasklist`` answers with ``listing``, ``taskkill`` succeeds."""

    def run(command, **kwargs):
        seen.append(command)
        stdout = listing if command[0] in ("tasklist", "ps") else ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(prozessstopp.subprocess, "run", run)


def _on_windows(monkeypatch) -> None:
    monkeypatch.setattr(prozessstopp.sys, "platform", "win32")
    monkeypatch.setattr(prozessstopp, "WINDOWS", True)


def test_on_windows_the_orphaned_picture_server_is_ended(turbo: Bildturbo, monkeypatch):
    seen: list = []
    _on_windows(monkeypatch)
    _fake_commands(monkeypatch, '"sd-server.exe","4242","Console","1","1.498.588 K"\r\n', seen)

    turbo._raeum_waise()

    assert seen[0][:3] == ["tasklist", "/FI", "PID eq 4242"]
    assert seen[1] == ["taskkill", "/T", "/F", "/PID", "4242"]
    assert not turbo._pid_datei.exists()


def test_on_windows_a_foreign_process_is_left_alone(turbo: Bildturbo, monkeypatch):
    seen: list = []
    _on_windows(monkeypatch)
    _fake_commands(monkeypatch, '"python.exe","4242","Console","1","53.028 K"\r\n', seen)

    turbo._raeum_waise()

    assert [command[0] for command in seen] == ["tasklist"]
    assert not turbo._pid_datei.exists()


def test_on_windows_a_free_id_is_left_alone(turbo: Bildturbo, monkeypatch):
    seen: list = []
    _on_windows(monkeypatch)
    _fake_commands(monkeypatch, "INFO: No tasks are running which match the specified criteria.\r\n", seen)

    turbo._raeum_waise()

    assert [command[0] for command in seen] == ["tasklist"]
    assert not turbo._pid_datei.exists()


def test_on_the_mac_the_check_still_asks_ps_and_ends_through_the_one_way(turbo: Bildturbo, monkeypatch):
    seen: list = []
    ended: list = []
    monkeypatch.setattr(prozessstopp.sys, "platform", "darwin")
    _fake_commands(monkeypatch, "sd-server\n", seen)

    def end(pid: int) -> bool:
        ended.append(pid)
        return True

    monkeypatch.setattr(prozessstopp, "beenden_nach_pid", end)

    turbo._raeum_waise()

    assert seen[0][0] == "ps" and ended == [4242]
    assert not turbo._pid_datei.exists()


def test_silence_without_a_note_nothing_is_asked(tmp_path: Path, monkeypatch):
    seen: list = []
    _fake_commands(monkeypatch, "sd-server\n", seen)

    Bildturbo(tmp_path, app_port=8095)._raeum_waise()

    assert seen == []
