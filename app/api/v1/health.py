"""Health check of the service.

Two paths, deliberately:
  * ``/health``        — unversioned, for Uptime Kuma and systemd. This
                         address must never change.
  * ``/api/v1/health`` — the same information within the versioned API,
                         and, there alone, which process the service is
                         (app/own_process.py): the versioned API stands
                         behind the session key, the unversioned address is
                         open to whoever reaches the port.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app import __version__, own_process
from app.api.abhaengigkeiten import hole_config, hole_repositories
from app.config import Config
from app.db import Repositories

router = APIRouter(tags=["health"])


class DatenbankStatus(BaseModel):
    erreichbar: bool
    schema_version: int | None = None
    fehler: str | None = None


class HealthAntwort(BaseModel):
    status: str
    version: str
    datenbank: DatenbankStatus


class ProcessNamed(BaseModel):
    pid: int
    began: float


class KeyedHealth(HealthAntwort):
    """What the versioned address answers: the same, and which process the
    service is. The open address keeps the answer it always gave."""

    process: ProcessNamed | None = None


def _health_ermitteln(config: Config, repositories: Repositories) -> HealthAntwort:
    try:
        version = repositories.db.schema_version()
        datenbank = DatenbankStatus(erreichbar=True, schema_version=version)
    except Exception as fehler:  # noqa: BLE001 - health must never crash itself
        datenbank = DatenbankStatus(erreichbar=False, fehler=str(fehler))

    return HealthAntwort(
        status="ok" if datenbank.erreichbar else "degraded",
        version=__version__,
        datenbank=datenbank,
    )


@router.get("/health", response_model=KeyedHealth, summary="Service status")
def health(
    config: Config = Depends(hole_config),
    repositories: Repositories = Depends(hole_repositories),
) -> KeyedHealth:
    this = own_process.named()
    return KeyedHealth(
        **_health_ermitteln(config, repositories).model_dump(),
        process=None if this is None else ProcessNamed(pid=this.pid, began=this.began),
    )
