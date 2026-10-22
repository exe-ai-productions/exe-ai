"""The password a service outside this machine demands.

A service bound to the loopback address is reachable by the programs of
this machine alone, and the key in its page is all the guard it needs. A
service bound to any other address stands in a network: whoever reaches it
would read the key from the page and hold every right, tools included. So
such a service runs only with a password set — it refuses to start without
one — and hands its key out only to a client that has sent that password
(``app/api/v1/anmeldung.py``).

The password lives in a file the configuration names, never on a command
line: an argument shows in every process listing. Where the configuration
names none, the web app's page writes it into a file of its own in the data
folder (``app/web_app.py``).

A request that comes through Tailscale Serve (``via_tailscale``) stands in
a network as well, whatever the service listens on: Serve connects from the
loopback address, so the address says nothing. It is told by the header
Serve adds to every request it forwards, and it always needs the password.
"""

from __future__ import annotations

import ipaddress
import logging
from pathlib import Path

from starlette.requests import Request

from app.config import Config

log = logging.getLogger(__name__)

# What the configuration, the environment and the terminal client call the
# file (app/config.py ``password_file``, ``EXE_AI_PASSWORD_FILE``,
# ``exe service start --password-file``).
PASSWORD_FILE_VARIABLE = "EXE_AI_PASSWORD_FILE"

# The file the password is kept in where the configuration names none: in the
# data folder, beside the rest of what belongs to the user.
DEFAULT_PASSWORD_FILE = "web_app_password.txt"

# The header Tailscale Serve sets on every request it forwards. A program on
# this machine can set it too, but only to be asked for the password more.
FORWARDED_HEADER = "x-forwarded-for"


def is_loopback(host: str) -> bool:
    """Whether a bind address names this machine alone."""
    name = host.strip().strip("[]").lower()
    if name == "localhost":
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def host_is_loopback(header: str) -> bool:
    """Whether a ``Host`` header names this machine: a loopback address or
    ``localhost``, with or without a port. A page that takes any other name
    could be loaded by a foreign site whose name was pointed at this
    machine (DNS rebinding) and would hand it the key."""
    name, port = header.strip(), ""
    if name.startswith("["):
        # "[::1]:8090" or "[::1]": the address ends at the closing bracket
        # and only a port may follow it.
        end = name.find("]")
        if end < 0 or name[end + 1:end + 2] not in ("", ":"):
            return False
        name, port = name[1:end], name[end + 2:]
    elif name.count(":") == 1:
        name, port = name.split(":", 1)
    return bool(name) and (not port or port.isdigit()) and is_loopback(name)


def required(config: Config) -> bool:
    """Whether this service demands a password: it listens beyond the
    loopback address."""
    return not is_loopback(config.app.host)


def password_file(config: Config) -> Path:
    """The file the password is read from and written to."""
    name = config.app.password_file.strip()
    return config.pfad(name) if name else config.datenverzeichnis / DEFAULT_PASSWORD_FILE


def read_password(config: Config) -> str | None:
    """The password from its file, or ``None``: no file there, or nothing
    in it."""
    file = password_file(config)
    try:
        password = file.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        # No file named and none made yet is the ordinary case; a file the
        # configuration names that is not there is worth a line.
        if config.app.password_file.strip():
            log.warning("Password file %s cannot be read: it is not there", file)
        return None
    except OSError as error:
        log.warning("Password file %s cannot be read: %s", file, error)
        return None
    return password or None


def via_tailscale(request: Request) -> bool:
    """Whether this request was forwarded by Tailscale Serve."""
    return FORWARDED_HEADER in request.headers


def needs_login(request: Request) -> bool:
    """Whether the page may not carry the key for this request: the service
    listens beyond the loopback address, or the request came through
    Tailscale."""
    return bool(getattr(request.app.state, "anmeldung", False)) or via_tailscale(request)


def check_at_start(config: Config, password: str | None) -> None:
    """Refuses a start that would put the service into a network without a
    password. Raised, not logged only: the service must not come up."""
    if required(config) and password is None:
        raise RuntimeError(
            f"The service would listen on {config.app.host}, beyond this machine, "
            "and no password is set. Name a file holding one: app.password_file "
            f"in the configuration, {PASSWORD_FILE_VARIABLE} in the environment, "
            "or exe service start --password-file."
        )
