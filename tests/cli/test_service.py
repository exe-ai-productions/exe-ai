"""The service from the client's side: where none answers at an address of
this machine, one is started cut loose from the terminal and waited for;
where one answers, or where the address is another machine's, none is
started; ``service run`` runs it on this terminal instead of a chat,
``service start`` starts it in the background and ends, ``service status``
says whether it runs and since when."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from cli import service
from cli.texts import Texts
from cli.main import main
from test_app_scaffold import SAFETY_NET_SECONDS, Service

OWN_ADDRESS = "http://127.0.0.1:8123"
FOREIGN_ADDRESS = "http://100.100.0.9:8123"
ENTER = "\r"


class Outside:
    """The outside world: no service until one has been started — then the
    scaffold's stand-in answers."""

    def __init__(self) -> None:
        self.started = False
        self.service = Service()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if not self.started:
            raise httpx.ConnectError("connection refused", request=request)
        return self.service(request)


class Process:
    """What the stand-in for starting a process hands back."""

    def __init__(self, returncode: int | None) -> None:
        self.returncode = returncode
        self.told_to_end = 0

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.told_to_end += 1

    def wait(self) -> int:
        return self.returncode or 0


class Started:
    """What the stand-in for starting a process kept: every command with
    its keyword arguments. ``outside`` is set by the test that wants the
    service to answer from the start on; ``exits`` lets the process end at
    once with that code."""

    def __init__(self) -> None:
        self.kept: list[tuple[list[str], dict[str, Any]]] = []
        self.outside: Outside | None = None
        self.exits: int | None = None
        self.processes: list[Process] = []

    def popen(self, command: list[str], **kwargs: Any) -> Process:
        self.kept.append((command, kwargs))
        if self.outside is not None:
            self.outside.started = True
        self.processes.append(Process(self.exits))
        return self.processes[-1]


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> Started:
    """Replaces starting a process with keeping what would have been
    started, and takes the pauses out of the waits."""
    stand_in = Started()
    monkeypatch.setattr(service.subprocess, "Popen", stand_in.popen)
    monkeypatch.setattr(service, "START_POLL_SECONDS", 0.0)
    return stand_in


def run(
    typed: str, *arguments: str, outside: httpx.MockTransport | Outside | Service, tmp_path: Path
) -> int:
    """The client with ``typed`` already waiting in its input, against
    whatever ``outside`` answers."""
    with create_pipe_input() as pipe:
        pipe.send_text(typed)
        safety_net = threading.Timer(SAFETY_NET_SECONDS, pipe.close)
        safety_net.start()
        try:
            with create_app_session(input=pipe, output=DummyOutput()):
                return main(
                    [*arguments, "--lang", "en"],
                    http=httpx.Client(transport=httpx.MockTransport(outside)),
                    prefs_path=tmp_path / "cli.json",
                )
        finally:
            safety_net.cancel()


