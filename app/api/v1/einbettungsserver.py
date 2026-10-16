"""The embedding server, from outside.

The same three questions the model server answers — what is there, is it
running, start and stop it — and deliberately nothing more. It is a small
service with one job, so it needs no context size, no layer count, no draft
model, no projector.

Its own route rather than a mode of the runner route next door: the two
servers must be startable independently, and a shared route is exactly how
they end up sharing a port.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app import embedding_start_choice
from app.api.abhaengigkeiten import hole_config, hole_repositories, hole_sprache
from app.db import Repositories
from app.api.v1.runner import Modelldatei, ProgramState, _fehler, program_state
from app.config import Config
from app.einbettung import modelle as einbettungsmodelle
from app.einbettungsserver import STAPEL
from app.i18n import t
from app.modellrunner import RunnerFehler
from app.ordner_oeffnen import OeffnenNichtMoeglich, ordner_oeffnen

router = APIRouter(prefix="/einbettungsserver", tags=["einbettungsserver"])


class Auskunft(ProgramState):
    ordner: str
    modelle: list[Modelldatei]
    laeuft: bool
    modell: str | None = None
    port: int | None = None
    # Live resident memory of the running server, for the machine head's sum
    # — the same measurement the runner already keeps for itself.
    belegt_gb: float | None = None
    # The architecture the last start failed on because the server's build
    # does not know it.
    unknown_architecture: str | None = None


class Start(BaseModel):
    modell: str = Field(min_length=1, max_length=200)
    # The one number this server has. Its own, because sharing a port with
    # the chat model is exactly what this server exists apart from.
    port: int | None = Field(default=None, ge=1024, le=65535)


def _runner(request: Request):
    return request.app.state.einbettungsrunner


def _auskunft(request: Request, config: Config) -> Auskunft:
    runner = _runner(request)
    lauf = runner.lauf()
    # The same list, in the same order, the folder's own reader answers
    # with (app/einbettung.py `modell_finden`): the picker's first entry is
    # the file the in-process path would reach for. Every size is read from
    # the file itself — the runner's listing drops projector files, and a
    # borrowed size would turn "not listed there" into a made-up zero. A
    # file gone between listing and read is left out.
    ordner = Path(runner.ordner)
    modelle: list[Modelldatei] = []
    for name in einbettungsmodelle(ordner):
        try:
            groesse = round((ordner / name).stat().st_size / 1e9, 1)
        except OSError:
            continue
        modelle.append(Modelldatei(name=name, groesse_gb=groesse))
    # Idle, the window shows what is stored for the next start (the file,
    # while it is still in the folder, and the port); running, what runs.
    gespeichert = embedding_start_choice.wahl(request.app.state.repositories)
    gewaehlt = gespeichert["model"] if gespeichert["model"] in {m.name for m in modelle} else None
    return Auskunft(
        **program_state(runner, request.app.state.config),
        ordner=str(ordner),
        modelle=modelle,
        laeuft=runner.laeuft(),
        modell=lauf.modell if lauf else gewaehlt,
        port=lauf.port if lauf else (gespeichert["port"] or runner.port_vorgabe),
        belegt_gb=runner.belegt_gb(),
        unknown_architecture=runner.unknown_architecture(),
    )


@router.get("", response_model=Auskunft, summary="Embedding server — status")
def auskunft(request: Request, config: Config = Depends(hole_config)) -> Auskunft:
    return _auskunft(request, config)


@router.get("/log", response_model=list[str], summary="Server messages")
def protokoll(request: Request) -> list[str]:
    return _runner(request).protokoll()


@router.post("/start", response_model=Auskunft, summary="Start the embedding server")
def starten(
    daten: Start,
    request: Request,
    config: Config = Depends(hole_config),
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> Auskunft:
    # The request's port, else the one stored with the file choice
    # (app/embedding_start_choice.py), else the server's own.
    port = daten.port or embedding_start_choice.wahl(repositories)["port"]
    try:
        # The window travels as a start value, not as an extra flag — one
        # `--ctx-size` on the command line, written by the one place that
        # writes command lines.
        _runner(request).starten(daten.modell, port=port, kontext=STAPEL)
    except RunnerFehler as fehler:
        raise _fehler(fehler.grund, sprache) from None
    # Deliberately NOT registered with the discovery: this server answers
    # embeddings, not chat. A model picker that offered it would let somebody
    # send a conversation to something that cannot hold one.
    return _auskunft(request, config)


@router.post("/stop", response_model=Auskunft, summary="Stop the embedding server")
def stoppen(request: Request, config: Config = Depends(hole_config)) -> Auskunft:
    _runner(request).stoppen()
    return _auskunft(request, config)


@router.post("/folder", response_model=bool, summary="Show the embedding models")
def ordner_zeigen(request: Request, sprache: str = Depends(hole_sprache)) -> bool:
    """Its OWN folder — the button that used to point at the wrong one."""
    try:
        ordner_oeffnen(Path(_runner(request).ordner))
    except OeffnenNichtMoeglich:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, t("fehler.ordner_oeffnen", sprache)
        ) from None
    return True
