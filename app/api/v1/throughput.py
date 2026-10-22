"""Tokens per second of a running server, from outside.

One route for the four servers that make text (model, agent, clean-up,
speech); the figures come from the readings the service keeps in memory
(app/throughput.py). Nothing is asked of a server here.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/servers", tags=["throughput"])


class Throughput(BaseModel):
    # Tokens per second of the latest stretch in which tokens were made, and
    # the average over the last five minutes. None where there is nothing to
    # say: no server running, or no token in the window.
    now: float | None = None
    average: float | None = None
    # The same rate for each of the last 30 slices of two seconds, 0 where no
    # token was made. Empty together with the two figures above.
    history: list[float] = []


@router.get(
    "/{server}/throughput",
    response_model=Throughput,
    summary="Tokens per second of a server",
)
def throughput(server: Literal["model", "agent", "cleanup", "speech"], request: Request) -> Throughput:
    figures = request.app.state.throughput.figures(server)
    return Throughput(**figures) if figures else Throughput()
