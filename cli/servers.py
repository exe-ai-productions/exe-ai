"""The servers from the client's side: which files of the model folder the
model server could carry, starting it with one of them, replacing what it
carries and waiting until the model is connected — and the command that
lists the six servers and starts, stops and reads the log of each.

Nothing here decides how a server runs: the service starts it with the
window, the layers and the engine levers of its stored choice, and the
client only names the file. What the service refuses is raised as its own
sentence and shown by the screen like any other refusal.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from cli import glyphs
from cli.client import ServiceError
from cli.interfaces import Context, Entry
from cli.status import ACTIVE, IDLE, OFFLINE
from cli.texts import Texts

# How often the service is asked while a model loads: the beat the window
# asks its own page at.
POLL_SECONDS = 2.0

# How many lines of the server's log stand under a start that failed.
LOG_LINES = 10

# The provider id the model server's models carry in the service's list.
PROVIDER = "runner"

# What the service answers a start with where the server's program is not
# on the machine.
NO_PROGRAM = 412


def not_carried(ctx: Context) -> list[dict[str, Any]]:
    """The files of the model folder the model server does not carry right
    now — all of them while it is off — each as an entry of the model list:
    ``datei`` names the file, ``name`` is what the list shows, and
    ``groesse_gb`` is the size as the service gives it. Empty where the
    service does not say or the folder holds none."""
    try:
        state = ctx.client.get("/runner")
    except ServiceError:
        return []
    if not isinstance(state, dict):
        return []
    carried = state.get("modell") if state.get("laeuft") else None
    files = state.get("modelle")
    listed = [entry for entry in files if isinstance(entry, dict)] if isinstance(files, list) else []
    return [
        {"datei": file["name"], "name": file["name"], "groesse_gb": file.get("groesse_gb")}
        for file in listed
        if isinstance(file.get("name"), str) and file["name"] != carried
    ]


def start_with(ctx: Context, file: str) -> dict[str, Any] | None:
    """Brings the model server up with ``file`` and returns the entry of the
    model list that is connected once it is — ``None`` where nothing came of
    it: the user said no, the server did not start, or the wait was ended.
    What the service refuses is raised.

    A server that already carries the file is not touched — it is waited
    for where it still loads. One that carries another model is stopped
    first, after a question where it is writing an answer. Where the
    program is missing, the user is asked and it is fetched. The wait has
    no limit of its own as long as the server lives; the interrupt key ends
    it and stops the server this call started."""
    state = ctx.client.get("/runner")
    running = isinstance(state, dict) and bool(state.get("laeuft"))
    carries = running and state.get("modell") == file
    with waiting(ctx) as cancel:
        if not carries:
            if running and not _stop_what_runs(ctx, file):
                return None
            if not _start(ctx, "/runner/start", file, cancel, fetches=True):
                return None
        return _wait_until_connected(ctx, file, cancel, started=not carries)


@contextlib.contextmanager
def waiting(ctx: Context) -> Iterator[threading.Event]:
    """What a command that waits for something stands in: the interrupt key
    ends the wait through the event, and once it is over the line above the
    status line is the running answer's again, or empty."""
    cancel = threading.Event()
    ctx.session.cancel_wait = cancel.set
    try:
        yield cancel
    finally:
        ctx.session.cancel_wait = None
        settle_activity(ctx)


def settle_activity(ctx: Context) -> None:
    """Gives the line above the status line back: to the running answer,
    or to nobody."""
    busy = ctx.texts.t("status.erzeugt_antwort") if ctx.session.answering else None
    ctx.screen.set_activity(busy)


def ask(ctx: Context, question: str) -> bool:
    """Whether the user answered a question of the client's own with yes. A
    selection that was closed is no."""
    texts = ctx.texts
    picked = ctx.asker.choose(
        [Entry(cells=[("text", texts.t("app.ja"))]), Entry(cells=[("text", texts.t("app.nein"))])],
        head=question,
    )
    return picked == 0


def _models(ctx: Context) -> list[dict[str, Any]]:
    listed = ctx.client.get("/models")
    return [entry for entry in listed if isinstance(entry, dict)] if isinstance(listed, list) else []


