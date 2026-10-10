"""Showing a shared working folder in the file manager.

One route, and the whole point of it is what it refuses. The client never
says which path to open — it says which chat and which of that chat's shared
folders. The path itself comes out of the chat row, so a request cannot ask
for a folder the user never shared, however it is spelled.

A request without a path opens the chat's own folder instead — the one the
program keeps for it under the data folder (``app/dokumentablage.py``). Its
place is built here from the chat's id, never taken from the request, so
this opens that one chat's folder and no other chat's — also in a chat that
shares folders of the user's. The opener makes it when it is not there yet.

The opening itself is ``app/ordner_oeffnen.py``, the same one the model
folder uses.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from app import dokumentablage
from app.api.abhaengigkeiten import (
    hole_benutzer_id,
    hole_config,
    hole_repositories,
    hole_sprache,
)
from app.api.v1.schemas import OrdnerOeffnen
from app.config import Config
from app.db import Repositories
from app.i18n import t
from app.ordner_oeffnen import OeffnenNichtMoeglich, ordner_oeffnen

log = logging.getLogger(__name__)

router = APIRouter(prefix="/ordner", tags=["ordner"])


@router.post("/oeffnen", response_model=bool, summary="Show a working folder")
def oeffnen(
    daten: OrdnerOeffnen,
    repositories: Repositories = Depends(hole_repositories),
    user_id: str = Depends(hole_benutzer_id),
    sprache: str = Depends(hole_sprache),
    config: Config = Depends(hole_config),
) -> bool:
    chat = repositories.chats.holen(daten.chat_id, user_id=user_id)
    if chat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("fehler.allgemein", sprache))

    if daten.pfad is None:
        own = dokumentablage.chatordner(config.datenverzeichnis, chat.id)
        # A stored chat id is always a valid one; this only narrows the type.
        assert own is not None
        target = own
    elif daten.pfad in (chat.working_dirs or []):
        target = Path(daten.pfad)
    else:
        # Not "not found": the folder may well exist. It is simply not one
        # this chat shared, and that is the whole boundary.
        raise HTTPException(status.HTTP_403_FORBIDDEN, t("fehler.allgemein", sprache))

    try:
        ordner_oeffnen(target)
    except OeffnenNichtMoeglich:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, t("fehler.ordner_oeffnen", sprache)
        ) from None
    except OSError as error:
        # A folder that cannot be made (read-only disk, full disk, a file in
        # its place) leaves the user exactly where a system without a file
        # manager does: nothing to show.
        log.warning("Folder %s could not be opened: %s", target, error)
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, t("fehler.ordner_oeffnen", sprache)
        ) from None
    return True
