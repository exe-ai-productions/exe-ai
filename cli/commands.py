"""The commands the user types after a slash.

A line that starts with a slash is a command and never goes to the model.
Each command is registered once, with its name, the key of the one line
that describes it, and the function that runs it.

A command shows what the service answers and changes what the service
keeps. Where the service refuses, its own sentence is shown — raising it is
enough, the screen writes it into the history.

A command that sets one of several — the chat, the model, the theme, the
language, the thinking stage — takes it as the word behind its name.
Without a word it opens a selection above the input field and goes on with
the entry picked there, as if that had been the word. Neither way writes
the list into the history.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from rich.console import RenderableType
from rich.table import Table
from rich.text import Text

from cli import chat, downloads, glyphs, prefs, servers, themes
from cli.client import ServiceError
from cli.interfaces import CommandSet, Context, Entry
from cli.render import local_time
from cli.texts import Texts, available_languages

# The setting the service keeps a chat's or a model's thinking stage in.
_THINKING_KEY = "denken"

# Where a scope stands in the list of settings: what applies everywhere
# first, then what the model sets over it, then what the chat sets over
# both. A value the service names no scope for stands last.
_SCOPE_ORDER = (("global", 0), ("modell:", 1), ("chat:", 2))
_UNNAMED_SCOPE = 3
# What the list says a value comes from that no scope has set: it is the
# one the service starts out with.
_NO_SCOPE = "default"

# The ending that makes an export a Markdown transcript; any other ending
# is the history as it was shown, as an HTML page.
_MARKDOWN = ".md"

# The setting the window keeps the model it last chose in; the client reads
# it at start and writes it when a model is chosen, so both show the same.
LAST_MODEL_KEY = "modell_zuletzt"

# Where ``/export`` writes without a name: a folder beside the client's own
# file of remembered choices, and a file named by the moment.
SAVED_FOLDER = "saved"
SAVED_PREFIX = "exe_conversation_"
_SAVED_STAMP = "%Y%m%d_%H%M%S"

# How many messages of a chat are read at once for a transcript.
_PAGE = 500

# The commands of the chat that make no sense without an answer to act on.
_NOT_OUTSIDE = ("stop",)

# The two kinds of thinking nothing can switch, and the sentence for each.
_FIXED_THINKING = {"immer": "denken.immer", "nie": "denken.nie"}

# The word after `/tools` that takes a standing permission back, and the two
# after `/theme nerd` that switch the icon font's signs.
_FORGET = "forget"
_NERD = "nerd"
_SWITCH = {"on": True, "off": False}
# The same two as they are typed in the client's other language.
_SWITCH_TYPED = {**_SWITCH, "an": True, "aus": False}


@dataclass(frozen=True)
class Command:
    # The word after the slash.
    name: str
    # The catalogue key of its one-line description.
    summary_key: str
    # Takes the context and whatever followed the name on the line.
    handler: Callable[[Context, str], None]


def _table(commands: Commands) -> tuple[Command, ...]:
    """Every command of the chat, in the order ``/help`` lists them."""
    return (
        Command("new", "chat.neu", commands.new_chat),
        Command("chats", "cli.cmd_chats", commands.chats),
        Command("model", "cli.cmd_model", commands.model),
        Command("server", "cli.cmd_server", commands.server),
        Command("download", "cli.cmd_download", commands.download),
        Command("status", "cli.cmd_status", commands.status),
        Command("theme", "cli.cmd_theme", commands.theme),
        Command("lang", "cli.cmd_lang", commands.language),
        Command("settings", "cli.cmd_settings", commands.settings),
        Command("set", "cli.cmd_set", commands.set_setting),
        Command("tools", "cli.cmd_tools", commands.tools),
        Command("think", "cli.cmd_think", commands.think),
        Command("export", "cli.cmd_export", commands.export),
        Command("stop", "eingabe.abbrechen", _stop),
        Command("clear", "cli.cmd_clear", _clear),
        Command("help", "cli.cmd_help", commands.show_help),
        Command("quit", "shortcuts.quit", _quit),
        Command("exit", "shortcuts.quit", _quit),
    )


def build_commands(ctx: Context) -> CommandSet:
    commands = Commands(ctx)
    for command in _table(commands):
        commands.register(command)
    return commands


def outside_entries(texts: Texts) -> list[tuple[str, str]]:
    """The commands that also go from outside the chat, each with the first
    line of its sentence: every command of the chat but ``stop``, which
    stops an answer, and from outside none runs."""
    probe = Commands(Context(client=None, texts=texts))  # type: ignore[arg-type]
    return [
        (command.name, texts.t(command.summary_key).split("\n", 1)[0])
        for command in _table(probe)
        if command.name not in _NOT_OUTSIDE
    ]


def _quit(ctx: Context, argument: str) -> None:
    ctx.screen.exit()


def _clear(ctx: Context, argument: str) -> None:
    ctx.screen.clear()


def _stop(ctx: Context, argument: str) -> None:
    # Without a running answer there is nothing to stop, and nothing to say.
    if ctx.session.answering:
        chat.stop(ctx)


# --- Shapes shared by the lists ---------------------------------------------------


def _grid(rows: Iterable[Iterable[RenderableType]], *, wide: int | None = None) -> Table:
    """Rows in columns, every column as wide as its widest cell.

    ``wide`` names the one column that gives way where the window is too
    narrow for all of them: its cells are carried on below, in their own
    column, so nothing of them is lost and the columns beside it keep their
    width. Without one, a row that does not fit is cut.
    """
    table = Table.grid(padding=(0, 2))
    for row in rows:
        cells = list(row)
        while len(table.columns) < len(cells):
            if len(table.columns) == wide:
                table.add_column(overflow="fold")
            else:
                table.add_column(no_wrap=True, overflow=glyphs.overflow())
        table.add_row(*cells)
    return table


def _one_line(value: Any) -> str:
    """A value as it stands in one cell. A word stands as itself; an empty
    one is written out, so its cell does not look like a missing value."""
    if isinstance(value, str) and value.strip():
        return " ".join(value.split())
    return json.dumps(value, ensure_ascii=False)


def _saved_page(ctx: Context) -> Path:
    """The file ``/export`` writes without a name: in the client's own
    folder, named by the moment — and never one that is already there, so
    two exports in one second are two files."""
    folder = (ctx.prefs_path or prefs.default_path()).parent / SAVED_FOLDER
    stem = SAVED_PREFIX + datetime.now().strftime(_SAVED_STAMP)
    path = folder / f"{stem}.html"
    number = 2
    while path.exists():
        path = folder / f"{stem}-{number}.html"
        number += 1
    return path


def _first_word(text: str) -> tuple[str, str]:
    """The first word of ``text`` and what follows it, whatever kind of
    blank stands between the two — a line break is one as well."""
    parts = text.split(None, 1)
    return (parts[0] if parts else "", parts[1].strip() if len(parts) > 1 else "")


def _no_number(name: str) -> Any:
    """Refuses the words a JSON reader takes for numbers that no JSON text
    can carry back out."""
    raise ValueError(name)


def _numbered(wanted: str, listed: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The entry ``wanted`` counts to, or ``None`` where it is no number of
    the list."""
    if wanted.isdecimal() and 1 <= int(wanted) <= len(listed):
        return listed[int(wanted) - 1]
    return None


