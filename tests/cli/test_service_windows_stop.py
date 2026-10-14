"""On Windows ``exe service stop`` asks the service to end itself.

A termination signal is the end of the process there: the service's shutdown
never runs, and its model server stays behind. So the client lays a marker
beside the note, waits for the port to be let go, and ends the process with
its children only when the service did not answer in time. Elsewhere the
signal is what it was. The platform and the process calls are stood in for.
"""

from __future__ import annotations

import os
import signal
from pathlib import Path

import pytest

from cli import service

PORT = 18421
PID = 424242


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A running service: a note, a port that answers until `ends` is true,
    a process that wrote the note. Records the signals and the tree ends."""
    monkeypatch.setenv(service.DATA_VARIABLE, str(tmp_path / "root"))
    monkeypatch.setattr(service, "STOP_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(service, "STOP_POLL_SECONDS", 0.005)
    file = service.note_file(PORT)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(f'{{"pid": {PID}}}', encoding="utf-8")
    state = {"alive": True, "signals": [], "trees": [], "ends_on_request": False}

    def answering(host, port):
        if state["ends_on_request"] and service.request_file(PORT).exists():
            state["alive"] = False
        return state["alive"]

    monkeypatch.setattr(service, "answering", answering)
    monkeypatch.setattr(service, "wrote", lambda pid, note: pid == PID)
    monkeypatch.setattr(os, "kill", lambda pid, sig: state["signals"].append((pid, sig)))

    def end_tree(pid):
        state["trees"].append(pid)
        state["alive"] = False

    monkeypatch.setattr(service, "_end_tree", end_tree)
    return state


def test_on_windows_the_service_is_asked_not_signalled(world, monkeypatch):
    monkeypatch.setattr(service, "_on_windows", lambda: True)
    world["ends_on_request"] = True

    assert service.stop("127.0.0.1", PORT) == service.STOPPED
    assert world["signals"] == []
    assert world["trees"] == []
    assert service.request_file(PORT).exists()


def test_on_windows_a_service_that_does_not_answer_is_ended_once_with_its_children(
    world, monkeypatch
):
    monkeypatch.setattr(service, "_on_windows", lambda: True)

    assert service.stop("127.0.0.1", PORT) == service.STOPPED
    assert world["signals"] == []
    assert world["trees"] == [PID]
    # The unanswered request is taken back, so the next service to start on
    # this port is not ended by it.
    assert not service.request_file(PORT).exists()


def test_on_windows_a_tree_that_cannot_be_ended_is_said_to_still_run(world, monkeypatch):
    monkeypatch.setattr(service, "_on_windows", lambda: True)
    monkeypatch.setattr(service, "_end_tree", lambda pid: world["trees"].append(pid))

    assert service.stop("127.0.0.1", PORT) == service.STILL_RUNNING
    assert world["trees"] == [PID]


def test_elsewhere_the_signal_is_what_it_was(world, monkeypatch):
    monkeypatch.setattr(service, "_on_windows", lambda: False)
    monkeypatch.setattr(
        os, "kill", lambda pid, sig: (world["signals"].append((pid, sig)), world.update(alive=False))
    )

    assert service.stop("127.0.0.1", PORT) == service.STOPPED
    assert world["signals"] == [(PID, signal.SIGTERM)]
    assert world["trees"] == []
    assert not service.request_file(PORT).exists()


def test_no_service_and_a_stranger_get_nothing_on_windows(world, monkeypatch):
    """Silence probe: no answering port is `not running`; a process that is
    not the note's writer gets neither a marker nor a tree end."""
    monkeypatch.setattr(service, "_on_windows", lambda: True)
    world["alive"] = False
    assert service.stop("127.0.0.1", PORT) == service.NOT_RUNNING

    world["alive"] = True
    monkeypatch.setattr(service, "wrote", lambda pid, note: False)
    assert service.stop("127.0.0.1", PORT) == service.NOT_RUNNING
    assert world["trees"] == [] and world["signals"] == []
    assert not service.request_file(PORT).exists()
