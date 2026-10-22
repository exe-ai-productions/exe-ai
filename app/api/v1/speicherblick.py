"""The machine's memory at a glance — for the pill in the header.

One number pair, polled every couple of seconds by the window: how much of
the machine's one memory pool is in use, and how big that pool is. It is a
fact about the MACHINE, not about this program — the header shows it so a
model plan can be judged before anything is started, the same way the
sibling programs show it.

Reading the figure shells out to ``vm_stat`` on macOS. That is cheap, but
not free — the interface polls on a slow, steady beat, and this endpoint
must never be put on a hot path.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from app import systemspeicher

router = APIRouter(tags=["system"])


class SpeicherblickAntwort(BaseModel):
    # Both in binary GB with one decimal, like the spec sheet counts them.
    # None where the platform cannot say — the window then shows nothing
    # rather than a guess.
    belegt_gb: float | None
    gesamt_gb: float | None
    anteil: float | None
    # The wired part alone (macOS), apart from the sum above, which stays what
    # it was for the pill. None where the platform has no such figure.
    wired_gb: float | None = None
    wired_anteil: float | None = None
    # The most the system lets stay wired (macOS, read from the graphics
    # device). The wired figure is measured against it: against the whole
    # memory the bar would never fill while the limit already holds. None
    # where it cannot be read — the share then falls back to the whole memory.
    wired_limit_gb: float | None = None


@router.get(
    "/system/speicher",
    response_model=SpeicherblickAntwort,
    summary="Current memory usage",
)
async def speicherblick() -> SpeicherblickAntwort:
    # The readout runs a subprocess; off the event loop, so a slow shell
    # never stalls a streaming answer.
    (belegt, wired), limit = await asyncio.gather(
        asyncio.to_thread(systemspeicher.used_and_wired_gb),
        asyncio.to_thread(systemspeicher.wired_limit_gb),
    )
    gesamt = systemspeicher.gesamt_gb()
    anteil = (
        round(min(belegt / gesamt, 1.0), 4)
        if belegt is not None and gesamt
        else None
    )
    denominator = limit or gesamt
    wired_anteil = (
        round(min(wired / denominator, 1.0), 4) if wired is not None and denominator else None
    )
    return SpeicherblickAntwort(
        belegt_gb=belegt,
        gesamt_gb=gesamt,
        anteil=anteil,
        wired_gb=wired,
        wired_anteil=wired_anteil,
        wired_limit_gb=limit,
    )
