"""The command runs of a chat — what has run, and what is running right now.

Its own channel, not part of the answer stream, and for one reason: a
background run outlives the answer that started it. Hanging its lines on the
generation would mean they stop arriving the moment the model is done
talking, which is precisely when a long build is still going.

Two routes, and they belong together: the window asks once for what is there
and then keeps listening.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app import berechtigungen, dokumentablage
from app.api.abhaengigkeiten import (
    hole_benutzer_id, hole_config, hole_repositories, hole_sprache,
)
from app.api.v1.schemas import BefehlAusfuehren
from app.berechtigungsregeln import laden as regeln_laden
from app.config import Config
from app.db import Repositories
from app.i18n import t
from app import bildlauf
from app.tools import shell
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


@router.get("/{chat_id}", summary="The command runs of a chat")
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


@router.post("/{chat_id}/{nummer}/stop", summary="Stop one running command")
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


@router.get("/{chat_id}/stream", summary="Watch the command runs (SSE)")
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


@router.post("/{chat_id}/befehl", summary="Run a command from the CLI module")
async def befehl_ausfuehren(
    chat_id: str,
    daten: BefehlAusfuehren,
    repositories: Repositories = Depends(hole_repositories),
    user_id: str = Depends(hole_benutzer_id),
    sprache: str = Depends(hole_sprache),
    config: Config = Depends(hole_config),
) -> dict:
    """Runs one command for the CLI module — the same runner the model uses.

    Same folders, same block list, same limits: there is one way to run a
    command in this program, and the CLI is not a second one — including
    Tor 3 (``app/berechtigungen.py``), so a ``niemals`` pattern configured in
    ``berechtigungen.json`` blocks a command here exactly as it would for the
    model. Read from ``config.app.berechtigungen_datei``, not the bare
    default — an operator who relocates the file must not have the CLI keep
    reading the old one while the model reads the new one.

    One difference, and it is deliberate: a path outside the shared folders
    is refused here instead of asked about. The confirmation belongs to a
    running answer, which is what holds the call open and can wait for a
    click. The CLI has no such run, so a "fragen" verdict is refused here
    too — named by path when that is the reason, or plainly otherwise, since
    "fragen" can also come from a per-tool rule or the standard answer with
    no path involved at all.
    """
    chat = repositories.chats.holen(chat_id, user_id=user_id)
    if chat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("fehler.allgemein", sprache))

    # Including this chat's own document folder where it has one, the dock
    # and the picture folder — the CLI runs in the same folders the model
    # does (app/dokumentablage.py).
    ordner = dokumentablage.ordner_dieses_chats(
        config.datenverzeichnis,
        chat.working_dirs,
        chat.id,
        dokumentablage.program_folders(config),
    )
    argumente = {"command": daten.command}
    regeln = regeln_laden(config.pfad(config.app.berechtigungen_datei))
    urteil = berechtigungen.urteil(shell.WERKZEUG_NAME, argumente, ordner, "chat", regeln=regeln)
    if urteil.antwort == "nein":
        return {"text": urteil.grund or "", "fehlgeschlagen": True}
    if urteil.antwort == "fragen":
        aussen = shell.aussenpfad(argumente, ordner)
        if aussen:
            return {
                "text": t("cli.ausserhalb", sprache, pfad=aussen),
                "fehlgeschlagen": True,
            }
        return {"text": t("cli.braucht_bestaetigung", sprache), "fehlgeschlagen": True}

    # The chat's own folder is in that list whether it exists yet or not
    # (app/dokumentablage.py); with nothing shared, the command runs in it,
    # and the command makes it as it runs (app/tools/grenzen.py
    # `prepare_folders`) — told apart by the data folder.
    try:
        text = await shell.ausfuehren(
            argumente, ordner, chat_id, data_dir=config.datenverzeichnis
        )
    except shell.ShellVerboten as fehler:
        return {"text": str(fehler), "fehlgeschlagen": True}
    return {"text": text, "fehlgeschlagen": False}
