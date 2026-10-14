"""The start, the window and the port probe look for the service on the
address it is bound to (`config.app.host`), by the rule the service's own
tools use (app/tools/aufbau.py): a wildcard is reached on loopback, a single
address on itself."""

from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest

import start
from app import main as service_main
from app.tools.aufbau import dial_host, service_url

ADDRESS = "100.100.0.7"
PORT = 18319


class _Socket:
    """Records what is connected to; answers as if something listened."""

    created: list[int] = []
    connected: list[tuple[str, int]] = []

    def __init__(self, family=socket.AF_INET, *args, **kwargs):
        type(self).created.append(family)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def settimeout(self, value):
        pass

    def connect_ex(self, address):
        type(self).connected.append(address)
        return 0


@pytest.fixture
def sockets(monkeypatch):
    _Socket.created = []
    _Socket.connected = []
    monkeypatch.setattr(socket, "socket", _Socket)
    return _Socket


@pytest.mark.parametrize(
    ("host", "reached"),
    [
        (ADDRESS, ADDRESS),
        ("0.0.0.0", "127.0.0.1"),
        ("", "127.0.0.1"),
        ("::", "::1"),
        ("127.0.0.1", "127.0.0.1"),
    ],
)
def test_the_rule_is_one_for_the_start_the_probe_and_the_tools(host, reached):
    assert dial_host(host) == reached


def test_the_url_brackets_an_address_of_the_second_family():
    assert service_url("::", 8090) == "http://[::1]:8090"
    assert service_url(ADDRESS, 8090) == f"http://{ADDRESS}:8090"


def test_the_start_asks_the_address_the_service_is_bound_to(sockets):
    assert start._antwortet(PORT, ADDRESS) is True
    assert sockets.connected == [(ADDRESS, PORT)]


def test_the_services_own_probe_asks_the_same_address(sockets):
    assert service_main._antwortet(PORT, host=ADDRESS) is True
    assert sockets.connected == [(ADDRESS, PORT)]


@pytest.mark.parametrize(("host", "reached"), [("0.0.0.0", "127.0.0.1"), ("", "127.0.0.1")])
def test_a_wildcard_is_asked_on_loopback_as_before(sockets, host, reached):
    start._antwortet(PORT, host)
    service_main._antwortet(PORT, host=host)
    assert sockets.connected == [(reached, PORT), (reached, PORT)]
    assert sockets.created == [socket.AF_INET, socket.AF_INET]


def test_the_ipv6_wildcard_is_asked_on_the_ipv6_loopback(sockets):
    start._antwortet(PORT, "::")
    assert sockets.connected == [("::1", PORT)]
    assert sockets.created == [socket.AF_INET6]


def test_the_window_opens_the_address_the_service_answers_on(monkeypatch):
    opened: list[str] = []
    monkeypatch.delenv("EXE_AI_TERMINAL_HEADLESS", raising=False)
    monkeypatch.setattr(start, "_antwortet", lambda port, host="127.0.0.1": True)
    import app.appfenster as window

    monkeypatch.setattr(window, "oeffnen", lambda address: opened.append(address) or True)
    start._browser_oeffnen(PORT, ADDRESS)
    assert opened == [f"http://{ADDRESS}:{PORT}/app/"]


def test_a_second_start_finds_a_service_bound_to_a_single_address(monkeypatch, capsys):
    asked: list[tuple[int, str]] = []
    monkeypatch.setattr(start, "_antwortet", lambda port, host="127.0.0.1": asked.append((port, host)) or True)
    import app.config as configuration

    monkeypatch.setattr(
        configuration, "get_config", lambda: SimpleNamespace(app=SimpleNamespace(host=ADDRESS, port=PORT))
    )
    assert start._terminal_bedienen(with_window=False) == 1
    assert asked == [(PORT, ADDRESS)]
    assert "already listening" in capsys.readouterr().err
