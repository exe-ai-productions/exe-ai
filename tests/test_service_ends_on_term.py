"""The service and every server it holds end on a termination signal.

A window holds a line of events open all the time. uvicorn waits for every
open connection before it runs the service's shutdown, so with no limit on
that wait the shutdown never began and the servers stayed behind; with the
limit of ``start.py`` only 2 of the 5 seconds the shell grants were left for
stopping the servers one after the other, and a server in its own session
survives a kill of the service. Now the end is heard ahead of uvicorn's wait,
the lines end at once, and the servers are stopped side by side within one
short time (``app/shutdown.py``).

The first test starts the real service the way the test service is started
(uvicorn without any limit), holds the window's line open and sends the
signal. The rest run the pieces: the lines, the shared stop with a server that
ignores the signal, a painter's process, the voice held by a load, an MCP
process that does not end, the picture server not starting while the service
ends, and the signal listener itself.
"""

from __future__ import annotations

import asyncio
import http.client
import inspect
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from app import prozessstopp, shutdown
from app.bildrunner import Bildrunner
from app.bildturbo import Bildturbo
from app.ereignisstrom import Ereignisstrom
from app.modellrunner import Modellrunner
from app.tools.hintergrund import Laufverwaltung
from app.tools.mcp_client import MCPStdioClient
from app.voice_service import VoiceService

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals; Windows ends through the marker file")

# A process that ignores the polite request and says when it does.
STUBBORN = (
    "import signal, sys, time\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "print('ready', flush=True)\n"
    "time.sleep(120)\n"
)


@pytest.fixture(autouse=True)
def fresh_shutdown():
    shutdown.reset()
    yield
    shutdown.reset()


def _stubborn(**kwargs) -> subprocess.Popen:
    process = subprocess.Popen(
        [sys.executable, "-c", STUBBORN], stdout=subprocess.PIPE, text=True, start_new_session=True, **kwargs
    )
    assert process.stdout is not None and process.stdout.readline().strip() == "ready"
    return process


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --- the real service ------------------------------------------------------


def test_the_service_ends_on_term_with_a_window_line_open_and_no_limit(tmp_path):
    port = _free_port()
    shutil.copy(ROOT / "config.example.yaml", tmp_path / "config.yaml")
    env = {
        **os.environ,
        "EXE_AI_TERMINAL_HEADLESS": "1",
        "EXE_AI_DATEN": str(tmp_path),
        "EXE_AI_CONFIG": str(tmp_path / "config.yaml"),
        "EXE_AI_PORT": str(port),
        "EXE_AI_HOST": "127.0.0.1",
    }
    service = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    line = None
    try:
        end = time.monotonic() + 90
        page = ""
        while time.monotonic() < end:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/app/", timeout=2) as answer:
                    page = answer.read().decode("utf-8")
                    break
            except OSError:
                time.sleep(0.3)
        else:
            pytest.fail("the service did not come up")
        # On the loopback address the page itself carries the session key.
        key = re.search(r'__SITZUNGSSCHLUESSEL__="([^"]+)"', page)
        assert key, "the page carries no session key"
        # The window's line of events, held open.
        line = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        line.request("GET", "/api/v1/events/stream", headers={"X-Sitzungsschluessel": key.group(1)})
        answer = line.getresponse()
        assert answer.status == 200, answer.status
        service.send_signal(signal.SIGTERM)
        started = time.monotonic()
        try:
            service.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pytest.fail("the service did not end within 5 seconds of the termination signal")
        assert time.monotonic() - started < 5
        # Ended by itself, not killed.
        assert service.returncode in (0, -signal.SIGTERM), service.returncode
    finally:
        if line is not None:
            line.close()
        if service.poll() is None:
            service.kill()
            service.wait()


# --- the lines ---------------------------------------------------------------


async def test_closing_the_watchers_ends_the_line_of_events_and_a_new_one_ends_at_once():
    strom = Ereignisstrom()
    first = strom.zuschauen(herzschlag_sekunden=60)
    waiting = asyncio.ensure_future(first.__anext__())
    await asyncio.sleep(0.05)
    assert strom.zuschauer == 1
    strom.close_watchers()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(waiting, 1)
    shutdown.begin()
    later = strom.zuschauen(herzschlag_sekunden=60)
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(later.__anext__(), 1)
    assert strom.zuschauer == 0


async def test_closing_the_watchers_ends_the_command_line_and_a_new_one_ends_at_once():
    runs = Laufverwaltung()
    first = runs.zuschauen("chat", herzschlag_sekunden=60)
    waiting = asyncio.ensure_future(first.__anext__())
    await asyncio.sleep(0.05)
    runs.close_watchers()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(waiting, 1)
    shutdown.begin()
    later = runs.zuschauen("chat", herzschlag_sekunden=60)
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(later.__anext__(), 1)


async def test_silence_without_an_end_the_lines_keep_their_heartbeat_and_their_events():
    strom = Ereignisstrom()
    watching = strom.zuschauen(herzschlag_sekunden=0.05)
    assert await asyncio.wait_for(watching.__anext__(), 1) is None  # the heartbeat
    strom.melden("hello")
    seen = await asyncio.wait_for(watching.__anext__(), 1)
    while seen is None:
        seen = await asyncio.wait_for(watching.__anext__(), 1)
    assert seen["typ"] == "hello"
    await watching.aclose()

    runs = Laufverwaltung()
    watching = runs.zuschauen("chat", herzschlag_sekunden=0.05)
    assert await asyncio.wait_for(watching.__anext__(), 1) is None
    await watching.aclose()


