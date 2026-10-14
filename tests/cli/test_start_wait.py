"""Waiting for a service the client started itself: for as long as the
started process lives, however long that is; no longer once it has ended;
and an interrupt from the keyboard ends the wait and the service with it."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from cli import service
from cli.texts import Texts
from tests.cli.program import ENTER, Run, run_client
from tests.cli.stub_service import AppTransport, StubService, eventually

OWN_ADDRESS = "http://127.0.0.1:8123"


class ComingUp(httpx.BaseTransport):
    """In front of the stand-in: a service that takes its time to come up.
    Nothing answers until the page was asked for ``looks`` times."""

    def __init__(self, stub: StubService, looks: int) -> None:
        self._answers = AppTransport(stub, stub._loop)
        self.remaining = looks
        self.looks = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self.remaining > 0:
            if request.url.path == "/app/":
                self.looks += 1
                self.remaining -= 1
            raise httpx.ConnectError("connection refused", request=request)
        return self._answers.handle_request(request)


class Process:
    """The started service: alive until it has been looked at ``lives``
    times — for ever, where that is ``None`` — or was told to end."""

    def __init__(self, lives: int | None = None) -> None:
        self._lives = lives
        self.told_to_end = 0
        self.waited_for = 0

    def poll(self) -> int | None:
        if self.told_to_end:
            return -15
        if self._lives is None:
            return None
        self._lives -= 1
        return 1 if self._lives < 0 else None

    def terminate(self) -> None:
        self.told_to_end += 1

    def wait(self) -> int:
        self.waited_for += 1
        return -15


class Clock:
    """Stands in for the clock of the wait: every look at it finds a minute
    gone, and no pause takes any time. ``interrupt_at`` lets the user press
    the interrupt key during that pause."""

    def __init__(self, interrupt_at: int | None = None) -> None:
        self.now = 1000.0
        self.pauses = 0
        self._interrupt_at = interrupt_at

    def monotonic(self) -> float:
        self.now += 60.0
        return self.now

    def sleep(self, seconds: float) -> None:
        self.pauses += 1
        if self.pauses == self._interrupt_at:
            raise KeyboardInterrupt


def leave_once_connected(stub: StubService) -> Callable[[Run, Callable[[str], None]], None]:
    def drive(run: Run, type_in: Callable[[str], None]) -> None:
        run.parts()
        eventually(lambda: stub.watchers == 1)
        type_in(f"/quit{ENTER}")

    return drive


def nothing_typed(run: Run, type_in: Callable[[str], None]) -> None:
    return None


def start(
    stub: StubService,
    outside: ComingUp,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drive: Callable[[Run, Callable[[str], None]], None],
) -> int | None:
    with httpx.Client(transport=outside) as http:
        return run_client(http, tmp_path, monkeypatch, drive, address=OWN_ADDRESS).code


def test_a_service_that_answers_long_after_half_a_minute_is_still_attached_to(
    stub: StubService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    handed_out: list[Process] = []
    process = Process()
    monkeypatch.setattr(service.subprocess, "Popen", lambda command, **kwargs: handed_out.append(process) or process)
    clock = Clock()
    monkeypatch.setattr(service, "time", clock)
    # The first look finds nothing and starts the service; then it takes
    # twenty more looks, a minute apiece by this clock, until it answers.
    outside = ComingUp(stub, looks=21)

    assert start(stub, outside, tmp_path, monkeypatch, leave_once_connected(stub)) == 0

    assert len(handed_out) == 1
    assert outside.looks == 21 and clock.pauses == 20
    assert process.told_to_end == 0
    shown = capsys.readouterr()
    assert Texts("en").t("cli.service_starting", address=OWN_ADDRESS) in shown.out
    assert Texts("en").t("cli.service_start_failed", address=OWN_ADDRESS) not in shown.err


def test_a_started_service_that_ends_before_it_answers_is_said_to_have_failed(
    stub: StubService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    process = Process(lives=3)
    monkeypatch.setattr(service.subprocess, "Popen", lambda command, **kwargs: process)
    clock = Clock()
    monkeypatch.setattr(service, "time", clock)
    outside = ComingUp(stub, looks=1000)

    assert start(stub, outside, tmp_path, monkeypatch, nothing_typed) == 1

    # Looked at while it lived, and not once more after it had ended.
    assert clock.pauses == 3
    assert process.told_to_end == 0
    assert Texts("en").t("cli.service_start_failed", address=OWN_ADDRESS) in capsys.readouterr().err


def test_the_interrupt_key_ends_the_wait_and_the_service_that_was_started(
    stub: StubService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    process = Process()
    monkeypatch.setattr(service.subprocess, "Popen", lambda command, **kwargs: process)
    clock = Clock(interrupt_at=2)
    monkeypatch.setattr(service, "time", clock)
    outside = ComingUp(stub, looks=1000)

    assert start(stub, outside, tmp_path, monkeypatch, nothing_typed) == 1

    # Told to end once, and waited for until it was gone.
    assert process.told_to_end == 1 and process.waited_for == 1
    # Nothing failed: the user ended it, and no sentence says otherwise.
    assert capsys.readouterr().err == ""


def test_a_service_that_answers_at_once_is_attached_to_without_a_pause(
    stub: StubService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = Process()
    monkeypatch.setattr(service.subprocess, "Popen", lambda command, **kwargs: process)
    clock = Clock()
    monkeypatch.setattr(service, "time", clock)
    outside = ComingUp(stub, looks=1)

    assert start(stub, outside, tmp_path, monkeypatch, leave_once_connected(stub)) == 0

    assert clock.pauses == 0
    assert process.told_to_end == 0


def test_the_wait_knows_no_bound_of_its_own() -> None:
    assert not hasattr(service, "START_WAIT_SECONDS")
