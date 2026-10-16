"""A stand-in for the service, for tests of the terminal client: the same
addresses, the same streams and the same key check — with a script where
the service has a model.

It is no part of the service and imports nothing of it. What it knows of
the API it says in its own words, so a client that works against the
stand-in and fails against the service shows where the two drifted apart.

The client is synchronous and keeps a stream open for as long as it runs.
Neither ready-made way to reach an app without a port can serve that: both
hand an answer over only once the app has finished it, and an endless
stream never finishes. So the stand-in is reached through a transport of
its own. The app runs on an event loop in a background thread, and every
piece of an answer is handed over the moment the app sends it.
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
import queue
import threading
import time
from collections.abc import Callable, Coroutine, Iterator
from concurrent.futures import Future
from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from cli import service as client_side

KEY_HEADER = "X-Sitzungsschluessel"
KEY_PARAMETER = "schluessel"
EVENT_PATH = "/api/v1/events/stream"

# What the stand-in says to a request without this run's key.
KEY_REFUSAL = "Invalid or missing session key"

# What stands in place of a tool's result after the user said no.
DECLINED = "The user declined this call."

# How long a helper waits for something that should happen at once. A test
# then fails on what it asserts instead of hanging.
PATIENCE_SECONDS = 10.0

# The comment that keeps a silent stream warm.
HEARTBEAT = ": still here\n\n"


# What the client asks for by itself, in the background, for as long as it
# runs — the listener's thread (cli/events.py) asks for the model list on
# every arrival and holds the event stream. How often it got to ask depends
# on how long a test took, so a stand-in that counts requests marks the
# listener's and leaves them out.
LISTENER_THREAD = "cli-events"
LISTENER = "listener"


def noted(request: httpx.Request) -> httpx.Request:
    """The request, marked when the listener's thread made it."""
    if threading.current_thread().name == LISTENER_THREAD:
        request.extensions[LISTENER] = True
    return request


def foreground(request: httpx.Request) -> bool:
    """Whether the client itself made the request, not its listener."""
    return not request.extensions.get(LISTENER)


def eventually(check: Callable[[], Any], *, timeout: float = PATIENCE_SECONDS) -> Any:
    """Waits until ``check`` answers with something true and returns it.

    The client works in threads of its own, so what a test set in motion is
    not there the moment the call returns."""
    deadline = time.monotonic() + timeout
    while True:
        found = check()
        if found:
            return found
        if time.monotonic() >= deadline:
            raise AssertionError(f"never happened within {timeout} s: {check!r}")
        time.sleep(0.005)


# --- Which process a stand-in says it is -------------------------------------------

# The names under which a stand-in is asked as the service of the machine
# the test runs on. Asked under any other, it stands for a service elsewhere.
THIS_MACHINE = frozenset({"127.0.0.1", "localhost", "::1"})

# How much earlier than the test's own the process of a service elsewhere
# began: an hour, far beyond the seconds two readings of a process list may
# lie apart.
ANOTHER_BEGINNING_SECONDS = 3600.0


@functools.cache
def _began_here() -> float:
    """When the process the test runs in began, as the system's process list
    tells it — read through the client, which is who checks it. That a
    service reads its own beginning to the same second is a test of the
    service."""
    began = client_side.began(os.getpid())
    assert began is not None, "the system does not say when this process began"
    return began


def this_process() -> dict[str, Any]:
    """The process the test runs in, the way a service names its own: the
    number the system gave it, and when it began."""
    return {"pid": os.getpid(), "began": _began_here()}


def a_process_elsewhere() -> dict[str, Any]:
    """The process of a service on another machine — the one hardest to
    tell from a process here: it has the number of one that runs on this
    machine, the test's own, and only began at another time."""
    return {"pid": os.getpid(), "began": _began_here() - ANOTHER_BEGINNING_SECONDS}


def process_by_name(host: str) -> dict[str, Any] | None:
    """What a stand-in says of its process where a test asked for nothing
    else. A stand-in runs in the test's process whatever name it is reached
    under; the name stands for where the service is meant to run. Under a
    name of this machine it is this machine's service and names the process
    it really runs in; under any other it is a service elsewhere."""
    return this_process() if host in THIS_MACHINE else a_process_elsewhere()


# --- Reaching an app without a port ----------------------------------------------


