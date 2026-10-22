"""The commands behind a slash: what each one asks the service for, what it
changes, what it writes into the history and what it lets the user pick
from — on a stand-in transport, with a screen that only keeps what it is
handed and a selection that picks what a test names."""

from __future__ import annotations

import io
import json
import re
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.completion import CompleteEvent, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.console import Console

from cli import chat, commands, events, glyphs, prefs, render, themes
from cli.client import KEY_HEADER, LANGUAGE_HEADER, ServiceClient, ServiceError
from cli.interfaces import Asker, Context, Entry, Renderer, Screen
from cli.main import main
from cli.texts import CATALOGUE_DIRECTORY, Texts
from test_stream import shown_text
from test_themes import Terminal
from stub_service import foreground, noted

KEY = "key-of-this-run"
PAGE = f'<html><head><script>window.__SITZUNGSSCHLUESSEL__="{KEY}";</script></head></html>'
ENTER = "\r"

# How long a step may wait for another thread before it gives up, and after
# how long a run that never leaves is cut off. Both only bound a failure.
WAIT_SECONDS = 10
SAFETY_NET_SECONDS = 30

MODELS: list[dict[str, Any]] = [
    {
        "id": "local",
        "name": "Local Model",
        "anbieter_name": "here",
        "erreichbar": True,
        "context_tokens": 8192,
        "denkprofil": {"stufen": ["off", "low", "high"], "standard": "low", "art": "stufen"},
    },
    {
        "id": "remote",
        "name": "Remote Model",
        "anbieter_name": "there",
        "erreichbar": True,
        "context_tokens": 200000,
        "denkprofil": {"stufen": [], "standard": None, "art": "nie"},
    },
]

CHATS: list[dict[str, Any]] = [
    {"id": "chat-1", "title": "A fresh chat", "updated_at": "2026-03-04T10:00:00+00:00"},
    {
        "id": "chat-2",
        "title": "Holiday Plans",
        "updated_at": "2026-03-03T09:30:00+00:00",
        "laeuft": True,
    },
    {"id": "chat-3", "title": "Twice", "updated_at": "2026-03-02T08:00:00+00:00"},
    {"id": "chat-4", "title": "twice", "updated_at": "2026-03-01T07:00:00+00:00"},
]

RESOLVED: dict[str, Any] = {
    "parameter": {
        "wert": {"temperature": 0.7, "max_tokens": 4096, "top_p": 0.9, "top_k": 40},
        "herkunft": {
            "temperature": "chat:chat-1",
            "max_tokens": "global",
            "top_p": "modell:local",
            "top_k": "modell:another",
        },
    },
    "berechtigungsmodus_chat": {"wert": "manuell", "herkunft": {}, "scope": "global"},
    "werkzeuge_aus": {"wert": {}, "herkunft": {}, "scope": None},
    "scrollstelle": {"wert": {"am_boden": True}, "herkunft": {}, "scope": None},
    "verdichtung_schwelle": {"wert": 70, "herkunft": {}, "scope": "chat:chat-1"},
}

# What the service says to a permission mode written outside the global scope.
ONLY_GLOBAL = "'berechtigungsmodus_chat' can only be set in the scope 'global'"

ANSWER = (
    b'data: {"typ": "start", "generation_id": "g1", "message_id": "m1"}\n\n'
    b'data: {"typ": "content", "text": "Hello."}\n\n'
    b'data: {"typ": "done", "message_id": "m1"}\n\n'
)


class Service:
    """A stand-in for the service with the addresses the commands talk to.
    Every request is kept."""

    def __init__(self) -> None:
        self.seen: list[httpx.Request] = []
        self.chats = {listed["id"]: dict(listed) for listed in CHATS}
        self.always = {"run_command": "ja", "gone_tool": "ja"}
        self.created = 0
        # What GET /skills lists and what a fold answers with.
        # ``None`` makes the listing fail.
        self.skills: list[dict[str, Any]] | None = []
        self.fold: dict[str, Any] = {"result": "folded", "replaced": 12}
        # Called while a fold is under way, for a test that acts then.
        self.while_folding: Callable[[], None] | None = None
        # Scope → key → what the scope holds; what /settings reads and writes.
        self.settings: dict[str, dict[str, Any]] = {
            "chat:chat-1": {"parameter": {"temperature": 0.7, "top_p": 0.9}}
        }

    def asked(self, method: str, path: str) -> list[httpx.Request]:
        return [
            request
            for request in self.seen
            if request.method == method and request.url.path == f"/api/v1{path}"
        ]

    def bodies(self, method: str, path: str) -> list[Any]:
        return [json.loads(request.content) for request in self.asked(method, path)]

    def paths(self) -> list[str]:
        return [
            f"{request.method} {request.url.path}"
            for request in self.seen
            if foreground(request)
        ]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(noted(request))
        path = request.url.path
        if path == "/app/":
            return httpx.Response(200, text=PAGE)
        if request.headers.get(KEY_HEADER) != KEY:
            return httpx.Response(401, json={"detail": "Invalid or missing session key"})
        path = path.removeprefix("/api/v1")
        method = request.method
        if path == "/health":
            return httpx.Response(200, json={"status": "ok", "version": "9.8.7"})
        if path == "/models":
            return httpx.Response(200, json=MODELS)
        if path == "/chats" and method == "POST":
            self.created += 1
            created = {
                "id": f"new-{self.created}",
                "title": "Untitled chat",
                **json.loads(request.content),
            }
            self.chats[created["id"]] = created
            return httpx.Response(201, json=created)
        if path == "/chats":
            wanted = request.url.params.get("suche")
            listed = [
                listed
                for listed in self.chats.values()
                if wanted is None or wanted.casefold() in listed["title"].casefold()
            ]
            return httpx.Response(200, json=listed)
        if path == "/skills":
            if self.skills is None:
                return httpx.Response(500, json={"detail": "The skills cannot be read"})
            return httpx.Response(200, json=self.skills)
        if path.startswith("/chats/") and path.endswith("/compact") and method == "POST":
            if self.while_folding is not None:
                self.while_folding()
            return httpx.Response(200, json=self.fold)
        if path.startswith("/chats/") and path.endswith("/messages"):
            page = [
                {"role": "user", "content": "Where to?"},
                {"role": "assistant", "content": "To the sea."},
            ]
            return httpx.Response(
                200, json={"nachrichten": page}, headers={"X-Nachrichten-Gesamt": "7"}
            )
        if path.startswith("/chats/"):
            chat_id = path.split("/")[2]
            if chat_id not in self.chats:
                return httpx.Response(404, json={"detail": "Chat not found"})
            if method == "PATCH":
                self.chats[chat_id].update(json.loads(request.content))
            return httpx.Response(200, json=self.chats[chat_id])
        if path == "/settings/resolved":
            # Asked without a list, the service answers with every setting
            # it has, in the order of its own table.
            keys = request.url.params.get("keys")
            asked_for = list(RESOLVED) if keys is None else keys.split(",")
            return httpx.Response(
                200,
                json={
                    key: RESOLVED.get(key, {"wert": {}, "herkunft": {}, "scope": None})
                    for key in asked_for
                },
            )
        if path == "/settings/resolved/denken":
            return httpx.Response(
                200,
                json={"schluessel": "denken", "wert": {"stufe": "high"}, "herkunft": {}},
            )
        if path.startswith("/settings/") and method in ("GET", "PUT", "PATCH"):
            _, _, scope, key = path.split("/")
            if scope != "global" and not scope.startswith(("modell:", "chat:")):
                return httpx.Response(
                    400, json={"detail": "The scope must be 'global', 'modell:<id>' or 'chat:<id>'"}
                )
            held = self.settings.setdefault(scope, {})
            if method == "GET":
                return httpx.Response(
                    200, json={"bereich": scope, "schluessel": key, "wert": held.get(key)}
                )
            if key == "berechtigungsmodus_chat" and scope != "global":
                return httpx.Response(400, json={"detail": ONLY_GLOBAL})
            value = json.loads(request.content)["wert"]
            if key == "verdichtung_schwelle" and value == 500:
                return httpx.Response(
                    422, json={"detail": [{"loc": ["body", "wert"], "msg": "500 is out of range"}]}
                )
            if method == "PATCH":
                # Only a set of values can be written field by field; the
                # fields sent go over the ones held.
                kept = held.get(key)
                if not isinstance(value, dict) or (kept is not None and not isinstance(kept, dict)):
                    return httpx.Response(400, json={"detail": "Not a set of values"})
                value = {**(kept or {}), **value}
            if value is None:
                held.pop(key, None)
            else:
                held[key] = value
            return httpx.Response(200, json={"bereich": scope, "schluessel": key, "wert": value})
        if path == "/tools":
            return httpx.Response(
                200,
                json={
                    "aktiv": True,
                    "server": ["files"],
                    "werkzeuge": [
                        {"name": "read_file", "server": "files", "beschreibung": "Reads."},
                        {"name": "run_command", "server": "shell", "beschreibung": "Runs."},
                    ],
                },
            )
        if path == "/permissions/always-allow" and method == "GET":
            return httpx.Response(200, json=self.always)
        if path.startswith("/permissions/always-allow/") and method == "DELETE":
            name = path.rsplit("/", 1)[1]
            if name not in self.always:
                return httpx.Response(404, json={"detail": "There is no such rule"})
            del self.always[name]
            return httpx.Response(204)
        if path == "/chat/completions":
            return httpx.Response(200, content=ANSWER)
        if path == "/chat/stop":
            return httpx.Response(200, json={"abgebrochen": 1})
        return httpx.Response(404, json={"detail": "No such address"})


