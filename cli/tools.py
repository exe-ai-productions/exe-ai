"""``/tools``: the tools shown with whether they are on, switched on and
off one by one, and a standing permission taken back.

The service owns the list and the rule that a tool that is switched off is
not offered to the model; the setting that names the switched-off tools
stands in the global scope. What is written here is the selection, the
whole new list sent to the service on a switch, and the line that says what
the tool is now.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from cli import glyphs
from cli.client import ServiceError
from cli.interfaces import Context, Entry

# The setting that holds the names of the tools that are switched off.
OFF_KEY = "werkzeuge_aus"

# The word that takes a standing permission back.
_FORGET = "forget"


def run_command(ctx: Context, argument: str) -> None:
    word, _, rest = argument.strip().partition(" ")
    rest = rest.strip()
    if not word:
        _choose(ctx)
    elif word.casefold() == _FORGET and rest:
        _forget(ctx, rest)
    elif word.isdecimal() and not rest:
        _numbered(ctx, int(word))
    else:
        ctx.renderer.error(ctx.texts.t("cli.werkzeug_syntax"))


# --- What the service holds ----------------------------------------------------------------


def _tools(ctx: Context) -> list[dict[str, Any]]:
    answer = ctx.client.get("/tools")
    listed = answer.get("werkzeuge") if isinstance(answer, dict) else None
    return [tool for tool in listed or [] if isinstance(tool, dict) and tool.get("name")]


def _always(ctx: Context) -> dict[str, Any]:
    answer = ctx.client.get("/permissions/always-allow")
    return answer if isinstance(answer, dict) else {}


def _switched_off(ctx: Context) -> list[str]:
    """The names of the tools that are off, as the service resolves the
    setting for this client."""
    answer = ctx.client.get("/settings/resolved", params={"keys": OFF_KEY})
    entry = answer.get(OFF_KEY) if isinstance(answer, dict) else None
    value = entry.get("wert") if isinstance(entry, dict) else None
    return [str(name) for name in value] if isinstance(value, list) else []


# --- The selection ---------------------------------------------------------------------------------


def _cells(ctx: Context, tool: dict[str, Any], *, always: bool, on: bool) -> list[tuple[str, str]]:
    texts = ctx.texts
    name = str(tool.get("name") or "")
    return [
        ("tool", glyphs.tool_glyph(name)),
        ("tool", name),
        ("muted", str(tool.get("server") or "")),
        ("green", texts.t("werkzeug.yes_dont_ask_again") if always else ""),
        ("blue" if on else "muted", texts.t("status.aktiv" if on else "status.inaktiv")),
    ]


def _line(cells: list[tuple[str, str]]) -> str:
    return "  ".join(text for _, text in cells if text)


def _choose(ctx: Context) -> None:
    texts = ctx.texts
    offered = _tools(ctx)
    if not offered:
        ctx.renderer.notice(texts.t("cli.keine_werkzeuge"))
        return
    ctx.session.shown_tools = [str(tool["name"]) for tool in offered]
    always = _always(ctx)
    off = set(_switched_off(ctx))
    entries = [
        Entry(cells=_cells(ctx, tool, always=tool["name"] in always, on=tool["name"] not in off))
        for tool in offered
    ]
    active = sum(1 for tool in offered if tool["name"] not in off)
    picked = ctx.asker.choose(
        entries, head=texts.t("cli.tools_count", active=active, total=len(offered))
    )
    if picked is None:
        return
    _switch(ctx, offered[picked], offered_with=always)


def _numbered(ctx: Context, number: int) -> None:
    """A number counts into the list as it was last shown."""
    shown = ctx.session.shown_tools
    offered = _tools(ctx)
    names = shown if shown is not None else [str(tool["name"]) for tool in offered]
    if not 1 <= number <= len(names):
        ctx.renderer.error(ctx.texts.t("cli.werkzeug_syntax"))
        return
    found = next((tool for tool in offered if tool["name"] == names[number - 1]), None)
    if found is None:
        # A tool of the list that is not offered any more.
        ctx.renderer.error(ctx.texts.t("cli.werkzeug_syntax"))
        return
    _switch(ctx, found, offered_with=_always(ctx))


def _switch(ctx: Context, tool: dict[str, Any], *, offered_with: dict[str, Any]) -> None:
    """Switches one tool: the whole new list of the switched-off tools goes
    to the service, an empty one as nothing. The line of the tool as it is
    now stands in the notice line."""
    name = str(tool["name"])
    off = _switched_off(ctx)
    now_on = name in off
    changed = [kept for kept in off if kept != name] if now_on else [*off, name]
    try:
        ctx.client.put(f"/settings/global/{OFF_KEY}", json={"wert": changed or None})
    except ServiceError as error:
        ctx.renderer.error(error.detail)
        return
    ctx.renderer.notice(_line(_cells(ctx, tool, always=name in offered_with, on=now_on)))


def _forget(ctx: Context, name: str) -> None:
    ctx.client.delete(f"/permissions/always-allow/{quote(name, safe='')}")
    ctx.renderer.notice(ctx.texts.t("cli.tool_asks_again", name=name))
