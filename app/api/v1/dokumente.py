"""Document upload.

The path is the same as for images: upload raw bytes BEFORE sending the
message. What gets stored is the **extracted text** — the ``documents`` table
has been ready for that since phase 1 (``extracted_text``) — and, since the
file is kept, the place that file lies in.

**The file stays.** It used to be dropped once the text was out, and with it
went every way of reading a passage back: a document too large to travel
inside a request was named and nothing more, and a page number could not be
recovered at all. It is written into the folder shared with the chat instead
(``app/dokumentablage.py``), and nothing ever deletes it again. A chat sharing
no folder writes into a folder of its own instead, which goes when the chat
goes.

Extraction means READING from the file — nothing is generated. PDFs are read
by pypdf, page by page (``app/pdfseiten.py``, the same reader ``read_file``
uses); every other allowed ending is text already. The whole text is kept: how much of it a
request carries is decided per model when the request is built
(app/dokumentbudget.py) — whole where it fits the window and stays under
a ceiling of half that window, not at all where it does not. Those two are all a card can say, and a card says which of them
happened (``getragen``). Where it does not fit, the request names the file's
place so the model can read the parts it needs.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import docfolder, dokumentablage, pdfseiten
from app.agentendock import type_from_name
from app.api.abhaengigkeiten import hole_repositories, hole_sprache
from app.db import Repositories
from app.i18n import t
from app.ordner_oeffnen import OeffnenNichtMoeglich, datei_oeffnen

router = APIRouter(tags=["dokumente"])

# Every text ending a document may carry — the gate is the name's ending,
# never the bytes. Read as UTF-8; ``.env`` is deliberately absent: it holds
# keys, not prose. One list gates the upload and the card's kind.
TEXT_ENDUNGEN = (
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".log", ".json", ".jsonl", ".ndjson", ".xml",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".properties", ".html", ".htm",
    ".css", ".scss", ".sass", ".less", ".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".c", ".h", ".cpp", ".cc", ".hpp", ".cs",
    ".java", ".kt", ".go", ".rs", ".rb", ".php", ".pl", ".lua", ".r", ".jl", ".swift", ".m",
    ".scala", ".clj", ".ex", ".exs", ".erl", ".sql", ".graphql", ".proto", ".tf", ".hcl",
    ".dockerfile", ".makefile", ".cmake", ".gradle", ".rst", ".tex", ".srt", ".vtt", ".diff",
    ".patch",
)
ERLAUBTE_ENDUNGEN = {
    **{endung: "text/plain" for endung in TEXT_ENDUNGEN},
    ".md": "text/markdown",
    ".pdf": "application/pdf",
}
MAX_BYTES = 20 * 1024 * 1024


def _reiner_name(roh: str) -> str:
    """Only the file name, never a path — no matter which system it comes
    from. A null byte cannot stand in any file name, so it goes."""
    return PureWindowsPath(PurePosixPath(roh).name).name.replace("\x00", "")


def _endung(name: str) -> str:
    """The name's ending, lower case, the dot included — "" when it has none."""
    return ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""


# What the latest answer carried of a document, as the service writes it
# onto the message the document hangs on (app/api/v1/generierung.py): the
# whole text, no more than its name — or a third answer, written AFTER the
# request came back refused for its size. The first two are a plan made
# before the request goes out; only the third one knows what really
# happened, and without it the card kept saying "whole in the context"
# beside a turn that said the context was full.
ABGELEHNT = "abgelehnt"
GETRAGEN = ("ganz", "kein_platz", ABGELEHNT)


class DokumentMeta(BaseModel):
    id: str
    name: str
    typ: str  # the name's ending without its dot: "pdf", "html", …
    seiten: int | None = None
    kb: int
    # One of GETRAGEN, or None while no answer has carried the document yet.
    getragen: str | None = None
    # Where the file itself lies, so the window can show it; None for an
    # upload from before files were kept.
    pfad: str | None = None


class DokumentHochgeladen(BaseModel):
    dokument: DokumentMeta


