"""MCP tools: the name the model calls them by, and how long a call may take.

A server's tool reaches the model as ``mcp__<server>__<tool>`` and is called
on the server by the name the server gave it. A call may take 300 seconds
unless the server's entry carries a ``timeout``; starting a server keeps its
own 30.

The calls here are real: a tiny MCP server as a subprocess over standard
input and output, and a tiny one over HTTP in the test process — protocol
instead of mock, as in test_mcp_http.py.
"""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap
from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from app import mcp_name_move
from app.tools.mcp_client import (
    CALL_TIMEOUT,
    START_TIMEOUT,
    MCPFehler,
    MCPStdioClient,
    MCPWerkzeug,
)
from app.tools.mcp_http import MCPHttpClient
from app.tools.mcp_names import model_name
from app.tools.registry import (
    ServerEintrag,
    WerkzeugRegistry,
    WerkzeugVerboten,
    konfiguration_pruefen,
)


# --- A tiny MCP server over standard input and output -------------------------

_STDIO_SERVER = textwrap.dedent(
    '''
    import json, sys, time

    TOOLS = [
        {"name": "read_file", "description": "reads", "inputSchema": {"type": "object"}},
        {"name": "slow", "description": "waits", "inputSchema": {"type": "object"}},
        {"name": "other", "description": "other", "inputSchema": {"type": "object"}},
    ]

    for line in sys.stdin:
        message = json.loads(line)
        method, ident = message.get("method"), message.get("id")
        if ident is None:
            continue
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "s"}}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = message["params"]
            if params["name"] == "slow":
                time.sleep(float(params["arguments"].get("sekunden", 5)))
            result = {"content": [{"type": "text", "text": "called:" + params["name"]}]}
        else:
            result = {}
        print(json.dumps({"jsonrpc": "2.0", "id": ident, "result": result}), flush=True)
    '''
)


@pytest.fixture
def stdio_server(tmp_path: Path) -> Path:
    script = tmp_path / "mcp_server.py"
    script.write_text(_STDIO_SERVER, encoding="utf-8")
    return script


def _stdio_entry(script: Path, name: str = "fs", **fields) -> ServerEintrag:
    return ServerEintrag(name=name, command=sys.executable, args=[str(script)], **fields)


# --- The name -----------------------------------------------------------------


def test_the_name_carries_server_and_tool():
    assert model_name("fs", "read_file") == "mcp__fs__read_file"


def test_a_character_other_than_letters_digits_and_underscore_becomes_an_underscore():
    assert model_name("my-server", "get.item v2") == "mcp__my_server__get_item_v2"


async def test_a_tool_stands_under_the_new_name_beside_the_built_in_one(stdio_server):
    """`read_file` of a server and the built-in `read_file` are both in the
    offer — they are told apart by their names now."""
    registry = WerkzeugRegistry([_stdio_entry(stdio_server)], shell_an=True)
    await registry.starten()
    try:
        offer = {w["function"]["name"] for w in registry.als_openai_werkzeuge()}
        assert "read_file" in offer  # the built-in one
        assert "mcp__fs__read_file" in offer
        assert "mcp__fs__other" in offer
        # The server's own name is not offered next to its new one.
        assert "other" not in offer
        assert registry.server_von("mcp__fs__read_file") == "fs"
    finally:
        await registry.stoppen()


async def test_the_server_is_called_by_its_own_name(stdio_server):
    registry = WerkzeugRegistry([_stdio_entry(stdio_server)], shell_an=True)
    await registry.starten()
    try:
        text = await registry.ausfuehren("mcp__fs__read_file", {})
        assert text == "called:read_file"
        with pytest.raises(WerkzeugVerboten):
            # Only the new name is a tool of this server.
            await registry.ausfuehren("other", {})
    finally:
        await registry.stoppen()


async def test_two_servers_with_an_equally_named_tool_are_both_reachable(stdio_server):
    registry = WerkzeugRegistry(
        [_stdio_entry(stdio_server, "alpha"), _stdio_entry(stdio_server, "beta")]
    )
    await registry.starten()
    try:
        offer = {w["function"]["name"] for w in registry.als_openai_werkzeuge()}
        assert {"mcp__alpha__other", "mcp__beta__other"} <= offer
        assert registry.server_von("mcp__alpha__other") == "alpha"
        assert registry.server_von("mcp__beta__other") == "beta"
    finally:
        await registry.stoppen()


