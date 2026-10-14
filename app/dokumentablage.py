"""Where an uploaded document lands on disk.

The upload used to read the file, pull its text out and drop the bytes. After
that the file existed nowhere: no tool could fetch a passage back once the
document's row had left the prompt, and a page number was gone for good,
because joining the pages is the only thing that was kept.

So the file is kept. It goes into the folder shared with the chat — next to
the ``exe.md``, the place that already belongs to this project — and nothing
ever removes it again: what happens to a file in the user's own folder is the
user's decision, not the program's.

**A chat that shares no folder gets one of its own**, under the chat's id in
the program's data folder. Without it that chat was a dead end: no place, no
path on the row, and after a compaction the model could only say it no longer
had the wording. The folder belongs to the program, not to the user, so it is
deliberately NOT a named location (``app/speicherorte.py``): an entry in
``ORTE`` shows up in the settings screen and can be pointed elsewhere there,
while ``setzen`` moves no file — every path already stored would then lead
nowhere. It lies fixed under the data folder and travels only with it.

The same document in five such chats lies five times, and that is the
intent: no chat counts who else still needs a file, each one clears up after
itself. When the chat goes, its folder goes with it
(``app/db/repositories/chats.py``), and a document taken off a message takes
its file (``app/db/repositories/documents.py``) — the user's own shared folder
never loses anything either way.

**Nothing here may break an upload.** A read-only folder, a share that has
since been unplugged, a data folder that cannot be written: the document then
lives in the database alone, exactly as every document did before, and the
upload succeeds. What is lost in that case is the reading back, not the
document.

**An existing file is never overwritten.** Holding the same bytes it already
IS the answer and is used as it lies. Holding different ones it keeps its
place, and the upload lands beside it under a name carrying the content's
fingerprint — so the same file uploaded twice still only lands once, and a
second, different ``report.pdf`` does not eat the first.

The write goes past the permission gate (``app/berechtigungen.py``), the same
way ``app/ordnerwissen.py`` writes an ``exe.md``: the program is acting on an
explicit action of the user's — they just attached this file — not on a
model's call. That is only defensible while the target cannot move, which is
why the name arrives stripped to its last segment and the result is checked
to lie inside the shared folder.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from typing import Any

from app import ordnerwissen

log = logging.getLogger(__name__)

# How much of the content's fingerprint distinguishes two files of the same
# name. Long enough that two different documents in one folder will not
# collide, short enough to stay readable in a file name.
KENNUNG_ZEICHEN = 8

# The folder under the data folder that holds one subfolder per chat without
# a shared folder of its own. A plain name, resolved from the data folder at
# every call, so it follows a moved data folder and can never be moved on its
# own — see the module docstring for why that is the point.
CHATDATEIEN = "chat_files"


def chatordner(datenverzeichnis: Path, chat_id: str) -> Path | None:
    """Where THIS chat keeps uploads when it shares no folder of its own.

    Not created here — the folder comes into being at the first upload
    (``ablegen``), or when a tool call that works in it RUNS while it is
    missing — a reading one as much as a writing one, a file tool or a
    command (``app/tools/grenzen.py``, ``prepare_folders``) — not on the
    chance of one, and never while the model is still writing the call.

    ``None`` for an id that is not one: chat ids are hex uuids, and the id
    travels in from a URL, so anything that could climb out of the data
    folder or name a place of its own is refused rather than sanitised.
    """
    if not chat_id or not all(z.isalnum() or z in "-_" for z in chat_id):
        return None
    return datenverzeichnis / CHATDATEIEN / chat_id


def aufraeumen(datenverzeichnis: Path, chat_id: str) -> None:
    """Removes this one chat's folder, with whatever lies in it.

    Only ever this folder: the path is built here from the data folder and
    the id, never taken from a row, so nothing the user shared can end up
    under this call. A folder that was never created is not an error — most
    chats never upload anything.
    """
    ordner = chatordner(datenverzeichnis, chat_id)
    if ordner is None:
        return
    try:
        shutil.rmtree(ordner)
    except FileNotFoundError:
        return
    except OSError as fehler:
        log.warning("Chat folder %s could not be removed: %s", ordner, fehler)


def eigene_datei_entfernen(datenverzeichnis: Path, chat_id: str, pfad: str) -> None:
    """Removes ONE uploaded file — and only out of this chat's own folder.

    A file in a folder of the user's is never the program's to remove: what
    happens to it is their decision, as the module docstring says. So the
    path is measured against the folder this module built itself, and
    anything lying anywhere else is left exactly where it is.

    For the row that goes when a document is taken off a message. Without
    it, the file in the program's own folder would outlive the only thing
    that could name it.
    """
    ordner = chatordner(datenverzeichnis, chat_id)
    if ordner is None:
        return
    try:
        ziel = Path(pfad).resolve()
        ziel.relative_to(ordner.resolve())
    except (OSError, RuntimeError, ValueError):
        return
    try:
        ziel.unlink()
    except FileNotFoundError:
        return
    except OSError as fehler:
        log.warning("Document file %s could not be removed: %s", ziel, fehler)


def program_folders(config: Any) -> list[str]:
    """The dock and the picture folder — the two places every run sees,
    in a chat and in a job, beside its own folders.

    Asked for by name: ``ort()`` answers with the place each is ACTUALLY
    kept, so a folder the user moved is still the one a run may read. Made
    when missing, because the file tools refuse a share whose folder does
    not exist, and an untouched installation has neither before the first
    delivery or picture. A folder that cannot be made (a moved location on a
    drive that is not plugged in) is not worth failing a run over: the share
    is simply refused later.

    The folders themselves, never the data folder above them — that one
    holds chats, keys and the configuration (``app/speicherorte.py``
    refuses a location there).
    """
    from app import speicherorte
    from app.agentendock import ORT_NAME

    orte = [speicherorte.ort(config, ORT_NAME), speicherorte.ort(config, "images")]
    for ort in orte:
        try:
            ort.mkdir(parents=True, exist_ok=True)
        except OSError as fehler:
            log.warning("Folder cannot be created (%s): %s", ort, fehler)
    return [str(ort) for ort in orte]


def ordner_dieses_chats(
    datenverzeichnis: Path,
    working_dirs: list[str] | None,
    chat_id: str,
    program: list[str] | None = None,
) -> list[str]:
    """The folders a tool call of THIS chat may work in.

    The user's shared folders, plus — at the end, never in front — this
    chat's own document folder, which a chat sharing nothing writes its
    uploads into. It counts as shared for this one chat: without that, the
    very file a request tells the model to read back would sit outside the
    fence and ``read_file`` would ask about it or refuse it.

    At the end, because the first folder in the list is also where a relative
    path is resolved from (``app/tools/grenzen.py``) — a chat that shares a
    folder of the user's must keep working from that one.

    The gate itself is not touched for this (``app/berechtigungen.py``,
    ``app/tools/registry.py``): it is handed a list of folders and knows
    nothing of chats, so the folder is put into the list by the callers that
    know which chat this is. Another chat's folder is never in that list and
    stays outside for it, like any other path.

    In the list once it exists — and, while nothing else is shared, even
    before: then it is the chat's floor, the one place its file tools work
    in. It is created at the first upload, or when a call that works in it
    runs while nothing else is shared — reading or writing, a file tool or
    a command (``app/tools/grenzen.py``, ``prepare_folders``), or when the user opens
    it from the folder chip's menu ("Open", ``app/api/v1/arbeitsordner.py``)
    — the last one also in a chat that shares folders, and from then on the
    model sees it beside them. A chat that never needs it leaves no empty
    folder behind. With a folder of the user's
    shared it is not named before it exists: a folder named to the model
    and then not found would only send it at a refusal.

    ``working_dirs`` itself is deliberately left alone. Where it comes from
    changes with the projects step, and a second writer here would have to be
    undone there.

    ``program`` is ``program_folders`` as the caller read it: the dock and
    the picture folder, after everything else and once each, so a relative
    path still resolves against the chat's own first folder.
    """
    ordner = list(working_dirs or [])
    eigen = chatordner(datenverzeichnis, chat_id)
    if eigen is not None and (not ordner or eigen.is_dir()):
        ordner.append(str(eigen))
    for pfad in program or []:
        if pfad not in ordner:
            ordner.append(pfad)
    return ordner


def own_folder_in(
    datenverzeichnis: Path, chat_id: str, working_dirs: list[str] | None, folders: list[str]
) -> str | None:
    """This chat's own folder when ``ordner_dieses_chats`` put it into
    ``folders`` and the user did not share it too — so the prompt can name
    it as the chat's own and not as one of the user's shares. None
    otherwise: a folder the user shared is a share, whoever made it."""
    own = chatordner(datenverzeichnis, chat_id)
    if own is None or str(own) not in folders or str(own) in (working_dirs or []):
        return None
    return str(own)


def _kennzeichnet(ziel: Path, daten: bytes) -> Path:
    """The same name with the content's fingerprint in it."""
    kennung = hashlib.sha256(daten).hexdigest()[:KENNUNG_ZEICHEN]
    return ziel.with_name(f"{ziel.stem} ({kennung}){ziel.suffix}")


