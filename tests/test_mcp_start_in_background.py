"""MCP: the start does not wait for the servers.

The service answers at once with the built-in tools; the servers start behind
it, side by side, and each brings its tools into the offer when it is ready.
A server that never answers costs the others nothing, names its reason in the
log and has its process ended; a service that ends while servers are still
starting ends them too.

The servers are real: tiny MCP servers as subprocesses over standard input and
output, one that answers and one that answers ``initialize`` and then never
the tool list — protocol instead of mock, as in test_mcp_names_and_time_limit.py.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import textwrap
import time
from pathlib import Path

import psutil
import pytest

from app.tools import mcp_client
from app.tools.registry import ServerEintrag, WerkzeugRegistry

_ANSWERING = textwrap.dedent(
    '''
    import json, sys

    for line in sys.stdin:
        message = json.loads(line)
        method, ident = message.get("method"), message.get("id")
        if ident is None:
            continue
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "s"}}
        elif method == "tools/list":
            result = {"tools": [{"name": "other", "description": "x", "inputSchema": {"type": "object"}}]}
        else:
            result = {}
        print(json.dumps({"jsonrpc": "2.0", "id": ident, "result": result}), flush=True)
    '''
)

# Writes its process id where the test can read it, answers ``initialize``,
# and never answers the tool list.
_HANGING = textwrap.dedent(
    '''
    import json, os, sys, time

    open(sys.argv[1], "w").write(str(os.getpid()))
    for line in sys.stdin:
        message = json.loads(line)
        method, ident = message.get("method"), message.get("id")
        if ident is None:
            continue
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "h"}}
            print(json.dumps({"jsonrpc": "2.0", "id": ident, "result": result}), flush=True)
        elif method == "tools/list":
            time.sleep(600)
    '''
)


@pytest.fixture
def answering_entry(tmp_path: Path) -> ServerEintrag:
    script = tmp_path / "answering.py"
    script.write_text(_ANSWERING, encoding="utf-8")
    return ServerEintrag(name="fs", command=sys.executable, args=[str(script)])


@pytest.fixture
def hanging_entries(tmp_path: Path) -> list[ServerEintrag]:
    script = tmp_path / "hanging.py"
    script.write_text(_HANGING, encoding="utf-8")
    return [
        ServerEintrag(
            name=name, command=sys.executable, args=[str(script), str(tmp_path / f"{name}.pid")]
        )
        for name in ("stuck_a", "stuck_b")
    ]


def _pid(tmp_path: Path, name: str) -> int:
    return int((tmp_path / f"{name}.pid").read_text(encoding="utf-8"))


async def _wait_for(condition, seconds: float = 15.0) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "the condition never held"
        await asyncio.sleep(0.05)


async def test_the_service_is_ready_while_a_server_still_starts(hanging_entries):
    registry = WerkzeugRegistry([hanging_entries[0]])
    began = time.monotonic()
    task = registry.start_in_background()
    try:
        assert time.monotonic() - began < 1.0
        assert not task.done()
        assert registry.builtin_names()
        assert registry.clients == {}
    finally:
        await registry.stoppen(frist=2)


async def test_the_tools_of_an_answering_server_are_offered_before_a_hanging_one_gives_up(
    answering_entry, hanging_entries, monkeypatch
):
    monkeypatch.setattr(mcp_client, "START_TIMEOUT", 6.0)
    registry = WerkzeugRegistry([hanging_entries[0], answering_entry])
    task = registry.start_in_background()
    try:
        await _wait_for(lambda: "mcp__fs__other" in registry.namen())
        assert not task.done(), "the hanging server was still starting"
        assert list(registry.clients) == ["fs"]
    finally:
        await registry.stoppen(frist=2)


async def test_a_hanging_server_names_its_reason_and_its_process_is_ended(
    hanging_entries, monkeypatch, caplog, tmp_path
):
    monkeypatch.setattr(mcp_client, "START_TIMEOUT", 1.0)
    registry = WerkzeugRegistry([hanging_entries[0]])
    with caplog.at_level(logging.ERROR):
        await registry.starten()
    line = next(r.getMessage() for r in caplog.records if "could not start" in r.getMessage())
    assert "stuck_a" in line
    assert "tools/list" in line
    assert "1 seconds" in line
    assert not psutil.pid_exists(_pid(tmp_path, "stuck_a"))
    assert registry.clients == {}


async def test_two_hanging_servers_cost_one_time_limit(hanging_entries, monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_client, "START_TIMEOUT", 2.0)
    registry = WerkzeugRegistry(hanging_entries)
    began = time.monotonic()
    await registry.starten()
    elapsed = time.monotonic() - began
    assert 2.0 <= elapsed < 3.6, "side by side, not one after the other"
    for entry in hanging_entries:
        assert not psutil.pid_exists(_pid(tmp_path, entry.name))


async def test_ending_the_service_ends_the_servers_still_starting(hanging_entries, tmp_path):
    registry = WerkzeugRegistry(hanging_entries)
    task = registry.start_in_background()
    await _wait_for(
        lambda: all((tmp_path / f"{e.name}.pid").exists() for e in hanging_entries)
    )
    pids = [_pid(tmp_path, e.name) for e in hanging_entries]
    # Both have been given their request: they are in the middle of the start.
    await asyncio.sleep(0.5)
    began = time.monotonic()
    await registry.stoppen(frist=5)
    assert time.monotonic() - began < 8.0
    assert task.done()
    for pid in pids:
        assert not psutil.pid_exists(pid)


async def test_an_answering_server_stands_in_the_offer_as_before(answering_entry):
    reported: list[tuple[str, list[str]]] = []
    registry = WerkzeugRegistry(
        [answering_entry], on_tool_list=lambda server, names: reported.append((server, names))
    )
    await registry.starten()
    try:
        assert [n for n in registry.namen() if n.startswith("mcp__")] == ["mcp__fs__other"]
        assert reported == [("fs", ["other"])]
    finally:
        await registry.stoppen()


def test_a_start_failure_names_the_kind_and_the_text():
    assert mcp_client.start_failure_text(OSError("no such file")) == "OSError: no such file"
    assert mcp_client.start_failure_text(TimeoutError()) == "TimeoutError"
    assert mcp_client.start_failure_text(mcp_client.MCPFehler("gone")) == "gone"
    assert (
        mcp_client.start_time_limit_sentence("fs", "tools/list", 30.0)
        == "MCP server 'fs' did not answer 'tools/list' within 30 seconds."
    )
