"""A server that sends its whole chain of thought a second time, as the answer.

Measured against a local MLX server: stopped at its token ceiling WHILE
STILL THINKING, it closes the stream with one last packet whose ``content``
is the complete chain of thought it has streamed so far — 275 characters of
thinking in eight pieces, then a single content piece of exactly those 275
characters, ``finish_reason`` ``length``. With room to finish, the same
question gave 1520 characters of thinking and 1557 entirely different
characters of answer; stopped AFTER the thinking was done, 1722 characters
of thinking and 351 characters of a real, half-written answer.

Read as an answer, that flush is the worst outcome a ceiling can have: the
whole chain of thought stands there AS the answer, there is no answer under
it, and nothing says anything was cut. Dropped, the answer is empty — and
an empty answer that stopped at the ceiling is what the cut-off flag is
there to explain.

Every case here also has its silence probe: the two shapes that must come
through untouched are the finished answer and the answer cut off after the
thinking ended.
"""

from __future__ import annotations

import asyncio
import json
import socket

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from app import denkdopplung
from app.config import EndpointConfig
from app.providers import ChatNachricht, Generierungsanfrage
from app.providers.openai_kompatibel import OpenAIKompatiblerProvider


# --- The rule on its own ---------------------------------------------------


def test_das_ganze_denken_als_antwort_ist_eine_wiederholung():
    wache = denkdopplung.Wache()
    wache.denken("Let me think ")
    wache.denken("about this.")
    assert wache.ist_wiederholung("Let me think about this.")


def test_ein_stueck_davon_ist_keine_wiederholung():
    """Not a prefix, and not a part: the thinking measured above begins with
    a newline, and so does many an answer."""
    wache = denkdopplung.Wache()
    wache.denken("\nLet me think about this.")
    assert not wache.ist_wiederholung("\n")
    assert not wache.ist_wiederholung("\nLet me think")
    assert not wache.ist_wiederholung("Let me think about this.")


def test_nach_dem_ersten_antworttext_ist_nichts_mehr_eine_wiederholung():
    """From the first word of the answer on, the model is writing, and what
    it writes is its own — even if it should repeat itself word for word."""
    wache = denkdopplung.Wache()
    wache.denken("Let me think.")
    wache.antwort("The answer is 391.")
    assert not wache.ist_wiederholung("Let me think.")


def test_leerzeichen_sind_kein_denken():
    """A trace of one newline and an answer whose first piece is that same
    newline are the same two characters. Nothing is taken from an answer
    over a trace that said nothing."""
    wache = denkdopplung.Wache()
    wache.denken("\n")
    assert not wache.ist_wiederholung("\n")


def test_ohne_denken_gibt_es_nichts_zu_wiederholen():
    """A server that never labelled anything as thinking keeps no second
    copy anywhere — including one that marks its thinking inside the text."""
    wache = denkdopplung.Wache()
    assert not wache.ist_wiederholung("anything at all")


# --- The same thing on a real stream ---------------------------------------


class ModellServerAttrappe:
    """An OpenAI-compatible server, fed packet by packet from a test."""

    def __init__(self) -> None:
        self.pakete: list[dict] = []
        self.app = FastAPI()

        @self.app.get("/v1/models")
        async def modelle():
            return {"object": "list", "data": [{"id": "testmodell"}]}

        @self.app.post("/v1/chat/completions")
        async def completions(request: Request):
            await request.json()

            async def strom():
                for paket in self.pakete:
                    yield f"data: {json.dumps(paket)}\n\n"
                    await asyncio.sleep(0)
                yield "data: [DONE]\n\n"

            return StreamingResponse(strom(), media_type="text/event-stream")


@pytest.fixture
async def modellserver():
    attrappe = ModellServerAttrappe()

    lauscher = socket.socket()
    lauscher.bind(("127.0.0.1", 0))
    port = lauscher.getsockname()[1]
    lauscher.close()

    server = uvicorn.Server(
        uvicorn.Config(attrappe.app, host="127.0.0.1", port=port, log_level="error")
    )
    aufgabe = asyncio.create_task(server.serve())
    while not server.started:
        if aufgabe.done():
            # Whatever went wrong starting up — the port taken between the
            # probe above and this line, anything raised inside uvicorn —
            # is raised here. Without this the loop waits for a `started`
            # that will never come, and the test hangs instead of failing.
            aufgabe.result()
            raise RuntimeError("the mock server stopped before it was ready")
        await asyncio.sleep(0.01)

    attrappe.basis = f"http://127.0.0.1:{port}/v1"
    try:
        yield attrappe
    finally:
        server.should_exit = True
        await aufgabe


