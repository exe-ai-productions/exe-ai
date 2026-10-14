"""Moves the lists and rules that name an MCP tool to the name the model is
offered it under.

A tool of a server used to be offered under the name the server gave it, and
three places that were written then still carry that name: the tools a
person switched off (``werkzeuge_aus`` in every scope of the settings), the
``tools:`` and ``permissions:`` of the user's agent files, and the rules in
``berechtigungen.json``. From now on the model is offered
``mcp__<server>__<tool>`` (``app/tools/mcp_names.py``) and those places are
read by that name, so each of them is moved once, for each server, as soon as
the server reports its tools.

An old name that a built-in tool carries as well (``read_file``) may have
meant the built-in one: it stays, and the new name is added beside it, so
that what was switched off, allowed or refused before still is — for the
built-in tool and for the server's alike.

A server that was moved is written down, and is not moved again: a person who
later puts the plain name back into a list means the built-in tool then.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app import atomic_file
from app.tools.mcp_names import model_name

log = logging.getLogger(__name__)

# The key of the settings cascade the switched-off tools are kept under.
OFF_TOOLS_KEY = "werkzeuge_aus"

# The two header fields of an agent file that name tools.
_HEADER_FIELDS = ("tools", "permissions")

_KEY_LINE = re.compile(r"^([A-Za-z_][\w-]*)\s*:(.*)$")
_LIST_ENTRY = re.compile(r"^(\s*-\s*)(['\"]?)([^'\"#\s][^'\"#]*?)\2(\s*(#.*)?)$")
_MAP_ENTRY = re.compile(r"^(\s+)(['\"]?)([^'\"#:\s][^'\"#:]*?)\2(\s*:.*)$")
_FLOW_LIST = re.compile(r"^(\s*)\[(.*)\](\s*(#.*)?)$")
_FLOW_MAP = re.compile(r"^(\s*)\{(.*)\}(\s*(#.*)?)$")
_BOM = b"\xef\xbb\xbf"


def _name_mapping(server: str, tools: list[str]) -> dict[str, str]:
    return {name: model_name(server, name) for name in tools}


# --- A list of names ------------------------------------------------------


def move_name_list(
    names: list[str], mapping: dict[str, str], stays: set[str]
) -> list[str]:
    """``namen`` with each moved name replaced by its new one; one that
    ``bleibt`` stays and has the new one beside it. Order is kept."""
    result: list[str] = []
    for name in names:
        new = mapping.get(name)
        if new is None:
            result.append(name)
            continue
        if name in stays:
            result.append(name)
        # Already listed under the new name: the old one just goes.
        if new not in result and new not in names:
            result.append(new)
    return result


# --- The settings -----------------------------------------------------------


def _move_settings(
    repositories: Any, mapping: dict[str, str], stays: set[str]
) -> int:
    """``werkzeuge_aus`` in every scope. How many scopes were changed."""
    changed = 0
    settings = repositories.einstellungen
    for scope, value in settings.all_with_key(OFF_TOOLS_KEY):
        if not isinstance(value, list) or not all(isinstance(n, str) for n in value):
            continue
        new = move_name_list(value, mapping, stays)
        if new != value:
            settings.setzen(scope, OFF_TOOLS_KEY, new)
            changed += 1
    return changed


# --- The agent files --------------------------------------------------------


def _replace_lines(
    lines: list[str], mapping: dict[str, str], stays: set[str]
) -> list[str]:
    """The lines of one header field (``tools`` or ``permissions``) with its
    names moved; every other character stays as it was written."""
    result: list[str] = []
    for line in lines:
        match = _LIST_ENTRY.match(line)
        if match is not None:
            before, quote_mark, name, after = match.group(1), match.group(2), match.group(3), match.group(4)
            new = mapping.get(name.strip())
            if new is None:
                result.append(line)
                continue
            if name.strip() in stays:
                result.append(line)
                result.append(f"{before}{quote_mark}{new}{quote_mark}{after}")
            else:
                result.append(f"{before}{quote_mark}{new}{quote_mark}{after}")
            continue
        match = _MAP_ENTRY.match(line)
        if match is not None:
            before, quote_mark, name, after = match.group(1), match.group(2), match.group(3), match.group(4)
            new = mapping.get(name.strip())
            if new is None:
                result.append(line)
                continue
            if name.strip() in stays:
                result.append(line)
            result.append(f"{before}{quote_mark}{new}{quote_mark}{after}")
            continue
        result.append(line)
    return result


def _replace_flow_list(
    content: str, mapping: dict[str, str], stays: set[str]
) -> str:
    """``[a, b]`` — the inside of a list written on the key's own line."""
    names = [part.strip().strip("'\"") for part in content.split(",")]
    new = move_name_list([n for n in names if n], mapping, stays)
    if new == [n for n in names if n]:
        return content
    return ", ".join(new)


def _move_flow_map(inside: str, mapping: dict[str, str], stays: set[str]) -> str:
    """``{a: allow, b: deny}`` — the inside of a mapping written on the key's
    own line. A name that moved keeps the value it had."""
    entries = [entry.strip() for entry in inside.split(",") if entry.strip()]
    keys = {entry.partition(":")[0].strip().strip("'\"") for entry in entries}
    result: list[str] = []
    for entry in entries:
        key, colon, value = entry.partition(":")
        name = key.strip().strip("'\"")
        new = mapping.get(name)
        if new is None or not colon:
            result.append(entry)
            continue
        if name in stays:
            result.append(entry)
        if new not in keys:
            quote = key.strip()[0] if key.strip()[:1] in ("'", '"') else ""
            result.append(f"{quote}{new}{quote}:{value}")
    return inside if result == entries else ", ".join(result)


