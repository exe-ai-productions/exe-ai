"""A request that comes through Tailscale needs the password, wherever the
service listens; a request from this machine itself does not.

Serve connects to the service from the loopback address, so the address says
nothing — the header it adds to every request it forwards does.
"""

from __future__ import annotations

import os
import stat

import pytest
from fastapi.testclient import TestClient

from app import anmeldung
from app.main import app_erstellen

PASSWORD = "open-sesame"
# The page of the interface goes only to a request that names this machine.
LOOPBACK = "http://127.0.0.1"
FORWARDED = {"X-Forwarded-For": "100.100.0.2"}


class FakeWebApp:
    """What the routes call; the real one talks to Tailscale."""

    def __init__(self) -> None:
        self.passwords: list[str] = []

    def snapshot(self):
        return {"tailscale": {"connected": False, "kind": "none", "login_url": ""},
                "service": {"running": False, "address": ""}, "password": bool(self.passwords)}

    def set_password(self, password: str) -> None:
        self.passwords.append(password)

    def resume(self) -> None:
        pass

    def end(self) -> None:
        pass


@pytest.fixture
def service(config):
    """A service on the loopback address with a password in its default file."""
    (config.datenverzeichnis).mkdir(parents=True, exist_ok=True)
    (config.datenverzeichnis / anmeldung.DEFAULT_PASSWORD_FILE).write_text(PASSWORD + "\n", encoding="utf-8")
    app = app_erstellen(config)
    app.state.web_app = FakeWebApp()
    with TestClient(app, base_url=LOOPBACK) as client:
        yield client, app


def _page(client, headers=None) -> str:
    response = client.get("/app/", headers=headers or {})
    assert response.status_code == 200
    return response.text


def test_the_page_of_a_request_from_this_machine_carries_the_key(service):
    client, app = service
    page = _page(client)
    assert f'window.__SITZUNGSSCHLUESSEL__="{app.state.sitzungsschluessel}"' in page
    assert "window.__ANMELDUNG__=false" in page


def test_the_page_of_a_request_through_tailscale_carries_no_key(service):
    client, app = service
    page = _page(client, FORWARDED)
    assert "window.__SITZUNGSSCHLUESSEL__=null" in page
    assert app.state.sitzungsschluessel not in page
    assert "window.__ANMELDUNG__=true" in page


def test_a_request_through_tailscale_gets_the_key_for_the_password_only(service):
    client, app = service
    wrong = client.post("/api/v1/login", json={"password": "wrong"}, headers=FORWARDED)
    assert wrong.status_code == 401
    right = client.post("/api/v1/login", json={"password": PASSWORD}, headers=FORWARDED)
    assert right.status_code == 200
    assert right.json() == {"key": app.state.sitzungsschluessel}


def test_a_request_from_this_machine_has_nothing_to_sign_in_to(service):
    """The silent case: without the header the sign-in refuses as it always did."""
    client, _ = service
    assert client.post("/api/v1/login", json={"password": PASSWORD}).status_code == 401


def test_without_a_password_nothing_signs_in_through_tailscale(config):
    app = app_erstellen(config)
    with TestClient(app, base_url=LOOPBACK) as client:
        assert client.post("/api/v1/login", json={"password": ""}, headers=FORWARDED).status_code == 401
        assert "window.__SITZUNGSSCHLUESSEL__=null" in _page(client, FORWARDED)


def test_the_api_stays_behind_the_key_for_a_request_through_tailscale(service):
    client, _ = service
    assert client.get("/api/v1/chats", headers={**FORWARDED, "X-Sitzungsschluessel": ""}).status_code == 401


def test_the_web_app_is_managed_from_this_machine_only(service):
    client, app = service
    key = {"X-Sitzungsschluessel": app.state.sitzungsschluessel}
    assert client.get("/api/v1/web-app", headers=key).status_code == 200
    for method, path in (("get", "/api/v1/web-app"), ("post", "/api/v1/web-app/start"),
                         ("post", "/api/v1/web-app/stop"), ("post", "/api/v1/web-app/tailscale/start")):
        assert getattr(client, method)(path, headers={**key, **FORWARDED}).status_code == 403, path
    assert client.put("/api/v1/web-app/password", json={"password": "x"}, headers={**key, **FORWARDED}).status_code == 403
    assert app.state.web_app.passwords == []


