"""Starts the terminal client: reads the arguments, finds the service,
builds the parts and hands over to the screen.

Where no service answers at an address of this machine, the client starts
one without a window and attaches to it; the service outlives the client.
At any other address the client only ever connects: one sentence names the
address, and the client ends. ``service`` starts, runs, stops and asks after
the service; ``install`` places the command on the path; a command of the
chat — ``theme``, ``model`` — runs from outside it, writes its result and
ends; ``--version`` and ``--help`` need no service at all.
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn, TextIO

import httpx

from cli import (
    chat,
    commands,
    dialogs,
    events,
    install,
    outside,
    prefs,
    render,
    service,
    status,
    themes,
)
from cli.app import CliApp, LeaveAsked
from cli.client import CONNECT_SECONDS, ServiceClient, ServiceError, ServiceUnreachable
from cli.interfaces import Context
from cli.texts import Texts, available_languages, resolve_language

# Where the service listens out of the box.
DEFAULT_ADDRESS = "http://127.0.0.1:8090"

# What the program is called on the command line.
PROGRAM = "exe"

# How long leaving waits for a thread the service still holds: as long as
# the service gets to take a connection. A service that stays silent for
# that long counts as gone, here as there.
LEAVE_WAIT_SECONDS = CONNECT_SECONDS

# The words that make the program do something other than open a chat: the
# service with the four things it is told to do, and the link on the path.
# A command of the chat is one as well, without its slash.
SERVICE = "service"
START = "start"
RUN = "run"
STOP = "stop"
STATUS = "status"
SERVICE_WORDS = (START, RUN, STOP, STATUS)
INSTALL = "install"
# The command that writes the program's own help, as ``--help`` does.
HELP = "help"
# The command of the chat that has no result of its own to write: it opens
# a new chat, and from outside that is the client itself.
NEW = "new"

# Where the version stands — the one place the service reads it from as
# well, read here as a file so that none of the service's code is loaded.
VERSION_FILE = Path(__file__).resolve().parent.parent / "app" / "__init__.py"
_VERSION_PATTERN = re.compile(r'^__version__\s*=\s*"([^"]*)"', re.MULTILINE)


def version() -> str:
    """The program's version, or an empty string where the file that holds
    it is out of reach."""
    try:
        found = _VERSION_PATTERN.search(VERSION_FILE.read_text(encoding="utf-8"))
    except OSError:
        return ""
    return found.group(1) if found else ""


class _Refused(Exception):
    """The parser turned an argument down; its own words say why."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # The parser prints its usage line and its own sentence, in English
        # whatever language was asked for. Both are left to the client.
        raise _Refused(message)


