"""A reattach replays the history — and says which questions are already over.

The window used to put every replayed question up again: sound, box and a
yellow entry, until the call or the result of the same ``aufruf_id`` came by
and took it down. The service knows the whole history, so it marks a settled
question with ``"settled": true``; an open one and everything live stay as
they are.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.api.v1.generierung import _sse
from app.generationen import Generierungsverwaltung, nachgeholt


def _lesen(zeile: str) -> dict:
    assert zeile.startswith("data: ")
    return json.loads(zeile[len("data: ") :])


def test_beantwortete_fragen_tragen_die_marke_die_offene_nicht():
    zeilen = [
        _sse("tool_confirm", name="write_file", argumente={}, aufruf_id="a1"),
        _sse("tool_call", name="write_file", argumente={}, aufruf_id="a1"),
        _sse("user_ask", frage="Which one?", optionen=[], aufruf_id="a2"),
        _sse("tool_result", name="ask_user", aufruf_id="a2", text="ok"),
        _sse("job_confirm", agent="x", task="y", aufruf_id="a3"),
        _sse("tool_result", name="start_job", aufruf_id="a3", text="ok"),
        _sse("user_ask", frage="Still open?", optionen=[], aufruf_id="a4"),
    ]

    ergebnis = [_lesen(z) for z in nachgeholt(zeilen)]

    marken = {e["aufruf_id"]: e.get("settled") for e in ergebnis if e["typ"].endswith(("_confirm", "_ask"))}
    assert marken == {"a1": True, "a2": True, "a3": True, "a4": None}
    # Nothing but the mark changed: the question keeps every other field.
    assert ergebnis[2]["frage"] == "Which one?"
    assert ergebnis[6]["frage"] == "Still open?"


def test_ohne_beantwortete_frage_bleibt_jede_zeile_unveraendert():
    """The silence test: no call, no result — the history is passed on as is."""
    zeilen = [
        _sse("content", text="hello"),
        _sse("user_ask", frage="Open?", optionen=[], aufruf_id="a1"),
        "not an event line",
    ]
    assert nachgeholt(zeilen) == zeilen


def test_eine_wiederholte_kennung_erledigt_die_neue_frage_nicht():
    """A server that reuses a call id: the first question was answered, the
    second one with the same id is open and must stay a live question."""
    zeilen = [
        _sse("user_ask", frage="First", optionen=[], aufruf_id="call_0"),
        _sse("tool_result", name="ask_user", aufruf_id="call_0", text="ok"),
        _sse("user_ask", frage="Second", optionen=[], aufruf_id="call_0"),
    ]

    ergebnis = [_lesen(z) for z in nachgeholt(zeilen)]

    assert [(e["frage"], e.get("settled")) for e in ergebnis if e["typ"] == "user_ask"] == [
        ("First", True),
        ("Second", None),
    ]


def test_ein_ergebnis_vor_der_frage_erledigt_sie_nicht():
    zeilen = [
        _sse("tool_result", name="ask_user", aufruf_id="a1", text="old"),
        _sse("user_ask", frage="Q", optionen=[], aufruf_id="a1"),
    ]
    assert nachgeholt(zeilen) == zeilen


def test_ein_ergebnis_einer_anderen_frage_erledigt_diese_nicht():
    zeilen = [
        _sse("user_ask", frage="Q", optionen=[], aufruf_id="a1"),
        _sse("tool_result", name="read_file", aufruf_id="other", text="x"),
    ]
    assert nachgeholt(zeilen) == zeilen


@pytest.mark.asyncio
async def test_der_nachholteil_markiert_der_live_teil_bleibt():
    verwaltung = Generierungsverwaltung()
    zuschauer_da = asyncio.Event()
    geschichte_da = asyncio.Event()

    async def arbeit(lauf):
        lauf.melden(_sse("user_ask", frage="Q1", optionen=[], aufruf_id="a1"))
        lauf.melden(_sse("tool_result", name="ask_user", aufruf_id="a1", text="ok"))
        geschichte_da.set()
        # Live, only once the watcher has caught up: a new question with the
        # same id as the settled one — it must reach the watcher unmarked.
        await zuschauer_da.wait()
        lauf.melden(_sse("user_ask", frage="Q2", optionen=[], aufruf_id="a1"))

    lauf = verwaltung.starten(chat_id="c", endpoint_id="e", arbeit=arbeit)
    await asyncio.wait_for(geschichte_da.wait(), timeout=2)
    gelesen = []
    async for zeile in lauf.zuschauen():
        gelesen.append(_lesen(zeile))
        if len(gelesen) == 2:
            zuschauer_da.set()

    fragen = [e for e in gelesen if e["typ"] == "user_ask"]
    assert [(f["frage"], f.get("settled")) for f in fragen] == [("Q1", True), ("Q2", None)]


@pytest.mark.asyncio
async def test_der_zaehlstand_gilt_weiter_auf_der_markierten_geschichte():
    verwaltung = Generierungsverwaltung()

    async def arbeit(lauf):
        lauf.melden(_sse("user_ask", frage="Q", optionen=[], aufruf_id="a1"))
        lauf.melden(_sse("tool_result", name="ask_user", aufruf_id="a1", text="ok"))
        lauf.melden(_sse("content", text="after"))

    lauf = verwaltung.starten(chat_id="c", endpoint_id="e", arbeit=arbeit)
    await asyncio.wait_for(lauf.fertig.wait(), timeout=2)

    # A watcher that already read the question gets only what came after it —
    # and the question it read stays as it was sent.
    gelesen = [_lesen(z) async for z in lauf.zuschauen(ab=1)]
    assert [e["typ"] for e in gelesen] == ["tool_result", "content"]