class Shown(Screen):
    """A screen that writes what it is handed into a console of a fixed
    width and keeps the rest."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx
        self.console = Console(
            file=io.StringIO(),
            width=100,
            record=True,
            force_terminal=False,
            theme=themes.current().rich_theme(),
        )
        self.status: dict[str, Any] = {}
        self.cleared = 0
        self.left = False
        self.waiting: list[dict[str, Any]] = []
        self.new_chats_waiting = 0

    def print_above(self, *renderables: Any) -> None:
        for renderable in renderables:
            self.console.print(renderable)

    def update_status(self, **fields: Any) -> None:
        self.status.update(fields)

    def clear(self) -> None:
        self.cleared += 1

    def exit(self) -> None:
        self.left = True

    def open_chat(self, opened: Any) -> None:
        # The running screen opens a chat in its turn among the waiting
        # lines; with no answer running that turn is now.
        if self._ctx.session.answering:
            self.waiting.append(dict(opened))
        else:
            chat.open_chat(self._ctx, opened)

    def new_chat(self) -> None:
        # A new chat takes its turn the same way.
        if self._ctx.session.answering:
            self.new_chats_waiting += 1
        else:
            chat.new_chat(self._ctx)

    def text(self) -> str:
        return self.console.export_text(clear=False)

    def lines(self) -> list[str]:
        return [" ".join(line.split()) for line in self.text().splitlines()]


class Lines(Renderer):
    """A renderer that writes its own lines plainly and keeps the messages
    of an opened chat."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx
        self.notices: list[str] = []
        self.remarks: list[str] = []
        self.errors: list[str] = []
        self.stored: list[Any] = []

    def notice(self, text: str) -> None:
        # A notice stands above the input field, never in the history.
        self.notices.append(text)

    def remark(self, text: str) -> None:
        self.remarks.append(text)
        self._ctx.screen.print_above(text)

    def error(self, text: str) -> None:
        self.errors.append(text)
        self._ctx.screen.print_above(text)

    def stored_message(self, message: Any) -> None:
        self.stored.append(message)


class Silent(Asker):
    """No question is asked in these tests."""


class Picking(Silent):
    """Stands in for the selection above the input field: it keeps every
    list of entries it is shown and picks the entry a test names — none,
    until one is named."""

    def __init__(self) -> None:
        self.shown: list[list[Entry]] = []
        # The line shown above each selection, as it was handed over.
        self.heads: list[str] = []
        self.pick: int | None = None

    def choose(self, entries: Any, head: str = "") -> int | None:
        self.shown.append(list(entries))
        self.heads.append(head)
        return self.pick

    def rows(self) -> list[list[str]]:
        """The entries of the selection shown last, column by column."""
        return [[text for _, text in entry.cells] for entry in self.shown[-1]]

    def in_use(self) -> list[int]:
        """Which entries of the selection shown last are marked as in use."""
        return [number for number, entry in enumerate(self.shown[-1]) if entry.in_use]


class Walking(Picking):
    """Picks the entries a test names, one selection after the other; a
    selection past the last one is closed. Text questions are answered from
    ``typed`` in turn and kept in ``questions``."""

    def __init__(self, *picks: int | None, typed: list[str | None] | None = None) -> None:
        super().__init__()
        self.picks = list(picks)
        self.typed = list(typed or [])
        self.questions: list[tuple[str, str | None]] = []

    def choose(self, entries: Any, head: str = "") -> int | None:
        self.shown.append(list(entries))
        self.heads.append(head)
        return self.picks.pop(0) if self.picks else None

    def ask_text(
        self, head: str, *, secret: bool = False, default: str | None = None
    ) -> str | None:
        self.questions.append((head, default))
        return self.typed.pop(0) if self.typed else None

    def remarks(self) -> list[str]:
        """The remark of each entry of the selection shown last."""
        return [entry.note for entry in self.shown[-1]]


def context(service: Service, tmp_path: Path, language: str = "en") -> Context:
    """Everything the commands need, without a screen that runs."""
    client = ServiceClient(
        "http://service.test", language, http=httpx.Client(transport=httpx.MockTransport(service))
    )
    client.connect()
    ctx = Context(client=client, texts=Texts(language), prefs_path=tmp_path / "cli.json")
    ctx.screen = Shown(ctx)
    ctx.renderer = Lines(ctx)
    ctx.asker = Picking()
    ctx.commands = commands.build_commands(ctx)
    ctx.session.models = [dict(model) for model in MODELS]
    ctx.session.endpoint_id = "local"
    ctx.session.chat = dict(CHATS[0])
    service.seen.clear()
    return ctx


@pytest.fixture
def service() -> Service:
    return Service()


@pytest.fixture
def ctx(service: Service, tmp_path: Path) -> Context:
    return context(service, tmp_path)


@pytest.fixture(autouse=True)
def the_default_look():
    yield
    themes.set_look(themes.DEFAULT_LOOK)


def until(condition: Callable[[], Any]) -> None:
    """Waits for another thread to get somewhere."""
    deadline = time.monotonic() + WAIT_SECONDS
    while not condition():
        assert time.monotonic() < deadline, "the other thread never got there"
        time.sleep(0.01)


def played(steps: list[str | Callable[[], Any]], service: Service, tmp_path: Path) -> str:
    """Runs the whole client and types ``steps`` into it, one after the
    other: a text is typed as it stands, a condition is waited for. Returns
    the plain text of everything shown, read back from an export of the
    history written once the client has left."""
    parts: list[Context] = []
    built = events.build_events

    def remember(ctx: Context) -> Any:
        parts.append(ctx)
        return built(ctx)

    with create_pipe_input() as pipe:

        def type_them() -> None:
            for step in steps:
                if callable(step):
                    until(step)
                else:
                    pipe.send_text(step)

        typing = threading.Thread(target=type_them, daemon=True)
        safety_net = threading.Timer(SAFETY_NET_SECONDS, pipe.close)
        safety_net.start()
        events.build_events = remember
        try:
            with create_app_session(input=pipe, output=DummyOutput()):
                typing.start()
                code = main(
                    ["--url", "http://service.test", "--lang", "en"],
                    http=httpx.Client(transport=httpx.MockTransport(service)),
                    prefs_path=tmp_path / "cli.json",
                )
        finally:
            events.build_events = built
            safety_net.cancel()
    assert code == 0
    target = tmp_path / "shown.html"
    parts[0].screen.export(target)
    return shown_text(target.read_text(encoding="utf-8"))


# --- The register, /help, /quit, /clear, completion --------------------------------


def test_help_names_every_registered_command_with_its_one_line(ctx):
    ctx.commands.run("/help")
    lines = ctx.screen.lines()
    names = ctx.commands.names()
    assert names == [
        "new", "chats", "rename", "delete", "archive", "project", "model", "server", "download", "provider", "status", "theme", "lang", "setup",
        "settings", "agents", "cron", "tools", "ps", "mcp", "skills", "files", "image", "rollback", "memory", "system", "dir", "think", "compact", "export", "stop", "clear", "help", "quit", "exit",
    ]  # fmt: skip
    # A row begins with the command's name; whatever stands below it up to
    # the next name belongs to it. A line that carries a sentence on may
    # itself begin with a command's name, so only the name that is next
    # opens a row.
    rows: list[list[str]] = []
    for line in lines:
        following = names[len(rows)] if len(rows) < len(names) else None
        if following is not None and line.startswith(f"/{following} "):
            rows.append([line])
        else:
            rows[-1].append(line)
    assert len(rows) == len(names)
    for name, row in zip(names, rows, strict=True):
        command = next(found for found in ctx.commands.matching(name) if found.name == name)
        summary = ctx.commands.summary(command)
        first, *further = summary.split("\n")
        assert row[0] == f"/{name} {first}", row
        # A summary that runs on to a second line keeps that line in the
        # same row, below its first — carried on below itself where it is
        # longer than the window is wide. Nothing of it is lost.
        if further:
            assert row[1].startswith(further[0].split()[0]), row
        assert " ".join(row) == f"/{name} {' '.join(summary.split())}", row
        # A sentence of the catalogue, not a key left standing.
        assert not re.fullmatch(r"[a-z_]+(\.[a-z_]+)+", summary), summary


def test_help_shows_the_lines_as_they_were_approved(ctx):
    ctx.commands.run("/help")
    lines = ctx.screen.lines()
    assert "/chats Choose a chat" in lines
    assert "/clear Clear the screen; keep the chat" in lines
    # A sentence of two lines: the second stands below the first.
    theme = lines.index("/theme Choose a theme")
    assert lines[theme + 1] == (
        "Enable Nerd Font symbols with /theme nerd on; disable them with /theme nerd off."
    )


def test_the_completer_shows_the_first_line_of_a_summary_that_has_two(ctx):
    summary = ctx.commands.summary(ctx.commands.matching("theme")[0])
    first, second = summary.split("\n")
    assert first == "Choose a theme" and second.startswith("Enable Nerd Font symbols")
    assert completions(ctx, "/the") == [("/theme", first)]


@pytest.mark.parametrize("line", ["/chat", "/chat 2", "/look", "/look pearl"])
def test_the_two_commands_that_went_are_unknown_and_do_nothing(ctx, service, line):
    ctx.commands.run(line)
    assert ctx.renderer.errors == [Texts("en").t("cli.unbekannt", name=line.split()[0][1:])]
    assert service.paths() == ["GET /api/v1/skills"] and ctx.asker.shown == []
    assert ctx.session.chat["id"] == "chat-1"
    assert themes.current().name == themes.DEFAULT_LOOK


