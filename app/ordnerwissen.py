"""What the user wrote down about a shared folder — its ``exe.md``.

The counterpart to the memory: the memory knows the person, this one knows
the place. A shared working folder carries a file called ``exe.md`` at its
top level, and whatever stands in it rides along in the system message for
as long as that folder is shared. That is the whole idea — a small local
model knows too little, a large one at a provider knows nothing about THIS
project, and both of them can read three sentences.

**Code, not a skill.** The ``SKILLS`` block in app/grundprompt.py justifies
why a skill may be followed: *"the program took it out of a folder on this
machine that only the user writes to."* A shared working folder is by
definition not such a place, so loading an ``exe.md`` as a skill would hand
it a standing that block carefully limits to somewhere else.

**It is read as the user's own word.** That is a decision, and it has a
price which is named rather than hidden: whoever drops a file called
``exe.md`` into a folder that is later shared is writing into the system
message. A folder is to be shared like a folder whose contents are known —
an unpacked archive or a fresh clone is exactly the case where that counts.
The register below cannot prevent it; it only keeps the answer to "where did
this file come from" available afterwards.

**It ranks below the program's own layers.** Under ``prompts/system.md`` and
under the memory, and it never lifts a rule about what the machine does —
the same line ``mit_benutzerprompt`` already draws.

**Read fresh on every request**, like everything else in that chain: the
usual case is that the model wrote the file a moment ago, and a cache would
make that take effect one request too late — the most confusing kind of
error there is. A folder without an ``exe.md`` produces nothing at all, not
even a line saying there is none.

**Nothing here may reach the chat as an error.** Read-only file system,
hanging network share, permissions: ``OSError`` is logged and the folder
carries on without notes, the same posture ``config.memory_lesen()`` has.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app import atomic_file
from app.events import Ereignisse, bus

log = logging.getLogger(__name__)

# Exactly this name, exactly the top level of a shared folder, nowhere else.
# The write below goes past the permission gate (app/berechtigungen.py) —
# the program acts on an explicit action of the user's, not on a model's
# call — and that is only defensible while the target cannot move.
DATEINAME = "exe.md"

# Above this the interface says so, in yellow. A WARNING, not a cut: the
# file is always read whole, however large it is. There is no second limit
# on purpose — tidying up is done by hand.
SCHWELLE = 4096

# The wording of that warning. It lives here and not in
# the frontend so the threshold and the sentence about it cannot drift.
MELDUNG = "exe.md > 4 KB"

# The event the interface will listen for: Ereignisse.EXEMD_ZU_GROSS.
# app/events.py is process-internal and does not reach the browser by
# itself — the piece that forwards it into the chat's SSE stream is a
# separate job, and until it exists this event fires into an empty room
# without costing anything.

# What a fresh file says. Four headings, no example content: an example a
# model mistakes for a fact is the worst kind of wrong. English like
# everything that becomes prompt content — what the user or the model then
# writes underneath is in whatever language they speak.
GERUEST = """# exe.md

Information Exe AI needs about this folder. This file accompanies every
message while the folder is shared. Keep it concise and accurate; omit
information that can be obtained directly from the files.

## Rules that cannot be inferred

## How work is done here

## Where things belong

