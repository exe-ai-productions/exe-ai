"""The server list a fresh installation starts with.

On first start the example list becomes the user's own. Whatever stands in it
shows on the server page as a server this person has set up: switched off, or
signed out. A hosted server therefore has no place in it — the catalogue
offers every one of them with a plain connect button, and connecting is what
writes its entry.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.tools.registry import MCP_SERVER

ROOT = Path(__file__).resolve().parent.parent
SHIPPED_LIST = ROOT / "mcp_servers.example.json"


def _shipped() -> dict:
    return json.loads(SHIPPED_LIST.read_text(encoding="utf-8"))["mcpServers"]


def test_the_shipped_list_holds_only_servers_the_program_runs_itself():
    foreign = set(_shipped()) - MCP_SERVER
    assert not foreign, (
        f"{sorted(foreign)} would show on a fresh installation as already set up. "
        "A hosted server belongs to the catalogue, not to the shipped list."
    )


def test_no_shipped_entry_reaches_an_address_outside_the_program():
    for name, entry in _shipped().items():
        assert entry.get("type") == "stdio", f"{name} is not started by the program itself"
        assert "url" not in entry, f"{name} carries an address"