@pytest.mark.parametrize("line", ["/model", "/chats", "/theme", "/lang", "/think", "/theme nerd"])
def test_without_a_word_the_command_opens_a_selection_and_writes_nothing(ctx, service, line):
    ctx.commands.run(line)
    assert len(ctx.asker.shown) == 1 and ctx.asker.shown[0]
    # Nothing in the history, nothing above the input field, nothing to
    # the model.
    assert ctx.screen.text() == ""
    assert ctx.renderer.notices == [] and ctx.renderer.errors == []
    assert not service.asked("POST", "/chat/completions")


@pytest.mark.parametrize(
    "line", ["/model 2", "/theme pearl", "/lang de", "/think high", "/theme nerd on"]
)
def test_with_a_word_the_command_takes_it_and_lists_nothing(ctx, service, line, monkeypatch):
    monkeypatch.setattr(glyphs, "use_nerd", lambda switched: None)
    ctx.commands.run(line)
    # Taken as it stands: no selection opens, and no list is written.
    assert ctx.asker.shown == [] and ctx.screen.text() == ""
    assert ctx.renderer.errors == []


def test_a_chat_named_by_its_number_is_opened_and_only_its_own_history_is_written(ctx, service):
    ctx.commands.run("/chats 2")
    assert ctx.asker.shown == [] and ctx.renderer.errors == []
    assert ctx.session.chat["id"] == "chat-2"
    # The line that counts the chat's messages, and no list of chats.
    assert ctx.screen.lines() == [f"2/7 {Texts('en').t('cli.messages')}"]


def test_an_unknown_command_is_answered_and_asks_the_service_only_for_its_skills(ctx, service):
    ctx.commands.run("/nope now")
    assert ctx.renderer.errors == [Texts("en").t("cli.unbekannt", name="nope")]
    # The word might name a skill: the list of them is the one thing asked.
    assert service.paths() == ["GET /api/v1/skills"]


def test_quit_and_exit_leave_the_client(ctx):
    ctx.commands.run("/quit")
    assert ctx.screen.left
    ctx.screen.left = False
    ctx.commands.run("/exit")
    assert ctx.screen.left


def test_clear_empties_the_screen_and_the_chat_stays(ctx, service):
    ctx.commands.run("/clear")
    assert ctx.screen.cleared == 1
    assert ctx.session.chat["id"] == "chat-1"
    assert service.seen == []


def offered(ctx: Context, typed: str) -> list[Completion]:
    completer = ctx.commands.completer()
    assert completer is not None
    return list(completer.get_completions(Document(typed), CompleteEvent()))


def completions(ctx: Context, typed: str) -> list[tuple[str, str]]:
    return [(completion.text, completion.display_meta_text) for completion in offered(ctx, typed)]


def test_the_completer_offers_model_for_mo(ctx):
    assert completions(ctx, "/mo") == [("/model", Texts("en").t("cli.cmd_model"))]


def test_the_completer_offers_every_command_after_a_bare_slash(ctx):
    assert [text for text, _ in completions(ctx, "/")] == [
        f"/{name}" for name in ctx.commands.names()
    ]


def test_the_completer_replaces_what_was_typed_and_not_more(ctx):
    assert [(completion.text, completion.start_position) for completion in offered(ctx, "/CH")] == [
        ("/chats", -3),
    ]


def test_the_completer_is_silent_without_a_slash_and_behind_the_first_word(ctx):
    assert completions(ctx, "mo") == []
    assert completions(ctx, "say /mo") == []
    assert completions(ctx, "/model 2") == []
    assert completions(ctx, "/model ") == []


def test_a_line_with_a_slash_runs_a_command_and_never_goes_to_the_model(service, tmp_path):
    shown = played(["/help" + ENTER, "/quit" + ENTER], service, tmp_path)
    assert f"/help      {Texts('en').t('cli.cmd_help')}" in shown
    assert not service.asked("POST", "/chat/completions")


def test_a_line_without_a_slash_never_reaches_the_register(service, tmp_path):
    shown = played(
        [
            "help" + ENTER,
            lambda: service.asked("POST", "/chat/completions"),
            "/quit" + ENTER,
        ],
        service,
        tmp_path,
    )
    assert service.bodies("POST", "/chat/completions")[0]["content"] == "help"
    assert Texts("en").t("cli.cmd_help") not in shown


# --- the skills behind the slash ---------------------------------------------------

SKILLS = [
    {"name": "summarise", "beschreibung": "Sums a text up.\nSecond line.", "auto": True},
    {"name": "resume", "beschreibung": "Picks a thread up again.", "auto": False},
    {"name": "export", "beschreibung": "Clashes with the command.", "auto": False},
]


def test_the_skills_stand_behind_the_commands_once_the_service_has_listed_them(ctx, service):
    service.skills = SKILLS
    offered(ctx, "/")  # starts the reading on a thread of its own
    until(lambda: len(service.asked("GET", "/skills")) == 1)
    until(lambda: any(c.text == "/summarise" for c in offered(ctx, "/")))
    names = [completion.text for completion in offered(ctx, "/")]
    assert names.index("/summarise") > names.index("/export")
    assert names.count("/export") == 1
    # The first line of the description is what stands beside the name.
    found = {c.text: c.display_meta_text for c in offered(ctx, "/summ")}
    assert found == {"/summarise": "Sums a text up."}
    # Asked once, however often the list is opened.
    assert len(service.asked("GET", "/skills")) == 1


def test_skills_that_start_with_the_letters_come_before_those_that_hold_them(ctx, service):
    service.skills = SKILLS
    offered(ctx, "/")
    until(lambda: any(c.text == "/resume" for c in offered(ctx, "/")))
    # "su" starts summarise and sits inside resume.
    assert [c.text for c in offered(ctx, "/su")] == ["/summarise", "/resume"]


def test_a_line_with_a_skill_name_goes_out_as_a_message_with_the_skill(ctx, service):
    service.skills = SKILLS
    ctx.commands.run("/summarise the report on sails")
    sent = service.bodies("POST", "/chat/completions")
    assert len(sent) == 1
    assert sent[0]["content"] == "/summarise the report on sails"
    assert sent[0]["skill"] == "summarise"
    assert sent[0]["chat_id"] == "chat-1"
    assert ctx.renderer.errors == []


def test_a_skill_name_is_found_whatever_its_case(ctx, service):
    service.skills = SKILLS
    ctx.commands.run("/SUMMARISE now")
    assert service.bodies("POST", "/chat/completions")[0]["skill"] == "summarise"


def test_the_first_skill_line_of_a_new_chat_names_it_after_the_words_behind_it(ctx, service):
    service.skills = SKILLS
    ctx.commands.run("/new")
    ctx.commands.run("/summarise the report on sails")
    assert service.chats["new-1"]["title"] == "the report on sails"


def test_a_skill_named_like_a_command_is_the_command(ctx, service):
    service.skills = SKILLS + [{"name": "Compact", "beschreibung": "Same word.", "auto": False}]
    offered(ctx, "/")
    until(lambda: any(c.text == "/summarise" for c in offered(ctx, "/")))
    # Whatever its case, the skill with the name of a command is not listed.
    assert [c.text for c in offered(ctx, "/")].count("/export") == 1
    assert "/Compact" not in [c.text for c in offered(ctx, "/")]
    ctx.commands.run("/export")
    assert not service.asked("POST", "/chat/completions")


def test_a_skill_line_waits_behind_a_running_answer(ctx, service):
    service.skills = SKILLS
    queued: list[Callable[[], None]] = []
    ctx.screen.queue = queued.append  # type: ignore[method-assign]
    ctx.session.answering = True
    ctx.commands.run("/summarise it")
    assert queued and not service.asked("POST", "/chat/completions")
    ctx.session.answering = False
    queued[0]()
    assert service.bodies("POST", "/chat/completions")[0]["skill"] == "summarise"


def test_the_commands_stand_without_an_error_line_when_the_skills_cannot_be_read(ctx, service):
    service.skills = None
    names = [completion.text for completion in offered(ctx, "/")]
    assert "/export" in names
    until(lambda: service.asked("GET", "/skills"))
    assert ctx.renderer.errors == []
    ctx.commands.run("/summarise it")
    assert ctx.renderer.errors == [Texts("en").t("cli.unbekannt", name="summarise")]


def test_a_message_without_a_slash_carries_no_skill(ctx, service):
    service.skills = SKILLS
    chat.send(ctx, "summarise this")
    assert "skill" not in service.bodies("POST", "/chat/completions")[0]


def test_an_unknown_word_is_still_unknown_when_the_skills_are_not_listed(ctx, service):
    ctx.commands.run("/summarise it")
    assert ctx.renderer.errors == [Texts("en").t("cli.unbekannt", name="summarise")]
    assert not service.asked("POST", "/chat/completions")


# --- /compact ----------------------------------------------------------------------


def test_compact_asks_the_service_to_fold_with_the_topic_and_says_how_many(ctx, service):
    ctx.commands.run("/compact the budget talk")
    assert service.bodies("POST", "/chats/chat-1/compact") == [
        {"endpoint_id": ctx.session.endpoint_id, "topic": "the budget talk"}
    ]
    assert ctx.renderer.remarks == [Texts("en").t("nachricht.verdichtet", anzahl=12)]


