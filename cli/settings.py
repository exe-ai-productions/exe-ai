"""``/settings``: the settings of the three scopes as a selection, a value
set from there or in one line, and the storage locations.

Which settings there are is the service's to say: asked without a list it
answers with all of them, each with the scope it comes from. Nothing of a
list is kept here.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from rich.text import Text

from cli import chat, glyphs, tables
from cli.client import ServiceError
from cli.interfaces import Context, Entry

# The scopes of a selection, by the word that names them in a line.
GLOBAL, MODEL, CHAT = "global", "model", "chat"
_AREAS = (GLOBAL, MODEL, CHAT)

# Where a scope stands in the list of settings: what applies everywhere
# first, then what the model sets over it, then what the chat sets over
# both. A value the service names no scope for stands last.
_SCOPE_ORDER = (("global", 0), ("modell:", 1), ("chat:", 2))
_UNNAMED_SCOPE = 3
# What the list says a value comes from that no scope has set: it is the
# one the service starts out with.
_NO_SCOPE = "default"

# The storage locations a person can move here, with the word each one has
# in the window. The folders of the models stay where they are shown.
_PLACES = {
    "images": "bilder.bildordner",
    "scripts": "speicherorte.skripte_ordner",
    "agent_dock": "docfolder.ordner",
}


def _no_number(name: str) -> Any:
    """Refuses the words a JSON reader takes for numbers that no JSON text
    can carry back out."""
    raise ValueError(name)


def scope_rank(scope: str) -> int:
    """Where a value of that scope stands in the list of settings."""
    for beginning, rank in _SCOPE_ORDER:
        if scope == beginning or scope.startswith(beginning):
            return rank
    return _UNNAMED_SCOPE


def run_command(ctx: Context, argument: str) -> None:
    word = argument.strip()
    if not word:
        _choose_area(ctx)
    else:
        _set_in_a_line(ctx, word)


# --- The selection -------------------------------------------------------------------------------


def _choose_area(ctx: Context) -> None:
    texts = ctx.texts
    rows = [Entry(cells=[("text", area)]) for area in _AREAS]
    rows.append(Entry(cells=[("text", texts.t("cli.storage_title"))]))
    picked = ctx.asker.choose(rows)
    if picked is None:
        return
    if picked < len(_AREAS):
        _choose_setting(ctx, _AREAS[picked])
    else:
        _choose_place(ctx)


def _scope_params(ctx: Context, area: str) -> dict[str, Any]:
    """What the resolving request names for an area: nothing for the
    global one, the model for the model's, the open chat and its model for
    the chat's."""
    session = ctx.session
    params: dict[str, Any] = {}
    if area == CHAT and session.chat is not None:
        params["chat"] = session.chat["id"]
    if area in (MODEL, CHAT) and session.endpoint_id:
        params["modell"] = session.endpoint_id
    return params


def _rows(ctx: Context, area: str) -> list[tuple[str, Any, str]]:
    """Every setting that has a value for the area, as ``(name, value,
    origin)`` in the order of the scopes. A set of values is shown value by
    value, each with the scope the service names for it; anything else is
    one value under the setting's own name. A value no scope has set says
    so in the place of one."""
    resolved = ctx.client.get("/settings/resolved", params=_scope_params(ctx, area))
    resolved = resolved if isinstance(resolved, dict) else {}
    # This chat's scope and this model's are named the way a line takes
    # them: their full names are long enough to leave the values no room,
    # and they say nothing the open chat does not.
    named = {
        f"chat:{(ctx.session.chat or {}).get('id')}": CHAT,
        f"modell:{ctx.session.endpoint_id}": MODEL,
    }
    rows: list[tuple[int, str, Any, str]] = []
    for key, entry in resolved.items():
        if not isinstance(entry, dict):
            continue
        value, origin = entry.get("wert"), entry.get("herkunft")
        origin = origin if isinstance(origin, dict) else {}
        fields = (
            [(f"{key}.{name}", part, str(origin.get(name) or "")) for name, part in value.items()]
            if isinstance(value, dict)
            else [(key, value, str(entry.get("scope") or ""))]
        )
        for name, part, scope in fields:
            if part is None:
                continue
            rows.append((scope_rank(scope), name, part, named.get(scope, scope) or _NO_SCOPE))
    # A stable sort: within a scope the settings keep their own order.
    rows.sort(key=lambda row: row[0])
    return [(name, part, scope) for _, name, part, scope in rows]


