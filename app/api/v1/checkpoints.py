"""The snapshots of a working folder: what there is, and putting files back.

The snapshots are taken while the model works (``app/checkpoint_hooks.py``);
this route only reads them and restores from them. It knows no folder that
was never snapshotted, so it cannot be pointed at an arbitrary place.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import checkpoint_hooks, checkpoints
from app.api.abhaengigkeiten import hole_config, hole_repositories, hole_sprache
from app.checkpoint_choice import enabled
from app.config import Config
from app.db import Repositories
from app.i18n import t

router = APIRouter(prefix="/checkpoints", tags=["checkpoints"])

_STATUS = {
    "too_many": 409, "unknown_folder": 404, "unknown_snapshot": 404, "bad_file": 400, "failed": 500,
}


class Listing(BaseModel):
    enabled: bool
    snapshots: list[dict[str, Any]] = []


class RestoreRequest(BaseModel):
    directory: str
    snapshot: str
    file: str | None = None
    all: bool = False


class RestoreResult(BaseModel):
    restored: list[str]
    skipped: list[str]
    failed: list[str]


def _refused(error: checkpoints.CheckpointError, sprache: str) -> HTTPException:
    return HTTPException(_STATUS.get(error.kind, 400), t(f"fehler.checkpoints_{error.kind}", sprache))


@router.get("", response_model=Listing, summary="The snapshots of a folder")
def listing(
    directory: str,
    config: Config = Depends(hole_config),
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> Listing:
    base = checkpoint_hooks.store_folder(config.datenverzeichnis)
    try:
        listed = checkpoints.snapshots(base, directory)
    except checkpoints.CheckpointError as error:
        raise _refused(error, sprache) from None
    return Listing(enabled=enabled(repositories), snapshots=listed)


@router.post("/restore", response_model=RestoreResult, summary="Put files back to a snapshot")
def restore(
    body: RestoreRequest,
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> RestoreResult:
    base = checkpoint_hooks.store_folder(config.datenverzeichnis)
    try:
        done = checkpoints.restore(
            base, body.directory, body.snapshot, file=body.file, everything=body.all
        )
    except checkpoints.CheckpointError as error:
        raise _refused(error, sprache) from None
    return RestoreResult(**done)
