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
from io import StringIO
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.representer import RoundTripRepresenter

from app import atomic_file
from app.api.abhaengigkeiten import hole_config, hole_sprache
from app import fenstergroesse
from app.config import Config, EndpointConfig, config_file
from app.env_datei import env_entfernen, env_schreiben, key_leaves_with
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


class _KonfigDarsteller(RoundTripRepresenter):
    """Writes an empty value as the word `null`, the way the file has always
    carried it; the parser would write it as nothing at all."""

    def darstellen_nichts(self, daten: None) -> Any:
        return self.represent_scalar("tag:yaml.org,2002:null", "null")


# On the subclass only: the parser's own class keeps its way of writing.
_KonfigDarsteller.add_representer(type(None), _KonfigDarsteller.darstellen_nichts)


def _einzug(text: str) -> tuple[int, int]:
    """The indent the file already uses: the width of a nested mapping, and
    how far a list dash stands in from its key. A file written by hand or by
    this program keeps its own look when it is written back."""
    mapping, dash = 2, 0
    zeilen = text.splitlines()
    for zeile in zeilen:
        stripped = zeile.lstrip(" ")
        if stripped.startswith("- "):
            dash = len(zeile) - len(stripped)
            break
    for zeile in zeilen:
        stripped = zeile.lstrip(" ")
        if stripped and not stripped.startswith(("#", "- ")) and len(zeile) > len(stripped):
            mapping = len(zeile) - len(stripped)
            break
    return mapping, dash


def _lesen(konfig_datei: Path) -> tuple[Any, YAML]:
    """The file parsed for writing back, and the writer that gives it back as
    it was: comments, blank lines, key order, quotes and the indent stay, and
    only what a route changed in the returned value changes in the file.

    The value is changed in place (an entry removed with ``del``, not by
    building a new list): a new list has none of the comments the old one
    carried between its entries.
    """
    text = konfig_datei.read_text(encoding="utf-8")
    mapping, dash = _einzug(text)
    schreiber = YAML()
    schreiber.preserve_quotes = True
    schreiber.allow_unicode = True
    # A long value is never folded onto a second line.
    schreiber.width = 4096
    schreiber.indent(mapping=mapping, sequence=dash + 2, offset=dash)
    schreiber.Representer = _KonfigDarsteller
    daten = schreiber.load(text)
    return (CommentedMap() if daten is None else daten), schreiber


def _schwanz(eintrag: Any) -> tuple[CommentedMap, Any] | None:
    """Where the comment lines behind an entry are kept: on the last key of
    its last nested mapping (the parser hangs them on the value they follow).
    None for an entry that ends in a list — those comments stay where they
    are."""
    knoten = eintrag
    while isinstance(knoten, CommentedMap) and knoten:
        schluessel = list(knoten.keys())[-1]
        wert = knoten[schluessel]
        if isinstance(wert, CommentedMap) and wert:
            knoten = wert
            continue
        if isinstance(wert, CommentedSeq):
            return None
        return knoten, schluessel
    return None


def _eintrag_entfernen(endpunkte: Any, stelle: int) -> None:
    """Takes one entry out of the list, with the comment that introduced it
    and the one that ends its last line, and keeps the comment lines behind
    it: those introduce the NEXT entry, and the parser has them hanging on
    this one, where a plain removal would drop them with it."""
    if stelle > 0:
        weg = _schwanz(endpunkte[stelle])
        davor = _schwanz(endpunkte[stelle - 1])
        if weg and davor:
            wegstelle = weg[0].ca.items.get(weg[1])
            token = wegstelle[2] if wegstelle else None
            if token is not None:
                # Everything behind the first line break is comment lines of
                # their own; the first line is the removed entry's own line end.
                rest = token.value.split("\n", 1)[1] if "\n" in token.value else ""
                eintrag = davor[0].ca.items.setdefault(davor[1], [None, None, None, None])
                if eintrag[2] is not None:
                    # The line end of the entry in front keeps its own comment.
                    eintrag[2].value = eintrag[2].value.split("\n", 1)[0] + "\n" + rest
                else:
                    token.value = "\n" + rest
                    eintrag[2] = token
    del endpunkte[stelle]


