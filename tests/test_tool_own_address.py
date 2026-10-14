"""The drawing tool reaches this very service where the service listens.

It used to call 127.0.0.1 always; a service bound to one other address (one
on a Tailscale address, a server set-up) does not answer there,
and draw_image failed with a connection error.
"""

from __future__ import annotations

import pytest

from app.config import Config
from app.tools.aufbau import own_address


@pytest.mark.parametrize(
    ("host", "address"),
    [
        ("100.80.1.2", "http://100.80.1.2:8095"),
        ("0.0.0.0", "http://127.0.0.1:8095"),
        ("::", "http://[::1]:8095"),
        ("::0", "http://[::1]:8095"),
        ("", "http://127.0.0.1:8095"),
        ("fe80::1%en0", "http://[fe80::1%en0]:8095"),
        ("fd00::1", "http://[fd00::1]:8095"),
        ("127.0.0.1", "http://127.0.0.1:8095"),
    ],
)
def test_the_own_address_follows_the_host(host, address):
    config = Config()
    config.app.host = host
    config.app.port = 8095
    assert own_address(config) == address


def test_the_host_from_the_environment_reaches_the_tool(monkeypatch):
    """EXE_AI_HOST, as a service bound to its own address sets it, read
    the way config_laden reads it."""
    from app.config import _umgebung_anwenden

    monkeypatch.setenv("EXE_AI_HOST", "100.80.1.2")
    monkeypatch.setenv("EXE_AI_PORT", "8095")
    config = Config.model_validate(_umgebung_anwenden({}))
    assert own_address(config) == "http://100.80.1.2:8095"


def test_without_a_setting_it_stays_loopback():
    config = Config()
    config.app.port = 8095
    assert own_address(config) == "http://127.0.0.1:8095"


def test_the_registry_hands_the_drawing_tool_that_address(config: Config, tmp_path):
    """The wiring itself: the registry the service builds gives draw_image
    the address it listens on."""
    from fastapi.testclient import TestClient

    from app.main import app_erstellen
    from app.tools.aufbau import registry_bauen

    config.app.host = "100.80.1.2"
    # Beyond the loopback address the service starts only with a password
    # set (app/anmeldung.py) — the file a server set-up names as well.
    password_file = tmp_path / "password.txt"
    password_file.write_text("open-sesame\n", encoding="utf-8")
    config.app.password_file = str(password_file)
    with TestClient(app_erstellen(config)) as testclient:
        registry = registry_bauen(testclient.app, config)
    assert registry.bild_zugang is not None
    assert registry.bild_zugang[0] == f"http://100.80.1.2:{config.app.port}/api/v1"
