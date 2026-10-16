#!/usr/bin/env python3
"""The one program, in whichever role it was asked for.

Packaged into a single file there is no interpreter left to start a helper
with — so the program is its own helper. Called plainly it serves the
terminal and opens the interface; called with ``--serve`` it serves without
opening anything, for the terminal client that started it and for machines
without a window; called with ``--mcp <name>`` it becomes the tool server it
would otherwise have started as a separate script; called with ``--cli`` it
is the terminal client itself — the command ``exe`` on the path.

That is why this file exists at all and why it stays this short: it is the
only place that decides which of the four the program is going to be, and
it must decide before anything heavy is imported.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Packaged without a console — the normal case on Windows, where a double
# click opens no terminal — Python hands out None for the standard streams
# instead of a file. Everything that asks a stream a question then dies on
# it: uvicorn's log formatter asks isatty() before the service ever starts.
# A sink costs nothing and keeps every later import honest, so it happens
# here, before anything heavy is imported.
if sys.stdout is None or sys.stderr is None:
    import os

    _leerlauf = open(os.devnull, "w")
    if sys.stdout is None:
        sys.stdout = _leerlauf
    if sys.stderr is None:
        sys.stderr = _leerlauf

# The tool servers live next to each other and import each other by plain
# name, exactly as they do when started as separate scripts.
WURZEL = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
for ordner in (WURZEL, WURZEL / "mcp"):
    if str(ordner) not in sys.path:
        sys.path.insert(0, str(ordner))

# Which name reaches which server. A list and not a guess from the name: a
# switch that accepts anything would let a command line pick what runs.
MCP_SERVER = {
    "websuche": "ddgs_server",
    "searxng": "searxng_server",
}


def _mcp_bedienen(name: str) -> int:
    modul_name = MCP_SERVER.get(name)
    if modul_name is None:
        print(f"Unknown tool server: {name}", file=sys.stderr)
        return 2

    import importlib

    import mcp_schleife

    modul = importlib.import_module(modul_name)
    mcp_schleife.starten(
        name, "0.1.0", modul.WERKZEUGE, modul.werkzeug_ausfuehren
    )
    return 0


def _voice_bedienen() -> int:
    """The kept voice, in a process of its own: the program is its own
    voice process (app/voice_service.py starts it with ``--voice``)."""
    from app.voice_worker import main as voice_main

    return voice_main()


def _cli_bedienen(argumente: list[str]) -> int:
    """The terminal client, in this process: the command ``exe`` hands its
    arguments here, and the client takes them as its own command line."""
    from cli.main import main as cli_main

    return cli_main(argumente)


def _ist_cli_programm() -> bool:
    """Packaged for Windows, the client is a program of its own name beside
    the service's: ``exe.exe``, a console program, started by the command on
    the path and by the Store's alias — which starts it by name and cannot
    add a switch. So there the name decides; everywhere else ``--cli`` does,
    and a program called anything else is never the client by name."""
    if not getattr(sys, "frozen", False):
        return False
    return Path(sys.executable).stem.lower() == "exe"


def _orte_zeigen() -> int:
    """Where this program keeps things — asked more often than one expects.

    A packaged program hides its folders by design, and the first question
    when something is missing is always the same one.
    """
    from app import paketierung

    print(f"frozen: {paketierung.ist_eingefroren()}")
    print(f"program:    {paketierung.programmpfad()}")
    print(f"mitgeliefert:{paketierung.ressourcen()}")
    print(f"own data:    {paketierung.daten()}")
    return 0


def _antwortet(port: int, host: str = "127.0.0.1") -> bool:
    """Is something already serving on that port, on the address the service
    binds to (a wildcard is reached on loopback)?"""
    import socket

    from app.tools.aufbau import dial_host

    erreicht = dial_host(host)
    familie = socket.AF_INET6 if ":" in erreicht else socket.AF_INET
    with socket.socket(familie) as verbindung:
        verbindung.settimeout(0.4)
        try:
            return verbindung.connect_ex((erreicht, port)) == 0
        except OSError:
            return False


def _browser_oeffnen(port: int, host: str = "127.0.0.1") -> None:
    """Opens the interface once the service answers.

    Started by a double click, the program has to show something — a window
    that only prints log lines looks like a program that failed. Waiting for
    the port and not for a fixed number of seconds: a first start sets up a
    database and takes longer than a second one.

    Preferably as a window of its own (app/appfenster.py); the plain
    browser tab is the fallback for machines without one.
    """
    import os
    import time
    import webbrowser

    from app.appfenster import oeffnen
    from app.tools.aufbau import service_url

    # The native shell sets this when it starts the service as its sidecar:
    # the shell already is the window, a second one would greet every user
    # twice.
    if os.environ.get("EXE_AI_TERMINAL_HEADLESS"):
        return

    ende = time.time() + 30
    while time.time() < ende:
        if _antwortet(port, host):
            adresse = f"{service_url(host, port)}/app/"
            if not oeffnen(adresse):
                webbrowser.open(adresse)
            return
        time.sleep(0.3)


def _terminal_bedienen(*, with_window: bool = True) -> int:
    """Serves. With the window: opens the interface once the service
    answers. Without it (``--serve``): the service alone, on this terminal,
    for whoever started it that way — a terminal client, a service file."""
    import threading

    import uvicorn

    from app.config import get_config

    konfiguration = get_config()
    port = konfiguration.app.port
    host = konfiguration.app.host

    # A second double click should not start a second service and fail on the
    # port. It brings the window forward instead — which is what somebody
    # clicking again actually wants. Asked to serve alone, there is nothing
    # to bring forward: a service is there already, and this one ends.
    if _antwortet(port, host):
        if not with_window:
            print(f"A service is already listening on port {port}.", file=sys.stderr)
            return 1
        _browser_oeffnen(port, host)
        return 0

    if with_window:
        threading.Thread(target=_browser_oeffnen, args=(port, host), daemon=True).start()
    uvicorn.run(
        "app.main:app",
        host=konfiguration.app.host,
        port=port,
        reload=False,
        # On SIGTERM (the window closing sends one) do not hang on a
        # half-minute request still drawing a picture: cut it after a few
        # seconds and run the shutdown, which is what stops the model,
        # embedding and image servers. Without this, closing the window during
        # a draw could time out and hard-kill the service, orphaning them.
        timeout_graceful_shutdown=3,
    )
    return 0


def main(argumente: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argumente is None else argumente)
    if argv and argv[0] == "--wo":
        return _orte_zeigen()
    if argv and argv[0] == "--mcp":
        if len(argv) < 2:
            print("--mcp braucht einen Namen", file=sys.stderr)
            return 2
        return _mcp_bedienen(argv[1])
    if argv and argv[0] == "--voice":
        return _voice_bedienen()
    if argv and argv[0] == "--serve":
        return _terminal_bedienen(with_window=False)
    # After the service's own switches: the client program starts the
    # service with ``--serve`` from its own file, and that start must not
    # be taken for a client by its name.
    if argv and argv[0] == "--cli":
        return _cli_bedienen(argv[1:])
    if _ist_cli_programm():
        return _cli_bedienen(argv)
    return _terminal_bedienen()


if __name__ == "__main__":
    raise SystemExit(main())
