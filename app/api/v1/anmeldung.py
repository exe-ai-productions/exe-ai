"""Signing in to a service that demands a password.

The one route below ``/api/v1`` that answers without the session key — a
client that has no key yet is exactly who calls it. It gives out this run's
key in exchange for the password; from then on the client sends the key
like every other. Wrong passwords are counted and braked
(``app/login_limit.py``).
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.abhaengigkeiten import hole_sprache
from app.i18n import t
from app.login_limit import LimitReached

router = APIRouter(tags=["anmeldung"])

LOGIN_PATH = "/login"


class Anmeldung(BaseModel):
    password: str


class Sitzungsschluessel(BaseModel):
    key: str


@router.post(LOGIN_PATH, response_model=Sitzungsschluessel, summary="Signs in with the password")
def anmelden(
    daten: Anmeldung, request: Request, sprache: str = Depends(hole_sprache)
) -> Sitzungsschluessel:
    """The key for the password. A service that demands no password — one
    on the loopback address, whose page carries the key — refuses as
    well: there is nothing to sign in to."""
    state = request.app.state
    passwort = getattr(state, "passwort", None)
    if not (getattr(state, "anmeldung", False) and passwort):
        # Nothing to sign in to, so nothing to guess and nothing to count.
        raise HTTPException(status_code=401, detail=t("fehler.anmeldung", sprache))
    try:
        # ``compare_digest`` takes the same time whichever character
        # differs, so a wrong password cannot be guessed one character at a
        # time.
        stimmt = state.login_limit.attempt(
            lambda: secrets.compare_digest(
                daten.password.encode("utf-8"), passwort.encode("utf-8")
            )
        )
    except LimitReached:
        # Too many wrong passwords: nothing was compared, so not even the
        # right one gets through until a window has cleared.
        raise HTTPException(
            status_code=429, detail=t("fehler.login_limited", sprache)
        ) from None
    if not stimmt:
        raise HTTPException(status_code=401, detail=t("fehler.anmeldung", sprache))
    return Sitzungsschluessel(key=state.sitzungsschluessel)
