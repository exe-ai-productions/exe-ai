"""A server the program starts itself comes back with the entry it ships.

Its card has no address to write: once the entry is removed, "connect" used
to send an `http` server without a `url` and the file check refused it. The
gallery now names the server as shipped, and the service puts the shipped
entry back before the named fields go on top of it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.api.v1 import werkzeuge

ROOT = Path(__file__).resolve().parent.parent
SHIPPED = json.loads(
    (ROOT / "mcp_servers.example.json").read_text(encoding="utf-8")
)["mcpServers"]

OWN_SERVER = {"type": "http", "url": "https://beispiel.invalid/mcp", "enabled": True}


@pytest.fixture(autouse=True)
def own_servers_file(config):
    """Never touch the project's real file."""
    config.mcp.servers_file = str(Path(config.app.data_dir) / "mcp_servers.json")


def _on_file(config) -> dict:
    path = config.pfad(config.mcp.servers_file)
    return json.loads(path.read_text(encoding="utf-8"))["mcpServers"]


def _write(config, entries: dict) -> None:
    path = config.pfad(config.mcp.servers_file)
    path.write_text(json.dumps({"mcpServers": entries}), encoding="utf-8")


def _removed(client, config, name: str) -> dict:
    """The file as a person leaves it after "Eintrag entfernen" on `name`:
    both shipped servers and one of their own on file, then `name` removed
    through the route the button calls."""
    _write(config, {**SHIPPED, "eigener": OWN_SERVER})
    assert client.delete(f"/api/v1/tools/servers/{name}").status_code == 204
    assert name not in _on_file(config)
    return _on_file(config)


@pytest.mark.parametrize("name", sorted(SHIPPED))
def test_a_removed_shipped_server_comes_back_as_it_ships(client, config, name):
    rest = _removed(client, config, name)

    response = client.put(
        f"/api/v1/tools/servers/{name}?shipped=true", json={"enabled": True}
    )

    assert response.status_code == 200
    assert response.json()["kaputt"] is None
    on_file = _on_file(config)
    # Exactly the shipped entry — command, arguments, environment, tool
    # lists — with the one field the button names set on top.
    assert on_file[name] == {**SHIPPED[name], "enabled": True}
    # Nothing else in the file moved.
    assert {k: v for k, v in on_file.items() if k != name} == rest


def test_the_body_the_card_used_to_send_is_still_refused(client, config):
    """The root of the failure: an `http` server with no address. The check
    keeps refusing it, and nothing is written."""
    rest = _removed(client, config, "websuche")

    response = client.put(
        "/api/v1/tools/servers/websuche",
        json={"type": "http", "url": None, "enabled": True},
    )

    assert response.status_code == 400
    assert "url" in response.json()["detail"]
    assert _on_file(config) == rest


def test_an_entry_on_file_is_not_replaced_by_the_shipped_one(client, config):
    own_version = {**SHIPPED["websuche"], "enabled": False,
                   "env": {"SUCHE_MAX_TREFFER": "3"}}
    _write(config, {"websuche": own_version})

    response = client.put(
        "/api/v1/tools/servers/websuche?shipped=true", json={"enabled": True}
    )

    assert response.status_code == 200
    assert _on_file(config)["websuche"] == {**own_version, "enabled": True}


def test_a_name_the_program_ships_nothing_under_is_refused(client, config):
    _write(config, {"eigener": OWN_SERVER})

    response = client.put(
        "/api/v1/tools/servers/notion?shipped=true", json={"enabled": True}
    )

    assert response.status_code == 404
    assert _on_file(config) == {"eigener": OWN_SERVER}


def test_an_unreadable_shipped_list_refuses_instead_of_writing_a_stub(
    client, config, monkeypatch, tmp_path
):
    _write(config, {"eigener": OWN_SERVER})
    monkeypatch.setattr(werkzeuge, "aufloesen", lambda path, **_: tmp_path / "fehlt.json")

    response = client.put(
        "/api/v1/tools/servers/websuche?shipped=true", json={"enabled": True}
    )

    assert response.status_code == 404
    assert "websuche" not in _on_file(config)


def test_silence_a_server_of_the_person_connects_as_before(client, config):
    """Without the switch the write is the one the gallery always made:
    only the named fields, no shipped entry mixed in."""
    _write(config, {})

    response = client.put("/api/v1/tools/servers/eigener", json=OWN_SERVER)

    assert response.status_code == 200
    assert _on_file(config) == {"eigener": OWN_SERVER}


# --- The self-run search: nothing shipped, the address of the person's own ---

SEARXNG_ENTRY = {
    "type": "stdio",
    "command": ".venv/bin/python",
    "args": ["mcp/searxng_server.py"],
    "env": {"SEARXNG_URL": "https://suche.example.org"},
    "enabled": True,
}


def test_nothing_ships_for_the_self_run_search():
    """The program has no address of its own to put in; the shipped list
    carries no entry of it and no placeholder for one."""
    assert "searxng" not in SHIPPED
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "SEARXNG_URL" not in env_example
    assert "${SEARXNG_URL}" not in (ROOT / "mcp_servers.example.json").read_text(encoding="utf-8")


def test_the_entry_of_the_self_run_search_is_written_with_its_environment(client, config):
    """The card writes the program and the typed address as the new entry's
    own environment; the other entries stand as they are."""
    _write(config, {"eigener": OWN_SERVER})

    response = client.put("/api/v1/tools/servers/searxng?neu=true", json=SEARXNG_ENTRY)

    assert response.status_code == 200
    assert response.json()["kaputt"] is None
    assert _on_file(config) == {"eigener": OWN_SERVER, "searxng": SEARXNG_ENTRY}


def test_the_self_run_search_is_no_shipped_name_any_more(client, config):
    _write(config, {"eigener": OWN_SERVER})

    response = client.put("/api/v1/tools/servers/searxng?shipped=true", json={"enabled": True})

    assert response.status_code == 404
    assert "searxng" not in _on_file(config)


def test_silence_an_entry_with_the_old_placeholder_still_runs_as_before(client, config):
    """A file written by an earlier version keeps its `${SEARXNG_URL}`; the
    service reads it without complaint."""
    old = {**SEARXNG_ENTRY, "env": {"SEARXNG_URL": "${SEARXNG_URL}"}, "enabled": False}
    _write(config, {"searxng": old})

    response = client.get("/api/v1/tools/servers")

    assert response.status_code == 200
    assert [e["name"] for e in response.json()] == ["searxng"]
