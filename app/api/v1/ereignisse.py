"""The one live line a window keeps open for the whole program.

The stream itself, and why it exists at all, is described in
app/ereignisstrom.py. This is only its door: the same shape the command
stream next door already has (``zusehen``, app/api/v1/befehle.py) —
``text/event-stream``, no caching, no buffering in front of it.

There is no ``ab`` here and nothing is replayed. The command stream numbers
its events because a missed line is a hole in an output nobody can get
back; this one says "go and look", and a window that reconnects goes and
looks anyway.
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from app.ereignisstrom import strom
from app.i18n import verfuegbare_sprachen

router = APIRouter(prefix="/events", tags=["events"])


async def _sse_strom(quelle: AsyncIterator[dict | None]) -> AsyncIterator[str]:
    """Turns the hub's events into SSE lines. Its own function, like the
    command stream's, so the end-of-source handling is testable without a
    real HTTP round trip.

    ``None`` is the hub's heartbeat and becomes an SSE comment rather than a
    data line — an EventSource would otherwise hand the client an event with
    nothing in it.
    """
    try:
        async for ereignis in quelle:
            if ereignis is None:
                yield ": still here\n\n"
                continue
            yield f"data: {json.dumps(ereignis, ensure_ascii=False)}\n\n"
    except (asyncio.CancelledError, GeneratorExit):
        raise
    finally:
        await quelle.aclose()


@router.get("/stream", summary="Monitor application-wide events (SSE)")
async def zusehen() -> StreamingResponse:
    return StreamingResponse(
        _sse_strom(strom.zuschauen()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


class FensterThema(BaseModel):
    """What the window page shows now, as the terminal client inside the
    window calls it: the look by its short lower-case name, and the language
    by its code. Either one alone, or both; neither is no announcement."""

    theme: str | None = Field(default=None, pattern=r"^[a-z]{1,16}$")
    language: str | None = None

    @model_validator(mode="after")
    def _etwas_gemeldet(self) -> "FensterThema":
        if self.theme is None and self.language is None:
            raise ValueError("a look or a language is needed")
        if self.language is not None and self.language not in verfuegbare_sprachen():
            raise ValueError("unknown language")
        return self


@router.post("/window-theme", summary="Announce the look and language the window shows now")
async def fenster_thema(wunsch: FensterThema) -> dict[str, str]:
    """The window page tells that the look or the language it shows has
    changed; the terminal client inside the window follows. Nothing is
    stored here: what changed goes to whoever watches the stream, once."""
    gemeldet = {
        name: wert
        for name, wert in (("theme", wunsch.theme), ("language", wunsch.language))
        if wert is not None
    }
    strom.melden("window_theme", **gemeldet)
    return gemeldet
