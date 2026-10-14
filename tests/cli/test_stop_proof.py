"""``stop`` ends only the process that wrote the note. A service that was
killed leaves its note behind, and the system hands its number on: a
process that began after the note was written is a stranger, and no
stranger gets a signal — whatever answers on the port."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from cli import service
from cli.main import main
from cli.texts import Texts
from tests.cli.program import free_port

# A process that does nothing but be there.
IDLE = "import time; time.sleep(120)"

# A process that listens on the port it is given, says so, and stays — the
# part of a service that ``stop`` goes by.
LISTENING = (
    "import socket, sys, time\n"
    "listener = socket.socket()\n"
    "listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
    "listener.bind(('127.0.0.1', int(sys.argv[1])))\n"
    "listener.listen()\n"
    "print('listening', flush=True)\n"
    "time.sleep(120)\n"
)

HOUR = 3600.0


def refusing(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"a request went out: {request.method} {request.url}")


def stop(port: int, tmp_path: Path) -> int:
    return main(
        ["service", "stop", "--url", f"http://127.0.0.1:{port}", "--lang", "en"],
        http=httpx.Client(transport=httpx.MockTransport(refusing)),
        prefs_path=tmp_path / "cli.json",
    )


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data-root"
    monkeypatch.setenv(service.DATA_VARIABLE, str(root))
    return root


@pytest.fixture
def processes() -> Iterator[list[subprocess.Popen[str]]]:
    """The processes a test started; whichever still runs at its end is
    ended there."""
    running: list[subprocess.Popen[str]] = []
    yield running
    for process in running:
        if process.poll() is None:
            process.kill()
        process.wait()
        if process.stdout is not None:
            process.stdout.close()


def note(port: int, pid: int, *, written: float | None = None) -> Path:
    """The note of a service on ``port`` naming ``pid`` — written now, or
    at the time given."""
    file = service.note_file(port)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps({"pid": pid, "port": port}), encoding="utf-8")
    if written is not None:
        os.utime(file, (written, written))
    return file


def test_a_stranger_that_inherited_the_number_gets_no_signal(
    data_root: Path,
    processes: list[subprocess.Popen[str]],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The port answers — some program listens there.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        # The note of a service that is long gone, and a process that began
        # just now under the number the note names.
        stranger = subprocess.Popen([sys.executable, "-c", IDLE], text=True)
        processes.append(stranger)
        note(port, stranger.pid, written=time.time() - HOUR)

        assert stop(port, tmp_path) == 0

    assert stranger.poll() is None, "the stranger was ended"
    assert capsys.readouterr().out == Texts("en").t("cli.service_not_running", port=port) + "\n"


def test_the_process_that_wrote_the_note_is_ended_as_ever(
    data_root: Path,
    processes: list[subprocess.Popen[str]],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    port = free_port()
    running = subprocess.Popen(
        [sys.executable, "-c", LISTENING, str(port)], stdout=subprocess.PIPE, text=True
    )
    processes.append(running)
    assert running.stdout is not None and running.stdout.readline().strip() == "listening"
    # Written after the process began, the way a service writes it.
    note(port, running.pid)

    assert stop(port, tmp_path) == 0

    assert running.wait(service.STOP_WAIT_SECONDS) != 0
    assert capsys.readouterr().out == Texts("en").t("cli.service_stopped", port=port) + "\n"


# A program that answers every GET with the status and body it is given,
# the way a service answers its open health address.
HEALTH = (
    "import http.server, sys\n"
    "status, body = int(sys.argv[2]), sys.argv[3].encode()\n"
    "class Handler(http.server.BaseHTTPRequestHandler):\n"
    "    def do_GET(self):\n"
    "        self.send_response(status)\n"
    "        self.send_header('Content-Type', 'application/json')\n"
    "        self.send_header('Content-Length', str(len(body)))\n"
    "        self.end_headers()\n"
    "        self.wfile.write(body)\n"
    "    def log_message(self, *args):\n"
    "        pass\n"
    "server = http.server.HTTPServer(('127.0.0.1', int(sys.argv[1])), Handler)\n"
    "print('listening', flush=True)\n"
    "server.serve_forever()\n"
)

SERVICE_HEALTH = '{"status": "ok", "version": "0.6.11", "datenbank": {"erreichbar": true}}'


def answering_with(
    processes: list[subprocess.Popen[str]], status: int, body: str
) -> tuple[int, subprocess.Popen[str]]:
    """A program on a free port that answers the health address with the
    status and body given, and the port it is on."""
    port = free_port()
    program = subprocess.Popen(
        [sys.executable, "-c", HEALTH, str(port), str(status), body],
        stdout=subprocess.PIPE,
        text=True,
    )
    processes.append(program)
    assert program.stdout is not None and program.stdout.readline().strip() == "listening"
    return port, program


def test_a_service_that_left_no_note_here_is_not_reported_as_absent(
    data_root: Path,
    processes: list[subprocess.Popen[str]],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A service whose configuration names a data folder of its own writes its
    note there. Nothing is found here, but it answers: it is still running,
    and nobody gets a signal."""
    port, running = answering_with(processes, 200, SERVICE_HEALTH)

    assert stop(port, tmp_path) == 1

    assert running.poll() is None, "the service was ended"
    assert capsys.readouterr().err == Texts("en").t("cli.service_not_stopped", port=port) + "\n"


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (200, '{"hello": "world"}'),
        (200, '{"version": ""}'),
        (200, "[1, 2]"),
        (200, "not json"),
        (404, '{"version": "1.0"}'),
    ],
)
def test_another_program_on_the_port_is_still_reported_as_absent(
    data_root: Path,
    processes: list[subprocess.Popen[str]],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    status: int,
    body: str,
) -> None:
    port, stranger = answering_with(processes, status, body)

    assert stop(port, tmp_path) == 0

    assert stranger.poll() is None
    assert capsys.readouterr().out == Texts("en").t("cli.service_not_running", port=port) + "\n"


