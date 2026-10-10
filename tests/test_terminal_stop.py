"""Stopping one command from the terminal, and the folder it runs in.

A running command — in the foreground or the background — stops with its
whole process tree when its stop is pressed, and its run then reads
"stopped" rather than failed. Another run of the same chat goes on, and a
run that has already ended is simply returned.
"""

from __future__ import annotations

import asyncio
import os
import re
import time

import pytest
from fastapi import HTTPException

from app.api.v1 import befehle
from app.tools import hintergrund, ordnergedaechtnis, shell
from tests.conftest import python_command


@pytest.fixture(autouse=True)
def clean():
    ordnergedaechtnis.vergessen()
    hintergrund.laeufe._laeufe.clear()
    hintergrund.laeufe._ereignisse.clear()
    hintergrund.laeufe.abschluss = None
    yield
    ordnergedaechtnis.vergessen()
    hintergrund.laeufe._laeufe.clear()
    hintergrund.laeufe._ereignisse.clear()
    hintergrund.laeufe.abschluss = None


@pytest.fixture()
def folders(tmp_path):
    return [str(tmp_path)]


# A command that stays, on every system.
SLEEP_60 = python_command("import time; time.sleep(60)")


async def _until(condition, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.05)
    return condition()


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def _route(client, chat_id, nummer):
    return befehle.lauf_stoppen(
        chat_id, nummer, repositories=client.app.state.repositories,
        user_id="standard", sprache="en",
    )


async def _background_with_child(folders, chat="chat-1"):
    """A background run whose shell starts a child and says its number."""
    await shell.ausfuehren(
        {"command": "sleep 60 & echo child=$!; wait", "background": True}, folders, chat
    )
    run = hintergrund.laeufe.laeufe(chat)[-1]
    assert await _until(lambda: "child=" in run.ausgabe)
    child = int(re.search(r"child=(\d+)", run.ausgabe).group(1))
    return run, child


@pytest.mark.asyncio
@pytest.mark.platforms("posix", reason="a shell child by `$!` and `wait`")
async def test_the_stop_route_ends_a_background_command_and_its_child(folders, client, chat_id):
    reports = []
    hintergrund.laeufe.abschluss = lambda run, text: reports.append(text)
    run, child = await _background_with_child(folders, chat=chat_id)

    answer = await _route(client, chat_id, run.nummer)

    assert await _until(lambda: run.zustand != hintergrund.LAEUFT)
    assert answer["lauf"] == run.nummer
    assert run.zustand == hintergrund.ABGEBROCHEN
    assert await _until(lambda: _gone(child)), "the child outlived the stop"
    assert await _until(lambda: bool(reports))
    assert reports[0].startswith(shell.STOPPED_BY_USER)


@pytest.mark.asyncio
async def test_a_foreground_command_stops_and_its_call_says_so(folders):
    call = asyncio.create_task(shell.ausfuehren({"command": SLEEP_60}, folders, "chat-1"))
    assert await _until(lambda: bool(hintergrund.laeufe.laeufe("chat-1")))
    run = hintergrund.laeufe.laeufe("chat-1")[-1]
    assert await _until(lambda: run.prozess is not None)

    await hintergrund.laeufe.stop("chat-1", run.nummer)
    answer = await asyncio.wait_for(call, timeout=15)

    assert answer.startswith(shell.STOPPED_BY_USER)
    assert run.zustand == hintergrund.ABGEBROCHEN


@pytest.mark.asyncio
@pytest.mark.platforms("posix", reason="a shell child by `$!` and `wait`")
async def test_another_run_of_the_chat_goes_on(folders):
    """The silence probe: only the run whose stop was pressed ends."""
    stopped, _ = await _background_with_child(folders)
    other, other_child = await _background_with_child(folders)

    await hintergrund.laeufe.stop("chat-1", stopped.nummer)

    assert await _until(lambda: stopped.zustand == hintergrund.ABGEBROCHEN)
    assert other.zustand == hintergrund.LAEUFT
    assert not _gone(other_child)
    await hintergrund.laeufe.stop("chat-1", other.nummer)


@pytest.mark.asyncio
async def test_stopping_a_finished_run_is_no_fault(folders, client, chat_id):
    await shell.ausfuehren({"command": "echo done"}, folders, chat_id)
    run = hintergrund.laeufe.laeufe(chat_id)[-1]

    answer = await _route(client, chat_id, run.nummer)

    assert answer["zustand"] == hintergrund.FERTIG
    assert run.stop_requested is False


@pytest.mark.asyncio
async def test_an_unknown_run_and_a_run_outside_a_chat_are_not_found(folders, client, chat_id):
    """A schedule's script keeps its runs under its job, not under a chat:
    it is stopped from there, not from here."""
    await shell.ausfuehren({"command": "echo done"}, folders, "job-1")

    for owner, nummer in ((chat_id, 99), ("job-1", 1)):
        with pytest.raises(HTTPException) as missing:
            await _route(client, owner, nummer)
        assert missing.value.status_code == 404


def test_a_command_that_finished_as_stop_was_pressed_finished():
    run = hintergrund.laeufe.anlegen("chat-1", "true")
    run.stop_requested = True
    hintergrund.laeufe.beenden(run, 0)
    assert run.zustand == hintergrund.FERTIG

    cut = hintergrund.laeufe.anlegen("chat-1", "sleep 9")
    cut.stop_requested = True
    hintergrund.laeufe.beenden(cut, -15)
    assert cut.zustand == hintergrund.ABGEBROCHEN
    # The signal's number is not shown as the command's exit code.
    assert cut.code is None


@pytest.mark.asyncio
async def test_a_stop_that_runs_into_the_time_limit_stays_the_users(folders):
    call = asyncio.create_task(
        shell.ausfuehren({"command": SLEEP_60}, folders, "chat-1", zeitgrenze=1)
    )
    assert await _until(lambda: bool(hintergrund.laeufe.laeufe("chat-1")))
    hintergrund.laeufe.laeufe("chat-1")[-1].stop_requested = True

    answer = await asyncio.wait_for(call, timeout=15)

    assert answer.startswith(shell.STOPPED_BY_USER)
    assert "background set to true" not in answer


@pytest.mark.asyncio
async def test_a_run_names_the_folder_it_runs_in(folders, tmp_path):
    await shell.ausfuehren({"command": "echo here"}, folders, "chat-1")
    run = hintergrund.laeufe.laeufe("chat-1")[-1]

    assert run.folder == str(tmp_path.resolve())
    assert befehle._als_daten(run)["folder"] == run.folder
    start = next(
        event for event in hintergrund.laeufe._ereignisse["chat-1"]
        if event["typ"] == "lauf_start"
    )
    assert start["folder"] == run.folder
