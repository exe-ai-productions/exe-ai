"""``/agents edit``: an agent made, changed field by field the way the mask
of the window asks them, and deleted.

The service owns the agent files and every rule about them. What is written
here is the walk through the fields — the description, the tools as a
checklist, the folders, the limits and the instruction — and the answer it
ends in: only the fields that were changed, and nothing at all where none
was.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any
from urllib.parse import quote

from cli import editor
from cli import folders as shared_folders
from cli.client import ServiceError
from cli.interfaces import Context, Entry

# What the mask takes as the name of an agent.
_NAME = re.compile(r"^[A-Za-z0-9_-]{1,100}$")

# The limits as the mask has them: the field, the label, the lowest and the
# highest value (``None``: no highest) and whether empty — the service's own
# choice — is a value there.
_LIMITS: tuple[tuple[str, str, int, int | None, bool], ...] = (
    ("max_rounds", "agenten.max_runden", 1, 999, False),
    ("max_minutes", "agenten.max_minuten", 1, 1440, False),
    ("max_tokens", "agenten.max_token", 1, 1_000_000, True),
    ("reasoning_budget", "agenten.denklaenge", 0, 1_000_000, True),
    ("max_command_seconds", "agenten.max_befehlssekunden", 1, None, True),
)

# What a new agent starts with, as the mask has it.
_DEFAULT_ROUNDS = 30
_DEFAULT_MINUTES = 20

# Nothing was typed that changes a limit.
_KEEP = object()


def _path(name: str) -> str:
    return quote(name, safe="")


def run_command(ctx: Context, argument: str) -> None:
    """What stands behind ``/agents edit``: the name of an agent, or
    nothing — then the selection opens."""
    name = argument.strip()
    if not name:
        _choose(ctx)
        return
    listed = _files(ctx)
    for entry in listed:
        if entry.get("name") == name:
            broken = entry.get("kaputt")
            if broken:
                ctx.renderer.error(str(broken))
            else:
                _change(ctx, name)
            return
    ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=name))


# --- What the service holds ---------------------------------------------------------------


def _files(ctx: Context) -> list[dict[str, Any]]:
    found = ctx.client.get("/agent-files")
    return [entry for entry in found if isinstance(entry, dict)] if isinstance(found, list) else []


def _agent(ctx: Context, name: str) -> dict[str, Any] | None:
    found = ctx.client.get("/agents")
    for entry in found if isinstance(found, list) else []:
        if isinstance(entry, dict) and entry.get("name") == name:
            return entry
    return None


def _state(agent: dict[str, Any] | None, prompt: str) -> dict[str, Any]:
    """The mask's fields for an agent — for ``None`` the ones a new agent
    starts out with."""
    source = agent or {}
    tools = source.get("tools")
    return {
        "description": str(source.get("description") or ""),
        "tools": [str(name) for name in tools] if isinstance(tools, list) else None,
        "folders": [str(path) for path in source.get("folders") or []],
        "max_rounds": source.get("max_rounds", _DEFAULT_ROUNDS),
        "max_minutes": source.get("max_minutes", _DEFAULT_MINUTES),
        "max_tokens": source.get("max_tokens"),
        "reasoning_budget": source.get("reasoning_budget"),
        "max_command_seconds": source.get("max_command_seconds"),
        "prompt": prompt,
    }


# --- The selection ----------------------------------------------------------------------------


def _choose(ctx: Context) -> None:
    texts = ctx.texts
    listed = _files(ctx)
    entries = [Entry(cells=[("text", texts.t("agenten.neu_kurz"))])]
    for entry in listed:
        broken = str(entry.get("kaputt") or "")
        entries.append(
            Entry(
                cells=[("yellow" if broken else "text", str(entry.get("name") or ""))],
                note=broken,
            )
        )
    picked = ctx.asker.choose(entries)
    if picked is None:
        return
    if picked == 0:
        _new(ctx)
        return
    chosen = listed[picked - 1]
    name = str(chosen.get("name") or "")
    actions: list[tuple[str, str]] = []
    if not chosen.get("kaputt"):
        actions.append(("edit", texts.t("agenten.bearbeiten")))
    actions.append(("delete", texts.t("agenten.loeschen")))
    what = ctx.asker.choose([Entry(cells=[("text", label)]) for _, label in actions], head=name)
    if what is None:
        return
    if actions[what][0] == "edit":
        _change(ctx, name)
    else:
        _delete(ctx, name)


def _delete(ctx: Context, name: str) -> None:
    texts = ctx.texts
    sure = ctx.asker.choose(
        [Entry(cells=[("text", texts.t("app.ja"))]), Entry(cells=[("text", texts.t("app.nein"))])],
        head=texts.t("agenten.loeschen_frage", name=name),
    )
    if sure != 0:
        return
    try:
        ctx.client.delete(f"/agents/{_path(name)}")
    except ServiceError as error:
        ctx.renderer.error(error.detail)
        return
    ctx.renderer.notice(texts.t("agenten.geloescht", name=name))


# --- Making and changing --------------------------------------------------------------------


def _new(ctx: Context) -> None:
    texts = ctx.texts
    typed = ctx.asker.ask_text(texts.t("agenten.name"))
    name = (typed or "").strip()
    if not name:
        return
    if not _NAME.match(name):
        ctx.renderer.error(texts.t("fehler.agent_name_ungueltig"))
        return
    if any(entry.get("name") == name for entry in _files(ctx)):
        # A name that is taken is that agent: its fields are asked as they
        # stand, and nothing of it is written over with the starting values.
        _change(ctx, name)
        return
    state = _state(None, "")
    _walk(ctx, state)
    if not state["prompt"].strip():
        # An agent without an instruction is not saved, as in the mask.
        return
    body = {
        "description": state["description"].strip() or None,
        "tools": state["tools"],
        "folders": state["folders"] or None,
        "max_rounds": state["max_rounds"],
        "max_minutes": state["max_minutes"],
        "max_tokens": state["max_tokens"],
        "reasoning_budget": state["reasoning_budget"],
        "max_command_seconds": state["max_command_seconds"],
        "prompt": state["prompt"].strip(),
    }
    _save(ctx, name, body)


def _change(ctx: Context, name: str) -> None:
    agent = _agent(ctx, name)
    if agent is None:
        ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=name))
        return
    file = ctx.client.get(f"/agents/{_path(name)}")
    file = file if isinstance(file, dict) else {}
    if file.get("kaputt"):
        ctx.renderer.error(str(file["kaputt"]))
        return
    before = _state(agent, str(file.get("prompt") or ""))
    after = {**before, "tools": None if before["tools"] is None else list(before["tools"]),
             "folders": list(before["folders"])}
    _walk(ctx, after)
    body: dict[str, Any] = {}
    if after["description"].strip() != before["description"].strip():
        body["description"] = after["description"].strip() or None
    if _tool_set(after["tools"]) != _tool_set(before["tools"]):
        body["tools"] = after["tools"]
    if after["folders"] != before["folders"]:
        body["folders"] = after["folders"] or None
    for field, *_ in _LIMITS:
        if after[field] != before[field]:
            body[field] = after[field]
    if after["prompt"].strip() != before["prompt"].strip():
        body["prompt"] = after["prompt"].strip()
    if not body:
        return
    _save(ctx, name, body)


def _tool_set(tools: Sequence[str] | None) -> frozenset[str] | None:
    return None if tools is None else frozenset(tools)


def _save(ctx: Context, name: str, body: dict[str, Any]) -> None:
    try:
        ctx.client.put(f"/agents/{_path(name)}/fields", json=body)
    except ServiceError as error:
        ctx.renderer.error(error.detail)
        return
    ctx.renderer.notice(ctx.texts.t("agenten.gesichert", name=name))


# --- The walk through the fields ---------------------------------------------------------------


def _walk(ctx: Context, state: dict[str, Any]) -> None:
    """The fields in the order of the mask. Leaving a question with Esc
    leaves that field as it is."""
    typed = ctx.asker.ask_text(
        ctx.texts.t("agenten.purpose"), default=state["description"] or None
    )
    if typed is not None:
        state["description"] = typed.strip()
    _tools(ctx, state)
    _folders(ctx, state)
    _limits(ctx, state)
    edited = editor.edit(ctx, state["prompt"])
    if edited is not None:
        state["prompt"] = edited


def _tools(ctx: Context, state: dict[str, Any]) -> None:
    """The tools as a checklist, "all approved tools" on top. Ticked is
    what holds: that one where the agent has no list of its own."""
    texts = ctx.texts
    answer = ctx.client.get("/tools")
    offered = answer.get("werkzeuge") if isinstance(answer, dict) else None
    names: list[str] = []
    labels: list[str] = []
    for tool in offered if isinstance(offered, list) else []:
        if not isinstance(tool, dict) or not tool.get("name"):
            continue
        name = str(tool["name"])
        shown = str(tool.get("anzeige") or name)
        server = str(tool.get("server") or "")
        # A tool of a server stands with the server's name in front.
        names.append(name)
        labels.append(f"{server} · {shown}" if tool.get("anzeige") and server else shown)
    current = state["tools"]
    # A tool the agent names that is not offered right now stays on its
    # list, so that confirming the list does not drop it.
    for name in current or []:
        if name not in names:
            names.append(name)
            labels.append(name)
    entries = [Entry(cells=[("text", texts.t("agenten.alle_werkzeuge"))])]
    entries += [Entry(cells=[("text", label)]) for label in labels]
    if current is None:
        ticked = {0}
    else:
        ticked = {number + 1 for number, name in enumerate(names) if name in current}
    result = ctx.asker.check(entries, head=texts.t("werkzeuge.titel"), checked=sorted(ticked))
    if result is None:
        return
    chosen = set(result)
    state["tools"] = None if 0 in chosen else [
        name for number, name in enumerate(names) if number + 1 in chosen
    ]


def _folders(ctx: Context, state: dict[str, Any]) -> None:
    """The folders of the agent: every pick changes the list, and Esc ends
    the step."""
    listed: list[str] = state["folders"]
    while True:
        picked = shared_folders.pick(ctx, listed)
        if picked is None:
            return
        if picked == shared_folders.SHARE:
            path = shared_folders.ask_path(ctx)
            if path and path not in listed:
                listed.append(path)
        elif shared_folders.confirm_release(ctx, listed[picked]):
            del listed[picked]


def _thinking_lock(ctx: Context, state: dict[str, Any]) -> str | None:
    """Why the thinking length cannot be set right now — the sentence of
    the service — or ``None`` where it can, or where nobody can say."""
    needs_tools = state["tools"] is None or bool(state["tools"])
    try:
        answer = ctx.client.get(
            "/jobs/laufmodell", params={"werkzeuge": "true" if needs_tools else "false"}
        )
    except ServiceError:
        return None
    row = answer.get("denklaenge") if isinstance(answer, dict) else None
    if isinstance(row, dict) and row.get("aktiv") is False:
        return str(row.get("grund") or "") or " "
    return None


def _limits(ctx: Context, state: dict[str, Any]) -> None:
    """The five limits: a selection with each value, and a number asked for
    the one that is picked. Esc ends the step."""
    texts = ctx.texts
    auto = texts.t("parameter.auto")
    locked = _thinking_lock(ctx, state)
    while True:
        entries = []
        for field, label, _, _, _ in _LIMITS:
            value = state[field]
            shown = auto if value is None else f"{value:g}" if isinstance(value, float) else str(value)
            entries.append(
                Entry(
                    cells=[("text", texts.t(label)), ("muted", shown)],
                    note=(locked or "").strip() if field == "reasoning_budget" else "",
                )
            )
        picked = ctx.asker.choose(entries, head=texts.t("agenten.grenzen"))
        if picked is None:
            return
        field, label, lowest, highest, auto_allowed = _LIMITS[picked]
        if field == "reasoning_budget" and locked is not None:
            continue
        value = state[field]
        typed = ctx.asker.ask_text(
            texts.t(label), default=None if value is None else f"{value:g}" if isinstance(value, float) else str(value)
        )
        if typed is None:
            continue
        number = _number(typed, lowest, highest, auto_allowed, auto)
        if number is not _KEEP:
            state[field] = number


def _number(typed: str, lowest: int, highest: int | None, auto_allowed: bool, auto: str) -> Any:
    """What a typed word sets a limit to: empty — or the word for the
    service's own choice — where that is a value, otherwise a whole number
    held within the span of the mask."""
    word = typed.strip()
    if not word or word.casefold() == auto.casefold():
        return None if auto_allowed else _KEEP
    try:
        number = int(float(word))
    except ValueError:
        return _KEEP
    number = max(lowest, number)
    return number if highest is None else min(highest, number)