def test_the_password_is_written_to_a_file_of_its_own_and_never_answered(config):
    app = app_erstellen(config)
    with TestClient(app, base_url=LOOPBACK) as client:
        key = {"X-Sitzungsschluessel": app.state.sitzungsschluessel}
        response = client.put("/api/v1/web-app/password", json={"password": "a new one"}, headers=key)
        assert response.status_code == 200
        assert "a new one" not in response.text
        file = anmeldung.password_file(config)
        assert file.read_text(encoding="utf-8").strip() == "a new one"
        if os.name != "nt":
            # Windows keeps no permission bits: the file inherits the access
            # list of the user's data folder.
            assert stat.S_IMODE(file.stat().st_mode) == 0o600
        # The running service takes it at once.
        assert client.post("/api/v1/login", json={"password": "a new one"}, headers=FORWARDED).status_code == 200


def test_an_empty_password_is_not_a_password(config):
    app = app_erstellen(config)
    with TestClient(app, base_url=LOOPBACK) as client:
        key = {"X-Sitzungsschluessel": app.state.sitzungsschluessel}
        assert client.put("/api/v1/web-app/password", json={"password": "   "}, headers=key).status_code == 422
        # Long enough only with its edges: the service counts what it keeps.
        spaced = client.put("/api/v1/web-app/password", json={"password": "  abc    "}, headers=key)
        assert spaced.status_code == 422 and spaced.json()["detail"] == "password_too_short"


def test_the_password_has_at_least_eight_characters(config):
    app = app_erstellen(config)
    with TestClient(app, base_url=LOOPBACK) as client:
        key = {"X-Sitzungsschluessel": app.state.sitzungsschluessel}
        assert client.put("/api/v1/web-app/password", json={"password": "1234567"}, headers=key).status_code == 422
        assert not anmeldung.password_file(config).exists()
        assert client.put("/api/v1/web-app/password", json={"password": "12345678"}, headers=key).status_code == 200
        assert anmeldung.password_file(config).read_text(encoding="utf-8").strip() == "12345678"


def test_a_request_through_tailscale_gets_no_folder_dialog_on_this_machine(service, monkeypatch):
    """Serve connects from the loopback address: the dialog would open on this
    machine's screen for somebody elsewhere."""
    client, app = service
    monkeypatch.setattr("app.api.v1.dateisystem.dialog_verfuegbar", lambda: "a dialog")
    # The test client is no loopback address; it stands in for one.
    monkeypatch.setattr("app.api.v1.dateisystem.LOKAL", {"testclient"})
    key = {"X-Sitzungsschluessel": app.state.sitzungsschluessel}
    here = client.get("/api/v1/filesystem/folder-dialog", headers=key)
    assert here.json()["verfuegbar"] is True
    away = client.get("/api/v1/filesystem/folder-dialog", headers={**key, **FORWARDED})
    assert away.json()["verfuegbar"] is False
    assert client.post("/api/v1/filesystem/choose-folder", json={}, headers={**key, **FORWARDED}).status_code == 400


def test_a_refusal_carries_its_reason_and_what_tailscale_said_as_one_string(config):
    from app.tailscale import TailscaleError

    class Refusing(FakeWebApp):
        def start_service(self):
            raise TailscaleError("serve_failed", "approve at https://login.tailscale.com/f/serve")

    app = app_erstellen(config)
    app.state.web_app = Refusing()
    with TestClient(app, base_url=LOOPBACK) as client:
        key = {"X-Sitzungsschluessel": app.state.sitzungsschluessel}
        response = client.post("/api/v1/web-app/start", headers=key)
        assert response.status_code == 409
        assert response.json() == {"detail": "serve_failed: approve at https://login.tailscale.com/f/serve"}