def _stop_what_runs(ctx: Context, file: str) -> bool:
    """Stops the model server that runs — asking first where it is writing
    an answer. ``False`` where the user said no."""
    server = [entry for entry in _models(ctx) if entry.get("anbieter") == PROVIDER]
    if any(entry.get("server_state") == ACTIVE for entry in server):
        if not ask(ctx, ctx.texts.t("cli.model_swap_ask", name=file)):
            return False
    ctx.client.post("/runner/stop")
    return True


def _connected(ctx: Context) -> dict[str, Any] | None:
    """The entry of the model server's model in the service's list, once it
    answers."""
    return next(
        (
            entry
            for entry in _models(ctx)
            if entry.get("anbieter") == PROVIDER and entry.get("erreichbar")
        ),
        None,
    )


def _start(
    ctx: Context, path: str, file: str, cancel: threading.Event, *, fetches: bool
) -> bool:
    """Starts a server with ``file``. Where its program is not there and
    one can be fetched, the user is asked, and it is fetched and the start
    made again. ``False`` where the user said no or the wait for the
    program was ended."""
    try:
        ctx.client.post(path, json={"modell": file})
        return True
    except ServiceError as error:
        if error.status != NO_PROGRAM or not fetches:
            raise
    if not ask(ctx, ctx.texts.t("cli.program_missing_ask")):
        return False
    if not _fetch_program(ctx, cancel):
        return False
    ctx.client.post(path, json={"modell": file})
    return True


def _start_image(ctx: Context, file: str, cancel: threading.Event) -> bool:
    """Starts the image server with ``file``. Where its program is not
    there, it is offered as the window offers it — as one entry of the
    selection, not as a question — and fetched, and the start is made
    again. ``False`` where the selection was closed or the wait ended."""
    path = SERVERS[-1].start
    try:
        ctx.client.post(path, json={"modell": file})
        return True
    except ServiceError as error:
        if error.status != NO_PROGRAM:
            raise
    if not fetch_image_program(ctx, cancel):
        return False
    ctx.client.post(path, json={"modell": file})
    return True


def _fetch_program(
    ctx: Context,
    cancel: threading.Event,
    *,
    newest: bool = False,
    path: str = "/runner/programm",
    variant: str | None = None,
    word_key: str = "modell.server_holen",
) -> bool:
    """Has the service fetch a program — the newest build where ``newest``,
    the build of ``variant`` where one is named — and waits for it, saying
    how far it is. ``False`` where it failed — which has been said, as the
    window says it — or the wait was ended; the service has no way to end a
    fetch, so one that was walked away from goes on."""
    texts = ctx.texts
    body: dict[str, Any] | None = None
    if newest:
        body = {"aktualisieren": True}
    elif variant is not None:
        body = {"variante": variant}
    stand = ctx.client.post(path, json=body)
    while True:
        if isinstance(stand, dict):
            if stand.get("fehler"):
                # The state names a reason, not a sentence.
                ctx.renderer.error(texts.t("bildserver.generator_fehler"))
                return False
            if stand.get("fertig"):
                return True
            anteil = stand.get("anteil")
            percent = round(float(anteil) * 100) if isinstance(anteil, (int, float)) else 0
            ctx.screen.set_activity(f"{texts.t(word_key)} {percent} %")
        elif stand is None and path != "/runner/programm":
            # The image program's state is empty once nothing is being
            # fetched: what is left to say is whether the program is there.
            return bool(_image_listing(ctx).get("programm_da"))
        if cancel.wait(POLL_SECONDS):
            return False
        stand = ctx.client.get(path)


# --- The image server's program ------------------------------------------------------------

IMAGE_PROGRAM = "/bild/programm"


