"""The Hugging Face token, set from the window instead of a text editor.

Optional on purpose: everything public works without one. With one, the
catalogue lifts its rate limits and opens gated models — the very models
somebody signs an agreement for. Same handling as the provider keys: into
``.env`` with tight permissions and into the running environment. The
window learns whether one is there and its last four characters — enough
to tell two tokens apart, too few to use — and can take it out again.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.abhaengigkeiten import hole_config
from app.config import Config
from app.env_datei import env_entfernen, env_schreiben

router = APIRouter(prefix="/models", tags=["modellsuche"])

NAME = "HF_TOKEN"


class TokenStand(BaseModel):
    gesetzt: bool
    # The last four characters, shown behind the masking dots.
    ende: str | None = None


class NeuesToken(BaseModel):
    token: str = Field(min_length=8, max_length=400)


def token() -> str | None:
    wert = os.environ.get(NAME, "").strip()
    return wert or None


@router.get("/token", response_model=TokenStand, summary="Whether a token has been configured")
def stand() -> TokenStand:
    wert = token()
    return TokenStand(gesetzt=wert is not None, ende=wert[-4:] if wert else None)


@router.post("/token", response_model=TokenStand, summary="Set the Hugging Face token")
def setzen(daten: NeuesToken, config: Config = Depends(hole_config)) -> TokenStand:
    wert = daten.token.strip()
    env_schreiben(config.pfad("./.env"), NAME, wert)
    os.environ[NAME] = wert
    return TokenStand(gesetzt=True, ende=wert[-4:])


@router.delete("/token", response_model=TokenStand, summary="Remove the Hugging Face token")
def entfernen(config: Config = Depends(hole_config)) -> TokenStand:
    env_entfernen(config.pfad("./.env"), NAME)
    os.environ.pop(NAME, None)
    return TokenStand(gesetzt=False)
