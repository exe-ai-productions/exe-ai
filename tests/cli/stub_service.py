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

    def state(self) -> dict[str, Any]:
        return {
            "zustand": self.word,
            "modell": self.model,
            "programm_da": True,
            "picture_running": False,
        }

    def start(self, file: str) -> dict[str, Any]:
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
        async def list_chats(suche: str = "", limit: int = 100) -> list[dict[str, Any]]:
            found = [
                chat
                for chat in self.chats.values()
                if suche.casefold() in str(chat["title"]).casefold()
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
            for field in ("title", "endpoint_id", "working_dirs"):
                if changes.get(field) is not None:
                    chat[field] = changes[field]
            return chat

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

        @api.get("/settings/{scope}/{name}")
        async def read_setting(scope: str, name: str) -> dict[str, Any]:
            value = self.settings.get(scope, {}).get(name)
            return {"bereich": scope, "schluessel": name, "wert": value}

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
