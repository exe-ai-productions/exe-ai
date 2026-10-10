"""The prompt preparation: the picture window's "Enhance" button and
``draw_image`` both ask here for an English prompt.

It is its own router and not a route in ``bild.py`` because it talks to a
different machine entirely: everything in ``bild.py`` speaks to the local
image generator, this one speaks to the language model chosen in the picture
server's "Prompt preparation" block (app/bildaufbereitung.py) — the agent
server, the model server, the clean-up server or a cloud model.

The endpoint refuses rather than falls back. If the chosen server does not
answer, the honest answer is "nobody prepared it" — quietly returning the
prompt unchanged would look like a button that did nothing; the caller says
so and goes on with the request as it was (``draw_image`` draws anyway).
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app import (
    agentenmodellwahl, agentenserver, bildaufbereitung, bildinhalt, bildmodellwerte,
    denkablehnung, denkschalter, generationen, image_families, sprachserver,
)
from app.api.abhaengigkeiten import hole_config, hole_repositories, hole_sprache
from app.bildprompt import (
    ANWEISUNG_NEGATIV,
    ANWEISUNGEN,
    LESER,
    MAX_EINGABE,
    PromptFehler,
    nachricht,
    verbessern,
)
from app.bildrunner import modell_pfad
from app.config import Config, EndpointConfig
from app.db import Repositories
from app.discovery import Discovery, EndpunktZustand, refusal_key
from app.i18n import t
from app.providers import ProviderFehler, provider_bauen
from app.speicherorte import ort

log = logging.getLogger(__name__)

router = APIRouter(tags=["bild"])


def hole_discovery(request: Request) -> Discovery:
    return request.app.state.discovery


class PromptWunsch(BaseModel):
    # The request, in whatever language it was written.
    prompt: str = Field(min_length=1)
    # The negative prompt rides along: it needs the same translation to
    # English (picture models read it just as literally), only tidied
    # instead of expanded. Empty means there is nothing to rewrite.
    negativ: str = ""
    # The picture model the prompt is for, by its file name: its family
    # picks the instruction, its own values bring the trigger words and the
    # note (app/bildmodellwerte.py).
    modell: str = ""
    # The family the picture window states for it; empty reads the family
    # from the model's own header, as ``/bild/vorgaben`` does.
    familie: str = ""
    # The CFG the picture is drawn at. At 1 and below sd.cpp leaves the
    # negative prompt out, so none is written.
    cfg: float | None = None
    # The picture window's style addition, a fact beside the request.
    stil: str = ""


class PromptAntwort(BaseModel):
    prompt: str
    negativ: str = ""


@router.post(
    "/bild/prompt",
    response_model=PromptAntwort,
    summary="Improve a picture prompt",
)
async def prompt_verbessern(
    wunsch: PromptWunsch,
    request: Request,
    discovery: Discovery = Depends(hole_discovery),
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
    repositories: Repositories = Depends(hole_repositories),
) -> PromptAntwort:
    # Checked BEFORE a model is asked: the user's own fields are refused as a
    # bad request, not reported as "the model could not be reached", and a
    # refused input does not cost a request.
    if len(wunsch.prompt.strip()) > MAX_EINGABE:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, t("bild.prompt_fehlgeschlagen", sprache)
        )
    if len(wunsch.stil.strip()) > MAX_EINGABE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, t("bild.stil_zu_lang", sprache)
        )
    family = _familie(config, wunsch.modell, wunsch.familie)
    # A family that is not known, or one that does not draw from text, has
    # no instruction: the window asks for the family, and ``draw_image``
    # draws with the request as it is.
    anweisung = bildaufbereitung.anweisung(repositories, family) if family else None
    if anweisung is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, t("bild.prompt_ohne_familie", sprache)
        )
    eigene = bildmodellwerte.eigene(repositories, wunsch.modell) if wunsch.modell else {}
    eintrag = image_families.get(family)
    negativ_wirkt = wunsch.cfg is None or wunsch.cfg > 1
    eingabe = nachricht(
        wunsch.prompt,
        datei=wunsch.modell,
        familie=eintrag.label if eintrag else "",
        negativ_wirkt=negativ_wirkt,
        trigger=str(eigene.get("trigger") or ""),
        hinweis=str(eigene.get("hinweis") or ""),
        stil=wunsch.stil,
    )
    zustand, modellname = _verbesserer(request, repositories, discovery, sprache)
    # The one list of stages this server has refused, under the id the model
    # list carries for it — the list a chat and a fold read and write too.
    # An "off" it has refused before is not sent again.
    refusal_id = refusal_key(zustand, modellname)

    def switch_off() -> dict:
        return denkschalter.zusatz(
            False, zustand, modell=modellname,
            abgelehnt=denkablehnung.gemerkt(repositories.einstellungen, refusal_id),
        )

    # The negative goes through its own, narrower instruction — and only
    # when there is one and it has an effect: an empty field stays an empty
    # field, and at CFG 1 and below the picture is drawn without it.
    negativ = wunsch.negativ.strip() if negativ_wirkt else ""

    async def rewrite(ohne_denken: dict) -> list[str]:
        """Both rewrites side by side — they are independent of each other."""
        laeufe = [verbessern(
            zustand.provider, modellname, eingabe, ohne_denken, anweisung=anweisung,
        )]
        if negativ:
            # The facts and the style describe the picture, so they belong to
            # the prompt that DESCRIBES one. The avoid-list is only translated
            # and tidied; a style hung on it would ask the model to keep the
            # wanted style OUT of the picture.
            laeufe.append(verbessern(
                zustand.provider, modellname, negativ,
                ohne_denken, anweisung=ANWEISUNG_NEGATIV,
            ))
        # Both requests together, and both end together: one that failed
        # leaves no other still holding a place on the model server. Ended
        # through the same place the runs use (app/generationen.discard) —
        # it waits for each to settle, and it reads and logs what a sibling
        # that had already finished carried: that failure is usually the
        # reason this cleanup is running at all, so it is written down here.
        aufgaben = [asyncio.ensure_future(lauf) for lauf in laeufe]
        try:
            return await asyncio.gather(*aufgaben)
        except BaseException:
            for aufgabe in aufgaben:
                gescheitert = await generationen.discard(aufgabe)
                if gescheitert is not None:
                    log.warning("The other image prompt request failed: %r", gescheitert)
            raise

    ohne_denken = switch_off()
    try:
        try:
            answers = await rewrite(ohne_denken)
        except ProviderFehler as fehler:
            # A refusal of the "off" is written down like a fold's, and the
            # rewrite goes out once more at once without it, as a fold does.
            # Any other failure gets no second request.
            if not denkablehnung.lernen(
                repositories.einstellungen, refusal_id, fehler, ohne_denken, "off",
                route=denkschalter.route_for(zustand, modell=modellname),
            ):
                raise
            answers = await rewrite(switch_off())
        ergebnis = answers[0]
        if negativ:
            negativ = answers[1]
    except PromptFehler as fehler:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, t("bild.prompt_fehlgeschlagen", sprache)
        ) from fehler
    except ProviderFehler as fehler:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, t("bild.prompt_fehlgeschlagen", sprache)
        ) from fehler
    return PromptAntwort(prompt=ergebnis, negativ=negativ)


class AufbereitungAntwort(BaseModel):
    # Who writes the prompts now: "agent", "modell", "putzmodell" or
    # "kennung:<id>" (app/bildaufbereitung.py).
    verbesserer: str
    # The instruction each family writes with right now, and the works text
    # "reset" brings back — the text lives in app/bildprompt.py, and the
    # block only ever shows a copy of it.
    anweisungen: dict[str, str]
    ab_werk: dict[str, str]
    # The families by the reader their text goes through, in the order the
    # block lists them.
    leser: dict[str, list[str]]


@router.get(
    "/bild/prompt/aufbereitung",
    response_model=AufbereitungAntwort,
    summary="The image server's prompt preparation",
)
def aufbereitung_lesen(
    repositories: Repositories = Depends(hole_repositories),
) -> AufbereitungAntwort:
    """What the picture server's "Prompt preparation" block shows. Written
    through the settings route (``bildaufbereitung``), like every other
    block of the server windows."""
    eigene = bildaufbereitung.eigene_anweisungen(repositories)
    return AufbereitungAntwort(
        verbesserer=bildaufbereitung.verbesserer(repositories),
        anweisungen={name: eigene.get(name, text) for name, text in ANWEISUNGEN.items()},
        ab_werk=dict(ANWEISUNGEN),
        leser={leser: list(namen) for leser, namen in LESER.items()},
    )


def _familie(config: Config, modell: str, genannt: str) -> str:
    """The family the prompt is written for: the one the window states, and
    without one the family the model's own header names."""
    if image_families.get(genannt) is not None:
        return genannt
    if not modell:
        return ""
    try:
        pfad = modell_pfad(ort(config, "image_models"), modell)
    except Exception:  # noqa: BLE001 - a name that is no file has no family
        return ""
    return bildinhalt.family(pfad) or ""