def _passt(ziel: Path, daten: bytes) -> bool:
    """Whether the file already lying there is this very document."""
    try:
        return ziel.is_file() and ziel.read_bytes() == daten
    except OSError:
        return False


def _wurzel(ordner: list[str], rueckfall: Path | None) -> Path | None:
    """The folder this upload writes into, or ``None`` when there is none.

    The chat's first shared folder wins wherever there is one — the file then
    lies where the user already keeps this project's things, and stays there
    for good. Only a chat that shares nothing falls back to its own folder,
    which is created right here, at the first upload that needs it.
    """
    if ordner:
        try:
            wurzel = Path(ordner[0]).resolve()
        except (OSError, RuntimeError):
            return None
        return wurzel if wurzel.is_dir() else None
    if rueckfall is None:
        return None
    try:
        rueckfall.mkdir(parents=True, exist_ok=True)
        return rueckfall.resolve()
    except (OSError, RuntimeError) as fehler:
        log.warning("Chat folder %s could not be created: %s", rueckfall, fehler)
        return None


def ablegen(
    daten: bytes, name: str, ordner: list[str], rueckfall: Path | None = None
) -> str | None:
    """Keeps the uploaded bytes in the chat's first shared folder.

    ``rueckfall`` is this chat's own folder (``chatordner``), used only when
    the chat shares none of the user's — everything below happens the same
    way in either place: the fingerprint in the name, the same bytes reused
    where they already lie, ``exe.md`` out of reach. One way, one writer.

    Returns the absolute path of the file the document can be read from, or
    ``None`` when there is no folder to write into or the write did not work.

    ``name`` must already be stripped to a file name (no path); the result is
    checked against that folder regardless.
    """
    wurzel = _wurzel(ordner, rueckfall)
    if wurzel is None:
        return None
    # What ``exe.md`` is measured against below: the shared folders where
    # there are any, otherwise the one folder this upload is writing into.
    freigaben = ordner or [str(wurzel)]

    try:
        ziel = (wurzel / name).resolve()
    except (OSError, RuntimeError):
        return None
    try:
        ziel.relative_to(wurzel)
    except ValueError:
        # A name that climbs out of the shared folder is not written at all.
        log.warning("Document name points out of the folder: %r", name)
        return None

    # The one name an upload may never take. An ``exe.md`` at the top of a
    # shared folder is read as the user's own word and goes into the system
    # message of every chat sharing that folder (app/ordnerwissen.py) — so a
    # document called exe.md, which .md uploads make possible, would write
    # itself into the system prompt. It lands under its fingerprint instead,
    # where it is an ordinary file like every other.
    if ordnerwissen.ist_notiz(ziel, freigaben):
        ziel = _kennzeichnet(ziel, daten)

    if ziel.exists():
        if _passt(ziel, daten):
            return str(ziel)
        ziel = _kennzeichnet(ziel, daten)
        if ziel.exists():
            # Same name AND same fingerprint: this is the same document
            # again. Anything else under that name is not written over.
            return str(ziel) if _passt(ziel, daten) else None

    try:
        ziel.write_bytes(daten)
    except OSError as fehler:
        log.warning("Document %r could not be stored: %s", name, fehler)
        return None
    return str(ziel)