def _scope_rank(scope: str) -> int:
    """Where a value of that scope stands in the list of settings."""
    for beginning, rank in _SCOPE_ORDER:
        if scope == beginning or scope.startswith(beginning):
            return rank
    return _UNNAMED_SCOPE


class SlashCompleter(Completer):
    """Offers the commands while the first word of the input is being typed
    and starts with a slash."""

    def __init__(self, commands: Commands) -> None:
        self._commands = commands

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterator[Completion]:
        typed = document.text_before_cursor
        if not typed.startswith("/") or any(character.isspace() for character in typed):
            return
        for command in self._commands.matching(typed[1:]):
            # A row of the menu is one line: a summary that runs on to a
            # second line shows its first here and all of it under /help.
            yield Completion(
                f"/{command.name}",
                start_position=-len(typed),
                display_meta=self._commands.summary(command).split("\n", 1)[0],
            )


class Commands(CommandSet):
    """The register: finds the command a line names and runs it."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx
        self._commands: dict[str, Command] = {}
        self._completer = SlashCompleter(self)
        # The models as they were last shown. A number the user types
        # counts into what stood on the screen, not into what the service
        # would list now. The chats last shown are kept with the session:
        # the head shows them with numbers as well.
        self._shown_models: list[dict[str, Any]] | None = None
        # Whether the icon font's signs were switched in this run, and to
        # what; ``None`` while they stand as the start left them.
        self._nerd_signs: bool | None = None

    def register(self, command: Command) -> None:
        self._commands[command.name] = command

    def names(self) -> list[str]:
        return list(self._commands)

    def matching(self, beginning: str) -> list[Command]:
        """The commands whose name starts with ``beginning``."""
        wanted = beginning.lower()
        return [
            command for name, command in self._commands.items() if name.startswith(wanted)
        ]

    def summary(self, command: Command) -> str:
        return self._ctx.texts.t(command.summary_key)

    def completer(self) -> Completer:
        return self._completer

    def run(self, line: str) -> None:
        name, argument = _first_word(line.strip()[1:])
        command = self._commands.get(name.lower())
        if command is None:
            self._ctx.renderer.error(self._ctx.texts.t("cli.unbekannt", name=name))
            return
        command.handler(self._ctx, argument)

    # --- /help ---

    def show_help(self, ctx: Context, argument: str) -> None:
        """Every command with its one line."""
        ctx.screen.print_above(
            _grid(
                (
                    (
                        Text(f"/{command.name}", style="exe.accent"),
                        Text(self.summary(command), style="exe.text"),
                    )
                    for command in self._commands.values()
                ),
                wide=1,
            )
        )

    # --- /new, /chats ---

    def new_chat(self, ctx: Context, argument: str) -> None:
        session = ctx.session
        if not session.answering:
            chat.new_chat(ctx)
            # A stage belongs to the chat it was set in.
            session.thinking = None
            ctx.renderer.notice(ctx.texts.t("cli.chat_neu"))
            return
        # An answer is still being written into the open chat. The new one
        # is opened behind that answer, in its turn among the lines already
        # waiting — named, until then, the way the service names a fresh
        # chat.
        ctx.renderer.notice(ctx.texts.t("cli.chat_waits", name=chat.fresh_title(ctx)))
        ctx.screen.new_chat()

    def chats(self, ctx: Context, argument: str) -> None:
        if argument:
            found = self._named_chat(argument)
        else:
            found = self._picked_chat()
        if found is None:
            # Nothing was picked; or nothing, or more than one chat, answers
            # to that name, and which of the two has just been said.
            return
        if ctx.session.answering:
            self._open_behind_answer(found)
            return
        # A stage belongs to the chat it was set in.
        ctx.session.thinking = None
        ctx.renderer.notice(ctx.texts.t("cli.chat_gewechselt", name=found.get("title")))
        ctx.screen.open_chat(found)

    def _named_chat(self, argument: str) -> dict[str, Any] | None:
        """The chat the word behind the command names. A number counts into
        the list as it was last shown; anything else, and a number the list
        does not reach, is an id or a title."""
        ctx = self._ctx
        if argument.isdecimal():
            if ctx.session.shown_chats is None:
                ctx.session.shown_chats = self._chats()
            shown = _numbered(argument, ctx.session.shown_chats)
            found = None if shown is None else self._as_it_is_now(shown)
            if found:
                return found
        return chat.find_chat(ctx, argument)

    def _picked_chat(self) -> dict[str, Any] | None:
        """The chat picked from the selection: the chats in the order the
        service lists them, the newest first, under the numbers the head
        gives them. Where there is no chat, there is nothing to pick."""
        ctx = self._ctx
        listed = self._chats()
        # The numbers a word behind the command counts into from here on.
        ctx.session.shown_chats = listed
        if not listed:
            return None
        open_id = ctx.session.chat_id()
        picked = ctx.asker.choose(
            [
                Entry(
                    cells=[
                        ("text", " ".join(str(entry.get("title") or "").split())),
                        ("muted", local_time(entry.get("updated_at"))),
                        ("blue", ctx.texts.t("cli.laeuft") if entry.get("laeuft") else ""),
                    ],
                    in_use=entry.get("id") == open_id,
                )
                for entry in listed
            ]
        )
        return None if picked is None else self._as_it_is_now(listed[picked])

    def _as_it_is_now(self, shown: dict[str, Any]) -> dict[str, Any] | None:
        """An entry is as old as the list it stood in. The chat is read
        anew and opened as the service has it now, with the name and the
        model it was given since."""
        found = chat.read_chat(self._ctx, str(shown.get("id")))
        return found if isinstance(found, dict) else None

    def _chats(self) -> list[dict[str, Any]]:
        listed = self._ctx.client.get("/chats")
        return listed if isinstance(listed, list) else []

    def _open_behind_answer(self, wanted: dict[str, Any]) -> None:
        """Hands the switch to the screen, which makes it once the running
        answer is over. The thinking stage stays as it is until then: the
        lines still waiting for the chat before were typed under it."""
        ctx = self._ctx
        ctx.renderer.notice(ctx.texts.t("cli.chat_waits", name=wanted.get("title")))
        ctx.screen.open_chat(wanted)

    # --- /model ---

    def model(self, ctx: Context, argument: str) -> None:
        if not argument:
            found = self._picked_model()
        else:
            if self._shown_models is None:
                self._shown_models = self._listing()
            listed = self._shown_models
            found = _numbered(argument, listed)
            if found is None:
                named = [
                    model
                    for model in listed
                    if argument.casefold()
                    in (str(model.get("name") or "").casefold(), str(model.get("id") or "").casefold())
                ]
                if len(named) > 1:
                    # Several answer to the name; which of them is meant
                    # is picked from the selection.
                    found = self._picked_model()
                elif named:
                    found = named[0]
                else:
                    ctx.renderer.error(ctx.texts.t("cli.modell_unbekannt", name=argument))
        if found is not None and found.get("datei"):
            # A file of the model folder: the model server is brought up
            # with it, and the choice is the model it connects as. Where
            # nothing came of it, the choice stays as it was.
            found = servers.start_with(ctx, str(found["datei"]))
        if found is None:
            return
        session = ctx.session
        if session.chat is not None:
            # Kept with the chat, so the window opens it with the same model.
            # Before anything changes here: a refusal leaves all as it was.
            session.chat = ctx.client.patch(
                f"/chats/{session.chat['id']}", json={"endpoint_id": found.get("id")}
            )
        # Remembered the way the window remembers its choice, so the next
        # start of either shows the same model — the name with the id: the
        # service names a model only while its server answers. A memo only:
        # a refusal is not worth stopping the switch over, and the window
        # ignores it too.
        choice = {"id": found.get("id")}
        if found.get("name"):
            choice["name"] = found.get("name")
        try:
            ctx.client.put(f"/settings/global/{LAST_MODEL_KEY}", json={"wert": choice})
        except ServiceError:
            pass
        session.endpoint_id = found.get("id")
        # A stage of the model before may be none of this one's.
        session.thinking = None
        ctx.screen.update_status(
            model_name=found.get("name"), context_window=found.get("context_tokens")
        )
        ctx.renderer.notice(ctx.texts.t("cli.modell_gewaehlt", name=found.get("name")))

    # --- /server, /status ---

    def server(self, ctx: Context, argument: str) -> None:
        servers.run_command(ctx, argument)

    def download(self, ctx: Context, argument: str) -> None:
        downloads.run_command(ctx, argument)

    def status(self, ctx: Context, argument: str) -> None:
        """What runs and how full the memory is, written into the history:
        nothing to pick from, nothing changed."""
        head, rows = servers.overview(ctx)
        ctx.screen.print_above(
            Text(head, style="exe.muted"),
            _grid(
                [Text(text, style=f"{themes.RICH_PREFIX}{style}") for style, text in row]
                for row in rows
            ),
        )

    def _models(self) -> list[dict[str, Any]]:
        listed = self._ctx.client.get("/models")
        models: list[dict[str, Any]] = listed if isinstance(listed, list) else []
        self._ctx.session.models = models
        return models

    def _listing(self) -> list[dict[str, Any]]:
        """What /model offers: the models the service lists, then the files
        of the model folder the model server does not carry — a file is
        marked by ``datei``, which no model of the service has."""
        return [*self._models(), *servers.not_carried(self._ctx)]

    def _picked_model(self) -> dict[str, Any] | None:
        """The model picked from the selection: the models as the service
        lists them now, under the numbers a word behind the command counts
        into from here on. Where it lists none, that is said instead."""
        ctx = self._ctx
        self._shown_models = self._listing()
        listed = self._shown_models
        if not listed:
            ctx.renderer.notice(ctx.texts.t("cli.keine_modelle"))
            return None
        entries = []
        for model in listed:
            if model.get("datei"):
                entries.append(self._file_entry(model))
                continue
            reachable = bool(model.get("erreichbar"))
            window = model.get("context_tokens")
            entries.append(
                Entry(
                    cells=[
                        ("text", str(model.get("name") or "")),
                        ("muted", str(model.get("anbieter_name") or "")),
                        (
                            "green" if reachable else "red",
                            ctx.texts.t("status.erreichbar" if reachable else "status.nicht_erreichbar"),
                        ),
                        ("muted", "" if window is None else str(window)),
                    ],
                    in_use=model.get("id") == ctx.session.endpoint_id,
                )
            )
        picked = ctx.asker.choose(entries)
        return None if picked is None else listed[picked]

    def _file_entry(self, model: dict[str, Any]) -> Entry:
        """A file of the model folder as a row of the selection: where it
        would run, that it is not running, and how large it is."""
        texts = self._ctx.texts
        return Entry(
            cells=[
                ("text", str(model.get("name") or "")),
                ("muted", texts.t("modell.server")),
                ("muted", texts.t("status.inaktiv")),
                ("muted", servers.size_text(texts, model.get("groesse_gb"))),
            ]
        )

    # --- /think ---

    def think(self, ctx: Context, argument: str) -> None:
        texts = ctx.texts
        profile = (ctx.session.model() or {}).get("denkprofil")
        profile = profile if isinstance(profile, dict) else {}
        fixed = _FIXED_THINKING.get(str(profile.get("art") or ""))
        stages = [str(stage) for stage in profile.get("stufen") or []]
        if fixed is not None or not stages:
            # Nothing to set: the model thinks always, or never. A model
            # that is not in the list says nothing about itself and counts
            # as one that never does.
            ctx.renderer.notice(texts.t(fixed or _FIXED_THINKING["nie"]))
            return
        if argument:
            wanted = argument.casefold()
            named = [
                stage
                for stage in stages
                if wanted in (stage.casefold(), texts.t(f"denken.stufe.{stage}").casefold())
            ]
            if named:
                ctx.session.thinking = named[0]
            else:
                ctx.renderer.error(texts.t("cli.unknown_choice", name=argument))
            return
        in_force = ctx.session.thinking or self._stored_stage() or profile.get("standard")
        picked = ctx.asker.choose(
            [
                Entry(
                    cells=[("text", stage), ("muted", texts.t(f"denken.stufe.{stage}"))],
                    in_use=stage == in_force,
                )
                for stage in stages
            ]
        )
        if picked is not None:
            ctx.session.thinking = stages[picked]

    def _stored_stage(self) -> Any:
        """The stage the service keeps for this chat and this model — what a
        message is answered with while none is set here."""
        resolved = self._ctx.client.get(
            f"/settings/resolved/{_THINKING_KEY}", params=self._scope_of_chat()
        )
        value = resolved.get("wert") if isinstance(resolved, dict) else None
        return value.get("stufe") if isinstance(value, dict) else None

    # --- /settings, /set ---

    def _scope_of_chat(self) -> dict[str, Any]:
        """What a resolving request names: the open chat and its model."""
        session = self._ctx.session
        scope: dict[str, Any] = {}
        if session.chat is not None:
            scope["chat"] = session.chat["id"]
        if session.endpoint_id:
            scope["modell"] = session.endpoint_id
        return scope

    def settings(self, ctx: Context, argument: str) -> None:
        """Every setting that has a value, with the scope it comes from —
        in the order of the scopes: what applies everywhere, then what the
        model sets over it, then what the chat sets over both. Which
        settings there are is the service's to say: asked without a list,
        it answers with all of them."""
        resolved = ctx.client.get("/settings/resolved", params=self._scope_of_chat())
        resolved = resolved if isinstance(resolved, dict) else {}
        # This chat's scope and this model's are named the way /set
        # takes them: their full names are long enough to leave the
        # values no room, and they say nothing the open chat does not.
        named = {
            f"chat:{(ctx.session.chat or {}).get('id')}": "chat",
            f"modell:{ctx.session.endpoint_id}": "model",
        }
        rows: list[tuple[int, str, Any, str]] = []
        for key, entry in resolved.items():
            if not isinstance(entry, dict):
                continue
            value, origin = entry.get("wert"), entry.get("herkunft")
            origin = origin if isinstance(origin, dict) else {}
            # A set of values is shown value by value, each with the scope
            # the service names for it. Anything else is one value under the
            # setting's own name, with the scope the service names for the
            # value as a whole. A value no scope has set says so in the
            # place of one. A setting nothing is set for has no row.
            fields = (
                [(f"{key}.{name}", part, str(origin.get(name) or "")) for name, part in value.items()]
                if isinstance(value, dict)
                else [(key, value, str(entry.get("scope") or ""))]
            )
            for name, part, scope in fields:
                if part is None:
                    continue
                rows.append((_scope_rank(scope), name, part, named.get(scope, scope) or _NO_SCOPE))
        # A stable sort: within a scope the settings keep their own order.
        rows.sort(key=lambda row: row[0])
        ctx.screen.print_above(
            _grid(
                (
                    (
                        Text(name, style="exe.accent"),
                        Text(_one_line(part), style="exe.text"),
                        Text(scope, style="exe.muted"),
                    )
                    for _, name, part, scope in rows
                ),
                wide=1,
            )
        )

    def set_setting(self, ctx: Context, argument: str) -> None:
        """``/set <scope>.<key> <value>`` sets the whole value; a third part
        names one field of a set of values and sets that field alone. The
        line that answers sets what the scope held against what it holds
        now."""
        target, written = _first_word(argument)
        parts = target.split(".")
        if not written or len(parts) not in (2, 3) or not all(parts):
            ctx.renderer.error(ctx.texts.t("cli.set_form"))
            return
        scope, key = parts[0], parts[1]
        field = parts[2] if len(parts) == 3 else None
        session = ctx.session
        # The two scopes nobody can be asked to type out: this chat's and
        # this model's. Every other word goes to the service as it stands.
        # A value set for a new chat is the first thing written into it,
        # and what creates it on the service.
        if scope == "chat":
            scope = f"chat:{chat.service_chat(ctx)['id']}"
        elif scope in ("model", "modell") and session.endpoint_id:
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
        # Before and after, as the service read them back.
        ctx.screen.print_above(
            _grid(
                [
                    (
                        Text(name, style="exe.accent"),
                        Text(_one_line(before), style="exe.muted"),
                        Text(glyphs.glyph("arrow"), style="exe.muted"),
                        Text(_one_line(after), style="exe.text"),
                    )
                ],
                wide=3,
            )
        )

    # --- /export ---

    def export(self, ctx: Context, argument: str) -> None:
        """The chat as a file: a Markdown transcript of its messages where
        the name ends in ``.md``, else the history as it was shown, as an
        HTML page. Without a name, a page in the client's own folder, named
        by the moment."""
        path = _saved_page(ctx) if not argument else Path(argument).expanduser()
        try:
            if path.suffix.lower() == _MARKDOWN:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(self._transcript(), encoding="utf-8")
            else:
                ctx.screen.export(path)
        except OSError as error:
            # Said in the system's own words; the chat is as it was.
            ctx.renderer.error(str(error))
            return
        ctx.renderer.notice(ctx.texts.t("cli.exported", path=str(path)))

    def _transcript(self) -> str:
        """The open chat as Markdown: its title, then every message under a
        heading that names who wrote it, in the words the service stores."""
        ctx = self._ctx
        # A new chat nobody wrote into has no messages, and goes by the
        # name the status line gives it.
        opened = ctx.session.chat or {"title": chat.fresh_title(ctx)}
        lines = [f"# {opened.get('title') or ''}".rstrip(), ""]
        for message in self._all_messages(opened.get("id")):
            role = str(message.get("role") or "").title()
            lines += [f"## {role}".rstrip(), "", str(message.get("content") or ""), ""]
        return "\n".join(lines).rstrip("\n") + "\n"

    def _all_messages(self, chat_id: Any) -> list[dict[str, Any]]:
        """Every message of that chat, oldest first, page by page."""
        listed: list[dict[str, Any]] = []
        if not chat_id:
            return listed
        while True:
            page = self._ctx.client.get(
                f"/chats/{chat_id}/messages", params={"limit": _PAGE, "offset": len(listed)}
            )
            got = page.get("nachrichten") if isinstance(page, dict) else None
            got = [message for message in got if isinstance(message, dict)] if isinstance(got, list) else []
            listed.extend(got)
            if len(got) < _PAGE:
                return listed

    # --- /tools ---

    def tools(self, ctx: Context, argument: str) -> None:
        word, name = _first_word(argument)
        if word.lower() == _FORGET and name:
            ctx.client.delete(f"/permissions/always-allow/{quote(name, safe='')}")
            ctx.renderer.notice(ctx.texts.t("cli.tool_asks_again", name=name))
            return
        if argument:
            ctx.renderer.error(ctx.texts.t("cli.werkzeug_syntax"))
            return
        answer = ctx.client.get("/tools")
        answer = answer if isinstance(answer, dict) else {}
        always = ctx.client.get("/permissions/always-allow")
        always = always if isinstance(always, dict) else {}
        offered = [tool for tool in answer.get("werkzeuge") or [] if isinstance(tool, dict)]
        if not offered and not always:
            ctx.renderer.notice(ctx.texts.t("cli.keine_werkzeuge"))
            return
        standing = ctx.texts.t("werkzeug.yes_dont_ask_again")
        # A standing permission for a tool that is not offered right now is
        # still on file and can still be taken back: it gets a row as well.
        offered_names = {tool.get("name") for tool in offered}
        listed = offered + [{"name": name} for name in always if name not in offered_names]
        ctx.screen.print_above(
            _grid(
                (
                    Text(glyphs.tool_glyph(str(tool.get("name") or "")), style="exe.tool"),
                    Text(str(tool.get("name") or ""), style="exe.tool"),
                    Text(str(tool.get("server") or ""), style="exe.muted"),
                    Text(standing if tool.get("name") in always else "", style="exe.green"),
                )
                for tool in listed
            )
        )

    # --- /theme, /lang ---

    def theme(self, ctx: Context, argument: str) -> None:
        # Names and words are written in lower case; how they are typed
        # does not matter.
        argument = argument.lower()
        word, rest = _first_word(argument)
        if word == _NERD:
            self._nerd(rest)
            return
        if themes.WINDOW_VARIABLE in os.environ:
            # Inside the window's tab the theme is the app's own, handed over
            # at the start: nothing is switched or remembered here, and the
            # sentence says where it is set.
            ctx.renderer.notice(ctx.texts.t("cli.theme_in_app"))
            return
        names = themes.available()
        before = themes.current()
        if not argument:
            picked = ctx.asker.choose(
                [
                    Entry(
                        cells=[("text", name)],
                        # The theme that follows the machine says so.
                        note=ctx.texts.t("cli.theme_auto") if name == themes.AUTO_LOOK else "",
                        in_use=name == before.name,
                    )
                    for name in names
                ]
            )
            if picked is None:
                return
            argument = names[picked]
        elif argument not in names:
            ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=argument))
            return
        unwritten = ""
        try:
            # Switched at once and kept for the next start. The switch
            # comes first: it holds for this run even where the choice
            # cannot be written.
            themes.set_look(argument, remember=True, prefs_path=ctx.prefs_path)
        except OSError as error:
            unwritten = str(error)
        # The terminal's ground follows at once.
        themes.paint()
        ctx.screen.update_status(look=themes.current().name)
        if themes.current() is not before:
            # What stands in the window was written in the colours of the
            # theme before, for its ground. On the new ground it is written
            # again.
            ctx.screen.redraw()
        if unwritten:
            # Said after the history: with no answer running it then stays
            # in sight.
            ctx.renderer.error(unwritten)

    def _nerd(self, wanted: str) -> None:
        """Switches the signs of the icon font on or off. They are off out
        of the box: no terminal says which font it draws with."""
        ctx = self._ctx
        if wanted and wanted not in _SWITCH_TYPED:
            ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=wanted))
            return
        if not wanted:
            # What this run switched to; before that, what the start read
            # from the remembered choices.
            active = self._nerd_signs
            if active is None:
                active = prefs.load(ctx.prefs_path).get(_NERD) is True
            words = list(_SWITCH)
            picked = ctx.asker.choose(
                [Entry(cells=[("text", word)], in_use=_SWITCH[word] == active) for word in words]
            )
            if picked is None:
                return
            wanted = words[picked]
        self._nerd_signs = _SWITCH_TYPED[wanted]
        glyphs.use_nerd(self._nerd_signs)
        self._remember(nerd=self._nerd_signs)
        # The fixed block carries signs too.
        ctx.screen.invalidate()

    def language(self, ctx: Context, argument: str) -> None:
        languages = list(available_languages())
        wanted = argument.lower()
        if not wanted:
            picked = ctx.asker.choose(
                [
                    Entry(cells=[("text", code)], in_use=code == ctx.texts.language)
                    for code in languages
                ]
            )
            if picked is None:
                return
            wanted = languages[picked]
        elif wanted not in languages:
            ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=argument))
            return
        ctx.texts.set_language(wanted)
        # The service's own sentences follow: every request names the
        # language it wants them in.
        ctx.client.language = wanted
        self._remember(language=wanted)

    def _remember(self, **choices: Any) -> None:
        """Keeps a choice for the next start. It holds for this run either
        way; that it could not be written is said in the system's words."""
        try:
            prefs.remember(self._ctx.prefs_path, **choices)
        except OSError as error:
            self._ctx.renderer.error(str(error))
