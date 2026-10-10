"""The answer's stop ends a command in the foreground; on Windows the kill
runs off the event loop, and the command line reaches cmd.exe as written.

The stop tests run real shells on this machine (POSIX). The Windows paths
are taken with the platform pretended, the way tests/test_prozessstopp.py
does it: shown to be taken, never run.
"""

from __future__ import annotations

import asyncio
import os
import re
import signal
import threading
import time
from types import SimpleNamespace

import pytest

from app.api.v1.generierung import _werkzeug_ausfuehren
from app.tools import WerkzeugRegistry, hintergrund, ordnergedaechtnis, shell
from tests.conftest import python_command


@pytest.fixture(autouse=True)
def clean():
    ordnergedaechtnis.vergessen()
    hintergrund.laeufe._laeufe.clear()
    hintergrund.laeufe._ereignisse.clear()
    hintergrund.laeufe.abschluss = None
    yield
    ordnergedaechtnis.vergessen()
    hintergrund.laeufe._laeufe.clear()
    hintergrund.laeufe._ereignisse.clear()
    hintergrund.laeufe.abschluss = None


async def _until(condition, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.05)
    return condition()


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def _call(command: str, **more):
    return SimpleNamespace(name=shell.WERKZEUG_NAME, argumente={"command": command, **more})


CHILD_COMMAND = "sleep 60 & echo child=$!; wait"


async def _child_of(run) -> int:
    assert await _until(lambda: "child=" in run.ausgabe)
    match = re.search(r"child=(\d+)", run.ausgabe)
    assert match
    return int(match.group(1))


# --- the answer's stop ends the command in the foreground -----------------


async def _cancelled_run(tmp_path, *, herkunft: str, owner: str):
    """A long foreground command through the tool call of a chat or a job,
    cancelled while it runs. Returns (result, child pid, run)."""
    registry = WerkzeugRegistry([], shell_an=True)
    stop = asyncio.Event()
    call = asyncio.create_task(_werkzeug_ausfuehren(
        registry, _call(CHILD_COMMAND), "en",
        ordner=[str(tmp_path)], chat_id=owner, herkunft=herkunft, abbruch=stop,
    ))
    assert await _until(lambda: bool(hintergrund.laeufe.laeufe(owner)))
    run = hintergrund.laeufe.laeufe(owner)[-1]
    child = await _child_of(run)
    try:
        stop.set()
        result, failed, _, _ = await asyncio.wait_for(call, timeout=15)
    finally:
        if not _gone(child):
            os.kill(child, signal.SIGKILL)
    return result, child, run


@pytest.mark.asyncio
@pytest.mark.platforms("posix", reason="a shell child by `$!` and `wait`")
async def test_cancelling_the_answer_ends_the_command_and_its_tree(tmp_path, caplog):
    caplog.set_level("INFO", logger="app.tools.shell")
    result, child, run = await _cancelled_run(tmp_path, herkunft="chat", owner="chat-1")
    assert result.startswith(shell.STOPPED_BY_USER)
    assert await _until(lambda: _gone(child)), "the child outlived the stop"
    assert run.zustand == hintergrund.ABGEBROCHEN
    assert f"Run #{run.nummer} in chat chat-1 stopped with its answer: {CHILD_COMMAND}" in caplog.text


@pytest.mark.asyncio
@pytest.mark.platforms("posix", reason="a shell child by `$!` and `wait`")
async def test_cancelling_the_job_ends_its_command_too(tmp_path):
    result, child, run = await _cancelled_run(tmp_path, herkunft="agent", owner="job-1")
    assert result.startswith(shell.STOPPED_BY_USER)
    assert await _until(lambda: _gone(child)), "the child outlived the stop"
    assert run.zustand == hintergrund.ABGEBROCHEN


@pytest.mark.asyncio
async def test_a_cancelled_command_without_a_run_record_still_says_stopped(tmp_path):
    """No chat, no run record — the answer still carries the stop line."""
    stop = asyncio.Event()
    # A command that runs long on every system: cmd.exe knows no `sleep`.
    command = python_command("import time; time.sleep(60)")
    call = asyncio.create_task(shell.ausfuehren(
        {"command": command}, [str(tmp_path)], None, abbruch=stop,
    ))
    await asyncio.sleep(0.3)
    stop.set()
    result = await asyncio.wait_for(call, timeout=15)
    assert result.startswith(shell.STOPPED_BY_USER)


