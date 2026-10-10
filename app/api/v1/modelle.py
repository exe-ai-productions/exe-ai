"""Which models are currently reachable."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app import denkablehnung
from app.api.abhaengigkeiten import hole_repositories, hole_sprache
from app.api.v1.schemas import ModellAntwort
from app.db import Repositories
from app.discovery import Discovery, refusal_key

router = APIRouter(tags=["modelle"])


def hole_discovery(request: Request) -> Discovery:
    return request.app.state.discovery


@router.get("/models", response_model=list[ModellAntwort], summary="Available models")
async def modelle(
    alle: bool = Query(
        default=False,
        description="Auch nicht erreichbare Kandidaten mit ausgeben (für Diagnose).",
    ),
    jetzt_pruefen: bool = Query(
        default=False, description="Vor der Antwort einen frischen Health-Check machen."
    ),
    discovery: Discovery = Depends(hole_discovery),
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> list[ModellAntwort]:
    if jetzt_pruefen:
        await discovery.einmal_pruefen()

    zustaende = discovery.alle() if alle else discovery.erreichbare()
    # One entry per model, not per address: a provider with a catalogue
    # appears once for each model it offers.
    #
    # A stage this model has already answered with an error leaves its list
    # here rather than in the discovery: what a server can do is the
    # discovery's question, what one model turned out to refuse is a stored
    # fact about that model, and the two belong to different owners.
    return [
        ModellAntwort(
            **zustand.als_dict(
                modell,
                sprache,
                abgelehnt=denkablehnung.gemerkt(
                    repositories.einstellungen, refusal_key(zustand, modell)
                ),
            )
        )
        for zustand, modell in discovery.aufgefaechert(zustaende)
    ]
