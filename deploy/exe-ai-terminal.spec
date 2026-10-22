# PyInstaller build description — one folder, on every system.
#
# Run from the project root:
#
#     .venv/bin/pyinstaller deploy/exe-ai-terminal.spec
#
# What ships is everything the program only reads: the built interface, the
# translations, the shipped skills and tool servers, the example
# configuration. What the user owns — database, own settings, models, own
# skills — is deliberately NOT in here; it is created next to their other
# application data on first start (app/paketierung.py).
#
# `static/app` has to be built beforehand (`cd frontend && npm run build`),
# otherwise the program ships with an interface older than itself. There is
# no check for that here, because a build description that quietly fixes
# things hides exactly the mistake it should be showing.

import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

WURZEL = Path(SPECPATH).parent

# The one version, read where it lives — a second number here would drift.
VERSION = re.search(
    r'__version__ = "(.+)"', (WURZEL / "app" / "__init__.py").read_text()
).group(1)

# Build-machine debris a directory tuple below would otherwise carry along
# wholesale (Schritt 6) — never anything a user put there, only what a
# development checkout accumulates on its own: Finder's marker file, and
# bytecode cached for whichever Python happened to run it last. ".map" is
# a deliberate addition, not debris: the built frontend's source maps
# (frontend/vite.config.js keeps generating them, on purpose, for local
# debugging) unpack to the original source of every own file — they stay
# off the disk of anyone who did not build this themselves.
_MUELL_DATEINAMEN = {".DS_Store"}
_MUELL_ENDUNGEN = {".pyc", ".pyo", ".map"}
_MUELL_ORDNER = {"__pycache__"}


def _gefiltert(quelle: Path, ziel: str) -> list[tuple[str, str]]:
    """Packs a folder file by file rather than as a whole directory, so
    what actually sits on the machine that builds this — not just what git
    tracks — can be filtered before it ships. ``static/app`` still ships in
    full through this: it is git-ignored for an unrelated reason (built,
    not committed), not because it is anyone's private content.
    """
    eintraege = []
    for datei in sorted(quelle.rglob("*")):
        if not datei.is_file():
            continue
        rel = datei.relative_to(quelle)
        if datei.name in _MUELL_DATEINAMEN or datei.suffix in _MUELL_ENDUNGEN:
            continue
        if _MUELL_ORDNER & set(rel.parts[:-1]):
            continue
        eintraege.append((str(datei), str(Path(ziel) / rel.parent)))
    return eintraege


mitgeliefert = [
    *_gefiltert(WURZEL / "static", "static"),
    *_gefiltert(WURZEL / "app" / "locales", "app/locales"),
    # The thinking-stage catalogue. A data file, read at runtime like the
    # translations beside it — without it every model would fall back to
    # what its own server gives away, which for a cloud provider is nothing.
    *_gefiltert(WURZEL / "app" / "daten", "app/daten"),
    (str(WURZEL / "app" / "db" / "schema.sql"), "app/db"),
    # The version, as a file: the terminal client reads it from here rather
    # than importing the service (cli/main.py), and packaged, a module is
    # no file any more — this copy is the one it finds.
    (str(WURZEL / "app" / "__init__.py"), "app"),
    *_gefiltert(WURZEL / "skills", "skills"),
    # The program's own Tailscale, built beforehand by deploy/build_tailscale.sh
    # for the system this runs on. Where it was not built, the program ships
    # without it and uses the owner's, if there is one (app/tailscale.py).
    *(_gefiltert(WURZEL / "dist" / "tailscale", "tailscale") if (WURZEL / "dist" / "tailscale").is_dir() else []),
    # Shipped agents, the same two-layer rule as the skills: this folder is
    # replaced by every update, the user's prompts/agenten/ never is, and a
    # same-named user file wins (app/agenten.py).
    *_gefiltert(WURZEL / "agenten", "agenten"),
    *_gefiltert(WURZEL / "mcp", "mcp"),
    # prompts/ ships nothing — everything under it (memory, system prompt,
    # the user's own agents and skills) is written into the user's OWN data
    # folder, never read from here (app/config.py's ``pfad()``), and every
    # piece the program needs on a first start creates itself there: the
    # memory and system prompt files (app/config.py:490, :500), on demand.
    # Shipping this folder was pure risk for no reader on the other end.
    (str(WURZEL / "config.example.yaml"), "."),
    # The EXAMPLE, never the real one: the server list holds addresses, keys
    # and machines of whoever built this, and a package carries it to
    # strangers. It is git-ignored for that reason, which also means a fresh
    # checkout has no such file and the build broke here. config.py copies
    # the example into the user's folder on first start.
    (str(WURZEL / "mcp_servers.example.json"), "."),
    # The license texts for what this package ships beside its own code — a
    # legal requirement at delivery, not merely a repository convenience.
    (str(WURZEL / "THIRD_PARTY_NOTICES.md"), "."),
]