def _arguments(argv: Sequence[str] | None) -> tuple[argparse.Namespace, list[str]]:
    """What was typed, and the words that no switch or command of the
    client takes — in the order they came.

    Help is not left to the parser, and neither is a refusal: their
    sentences come from the catalogue in the language that was asked for,
    which is only known once the arguments are read. A word or a value it
    cannot judge by itself is only recorded here and judged by
    ``_refusal``. A switch is taken only as it is spelled out in the help:
    no beginning of one stands for it."""
    parser = _Parser(prog=PROGRAM, add_help=False, allow_abbrev=False)
    parser.add_argument("command", nargs="?")
    parser.add_argument("--url")
    parser.add_argument("--lang")
    # The switch carries the word the sentences use. Inside the client the
    # choice keeps the name it is remembered under.
    parser.add_argument("--theme", dest="look")
    parser.add_argument("--chat")
    # The file holding a password, never the word itself: an argument shows
    # in every process listing. For ``serve`` the password the service is
    # to demand; for a remote address the one it asks for.
    parser.add_argument("--password-file", type=Path)
    parser.add_argument("--version", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    return parser.parse_known_args(argv)


def _replace_what_cannot_be_written() -> None:
    """Sets the program's two outputs to replace a character they cannot
    encode instead of failing on it. A console that is not in UTF-8 — or an
    output redirected into something narrower — cannot take every character
    of a chat, and one such character must not end the client."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            # An output set in place of the program's own: it writes as it
            # was made to.
            continue
        with contextlib.suppress(ValueError, OSError):
            reconfigure(errors="replace")


def _help_entries(texts: Texts) -> list[tuple[str, str] | None]:
    """The commands and the switches with their sentences, a ``None``
    between the two groups."""
    return [
        *commands.outside_entries(texts),
        (f"{SERVICE} {START}", texts.t("cli.help_service_start")),
        (f"{SERVICE} {RUN}", texts.t("cli.help_serve")),
        (f"{SERVICE} {STOP}", texts.t("cli.help_stop")),
        (f"{SERVICE} {STATUS}", texts.t("cli.help_service_status")),
        (INSTALL, texts.t("cli.help_install")),
        None,
        ("--url", texts.t("cli.help_url", address=DEFAULT_ADDRESS)),
        ("--lang", texts.t("cli.help_lang", codes=", ".join(available_languages()))),
        ("--theme", texts.t("cli.help_theme", names=", ".join(themes.available()))),
        ("--chat", texts.t("cli.help_chat")),
        ("--password-file", texts.t("cli.help_password_file")),
        ("--version", texts.t("cli.help_version")),
        ("--help", texts.t("cli.help_help")),
    ]


def _help_line(texts: Texts, name: str) -> str | None:
    """The line ``--help`` prints for one command or switch; ``None`` for a
    word the help does not name."""
    entries = [entry for entry in _help_entries(texts) if entry is not None]
    width = max(len(entry[0]) for entry in entries)
    sentence = next((sentence for entry_name, sentence in entries if entry_name == name), None)
    return None if sentence is None else f"  {name.ljust(width)}  {sentence}"


def help_text(texts: Texts) -> str:
    """What ``--help`` prints: the usage line, the commands, the switches —
    each with its sentence from the catalogue."""
    lines = [texts.t("cli.help_usage", program=PROGRAM), "", texts.t("cli.help_commands")]
    for entry in _help_entries(texts):
        if entry is None:
            lines.extend(["", texts.t("cli.help_options")])
        else:
            lines.append(_help_line(texts, entry[0]) or "")
    return "\n".join(lines)


def _refusal(args: argparse.Namespace, left_over: list[str], texts: Texts) -> str | None:
    """What is wrong with what was typed, in the catalogue's words: a
    switch or a command the client does not have, or a value a switch does
    not take — then below the sentence the line the help gives that
    switch. ``None`` where all of it is understood."""
    for word in left_over:
        if word.startswith("-"):
            return texts.t("cli.unknown_option", name=word.split("=", 1)[0], program=PROGRAM)
    command = args.command
    if command is not None:
        unknown = _unknown_word(command, left_over, texts)
        if unknown is not None:
            return unknown
    for switch, value, known in (
        ("--lang", args.lang, available_languages()),
        ("--theme", args.look, themes.available()),
    ):
        if value is not None and value not in known:
            return "\n".join(
                (texts.t("cli.unknown_choice", name=value), _help_line(texts, switch) or "")
            )
    return None


def _unknown_word(command: str, words: list[str], texts: Texts) -> str | None:
    """What is wrong with the words after the program's name — the command
    and what follows it — or ``None`` where they stand for something the
    program does. A command of the chat takes whatever follows as its
    word; the others take nothing more, or the one of ``service``."""
    def refused(name: str) -> str:
        return texts.t("cli.unknown_outside_command", name=name, program=PROGRAM)

    if command == SERVICE:
        if not words:
            # Which four there are is said with the lines of the help.
            return "\n".join(
                _help_line(texts, f"{SERVICE} {word}") or "" for word in SERVICE_WORDS
            )
        if words[0] not in SERVICE_WORDS:
            return refused(f"{SERVICE} {words[0]}")
        return refused(words[1]) if len(words) > 1 else None
    if command == INSTALL:
        return refused(words[0]) if words else None
    if command in (name for name, _ in commands.outside_entries(texts)):
        return None
    return refused(command)


def main(
    argv: Sequence[str] | None = None,
    *,
    http: httpx.Client | None = None,
    prefs_path: Path | None = None,
) -> int:
    """Runs the client until the user leaves; the return value is the
    process's exit code.

    The keyword arguments stand in for the outside world: a ready HTTP
    client instead of a connection, and the file the choices are remembered
    in. A stand-in for the terminal itself is set the way prompt_toolkit
    provides for it, as the session the screen is created in.
    """
    _replace_what_cannot_be_written()
    remembered = prefs.load(prefs_path)
    try:
        args, left_over = _arguments(argv)
    except _Refused as refused:
        # A switch that lacks its value: its line from the help says what
        # it takes. The language asked for is not known here.
        texts = Texts(resolve_language(None, remembered.get("language")))
        named = re.search(r"argument (-[-\w]+)", str(refused))
        line = _help_line(texts, named.group(1)) if named else None
        print(line or texts.t("cli.help_usage", program=PROGRAM), file=sys.stderr)
        return 2

    language = resolve_language(args.lang, remembered.get("language"))
    texts = Texts(language)
    refusal = _refusal(args, left_over, texts)
    if refusal is not None:
        # Before anything is asked of a service, and before anything is
        # remembered.
        print(refusal, file=sys.stderr)
        return 2
    if args.help or args.command == HELP:
        # ``exe help`` writes what ``--help`` writes, without a service: the
        # chat's list of slash commands belongs to the chat.
        print(help_text(texts))
        return 0
    if args.version:
        print(version())
        return 0
    if args.command == INSTALL:
        # Needs no service and no address: it places a link on this machine.
        return install.run(texts)
    address = args.url or remembered.get("url") or DEFAULT_ADDRESS
    look = args.look or remembered.get("look")
    if look not in themes.available():
        # A remembered look this version no longer has.
        look = themes.DEFAULT_LOOK
    themes.set_look(look)

    client = ServiceClient(address, language, http=http)
    try:
        if args.command == SERVICE:
            return _service(left_over[0], client, texts, args.password_file)
        if args.command is not None:
            return _outside(
                [args.command, *left_over],
                args,
                client,
                texts,
                prefs_path,
                language=language,
                look=look,
            )
        return _run(args, client, texts, prefs_path, language=language, look=look)
    finally:
        # A client handed in belongs to whoever handed it in.
        if http is None:
            client.close()


def _service(
    word: str, client: ServiceClient, texts: Texts, password_file: Path | None
) -> int:
    """``service`` and one of its four words."""
    if word == START:
        return _service_start(client, texts, password_file)
    if word == RUN:
        return _serve(client, texts, password_file)
    if word == STOP:
        return _stop(client, texts)
    return _service_status(client, texts)


def _serve(client: ServiceClient, texts: Texts, password_file: Path | None) -> int:
    """``service run``: the service on this terminal, at the address given — any
    host, this machine's or a network's; beyond the loopback address the
    service insists on the password file — until it ends. Unless one is
    already answering there, which is said instead."""
    port = service.port_of(client.address)
    if port is None:
        # An address without a port is no address to serve at: what
        # ``--url`` takes is said, as the help says it.
        print(texts.t("cli.help_url", address=DEFAULT_ADDRESS), file=sys.stderr)
        return 2
    try:
        client.connect()
    except ServiceUnreachable:
        return service.serve(service.host_of(client.address), port, password_file)
    print(texts.t("cli.service_running", address=client.address), file=sys.stderr)
    return 1


def _stop(client: ServiceClient, texts: Texts) -> int:
    """``service stop``: ends the service at the address — one of this machine's,
    whatever address it listens at: its note lies in this machine's data
    folder, and a port on another machine has none — and says what
    happened."""
    port = service.port_of(client.address)
    if port is None:
        print(texts.t("cli.help_url", address=DEFAULT_ADDRESS), file=sys.stderr)
        return 2
    try:
        outcome = service.stop(service.host_of(client.address), port)
    except OSError as error:
        # A process that is not ours to end: the system's own words.
        print(str(error), file=sys.stderr)
        return 1
    if outcome == service.STOPPED:
        print(texts.t("cli.service_stopped", port=port))
        return 0
    if outcome == service.NOT_RUNNING:
        print(texts.t("cli.service_not_running", port=port))
        return 0
    print(texts.t("cli.service_not_stopped", port=port), file=sys.stderr)
    return 1


def _service_start(client: ServiceClient, texts: Texts, password_file: Path | None) -> int:
    """``service start``: the service in the background at the address of
    this machine, waited for until it answers; then the line ``service
    status`` writes, and the program ends while the service goes on. Not
    where one answers already, and not at an address of another machine."""
    port = service.port_of(client.address)
    if port is None:
        print(texts.t("cli.help_url", address=DEFAULT_ADDRESS), file=sys.stderr)
        return 2
    try:
        client.connect()
    except ServiceUnreachable:
        pass
    else:
        print(texts.t("cli.service_running", address=client.address), file=sys.stderr)
        return 1
    if not service.is_own(client.address):
        print(texts.t("cli.service_start_failed", address=client.address), file=sys.stderr)
        return 1
    print(texts.t("cli.service_starting", address=client.address))
    try:
        started = service.start_and_wait(client, port, password_file)
    except KeyboardInterrupt:
        # The wait was ended, and the service that was started with it.
        return 1
    if not started:
        print(texts.t("cli.service_start_failed", address=client.address), file=sys.stderr)
        return 1
    return _service_status(client, texts)


def _service_status(client: ServiceClient, texts: Texts) -> int:
    """``service status``: since when the service at the address runs —
    where it does; where it does not, that, with a code that says so."""
    port = service.port_of(client.address)
    if port is None:
        print(texts.t("cli.help_url", address=DEFAULT_ADDRESS), file=sys.stderr)
        return 2
    try:
        client.connect()
        health = client.get("/health")
    except ServiceUnreachable:
        print(texts.t("cli.service_not_running", port=port))
        return 1
    except ServiceError as error:
        print(error.detail, file=sys.stderr)
        return 1
    since = _began(health)
    if since is None:
        # A service that does not name its process says only that it is there.
        print(texts.t("cli.service_running", address=client.address))
    else:
        print(texts.t("cli.service_since", address=client.address, time=since))
    return 0


def _began(health: object) -> str | None:
    """When the process behind the service began, in the clock of this
    machine, or ``None`` where the service does not say."""
    process = health.get("process") if isinstance(health, dict) else None
    began = process.get("began") if isinstance(process, dict) else None
    if isinstance(began, bool) or not isinstance(began, (int, float)):
        return None
    try:
        stamp = datetime.fromtimestamp(began, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None
    return render.local_time(stamp)


def _outside(
    words: list[str],
    args: argparse.Namespace,
    client: ServiceClient,
    texts: Texts,
    prefs_path: Path | None,
    *,
    language: str,
    look: str,
) -> int:
    """A command of the chat, from outside it: the same handler as behind
    the slash, run against the service, its lines written out and the
    program ended. A command that opens a chat starts the client with it."""
    try:
        if not _reach(client, texts, args.password_file):
            return 1
        if client.login_required and not _sign_in(client, texts, args, prefs_path):
            return 1
        health = client.get("/health")
        models = client.get("/models")
    except ServiceUnreachable as error:
        print(texts.t("fehler.dienst_antwortet_nicht", error=error.address), file=sys.stderr)
        return 1
    except ServiceError as error:
        print(error.detail, file=sys.stderr)
        return 1

    ctx = Context(client=client, texts=texts, prefs_path=prefs_path)
    ctx.session.health = health if isinstance(health, dict) else {}
    ctx.session.models = models if isinstance(models, list) else []
    ctx.status = status.build_status(ctx)
    screen = outside.OutsideScreen()
    renderer = outside.PlainRenderer()
    ctx.screen = screen
    ctx.renderer = renderer
    ctx.asker = outside.OutsideAsker(ctx)
    ctx.blocking = True
    ctx.commands = commands.build_commands(ctx)
    try:
        _pick_model(ctx)
        _remember(ctx, args, language=language, look=look)
        ctx.commands.run("/" + " ".join(words))
    except outside.NeedsTerminal:
        print(texts.t("cli.needs_terminal", program=PROGRAM), file=sys.stderr)
        return 2
    except ServiceUnreachable as error:
        print(texts.t("fehler.dienst_antwortet_nicht", error=error.address), file=sys.stderr)
        return 1
    except ServiceError as error:
        print(error.detail, file=sys.stderr)
        return 1
    opened = screen.opened
    if opened is not None or words[0].lower() == NEW:
        # The command opens a chat: the client goes on with it, with that
        # chat or a new one.
        args.chat = str(opened.get("id")) if opened is not None else None
        return _run(args, client, texts, prefs_path, language=language, look=look)
    return 1 if renderer.failed else 0


def _reach(client: ServiceClient, texts: Texts, password_file: Path | None) -> bool:
    """Connects to the service — and where none answers at an address of
    this machine, starts one first and waits for it, for as long as the
    started service lives. ``False`` once the start failed, which has been
    said — or once the user ended the wait from the keyboard, which ended
    the started service with it and needs no sentence. Any other address
    that stays silent raises, as it always did."""
    try:
        client.connect()
        return True
    except ServiceUnreachable:
        port = service.port_of(client.address)
        if port is None or not service.is_own(client.address):
            raise
    print(texts.t("cli.service_starting", address=client.address))
    try:
        if service.start_and_wait(client, port, password_file):
            return True
    except KeyboardInterrupt:
        return False
    print(texts.t("cli.service_start_failed", address=client.address), file=sys.stderr)
    return False


def _ask_password(prompt: str) -> str | None:
    """The password typed at the terminal, without echo — or ``None`` where
    there is no terminal to ask on."""
    if not sys.stdin.isatty():
        return None
    return getpass.getpass(prompt)


def _password(args: argparse.Namespace, texts: Texts, address: str) -> str | None:
    """The password for a service that demands one: from the file named on
    the command line, else typed at the terminal. ``None`` where neither
    is there, which has been said."""
    if args.password_file is not None:
        try:
            return args.password_file.read_text(encoding="utf-8").strip()
        except OSError as error:
            print(str(error), file=sys.stderr)
            return None
    password = _ask_password(texts.t("cli.password_prompt", address=address))
    if password is None:
        print(texts.t("cli.password_hint", address=address), file=sys.stderr)
    return password


def _sign_in(
    client: ServiceClient, texts: Texts, args: argparse.Namespace, prefs_path: Path | None
) -> bool:
    """Where the service hands its key out only against a password: the key
    remembered for this address, if the service still takes it — else the
    password, asked for once, and the key it buys, remembered for the next
    start. ``False`` once that failed, which has been said."""
    remembered = prefs.load(prefs_path).get("keys") or {}
    known = remembered.get(client.address)
    if isinstance(known, str) and known:
        client.key = known
        try:
            client.get("/health")
            return True
        except ServiceError as error:
            # A key of a run that is over: the service was restarted since.
            if error.status != 401:
                raise
            client.key = None
    password = _password(args, texts, client.address)
    if password is None:
        return False
    try:
        key = client.login(password)
    except ServiceError as error:
        print(error.detail, file=sys.stderr)
        return False
    try:
        prefs.remember(prefs_path, keys={**remembered, client.address: key})
    except OSError as error:
        # Signed in all the same; that it will ask again next time is said,
        # in the system's own words.
        print(str(error), file=sys.stderr)
    return True


def _run(
    args: argparse.Namespace,
    client: ServiceClient,
    texts: Texts,
    prefs_path: Path | None,
    *,
    language: str,
    look: str,
) -> int:
    try:
        if not _reach(client, texts, args.password_file):
            return 1
        if client.login_required and not _sign_in(client, texts, args, prefs_path):
            return 1
        health = client.get("/health")
        models = client.get("/models")
    except ServiceUnreachable as error:
        print(texts.t("fehler.dienst_antwortet_nicht", error=error.address), file=sys.stderr)
        return 1
    except ServiceError as error:
        print(error.detail, file=sys.stderr)
        return 1

    ctx = Context(client=client, texts=texts, prefs_path=prefs_path)
    ctx.session.health = health if isinstance(health, dict) else {}
    ctx.session.models = models if isinstance(models, list) else []
    ctx.status = status.build_status(ctx)
    ctx.renderer = render.build_renderer(ctx)
    ctx.asker = dialogs.build_asker(ctx)
    ctx.commands = commands.build_commands(ctx)
    listener = events.build_events(ctx)
    ctx.events = listener
    app = CliApp(ctx)
    ctx.screen = app
    # A service that wants a password and no longer takes this client's key
    # ends the run: whichever thread hears it, the screen leaves.
    client.on_signed_out = app.exit

    code = 0
    restore: Callable[[], None] | None = None
    report_again = _keep_quiet_about_a_gone_terminal()
    try:
        try:
            # From here on a request to end the process leaves the way the
            # user would, whatever the start is doing: the terminal gets
            # its ground back and nobody is left reading the service.
            restore = app.leave_on_signals()
            # The look owns the terminal's ground for as long as the client
            # runs.
            themes.paint()
            # The model is chosen, and a chat asked for is entered, before
            # the head is written: the head names the model the first
            # message really goes to — the same one the status line names.
            _pick_model(ctx)
            wanted = chat.find_chat(ctx, args.chat) if args.chat else None
            if wanted is not None:
                chat.enter_chat(ctx, wanted)
            render.show_head(ctx)
            ctx.status.update(address=client.address, look=look)
            _remember(ctx, args, language=language, look=look)
            if not args.chat:
                chat.new_chat(ctx)
            elif wanted is None:
                # Nothing, or more than one chat, answers to that name;
                # which of the two has just been said, and the client ends.
                code = 1
            else:
                chat.show_history(ctx, wanted)
            if code == 0:
                ctx.events.start()
                app.run()
        except ServiceUnreachable as error:
            ctx.renderer.error(texts.t("fehler.dienst_antwortet_nicht", error=error.address))
            code = 1
        except ServiceError as error:
            ctx.renderer.error(error.detail)
            code = 1
    except LeaveAsked:
        # Asked to end during the start — or while the start was saying
        # what went wrong: the client leaves as it does after a run.
        pass
    except OSError as error:
        # The terminal went away, and whoever was writing to it failed on
        # that: a way of leaving too. Nothing else in here reads or writes
        # a device on this thread, and any other failure is one as ever.
        if not themes.went_away(error):
            raise
    finally:
        # The start is over, however it ended. Said before anything else,
        # and as a plain value: a request to end that comes right now finds
        # a client that is leaving, and is not raised into its leave.
        app.starting = False
        # A client that is leaving has nothing left to hand a request to:
        # from here on the system answers one again, as before the start.
        if restore is not None:
            restore()
        try:
            try:
                # Leaving: nothing more is asked of the service, and whoever
                # still reads one of its streams sees it end.
                client.hang_up()
                listener.stop()
            finally:
                # Whatever happened, the terminal has its ground back.
                themes.unpaint()
            # The threads that worked for this run are over before the
            # interpreter is. An interrupt from the keyboard ends the wait:
            # whatever still runs then ends with the process.
            until = time.monotonic() + LEAVE_WAIT_SECONDS
            with contextlib.suppress(KeyboardInterrupt):
                app.wait(until)
                listener.wait(until)
            # Nobody writes any more. What a terminal that is gone has not
            # taken is let go of, so that the interpreter ends without a
            # word.
            _leave_nothing_unwritten()
        finally:
            report_again()
    if client.signed_out:
        print(texts.t("cli.signed_out", address=client.address), file=sys.stderr)
        return 1
    return code


def _leave_nothing_unwritten(out: TextIO | None = None) -> None:
    """Writes out what still waits to be written to ``out`` (the standard
    output where none is named). Where the terminal behind it is gone,
    what waits can go nowhere, and the interpreter, which writes it out
    once more at its own end, would fail on it and end with a code of its
    own. So the output is then pointed at nothing — and the error output
    with it where both are the same terminal."""
    out = sys.stdout if out is None else out
    try:
        out.flush()
        return
    except OSError as error:
        if not themes.went_away(error):
            raise
    gone = [out]
    if out is sys.stdout and _same_terminal(out, sys.stderr):
        gone.append(sys.stderr)
    nothing = os.open(os.devnull, os.O_WRONLY)
    try:
        for stream in gone:
            os.dup2(nothing, stream.fileno())
            stream.flush()
    finally:
        os.close(nothing)


def _same_terminal(one: TextIO, other: TextIO) -> bool:
    try:
        return os.path.sameopenfile(one.fileno(), other.fileno())
    except (OSError, ValueError):
        # One of them is no file of the system's: a stand-in of a test.
        return False


def _keep_quiet_about_a_gone_terminal() -> Callable[[], None]:
    """A thread that fails because the terminal is gone has nothing to
    report and nobody to report it to: what the interpreter would write
    about it is dropped, every other failure of a thread is reported as
    ever. Returns what puts the former way of reporting back."""
    former = threading.excepthook

    def report(failed: threading.ExceptHookArgs) -> None:
        error = failed.exc_value
        if isinstance(error, OSError) and themes.went_away(error):
            return
        former(failed)

    threading.excepthook = report

    def report_again() -> None:
        threading.excepthook = former

    return report_again


def _pick_model(ctx: Context) -> None:
    """The model the first message goes to: the one chosen last — in the
    window or here. It stays chosen while it is not reachable, for as long
    as the service still carries its server: nothing is taken in its place,
    and the status line names it — by the name stored with the choice —
    with its server's word. The first model the service lists is taken only
    where none was chosen yet or the server of the chosen one is gone from
    the service — the order the window keeps as well. With nothing chosen
    and nothing reachable none is picked, and the service says so when
    asked. Where the list names the chosen model otherwise than the name
    stored with the choice, the stored name follows the list."""
    models = ctx.session.models
    wanted, kept_name = _last_model(ctx)
    model = next((listed for listed in models if listed.get("id") == wanted), None)
    if model is not None and wanted:
        _follow_name(ctx, wanted, kept_name, model)
    if model is None and wanted:
        model = _unreachable_choice(ctx, wanted, kept_name)
    if model is None:
        if not models:
            return
        model = models[0]
    ctx.session.endpoint_id = model.get("id")
    ctx.status.update(model_name=model.get("name"), context_window=model.get("context_tokens"))


def _follow_name(
    ctx: Context, chosen: str, kept_name: str | None, listed: dict[str, object]
) -> None:
    """Stores the choice again under the name the service's list gives the
    chosen model, where that is another one than the name stored with the
    choice. A server may run another model behind the same id, or name its
    model anew, and the stored name is what a start with the server away
    has to show. The same choice, and without a word. An entry without a
    name says nothing about it: the stored one stays. So does an entry
    whose name is only the one the configuration gives its server: that
    names the server, and the model is not what it names. The choice was
    read from the service a moment ago, so what is written is the one that
    stands there. The name is compared and sent without the blanks around
    it, the way the service keeps it — one that differed only there would be
    written at every start. A memo only, as where the model is chosen: a
    refusal is not worth stopping the start over."""
    listed_name = listed.get("name") if listed.get("name_gemeldet") is True else None
    name = listed_name.strip() if isinstance(listed_name, str) else ""
    if not name or name == kept_name:
        return
    try:
        ctx.client.put(
            f"/settings/global/{commands.LAST_MODEL_KEY}",
            json={"wert": {"id": chosen, "name": name}},
        )
    except ServiceError:
        pass


def _unreachable_choice(
    ctx: Context, wanted: str, kept_name: str | None
) -> dict[str, object] | None:
    """The chosen model while it is not among the reachable ones — ``None``
    where the service's full list no longer carries its server. Its name is
    the one stored with the choice. The full list names a server it cannot
    reach once, under its bare id and its configured name: that name is
    shown only for this very id and only where none was stored, and a model
    of a catalogue takes no name from the entry at all, because the name
    there is the server's. Where the list does not answer, nothing is known
    against the choice, and it stands."""
    try:
        carried = ctx.client.get("/models", params={"alle": "true"})
    except ServiceError:
        return {"id": wanted, "name": kept_name}
    listed = carried if isinstance(carried, list) else []
    entries = [entry for entry in listed if isinstance(entry, dict)]
    same = next((entry for entry in entries if entry.get("id") == wanted), None)
    if same is not None:
        return {
            "id": wanted,
            "name": kept_name or same.get("name"),
            "context_tokens": same.get("context_tokens"),
        }
    server = status.server_of(wanted)
    if any(status.server_of(str(entry.get("id") or "")) == server for entry in entries):
        return {"id": wanted, "name": kept_name}
    return None


def _last_model(ctx: Context) -> tuple[str | None, str | None]:
    """The model chosen last, as the service keeps it: its id and the name
    stored with it. The id is ``None`` where none was chosen yet or the
    service does not say, the name where the choice was stored without
    one."""
    try:
        resolved = ctx.client.get("/settings/resolved", params={"keys": commands.LAST_MODEL_KEY})
    except ServiceError:
        return None, None
    entry = resolved.get(commands.LAST_MODEL_KEY) if isinstance(resolved, dict) else None
    value = entry.get("wert") if isinstance(entry, dict) else None
    if not isinstance(value, dict):
        return None, None
    chosen, name = value.get("id"), value.get("name")
    if not isinstance(chosen, str) or not chosen:
        return None, None
    return chosen, name if isinstance(name, str) and name else None


def _remember(ctx: Context, args: argparse.Namespace, *, language: str, look: str) -> None:
    """Keeps what was asked for on the command line for the next start.

    Only after the service has answered: an address that reached nothing is
    not worth remembering. Not inside the window's tab: what the window
    hands the client there — its address, its theme, its language — is no
    choice of the user's own, and would stand in the way of the next start
    in a terminal.
    """
    if themes.WINDOW_VARIABLE in os.environ:
        return
    choices: dict[str, str] = {}
    if args.url:
        choices["url"] = ctx.client.address
    if args.lang:
        choices["language"] = language
    if args.look:
        choices["look"] = look
    if not choices:
        return
    try:
        prefs.remember(ctx.prefs_path, **choices)
    except OSError as error:
        # The choice holds for this run all the same; that it will not be
        # there next time is said, in the system's own words.
        ctx.renderer.error(str(error))
