"""The web app of the settings page: its state, the password, and starting
and stopping the service shown to a phone (``app/web_app.py``).

Managed from this machine only: a request that came through Tailscale — a
phone that signed in with the password — may use the interface but not
change how it is reached.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.anmeldung import via_tailscale
from app.tailscale import TailscaleError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/web-app", tags=["web-app"])


class Password(BaseModel):
    # Its length is held in ``WebApp.set_password``, behind the check of where
    # the request comes from: a refusal for another place comes first.
    password: str


def _web_app(request: Request):
    if via_tailscale(request):
        raise HTTPException(status_code=403, detail="from_this_machine_only")
    return request.app.state.web_app


def _refused(error: TailscaleError) -> HTTPException:
    """``detail`` is the short word of the reason, and after a colon what
    Tailscale itself said, where it said anything: that can be an address the
    owner has to open — where https certificates are not switched on yet.
    A plain string, as every error the page reads."""
    log.warning("Web app refused: %s", error)
    return HTTPException(status_code=409, detail=str(error))


@router.get("", summary="The state of the web app")
def state(request: Request) -> dict[str, Any]:
    return _web_app(request).snapshot()


@router.put("/password", summary="Sets the password of the web app")
def set_password(body: Password, request: Request) -> dict[str, Any]:
    web_app = _web_app(request)
    try:
        web_app.set_password(body.password)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="password_too_short") from error
    return web_app.snapshot()


@router.post("/start", summary="Shows the service over https")
def start(request: Request) -> dict[str, Any]:
    try:
        return _web_app(request).start_service()
    except TailscaleError as error:
        raise _refused(error) from error


@router.post("/stop", summary="Stops showing the service")
def stop(request: Request) -> dict[str, Any]:
    try:
        return _web_app(request).stop_service()
    except TailscaleError as error:
        raise _refused(error) from error


@router.post("/tailscale/start", summary="Starts Tailscale")
def start_tailscale(request: Request) -> dict[str, Any]:
    try:
        return _web_app(request).start_tailscale()
    except TailscaleError as error:
        raise _refused(error) from error
