"""``/mcp``: the MCP servers shown with whether they answer, a new one
entered the way the mask of the window enters it, the switches of one
entry, the sign-in through the browser, and an entry removed.

The service owns the entries, the probe of an address and the sign-in. What
is written here is the walk through the fields, the waiting for the server
to answer, and the lines that say how the entry stands now. A key or a
secret typed here stands in no line: what the service says against it is
shown without it.
"""

from __future__ import annotations

import math
import re
import webbrowser
from typing import Any
from urllib.parse import urlparse

from cli import servers
from cli.client import ServiceError
from cli.interfaces import Context, Entry

# The ways one tool of a server is switched: active, asking first, inactive —
# and active again. The words the row shows are the catalogue's, the ones
# the tool detail of Exe AI reads.
ON, ASKS, OFF = "an", "fragt", "aus"
_NEXT = {ON: ASKS, ASKS: OFF, OFF: ON}
_STATE_KEY = {ON: "status.aktiv", ASKS: "werkzeuge.fragt", OFF: "status.inaktiv"}

# How often the server is asked whether it runs: after it was entered, and
# while the user signs in at the browser — a person's own pace.
_POLLS_ENTERED = 8
_POLLS_SIGN_IN = 90
# The pause before the first asking, and between the later ones, in seconds.
_FIRST_WAIT = 0.5
_NEXT_WAIT = 1.5

# The longest an id made from a name is.
_ID_LENGTH = 30


def run_command(ctx: Context, argument: str) -> None:
    word = argument.strip()
    if not word:
        _choose(ctx)
    elif word.isdecimal():
        _numbered(ctx, int(word), word)
    else:
        ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=word))


# --- Names as the mask makes them ---------------------------------------------------------


def server_id(name: str) -> str:
    """A name as the id of an entry: lower case, every run of characters
    outside letters and digits one hyphen, none at the edges, at most
    thirty characters."""
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")[:_ID_LENGTH]


def key_variable(identifier: str) -> str:
    """The name of the variable that holds the key of the entry. The service
    refuses a name that starts with a digit, so an id made of an address
    gets an underscore in front."""
    name = f"{identifier.upper().replace('-', '_')}_API_KEY"
    return f"_{name}" if name[0].isdigit() else name


def _host_id(url: str) -> str:
    try:
        host = urlparse(url).hostname
    except ValueError:
        host = None
    return server_id(host or url)


def time_limit(typed: str) -> float | None:
    """The seconds a field holds: a number above zero, else ``None``."""
    try:
        seconds = float(typed.strip())
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds > 0 else None


def state_of(tool: str, entry: dict[str, Any]) -> str:
    """The state of a tool read from the entry. Being left out of the
    offered tools is checked first: such a tool is off whatever the list of
    those that ask says."""
    offered = entry.get("allowed_tools")
    if offered is not None and tool not in offered:
        return OFF
    return ASKS if tool in (entry.get("needs_confirmation") or []) else ON


def lists_of(states: dict[str, str]) -> dict[str, list[str]]:
    """The two lists the service reads, from the states the tools stand
    in: a tool that asks first stands in both."""
    allowed = [name for name, state in states.items() if state != OFF]
    return {
        "allowed_tools": allowed,
        "needs_confirmation": [name for name in allowed if states[name] == ASKS],
    }


# --- What the service holds ------------------------------------------------------------------


def _entries(ctx: Context) -> list[dict[str, Any]]:
    found = ctx.client.get("/tools/servers")
    return [entry for entry in found if isinstance(entry, dict)] if isinstance(found, list) else []


def _entry(ctx: Context, name: str) -> dict[str, Any] | None:
    return next((entry for entry in _entries(ctx) if entry.get("name") == name), None)


def _cells(ctx: Context, entry: dict[str, Any]) -> list[tuple[str, str]]:
    texts = ctx.texts
    running = bool(entry.get("laeuft"))
    return [
        ("text", str(entry.get("name") or "")),
        ("green" if running else "muted", texts.t("verbindungen.stand_verbunden" if running else "verbindungen.stand_getrennt")),
        ("muted", texts.t("mcp.tools_zahl", n=len(entry.get("alle_werkzeuge") or [])) if running else ""),
    ]


def _line(ctx: Context, entry: dict[str, Any]) -> str:
    return "  ".join(text for _, text in _cells(ctx, entry) if text)


