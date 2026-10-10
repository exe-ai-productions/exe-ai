"""``app/aufgaben.py``: one place that holds a fire-and-forget task.

Four modules had written the same three lines — create, add to a set,
discard on done — each with a done-callback of its own, and six older
``create_task`` calls had written none and were held by nothing but the
loop's weak reference. The helper is what all of them go through now.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from app import aufgaben

WURZEL = Path(__file__).resolve().parent.parent


@pytest.mark.asyncio
async def test_eine_aufgabe_wird_gehalten_und_am_ende_losgelassen():
    weiter = asyncio.Event()

    async def arbeit():
        await weiter.wait()
        return 7

    aufgabe = aufgaben.halten(arbeit(), name="probe")
    assert aufgabe in aufgaben.offene()
    weiter.set()
    assert await aufgabe == 7
    await asyncio.sleep(0)
    assert aufgabe not in aufgaben._gehalten


@pytest.mark.asyncio
async def test_eine_eigene_menge_und_ein_ende_haken_werden_bedient():
    eigene: set[asyncio.Task] = set()
    beendet = []

    async def arbeit():
        raise RuntimeError("kaputt")

    aufgabe = aufgaben.halten(arbeit(), name="probe", menge=eigene, bei_ende=beendet.append)
    assert aufgabe in eigene
    assert aufgabe not in aufgaben._gehalten
    with pytest.raises(RuntimeError):
        await aufgabe
    await asyncio.sleep(0)
    # Let go of first, then told: the callback sees a set the task has left.
    assert beendet == [aufgabe]
    assert not eigene


def test_niemand_ruft_create_task_mehr_ohne_halter():
    """Source-text guard: the five modules that held tasks by hand, and the
    one that held none, go through the helper. A task the loop only
    remembers weakly is the fault this module exists against."""
    dateien = (
        "app/api/v1/werkzeuge.py",
        "app/api/v1/generierung.py",
        "app/hintergrundwecken.py",
        "app/tools/shell.py",
        "app/events.py",
    )
    for datei in dateien:
        quelle = (WURZEL / datei).read_text(encoding="utf-8")
        assert not re.search(r"\bcreate_task\(|\bensure_future\(", quelle), (
            f"{datei} starts a task past aufgaben.halten"
        )
        assert "aufgaben.halten(" in quelle, f"{datei} does not use aufgaben.halten"
