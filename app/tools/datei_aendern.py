"""The edit tool — `edit_file`.

Changing one passage without rewriting the whole file. The old text has to
match exactly once: no match means the model is looking at something it has
not read, several matches mean it does not know which one it is changing.
Both are refused, and the answer says which of the two it was — that is the
difference between a model that fixes its call and one that guesses again.
"""

from __future__ import annotations

from typing import Any

from app.tools import aenderungsblock, grenzen
from app.tools.mcp_client import MCPWerkzeug

SERVER_NAME = "shell"
WERKZEUG_NAME = "edit_file"


def werkzeug_beschreibung() -> MCPWerkzeug:
    return MCPWerkzeug(
        name=WERKZEUG_NAME,
        beschreibung=(
            "Replaces one passage in a text file. old_text has to appear exactly "
            "once, so give enough surrounding lines to make it unique — the call "
            "is refused if it appears twice.\n"
            "Read the file first: the text has to match the file character for "
            "character, indentation included.\n"
            "Works inside the shared folders — relative paths resolve against "
            "the first one, or against a private working folder when none is "
            "shared."
        ),
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": 'File to edit, e.g. "notes/todo.md".',
                },
                "old_text": {
                    "type": "string",
                    "description": "The exact passage currently in the file.",
                },
                "new_text": {
                    "type": "string",
                    "description": "Replacement text. An empty value deletes the passage.",
                },
            },
            "required": ["path", "old_text", "new_text"],
        },
        server=SERVER_NAME,
    )


CRLF = "\r\n"
LF = "\n"


def line_ending(text: str) -> str:
    """The line ending the file uses, read the way an editor reads it: more
    than half of the line ends are ``\\r\\n``, then CRLF — otherwise LF. A
    file with no line end at all is an LF file."""
    crlf = text.count(CRLF)
    lf = text.count(LF) - crlf
    return CRLF if crlf > lf else LF


def aussenpfad(argumente: dict[str, Any], ordner: list[str]) -> str | None:
    return grenzen.aussenpfad(argumente, ordner)


def braucht_bestaetigung(argumente: dict[str, Any], ordner: list[str]) -> bool:
    return aussenpfad(argumente, ordner) is not None


async def ausfuehren(argumente: dict[str, Any], ordner: list[str], data_dir=None) -> str:
    roh = str(argumente.get("path") or "").strip()
    if not roh:
        raise grenzen.GrenzeVerletzt("No path provided.")
    alt = argumente.get("old_text")
    if not alt:
        raise grenzen.GrenzeVerletzt("No old_text provided; there is nothing to search for.")
    alt = str(alt)
    neu = str(argumente.get("new_text") or "")

    ziel = grenzen.ziel(roh, ordner, data_dir)
    if not ziel.exists():
        raise grenzen.GrenzeVerletzt(grenzen.missing(ziel, ordner, data_dir))
    if ziel.is_dir():
        raise grenzen.GrenzeVerletzt(f"'{ziel}' is a folder, not a file.")

    try:
        # Read with the line ends as they stand in the file (``newline=""``
        # keeps them): the ending is read off the file and written back the
        # same, so a file that had \r\n keeps \r\n on every line, the new
        # lines included. Searching and the change block work on the text
        # with \n alone, the way the model sees a file.
        with ziel.open(encoding="utf-8", newline="") as datei:
            roh = datei.read()
    except (OSError, UnicodeDecodeError) as fehler:
        raise grenzen.GrenzeVerletzt(f"'{ziel}' could not be read ({fehler}).") from fehler
    ending = line_ending(roh)
    text = roh.replace(CRLF, LF)
    alt = alt.replace(CRLF, LF)
    neu = neu.replace(CRLF, LF)

    treffer = text.count(alt)
    if treffer == 0:
        raise grenzen.GrenzeVerletzt(
            f"old_text was not found in '{ziel}'. Read the file and copy the passage exactly, "
            "including whitespace."
        )
    if treffer > 1:
        raise grenzen.GrenzeVerletzt(
            f"old_text occurs {treffer} times in '{ziel}'. Include more surrounding lines to "
            "identify a unique match."
        )

    zeile = text[: text.index(alt)].count("\n") + 1
    nachher = text.replace(alt, neu, 1)
    try:
        # The file's own ending on every line, and nothing translated on the
        # way out (``newline=""``, see app/tools/datei_schreiben.py): Windows
        # would otherwise write \r\n into a file that had \n.
        ziel.write_text(nachher.replace(LF, ending), encoding="utf-8", newline="")
    except OSError as fehler:
        raise grenzen.GrenzeVerletzt(f"'{ziel}' could not be written ({fehler}).") from fehler

    antwort = f"Changed {ziel} at line {zeile}."
    block = aenderungsblock.bauen(text, nachher)
    if block:
        antwort += "\n\n" + block
    return antwort
