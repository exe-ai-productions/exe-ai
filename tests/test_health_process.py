"""The service says which process it is, so that a client on the same
machine can find that process in its own process list — and says so behind
its key only: the open address for monitoring answers what it always did."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import own_process
from cli import service as client_side

KEY_HEADER = "X-Sitzungsschluessel"


@pytest.fixture(autouse=True)
def nothing_kept() -> Iterator[None]:
    """What the service keeps of a start named on Windows is kept for as
    long as it runs; every test here starts with nothing kept, and leaves
    none of its stand-in answers behind."""
    own_process._start_on_windows.cache_clear()
    yield
    own_process._start_on_windows.cache_clear()


def test_behind_the_key_the_service_names_the_process_it_runs_in(client: TestClient) -> None:
    said = client.get("/api/v1/health").json()

    assert said["status"] == "ok"
    assert said["process"]["pid"] == os.getpid()
    # The client's own check against this machine's process list: what the
    # service read about itself and what the client reads are one process.
    assert client_side.runs_here(said) is True


def test_the_open_address_names_no_process_and_answers_what_it_always_did(
    client: TestClient,
) -> None:
    """The address for monitoring answers whoever reaches the port, and
    whatever reads it reads the answer it knows."""
    del client.headers[KEY_HEADER]

    answer = client.get("/health")

    assert answer.status_code == 200
    assert set(answer.json()) == {"status", "version", "datenbank"}
    assert answer.json()["status"] == "ok"
    assert client_side.runs_here(answer.json()) is False


def test_without_the_key_nobody_is_told_the_process(client: TestClient) -> None:
    del client.headers[KEY_HEADER]

    answer = client.get("/api/v1/health")

    assert answer.status_code == 401
    assert "process" not in answer.json()


def test_the_beginning_is_read_anew_so_a_clock_set_since_moves_it_as_it_moves_a_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Falls over where the service keeps its first reading: the process
    list says how long ago, and a machine whose clock is set after that
    reading — a start before the time was synchronised — would name a
    beginning no client computes."""
    clock = iter([1_000.0, 5_000.0])
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(own_process, "_listed", lambda command: "00:10")
    # The module's own clock only: the rest of the test run keeps its time.
    monkeypatch.setattr(own_process, "time", SimpleNamespace(time=lambda: next(clock)))

    first, second = own_process.named(), own_process.named()

    assert first == own_process.Process(os.getpid(), 990.0)
    assert second == own_process.Process(os.getpid(), 4_990.0)


def test_an_ask_the_system_left_unanswered_is_not_kept(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One failed start of the system's tool must not leave the service
    without a process for as long as it runs."""
    read = own_process._listed
    monkeypatch.setattr(own_process, "_listed", lambda command: None)
    assert client.get("/api/v1/health").json()["process"] is None

    monkeypatch.setattr(own_process, "_listed", read)
    assert client.get("/api/v1/health").json()["process"]["pid"] == os.getpid()


def test_on_windows_the_start_is_asked_for_once_and_a_failure_is_asked_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """There the shell names the start itself — a figure no clock moves —
    and takes its time over it."""
    answers = iter([None, "134116992000000000"])
    asked: list[list[str]] = []

    def shell(command: list[str]) -> str | None:
        asked.append(command)
        return next(answers)

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(own_process, "_listed", shell)

    assert own_process.named() is None
    assert own_process.named() == own_process.Process(os.getpid(), 1_767_225_600.0)
    assert own_process.named() == own_process.Process(os.getpid(), 1_767_225_600.0)
    assert len(asked) == 2


def test_where_the_system_does_not_say_the_service_names_no_process_and_is_well(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(own_process, "_listed", lambda command: None)

    said = client.get("/api/v1/health").json()

    assert said["status"] == "ok"
    assert said["process"] is None
    assert client_side.runs_here(said) is False


@pytest.mark.parametrize(
    "listed",
    ["00:05", "12:34", "01:02:03", "2-03:04:05", "", "soon", "1:2:3:4", "x-00:01"],
)
def test_the_service_reads_a_running_time_as_the_client_reads_it(listed: str) -> None:
    """Two readers of one list: where they read a line differently, the
    client would take this machine's service for one elsewhere."""
    assert own_process._elapsed(listed) == client_side._elapsed(listed)


def test_on_windows_the_service_reads_its_start_as_the_client_reads_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """There the shell names the start itself, in the system's own count of
    time: both read the same figure out of it."""
    # The first second of 2026, in steps of a hundred nanoseconds since 1601.
    ticks, seconds = "134116992000000000", 1_767_225_600.0
    asked: list[list[str]] = []

    def shell(command: list[str]) -> str:
        asked.append(command)
        return ticks

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(own_process, "_listed", shell)
    monkeypatch.setattr(client_side, "_listed", shell)

    assert own_process._began(4242) == client_side.began(4242) == seconds
    assert asked[0] == asked[1]