def test_compact_without_words_sends_no_topic(ctx, service):
    ctx.commands.run("/compact")
    assert service.bodies("POST", "/chats/chat-1/compact")[0]["topic"] is None


@pytest.mark.parametrize(
    ("answer", "key"),
    [
        ({"result": "too_short", "replaced": 0}, "eingabe.compact_too_short"),
        ({"result": "no_saving", "replaced": 0}, "eingabe.compact_no_saving"),
    ],
)
def test_compact_says_why_it_did_not_fold(ctx, service, answer, key):
    service.fold = answer
    ctx.commands.run("/compact")
    assert ctx.renderer.notices == [Texts("en").t(key)]
    assert ctx.renderer.remarks == [] and ctx.renderer.errors == []


def test_compact_that_was_stopped_says_nothing(ctx, service):
    service.fold = {"result": "stopped", "replaced": 0}
    ctx.commands.run("/compact")
    assert ctx.renderer.notices == [] and ctx.renderer.errors == [] and ctx.renderer.remarks == []


def test_the_interrupt_key_during_a_fold_asks_the_service_to_stop(ctx, service):
    service.fold = {"result": "stopped", "replaced": 0}
    service.while_folding = lambda: ctx.session.cancel_wait()
    ctx.commands.run("/compact")
    until(lambda: service.asked("POST", "/chat/stop"))
    assert service.bodies("POST", "/chat/stop") == [{"chat_id": "chat-1"}]
    assert ctx.renderer.notices == [] and ctx.renderer.errors == [] and ctx.renderer.remarks == []
    # The key is the key of an answer again once the fold is over.
    assert ctx.session.cancel_wait is None


def test_compact_that_failed_says_so(ctx, service):
    service.fold = {"result": "failed", "replaced": 0}
    ctx.commands.run("/compact")
    assert ctx.renderer.errors == [Texts("en").t("nachricht.komprimieren_fehlgeschlagen")]


def test_compact_without_a_number_still_says_it_folded(ctx, service):
    service.fold = {"result": "folded"}
    ctx.commands.run("/compact")
    assert ctx.renderer.remarks == [Texts("en").t("nachricht.verdichtet_ohne_zahl")]


def test_compact_in_a_chat_the_service_does_not_have_yet_has_nothing_to_fold(ctx, service):
    ctx.commands.run("/new")
    service.seen.clear()
    ctx.commands.run("/compact")
    assert ctx.renderer.notices[-1] == Texts("en").t("eingabe.compact_too_short")
    assert service.seen == []


def test_compact_during_an_answer_is_refused_and_asks_nothing(ctx, service):
    ctx.session.answering = True
    ctx.commands.run("/compact")
    assert ctx.renderer.notices == [Texts("en").t("fehler.antwort_laeuft_schon")]
    assert not service.asked("POST", "/chats/chat-1/compact")


def test_every_text_the_commands_and_questions_name_stands_in_both_catalogues():
    """A key written into the two modules and missing in a catalogue would
    stand on the screen as the key itself."""
    package = Path(commands.__file__).resolve().parent
    named: set[str] = set()
    for module in ("commands.py", "dialogs.py"):
        source = (package / module).read_text(encoding="utf-8")
        named.update(re.findall(r'"([a-z_]+(?:\.[a-z_]+)+)"', source))
    # Style names share the shape of a key and are none.
    named = {name for name in named if not name.startswith("exe.")}
    assert "cli.cmd_help" in named and "werkzeug.just_this_once" in named
    for language in ("en", "de"):
        catalogue = json.loads((CATALOGUE_DIRECTORY / f"{language}.json").read_text("utf-8"))
        missing = []
        for name in sorted(named):
            node: Any = catalogue
            for part in name.split("."):
                node = node.get(part) if isinstance(node, dict) else None
            if not isinstance(node, str):
                missing.append(name)
        assert not missing, f"missing in {language}.json: {missing}"


# --- /new, /chats -----------------------------------------------------------------


def test_new_opens_a_chat_the_service_is_not_asked_for(ctx, service):
    ctx.session.thinking = "high"
    ctx.commands.run("/new")
    # Nothing was written into it: the service's list stays as long as it was.
    assert service.seen == []
    assert len(service.chats) == len(CHATS)
    assert ctx.session.chat is None and ctx.session.unnamed
    assert ctx.screen.status["chat_title"] == "Untitled chat"
    assert ctx.renderer.notices == [Texts("en").t("cli.chat_neu")]
    # The stage belonged to the chat before.
    assert ctx.session.thinking is None


def test_the_first_message_of_a_new_chat_creates_it_with_the_model_in_use(ctx, service):
    ctx.commands.run("/new")
    chat.send(ctx, "Where to this year")
    assert service.bodies("POST", "/chats") == [{"endpoint_id": "local"}]
    assert ctx.session.chat["id"] == "new-1"
    assert service.bodies("POST", "/chat/completions")[0]["chat_id"] == "new-1"
    # And it names the chat, as before.
    assert service.chats["new-1"]["title"] == "Where to this year"
    assert not ctx.session.unnamed


def test_a_value_set_for_a_new_chat_creates_it(ctx, service):
    """A value that hangs on the chat is something written into it."""
    ctx.commands.run("/new")
    ctx.commands.run('/settings chat.parameter {"temperature": 0.3}')
    assert service.bodies("POST", "/chats") == [{"endpoint_id": "local"}]
    assert service.bodies("PUT", "/settings/chat:new-1/parameter") == [{"wert": {"temperature": 0.3}}]
    assert ctx.session.chat["id"] == "new-1"


def test_a_model_chosen_in_a_new_chat_goes_along_when_it_is_created(ctx, service):
    """Silence probe: choosing a model writes nothing into the chat; the
    chat is created with it once a message does."""
    ctx.commands.run("/new")
    ctx.commands.run("/model remote")
    assert not service.asked("POST", "/chats")
    chat.send(ctx, "Hello")
    assert service.bodies("POST", "/chats") == [{"endpoint_id": "remote"}]


def test_new_behind_a_running_answer_waits_for_its_end(ctx, service):
    ctx.session.answering = True
    ctx.commands.run("/new")
    assert not service.asked("POST", "/chats")
    # The answer still belongs to the chat it runs in.
    assert ctx.session.chat["id"] == "chat-1"
    assert ctx.screen.new_chats_waiting == 1 and ctx.screen.waiting == []
    assert ctx.renderer.notices == [Texts("en").t("cli.chat_waits", name="Untitled chat")]


