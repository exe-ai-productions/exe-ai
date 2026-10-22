"""Tailscale as the web app uses it: which one is there, what it shows, and
where the service goes beside what is shown already.

Every command is played: a fake ``tailscale`` answers the calls with the JSON
the real one gives (measured with Tailscale 1.104), and records them.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from app.tailscale import FALLBACK_PORT, HOSTNAME, PREFERRED_PORT, Tailscale, TailscaleError

APP_PORT = 8096
OURS = f"http://127.0.0.1:{APP_PORT}"
HOST = "mac.tailnet-name.ts.net."


def status(state: str = "Running", auth_url: str = "") -> dict:
    return {"BackendState": state, "AuthURL": auth_url, "Self": {"DNSName": HOST}}


def serve_status(**ports: dict[str, str]) -> dict:
    """``serve status --json`` for the given port -> {path: proxy}."""
    return {
        "TCP": {str(port): {"HTTPS": True} for port in ports},
        "Web": {
            f"mac.tailnet-name.ts.net:{port}": {"Handlers": {path: {"Proxy": proxy} for path, proxy in paths.items()}}
            for port, paths in ports.items()
        },
    }


class Fake:
    """A Tailscale that answers by what is asked and keeps a record."""

    def __init__(self, state: dict, serve: dict | None = None, after_up: dict | None = None) -> None:
        self.state = state
        # What Tailscale reports once it was asked to sign in.
        self.after_up = after_up
        self.serve = serve or {}
        self.calls: list[list[str]] = []
        self.spawned: list[list[str]] = []
        # Whether the program's own daemon has to be started for Tailscale
        # to answer at all, and whether it has been.
        self.daemon_needed = False
        self.daemon_up = False

    def run(self, args: list[str], timeout: float = 0) -> subprocess.CompletedProcess[str]:
        # The programs' own client is told its socket first.
        words = [word for word in args[1:] if not word.startswith("--socket=")]
        self.calls.append(words)
        if self.daemon_needed and not self.daemon_up:
            return subprocess.CompletedProcess(args, 1, "", "failed to connect to local tailscaled")
        if words[:2] == ["status", "--json"]:
            return subprocess.CompletedProcess(args, 0, json.dumps(self.state), "")
        if words[:3] == ["serve", "status", "--json"]:
            return subprocess.CompletedProcess(args, 0, json.dumps(self.serve), "")
        return subprocess.CompletedProcess(args, 0, "", "")

    def spawn(self, args: list[str], **_: object) -> "Process":
        self.spawned.append(args)
        if Path(args[0]).stem == "tailscaled":
            self.daemon_up = True
        if "up" in args and self.after_up is not None:
            self.state = self.after_up
        return Process()


class Process:
    def __init__(self) -> None:
        self.ended = False
        self.waited = False

    def wait(self, timeout: float = 0) -> int:
        self.waited = True
        return 0

    def poll(self):
        return 0 if self.ended else None

    def terminate(self) -> None:
        self.ended = True


def own(tmp_path: Path, fake: Fake) -> Tailscale:
    command = tmp_path / "tailscale-own"
    command.write_text("", encoding="utf-8")
    return Tailscale(
        data_folder=tmp_path / "data", app_port=APP_PORT, own_command=str(command),
        run=fake.run, spawn=fake.spawn, sleep=lambda _: None,
    )


def builtin(tmp_path: Path, fake: Fake) -> Tailscale:
    fake.daemon_needed = True
    folder = tmp_path / "program"
    folder.mkdir(parents=True)
    suffix = ".exe" if os.name == "nt" else ""
    for name in ("tailscale", "tailscaled"):
        (folder / (name + suffix)).write_text("", encoding="utf-8")
    return Tailscale(
        data_folder=tmp_path / "data", app_port=APP_PORT, program_folder=folder,
        own_command=str(tmp_path / "none"),
        run=fake.run, spawn=fake.spawn, sleep=lambda _: None,
    )


def test_the_owners_tailscale_is_used_where_there_is_one_and_the_programs_where_not(tmp_path):
    fake = Fake(status())
    assert own(tmp_path, fake).kind() == "own"
    assert builtin(tmp_path / "b", fake).kind() == "builtin"
    nothing = Tailscale(data_folder=tmp_path, app_port=APP_PORT, own_command=str(tmp_path / "none"))
    assert nothing.kind() == "none"


def test_the_state_is_connected_only_while_tailscale_runs(tmp_path):
    assert own(tmp_path, Fake(status())).state().connected is True
    stopped = own(tmp_path, Fake(status("Stopped"))).state()
    assert stopped.connected is False
    assert stopped.host == ""
    waiting = own(tmp_path, Fake(status("NeedsLogin", "https://login.tailscale.com/a/abc"))).state()
    assert waiting.connected is False
    assert waiting.login_url == "https://login.tailscale.com/a/abc"


def test_the_service_takes_443_where_it_is_free(tmp_path):
    fake = Fake(status(), serve_status())
    address = own(tmp_path, fake).serve()
    assert ["serve", "--bg", f"--https={PREFERRED_PORT}", OURS] in fake.calls
    assert address.startswith("https://mac.tailnet-name.ts.net")


def test_the_service_takes_8443_where_443_shows_at_something_else(tmp_path):
    """The owner's own entries on 443 are left as they are."""
    other = {"/": "http://127.0.0.1:8090", "/vorschau": "http://127.0.0.1:8090/vorschau"}
    fake = Fake(status(), serve_status(**{"443": other}))
    own(tmp_path, fake).serve()
    assert ["serve", "--bg", f"--https={FALLBACK_PORT}", OURS] in fake.calls
    assert not any("--https=443" in call for call in fake.calls)