## Reasons behind the design
"""

# Our own data, never the shared folder: a register that lived where anyone
# can drop a file could be rewritten by dropping one.
REGISTER = "ordnerwissen.json"
SICHERUNGEN = "ordnerwissen"

# What the register says about where a file came from.
ANGELEGT = "angelegt"
VORGEFUNDEN = "vorgefunden"

# How putting a copy back ended. These keys travel outwards as they are: the
# sentence a person reads belongs in the translation catalogue, and a key
# that names the outcome outlives whichever wording is chosen for it.
#
#   ZURUECK           the copy is on disk again
#   KEINE_SICHERUNG   there is nothing kept for this folder
#   UNVERAENDERT      the file already says exactly what the copy says
#   IM_WEG            other notes are there and were left alone
#   NICHT_SCHREIBBAR  the folder refused the write
ZURUECK = "zurueck"
KEINE_SICHERUNG = "keine_sicherung"
UNVERAENDERT = "unveraendert"
IM_WEG = "im_weg"
NICHT_SCHREIBBAR = "nicht_schreibbar"

# Chat (or job) plus folder that has already been warned about. Process-wide
# and deliberately not persisted: the warning is meant once per run of the
# program, and a chat that never comes back must not keep a row somewhere.
_gewarnt: set[tuple[str, str]] = set()

# Folder -> hash of the file bytes last written to the backup copy. Saves reading
# the copy back on every request; a restart costs one extra write.
_zuletzt_gesichert: dict[str, str] = {}


def plain_text(raw: str) -> str:
    """The file's words as the system message carries them.

    Line endings made plain and the whitespace at both ends trimmed. The one
    definition of "empty" and "the same": ``lesen`` and ``wiederherstellen``
    both ask it, so a file that differs from its copy only in line endings
    is not taken for a different one.

    A byte order mark at the start is not a word either: an editor that
    saves one adds nothing a reader wrote, and ``strip()`` alone would leave
    it standing. ``raw`` keeps it, so the copy is still the file.
    """
    return raw.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()


def _read_raw(pfad: Path) -> str:
    """The file exactly as it is. Bytes, not read_text: that would turn
    "\r\n" into "\n" on the way in, and a copy would no longer be the file."""
    return pfad.read_bytes().decode("utf-8")


@dataclass(frozen=True)
class Notiz:
    """One folder's ``exe.md``, as it stands on disk right now.

    ``text`` is what the system message carries: line endings made plain
    and the whitespace at both ends trimmed. ``raw`` is the file exactly as
    it is — what the backup keeps, so a file put back from it is the same
    file, down to its last line break.
    """

    ordner: str
    text: str
    raw: str

    @property
    def zeichen(self) -> int:
        return len(self.text)

    @property
    def zu_gross(self) -> bool:
        """Measured in bytes, because that is what "4 KB" means."""
        return len(self.text.encode("utf-8")) > SCHWELLE


@dataclass(frozen=True)
class Wiederherstellung:
    """What an attempt to put a copy back did, and to which text.

    Every ending is reported the same way, the good one included. A caller
    that only learns "it failed" cannot tell a folder with no copy from one
    whose notes were left alone on purpose, and those two want opposite
    things offered next.
    """

    ordner: str
    ergebnis: str
    text: str = ""

    @property
    def erfolg(self) -> bool:
        """Only a real write counts. A file that already said the right
        thing was not restored — it was never gone."""
        return self.ergebnis == ZURUECK


def datei(ordner: str) -> Path:
    """Where the notes for this folder live — top level, exact name."""
    return Path(ordner) / DATEINAME


def lesen(ordner: Sequence[str]) -> list[Notiz]:
    """The notes of every shared folder that has any, in the shared order.

    A folder without the file, or with one holding nothing but whitespace,
    is left out entirely — not carried along as an empty heading. The order
    is the one the folders were shared in, so the blocks in the prompt line
    up with the list in the folder section above them.
    """
    notizen: list[Notiz] = []
    for eintrag in ordner:
        pfad = datei(eintrag)
        try:
            if not pfad.is_file():
                continue
            raw = _read_raw(pfad)
        except (OSError, UnicodeDecodeError) as fehler:
            log.warning("exe.md cannot be read (%s): %s", pfad, fehler)
            continue
        text = plain_text(raw)
        if not text:
            continue
        notizen.append(Notiz(ordner=eintrag, text=text, raw=raw))
    return notizen


def fuer_prompt(notizen: Sequence[Notiz]) -> list[tuple[str, str]]:
    """Folder and text, in the shape app/grundprompt.py takes."""
    return [(n.ordner, n.text) for n in notizen]


def anlegen(ordner: Sequence[str], datenordner: Path | None = None) -> None:
    """Puts an ``exe.md`` in every one of these folders that has none.

    Called when folders are shared, never during a request: sharing is one
    clear moment, and a hanging network share then delays a PATCH instead of
    the answer itself. No dialogue, no question, no message — the file is
    simply there afterwards, the way a ``CLAUDE.md`` is.

    An existing file is not touched, not appended to, not read for a
    decision. It is only recorded that it was already there.
    """
    for eintrag in ordner:
        pfad = datei(eintrag)
        try:
            if pfad.exists():
                _vermerken(eintrag, VORGEFUNDEN, datenordner)
                continue
            pfad.write_text(GERUEST, encoding="utf-8")
        except OSError as fehler:
            # The share succeeds either way. The folder is shared, there is
            # simply no exe.md in it — and saying so belongs in the window,
            # which is a separate job.
            log.warning("exe.md cannot be created (%s): %s", pfad, fehler)
            continue
        _vermerken(eintrag, ANGELEGT, datenordner)


def herkunft(ordner: str, datenordner: Path | None) -> str:
    """Where this folder's file came from: ours, found, or nothing recorded.

    It no longer decides anything — a found file counts as the user's word
    just as ours does. It is kept so the question "where did this come from"
    can still be answered later, and it lives outside the shared folder so
    dropping a file in cannot rewrite the answer.
    """
    return str(_register(datenordner).get(ordner, {}).get("herkunft", ""))


def sichern(notizen: Sequence[Notiz], datenordner: Path | None) -> None:
    """Keeps our own copy of what each file says right now.

    The net under the delete protection, and the only layer that survives a
    ``run_command``: nothing can stop ``rm exe.md``, but a copy in our data
    folder means the file is not gone with it. Written only when the file
    actually changed — byte for byte, a new line ending counts — so an
    unchanged folder costs one hash and no disk.

    What it cannot catch, said plainly: a change made and destroyed between
    two requests never becomes a copy. The copy is the last state this
    program saw, not every state the file ever had.

    The way back out is ``wiederherstellen``.
    """
    if datenordner is None:
        return
    for notiz in notizen:
        raw_bytes = notiz.raw.encode("utf-8")
        fingerabdruck = hashlib.sha256(raw_bytes).hexdigest()
        if _zuletzt_gesichert.get(notiz.ordner) == fingerabdruck:
            continue
        name = f"{_kennung(notiz.ordner)}.md"
        try:
            ordner = Path(datenordner) / SICHERUNGEN
            ordner.mkdir(parents=True, exist_ok=True)
            atomic_file.write(ordner / name, raw_bytes)
        except OSError as fehler:
            log.warning("exe.md backup failed (%s): %s", notiz.ordner, fehler)
            continue
        _zuletzt_gesichert[notiz.ordner] = fingerabdruck
        _eintragen(notiz.ordner, datenordner, sicherung=name, gesichert=_jetzt())


def sicherung(ordner: str, datenordner: Path | None) -> str | None:
    """The last copy this program kept of that folder's file, if there is one."""
    if datenordner is None:
        return None
    name = str(_register(datenordner).get(ordner, {}).get("sicherung") or "")
    if not name:
        return None
    pfad = Path(datenordner) / SICHERUNGEN / name
    try:
        return _read_raw(pfad) if pfad.is_file() else None
    except (OSError, UnicodeDecodeError) as fehler:
        # Answered as "no copy", because none can be offered — but said in
        # the log, so a damaged copy does not pass for one never kept.
        log.warning("exe.md backup unreadable (%s): %s", pfad, fehler)
        # Forget that this copy was written, so the next request that reads
        # the file writes a sound one instead of trusting the damaged one.
        _zuletzt_gesichert.pop(ordner, None)
        return None