def fetch_image_program(ctx: Context, cancel: threading.Event) -> bool:
    """The image server's program is not there: offers to fetch it — as one
    entry of a selection that the window's button stands for, or, on a
    system that offers more than one build, one entry per build — and
    fetches the one picked, saying how far it is. ``False`` where the
    selection was closed, a build that is there was picked, or it failed."""
    texts = ctx.texts
    builds = _image_builds(ctx)
    if builds:
        entries = [
            Entry(
                cells=[
                    ("text", name),
                    (
                        "muted",
                        texts.t("bildserver.variante_installiert")
                        if name == installed
                        else texts.t("bildserver.variante_holen", groesse=_build_size(size)),
                    ),
                ]
            )
            for name, size, installed in builds
        ]
    else:
        entries = [Entry(cells=[("text", texts.t("bildserver.generator_holen"))])]
    picked = ctx.asker.choose(entries)
    if picked is None:
        return False
    name = builds[picked][0] if builds else None
    if builds and builds[picked][0] == builds[picked][2]:
        return False
    return _fetch_program(
        ctx, cancel, path=IMAGE_PROGRAM, variant=name, word_key="bildserver.generator_laedt"
    )


def _image_builds(ctx: Context) -> list[tuple[str, Any, str | None]]:
    """The builds of the program a machine can choose between, each with
    its size and which one is installed — empty where the system offers
    only one, as everywhere but on Windows."""
    try:
        answer = ctx.client.get(f"{IMAGE_PROGRAM}/varianten")
    except ServiceError:
        return []
    answer = answer if isinstance(answer, dict) else {}
    listed = answer.get("varianten")
    installed = answer.get("installiert")
    installed = installed if isinstance(installed, str) else None
    return [
        (str(entry["variante"]), entry.get("groesse"), installed)
        for entry in (listed if isinstance(listed, list) else [])
        if isinstance(entry, dict) and isinstance(entry.get("variante"), str)
    ]


def _build_size(size: Any) -> str:
    """A build's size as the window words it: whole megabytes."""
    return f"{round(size / (1024 * 1024))} MB" if _is_number(size) else ""


def _image_listing(ctx: Context) -> dict[str, Any]:
    listed = ctx.client.get("/bild/modelle")
    return listed if isinstance(listed, dict) else {}


def _wait_until_connected(
    ctx: Context, file: str, cancel: threading.Event, *, started: bool
) -> dict[str, Any] | None:
    """Asks the service until the model server's model is among the models
    it lists as connected. Ends when the server no longer runs — said, with
    the last lines of its log — or when the interrupt key ends the wait,
    which stops the server where this command started it."""
    ctx.screen.set_activity(ctx.texts.t("cli.model_starting", name=file))
    while True:
        connected = _connected(ctx)
        if connected is not None:
            return connected
        state = ctx.client.get("/runner")
        if not (isinstance(state, dict) and state.get("laeuft")):
            _say_why_not(ctx)
            return None
        if cancel.wait(POLL_SECONDS):
            if started:
                ctx.client.post("/runner/stop")
            return None


def _say_why_not(ctx: Context) -> None:
    """The server ended before its model was connected: the client's
    sentence, and below it what the server last said."""
    ctx.renderer.error(ctx.texts.t("cli.model_start_failed"))
    try:
        log = ctx.client.get("/runner/log")
    except ServiceError:
        return
    for line in [str(entry) for entry in log][-LOG_LINES:] if isinstance(log, list) else []:
        ctx.renderer.shell_line(line)


# --- The six servers ----------------------------------------------------------------

# The words behind ``/server`` that name a server, and the three that name
# what is done to one.
MODEL = "model"
IMAGE = "image"
START = "start"
STOP = "stop"
LOG = "log"
ACTIONS = (START, STOP, LOG)

# What the entries of a server's own selection stand for besides the three
# above: the check for a newer program, the fetch of it, and — for the image
# server — the fetch of the program itself.
_CHECK = "check"
_UPDATE = "update"
_GET = "get"

# What the image server says of itself while it can draw.
_IMAGE_RUNNING = ("bereit", "zeichnet")

# A style name of the client's look, and the sentence.
Row = list[tuple[str, str]]


@dataclass(frozen=True)
class Server:
    word: str
    # The catalogue key of the name Exe AI gives it.
    title: str
    # Where the service says how it stands, starts it, stops it, and reads
    # its log.
    status: str
    start: str
    stop: str
    log: str