def test_a_note_of_a_stranger_does_not_hide_a_service_that_answers(
    data_root: Path,
    processes: list[subprocess.Popen[str]],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The note names a process that began after it was written — the number
    was handed on — while the service itself answers at the port."""
    port, running = answering_with(processes, 200, SERVICE_HEALTH)
    stranger = subprocess.Popen([sys.executable, "-c", IDLE], text=True)
    processes.append(stranger)
    note(port, stranger.pid, written=time.time() - HOUR)

    assert stop(port, tmp_path) == 1

    assert stranger.poll() is None and running.poll() is None
    assert capsys.readouterr().err == Texts("en").t("cli.service_not_stopped", port=port) + "\n"


def test_a_note_that_names_no_running_process_proves_nothing(
    data_root: Path, processes: list[subprocess.Popen[str]]
) -> None:
    gone = subprocess.Popen([sys.executable, "-c", "pass"], text=True)
    processes.append(gone)
    gone.wait()
    file = note(8123, gone.pid)
    assert service.began(gone.pid) is None
    assert service.wrote(gone.pid, file) is False


def test_a_process_is_only_the_writer_of_a_note_that_is_there(data_root: Path) -> None:
    assert service.wrote(os.getpid(), service.note_file(8123)) is False


def test_the_system_says_when_a_process_began() -> None:
    began = service.began(os.getpid())
    assert began is not None
    # This process began before now, and not before the machine's clock did.
    assert 0 < began <= time.time()


def test_the_proof_goes_by_the_time_the_note_was_written(
    data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = note(8123, 4242, written=1_000_000.0)
    # There before the note was: its writer.
    monkeypatch.setattr(service, "began", lambda pid: 999_000.0)
    assert service.wrote(4242, file) is True
    # Within the second the process list rounds to: still its writer.
    monkeypatch.setattr(service, "began", lambda pid: 1_000_000.9)
    assert service.wrote(4242, file) is True
    # Begun after the note was written: a stranger.
    monkeypatch.setattr(service, "began", lambda pid: 1_000_002.0)
    assert service.wrote(4242, file) is False


@pytest.mark.parametrize(
    ("listed", "seconds"),
    [
        ("00:05", 5.0),
        ("12:34", 754.0),
        ("01:02:03", 3723.0),
        ("2-03:04:05", 183845.0),
        ("", None),
        ("soon", None),
        ("1:2:3:4", None),
        ("x-00:01", None),
    ],
)
def test_a_running_time_is_read_as_the_process_list_writes_it(
    listed: str, seconds: float | None
) -> None:
    assert service._elapsed(listed) == seconds