def test_chats_without_a_word_opens_a_selection_in_the_services_order(ctx, service):
    ctx.commands.run("/chats")
    assert service.paths() == ["GET /api/v1/chats"]
    rows = ctx.asker.rows()
    # The newest first, as the service lists them and as the head numbers
    # them: title, time of the last change, and what runs.
    assert [row[0] for row in rows] == ["A fresh chat", "Holiday Plans", "Twice", "twice"]
    assert all(re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d", row[1]) for row in rows)
    assert [row[2] for row in rows] == ["", Texts("en").t("cli.laeuft"), "", ""]
    # The open chat is the one in use.
    assert ctx.asker.in_use() == [0]
    # Nothing was picked: nothing is opened, and nothing is said.
    assert ctx.session.chat["id"] == "chat-1"
    assert ctx.renderer.stored == [] and ctx.renderer.notices == []


def test_a_chat_picked_from_the_selection_is_opened_as_its_number_would_open_it(ctx, service):
    ctx.session.thinking = "high"
    ctx.asker.pick = 1
    ctx.commands.run("/chats")
    assert ctx.session.chat["id"] == "chat-2"
    # Read anew by its id, not taken from the list it stood in.
    assert service.asked("GET", "/chats/chat-2")
    assert [message["content"] for message in ctx.renderer.stored] == ["Where to?", "To the sea."]
    assert ctx.renderer.notices == [Texts("en").t("cli.chat_gewechselt", name="Holiday Plans")]
    assert ctx.screen.status["chat_title"] == "Holiday Plans"
    assert ctx.session.thinking is None
    # Its own history, as for a chat named by its number; no list of chats.
    assert ctx.screen.lines() == [f"2/7 {Texts('en').t('cli.messages')}"]


def test_a_chat_picked_behind_a_running_answer_waits_for_its_end(ctx, service):
    ctx.session.answering = True
    ctx.asker.pick = 1
    ctx.commands.run("/chats")
    assert ctx.session.chat["id"] == "chat-1"
    assert [waiting["id"] for waiting in ctx.screen.waiting] == ["chat-2"]
    assert ctx.renderer.notices == [Texts("en").t("cli.chat_waits", name="Holiday Plans")]


def test_in_a_new_chat_no_entry_of_the_selection_is_in_use(ctx):
    ctx.commands.run("/new")
    ctx.commands.run("/chats")
    assert len(ctx.asker.rows()) == len(CHATS) and ctx.asker.in_use() == []


def test_without_a_chat_there_is_nothing_to_pick_and_nothing_is_said(ctx, service):
    """Silence probe: as before, when the list of no chats was empty."""
    service.chats = {}
    ctx.commands.run("/chats")
    assert ctx.asker.shown == []
    assert ctx.screen.text() == ""
    assert ctx.renderer.notices == [] and ctx.renderer.errors == []
    # The numbers a word counts into are those of this list: none.
    assert ctx.session.shown_chats == []


def test_chat_with_a_title_switches_whatever_its_case_and_reads_the_history(ctx, service):
    ctx.session.thinking = "high"
    ctx.commands.run("/chats holiday plans")
    assert ctx.session.chat["id"] == "chat-2"
    assert service.asked("GET", "/chats/chat-2/messages")
    assert [message["content"] for message in ctx.renderer.stored] == ["Where to?", "To the sea."]
    assert ctx.renderer.notices[0] == Texts("en").t("cli.chat_gewechselt", name="Holiday Plans")
    assert ctx.screen.status["chat_title"] == "Holiday Plans"
    assert ctx.session.thinking is None
    # A title is asked for by name; the whole list is fetched for a number.
    assert [request.url.params.get("suche") for request in service.asked("GET", "/chats")] == [
        "holiday plans"
    ]


def test_chat_with_a_number_takes_the_chat_that_stood_at_that_number(ctx, service):
    ctx.commands.run("/chats")
    # What the service would list now has moved on; the number still means
    # what stood on the screen.
    service.chats = dict(reversed(list(service.chats.items())))
    ctx.commands.run("/chats 2")
    assert ctx.session.chat["id"] == "chat-2"


def test_chat_with_a_number_and_no_list_shown_counts_into_the_services_list(ctx, service):
    ctx.commands.run("/chats 3")
    assert ctx.session.chat["id"] == "chat-3"


def a_chat_made_elsewhere(service: Service) -> None:
    """A chat that came into being since the list was shown; the service
    lists it first."""
    newest = {"id": "chat-9", "title": "Made elsewhere", "updated_at": "2026-03-05T12:00:00+00:00"}
    service.chats = {"chat-9": newest, **service.chats}


def test_chat_with_a_number_takes_the_chat_the_head_named_under_it(ctx, service):
    """The head numbers the newest chats. A chat made elsewhere since then
    pushes every one of them down the service's list by one; the number
    still opens the chat it stood beside."""
    render.build_renderer(ctx).header("9.8.7", "http://service.test")
    assert any(line.startswith("2 Holiday Plans") for line in ctx.screen.lines())
    a_chat_made_elsewhere(service)
    ctx.commands.run("/chats 2")
    assert ctx.session.chat["id"] == "chat-2"


def test_after_the_list_of_chats_its_numbers_are_the_ones_that_count(ctx, service):
    """Silence probe: the head's numbers hold until a list is shown again."""
    render.build_renderer(ctx).header("9.8.7", "http://service.test")
    a_chat_made_elsewhere(service)
    ctx.commands.run("/chats")
    ctx.commands.run("/chats 2")
    assert ctx.session.chat["id"] == "chat-1"


def test_a_chat_opened_by_its_number_is_opened_as_the_service_has_it_now(ctx, service):
    """The number says which chat; what the list said about it then may be
    old. Renamed and given a model elsewhere since, the chat is opened under
    its name of now and keeps that model."""
    render.build_renderer(ctx).header("9.8.7", "http://service.test")
    service.chats["chat-2"].update(title="Renamed since", endpoint_id="remote")
    ctx.commands.run("/chats 2")
    assert ctx.session.chat["title"] == "Renamed since"
    assert ctx.session.endpoint_id == "remote"
    assert ctx.renderer.notices == [Texts("en").t("cli.chat_gewechselt", name="Renamed since")]
    assert not [request for request in service.seen if request.method == "PATCH"]


def test_a_number_whose_chat_is_gone_says_so_in_the_services_words_and_switches_to_none(
    ctx, service
):
    render.build_renderer(ctx).header("9.8.7", "http://service.test")
    del service.chats["chat-2"]
    with pytest.raises(ServiceError) as refused:
        ctx.commands.run("/chats 2")
    assert refused.value.detail == "Chat not found"
    assert ctx.session.chat["id"] == "chat-1"
    assert not service.asked("GET", "/chats/chat-2/messages")


def test_a_number_the_list_does_not_reach_is_a_title(ctx, service):
    """Silence probe: as before."""
    service.chats["chat-7"] = {"id": "chat-7", "title": "7", "updated_at": "2026-03-01T06:00:00+00:00"}
    ctx.session.shown_chats = [dict(listed) for listed in CHATS]
    ctx.commands.run("/chats 7")
    assert ctx.session.chat["id"] == "chat-7"


def test_a_title_two_chats_carry_lists_them_and_switches_to_none(ctx, service):
    ctx.commands.run("/chats TWICE")
    assert ctx.session.chat["id"] == "chat-1"
    assert not service.asked("GET", "/chats/chat-3/messages")
    # The two are listed in the history, where a list belongs.
    assert [remark.split()[0] for remark in ctx.renderer.remarks] == ["Twice", "twice"]
    assert ctx.renderer.notices == []


def test_chat_with_a_name_nothing_answers_to_says_so(ctx, service):
    ctx.commands.run("/chats nowhere")
    assert ctx.session.chat["id"] == "chat-1"
    assert ctx.renderer.errors == [Texts("en").t("cli.chat_unbekannt", name="nowhere")]


def test_chat_behind_a_running_answer_waits_for_its_end(ctx, service):
    ctx.session.answering = True
    ctx.commands.run("/chats 2")
    assert ctx.session.chat["id"] == "chat-1"
    assert [waiting["id"] for waiting in ctx.screen.waiting] == ["chat-2"]
    assert ctx.renderer.notices == [Texts("en").t("cli.chat_waits", name="Holiday Plans")]


def test_a_switch_that_waits_leaves_the_stage_to_the_lines_still_waiting(ctx, service):
    ctx.session.answering = True
    ctx.session.thinking = "high"
    ctx.commands.run("/chats 2")
    ctx.commands.run("/new")
    assert ctx.session.thinking == "high"


# --- /model -----------------------------------------------------------------------


def test_model_without_a_word_opens_a_selection_of_the_services_models(ctx, service):
    ctx.commands.run("/model")
    # The model folder is asked too: its files are offered behind the models.
    assert service.paths() == ["GET /api/v1/models", "GET /api/v1/runner"]
    connected = Texts("en").t("status.erreichbar")
    assert ctx.asker.rows() == [
        ["Local Model", "here", connected, "8192"],
        ["Remote Model", "there", connected, "200000"],
    ]
    # The model the next message goes to is the one in use.
    assert ctx.asker.in_use() == [0]
    # Nothing was picked: nothing is changed, and nothing is said.
    assert ctx.session.endpoint_id == "local"
    assert ctx.renderer.notices == [] and ctx.screen.status == {}


def test_a_model_picked_from_the_selection_is_chosen_as_its_number_would_choose_it(ctx, service):
    ctx.session.thinking = "high"
    ctx.asker.pick = 1
    ctx.commands.run("/model")
    assert service.bodies("PATCH", "/chats/chat-1") == [{"endpoint_id": "remote"}]
    assert service.bodies("PUT", f"/settings/global/{commands.LAST_MODEL_KEY}") == [
        {"wert": {"id": "remote", "name": "Remote Model"}}
    ]
    assert ctx.session.endpoint_id == "remote"
    assert ctx.screen.status == {"model_name": "Remote Model", "context_window": 200000}
    assert ctx.renderer.notices == [Texts("en").t("cli.modell_gewaehlt", name="Remote Model")]
    assert ctx.session.thinking is None
    assert ctx.screen.text() == ""


def test_without_a_model_there_is_nothing_to_pick_and_that_is_said(ctx, service, monkeypatch):
    """Silence probe: as before, when the list of no models said so."""
    monkeypatch.setattr(sys.modules[__name__], "MODELS", [])
    ctx.commands.run("/model")
    assert ctx.asker.shown == []
    assert ctx.renderer.notices == [Texts("en").t("cli.keine_modelle")]


def test_a_name_two_models_carry_opens_the_selection_to_pick_from(ctx, service, monkeypatch):
    twins = [dict(MODELS[0]), {**MODELS[1], "name": "Local Model"}]
    monkeypatch.setattr(sys.modules[__name__], "MODELS", twins)
    ctx.asker.pick = 1
    ctx.commands.run("/model local model")
    assert [row[0] for row in ctx.asker.rows()] == ["Local Model", "Local Model"]
    assert ctx.session.endpoint_id == "remote"
    assert ctx.renderer.errors == []


def test_model_with_a_number_is_kept_with_the_chat_and_the_next_message_carries_it(ctx, service):
    ctx.session.thinking = "high"
    ctx.commands.run("/model")
    ctx.commands.run("/model 2")
    assert service.bodies("PATCH", "/chats/chat-1") == [{"endpoint_id": "remote"}]
    # Remembered the way the window remembers its choice, so the next start
    # of either shows the same model — under its name, while its server is
    # away and names nothing.
    assert service.bodies("PUT", f"/settings/global/{commands.LAST_MODEL_KEY}") == [
        {"wert": {"id": "remote", "name": "Remote Model"}}
    ]
    assert ctx.session.endpoint_id == "remote"
    assert ctx.session.chat["endpoint_id"] == "remote"
    assert ctx.screen.status == {"model_name": "Remote Model", "context_window": 200000}
    assert ctx.renderer.notices == [Texts("en").t("cli.modell_gewaehlt", name="Remote Model")]
    # A stage of the model before is none of this one's.
    assert ctx.session.thinking is None
    chat.send(ctx, "Hello")
    sent = service.bodies("POST", "/chat/completions")[0]
    assert sent["endpoint_id"] == "remote" and "thinking" not in sent


def test_model_with_a_name_takes_it_whatever_its_case(ctx, service):
    ctx.commands.run("/model remote MODEL")
    assert ctx.session.endpoint_id == "remote"
    assert service.bodies("PATCH", "/chats/chat-1") == [{"endpoint_id": "remote"}]


def test_model_with_a_number_the_list_does_not_reach_changes_nothing_and_says_so(ctx, service):
    ctx.commands.run("/model 99")
    assert ctx.session.endpoint_id == "local"
    assert not service.asked("PATCH", "/chats/chat-1")
    assert ctx.screen.status == {}
    assert ctx.renderer.errors == [Texts("en").t("cli.modell_unbekannt", name="99")]


def test_a_refused_model_leaves_everything_as_it_was(ctx, service):
    ctx.session.chat = {"id": "gone", "title": "A chat that was deleted"}
    with pytest.raises(ServiceError) as refused:
        ctx.commands.run("/model 2")
    assert refused.value.detail == "Chat not found"
    assert ctx.session.endpoint_id == "local"
    assert ctx.screen.status == {}


# --- /settings --------------------------------------------------------------


def scope_rows(ctx: Context, area: int) -> dict[str, tuple[str, str]]:
    """Opens ``/settings`` and then the scope at ``area``: each setting
    shown with its origin and its value, by name."""
    ctx.asker = Walking(area)
    ctx.commands.run("/settings")
    rows = ctx.asker.rows()
    return {
        row[0]: (row[1], note) for row, note in zip(rows, ctx.asker.remarks(), strict=True)
    }


def test_settings_offer_the_three_scopes_and_the_storage_locations(ctx, service):
    ctx.asker = Walking()
    ctx.commands.run("/settings")
    assert ctx.asker.rows() == [["global"], ["model"], ["chat"], [Texts("en").t("cli.storage_title")]]
    assert service.asked("GET", "/settings/resolved") == []


def test_the_chat_scope_shows_value_and_origin_for_the_open_chat_and_its_model(ctx, service):
    rows = scope_rows(ctx, 2)
    asked = service.asked("GET", "/settings/resolved")[0].url.params
    # No list of its own: which settings there are is the service's to say.
    assert "keys" not in asked
    assert (asked["chat"], asked["modell"]) == ("chat-1", "local")
    # The open chat's scope is named the way a line takes it.
    assert rows["parameter.temperature"] == ("chat", "0.7")
    assert rows["parameter.top_p"] == ("model", "0.9")
    assert rows["parameter.max_tokens"] == ("global", "4096")
    # Any other scope stands as the service names it.
    assert rows["parameter.top_k"] == ("modell:another", "40")
    # A value that is no set of values stands under the setting's own
    # name, with the scope the service names for it as a whole.
    assert rows["berechtigungsmodus_chat"] == ("global", "manuell")
    assert rows["verdichtung_schwelle"] == ("chat", "70")
    # A value of a set that no scope has set comes from the default; the
    # service names no scope for it, and the row says where it comes from.
    assert rows["scrollstelle.am_boden"] == ("default", "true")
    # A setting nothing is set for has no row.
    assert not any(name.startswith("werkzeuge_aus") for name in rows)


def test_the_global_scope_is_asked_without_the_chat_and_the_model(ctx, service):
    scope_rows(ctx, 0)
    asked = service.asked("GET", "/settings/resolved")[0].url.params
    assert "chat" not in asked and "modell" not in asked


def test_the_model_scope_is_asked_with_the_model_alone(ctx, service):
    scope_rows(ctx, 1)
    asked = service.asked("GET", "/settings/resolved")[0].url.params
    assert asked["modell"] == "local" and "chat" not in asked


def test_settings_stand_in_the_order_of_the_scopes_each_key_once(ctx, service):
    rows = scope_rows(ctx, 2)
    # What applies everywhere first, then the model's, then the chat's; what
    # the service names no scope for stands last.
    assert list(rows) == [
        "parameter.max_tokens",
        "berechtigungsmodus_chat",
        "parameter.top_p",
        "parameter.top_k",
        "parameter.temperature",
        "verdichtung_schwelle",
        "scrollstelle.am_boden",
    ]
    assert [origin for origin, _ in rows.values()] == [
        "global", "global", "model", "modell:another", "chat", "chat", "default"
    ]


def test_a_whole_value_no_scope_has_set_says_that_it_is_the_default(ctx, service, monkeypatch):
    monkeypatch.setitem(RESOLVED, "page_size", {"wert": 50, "herkunft": {}, "scope": None})
    assert scope_rows(ctx, 2)["page_size"] == ("default", "50")


def test_a_setting_the_client_has_never_heard_of_is_shown_as_the_service_names_it(
    ctx, service, monkeypatch
):
    """The client carries no list of settings: whatever the service
    answers with has a row."""
    monkeypatch.setitem(
        RESOLVED, "added_later", {"wert": "new", "herkunft": {}, "scope": "modell:local"}
    )
    assert scope_rows(ctx, 2)["added_later"] == ("model", "new")


def test_a_setting_picked_from_the_selection_is_asked_for_and_written_into_that_scope(ctx, service):
    # The chat scope, the fifth row: parameter.temperature.
    ctx.asker = Walking(2, 4, typed=["0.3"])
    ctx.commands.run("/settings")
    # The name stands over the input, as it stands in the row.
    assert ctx.asker.questions == [("parameter.temperature", None)]
    assert service.bodies("PATCH", "/settings/chat:chat-1/parameter") == [
        {"wert": {"temperature": 0.3}}
    ]
    assert ctx.screen.lines() == [f"chat:chat-1.parameter.temperature 0.7 {glyphs.glyph('arrow')} 0.3"]


def test_a_whole_value_picked_from_the_selection_is_put(ctx, service):
    # The global scope, the second row: berechtigungsmodus_chat.
    ctx.asker = Walking(0, 1, typed=["auto"])
    ctx.commands.run("/settings")
    assert service.bodies("PUT", "/settings/global/berechtigungsmodus_chat") == [{"wert": "auto"}]


@pytest.mark.parametrize("typed", [None, "", "   "])
def test_an_empty_answer_or_esc_writes_nothing(ctx, service, typed):
    ctx.asker = Walking(2, 4, typed=[typed])
    ctx.commands.run("/settings")
    assert not service.asked("PATCH", "/settings/chat:chat-1/parameter")
    assert ctx.screen.lines() == []


def test_set_sends_the_value_to_the_scope_and_shows_before_and_after(ctx, service):
    ctx.commands.run('/settings chat.parameter {"temperature": 0.3}')
    sent = service.asked("PUT", "/settings/chat:chat-1/parameter")
    assert [json.loads(request.content) for request in sent] == [{"wert": {"temperature": 0.3}}]
    assert not service.asked("PATCH", "/settings/chat:chat-1/parameter")
    # The whole value went: what the scope held before, and what it holds now.
    arrow = glyphs.glyph("arrow")
    assert ctx.screen.lines() == [
        f'chat:chat-1.parameter {{"temperature": 0.7, "top_p": 0.9}} {arrow} {{"temperature": 0.3}}'
    ]


def test_set_with_a_third_part_sets_that_field_alone(ctx, service):
    ctx.commands.run("/settings chat.parameter.temperature 0.3")
    assert service.bodies("PATCH", "/settings/chat:chat-1/parameter") == [
        {"wert": {"temperature": 0.3}}
    ]
    assert not service.asked("PUT", "/settings/chat:chat-1/parameter")
    # The rest of the set stays as it was.
    assert service.settings["chat:chat-1"]["parameter"] == {"temperature": 0.3, "top_p": 0.9}
    assert ctx.screen.lines() == [f"chat:chat-1.parameter.temperature 0.7 {glyphs.glyph('arrow')} 0.3"]


def test_set_of_a_field_the_scope_did_not_hold_shows_null_before(ctx, service):
    ctx.commands.run("/settings global.parameter.top_k 40")
    assert service.bodies("PATCH", "/settings/global/parameter") == [{"wert": {"top_k": 40}}]
    assert ctx.screen.lines() == [f"global.parameter.top_k null {glyphs.glyph('arrow')} 40"]


def test_set_of_a_field_of_a_value_that_is_no_set_is_refused_in_the_services_words(ctx, service):
    service.settings["global"] = {"sprache": "de"}
    with pytest.raises(ServiceError) as refused:
        ctx.commands.run("/settings global.sprache.code en")
    assert refused.value.detail == "Not a set of values"
    assert service.settings["global"] == {"sprache": "de"}


def test_set_names_this_models_scope_and_takes_a_bare_word_as_it_stands(ctx, service):
    ctx.commands.run("/settings model.sprache en")
    assert service.bodies("PUT", "/settings/modell:local/sprache") == [{"wert": "en"}]


def test_set_of_the_permission_mode_outside_the_global_scope_is_refused_in_the_services_words(
    ctx, service
):
    for scope in ("chat", "model"):
        with pytest.raises(ServiceError) as refused:
            ctx.commands.run(f"/settings {scope}.berechtigungsmodus_chat manuell")
        assert refused.value.detail == ONLY_GLOBAL
    assert "berechtigungsmodus_chat" not in service.settings.get("chat:chat-1", {})
    assert "berechtigungsmodus_chat" not in service.settings.get("modell:local", {})
    # In the global scope it is taken as it always was.
    ctx.commands.run("/settings global.berechtigungsmodus_chat manuell")
    assert service.settings["global"]["berechtigungsmodus_chat"] == "manuell"


def test_set_with_a_number_sends_a_number_and_null_takes_the_value_back(ctx, service):
    ctx.commands.run("/settings global.verdichtung_schwelle 70")
    ctx.commands.run("/settings global.verdichtung_schwelle null")
    assert service.bodies("PUT", "/settings/global/verdichtung_schwelle") == [
        {"wert": 70},
        {"wert": None},
    ]


def test_set_sends_whatever_scope_is_typed_and_the_refusal_is_the_services_own(ctx, service):
    with pytest.raises(ServiceError) as refused:
        ctx.commands.run("/settings parameter.temperature 0.3")
    # Refused where the scope is first read; nothing is written after that.
    assert service.asked("GET", "/settings/parameter/temperature")
    assert service.asked("PUT", "/settings/parameter/temperature") == []
    assert refused.value.detail == "The scope must be 'global', 'modell:<id>' or 'chat:<id>'"


def test_set_sends_a_word_json_cannot_carry_as_the_word_it_is(ctx, service):
    ctx.commands.run("/settings global.verdichtung_schwelle NaN")
    assert service.bodies("PUT", "/settings/global/verdichtung_schwelle") == [{"wert": "NaN"}]


def test_a_line_break_or_a_tab_parts_a_command_from_its_value_like_a_space(ctx, service):
    ctx.commands.run("/settings\nglobal.verdichtung_schwelle\t70")
    assert service.bodies("PUT", "/settings/global/verdichtung_schwelle") == [{"wert": 70}]


def test_a_refused_setting_stands_in_the_history_in_the_services_words(service, tmp_path):
    shown = played(
        [
            "/settings global.verdichtung_schwelle 500" + ENTER,
            lambda: service.asked("PUT", "/settings/global/verdichtung_schwelle"),
            "/quit" + ENTER,
        ],
        service,
        tmp_path,
    )
    assert '[{"loc": ["body", "wert"], "msg": "500 is out of range"}]' in shown


@pytest.mark.parametrize(
    "line",
    [
        "/settings global.parameter",
        "/settings parameter 0.3",
        "/settings .parameter 1",
        "/settings global.parameter.temperature",
        "/settings global.parameter..temperature 0.3",
        "/settings a.b.c.d 1",
    ],
)
def test_set_without_scope_key_or_value_sends_nothing_and_names_the_form(ctx, service, line):
    ctx.commands.run(line)
    assert service.seen == []
    assert ctx.renderer.errors == [Texts("en").t("cli.set_form")]


# --- /tools -----------------------------------------------------------------------


def test_tools_shows_what_is_offered_with_its_state_and_what_is_always_allowed(ctx, service):
    ctx.commands.run("/tools")
    assert service.paths() == [
        "GET /api/v1/tools",
        "GET /api/v1/permissions/always-allow",
        "GET /api/v1/settings/resolved",
    ]
    always = Texts("en").t("werkzeug.yes_dont_ask_again")
    active = Texts("en").t("status.aktiv")
    # The tool that is on file but not offered has no row: there is nothing
    # to switch.
    assert [row[1:] for row in ctx.asker.rows()] == [
        ["read_file", "files", "", active],
        ["run_command", "shell", always, active],
    ]
    assert ctx.asker.heads == [Texts("en").t("cli.tools_count", active=2, total=2)]


def test_tools_forget_takes_a_standing_permission_back(ctx, service):
    ctx.commands.run("/tools forget run_command")
    assert service.paths() == ["DELETE /api/v1/permissions/always-allow/run_command"]
    assert ctx.renderer.notices == [Texts("en").t("cli.tool_asks_again", name="run_command")]


def test_forgetting_a_permission_that_is_not_there_is_refused_in_the_services_words(ctx):
    with pytest.raises(ServiceError) as refused:
        ctx.commands.run("/tools forget read_file")
    assert refused.value.detail == "There is no such rule"
    assert ctx.renderer.notices == []


@pytest.mark.parametrize("line", ["/tools forget", "/tools on read_file", "/tools everything"])
def test_tools_with_a_word_it_does_not_know_sends_nothing_and_names_the_form(ctx, service, line):
    ctx.commands.run(line)
    assert service.seen == []
    assert ctx.renderer.errors == [Texts("en").t("cli.werkzeug_syntax")]


# --- /think -----------------------------------------------------------------------


def test_think_takes_the_stage_by_its_name_and_the_next_message_carries_it(service, tmp_path):
    ctx = context(service, tmp_path, language="de")
    ctx.commands.run("/think hoch")
    assert ctx.session.thinking == "high"
    chat.send(ctx, "Hallo")
    assert service.bodies("POST", "/chat/completions")[0]["thinking"] == "high"


def test_think_takes_the_stage_by_its_key_and_asks_nobody(ctx, service):
    ctx.commands.run("/think OFF")
    assert ctx.session.thinking == "off"
    # What is set here needs no asking, and no list follows it.
    assert service.seen == []
    assert ctx.asker.shown == [] and ctx.screen.text() == ""


def test_think_without_a_word_opens_a_selection_with_the_stage_the_service_keeps_in_use(
    ctx, service
):
    ctx.commands.run("/think")
    asked = service.asked("GET", "/settings/resolved/denken")[0].url.params
    assert (asked["chat"], asked["modell"]) == ("chat-1", "local")
    assert ctx.asker.rows() == [["off", "Off"], ["low", "Low"], ["high", "High"]]
    assert ctx.asker.in_use() == [2]
    # Nothing was picked: the stage stays the service's own.
    assert ctx.session.thinking is None


def test_a_stage_set_here_is_the_one_in_use_when_the_selection_opens_again(ctx, service):
    ctx.commands.run("/think low")
    ctx.commands.run("/think")
    assert ctx.asker.in_use() == [1]


def test_a_stage_picked_from_the_selection_is_the_one_the_next_message_carries(ctx, service):
    ctx.asker.pick = 0
    ctx.commands.run("/think")
    assert ctx.session.thinking == "off"
    chat.send(ctx, "Hello")
    assert service.bodies("POST", "/chat/completions")[0]["thinking"] == "off"


def test_think_with_a_stage_the_model_does_not_have_changes_nothing_and_says_so(ctx):
    ctx.commands.run("/think turbo")
    assert ctx.session.thinking is None
    assert ctx.renderer.errors == [Texts("en").t("cli.unknown_choice", name="turbo")]


@pytest.mark.parametrize("line", ["/think high", "/think"])
def test_a_model_that_never_thinks_says_so_and_takes_no_stage(ctx, service, line):
    """With a word or without one: there is nothing to set, so there is
    nothing to pick from either."""
    ctx.session.endpoint_id = "remote"
    ctx.commands.run(line)
    assert ctx.session.thinking is None
    assert ctx.renderer.notices == [Texts("en").t("denken.nie")]
    assert service.seen == [] and ctx.asker.shown == []


# --- /theme, /lang ----------------------------------------------------------------


def test_theme_switches_at_once_and_is_remembered(ctx, tmp_path, monkeypatch):
    terminal = Terminal()
    monkeypatch.setattr(sys, "stdout", terminal)
    ctx.commands.run("/theme pearl")
    assert themes.current().name == "pearl"
    # The terminal's ground follows the switch at once.
    assert terminal.getvalue() == themes.get("pearl").ground()
    assert ctx.screen.status == {"look": "pearl"}
    assert prefs.load(tmp_path / "cli.json")["look"] == "pearl"
    # Named by its word, the theme is switched to; no list follows.
    assert ctx.asker.shown == [] and ctx.screen.text() == ""


def test_theme_takes_a_name_and_its_words_however_they_are_typed(ctx, tmp_path, monkeypatch):
    switched: list[bool] = []
    monkeypatch.setattr(glyphs, "use_nerd", switched.append)
    ctx.commands.run("/theme PEARL")
    ctx.commands.run("/theme Nerd ON")
    assert themes.current().name == "pearl" and switched == [True]


def test_theme_without_a_word_opens_a_selection_with_the_theme_in_use(ctx, tmp_path):
    ctx.commands.run("/theme")
    names = list(themes.available())
    assert ctx.asker.rows() == [[name] for name in names]
    assert ctx.asker.in_use() == [names.index(themes.DEFAULT_LOOK)]
    # Nothing was picked: nothing is switched, and nothing is remembered.
    assert themes.current().name == themes.DEFAULT_LOOK
    assert ctx.screen.status == {}
    assert not (tmp_path / "cli.json").exists()


def test_a_theme_picked_from_the_selection_is_switched_to_as_its_name_would(ctx, tmp_path):
    ctx.asker.pick = list(themes.available()).index("pearl")
    ctx.commands.run("/theme")
    assert themes.current().name == "pearl"
    assert ctx.screen.status == {"look": "pearl"}
    assert prefs.load(tmp_path / "cli.json")["look"] == "pearl"
    assert ctx.screen.text() == ""


def test_the_entry_auto_says_in_a_remark_what_it_follows(ctx, monkeypatch):
    monkeypatch.setattr(themes, "available", lambda: ("auto", "exe", "pearl"))
    ctx.commands.run("/theme")
    remarks = {entry.cells[0][1]: entry.note for entry in ctx.asker.shown[-1]}
    assert remarks == {"auto": Texts("en").t("cli.theme_auto"), "exe": "", "pearl": ""}
    # A sentence of the catalogue, not a key left standing.
    assert remarks["auto"].startswith("Use exe for dark system appearance")


def test_where_no_theme_is_called_auto_no_entry_carries_a_remark(ctx, monkeypatch):
    """Silence probe: the remark belongs to that one entry."""
    monkeypatch.setattr(themes, "available", lambda: ("exe", "pearl"))
    ctx.commands.run("/theme")
    assert [entry.note for entry in ctx.asker.shown[-1]] == ["", ""]


def test_a_theme_that_does_not_exist_changes_nothing_and_says_so(ctx, tmp_path):
    ctx.commands.run("/theme neon")
    assert themes.current().name == themes.DEFAULT_LOOK
    assert ctx.renderer.errors == [Texts("en").t("cli.unknown_choice", name="neon")]
    assert ctx.asker.shown == []
    assert not (tmp_path / "cli.json").exists()


@pytest.mark.parametrize(
    ("language", "sentence"),
    [
        ("en", "Inside Exe AI, the theme follows the app's appearance. "
               "Change it under Settings › Appearance."),
        ("de", "In Exe AI richtet sich das Erscheinungsbild nach der App. "
               "Ändern unter Einstellungen › Erscheinungsbild."),
    ],
)
@pytest.mark.parametrize("typed", ["/theme", "/theme pearl"])
def test_in_the_windows_tab_theme_switches_nothing_and_says_where_it_is_set(
    service, tmp_path, monkeypatch, language, sentence, typed
):
    monkeypatch.setenv(themes.WINDOW_VARIABLE, "1")
    ctx = context(service, tmp_path, language)
    ctx.commands.run(typed)
    assert ctx.renderer.notices == [sentence]
    # Neither a selection nor a switch nor a remembered choice.
    assert ctx.asker.shown == []
    assert themes.current().name == themes.DEFAULT_LOOK
    assert ctx.screen.status == {}
    assert not (tmp_path / "cli.json").exists()


def test_the_nerd_signs_are_no_theme_and_switch_in_the_windows_tab_too(
    ctx, tmp_path, monkeypatch
):
    """Silence probe: only the choice of a theme is the app's."""
    monkeypatch.setenv(themes.WINDOW_VARIABLE, "1")
    switched: list[bool] = []
    monkeypatch.setattr(glyphs, "use_nerd", switched.append)
    ctx.commands.run("/theme nerd on")
    assert switched == [True]
    assert ctx.renderer.notices == []


def test_outside_the_windows_tab_theme_switches_as_before(ctx, tmp_path, monkeypatch):
    monkeypatch.delenv(themes.WINDOW_VARIABLE, raising=False)
    ctx.commands.run("/theme pearl")
    assert themes.current().name == "pearl"
    assert prefs.load(tmp_path / "cli.json")["look"] == "pearl"
    assert ctx.renderer.notices == []


def test_a_theme_that_cannot_be_remembered_still_holds_for_this_run(ctx, tmp_path):
    in_the_way = tmp_path / "a-file"
    in_the_way.write_text("x", encoding="utf-8")
    ctx.prefs_path = in_the_way / "cli.json"
    ctx.commands.run("/theme heaven")
    assert themes.current().name == "heaven"
    assert ctx.screen.status == {"look": "heaven"}
    assert len(ctx.renderer.errors) == 1 and "a-file" in ctx.renderer.errors[0]


def test_theme_nerd_switches_the_icon_font_signs_and_is_remembered(ctx, tmp_path, monkeypatch):
    switched: list[bool] = []
    monkeypatch.setattr(glyphs, "use_nerd", switched.append)
    ctx.commands.run("/theme nerd")
    # Off out of the box, and a selection nothing is picked from changes
    # nothing.
    assert ctx.asker.rows() == [["on"], ["off"]] and ctx.asker.in_use() == [1]
    assert switched == [] and not (tmp_path / "cli.json").exists()
    ctx.commands.run("/theme nerd on")
    assert switched == [True]
    assert prefs.load(tmp_path / "cli.json")["nerd"] is True
    ctx.commands.run("/theme nerd")
    assert ctx.asker.in_use() == [0]
    ctx.commands.run("/theme nerd off")
    assert switched == [True, False]
    assert prefs.load(tmp_path / "cli.json")["nerd"] is False
    # Neither word left a list behind.
    assert ctx.screen.text() == ""


def test_the_word_picked_behind_nerd_switches_the_signs_like_the_word_typed(
    ctx, tmp_path, monkeypatch
):
    switched = []
    monkeypatch.setattr(glyphs, "use_nerd", switched.append)
    ctx.asker.pick = 0
    ctx.commands.run("/theme nerd")
    assert switched == [True]
    assert prefs.load(tmp_path / "cli.json")["nerd"] is True


def test_theme_nerd_takes_the_two_words_of_the_other_language_as_well(ctx, tmp_path, monkeypatch):
    switched: list[bool] = []
    monkeypatch.setattr(glyphs, "use_nerd", switched.append)
    ctx.commands.run("/theme nerd an")
    assert prefs.load(tmp_path / "cli.json")["nerd"] is True
    # The selection names the two words it always names.
    ctx.commands.run("/theme nerd")
    assert ctx.asker.rows() == [["on"], ["off"]] and ctx.asker.in_use() == [0]
    ctx.commands.run("/theme nerd aus")
    assert switched == [True, False]
    assert prefs.load(tmp_path / "cli.json")["nerd"] is False


def test_theme_nerd_shows_what_the_start_read_from_the_remembered_choices(ctx, tmp_path):
    prefs.save({"nerd": True}, tmp_path / "cli.json")
    ctx.commands.run("/theme nerd")
    assert ctx.asker.in_use() == [0]


def test_theme_nerd_with_another_word_changes_nothing_and_says_so(ctx, tmp_path, monkeypatch):
    switched: list[bool] = []
    monkeypatch.setattr(glyphs, "use_nerd", switched.append)
    ctx.commands.run("/theme nerd maybe")
    assert ctx.renderer.errors == [Texts("en").t("cli.unknown_choice", name="maybe")]
    assert switched == [] and not (tmp_path / "cli.json").exists()
    assert ctx.asker.shown == []


def test_lang_without_a_word_opens_a_selection_with_the_language_in_use(ctx, tmp_path):
    ctx.commands.run("/lang")
    assert ctx.asker.rows() == [["de"], ["en"]] and ctx.asker.in_use() == [1]
    # Nothing was picked: the language stays, and nothing is remembered.
    assert ctx.texts.language == "en" and ctx.client.language == "en"
    assert not (tmp_path / "cli.json").exists()


def test_a_language_picked_from_the_selection_is_switched_to_as_its_code_would(ctx, tmp_path):
    ctx.asker.pick = 0
    ctx.commands.run("/lang")
    assert ctx.texts.language == "de" and ctx.client.language == "de"
    assert prefs.load(tmp_path / "cli.json")["language"] == "de"
    assert ctx.screen.text() == ""


def test_lang_switches_the_clients_sentences_and_the_services_and_is_remembered(
    ctx, service, tmp_path
):
    ctx.commands.run("/lang DE")
    assert ctx.texts.language == "de"
    assert prefs.load(tmp_path / "cli.json")["language"] == "de"
    # No list follows the switch.
    assert ctx.asker.shown == [] and ctx.screen.text() == ""
    # From now on the service is asked for its sentences in that language.
    ctx.commands.run("/tools")
    assert {request.headers[LANGUAGE_HEADER] for request in service.seen} == {"de"}
    assert Texts("de").t("cli.tools_count", active=2, total=2) in ctx.asker.heads


def test_a_language_without_a_catalogue_changes_nothing_and_says_so(ctx, tmp_path):
    ctx.commands.run("/lang xx")
    assert ctx.texts.language == "en"
    assert ctx.client.language == "en"
    assert ctx.renderer.errors == [Texts("en").t("cli.unknown_choice", name="xx")]
    assert not (tmp_path / "cli.json").exists()


def test_a_choice_that_cannot_be_written_holds_for_this_run_and_is_said(ctx, tmp_path):
    in_the_way = tmp_path / "a-file"
    in_the_way.write_text("x", encoding="utf-8")
    ctx.prefs_path = in_the_way / "cli.json"
    ctx.commands.run("/lang de")
    assert ctx.texts.language == "de"
    assert len(ctx.renderer.errors) == 1 and "a-file" in ctx.renderer.errors[0]


# --- /export ----------------------------------------------------------------------


class Moment:
    """A clock that stands still, so two pages asked for in a row are asked
    for in the same second."""

    @staticmethod
    def now() -> datetime:
        return datetime(2026, 10, 11, 18, 30, 45)


def test_export_without_a_name_goes_to_the_clients_own_folder_in_the_home_folder(
    ctx, tmp_path, monkeypatch
):
    # The home folder is bent aside: the real one is never written to.
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(commands, "datetime", Moment)
    ctx.prefs_path = None
    page = commands._saved_page(ctx)
    assert page == (
        tmp_path / "home" / ".exe-ai" / commands.SAVED_FOLDER / "exe_conversation_20261011_183045.html"
    )


def test_a_second_export_in_the_same_moment_is_a_second_file(ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "datetime", Moment)
    ctx.prefs_path = tmp_path / "cli.json"
    first = commands._saved_page(ctx)
    assert first == tmp_path / commands.SAVED_FOLDER / "exe_conversation_20261011_183045.html"
    first.parent.mkdir(parents=True)
    first.write_text("x", encoding="utf-8")
    assert commands._saved_page(ctx) == first.with_name("exe_conversation_20261011_183045-2.html")


# --- /stop ------------------------------------------------------------------------


def test_stop_ends_the_running_answer_of_the_open_chat(ctx, service):
    ctx.session.answering = True
    ctx.commands.run("/stop")
    assert service.bodies("POST", "/chat/stop") == [{"chat_id": "chat-1"}]


def test_stop_without_a_running_answer_sends_nothing(ctx, service):
    ctx.commands.run("/stop")
    assert service.seen == []
    assert ctx.renderer.errors == [] and ctx.renderer.notices == []
