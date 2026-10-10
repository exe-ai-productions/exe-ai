"""The dock: the one shelf where files without a chat land.

The person drops files here from the start page, and a job that has no chat
delivers here; a job started from a chat delivers into that chat's own
folder instead (``app/dokumentablage.py``), so the delivery goes with the
chat. There is no second dock beside this one: the person's own dock that
stood here once, with its ceiling of places and its rule that the model
never sees it, has been folded in (``_carry_old_dock``).

**The dock keeps its own copy.** A path into a shared folder would break
the moment it is tidied up, and it would quietly hand the interface a file
it was never given.

**The folder belongs to the user**. It is a named storage
location (``app/speicherorte.py``), the pictures' construction exactly: a
path shown in the panel, opened in the file manager, and moved with the
pencil. It used to be ``data_dir + "agentendock"`` written into this module,
which meant nobody could say where their delivered files should go.

**The record lives INSIDE the folder**, not one level up in the data folder
where it began. That is what makes the folder the whole shelf: move it and
the list moves with it, so there is never a list here naming files that are
over there. It is also the only honest answer to a moved folder — the
pictures show an empty wall and leave the old ones where they are, and this
shelf does exactly the same, restored in full by pointing back.

The per-file ceiling below is a working limit for the delivery TOOL only
(``app/tools/agentendock.py``); what the person drops has none, like a
picture upload. There is deliberately no ceiling on the NUMBER of files: it
was a wall with no door — a run that met it was refused and still reported
"fertig" — and the folder is the user's own now, the same way the picture
folder has always been, which has never counted either.
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from app import atomic_file
from app import ordnerinhalt
from app.speicherorte import ort

if TYPE_CHECKING:
    from app.config import Config

log = logging.getLogger(__name__)

# One writer at a time. Every write is read-modify-write over the WHOLE
# record, and the shelf is reached from two lanes at once: a run's
# ``deliver_file`` on the event loop, and the panel's own listing and delete
# in the threadpool FastAPI gives a synchronous endpoint
# (``app/api/v1/agentendock.py``). Without this, two deliveries that read the
# same list both wrote their own version of it and one of them was simply
# gone. The same lock the storage locations keep for the same reason
# (``app/speicherorte.py``) — module level, because the shelf itself is built
# fresh on every call (``dock_fuer``) and a lock on the instance would guard
# nothing.
_SCHLOSS = threading.Lock()

# The storage location this shelf is kept in (app/speicherorte.py). The name
# is also the folder under data_dir when nothing was moved, so an untouched
# installation keeps the exact place it always had.
ORT_NAME = "agent_dock"
ORDNER = ORT_NAME
DATEI = "agentendock.json"

# Per file, and for the delivery tool alone (app/tools/agentendock.py). A
# report, a page, a picture — not an archive: one call cannot be allowed to
# write a disk full, and the caller is told the size and the ceiling so it
# can act. What the person drops is not held to it.
MAX_BYTES = 10 * 1024 * 1024

# The person's own dock from before there was one dock: a folder of files
# and a list naming them, both straight under the data folder. Read once and
# carried over (``_carry_old_dock``), then removed.
OLD_DOCK_FOLDER = "dock"
OLD_DOCK_RECORD = "dock.json"

# What a name may become on disk. The name the user sees is kept as it was;
# the file itself gets a safe one, so nothing can escape the folder.
_UNSICHER = re.compile(r"[^A-Za-z0-9._-]+")

# Python's own table only learned Markdown in 3.13, and a report is the
# delivery agents make most often — so the shelf carries that one itself.
NACHSCHLAG = {".md": "text/markdown"}


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat()


def sicherer_name(name: str) -> str:
    sauber = _UNSICHER.sub("_", Path(str(name or "datei")).name).strip("._") or "datei"
    return sauber[:120]


def eintragsname(name: str) -> str:
    """What the shelf calls a delivery — its one identity, everywhere.

    ``Path(...).name`` because that is what a tile has always shown: the
    folder holds one flat set of files, so "out/daten.csv" and "daten.csv"
    are the same tile and asking for one is asking for the other. The debt a
    run still owes is about what is ON the shelf, so it is kept under this
    name too (``app/zwischenstand.py``) — otherwise a refused "out/daten.csv"
    stayed owed after "daten.csv" landed, and the run failed over a file
    that was right there.

    Whitespace is collapsed into single spaces first, and that is not
    cosmetic: a name is written into the handoff as one ``- `` bullet, and a
    name carrying a newline could otherwise close that list and open
    another. Measured before this existed: a delivery named
    ``"a.md\\n## Next\\n- b.md"`` wiped a second, real name out of the debt.

    Empty is a real answer ("" for a nameless or path-only call) — the
    caller decides what that means; the tool refuses such a call outright,
    and the shelf falls back to a placeholder.
    """
    return Path(" ".join(str(name or "").split())).name


def _kennung_aus_name(name: str) -> str:
    """A file's own, stable id, derived from its name.

    Thirty-two hex characters, the shape a delivered file's id already has,
    so nothing downstream can tell the two apart or has to. Derived rather
    than drawn, because a straggler is not written into the record: an id
    drawn fresh per listing would be a different id every time the wall was
    read, and the click that followed the first listing would miss.

    The folder holds one flat set of names, so a name identifies a file in it
    as well as a record could.
    """
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:32]


def type_from_name(name: str) -> str:
    """The file type, read off the name's extension.

    The name is the only source that covers both ways into the shelf:
    ``content`` arrives as plain text and a copied ``path`` carries no type
    either, while the extension travels with every delivery — the same
    reasoning the document dock's upload already spells out (the name is
    passed because "the extension matters and the content type does not
    reliably carry it").

    Without a type the shelf hands every file out as
    ``application/octet-stream``, and a delivered picture is then neither
    shown as a thumbnail nor accepted as an image in the chat.

    A compressed name ("report.md.gz") guesses the type of what is INSIDE
    the archive, not of the bytes stored here — that guess is dropped
    rather than served as a lie.
    """
    typ, kodierung = mimetypes.guess_type(name)
    if kodierung:
        return ""
    if not typ:
        # Only what Python's own table misses, and only here — a global
        # ``add_type`` would change how the whole program serves files.
        return NACHSCHLAG.get(Path(name).suffix.lower(), "")
    return typ


class AgentenDock:
    """The shelf and its files.

    Built on the FOLDER the shelf lives in, not on the data folder it used
    to be derived from: the folder is a storage location the user may move,
    and a shelf that worked out its own place from data_dir could never
    follow.

    The folder may be handed in as a path or as a question to ask — the
    registry holds one of these from startup to the next settings save, and
    a path bound back then would go on writing into the old folder for the
    rest of the session. Same reasoning, same shape as the script folder the
    cron tool is handed (``app/tools/aufbau.py``).
    """

    def __init__(self, ordner: Path | Callable[[], Path]) -> None:
        self._ordner = ordner

    @property
    def ordner(self) -> Path:
        return Path(self._ordner() if callable(self._ordner) else self._ordner)

    @property
    def pfad(self) -> Path:
        """The record — INSIDE the folder, so folder and record are one thing
        that moves together. A record left behind in the data folder would
        name files the new folder does not hold: every tile broken, and
        nothing on screen saying why."""
        return self.ordner / DATEI

    def alle(self) -> list[dict[str, Any]]:
        """What is on the shelf, for showing and for looking up.

        Soft on a record it cannot read: an empty wall and a loud line in the
        log, because a broken record must not take the whole agents panel
        down with it. The paths that WRITE read it strictly instead (see
        ``_lesen``) — that is where an unreadable record has to stop the
        world, not here.

        A file lying in the folder that the record does not know about is
        TAKEN IN here rather than ignored. The folder is the user's own — it
        is opened in the file manager and moved with a pencil — and a run
        that wrote into it with a file tool instead of the delivery tool put
        a real file there by any honest reading. It was simply invisible:
        measured on an installation whose shelf held a script and showed
        "nothing delivered yet".

        Only ever when the record could be read STRICTLY. On a damaged one
        this returns the empty wall as before and takes nothing in — writing
        stragglers over a record we could not read is the silent loss
        ``_lesen`` exists to prevent, and it would cost the names of
        everything already on the shelf.
        """
        try:
            liste = self._lesen(streng=True)
        except ValueError:
            return self._lesen(streng=False)
        return self._nachzuegler_aufnehmen(liste)

    def _nachzuegler_aufnehmen(
        self, liste: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Adds whatever lies in the folder unaccounted for.

        SHOWN, NOT WRITTEN DOWN. Listing is a read, and a read that writes is
        a read that can fail: a folder on a read-only mount made the whole
        agents panel answer 500 where it had listed the shelf perfectly well
        before, because the write of the side file raised underneath it.

        What the write was for was a STABLE id — a tile's id must be the same
        on the next listing or the very next click on it misses. That comes
        from the file's own name instead: the folder holds one flat set of
        names, so the name identifies the file as well as any record could,
        and it survives a folder nobody can write to.

        A straggler brings its own name — the difference from a delivered
        file, which lies there as ``<uuid><ext>`` and is nameless without the
        record. So its file name is its name, and it says nothing about who
        delivered it, because nobody did.
        """
        bekannt = {str(e.get("datei") or "") for e in liste}
        # The record and the side file a write goes through are bookkeeping,
        # not deliveries. The side file matters as much as the record: it
        # exists only between one write's two steps (app/atomic_file.py),
        # and a listing that caught it there would adopt a duplicate of the
        # record — and drop it again on the next listing.
        nachzuegler: list[dict[str, Any]] = []
        for pfad in ordnerinhalt.auflisten(self.ordner, auslassen=frozenset({DATEI})):
            if pfad.name in bekannt or atomic_file.is_side_file(pfad.name, DATEI):
                continue
            try:
                stand = pfad.stat()
            except OSError:
                # Gone since the listing. The next one will not see it either.
                continue
            nachzuegler.append(
                {
                    "id": _kennung_aus_name(pfad.name),
                    "name": pfad.name,
                    "datei": pfad.name,
                    "typ": type_from_name(pfad.name),
                    "groesse": stand.st_size,
                    # Nobody delivered it, so nobody is named.
                    "agent": "",
                    "abgelegt": datetime.fromtimestamp(
                        stand.st_mtime, tz=timezone.utc
                    ).isoformat(),
                }
            )
        return [*liste, *nachzuegler] if nachzuegler else liste

    def _lesen(self, streng: bool) -> list[dict[str, Any]]:
        """The record.

        ``streng`` is for the callers that are about to write it back.
        Reading it as an empty shelf there is what turned a damaged record
        into a permanent loss: the next delivery wrote its one entry over the
        whole list, and every file already on the shelf stayed on disk as a
        nameless ``<uuid>.md`` nobody could map back to a name. The record is
        the ONLY thing that holds those names, so a write that cannot read it
        first is refused — loudly, through the same road a refused delivery
        already takes (``ValueError`` -> ``AblageVerboten`` -> the run ends
        ``ablage_gescheitert``), and with every byte still where it was.

        Deliberately not "move it aside and start fresh": that is the silent
        loss again, only with the evidence renamed. The file stays in the
        user's own folder, named, openable and repairable.
        """
        pfad = self.pfad
        if not pfad.exists():
            return []
        try:
            daten = json.loads(pfad.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as fehler:
            log.warning("Dock record cannot be read (%s): %s", pfad, fehler)
            if streng:
                raise ValueError(
                    f"The agent dock's record ({pfad}) cannot be read, so nothing "
                    f"was written — writing would have overwritten it ({fehler})."
                ) from fehler
            return []
        if isinstance(daten, list):
            return daten
        log.warning("Dock record is not a list (%s)", pfad)
        if streng:
            raise ValueError(
                f"The agent dock's record ({pfad}) is not a list, so nothing was "
                "written — writing would have overwritten it."
            )
        return []

    def _schreiben(self, liste: list[dict[str, Any]]) -> None:
        """The one way of writing (``app/atomic_file.py``).

        ``write_text`` truncates and then writes, so anyone reading in
        between got half a file, read it as an empty shelf, and wrote that
        emptiness back. The bigger the shelf the wider that window: 89
        entries are 23 KB, which is no longer one go. A rename is a single
        step — a reader sees either the whole old record or the whole new
        one, and an interrupted write leaves the old one intact; and on
        Windows a second window reading the record no longer makes the
        rename fail.
        """
        pfad = self.pfad
        pfad.parent.mkdir(parents=True, exist_ok=True)
        atomic_file.write(pfad, json.dumps(liste, ensure_ascii=False, indent=2))

    def ablegen(
        self, name: str, daten: bytes, typ: str = "", agent: str = "", job: str = ""
    ) -> dict[str, Any]:
        """Copies a file onto the shelf. Raises ValueError when the record
        cannot be read.

        ``agent`` is who delivered — shown beside the file, so a shelf with
        several agents' output stays readable.

        ``job`` is the run that delivered it. Through the run's chat the doc
        folder knows which project a delivered file belongs to
        (app/docfolder.py); an entry without it belongs to none.

        ``typ`` is optional: left empty it is read off the name (see
        ``type_from_name``), so a delivery never has to know its own type.

        There is no ceiling on the number of files. The one that stood here
        refused the 51st delivery and left the run reporting success, and no
        part of the program ever cleared a place — a wall with no door. What
        it was there for (a runaway agent filling a disk) is answered by the
        per-file ceiling on the delivery tool and by the folder being the
        user's own, named, movable and openable, exactly as the picture
        folder is. The ceiling is checked there and not here, because the
        person drops files through this same method and has none.

        Read and write are one step under ``_SCHLOSS``: two deliveries at the
        same moment are the normal case (runs are ``asyncio`` tasks, two due
        cron entries or a firing beside a hand-started job), and read-then-
        write without a lock loses whichever of them writes first.
        """
        with _SCHLOSS:
            liste = self._lesen(streng=True)
            kennung = uuid.uuid4().hex
            sicher = sicherer_name(name)
            endung = Path(sicher).suffix
            self.ordner.mkdir(parents=True, exist_ok=True)
            (self.ordner / f"{kennung}{endung}").write_bytes(daten)

            eintrag = {
                "id": kennung,
                "name": eintragsname(name) or "Datei",
                "datei": f"{kennung}{endung}",
                # A given type wins; otherwise the name decides. Both ways in
                # (text ``content`` and a copied ``path``) meet here, so this
                # is the one place that needs to know.
                "typ": str(typ or "") or type_from_name(sicher),
                "groesse": len(daten),
                "agent": str(agent or ""),
                "job": str(job or ""),
                "abgelegt": _jetzt(),
            }
            self._schreiben([*liste, eintrag])
            return eintrag

    def holen(self, kennung: str) -> tuple[dict[str, Any], Path] | None:
        for eintrag in self.alle():
            if eintrag.get("id") == kennung:
                # The same guard the pictures use (app/ordnerinhalt.py). The
                # check that stood here compared the PARENT folder, and the
                # parent of a link is the folder it lies in — so a link named
                # innocently inside the shelf was served with whatever it
                # really pointed at. That was unreachable while only
                # server-minted entries existed; it stopped being unreachable
                # the moment the shelf started taking in what it finds.
                pfad = ordnerinhalt.sicherer_pfad(
                    self.ordner, str(eintrag.get("datei") or "")
                )
                if pfad is None:
                    return None
                return eintrag, pfad
        return None

    def entfernen(self, kennung: str) -> bool:
        """Takes one file off the shelf. Under the same lock and the same
        strict read as ``ablegen``: this rewrites the whole record too, and
        a delete racing a delivery would drop the delivery just as surely."""
        with _SCHLOSS:
            liste = self._lesen(streng=True)
            rest = [e for e in liste if e.get("id") != kennung]
            if len(rest) == len(liste):
                # Not in the record — but it may still be ON the shelf: a
                # file the folder holds that nobody delivered carries an id
                # derived from its own name and is never written down. The
                # cross on its tile has to take it away all the same, or the
                # wall shows a control that does nothing.
                return self._nachzuegler_entfernen(kennung)
            # Resolved from the entry we already have. Asking ``holen`` here
            # took this lock a second time through ``alle`` the moment the
            # folder held anything unaccounted for, and a plain lock taken
            # twice by one thread never comes back — the request simply
            # stopped, and every delivery after it queued behind it.
            eintrag = next(e for e in liste if e.get("id") == kennung)
            pfad = ordnerinhalt.sicherer_pfad(
                self.ordner, str(eintrag.get("datei") or "")
            )
            if pfad is not None:
                pfad.unlink(missing_ok=True)
            self._schreiben(rest)
            return True


    def _nachzuegler_entfernen(self, kennung: str) -> bool:
        """Deletes a file the folder holds and the record does not.

        Called with ``_SCHLOSS`` already held, and it takes no lock of its
        own: it touches one file and never the record, which is the whole
        reason a straggler needs no entry in the first place.
        """
        eigene = frozenset({DATEI, DATEI + ".neu"})
        for pfad in ordnerinhalt.auflisten(self.ordner, auslassen=eigene):
            if _kennung_aus_name(pfad.name) != kennung:
                continue
            sicher = ordnerinhalt.sicherer_pfad(self.ordner, pfad.name)
            if sicher is None:
                return False
            sicher.unlink(missing_ok=True)
            return True
        return False


def dock_fuer(config: "Config") -> AgentenDock:
    """The shelf as it stands right now.

    The folder is asked for at every call rather than bound once, so moving
    it in the agents panel is felt by the very next delivery, listing or
    download — no restart, the same promise the picture folder makes.

    The one place that builds a shelf: two callers needed it (the tool
    registry and the API), and a second way to work out the folder is a
    second answer waiting to disagree with the first.
    """
    _altbestand_uebernehmen(config, ort(config, ORT_NAME))
    dock = AgentenDock(lambda: ort(config, ORT_NAME))
    _carry_old_dock(config, dock)
    return dock


def _altbestand_uebernehmen(config: "Config", ordner: Path) -> None:
    """Carries a record written before the shelf had a folder of its own
    into that folder — once, and only while the shelf still stands where it
    was born.

    Without this, an installation that already had deliveries would open an
    empty shelf after the update while its files sat right there: a silent
    loss, and the very kind this step exists to end. Skipped as soon as the
    folder was moved, because then the files are elsewhere and dragging the
    old list after them would name what the new folder does not hold.
    """
    alt = Path(config.datenverzeichnis) / DATEI
    if not alt.is_file():
        return
    if ordner.resolve() != (Path(config.datenverzeichnis) / ORDNER).resolve():
        return
    neu = ordner / DATEI
    # Under the same lock as every other write, and the check belongs INSIDE
    # it: "the folder has no record yet" and "so move the old one in" have to
    # be one step. A delivery landing between the two wrote its record and
    # then had it replaced by the old folder's — the entry gone, its file
    # left in the folder as a nameless blob. And from then on the test above
    # is false forever, so the old record is never adopted at all.
    with _SCHLOSS:
        if neu.exists():
            return
        try:
            ordner.mkdir(parents=True, exist_ok=True)
            atomic_file.rename_onto(alt, neu)
        except OSError as fehler:
            # Not fatal: the shelf simply reads as empty this time round, and
            # the next start tries again. Loud in the log, because a shelf
            # that lost its record is worth looking at.
            log.warning(
                "Dock record could not be carried over (%s): %s", alt, fehler
            )


def _carry_old_dock(config: "Config", dock: AgentenDock) -> None:
    """Carries the person's own dock from before there was one dock onto
    this shelf — once, then removes it.

    Every entry keeps its id, name, type, size and date, and gets no agent:
    nobody delivered it, the person dropped it. Its file is COPIED first and
    the old folder is only removed once the record naming the copies has
    been written — an interruption anywhere before that leaves the old dock
    whole, and the next call simply tries again. An entry whose id the
    shelf already names is not taken twice, so a removal that failed after
    a written record does not duplicate anything on the next try.

    The old entries named the chat they were dropped in. That is not
    carried: the shelf is the place for what has no chat, and a chat's
    files live in the chat's own folder now.
    """
    daten = Path(config.datenverzeichnis)
    old_record = daten / OLD_DOCK_RECORD
    old_folder = daten / OLD_DOCK_FOLDER
    # The list is what names the files; a folder without it holds nameless
    # blobs nobody can map back, and those are left alone rather than lost.
    if not old_record.is_file():
        return
    try:
        gelesen = json.loads(old_record.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as fehler:
        # Left where it is: an unreadable list is the only thing that
        # still names those files, and removing it would lose them.
        log.warning("Old dock record cannot be read (%s): %s", old_record, fehler)
        return
    if not isinstance(gelesen, list):
        log.warning("Old dock record is not a list (%s)", old_record)
        return
    alt: list[dict[str, Any]] = gelesen
    with _SCHLOSS:
        try:
            liste = dock._lesen(streng=True)
        except ValueError:
            return
        bekannt = {str(e.get("id") or "") for e in liste}
        neu: list[dict[str, Any]] = []
        try:
            for eintrag in alt:
                if not isinstance(eintrag, dict):
                    continue
                kennung = str(eintrag.get("id") or "")
                datei = str(eintrag.get("datei") or "")
                if not kennung or kennung in bekannt:
                    continue
                quelle = ordnerinhalt.sicherer_pfad(old_folder, datei)
                if quelle is None:
                    continue
                dock.ordner.mkdir(parents=True, exist_ok=True)
                shutil.copy2(quelle, dock.ordner / quelle.name)
                neu.append(
                    {
                        "id": kennung,
                        "name": str(eintrag.get("name") or "") or "Datei",
                        "datei": quelle.name,
                        "typ": str(eintrag.get("typ") or "") or type_from_name(quelle.name),
                        "groesse": int(eintrag.get("groesse") or 0),
                        "agent": "",
                        "job": "",
                        "abgelegt": str(eintrag.get("abgelegt") or "") or _jetzt(),
                    }
                )
            if neu:
                dock._schreiben([*liste, *neu])
        except OSError as fehler:
            log.warning("Old dock could not be carried over (%s): %s", old_folder, fehler)
            return
    try:
        old_record.unlink(missing_ok=True)
        shutil.rmtree(old_folder, ignore_errors=True)
    except OSError as fehler:
        log.warning("Old dock could not be removed (%s): %s", old_folder, fehler)
