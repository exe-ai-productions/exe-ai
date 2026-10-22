"""Version 1 of the API.

All endpoints live under ``/api/v1/``. If a breaking change comes along later,
``/api/v2/`` is created alongside it — existing clients don't break.
"""

from fastapi import APIRouter

from app.api.v1 import (
    agentendock,
    agentenserver,
    anbieter,
    anmeldung,
    arbeitsordner,
    ordnerwissen,
    befehle,
    berechtigungen,
    bereinigungsserver,
    bild,
    bilder,
    bildprompt,
    checkpoints,
    dateien,
    dateisystem,
    auftraege,
    chats,
    cronjobs,
    dokumente,
    einbettungsserver,
    einstellungen,
    ereignisse,
    gedaechtnis,
    generierung,
    health,
    hf_token,
    image_tools,
    meta,
    modelldateien,
    modelle,
    modellsuche,
    projects,
    runner,
    skills,
    skripte,
    speicherblick,
    speicherorte,
    sprachserver,
    systemprompt,
    throughput,
    web_app,
    werkzeuge,
)

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(anmeldung.router)
router.include_router(meta.router)
router.include_router(einstellungen.router)
router.include_router(ereignisse.router)
router.include_router(modelle.router)
router.include_router(anbieter.router)
router.include_router(modellsuche.router)
router.include_router(modelldateien.router)
router.include_router(hf_token.router)
router.include_router(runner.router)
router.include_router(einbettungsserver.router)
router.include_router(sprachserver.router)
router.include_router(bereinigungsserver.router)
router.include_router(agentenserver.router)
router.include_router(throughput.router)
router.include_router(web_app.router)
router.include_router(werkzeuge.router)
router.include_router(berechtigungen.router)
router.include_router(dateien.router)
router.include_router(dateisystem.router)
router.include_router(speicherblick.router)
router.include_router(speicherorte.router)
router.include_router(systemprompt.router)
router.include_router(gedaechtnis.router)
router.include_router(skills.router)
router.include_router(skripte.router)
router.include_router(bilder.router)
router.include_router(bild.router)
router.include_router(bildprompt.router)
router.include_router(image_tools.router)
router.include_router(dokumente.router)
router.include_router(chats.router)
router.include_router(projects.router)
router.include_router(generierung.router)
router.include_router(befehle.router)
router.include_router(arbeitsordner.router)
# Registered INSIDE the v1 router on purpose, like every one of its
# neighbours: the static files are mounted on "/" last and answer every
# path, so a route added after them comes back 405 rather than 404.
router.include_router(ordnerwissen.router)
router.include_router(agentendock.router)
router.include_router(auftraege.router)
router.include_router(cronjobs.router)
router.include_router(checkpoints.router)

__all__ = ["router"]