def test_without_a_service_the_own_address_starts_one_cut_loose_and_waits_for_its_page(
    started, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = Outside()
    started.outside = outside

    assert run(f"/quit{ENTER}", "--url", OWN_ADDRESS, outside=outside, tmp_path=tmp_path) == 0

    assert len(started.kept) == 1
    command, kwargs = started.kept[0]
    assert command == [sys.executable, str(service.START_SCRIPT), service.SERVE_FLAG]
    assert kwargs["env"][service.PORT_VARIABLE] == "8123"
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL
    if sys.platform == "win32":
        assert kwargs["creationflags"]
    else:
        assert kwargs["start_new_session"] is True
    assert "Starting the service at http://127.0.0.1:8123" in capsys.readouterr().out
    # And the client went on to talk to it.
    assert "GET /api/v1/health" in outside.service.paths()


def test_a_running_service_is_never_started_a_second_time(started, tmp_path: Path) -> None:
    assert run(f"/quit{ENTER}", "--url", OWN_ADDRESS, outside=Service(), tmp_path=tmp_path) == 0
    assert started.kept == []


def test_a_foreign_address_never_starts_a_service(
    started, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = Outside()
    started.outside = outside

    assert run("", "--url", FOREIGN_ADDRESS, outside=outside, tmp_path=tmp_path) == 1

    assert started.kept == []
    assert outside.started is False
    assert "The service is not answering: http://100.100.0.9:8123" in capsys.readouterr().err


def test_an_address_without_a_port_starts_nothing(
    started, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = Outside()
    started.outside = outside

    assert run("", "--url", "http://localhost", outside=outside, tmp_path=tmp_path) == 1

    assert started.kept == []
    assert "not answering" in capsys.readouterr().err


def test_a_process_that_ends_at_once_ends_the_wait(
    started, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    started.exits = 1

    assert run("", "--url", OWN_ADDRESS, outside=Outside(), tmp_path=tmp_path) == 1

    assert len(started.kept) == 1
    assert Texts("en").t("cli.service_start_failed", address="http://127.0.0.1:8123") in capsys.readouterr().err


INTERFACE_SENTENCE = "The interface is missing"


def _without_interface(request: httpx.Request) -> httpx.Response:
    """A service that came up and answers, but has no page built."""
    return httpx.Response(404, json={"detail": INTERFACE_SENTENCE})


def test_a_started_service_without_its_interface_is_not_waited_for(
    started, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("", "--url", OWN_ADDRESS, outside=_without_interface, tmp_path=tmp_path) == 1

    # Ended like at the interrupt key, and its own sentence came first.
    assert len(started.processes) == 1 and started.processes[0].told_to_end == 1
    said = capsys.readouterr().err.splitlines()
    assert said == [
        INTERFACE_SENTENCE,
        Texts("en").t("cli.service_start_failed", address=OWN_ADDRESS),
    ]


def test_service_start_without_its_interface_says_so_ends_the_service_and_fails(
    started, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("", "service", "start", "--url", OWN_ADDRESS, outside=_without_interface, tmp_path=tmp_path) == 1

    assert len(started.processes) == 1 and started.processes[0].told_to_end == 1
    said = capsys.readouterr().err.splitlines()
    assert said == [
        INTERFACE_SENTENCE,
        Texts("en").t("cli.service_start_failed", address=OWN_ADDRESS),
    ]


def test_silence_a_404_without_a_sentence_of_the_service_is_still_waited_out(
    started, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Anything but the service's own sentence is no news about its page: the
    wait goes on while the process lives, and ends when it ends."""
    started.exits = 1

    def plain_404(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    assert run("", "--url", OWN_ADDRESS, outside=plain_404, tmp_path=tmp_path) == 1

    assert started.processes[0].told_to_end == 0
    assert capsys.readouterr().err.splitlines() == [
        Texts("en").t("cli.service_start_failed", address=OWN_ADDRESS)
    ]


def test_serve_runs_the_service_on_this_terminal_and_answers_with_its_code(
    started, tmp_path: Path
) -> None:
    started.exits = 3

    assert run("", "service", "run", "--url", OWN_ADDRESS, outside=Outside(), tmp_path=tmp_path) == 3

    command, kwargs = started.kept[0]
    assert command == [sys.executable, str(service.START_SCRIPT), service.SERVE_FLAG]
    assert kwargs["env"][service.PORT_VARIABLE] == "8123"
    # On this terminal: the service keeps the streams, nothing is cut loose.
    assert "stdout" not in kwargs
    assert "start_new_session" not in kwargs


def test_serve_with_a_service_already_answering_starts_none_and_says_so(
    started, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("", "service", "run", "--url", OWN_ADDRESS, outside=Service(), tmp_path=tmp_path) == 1

    assert started.kept == []
    assert "A service is already running at http://127.0.0.1:8123." in capsys.readouterr().err


def test_serve_serves_at_the_address_given_host_and_port_alike(started, tmp_path: Path) -> None:
    """A network address is served at as well: the service then insists on
    its password (app/anmeldung.py), which travels as the file named."""
    file = tmp_path / "password.txt"
    file.write_text("open-sesame\n", encoding="utf-8")
    assert (
        run(
            "", "service", "run", "--url", FOREIGN_ADDRESS, "--password-file", str(file),
            outside=Outside(), tmp_path=tmp_path,
        )
        == 0
    )

    command, kwargs = started.kept[0]
    assert command == [sys.executable, str(service.START_SCRIPT), service.SERVE_FLAG]
    assert kwargs["env"][service.HOST_VARIABLE] == "100.100.0.9"
    assert kwargs["env"][service.PORT_VARIABLE] == "8123"
    assert kwargs["env"][service.PASSWORD_FILE_VARIABLE] == str(file.resolve())


def test_serve_without_a_password_file_names_none_to_the_service(started, tmp_path: Path) -> None:
    assert run("", "service", "run", "--url", OWN_ADDRESS, outside=Outside(), tmp_path=tmp_path) == 0
    command, kwargs = started.kept[0]
    assert service.PASSWORD_FILE_VARIABLE not in kwargs["env"]
    assert kwargs["env"][service.HOST_VARIABLE] == "127.0.0.1"


def test_serve_at_an_address_without_a_port_says_what_url_takes(
    started, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("", "service", "run", "--url", "http://localhost", outside=Outside(), tmp_path=tmp_path) == 2
    assert started.kept == []
    assert "http://127.0.0.1:8090" in capsys.readouterr().err


# --- service start, service status ------------------------------------------------

# A moment the service says its process began at, and how it stands in the
# clock of this machine.
BEGAN = 1_760_000_000.0


class Naming(Service):
    """A service that names its process, as the real one does."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        answered = super().__call__(request)
        if request.url.path == "/api/v1/health" and answered.status_code == 200:
            return httpx.Response(
                200, json={**answered.json(), "process": {"pid": 4242, "began": BEGAN}}
            )
        return answered


class NamingOutside(Outside):
    def __init__(self) -> None:
        super().__init__()
        self.service = Naming()


def _since() -> str:
    return datetime.fromtimestamp(BEGAN).strftime("%Y-%m-%d %H:%M")


def test_start_starts_the_service_cut_loose_waits_for_it_and_writes_since_when_it_runs(
    started, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = NamingOutside()
    started.outside = outside

    assert run("", "service", "start", "--url", OWN_ADDRESS, outside=outside, tmp_path=tmp_path) == 0

    assert len(started.kept) == 1
    command, kwargs = started.kept[0]
    assert command == [sys.executable, str(service.START_SCRIPT), service.SERVE_FLAG]
    assert kwargs["stdout"] is subprocess.DEVNULL
    if sys.platform != "win32":
        assert kwargs["start_new_session"] is True
    said = capsys.readouterr().out.splitlines()
    assert said == [
        Texts("en").t("cli.service_starting", address=OWN_ADDRESS),
        Texts("en").t("cli.service_since", address=OWN_ADDRESS, time=_since()),
    ]
    # No chat: the program ended with the line, the service goes on.
    assert not any(path.startswith("POST /api/v1/chats") for path in outside.service.paths())


def test_start_with_a_service_answering_starts_none_and_says_so(
    started, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("", "service", "start", "--url", OWN_ADDRESS, outside=Service(), tmp_path=tmp_path) == 1
    assert started.kept == []
    assert capsys.readouterr().err == Texts("en").t("cli.service_running", address=OWN_ADDRESS) + "\n"


def test_start_at_another_machines_address_starts_nothing(
    started, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = Outside()
    started.outside = outside
    assert run("", "service", "start", "--url", FOREIGN_ADDRESS, outside=outside, tmp_path=tmp_path) == 1
    assert started.kept == []
    assert Texts("en").t("cli.service_start_failed", address=FOREIGN_ADDRESS) in capsys.readouterr().err


def test_start_with_a_process_that_ends_at_once_says_it_did_not_start(
    started, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    started.exits = 1
    assert run("", "service", "start", "--url", OWN_ADDRESS, outside=Outside(), tmp_path=tmp_path) == 1
    assert Texts("en").t("cli.service_start_failed", address=OWN_ADDRESS) in capsys.readouterr().err


def test_start_carries_the_password_file_to_the_service(started, tmp_path: Path) -> None:
    file = tmp_path / "password.txt"
    file.write_text("open-sesame\n", encoding="utf-8")
    outside = NamingOutside()
    started.outside = outside
    assert (
        run(
            "", "service", "start", "--url", OWN_ADDRESS, "--password-file", str(file),
            outside=outside, tmp_path=tmp_path,
        )
        == 0
    )
    assert started.kept[0][1]["env"][service.PASSWORD_FILE_VARIABLE] == str(file.resolve())


def test_start_at_an_address_without_a_port_says_what_url_takes(
    started, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("", "service", "start", "--url", "http://localhost", outside=Outside(), tmp_path=tmp_path) == 2
    assert started.kept == []
    assert "http://127.0.0.1:8090" in capsys.readouterr().err


def test_status_of_a_running_service_writes_where_and_since_when_with_code_zero(
    started, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("", "service", "status", "--url", OWN_ADDRESS, outside=Naming(), tmp_path=tmp_path) == 0
    assert capsys.readouterr().out == (
        Texts("en").t("cli.service_since", address=OWN_ADDRESS, time=_since()) + "\n"
    )
    assert started.kept == []


def test_status_without_a_service_says_so_with_code_one_and_starts_none(
    started, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("", "service", "status", "--url", OWN_ADDRESS, outside=Outside(), tmp_path=tmp_path) == 1
    assert capsys.readouterr().out == Texts("en").t("cli.service_not_running", port=8123) + "\n"
    assert started.kept == []


def test_status_of_a_service_that_names_no_process_says_that_it_is_there(
    started, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("", "service", "status", "--url", OWN_ADDRESS, outside=Service(), tmp_path=tmp_path) == 0
    assert capsys.readouterr().out == Texts("en").t("cli.service_running", address=OWN_ADDRESS) + "\n"


def test_the_command_is_the_program_in_its_service_role(monkeypatch: pytest.MonkeyPatch) -> None:
    assert service.command() == [sys.executable, str(service.START_SCRIPT), "--serve"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert service.command() == [sys.executable, "--serve"]


def test_packaged_the_service_is_started_as_an_instance_of_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """Packaged into one file, a process started from the program shares the
    folder its starter unpacked, and that folder goes when the starter ends.
    The service outlives the client, so its environment says it is on its
    own — in both ways the client starts one. From source there is no such
    folder, and the environment says nothing."""
    monkeypatch.delenv(service.OWN_INSTANCE_VARIABLE, raising=False)
    assert service.OWN_INSTANCE_VARIABLE not in service._environment(8123, None)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert service._environment(8123, None)[service.OWN_INSTANCE_VARIABLE] == "1"
    assert service._environment(8123, None, "100.100.0.9")[service.OWN_INSTANCE_VARIABLE] == "1"


@pytest.mark.parametrize(
    ("address", "own", "port"),
    [
        ("http://127.0.0.1:8090", True, 8090),
        ("http://localhost:8123", True, 8123),
        ("http://[::1]:8123", True, 8123),
        ("http://LOCALHOST:8123/", True, 8123),
        ("http://100.100.0.9:8123", False, 8123),
        ("http://exe.example:8123", False, 8123),
        ("http://localhost", True, None),
        ("http://localhost:port", True, None),
    ],
)
def test_which_addresses_are_this_machines(address: str, own: bool, port: int | None) -> None:
    assert service.is_own(address) is own
    assert service.port_of(address) == port


# --- Whether a service runs on this machine ----------------------------------------


def health(process: Any) -> dict[str, Any]:
    """What a service says about how it is, with that about its process."""
    return {"status": "ok", "version": "9.8.7", "process": process}


def this_process() -> dict[str, Any]:
    """The test's own process, as the system's process list knows it."""
    began = service.began(os.getpid())
    assert began is not None
    return {"pid": os.getpid(), "began": began}


def test_a_service_that_names_a_process_of_this_machine_with_its_beginning_runs_here() -> None:
    assert service.runs_here(health(this_process())) is True


def test_a_service_that_names_a_process_this_machine_does_not_have_runs_elsewhere() -> None:
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    here = this_process()
    assert service.runs_here(health({"pid": gone.pid, "began": here["began"]})) is False


@pytest.mark.parametrize("apart", [-3600.0, 3600.0])
def test_the_number_of_a_process_here_with_another_beginning_is_a_process_elsewhere(
    apart: float,
) -> None:
    """Every machine counts its processes from one: a service elsewhere may
    well have the number of a process that runs here."""
    here = this_process()
    named = {"pid": here["pid"], "began": here["began"] + apart}
    assert service.runs_here(health(named)) is False


@pytest.mark.parametrize(
    ("seconds_apart", "here"),
    [(0.0, True), (1.0, True), (-1.0, True), (2.0, True), (-2.0, True), (2.5, False), (-2.5, False)],
)
def test_two_readings_of_one_beginning_may_lie_twice_the_tolerance_apart(
    seconds_apart: float, here: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the service says of itself is compared with the client's own
    reading, which may lie twice the tolerance away from it, and no further."""
    monkeypatch.setattr(service, "began", lambda pid: 1_000_000.0)
    named = {"pid": 4242, "began": 1_000_000.0 + seconds_apart}
    assert service.runs_here(health(named)) is here


def test_asking_whether_a_service_runs_here_starts_no_program(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not the process list, not a shell: every new chat asks, and on Windows
    a shell takes its time to start."""

    def refused(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"a program was started: {args!r}")

    monkeypatch.setattr(subprocess, "run", refused)
    monkeypatch.setattr(subprocess, "Popen", refused)
    for platform in ("linux", "darwin", "win32"):
        monkeypatch.setattr(sys, "platform", platform)
        assert service.runs_here(health(this_process())) is True
    # A service elsewhere stays elsewhere.
    assert service.runs_here(health({"pid": os.getpid(), "began": 1.0})) is False


@pytest.mark.parametrize(
    "beginning", [float("nan"), float("inf"), float("-inf"), 10**400, -(10**400)]
)
def test_a_beginning_that_is_no_point_in_time_is_no_beginning(
    beginning: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What a service sends is read as it comes, and a whole number may be
    longer than any number a moment in time is counted in."""
    monkeypatch.setattr(service, "began", lambda pid: 1_000_000.0)
    assert service.runs_here(health({"pid": 4242, "began": beginning})) is False


@pytest.mark.parametrize(
    "said",
    [
        None,
        "ok",
        [],
        {},
        {"status": "ok", "version": "9.8.7"},
        health(None),
        health("4242"),
        health([4242, 1.0]),
        health({}),
        health({"pid": 4242}),
        health({"began": 1.0}),
        health({"pid": "4242", "began": 1.0}),
        health({"pid": 4242.0, "began": 1.0}),
        health({"pid": 4242, "began": "then"}),
        health({"pid": 4242, "began": None}),
        health({"pid": True, "began": 1.0}),
        health({"pid": 4242, "began": True}),
    ],
)
def test_a_service_that_names_no_process_runs_elsewhere_and_the_system_is_not_asked(
    said: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing, an older service without the word, or something that is no
    number and no time: there is no process to look for."""

    def asked(pid: int) -> float | None:
        raise AssertionError(f"the process list was asked about {pid!r}")

    monkeypatch.setattr(service, "began", asked)
    assert service.runs_here(said) is False


def test_silence_probe_a_service_is_still_started_only_under_a_name_of_this_machine(
    started, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Where a service may be started is another question than where one
    runs: nothing answers yet, so nothing says which process it is. A
    silent address that is no name of this machine starts nothing, as
    before — whatever a service would say of itself."""
    monkeypatch.setattr(service, "runs_here", lambda said: True)
    outside = Outside()
    started.outside = outside

    assert run("", "--url", FOREIGN_ADDRESS, outside=outside, tmp_path=tmp_path) == 1

    assert started.kept == []
    assert outside.started is False