@router.post(
    "/documents",
    response_model=DokumentHochgeladen,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document for a message (raw bytes) and extract its text",
)
async def dokument_hochladen(
    chat_id: str,
    name: str,
    request: Request,
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> DokumentHochgeladen:
    # The switch in the config really counts (interface close-out C):
    # off means off, even if someone talks to the API directly.
    if not request.app.state.config.features.document_upload:
        raise HTTPException(status.HTTP_403_FORBIDDEN, t("fehler.funktion_aus", sprache))

    chat = repositories.chats.holen(chat_id)
    if chat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("fehler.chat_nicht_gefunden", sprache))

    # The gate reads the whole name; only what is stored is capped, and
    # the ending stays part of it — a cut-off ending would leave the file
    # in the shared folder a nameless thing this same route refuses.
    voller_name = _reiner_name(name)
    endung = _endung(voller_name)
    if endung not in ERLAUBTE_ENDUNGEN:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, t("fehler.dokument_typ", sprache)
        )
    anzeigename = voller_name
    if len(voller_name) > 120:
        anzeigename = voller_name[: 120 - len(endung)] + endung

    daten = await request.body()
    if len(daten) > MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, t("fehler.dokument_zu_gross", sprache)
        )
    if not daten:
        # An empty body has no text to carry — the same answer an empty
        # document gets below, not a word about file types.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, t("fehler.dokument_unlesbar", sprache)
        )

    seiten: int | None = None
    if endung == pdfseiten.ENDUNG:
        try:
            seitentexte = pdfseiten.seiten(daten, merken=False)
        except pdfseiten.PdfUnlesbar as fehler:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                t("fehler.dokument_unlesbar", sprache),
            ) from fehler
        seiten = len(seitentexte)
        leer = not any(seite.strip() for seite in seitentexte)
        text = pdfseiten.volltext(seitentexte)
    else:
        text = daten.decode("utf-8", errors="replace")
        leer = not text.strip()

    text = text.strip()
    if leer:
        # A scan without a text layer, for example — reject honestly instead
        # of slipping the model an empty document. Checked on the raw pages
        # for a PDF, because the [page N] marks volltext() adds would
        # otherwise turn even an all-blank PDF into non-empty text.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, t("fehler.dokument_unlesbar", sprache)
        )

    # And the file itself stays, in the folder shared with the chat. That is
    # what makes a document readable again after its text has left the prompt:
    # the row carries the place, and `read_file` reads the page or the stretch
    # the model asks for. A chat with no shared folder falls back to a folder
    # of its own under the data folder, so that chat is no longer the dead end
    # it was — same writer, same rules, only a different roof.
    pfad = dokumentablage.ablegen(
        daten,
        anzeigename,
        chat.working_dirs,
        rueckfall=dokumentablage.chatordner(
            request.app.state.config.datenverzeichnis, chat.id
        ),
    )

    # The whole text is kept — nothing is cut here any more. How much of it
    # a request carries is decided per model when the request is built
    # (app/dokumentbudget.py): whole where it fits the window, not at all
    # where it does not. The file-size cap above is the only ceiling.
    dokument = repositories.documents.speichern(
        chat_id=chat.id,
        filename=anzeigename,
        mime_type=ERLAUBTE_ENDUNGEN[endung],
        size_bytes=len(daten),
        extracted_text=text,
        pages=seiten,
        pfad=pfad,
    )
    return DokumentHochgeladen(dokument=meta_bauen(dokument))


class DokumentInhalt(BaseModel):
    """The stored text of one document — what the preview shows.

    The extracted text, not the file: what the model reads is what is shown.
    The file itself lies in the shared folder and is the user's to open.
    """

    dokument: DokumentMeta
    text: str


@router.get(
    "/documents/{dokument_id}",
    response_model=DokumentInhalt,
    summary="Text extracted from a document (for the preview)",
)
def dokument_lesen(
    dokument_id: str,
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> DokumentInhalt:
    dokument = repositories.documents.holen(dokument_id)
    if dokument is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t("fehler.dokument_fehlt", sprache)
        )
    return DokumentInhalt(
        dokument=meta_bauen(dokument),
        text=dokument.extracted_text or "",
    )


@router.post(
    "/documents/{dokument_id}/open",
    response_model=bool,
    summary="Open a saved document in the system's default application",
)
def dokument_oeffnen(
    dokument_id: str,
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> bool:
    """Opens the file a document row points at — never a path the client
    names itself. The id is the only input; the place it leads to comes
    entirely out of the database, the same boundary `/ordner/oeffnen`
    draws for a shared folder.
    """
    dokument = repositories.documents.holen(dokument_id)
    if dokument is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t("fehler.dokument_fehlt", sprache)
        )
    if not dokument.pfad:
        # Found, but nothing was ever kept for it (a document from before
        # the file itself was stored) — honest about what is missing rather
        # than a 404 that would claim the document itself does not exist.
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, t("fehler.dokument_oeffnen", sprache)
        )
    try:
        datei_oeffnen(Path(dokument.pfad))
    except OeffnenNichtMoeglich:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, t("fehler.dokument_oeffnen", sprache)
        ) from None
    return True


@router.delete(
    "/documents/{dokument_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Remove a document that has not been sent",
)
def dokument_entfernen(
    dokument_id: str,
    request: Request,
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> None:
    """The ✕ on an attachment that was uploaded on picking it (4.1's
    upload-on-attach) and never sent. Once a message carries the document,
    this route refuses: from there on only that message's own ✕
    (`/chats/{chat_id}/messages/{message_id}/anhang`) may drop it, because
    that one checks the document against the message it is actually
    attached to instead of taking a bare id on faith.
    """
    dokument = repositories.documents.holen(dokument_id)
    if dokument is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t("fehler.dokument_fehlt", sprache)
        )
    if repositories.messages.dokument_angehaengt(dokument_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, t("fehler.dokument_gesendet", sprache)
        )
    repositories.documents.loeschen(
        dokument_id, datenverzeichnis=request.app.state.config.datenverzeichnis
    )


