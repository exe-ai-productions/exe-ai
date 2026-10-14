"""Which models are currently reachable."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app import denkablehnung, denkenwahl, server_state
from app.api.abhaengigkeiten import hole_repositories, hole_sprache
from app.api.v1.schemas import ModellAntwort
from app.db import Repositories
from app.discovery import Discovery, refusal_key
from app.env_datei import key_leaves_with
from app.generationen import Generierungsverwaltung

router = APIRouter(tags=["modelle"])


def hole_discovery(request: Request) -> Discovery:
    return request.app.state.discovery


def hole_generierungen(request: Request) -> Generierungsverwaltung:
    return request.app.state.generierungen


@router.get("/models", response_model=list[ModellAntwort], summary="Available models")
async def modelle(
    alle: bool = Query(
        default=False,
        description="Include unreachable candidates for diagnostic purposes.",
    ),
    jetzt_pruefen: bool = Query(
        default=False, description="Run a fresh health check before responding."
    ),
    discovery: Discovery = Depends(hole_discovery),
    generierungen: Generierungsverwaltung = Depends(hole_generierungen),
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> list[ModellAntwort]:
    if jetzt_pruefen:
        await discovery.einmal_pruefen()

    zustaende = discovery.alle() if alle else discovery.erreichbare()
    # Which servers are writing an answer right now — asked once for the
    # whole list, not once per entry.
    writing = generierungen.active_endpoints()
    # Whose key line goes along when the provider is removed — judged over
    # every configured provider, not only the ones listed here, so a
    # provider that is down still counts as a user of the variable.
    endpoints = [z.endpunkt for z in discovery.alle()]
    key_goes = {e.id for e in endpoints if key_leaves_with(endpoints, e.id)}
    # One entry per model, not per address: a provider with a catalogue
    # appears once for each model it offers.
    #
    # A stage this model has already answered with an error leaves its list
    # here rather than in the discovery: what a server can do is the
    # discovery's question, what one model turned out to refuse is a stored
    # fact about that model, and the two belong to different owners.
    antworten = []
    for zustand, modell in discovery.aufgefaechert(zustaende):
        refusal_id = refusal_key(zustand, modell)
        abgelehnt = denkablehnung.gemerkt(repositories.einstellungen, refusal_id)
        antworten.append(
            ModellAntwort(
                **discovery.fuer_modell(zustand, modell).als_dict(
                    modell, sprache, abgelehnt=abgelehnt
                ),
                server_state=server_state.word(
                    running=zustand.endpunkt.id in writing, reachable=zustand.erreichbar
                ),
                key_goes_with_provider=zustand.endpunkt.id in key_goes,
                # What a request without a stage of its own carries for this
                # model: the stored stage where it is still offered, else the
                # one standing in for it.
                thinking_sent=denkenwahl.sent_stage(
                    repositories.einstellungen,
                    zustand.denkprofil(modell, abgelehnt),
                    refusal_id,
                ),
            )
        )
    return antworten
