"""The web app's own logic: the password, whether the service is meant to be
shown, and what follows a start, a stop and a restart of the program.

Tailscale is played; what is under test is when ``app/web_app.py`` asks it.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from app import anmeldung
from app.tailscale import State, TailscaleError
from app.web_app import WebApp


class FakeTailscale:
    def __init__(self, *, connected: bool = True, kind: str = "own", login_url: str = "") -> None:
        self.connected = connected
        self.kind_name = kind
        self.login_url = login_url
        self.shown = False
        self.refuse_serve = False
        self.calls: list[str] = []

    def state(self) -> State:
        return State(self.connected, self.kind_name, "" if self.connected else self.login_url,
                     "mac.tailnet-name.ts.net" if self.connected else "")

    def kind(self) -> str:
        return self.kind_name

    def start(self) -> str:
        self.calls.append("start")
        return "" if self.connected else self.login_url

    def serve(self) -> str:
        self.calls.append("serve")
        if not self.connected:
            raise TailscaleError("not_connected")
        if self.refuse_serve:
            raise TailscaleError("serve_failed", "approve at https://login.tailscale.com/f/serve")
        self.shown = True
        return "https://mac.tailnet-name.ts.net"

    def unserve(self) -> None:
        self.calls.append("unserve")
        self.shown = False

    def our_port(self):
        return 443 if self.shown else None

    def address(self) -> str:
        return "https://mac.tailnet-name.ts.net" if self.shown else ""

    @staticmethod
    def compose(host: str, port: int) -> str:
        return f"https://{host}"

    def stop_daemon(self) -> None:
        self.calls.append("stop_daemon")


@pytest.fixture
def parts(config):
    config.datenverzeichnis.mkdir(parents=True, exist_ok=True)
    tailscale = FakeTailscale()
    state = SimpleNamespace(passwort=None)
    return WebApp(config, tailscale, state), tailscale, state


def test_a_password_is_kept_in_a_file_and_taken_into_the_running_service(parts, config):
    web_app, _, state = parts
    assert web_app.has_password() is False
    web_app.set_password("  open-sesame ")
    assert state.passwort == "open-sesame"
    assert anmeldung.read_password(config) == "open-sesame"


def test_a_password_of_seven_characters_is_refused_and_one_of_eight_taken(parts, config):
    web_app, _, state = parts
    with pytest.raises(ValueError):
        web_app.set_password("1234567")
    # Counted without its edges, as it is kept.
    with pytest.raises(ValueError):
        web_app.set_password("  1234567  ")
    assert web_app.has_password() is False
    assert not anmeldung.password_file(config).exists()
    web_app.set_password("12345678")
    assert state.passwort == "12345678"
    assert web_app.snapshot()["password_min"] == 8


def test_the_state_never_carries_the_password(parts):
    web_app, _, _ = parts
    web_app.set_password("open-sesame")
    assert "open-sesame" not in str(web_app.snapshot())
    assert web_app.snapshot()["password"] is True


def test_the_service_is_not_started_without_a_password(parts):
    web_app, tailscale, _ = parts
    with pytest.raises(TailscaleError) as caught:
        web_app.start_service()
    assert caught.value.reason == "no_password"
    assert tailscale.calls == []
    assert web_app.wanted() is False


def test_starting_shows_the_service_where_tailscale_is_connected(parts):
    web_app, tailscale, _ = parts
    web_app.set_password("open-sesame")
    snapshot = web_app.start_service()
    assert tailscale.calls == ["start", "serve"]
    assert snapshot["service"]["running"] is True
    # The address ends on the path of the app: the root of the service answers with its health.
    assert snapshot["service"]["address"] == "https://mac.tailnet-name.ts.net/app"
    assert web_app.wanted() is True


def test_starting_without_a_sign_in_answers_its_address_and_shows_nothing_yet(parts):
    web_app, tailscale, _ = parts
    tailscale.connected = False
    tailscale.login_url = "https://login.tailscale.com/a/abc"
    web_app.set_password("open-sesame")
    snapshot = web_app.start_service()
    assert snapshot["tailscale"]["login_url"] == "https://login.tailscale.com/a/abc"
    assert snapshot["service"]["running"] is False
    assert "serve" not in tailscale.calls
    assert web_app.wanted() is True


def test_the_service_is_shown_once_the_sign_in_is_done(parts):
    """What the page's next look at the state finishes: the owner signed in
    in the browser, and the service that was wanted is shown."""
    web_app, tailscale, _ = parts
    tailscale.connected = False
    tailscale.login_url = "https://login.tailscale.com/a/abc"
    web_app.set_password("open-sesame")
    web_app.start_service()
    tailscale.connected = True
    assert web_app.snapshot()["service"]["running"] is True


def test_a_service_nobody_wants_is_not_shown_by_a_look_at_the_state(parts):
    """The silent case: Tailscale connected, nothing asked for."""
    web_app, tailscale, _ = parts
    assert web_app.snapshot()["service"]["running"] is False
    assert "serve" not in tailscale.calls


def test_stopping_takes_the_entry_away_and_ends_only_the_programs_own_tailscale(parts):
    web_app, tailscale, _ = parts
    web_app.set_password("open-sesame")
    web_app.start_service()
    web_app.stop_service()
    assert "unserve" in tailscale.calls
    assert "stop_daemon" not in tailscale.calls
    assert web_app.wanted() is False
    tailscale.kind_name = "builtin"
    web_app.start_service()
    web_app.stop_service()
    assert "stop_daemon" in tailscale.calls


def test_a_service_that_was_shown_when_the_program_ended_is_shown_again(parts):
    web_app, tailscale, _ = parts
    web_app.set_password("open-sesame")
    web_app.start_service()
    tailscale.shown = False
    tailscale.calls.clear()
    web_app.end()
    # The next start of the program: a new object on the same data folder.
    WebApp(web_app._config, tailscale, SimpleNamespace(passwort="open-sesame")).resume()
    assert tailscale.calls == ["stop_daemon", "start", "serve"]


def test_a_service_that_was_stopped_stays_stopped_after_a_start_of_the_program(parts):
    web_app, tailscale, _ = parts
    web_app.set_password("open-sesame")
    web_app.start_service()
    web_app.stop_service()
    tailscale.calls.clear()
    web_app.resume()
    assert tailscale.calls == []


def test_starting_tailscale_alone_shows_nothing(parts):
    web_app, tailscale, _ = parts
    web_app.start_tailscale()
    assert tailscale.calls == ["start"]
    assert web_app.wanted() is False


def test_a_start_that_failed_is_not_wanted_any_more(parts):
    """Nothing tries again at the next look at the state or at the next start
    of the program."""
    web_app, tailscale, _ = parts
    tailscale.refuse_serve = True
    web_app.set_password("open-sesame")
    with pytest.raises(TailscaleError) as caught:
        web_app.start_service()
    assert caught.value.detail.startswith("approve at")
    assert web_app.wanted() is False
    tailscale.calls.clear()
    web_app.snapshot()
    web_app.resume()
    assert "serve" not in tailscale.calls


def test_a_start_of_the_program_that_is_still_under_way_at_its_end_leaves_no_tailscale(parts):
    web_app, tailscale, _ = parts
    web_app.set_password("open-sesame")
    web_app.start_service()
    tailscale.calls.clear()
    original = tailscale.start

    def start_while_the_program_ends() -> str:
        web_app.end()
        return original()

    tailscale.start = start_while_the_program_ends
    web_app.resume()
    assert tailscale.calls.count("stop_daemon") == 2


def test_a_new_password_file_is_made_for_its_owner_alone_before_a_word_is_in_it(config, monkeypatch):
    import os
    opened = []
    real_open = os.open
    def recording_open(path, flags, mode=0o777):
        if str(path).endswith("web_app_password.txt"):
            opened.append(mode)
        return real_open(path, flags, mode)

    monkeypatch.setattr("app.web_app.os.open", recording_open)
    config.datenverzeichnis.mkdir(parents=True, exist_ok=True)
    WebApp(config, FakeTailscale(), SimpleNamespace(passwort=None)).set_password("open-sesame")
    assert opened == [0o600]


def test_a_look_at_the_state_that_could_not_show_the_service_does_not_try_again(parts):
    web_app, tailscale, _ = parts
    web_app.set_password("open-sesame")
    web_app._want(True)
    tailscale.refuse_serve = True
    web_app.snapshot()
    tailscale.calls.clear()
    web_app.snapshot()
    assert "serve" not in tailscale.calls
    assert web_app.wanted() is False


def test_a_connected_tailscale_without_a_name_has_no_address(parts):
    web_app, tailscale, _ = parts
    tailscale.shown = True
    tailscale.state = lambda: State(True, "own", "", "")
    service = web_app.snapshot()["service"]
    assert (service["running"], service["address"], service["qr"]) == (False, "", "")


def test_a_password_file_of_wider_permissions_is_narrowed_when_a_password_is_set(parts, config):
    import stat
    web_app, _, _ = parts
    file = anmeldung.password_file(config)
    file.write_text("old\n", encoding="utf-8")
    file.chmod(0o644)
    web_app.set_password("open-sesame")
    if os.name != "nt":
        # Windows keeps no permission bits: the file inherits the access list
        # of the user's data folder.
        assert stat.S_IMODE(file.stat().st_mode) == 0o600


def test_the_state_carries_the_code_of_the_address_while_the_service_is_shown(parts):
    web_app, _, _ = parts
    web_app.set_password("open-sesame")
    assert web_app.snapshot()["service"]["qr"] == ""
    web_app.start_service()
    code = web_app.snapshot()["service"]["qr"]
    assert code.startswith("<svg") and "<path" in code


def test_the_code_of_an_address_is_a_vector_graphic_of_one_colour():
    from app import qr_code
    code = qr_code.svg("https://exe-ai.tailnet-name.ts.net")
    assert code.startswith("<svg") and code.endswith("</svg>")
    assert "<?xml" not in code
    # The page sizes it: a drawing with a fixed width would stay small in its box.
    assert "viewBox=" in code and " width=" not in code.split(">", 1)[0]
    assert qr_code.svg("https://exe-ai.tailnet-name.ts.net") == code
    assert qr_code.svg("https://exe-ai.tailnet-name.ts.net:8443") != code