class DocFolderEntry(BaseModel):
    id: str
    source: str
    origin: str
    name: str
    type: str = ""
    size: int = 0
    created: str = ""
    agent: str = ""
    chat_id: str | None = None
    project_id: str | None = None
    path: str = ""


@router.get(
    "/doc-folder",
    response_model=list[DocFolderEntry],
    summary="List all uploaded and delivered files with their origins",
)
def doc_folder(
    request: Request,
    origin: str | None = Query(default=None, pattern=docfolder.ORIGIN_PATTERN),
    project: str | None = None,
    chat: str | None = None,
    repositories: Repositories = Depends(hole_repositories),
) -> list[DocFolderEntry]:
    """``chat``: the open chat's files only; without it, every file."""
    return [
        DocFolderEntry(**row)
        for row in docfolder.entries(
            request.app.state.config,
            repositories,
            origin=origin,
            project=project,
            chat=chat,
        )
    ]


class DocFolderPlace(BaseModel):
    path: str


@router.get(
    "/doc-folder/place",
    response_model=DocFolderPlace,
    summary="The folder the doc folder's files of a chat lie in",
)
def doc_folder_place(
    request: Request,
    chat: str,
    language: str = Depends(hole_sprache),
) -> DocFolderPlace:
    """The path the folder row of an open chat names. Without a chat the row
    names the dock, which the storage locations already say."""
    path = docfolder.chat_folder_path(request.app.state.config, chat)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("fehler.dokument_fehlt", language))
    return DocFolderPlace(path=path)


@router.get("/documents/{dokument_id}/file", summary="The uploaded file")
def document_file(
    dokument_id: str,
    repositories: Repositories = Depends(hole_repositories),
    language: str = Depends(hole_sprache),
) -> FileResponse:
    """The file a document row points at, for the doc folder's card. The
    place comes out of the database, never from the request — the same
    boundary the route that opens it draws."""
    document = repositories.documents.holen(dokument_id)
    if document is None or not document.pfad or not Path(document.pfad).is_file():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t("fehler.dokument_fehlt", language)
        )
    return FileResponse(
        document.pfad,
        media_type=document.mime_type or "application/octet-stream",
        filename=document.filename,
        content_disposition_type=_disposition(document.mime_type),
    )


@router.get(
    "/chat-files/{chat_id}/{name:path}",
    summary="A file within a chat's own folder that is not referenced by any document",
)
def chat_file(
    chat_id: str,
    name: str,
    request: Request,
    language: str = Depends(hole_sprache),
) -> FileResponse:
    """What a write tool or a command left in the chat's folder or in a
    folder below it, for the doc folder's tile. The chat and the path below
    its folder are all the request may say: the folder is built from the
    id, and what the path resolves to has to lie in that folder
    (``docfolder.chat_file``) — ``..`` and a link leading out get the 404 of
    a file that is not there.

    Handed out the way a document's file is: only a PDF is shown in place.
    A page a model wrote must never run under this service's address."""
    file = docfolder.chat_file(request.app.state.config, chat_id, name)
    if file is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t("fehler.dokument_fehlt", language)
        )
    mime_type = type_from_name(file.name) or "application/octet-stream"
    return FileResponse(
        file,
        media_type=mime_type,
        filename=file.name,
        content_disposition_type=_disposition(mime_type),
    )


# The one type the window shows in a frame: the browser's own viewer draws a
# PDF's pages, and it only does so for an answer that says "inline".
FRAMED_TYPE = "application/pdf"


def _disposition(mime_type: str | None) -> str:
    """How the browser is to take the file: shown in place, or saved.

    Only a PDF is shown. Every other type keeps "attachment": a file of this
    shelf is never served as a page, and an address that opened one in place
    would hand a document's own markup this service's origin."""
    return "inline" if mime_type == FRAMED_TYPE else "attachment"


def meta_bauen(dokument, getragen: str | None = None) -> DokumentMeta:
    """The meta card for the window — always built from the database row,
    never from client input. The message retrieval uses it too.

    ``getragen`` is what the latest answer carried of it, read off the
    message by the caller; anything but one of GETRAGEN counts as no word."""
    # The kind is the file name's own ending. Reading it back off the
    # media type turned random the moment several endings shared one type;
    # a row without any ending falls back the way it always did.
    endung = _endung(dokument.filename or "") or ".txt"
    return DokumentMeta(
        id=dokument.id,
        name=dokument.filename,
        typ=endung[1:],
        seiten=dokument.pages,
        kb=max(1, round((dokument.size_bytes or 0) / 1024)),
        getragen=getragen if getragen in GETRAGEN else None,
        pfad=dokument.pfad or None,
    )
