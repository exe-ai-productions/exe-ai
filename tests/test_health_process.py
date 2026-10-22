"""The service says which process it is, so that a client on the same
machine can find that process in its own process list — and says so behind
its key only: the open address for monitoring answers what it always did."""

from __future__ import annotations

import os
import subprocess

import psutil
import pytest
from fastapi.testclient import TestClient

from app import own_process
from cli import service as client_side

KEY_HEADER = "X-Sitzungsschluessel"


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


def test_the_beginning_is_the_one_the_system_says() -> None:
    assert own_process.named() == own_process.Process(
        os.getpid(), psutil.Process().create_time()
    )


def test_the_service_and_the_client_read_one_beginning() -> None:
    """Two readers of one process: where they read it differently, the client
    would take this machine's service for one elsewhere."""
    assert own_process._began(os.getpid()) == client_side.began(os.getpid())


def test_no_program_of_the_system_is_started_to_read_a_beginning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Neither the process list nor a shell: a machine without them, or one
    whose shell takes seconds to start, reads the same beginning."""

    def refused(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"a program was started: {args!r}")

    monkeypatch.setattr(subprocess, "run", refused)
    monkeypatch.setattr(subprocess, "Popen", refused)

    assert own_process.named() is not None
    assert client_side.began(os.getpid()) is not None


def test_an_ask_the_system_left_unanswered_is_not_kept(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One failed reading must not leave the service without a process for
    as long as it runs."""
    read = own_process._began
    monkeypatch.setattr(own_process, "_began", lambda pid: None)
    assert client.get("/api/v1/health").json()["process"] is None

    monkeypatch.setattr(own_process, "_began", read)
    assert client.get("/api/v1/health").json()["process"]["pid"] == os.getpid()


def test_where_the_system_does_not_say_the_service_names_no_process_and_is_well(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(own_process, "_began", lambda pid: None)

    said = client.get("/api/v1/health").json()

    assert said["status"] == "ok"
    assert said["process"] is None
    assert client_side.runs_here(said) is False
