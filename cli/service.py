"""The service from the client's side: started without a window where none
answers, run in the foreground for servers, and stopped again.

The client is a client. The service is the one program in another of its
roles (``start.py --serve``: the service alone, no window), and what is
started here is that program — cut loose from the terminal, so that it
outlives the client that started it. The next client, and the window, find
it running and attach to it instead of starting a second one.

Nothing of the service's code is imported for this; what the client needs
to know about it (where the port comes from, where the note about a running
service lies) is read the way the window's shell reads it.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import psutil

from cli.client import InterfaceMissing, ServiceClient, ServiceUnreachable

# The program in its service role: packaged, the program itself; from source,
# the script at the root of the tree, run by the interpreter of this client.
START_SCRIPT = Path(__file__).resolve().parent.parent / "start.py"
SERVE_FLAG = "--serve"

# Where the service reads its port from (app/config.py, ``EXE_AI_PORT``),
# where it keeps its data (app/paketierung.py, ``EXE_AI_DATEN``) and where
# it reads the file holding its password (app/anmeldung.py).
PORT_VARIABLE = "EXE_AI_PORT"
HOST_VARIABLE = "EXE_AI_HOST"
DATA_VARIABLE = "EXE_AI_DATEN"
PASSWORD_FILE_VARIABLE = "EXE_AI_PASSWORD_FILE"

# What tells a packaged program, started from itself, to be an instance of
# its own. By default a second process started from the first counts as its
# helper and takes over what the first one set up for itself — right for a
# helper, which ends before its starter does. The service outlives this
# client, so it starts as a program of its own.
OWN_INSTANCE_VARIABLE = "PYINSTALLER_RESET_ENVIRONMENT"

# The service's own name for the note it writes about itself while it runs
# (app/main.py, ``INSTANZNOTIZ``: its process id, its port and when its process
# began) and the data
# folder under the root it writes it into (config.example.yaml, ``data_dir``).
NOTE_PREFIX = ".dienst"
DATA_FOLDER = "data"

# The names under which an address means this machine. Only there can a
# service be started or stopped: a process on another machine is out of
# reach of a signal, and a port there is not ours to serve on.
OWN_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
# The addresses that mean "every address of this machine" in a bind.
UNSPECIFIED_HOSTS = frozenset({"0.0.0.0", "::", ""})

# The pause between two looks at a freshly started service — the one the
# program itself takes while it waits for its port before it opens the
# window (start.py, ``_browser_oeffnen``).
START_POLL_SECONDS = 0.3

# How long a stopped service gets to let go of its port: twenty looks of
# half a second — room for a shutdown that first cuts a running request
# short (start.py, three seconds) and then stops the model server.
STOP_WAIT_SECONDS = 10.0
STOP_POLL_SECONDS = 0.5

# How a connection test waits for the port, the service's own figure
# (app/main.py, ``_antwortet``).
PROBE_SECONDS = 0.4

# How far two readings of one process's start may lie apart: the service wrote
# its own and this client reads it again — on Linux both are worked out from
# the time the machine booted, which a clock set in between moves. A service
# of an earlier build read its beginning from the process list, which counts
# whole seconds, so the comparison with what a service says of itself allows
# twice that.
START_TOLERANCE_SECONDS = 1.0

# Where the request to end a service lies on Windows (app/stoppmarke.py): the
# note's name with another ending. There, a termination signal is the end of
# the process with no shutdown, so the service is asked to end itself, and
# only a service that does not answer in time is ended from outside.
STOP_REQUEST_SUFFIX = ".stop"

# What ``stop`` says happened.
STOPPED = "stopped"
NOT_RUNNING = "not running"
STILL_RUNNING = "still running"


def is_own(address: str) -> bool:
    """Whether the address names this machine."""
    host = urlsplit(address).hostname
    return host is not None and host.lower() in OWN_HOSTS


def host_of(address: str) -> str:
    """The host the address names; empty where it names none."""
    return urlsplit(address).hostname or ""


def port_of(address: str) -> int | None:
    """The port the address names, or ``None`` where it names none or one
    that is no port."""
    try:
        return urlsplit(address).port
    except ValueError:
        return None


def command() -> list[str]:
    """What starts the service."""
    if getattr(sys, "frozen", False):
        return [sys.executable, SERVE_FLAG]
    return [sys.executable, str(START_SCRIPT), SERVE_FLAG]


def _environment(
    port: int, password_file: Path | None, host: str | None = None
) -> dict[str, str]:
    """This client's environment, with the port the service is to take —
    and the host, where the service is to listen at an address of the
    caller's choosing — and, where one was named, the file holding its
    password: the file, never the word, an argument shows in every process
    listing. Packaged, the service is told to be an instance of its own."""
    environment = dict(os.environ)
    environment[PORT_VARIABLE] = str(port)
    if getattr(sys, "frozen", False):
        environment[OWN_INSTANCE_VARIABLE] = "1"
    if host:
        environment[HOST_VARIABLE] = host
    if password_file is not None:
        environment[PASSWORD_FILE_VARIABLE] = str(password_file.resolve())
    return environment


def start_detached(port: int, password_file: Path | None = None) -> subprocess.Popen[bytes]:
    """Starts the service on ``port`` as a process of its own, cut loose from
    this terminal: in a session of its own, so that neither a hang-up nor an
    interrupt here reaches it, and without this client's streams — it writes
    its own log file."""
    loose: dict[str, Any] = {}
    if sys.platform == "win32":
        loose["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        loose["start_new_session"] = True
    return subprocess.Popen(
        command(),
        env=_environment(port, password_file),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **loose,
    )


def start_and_wait(
    client: ServiceClient, port: int, password_file: Path | None = None
) -> bool:
    """Starts the service and waits until its page answers — for as long as
    the started process lives: how long a start takes is the machine's
    call, and a service given up on would come up later with nobody
    attached to it. ``False`` when the process ended first. An interrupt
    from the keyboard ends the wait and the service that was started for
    it, and is raised on. A service that answers that its interface is
    missing is ended the same way, and ``InterfaceMissing`` is raised."""
    process = start_detached(port, password_file)
    try:
        while True:
            try:
                client.connect()
                return True
            except InterfaceMissing:
                # It answers, and says that its page is not built: nothing
                # more will come of waiting. The one that was started is
                # ended like at the interrupt key, and the sentence goes on.
                process.terminate()
                process.wait()
                raise
            except ServiceUnreachable:
                pass
            if process.poll() is not None:
                return False
            time.sleep(START_POLL_SECONDS)
    except KeyboardInterrupt:
        # Cut loose from this terminal, the service did not hear the
        # interrupt: it is told to end, and waited for.
        process.terminate()
        process.wait()
        raise


def serve(host: str, port: int, password_file: Path | None = None) -> int:
    """Runs the service on this terminal, at the address given, until it
    ends, and answers with its exit code. Beyond the loopback address the
    service itself insists on the password file. An interrupt from the
    keyboard reaches the service directly; the client then only waits for
    it to finish shutting down."""
    process = subprocess.Popen(command(), env=_environment(port, password_file, host))
    while True:
        try:
            return process.wait()
        except KeyboardInterrupt:
            # The interrupt reached the service as well; it is shutting
            # down, and a second one changes nothing about that.
            continue


def data_root() -> Path:
    """The root the service keeps its data under, resolved the way the
    service itself does it (app/paketierung.py, ``daten``) and the window's
    shell does it after it (fenster-electron/dienstsuche.js): the folder
    ``EXE_AI_DATEN`` names, else the system's place for the packaged program,
    else the source tree. A service given another data folder in its own
    configuration file leaves no note here."""
    own = os.environ.get(DATA_VARIABLE, "").strip()
    if own:
        return Path(own).expanduser()
    if not getattr(sys, "frozen", False):
        return START_SCRIPT.parent
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Exe AI Terminal"
    if sys.platform == "win32":
        return Path.home() / "AppData" / "Roaming" / "Exe AI Terminal"
    return Path.home() / ".local" / "share" / "exe-ai-terminal"


def note_file(port: int) -> Path:
    """Where the note of a service on ``port`` lies."""
    return data_root() / DATA_FOLDER / f"{NOTE_PREFIX}-{port}.json"


def read_note(file: Path) -> int | None:
    """The process id the note names, or ``None`` where there is no readable
    note: half a file, a folder, a stranger's format are all none."""
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
        return int(data["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def read_beginning(file: Path) -> float | None:
    """The moment the note says its process began, in seconds since the
    epoch — ``None`` where the note says none: a note of an older service, or
    no readable note."""
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
        beginning = data["began"]
        if isinstance(beginning, bool) or not isinstance(beginning, (int, float)):
            return None
        return float(beginning)
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        # A whole number beyond any moment in time is none.
        return None


def began(pid: int) -> float | None:
    """When the process behind ``pid`` began, in seconds since the epoch —
    ``None`` where there is no such process or the system does not say. Read
    from the system by the process library, with no program of the system's
    started and no clock reckoned from."""
    try:
        return psutil.Process(int(pid)).create_time()
    except (psutil.Error, OSError, OverflowError, ValueError):
        return None


def wrote(pid: int, note: Path) -> bool:
    """Whether the process behind ``pid`` is the one that wrote the note.

    A service writes into its note when its own process began. The system
    hands the id of a process that is gone on to a later one, and that one
    has begun at another time: only the process that began at the moment the
    note names wrote it. A note that names no beginning proves nothing, and
    neither does a system that does not say when the process began."""
    claimed = read_beginning(note)
    start = began(pid)
    if claimed is None or start is None:
        return False
    return abs(start - claimed) <= START_TOLERANCE_SECONDS


def runs_here(said: Any) -> bool:
    """Whether the service that said this about itself runs on this
    machine, whatever the name of the address it was asked at.

    A service names its process in what it says about its health
    (``process``): the number the system gave it, and when that process
    began. Only on the service's own machine does the system know a process
    of that number that began then. The number alone would prove nothing —
    every machine counts its own, and hands the number of a process that is
    gone on to a later one. The service read its beginning as it is read here,
    so the two readings may lie twice ``START_TOLERANCE_SECONDS`` apart. A service
    that names no process, or one this machine does not know, is a service
    elsewhere.
    """
    named = said.get("process") if isinstance(said, dict) else None
    if not isinstance(named, dict):
        return False
    pid, claimed = named.get("pid"), named.get("began")
    # A truth value is a number to the language and none to a process list.
    if isinstance(pid, bool) or isinstance(claimed, bool):
        return False
    if not isinstance(pid, int) or not isinstance(claimed, (int, float)):
        return False
    start = began(pid)
    if start is None:
        return False
    try:
        apart = abs(start - claimed)
    except OverflowError:
        # A whole number beyond any moment in time.
        return False
    return apart <= 2 * START_TOLERANCE_SECONDS


def answering(host: str, port: int) -> bool:
    """Is something listening on that port? Whichever family the host
    belongs to — ``::1`` is as much this machine as ``127.0.0.1``."""
    try:
        with socket.create_connection((host, port), timeout=PROBE_SECONDS):
            return True
    except OSError:
        return False


def says_its_version(host: str, port: int) -> bool:
    """Whether what listens on the port is a service of this program, told
    the way the window's shell tells it (fenster-electron/dienstsuche.js):
    its open health address answers a complete 200 with a ``version`` text.
    Anything else — silence, another status, another program's answer —
    is not one."""
    shown = f"[{host}]" if ":" in host else host
    try:
        answer = httpx.get(f"http://{shown}:{port}/health", timeout=PROBE_SECONDS, trust_env=False)
        version = answer.json().get("version")
    except (httpx.HTTPError, ValueError, AttributeError):
        return False
    return answer.status_code == 200 and isinstance(version, str) and bool(version.strip())


def _on_windows() -> bool:
    return sys.platform == "win32"


def request_file(port: int) -> Path:
    """Where the request to end the service on ``port`` is laid (Windows)."""
    return data_root() / DATA_FOLDER / f"{NOTE_PREFIX}-{port}{STOP_REQUEST_SUFFIX}"


def _wait_until_free(host: str, port: int, seconds: float) -> bool:
    """Whether the port lets go within ``seconds``."""
    deadline = time.monotonic() + seconds
    while answering(host, port):
        if time.monotonic() >= deadline:
            return False
        time.sleep(STOP_POLL_SECONDS)
    return True


def _end_tree(pid: int) -> None:
    """Ends the process and everything it started — the one call the
    program's own process stopping makes on Windows (app/prozessstopp.py)."""
    subprocess.run(
        ["taskkill", "/T", "/F", "/PID", str(pid)],
        check=False,
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _stop_on_windows(host: str, port: int, pid: int) -> str:
    """Asks the service to end itself and waits for it; only a service that
    still answers after the wait is ended from outside, with its children."""
    request = request_file(port)
    written = True
    try:
        request.parent.mkdir(parents=True, exist_ok=True)
        request.write_text("stop\n", encoding="utf-8")
    except OSError:
        written = False
    if _wait_until_free(host, port, STOP_WAIT_SECONDS):
        return STOPPED
    if written:
        request.unlink(missing_ok=True)
    _end_tree(pid)
    if _wait_until_free(host, port, STOP_WAIT_SECONDS):
        return STOPPED
    return STILL_RUNNING


def stop(host: str, port: int) -> str:
    """Stops the service on ``port``: reads its note, asks the process to end
    and waits until the port is free. The service's own shutdown takes its
    model server with it.

    The note alone proves nothing — a service that was killed leaves it
    behind, and the system may have handed its number to a stranger since.
    So only a port that answers is a service to stop, and only the process
    that began at the moment the note names is asked to end: any other is a
    stranger, and no process gets a signal. The request is a
    termination signal. On Windows, where the system knows no such signal —
    it would be the end of the process with no shutdown, and the servers the
    service started would stay behind — the service is asked through a
    marker file to end itself, and only one that does not answer in time is
    ended from outside, with its children. A process that is not ours to
    signal raises the system's own error.
    """
    # A service bound to every address is reached at the loopback one:
    # the unspecified address is no address to connect to on every system.
    if host in UNSPECIFIED_HOSTS:
        host = "127.0.0.1"
    note = note_file(port)
    pid = read_note(note)
    if not answering(host, port):
        return NOT_RUNNING
    if pid is None or not wrote(pid, note):
        # No process is proven, so none is signalled. A service that
        # answers all the same keeps running: whoever asked for the stop
        # has to be told it is not stopped, not that nothing was there.
        return STILL_RUNNING if says_its_version(host, port) else NOT_RUNNING
    if _on_windows():
        return _stop_on_windows(host, port, pid)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return NOT_RUNNING
    deadline = time.monotonic() + STOP_WAIT_SECONDS
    while answering(host, port):
        if time.monotonic() >= deadline:
            return STILL_RUNNING
        time.sleep(STOP_POLL_SECONDS)
    return STOPPED