SERVERS = (
    Server(MODEL, "modell.server", "/runner", "/runner/start", "/runner/stop", "/runner/log"),
    Server(
        "agent", "agentserver.titel", "/agentenmodell", "/agentenmodell/start",
        "/agentenmodell/stop", "/agentenmodell/log",
    ),
    Server(
        "embedding", "einbettungsserver.titel", "/einbettungsserver",
        "/einbettungsserver/start", "/einbettungsserver/stop", "/einbettungsserver/log",
    ),
    Server(
        "speech", "sprachserver.titel", "/sprachserver", "/sprachserver/start",
        "/sprachserver/stop", "/sprachserver/log",
    ),
    Server(
        "cleanup", "bereinigungsserver.titel", "/bereinigungsserver",
        "/bereinigungsserver/start", "/bereinigungsserver/stop", "/bereinigungsserver/log",
    ),
    Server(
        IMAGE, "bildserver.titel", "/bild/turbo", "/bild/turbo/start", "/bild/turbo/stop",
        "/bild/server/log",
    ),
)


@dataclass
class Standing:
    """How a server stands, as the service says it now."""

    running: bool = False
    file: str | None = None
    port: int | None = None
    memory: float | None = None
    # The files of its folder, each with its size in GB as the service
    # names it.
    files: list[tuple[str, Any]] = field(default_factory=list)
    # Whether the service offers to look for a newer program.
    updatable: bool = False
    # Whether the service says the server's program is not on the machine.
    program_missing: bool = False


def size_text(texts: Texts, size: Any) -> str:
    """A size as the catalogue words it, with a plain space: the one the
    catalogue holds is a no-break space, which a terminal draws as a box."""
    if size is None:
        return ""
    return texts.t("modell.gb", zahl=size).replace("\u00a0", " ")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _standing(
    ctx: Context, server: Server, *, files: bool = False, program: bool = False
) -> Standing:
    """How ``server`` stands. The image server's files and the word whether
    its program is there are a request of their own, made only where
    ``files`` or ``program`` asks for them."""
    state = ctx.client.get(server.status)
    state = state if isinstance(state, dict) else {}
    if server.word == IMAGE:
        running = state.get("zustand") in _IMAGE_RUNNING
        model = state.get("modell")
        listing = _image_listing(ctx) if files or program else {}
        return Standing(
            running=running,
            file=model if running and isinstance(model, str) else None,
            files=_image_files(listing) if files else [],
            # The program is there, so there is something to compare with.
            updatable=bool(listing.get("programm_da")),
            program_missing="programm_da" in listing and not listing["programm_da"],
        )
    running = bool(state.get("laeuft"))
    model, port, memory = state.get("modell"), state.get("port"), state.get("belegt_gb")
    listed = state.get("modelle")
    return Standing(
        running=running,
        # A server that stands still may still name the model it had.
        file=model if running and isinstance(model, str) else None,
        port=port if running and _is_number(port) else None,
        memory=memory if running and _is_number(memory) else None,
        files=[
            (entry["name"], entry.get("groesse_gb"))
            for entry in (listed if isinstance(listed, list) else [])
            if isinstance(entry, dict) and isinstance(entry.get("name"), str)
        ],
        updatable=server.word == MODEL and bool(state.get("updatable")),
    )


def _image_files(listed: dict[str, Any]) -> list[tuple[str, Any]]:
    """The models of the image server's folder, sized the way the other
    servers' files are."""
    names = listed.get("modelle")
    sizes = listed.get("sizes")
    sizes = sizes if isinstance(sizes, dict) else {}
    return [
        (name, round(sizes[name] / 1e9, 1) if _is_number(sizes.get(name)) else None)
        for name in (names if isinstance(names, list) else [])
        if isinstance(name, str)
    ]


def _cells(ctx: Context, server: Server, standing: Standing) -> Row:
    """One server as the columns of a row: its name, active or inactive,
    and — where it runs — the file, the port and the memory, as far as the
    service names them."""
    texts = ctx.texts
    return [
        ("text", texts.t(server.title)),
        (
            ("blue", texts.t("status.aktiv"))
            if standing.running
            else ("muted", texts.t("status.inaktiv"))
        ),
        ("muted", standing.file or ""),
        ("muted", "" if standing.port is None else f"{texts.t('kopf.port')} {standing.port}"),
        (
            "muted",
            "" if standing.memory is None else texts.t("modell.im_speicher", gb=standing.memory),
        ),
    ]


