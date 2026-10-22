"""The memory tool — ``memory_save``.

Built in rather than an MCP server, for the same reason as the shell tool:
the file belongs to the program, and an outside process would have to be told
where it is on every call — and anything passed as an argument can be forged
by the model.

What it can do is deliberately narrow. It appends ONE entry under one of two
headings, replaces ONE existing entry with a new one, or deletes ONE entry. It
cannot hand over whole file contents: the model names a short part of the
entry it means and the program finds it.

The tool exists only where the memory travels to the model (app/gedaechtnis.py
``mitschicken``): where the switch for the endpoint's side is off, the model
has neither the memory block in its prompt nor this tool — not in its list and
not in a call (app/tools/registry.py). Storing without being shown what is
stored would tell the model, through the answer to each call, whether a
sentence is already there.

There is no way to read the memory through the tool: the entries stand in the
system prompt from the start of a conversation, and a refusal that names the
entries (a part that matched none or several, a memory that is full) carries
them in its answer, so the next call can aim right.

An entry to replace or delete is found by a short part of its text, not by
its full wording — the model rarely has the exact sentence in front of it.
The part has to point at ONE entry; when it points at none or at several,
nothing is written and the answer carries the entries.

The memory is one size: the entries of both lists together hold at most
``MAX_TOTAL`` characters, an entry at most ``MAX_LAENGE``. A write that would
take the entries past it is refused with the entries in the answer, so the
model can summarize or delete first.

The two kinds are not decoration:

  * A **rule** changes behaviour and applies always.
  * A **fact** is knowledge and applies where it fits.

Nothing asks before it is stored, replaced or deleted
(app/berechtigungen.py ``NEVER_ASKED``). There is exactly one prompt in the
whole program that matters — the shell reaching outside the shared folders —
and it is worth something only because it is rare. A prompt that comes ten
times a session gets clicked away without reading, and then it protects
nothing.

What carries that here is that the memory is **visible and reversible**: it
is one file, it stands open in the settings window, and a line can be taken
out by editing it there. Looking at it does everything a prompt would have
done, and it does it after the fact instead of in the way.
"""

from __future__ import annotations

import asyncio
import logging
import re
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

# The entries of both lists together, one per line: 2,200 characters for the
# rules and 1,375 for the facts, as one budget.
MAX_TOTAL = 3575

REGEL = "rule"
FAKTUM = "fact"

# One writer at a time. A chat and a job running overnight can hit this in the
# same second, and both do read-modify-write — without the gate one of them
# writes over what the other just added.
_schleuse = asyncio.Lock()


class MemoryVerboten(Exception):
    """The call was refused — nothing was written."""


class ErsetztNichtEindeutig(MemoryVerboten):
    """``replaces`` pointed at no entry or at several — nothing was written.

    ``eintraege`` carries the listing, for a caller whose model may see it.
    """

    def __init__(self, meldung: str, eintraege: str) -> None:
        super().__init__(meldung)
        self.eintraege = eintraege


class MemoryFull(MemoryVerboten):
    """The write would take the entries past ``MAX_TOTAL`` — nothing was written."""


def _vergleichbar(text: str) -> str:
    """Case and runs of whitespace do not decide whether a part matches."""
    return " ".join(text.split()).casefold()