def _atomar_schreiben(konfig_datei: Path, rohdaten: Any, schreiber: YAML) -> None:
    """Whole or not at all (app/atomic_file.py): an interrupted write in
    place would leave a half file — and a half ``config.yaml`` is a program
    with no endpoints at all on the next start.

    Blocking: the write waits on Windows while the file is held. A route
    calls it through ``asyncio.to_thread`` so the event loop keeps answering.
    """
    ausgabe = StringIO()
    schreiber.dump(rohdaten, ausgabe)
    atomic_file.write(konfig_datei, ausgabe.getvalue())


# One route at a time between reading config.yaml and writing it back: the
# write runs in a thread, so the loop is free in between — and a second
# route reading the file in that gap would write the older content over
# the newer one.
_schleuse = asyncio.Lock()


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
    art: str = Field(description="anthropic, openai, or eigen")
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
    # Where the provider said why it refuses, the sentence for the window to
    # show; None otherwise.
    hinweis: str | None = None


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

    konfig_datei = config_file(config)
    async with _schleuse:
        rohdaten, schreiber = _lesen(konfig_datei)
        endpunkte = rohdaten.setdefault("endpoints", [])

        if any(e.get("id") == kennung for e in endpunkte):
            raise HTTPException(status.HTTP_409_CONFLICT, t("fehler.anbieter_doppelt", sprache))

        endpunkte.append({"id": kennung, "group": "cloud", **vorlage})
        await asyncio.to_thread(_atomar_schreiben, konfig_datei, rohdaten, schreiber)

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
    erreichbar = bool(zustand and zustand.erreichbar)
    hinweis = None
    if zustand is not None and not erreichbar and zustand.grund:
        hinweis = t(
            "fehler.anbieter_nicht_erreichbar", sprache,
            name=zustand.provider.name, detail=zustand.grund,
        )

    return Angelegt(
        id=kennung,
        api_key_env=vorlage["api_key_env"],
        erreichbar=erreichbar,
        hinweis=hinweis,
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
    konfig_datei = config_file(config)
    async with _schleuse:
        if konfig_datei.is_file():
            rohdaten, schreiber = _lesen(konfig_datei)
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
            await asyncio.to_thread(_atomar_schreiben, konfig_datei, rohdaten, schreiber)

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

    konfig_datei = config_file(config)
    async with _schleuse:
        if konfig_datei.is_file():
            rohdaten, schreiber = _lesen(konfig_datei)
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
                await asyncio.to_thread(_atomar_schreiben, konfig_datei, rohdaten, schreiber)

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

    konfig_datei = config_file(config)
    async with _schleuse:
        if konfig_datei.is_file():
            rohdaten, schreiber = _lesen(konfig_datei)
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
                await asyncio.to_thread(_atomar_schreiben, konfig_datei, rohdaten, schreiber)

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

    The entry leaves ``config.yaml`` and its key line leaves ``.env`` — unless
    another provider reads the same variable, then the line stays for that
    one. Writing happens where the running service actually read its
    endpoints from (``config_file``), never the template, and the other
    entries and lines travel through the round trip unchanged.
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
    konfig_datei = config_file(config)
    async with _schleuse:
        if konfig_datei.is_file():
            entfernt = False
            rohdaten, schreiber = _lesen(konfig_datei)
            endpunkte = rohdaten.get("endpoints") or []
            # In place, last to first: the entries after a removed one move up
            # and the comments between them move with them.
            for stelle in range(len(endpunkte) - 1, -1, -1):
                if endpunkte[stelle].get("id") == endpoint_id:
                    _eintrag_entfernen(endpunkte, stelle)
                    entfernt = True
            if entfernt:
                await asyncio.to_thread(_atomar_schreiben, konfig_datei, rohdaten, schreiber)

    # Asked, removed from the list and taken out of ``.env`` in one go, with
    # no wait in between: a provider added meanwhile either is in the list
    # when this asks, or writes its line after this has run. The running
    # environment loses the variable only where the line came out of the
    # file — a variable the shell set was never this window's to take away.
    key_goes = key_leaves_with(config.endpoints, endpoint_id)
    config.endpoints[:] = [e for e in config.endpoints if e.id != endpoint_id]
    if key_goes and env_entfernen(config.pfad("./.env"), endpunkt.api_key_env):
        os.environ.pop(endpunkt.api_key_env, None)

    await request.app.state.discovery.abmelden(endpoint_id)

    return Response(status_code=204)