def _verbesserer(request: Request, repositories, discovery: Discovery, sprache: str):
    """The server chosen to write the prompt, as an endpoint and the model
    to ask — or an error saying it does not answer.

    The agent server is the agent model as a run resolves it, the model
    server is the main model, a cloud model is asked by its id. The clean-up
    server is no endpoint of the model list, so it is asked at the address
    it runs on, the way the speech server's clean-up asks it.

    The choice is honoured or REFUSED: preparing on some other model than
    the one chosen would be the same lie as a button that does nothing.
    """
    wer = bildaufbereitung.verbesserer(repositories)
    if wer == "putzmodell":
        putz = request.app.state.sprachputzrunner
        lauf = putz.lauf()
        if lauf is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, t("bild.prompt_kein_modell", sprache)
            )
        endpunkt = EndpointConfig(
            id="bereinigung",
            base_url=f"http://127.0.0.1:{lauf.port}/v1",
            provider="openai_compatible",
            parameter_dialect="llama_cpp",
            group="local",
            api_key_env=sprachserver.PUTZ_SCHLUESSEL_VARIABLE,
        )
        zustand = EndpunktZustand(endpunkt=endpunkt, provider=provider_bauen(endpunkt), erreichbar=True)
        return zustand, zustand.gemeldeter_name
    if wer == "agent":
        kennung = agentenmodellwahl.lauf_kennung(
            repositories, discovery, slot_id=agentenserver.ENDPUNKT_ID,
        )
    elif wer == "modell":
        kennung = agentenmodellwahl.HAUPTMODELL
    else:
        kennung = wer.removeprefix(bildaufbereitung.KENNUNG)
    gefunden = discovery.aufloesen(kennung) if kennung else None
    if gefunden is not None and gefunden[0].erreichbar:
        return gefunden
    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE, t("bild.prompt_kein_modell", sprache)
    )