def werkzeug_beschreibung() -> MCPWerkzeug:
    """The tool as the model sees it.

    It is only ever shown to a model the memory travels to, where the entries
    are read when a conversation begins: a change is in front of the model
    from the next conversation on and not at once.
    """
    return MCPWerkzeug(
        name=WERKZEUG_NAME,
        beschreibung=(
            "Keeps the memory about this user across conversations: how they "
            "want to be worked with, what they prefer, who they are, how their "
            "project is put together.\n"
            "Kind 'rule' is an instruction that changes how you work and "
            "always applies. Kind 'fact' is knowledge that applies where it "
            "fits. A correction the user makes, or a preference they state in "
            "passing, is worth an entry even when they never asked for one.\n"
            "The tool does three things, one entry per call. To save a new "
            "entry, pass 'text' and 'kind'. To change one, pass the new 'text' "
            "and 'kind', and in 'replaces' a short part of the old entry's "
            "text. To delete one, pass only 'remove' with a short part of its "
            "text. The part must match exactly one entry, otherwise nothing is "
            "changed and the answer lists the entries.\n"
            "Nothing is asked before an entry is saved, changed or deleted. "
            "Memory is loaded at the start of a conversation, so a change is in "
            "front of you in the next conversation, not immediately; the answer "
            "of this tool says what was done.\n"
            f"An entry is one sentence of at most {MAX_LAENGE} characters, and "
            f"the whole memory holds at most {MAX_TOTAL:,} characters. When a "
            "change would exceed that, nothing is saved and the answer lists the "
            "entries: summarize some with 'replaces' or delete stale ones with "
            "'remove', then save again."
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
                "remove": {
                    "type": "string",
                    "description": (
                        "A brief excerpt from the existing entry to delete. Pass it alone, "
                        "without 'text'."
                    ),
                },
            },
            "required": [],
        },
        server=SERVER_NAME,
    )


def _text_von(argumente: dict[str, Any]) -> str:
    return str(argumente.get("text") or "").strip()


def _art_von(argumente: dict[str, Any]) -> str:
    art = str(argumente.get("kind") or "").strip().lower()
    return art if art in (REGEL, FAKTUM) else FAKTUM


# A line that is a heading by the rules of Markdown: up to three blanks of
# indentation, one to six ``#``, then a blank, a tab or the end of the line.
# ``#hashtag`` is not one.
_UEBERSCHRIFT = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")


def _kopfart(zeile: str) -> str | None:
    """What a line is as a heading: the kind whose own heading it is, ``""``
    for any other heading, ``None`` for a line that is no heading."""
    if zeile.strip() == UEBERSCHRIFT_REGELN:
        return REGEL
    if zeile.strip() == UEBERSCHRIFT_FAKTEN:
        return FAKTUM
    return "" if _UEBERSCHRIFT.match(zeile.rstrip("\r\n")) else None


def _gliedern(inhalt: str) -> tuple[str, list[tuple[str, str]]]:
    """Cuts the file into what stands above its first own heading and the
    blocks from there on, each a heading with the lines up to the next
    heading of any kind: ``(kind, text)``, ``kind`` being ``rule`` or
    ``fact`` for an own heading and ``""`` for a heading of the person's
    own. The text keeps every character."""
    preamble: list[str] = []
    blocks: list[tuple[str, list[str]]] = []
    for zeile in inhalt.splitlines(keepends=True):
        art = _kopfart(zeile)
        if art is not None and (art or blocks):
            blocks.append((art, [zeile]))
        elif blocks:
            blocks[-1][1].append(zeile)
        else:
            preamble.append(zeile)
    return "".join(preamble), [(art, "".join(lines)) for art, lines in blocks]


def _zeilen_teilen(inhalt: str) -> tuple[list[str], list[str]]:
    """The entries of the two lists, from every block under one of the two
    headings.

    Whatever stands outside them is left out on purpose: the file is
    hand-editable, and what a person writes above the first heading or
    under a heading of their own is theirs to keep — ``_zusammensetzen``
    writes it back where it stood.
    """
    regeln: list[str] = []
    fakten: list[str] = []
    for art, text in _gliedern(inhalt)[1]:
        if not art:
            continue
        for zeile in text.splitlines()[1:]:
            kopf = zeile.strip()
            if not kopf:
                continue
            (regeln if art == REGEL else fakten).append(
                kopf.removeprefix("-").strip() if kopf.startswith("-") else kopf
            )
    return regeln, fakten


