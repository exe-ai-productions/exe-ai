"""The clean-up server, from outside.

Its own route rather than a mode of the speech route next door — the same
reasoning the embedding server's file carries: the two servers must be
startable independently, and a shared route is exactly how a start of one
becomes a start of the other.

The file it runs from and the numbers it runs with are settings
(app/diktatsprachewahl.py), not choices of this request: the window writes
each of them as it is touched, and this route reads them at the moment of
the start, so the process comes up on what the window shows.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app import diktatsprachewahl
from app.api.abhaengigkeiten import hole_repositories, hole_sprache
from app.api.v1.runner import Modelldatei, ProgramState, _fehler, program_state
from app.db import Repositories
from app.modellrunner import RunnerFehler

router = APIRouter(prefix="/bereinigungsserver", tags=["bereinigungsserver"])


class Auskunft(ProgramState):
    ordner: str
    modelle: list[Modelldatei] = []
    laeuft: bool = False
    # What the field shows: the run's file while one runs, the stored choice
    # otherwise — the same two sources the speech panel reads.
    modell: str | None = None
    port: int | None = None
    kerne: int | None = None
    # The architecture the last start failed on because the server's build
    # does not know it.
    unknown_architecture: str | None = None
    # The works answers for the tidy-up numbers and the five generation
    # values — sent rather than written into the page, the same way the
    # speech panel is told its own field defaults.
    diktat_vorgaben: dict = {}


class Start(BaseModel):
    modell: str = Field(min_length=1, max_length=200)
    # Its own port, because sharing one with the speech model is exactly
    # what a server of its own is for.
    port: int | None = Field(default=None, ge=1024, le=65535)


def _runner(request: Request):
    return request.app.state.sprachputzrunner


def _auskunft(request: Request, repositories: Repositories) -> Auskunft:
    runner = _runner(request)
    lauf = runner.lauf()
    return Auskunft(
        **program_state(runner, request.app.state.config),
        ordner=str(runner.ordner),
        modelle=[
            Modelldatei(name=m.name, groesse_gb=m.groesse_gb)
            for m in runner.modelle()
        ],
        laeuft=runner.laeuft(),
        modell=lauf.modell if lauf else (diktatsprachewahl.putzmodell(repositories) or None),
        port=lauf.port if lauf else (
            diktatsprachewahl.wahl(repositories)["cleanup_port"] or runner.port_vorgabe
        ),
        kerne=os.cpu_count(),
        unknown_architecture=runner.unknown_architecture(),
        diktat_vorgaben=diktatsprachewahl.vorgaben(),
    )


@router.get("", response_model=Auskunft, summary="Clean-up server — status")
def auskunft(
    request: Request,
    repositories: Repositories = Depends(hole_repositories),
) -> Auskunft:
    return _auskunft(request, repositories)


@router.get("/log", response_model=list[str], summary="Server messages")
def protokoll(request: Request) -> list[str]:
    return _runner(request).protokoll()


@router.post("/start", response_model=Auskunft, summary="Start the clean-up server")
def starten(
    daten: Start,
    request: Request,
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> Auskunft:
    # One read of the setting for everything this start needs from it.
    stand = diktatsprachewahl.wahl(repositories)
    kontext, schichten, faeden = diktatsprachewahl.putzspeicher(repositories, stand)
    try:
        _runner(request).starten(
            daten.modell,
            kontext=kontext,
            schichten=schichten,
            # The request's port, else the one stored with the other start
            # values, else the server's own.
            port=daten.port or stand["cleanup_port"],
            # No speed module and no projector here: a cleaner reads text
            # and writes text, and its folder may well hold a pair meant
            # for the speech model beside it.
            drafter="",
            vision="",
            faeden=faeden,
            sampling=diktatsprachewahl.putzsampling(repositories, stand),
        )
    except RunnerFehler as fehler:
        raise _fehler(fehler.grund, sprache) from None
    return _auskunft(request, repositories)


@router.post("/stop", response_model=Auskunft, summary="Stop the clean-up server")
def stoppen(
    request: Request,
    repositories: Repositories = Depends(hole_repositories),
) -> Auskunft:
    _runner(request).stoppen()
    return _auskunft(request, repositories)
