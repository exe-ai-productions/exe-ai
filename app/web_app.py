"""The web app: the service shown to a phone over https.

What the settings page's Web App section stands on. It holds the three
things the page shows and changes — the password, whether the service is
shown, and Tailscale — and keeps them in step:

* The password is a file (``app/anmeldung.py``): a request that comes
  through Tailscale needs it, and a service is not shown before one is set.
* Whether the service is meant to be shown is a note in the data folder.
  Where it was shown when the program ended, it is shown again after the
  next start, with nothing to click.
* Tailscale is the one of ``app/tailscale.py``; its sign-in, which only the
  owner can do, is an address the page opens in the browser.

Showing the service does not restart anything: it stays on the loopback
address, and Tailscale Serve forwards to it.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
from typing import Any

from app import anmeldung, atomic_file, qr_code
from app.config import Config
from app.tailscale import Tailscale, TailscaleError

log = logging.getLogger(__name__)

NOTE_FILE = "web_app.json"

# Shorter than this is no password for a service that is reached from outside
# the house; the page and the route both hold to it.
MIN_PASSWORD_LENGTH = 8

# The path the web app is served under: the address the page shows and the code
# carries ends here, since the root of the service answers with its health.
APP_PATH = "/app"


class WebApp:
    def __init__(self, config: Config, tailscale: Tailscale, state: Any) -> None:
        self._config = config
        self._tailscale = tailscale
        # The state of the application, where the password is read from for
        # each sign-in (``state.passwort``).
        self._state = state
        # Held by whatever changes things (start, stop, resume): the ones that
        # wait for Tailscale for a while. A look at the state never waits for
        # it.
        self._lock = threading.RLock()
        # Set once the program ends: a start that is still under way must not
        # leave a Tailscale behind.
        self._closed = False

    # -- The password ------------------------------------------------------

    def has_password(self) -> bool:
        return bool(getattr(self._state, "passwort", None))

    def set_password(self, password: str) -> None:
        """Writes the password to its file and takes it into the running
        service at once. It is never answered back."""
        password = password.strip()
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError("password too short")
        with self._lock:
            file = anmeldung.password_file(self._config)
            file.parent.mkdir(parents=True, exist_ok=True)
            # Made for its owner alone before a word is in it; the write
            # that follows keeps the permissions of the file it replaces.
            os.close(os.open(file, os.O_WRONLY | os.O_CREAT, 0o600))
            with contextlib.suppress(OSError):
                # A file of an earlier version, or made by hand, may be wider.
                file.chmod(0o600)
            atomic_file.write(file, password + "\n")
            self._state.passwort = password

    # -- Whether it is shown -----------------------------------------------

    def _note(self):
        return self._config.datenverzeichnis / NOTE_FILE

    def wanted(self) -> bool:
        try:
            return bool(json.loads(self._note().read_text(encoding="utf-8")).get("active"))
        except (OSError, ValueError, AttributeError):
            return False

    def _want(self, active: bool) -> None:
        self._note().parent.mkdir(parents=True, exist_ok=True)
        atomic_file.write(self._note(), json.dumps({"active": active}) + "\n")

    # -- What the page shows -----------------------------------------------

    def snapshot(self, login_url: str = "") -> dict[str, Any]:
        """The state as the page shows it, read once. A wanted service whose
        Tailscale has been signed in since is shown now (``settle``) —
        unless a start holds the lock, which is then finishing it anyway."""
        tailscale = self._tailscale.state()
        port = self._tailscale.our_port() if tailscale.connected else None
        if port is None and tailscale.connected and self.wanted() and self._lock.acquire(blocking=False):
            try:
                self._tailscale.serve()
                port = self._tailscale.our_port()
            except TailscaleError as error:
                # Not wanted any more, as after a start that failed: the next
                # look must not try again.
                log.warning("The web app could not be shown: %s", error)
                self._want(False)
            finally:
                self._lock.release()
        address = (
            self._tailscale.compose(tailscale.host, port) + APP_PATH
            if port is not None and tailscale.host
            else ""
        )
        return {
            "tailscale": {
                "connected": tailscale.connected,
                "kind": tailscale.kind,
                "login_url": login_url or tailscale.login_url,
            },
            # The code of the address, drawn by the page beside it; none
            # while there is no address to scan.
            "service": {"running": bool(address), "address": address, "qr": qr_code.svg(address) if address else ""},
            "password": self.has_password(),
            "password_min": MIN_PASSWORD_LENGTH,
        }

    # -- What the page does ------------------------------------------------

    def start_service(self) -> dict[str, Any]:
        """"Start service": Tailscale is started if it is not running, and
        once it is, the service is shown. Where Tailscale first needs the
        owner's sign-in, its address is answered and the rest follows when
        the sign-in is done."""
        with self._lock:
            if not self.has_password():
                raise TailscaleError("no_password")
            self._want(True)
            try:
                login_url = self._tailscale.start()
                if not login_url:
                    self._tailscale.serve()
            except TailscaleError:
                # A start that failed is not a service that is wanted: the
                # next look at the state must not try again, nor the next
                # start of the program.
                self._want(False)
                raise
            return self.snapshot(login_url)

    def start_tailscale(self) -> dict[str, Any]:
        """"Start Tailscale": the same start, without showing the service."""
        with self._lock:
            login_url = self._tailscale.start()
            return self.snapshot(login_url)

    def stop_service(self) -> dict[str, Any]:
        """"Stop service": the service's own entry goes, any other stays;
        the program's own Tailscale is ended, the owner's keeps running."""
        with self._lock:
            self._want(False)
            if self._tailscale.state().connected:
                self._tailscale.unserve()
            if self._tailscale.kind() == "builtin":
                self._tailscale.stop_daemon()
            return self.snapshot()

    def resume(self) -> None:
        """After a start of the program: a service that was shown when the
        program ended is shown again."""
        with self._lock:
            if self._closed or not self.wanted() or not self.has_password():
                return
            try:
                if not self._tailscale.start():
                    self._tailscale.serve()
            except TailscaleError as error:
                log.warning("The web app could not be shown again: %s", error)
            if self._closed:
                # The program ended while Tailscale was being started.
                self._tailscale.stop_daemon()

    def end(self) -> None:
        """At the end of the program: its own Tailscale goes with it. The
        note stays, so the next start shows the service again."""
        self._closed = True
        self._tailscale.stop_daemon()