def _zusammensetzen(
    regeln: list[str], fakten: list[str], blocks: list[tuple[str, str]] | None = None
) -> str:
    """The file from the two lists. The blocks the file had stay in their
    order: a block of the person's own is written as it was, and each list
    goes under the first of its own headings (one that stood again further
    down is merged into it). A list without a heading yet gets one, the rules
    ahead of the facts."""
    listen = {REGEL: regeln, FAKTUM: fakten}
    ueberschriften = {REGEL: UEBERSCHRIFT_REGELN, FAKTUM: UEBERSCHRIFT_FAKTEN}

    def stueck(art: str) -> str:
        return ueberschriften[art] + "\n" + "\n".join(f"- {z}" for z in listen[art])

    teile: list[str] = []
    geschrieben: set[str] = set()
    vorhanden = {art for art, _ in blocks or []}
    for art, text in blocks or []:
        if not art:
            teile.append(text)
            continue
        if art == FAKTUM and REGEL not in vorhanden and regeln:
            teile.append(stueck(REGEL))
            vorhanden.add(REGEL)
            geschrieben.add(REGEL)
        if art not in geschrieben and listen[art]:
            teile.append(stueck(art))
        geschrieben.add(art)
    for art in (REGEL, FAKTUM):
        if art not in geschrieben and listen[art]:
            teile.append(stueck(art))

    ausgabe = ""
    for teil in teile:
        if ausgabe:
            # A piece of ours has no line break at its end and is set apart
            # by a blank line; a block of the person's own is written as it
            # was and has nothing added behind it.
            ausgabe += "" if ausgabe.endswith("\n") else "\n\n"
        ausgabe += teil
    return ausgabe.rstrip("\n")


def auflisten(inhalt: str) -> str:
    """The entries as the model is told them, headings and all."""
    regeln, fakten = _zeilen_teilen(inhalt)
    if not regeln and not fakten:
        return "No entries stored yet."
    return _zusammensetzen(regeln, fakten)


def _total_size(regeln: list[str], fakten: list[str]) -> int:
    """How much room the entries take: both lists, one entry to a line."""
    return len("\n".join(regeln + fakten))


def _refuse_if_full(inhalt: str, regeln: list[str], fakten: list[str], before: int, was: str) -> None:
    """Refuses a write that would take the entries past ``MAX_TOTAL``.

    Only a write that grows them counts: a file somebody filled past the line
    by hand can still be summarized or cleared, which is the way out.
    """
    now = _total_size(regeln, fakten)
    if now > MAX_TOTAL and now > before:
        raise MemoryFull(
            f"The memory holds {before:,} of {MAX_TOTAL:,} characters. {was} would exceed the "
            "limit. Nothing was saved. Summarize overlapping entries with 'replaces' or delete "
            "stale ones with 'remove', then try again.\n\n" + auflisten(inhalt)
        )


def _single_match(inhalt: str, regeln: list[str], fakten: list[str], teil: str, purpose: str) -> str:
    """The comparable form of the ONE entry a part of text points at.

    The whole entry first: a short entry is also a part of every longer one
    that repeats it, and could otherwise never be named alone. Copies of the
    same sentence (case and spacing aside) count as one. Pointing at none or
    at several raises ``ErsetztNichtEindeutig``, the entries in its
    ``eintraege``; ``purpose`` names what the part was for in the sentence.
    """
    alle = [_vergleichbar(e) for e in regeln + fakten]
    gesucht = _vergleichbar(teil)
    getroffen = {e for e in alle if e == gesucht}
    if not getroffen:
        getroffen = {e for e in alle if gesucht in e}
    if len(getroffen) != 1:
        grund = (
            f"No entry contains '{teil}'."
            if not getroffen
            else f"{len(getroffen)} entries contain '{teil}'."
        )
        raise ErsetztNichtEindeutig(
            f"{grund} Nothing was saved. Retry with text matching exactly one entry as "
            f"'{purpose}'.",
            eintraege=auflisten(inhalt),
        )
    (alter,) = getroffen
    return alter