def _line(ctx: Context, server: Server, standing: Standing) -> str:
    """The same row as one line."""
    return "  ".join(text for _, text in _cells(ctx, server, standing) if text)


def _say(ctx: Context, server: Server, standing: Standing | None = None) -> None:
    """The server's line as the service names it now."""
    ctx.renderer.notice(_line(ctx, server, standing or _standing(ctx, server)))


def _server_of(word: str) -> Server | None:
    return next((server for server in SERVERS if server.word == word.lower()), None)


def run_command(ctx: Context, argument: str) -> None:
    """``/server``: without a word, the selection of the six servers; a word
    that names one opens its selection; ``start``, ``stop`` and ``log``
    with a server's word — or without one, then the model server — act at
    once. A word that is none of these is said, and the service is not
    asked."""
    parts = argument.split(None, 1)
    first = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""
    if not first:
        picked = _choose_server(ctx)
        if picked is not None:
            _menu(ctx, picked)
        return
    if first in ACTIONS:
        server = _server_of(rest or MODEL)
        if server is None:
            ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=rest))
            return
        {START: _start_server, STOP: _stop_server, LOG: _show_log}[first](ctx, server)
        return
    server = None if rest else _server_of(first)
    if server is None:
        ctx.renderer.error(ctx.texts.t("cli.unknown_choice", name=argument))
        return
    _menu(ctx, server)


def _choose_server(ctx: Context) -> Server | None:
    entries = [
        Entry(cells=_cells(ctx, server, standing))
        for server, standing in ((server, _standing(ctx, server)) for server in SERVERS)
    ]
    picked = ctx.asker.choose(entries)
    return None if picked is None else SERVERS[picked]


def _menu(ctx: Context, server: Server, *, newer: bool = False) -> None:
    """What can be done with one server, under its line: start or stop, its
    log, and where the service offers one, the check for a newer program —
    or, once it has said one is there, the fetch of it."""
    texts = ctx.texts
    standing = _standing(ctx, server, program=True)
    actions: list[tuple[str, str]] = [
        (STOP, texts.t("modell.server_anhalten"))
        if standing.running
        else (START, texts.t("modell.server_starten")),
        (LOG, texts.t("modell.protokoll")),
    ]
    # The image server's program: fetched where it is not there, and where
    # the system offers more than one build, chosen from them.
    if server.word == IMAGE and (standing.program_missing or _image_builds(ctx)):
        actions.append((_GET, texts.t("bildserver.generator_holen")))
    if standing.updatable:
        actions.append(
            (_UPDATE, texts.t("bildserver.generator_aktualisieren"))
            if newer
            else (_CHECK, texts.t("bildserver.nach_updates_suchen"))
        )
    picked = ctx.asker.choose(
        [Entry(cells=[("text", label)]) for _, label in actions],
        head=_line(ctx, server, standing),
    )
    if picked is None:
        return
    action = actions[picked][0]
    if action == START:
        _start_server(ctx, server)
    elif action == STOP:
        _stop_server(ctx, server)
    elif action == LOG:
        _show_log(ctx, server)
    elif action == _GET:
        with waiting(ctx) as cancel:
            fetch_image_program(ctx, cancel)
        _say(ctx, server)
    elif action == _CHECK:
        _check_program(ctx, server)
    else:
        _update_program(ctx, server)


def _start_server(ctx: Context, server: Server) -> None:
    """Asks which file of the server's folder, and starts the server with
    it. Where there is none, or the server runs already, there is nothing
    to do and its line says how it stands."""
    standing = _standing(ctx, server, files=True)
    if not standing.running and not standing.files:
        # Nothing lies in its folder: the sentence that says how to get
        # one, in place of the server's line.
        ctx.renderer.notice(ctx.texts.t("cli.no_model_in_folder"))
        return
    if standing.running:
        _say(ctx, server, standing)
        return
    texts = ctx.texts
    if server.word == IMAGE and standing.program_missing:
        # The program first: the window does not let the server start
        # without it either.
        with waiting(ctx) as cancel:
            if not fetch_image_program(ctx, cancel):
                return
    picked = ctx.asker.choose(
        [
            Entry(cells=[("text", name), ("muted", size_text(texts, size))])
            for name, size in standing.files
        ]
    )
    if picked is None:
        return
    with waiting(ctx) as cancel:
        file = standing.files[picked][0]
        started = (
            _start_image(ctx, file, cancel)
            if server.word == IMAGE
            else _start(ctx, server.start, file, cancel, fetches=True)
        )
        if not started:
            return
    _say(ctx, server)