# --- the servers ---------------------------------------------------------------


def test_servers_are_stopped_side_by_side_and_one_that_ignores_the_signal_is_killed():
    grace = 0.5
    processes = [_stubborn() for _ in range(3)]
    stoppers = {
        f"server{n}": (lambda p=p: prozessstopp.beenden(p, frist=grace)) for n, p in enumerate(processes)
    }
    started = time.monotonic()
    late = shutdown.stop_together(stoppers, deadline=grace + 1.0)
    elapsed = time.monotonic() - started
    try:
        assert late == []
        # Side by side: three servers that each take the whole grace period
        # would take three of them one after the other.
        assert elapsed < 3 * grace, elapsed
        # Killed, and reaped a moment later: the kill is asked for, not awaited.
        for process in processes:
            assert process.wait(timeout=2) is not None
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()


def test_a_stop_that_never_returns_does_not_hold_the_end_up_and_is_named():
    release = threading.Event()
    stoppers = {"stuck": lambda: release.wait(30), "quick": lambda: None}
    started = time.monotonic()
    try:
        late = shutdown.stop_together(stoppers, deadline=0.3)
        assert late == ["stuck"], late
        assert time.monotonic() - started < 2
    finally:
        release.set()


def test_a_stop_that_raises_is_logged_and_the_others_still_end(caplog):
    done = []

    def broken():
        raise RuntimeError("no")

    late = shutdown.stop_together({"broken": broken, "fine": lambda: done.append(1)}, deadline=1)
    assert late == [] and done == [1]


def test_the_painters_running_process_ends_within_the_grace_period(tmp_path):
    runner = Bildrunner(tmp_path)
    process = _stubborn()
    runner._prozess = process
    started = time.monotonic()
    try:
        assert runner.stoppen(frist=0.3) is True
        assert process.wait(timeout=2) is not None
        assert time.monotonic() - started < 2
    finally:
        if process.poll() is None:
            process.kill()


def test_every_server_class_takes_a_grace_period_and_the_shutdown_names_all_of_them():
    for cls in (Modellrunner, Bildrunner, Bildturbo):
        assert "frist" in inspect.signature(cls.stoppen).parameters, cls
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    for name in ("modellrunner", "einbettungsrunner", "agentenrunner", "sprachrunner",
                 "sprachputzrunner", "bildturbo", "bildrunner"):
        assert f'"{name}"' in source.split("stoppers: dict", 1)[1].split("late = await", 1)[0], name


def test_silence_the_default_grace_periods_are_what_they_were():
    assert inspect.signature(Modellrunner.stoppen).parameters["frist"].default == prozessstopp.FRIST
    assert inspect.signature(Bildturbo.stoppen).parameters["frist"].default == 5.0


def test_the_picture_server_is_not_started_while_the_service_ends(tmp_path):
    turbo = Bildturbo(tmp_path, 18999, lambda: None)
    shutdown.begin()
    assert turbo.starten(tmp_path / "model.gguf") is False
    assert turbo.laeuft() is False


# --- the voice and MCP ---------------------------------------------------------


def test_the_voice_held_by_a_load_does_not_hold_the_end_up():
    service = VoiceService(command=lambda: [sys.executable, "-c", "import time; time.sleep(120)"])
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"], stdin=subprocess.PIPE, text=True,
        start_new_session=True,
    )
    service._process = process
    held = threading.Event()
    release = threading.Event()

    def hold():
        with service._work:
            held.set()
            release.wait(30)

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    assert held.wait(2)
    started = time.monotonic()
    try:
        service.stop(wait=0.2)
        assert time.monotonic() - started < 2
        assert process.wait(timeout=2) is not None, "the voice process was left running"
    finally:
        release.set()
        holder.join(2)
        if process.poll() is None:
            process.kill()


def test_silence_the_voice_stops_as_before_when_nothing_holds_it():
    service = VoiceService()
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE, text=True,
    )
    service._process = process
    service.stop()
    assert process.poll() is not None
    assert service._process is None


async def test_an_mcp_process_that_ignores_the_signal_is_killed_and_does_not_hold_the_end_up():
    client = MCPStdioClient("stubborn", sys.executable)
    client._prozess = await asyncio.create_subprocess_exec(
        sys.executable, "-c", STUBBORN, stdout=asyncio.subprocess.PIPE
    )
    assert client._prozess.stdout is not None
    assert (await client._prozess.stdout.readline()).strip() == b"ready"
    started = time.monotonic()
    await client.stoppen(0.3)
    assert time.monotonic() - started < 2
    assert client._prozess is None


# --- the listener ----------------------------------------------------------------


async def test_the_listener_hears_the_signal_ahead_of_the_previous_handler_and_hands_it_on():
    handed_on = []
    previous = signal.signal(signal.SIGTERM, lambda number, frame: handed_on.append(number))
    seen = []
    shutdown.on_begin(lambda: seen.append("begun"))
    restore = shutdown.listen(asyncio.get_running_loop())
    try:
        signal.raise_signal(signal.SIGTERM)
        for _ in range(40):
            if seen:
                break
            await asyncio.sleep(0.02)
        assert seen == ["begun"]
        assert handed_on == [signal.SIGTERM]
        assert shutdown.begun()
        # A second signal does nothing twice.
        signal.raise_signal(signal.SIGTERM)
        await asyncio.sleep(0.1)
        assert seen == ["begun"]
    finally:
        restore()
        signal.signal(signal.SIGTERM, previous)