def _compose_file(inhalt: str, regeln: list[str], fakten: list[str]) -> str:
    """The file from the two lists, what the person wrote kept as it stood:
    the text above the first heading of ours, and every heading of their own
    with its lines."""
    preamble, blocks = _gliedern(inhalt)
    entries = _zusammensetzen(regeln, fakten, blocks)
    if not preamble.strip():
        return entries
    # As written, the gap before the first heading included; a note without
    # a line break of its own gets one, so the heading stays a heading.
    return preamble + entries if preamble.endswith("\n") else f"{preamble}\n{entries}"


def eintragen(inhalt: str, text: str, art: str, ersetzt: str = "") -> str:
    """The new file content — pure text in, pure text out, nothing on disk.

    Kept free of the filesystem so the rules of the game can be tested
    without one: replacing hits the entry no matter which heading it sits
    under, and an entry that is already there is not written twice.

    ``ersetzt`` is a part of the entry's text. It has to point at one entry;
    copies of the same sentence (case and spacing aside) count as one, and
    all of them go. Pointing at none or at several raises
    ``ErsetztNichtEindeutig``, the entries in its ``eintraege``. A result that
    would take the entries past ``MAX_TOTAL`` raises ``MemoryFull``.

    What the person wrote into the file stays as it stood: the text above the
    first heading of ours, and every heading of their own with its lines.
    """
    regeln, fakten = _zeilen_teilen(inhalt)
    before = _total_size(regeln, fakten)
    ersetzt = ersetzt.strip().removeprefix("-").strip()

    ziel = regeln if art == REGEL else fakten
    if ersetzt:
        alter = _single_match(inhalt, regeln, fakten, ersetzt, "replaces")
        # Every copy goes, so no stale sentence is left beside the new one;
        # under its own heading the new entry takes the old one's place.
        stelle = next((i for i, e in enumerate(ziel) if _vergleichbar(e) == alter), None)
        for liste in (regeln, fakten):
            liste[:] = [e for e in liste if _vergleichbar(e) != alter]
        if stelle is not None and text not in ziel:
            ziel.insert(stelle, text)

    if text not in ziel:
        ziel.append(text)
    was = "Replacing the entry" if ersetzt else "Saving this entry"
    _refuse_if_full(inhalt, regeln, fakten, before, f"{was} ({len(text)} characters)")
    return _compose_file(inhalt, regeln, fakten)


def remove_entry(inhalt: str, teil: str) -> str:
    """The new file content without the ONE entry a part of its text points
    at — pure text in, pure text out, like ``eintragen``. Copies of the same
    sentence go together. Pointing at none or at several raises
    ``ErsetztNichtEindeutig``."""
    regeln, fakten = _zeilen_teilen(inhalt)
    teil = teil.strip().removeprefix("-").strip()
    alter = _single_match(inhalt, regeln, fakten, teil, "remove")
    for liste in (regeln, fakten):
        liste[:] = [e for e in liste if _vergleichbar(e) != alter]
    return _compose_file(inhalt, regeln, fakten)


async def ausfuehren(argumente: dict[str, Any], pfad: Path) -> str:
    """Saves, replaces or deletes one entry. Returns what the model is told
    about it.

    Only a model the memory travels to gets here
    (app/gedaechtnis.py ``mitschicken``): the registry refuses the call for
    any other (app/tools/registry.py).
    """
    text = _text_von(argumente)
    removed = str(argumente.get("remove") or "").strip().removeprefix("-").strip()
    if removed and text:
        raise MemoryVerboten(
            "'remove' deletes an entry and takes no 'text'. Nothing was changed. To change an "
            "entry, pass the new 'text' with 'replaces' instead."
        )
    if not text and not removed:
        raise MemoryVerboten(
            "No text provided; nothing was changed. To save an entry pass 'text' and 'kind'; "
            "to delete one pass 'remove' with a short part of its text."
        )
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
            neu = remove_entry(alt, removed) if removed else eintragen(alt, text, art, ersetzt)
        except ErsetztNichtEindeutig as fehler:
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

    if removed:
        log.info("Memory entry deleted")
        return "Removed."
    log.info("Memory extended (%s): %s", art, text)
    return "Replaced." if ersetzt else "Saved."