def _choose_setting(ctx: Context, area: str) -> None:
    rows = _rows(ctx, area)
    # The value is a remark behind the columns: it wraps, where a column of
    # its width would push the names out.
    entries = [
        Entry(cells=[("accent", name), ("muted", scope)], note=tables.one_line(value))
        for name, value, scope in rows
    ]
    picked = ctx.asker.choose(entries)
    if picked is None:
        return
    name = rows[picked][0]
    written = ctx.asker.ask_text(name)
    if written is None or not written.strip():
        return
    key, _, field = name.partition(".")
    _write(ctx, area, key, field or None, written.strip())


# --- Setting a value --------------------------------------------------------------------------


def _set_in_a_line(ctx: Context, line: str) -> None:
    """``<scope>.<key> <value>`` sets the whole value; a third part names
    one field of a set of values and sets that field alone."""
    pieces = line.split(None, 1)
    target, written = pieces[0], pieces[1].strip() if len(pieces) > 1 else ""
    parts = target.split(".")
    if not written or len(parts) not in (2, 3) or not all(parts):
        ctx.renderer.error(ctx.texts.t("cli.set_form"))
        return
    field = parts[2] if len(parts) == 3 else None
    _write(ctx, parts[0], parts[1], field, written)


def _write(ctx: Context, scope: str, key: str, field: str | None, written: str) -> None:
    """Writes the value into the scope and shows what the scope held before
    against what it holds now, as the service read them back.

    The two scopes nobody can be asked to type out are the chat's and the
    model's; every other word goes to the service as it stands. A value set
    for a new chat is the first thing written into it, and what creates it
    on the service."""
    session = ctx.session
    if scope == CHAT:
        scope = f"chat:{chat.service_chat(ctx)['id']}"
    elif scope in (MODEL, "modell") and session.endpoint_id:
        scope = f"modell:{session.endpoint_id}"
    try:
        value = json.loads(written, parse_constant=_no_number)
    except ValueError:
        # No JSON: a bare word is the word itself.
        value = written
    address = f"/settings/{quote(scope, safe=':')}/{quote(key, safe='')}"
    # What the scope held before, read first: the write replaces it.
    held = ctx.client.get(address)
    before = held.get("wert") if isinstance(held, dict) else None
    if field is None:
        stored = ctx.client.put(address, json={"wert": value})
    else:
        # Only this one field; the rest of the set stays as it is.
        stored = ctx.client.patch(address, json={"wert": {field: value}})
    stored = stored if isinstance(stored, dict) else {}
    after = stored.get("wert")
    name = f"{stored.get('bereich')}.{stored.get('schluessel')}"
    if field is not None:
        before = before.get(field) if isinstance(before, dict) else None
        after = after.get(field) if isinstance(after, dict) else None
        name = f"{name}.{field}"
    ctx.screen.print_above(
        tables.grid(
            [
                (
                    Text(name, style="exe.accent"),
                    Text(tables.one_line(before), style="exe.muted"),
                    Text(glyphs.glyph("arrow"), style="exe.muted"),
                    Text(tables.one_line(after), style="exe.text"),
                )
            ],
            wide=3,
        )
    )


# --- Storage locations ----------------------------------------------------------------------------


def _places(ctx: Context) -> list[dict[str, Any]]:
    found = ctx.client.get("/speicherorte")
    listed = [entry for entry in found if isinstance(entry, dict)] if isinstance(found, list) else []
    return [entry for entry in listed if entry.get("name") in _PLACES]


def _choose_place(ctx: Context) -> None:
    texts = ctx.texts
    places = _places(ctx)
    rows = [
        Entry(cells=[("text", texts.t(_PLACES[str(place["name"])])), ("muted", str(place.get("pfad") or ""))])
        for place in places
    ]
    picked = ctx.asker.choose(rows, head=texts.t("cli.storage_title"))
    if picked is None:
        return
    place = places[picked]
    action = ctx.asker.choose([Entry(cells=[("text", texts.t("speicherorte.aendern"))])])
    if action is None:
        return
    current = str(place.get("pfad") or "")
    typed = ctx.asker.ask_text(texts.t("speicherorte.frage"), default=current)
    # The same folder, or none, changes nothing.
    if typed is None or not typed.strip() or typed.strip() == current:
        return
    try:
        ctx.client.put(f"/speicherorte/{quote(str(place['name']), safe='')}", json={"pfad": typed.strip()})
    except ServiceError as error:
        ctx.renderer.error(error.detail)
        return
    ctx.renderer.notice(texts.t("speicherorte.geaendert"))
