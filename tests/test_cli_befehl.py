"""The service runs no command a caller hands it over the network.

A route once took a command line for a chat and ran it on the machine of the
service — the door of a module the window no longer shows. With remote
access switched on, that door stood open to every machine that holds the
password. It is gone: a command reaches the runner through a tool call of
the model, and the user's own shell line runs on the machine the terminal
client runs on.

What the window's terminal tab reads stays as it was: the list of a chat's
runs, their live stream and the stop.
"""

from __future__ import annotations

import pytest

from app.main import app
from app.tools import hintergrund
from tests.conftest import python_command

RUNS = "/api/v1/laeufe"


@pytest.fixture(autouse=True)
def clean_runs():
    hintergrund.laeufe._laeufe.clear()
    hintergrund.laeufe._ereignisse.clear()
    yield
    hintergrund.laeufe._laeufe.clear()
    hintergrund.laeufe._ereignisse.clear()


def _run_routes() -> set[tuple[str, str]]:
    """Every route under the runs, as (method, path)."""
    return {
        (method, route.path)
        for route in app.routes
        if getattr(route, "path", "").startswith(RUNS)
        for method in getattr(route, "methods", ()) or ()
        if method != "HEAD"
    }


def test_a_command_sent_to_the_service_is_not_run(client, chat_id, tmp_path):
    """Falls over with the route in place: the file would be written."""
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(tmp_path)]})
    mark = tmp_path / "ran.txt"
    command = python_command(f"open({str(mark)!r}, 'w').close()")

    answer = client.post(f"{RUNS}/{chat_id}/befehl", json={"command": command})

    assert answer.status_code in (404, 405)
    assert not mark.exists()
    assert client.get(f"{RUNS}/{chat_id}").json()["laeufe"] == []


def test_the_runs_keep_the_routes_of_the_terminal_tab_and_take_no_command():
    routes = _run_routes()
    assert {
        ("GET", f"{RUNS}/{{chat_id}}"),
        ("GET", f"{RUNS}/{{chat_id}}/stream"),
        ("POST", f"{RUNS}/{{chat_id}}/{{nummer}}/stop"),
    } <= routes
    assert not [path for _, path in routes if path.endswith("/befehl")]


def test_silence_probe_the_list_of_runs_answers_as_before(client, chat_id):
    run = hintergrund.laeufe.anlegen(chat_id, "echo hello")
    hintergrund.laeufe.zeile(run, "hello")
    hintergrund.laeufe.beenden(run, 0)

    answer = client.get(f"{RUNS}/{chat_id}")

    assert answer.status_code == 200
    listed = answer.json()
    assert listed["ab"] == 3
    assert [(entry["befehl"], entry["ausgabe"], entry["zustand"]) for entry in listed["laeufe"]] == [
        ("echo hello", "hello", "fertig")
    ]


def test_silence_probe_the_stop_answers_as_before(client, chat_id):
    """A run that has ended comes back as it is; one that does not exist is
    not found."""
    run = hintergrund.laeufe.anlegen(chat_id, "echo hello")
    hintergrund.laeufe.beenden(run, 0)

    ended = client.post(f"{RUNS}/{chat_id}/{run.nummer}/stop")
    missing = client.post(f"{RUNS}/{chat_id}/99/stop")

    assert ended.status_code == 200 and ended.json()["zustand"] == "fertig"
    assert missing.status_code == 404
