"""The storage locations — reading them, moving them, opening them (module,
step 2).

A thin route over ``app.speicherorte``: it lists what each location points
at, sets a new folder for one, resets one to its installed default, and
opens one in the file manager. The checking and the writing live in the
module; this only speaks HTTP.

Moving the FILES that already sit in the old folder is a later step — this
one changes only where NEW things are written. Every location is read fresh
where it is needed (a listing, a start, a download), so a move is felt at
once; a server that is up keeps the model it loaded.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.abhaengigkeiten import hole_config, hole_sprache
from app.config import Config
from app.i18n import t
from app.modellrunner import begleiter_einsortieren
from app.ordner_oeffnen import OeffnenNichtMoeglich, ordner_oeffnen
from app import speicherorte

# The locations that hold model files: a folder taking hold gets its loose
# companions sorted once, as the folder at service start does.
_MODEL_LOCATIONS = frozenset({"models", "speech_models"})

router = APIRouter(prefix="/speicherorte", tags=["speicherorte"])


class OrtAntwort(BaseModel):
    name: str
    pfad: str
    standard: str
    ist_standard: bool


class PfadWunsch(BaseModel):
    pfad: str


@router.get("", response_model=list[OrtAntwort], summary="Read the storage locations")
def lesen(config: Config = Depends(hole_config)) -> list[OrtAntwort]:
    return [OrtAntwort(**zeile) for zeile in speicherorte.uebersicht(config)]


@router.put("/{name}", response_model=OrtAntwort, summary="Set a storage location")
def setzen(
    name: str,
    wunsch: PfadWunsch,
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> OrtAntwort:
    """Point one location at a new folder. The folder is checked first; an
    unusable one is refused with a specific reason instead of failing later
    as a picture that would not draw."""
    _bekannt(name, sprache)
    try:
        speicherorte.setzen(config, name, wunsch.pfad)
    except speicherorte.SpeicherortFehler as fehler:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, t(fehler.grund, sprache)) from fehler
    _takes_hold(config, name)
    return _zeile(config, name)


@router.delete("/{name}", response_model=OrtAntwort, summary="Reset a storage location")
def zuruecksetzen(
    name: str,
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> OrtAntwort:
    """Back to the installed default — the override is dropped."""
    _bekannt(name, sprache)
    speicherorte.loeschen(config, name)
    _takes_hold(config, name)
    return _zeile(config, name)


@router.post("/{name}/folder", response_model=bool, summary="Show a storage location")
def zeigen(
    name: str,
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> bool:
    """Open the location in the file manager, so a file can be dropped in by
    hand. The folder is created if it is not there yet — an empty stack is
    still a stack, and opening nothing helps nobody."""
    _bekannt(name, sprache)
    ziel = speicherorte.ort(config, name)
    ziel.mkdir(parents=True, exist_ok=True)
    try:
        ordner_oeffnen(ziel)
    except OeffnenNichtMoeglich as fehler:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, t("fehler.ordner_oeffnen", sprache)
        ) from fehler
    return True


def _takes_hold(config: Config, name: str) -> None:
    if name in _MODEL_LOCATIONS:
        begleiter_einsortieren(speicherorte.ort(config, name))


def _bekannt(name: str, sprache: str) -> None:
    if name not in {o.name for o in speicherorte.ORTE}:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t("speicherorte.unbekannt", sprache)
        )


def _zeile(config: Config, name: str) -> OrtAntwort:
    for zeile in speicherorte.uebersicht(config):
        if zeile["name"] == name:
            return OrtAntwort(**zeile)
    # Unreachable: _bekannt ran first. Kept so a future rename fails loudly.
    raise HTTPException(status.HTTP_404_NOT_FOUND, "unbekannt")
