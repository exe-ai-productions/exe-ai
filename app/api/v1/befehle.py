"""The command runs of a chat — what has run, and what is running right now.

Its own channel, not part of the answer stream, and for one reason: a
background run outlives the answer that started it. Hanging its lines on the
generation would mean they stop arriving the moment the model is done
talking, which is precisely when a long build is still going.

Two routes belong together: the window asks once for what is there and then
keeps listening. A third stops a run.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.abhaengigkeiten import hole_benutzer_id, hole_repositories, hole_sprache
from app.db import Repositories
from app.i18n import t
from app import bildlauf
from app.tools.hintergrund import ART_BILD, Lauf, laeufe

log = logging.getLogger(__name__)

router = APIRouter(prefix="/laeufe", tags=["laeufe"])


def _als_daten(lauf: Lauf) -> dict:
    return {
        "lauf": lauf.nummer,
        "befehl": lauf.befehl,
        "hintergrund": lauf.hintergrund,
        "zustand": lauf.zustand,
        "code": lauf.code,
        "ausgabe": lauf.ausgabe,
        "art": lauf.art,
        "dauer_sekunden": lauf.dauer_sekunden,
        # Whether an answer has read this run's report yet — the card of
        # the call pulses until it has (see Lauf.gelesen).
        "gelesen": lauf.gelesen,
        "folder": lauf.folder,
        # A snapshot fetch does not replay bildlauf's own "lauf_regler"
        # event (see its module for why the dials live there, not on this
        # object) — a reload asks it directly instead.
        "regler": bildlauf.regler_von(lauf.chat_id, lauf.nummer) if lauf.art == ART_BILD else None,
    }


@router.get("/{chat_id}", summary="Command executions in a chat")
def laeufe_auflisten(chat_id: str) -> dict:
    """``ab`` rides along so a caller that opens the stream right after knows
    where to resume from without repeating what this answer already covers.
    """
    return {
        "laeufe": [_als_daten(lauf) for lauf in laeufe.laeufe(chat_id)],
        "ab": laeufe.ereignisstand(chat_id),
    }


async def _sse_strom(quelle: AsyncIterator[dict | None]) -> AsyncIterator[str]:
    """Turns one live-events source into SSE lines — its own function so the
    end-of-source handling below is directly testable without a real HTTP
    round trip.

    ``quelle`` running dry ends the stream cleanly: ``async for`` handles
    that itself, nothing here has to catch a ``StopAsyncIteration``. A
    ``None`` from the source is its own heartbeat (``Laufverwaltung.zuschauen``)
    — turned into an SSE comment line rather than a data line, since an
    EventSource client would otherwise try to parse it as an event.
    """
    try:
        async for ereignis in quelle:
            if ereignis is None:
                yield ": still here\n\n"
                continue
            yield f"data: {json.dumps(ereignis, ensure_ascii=False)}\n\n"
    except (asyncio.CancelledError, GeneratorExit):
        raise
    finally:
        await quelle.aclose()


@router.post("/{chat_id}/{nummer}/stop", summary="Stop a running command")
async def lauf_stoppen(
    chat_id: str,
    nummer: int,
    repositories: Repositories = Depends(hole_repositories),
    user_id: str = Depends(hole_benutzer_id),
    sprache: str = Depends(hole_sprache),
) -> dict:
    """Stops a running command of a chat with everything it started —
    foreground and background alike. A run that has already ended comes back
    as it is.

    A chat's runs only: a schedule's script keeps its runs under its job,
    and is stopped from that job, whose own cancel books the ending as the
    schedule's."""
    if repositories.chats.holen(chat_id, user_id=user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("fehler.allgemein", sprache))
    lauf = await laeufe.stop(chat_id, nummer)
    if lauf is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("fehler.allgemein", sprache))
    return _als_daten(lauf)


@router.get("/{chat_id}/stream", summary="Monitor command executions (SSE)")
async def zusehen(chat_id: str, ab: int = 0) -> StreamingResponse:
    return StreamingResponse(
        _sse_strom(laeufe.zuschauen(chat_id, ab=ab)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
