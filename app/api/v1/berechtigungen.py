"""Immer-erlauben rules, seen and taken back — the durable
half of the confirmation box's third button.

Writing a rule happens through ``/chat/confirm`` (app/api/v1/generierung.py):
that route already has the waiting call, argument and all, so it is the one
place that can act on "yes, and remember it" in a single round trip. This
router only shows what ended up on file and lets one line be removed again.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app import immererlauben
from app.api.abhaengigkeiten import hole_config, hole_sprache
from app.i18n import t
from app.config import Config

router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.get("/always-allow", summary="Permanently allowed tools")
def auflisten(config: Config = Depends(hole_config)) -> dict[str, str]:
    return immererlauben.auflisten(config.pfad(config.app.berechtigungen_datei))


@router.delete(
    "/always-allow/{name}",
    status_code=204,
    response_class=Response,
    response_model=None,
    summary="Remove a permanent rule",
)
def entfernen(
    name: str, config: Config = Depends(hole_config), sprache: str = Depends(hole_sprache)
) -> Response:
    if not immererlauben.entfernen(config.pfad(config.app.berechtigungen_datei), name):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t("fehler.berechtigung_regel_fehlt", sprache)
        )
    return Response(status_code=204)
