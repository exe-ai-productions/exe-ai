# PyInstaller build description — one file on macOS, one folder on Windows.
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
    *_gefiltert(WURZEL / "skills", "skills"),
    # Shipped agents, the same two-layer rule as the skills: this folder is
    # replaced by every update, the user's prompts/agenten/ never is, and a
    # same-named user file wins (app/agenten.py).
    *_gefiltert(WURZEL / "agenten", "agenten"),
    *_gefiltert(WURZEL / "mcp", "mcp"),
    # prompts/ ships nothing — everything under it (memory, system prompt,
    # the user's own agents and skills) is written into the user's OWN data
    # folder, never read from here (app/config.py's ``pfad()``), and every
    # piece the program needs on a first start creates itself there: the
    # reminder agent (app/erinnerungsagent.py:37), the memory and system
    # prompt files (app/config.py:375, :387), both on demand. Shipping this
    # folder was pure risk for no reader on the other end (Schritt 6).
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

# One file on macOS, where the bundle below wraps it; a FOLDER on Windows.
# The one-file build there runs as two processes and unpacks itself into
# %TEMP%\_MEIxxxxxx on every start — measured in a Windows VM: 2.6 seconds,
# and 66 MB left behind after every hard end — while the folder build runs as
# one process and unpacks nothing. The Electron shell ships that folder beside
# itself and starts the exe inside it (fenster-electron/main.js, dienstpfad).
ONE_FILE = sys.platform != "win32"

exe = EXE(
    pyz,
    analyse.scripts,
    # In the one-file build everything rides inside the exe; in the folder
    # build COLLECT below lays it out beside the exe instead.
    analyse.binaries if ONE_FILE else [],
    analyse.datas if ONE_FILE else [],
    [],
    exclude_binaries=not ONE_FILE,
    # The name the service binary carries. On Windows this is what the Task
    # Manager and the process list read — it follows the product name, not the
    # old one. On macOS the binary hides inside the .app below and this name
    # never shows; the user's data folder is a fixed string in
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

# The folder build: the exe above, and beside it everything it needs. Its name
# is the folder's name, and with it the path the shell starts — dist/Exe AI/
# Exe AI.exe (the shell's dienstpfad()).
if not ONE_FILE:
    coll = COLLECT(
        exe,
        analyse.binaries,
        analyse.datas,
        strip=False,
        upx=False,
        name="Exe AI",
    )

# macOS gets a real application folder around the same file: an icon, a
# name, and a double click that opens no terminal window. The service has
# no window of its own, so the bundle stays out of the Dock — the browser
# is the window, and a dockless background program cannot sit there
# bouncing forever.
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
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
