"""Information about the running service for the frontend.

The frontend asks here which features are switched on and which languages
exist — instead of hard-coding such things. Secrets and internal addresses
are deliberately not shipped along.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app import __version__
from app.api.abhaengigkeiten import hole_config, hole_sprache
from app.config import Config
from app.i18n import STANDARDSPRACHE, verfuegbare_sprachen

router = APIRouter(tags=["meta"])


class MetaAntwort(BaseModel):
    name: str
    version: str
    sprache: str
    standardsprache: str
    verfuegbare_sprachen: list[str]
    features: dict[str, bool]
    # The first name the operating system knows — the address suggestion
    # for the first start. Empty when the system offers none.
    system_name: str = ""
    # The zone schedules fire in, so the window shows their times on the
    # same clock (``service_zone``). Empty only when not even the machine
    # names its zone; the window then reads the browser's clock.
    timezone: str = ""


def service_zone(configured: str | None) -> str:
    """The zone the service's clock reads schedules in: the configured one,
    or — with none set — the machine's own (app/wecker.py
    ``jetzt_in_zone``), by the name its zone database gives it. A browser
    on another machine, over the network or on a phone, would otherwise
    show a daily 08:00 at its own hour.

    The name itself is worked out in one place (``app/wecker.zone_name``):
    the prompt's date block and the clock tool ask for the very same name,
    and two answers would be two zones.
    """
    from app.wecker import zone_name

    return zone_name(configured)


def _systemname() -> str:
    """The user's first name as the system knows it, or an empty string."""
    import os

    voll = ""
    try:
        import pwd

        voll = pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0].strip()
    except Exception:
        voll = ""
    kurz = voll.split()[0] if voll else ""
    return kurz or os.environ.get("USER") or os.environ.get("USERNAME") or ""


@router.get("/meta", response_model=MetaAntwort, summary="Features and languages")
def meta(
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> MetaAntwort:
    return MetaAntwort(
        system_name=_systemname(),
        name="Exe AI",
        version=__version__,
        sprache=sprache,
        standardsprache=STANDARDSPRACHE,
        verfuegbare_sprachen=verfuegbare_sprachen(),
        features=config.features.model_dump(),
        timezone=service_zone(config.app.timezone),
    )


@router.get("/translations/{sprache}", summary="Translation catalog")
def uebersetzungen(sprache: str) -> dict:
    """Delivers the complete catalog of a language to the frontend."""
    from app.i18n import _katalog  # deliberately local: internal access, not part of the API

    katalog = _katalog(sprache)
    if not katalog:
        katalog = _katalog(STANDARDSPRACHE)
        sprache = STANDARDSPRACHE
    return {"sprache": sprache, "texte": katalog}