def move_agent_file_text(
    text: str, mapping: dict[str, str], stays: set[str]
) -> str | None:
    """The agent file's text with ``tools`` and ``permissions`` moved — or
    ``None`` where it holds nothing to move (or has no header to read)."""
    if not text.startswith("---"):
        return None
    lines = text.split("\n")
    # The header ends at the next line that is exactly the marker.
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return None
    head = lines[1:end]

    new_head: list[str] = []
    current: str | None = None
    block: list[str] = []

    def finish() -> None:
        if current in _HEADER_FIELDS:
            new_head.extend(_replace_lines(block, mapping, stays))
        else:
            new_head.extend(block)

    for line in head:
        match = _KEY_LINE.match(line)
        if match is not None and not line.startswith((" ", "\t")):
            finish()
            current = match.group(1)
            rest = match.group(2)
            flow = _FLOW_LIST.match(rest)
            if current == "tools" and flow is not None:
                inner = _replace_flow_list(flow.group(2), mapping, stays)
                line = f"{current}:{flow.group(1)}[{inner}]{flow.group(3)}"
                new_head.append(line)
                current = None
                block = []
                continue
            flow_map = _FLOW_MAP.match(rest) if current == "permissions" else None
            if flow_map is not None:
                inside = _move_flow_map(flow_map.group(2), mapping, stays)
                new_head.append(f"{current}:{flow_map.group(1)}{{{inside}}}{flow_map.group(3)}")
                current = None
                block = []
                continue
            block = [line]
            continue
        block.append(line)
    finish()

    if new_head == head:
        return None
    return "\n".join([lines[0], *new_head, *lines[end:]])


def _move_agent_files(
    folder: Path, mapping: dict[str, str], stays: set[str]
) -> int:
    """The user's agent files. How many were changed. A file that cannot be
    read is left as it is: it is not this move's to touch. Everything
    outside the moved names stays as it was written — the line endings and a
    byte order mark included."""
    if not folder.is_dir():
        return 0
    changed = 0
    for agent_file in sorted(folder.glob("*.md")):
        if not agent_file.is_file():
            continue
        try:
            raw = agent_file.read_bytes()
            bom = raw.startswith(_BOM)
            text = (raw[len(_BOM):] if bom else raw).decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new = move_agent_file_text(text, mapping, stays)
        if new is None:
            continue
        try:
            atomic_file.write(agent_file, (_BOM if bom else b"") + new.encode("utf-8"))
        except OSError as error:
            log.warning("Agent file %s could not be updated: %s", agent_file.name, error)
            continue
        changed += 1
    return changed


# --- The permission rules ---------------------------------------------------


def _move_rules(path: Path | None, mapping: dict[str, str], stays: set[str]) -> int:
    """The names under ``regeln`` in ``berechtigungen.json``. 1 where the
    file was changed, else 0. A file that is not what it should be is left
    alone — saying so is the loader's work."""
    if path is None or not path.is_file():
        return 0
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    rules = document.get("regeln") if isinstance(document, dict) else None
    if not isinstance(rules, dict):
        return 0
    new: dict[str, Any] = {}
    changed = False
    for name, value in rules.items():
        target = mapping.get(name) if isinstance(name, str) else None
        if target is None:
            new[name] = value
            continue
        if name in stays:
            new[name] = value
        if target not in rules:
            new[target] = value
        changed = changed or name not in stays or target not in rules
    if not changed:
        return 0
    document["regeln"] = new
    atomic_file.write(path, json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    return 1


# --- Once for each server ---------------------------------------------------


def _moved_servers(marker: Path) -> set[str]:
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    listed = data.get("server") if isinstance(data, dict) else None
    return {n for n in listed if isinstance(n, str)} if isinstance(listed, list) else set()


def move_for_server(
    server: str,
    tools: list[str],
    *,
    built_in: set[str],
    repositories: Any,
    agent_folder: Path,
    rules_path: Path | None,
    marker: Path,
) -> bool:
    """Moves what names ``server``'s tools to the new names, once.

    ``werkzeuge`` is every tool the server reported, ``eingebaut`` the names
    the program's own tools carry. Returns whether it moved anything — a
    server already moved, or one that reported nothing, does not.
    """
    if not tools:
        return False
    already = _moved_servers(marker)
    if server in already:
        return False
    mapping = _name_mapping(server, tools)
    stays = {name for name in tools if name in built_in}
    settings = _move_settings(repositories, mapping, stays)
    agents = _move_agent_files(agent_folder, mapping, stays)
    rules = _move_rules(rules_path, mapping, stays)
    atomic_file.write(
        marker, json.dumps({"server": sorted(already | {server})}, indent=2) + "\n"
    )
    if settings or agents or rules:
        log.info(
            "Tool names of '%s' moved: %d setting(s), %d agent file(s), %d rule file(s)",
            server, settings, agents, rules,
        )
    return bool(settings or agents or rules)
