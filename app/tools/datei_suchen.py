"""The search tool — `search_files`.

Searching used to require the shell (`grep` through `run_command`). A
research agent is exactly the kind that should NOT carry the shell — a page
it reads can talk it into commands. This tool gives it the one thing it
actually needs: find a pattern in the shared folders, nothing else.

Narrow on purpose: no replace, no execution, no reach beyond the boundary in
``grenzen.py``. The result is capped — a search that matches everything
teaches the model to narrow the pattern, not to read a wall of text.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.tools import grenzen
from app.tools.mcp_client import MCPWerkzeug

SERVER_NAME = "shell"
WERKZEUG_NAME = "search_files"

# Where the result stops. Enough to see whether the pattern was right, far
# from enough to fill the context.
MAX_TREFFER = 100

# How many files one search may open. A folder with a build tree in it would
# otherwise turn one call into minutes of disk work.
MAX_DATEIEN = 5_000

# Files above this are skipped, named in the result. Text people search is
# small; anything bigger is a log or a dump and needs a narrower path.
MAX_DATEI_BYTES = 2_000_000

# How much of one matched line survives. A minified file is one line long.
MAX_ZEILE_ZEICHEN = 300

# How much of the start decides whether a file is text at all — same probe as
# read_file: a null byte means no line has meaning.
PROBE_BYTES = 4096

# Folders no search wants to see: dependency trees and VCS internals bury
# every real match. Skipped by name, said so in the description.
UEBERSPRUNGEN = frozenset({".git", "node_modules", "__pycache__"})


def werkzeug_beschreibung() -> MCPWerkzeug:
    return MCPWerkzeug(
        name=WERKZEUG_NAME,
        beschreibung=(
            "Searches text files for a pattern and returns the matching lines "
            "as file:line:text.\n"
            "Works inside the shared folders — relative paths resolve against "
            "the first one, or against a private working folder when none is "
            "shared.\n"
            "The pattern is a regular expression; if it does not parse, it is "
            "searched literally. Case-insensitive unless case_sensitive is "
            "set.\n"
            f"The result stops at {MAX_TREFFER} matches — narrow the pattern "
            "or the path rather than reading a cut-off list. Binary files are "
            "skipped, and so are .git, node_modules and __pycache__ folders."
        ),
        schema={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": 'Pattern to search for, e.g. "TODO" or "def \\w+_handler".',
                },
                "path": {
                    "type": "string",
                    "description": (
                        "File or folder to search. Defaults to the first shared folder, or "
                        "the private working folder if none is shared."
                    ),
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "Match case exactly. Default: false.",
                },
            },
            "required": ["pattern"],
        },
        server=SERVER_NAME,
    )


def aussenpfad(argumente: dict[str, Any], ordner: list[str]) -> str | None:
    return grenzen.aussenpfad(argumente, ordner)


def braucht_bestaetigung(argumente: dict[str, Any], ordner: list[str]) -> bool:
    return aussenpfad(argumente, ordner) is not None


def _muster(argumente: dict[str, Any]) -> re.Pattern[str]:
    roh = str(argumente.get("pattern") or "")
    flags = 0 if bool(argumente.get("case_sensitive")) else re.IGNORECASE
    try:
        return re.compile(roh, flags)
    except re.error:
        # A model that meant "index[0]" literally should not be punished for
        # not escaping it — an unparseable pattern is searched as written.
        return re.compile(re.escape(roh), flags)


def _dateien(
    wurzel: Path, private: Callable[[Path], bool] | None = None
) -> tuple[list[Path], bool]:
    """Every searchable file under the root, and whether the walk was cut off.
    A private place of the program is walked past, never into."""
    if wurzel.is_file():
        return [wurzel], False
    dateien: list[Path] = []

    def hinein(ordner: Path) -> bool:
        try:
            eintraege = sorted(ordner.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return True
        for eintrag in eintraege:
            if len(dateien) >= MAX_DATEIEN:
                return False
            if eintrag.is_symlink():
                continue
            # Folders are asked, and the named files beside the settings; any
            # other file is private only through the folder it lies in.
            if (
                private is not None
                and (eintrag.is_dir() or eintrag.name in grenzen.PRIVATE_FILES)
                and private(eintrag)
            ):
                continue
            if eintrag.is_dir():
                if eintrag.name in UEBERSPRUNGEN:
                    continue
                if not hinein(eintrag):
                    return False
            elif eintrag.is_file():
                dateien.append(eintrag)
        return True

    vollstaendig = hinein(wurzel)
    return dateien, not vollstaendig


def _durchsuchbar(datei: Path) -> bool:
    """Text and small enough — everything else is skipped without a word.

    Silently on purpose: naming every skipped binary would drown the matches
    the caller actually asked for.
    """
    try:
        if datei.stat().st_size > MAX_DATEI_BYTES:
            return False
        with datei.open("rb") as offen:
            probe = offen.read(PROBE_BYTES)
    except OSError:
        return False
    return b"\0" not in probe


async def ausfuehren(
    argumente: dict[str, Any], ordner: list[str], data_dir=None,
    private: Callable[[Path], bool] | None = None,
) -> str:
    roh = str(argumente.get("pattern") or "").strip()
    if not roh:
        raise grenzen.GrenzeVerletzt("No pattern provided.")

    pfad = str(argumente.get("path") or "").strip()
    if pfad:
        wurzel = grenzen.ziel(pfad, ordner, data_dir)
    else:
        if not ordner:
            raise grenzen.GrenzeVerletzt(grenzen.OHNE_ORDNER)
        wurzel = grenzen.wurzeln(ordner)[0]
    if not wurzel.exists():
        raise grenzen.GrenzeVerletzt(grenzen.missing(wurzel, ordner, data_dir))

    muster = _muster(argumente)
    if private is None:
        private = grenzen.private_check(ordner, data_dir)
    dateien, dateien_abgeschnitten = _dateien(wurzel, private)

    treffer: list[str] = []
    abgeschnitten = False
    basis = wurzel if wurzel.is_dir() else wurzel.parent
    for datei in dateien:
        if not _durchsuchbar(datei):
            continue
        try:
            text = datei.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            name = str(datei.relative_to(basis))
        except ValueError:
            name = str(datei)
        for nummer, zeile in enumerate(text.splitlines(), start=1):
            if not muster.search(zeile):
                continue
            if len(treffer) >= MAX_TREFFER:
                abgeschnitten = True
                break
            inhalt = zeile.strip()
            if len(inhalt) > MAX_ZEILE_ZEICHEN:
                inhalt = inhalt[:MAX_ZEILE_ZEICHEN] + "…"
            treffer.append(f"{name}:{nummer}: {inhalt}")
        if abgeschnitten:
            break

    if not treffer:
        rand = ""
        if dateien_abgeschnitten:
            rand = f"\n(search stopped after {MAX_DATEIEN} files; narrow the path)"
        return f"No matches for the pattern in {wurzel}.{rand}"

    kopf = f"{len(treffer)} match{'es' if len(treffer) != 1 else ''} in {wurzel}"
    if abgeschnitten:
        kopf += f" (stopped at {MAX_TREFFER}; narrow the pattern or path)"
    elif dateien_abgeschnitten:
        kopf += f" (search stopped after {MAX_DATEIEN} files; narrow the path)"
    return "\n".join([kopf, *treffer])
