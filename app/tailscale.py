"""The web app over https, through Tailscale.

A phone reaches the service only over https: without it the browser keeps
dictation and "Add to Home Screen" locked. Tailscale Serve puts https, with
a certificate that is valid, in front of the service, inside the owner's
own Tailscale network and nowhere else — never Funnel, which would open it
to the internet.

Two Tailscales can do it. One the owner installed: it is used as it is, its
entries are left alone, and the service takes the port it needs beside them
— 443, or 8443 where 443 shows at something else. And one that comes with
the program: ``tailscaled`` runs in user space for this program alone, in a
folder of its own beside the data, so it asks the system for nothing — no
administrator password, no VPN permission. Whichever it is, the service
itself stays on the loopback address and nothing restarts.

Everything here is a call of the ``tailscale`` command line; the pieces that
touch the system (running a command, starting the daemon, waiting) are
handed in, so a test plays all of it without a Tailscale.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.no_console import no_window

log = logging.getLogger(__name__)

# The name the program's own Tailscale signs in with: the address is
# https://exe-ai.tailnet-name.ts.net. A second computer is named exe-ai-1 by
# Tailscale itself.
HOSTNAME = "exe-ai"

# The port Tailscale Serve takes for https, and the one it takes where the
# first shows at something else.
PREFERRED_PORT = 443
FALLBACK_PORT = 8443

# The folder, beside the program's data, the program's own Tailscale keeps
# its state in, and the names of the socket and the two programs.
STATE_FOLDER = "tailscale"
SOCKET_NAME = "tailscaled.sock"
CLIENT_NAME = "tailscale"
DAEMON_NAME = "tailscaled"

# Where the owner's own Tailscale keeps its command line on each system.
OWN_COMMANDS = (
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    r"C:\Program Files\Tailscale\tailscale.exe",
)

# A socket path of a unix system may be at most this long (104 on macOS); a
# longer one is moved to a short folder of the system.
SOCKET_PATH_LIMIT = 100

# How long a command may take, how long a daemon or a sign-in address is
# waited for, and how long a daemon gets to end before it is killed.
COMMAND_SECONDS = 30
LOGIN_WAIT_SECONDS = 20
END_WAIT_SECONDS = 5


# Names the folder the program's own Tailscale is in, for a trial run.
FOLDER_VARIABLE = "EXE_AI_TAILSCALE_DIR"


def program_folder() -> Path:
    """Where the program's own Tailscale ships: beside the program's other
    read-only files packaged, in the folder the build script writes to from
    a checkout."""
    named = os.environ.get(FOLDER_VARIABLE, "").strip()
    if named:
        return Path(named)
    from app import paketierung

    base = paketierung.ressourcen()
    return base / STATE_FOLDER if paketierung.ist_eingefroren() else base / "dist" / STATE_FOLDER


class TailscaleError(Exception):
    """Something Tailscale refused or does not have. ``reason`` is a short
    word the page can tell apart; ``detail`` is what Tailscale said."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class State:
    """What Tailscale is doing, as the page shows it."""

    connected: bool
    # "own" (the owner's), "builtin" (the program's) or "none" (neither is
    # there to be started).
    kind: str
    # Where a sign-in is waiting, or empty.
    login_url: str
    # The name of this computer in the network, without the trailing dot.
    host: str


def _no_state(kind: str = "none") -> State:
    return State(connected=False, kind=kind, login_url="", host="")