async def test_allowed_tools_and_needs_confirmation_stay_under_the_servers_name(stdio_server):
    entry = _stdio_entry(
        stdio_server, allowed_tools=["read_file"], needs_confirmation=["read_file"]
    )
    registry = WerkzeugRegistry([entry])
    await registry.starten()
    try:
        assert [n for n in registry.namen() if n.startswith("mcp__")] == ["mcp__fs__read_file"]
        assert registry._werkzeuge["mcp__fs__read_file"][2] is True
        # The window shows the server's word, the switch writes the other.
        row = next(e for e in registry.uebersicht() if e["name"] == "mcp__fs__read_file")
        assert row["anzeige"] == "read_file"
        assert registry.display_name("mcp__fs__read_file") == "read_file"
    finally:
        await registry.stoppen()


def test_a_built_in_tool_keeps_its_name():
    registry = WerkzeugRegistry([], shell_an=True)
    assert "read_file" in registry.namen()
    assert registry.display_name("read_file") == "read_file"


def test_the_known_names_list_the_new_and_the_old_one():
    entry = ServerEintrag(name="fs", command="x", allowed_tools=["read_file"])
    known = WerkzeugRegistry([entry]).known_names()
    assert known is not None
    assert {"mcp__fs__read_file", "read_file"} <= known


# --- The time limit -----------------------------------------------------------


def test_by_default_a_call_may_take_300_seconds():
    assert CALL_TIMEOUT == 300
    assert MCPStdioClient("s", "x").timeout == 300
    assert MCPHttpClient("s", "http://x/mcp").timeout == 300


def test_the_timeout_field_holds_for_the_server_and_without_it_the_default_holds():
    registry = WerkzeugRegistry([])
    without_limit = registry._client_bauen(ServerEintrag(name="a", command="x"))
    with_limit = registry._client_bauen(ServerEintrag(name="b", command="x", timeout=5))
    http = registry._client_bauen(
        ServerEintrag(name="c", type="http", url="http://x/mcp", timeout=7)
    )
    assert (without_limit.timeout, with_limit.timeout, http.timeout) == (300, 5, 7)


async def test_starting_keeps_its_limit_and_the_call_has_its_own(
    stdio_server, monkeypatch
):
    limits: list[tuple[str, float]] = []
    original = MCPStdioClient._aufrufen

    async def record(self, method, parameter, limit=START_TIMEOUT):
        limits.append((method, limit))
        return await original(self, method, parameter, limit)

    monkeypatch.setattr(MCPStdioClient, "_aufrufen", record)
    client = MCPStdioClient("fs", sys.executable, [str(stdio_server)], timeout=42)
    await client.starten()
    try:
        await client.werkzeug_aufrufen("other", {})
    finally:
        await client.stoppen()

    assert limits == [("initialize", 30.0), ("tools/list", 30.0), ("tools/call", 42)]


async def test_when_the_time_runs_out_the_model_gets_a_sentence_with_server_and_time(
    stdio_server,
):
    client = MCPStdioClient("fs", sys.executable, [str(stdio_server)], timeout=0.5)
    await client.starten()
    try:
        # A quick call runs as it did.
        assert await client.werkzeug_aufrufen("other", {}) == "called:other"
        with pytest.raises(MCPFehler) as error:
            await client.werkzeug_aufrufen("slow", {"sekunden": 5})
        assert str(error.value) == (
            "MCP server 'fs' did not answer the call to 'slow' within 0.5 seconds."
        )
    finally:
        await client.stoppen()


class _SlowServer:
    """An MCP server over HTTP whose tool call takes a while."""

    def __init__(self, seconds: float) -> None:
        self.sekunden = seconds

    def app(self) -> Starlette:
        return Starlette(routes=[Route("/mcp", self.mcp, methods=["POST", "DELETE"])])

    async def mcp(self, request: Request) -> Response:
        if request.method == "DELETE":
            return Response(status_code=204)
        message = json.loads(await request.body())
        method, ident = message.get("method"), message.get("id")
        if method == "notifications/initialized":
            return Response(status_code=202)
        result: dict[str, object]
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {}}
        elif method == "tools/list":
            result = {"tools": [{"name": "wait", "description": "w", "inputSchema": {}}]}
        else:
            await asyncio.sleep(self.sekunden)
            result = {"content": [{"type": "text", "text": "done"}]}
        return JSONResponse({"jsonrpc": "2.0", "id": ident, "result": result})