# Found by name at runtime rather than imported, so the collector cannot see
# them: the tool servers behind the --mcp switch, and uvicorn's own workers.
versteckt = [
    "ddgs_server",
    "searxng_server",
    "mcp_schleife",
    "webseite_lesen",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "app.main",
    # The machine's zone (app/wecker.py): tzlocal picks its reader by the
    # system at import time, and the Windows reader carries the table that
    # turns a registry name into the zone database's — both named here so
    # the bundle for Windows holds them whatever the analysis saw.
    "tzlocal.win32",
    "tzlocal.windows_tz",
    "tzlocal.unix",
    # The terminal client (start.py, ``--cli``): imported only once asked
    # for, and everything it draws with — prompt_toolkit, rich — rides in
    # behind it.
    "cli.main",
]

# The IANA time-zone database ships as data files that zoneinfo reads at
# runtime, not as an import — so the collector never sees them on its own.
# macOS and Linux fall back to the operating system's copy; Windows has none,
# and without these files the configured zone cannot resolve there.
mitgeliefert += collect_data_files("tzdata")

analyse = Analysis(
    [str(WURZEL / "start.py")],
    pathex=[str(WURZEL), str(WURZEL / "mcp")],
    binaries=[],
    datas=mitgeliefert,
    hiddenimports=versteckt,
    hookspath=[],
    runtime_hooks=[],
    # Test machinery has no business in a shipped program.
    excludes=["pytest", "_pytest", "PyInstaller"],
    noarchive=False,
)

pyz = PYZ(analyse.pure)

# A FOLDER, never one file. A one-file build runs as two processes and
# unpacks itself into the system's temporary folder on every start —
# measured in a Windows VM: 2.6 seconds, and 66 MB left behind after every
# hard end. On macOS the system empties those folders at night once they
# are a few days old, and a service that runs for longer loses its files
# while it runs. The folder build runs as one process and unpacks nothing.
# The Electron shell ships that folder beside itself and starts the program
# inside it (fenster-electron/main.js, dienstpfad).
exe = EXE(
    pyz,
    analyse.scripts,
    # Nothing rides inside the program itself: COLLECT below lays binaries
    # and data out beside it.
    [],
    [],
    [],
    exclude_binaries=True,
    # The name the service binary carries. It is what the Task Manager and
    # the process list read — it follows the product name, not the old one —
    # and it is the file the shell, the command on the path and `exe install`
    # address inside the folder (fenster-electron/main.js, deploy/exe,
    # cli/install.py). The user's data folder is a fixed string in
    # app/paketierung.py and does NOT ride on this, so renaming here cannot
    # strand it.
    name="Exe AI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # The program serves the browser; its own window would be a second one.
    # On Windows that means no console — a black box next to the app reads
    # as broken, and a failed start explains itself in the log files. On
    # macOS and Linux the bare binary keeps talking to whoever starts it
    # from a terminal; the double-click path goes through the app bundle
    # below, which opens no terminal to begin with.
    console=(sys.platform != "win32"),
    icon=str(WURZEL / "deploy" / "icon.ico") if sys.platform == "win32" else None,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# The folder: the program above, and beside it everything it needs. Its name
# is the folder's name, and with it the path the shell starts — dist/Exe AI/
# Exe AI, with .exe on Windows (the shell's dienstpfad()).
programs = [exe]

# On Windows a second exe in the same folder: the command on the path. The
# same program under its own name, WITH a console — the service's exe above
# has none, while the client draws into the terminal it was started from,
# and a program without a console has no terminal to draw into. One
# analysis, one folder: both share every file laid out beside them. The name
# is also the switch (start.py): the Store's alias starts the program by
# name and cannot add one. On macOS the command is the small script
# deploy/exe, which hands over to the one program with --cli.
if sys.platform == "win32":
    cli_exe = EXE(
        pyz,
        analyse.scripts,
        [],
        [],
        [],
        exclude_binaries=True,
        name="exe",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=True,
        icon=str(WURZEL / "deploy" / "icon.ico"),
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    programs.append(cli_exe)

coll = COLLECT(
    *programs,
    analyse.binaries,
    analyse.datas,
    strip=False,
    upx=False,
    name="Exe AI",
)

# macOS gets a real application folder around the same folder: an icon, a
# name, and a double click that opens no terminal window. The service has
# no window of its own, so the bundle stays out of the Dock — the browser
# is the window, and a dockless background program cannot sit there
# bouncing forever.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Exe AI Terminal.app",
        icon=str(WURZEL / "deploy" / "icon.icns"),
        bundle_identifier="net.exe-hq.exe-ai-terminal",
        version=VERSION,
        info_plist={
            "CFBundleName": "Exe AI",
            "CFBundleDisplayName": "Exe AI",
            "CFBundleShortVersionString": VERSION,
            "LSUIElement": True,
            "NSHighResolutionCapable": True,
        },
    )