def wiederherstellen(ordner: str, datenordner: Path | None) -> Wiederherstellung:
    """Writes the kept copy back into the folder it came from.

    The way out of ``sichern``. A copy that nothing can reach is the same as
    no copy at all, and until this function existed that was the whole state
    of the safety net: the bytes were on disk and no path led back to them.

    **It never overwrites notes that say something else.** The copy is by
    definition older than whatever stands in the folder now, and older text
    does not win by being available. A file with something in it is left
    exactly as it is and the answer names it as being in the way, so the
    copy stays for a second, deliberate decision rather than being spent on
    a guess. That is also why an unreadable file counts as occupied: what
    cannot be read cannot be weighed, and a restore may not guess there.

    **A file that holds nothing counts as gone.** ``lesen`` already treats
    whitespace as no notes at all, and this follows it rather than inventing
    a second definition — which makes a truncated file recoverable as well
    as a deleted one, and those are the same accident with different tools.

    **A copy is not touched, only read.** Failing halfway therefore leaves
    the copy intact and the folder in the state it was already in, and the
    caller is told which of the two happened.
    """
    kopie = sicherung(ordner, datenordner)
    if kopie is None:
        return Wiederherstellung(ordner, KEINE_SICHERUNG)

    pfad = datei(ordner)
    try:
        vorhanden = _read_raw(pfad) if pfad.is_file() else ""
    except (OSError, UnicodeDecodeError) as fehler:
        log.warning("exe.md cannot be read before restoring (%s): %s", pfad, fehler)
        return Wiederherstellung(ordner, IM_WEG, kopie)

    jetzt = plain_text(vorhanden)
    if jetzt == plain_text(kopie):
        # Nothing was lost here. Writing the same text again would only move
        # the timestamp of a file somebody may have open, and an offer to
        # restore should not turn into a change of its own.
        return Wiederherstellung(ordner, UNVERAENDERT, kopie)

    if jetzt:
        return Wiederherstellung(ordner, IM_WEG, kopie)

    try:
        atomic_file.write(pfad, kopie.encode("utf-8"))
    except OSError as fehler:
        log.warning("exe.md backup cannot be restored (%s): %s", ordner, fehler)
        return Wiederherstellung(ordner, NICHT_SCHREIBBAR, kopie)

    # Noted for the same reason the origin is noted: so the question "was
    # this file ever put back from a copy" still has an answer later, and
    # outside the shared folder, where dropping a file in cannot change it.
    _eintragen(ordner, datenordner, wiederhergestellt=_jetzt())
    return Wiederherstellung(ordner, ZURUECK, kopie)