def test_the_address_names_the_port_where_it_is_not_443(tmp_path):
    other = {"/": "http://127.0.0.1:8090"}
    fake = Fake(status(), serve_status(**{"443": other, "8443": {"/": OURS}}))
    assert own(tmp_path, fake).address() == "https://mac.tailnet-name.ts.net:8443"
    fake = Fake(status(), serve_status(**{"443": {"/": OURS}}))
    assert own(tmp_path, fake).address() == "https://mac.tailnet-name.ts.net"


def test_443_that_shows_at_this_service_is_its_own_entry(tmp_path):
    fake = Fake(status(), serve_status(**{"443": {"/": OURS}}))
    own(tmp_path, fake).serve()
    assert ["serve", "--bg", f"--https={PREFERRED_PORT}", OURS] in fake.calls


def test_with_both_ports_taken_by_others_nothing_is_written(tmp_path):
    other = {"/": "http://127.0.0.1:8090"}
    fake = Fake(status(), serve_status(**{"443": other, "8443": other}))
    with pytest.raises(TailscaleError) as caught:
        own(tmp_path, fake).serve()
    assert caught.value.reason == "port_taken"
    assert not any(call[:2] == ["serve", "--bg"] for call in fake.calls)


def test_stopping_takes_away_the_own_entry_and_no_other(tmp_path):
    other = {"/": "http://127.0.0.1:8090", "/vorschau": "http://127.0.0.1:8090/vorschau"}
    fake = Fake(status(), serve_status(**{"443": other, "8443": {"/": OURS}}))
    own(tmp_path, fake).unserve()
    assert ["serve", "--https=8443", "--set-path=/", "off"] in fake.calls
    assert not any("--https=443" in call for call in fake.calls)


def test_stopping_without_an_own_entry_touches_nothing(tmp_path):
    """The silent case: another entry is there, ours is not."""
    fake = Fake(status(), serve_status(**{"443": {"/": "http://127.0.0.1:8090"}}))
    own(tmp_path, fake).unserve()
    assert not any(call[:1] == ["serve"] and "off" in call for call in fake.calls)


def test_showing_needs_a_connected_tailscale(tmp_path):
    with pytest.raises(TailscaleError) as caught:
        own(tmp_path, Fake(status("Stopped"))).serve()
    assert caught.value.reason == "not_connected"


def test_the_programs_own_tailscale_runs_in_user_space_with_its_own_folder_and_name(tmp_path):
    fake = Fake(status("NeedsLogin"), after_up=status("NeedsLogin", "https://login.tailscale.com/a/abc"))
    login_url = builtin(tmp_path, fake).start()
    assert login_url == "https://login.tailscale.com/a/abc"
    daemon, = [call for call in fake.spawned if Path(call[0]).stem == "tailscaled"]
    assert "--tun=userspace-networking" in daemon
    assert f"--statedir={tmp_path / 'data' / 'tailscale'}" in daemon
    socket, = [word for word in daemon if word.startswith("--socket=")]
    up, = [call for call in fake.spawned if "up" in call]
    assert f"--hostname={HOSTNAME}" in up
    # The client talks to the socket the daemon listens on.
    assert socket in up


def test_a_signed_in_tailscale_needs_no_sign_in_address(tmp_path):
    fake = Fake(status())
    assert builtin(tmp_path, fake).start() == ""
    assert not any("up" in call for call in fake.spawned)


def test_the_owners_tailscale_is_started_without_a_name_of_ours(tmp_path):
    fake = Fake(status("NeedsLogin"), after_up=status("NeedsLogin", "https://login.tailscale.com/a/abc"))
    own(tmp_path, fake).start()
    up, = [call for call in fake.spawned if "up" in call]
    assert not any(word.startswith("--hostname") for word in up)