@pytest.mark.asyncio
async def test_a_command_that_ended_before_the_stop_keeps_output_and_code(tmp_path):
    """The silence probe: the signal is read only while the command runs."""
    stop = asyncio.Event()
    result = await shell.ausfuehren(
        {"command": python_command("import sys; print('fertig'); sys.exit(3)")},
        [str(tmp_path)], "chat-1", abbruch=stop,
    )
    stop.set()
    assert result.startswith("fertig")
    assert "[exit code 3]" in result
    assert shell.STOPPED_BY_USER not in result
    assert hintergrund.laeufe.laeufe("chat-1")[-1].zustand == hintergrund.FEHLER


@pytest.mark.asyncio
@pytest.mark.platforms("posix", reason="a shell child by `$!` and `wait`")
async def test_a_background_command_runs_on_after_the_stop(tmp_path):
    """The silence probe: a run in the background belongs to the terminal,
    not to the answer that started it."""
    stop = asyncio.Event()
    started = await shell.ausfuehren(
        {"command": CHILD_COMMAND, "background": True}, [str(tmp_path)], "chat-1", abbruch=stop,
    )
    assert started.startswith("Started in the background")
    run = hintergrund.laeufe.laeufe("chat-1")[-1]
    child = await _child_of(run)
    try:
        stop.set()
        await asyncio.sleep(0.5)
        assert run.zustand == hintergrund.LAEUFT
        assert not _gone(child)
    finally:
        await hintergrund.laeufe.stop("chat-1", run.nummer)
        assert await _until(lambda: run.zustand != hintergrund.LAEUFT)


def test_the_run_hands_its_stop_to_the_shell():
    """A chat's and a job's tool call hand their stop to the shell
    (app/api/v1/generierung.py), as they do to the tools that paint — and
    to no other tool."""
    class _Register:
        def __init__(self):
            self.calls: dict[str, dict] = {}

        async def ausfuehren(self, name, argumente, bild_senke=None, **more):
            self.calls[name] = more
            return "ok"

    register = _Register()
    stop = asyncio.Event()

    async def run():
        for name in (shell.WERKZEUG_NAME, "read_file"):
            await _werkzeug_ausfuehren(
                register, SimpleNamespace(name=name, argumente={}), "en", abbruch=stop
            )

    asyncio.run(run())
    assert register.calls[shell.WERKZEUG_NAME]["abbruch"] is stop
    assert "abbruch" not in register.calls["read_file"]


# --- Windows: the kill runs off the event loop ----------------------------


def _pretend_windows(monkeypatch) -> None:
    monkeypatch.setattr(shell, "WINDOWS", True)
    monkeypatch.delattr(shell.os, "killpg", raising=False)


@pytest.mark.asyncio
async def test_on_windows_the_kill_does_not_hold_the_event_loop(monkeypatch):
    """A taskkill that takes its time: the caller returns at once and another
    task of the loop keeps running meanwhile. Without the fix the loop stood
    for the whole call."""
    _pretend_windows(monkeypatch)
    calls: list = []
    finished = threading.Event()

    def slow_taskkill(command, **kwargs):
        calls.append(command)
        time.sleep(0.6)
        finished.set()
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(shell.subprocess, "run", slow_taskkill)
    process = SimpleNamespace(pid=4242, kill=lambda: calls.append("kill"))
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    clock = asyncio.create_task(ticker())
    try:
        started = time.monotonic()
        shell.gruppe_toeten(process)
        returned_after = time.monotonic() - started
        await asyncio.sleep(0.3)
        ticks_meanwhile = ticks
    finally:
        clock.cancel()
    assert finished.wait(5), "taskkill never ran"
    assert returned_after < 0.2, "the caller waited for taskkill"
    # Without the fix the loop stands for the whole 0.6 s and the count is
    # 0; a low bar keeps a loaded machine from reading as that.
    assert ticks_meanwhile >= 3, "the loop stood while taskkill ran"
    assert calls[0][:4] == ["taskkill", "/T", "/F", "/PID"] and "4242" in calls[0]
    assert "kill" not in calls