def _say(ctx: Context, name: str) -> None:
    """The line of the entry as it stands now."""
    entry = _entry(ctx, name)
    if entry is not None:
        ctx.renderer.notice(_line(ctx, entry))


def _scrubbed(error: ServiceError, secrets: list[str]) -> str:
    """What the service said, without the key or the secret that was sent
    with it."""
    detail = error.detail
    for secret in secrets:
        if secret:
            detail = detail.replace(secret, "…")
    return detail


# --- The selection -----------------------------------------------------------------------------


def _choose(ctx: Context) -> None:
    entries = _entries(ctx)
    ctx.session.shown_mcp = entries
    rows = [Entry(cells=[("text", ctx.texts.t("verbindungen.hinzufuegen"))])]
    rows += [Entry(cells=_cells(ctx, entry)) for entry in entries]
    picked = ctx.asker.choose(rows)
    if picked is None:
        return
    if picked == 0:
        _add(ctx)
    else:
        _menu(ctx, entries[picked - 1])


def _numbered(ctx: Context, number: int, word: str) -> None:
    """A number counts into the selection as it was last shown; the entry
    to add is 1."""
    entries = ctx.session.shown_mcp
    if entries is None:
        entries = ctx.session.shown_mcp = _entries(ctx)
    if number == 1:
        _add(ctx)
    elif 2 <= number <= len(entries) + 1:
        _menu(ctx, entries[number - 2])
    else:
        ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=word))


def _menu(ctx: Context, entry: dict[str, Any]) -> None:
    texts = ctx.texts
    actions = [("edit", texts.t("skills.bearbeiten"))]
    # The sign-in is for a hosted server without a fixed key, as the service
    # takes it.
    if entry.get("type") == "http" and not entry.get("api_key_env"):
        actions.append(("sign_in", texts.t("mcp.im_browser_anmelden")))
    actions.append(("remove", texts.t("verbindungen.entfernen")))
    picked = ctx.asker.choose(
        [Entry(cells=[("text", label)]) for _, label in actions], head=_line(ctx, entry)
    )
    if picked is None:
        return
    what = actions[picked][0]
    name = str(entry.get("name"))
    if what == "edit":
        _edit(ctx, name)
    elif what == "sign_in":
        _sign_in(ctx, name)
    else:
        _remove(ctx, name)


# --- Adding ----------------------------------------------------------------------------------------


def _add(ctx: Context) -> None:
    texts = ctx.texts
    typed = ctx.asker.ask_text(texts.t("mcp.url"))
    url = (typed or "").strip()
    if not url:
        return
    try:
        probe = ctx.client.post("/tools/mcp/sondieren", json={"url": url})
    except ServiceError as error:
        ctx.renderer.error(error.detail)
        return
    wanted = probe.get("verlangt") if isinstance(probe, dict) else None
    if wanted is None:
        name = server_id(str(probe.get("name") or url)) if isinstance(probe, dict) else server_id(url)
        if not name:
            ctx.renderer.error(texts.t("mcp.name_ungueltig"))
            return
        _write_and_connect(ctx, name, {"type": "http", "url": url})
        return
    name = _host_id(url)
    if not name:
        ctx.renderer.error(texts.t("mcp.name_ungueltig"))
        return
    if wanted == "schluessel":
        key = (ctx.asker.ask_text(texts.t("mcp.api_key"), secret=True) or "").strip()
        if not key:
            return
        fields = {"type": "http", "url": url, "api_key_env": key_variable(name), "api_key": key}
        _write_and_connect(ctx, name, fields, secrets=[key])
    else:
        _enter_and_sign_in(ctx, name, url, with_client_id=wanted == "oauth_kennung")


def _write(
    ctx: Context, name: str, fields: dict[str, Any], *, new: bool, secrets: list[str] | None = None
) -> bool:
    try:
        ctx.client.put(f"/tools/servers/{name}{'?neu=true' if new else ''}", json=fields)
    except ServiceError as error:
        ctx.renderer.error(_scrubbed(error, secrets or []))
        return False
    return True


def _write_and_connect(
    ctx: Context, name: str, fields: dict[str, Any], *, secrets: list[str] | None = None
) -> None:
    """Enters a new server, waits for it to answer, and asks the time limit
    of its calls once it does."""
    if not _write(ctx, name, fields, new=True, secrets=secrets):
        return
    _connected(ctx, name, _POLLS_ENTERED)