def _http_client(server: _SlowServer, timeout: float) -> MCPHttpClient:
    return MCPHttpClient(
        name="web",
        url="http://testserver/mcp",
        timeout=timeout,
        transport=httpx.ASGITransport(app=server.app()),
    )


async def test_over_http_the_time_limit_holds_for_the_whole_call():
    client = _http_client(_SlowServer(seconds=3), timeout=0.4)
    await client.starten()
    try:
        with pytest.raises(MCPFehler) as error:
            await client.werkzeug_aufrufen("wait", {})
        assert str(error.value) == (
            "MCP server 'web' did not answer the call to 'wait' within 0.4 seconds."
        )
    finally:
        await client.stoppen()


async def test_over_http_a_call_within_the_time_runs_as_before():
    client = _http_client(_SlowServer(seconds=0.05), timeout=5)
    await client.starten()
    try:
        assert await client.werkzeug_aufrufen("wait", {}) == "done"
    finally:
        await client.stoppen()


@pytest.mark.parametrize("value", [5, 0.5, 300])
def test_the_check_accepts_a_time_limit(value):
    text = json.dumps(
        {"mcpServers": {"a": {"type": "stdio", "command": "x", "timeout": value}}}
    )
    assert konfiguration_pruefen(text, "en") is None


@pytest.mark.parametrize("value", [0, -3, "viel", True, [5]])
def test_the_check_refuses_an_unusable_time_limit(value):
    text = json.dumps(
        {"mcpServers": {"a": {"type": "stdio", "command": "x", "timeout": value}}}
    )
    assert konfiguration_pruefen(text, "en") == (
        "Server 'a': 'timeout' must be a number of seconds above 0."
    )


# --- The stored names move once, for each server --------------------------------


def test_an_old_name_is_replaced_and_a_built_in_one_stays_with_the_new_one_beside_it():
    mapping = {"read_file": "mcp__fs__read_file", "other": "mcp__fs__other"}
    new = mcp_name_move.move_name_list(
        ["web_search", "read_file", "other"], mapping, stays={"read_file"}
    )
    assert new == ["web_search", "read_file", "mcp__fs__read_file", "mcp__fs__other"]


def test_a_name_that_is_new_already_is_not_written_twice():
    mapping = {"other": "mcp__fs__other"}
    assert mcp_name_move.move_name_list(
        ["other", "mcp__fs__other"], mapping, stays=set()
    ) == ["mcp__fs__other"]


_AGENT = textwrap.dedent(
    """\
    ---
    description: Searches with read_file and other.
    tools:
      - web_search
      - read_file
      - "other"
    permissions:
      other: nein
      read_file: fragen
    ---

    You search. Use read_file or other.
    """
)


def test_the_agent_file_moves_only_tools_and_permissions():
    mapping = {"read_file": "mcp__fs__read_file", "other": "mcp__fs__other"}
    new = mcp_name_move.move_agent_file_text(_AGENT, mapping, stays={"read_file"})

    assert new is not None
    head, _, body = new.partition("\n---\n\n")
    # tools: the built-in name stays with the new one beside it
    assert "  - read_file\n  - mcp__fs__read_file\n" in head
    assert '  - "mcp__fs__other"' in head
    assert '  - "other"' not in head
    # permissions: the same, with the answers
    assert "  mcp__fs__other: nein" in head
    assert "  other: nein" not in head
    assert "  read_file: fragen\n  mcp__fs__read_file: fragen" in head
    # prose and body are not touched
    assert "description: Searches with read_file and other." in head
    assert body == "You search. Use read_file or other.\n"


def test_an_agent_file_in_flow_style_is_moved():
    text = "---\ntools: [web_search, other]\n---\n\nHi.\n"
    new = mcp_name_move.move_agent_file_text(
        text, {"other": "mcp__fs__other"}, stays=set()
    )
    assert new == "---\ntools: [web_search, mcp__fs__other]\n---\n\nHi.\n"


def test_an_agent_file_without_old_names_stays_unchanged():
    assert mcp_name_move.move_agent_file_text(
        "---\ntools:\n  - web_search\n---\n\nHi.\n", {"other": "mcp__fs__other"}, set()
    ) is None
    # No header at all.
    assert mcp_name_move.move_agent_file_text("kein Kopf", {"a": "b"}, set()) is None