def test_on_windows_the_single_kill_follows_a_taskkill_that_finds_nothing(monkeypatch):
    _pretend_windows(monkeypatch)
    killed = threading.Event()
    monkeypatch.setattr(shell.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=128))
    shell.gruppe_toeten(SimpleNamespace(pid=4242, kill=killed.set))
    assert killed.wait(5), "the single kill never came"


@pytest.mark.platforms("posix", reason="the group kill by signal")
def test_on_posix_the_kill_signals_the_group_and_runs_no_taskkill(monkeypatch):
    """The silence probe."""
    signalled: list = []
    monkeypatch.setattr(shell.os, "killpg", lambda pid, sig: signalled.append((pid, sig)))
    monkeypatch.setattr(shell, "gruppe_ist_noch_unsere", lambda prozess: True)
    ran: list = []
    monkeypatch.setattr(shell.subprocess, "run", lambda *a, **k: ran.append(a))
    shell.gruppe_toeten(SimpleNamespace(pid=4242, kill=lambda: ran.append("kill")))
    assert signalled == [(4242, signal.SIGKILL)]
    assert ran == []


# --- Windows: the command line reaches cmd.exe as written -----------------


def test_the_windows_line_carries_no_double_quote_and_the_marker_starts_its_line(monkeypatch):
    monkeypatch.setattr(shell, "WINDOWS", True)
    line = shell._mit_ordnermarke("dir")
    assert '"' not in line
    assert line.startswith("(dir) & set __exe_rc=!ERRORLEVEL!&")
    # The marker is echoed as the first thing on a line of its own, the
    # folder right behind it — what the reader looks for at a line's start.
    assert f"& echo {shell.MARKE_WIN}!CD!&" in line
    assert line.endswith("& exit /b !__exe_rc!")


@pytest.mark.asyncio
async def test_on_windows_the_line_goes_to_the_processor_as_one_string(monkeypatch, tmp_path):
    """One string, verbatim — the user's own quotes included — with delayed
    expansion switched on; never a list the runtime would re-quote."""
    monkeypatch.setattr(shell, "WINDOWS", True)
    monkeypatch.setenv("COMSPEC", r"C:\Windows\system32\cmd.exe")
    seen: dict = {}

    async def fake_shell(command, **kwargs):
        seen["command"], seen["kwargs"] = command, kwargs
        return "process"

    async def no_exec(*args, **kwargs):
        raise AssertionError("the Windows line must not go through an argument list")

    monkeypatch.setattr(shell.asyncio, "create_subprocess_shell", fake_shell)
    monkeypatch.setattr(shell.asyncio, "create_subprocess_exec", no_exec)
    assert await shell._starten('echo "a b"', tmp_path) == "process"
    line = shell._mit_ordnermarke('echo "a b"')
    assert seen["command"] == f'C:\\Windows\\system32\\cmd.exe /v:on /c "{line}"'
    assert seen["kwargs"]["cwd"] == str(tmp_path)
    assert "start_new_session" not in seen["kwargs"]


def test_the_posix_line_is_unchanged(monkeypatch):
    """The silence probe, character for character — with the system
    pretended, the way the Windows tests above pretend theirs."""
    monkeypatch.setattr(shell, "WINDOWS", False)
    assert shell._mit_ordnermarke("ls") == (
        "{ ls\n} ; __exe_rc=$? ; printf '\\n\\036%s' \"$PWD\" ; exit $__exe_rc"
    )


@pytest.mark.asyncio
async def test_on_posix_the_command_still_goes_to_the_shell_as_its_argument(monkeypatch, tmp_path):
    monkeypatch.setattr(shell, "WINDOWS", False)
    seen: dict = {}

    async def fake_exec(program, *args, **kwargs):
        seen["program"], seen["args"], seen["kwargs"] = program, args, kwargs
        return "process"

    monkeypatch.setattr(shell.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setenv("SHELL", "/bin/zsh")
    assert await shell._starten("ls", tmp_path) == "process"
    assert seen["program"] == "/bin/zsh"
    assert seen["args"] == ("-c", shell._mit_ordnermarke("ls"))
    assert seen["kwargs"]["start_new_session"] is True