def _file_name(name: str) -> str:
    """The name a kept file goes by: its last path segment, blanks folded,
    and nothing a file name cannot hold."""
    return Path(" ".join(str(name or "").split())).name.replace("\x00", "")


def _already_in_chat_folder(datenverzeichnis: Path, chat_id: str, source: Path) -> str | None:
    """The path of ``source`` where it is a file that already lies in this
    chat's own folder — in a subfolder as well — and ``None`` for any other.

    Both sides are resolved first, so a link or a ``..`` cannot pass a file
    from elsewhere for one of the chat's own."""
    folder = chatordner(datenverzeichnis, chat_id)
    if folder is None:
        return None
    try:
        file = source.resolve()
        if file.is_file() and file.is_relative_to(folder.resolve()):
            return str(file)
    except (OSError, RuntimeError):
        pass
    return None


def keep_in_chat(
    repositories: Any,
    datenverzeichnis: Path,
    chat_id: str,
    name: str,
    daten: bytes,
    typ: str = "",
    agent: str = "",
    job: str = "",
    source: Path | None = None,
) -> Any | None:
    """Keeps a file in THIS chat's own folder and enters it as a document of
    the chat — what the person drops in an open chat, what the chat's own
    model delivers, and what a job started from that chat delivers.

    Always the chat's own folder, never a folder the user shared: the file
    belongs to the chat and has to go with it when the chat is deleted for
    good (``aufraeumen``), and a shared folder of the user's never loses
    anything. The row carries no extracted text — it is a file in the
    folder, not an attachment a request carries; the model reads it with
    ``read_file`` like any other file there.

    ``source`` is the file a delivery was made from, where it came from a
    path: one that already lies in the chat's own folder is not copied — the
    row points at it, so the folder holds one file and the wall one tile.

    ``None`` when the chat does not exist (the caller then keeps the file in
    the dock). Raises ``OSError`` when the file could not be written, so the
    caller can say so instead of reporting a file that is not there.
    """
    # The type is read off the name the way the shelf reads it: a delivery
    # carries none, and Python's own table misses the Markdown a report
    # mostly is — without one the file route hands it out as raw bytes.
    from app.agentendock import type_from_name

    if repositories.chats.holen(chat_id) is None:
        return None
    rueckfall = chatordner(datenverzeichnis, chat_id)
    if rueckfall is None:
        return None
    dateiname = _file_name(name)
    pfad = (
        _already_in_chat_folder(datenverzeichnis, chat_id, source) if source is not None else None
    ) or ablegen(daten, dateiname or "file", [], rueckfall=rueckfall)
    if pfad is None:
        raise OSError(f"'{dateiname}' could not be stored in the chat's folder.")
    return repositories.documents.speichern(
        chat_id=chat_id,
        filename=dateiname or "file",
        mime_type=typ or type_from_name(dateiname) or None,
        size_bytes=len(daten),
        pfad=pfad,
        agent=agent or None,
        job=job or None,
    )


