"""The dock — the one shelf for files without a chat.

The person drops files onto it from the start page; a job without a chat
delivers onto it through the ``deliver_file`` tool. A file dropped while a
chat is open goes into that chat's own folder instead, as a document of the
chat (``app/dokumentablage.py``) — the same way a job started from that chat
delivers.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError

from app import dokumentablage
from app.agentendock import AgentenDock, dock_fuer
from app.api.abhaengigkeiten import hole_sprache
from app.i18n import t

log = logging.getLogger(__name__)

router = APIRouter(prefix="/agentendock", tags=["agentendock"])


class AblageEintrag(BaseModel):
    id: str
    name: str
    typ: str = ""
    groesse: int = 0
    agent: str = ""
    abgelegt: str = ""


def _dock(request: Request) -> AgentenDock:
    # Per request, never held: the folder is a storage location the user can
    # move from the panel this very list feeds, so a shelf kept from startup
    # would go on listing the old place.
    return dock_fuer(request.app.state.config)


@router.get("/alle", response_model=list[AblageEintrag], summary="What is in the agent dock")
def liste(request: Request) -> list[AblageEintrag]:
    # Entry by entry, and a damaged one is dropped rather than raised. The
    # soft read behind ``alle`` promises an empty wall and a loud line for a
    # record it cannot read; a record whose ENTRIES are damaged has to keep
    # the same promise, or the promise only covers half the ways a
    # hand-repairable file can be wrong. Built in one comprehension, a single
    # bad row took the whole agents panel down with nothing on screen saying
    # whether the shelf or the record was the problem.
    eintraege: list[AblageEintrag] = []
    for roh in _dock(request).alle():
        try:
            eintraege.append(AblageEintrag(**roh))
        except (TypeError, ValidationError) as fehler:
            log.warning("Dock record entry unreadable, left out: %s", fehler)
    return eintraege


@router.post("", response_model=AblageEintrag, status_code=201, summary="Deliver a file")
async def ablegen(
    request: Request,
    name: str = "",
    chat: str = "",
    sprache: str = Depends(hole_sprache),
) -> AblageEintrag:
    """Raw bytes, like the image and document uploads: the name travels as a
    parameter because the extension matters and the content type does not
    reliably carry it. ``chat`` is the chat that was open when the file was
    dropped: then the file goes into that chat's own folder and stands as a
    document of the chat; empty on the start page, where it goes onto the
    dock. No size ceiling: the person's own file, like a picture upload."""
    daten = await request.body()
    if not daten:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Die Datei ist leer")
    typ = request.headers.get("content-type", "")
    if chat:
        try:
            dokument = dokumentablage.keep_in_chat(
                request.app.state.repositories,
                request.app.state.config.datenverzeichnis,
                chat,
                name,
                daten,
                typ,
            )
        except OSError as fehler:
            # A name that cannot become a file there, or a folder that
            # cannot be written: said as a refusal, not as a crash.
            log.warning("Drop into chat %s not stored: %s", chat, fehler)
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, t("fehler.allgemein", sprache)
            ) from fehler
        if dokument is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, t("fehler.chat_nicht_gefunden", sprache)
            )
        return AblageEintrag(
            id=dokument.id,
            name=dokument.filename,
            typ=dokument.mime_type or "",
            groesse=dokument.size_bytes or 0,
            abgelegt=dokument.created_at,
        )
    try:
        eintrag = _dock(request).ablegen(name, daten, typ)
    except ValueError as fehler:
        raise HTTPException(status.HTTP_409_CONFLICT, str(fehler)) from fehler
    return AblageEintrag(**eintrag)


@router.get("/{kennung}", summary="Fetch a file from the agent dock")
def datei(kennung: str, request: Request) -> FileResponse:
    gefunden = _dock(request).holen(kennung)
    if gefunden is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Diese Datei gibt es nicht")
    eintrag, pfad = gefunden
    return FileResponse(
        pfad,
        media_type=eintrag.get("typ") or "application/octet-stream",
        filename=eintrag.get("name") or "Datei",
    )


@router.delete(
    "/{kennung}", status_code=204, response_class=Response, summary="Remove a file"
)
def entfernen(kennung: str, request: Request) -> Response:
    if not _dock(request).entfernen(kennung):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Diese Datei gibt es nicht")
    return Response(status_code=204)
