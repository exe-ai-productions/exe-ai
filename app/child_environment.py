"""The environment of a process the model starts.

A command from ``run_command``, a script of a schedule and an MCP server
that starts as a program all inherit the environment of the service — and
the service holds the keys of every provider in it: ``config_laden`` puts
each line of the ``.env`` files into ``os.environ``. A command as plain as
``env`` then hands those keys to the model, past every lock on the data
folder.

So such a process gets the environment WITHOUT the names Exe AI keeps as
secrets, and nothing else is taken: ``PATH``, ``HOME``, the language and the
user's own variables stay, because the user expects the terminal they know.
A server that needs a key gets it the one way the entry names it, in its own
``env`` with ``${NAME}``.

The names are read at every call, not once at start: a key saved a moment
ago belongs to them already.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import dotenv_values

if TYPE_CHECKING:
    from app.config import Config

# The name of the variable that points at the password file of the service.
PASSWORD_FILE_VARIABLE = "EXE_AI_PASSWORD_FILE"

_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_-]*)\}")

# The configuration the service runs with: where the endpoints and the server
# file are read from. Set once at start (``use``).
_config: Config | None = None


def use(config: Config) -> None:
    """Names the configuration whose keys are secrets."""
    global _config
    _config = config


def _env_files() -> list[Path]:
    """The ``.env`` files ``config_laden`` reads, in the same two places."""
    from app.config import PROJEKT_WURZEL
    from app.paketierung import aufloesen, eigene_wurzel

    files = [aufloesen(".env", schreibbar=True)]
    if eigene_wurzel() is None:
        files.insert(0, PROJEKT_WURZEL / ".env")
    return files


def _server_file_names(config: Config) -> set[str]:
    """The variables the entries of the server file read as keys: the
    ``api_key_env`` of an entry and every ``${NAME}`` in its headers."""
    names: set[str] = set()
    try:
        raw = json.loads(config.pfad(config.mcp.servers_file).read_text(encoding="utf-8"))
        entries = (raw.get("mcpServers") or {}).values()
    except (OSError, ValueError, AttributeError):
        return names
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = entry.get("api_key_env")
        if isinstance(key, str) and key:
            names.add(key)
        headers = entry.get("headers")
        if isinstance(headers, dict):
            for value in headers.values():
                names.update(_PLACEHOLDER.findall(str(value)))
    return names


def _program_names() -> set[str]:
    """The variables the service itself puts a key into: the one each model
    server gets for a start, and the Hugging Face token."""
    from app import agentenserver, einbettungsserver, modellrunner, sprachserver

    return {
        modellrunner.SCHLUESSEL_VARIABLE,
        einbettungsserver.SCHLUESSEL_VARIABLE,
        agentenserver.SCHLUESSEL_VARIABLE,
        sprachserver.SCHLUESSEL_VARIABLE,
        sprachserver.PUTZ_SCHLUESSEL_VARIABLE,
        "HF_TOKEN",
    }


def secret_names() -> set[str]:
    """Every name Exe AI keeps as a secret: each name in the ``.env`` files,
    each ``api_key_env`` of the configuration (endpoints, providers, server
    entries), the variables of the model servers and the password file."""
    names: set[str] = {PASSWORD_FILE_VARIABLE}
    for path in _env_files():
        names.update(dotenv_values(path))
    names.update(_program_names())
    if _config is not None:
        names.update(
            endpoint.api_key_env for endpoint in _config.endpoints if endpoint.api_key_env
        )
        names.update(_server_file_names(_config))
    return names


def without_secrets(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """``environ`` — this process's own by default — without the secrets.
    Windows reads a variable name in any case, so the comparison there does
    too."""
    fold = str.upper if os.name == "nt" else (lambda name: name)
    secrets = {fold(name) for name in secret_names()}
    source = os.environ if environ is None else environ
    return {name: value for name, value in source.items() if fold(name) not in secrets}