def test_the_programs_own_tailscale_goes_with_stopping(tmp_path):
    fake = Fake(status("NeedsLogin"), after_up=status("NeedsLogin", "https://login.tailscale.com/a/abc"))
    tailscale = builtin(tmp_path, fake)
    tailscale.start()
    daemon = tailscale._daemon
    tailscale.stop_daemon()
    assert daemon.ended is True


def test_a_socket_path_too_long_for_a_unix_socket_is_moved_to_a_short_folder(tmp_path):
    long_folder = tmp_path / ("a" * 90) / "data"
    fake = Fake(status("NeedsLogin"), after_up=status("NeedsLogin", "https://login.tailscale.com/a/abc"))
    fake.daemon_needed = True
    folder = tmp_path / "program"
    folder.mkdir()
    suffix = ".exe" if os.name == "nt" else ""
    for name in ("tailscale", "tailscaled"):
        (folder / (name + suffix)).write_text("", encoding="utf-8")
    tailscale = Tailscale(
        data_folder=long_folder, app_port=APP_PORT, program_folder=folder, own_command=str(tmp_path / "none"),
        run=fake.run, spawn=fake.spawn, sleep=lambda _: None,
    )
    tailscale.start()
    daemon, = [call for call in fake.spawned if Path(call[0]).stem == "tailscaled"]
    socket, = [word for word in daemon if word.startswith("--socket=")]
    assert len(socket) - len("--socket=") <= 100
    assert str(long_folder) not in socket


def test_the_programs_own_daemon_is_waited_for_before_it_is_asked_to_sign_in(tmp_path):
    """The client asked before the daemon listens would fail, and nothing
    would ask the daemon to sign in."""
    fake = Fake(status("NeedsLogin"), after_up=status("NeedsLogin", "https://login.tailscale.com/a/abc"))
    tailscale = builtin(tmp_path, fake)
    order: list[str] = []
    real_spawn = fake.spawn

    def spawn(args, **kwargs):
        order.append("daemon" if Path(args[0]).stem == "tailscaled" else "up")
        return real_spawn(args, **kwargs)

    tailscale._spawn = spawn
    tailscale.start()
    assert order == ["daemon", "up"]
    # The first ask for its state found no daemon, the next ones did.
    assert fake.calls[0][:2] == ["status", "--json"]


def test_a_daemon_that_answers_already_is_not_started_a_second_time(tmp_path):
    """Left over from a run that ended badly, or started a moment ago."""
    fake = Fake(status())
    tailscale = builtin(tmp_path, fake)
    fake.daemon_up = True
    tailscale.start()
    assert fake.spawned == []


def test_ending_the_programs_own_tailscale_waits_for_it_to_be_gone(tmp_path):
    fake = Fake(status("NeedsLogin"), after_up=status("NeedsLogin", "https://login.tailscale.com/a/abc"))
    tailscale = builtin(tmp_path, fake)
    tailscale.start()
    daemon = tailscale._daemon
    tailscale.stop_daemon()
    assert daemon.waited is True


def test_a_second_sign_in_ends_the_first_that_is_still_waiting(tmp_path):
    fake = Fake(status("NeedsLogin"))
    tailscale = builtin(tmp_path, fake)
    with pytest.raises(TailscaleError):
        tailscale.start()
    first = tailscale._login
    fake.after_up = status("NeedsLogin", "https://login.tailscale.com/a/abc")
    fake.state = status("NeedsLogin")
    tailscale.start()
    assert first.ended is True


def test_a_program_that_cannot_be_started_is_a_tailscale_that_is_not_answering(tmp_path):
    fake = Fake(status("NeedsLogin"))
    tailscale = builtin(tmp_path, fake)

    def refuse(args, **kwargs):
        raise PermissionError("not executable")

    tailscale._spawn = refuse
    with pytest.raises(TailscaleError) as caught:
        tailscale.start()
    assert caught.value.reason == "not_answering"


def test_a_daemon_that_never_comes_up_is_told_at_once_not_after_a_second_wait(tmp_path):
    fake = Fake(status("NeedsLogin"))
    tailscale = builtin(tmp_path, fake)
    tailscale._spawn = lambda args, **kwargs: Process()
    waits: list[float] = []
    tailscale._sleep = waits.append
    fake.daemon_up = False
    with pytest.raises(TailscaleError) as caught:
        tailscale.start()
    assert caught.value.reason == "not_answering"
    # One wait for the daemon; none for a sign-in after it.
    assert len(waits) <= 2 * 20 + 1


def test_a_start_that_is_waiting_gives_up_when_tailscale_is_ended(tmp_path):
    fake = Fake(status("NeedsLogin"))
    tailscale = builtin(tmp_path, fake)

    def end_while_waiting(_: float) -> None:
        tailscale.stop_daemon()

    tailscale._sleep = end_while_waiting
    with pytest.raises(TailscaleError):
        tailscale.start()