def schon_gewarnt(kennung: str, ordner: str) -> bool:
    """Whether this chat has already been warned about this folder.

    Asked BEFORE ``melden``, which is what makes it useful: afterwards
    everything over the line is marked and the answer is always yes. The
    caller that wants to show the warning once — rather than at every
    sentence — needs to know which ones are new, and ``melden``'s own return
    value is deliberately the state and not the news (see its docstring).
    """
    return ((kennung or ""), ordner) in _gewarnt


def melden(kennung: str, notizen: Sequence[Notiz]) -> list[Notiz]:
    """Fires the threshold warning for every file over 4 KB — once each.

    Once, because this runs on every request and a warning that repeats at
    every sentence is not a warning. The event carries the folder and the
    size; the piece that turns it into the yellow line in the window is a
    separate job, and the file travels whole in either case.

    Returns the ones that were over the threshold this time, warned or not,
    so a caller can act on the state rather than on the event.
    """
    grosse = [n for n in notizen if n.zu_gross]
    for notiz in grosse:
        marke = (kennung or "", notiz.ordner)
        if marke in _gewarnt:
            continue
        _gewarnt.add(marke)
        log.warning("%s (%s, %d characters)", MELDUNG, notiz.ordner, notiz.zeichen)
        _feuern(kennung, notiz)
    # A file that shrank back below the line may warn again if it grows.
    unter_der_linie = {n.ordner for n in notizen} - {n.ordner for n in grosse}
    for eintrag in unter_der_linie:
        _gewarnt.discard(((kennung or ""), eintrag))
    return grosse


def vergessen() -> None:
    """Tests only — drops what has been warned about and backed up."""
    _gewarnt.clear()
    _zuletzt_gesichert.clear()


def ist_notiz(ziel: Path, ordner: Sequence[str]) -> bool:
    """Is this path the ``exe.md`` at the top of one of these folders?

    The one question the write tool asks before it replaces a file whole. A
    file of the same name one level down is not this file and is not
    protected — the protection is as narrow as the writing is.
    """
    if ziel.name != DATEINAME:
        return False
    for eintrag in ordner:
        try:
            if ziel == datei(eintrag).resolve() or ziel == datei(eintrag):
                return True
        except OSError:
            continue
    return False


# --- The register ------------------------------------------------------------


def _kennung(ordner: str) -> str:
    """A file name for a folder path. Hashed, because a path is not one."""
    return hashlib.sha256(ordner.encode("utf-8")).hexdigest()[:16]


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat()


def _register_datei(datenordner: Path) -> Path:
    return Path(datenordner) / REGISTER


def _register(datenordner: Path | None) -> dict[str, dict]:
    if datenordner is None:
        return {}
    pfad = _register_datei(datenordner)
    try:
        if not pfad.is_file():
            return {}
        roh = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as fehler:
        log.warning("Folder knowledge register cannot be read (%s): %s", pfad, fehler)
        return {}
    if not isinstance(roh, dict):
        return {}
    return {k: v for k, v in roh.items() if isinstance(v, dict)}


def _eintragen(ordner: str, datenordner: Path | None, **felder) -> None:
    if datenordner is None:
        return
    stand = _register(datenordner)
    eintrag = dict(stand.get(ordner) or {})
    eintrag.update(felder)
    stand[ordner] = eintrag
    pfad = _register_datei(datenordner)
    try:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        atomic_file.write(pfad, json.dumps(stand, ensure_ascii=False, indent=2))
    except OSError as fehler:
        log.warning("Folder knowledge register cannot be written (%s): %s", pfad, fehler)


def _vermerken(ordner: str, woher: str, datenordner: Path | None) -> None:
    """Records where the file came from — the first answer wins.

    A folder shared a second time must not turn a found file into one of
    ours, nor the other way round: the question is where the file came from
    the first time this program ever saw it.
    """
    if datenordner is None:
        return
    if _register(datenordner).get(ordner, {}).get("herkunft"):
        return
    _eintragen(ordner, datenordner, herkunft=woher, seit=_jetzt())


def _feuern(kennung: str, notiz: Notiz) -> None:
    bus.veroeffentlichen_ohne_warten(
        Ereignisse.EXEMD_ZU_GROSS,
        chat_id=kennung,
        ordner=notiz.ordner,
        zeichen=notiz.zeichen,
        meldung=MELDUNG,
    )
