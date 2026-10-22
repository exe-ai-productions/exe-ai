"""Searching Hugging Face for a model that can run on this machine.

The program has always assumed a model server was already running. For
whoever installs it fresh, that assumption is the whole problem: nothing
happens, and nothing says why. Finding a model is the first half of the
answer — running it is the second, and that one belongs to the runner that
does not exist yet.

Only GGUF is offered, on purpose: it is the one kind the program can fetch
as a single file and start by itself. Everything else on Hugging Face needs
Python, a framework or a graphics card to be sorted out first — that is a
different program, not ours. MLX runs beautifully on Apple silicon and is
still out, for the same reason it left the runner: it cannot travel with an
installer.

The search runs on the server and not in the browser: the page would have
to talk to a foreign host itself, and then every user's address ends up in
someone else's log for a search they only wanted to type. The picture of a
repository's owner is fetched the same way, for the same reason.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel

from app.api.abhaengigkeiten import hole_sprache
from app.i18n import t
from app.tools import mcp_logo

log = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["modellsuche"])

HF_ADRESSE = "https://huggingface.co/api/models"

# What we can do something with. The key is what the caller asks for — one
# of the catalogue's three tabs — the value is the list of Hugging Face
# task tags that belong to that kind. Always GGUF on top of it.
#
# The chat tab queries WITHOUT a tag and drops the other kinds afterwards:
# most community quant repositories carry no pipeline tag at all, and a
# hard tag filter makes nine of ten of them unfindable (measured against
# the live API). The embedding tab needs two tags, because half the known
# embedding repositories say "sentence-similarity" instead of
# "feature-extraction".
ARTEN = {
    "chat": [],
    "einbettung": ["feature-extraction", "sentence-similarity"],
    # Speech models. The tag is honest and narrow, but it also carries a lot
    # of PyTorch repositories that hold no GGUF at all — the file filter
    # below is what keeps those out of a tab whose server can only start a
    # single GGUF file. Speaking models carry their own tag, so the tab asks
    # for both kinds, like the embedding tab with its two.
    "sprache": ["automatic-speech-recognition", "text-to-speech"],
    "bild": ["text-to-image"],
    # Video generation. No tab of its own in this window — the kind exists
    # for the other Exe programs that share this search (Exe Motion asks
    # with it), so the token and the tunnel stay in one place.
    "video": ["image-to-video", "text-to-video"],
    # Accessories (VAE, LoRA, face detectors, drafters, projectors) have no
    # honest Hugging Face tag to search by — a tagless query would just spill
    # chat models into the tab. The tab is curated only; its search returns
    # nothing on purpose (see `suchen`).
    "zubehoer": [],
}

# The file format each tab restricts to, or None for no restriction. Chat and
# embedding models must be GGUF — that is the one form the program can fetch as
# a single file and start by itself. Image models are the exception: the
# shipped drawer (sd.cpp) reads safetensors AND gguf, and the big image
# checkpoints live on Hugging Face almost only as safetensors. A gguf filter
# on the image tab hid exactly the models people came for; the text-to-image
# tag keeps the tab to image models without it.
DATEIFILTER = {
    "chat": "gguf",
    "einbettung": "gguf",
    "sprache": "gguf",
    "bild": None,
    "video": None,
    "zubehoer": None,
}

# The kinds a tagless chat query must drop so the tabs stay separate.
KEIN_CHAT = {tag for tags in ARTEN.values() for tag in tags}

# The old name for "the one kind there was". A page from before the tabs
# may still ask with it; it meant what the chat tab means now.
ART_ALT = {"gguf": "chat"}

MAX_TREFFER = 24

HF_SITE = "https://huggingface.co"
# Where Hugging Face keeps the overview of an owner: first as an organisation,
# then as a user account.
AVATAR_KINDS = ("organizations", "users")
# What a name on Hugging Face may look like. The name goes into an address,
# so nothing else is let through.
_OWNER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
# An overview is a few kilobytes; anything beyond this is not one.
MAX_OVERVIEW_BYTES = 262_144
# A picture of an owner changes rarely; the browser may keep it for a day.
AVATAR_KEEP_SECONDS = 86_400


class Fund(BaseModel):
    id: str
    name: str
    anbieter: str
    ladungen: int
    beliebt: int
    aufgabe: str | None = None


class Avatar(BaseModel):
    image: str


def _fund_bauen(eintrag: dict[str, Any]) -> Fund:
    kennung = eintrag.get("modelId") or eintrag.get("id") or ""
    anbieter, _, name = kennung.partition("/")
    return Fund(
        id=kennung,
        name=name or kennung,
        anbieter=anbieter if name else "",
        ladungen=int(eintrag.get("downloads") or 0),
        beliebt=int(eintrag.get("likes") or 0),
        aufgabe=eintrag.get("pipeline_tag"),
    )


@router.get("/search", response_model=list[Fund], summary="Search models")
async def suchen(
    q: str = Query(min_length=1, max_length=100),
    art: str = Query("chat"),
    anzahl: int = Query(12, ge=1, le=MAX_TREFFER),
    sprache: str = Depends(hole_sprache),
) -> list[Fund]:
    art = ART_ALT.get(art, art)
    if art not in ARTEN:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, t("fehler.modellsuche_art", sprache)
        )
    # The accessories tab is curated only — there is no meaningful Hugging Face
    # query for it, so it never reaches the live search.
    if art == "zubehoer":
        return []

    import os

    kopf = {}
    wert = os.environ.get("HF_TOKEN", "").strip()
    if wert:
        kopf["Authorization"] = f"Bearer {wert}"

    grund = {
        "search": q,
        "sort": "downloads",
        "direction": "-1",
        "limit": anzahl,
    }
    if DATEIFILTER[art]:
        grund["filter"] = DATEIFILTER[art]
    # One query per tag; the chat tab is the one tagless query.
    anfragen = (
        [grund]
        if not ARTEN[art]
        else [{**grund, "pipeline_tag": tag} for tag in ARTEN[art]]
    )

    daten: list[Any] = []
    try:
        async with httpx.AsyncClient(timeout=15, headers=kopf) as client:
            for parameter in anfragen:
                antwort = await client.get(HF_ADRESSE, params=parameter)
                antwort.raise_for_status()
                teil = antwort.json()
                if not isinstance(teil, list):
                    raise HTTPException(
                        status.HTTP_502_BAD_GATEWAY,
                        t("fehler.modellsuche_fern", sprache),
                    )
                daten += teil
    except httpx.HTTPError:
        # The catalogue is somebody else's server. It being down is a normal
        # day, not an error in this program — and it says so instead of
        # showing an empty list that looks like "nothing found".
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, t("fehler.modellsuche_fern", sprache)
        ) from None

    # The tagless chat query drops the kinds the other tabs own; a tagged
    # multi-query merges, so duplicates go and the best-loaded come first.
    gesehen: set[str] = set()
    treffer: list[dict[str, Any]] = []
    for eintrag in daten:
        if not isinstance(eintrag, dict):
            continue
        kennung = eintrag.get("modelId") or eintrag.get("id") or ""
        if not kennung or kennung in gesehen:
            continue
        if not ARTEN[art] and eintrag.get("pipeline_tag") in KEIN_CHAT:
            continue
        gesehen.add(kennung)
        treffer.append(eintrag)
    treffer.sort(key=lambda e: int(e.get("downloads") or 0), reverse=True)

    return [_fund_bauen(eintrag) for eintrag in treffer[:anzahl]]


async def _avatar_address(client: httpx.AsyncClient, owner: str) -> str | None:
    """The address of the owner's picture as Hugging Face names it, asked of
    the organisation first and then of the user account of that name."""
    for kind in AVATAR_KINDS:
        async with client.stream("GET", f"{HF_SITE}/api/{kind}/{owner}/overview") as answer:
            if answer.status_code == 404:
                continue
            if answer.status_code != 200:
                return None
            body = bytearray()
            async for chunk in answer.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_OVERVIEW_BYTES:
                    return None
        overview = json.loads(bytes(body))
        address = overview.get("avatarUrl") if isinstance(overview, dict) else None
        if not isinstance(address, str):
            return None
        # The overview names the picture with a full address or with one
        # relative to the site.
        address = urljoin(HF_SITE + "/", address)
        return address if address.startswith("https://") else None
    return None


async def owner_avatar(owner: str, transport: httpx.AsyncBaseTransport | None = None) -> str | None:
    """The round picture Hugging Face shows for ``owner``, as a ``data:`` URL,
    or None.

    Fetched here and never by the browser, and kept nowhere: what leaves is
    one picture or nothing. The picture is checked like the logo an MCP server
    sends along (only https, a small size, no redirect, a kind decided on the
    bytes). Whatever fails leaves the letter in place; a picture is an extra
    and must never raise.
    """
    if not _OWNER_NAME.match(owner):
        return None
    try:
        # No token and no cookies: what is asked for is public.
        async with httpx.AsyncClient(
            timeout=10, follow_redirects=False, trust_env=False, transport=transport
        ) as client:
            address = await _avatar_address(client, owner)
        if address is None:
            return None
        return await mcp_logo.logo_of([{"src": address}], None, transport)
    except Exception:  # noqa: BLE001 - a picture must never keep a page from drawing
        log.info("The picture of a model owner is not taken: it could not be read", exc_info=True)
        return None


@router.get("/avatar/{owner}", response_model=Avatar, summary="Picture of a model owner")
async def avatar(owner: str, response: Response) -> Avatar:
    image = await owner_avatar(owner)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no picture")
    response.headers["Cache-Control"] = f"private, max-age={AVATAR_KEEP_SECONDS}"
    return Avatar(image=image)
