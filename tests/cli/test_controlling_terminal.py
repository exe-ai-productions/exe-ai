"""A client in a terminal that controls its session — the terminal of a
window — ends quietly when the window is closed.

Closing a window does more than end the reading and writing: the system
sends the session's processes the request to hang up as well. The other
program tests give the client a terminal for input and output only, where
nothing sends that request; this is the way of a real terminal window.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from cli import themes
from tests.cli.program import Held, on_a_port, posix_only
from tests.cli.stub_service import StubService, eventually
from tests.cli.test_leaving import ANSWER_WITH_A_RUNNING_TOOL, Unpluggable, running_tool


@posix_only
@pytest.mark.parametrize("busy", [False, True], ids=["with nothing running", "during an answer"])
def test_a_window_closed_under_a_client_of_its_own_session_ends_it_without_a_word(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, busy: bool
) -> None:
    # The look owns the ground, so leaving has a ground to give back to a
    # terminal that is no longer there.
    monkeypatch.delenv(themes.WINDOW_VARIABLE, raising=False)
    stub = Held() if busy else StubService()
    if busy:
        stub.script = list(ANSWER_WITH_A_RUNNING_TOOL)
    try:
        with on_a_port(stub) as address:
            program = Unpluggable(address, tmp_path, controlling=True)
            if busy:
                running_tool(program, stub, len(stub.sent))
            else:
                program.wait_for(lambda: stub.watchers >= 1)
                program.wait_until_it_listens()
            program.unplug()
            code, errors = program.ended()
            eventually(lambda: stub.watchers == 0)
    finally:
        stub.close()
    assert code == 0
    assert errors == ""


@posix_only
def test_the_terminal_of_the_client_is_the_controlling_one_of_a_session_of_its_own(
    tmp_path: Path,
) -> None:
    stub = StubService()
    try:
        with on_a_port(stub) as address:
            program = Unpluggable(address, tmp_path, controlling=True)
            program.wait_for(lambda: stub.watchers >= 1)
            program.wait_until_it_listens()
            pid = program._process.pid
            leads_its_session = os.getsid(pid) == pid
            terminal = subprocess.run(
                ["ps", "-o", "tty=", "-p", str(pid)], capture_output=True, text=True, check=True
            ).stdout.strip()
            program.type("/quit\r")
            code, errors = program.ended()
    finally:
        stub.close()
    # The client leads its own session, and the system names a terminal for
    # it; a process without one is shown as "?" or "??".
    assert leads_its_session
    assert terminal not in ("", "?", "??")
    assert code == 0
    assert errors == ""
