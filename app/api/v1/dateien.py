"""Configuration and credentials editable in the UI.

All important inputs that would otherwise have to be
made through a file in a folder must be visible in the UI. This means the
``config.yaml`` and the ``.env``.

This reverses an earlier design: back then the editor
only showed ``${…}`` placeholders and a traffic light, because the UI has
no login and was reachable over the network. **That rationale is gone** —
the program runs locally on your own machine and is no longer exposed
through a tunnel. Whoever sees the screen is sitting in front of it.

Deliberately ONLY these two files, hard-wired: no path comes from outside,
so nothing else can be read or overwritten with this.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.abhaengigkeiten import hole_config, hole_sprache
from app.config import Config
from app.i18n import t
from app.previous_version import set_beside

log = logging.getLogger(__name__)
router = APIRouter(prefix="/dateien", tags=["dateien"])

# Key -> (file name, whether YAML is validated, whether a restart is needed)
DATEIEN = {
    "konfiguration": ("config.yaml", True, True),
    "zugangsdaten": (".env", False, True),
}


class DateiAntwort(BaseModel):
    kennung: str
    datei: str
    inhalt: str
    kaputt: str | None = None
    neustart_noetig: bool


class DateiSchreiben(BaseModel):
    inhalt: str


def _pfad(config: Config, kennung: str, sprache: str) -> tuple[Path, bool, bool]:
    if kennung not in DATEIEN:
        raise HTTPException(404, t("dateien.unbekannt", sprache, kennung=kennung))
    name, prueft_yaml, neustart = DATEIEN[kennung]
    return config.pfad(f"./{name}"), prueft_yaml, neustart


def _pruefen(inhalt: str, sprache: str) -> str | None:
    try:
        daten = yaml.safe_load(inhalt)
    except yaml.YAMLError as fehler:
        return t("dateien.kein_yaml", sprache, fehler=fehler)
    if not isinstance(daten, dict):
        return t("dateien.oberste_ebene", sprache)
    return None


@router.get("/{kennung}", response_model=DateiAntwort, summary="Read a file")
def lesen(
    kennung: str,
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> DateiAntwort:
    pfad, prueft, neustart = _pfad(config, kennung, sprache)
    inhalt = pfad.read_text(encoding="utf-8") if pfad.exists() else ""
    return DateiAntwort(
        kennung=kennung, datei=pfad.name, inhalt=inhalt,
        kaputt=_pruefen(inhalt, sprache) if (prueft and inhalt.strip()) else None,
        neustart_noetig=neustart,
    )


@router.put("/{kennung}", response_model=DateiAntwort, summary="Save a file")
def sichern(
    kennung: str,
    daten: DateiSchreiben,
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> DateiAntwort:
    """Always saves — it is the user's file.

    If it's no good, the reason goes into ``kaputt``; it is still only
    applied at the next start. Before every write the previous version is
    set aside as ``<name>.vorher``: otherwise a typo in the config.yaml
    prevents startup, and then you could no longer reach the file through
    the UI.
    """
    pfad, prueft, neustart = _pfad(config, kennung, sprache)
    try:
        set_beside(pfad)
        pfad.write_text(daten.inhalt, encoding="utf-8")
    except OSError as fehler:
        log.error("%s could not be written: %s", pfad.name, fehler)
        raise HTTPException(
            500, t("dateien.nicht_geschrieben", sprache, name=pfad.name)
        ) from fehler

    return DateiAntwort(
        kennung=kennung, datei=pfad.name, inhalt=daten.inhalt,
        kaputt=_pruefen(daten.inhalt, sprache) if (prueft and daten.inhalt.strip()) else None,
        neustart_noetig=neustart,
    )
