"""Adding a cloud provider from the window instead of from a text editor.

The cloud window used to be a dead end: it said no provider was set up and
offered no way to set one up. The only way in was `.env` and `config.yaml`,
opened by hand — the one thing this program is supposed to spare people.

Two files change when a provider arrives, and both are the user's:

* the key goes into `.env`, where only the service reads it, and it is never
  handed back out — the window only ever learns *whether* one is there;
* the endpoint goes into `config.yaml`, in the same shape somebody would
  have typed by hand.

Three kinds are offered, and the third is the reason this stays small: for
anything OpenAI-compatible only the address differs, so a server in one's own
network costs no extra code.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app import atomic_file
from app.api.abhaengigkeiten import hole_config, hole_sprache
from app import fenstergroesse
from app.config import Config, EndpointConfig
from app.env_datei import env_schreiben
from app.i18n import t

router = APIRouter(prefix="/providers", tags=["anbieter"])

# What a known provider needs. Everything here would otherwise have to be
# typed correctly by hand — the address most of all.
BEKANNT = {
    "anthropic": {
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "api_key_env": "ANTHROPIC_API_KEY",
        "parameter_dialect": "anthropic",
        # Cloud servers have no /props to sniff, so without an explicit
        # entry every capability resolves to "no" and tools stay silent.
        # Both houses' chat models take tool calls and images.
        "capabilities": {"tool_calls": True, "vision": True},
    },
    "openai": {
        "provider": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "parameter_dialect": "openai",
        "capabilities": {"tool_calls": True, "vision": True},
    },
}

# An id becomes a key name in .env and a section in config.yaml, so it stays
# in the alphabet both of them can carry.
KENNUNG = re.compile(r"^[a-z][a-z0-9_-]{1,30}$")


def _atomar_schreiben(konfig_datei: Path, rohdaten: dict) -> None:
    """Whole or not at all (app/atomic_file.py): an interrupted write in
    place would leave a half file — and a half ``config.yaml`` is a program
    with no endpoints at all on the next start.

    Blocking: the write waits on Windows while the file is held. A route
    calls it through ``asyncio.to_thread`` so the event loop keeps answering.
    """
    atomic_file.write(
        konfig_datei, yaml.safe_dump(rohdaten, allow_unicode=True, sort_keys=False)
    )


# One route at a time between reading config.yaml and writing it back: the
# write runs in a thread, so the loop is free in between — and a second
# route reading the file in that gap would write the older content over
# the newer one.
_schleuse = asyncio.Lock()


def _konfig_datei(config: Config) -> Path:
    """The file the running service actually read its endpoints from.

    ``EXE_AI_CONFIG`` points a run at a different file (a test service with
    its own data does exactly that). Writing to the default location then
    changes a file NOBODY reads — and worse, one that belongs to somebody
    else's setup. The write has to land where the read came from.
    """
    eigen = os.getenv("EXE_AI_CONFIG")
    if eigen:
        return Path(eigen)
    return config.pfad("./config.yaml")


class KontextAendern(BaseModel):
    """The context window of an endpoint, said by hand.

    Not a capability and not a setting the model would obey — it is the one
    number the display needs and some providers never report. A local server
    answers it itself, and Anthropic's model list names it; an OpenAI model
    list carries nothing of the kind, so its context bar stayed empty with
    no way to fill it in short of editing ``config.yaml``.

    ``None`` (and a zero, which nobody means literally) removes the entry
    and returns the endpoint to asking its server.
    """

    # Same ceiling the request schema allows for a whole answer — a window
    # smaller than the answer it has to hold would be a typo, not a setting.
    context_tokens: int | None = Field(default=None, ge=0, le=10_000_000)


class FaehigkeitenAendern(BaseModel):
    """The hand-set capability of an endpoint.

    Cloud servers have no ``/props`` to sniff, and their model lists say
    nothing about modalities — so without an explicit entry a capability
    resolves to "no" even when the model could do it. This is the way to say
    so by hand: whoever knows their model sees images must be able to say
    it, and the configuration entry is exactly that word. ``None`` removes
    the entry and returns the endpoint to detection (local) or "no" (cloud).
    """

    vision: bool | None = None
    tool_calls: bool | None = None
    # A list of stage keys where somebody knows exactly what their model
    # takes; the bare boolean is the older form of the same word and still
    # reads as a plain on/off control.
    thinking: bool | list[str] | None = None


class ZeitgrenzeAendern(BaseModel):
    """The "Zeitgrenze" switch of an endpoint, set by hand.

    On by default: the 600 s a model call has always had. Off drops the
    read timeout only — the connect timeout stays, since a server that
    cannot even be reached has nothing to wait for.
    """

    timeout_enabled: bool


class NeuerAnbieter(BaseModel):
    art: str = Field(description="anthropic, openai oder eigen")
    schluessel: str = Field(min_length=8, max_length=400)
    # Only for `eigen`: everything else is known.
    kennung: str | None = None
    url: str | None = None


class Angelegt(BaseModel):
    id: str
    api_key_env: str
    # `anmelden()` below already checks reachability once, right away — this
    # just hands that one result on instead of letting the caller re-derive
    # it (or worse, assume success) from silence.
    erreichbar: bool


@router.post("", response_model=Angelegt, summary="Add a cloud provider")
async def hinzufuegen(
    daten: NeuerAnbieter,
    request: Request,
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> Angelegt:
    if daten.art in BEKANNT:
        kennung = daten.art
        vorlage = dict(BEKANNT[daten.art])
    elif daten.art == "eigen":
        kennung = (daten.kennung or "").strip().lower()
        if not KENNUNG.match(kennung):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, t("fehler.anbieter_kennung", sprache)
            )
        if not (daten.url or "").startswith(("http://", "https://")):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, t("fehler.anbieter_adresse", sprache)
            )
        vorlage = {
            "provider": "openai_compatible",
            "base_url": daten.url.rstrip("/"),
            "api_key_env": f"{kennung.upper().replace('-', '_')}_API_KEY",
            "parameter_dialect": "openai",
            # The same as the presets above: a server without /props never
            # says it takes tools, and without them every server measured
            # (oMLX, vLLM, llama.cpp, Ollama, LM Studio) writes a tool call
            # into the text. A hand-set `false` later stays.
            "capabilities": {"tool_calls": True},
        }
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, t("fehler.anbieter_art", sprache))

    konfig_datei = _konfig_datei(config)
    async with _schleuse:
        rohdaten = yaml.safe_load(konfig_datei.read_text(encoding="utf-8")) or {}
        endpunkte = rohdaten.setdefault("endpoints", [])

        if any(e.get("id") == kennung for e in endpunkte):
            raise HTTPException(status.HTTP_409_CONFLICT, t("fehler.anbieter_doppelt", sprache))

        endpunkte.append({"id": kennung, "group": "cloud", **vorlage})
        await asyncio.to_thread(_atomar_schreiben, konfig_datei, rohdaten)

    # The key last: an entry without a key shows a red lamp and can be
    # repaired, a key without an entry belongs to nothing and is only lying
    # around.
    env_schreiben(config.pfad("./.env"), vorlage["api_key_env"], daten.schluessel.strip())

    # The file serves the next start; the running service reads its
    # environment. Without this line the provider stays red until a restart —
    # a working key that looks broken.
    os.environ[vorlage["api_key_env"]] = daten.schluessel.strip()

    # And the provider joins the model list right away, same route as the
    # model server: the window that just added it is looking at that list.
    endpunkt = EndpointConfig(id=kennung, group="cloud", **vorlage)
    config.endpoints.append(endpunkt)
    await request.app.state.discovery.anmelden(endpunkt)
    zustand = request.app.state.discovery.zustaende.get(kennung)

    return Angelegt(
        id=kennung,
        api_key_env=vorlage["api_key_env"],
        erreichbar=bool(zustand and zustand.erreichbar),
    )


@router.put(
    "/{endpoint_id}/capabilities",
    response_model=dict,
    summary="Set an endpoint's capabilities by hand",
)
async def faehigkeiten_setzen(
    endpoint_id: str,
    daten: FaehigkeitenAendern,
    request: Request,
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> dict:
    """Writes the explicit capability entries for one endpoint.

    Only the fields the request carries are touched. An explicit entry
    always wins over detection — in both directions — which is exactly what
    the configuration contract in ``app/config.py`` promises. The change
    lands in ``config.yaml`` (it survives a restart) and in the running
    service (it works right now).
    """
    endpunkt = next((e for e in config.endpoints if e.id == endpoint_id), None)
    if endpunkt is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            t("fehler.modell_nicht_erreichbar", sprache, name=endpoint_id),
        )

    genannt = daten.model_fields_set
    if not genannt:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, t("fehler.anbieter_art", sprache))

    # The running service first: the window that flipped the switch is
    # looking at this list.
    for name in ("vision", "tool_calls", "thinking"):
        if name in genannt:
            setattr(endpunkt.capabilities, name, getattr(daten, name))

    # Then the file, so the word survives a restart. The file may not exist
    # on setups configured purely by environment — then the running value is
    # all there is, and saying nothing would hide that.
    konfig_datei = _konfig_datei(config)
    async with _schleuse:
        if konfig_datei.is_file():
            rohdaten = yaml.safe_load(konfig_datei.read_text(encoding="utf-8")) or {}
            for eintrag in rohdaten.get("endpoints") or []:
                if eintrag.get("id") != endpoint_id:
                    continue
                faehigkeiten = eintrag.setdefault("capabilities", {})
                for name in ("vision", "tool_calls", "thinking"):
                    if name not in genannt:
                        continue
                    wert = getattr(daten, name)
                    if wert is None:
                        faehigkeiten.pop(name, None)
                    else:
                        faehigkeiten[name] = wert
                if not faehigkeiten:
                    eintrag.pop("capabilities", None)
            await asyncio.to_thread(_atomar_schreiben, konfig_datei, rohdaten)

    return {"id": endpoint_id, "capabilities": endpunkt.capabilities.model_dump()}


@router.put(
    "/{endpoint_id}/context",
    response_model=dict,
    summary="Set an endpoint's context size by hand",
)
async def kontext_setzen(
    endpoint_id: str,
    daten: KontextAendern,
    request: Request,
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> dict:
    """Writes the context window for one endpoint.

    The same two places the capability switch writes to: the running service
    first, because the window that typed the number is looking at this list,
    then the file, so it survives a restart.

    Discovery caches what it once asked, so the cached number is replaced
    here as well. A value entered is simply that value, source "eingetragen".
    Cleared, it does not go back to a blank ``None`` — it is resolved again,
    right away, through the same order discovery uses (app/fenstergroesse.py):
    an emptied field should read as "work it out yourself" from the very
    next line the window draws, not as "unknown" until the next poll.
    """
    endpunkt = next((e for e in config.endpoints if e.id == endpoint_id), None)
    if endpunkt is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            t("fehler.modell_nicht_erreichbar", sprache, name=endpoint_id),
        )

    wert = daten.context_tokens or None
    endpunkt.context_tokens = wert
    zustand = request.app.state.discovery.zustaende.get(endpoint_id)
    if zustand is not None:
        if wert is not None:
            zustand.context_tokens = wert
            zustand.kontext_quelle = fenstergroesse.QUELLE_EINGETRAGEN
        else:
            zustand.context_tokens, zustand.kontext_quelle = (
                await fenstergroesse.serverseitig_aufloesen(
                    zustand, request.app.state.repositories, config.discovery.timeout_seconds
                )
            )

    konfig_datei = _konfig_datei(config)
    async with _schleuse:
        if konfig_datei.is_file():
            rohdaten = yaml.safe_load(konfig_datei.read_text(encoding="utf-8")) or {}
            getroffen = False
            for eintrag in rohdaten.get("endpoints") or []:
                if eintrag.get("id") != endpoint_id:
                    continue
                getroffen = True
                if wert is None:
                    eintrag.pop("context_tokens", None)
                else:
                    eintrag["context_tokens"] = wert
            # Only when this file actually carries the endpoint. Writing anyway
            # would round-trip the whole file for nothing, and this round trip is
            # not free: it goes through the parser, so every explaining comment in
            # it is gone afterwards.
            if getroffen:
                await asyncio.to_thread(_atomar_schreiben, konfig_datei, rohdaten)

    return {"id": endpoint_id, "context_tokens": wert}


@router.put(
    "/{endpoint_id}/timeout",
    response_model=dict,
    summary="Set an endpoint's time limit by hand",
)
async def zeitgrenze_setzen(
    endpoint_id: str,
    daten: ZeitgrenzeAendern,
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> dict:
    """Writes the "Zeitgrenze" switch for one endpoint.

    The same two places the capability switch writes to: the running
    service first, because the window that flipped the switch is looking at
    this list, then the file, so it survives a restart.
    """
    endpunkt = next((e for e in config.endpoints if e.id == endpoint_id), None)
    if endpunkt is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            t("fehler.modell_nicht_erreichbar", sprache, name=endpoint_id),
        )

    endpunkt.timeout_enabled = daten.timeout_enabled

    konfig_datei = _konfig_datei(config)
    async with _schleuse:
        if konfig_datei.is_file():
            rohdaten = yaml.safe_load(konfig_datei.read_text(encoding="utf-8")) or {}
            getroffen = False
            for eintrag in rohdaten.get("endpoints") or []:
                if eintrag.get("id") != endpoint_id:
                    continue
                getroffen = True
                # On is the default: an entry that agrees with it needs no
                # line of its own, the same as an absent one already means it.
                if daten.timeout_enabled:
                    eintrag.pop("timeout_enabled", None)
                else:
                    eintrag["timeout_enabled"] = False
            if getroffen:
                await asyncio.to_thread(_atomar_schreiben, konfig_datei, rohdaten)

    return {"id": endpoint_id, "timeout_enabled": daten.timeout_enabled}


@router.delete(
    "/{endpoint_id}", status_code=204, response_class=Response, summary="Remove a provider"
)
async def loeschen(
    endpoint_id: str,
    request: Request,
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> Response:
    """Removes a provider — the counterpart of ``hinzufuegen`` above.

    Only the entry in ``config.yaml`` goes; the key stays in ``.env``
    untouched, so re-adding the same provider later needs no new key. Writing
    happens where the running service actually read its endpoints from
    (``_konfig_datei``), never the template, and the other entries travel
    through the round trip unchanged.
    """
    endpunkt = next((e for e in config.endpoints if e.id == endpoint_id), None)
    if endpunkt is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            t("fehler.modell_nicht_erreichbar", sprache, name=endpoint_id),
        )

    # The file first: if this write fails, the running service and the
    # discovery list stay exactly as they were, and the client sees an
    # error instead of state that disagrees with the file.
    konfig_datei = _konfig_datei(config)
    async with _schleuse:
        if konfig_datei.is_file():
            rohdaten = yaml.safe_load(konfig_datei.read_text(encoding="utf-8")) or {}
            vorher = rohdaten.get("endpoints") or []
            rohdaten["endpoints"] = [e for e in vorher if e.get("id") != endpoint_id]
            if len(rohdaten["endpoints"]) != len(vorher):
                await asyncio.to_thread(_atomar_schreiben, konfig_datei, rohdaten)

    config.endpoints[:] = [e for e in config.endpoints if e.id != endpoint_id]
    await request.app.state.discovery.abmelden(endpoint_id)

    return Response(status_code=204)
