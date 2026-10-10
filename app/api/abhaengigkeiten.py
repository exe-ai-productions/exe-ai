"""Shared dependencies for the API routes.

FastAPI passes these functions into the routes via ``Depends``. That way no
route hangs directly off a global object, and tests can replace each
dependency individually.
"""

from __future__ import annotations

from fastapi import Header, Request

from app.config import Config
from app.db import Repositories
from app import sprachwahl

# As long as there is no login, everything belongs to this user. The user_id
# column exists from day one so that adding login later is an upgrade.
STANDARD_BENUTZER = "standard"


def hole_config(request: Request) -> Config:
    return request.app.state.config


def hole_repositories(request: Request) -> Repositories:
    return request.app.state.repositories


def hole_benutzer_id(request: Request) -> str:
    return getattr(request.app.state, "standard_benutzer", STANDARD_BENUTZER)


def hole_sprache(
    request: Request,
    accept_language: str | None = Header(default=None, alias=sprachwahl.HEADER_ACCEPT),
    ui_language: str | None = Header(default=None, alias=sprachwahl.HEADER_UI),
) -> str:
    """The language the interface shows, sent by the page with every request;
    without it the request's Accept-Language, otherwise the config's.

    The rule itself lives in ``app/sprachwahl.language_from_headers`` — the
    session guard, the served page and the answer to a refused input ask the
    same question, and one rule read in one place is what keeps the callers
    from drifting apart. Both headers stand in the signature so they appear
    in the API's own description; their names come from the same module."""
    return sprachwahl.language_from_headers(
        accept_language, ui_language, request.app.state.config.app.language
    )