def _connected(ctx: Context, name: str, polls: int) -> None:
    """Waits for the server to run. Where it does, asks the time limit and
    says its line; where it never does, says so — the entry stays."""
    answered, interrupted = _wait_for(ctx, name, polls)
    if interrupted:
        return
    if answered is None:
        ctx.renderer.error(ctx.texts.t("mcp.nicht_erreichbar"))
        return
    typed = ctx.asker.ask_text(ctx.texts.t("mcp.zeitgrenze"))
    seconds = time_limit(typed or "")
    if seconds is not None:
        try:
            ctx.client.put(f"/tools/servers/{name}", json={"timeout": seconds})
        except ServiceError as error:
            ctx.renderer.error(error.detail)
            return
    _say(ctx, name)


def _wait_for(ctx: Context, name: str, polls: int) -> tuple[dict[str, Any] | None, bool]:
    """Asks until the entry runs or the asking is used up; the interrupt
    key ends it. Returns the entry that runs — or ``None`` — and whether the
    wait was ended by the interrupt key."""
    with servers.waiting(ctx) as cancel:
        for attempt in range(polls):
            if cancel.wait(_FIRST_WAIT if attempt == 0 else _NEXT_WAIT):
                return None, True
            entry = _entry(ctx, name)
            if entry is not None and entry.get("laeuft"):
                return entry, False
    return None, False


def _enter_and_sign_in(ctx: Context, name: str, url: str, *, with_client_id: bool) -> None:
    texts = ctx.texts
    client_id = secret = ""
    if with_client_id:
        client_id = (ctx.asker.ask_text(texts.t("verbindungen.kennung")) or "").strip()
        secret = (ctx.asker.ask_text(texts.t("verbindungen.geheimnis"), secret=True) or "").strip()
        if not client_id:
            return
    if not _write(ctx, name, {"type": "http", "url": url, "enabled": True}, new=True):
        return
    _start_sign_in(ctx, name, client_id=client_id, secret=secret)


def _start_sign_in(ctx: Context, name: str, *, client_id: str = "", secret: str = "") -> None:
    body: dict[str, Any] = {"server": name}
    if client_id:
        body["client_id"] = client_id
        if secret:
            body["client_secret"] = secret
    try:
        started = ctx.client.post("/tools/oauth/start", json=body)
    except ServiceError as error:
        ctx.renderer.error(_scrubbed(error, [secret]))
        return
    address = started.get("url") if isinstance(started, dict) else None
    if isinstance(address, str) and address:
        webbrowser.open(address)
    _connected(ctx, name, _POLLS_SIGN_IN)


def _sign_in(ctx: Context, name: str) -> None:
    _start_sign_in(ctx, name)


# --- Editing ---------------------------------------------------------------------------------------


def _edit(ctx: Context, name: str) -> None:
    """The switches the window has in the menu of a server: whether it is
    active, and for each tool of a server that answers whether it is on,
    asks first, or is off. Esc ends it."""
    texts = ctx.texts
    while True:
        entry = _entry(ctx, name)
        if entry is None:
            return
        enabled = bool(entry.get("enabled"))
        tools = [str(tool.get("name")) for tool in entry.get("alle_werkzeuge") or [] if isinstance(tool, dict)]
        rows = [
            Entry(
                cells=[
                    ("text", texts.t("verbindungen.aktiv")),
                    ("blue" if enabled else "muted", texts.t("status.aktiv" if enabled else "status.inaktiv")),
                ]
            )
        ]
        states = {tool: state_of(tool, entry) for tool in tools}
        rows += [Entry(cells=[("text", tool), ("muted", texts.t(_STATE_KEY[states[tool]]))]) for tool in tools]
        picked = ctx.asker.choose(rows, head=_line(ctx, entry))
        if picked is None:
            return
        if picked == 0:
            fields: dict[str, Any] = {"enabled": not enabled}
        else:
            tool = tools[picked - 1]
            states[tool] = _NEXT[states[tool]]
            fields = lists_of(states)
        try:
            ctx.client.put(f"/tools/servers/{name}", json=fields)
        except ServiceError as error:
            ctx.renderer.error(error.detail)
            return
        _say(ctx, name)


# --- Removing -------------------------------------------------------------------------------------


def _remove(ctx: Context, name: str) -> None:
    if not servers.ask(ctx, ctx.texts.t("verbindungen.entfernen_frage", name=name)):
        return
    try:
        ctx.client.delete(f"/tools/servers/{name}")
    except ServiceError as error:
        ctx.renderer.error(error.detail)