def deliver_to_chat(
    repositories: Any,
    datenverzeichnis: Path,
    *,
    name: str,
    daten: bytes,
    agent: str = "",
    job: str = "",
    chat: str = "",
    answer: str | None = None,
    source: Path | None = None,
) -> Any | None:
    """A delivery kept in a chat — one way for the two callers that have one.

    A job names itself (``job``) and the file goes into the chat the job was
    started from. A chat's own call names the chat (``chat``) and the answer
    it is writing (``answer``): the document is hung on that row, so the
    file stands in the answer it was delivered with, the way an upload
    stands on the message it came with.

    ``None`` when there is no chat to keep it in — a job without one, or a
    chat that is gone. A job's delivery then goes onto the dock
    (``app/tools/agentendock.py``)."""
    if job:
        auftrag = repositories.auftraege.holen(job)
        chat = (auftrag.chat_id or "") if auftrag is not None else ""
    if not chat:
        return None
    if answer:
        # The same file handed over twice in one answer is one card: a model
        # that repeats its call after its own result gets the document it
        # already delivered, not a second row for the same bytes.
        row = repositories.messages.holen(answer)
        for known_id in row.dokument_ids() if row is not None else []:
            known = repositories.documents.holen(known_id)
            if (
                known is not None
                and known.filename == (_file_name(name) or "file")
                and known.pfad
                and _passt(Path(known.pfad), daten)
            ):
                return known
    document = keep_in_chat(
        repositories, datenverzeichnis, chat, name, daten, agent=agent, job=job, source=source
    )
    if document is not None and answer:
        repositories.messages.attach_document(answer, document.id)
    return document


def nachlesehinweis(pfad: str | None, seiten: int | None = None) -> str:
    """What a request tells the model about a document it cannot carry.

    The whole point of keeping the file: a document that does not fit, or one
    whose row has been folded away, is not simply gone — it lies somewhere,
    and the model has a tool that reads it. So the note says the place and the
    way, because a model told only "too large" has no next move and answers
    from what it half remembers instead.

    Empty where there is no file to read: a chat that shares no folder, or a
    document uploaded before the file was kept. Said by the one module that
    knows where these files live, and read by every note that has to mention
    them (app/verlaufsbau.py, app/chatverdichtung.py), so the way to read one
    back is described in a single place.

    It names the tool as a condition, not as a promise: the file tools can be
    switched off and a shared folder can be taken back, and this note also
    travels inside a stored summary, which outlives both. A flat promise would
    send the model at a refusal it has no way past.
    """
    if not pfad:
        return ""
    # A picture is read whole, every time: ``read_file`` takes no page, no
    # offset and no limit for one. Naming them would send the model at
    # arguments that do nothing but look like they might.
    #
    # The same two-step check ``read_file`` itself makes (app/tools/
    # datei_lesen.py): a picture-shaped name is only the gate, the bytes
    # decide. A text file named ``.png`` fails the byte check there and is
    # read in sections like any other text — this note has to say the same
    # thing, or it promises arguments the tool never asks for.
    from app.api.v1.bilder import ANZEIGBARE_ENDUNGEN

    ist_bild = False
    if Path(pfad).suffix.lower() in ANZEIGBARE_ENDUNGEN:
        from app.tools.datei_lesen import medientyp_aus_pfad

        ist_bild = medientyp_aus_pfad(pfad) is not None

    if ist_bild:
        return (
            f" The file is located at '{pfad}'. If read_file is available among your tools, "
            "use it to read the file."
        )
    umfang = f", {seiten} pages" if seiten else ""
    return (
        f" The file is located at '{pfad}'{umfang}. If read_file is available among your "
        "tools, use it to read the required sections: use page for a single PDF page, or "
        "offset and limit for a range of lines."
    )