def _stop_server(ctx: Context, server: Server) -> None:
    standing = _standing(ctx, server)
    if standing.running:
        ctx.client.post(server.stop)
    _say(ctx, server)


def _show_log(ctx: Context, server: Server) -> None:
    """The lines the service names, into the history; where it names none,
    the server's line."""
    log = ctx.client.get(server.log)
    lines = [str(line) for line in log] if isinstance(log, list) else []
    if not lines:
        _say(ctx, server)
        return
    for line in lines:
        ctx.renderer.shell_line(line)


def _check_program(ctx: Context, server: Server) -> None:
    """Asks the service whether a newer build of the program is there: up to
    date is said; a newer one brings the server's selection again with the
    fetch in the check's place; any other answer says nothing."""
    path = f"{IMAGE_PROGRAM}/aktualisierung" if server.word == IMAGE else "/runner/programm/aktualisierung"
    answer = ctx.client.get(path)
    if not isinstance(answer, dict):
        return
    if answer.get("aktuell"):
        ctx.renderer.notice(ctx.texts.t("bildserver.aktuell"))
    elif answer.get("verfuegbar"):
        _menu(ctx, server, newer=True)
    elif answer.get("unreadable"):
        ctx.renderer.notice(ctx.texts.t("bildserver.updates_nicht_pruefbar"))


def _update_program(ctx: Context, server: Server) -> None:
    with waiting(ctx) as cancel:
        if server.word == IMAGE:
            fetched = _fetch_program(
                ctx, cancel, newest=True, path=IMAGE_PROGRAM, word_key="bildserver.generator_laedt"
            )
        else:
            fetched = _fetch_program(ctx, cancel, newest=True)
        if not fetched:
            return
    _check_program(ctx, server)


def overview(ctx: Context) -> tuple[str, list[Row]]:
    """What ``/status`` writes: the line of the head — the program, its
    version and the address — and below it, row by row, the memory where the
    service names it, the model in use with how its server stands, and the
    six servers as ``/server`` shows them."""
    texts = ctx.texts
    title = texts.t("cli.titel")
    version = ctx.session.health.get("version")
    standing = [f"{title} {version}" if version else title, ctx.client.address]
    head = f" {glyphs.glyph('separator')} ".join(standing)
    rows: list[Row] = []
    memory = ctx.client.get("/system/speicher")
    memory = memory if isinstance(memory, dict) else {}
    used, total = memory.get("belegt_gb"), memory.get("gesamt_gb")
    if _is_number(used) and _is_number(total):
        both = size_text(texts, f"{round(used)}/{round(total)}")
        rows.append([("muted", texts.t("kopf.speicher")), ("text", both)])
    name = ctx.status.model_name()
    if name:
        row: Row = [("muted", texts.t("modell.titel")), ("text", name)]
        word = _model_state(ctx)
        if word is not None:
            row.append(word)
        rows.append(row)
    for server in SERVERS:
        rows.append(_cells(ctx, server, _standing(ctx, server)))
    # Every row as wide as the widest: a grid takes its columns from what
    # the rows bring, and a short row before a wider one would shift.
    width = max(len(row) for row in rows)
    return head, [row + [("muted", "")] * (width - len(row)) for row in rows]


def _model_state(ctx: Context) -> tuple[str, str] | None:
    """How the server behind the model in use stands, in the word the
    status line gives it — nothing where the service lists no such model."""
    entry = next(
        (model for model in _models(ctx) if model.get("id") == ctx.session.endpoint_id), None
    )
    state = entry.get("server_state") if entry else None
    found = {
        ACTIVE: ("blue", "kopf.server_active"),
        IDLE: ("green", "kopf.bereit"),
        OFFLINE: ("muted", "kopf.server_aus"),
    }.get(state)
    return None if found is None else (found[0], ctx.texts.t(found[1]))