class _Settings:
    """The two calls the move makes of the settings store."""

    def __init__(self, rows: dict[str, object]) -> None:
        self.rows = dict(rows)

    def all_with_key(self, key: str):
        assert key == "werkzeuge_aus"
        return list(self.rows.items())

    def setzen(self, scope: str, key: str, value):
        self.rows[scope] = value


class _Repositories:
    def __init__(self, rows: dict[str, object]) -> None:
        self.einstellungen = _Settings(rows)


def _move(tmp_path: Path, repositories, server="fs", tools=("read_file", "other")):
    return mcp_name_move.move_for_server(
        server,
        list(tools),
        built_in={"read_file", "web_search"},
        repositories=repositories,
        agent_folder=tmp_path / "agenten",
        rules_path=tmp_path / "berechtigungen.json",
        marker=tmp_path / "mcp_namen.json",
    )


def test_the_move_reaches_settings_agent_files_and_rules(tmp_path):
    agents = tmp_path / "agenten"
    agents.mkdir()
    (agents / "sucher.md").write_text(_AGENT, encoding="utf-8")
    rules = tmp_path / "berechtigungen.json"
    rules.write_text(
        json.dumps({"standard": {"chat": "ja"}, "regeln": {"other": "nein", "shell": "fragen"}}),
        encoding="utf-8",
    )
    repositories = _Repositories(
        {"global": ["other", "read_file"], "chat:1": ["unrelated"], "modell:m": "kaputt"}
    )

    assert _move(tmp_path, repositories) is True

    rows = repositories.einstellungen.rows
    assert rows["global"] == ["mcp__fs__other", "read_file", "mcp__fs__read_file"]
    assert rows["chat:1"] == ["unrelated"]
    assert rows["modell:m"] == "kaputt"
    text = (agents / "sucher.md").read_text(encoding="utf-8")
    assert "mcp__fs__other" in text and "  - other\n" not in text
    saved = json.loads(rules.read_text(encoding="utf-8"))
    assert saved["regeln"] == {"mcp__fs__other": "nein", "shell": "fragen"}
    assert saved["standard"] == {"chat": "ja"}


def test_a_server_is_moved_only_once(tmp_path):
    repositories = _Repositories({"global": ["other"]})
    assert _move(tmp_path, repositories) is True
    assert repositories.einstellungen.rows["global"] == ["mcp__fs__other"]

    # A person puts the plain name back; the next start of the same server
    # leaves it as it is.
    repositories.einstellungen.rows["global"] = ["other"]
    assert _move(tmp_path, repositories) is False
    assert repositories.einstellungen.rows["global"] == ["other"]
    # Another server is its own case.
    repositories.einstellungen.rows["global"] = ["thing"]
    assert _move(tmp_path, repositories, server="web", tools=("thing",)) is True
    assert repositories.einstellungen.rows["global"] == ["mcp__web__thing"]


def test_a_server_without_tools_is_not_noted_as_moved(tmp_path):
    assert _move(tmp_path, _Repositories({}), tools=()) is False
    assert not (tmp_path / "mcp_namen.json").exists()


async def test_the_registry_reports_all_tools_of_the_server_to_the_move(stdio_server):
    """Also the ones the entry does not release: a list may name them."""
    reported: list[tuple[str, list[str]]] = []
    entry = _stdio_entry(stdio_server, allowed_tools=["other"])
    registry = WerkzeugRegistry(
        [entry], on_tool_list=lambda server, names: reported.append((server, names))
    )
    await registry.starten()
    try:
        assert reported == [("fs", ["read_file", "slow", "other"])]
        assert [n for n in registry.namen() if n.startswith("mcp__")] == ["mcp__fs__other"]
    finally:
        await registry.stoppen()


async def test_a_failing_move_does_not_take_the_server_down(stdio_server):
    def broken(server, names):
        raise RuntimeError("boom")

    registry = WerkzeugRegistry([_stdio_entry(stdio_server)], on_tool_list=broken)
    await registry.starten()
    try:
        assert "mcp__fs__other" in registry.namen()
    finally:
        await registry.stoppen()


def test_the_tool_names_itself_by_the_name_it_is_given():
    tool = MCPWerkzeug(name="read_file", beschreibung="x", server="fs")
    assert tool.als_openai_werkzeug()["function"]["name"] == "read_file"
    assert (
        tool.als_openai_werkzeug("mcp__fs__read_file")["function"]["name"]
        == "mcp__fs__read_file"
    )
