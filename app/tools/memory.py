"""The memory tool — ``memory_save``.

Built in rather than an MCP server, for the same reason as the shell tool:
the file belongs to the program, and an outside process would have to be told
where it is on every call — and anything passed as an argument can be forged
by the model.

What it can do is deliberately narrow. It appends ONE entry under one of two
headings, or replaces ONE existing entry with a new one, and called without a
text it lists the entries it holds. It cannot hand over whole file contents,
and it cannot delete: a model that can write the file in one go can also wipe
it in one go, and clearing the memory is the user's move, one button away in
the settings window.

The list is a way of its own because the model cannot rely on the memory
block in its system prompt: that block only travels where the switch for the
endpoint's side is on (app/gedaechtnis.py), while the tool is offered either
way. A model that can write but never read cannot correct anything.

An entry to replace is found by a short part of its text, not by its full
wording — the model rarely has the exact sentence in front of it. The part
has to point at ONE entry; when it points at none or at several, nothing is
written and the answer carries the entries, so the next call can aim right.

The two kinds are not decoration:

  * A **rule** changes behaviour and applies always.
  * A **fact** is knowledge and applies where it fits.

Neither asks before it is stored. There is exactly one prompt in the whole
program — the shell reaching outside the shared folders — and it is worth
something only because it is rare. A prompt that comes ten times a session
gets clicked away without reading, and then it protects nothing.

What carries that here is that the memory is **visible and reversible**: it
is one file, it stands open in the settings window, and a line can be taken
out by editing it there. Looking at it does everything a prompt would have
done, and it does it after the fact instead of in the way.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from app import atomic_file
from app.gedaechtnis import UEBERSCHRIFT_FAKTEN, UEBERSCHRIFT_REGELN
from app.tools.mcp_client import MCPWerkzeug

log = logging.getLogger(__name__)

SERVER_NAME = "memory"
WERKZEUG_NAME = "memory_save"

# Long enough for a rule with its reasoning, short enough that nobody parks a
# whole document in the file that travels with every single request.
MAX_LAENGE = 600

REGEL = "rule"
FAKTUM = "fact"

# One writer at a time. A chat and a job running overnight can hit this in the
# same second, and both do read-modify-write — without the gate one of them
# writes over what the other just added.
_schleuse = asyncio.Lock()


# What a model is told where the memory does not travel to it.
VERBORGEN = (
    "Stored entries are not shown to this model because memory is disabled for its side in "
    "the settings."
)


class MemoryVerboten(Exception):
    """The call was refused — nothing was written."""


class ErsetztNichtEindeutig(MemoryVerboten):
    """``replaces`` pointed at no entry or at several — nothing was written.

    ``eintraege`` carries the listing, for a caller whose model may see it.
    """

    def __init__(self, meldung: str, eintraege: str) -> None:
        super().__init__(meldung)
        self.eintraege = eintraege


def _vergleichbar(text: str) -> str:
    """Case and runs of whitespace do not decide whether a part matches."""
    return " ".join(text.split()).casefold()


def werkzeug_beschreibung(shown: bool = True) -> MCPWerkzeug:
    """The tool as the model sees it.

    ``shown`` is whether the memory travels to THIS model
    (app/gedaechtnis.py ``mitschicken``) — the same reading ``ausfuehren``
    takes as ``zeigen``. It decides what the description may promise: where
    the memory travels, the entries are read when a conversation begins, so
    a new one is in front of the model from the next conversation on and not
    at once; where it does not, the model never sees them, cannot list them
    and can name an entry to replace only by its whole text.
    """
    if shown:
        when = (
            "Both are saved without confirmation. Memory is loaded at the start of a "
            "conversation, so newly saved entries become available in the next conversation, "
            "not immediately. This tool's response confirms that an entry was saved."
        )
        correcting = (
            "to correct something, pass a short part of the existing entry's "
            "text as 'replaces'; that part must match exactly one entry.\n"
            "Called with an empty 'text', it saves nothing and lists the "
            "entries you have stored.\n"
            "The answer says what happened: saved, replaced, already known, or "
            "which entries there are when 'replaces' matched none or several."
        )
    else:
        when = (
            f"Both are saved without confirmation. {VERBORGEN} Saved entries are available to "
            "models that receive the memory."
        )
        correcting = (
            "to correct an entry, pass its full existing text as 'replaces'.\n"
            "The response indicates whether it was saved, replaced, or already known."
        )
    return MCPWerkzeug(
        name=WERKZEUG_NAME,
        beschreibung=(
            "Remembers one thing about this user across conversations: how "
            "they want to be worked with, what they prefer, who they are, how "
            "their project is put together.\n"
            "Kind 'rule' is an instruction that changes how you work and "
            "always applies. Kind 'fact' is knowledge that applies where it "
            f"fits. {when} A correction the user "
            "makes, or a preference they state in passing, is worth an entry "
            "even when they never asked for one.\n"
            "One entry per call, one sentence, at most "
            f"{MAX_LAENGE} characters. It cannot delete and it cannot take "
            f"whole file contents — {correcting}"
        ),
        schema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        'A single-sentence entry that remains understandable on its own a '
                        'year from now. For example: "Prefers measured values to estimates."'
                    ),
                },
                "kind": {
                    "type": "string",
                    "enum": [REGEL, FAKTUM],
                    "description": "'rule' specifies behaviour; 'fact' records information.",
                },
                "replaces": {
                    "type": "string",
                    "description": (
                        "A brief excerpt from the existing entry to replace. Omit when adding "
                        "new information."
                    ),
                },
            },
            "required": ["text", "kind"],
        },
        server=SERVER_NAME,
    )


def _text_von(argumente: dict[str, Any]) -> str:
    return str(argumente.get("text") or "").strip()


def _art_von(argumente: dict[str, Any]) -> str:
    art = str(argumente.get("kind") or "").strip().lower()
    return art if art in (REGEL, FAKTUM) else FAKTUM


def _zeilen_teilen(inhalt: str) -> tuple[list[str], list[str]]:
    """Splits the file into the two lists of entries.

    Anything outside the two headings is left out of the lists on purpose:
    the file is hand-editable, and whatever a person writes above the first
    heading is theirs to keep — ``_preamble`` hands it back to ``eintragen``,
    which writes it first again.
    """
    regeln: list[str] = []
    fakten: list[str] = []
    ziel: list[str] | None = None
    for zeile in inhalt.splitlines():
        kopf = zeile.strip()
        if kopf == UEBERSCHRIFT_REGELN:
            ziel = regeln
            continue
        if kopf == UEBERSCHRIFT_FAKTEN:
            ziel = fakten
            continue
        if ziel is None or not kopf:
            continue
        ziel.append(kopf.removeprefix("-").strip() if kopf.startswith("-") else kopf)
    return regeln, fakten


def _preamble(inhalt: str) -> str:
    """Whatever stands above the first of the two headings, byte for byte
    — a note of the person's own, which saving an entry must not take away
    or reshape."""
    lines: list[str] = []
    for line in inhalt.splitlines(keepends=True):
        if line.strip() in (UEBERSCHRIFT_REGELN, UEBERSCHRIFT_FAKTEN):
            break
        lines.append(line)
    return "".join(lines)


def _zusammensetzen(regeln: list[str], fakten: list[str]) -> str:
    teile: list[str] = []
    if regeln:
        teile.append(UEBERSCHRIFT_REGELN + "\n" + "\n".join(f"- {z}" for z in regeln))
    if fakten:
        teile.append(UEBERSCHRIFT_FAKTEN + "\n" + "\n".join(f"- {z}" for z in fakten))
    return "\n\n".join(teile)


def auflisten(inhalt: str) -> str:
    """The entries as the model is told them, headings and all."""
    regeln, fakten = _zeilen_teilen(inhalt)
    if not regeln and not fakten:
        return "No entries stored yet."
    return _zusammensetzen(regeln, fakten)


def eintragen(
    inhalt: str, text: str, art: str, ersetzt: str = "", *, teiltext: bool = True
) -> str:
    """The new file content — pure text in, pure text out, nothing on disk.

    Kept free of the filesystem so the rules of the game can be tested
    without one: replacing hits the entry no matter which heading it sits
    under, and an entry that is already there is not written twice.

    ``ersetzt`` is a part of the entry's text — with ``teiltext=False`` the
    whole entry. It has to point at one entry; copies of the same sentence
    (case and spacing aside) count as one, and all of them go. Pointing at
    none or at several raises ``ErsetztNichtEindeutig``, the entries in its
    ``eintraege``.
    """
    regeln, fakten = _zeilen_teilen(inhalt)
    ersetzt = ersetzt.strip().removeprefix("-").strip()

    ziel = regeln if art == REGEL else fakten
    if ersetzt:
        alle = [_vergleichbar(e) for e in regeln + fakten]
        gesucht = _vergleichbar(ersetzt)
        # The whole entry first: a short entry is also a part of every longer
        # one that repeats it, and could otherwise never be named alone.
        getroffen = {e for e in alle if e == gesucht}
        if not getroffen and teiltext:
            getroffen = {e for e in alle if gesucht in e}
        if len(getroffen) != 1:
            grund = (
                f"No entry contains '{ersetzt}'."
                if not getroffen
                else f"{len(getroffen)} entries contain '{ersetzt}'."
            )
            raise ErsetztNichtEindeutig(
                f"{grund} Nothing was saved. Retry with text matching exactly one entry as "
                "'replaces'.",
                eintraege=auflisten(inhalt),
            )
        (alter,) = getroffen
        # Every copy goes, so no stale sentence is left beside the new one;
        # under its own heading the new entry takes the old one's place.
        stelle = next((i for i, e in enumerate(ziel) if _vergleichbar(e) == alter), None)
        for liste in (regeln, fakten):
            liste[:] = [e for e in liste if _vergleichbar(e) != alter]
        if stelle is not None and text not in ziel:
            ziel.insert(stelle, text)

    if text not in ziel:
        ziel.append(text)
    preamble = _preamble(inhalt)
    entries = _zusammensetzen(regeln, fakten)
    if not preamble.strip():
        return entries
    # As written, the gap before the first heading included; a note without
    # a line break of its own gets one, so the heading stays a heading.
    return preamble + entries if preamble.endswith("\n") else f"{preamble}\n{entries}"


async def ausfuehren(argumente: dict[str, Any], pfad: Path, *, zeigen: bool) -> str:
    """Writes one entry, or lists them all when no text is given. Returns
    what the model is told about it.

    ``zeigen`` is whether the memory travels to THIS model
    (app/gedaechtnis.py ``mitschicken``). Where it does not, the entries are
    not handed over through the tool either — the switch keeps the memory
    off that side, and a listing is the memory. Saving still works there.
    """
    text = _text_von(argumente)
    if not text:
        if not zeigen:
            return VERBORGEN
        async with _schleuse:
            alt = pfad.read_text(encoding="utf-8") if pfad.exists() else ""
        return f"No text provided; nothing was saved. Stored entries:\n\n{auflisten(alt)}"
    if len(text) > MAX_LAENGE:
        raise MemoryVerboten(
            f"The entry is too long ({len(text)} characters; maximum: {MAX_LAENGE}). A memory "
            "entry should be a single sentence, not a document."
        )

    art = _art_von(argumente)
    ersetzt = str(argumente.get("replaces") or "").strip().removeprefix("-").strip()

    async with _schleuse:
        alt = pfad.read_text(encoding="utf-8") if pfad.exists() else ""
        try:
            # Where the model cannot see the entries, it names one only by its
            # whole text, as before: a part it guessed could hit a sentence
            # it has never seen.
            neu = eintragen(alt, text, art, ersetzt, teiltext=zeigen)
        except ErsetztNichtEindeutig as fehler:
            if not zeigen:
                raise MemoryVerboten(
                    f"No entry exactly matches '{ersetzt}'. Nothing was saved. {VERBORGEN}"
                ) from fehler
            raise MemoryVerboten(f"{fehler}\n\n{fehler.eintraege}") from fehler
        if neu.strip() == alt.strip():
            return "Already known; nothing changed."
        pfad.parent.mkdir(parents=True, exist_ok=True)
        # Whole or not at all (app/atomic_file.py): an interrupted write would
        # otherwise leave the program having forgotten half of what it knew.
        # In a thread, because that write waits on Windows while the file is
        # held, and the event loop must keep answering meanwhile.
        # ``newline=""``: \n stays \n on Windows too (app/tools/datei_schreiben.py).
        await asyncio.to_thread(atomic_file.write, pfad, neu + "\n", newline="")

    log.info("Memory extended (%s): %s", art, text)
    return "Replaced." if ersetzt else "Saved."
