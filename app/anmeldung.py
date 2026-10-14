"""The password a service outside this machine demands.

A service bound to the loopback address is reachable by the programs of
this machine alone, and the key in its page is all the guard it needs. A
service bound to any other address stands in a network: whoever reaches it
would read the key from the page and hold every right, tools included. So
such a service runs only with a password set — it refuses to start without
one — and hands its key out only to a client that has sent that password
(``app/api/v1/anmeldung.py``).

The password lives in a file the configuration names, never on a command
line: an argument shows in every process listing.
"""

from __future__ import annotations

import ipaddress
import logging

from app.config import Config

log = logging.getLogger(__name__)

# What the configuration, the environment and the terminal client call the
# file (app/config.py ``password_file``, ``EXE_AI_PASSWORD_FILE``,
# ``exe service start --password-file``).
PASSWORD_FILE_VARIABLE = "EXE_AI_PASSWORD_FILE"


def is_loopback(host: str) -> bool:
    """Whether a bind address names this machine alone."""
    name = host.strip().strip("[]").lower()
    if name == "localhost":
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def required(config: Config) -> bool:
    """Whether this service demands a password: it listens beyond the
    loopback address."""
    return not is_loopback(config.app.host)


def read_password(config: Config) -> str | None:
    """The password from the file the configuration names, or ``None``:
    no file named, no file there, or nothing in it."""
    name = config.app.password_file.strip()
    if not name:
        return None
    file = config.pfad(name)
    try:
        password = file.read_text(encoding="utf-8").strip()
    except OSError as error:
        log.warning("Password file %s cannot be read: %s", file, error)
        return None
    return password or None


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