def _denkfeld(text: str) -> dict:
    return {"choices": [{"delta": {"reasoning_content": text}, "index": 0}]}


def _textfeld(text: str) -> dict:
    return {"choices": [{"delta": {"content": text}, "index": 0}]}


def _ende(grund: str) -> dict:
    return {"choices": [{"delta": {}, "finish_reason": grund, "index": 0}]}


async def _lauf(basis: str) -> dict:
    endpunkt = EndpointConfig.model_validate(
        {"id": "prueflabor", "base_url": basis, "reasoning_format": "native"}
    )
    provider = OpenAIKompatiblerProvider(endpunkt)
    anfrage = Generierungsanfrage(nachrichten=[ChatNachricht(role="user", content="Hallo")])
    stuecke = []
    async for stueck in provider.streamen(anfrage):
        stuecke.append(stueck)
    daten = dict(next(s for s in stuecke if s.sorte == "stats").daten)
    daten["_antwort"] = "".join(s.text for s in stuecke if s.sorte == "content")
    daten["_gedanke"] = "".join(s.text for s in stuecke if s.sorte == "reasoning")
    return daten


# The shape the flush really has: the thinking in pieces, then ONE content
# piece carrying all of it again, then the ceiling as the reason.
DENKSTUECKE = ["\nThe user wants ", "me to work this ", "out step by step."]


async def test_abbruch_im_denken_traegt_den_denktext_nicht_als_antwort(modellserver):
    """The defect itself: cut off mid-thought, answer and chain of thought
    used to come out as the same text, character for character."""
    modellserver.pakete = [_denkfeld(t) for t in DENKSTUECKE] + [
        _textfeld("".join(DENKSTUECKE)),
        _ende("length"),
    ]

    werte = await _lauf(modellserver.basis)

    assert werte["_gedanke"] == "".join(DENKSTUECKE)
    assert werte["_antwort"] != werte["_gedanke"]
    assert werte["_antwort"] == ""


async def test_und_dann_sagt_die_antwort_dass_sie_abgeschnitten_ist(modellserver):
    """An empty answer is only half of it. The other half is the flag the
    window turns into the cut-off notice — without it the user would be left
    with nothing at all and no word about why."""
    modellserver.pakete = [_denkfeld(t) for t in DENKSTUECKE] + [
        _textfeld("".join(DENKSTUECKE)),
        _ende("length"),
    ]

    werte = await _lauf(modellserver.basis)

    assert werte["abgeschnitten"] is True
    assert werte["ende_grund"] == "length"


async def test_schweigeprobe_eine_durchgelaufene_antwort_bleibt_getrennt(modellserver):
    """The comparison run: thinking and answer are different texts, and
    both arrive whole."""
    modellserver.pakete = [_denkfeld(t) for t in DENKSTUECKE] + [
        _textfeld("17 x 23 = 391."),
        _ende("stop"),
    ]

    werte = await _lauf(modellserver.basis)

    assert werte["_gedanke"] == "".join(DENKSTUECKE)
    assert werte["_antwort"] == "17 x 23 = 391."
    assert werte["abgeschnitten"] is False


async def test_schweigeprobe_abbruch_nach_dem_denken_behaelt_die_halbe_antwort(modellserver):
    """Stopped at the ceiling, but the thinking had finished and a real
    answer was under way: that half-written answer is kept, every word of
    it. It is the one thing the rule must never take."""
    modellserver.pakete = [_denkfeld(t) for t in DENKSTUECKE] + [
        _textfeld("17 x 23 = "),
        _textfeld("39"),
        _ende("length"),
    ]

    werte = await _lauf(modellserver.basis)

    assert werte["_antwort"] == "17 x 23 = 39"
    assert werte["abgeschnitten"] is True
