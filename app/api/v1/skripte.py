"""What lies in the scripts folder.

The folder has been a storage location for a while — shown in the schedules
mask, opened in the file manager, moved with a pencil — but nothing ever
listed it. A schedule that runs a script asked for the file name as free
text, so the one place that knows which scripts exist (the folder) and the
one place that needs to know (the mask) never met, and a typo became a
schedule that fails at its first firing.

Read only, and deliberately so. Putting a script into the folder is done in
the file manager, where a person can see what they are installing; running
one goes through ``app/skriptlauf.py``, which checks the same folder again at
every firing. This says what is there and whether it could run at all.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from datetime import datetime, timezone

from app import ordnerinhalt
from app.api.abhaengigkeiten import hole_config, hole_sprache
from app.config import Config
from app.i18n import t

router = APIRouter(prefix="/skripte", tags=["skripte"])


class SkriptEintrag(BaseModel):
    name: str
    groesse: int = 0
    geaendert: str = ""
    # Whether the executable bit is set. A script without it is listed rather
    # than hidden — it is in the folder, so it is on the wall — but the panel
    # can say why it would be refused before a schedule ever fires it
    # (``geprueft``, app/skriptlauf.py).
    startbar: bool = True


@router.get("", response_model=list[SkriptEintrag], summary="Script folder contents")
def liste(config: Config = Depends(hole_config)) -> list[SkriptEintrag]:
    # Imported here rather than at the top, the way the picture helper next
    # door does it (app/api/v1/generierung.py). `skriptlauf` pulls in the
    # shell tool, and pulling that into the ROUTER's import means it is
    # loaded while the service is starting — measured: it moved the startup
    # far enough for the discovery loop's first probe to land inside a test
    # that sets an endpoint reachable by hand, which then failed twice in
    # thirty runs where it had never failed before. A listing route has no
    # business changing when the service is ready.
    from app import skriptlauf

    eintraege: list[SkriptEintrag] = []
    for pfad in ordnerinhalt.auflisten(skriptlauf.ordner(config)):
        try:
            stand = pfad.stat()
        except OSError:
            # Gone since the listing; the next one will not see it either.
            continue
        eintraege.append(
            SkriptEintrag(
                name=pfad.name,
                groesse=stand.st_size,
                geaendert=datetime.fromtimestamp(
                    stand.st_mtime, tz=timezone.utc
                ).isoformat(),
                startbar=skriptlauf.startable(pfad),
            )
        )
    return eintraege


@router.get("/text", summary="The text of one script in the folder")
def script_text(
    name: str,
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> FileResponse:
    """The file itself as plain text, for the tile that shows its first lines.

    Only a plain file name in the scripts folder is answered: a name that
    spells out a path, or a file that is not there, is refused like any other
    file that is not in the folder. The answer carries no file name, so it is shown
    in place and never saved, and never run — running goes through ``app/skriptlauf.py``.
    """
    from app import skriptlauf

    try:
        rein = skriptlauf._kein_pfad(name)
    except skriptlauf.SkriptVerboten as fehler:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, t(fehler.schluessel, sprache, **fehler.werte)
        ) from fehler
    # A link lying in the folder and leading out of it is refused like a file
    # that is not there.
    pfad = ordnerinhalt.sicherer_pfad(skriptlauf.ordner(config), rein)
    if pfad is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("fehler.datei_nicht_vorhanden", sprache))
    return FileResponse(pfad, media_type="text/plain; charset=utf-8")