class LoopThread:
    """An event loop that runs in a thread of its own until it is closed."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.closed = False
        self._thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self._thread.start()

    def submit(self, work: Coroutine[Any, Any, Any]) -> Future[Any]:
        """Starts ``work`` on the loop and returns at once."""
        return asyncio.run_coroutine_threadsafe(work, self.loop)

    def call(self, function: Callable[[], Any]) -> Any:
        """Runs ``function`` on the loop and waits for what it returns."""

        async def run() -> Any:
            return function()

        return self.submit(run()).result(PATIENCE_SECONDS)

    def close(self) -> None:
        """Ends everything that still runs on the loop, then the loop."""
        if self.closed:
            return
        self.closed = True

        async def cancel_everything() -> None:
            running = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            for task in running:
                task.cancel()
            await asyncio.gather(*running, return_exceptions=True)

        self.submit(cancel_everything()).result(PATIENCE_SECONDS)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(PATIENCE_SECONDS)
        self.loop.close()


class _Call:
    """One request on its way through the app, and the pieces of its answer
    as they come back."""

    def __init__(self, app: Any, request: httpx.Request, loop: LoopThread) -> None:
        self._app = app
        self._request = request
        self._loop = loop
        self._body = request.read()
        # ("start", (status, headers)), ("body", bytes), ("failed", error)
        # and ("end", None), in the order the app produced them.
        self.pieces: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._hung_up: asyncio.Event | None = None

    def _scope(self) -> dict[str, Any]:
        url = self._request.url
        return {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": self._request.method,
            "scheme": url.scheme,
            "path": url.path,
            "raw_path": url.raw_path.split(b"?")[0],
            "query_string": url.query,
            "root_path": "",
            "headers": [(name.lower(), value) for name, value in self._request.headers.raw],
            "server": (url.host, url.port or 80),
            "client": ("127.0.0.1", 0),
        }

    async def serve(self) -> None:
        self._hung_up = asyncio.Event()
        hung_up = self._hung_up
        handed_over = False

        async def receive() -> dict[str, Any]:
            nonlocal handed_over
            if not handed_over:
                handed_over = True
                return {"type": "http.request", "body": self._body, "more_body": False}
            # Nothing more comes from the client until it hangs up.
            await hung_up.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                self.pieces.put(("start", (message["status"], message.get("headers", []))))
            elif message["type"] == "http.response.body":
                if message.get("body"):
                    self.pieces.put(("body", message["body"]))
                if not message.get("more_body", False):
                    self.pieces.put(("end", None))

        try:
            await self._app(self._scope(), receive, send)
        except Exception as error:  # noqa: BLE001
            self.pieces.put(("failed", error))
        finally:
            # Also where the app was cut off: whoever reads must not wait
            # for a piece that will never come.
            self.pieces.put(("end", None))

    def hang_up(self) -> None:
        """The client closed the answer; the app is told, as a server would
        tell it."""
        hung_up = self._hung_up
        if hung_up is not None and not self._loop.closed:
            self._loop.loop.call_soon_threadsafe(hung_up.set)


class _Pieces(httpx.SyncByteStream):
    """The body of an answer, piece by piece as the app sends it."""

    def __init__(self, call: _Call, request: httpx.Request, patience: float | None) -> None:
        self._call = call
        self._request = request
        self._patience = patience

    def take(self) -> tuple[str, Any]:
        """The next piece. Waiting longer for it than the request's own
        read timeout allows fails the way a silent connection fails."""
        try:
            return self._call.pieces.get(timeout=self._patience)
        except queue.Empty:
            raise httpx.ReadTimeout("no piece arrived in time", request=self._request) from None

    def __iter__(self) -> Iterator[bytes]:
        while True:
            kind, piece = self.take()
            if kind == "body":
                yield piece
            elif kind == "failed":
                raise httpx.ReadError(str(piece), request=self._request)
            elif kind == "end":
                return

    def close(self) -> None:
        self._call.hang_up()


class AppTransport(httpx.BaseTransport):
    """Hands every request to an app running on ``loop`` and returns its
    answer as a stream that grows while the app is still sending."""

    def __init__(self, app: Any, loop: LoopThread) -> None:
        self._app = app
        self._loop = loop

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self._loop.closed:
            # A stand-in that was closed is a service that is gone.
            raise httpx.ConnectError("nothing answers here any more", request=request)
        call = _Call(self._app, request, self._loop)
        timeouts = request.extensions.get("timeout") or {}
        pieces = _Pieces(call, request, timeouts.get("read"))
        self._loop.submit(call.serve())
        kind, piece = pieces.take()
        if kind != "start":
            raise httpx.ReadError(f"the app sent no answer: {piece!r}", request=request)
        status, headers = piece
        return httpx.Response(status, headers=headers, stream=pieces, request=request)


# --- The events of an answer, as the service shapes them -------------------------


def content(text: str) -> dict[str, Any]:
    return {"typ": "content", "text": text}


def reasoning(text: str) -> dict[str, Any]:
    return {"typ": "reasoning", "text": text}


def tool_confirm(
    name: str, arguments: dict[str, Any], call_id: str, *, reason: str = ""
) -> dict[str, Any]:
    """A tool waits for permission; the answer stands still until the
    client has sent its decision."""
    return {
        "typ": "tool_confirm",
        "name": name,
        "argumente": arguments,
        "grund": reason,
        "grund_wert": "",
        "aufruf_id": call_id,
    }


def tool_call(
    name: str, arguments: dict[str, Any], call_id: str, *, server: str = ""
) -> dict[str, Any]:
    return {
        "typ": "tool_call",
        "name": name,
        "server": server,
        "argumente": arguments,
        "aufruf_id": call_id,
    }


def tool_result(
    name: str, call_id: str, text: str, *, failed: bool = False, seconds: float = 0.0
) -> dict[str, Any]:
    return {
        "typ": "tool_result",
        "name": name,
        "aufruf_id": call_id,
        "fehlgeschlagen": failed,
        "text": text,
        "bild": None,
        "dauer_sekunden": seconds,
    }


def context(tokens: int) -> dict[str, Any]:
    return {"typ": "kontext", "gesamt_tokens": tokens}


def stats(**numbers: Any) -> dict[str, Any]:
    return {"typ": "stats", "daten": numbers}


def done(**fields: Any) -> dict[str, Any]:
    return {"typ": "done", "abgebrochen": False, "zustand": "fertig", **fields}


def model(
    endpoint: str = "local",
    name: str = "Local Model",
    *,
    window: int | None = 131072,
    server_state: str = "idle",
) -> dict[str, Any]:
    """One entry of the model list."""
    return {
        "id": endpoint,
        "name": name,
        # The name is one the server reports, not the configuration's.
        "name_gemeldet": True,
        "anbieter": "",
        "anbieter_name": "",
        "provider": "openai_compatible",
        "reasoning_format": "none",
        "erreichbar": True,
        # The word for the server behind this model, as the service says it.
        "server_state": server_state,
        "zuletzt_geprueft": None,
        "context_tokens": window,
        "capabilities": {},
        "group": "local",
    }


def _data(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


class _Run:
    """One answer the stand-in produces: every event so far, kept, so a
    client that lost its connection can read on from where it stopped."""

    def __init__(self, run_id: str, chat_id: str, message_id: str) -> None:
        self.id = run_id
        self.chat_id = chat_id
        self.message_id = message_id
        self.events: list[dict[str, Any]] = []
        self.over = False
        self.stopped = False
        self.changed = asyncio.Condition()
        # The decision each waiting call is standing on, by the call's id.
        self.waiting: dict[str, asyncio.Future[dict[str, Any]]] = {}


class StubServer:
    """One of the servers that start from a file of their folder: how it
    stands, what it was started with, and its log."""

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.files: list[dict[str, Any]] = []
        self.running = False
        self.model: str | None = None
        self.port = 8101
        self.memory: float | None = 1.5
        self.log: list[str] = []
        # The files it was started with, and how often it was stopped.
        self.starts: list[str] = []
        self.stops = 0
        # False answers a start with the refusal for a missing program.
        self.program = True

    def state(self) -> dict[str, Any]:
        return {
            "laeuft": self.running,
            # A stopped server may still name the model it had.
            "modell": self.model,
            "modelle": list(self.files),
            "port": self.port,
            "belegt_gb": self.memory,
        }

    def start(self, file: str) -> dict[str, Any]:
        if self.running:
            raise HTTPException(409, "The server is already running.")
        if not self.program:
            raise HTTPException(412, "The program is not installed.")
        if file not in [entry["name"] for entry in self.files]:
            raise HTTPException(404, "No such model file.")
        self.starts.append(file)
        self.running = True
        self.model = file
        return self.state()

    def stop(self) -> None:
        self.stops += 1
        self.running = False


class StubImageServer:
    """The image server: a state word, the model it carries, its folder."""

    def __init__(self) -> None:
        self.files: list[dict[str, Any]] = []
        self.word = "aus"
        self.model: str | None = None
        self.log: list[str] = []
        self.starts: list[str] = []
        self.stops = 0
        # The program: whether it is there, the builds a machine can
        # choose from (``{"variante", "groesse"}``) and which one is
        # installed, the answer of the check for a newer one, the steps of
        # a fetch (the last repeats; ``None`` is an empty state) and the
        # bodies of the fetches.
        self.program = True
        self.builds: list[dict[str, Any]] = []
        self.installed: str | None = None
        self.update: dict[str, Any] = {"verfuegbar": False, "aktuell": False}
        self.program_steps: list[dict[str, Any] | None] = [
            {"geladen": 1, "gesamt": 1, "anteil": 1.0, "fertig": True, "fehler": None}
        ]
        self.program_posts: list[Any] = []
        # A picture from one sentence: the bodies asked for, how long the
        # request is held (seconds, ended early by a stop), the steps of its
        # progress (the last repeats), what stops were asked for, and the
        # sentence a refusal says.
        self.draws: list[dict[str, Any]] = []
        self.draw_seconds = 0.0
        self.progress_steps: list[dict[str, Any]] = [{"laeuft": False}]
        self.draw_stops = 0
        self.refuse_draw = ""

    def state(self) -> dict[str, Any]:
        return {
            "zustand": self.word,
            "modell": self.model,
            "programm_da": self.program,
            "picture_running": False,
        }

    def program_step(self) -> dict[str, Any] | None:
        """The next answer of a fetch of the program; once it is over the
        program is there."""
        step = self.program_steps[0]
        if len(self.program_steps) > 1:
            self.program_steps.pop(0)
        if step and step.get("fertig"):
            self.program = True
            if self.builds and self.program_posts and isinstance(self.program_posts[-1], dict):
                chosen = self.program_posts[-1].get("variante")
                if chosen:
                    self.installed = chosen
        return step

    def start(self, file: str) -> dict[str, Any]:
        if not self.program:
            raise HTTPException(412, "The image program is not installed.")
        if file not in [entry["name"] for entry in self.files]:
            raise HTTPException(404, "No such model file.")
        self.starts.append(file)
        self.word = "bereit"
        self.model = file
        return self.state()

    def stop(self) -> dict[str, Any]:
        self.stops += 1
        self.word = "aus"
        return self.state()


class StubService:
    """The stand-in: its state, its app and the handles a test moves it by.

    Everything the app does runs on the stand-in's own loop. The handles —
    ``announce``, ``heartbeat``, ``break_events`` — may be called from the
    test's thread.
    """

    def __init__(self, *, key: str = "key-of-this-run") -> None:
        self.key = key
        # The key the served page carries. A test sets another one to stand
        # for a page that is older than the service behind it.
        self.page_key: str | None = key
        self.version = "9.8.7"
        self.models: list[dict[str, Any]] = [model()]
        self.model_server_running = False
        # The model server: the files its folder holds as ``{"name",
        # "groesse_gb"}``, the file it carries while it runs, and whether it
        # answers yet. ``runner_loads`` is how many times the list is read
        # before a started model is connected; ``runner_dies`` ends the
        # process at that moment instead; ``runner_server_state`` is the
        # word the list gives for it.
        self.runner_files: list[dict[str, Any]] = []
        self.runner_model: str | None = None
        self.runner_connected = False
        self.runner_loads = 0
        self.runner_dies = False
        self.runner_server_state = "idle"
        self.runner_log: list[str] = []
        self.runner_starts: list[str] = []
        # False answers a start with the refusal for a missing program;
        # ``program_steps`` are the answers of the fetch, one per call, and
        # the last is repeated. A step with ``fertig`` makes it present.
        self.runner_program = True
        self.program_steps: list[dict[str, Any]] = [{"anteil": 1.0, "fertig": True, "fehler": None}]
        # What the model server says of its port and memory while it runs,
        # whether a check for a newer program is offered, and what the
        # check answers; ``program_posts`` are the bodies of the fetches.
        self.runner_port = 8080
        self.runner_memory = 2.4
        self.runner_updatable = False
        self.program_update: dict[str, Any] = {"verfuegbar": False, "aktuell": False}
        self.program_posts: list[Any] = []
        # The search: what it lists and the parameters it was asked with;
        # the file list of any repository; the fetch — the states the
        # service reports one after the other (the last is repeated), the
        # bodies it was started with, a refusal to start with, and how often
        # it was cancelled; the token and what was sent for it.
        self.search_hits: list[dict[str, Any]] = []
        self.searches: list[dict[str, str]] = []
        self.repository_listing: dict[str, Any] = {"dateien": [], "mmproj": None}
        self.file_requests: list[dict[str, str]] = []
        self.download_steps: list[dict[str, Any]] = []
        self.download_posts: list[dict[str, Any]] = []
        self.download_refusal: tuple[int, str] | None = None
        self.download_cancelled = False
        self.download_deletes = 0
        self.token: str | None = None
        self.token_posts: list[dict[str, Any]] = []
        self.token_deletes = 0
        # The cloud providers: what each request was sent with, as
        # ``(route, body)``, and whether a provider that is added answers.
        self.provider_requests: list[tuple[str, Any]] = []
        self.provider_reachable = True
        # The two long texts the service keeps, and every write to them as
        # ``(route, text)``; ``refuse_writes`` makes the service say no.
        self.long_texts: dict[str, str] = {"/memory": "", "/system-prompt": ""}
        self.text_writes: list[tuple[str, str]] = []
        self.refuse_writes = False
        # What ``/meta`` says of the system: the name it suggests.
        self.system_name = ""
        # The four other servers that start from a file of a folder, by
        # the path of their routes, and the image server.
        self.servers: dict[str, StubServer] = {
            prefix: StubServer(prefix)
            for prefix in (
                "/agentenmodell", "/einbettungsserver", "/sprachserver", "/bereinigungsserver"
            )
        }
        self.image = StubImageServer()
        # What the system says of its memory; ``None`` says nothing.
        self.memory: dict[str, Any] = {"belegt_gb": 25.2, "gesamt_gb": 64.0, "anteil": 0.39}
        self.chats: dict[str, dict[str, Any]] = {}
        self.messages: dict[str, list[dict[str, Any]]] = {}
        self.tools: list[dict[str, Any]] = []
        self.always_allowed: dict[str, str] = {}
        # Scope ("global", "modell:<id>", "chat:<id>") → key → value.
        self.settings: dict[str, dict[str, Any]] = {}
        # What the next answer streams, after its first event and before
        # nothing: a script names its own last event.
        self.script: list[dict[str, Any]] = [content("Hello.\n"), done()]
        # While true, the event stream is refused.
        self.events_refused = False
        # What the stand-in says of its process, by the name it is asked
        # under. A test puts another answer here.
        self.process: Callable[[str], dict[str, Any] | None] = process_by_name
        # Read now and kept, not at the first ``health``: a test that
        # replaces the client's clock by then would make the process list's
        # answer fail, and the first look at the service with it.
        _began_here()

        # What the client did, for a test to look at.
        self.requests: list[str] = []
        # Every change of a chat, as it was asked for: the chat, then the
        # fields sent.
        self.changes: list[dict[str, Any]] = []
        # What was uploaded for a message, as ``(route, name, kind, bytes)``,
        # and the sentence a route refuses with ("" lets it through).
        self.uploads: list[tuple[str, str, str, bytes]] = []
        self.refuse_upload: dict[str, tuple[int, str]] = {}
        # The agents and the tasks they were given, and what was done to
        # them as ``(what, task id, body)``.
        self.agents: list[dict[str, Any]] = [
            {"name": "researcher", "description": "Reads and sums up."},
            {"name": "writer", "description": "Writes texts."},
        ]
        # The sentences of agent files that are broken, the instruction of
        # each agent, what was done to the files as ``(what, name, body)``,
        # the sentence a save is refused with ("" lets it through) and the
        # answer for the model a run would take.
        self.broken_agents: dict[str, str] = {}
        self.agent_prompts: dict[str, str] = {}
        self.agent_actions: list[tuple[str, str, Any]] = []
        self.refuse_agent = ""
        self.run_model: dict[str, Any] = {"endpoint_id": "local", "name": "Local Model", "denklaenge": None}
        self.run_model_asked: list[dict[str, str]] = []
        # What the list of chats was asked with, the chats that were
        # deleted, and the sentence a deletion is refused with.
        self.chat_listings: list[dict[str, Any]] = []
        # The commands of a chat by its id, the chats whose commands were
        # asked for, and the commands that were stopped as ``(chat, number)``.
        self.runs: dict[str, list[dict[str, Any]]] = {}
        self.run_listings: list[str] = []
        self.run_stops: list[tuple[str, int]] = []
        # The projects, what was done to them as ``(what, project id, body)``,
        # and the sentence a deletion is refused with ("" lets it through).
        self.projects: dict[str, dict[str, Any]] = {}
        self.project_actions: list[tuple[str, str, Any]] = []
        self.refuse_project_delete = ""
        self.chat_deletions: list[str] = []
        self.refuse_chat_delete = ""
        self.jobs: dict[str, dict[str, Any]] = {}
        self.job_steps: dict[str, list[dict[str, Any]]] = {}
        self.job_actions: list[tuple[str, str, Any]] = []
        # The scheduled tasks, their runs, and what was done to them as
        # ``(what, cronjob id, body)``.
        self.cronjobs: dict[str, dict[str, Any]] = {}
        self.cronjob_runs: list[dict[str, Any]] = []
        self.cronjob_actions: list[tuple[str, str, Any]] = []
        self.cronjob_notice: str | None = None
        # The folders of chats that are gone from the disk, and the sentence
        # the service gives a path it refuses ("" lets every path pass).
        self.missing_folders: list[str] = []
        self.refuse_folder = ""
        # The files of the doc folder (each with its ``chat_id``) and the
        # folder of a chat by its id; a chat with no folder answers 404.
        self.doc_files: list[dict[str, Any]] = []
        self.doc_places: dict[str, str] = {}
        # The storage locations the service lists, the paths they were set
        # to as ``(name, body)``, and the sentence a path is refused with.
        self.places: list[dict[str, Any]] = []
        self.place_actions: list[tuple[str, Any]] = []
        self.refuse_place = ""
        # The skills by name (``beschreibung``, ``auto``, ``eigen``,
        # ``mitgeliefert``, ``inhalt``), what was done to them as ``(what,
        # name, body)``, and the sentence a write is refused with.
        self.skill_files: dict[str, dict[str, Any]] = {}
        self.skill_actions: list[tuple[str, str, Any]] = []
        self.refuse_skill = ""
        # The MCP servers by name, what was done to them as ``(what, name,
        # body)``, what the probe of an address answers (by address; an
        # address left out needs nothing), the tools an entered server
        # offers, whether it answers once entered, and what a sign-in
        # opens and was asked with.
        self.mcp_servers: dict[str, dict[str, Any]] = {}
        self.mcp_actions: list[tuple[str, str, Any]] = []
        self.mcp_probes: dict[str, dict[str, Any]] = {}
        self.mcp_tool_names: list[str] = ["search", "fetch"]
        self.mcp_connects = True
        self.mcp_sign_in_url = "https://auth.example.test/authorize"
        self.refuse_mcp = ""
        self.sent: list[dict[str, Any]] = []
        self.confirmations: list[dict[str, Any]] = []
        self.stops: list[dict[str, Any]] = []

        self._runs: dict[str, _Run] = {}
        # Answers that are still being produced, held so none is collected
        # before it is over.
        self._producing: set[asyncio.Task[None]] = set()
        self._watchers: set[asyncio.Queue[str | None]] = set()
        self._numbers: dict[str, int] = {}
        self._loop = LoopThread()
        self._app = self._build()

    # --- For the test ------------------------------------------------------------

    def http(self) -> httpx.Client:
        """A client whose every request ends in this stand-in."""
        return httpx.Client(transport=AppTransport(self, self._loop))

    def close(self) -> None:
        self._loop.close()

    @property
    def watchers(self) -> int:
        """How many clients have the event stream open right now."""
        return len(self._watchers)

    def announce(self, kind: str, **fields: Any) -> None:
        """Sends one event to everyone on the event stream."""
        self._to_watchers(_data({"typ": kind, **fields}))

    def heartbeat(self) -> None:
        self._to_watchers(HEARTBEAT)

    def break_events(self) -> None:
        """Ends every open event stream, as a service going down does."""
        self._to_watchers(None)

    def _to_watchers(self, piece: str | None) -> None:
        def hand_out() -> None:
            for watcher in list(self._watchers):
                watcher.put_nowait(piece)

        self._loop.call(hand_out)

    def waiting_calls(self) -> list[str]:
        """The calls whose answer is standing still for a decision."""
        return [call for run in list(self._runs.values()) for call in list(run.waiting)]

    def running(self) -> int:
        """How many answers are not over yet."""
        return sum(1 for run in list(self._runs.values()) if not run.over)

    # --- The app -----------------------------------------------------------------

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            self.requests.append(f"{scope['method']} {scope['path']}")
        await self._app(scope, receive, send)

    def _next(self, kind: str) -> str:
        self._numbers[kind] = self._numbers.get(kind, 0) + 1
        return f"{kind}-{self._numbers[kind]}"

    async def _check_key(self, request: Request) -> None:
        """The service's own rule: the key as a header — and on the event
        stream, which a browser can only open without headers, as a query
        parameter too."""
        sent = request.headers.get(KEY_HEADER)
        if not sent and request.method == "GET" and request.url.path == EVENT_PATH:
            sent = request.query_params.get(KEY_PARAMETER)
        if sent != self.key:
            raise HTTPException(401, KEY_REFUSAL)

    def _program_step(self, *, fetched_newest: bool = False) -> dict[str, Any]:
        """The next answer of a program fetch; the last repeats. A fetch of
        the newest build that is over leaves the program up to date."""
        step = self.program_steps[0]
        if len(self.program_steps) > 1:
            self.program_steps.pop(0)
        if step.get("fertig"):
            self.runner_program = True
            if fetched_newest:
                self.program_update = {"verfuegbar": False, "aktuell": True}
        return step

    @staticmethod
    def _serve(api: APIRouter, prefix: str, server: StubServer) -> None:
        """The four routes the file-started servers share."""

        @api.get(prefix)
        async def state() -> dict[str, Any]:
            return server.state()

        @api.get(f"{prefix}/log")
        async def log() -> list[str]:
            return list(server.log)

        @api.post(f"{prefix}/start")
        async def start(wanted: dict[str, Any] = Body(default={})) -> dict[str, Any]:
            return server.start(str(wanted.get("modell") or ""))

        @api.post(f"{prefix}/stop")
        async def stop() -> dict[str, Any]:
            server.stop()
            return server.state()

    def _runner_models(self) -> list[dict[str, Any]]:
        """The model server's entry in the list, once its model answers."""
        if not self.model_server_running or self.runner_model is None:
            return []
        if not self.runner_connected:
            if self.runner_loads > 0:
                self.runner_loads -= 1
            elif self.runner_dies:
                self.model_server_running = False
            else:
                self.runner_connected = True
        if not self.runner_connected:
            return []
        return [
            {
                **model(
                    f"runner:{self.runner_model}",
                    self.runner_model,
                    server_state=self.runner_server_state,
                ),
                "anbieter": "runner",
                "anbieter_name": "Model server",
            }
        ]

    def _chat(self, chat_id: str) -> dict[str, Any]:
        chat = self.chats.get(chat_id)
        if chat is None:
            raise HTTPException(404, "No such chat")
        return chat

    def _write_long_text(self, route: str, wanted: dict[str, Any]) -> dict[str, Any]:
        self.text_writes.append((route, str(wanted.get("text"))))
        if self.refuse_writes:
            raise HTTPException(500, "The text could not be written.")
        self.long_texts[route] = str(wanted.get("text"))
        return {"text": self.long_texts[route], "datei": "file.md"}

    def _build(self) -> FastAPI:
        app = FastAPI()
        api = APIRouter(prefix="/api/v1", dependencies=[Depends(self._check_key)])

        @app.get("/app/", response_class=HTMLResponse)
        async def page() -> str:
            carried = (
                ""
                if self.page_key is None
                else f"<script>window.__SITZUNGSSCHLUESSEL__={json.dumps(self.page_key)};</script>"
            )
            return f"<html><head>{carried}</head><body></body></html>"

        @api.get("/health")
        async def health(request: Request) -> dict[str, Any]:
            return {
                "status": "ok",
                "version": self.version,
                "process": self.process(request.url.hostname or ""),
            }

        @api.get("/models")
        async def models(alle: bool = False) -> list[dict[str, Any]]:
            listed = [entry for entry in self.models if alle or entry.get("erreichbar")]
            return [*listed, *self._runner_models()]

        @api.get("/runner")
        async def model_server() -> dict[str, Any]:
            return {
                "laeuft": self.model_server_running,
                "modell": self.runner_model if self.model_server_running else None,
                "modelle": list(self.runner_files),
                "port": self.runner_port,
                "belegt_gb": self.runner_memory if self.model_server_running else None,
                "updatable": self.runner_updatable,
                "flash_aktiv": None,
                "mtp_aktiv": None,
            }

        @api.post("/runner/start")
        async def start_model_server(wanted: dict[str, Any] = Body(default={})) -> dict[str, Any]:
            file = str(wanted.get("modell") or "")
            if self.model_server_running:
                raise HTTPException(409, "The model server is already running.")
            if not self.runner_program:
                raise HTTPException(412, "The model server program is not installed.")
            if file not in [entry["name"] for entry in self.runner_files]:
                raise HTTPException(404, "No such model file.")
            self.runner_starts.append(file)
            self.model_server_running = True
            self.runner_model = file
            self.runner_connected = False
            return await model_server()

        @api.post("/runner/stop")
        async def stop_model_server() -> dict[str, Any]:
            self.model_server_running = False
            self.runner_connected = False
            return await model_server()

        @api.get("/runner/log")
        async def model_server_log() -> list[str]:
            return list(self.runner_log)

        @api.get("/runner/programm/aktualisierung")
        async def model_server_update() -> dict[str, Any]:
            return dict(self.program_update)

        @api.get("/runner/programm")
        async def model_server_program_state() -> dict[str, Any]:
            return self._program_step()

        @api.post("/runner/programm")
        async def model_server_program(
            wanted: dict[str, Any] | None = Body(default=None),
        ) -> dict[str, Any]:
            self.program_posts.append(wanted)
            return self._program_step(fetched_newest=bool(wanted and wanted.get("aktualisieren")))

        @api.get("/system/speicher")
        async def memory_of_the_system() -> dict[str, Any]:
            return dict(self.memory)

        # --- Model search and the fetch of a file ---

        @api.get("/models/search")
        async def search_models(request: Request) -> list[dict[str, Any]]:
            self.searches.append(dict(request.query_params))
            return [dict(hit) for hit in self.search_hits]

        @api.get("/models/files")
        async def repository_files(request: Request) -> dict[str, Any]:
            self.file_requests.append(dict(request.query_params))
            return json.loads(json.dumps(self.repository_listing))

        @api.get("/runner/download")
        async def fetch_state() -> dict[str, Any] | None:
            if self.download_cancelled:
                return {
                    "datei": self.download_posts[-1]["datei"] if self.download_posts else "",
                    "geladen": 0, "gesamt": 0, "anteil": 0.0, "fertig": False,
                    "fehler": "abgebrochen",
                }
            if not self.download_steps:
                return None
            step = self.download_steps[0] if len(self.download_steps) == 1 else self.download_steps.pop(0)
            return dict(step)

        @api.post("/runner/download")
        async def start_fetch(wanted: dict[str, Any] = Body(default={})) -> dict[str, Any]:
            if self.download_refusal is not None:
                raise HTTPException(*self.download_refusal)
            self.download_posts.append(dict(wanted))
            self.download_cancelled = False
            return {
                "datei": wanted.get("ziel") or str(wanted.get("datei", "")).rsplit("/", 1)[-1],
                "geladen": 0, "gesamt": 0, "anteil": 0.0, "fertig": False, "fehler": None,
            }

        @api.delete("/runner/download")
        async def cancel_fetch() -> None:
            self.download_deletes += 1
            self.download_cancelled = True

        @api.post("/models/token")
        async def set_token(wanted: dict[str, Any] = Body(default={})) -> dict[str, Any]:
            self.token_posts.append(dict(wanted))
            token = str(wanted.get("token") or "")
            if len(token) < 8:
                # The service's own validation names the value it refused.
                raise HTTPException(422, [{"msg": "too short", "input": token}])
            self.token = token
            return {"gesetzt": True, "ende": token[-4:]}

        @api.delete("/models/token")
        async def remove_token() -> dict[str, Any]:
            self.token_deletes += 1
            self.token = None
            return {"gesetzt": False}

        # --- The other servers ---

        for prefix, server in self.servers.items():
            self._serve(api, prefix, server)

        @api.get("/bild/modelle")
        async def image_models() -> dict[str, Any]:
            image = self.image
            return {
                "modelle": [entry["name"] for entry in image.files],
                "sizes": {entry["name"]: int(entry["groesse_gb"] * 1e9) for entry in image.files},
                "programm_da": image.program,
            }

        @api.get("/bild/programm")
        async def image_program_state() -> dict[str, Any] | None:
            return self.image.program_step()

        @api.post("/bild/programm")
        async def image_program(wanted: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
            self.image.program_posts.append(wanted)
            step = self.image.program_step()
            return step or {"geladen": 0, "gesamt": 0, "anteil": 0.0, "fertig": False}

        @api.get("/bild/programm/varianten")
        async def image_program_builds() -> dict[str, Any]:
            return {"varianten": list(self.image.builds), "installiert": self.image.installed}

        @api.get("/bild/programm/aktualisierung")
        async def image_program_update() -> dict[str, Any]:
            return dict(self.image.update)

        @api.get("/bild/fortschritt")
        async def image_progress() -> dict[str, Any]:
            steps = self.image.progress_steps
            step = steps[0]
            if len(steps) > 1:
                steps.pop(0)
            return step

        @api.post("/bild/stop")
        async def image_stop_drawing() -> bool:
            self.image.draw_stops += 1
            return True

        @api.post("/bild/satz", status_code=201)
        async def image_from_sentence(wanted: dict[str, Any] = Body(default={})) -> dict[str, Any]:
            image = self.image
            image.draws.append(dict(wanted))
            if str(wanted.get("chat_id")) not in self.chats:
                raise HTTPException(404, "Chat not found")
            if image.refuse_draw:
                raise HTTPException(409, image.refuse_draw)
            if not image.program:
                raise HTTPException(409, "The image program is not installed.")
            waited = 0.0
            stops_before = image.draw_stops
            while waited < image.draw_seconds:
                if image.draw_stops > stops_before:
                    raise HTTPException(409, "The picture was stopped.")
                await asyncio.sleep(0.02)
                waited += 0.02
            return {
                "bild": "lighthouse.png",
                "pfad": "/data/images/lighthouse.png",
                "seed": 7,
                "modell": "draw.safetensors",
                "prompt": str(wanted.get("prompt")),
                "werte": {},
            }

        @api.get("/bild/turbo")
        async def image_state() -> dict[str, Any]:
            return self.image.state()

        @api.post("/bild/turbo/start")
        async def image_start(wanted: dict[str, Any] = Body(default={})) -> dict[str, Any]:
            return self.image.start(str(wanted.get("modell") or ""))

        @api.post("/bild/turbo/stop")
        async def image_stop() -> dict[str, Any]:
            return self.image.stop()

        @api.get("/bild/server/log")
        async def image_log() -> list[str]:
            return list(self.image.log)

        # --- Chats ---

        @api.post("/chats", status_code=201)
        async def create_chat(wanted: dict[str, Any] = Body(default={})) -> dict[str, Any]:
            chat_id = self._next("chat")
            chat: dict[str, Any] = {
                "id": chat_id,
                "user_id": "user-1",
                "title": wanted.get("title") or "New chat",
                "prompt_aus": False,
                "endpoint_id": wanted.get("endpoint_id"),
                "pinned": False,
                "working_dirs": [],
                "created_at": "2000-01-01T00:00:00",
                "updated_at": "2000-01-01T00:00:00",
                "project_id": None,
                "archived": False,
                "laeuft": False,
            }
            self.chats[chat_id] = chat
            self.messages[chat_id] = []
            return chat

        @api.get("/chats")
        async def list_chats(
            suche: str = "", limit: int = 100, archived: bool = False
        ) -> list[dict[str, Any]]:
            self.chat_listings.append({"suche": suche, "archived": archived})
            found = [
                chat
                for chat in self.chats.values()
                if suche.casefold() in str(chat["title"]).casefold()
                and bool(chat.get("archived")) == archived
            ]
            return found[:limit]

        @api.get("/chats/{chat_id}")
        async def read_chat(chat_id: str) -> dict[str, Any]:
            return self._chat(chat_id)

        @api.patch("/chats/{chat_id}")
        async def change_chat(
            chat_id: str, changes: dict[str, Any] = Body(default={})
        ) -> dict[str, Any]:
            chat = self._chat(chat_id)
            self.changes.append({"chat": chat_id, **changes})
            if self.refuse_folder and changes.get("working_dirs") is not None:
                raise HTTPException(422, self.refuse_folder)
            for field in ("title", "endpoint_id", "working_dirs", "archived"):
                if changes.get(field) is not None:
                    chat[field] = changes[field]
            if "project_id" in changes:
                # A null takes the chat out of its project.
                chat["project_id"] = changes["project_id"]
            return chat

        @api.get("/laeufe/{chat_id}")
        async def list_runs(chat_id: str) -> dict[str, Any]:
            self.run_listings.append(chat_id)
            return {"laeufe": self.runs.get(chat_id, []), "ab": 0}

        @api.post("/laeufe/{chat_id}/{number}/stop")
        async def stop_run(chat_id: str, number: int) -> dict[str, Any]:
            self.run_stops.append((chat_id, number))
            for run in self.runs.get(chat_id, []):
                if run["lauf"] == number:
                    run["zustand"] = "abgebrochen"
                    return run
            raise HTTPException(404, "No such run")

        @api.get("/projects")
        async def list_projects() -> list[dict[str, Any]]:
            return [
                {
                    **project,
                    "chat_count": sum(
                        1 for chat in self.chats.values() if chat.get("project_id") == project["id"]
                    ),
                }
                for project in self.projects.values()
                if not project.get("archived")
            ]

        @api.post("/projects", status_code=201)
        async def create_project(wanted: dict[str, Any] = Body(default={})) -> dict[str, Any]:
            identifier = self._next("project")
            self.project_actions.append(("create", identifier, dict(wanted)))
            project = {"id": identifier, "name": wanted.get("name"), "archived": False, "chat_count": 0}
            self.projects[identifier] = project
            return project

        @api.patch("/projects/{project_id}")
        async def change_project(
            project_id: str, wanted: dict[str, Any] = Body(default={})
        ) -> dict[str, Any]:
            self.project_actions.append(("change", project_id, dict(wanted)))
            self.projects[project_id].update(wanted)
            return self.projects[project_id]

        @api.delete("/projects/{project_id}")
        async def delete_project(project_id: str) -> list[str]:
            project = self.projects[project_id]
            if not project.get("archived"):
                raise HTTPException(409, "Only archived projects can be deleted.")
            if self.refuse_project_delete:
                raise HTTPException(409, self.refuse_project_delete)
            self.project_actions.append(("delete", project_id, None))
            gone = [
                chat_id
                for chat_id, chat in list(self.chats.items())
                if chat.get("project_id") == project_id
            ]
            for chat_id in gone:
                self.chats.pop(chat_id, None)
            self.projects.pop(project_id, None)
            return gone

        @api.delete("/chats/{chat_id}", status_code=204)
        async def delete_chat(chat_id: str) -> Response:
            self._chat(chat_id)
            if self.refuse_chat_delete:
                raise HTTPException(409, self.refuse_chat_delete)
            self.chat_deletions.append(chat_id)
            self.chats.pop(chat_id, None)
            return Response(status_code=204)

        @api.post("/documents", status_code=201)
        async def upload_document(request: Request, chat_id: str, name: str) -> dict[str, Any]:
            self._chat(chat_id)
            if "/documents" in self.refuse_upload:
                code, detail = self.refuse_upload["/documents"]
                raise HTTPException(code, detail)
            data = await request.body()
            self.uploads.append(("/documents", name, "", data))
            identifier = self._next("doc")
            return {"dokument": {"id": identifier, "filename": name, "size_bytes": len(data)}}

        @api.post("/images", status_code=201)
        async def upload_image(request: Request) -> dict[str, str]:
            if "/images" in self.refuse_upload:
                code, detail = self.refuse_upload["/images"]
                raise HTTPException(code, detail)
            data = await request.body()
            kind = (request.headers.get("content-type") or "").split(";")[0]
            name = f"{self._next('picture')}.png"
            self.uploads.append(("/images", name, kind, data))
            return {"bild": name}

        @api.get("/agents")
        async def list_agents() -> list[dict[str, Any]]:
            return self.agents

        @api.get("/agent-files")
        async def list_agent_files() -> list[dict[str, Any]]:
            names = [agent["name"] for agent in self.agents] + list(self.broken_agents)
            return [{"name": name, "kaputt": self.broken_agents.get(name)} for name in sorted(names)]

        @api.get("/agents/{name}")
        async def read_agent(name: str) -> dict[str, Any]:
            if name in self.broken_agents:
                return {"name": name, "content": "", "kaputt": self.broken_agents[name], "prompt": None}
            if name not in [agent["name"] for agent in self.agents]:
                raise HTTPException(404, "No such agent")
            return {"name": name, "content": "", "kaputt": None, "prompt": self.agent_prompts.get(name, "")}

        @api.put("/agents/{name}/fields")
        async def save_agent_fields(name: str, wanted: dict[str, Any] = Body(default={})) -> dict[str, Any]:
            if self.refuse_agent:
                raise HTTPException(422, self.refuse_agent)
            self.agent_actions.append(("save", name, dict(wanted)))
            return {"name": name, "content": "", "kaputt": None, "prompt": wanted.get("prompt")}

        @api.delete("/agents/{name}", status_code=204)
        async def delete_agent(name: str) -> Response:
            self.agent_actions.append(("delete", name, None))
            self.agents = [agent for agent in self.agents if agent["name"] != name]
            self.broken_agents.pop(name, None)
            return Response(status_code=204)

        @api.get("/jobs/laufmodell")
        async def run_model(request: Request) -> dict[str, Any]:
            self.run_model_asked.append(dict(request.query_params))
            return self.run_model

        @api.get("/jobs")
        async def list_jobs() -> list[dict[str, Any]]:
            return list(self.jobs.values())

        @api.post("/jobs", status_code=201)
        async def start_job(wanted: dict[str, Any] = Body(default={})) -> dict[str, Any]:
            if wanted.get("agent") not in [agent["name"] for agent in self.agents]:
                names = ", ".join(agent["name"] for agent in self.agents)
                raise HTTPException(404, f"No agent of that name. There are: {names}")
            identifier = self._next("job")
            self.job_actions.append(("start", identifier, dict(wanted)))
            job = {
                "id": identifier,
                "agent": wanted["agent"],
                "task": wanted["task"],
                "state": "laeuft",
                "result": None,
                "question": None,
                "created_at": "2026-10-15T10:00:00+00:00",
                "updated_at": "2026-10-15T10:00:00+00:00",
            }
            self.jobs[identifier] = job
            return job

        @api.get("/jobs/{job_id}")
        async def read_job(job_id: str) -> dict[str, Any]:
            if job_id not in self.jobs:
                raise HTTPException(404, "No such task")
            return {**self.jobs[job_id], "schritte": self.job_steps.get(job_id, [])}

        @api.post("/jobs/{job_id}/cancel")
        async def cancel_job(job_id: str) -> dict[str, Any]:
            self.job_actions.append(("cancel", job_id, None))
            self.jobs[job_id]["state"] = "abgebrochen"
            return self.jobs[job_id]

        @api.post("/jobs/{job_id}/answer")
        async def answer_job(job_id: str, wanted: dict[str, Any] = Body(default={})) -> dict[str, Any]:
            self.job_actions.append(("answer", job_id, dict(wanted)))
            self.jobs[job_id].update(state="laeuft", question=None)
            return self.jobs[job_id]

        @api.delete("/jobs/{job_id}", status_code=204)
        async def delete_job(job_id: str) -> Response:
            self.job_actions.append(("delete", job_id, None))
            self.jobs.pop(job_id, None)
            return Response(status_code=204)

        @api.get("/cronjobs")
        async def list_cronjobs() -> list[dict[str, Any]]:
            return list(self.cronjobs.values())

        @api.get("/cronjobs/runs/all")
        async def cronjob_runs() -> list[dict[str, Any]]:
            return self.cronjob_runs

        @api.post("/cronjobs", status_code=201)
        async def create_cronjob(wanted: dict[str, Any] = Body(default={})) -> dict[str, Any]:
            identifier = self._next("cron")
            self.cronjob_actions.append(("create", identifier, dict(wanted)))
            kind = "reminder" if wanted.get("reminder") else "script" if wanted.get("skript") else "agent"
            entry = {
                "id": identifier,
                "agent": wanted.get("agent") or "(none)",
                "task": wanted.get("task", ""),
                "zeitplan": wanted["zeitplan"],
                "aktiv": True,
                "kind": kind,
                "skript": wanted.get("skript"),
                "einmalig": bool(wanted.get("einmalig")),
                "datum": wanted.get("datum"),
                "letzter_ausgang": None,
            }
            self.cronjobs[identifier] = entry
            return entry

        @api.patch("/cronjobs/{cronjob_id}")
        async def change_cronjob(
            cronjob_id: str, wanted: dict[str, Any] = Body(default={})
        ) -> dict[str, Any]:
            self.cronjob_actions.append(("change", cronjob_id, dict(wanted)))
            self.cronjobs[cronjob_id].update(wanted)
            return self.cronjobs[cronjob_id]

        @api.post("/cronjobs/{cronjob_id}/pause")
        async def pause_cronjob(cronjob_id: str) -> dict[str, Any]:
            self.cronjob_actions.append(("pause", cronjob_id, None))
            self.cronjobs[cronjob_id]["aktiv"] = False
            return self.cronjobs[cronjob_id]

        @api.post("/cronjobs/{cronjob_id}/resume")
        async def resume_cronjob(cronjob_id: str) -> dict[str, Any]:
            self.cronjob_actions.append(("resume", cronjob_id, None))
            self.cronjobs[cronjob_id]["aktiv"] = True
            return self.cronjobs[cronjob_id]

        @api.post("/cronjobs/{cronjob_id}/run")
        async def run_cronjob(cronjob_id: str) -> dict[str, Any]:
            if not self.cronjobs[cronjob_id]["aktiv"]:
                raise HTTPException(409, "This schedule is paused.")
            self.cronjob_actions.append(("run", cronjob_id, None))
            return {**self.cronjobs[cronjob_id], "notice": self.cronjob_notice}

        @api.delete("/cronjobs/{cronjob_id}", status_code=204)
        async def delete_cronjob(cronjob_id: str) -> Response:
            self.cronjob_actions.append(("delete", cronjob_id, None))
            self.cronjobs.pop(cronjob_id, None)
            return Response(status_code=204)

        @api.get("/chats/{chat_id}/ordnerstand")
        async def folder_state(chat_id: str) -> dict[str, Any]:
            chat = self._chat(chat_id)
            return {
                "fehlend": [
                    folder
                    for folder in chat.get("working_dirs") or []
                    if folder in self.missing_folders
                ]
            }

        @api.get("/chats/{chat_id}/messages")
        async def list_messages(chat_id: str) -> JSONResponse:
            self._chat(chat_id)
            stored = self.messages[chat_id]
            return JSONResponse(
                {"nachrichten": stored, "laufend": None, "gehalten": False},
                headers={"X-Nachrichten-Gesamt": str(len(stored))},
            )

        # --- One answer ---

        @api.post("/chat/completions")
        async def answer(message: dict[str, Any] = Body(...)) -> StreamingResponse:
            chat = self._chat(str(message.get("chat_id")))
            endpoint = message.get("endpoint_id") or chat.get("endpoint_id")
            if not endpoint:
                raise HTTPException(400, "No model chosen")
            self.sent.append(message)
            if message.get("content") is not None:
                self._store(chat["id"], "user", str(message["content"]))
            run = _Run(self._next("run"), chat["id"], self._next("message"))
            self._runs[run.id] = run
            # On its own, not inside this request: an answer goes on when
            # the client that asked for it is gone.
            task = asyncio.create_task(self._produce(run, list(self.script), str(endpoint)))
            self._producing.add(task)
            task.add_done_callback(self._producing.discard)
            return StreamingResponse(self._follow(run, 0), media_type="text/event-stream")

        @api.get("/chat/stream/{run_id}")
        async def watch(run_id: str, ab: int = 0) -> StreamingResponse:
            run = self._runs.get(run_id)
            if run is None:
                raise HTTPException(404, "No such answer")
            return StreamingResponse(self._follow(run, ab), media_type="text/event-stream")

        @api.post("/chat/confirm")
        async def confirm(decision: dict[str, Any] = Body(...)) -> dict[str, bool]:
            self.confirmations.append(decision)
            run = self._runs.get(str(decision.get("generation_id")))
            waiting = run.waiting.pop(str(decision.get("aufruf_id")), None) if run else None
            if waiting is None or waiting.done():
                return {"zugestellt": False}
            if decision.get("erlaubt") and decision.get("dauerhaft") and decision.get("name"):
                self.always_allowed[str(decision["name"])] = "allow"
            waiting.set_result(decision)
            return {"zugestellt": True}

        @api.post("/chat/stop")
        async def stop(wanted: dict[str, Any] = Body(default={})) -> dict[str, int]:
            self.stops.append(wanted)
            if not wanted.get("chat_id") and not wanted.get("generation_id"):
                raise HTTPException(400, "Neither a chat nor an answer was named")
            stopped = 0
            for run in self._runs.values():
                named = run.chat_id == wanted.get("chat_id") or run.id == wanted.get("generation_id")
                if named and not run.over and not run.stopped:
                    run.stopped = True
                    for waiting in run.waiting.values():
                        if not waiting.done():
                            waiting.cancel()
                    stopped += 1
            return {"abgebrochen": stopped}

        # --- The program's own events ---

        @api.get("/events/stream")
        async def events() -> StreamingResponse:
            if self.events_refused:
                raise HTTPException(503, "The event stream is closed")
            watcher: asyncio.Queue[str | None] = asyncio.Queue()
            self._watchers.add(watcher)
            return StreamingResponse(self._watch(watcher), media_type="text/event-stream")

        # --- Cloud providers --------------------------------------------------------

        @api.get("/meta")
        async def meta() -> dict[str, Any]:
            return {"system_name": self.system_name}

        @api.get("/memory")
        async def read_memory() -> dict[str, Any]:
            return {"text": self.long_texts["/memory"], "datei": "memory.md"}

        @api.put("/memory")
        async def write_memory(wanted: dict[str, Any] = Body(default={})) -> dict[str, Any]:
            return self._write_long_text("/memory", wanted)

        @api.get("/system-prompt")
        async def read_system_prompt() -> dict[str, Any]:
            return {"text": self.long_texts["/system-prompt"], "datei": "system.md"}

        @api.put("/system-prompt")
        async def write_system_prompt(wanted: dict[str, Any] = Body(default={})) -> dict[str, Any]:
            return self._write_long_text("/system-prompt", wanted)

        @api.post("/providers")
        async def add_provider(wanted: dict[str, Any] = Body(default={})) -> dict[str, Any]:
            self.provider_requests.append(("add", dict(wanted)))
            key = str(wanted.get("schluessel") or "")
            if len(key) < 8:
                # The service's own validation names the value it refused.
                raise HTTPException(422, [{"msg": "too short", "input": key}])
            kind = str(wanted.get("art") or "")
            identifier = str(wanted.get("kennung") or kind).lower()
            if any(entry.get("anbieter") == identifier for entry in self.models):
                raise HTTPException(409, "A provider with that id exists already.")
            entry = model(f"{identifier}-model", f"{identifier} model")
            entry.update(
                {
                    "anbieter": identifier,
                    "anbieter_name": {"anthropic": "Anthropic", "openai": "OpenAI"}.get(
                        identifier, identifier
                    ),
                    "group": "cloud",
                    "erreichbar": self.provider_reachable,
                    "schluessel_gesetzt": True,
                    "key_goes_with_provider": True,
                }
            )
            self.models.append(entry)
            return {
                "id": identifier,
                "api_key_env": f"{identifier.upper()}_API_KEY",
                "erreichbar": self.provider_reachable,
            }

        def provider_models(identifier: str) -> list[dict[str, Any]]:
            found = [entry for entry in self.models if entry.get("anbieter") == identifier]
            if not found:
                raise HTTPException(404, f"No such provider: {identifier}")
            return found

        @api.put("/providers/{identifier}/capabilities")
        async def provider_capabilities(
            identifier: str, wanted: dict[str, Any] = Body(default={})
        ) -> dict[str, Any]:
            self.provider_requests.append((f"{identifier}/capabilities", dict(wanted)))
            for entry in provider_models(identifier):
                entry.setdefault("capabilities", {}).update(wanted)
            return {"id": identifier}

        @api.put("/providers/{identifier}/context")
        async def provider_context(
            identifier: str, wanted: dict[str, Any] = Body(default={})
        ) -> dict[str, Any]:
            self.provider_requests.append((f"{identifier}/context", dict(wanted)))
            for entry in provider_models(identifier):
                entry["kontext_eigen"] = wanted.get("context_tokens")
            return {"id": identifier}

        @api.put("/providers/{identifier}/timeout")
        async def provider_timeout(
            identifier: str, wanted: dict[str, Any] = Body(default={})
        ) -> dict[str, Any]:
            self.provider_requests.append((f"{identifier}/timeout", dict(wanted)))
            for entry in provider_models(identifier):
                entry["timeout_enabled"] = wanted.get("timeout_enabled")
            return {"id": identifier}

        @api.delete("/providers/{identifier}", status_code=204)
        async def remove_provider(identifier: str) -> Response:
            self.provider_requests.append((f"{identifier}/remove", None))
            provider_models(identifier)
            self.models[:] = [entry for entry in self.models if entry.get("anbieter") != identifier]
            return Response(status_code=204)

        # --- Settings, tools, permissions ---

        @api.get("/settings/resolved")
        async def resolved(
            keys: str | None = None, modell: str | None = None, chat: str | None = None
        ) -> dict[str, Any]:
            if keys is None:
                # Asked without a list: every setting any scope holds.
                names = list(dict.fromkeys(name for held in self.settings.values() for name in held))
            else:
                names = [name.strip() for name in keys.split(",") if name.strip()]
                if not names:
                    raise HTTPException(400, "No setting was named")
            return {name: self._resolved(name, modell, chat) for name in names}

        @api.get("/settings/resolved/{name}")
        async def resolved_one(
            name: str, modell: str | None = None, chat: str | None = None
        ) -> dict[str, Any]:
            return self._resolved(name, modell, chat)

        @api.get("/settings/{scope}/{name}")
        async def read_setting(scope: str, name: str) -> dict[str, Any]:
            value = self.settings.get(scope, {}).get(name)
            return {"bereich": scope, "schluessel": name, "wert": value}

        @api.patch("/settings/{scope}/{name}")
        async def merge_setting(
            scope: str, name: str, wanted: dict[str, Any] = Body(...)
        ) -> dict[str, Any]:
            held = self.settings.setdefault(scope, {}).get(name)
            merged = {**(held if isinstance(held, dict) else {}), **(wanted.get("wert") or {})}
            self.settings[scope][name] = merged
            return {"bereich": scope, "schluessel": name, "wert": merged}

        @api.put("/settings/{scope}/{name}")
        async def write_setting(
            scope: str, name: str, wanted: dict[str, Any] = Body(...)
        ) -> dict[str, Any]:
            if name.startswith("unknown"):
                raise HTTPException(400, f"Unknown setting: {name}")
            value = wanted.get("wert")
            if value is None:
                self.settings.get(scope, {}).pop(name, None)
            else:
                self.settings.setdefault(scope, {})[name] = value
            return {"bereich": scope, "schluessel": name, "wert": value}

        @api.get("/tools")
        async def tools() -> dict[str, Any]:
            servers = sorted({str(tool.get("server") or "") for tool in self.tools} - {""})
            return {"aktiv": bool(self.tools), "server": servers, "werkzeuge": self.tools}

        def skill_row(name: str) -> dict[str, Any]:
            skill = self.skill_files[name]
            return {
                "name": name,
                "beschreibung": skill.get("beschreibung", ""),
                "auto": bool(skill.get("auto")),
                "eigen": bool(skill.get("eigen")),
                "mitgeliefert": bool(skill.get("mitgeliefert")),
            }

        @api.get("/skills")
        async def skills_offered() -> list[dict[str, Any]]:
            return [
                {key: row[key] for key in ("name", "beschreibung", "auto")}
                for row in (skill_row(name) for name in sorted(self.skill_files))
            ]

        @api.get("/skills/verwaltung")
        async def skills_managed() -> list[dict[str, Any]]:
            return [skill_row(name) for name in sorted(self.skill_files)]

        @api.post("/skills", status_code=201)
        async def skill_create(wanted: dict[str, Any] = Body(default={})) -> dict[str, Any]:
            if self.refuse_skill:
                raise HTTPException(400, self.refuse_skill)
            name = str(wanted.get("name"))
            self.skill_actions.append(("create", name, dict(wanted)))
            self.skill_files[name] = {
                "beschreibung": "", "auto": False, "eigen": True, "mitgeliefert": False,
                "inhalt": wanted.get("inhalt", ""),
            }
            return skill_row(name)

        @api.get("/skills/{name}")
        async def skill_file(name: str) -> dict[str, Any]:
            if name not in self.skill_files:
                raise HTTPException(404, "No such skill")
            skill = self.skill_files[name]
            return {
                "name": name, "inhalt": skill.get("inhalt", ""),
                "eigen": bool(skill.get("eigen")), "mitgeliefert": bool(skill.get("mitgeliefert")),
            }

        @api.put("/skills/{name}")
        async def skill_save(name: str, wanted: dict[str, Any] = Body(default={})) -> dict[str, Any]:
            if self.refuse_skill:
                raise HTTPException(400, self.refuse_skill)
            self.skill_actions.append(("save", name, dict(wanted)))
            self.skill_files[name].update(inhalt=wanted.get("inhalt", ""), eigen=True)
            return skill_row(name)

        @api.patch("/skills/{name}")
        async def skill_auto(name: str, wanted: dict[str, Any] = Body(default={})) -> dict[str, Any]:
            if self.refuse_skill:
                raise HTTPException(400, self.refuse_skill)
            self.skill_actions.append(("auto", name, dict(wanted)))
            self.skill_files[name].update(auto=bool(wanted.get("auto")), eigen=True)
            return skill_row(name)

        @api.delete("/skills/{name}", status_code=204)
        async def skill_remove(name: str) -> Response:
            skill = self.skill_files.get(name)
            if skill is None or not skill.get("eigen"):
                raise HTTPException(404, "No copy of your own")
            self.skill_actions.append(("remove", name, None))
            if skill.get("mitgeliefert"):
                skill["eigen"] = False
            else:
                del self.skill_files[name]
            return Response(status_code=204)

        @api.get("/doc-folder")
        async def doc_folder(chat: str | None = None) -> list[dict[str, Any]]:
            return [
                entry for entry in self.doc_files if chat is None or entry.get("chat_id") == chat
            ]

        @api.get("/doc-folder/place")
        async def doc_folder_place(chat: str) -> dict[str, Any]:
            if chat not in self.doc_places:
                raise HTTPException(404, "No such file")
            return {"path": self.doc_places[chat]}

        @api.get("/speicherorte")
        async def storage_places() -> list[dict[str, Any]]:
            return self.places

        @api.put("/speicherorte/{name}")
        async def storage_place_set(
            name: str, wanted: dict[str, Any] = Body(default={})
        ) -> dict[str, Any]:
            if self.refuse_place:
                raise HTTPException(400, self.refuse_place)
            place = next((entry for entry in self.places if entry["name"] == name), None)
            if place is None:
                raise HTTPException(404, "This storage location does not exist")
            self.place_actions.append((name, dict(wanted)))
            place["pfad"] = wanted.get("pfad")
            return place

        @api.get("/tools/servers")
        async def mcp_servers() -> list[dict[str, Any]]:
            return list(self.mcp_servers.values())

        @api.post("/tools/mcp/sondieren")
        async def mcp_probe(wanted: dict[str, Any] = Body(default={})) -> dict[str, Any]:
            self.mcp_actions.append(("probe", str(wanted.get("url")), dict(wanted)))
            return self.mcp_probes.get(str(wanted.get("url")), {"verlangt": None})

        @api.put("/tools/servers/{name}")
        async def mcp_write(
            name: str, neu: bool = False, wanted: dict[str, Any] = Body(default={})
        ) -> dict[str, Any]:
            if self.refuse_mcp:
                raise HTTPException(422, self.refuse_mcp)
            if neu and name in self.mcp_servers:
                raise HTTPException(409, "Name already taken")
            self.mcp_actions.append(("write", name, dict(wanted)))
            entry = self.mcp_servers.setdefault(
                name,
                {
                    "name": name,
                    "type": "http",
                    "enabled": True,
                    "laeuft": False,
                    "alle_werkzeuge": [],
                    "allowed_tools": None,
                    "needs_confirmation": [],
                },
            )
            fields = {key: value for key, value in wanted.items() if key != "api_key"}
            entry.update(fields)
            if neu:
                entry["laeuft"] = self.mcp_connects
                entry["alle_werkzeuge"] = (
                    [{"name": tool, "beschreibung": ""} for tool in self.mcp_tool_names]
                    if self.mcp_connects
                    else []
                )
            return entry

        @api.delete("/tools/servers/{name}", status_code=204)
        async def mcp_remove(name: str) -> Response:
            if name not in self.mcp_servers:
                raise HTTPException(404, "No such server")
            self.mcp_actions.append(("delete", name, None))
            del self.mcp_servers[name]
            return Response(status_code=204)

        @api.post("/tools/oauth/start")
        async def mcp_sign_in(wanted: dict[str, Any] = Body(default={})) -> dict[str, Any]:
            self.mcp_actions.append(("oauth", str(wanted.get("server")), dict(wanted)))
            entry = self.mcp_servers.get(str(wanted.get("server")))
            if entry is not None and self.mcp_connects:
                entry["laeuft"] = True
                entry["alle_werkzeuge"] = [
                    {"name": tool, "beschreibung": ""} for tool in self.mcp_tool_names
                ]
            return {"url": self.mcp_sign_in_url}

        @api.get("/permissions/always-allow")
        async def always_allowed() -> dict[str, str]:
            return self.always_allowed

        @api.delete("/permissions/always-allow/{name}", status_code=204)
        async def forget(name: str) -> Response:
            if self.always_allowed.pop(name, None) is None:
                raise HTTPException(404, "No such rule")
            return Response(status_code=204)

        app.include_router(api)
        return app

    # --- Behind the addresses ----------------------------------------------------

    def _store(self, chat_id: str, role: str, text: str, thought: str = "") -> None:
        self.messages[chat_id].append(
            {
                "id": self._next("stored"),
                "chat_id": chat_id,
                "role": role,
                "content": text,
                "reasoning": thought or None,
                "stats": {},
                "created_at": "2000-01-01T00:00:00",
            }
        )

    def _resolved(self, name: str, model_id: str | None, chat_id: str | None) -> dict[str, Any]:
        """What applies for one setting and where each value comes from: the
        widest scope first, every narrower one over it. A value that is no
        set of values names the scope it came from as a whole."""
        scopes = ["global"]
        if model_id:
            scopes.append(f"modell:{model_id}")
        if chat_id:
            scopes.append(f"chat:{chat_id}")
        value: Any = {}
        origin: dict[str, str] = {}
        whole: str | None = None
        for scope in scopes:
            held = self.settings.get(scope, {}).get(name)
            if isinstance(held, dict) and isinstance(value, dict):
                value = {**value, **held}
                origin.update(dict.fromkeys(held, scope))
                whole = None
            elif held is not None:
                value, origin, whole = held, {}, scope
        return {"wert": value, "herkunft": origin, "scope": whole}

    async def _emit(self, run: _Run, kind: str, **fields: Any) -> None:
        async with run.changed:
            run.events.append({"typ": kind, "zeitpunkt_ms": round(time.time() * 1000), **fields})
            run.changed.notify_all()

    async def _produce(self, run: _Run, script: list[dict[str, Any]], endpoint: str) -> None:
        """Plays the script as one answer. A call that waits for permission
        holds the answer until the decision is in; a stop ends it where it
        stands."""
        said = ""
        thought = ""
        declined: set[str] = set()
        try:
            await self._emit(
                run,
                "start",
                generation_id=run.id,
                message_id=run.message_id,
                chat_id=run.chat_id,
                endpoint_id=endpoint,
            )
            for step in script:
                if run.stopped:
                    break
                event = dict(step)
                kind = str(event.pop("typ"))
                call = str(event.get("aufruf_id") or "")
                if kind == "content":
                    said += str(event.get("text") or "")
                elif kind == "reasoning":
                    thought += str(event.get("text") or "")
                elif kind in ("kontext", "done"):
                    event.setdefault("message_id", run.message_id)
                elif kind == "tool_result" and call in declined:
                    event.update(fehlgeschlagen=True, text=DECLINED)
                asked: asyncio.Future[dict[str, Any]] | None = None
                if kind in ("tool_confirm", "user_ask"):
                    # Standing before the question is out, so no decision
                    # can arrive ahead of who waits for it.
                    asked = run.waiting[call] = asyncio.get_running_loop().create_future()
                await self._emit(run, kind, **event)
                if asked is not None:
                    try:
                        decision = await asked
                    except asyncio.CancelledError:
                        if not run.stopped:
                            raise
                        break
                    if kind == "tool_confirm" and not decision.get("erlaubt"):
                        declined.add(call)
            if run.stopped:
                await self._emit(
                    run, "done", message_id=run.message_id, abgebrochen=True, zustand="abgebrochen"
                )
        finally:
            if said or thought:
                self._store(run.chat_id, "assistant", said, thought)
            async with run.changed:
                run.over = True
                run.changed.notify_all()

    async def _follow(self, run: _Run, position: int) -> Any:
        """The events of an answer from ``position`` on, each as soon as it
        exists, to the answer's end."""
        while True:
            async with run.changed:
                while position >= len(run.events) and not run.over:
                    await run.changed.wait()
                ready = run.events[position:]
                over = run.over
            for event in ready:
                yield _data(event)
            position += len(ready)
            if over and position >= len(run.events):
                return

    async def _watch(self, watcher: asyncio.Queue[str | None]) -> Any:
        try:
            while True:
                piece = await watcher.get()
                if piece is None:
                    return
                yield piece
        finally:
            self._watchers.discard(watcher)