class Tailscale:
    def __init__(
        self,
        *,
        data_folder: Path,
        app_port: int,
        program_folder: Path | None = None,
        own_command: str | None = None,
        run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        spawn: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._state_folder = data_folder / STATE_FOLDER
        self._app_port = app_port
        self._program_folder = program_folder
        self._own_command = own_command
        self._run = run or self._run_command
        self._spawn = spawn or subprocess.Popen
        self._sleep = sleep
        # The program's own daemon, once this process started it.
        self._daemon: Any = None
        # The command of a sign-in that is under way.
        self._login: Any = None
        # Set when Tailscale is ended while a start still waits for it.
        self._cancelled = False

    def _socket(self) -> Path:
        """Where the program's own daemon listens. In its folder, unless the
        path is too long for a unix socket: then in a short one of the
        system, named after the folder so it is the same on every start."""
        inside = self._state_folder / SOCKET_NAME
        if len(str(inside)) <= SOCKET_PATH_LIMIT:
            return inside
        name = hashlib.sha1(str(self._state_folder).encode("utf-8")).hexdigest()[:10]
        return Path(tempfile.gettempdir()) / f"exe-ai-ts-{name}.sock"

    # -- Which Tailscale ---------------------------------------------------

    def _find_own(self) -> str | None:
        if self._own_command:
            return self._own_command if Path(self._own_command).exists() else None
        for candidate in OWN_COMMANDS:
            if Path(candidate).exists():
                return candidate
        return shutil.which(CLIENT_NAME)

    def _builtin(self) -> tuple[Path, Path] | None:
        """The program's own client and daemon, where they ship."""
        if self._program_folder is None:
            return None
        suffix = ".exe" if os.name == "nt" else ""
        client = self._program_folder / (CLIENT_NAME + suffix)
        daemon = self._program_folder / (DAEMON_NAME + suffix)
        return (client, daemon) if client.exists() and daemon.exists() else None

    def kind(self) -> str:
        """``own`` wherever the owner has a Tailscale, else ``builtin``
        where the program ships one, else ``none``."""
        if self._find_own():
            return "own"
        if self._builtin():
            return "builtin"
        return "none"

    def _client(self) -> list[str]:
        """The command line of the client of the Tailscale in use."""
        own = self._find_own()
        if own:
            return [own]
        builtin = self._builtin()
        if builtin is None:
            raise TailscaleError("not_available")
        return [str(builtin[0]), f"--socket={self._socket()}"]

    # -- Running a command -------------------------------------------------

    @staticmethod
    def _run_command(args: list[str], timeout: float = COMMAND_SECONDS) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=False, **no_window()
        )

    def _call(self, *args: str, timeout: float = COMMAND_SECONDS) -> subprocess.CompletedProcess[str]:
        try:
            return self._run([*self._client(), *args], timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise TailscaleError("not_answering", str(error)) from error

    def _json(self, *args: str) -> dict[str, Any]:
        done = self._call(*args)
        if done.returncode != 0:
            raise TailscaleError("failed", (done.stderr or done.stdout).strip())
        try:
            data = json.loads(done.stdout or "{}")
        except ValueError as error:
            raise TailscaleError("failed", "no JSON") from error
        return data if isinstance(data, dict) else {}

    # -- State -------------------------------------------------------------

    def state(self) -> State:
        kind = self.kind()
        if kind == "none":
            return _no_state()
        try:
            status = self._json("status", "--json")
        except TailscaleError:
            # The daemon does not answer: Tailscale is there but not running.
            return _no_state(kind)
        connected = status.get("BackendState") == "Running"
        host = str((status.get("Self") or {}).get("DNSName", "")).rstrip(".")
        return State(
            connected=connected,
            kind=kind,
            login_url="" if connected else str(status.get("AuthURL") or ""),
            host=host if connected else "",
        )

    # -- Starting ----------------------------------------------------------

    def _start_daemon(self) -> None:
        """Starts the program's own daemon and waits until it answers. One
        that answers already — left over from a run that ended badly, or
        started a moment ago — is used as it is, never started twice."""
        builtin = self._builtin()
        if builtin is None or not self._daemon_missing():
            return
        self._end(self._daemon)
        try:
            self._state_folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise TailscaleError("not_answering", str(error)) from error
        self._daemon = self._launch(
            [
                str(builtin[1]),
                "--tun=userspace-networking",
                f"--statedir={self._state_folder}",
                f"--socket={self._socket()}",
                # A port of its own, so it never fights the owner's
                # Tailscale for the usual one.
                "--port=0",
            ],
            # Its log stays in its own folder, not in the system's.
            env={**os.environ, "TS_LOGS_DIR": str(self._state_folder)},
        )
        if not self._wait_until(lambda: not self._daemon_missing()):
            raise TailscaleError("not_answering", "the daemon did not come up")

    def _wait_until(self, done: Callable[[], bool]) -> bool:
        waited = 0.0
        while waited < LOGIN_WAIT_SECONDS and not self._cancelled:
            if done():
                return True
            self._sleep(0.5)
            waited += 0.5
        return False

    def _launch(self, args: list[str], **extra: Any) -> Any:
        """Starts a program that stays: no input, no output, no console
        window. A program that cannot be started is a Tailscale that is not
        answering, not a failure of this one."""
        try:
            return self._spawn(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **no_window(),
                **extra,
            )
        except OSError as error:
            raise TailscaleError("not_answering", str(error)) from error

    @staticmethod
    def _end(process: Any) -> None:
        """Ends a program started here and waits for it, so a start straight
        after finds its socket and its folder free."""
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=END_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()

    def start(self) -> str:
        """Gets Tailscale running. Answers where a sign-in waits, or an
        empty string when it is signed in already."""
        kind = self.kind()
        if kind == "none":
            raise TailscaleError("not_available")
        self._cancelled = False
        if kind == "builtin":
            self._start_daemon()
        elif self._daemon_missing():
            self._open_own_app()
        current = self.state()
        if current.connected:
            return ""
        if current.login_url:
            return current.login_url
        arguments = ["up"]
        if kind == "builtin":
            arguments.append(f"--hostname={HOSTNAME}")
        # ``up`` stays until the sign-in is done: it is left running, and
        # the address it waits at is read from the status. One that is still
        # waiting from an earlier press is ended first.
        self._end(self._login)
        self._login = self._launch([*self._client(), *arguments])
        found: list[State] = []

        def signed_in_or_waiting() -> bool:
            current = self.state()
            if current.connected or current.login_url:
                found.append(current)
                return True
            return False

        if self._wait_until(signed_in_or_waiting):
            return "" if found[0].connected else found[0].login_url
        raise TailscaleError("no_login_address")

    def _daemon_missing(self) -> bool:
        try:
            self._json("status", "--json")
        except TailscaleError:
            return True
        return False

    def _open_own_app(self) -> None:
        """The owner's Tailscale is installed and not running: on a Mac its
        application is opened, which starts the daemon."""
        if os.name != "posix" or not Path("/Applications/Tailscale.app").exists():
            return
        try:
            subprocess.run(
                ["open", "-a", "Tailscale"], capture_output=True, timeout=COMMAND_SECONDS, check=False, **no_window()
            )
        except (OSError, subprocess.TimeoutExpired):
            return
        self._wait_until(lambda: not self._daemon_missing())

    # -- Serve -------------------------------------------------------------

    @property
    def target(self) -> str:
        return f"http://127.0.0.1:{self._app_port}"

    def _entries(self) -> dict[int, dict[str, Any]]:
        """What Serve shows at each https port: the handlers of that port."""
        try:
            status = self._json("serve", "status", "--json")
        except TailscaleError:
            return {}
        found: dict[int, dict[str, Any]] = {}
        for key, web in (status.get("Web") or {}).items():
            _, _, port = str(key).rpartition(":")
            if port.isdigit():
                found.setdefault(int(port), {}).update((web or {}).get("Handlers") or {})
        # A port Serve forwards without a web entry still counts as taken.
        for port in (status.get("TCP") or {}):
            if str(port).isdigit():
                found.setdefault(int(port), {})
        return found

    def _is_ours(self, handlers: dict[str, Any]) -> bool:
        root = handlers.get("/")
        return isinstance(root, dict) and str(root.get("Proxy", "")).rstrip("/") == self.target

    def our_port(self) -> int | None:
        """The port at which this service is shown now, or ``None``."""
        for port, handlers in self._entries().items():
            if self._is_ours(handlers):
                return port
        return None

    def _free_port(self) -> int:
        """443 where it is free or already this service's, else 8443. The
        program's own Tailscale has nothing but this service, so 443 only."""
        entries = self._entries()
        ports = (PREFERRED_PORT,) if self.kind() == "builtin" else (PREFERRED_PORT, FALLBACK_PORT)
        for port in ports:
            handlers = entries.get(port)
            if handlers is None or self._is_ours(handlers):
                return port
        raise TailscaleError("port_taken")

    def serve(self) -> str:
        """Shows the service over https and answers the address. Only this
        service's entry is written; whatever else Serve shows stays."""
        current = self.state()
        if not current.connected:
            raise TailscaleError("not_connected")
        port = self._free_port()
        done = self._call("serve", "--bg", f"--https={port}", self.target)
        if done.returncode != 0:
            # Tailscale answers with an address to approve where https
            # certificates or the name service are not switched on yet.
            raise TailscaleError("serve_failed", (done.stderr or done.stdout).strip())
        return self.address() or self.compose(current.host, port)

    def address(self) -> str:
        """The https address of this service now, or an empty string."""
        port = self.our_port()
        host = self.state().host
        if port is None or not host:
            return ""
        return self.compose(host, port)

    @staticmethod
    def compose(host: str, port: int) -> str:
        """The https address of a host at a port."""
        return f"https://{host}" if port == PREFERRED_PORT else f"https://{host}:{port}"

    def unserve(self) -> None:
        """Takes this service's own entry away and no other."""
        port = self.our_port()
        if port is None:
            return
        done = self._call("serve", f"--https={port}", "--set-path=/", "off")
        if done.returncode != 0:
            raise TailscaleError("serve_failed", (done.stderr or done.stdout).strip())

    def stop_daemon(self) -> None:
        """Ends the program's own Tailscale. The owner's keeps running. A
        start that still waits for it is told to give up."""
        self._cancelled = True
        for process in (self._login, self._daemon):
            self._end(process)
        self._login = None
        self._daemon = None
