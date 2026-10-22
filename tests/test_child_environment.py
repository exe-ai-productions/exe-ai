"""The environment of a process the model starts: without the keys.

The service holds the keys of every provider in its environment, and a plain
``env`` from ``run_command`` — or a script, or an MCP server that starts as a
program — would hand them over. These tests pin what such a process gets
instead: the environment of the service minus the names Exe AI keeps as
secrets, and nothing else taken.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from app import child_environment, skriptlauf
from app.tools import WerkzeugRegistry, shell
from app.tools.mcp_client import MCPStdioClient
from app.tools.registry import ServerEintrag
from tests.conftest import script_file


@pytest.fixture
def secrets(config, tmp_path, monkeypatch) -> Path:
    """A ``.env`` with one made-up key, an endpoint and two server entries
    that name keys of their own, and the variables themselves set."""
    env_file = tmp_path / "dot.env"
    env_file.write_text("EXE_TEST_SECRET=x\n", encoding="utf-8")
    monkeypatch.setattr(child_environment, "_env_files", lambda: [env_file])
    monkeypatch.setattr(child_environment, "_config", config)
    config.endpoints.append(
        config.endpoints[0].model_copy(update={"id": "keyed", "api_key_env": "EXE_TEST_KEY"})
    )
    servers = config.pfad(config.mcp.servers_file)
    servers.parent.mkdir(parents=True, exist_ok=True)
    servers.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "hosted": {"type": "http", "url": "https://x.test/mcp", "api_key_env": "EXE_FILE_KEY"},
                    "headed": {
                        "type": "http", "url": "https://y.test/mcp",
                        "headers": {"X-Key": "${EXE_HEADER_KEY}"},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    for name in ("EXE_TEST_SECRET", "EXE_TEST_KEY", "EXE_FILE_KEY", "EXE_HEADER_KEY"):
        monkeypatch.setenv(name, "made-up")
    monkeypatch.setenv("EXE_NOT_A_SECRET", "kept")
    return env_file


def test_the_names_are_the_env_files_the_endpoints_the_server_file_and_the_password_file(secrets):
    names = child_environment.secret_names()
    assert {
        "EXE_TEST_SECRET", "EXE_TEST_KEY", "EXE_FILE_KEY", "EXE_HEADER_KEY",
        child_environment.PASSWORD_FILE_VARIABLE,
    } <= names
    assert "EXE_NOT_A_SECRET" not in names


def test_a_key_saved_after_the_start_belongs_to_the_names_at_once(secrets, monkeypatch):
    assert "EXE_LATE_KEY" not in child_environment.secret_names()
    secrets.write_text("EXE_TEST_SECRET=x\nEXE_LATE_KEY=y\n", encoding="utf-8")
    monkeypatch.setenv("EXE_LATE_KEY", "made-up")
    assert "EXE_LATE_KEY" in child_environment.secret_names()
    assert "EXE_LATE_KEY" not in child_environment.without_secrets()


def test_the_environment_loses_the_secrets_and_keeps_everything_else(secrets):
    environment = child_environment.without_secrets()
    for name in ("EXE_TEST_SECRET", "EXE_TEST_KEY", "EXE_FILE_KEY", "EXE_HEADER_KEY"):
        assert name not in environment
    assert environment["EXE_NOT_A_SECRET"] == "kept"
    assert environment["PATH"] == os.environ["PATH"]
    assert environment.get("HOME") == os.environ.get("HOME")


def test_a_given_environment_is_cleaned_instead_of_the_own(secrets):
    given = {"EXE_TEST_SECRET": "a", "KEEP": "b"}
    assert child_environment.without_secrets(given) == {"KEEP": "b"}


@pytest.mark.skipif(os.name == "nt", reason="the command lists its environment with env")
async def test_run_command_does_not_show_the_keys(secrets, tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    shown = await shell.ausfuehren({"command": "env"}, [str(folder)], data_dir=tmp_path / "data")
    assert "EXE_TEST_SECRET" not in shown and "EXE_TEST_KEY" not in shown
    assert "EXE_NOT_A_SECRET=kept" in shown
    assert "PATH=" in shown


async def test_a_script_does_not_inherit_the_keys(secrets, config, monkeypatch):
    seen: list[dict] = []

    async def fake_exec(*argv, **kwargs):
        seen.append(kwargs)
        raise OSError(2, "stop here")

    monkeypatch.setattr(skriptlauf.asyncio, "create_subprocess_exec", fake_exec)
    folder = skriptlauf.ordner(config)
    folder.mkdir(parents=True, exist_ok=True)
    path = script_file(folder, "night.py", "print(1)\n")
    await skriptlauf.starten(path, folder, 10)
    (kwargs,) = seen
    assert "EXE_TEST_SECRET" not in kwargs["env"]
    assert kwargs["env"]["EXE_NOT_A_SECRET"] == "kept"
    assert kwargs["env"]["PATH"] == os.environ["PATH"]


async def test_a_server_gets_a_key_only_where_its_own_entry_names_it(secrets, monkeypatch):
    seen: dict[str, dict] = {}
    current = {"name": ""}

    async def fake_exec(*argv, **kwargs):
        seen[current["name"]] = kwargs["env"]
        raise OSError(2, "stop here")

    import app.tools.mcp_client as mcp_client

    monkeypatch.setattr(mcp_client.asyncio, "create_subprocess_exec", fake_exec)
    registry = WerkzeugRegistry([])
    plain = ServerEintrag(name="plain", command=sys.executable, args=["-c", "pass"], env={})
    naming = ServerEintrag(
        name="naming", command=sys.executable, args=["-c", "pass"],
        env={"EXE_TEST_SECRET": "${EXE_TEST_SECRET}"},
    )
    for entry in (plain, naming):
        client = registry._client_bauen(entry)
        assert isinstance(client, MCPStdioClient)
        current["name"] = entry.name
        with pytest.raises(OSError):
            await client.starten()

    assert "EXE_TEST_SECRET" not in seen["plain"]
    assert seen["naming"]["EXE_TEST_SECRET"] == "made-up"
    assert "EXE_TEST_KEY" not in seen["naming"]
    # The silence probe: the rest of the environment is theirs as before.
    for environment in seen.values():
        assert environment["PATH"] == os.environ["PATH"]
        assert environment["EXE_NOT_A_SECRET"] == "kept"
